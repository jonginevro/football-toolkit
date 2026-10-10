"""Per-player PPR production as of a week, shared by the Vegas and trade tools.

`production(season, before_week)` uses only games played before `before_week`
and blends this season's per-game with last season's, so a player with one
big game isn't treated as a star and a rookie isn't treated as zero."""
from __future__ import annotations

import functools

import numpy as np
import pandas as pd

from .. import config
from ..data import nflverse
from ..model import snapshot as snap

PRIOR_GAMES = 4  # last season counts like this many games of this season
# Typical 12-team, 1QB starting-lineup depth: production is measured above the
# player at this rank, so a QB's raw points don't outrank a WR's scarcity.
REPLACEMENT_RANK = {"QB": 12, "RB": 30, "WR": 36, "TE": 12}


@functools.lru_cache(maxsize=None)
def _bio() -> pd.DataFrame:
    return nflverse.players().drop_duplicates("gsis_id").set_index("gsis_id")


@functools.lru_cache(maxsize=None)
def _rosters(season: int) -> pd.DataFrame:
    return nflverse.weekly_roster(season)


def roster_asof(season: int, week: int) -> pd.DataFrame:
    """Active skill players and their team in the latest roster week <= `week`."""
    r = _rosters(season)
    r = r[r["position"].isin(config.SKILL_POSITIONS)]
    if r.empty:
        return pd.DataFrame(columns=["gsis_id", "team", "position", "full_name", "status", "sleeper_id", "headshot_url"])
    wk = r.loc[r["week"] <= week, "week"].max()
    if pd.isna(wk):
        wk = r["week"].min()
    cur = r[(r["week"] == wk) & r["status"].isin(["ACT", "INA", "RES"])]
    return cur.drop_duplicates("gsis_id")[["gsis_id", "team", "position", "full_name", "status",
                                           "sleeper_id", "headshot_url"]]


def production(season: int, before_week: int) -> pd.DataFrame:
    """One row per rostered skill player: games and PPR/g this season (before
    `before_week`), last season's PPR/g, the blended estimate, and points above
    a replacement-level starter at his position."""
    roster = roster_asof(season, max(before_week - 1, 1))
    cur = snap.season_stats(season)
    cur = cur[cur["week"] < before_week]
    prev = snap.season_stats(season - 1)

    agg = lambda s: s.groupby("player_id")["ppr"].agg(["sum", "count"])
    c, p = agg(cur), agg(prev)
    df = roster.copy()
    df["games"] = df["gsis_id"].map(c["count"]).fillna(0)
    df["pts"] = df["gsis_id"].map(c["sum"]).fillna(0)
    df["prior_ppg"] = df["gsis_id"].map(p["sum"] / p["count"])

    # rookies / no prior: lean on a low positional default instead of zero
    default = {pos: 0.6 * lvl for pos, lvl in _replacement_levels(prev).items()}
    prior = df["prior_ppg"].fillna(df["position"].map(default))
    df["ppg"] = np.where(df["games"] > 0, df["pts"] / df["games"].clip(lower=1), np.nan)
    df["est_ppg"] = (df["pts"] + PRIOR_GAMES * prior) / (df["games"] + PRIOR_GAMES)

    repl = df.groupby("position")["est_ppg"].apply(
        lambda s: s.sort_values(ascending=False).iloc[min(REPLACEMENT_RANK[s.name], len(s)) - 1])
    df["vorp"] = df["est_ppg"] - df["position"].map(repl)

    bio = _bio()
    df["name"] = df["gsis_id"].map(bio["display_name"]).fillna(df["full_name"])
    df["headshot"] = df["headshot_url"].fillna(df["gsis_id"].map(bio["headshot"]))
    df["sleeper_id"] = df["sleeper_id"].astype("string").str.replace(r"\.0$", "", regex=True)
    return df.drop(columns=["full_name", "headshot_url"]).reset_index(drop=True)


def _replacement_levels(stats: pd.DataFrame) -> dict:
    if stats.empty:
        return {"QB": 15.0, "RB": 9.0, "WR": 9.0, "TE": 7.0}
    ppg = stats.groupby(["player_id", "position"])["ppr"].mean().reset_index()
    return {pos: float(g["ppr"].sort_values(ascending=False).iloc[min(REPLACEMENT_RANK[pos], len(g)) - 1])
            for pos, g in ppg.groupby("position")}


def injuries() -> pd.Series:
    """sleeper_id -> Sleeper injury tag (Questionable, Out, IR, ...)."""
    from ..data import sleeper
    sl = sleeper.players()
    if sl.empty:
        return pd.Series(dtype=object)
    return sl.drop_duplicates("sleeper_id").set_index("sleeper_id")["injury_status"]
