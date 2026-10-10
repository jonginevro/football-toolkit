# Football Toolkit

Football tools that rebuild themselves from fresh data every day (and after every game during the season): fantasy help, Vegas odds, weather, upset long shots and survivor picks. The site name lives in one constant, `BRAND` in `docs/assets/common.js`.

| Page | What it does |
|---|---|
| **Breakout Board** | Ranks skill players by their chance to jump to a startable level over the rest of the season, weighted by how cheap they are. History shows each preseason board since 2020 next to what every player actually scored. |
| **Vegas Rankings** | Turns each game's spread and total into implied team totals, then scales every player's PPR/g by how that compares with what his team usually scores. |
| **Weather Report** | Kickoff-window forecasts for every outdoor game and what wind, rain, snow or cold usually does to kickers, passing and the run. Domes are marked; retractable roofs are noted. |
| **Trade Value Chart** | A week-by-week redraft trade value chart (12-team, 1QB, PPR) with tiers and week-over-week trend. |
| **Survivor Helper** | Mark the teams you've used and set skip rules (division, Thursday, road, international); it plans the next few weeks at once so this week's pick doesn't burn a team you'll need later. |
| **Upset Watch** | Three long shots a week with the most situational signals pointing their way (rest, travel, weather, blowouts, injuries), plus an honest replay of how the method has done since 2014. |

## Vegas

Lines come from the nflverse schedule (`nfldata/games.csv`), which carries the spread, total and moneylines for each game. With `spread > 0` meaning the home team is favored:

```
implied (home) = (total + spread) / 2
implied (away) = (total - spread) / 2
vegas PPR      = PPR/g × implied / team's usual points
```

A team's usual points blend its games so far with the league average (like 3 games of it). PPR/g blends this season with last season (like 4 games of it). Players listed Out or on IR are dropped. Code: `src/tools/vegas.py`.

## Weather

[Open-Meteo](https://open-meteo.com) hourly forecasts (free, no key) at each stadium for kickoff through the next three hours: temperature, wind, gusts, rain chance and amount, snow. Stadium coordinates and roof types are in `config/stadiums.yaml`, matched on stadium name first because the schedule sometimes files international games under the home team's stadium id. Thresholds for each note are in `src/tools/weather.py`.

## Trade values

Each week every player gets a **market** rank (FantasyPros overall ECR from the snapshot published before that week) and a **production** rank (PPR/g above a replacement-level starter: QB12, RB30, WR36, TE12). Both go through `80 × e^(−(rank − 1) / 50)` and the value is 60% market, 40% production, rounded to the half point. Players below 1.5 aren't relevant in redraft and are left off.

Every past week is rebuilt from what was known then, so the trend (this week minus last) needs no saved state. The current week also counts games already played. Code: `src/tools/trade.py`.

## Survivor Helper

Win chances come from the moneylines where they're posted (usually this week and next). Later weeks use power ratings fitted by weighted least squares to every spread posted this season (last season's count 30%), with a fitted home edge, turned into a win chance with a normal curve (13.5-point margin spread). The browser then solves an assignment problem with the Hungarian algorithm: one team per week over the chosen horizon, no repeats, skip rules applied, maximizing the chance of winning every week. Each option this week is scored by locking it in and re-planning the rest. Used teams and settings are saved in the browser. Code: `src/tools/survivor.py`, `docs/survivor/survivor.js`.

## Upset Watch

Long shots, not coin flips: only underdogs Vegas gives a 15–42% chance are considered. Each gets an upset score, the sum of every situational spot it's in (rest edges, short weeks, byes, division games, neutral sites, body clock, long trips, wind, cold, high/low totals, point differential, letdown and bounce-back spots, night games). Each spot is weighted by how much underdogs in it have beaten Vegas's expectation since 2007, shrunk toward zero for small samples (`gap × games / (games + 400)`). Injury news adds fixed weights (favorite's QB out +5, another key starter +1; reversed for the underdog). The three long shots with the highest score above zero are the picks.

The page publishes the method's track record, replayed season by season with weights learned only from earlier seasons: 2014–2025 picks won 168 of 556 against 174 expected, and $100 on each would be down $4,062, about the bookmaker's cut. The market prices most of this, so these are interesting long shots, not an edge. Code: `src/tools/upsets.py`.

## Breakouts

### What counts as a breakout

From the week a board is made through the end of that season, a player has to average a startable PPR line (QB 17, RB/WR 12, TE 9) *and* beat his established level by 3 PPR/g (2.5 for TE). "Established level" blends this season's per-game with last season's. A healthy season two years back counts too, so injury bounce-backs aren't breakouts. Thresholds live in `config/model.yaml`.

### The model

`snapshot(season, week)` builds the league as it looked going into a given week (week 1 = preseason). It uses only what was known then:

| Factor | Features |
|---|---|
| Talent | draft capital, points per touch vs. position, last season's PPR/g |
| Role | share of team workload, workload that's opened up (departures, cuts, IR), depth chart that week, new team, usage trend over the last 2 games |
| Age & experience | rookie / year 2 / year 3, age vs. position peak |
| Starting level | how high his current per-game already is |

A logistic regression turns those into a probability. Its log-odds split exactly into the four factor groups. That split powers the sliders on the site, which re-weight a group and re-grade every past preseason board in the browser.

### Value: why the board leans niche

Chance alone favors high-profile rookies everyone already expects to pop. The board ranks by

```
score = 100 * chance * (floor + (1 - floor) * sweet_spot(ECR))
```

`sweet_spot` peaks at FantasyPros overall rank 150 (cheap but on the radar) and fades for stars and for players nobody ranks. Historical ECR snapshots (via DynastyProcess, 2020 →) price each past preseason board with that August's rankings, so the value layer is backtested too. The defaults, chosen on those same seasons (so slightly optimistic), kept about 6 breakouts per preseason top 20 while the typical pick's ECR moved from ~95 to ~137. Value emphasis and the sweet spot are sliders on the site.

### Honest grading

Each past season is scored **walk-forward** by a model trained only on earlier seasons. The depth chart is the one published that week, never the end-of-season one. Average over 2017–2025 (the site's History page shows the preseason boards from 2020 on):

| Board made | AUC | Draft pick alone | Breakouts in top 20 | Random top 20 |
|---|---|---|---|---|
| Preseason | 0.81 | 0.76 | 6.0 | 1.2 |
| Week 4 | 0.84 | 0.71 | 5.3 | 1.0 |
| Week 7 | 0.82 | 0.68 | 4.1 | 1.0 |
| Week 10 | 0.81 | 0.69 | 5.9 | 1.2 |

ESPN roster % (and its 7-day change) and Sleeper waiver adds are shown for context but kept out of the score. They have no history to backtest against. Roster % comes from ESPN because it covers every player; Sleeper's trending endpoint only ever returns its top 100.

## Data

- [nflverse](https://github.com/nflverse/nflverse-data): weekly stats, weekly rosters, depth charts, player bios/draft (2013 →)
- [ESPN fantasy API](https://fantasy.espn.com): roster % and 7-day change, for every player
- [DynastyProcess](https://github.com/dynastyprocess/data): historical + current FantasyPros ECR, id crosswalk
- [Sleeper API](https://docs.sleeper.com): market rank, injury tag, trending adds (top 100 only)
- [nfldata](https://github.com/nflverse/nfldata): schedule, scores, spreads, totals, moneylines, roof and stadium
- [Open-Meteo](https://open-meteo.com): hourly game-time forecasts

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m src.export          # writes docs/data/*.json
python3 -m http.server -d docs 8000     # open http://localhost:8000
.venv/bin/python -m src.export --tools-only   # just Vegas, weather and trade values (fast)
```

`python -m src.model.train` prints the full walk-forward report and the learned weights.

## Deployment

`docs/` is a static site: a home page plus `breakouts/`, `vegas/`, `weather/`, `trade/`, `upsets/` and `survivor/`, all sharing `assets/site.css` and `assets/common.js`. The **Refresh site data** workflow rebuilds `docs/data` daily during the season (weekly in the offseason) and commits it. On game nights it also runs `--tools-only` so Vegas, weather, trade values, upsets and survivor odds update after every game. The [portfolio](https://github.com/jonginevro/portfolio) deploy copies `docs/` to `jonginevro.com/breakout-board/`.

## Tuning

- `config/model.yaml`: breakout thresholds, value sweet-spot defaults, regularization, snapshot weeks, which features belong to which factor group.
- `config/manual_catalysts.yaml`: human-judgment nudges (new coaching staff, camp buzz) for the live board.
- `config/stadiums.yaml`: stadium coordinates and roof types for the weather page.
- `src/tools/trade.py`: trade value curve, market/production weighting and tier cut-offs.
