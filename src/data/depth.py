"""Normalize nflverse depth charts into one as-of view: for a (season, week),
each offensive skill player's depth TIER on his team — 1 = starter, 2 = next
man up, 3 = deeper. Two raw schemas have to be reconciled:

* <= 2024: one row per (team, week, slot) with `depth_team` 1/2/3. Three WR
  slots each have their own depth_team 1, so "tier 1" already means starter.
* >= 2025: timestamped ESPN snapshots with a team-wide `pos_rank` per position
  (WR1..WR10). We map rank -> tier using how many start at that position.

Critically this never looks past the week being scored: an end-of-season depth
chart would leak who actually broke out."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from . import nflverse

STARTERS = {"QB": 1, "RB": 1, "WR": 3, "TE": 1}
_OLD_POS = {"QB": "QB", "RB": "RB", "HB": "RB", "WR": "WR", "LWR": "WR",
            "RWR": "WR", "SWR": "WR", "TE": "TE"}


def week_start(season: int, week: int) -> pd.Timestamp:
    """Tuesday before week `week`'s games (week 1 opens the Thursday after Labor Day)."""
    sept1 = dt.date(season, 9, 1)
    labor_day = sept1 + dt.timedelta(days=(7 - sept1.weekday()) % 7)
    return pd.Timestamp(labor_day + dt.timedelta(days=1 + 7 * (week - 1)), tz="UTC")


def depth_asof(season: int, week: int) -> pd.DataFrame:
    """gsis_id -> depth tier, as known going into `week` of `season`."""
    raw = nflverse.depth_charts(season)
    if raw.empty:
        return pd.DataFrame(columns=["gsis_id", "depth_tier"])

    if "depth_team" in raw.columns:  # old schema
        d = raw[(raw["formation"] == "Offense") & (raw["game_type"] == "REG")].copy()
        d["pos"] = d["depth_position"].astype(str).str.strip().map(_OLD_POS)
        d = d.dropna(subset=["pos", "gsis_id", "week"])
        avail = d["week"].unique()
        # the chart published for this week, else the latest one before it
        prior = [w for w in avail if w <= week]
        if not prior:
            return pd.DataFrame(columns=["gsis_id", "depth_tier"])
        d = d[d["week"] == max(prior)]
        d["depth_tier"] = pd.to_numeric(d["depth_team"], errors="coerce")
        return (d.groupby("gsis_id", as_index=False)["depth_tier"].min())

    d = raw[raw["pos_abb"].isin(STARTERS) & raw["gsis_id"].notna()].copy()
    d["ts"] = pd.to_datetime(d["dt"], utc=True)
    cutoff = week_start(season, week)
    before = d[d["ts"] < cutoff]
    if before.empty:
        return pd.DataFrame(columns=["gsis_id", "depth_tier"])
    # latest snapshot per team (teams update on different days)
    last = before.groupby("team")["ts"].transform("max")
    d = before[before["ts"] == last]
    n = d["pos_abb"].map(STARTERS)
    d = d.assign(depth_tier=np.ceil(d["pos_rank"] / n).clip(upper=3))
    return d.groupby("gsis_id", as_index=False)["depth_tier"].min()
