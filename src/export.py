"""Build every JSON file the static site reads.

    python -m src.export

Writes docs/data/:
  meta.json            model description, learned weights, season/week, metrics
  board.json           the live board for the current season as of this week
  history/<year>.json  each past season's boards (walk-forward scored) + outcomes
"""
from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np
import pandas as pd

from . import config
from .data import depth, espn, market, sleeper
from .model import snapshot as snap
from .model import train

GROUP_INFO = {
    "talent": ("Talent", "Draft capital, points per touch, and last year's production."),
    "role": ("Role", "Share of his team's work, work that's opened up (departures, injuries), "
                     "depth chart spot, new team, and recent usage trend."),
    "profile": ("Age & experience", "Rookie / year-2 / year-3 jumps and age relative to "
                                    "the position's peak."),
    "ceiling": ("Starting level", "How high his current per-game level already is. "
                                  "Already-elite players have little room to break out."),
}
NOTES_LOGIT = 1.0  # a maxed-out manual note adds this much log-odds

POS_WORK = {"QB": "QB dropbacks", "RB": "RB touches", "WR": "WR targets", "TE": "TE targets"}


# --------------------------------------------------------------------------- #
#  Plain-English reasons                                                       #
# --------------------------------------------------------------------------- #
def _reason(f: str, r: pd.Series, up: bool) -> str | None:
    pos = r["position"]
    pick = r["draft_pick"]
    if f == "log_pick":
        if pd.isna(pick):
            return "Undrafted"
        rnd = "1st" if pick <= 32 else "2nd" if pick <= 64 else "3rd" if pick <= 100 else "Day 3"
        return f"{rnd}-round capital (pick {int(pick)})" if rnd != "Day 3" else f"Day-3 pick ({int(pick)})"
    if f == "eff_rel":
        return f"{'Efficient' if up else 'Inefficient'}: {r['eff_rel']:.0%} of position-avg points per touch"
    if f == "prior_ppg_rel":
        return f"{r['prior_ppg']:.1f} PPR/g last season"
    if f == "own_share":
        return f"Owns {r['own_share']:.0%} of team {POS_WORK[pos]}"
    if f == "open_opp":
        return f"{r['open_opp']:.0%} of team {POS_WORK[pos]} up for grabs"
    if f == "starter":
        return "Starter on the depth chart" if up else "Not a listed starter"
    if f == "backup":
        return "Next man up on the depth chart" if up else None
    if f == "new_team":
        return "Fresh start on a new team" if r["new_team"] else None
    if f == "recent_delta":
        d = r["recent_delta"]
        return f"Usage {'rising' if d > 0 else 'falling'}: {d:+.0%} share last 2 games"
    if f == "rookie":
        return "Rookie" if r["exp"] == 0 else None
    if f == "year2":
        return "Year-2 leap window" if r["exp"] == 1 else None
    if f == "year3":
        return "Year-3 window" if r["exp"] == 2 else None
    if f in ("age_rel", "age_rel_sq"):
        a = r["age"]
        return (f"Age {a:.1f}, ahead of the {pos} peak" if up
                else f"Age {a:.1f}, past the {pos} prime")
    if f in ("baseline_rel", "baseline_rel_sq"):
        b = r["baseline_ppg"]
        return f"Low bar: {b:.1f} PPR/g now, room to jump" if up else f"Already at {b:.1f} PPR/g"
    return None


def feature_contribs(model: train.Logit, X: pd.DataFrame) -> pd.DataFrame:
    """Per-feature log-odds contributions (they sum to the group terms). Squared
    terms are folded into their base feature so each reads as one effect."""
    b = pd.Series(model.beta, index=model.cols)
    mu = pd.Series(model.mu, index=model.cols)
    grouped = [f for fs in train.feature_groups().values() for f in fs]
    contrib = (X[grouped] - mu[grouped]) * b[grouped]
    contrib["age_rel"] = contrib["age_rel"] + contrib.pop("age_rel_sq")
    contrib["baseline_rel"] = contrib["baseline_rel"] + contrib.pop("baseline_rel_sq")
    return contrib


def explain_features() -> list[str]:
    return [f for fs in train.feature_groups().values() for f in fs
            if not f.endswith("_sq")]


def reasons(df: pd.DataFrame, model: train.Logit, X: pd.DataFrame, n_up=3, n_down=1):
    contrib = feature_contribs(model, X)
    df["fc"] = [[round(float(v), 3) for v in row]
                for row in contrib[explain_features()].itertuples(index=False)]
    ups, downs = [], []
    for i, r in df.iterrows():
        c = contrib.loc[i].sort_values()
        u = [t for f in c[c > 0.12].index[::-1] if (t := _reason(f, r, True))][:n_up]
        d = [t for f in c[c < -0.25].index if (t := _reason(f, r, False))][:n_down]
        ups.append(u)
        downs.append(d)
    return ups, downs


# --------------------------------------------------------------------------- #
#  Live extras (Sleeper + manual notes)                                        #
# --------------------------------------------------------------------------- #
def _name_key(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().str.replace(r"\b(jr|sr|ii|iii|iv)\b", "", regex=True) \
            .str.replace(r"[^a-z]", "", regex=True)


def attach_sleeper(df: pd.DataFrame) -> pd.DataFrame:
    sl = sleeper.players()
    df = df.copy()
    df["sleeper_id"] = df["sleeper_id"].astype("string").str.replace(r"\.0$", "", regex=True)
    if len(sl):
        by_gsis = sl.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id")["sleeper_id"]
        sl["_k"] = _name_key(sl["sleeper_name"]) + sl["sleeper_pos"].astype(str)
        by_name = sl.drop_duplicates("_k").set_index("_k")["sleeper_id"]
        df["sleeper_id"] = (df["sleeper_id"].fillna(df["gsis_id"].map(by_gsis))
                            .fillna((_name_key(df["name"]) + df["position"]).map(by_name)))
        meta = sl.drop_duplicates("sleeper_id").set_index("sleeper_id")
        df["market_rank"] = df["sleeper_id"].map(meta["search_rank"])
        df["injury"] = df["sleeper_id"].map(meta["injury_status"])
    else:
        df["market_rank"], df["injury"] = np.nan, None
    # search_rank uses a huge sentinel for unranked players
    df.loc[df["market_rank"] >= 9_999_999, "market_rank"] = np.nan
    for hours, col in ((24, "adds_24h"), (168, "adds_7d")):
        t = sleeper.trending(hours).set_index("sleeper_id")["adds"]
        df[col] = df["sleeper_id"].map(t)

    # ESPN roster % covers everyone (Sleeper adds only cover its top 100)
    own = espn.ownership(config.CURRENT_SEASON).drop_duplicates("espn_id").set_index("espn_id")
    eid = df["espn_id"].astype("string").str.replace(r"\.0$", "", regex=True)
    df["rostered_pct"] = eid.map(own["rostered_pct"])
    df["rostered_chg"] = eid.map(own["rostered_chg"])
    # off ESPN's list entirely = effectively unrostered, not unknown
    df["rostered_pct"] = df["rostered_pct"].fillna(0.0)
    df["rostered_chg"] = df["rostered_chg"].fillna(0.0)
    return df


def manual_notes(df: pd.DataFrame) -> pd.Series:
    cat = config.manual_catalysts()
    players = {k.lower(): v for k, v in cat["players"].items()}

    def score(r):
        tot = sum(float(v) for v in (cat["teams"].get(r["team"]) or {}).values())
        tot += sum(float(v) for v in (players.get(str(r["name"]).lower()) or {}).values())
        return min(tot, 1.0) * NOTES_LOGIT

    return df.apply(score, axis=1) if len(df) else pd.Series(dtype=float)


# --------------------------------------------------------------------------- #
#  Serialization                                                               #
# --------------------------------------------------------------------------- #
def _clean(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else round(float(v), 3)
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def table(df: pd.DataFrame, cols: dict[str, str]) -> dict:
    """Column-oriented-ish compact table: {cols: [...], rows: [[...], ...]}."""
    out = df[list(cols.values())]
    return {"cols": list(cols.keys()),
            "rows": [[_clean(v) for v in row] for row in out.itertuples(index=False)]}


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


COMMON = {
    "id": "gsis_id", "name": "name", "pos": "position", "team": "team", "age": "age",
    "exp": "exp", "pick": "draft_pick", "depth": "depth_tier", "base": "base",
    "talent": "talent", "role": "role", "profile": "profile", "ceiling": "ceiling",
    "baseline": "baseline_ppg", "prior_ppg": "prior_ppg", "ytd_ppg": "ytd_ppg",
    "ytd_g": "ytd_games", "share": "own_share", "open": "open_opp", "eff": "eff_rel",
    "new_team": "new_team", "up": "up", "down": "down", "fc": "fc",
}


def _summary(r: pd.DataFrame) -> dict:
    return {"auc": round(r["auc"].mean(), 3), "auc_draft": round(r["auc_draft"].mean(), 3),
            "auc_prior": round(r["auc_prior"].mean(), 3), "hits20": round(r["hits@20"].mean(), 1),
            "rand20": round(r["base@20"].mean(), 1)}


# --------------------------------------------------------------------------- #
#  Main                                                                        #
# --------------------------------------------------------------------------- #
def main():
    season = config.CURRENT_SEASON
    last = snap.last_stats_week(season)
    week = min(last + 1, 18)
    weeks = sorted(set(config.model_config()["snapshot_weeks"]) | {week})

    hist = train.history(weeks)
    print(f"history: {len(hist)} rows, {int(hist['breakout'].sum())} breakouts")
    scored = train.walk_forward(hist)
    rep = train.report(scored)

    # ---- live board -----------------------------------------------------------
    model = train.fit(hist)
    live = snap.snapshot(season, week)
    live = live[live["eligible"]].reset_index(drop=True)
    if live.empty:
        raise SystemExit(f"No roster data for {season} yet; leaving the site untouched.")
    X = train.features(live)
    live = live.join(model.decompose(X))
    live["up"], live["down"] = reasons(live, model, X)
    live = attach_sleeper(live)
    ecr_now, ecr_when = market.ecr_asof(pd.Timestamp.now())
    live["ecr"] = live["gsis_id"].map(ecr_now)
    live["notes"] = manual_notes(live)
    board_cols = {**COMMON, "headshot": "headshot", "notes": "notes",
                  "recent": "recent_delta", "market": "market_rank",
                  "adds24": "adds_24h", "adds7d": "adds_7d", "injury": "injury",
                  "own": "rostered_pct", "own_chg": "rostered_chg", "ecr": "ecr"}
    _write(config.SITE_DATA_DIR / "board.json", table(live, board_cols))

    # ---- history: each season's PRESEASON board, graded on the full season --------
    # (in-season weeks still train the model; they just aren't published)
    # reasons need the model that scored that season; rebuild them per fold
    hist_cols = {**COMMON, "ecr": "ecr", "season_ppg": "ros_ppg", "season_g": "ros_games",
                 "hit": "breakout", "startable": "startable", "next_ppg": "next_ppg"}
    pre = scored[(scored["week"] == 1) & (scored["season"] >= config.FIRST_HISTORY_SEASON)]
    hist_dir = config.SITE_DATA_DIR / "history"
    for old in hist_dir.glob("*.json"):
        old.unlink()
    for s in sorted(pre["season"].unique()):
        fold_model = train.fit(hist[hist["season"] < s])
        seas = pre[pre["season"] == s].copy()
        Xs = train.features(seas)
        seas["up"], seas["down"] = reasons(seas, fold_model, Xs)
        ecr_then, _ = market.ecr_asof(depth.week_start(int(s), 1))  # that August's rankings
        seas["ecr"] = seas["gsis_id"].map(ecr_then)
        if "next_ppg" not in seas:
            seas["next_ppg"] = np.nan
        _write(hist_dir / f"{s}.json", {"season": int(s), **table(seas, hist_cols)})

    # ---- meta -------------------------------------------------------------------
    start, jump = snap.thresholds()
    b = pd.Series(model.beta * model.sd, index=model.cols)  # per-1-sd effect
    meta = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "season": season, "week": week, "stats_through": last,
        "mode": "preseason" if week == 1 else "in-season",
        "thresholds": {"startable": start, "jump": jump},
        "groups": [{"key": g, "label": GROUP_INFO[g][0], "blurb": GROUP_INFO[g][1],
                    "weights": {f: round(float(b[f]), 3) for f in fs}}
                   for g, fs in train.feature_groups().items()],
        "features": explain_features(),
        "history_seasons": [int(s) for s in sorted(pre["season"].unique())],
        "train_seasons": [config.FIRST_TRAIN_SEASON, season - 1],
        "train_weeks": weeks,
        "value": {**config.model_config()["value"], "unranked": market.UNRANKED},
        "ecr_date": ecr_when.strftime("%Y-%m-%d") if ecr_when is not None else None,
        "preseason": _summary(rep[(rep["week"] == 1) & (rep["season"] >= config.FIRST_HISTORY_SEASON)]),
    }
    _write(config.SITE_DATA_DIR / "meta.json", meta)

    pooled = rep.groupby("week")[["auc", "auc_draft", "auc_prior", "hits@20", "base@20"]].mean()
    print(pooled.round(3).to_string())
    print(f"board: {season} week {week} ({len(live)} players)")


if __name__ == "__main__":
    main()
