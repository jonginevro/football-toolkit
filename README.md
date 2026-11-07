# Football Toolkit

A static site with a handful of football tools. The data rebuilds every day during the season.

- Breakout Board: players most likely to jump to a startable level the rest of the season, weighted toward cheap ones
- Vegas Rankings: implied team totals from the spread and over/under, and each player's PPR/g scaled by them
- Weather Report: game-time forecasts for outdoor stadiums and what the conditions usually mean
- Trade Value Chart: weekly redraft trade values (12-team, 1QB, PPR) with week-over-week trend
- Upset Watch: three long-shot underdogs a week with the most situational factors in their favor
- Survivor Helper: mark the teams you've used and it plans the next few weeks of picks

## Running The App

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m src.export               # rebuild everything into docs/data
.venv/bin/python -m src.export --tools-only  # skip the breakout model (faster)
python3 -m http.server -d docs 8000
```

## Data

- [nflverse](https://github.com/nflverse/nflverse-data)
- [nfldata](https://github.com/nflverse/nfldata)
- [DynastyProcess](https://github.com/dynastyprocess/data)
- [Sleeper](https://docs.sleeper.com)
- [ESPN](https://fantasy.espn.com)
- [Open-Meteo](https://open-meteo.com)
