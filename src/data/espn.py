"""ESPN fantasy ownership: the share of ESPN leagues rostering each player and
how much that moved over the last 7 days. Unlike Sleeper's trending feed (top
100 only) this covers every fantasy-relevant player, so a 0.0 change is a real
"nobody's moving on him". Public endpoint, no auth; keyed by ESPN player id,
which nflverse rosters carry as `espn_id`."""
from __future__ import annotations

import json
import time

import pandas as pd
import requests

from .. import config

_FILTER = {"players": {"limit": 3000, "sortPercOwned": {"sortAsc": False, "sortPriority": 1}}}


def ownership(season: int, max_age_hours: float = 3, force: bool = False) -> pd.DataFrame:
    path = config.CACHE_DIR / f"espn_ownership_{season}.json"
    fresh = path.exists() and (time.time() - path.stat().st_mtime) / 3600 < max_age_hours
    raw = None
    if fresh and not force:
        raw = json.loads(path.read_text())
    else:
        try:
            resp = requests.get(config.ESPN_PLAYERS_URL.format(season=season), timeout=60,
                                headers={"X-Fantasy-Filter": json.dumps(_FILTER),
                                         "X-Fantasy-Platform": "kona-PROD"})
            resp.raise_for_status()
            raw = resp.json()
            path.write_text(json.dumps(raw))
        except Exception:
            if path.exists():
                raw = json.loads(path.read_text())
    rows = []
    for p in (raw or {}).get("players", []):
        pl = p.get("player") or {}
        own = pl.get("ownership") or {}
        if "percentOwned" not in own:
            continue
        rows.append({"espn_id": str(pl.get("id")),
                     "rostered_pct": own.get("percentOwned"),
                     "rostered_chg": own.get("percentChange")})
    return pd.DataFrame(rows, columns=["espn_id", "rostered_pct", "rostered_chg"])
