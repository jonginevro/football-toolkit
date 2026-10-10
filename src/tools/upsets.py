"""Upset watch: long shots worth a look, not coin flips.

Only real underdogs are considered (Vegas gives them LONG_SHOT chance). Each
one gets an upset score: the sum of every situational spot it's in, each
weighted by how much underdogs in that spot have beaten Vegas's expectation
since 2007 (shrunk toward zero for small samples, so a spot needs a real
record to count), plus late injury news. Spots that historically favor the
favorite count against. The three long shots with the most going for them
each week are the picks.

The market prices most of this already, so most picks will lose; that's the
point of a long-shot list. The page publishes how the same method would have
done each past season (weights learned only from earlier seasons): wins vs.
what Vegas expected, and the result of a flat $100 on every pick. A
flags-plus-line model is also scored against the line alone."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import players, schedule, weather

FIRST_SEASON = 2007   # moneylines are near-complete from here
LONG_SHOT = (0.15, 0.42)   # Vegas win chance range for a pick: real underdogs, not coin flips or hopeless
SHRINK_GAMES = 400         # a spot's weight is its gap x games / (games + this)
PICKS = 3
# injury news has no history to learn from: fixed, deliberately modest weights (points of win chance)
INJURY_PTS = {("fav", "QB"): 5.0, ("fav", "other"): 1.0, ("dog", "QB"): -5.0, ("dog", "other"): -1.0}
L2 = 100.0
EVAL_SEASONS = 12

TZ = {**{t: 0 for t in ["ATL", "BAL", "BUF", "CAR", "CIN", "CLE", "DET", "IND", "JAX", "MIA",
                        "NE", "NYG", "NYJ", "PHI", "PIT", "TB", "WAS"]},
      **{t: -1 for t in ["CHI", "DAL", "GB", "HOU", "KC", "MIN", "NO", "TEN", "STL"]},
      **{t: -2 for t in ["DEN", "ARI"]},
      **{t: -3 for t in ["LA", "LAC", "LV", "OAK", "SD", "SEA", "SF"]}}

FEATURES = ["mkt_logit", "total_c", "rest_diff", "fav_short", "dog_bye", "fav_bye", "div", "neutral",
            "dog_home", "wind", "cold", "west_early", "fav_trip", "form_diff", "fav_letdown", "dog_bounce",
            "primetime"]

# flag key -> (label, condition on the feature table, plain-language text for one game)
FLAGS = {
    "high_total": ("High total", lambda X: X["total_c"] >= 0.5,
                   lambda r: f"Total of {r['total_line']:.1f}: lots of scoring, more variance"),
    "low_total": ("Low total", lambda X: X["total_c"] <= -0.5,
                  lambda r: f"Total of {r['total_line']:.1f}: a low-scoring game"),
    "dog_rest": ("Underdog rest edge", lambda X: X["rest_diff"] >= 3,
                 lambda r: f"{r['dog']} has {int(r['rest_diff'])} more days of rest"),
    "fav_rest": ("Favorite rest edge", lambda X: X["rest_diff"] <= -3,
                 lambda r: f"{r['fav']} has {int(-r['rest_diff'])} more days of rest"),
    "fav_short": ("Favorite on a short week", lambda X: X["fav_short"] == 1,
                  lambda r: f"{r['fav']} is on a short week"),
    "dog_bye": ("Underdog off a bye", lambda X: X["dog_bye"] == 1, lambda r: f"{r['dog']} is coming off a bye"),
    "fav_bye": ("Favorite off a bye", lambda X: X["fav_bye"] == 1, lambda r: f"{r['fav']} is coming off a bye"),
    "div": ("Division game", lambda X: X["div"] == 1, lambda r: "Division rivals who know each other well"),
    "neutral": ("Neutral or international site", lambda X: X["neutral"] == 1,
                lambda r: "Neutral site, so no home-field advantage"),
    "dog_home": ("Home underdog", lambda X: X["dog_home"] == 1, lambda r: f"{r['dog']} is at home"),
    "wind": ("Wind 15+ mph", lambda X: X["wind"] == 1, lambda r: "Wind of 15+ mph"),
    "cold": ("Freezing", lambda X: X["cold"] == 1, lambda r: "Freezing temperatures"),
    "fav_clock": ("Favorite's body clock", lambda X: X["west_early"] > 0,
                  lambda r: f"{r['fav']} is a western team in an early eastern kickoff"),
    "dog_clock": ("Underdog's body clock", lambda X: X["west_early"] < 0,
                  lambda r: f"{r['dog']} is a western team in an early eastern kickoff"),
    "fav_trip": ("Favorite's long trip", lambda X: X["fav_trip"] == 1,
                 lambda r: f"{r['fav']} travels two or more time zones"),
    "dog_form": ("Underdog has the better point differential", lambda X: X["form_diff"] > 0,
                 lambda r: f"{r['dog']} has outscored opponents by more per game than {r['fav']}"),
    "fav_letdown": ("Favorite after a 20+ point win", lambda X: X["fav_letdown"] == 1,
                    lambda r: f"{r['fav']} won its last game by 20+"),
    "dog_bounce": ("Underdog after a 20+ point loss", lambda X: X["dog_bounce"] == 1,
                   lambda r: f"{r['dog']} lost its last game by 20+"),
    "primetime": ("Night game", lambda X: X["primetime"] == 1, lambda r: "Night game"),
}


def _implied(ml: pd.Series) -> pd.Series:
    return np.where(ml > 0, 100 / (ml + 100), -ml / (-ml + 100))


def _team_form(g: pd.DataFrame) -> pd.DataFrame:
    """Per (game, team): season-to-date point diff per game, games played and
    last game's margin, using only games before this one."""
    long = pd.concat([
        g[["game_id", "season", "week", "home_team", "home_score", "away_score"]]
        .set_axis(["game_id", "season", "week", "team", "pf", "pa"], axis=1),
        g[["game_id", "season", "week", "away_team", "away_score", "home_score"]]
        .set_axis(["game_id", "season", "week", "team", "pf", "pa"], axis=1),
    ]).sort_values(["season", "team", "week"])
    long["margin"] = long["pf"] - long["pa"]
    grp = long.groupby(["season", "team"])["margin"]
    long["ppd"] = grp.transform(lambda s: s.shift().expanding().mean())
    long["n"] = grp.transform(lambda s: s.shift().expanding().count())
    long["last"] = grp.shift()
    return long.set_index(["game_id", "team"])[["ppd", "n", "last"]]


def features(g: pd.DataFrame, form: pd.DataFrame) -> pd.DataFrame:
    """One row per game with a line, from the underdog's side."""
    g = g[g["home_moneyline"].notna() & g["away_moneyline"].notna()].copy()
    ph, pa = _implied(g["home_moneyline"]), _implied(g["away_moneyline"])
    g["p_home"] = ph / (ph + pa)
    g = g[g["p_home"] != 0.5]
    home_dog = g["p_home"] < 0.5
    g["dog"] = np.where(home_dog, g["home_team"], g["away_team"])
    g["fav"] = np.where(home_dog, g["away_team"], g["home_team"])
    g["p_mkt"] = np.where(home_dog, g["p_home"], 1 - g["p_home"])
    dog_rest = np.where(home_dog, g["home_rest"], g["away_rest"])
    fav_rest = np.where(home_dog, g["away_rest"], g["home_rest"])
    neutral = g["location"].eq("Neutral")

    X = pd.DataFrame(index=g.index)
    X["mkt_logit"] = np.log(g["p_mkt"] / (1 - g["p_mkt"]))
    X["total_c"] = ((g["total_line"] - 44) / 10).fillna(0)
    X["rest_diff"] = np.clip(dog_rest - fav_rest, -7, 7)
    X["fav_short"] = (fav_rest <= 4).astype(float)
    X["dog_bye"] = (dog_rest >= 13).astype(float)
    X["fav_bye"] = (fav_rest >= 13).astype(float)
    X["div"] = g["div_game"].fillna(0).astype(float)
    X["neutral"] = neutral.astype(float)
    X["dog_home"] = (home_dog & ~neutral).astype(float)
    X["wind"] = (g["wind"].fillna(0).clip(upper=30) >= 15).astype(float)
    X["cold"] = (g["temp"].fillna(60) <= 32).astype(float)

    tz = lambda s: s.map(TZ).fillna(0)
    home_tz, away_tz = tz(g["home_team"]), tz(g["away_team"])
    early = pd.to_datetime(g["gametime"].fillna("13:00"), format="%H:%M").dt.hour <= 13
    west_early = (~neutral & early & (away_tz <= -2) & (home_tz == 0))  # away team's body clock says ~10am
    X["west_early"] = np.where(west_early, np.where(home_dog, 1.0, -1.0), 0.0)
    X["fav_trip"] = (~home_dog & ~neutral & ((away_tz - home_tz).abs() >= 2)).astype(float)

    f = lambda team: form.reindex(pd.MultiIndex.from_arrays([g["game_id"], team]))
    fd, ff = f(g["dog"]), f(g["fav"])
    both = (fd["n"].to_numpy() >= 3) & (ff["n"].to_numpy() >= 3)
    X["form_diff"] = np.where(both, (fd["ppd"].to_numpy() - ff["ppd"].to_numpy()) / 7, 0.0)
    X["fav_letdown"] = (ff["last"].to_numpy() >= 20).astype(float)
    X["dog_bounce"] = (fd["last"].to_numpy() <= -20).astype(float)
    X["primetime"] = (pd.to_datetime(g["gametime"].fillna("13:00"), format="%H:%M").dt.hour >= 19).astype(float)

    y = np.where(g["home_score"].isna(), np.nan,
                 np.where(home_dog, g["home_score"] > g["away_score"], g["away_score"] > g["home_score"]).astype(float))
    y = np.where(g["home_score"] == g["away_score"], np.nan, y)
    g["dog_ml"] = np.where(home_dog, g["home_moneyline"], g["away_moneyline"])
    meta = g[["game_id", "season", "week", "kickoff", "home_team", "away_team", "dog", "fav", "p_mkt", "dog_ml",
              "spread_line", "total_line", "home_moneyline", "away_moneyline", "final", "home_score", "away_score"]]
    return X.join(meta).assign(y=y)


def _logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _fit_offset(Z: np.ndarray, offset: np.ndarray, y: np.ndarray, l2: float) -> np.ndarray:
    """Logistic regression on top of a fixed offset (the market's log-odds):
    only the factors are learned and shrunk, Vegas stays at full weight."""
    w = np.zeros(Z.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-(offset + Z @ w)))
        step = np.linalg.solve((Z * (p * (1 - p))[:, None]).T @ Z + l2 * np.eye(len(w)), Z.T @ (p - y) + l2 * w)
        w -= step
        if np.abs(step).max() < 1e-9:
            break
    return w


def flag_record(hist: pd.DataFrame) -> dict:
    """How underdogs did in each spot vs. what Vegas expected. `band` is two
    standard errors: a gap smaller than that is within normal noise."""
    out = {}
    for k, (label, cond, _) in FLAGS.items():
        h = hist[cond(hist)]
        if len(h) == 0:
            continue
        exp = h["p_mkt"]
        out[k] = {"label": label, "games": int(len(h)), "actual": round(float(h["y"].mean()), 3),
                  "expected": round(float(exp.mean()), 3),
                  "band": round(float(2 * np.sqrt((exp * (1 - exp)).sum()) / len(h)), 3)}
    return out


def evaluate(hist: pd.DataFrame, season: int) -> dict:
    """Walk-forward: each season scored by a flags-plus-line model trained on
    the seasons before it, vs. the line alone. Lower log loss is better."""
    factors = FEATURES[1:]
    rows = []
    for s in range(season - EVAL_SEASONS, season):
        tr, te = hist[hist["season"] < s], hist[hist["season"] == s]
        if len(te) == 0 or len(tr) == 0:
            continue
        w = _fit_offset(tr[factors].to_numpy(), tr["mkt_logit"].to_numpy(), tr["y"].to_numpy(), L2)
        p = 1 / (1 + np.exp(-(te["mkt_logit"].to_numpy() + te[factors].to_numpy() @ w)))
        rows.append((s, len(te), _logloss(p, te["y"]), _logloss(te["p_mkt"], te["y"])))
    if not rows:
        return {}
    n = sum(r[1] for r in rows)
    return {"seasons": [rows[0][0], rows[-1][0]], "games": n,
            "model": round(sum(r[1] * r[2] for r in rows) / n, 4),
            "vegas": round(sum(r[1] * r[3] for r in rows) / n, 4),
            "model_better_seasons": sum(r[2] < r[3] for r in rows), "n_seasons": len(rows)}


def weights(record: dict) -> dict:
    """Spot -> points of win chance it adds for the underdog, shrunk by sample size."""
    return {k: (r["actual"] - r["expected"]) * 100 * r["games"] / (r["games"] + SHRINK_GAMES)
            for k, r in record.items()}


def _flag_matrix(X: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({k: cond(X).astype(float) for k, (_, cond, _) in FLAGS.items()}, index=X.index)


def track_record(hist: pd.DataFrame, season: int) -> dict:
    """Replay the picks for each past season with weights from earlier seasons only
    (no injuries: there's no history of them)."""
    flags = _flag_matrix(hist)
    seasons = []
    for s in range(season - EVAL_SEASONS, season):
        past, cur = hist[hist["season"] < s], hist[hist["season"] == s]
        if len(cur) == 0:
            continue
        w = pd.Series(weights(flag_record(past))).reindex(flags.columns).fillna(0)
        c = cur.assign(score=flags.loc[cur.index] @ w)
        c = c[c["p_mkt"].between(*LONG_SHOT) & (c["score"] > 0)]
        picks = c.sort_values("score", ascending=False).groupby("week").head(PICKS)
        profit = np.where(picks["y"] == 1, picks["dog_ml"].clip(lower=100), -100).sum()
        seasons.append({"season": s, "picks": len(picks), "wins": int(picks["y"].sum()),
                        "expected": round(float(picks["p_mkt"].sum()), 1), "profit": int(profit)})
    tot = {k: sum(x[k] for x in seasons) for k in ("picks", "wins", "profit")}
    tot["expected"] = round(sum(x["expected"] for x in seasons), 1)
    return {"seasons": seasons, "total": tot}


def build(season: int, week: int) -> dict:
    g = schedule.games()
    g = g[g["season"] >= FIRST_SEASON]
    allx = features(g, _team_form(g))  # unplayed games get form from the games before them
    hist = allx[allx["y"].notna() & ((allx["season"] < season) | (allx["week"] < week))]
    record = flag_record(hist)
    w = weights(record)

    cur = allx[(allx["season"] == season) & (allx["week"] == week)].copy()
    cur = _live_weather(cur, season, week)
    inj = _injuries(season, week)
    games = []
    for _, r in cur.iterrows():
        row = cur.loc[[r.name]]
        reasons = [{"text": text(r), "pts": round(w.get(k, 0.0), 1), "key": k}
                   for k, (_, cond, text) in FLAGS.items() if bool(cond(row).iloc[0])]
        for side, team in (("fav", r["fav"]), ("dog", r["dog"])):
            for p in inj.get(team, []):
                pts = INJURY_PTS[(side, "QB" if p["pos"] == "QB" else "other")]
                status = "out" if p["status"] == "Out" else "doubtful"
                reasons.append({"text": f"{team} {'QB ' if p['pos'] == 'QB' else ''}{p['name']} is {status}",
                                "pts": pts, "key": "injury"})
        score = round(sum(x["pts"] for x in reasons), 1)
        reasons = [x for x in reasons if abs(x["pts"]) >= 0.25]  # tiny weights are noise; still in the score
        reasons.sort(key=lambda x: -x["pts"])
        games.append({
            "id": r["game_id"], "kickoff": r["kickoff"].isoformat(), "home": r["home_team"], "away": r["away_team"],
            "dog": r["dog"], "fav": r["fav"], "p_mkt": round(float(r["p_mkt"]), 3),
            "spread": abs(float(r["spread_line"])) if pd.notna(r["spread_line"]) else None,
            "dog_ml": _f(r["dog_ml"]), "score": score, "reasons": reasons,
            "long_shot": bool(LONG_SHOT[0] <= r["p_mkt"] <= LONG_SHOT[1]),
            "final": bool(r["final"]), "dog_won": None if pd.isna(r["y"]) else bool(r["y"]),
            "result": None if not r["final"] else {"home": int(r["home_score"]), "away": int(r["away_score"])},
        })
    games.sort(key=lambda x: (-x["long_shot"], -x["score"]))
    picks = [x["id"] for x in games if x["long_shot"] and not x["final"] and x["score"] > 0][:PICKS]
    return {"season": season, "week": week, "since": FIRST_SEASON, "n_games": int(len(hist)),
            "long_shot": LONG_SHOT, "picks": picks, "games": games,
            "record": {k: {**v, "pts": round(w[k], 1)} for k, v in record.items()},
            "track": track_record(hist, season), "eval": evaluate(hist, season)}


def _live_weather(cur: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """The schedule has no game-time weather until it's played: use the forecast."""
    try:
        wx = {g["id"]: g["conditions"] for g in weather.build(season, week)["games"] if g["conditions"]}
    except Exception:
        return cur
    for i, r in cur.iterrows():
        c = wx.get(r["game_id"])
        if c and not r["final"]:
            cur.at[i, "wind"] = float(c["wind"] >= 15)
            cur.at[i, "cold"] = float(c["temp"] <= 32)
    return cur


def _injuries(season: int, week: int) -> dict:
    """team -> key players listed Out or Doubtful this week (season-long IR is
    old news the line has long since absorbed)."""
    try:
        prod = players.production(season, week)
        prod["injury"] = prod["sleeper_id"].map(players.injuries())
    except Exception:
        return {}
    keep = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}
    prod["pos_rank"] = prod.groupby(["team", "position"])["est_ppg"].rank(ascending=False, method="first")
    key = prod[(prod["pos_rank"] <= prod["position"].map(keep)) & prod["injury"].isin(["Out", "Doubtful"])]
    out = {}
    for r in key.sort_values("est_ppg", ascending=False).itertuples():
        out.setdefault(r.team, []).append({"name": r.name, "pos": r.position, "status": r.injury,
                                           "ppg": round(float(r.est_ppg), 1)})
    return out


def _f(v):
    return None if v is None or pd.isna(v) else float(v)
