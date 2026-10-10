# Football Toolkit

A static site with a handful of football tools. The data rebuilds every day during the season, plus a few extra runs on game nights.

- Breakout Board: players most likely to jump to a startable level the rest of the season, weighted toward cheap ones
- Vegas Rankings: implied team totals from the spread and over/under, and each player's PPR/g scaled by them
- Weather Report: game-time forecasts for outdoor stadiums and what the conditions usually mean
- Trade Value Chart: weekly redraft trade values (12-team, 1QB, PPR) with week-over-week trend
- Upset Watch: three long-shot underdogs a week with the most situational factors in their favor
- Survivor Helper: mark the teams you've used and it plans the next few weeks of picks

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m src.export               # rebuild everything into docs/data
.venv/bin/python -m src.export --tools-only  # skip the breakout model (much faster)
python3 -m http.server -d docs 8000
```

`docs/` is the whole site. `.github/workflows/refresh.yml` runs the export on a schedule and commits the new data.

## How the tools work

Breakout Board. A logistic regression trained on every season since 2014. For each week it only sees what was known going into that week: draft capital, efficiency, last season's production, share of team work, work that's opened up, depth chart, age and experience. A "breakout" means averaging a startable line (QB 17, RB/WR 12, TE 9 PPR/g) and beating your established level by 3 (2.5 for TE) over the rest of the season. Past seasons are scored walk-forward, so a season is never graded by a model that saw it. Preseason AUC averages about 0.81. The board then weights the chance by price (FantasyPros ECR), peaking around rank 150, so it doesn't just list rookies everyone already likes. Thresholds and defaults are in `config/model.yaml`.

Vegas Rankings. Implied total = (total ± spread) / 2. A player's PPR/g (this season blended with last) gets multiplied by his team's implied total over its usual points per game.

Weather Report. Open-Meteo hourly forecasts at each stadium from kickoff through the next few hours. Stadium locations and roof types are in `config/stadiums.yaml`.

Trade Value Chart. Each player gets a market rank (FantasyPros ECR) and a production rank (PPR/g above replacement at his position). Both go through the same decay curve and the value is 60/40 market/production. Past weeks are rebuilt from what was known at the time, which is how trends work without storing anything.

Upset Watch. Only underdogs Vegas gives a 15–42% chance. Each one adds up the situational spots it's in (rest, byes, travel, body clock, wind, cold, totals, blowout bounce-backs and so on), weighted by how underdogs in that spot have done against the closing line since 2007, plus key injuries. The page shows how the picks would have done in past seasons. Short version: a little worse than Vegas expected, down about 7% at flat stakes, so treat them as long shots.

Survivor Helper. Uses moneylines where they're posted and power ratings fitted to this season's spreads for later weeks. The browser picks one team per week over the chosen horizon, no repeats, to maximize the chance of surviving every week (Hungarian algorithm).

## Data

- [nflverse](https://github.com/nflverse/nflverse-data): stats, rosters, depth charts, players
- [nfldata](https://github.com/nflverse/nfldata): schedule, scores, lines
- [DynastyProcess](https://github.com/dynastyprocess/data): FantasyPros ECR history
- [Sleeper](https://docs.sleeper.com): injuries, trending adds
- [ESPN](https://fantasy.espn.com): roster percentages
- [Open-Meteo](https://open-meteo.com): forecasts
