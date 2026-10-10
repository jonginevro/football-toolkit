"""Week-to-week redraft trade values (12-team, 1QB, PPR).

Each week's chart blends two ranks of every skill player into one value:

* market: FantasyPros overall ECR from the snapshot published before that week
  (rest-of-season rankings once the season starts), so QBs land where a 1QB
  market prices them
* production: points per game above a replacement-level starter at his
  position, from games played before that week blended with last season

    value = MARKET_WEIGHT * curve(market rank) + (1 - MARKET_WEIGHT) * curve(production rank)
    curve(rank) = TOP * exp(-(rank - 1) / DECAY)

Every past week is rebuilt from what was known then, so a week's trend
(value minus the week before) is reproducible and needs no saved state. The
current week also counts games already played this week, so it moves after
every game."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import depth, market
from . import players

TOP = 80.0
DECAY = 50.0
MARKET_WEIGHT = 0.6
# Lower bound of each tier. Below the last one a player isn't relevant in
# redraft, so he's left off the chart.
TIERS = [60, 40, 25, 15, 10, 6, 3.5, 1.5]
MIN_VALUE = TIERS[-1]


def curve(rank: pd.Series) -> pd.Series:
    return (TOP * np.exp(-(rank - 1) / DECAY)).fillna(0.0)


def values(season: int, week: int, live: bool) -> tuple[pd.DataFrame, str | None]:
    prod = players.production(season, week + 1 if live else week)
    cutoff = pd.Timestamp.now() if live else depth.week_start(season, week).tz_localize(None)
    ecr, when = market.ecr_asof(cutoff)
    prod["ecr"] = prod["gsis_id"].map(ecr)
    prod["market_rank"] = prod["ecr"].rank(method="first")
    prod["prod_rank"] = prod["vorp"].rank(ascending=False, method="first")
    raw = MARKET_WEIGHT * curve(prod["market_rank"]) + (1 - MARKET_WEIGHT) * curve(prod["prod_rank"])
    prod["value"] = (raw * 2).round() / 2
    prod = prod[prod["value"] >= MIN_VALUE].sort_values("value", ascending=False)
    return prod, when.strftime("%Y-%m-%d") if when is not None else None


def tier(v: float) -> int:
    return next(i + 1 for i, lo in enumerate(TIERS) if v >= lo)


def build(season: int, current: int) -> dict:
    weeks, prev = [], None
    inj = players.injuries()
    for wk in range(1, current + 1):
        live = wk == current
        df, ecr_date = values(season, wk, live)
        trend = df["gsis_id"].map(prev) if prev is not None else pd.Series(np.nan, index=df.index)
        df["trend"] = df["value"] - trend
        rows = [[r.gsis_id, r.name, r.position, r.team, float(r.value),
                 None if pd.isna(r.trend) else round(float(r.trend), 1), tier(r.value),
                 round(float(r.est_ppg), 1), int(r.games), None if pd.isna(r.ecr) else int(r.ecr),
                 (inj.get(r.sleeper_id) if live and isinstance(r.sleeper_id, str) else None)]
                for r in df.itertuples()]
        weeks.append({"week": wk, "ecr_date": ecr_date, "rows": rows})
        prev = df.set_index("gsis_id")["value"]
    return {
        "season": season, "current": current, "tiers": TIERS,
        "settings": {"top": TOP, "decay": DECAY, "market_weight": MARKET_WEIGHT},
        "cols": ["id", "name", "pos", "team", "value", "trend", "tier", "ppg", "games", "ecr", "injury"],
        "weeks": weeks,
    }
