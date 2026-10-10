"""Fetch nflverse release data (weekly stats, weekly rosters, depth charts,
players) with an on-disk parquet cache. Completed seasons never change, so they
are cached forever; the current season is refreshed when stale."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from .. import config


def _cache_path(name: str) -> Path:
    return config.CACHE_DIR / f"{name}.parquet"


def _load(name: str, url: str, max_age_hours: float | None, force: bool = False,
          columns: list[str] | None = None) -> pd.DataFrame:
    """Return a cached parquet if fresh (max_age_hours=None means never stale),
    else download from `url` and cache it."""
    path = _cache_path(name)
    if not force and path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if max_age_hours is None or age_h < max_age_hours:
            return pd.read_parquet(path, columns=columns)
    try:
        df = pd.read_parquet(url)
        if columns:
            df = df[[c for c in columns if c in df.columns]]
        df.to_parquet(path)
        return df
    except Exception:
        if path.exists():  # network hiccup: fall back to a stale cache
            return pd.read_parquet(path, columns=columns)
        raise


def _ttl(season: int) -> float | None:
    return 6 if season >= config.CURRENT_SEASON else None


STAT_COLS = [
    "player_id", "player_display_name", "position", "season", "week", "season_type",
    "team", "attempts", "carries", "receptions", "targets", "passing_yards",
    "rushing_yards", "receiving_yards", "fantasy_points_ppr",
]


def weekly_stats(season: int, force: bool = False) -> pd.DataFrame:
    """Regular-season weekly player stats for one season (empty if unpublished)."""
    try:
        df = _load(f"stats_{season}", config.stats_url(season), _ttl(season), force,
                   columns=STAT_COLS)
    except Exception:
        return pd.DataFrame(columns=STAT_COLS)
    return df[df["season_type"] == "REG"].copy()


ROSTER_COLS = ["season", "week", "game_type", "team", "position", "status",
               "full_name", "gsis_id", "sleeper_id", "espn_id", "birth_date", "entry_year",
               "rookie_year", "draft_number", "headshot_url"]


def weekly_roster(season: int, force: bool = False) -> pd.DataFrame:
    try:
        df = _load(f"roster_weekly_{season}", config.weekly_roster_url(season),
                   _ttl(season), force, columns=ROSTER_COLS)
    except Exception:
        return pd.DataFrame(columns=ROSTER_COLS)
    return df[df["game_type"] == "REG"].copy()


def depth_charts(season: int, force: bool = False) -> pd.DataFrame:
    """Raw depth charts. nflverse switched schemas in 2025: before that it is one
    row per (team, week, slot) with `depth_team`; from 2025 it is ESPN snapshots
    keyed by timestamp `dt` with `pos_rank`. data/depth.py normalizes both."""
    try:
        return _load(f"depth_{season}", config.depth_chart_url(season), _ttl(season), force)
    except Exception:
        return pd.DataFrame()


def players(force: bool = False) -> pd.DataFrame:
    """One row per player ever: birth date and draft capital, season-independent."""
    cols = ["gsis_id", "display_name", "position", "birth_date", "rookie_season",
            "draft_year", "draft_round", "draft_pick", "headshot"]
    return _load("players", config.PLAYERS_URL, 24 * 7, force, columns=cols)
