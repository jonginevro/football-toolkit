"""Learn the breakout model from history and grade it walk-forward.

Model: L2-regularized logistic regression on a small set of interpretable
features, pooled across positions (position enters as an intercept shift and
every rate is scaled to that position's startable bar).

Grading is walk-forward: the board for season S is scored by a model trained
only on seasons before S, exactly as it would have looked at the time. The live
board uses a model trained on every completed season.

A player's log-odds decompose exactly into per-group contributions,

    logit = base + talent + role + profile + ceiling

where each group term is sum(beta_f * (x_f - mean_f)). The site lets you scale
each group and recomputes every probability and every backtest metric live, so
the "tinker" loop needs nothing but this decomposition."""
from __future__ import annotations

import functools

import numpy as np
import pandas as pd

from .. import config
from . import snapshot as snap

BASE_FEATURES = ["pos_RB", "pos_WR", "pos_TE", "progress"]


def feature_groups() -> dict[str, list[str]]:
    return config.model_config()["groups"]


def feature_names() -> list[str]:
    return BASE_FEATURES + [f for fs in feature_groups().values() for f in fs]


def features(df: pd.DataFrame) -> pd.DataFrame:
    start, _ = snap.thresholds()
    bar = df["position"].map(start)
    X = pd.DataFrame(index=df.index)
    for p in ("RB", "WR", "TE"):
        X[f"pos_{p}"] = (df["position"] == p).astype(float)
    X["progress"] = (df["week"] - 1) / 17

    # talent
    X["log_pick"] = -np.log(df["draft_pick"].fillna(300).clip(1, 300))
    X["eff_rel"] = df["eff_rel"].fillna(1.0).clip(0.4, 1.8)
    X["prior_ppg_rel"] = (df["prior_ppg"] / bar).clip(-0.2, 2)
    # role
    X["own_share"] = df["own_share"]
    X["open_opp"] = df["open_opp"]
    X["starter"] = (df["depth_tier"] == 1).astype(float)
    X["backup"] = (df["depth_tier"] == 2).astype(float)
    X["new_team"] = df["new_team"]
    X["recent_delta"] = df["recent_delta"].clip(-0.5, 0.5)
    # profile
    exp = df["exp"]
    X["rookie"] = (exp == 0).astype(float)
    X["year2"] = (exp == 1).astype(float)
    X["year3"] = (exp == 2).astype(float)
    age_rel = (df["age"] - df["position"].map(snap.PEAK_AGE)).clip(-5, 10)
    X["age_rel"] = age_rel
    X["age_rel_sq"] = age_rel ** 2 / 10
    # ceiling: how high the bar already is
    X["baseline_rel"] = (df["baseline_ppg"] / bar).clip(-0.2, 2)
    X["baseline_rel_sq"] = X["baseline_rel"] ** 2
    return X[feature_names()]


# --------------------------------------------------------------------------- #
#  Logistic regression (Newton / IRLS) — tiny problem, no sklearn needed       #
# --------------------------------------------------------------------------- #
class Logit:
    def fit(self, X: pd.DataFrame, y: np.ndarray, l2: float) -> "Logit":
        self.cols = list(X.columns)
        self.mu = X.mean().to_numpy()
        self.sd = X.std().replace(0, 1).to_numpy()
        Z = (X.to_numpy() - self.mu) / self.sd
        Z = np.column_stack([np.ones(len(Z)), Z])
        w = np.zeros(Z.shape[1])
        reg = np.full(Z.shape[1], l2)
        reg[0] = 0.0  # don't shrink the intercept
        for _ in range(50):
            p = 1 / (1 + np.exp(-Z @ w))
            g = Z.T @ (p - y) + reg * w
            H = (Z * (p * (1 - p))[:, None]).T @ Z + np.diag(reg)
            step = np.linalg.solve(H, g)
            w -= step
            if np.abs(step).max() < 1e-8:
                break
        # back to raw feature units
        self.beta = w[1:] / self.sd
        self.intercept = w[0] - (self.beta * self.mu).sum()
        return self

    def decompose(self, X: pd.DataFrame) -> pd.DataFrame:
        """Exact split of log-odds into base + one term per feature group,
        each group centered on the training mean (0 = an average player)."""
        b = pd.Series(self.beta, index=self.cols)
        mu = pd.Series(self.mu, index=self.cols)
        out = pd.DataFrame(index=X.index)
        grouped = [f for fs in feature_groups().values() for f in fs]
        out["base"] = (self.intercept + (X[BASE_FEATURES] * b[BASE_FEATURES]).sum(axis=1)
                       + (b[grouped] * mu[grouped]).sum())
        for g, fs in feature_groups().items():
            out[g] = ((X[fs] - mu[fs]) * b[fs]).sum(axis=1)
        return out

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return 1 / (1 + np.exp(-self.decompose(X).sum(axis=1).to_numpy()))


# --------------------------------------------------------------------------- #
#  Data                                                                        #
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=None)
def snapshot_cached(season: int, week: int) -> pd.DataFrame:
    """Snapshots of completed seasons never change: cache them on disk."""
    path = config.CACHE_DIR / f"snap_{season}_{week}.parquet"
    done = season < config.CURRENT_SEASON
    if done and path.exists():
        return pd.read_parquet(path)
    df = snap.snapshot(season, week)
    if done and len(df):
        df.to_parquet(path)
    return df


def history(weeks: list[int]) -> pd.DataFrame:
    frames = [snapshot_cached(s, w)
              for s in range(config.FIRST_TRAIN_SEASON, config.CURRENT_SEASON)
              for w in weeks]
    df = pd.concat([f for f in frames if len(f)], ignore_index=True)
    return df[df["breakout"].notna() & df["eligible"]].reset_index(drop=True)


def fit(df: pd.DataFrame) -> Logit:
    return Logit().fit(features(df), df["breakout"].to_numpy(float),
                       config.model_config().get("l2", 1.0))


def walk_forward(hist: pd.DataFrame) -> pd.DataFrame:
    """Score each past season with a model trained only on earlier seasons."""
    seasons = sorted(hist["season"].unique())
    out = []
    for s in seasons[config.MIN_TRAIN_SEASONS:]:
        m = fit(hist[hist["season"] < s])
        test = hist[hist["season"] == s].copy()
        parts = m.decompose(features(test))
        test = test.join(parts)
        test["prob"] = 1 / (1 + np.exp(-parts.sum(axis=1)))
        out.append(test)
    return pd.concat(out, ignore_index=True)


# --------------------------------------------------------------------------- #
#  Metrics                                                                     #
# --------------------------------------------------------------------------- #
def auc(score, label) -> float:
    s, y = pd.Series(score).reset_index(drop=True), pd.Series(label).astype(bool).reset_index(drop=True)
    n1, n0 = int(y.sum()), int((~y).sum())
    if not n1 or not n0:
        return float("nan")
    r = s.rank()
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def report(scored: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (s, w), g in scored.groupby(["season", "week"]):
        rows.append({
            "season": s, "week": w, "n": len(g), "breakouts": int(g["breakout"].sum()),
            "auc": auc(g["prob"], g["breakout"]),
            "auc_draft": auc(-g["draft_pick"].fillna(300), g["breakout"]),
            "auc_prior": auc(g["prior_ppg"], g["breakout"]),
            "hits@20": int(g.nlargest(20, "prob")["breakout"].sum()),
            "base@20": 20 * g["breakout"].mean(),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    weeks = config.model_config()["snapshot_weeks"]
    hist = history(weeks)
    print(f"{len(hist)} training rows, {int(hist['breakout'].sum())} breakouts")
    scored = walk_forward(hist)
    r = report(scored)
    pd.set_option("display.width", 200)
    print(r.round(3).to_string(index=False))
    print("\nBy week (mean over seasons):")
    print(r.groupby("week")[["auc", "auc_draft", "auc_prior", "hits@20", "base@20"]].mean().round(3))
    print("\nPooled AUC:", round(auc(scored["prob"], scored["breakout"]), 3))
    m = fit(hist)
    print(pd.Series(m.beta * m.sd, index=m.cols).round(3).to_string())
