"""Survivor pool data: every team's chance to win each remaining game.

This week (and any later week the books have posted) uses the moneylines with
the bookmaker's cut removed. Weeks without lines use power ratings fitted to
the spreads posted so far this season (last season's spreads count a little,
so week 1 has something to go on):

    spread (home) = rating(home) - rating(away) + HOME_EDGE (unless neutral)
    win chance    = Normal CDF(spread / MARGIN_SD)

The page does the planning in the browser, because it depends on which teams
the reader has already used."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import schedule

HOME_EDGE = 1.7
MARGIN_SD = 13.5       # spread of NFL final margins around the line
LAST_SEASON_WEIGHT = 0.3
RIDGE = 2.0


def ratings(season: int) -> tuple[pd.Series, float]:
    """Team power ratings in points from weighted least squares on posted spreads."""
    g = schedule.games()
    g = g[g["season"].isin([season - 1, season]) & g["spread_line"].notna()]
    teams = sorted(set(g["home_team"]) | set(g["away_team"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(g)
    A = np.zeros((n, len(teams) + 1))
    A[np.arange(n), g["home_team"].map(idx)] = 1
    A[np.arange(n), g["away_team"].map(idx)] = -1
    A[:, -1] = (g["location"] != "Neutral").astype(float)
    w = np.where(g["season"] == season, 1.0, LAST_SEASON_WEIGHT)
    y = g["spread_line"].to_numpy()
    reg = np.full(len(teams) + 1, RIDGE)
    reg[-1] = 0.0
    W = A * w[:, None]
    beta = np.linalg.solve(A.T @ W + np.diag(reg), W.T @ y)
    return pd.Series(beta[:-1], index=teams), float(beta[-1])


def _cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _implied(ml: float) -> float:
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def build(season: int, week: int) -> dict:
    r, home_edge = ratings(season)
    g = schedule.season_games(season)
    g = g[g["week"] >= week].sort_values(["week", "kickoff"])
    weeks = {}
    for x in g.itertuples():
        neutral = x.location == "Neutral"
        if pd.notna(x.home_moneyline) and pd.notna(x.away_moneyline):
            ph, pa = _implied(x.home_moneyline), _implied(x.away_moneyline)
            p_home, source = ph / (ph + pa), "vegas"
        else:
            spread = r.get(x.home_team, 0) - r.get(x.away_team, 0) + (0 if neutral else home_edge)
            p_home, source = _cdf(spread / MARGIN_SD), "rating"
        weeks.setdefault(int(x.week), []).append({
            "id": x.game_id, "kickoff": x.kickoff.isoformat(), "home": x.home_team, "away": x.away_team,
            "p_home": round(p_home, 3), "source": source, "final": bool(x.final),
            "winner": (None if not x.final else x.home_team if x.home_score > x.away_score
                       else x.away_team if x.away_score > x.home_score else "TIE"),
            "div": bool(x.div_game), "thursday": x.kickoff.weekday() == 3, "intl": bool(neutral),
            "night": x.kickoff.hour >= 19,
        })
    return {
        "season": season, "week": week,
        "teams": sorted(r.index[r.index.isin(set(g["home_team"]) | set(g["away_team"]))].tolist()),
        "ratings": {t: round(float(v), 1) for t, v in r.sort_values(ascending=False).items()},
        "home_edge": round(home_edge, 2),
        "weeks": [{"week": w, "games": gs} for w, gs in sorted(weeks.items())],
    }
