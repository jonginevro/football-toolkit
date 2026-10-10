"""Central configuration: seasons, data URLs, paths, and the tunable YAML files."""
from __future__ import annotations

import datetime as dt
import functools
from pathlib import Path

import yaml

# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
SITE_DIR = ROOT / "docs"
SITE_DATA_DIR = SITE_DIR / "data"

# --- Seasons -----------------------------------------------------------------
# The season the live board is for. Rolls over in August so the board flips to
# "preseason" for the new year once rosters for it exist.
_today = dt.date.today()
CURRENT_SEASON = _today.year if _today.month >= 8 else _today.year - 1

# Earliest season with weekly stats we pull (the prior-year baseline for the
# first training season).
FIRST_STATS_SEASON = 2013
# Seasons used as training rows: each needs the season before it for a baseline.
FIRST_TRAIN_SEASON = 2014
# Walk-forward folds start once there are at least this many training seasons.
MIN_TRAIN_SEASONS = 3
# First season whose preseason board is published on the History page.
FIRST_HISTORY_SEASON = 2020

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# --- nflverse release asset URLs --------------------------------------------
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"


def stats_url(season: int) -> str:
    return f"{NFLVERSE}/stats_player/stats_player_week_{season}.parquet"


def weekly_roster_url(season: int) -> str:
    return f"{NFLVERSE}/weekly_rosters/roster_weekly_{season}.parquet"


def depth_chart_url(season: int) -> str:
    return f"{NFLVERSE}/depth_charts/depth_charts_{season}.parquet"


PLAYERS_URL = f"{NFLVERSE}/players/players.parquet"

# --- Sleeper API -------------------------------------------------------------
SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_TRENDING_URL = "https://api.sleeper.app/v1/players/nfl/trending/{kind}"

# --- ESPN fantasy (public, no auth): roster % and its 7-day change, all players
ESPN_PLAYERS_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
                    "{season}/segments/0/leaguedefaults/3?view=kona_player_info")


# --- Tunable configs ---------------------------------------------------------
@functools.lru_cache(maxsize=None)
def model_config() -> dict:
    with open(CONFIG_DIR / "model.yaml") as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=None)
def manual_catalysts() -> dict:
    path = CONFIG_DIR / "manual_catalysts.yaml"
    if not path.exists():
        return {"teams": {}, "players": {}}
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    return {"teams": data.get("teams") or {}, "players": data.get("players") or {}}
