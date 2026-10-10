# Fantasy Football Breakout Board

Live at **[jonginevro.com/breakout-board](https://jonginevro.com/breakout-board/)**.

Ranks NFL skill players by their **chance to break out over the rest of the season**, meaning a jump to a startable level well above where they are now. Established stars are left off. The board always reflects the current week. The History page shows each season's *preseason* board since 2020, scored the way it would have looked that August, next to how every call turned out. How it works walks a real player through the model step by step.

## What counts as a breakout

From the week a board is made through the end of that season, a player has to average a startable PPR line (QB 17, RB/WR 12, TE 9) *and* beat his established level by 3 PPR/g (2.5 for TE). "Established level" blends this season's per-game with last season's. A healthy season two years back counts too, so injury bounce-backs aren't breakouts. Thresholds live in `config/model.yaml`.

## The model

`snapshot(season, week)` builds the league as it looked going into a given week (week 1 = preseason). It uses only what was known then:

| Factor | Features |
|---|---|
| Talent | draft capital, points per touch vs. position, last season's PPR/g |
| Role | share of team workload, workload that's opened up (departures, cuts, IR), depth chart that week, new team, usage trend over the last 2 games |
| Age & experience | rookie / year 2 / year 3, age vs. position peak |
| Starting level | how high his current per-game already is |

A logistic regression turns those into a probability. Its log-odds split exactly into the four factor groups. That split powers the sliders on the site, which re-weight a group and re-grade every past preseason board in the browser.

## Value: why the board leans niche

Chance alone favors high-profile rookies everyone already expects to pop. The board ranks by

```
score = 100 * chance * (floor + (1 - floor) * sweet_spot(ECR))
```

`sweet_spot` peaks at FantasyPros overall rank 150 (cheap but on the radar) and fades for stars and for players nobody ranks. Historical ECR snapshots (via DynastyProcess, 2020 →) price each past preseason board with that August's rankings, so the value layer is backtested too. The defaults, chosen on those same seasons (so slightly optimistic), kept about 6 breakouts per preseason top 20 while the typical pick's ECR moved from ~95 to ~137. Value emphasis and the sweet spot are sliders on the site.

## Honest grading

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

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m src.export          # writes docs/data/*.json
python3 -m http.server -d docs 8000     # open http://localhost:8000
```

`python -m src.model.train` prints the full walk-forward report and the learned weights.

## Deployment

`docs/` is a static site. The **Refresh board data** workflow rebuilds `docs/data` daily during the season (weekly in the offseason) and commits it. The [portfolio](https://github.com/jonginevro/portfolio) deploy copies `docs/` to `jonginevro.com/breakout-board/`.

## Tuning

- `config/model.yaml`: breakout thresholds, value sweet-spot defaults, regularization, snapshot weeks, which features belong to which factor group.
- `config/manual_catalysts.yaml`: human-judgment nudges (new coaching staff, camp buzz) for the live board.
