"""Game-time weather for the week's slate, from Open-Meteo (free, no key), and
what it usually means for fantasy. Forecasts reach about 16 days out; the
window is kickoff through the next three hours."""
from __future__ import annotations

import functools

import numpy as np
import pandas as pd
import requests
import yaml

from .. import config
from . import schedule

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = ["temperature_2m", "precipitation_probability", "precipitation", "snowfall",
          "wind_speed_10m", "wind_gusts_10m", "weather_code"]
WINDOW_HOURS = 4
LEVELS = ["Indoors", "No concerns", "Minor", "Worth watching", "Major"]


@functools.lru_cache(maxsize=None)
def stadiums() -> tuple[dict, dict]:
    with open(config.CONFIG_DIR / "stadiums.yaml") as fh:
        rows = yaml.safe_load(fh)
    by_name = {n.lower(): r for r in rows for n in r["names"]}
    by_id = {r["id"]: r for r in rows}
    return by_name, by_id


def locate(stadium: str, stadium_id: str) -> dict | None:
    by_name, by_id = stadiums()
    return by_name.get(str(stadium).lower()) or by_id.get(stadium_id)


@functools.lru_cache(maxsize=None)
def _forecast(lat: float, lon: float) -> pd.DataFrame:
    resp = requests.get(FORECAST_URL, timeout=30, params={
        "latitude": lat, "longitude": lon, "hourly": ",".join(HOURLY),
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch",
        "timezone": "America/New_York", "forecast_days": 16})
    resp.raise_for_status()
    h = resp.json()["hourly"]
    df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize("America/New_York", ambiguous="NaT",
                                                           nonexistent="shift_forward")
    return df.set_index("time")


def conditions(lat: float, lon: float, kickoff: pd.Timestamp) -> dict | None:
    try:
        f = _forecast(lat, lon)
    except Exception:
        return None
    start = kickoff.floor("h")
    w = f.loc[start: start + pd.Timedelta(hours=WINDOW_HOURS - 1)]
    if w.empty or w["temperature_2m"].isna().all():
        return None
    return {
        "temp": round(float(w["temperature_2m"].mean())),
        "wind": round(float(w["wind_speed_10m"].max())),
        "gust": round(float(w["wind_gusts_10m"].max())),
        "precip_prob": int(w["precipitation_probability"].max()) if w["precipitation_probability"].notna().any() else None,
        "precip": round(float(w["precipitation"].sum()), 2),
        "snow": round(float(w["snowfall"].sum()), 1) if w["snowfall"].notna().any() else 0.0,
        "code": int(w["weather_code"].mode().iloc[0]),
    }


def impacts(c: dict) -> list[dict]:
    """Plain-language effects, each with a 1-3 level and the positions it touches."""
    out = []
    wind, gust = c["wind"], c["gust"]
    if wind >= 20 or gust >= 35:
        out.append((3, f"Strong wind ({wind} mph, gusts {gust}). Long field goals and deep passes get much "
                       "harder, and teams tend to lean on the run.", ["K", "QB", "WR"]))
    elif wind >= 15 or gust >= 28:
        out.append((2, f"Breezy ({wind} mph, gusts {gust}). Kickers and deep throws take a hit.", ["K", "QB", "WR"]))
    elif wind >= 11:
        out.append((1, f"Some wind ({wind} mph). Small effect on long kicks.", ["K"]))

    if c["snow"] >= 0.5:
        out.append((3, f"Snow ({c['snow']} in). Footing and visibility drop, scoring usually falls, "
                       "and kickers struggle.", ["K", "QB", "WR", "TE"]))
    elif c["snow"] > 0:
        out.append((2, "Light snow possible. Slick footing and a harder ball to grip.", ["K", "QB", "WR"]))
    elif c["precip"] >= 0.5:
        out.append((3, f"Heavy rain ({c['precip']} in). Expect more drops and fumbles and fewer deep passes.",
                    ["QB", "WR", "TE", "K"]))
    elif c["precip"] >= 0.1 and (c["precip_prob"] or 0) >= 50:
        out.append((2, f"Rain likely ({c['precip_prob']}%). A wet ball means a few more drops and fumbles; "
                       "passing usually dips a little.", ["QB", "WR", "TE"]))
    elif (c["precip_prob"] or 0) >= 40:
        out.append((1, f"Chance of showers ({c['precip_prob']}%).", []))

    if c["temp"] <= 20:
        out.append((2, f"Bitter cold ({c['temp']}°F). Harder to throw, catch and kick.", ["K", "QB", "WR"]))
    elif c["temp"] <= 32:
        out.append((1, f"Cold ({c['temp']}°F). Kicks travel a little shorter.", ["K"]))
    elif c["temp"] >= 88:
        out.append((1, f"Hot ({c['temp']}°F). More rotation and late-game fatigue.", []))
    return [{"level": lv, "text": t, "who": who} for lv, t, who in out]


def build(season: int, week: int) -> dict:
    now = pd.Timestamp.now(tz="America/New_York")
    games = []
    for g in schedule.slate(season, week).itertuples():
        st = locate(g.stadium, g.stadium_id)
        row = {"id": g.game_id, "kickoff": g.kickoff.isoformat(), "away": g.away_team, "home": g.home_team,
               "stadium": g.stadium, "roof": st["roof"] if st else None, "final": bool(g.final),
               "conditions": None, "impacts": [], "level": None, "note": None}
        if st is None:
            row["note"] = "Stadium location unknown."
        elif st["roof"] == "dome":
            row["note"] = "Indoors. Weather doesn't matter."
            row["level"] = 0
        elif g.final or g.kickoff < now - pd.Timedelta(hours=4):
            row["note"] = "Game played."
        else:
            c = conditions(st["lat"], st["lon"], g.kickoff)
            if c is None:
                row["note"] = "Forecast not out yet."
            else:
                imp = impacts(c)
                lvl = max([i["level"] for i in imp], default=0)
                if st["roof"] == "retractable" and lvl >= 1:
                    row["note"] = "Retractable roof. It's usually closed when conditions are bad, which cancels these."
                    lvl = min(lvl, 1)
                row.update(conditions=c, impacts=imp, level=lvl + 1)
        games.append(row)
    games.sort(key=lambda r: (-(r["level"] if r["level"] is not None else -1), r["kickoff"]))
    return {"season": season, "week": week, "levels": LEVELS, "games": games}
