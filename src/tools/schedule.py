"""The NFL schedule with Vegas lines, from nflverse's games file (Lee Sharpe's
nfldata). One row per game: kickoff (ET), teams, final score once played,
closing-ish spread / total / moneylines, roof and stadium.

`current_week` is the week whose games are still being played (or next up), so
"this week" means the same thing on every page: Thursday's game being final
doesn't flip the site to the next week."""
from __future__ import annotations

import functools
import time

import pandas as pd

from .. import config

GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
COLS = ["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team",
        "home_team", "away_score", "home_score", "spread_line", "total_line",
        "away_moneyline", "home_moneyline", "roof", "stadium_id", "stadium", "location",
        "div_game", "away_rest", "home_rest", "temp", "wind"]


@functools.lru_cache(maxsize=None)
def games() -> pd.DataFrame:
    path = config.CACHE_DIR / "games_v2.parquet"
    fresh = path.exists() and (time.time() - path.stat().st_mtime) / 3600 < 3
    if not fresh:
        try:
            pd.read_csv(GAMES_URL, usecols=COLS).to_parquet(path)
        except Exception:
            if not path.exists():
                raise
    g = pd.read_parquet(path)
    g = g[g["game_type"] == "REG"].copy()
    g["kickoff"] = pd.to_datetime(g["gameday"] + " " + g["gametime"].fillna("13:00")) \
        .dt.tz_localize("America/New_York")
    g["final"] = g["home_score"].notna()
    return g


def season_games(season: int) -> pd.DataFrame:
    return games()[games()["season"] == season].copy()


def current_week(season: int) -> int:
    """Lowest week with a game not yet final; 1 before the season, 18 after it."""
    g = season_games(season)
    if g.empty:
        return 1
    open_weeks = g.loc[~g["final"], "week"]
    return int(open_weeks.min()) if len(open_weeks) else int(g["week"].max())


def slate(season: int, week: int) -> pd.DataFrame:
    return season_games(season).query("week == @week").sort_values(["kickoff", "game_id"])


def team_points(season: int) -> pd.DataFrame:
    """Points scored per completed game, one row per (team, game)."""
    g = season_games(season)
    g = g[g["final"]]
    home = g[["week", "home_team", "home_score"]].set_axis(["week", "team", "pts"], axis=1)
    away = g[["week", "away_team", "away_score"]].set_axis(["week", "team", "pts"], axis=1)
    return pd.concat([home, away], ignore_index=True)
