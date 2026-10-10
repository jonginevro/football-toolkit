"""Fantasy market price: FantasyPros expert consensus rank (ECR), overall
redraft, via DynastyProcess's archive of weekly snapshots (2020 →). Having the
history is what lets the value "sweet spot" be backtested: a past preseason
board is priced with the rankings published that August, and the live board
with the latest snapshot (in-season these are rest-of-season rankings)."""
from __future__ import annotations

import functools
import time

import numpy as np
import pandas as pd

from . import nflverse

DP = "https://github.com/dynastyprocess/data/raw/master/files"
UNRANKED = 400.0  # off every expert's list: priced like waiver-wire dust


@functools.lru_cache(maxsize=None)
def _ecr() -> pd.DataFrame:
    cols = ["page_type", "id", "ecr", "scrape_date"]
    e = nflverse._load("db_fpecr", f"{DP}/db_fpecr.parquet", 24 * 3, columns=cols)
    e = e[e["page_type"] == "redraft-overall"].copy()
    e["scrape_date"] = pd.to_datetime(e["scrape_date"])
    e["id"] = e["id"].astype(str)
    return e[["id", "ecr", "scrape_date"]]


@functools.lru_cache(maxsize=None)
def _fp_to_gsis() -> pd.Series:
    """FantasyPros id -> gsis_id (DynastyProcess's id crosswalk, a CSV)."""
    path = nflverse.config.CACHE_DIR / "db_playerids.parquet"
    stale = not path.exists() or (time.time() - path.stat().st_mtime) / 3600 > 24 * 3
    if stale:
        try:
            pd.read_csv(f"{DP}/db_playerids.csv", usecols=["fantasypros_id", "gsis_id"]).to_parquet(path)
        except Exception:
            if not path.exists():
                raise
    ids = pd.read_parquet(path).dropna()
    ids["fantasypros_id"] = ids["fantasypros_id"].astype(int).astype(str)
    return ids.drop_duplicates("fantasypros_id").set_index("fantasypros_id")["gsis_id"]


def ecr_asof(cutoff: pd.Timestamp) -> tuple[pd.Series, pd.Timestamp | None]:
    """gsis_id -> overall ECR from the last snapshot on or before `cutoff`,
    re-ranked 1..N so ties and gaps don't matter."""
    e = _ecr()
    cutoff = cutoff.tz_localize(None) if cutoff.tzinfo else cutoff
    e = e[e["scrape_date"] <= cutoff]
    if e.empty:
        return pd.Series(dtype=float), None
    when = e["scrape_date"].max()
    snap = e[e["scrape_date"] == when].copy()
    snap["gsis_id"] = snap["id"].map(_fp_to_gsis())
    snap = snap.dropna(subset=["gsis_id"]).sort_values("ecr").drop_duplicates("gsis_id")
    snap["rank"] = np.arange(1, len(snap) + 1, dtype=float)
    return snap.set_index("gsis_id")["rank"], when
