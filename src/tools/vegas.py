"""Vegas view of the week: implied team totals from the spread and total, and
each player's PPR/g scaled by how many points Vegas expects his team to score
compared with what that team usually scores.

    implied (home) = (total + spread) / 2      spread > 0 = home favored
    implied (away) = (total - spread) / 2
    vegas PPR      = PPR/g x implied / team's usual points

A team's usual points blend its games so far with the league average (like
LEAGUE_GAMES games of it), so one blowout doesn't swing the multiplier."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import players, schedule

LEAGUE_GAMES = 3
MIN_EST_PPG = 4.0     # skip deep reserves; nobody is starting them
OUT = {"Out", "IR", "PUP", "Sus", "NA", "DNR"}


def build(season: int, week: int) -> dict:
    games = schedule.slate(season, week)
    pts = schedule.team_points(season)
    league = float(pts["pts"].mean()) if len(pts) else 22.0
    by_team = pts.groupby("team")["pts"].agg(["sum", "count"])
    usual = lambda t: (by_team["sum"].get(t, 0) + LEAGUE_GAMES * league) / (by_team["count"].get(t, 0) + LEAGUE_GAMES)

    teams, game_rows = {}, []
    for g in games.itertuples():
        has_line = pd.notna(g.spread_line) and pd.notna(g.total_line)
        home_imp = (g.total_line + g.spread_line) / 2 if has_line else None
        away_imp = (g.total_line - g.spread_line) / 2 if has_line else None
        game_rows.append({
            "id": g.game_id, "kickoff": g.kickoff.isoformat(), "away": g.away_team, "home": g.home_team,
            "spread": g.spread_line, "total": g.total_line, "away_ml": g.away_moneyline,
            "home_ml": g.home_moneyline, "away_imp": away_imp, "home_imp": home_imp,
            "final": bool(g.final), "away_score": g.away_score, "home_score": g.home_score,
        })
        for team, opp, imp, home, sp in ((g.home_team, g.away_team, home_imp, True, g.spread_line),
                                         (g.away_team, g.home_team, away_imp, False, -g.spread_line if has_line else None)):
            teams[team] = {"opp": opp, "home": home, "implied": imp, "spread": sp,
                           "usual": usual(team), "final": bool(g.final), "game": g.game_id}

    prod = players.production(season, week)
    prod = prod[prod["team"].isin(teams) & (prod["est_ppg"] >= MIN_EST_PPG)].copy()
    prod["injury"] = prod["sleeper_id"].map(players.injuries())
    prod = prod[~prod["injury"].isin(OUT)]
    t = pd.DataFrame.from_dict(teams, orient="index")
    prod = prod.join(t, on="team")
    prod = prod[prod["implied"].notna()]
    prod["mult"] = prod["implied"] / prod["usual"]
    prod["vegas_ppg"] = prod["est_ppg"] * prod["mult"]
    prod = prod.sort_values("vegas_ppg", ascending=False)

    rows = [[r.gsis_id, r.name, r.position, r.team, r.opp, bool(r.home), _r(r.implied), _r(r.usual),
             _r(r.spread), _r(r.est_ppg), _r(r.vegas_ppg), _r(r.mult, 3), r.injury if isinstance(r.injury, str) else None,
             r.headshot if isinstance(r.headshot, str) else None, bool(r.final)]
            for r in prod.itertuples()]
    return {
        "season": season, "week": week, "league_avg": round(league, 1),
        "games": [{k: _r(v) if isinstance(v, float) else v for k, v in row.items()} for row in game_rows],
        "cols": ["id", "name", "pos", "team", "opp", "home", "implied", "usual", "spread",
                 "ppg", "vegas", "mult", "injury", "headshot", "final"],
        "rows": rows,
    }


def _r(v, d=1):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return round(float(v), d)
