"""Sleeper API: market popularity (search_rank) and live waiver-wire adds.
Free, no auth. Neither has history, so both are shown on the board but kept out
of the model — nothing here could be backtested.

Note on adds: Sleeper's trending endpoint returns at most 100 players no matter
what `limit` you pass, and kickers/defenses take some of those slots. A player
missing from the list is not "0 adds", he is "not in the top 100" — so we keep
that as missing instead of filling a fake zero, and pull two windows (24h and
7 days) so a riser shows up in either."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

from .. import config


def _cache(name: str) -> Path:
    return config.CACHE_DIR / name


def _get_json(url: str, cache_name: str, max_age_hours: float, params=None, force=False):
    path = _cache(cache_name)
    fresh = path.exists() and (time.time() - path.stat().st_mtime) / 3600 < max_age_hours
    if fresh and not force:
        return json.loads(path.read_text())
    try:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        raw = resp.json()
        path.write_text(json.dumps(raw))
        return raw
    except Exception:
        if path.exists():
            return json.loads(path.read_text())
        return None


def players(force: bool = False) -> pd.DataFrame:
    raw = _get_json(config.SLEEPER_PLAYERS_URL, "sleeper_players.json", 12, force=force) or {}
    rows = [{
        "sleeper_id": str(pid),
        "gsis_id": (p.get("gsis_id") or "").strip() or None,
        "sleeper_name": p.get("full_name"),
        "sleeper_pos": p.get("position"),
        "search_rank": p.get("search_rank"),
        "injury_status": p.get("injury_status"),
    } for pid, p in raw.items() if isinstance(p, dict)]
    df = pd.DataFrame(rows)
    if len(df):
        df["search_rank"] = pd.to_numeric(df["search_rank"], errors="coerce")
    return df


def trending(lookback_hours: int, force: bool = False) -> pd.DataFrame:
    """sleeper_id -> adds over the window, for Sleeper's top-100 trending list."""
    raw = _get_json(config.SLEEPER_TRENDING_URL.format(kind="add"),
                    f"sleeper_trending_add_{lookback_hours}h.json", 3,
                    params={"lookback_hours": lookback_hours, "limit": 100}, force=force)
    if not raw:
        return pd.DataFrame(columns=["sleeper_id", "adds"])
    return pd.DataFrame([{"sleeper_id": str(r["player_id"]), "adds": int(r.get("count", 0))}
                         for r in raw])
