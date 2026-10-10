"""Build the model's view of the league AS OF a given week.

`snapshot(season, week)` returns one row per rostered skill player carrying
only what was knowable going into `week` (week 1 = preseason): last season's
production, this season's usage through week-1, the depth chart and roster at
that moment, and bio/draft facts. If the rest of that season has been played it
also carries the outcome, so the same function feeds training, the backtest and
the live board — there is no separate "historical" code path to drift."""
from __future__ import annotations

import functools

import numpy as np
import pandas as pd

from .. import config
from ..data import depth, nflverse

# Age where each position's production typically peaks.
PEAK_AGE = {"QB": 27, "RB": 24, "WR": 25, "TE": 26}
ACTIVE = {"ACT", "INA"}


def thresholds() -> tuple[dict, dict]:
    b = config.model_config()["breakout"]
    return b["startable_ppg"], b["min_jump_ppg"]


# --------------------------------------------------------------------------- #
#  Cached per-season inputs                                                    #
# --------------------------------------------------------------------------- #
def _opp_units(df: pd.DataFrame) -> pd.Series:
    """The workload a breakout captures more of. RB: carries+catches,
    WR/TE: targets, QB: dropbacks proxy (attempts + carries)."""
    c, r = df["carries"].fillna(0), df["receptions"].fillna(0)
    t, a = df["targets"].fillna(0), df["attempts"].fillna(0)
    return np.select([df["position"] == "RB", df["position"].isin(["WR", "TE"])],
                     [c + r, t], default=a + c)


@functools.lru_cache(maxsize=None)
def season_stats(season: int) -> pd.DataFrame:
    s = nflverse.weekly_stats(season)
    s = s[s["position"].isin(config.SKILL_POSITIONS)].copy()
    s["opp"] = _opp_units(s)
    s["ppr"] = s["fantasy_points_ppr"].fillna(0)
    return s[["player_id", "player_display_name", "position", "season", "week",
              "team", "opp", "ppr"]]


@functools.lru_cache(maxsize=None)
def _players() -> pd.DataFrame:
    return nflverse.players().drop_duplicates("gsis_id").set_index("gsis_id")


def last_stats_week(season: int) -> int:
    s = season_stats(season)
    return int(s["week"].max()) if len(s) else 0


def _usage(s: pd.DataFrame) -> pd.DataFrame:
    """Per (player, team) usage over a block of weeks: games, points, workload,
    and his share of that team's positional workload in the weeks he was there."""
    if s.empty:
        return pd.DataFrame(columns=["player_id", "team", "games", "ppr", "opp", "share"])
    team_wk = s.groupby(["team", "position", "week"])["opp"].sum().rename("team_opp")
    s = s.join(team_wk, on=["team", "position", "week"])
    g = s.groupby(["player_id", "team"]).agg(
        games=("week", "nunique"), ppr=("ppr", "sum"), opp=("opp", "sum"),
        team_opp=("team_opp", "sum")).reset_index()
    g["share"] = g["opp"] / g["team_opp"].clip(lower=1)
    return g


def _team_blocks(s: pd.DataFrame) -> pd.DataFrame:
    """For every (team, position), each player's share of that team's workload
    over the whole block — including weeks he didn't play (injuries count)."""
    if s.empty:
        return pd.DataFrame(columns=["team", "position", "player_id", "pool_share"])
    team_tot = s.groupby(["team", "position"])["opp"].sum().rename("tot")
    p = s.groupby(["team", "position", "player_id"])["opp"].sum().rename("o").reset_index()
    p = p.join(team_tot, on=["team", "position"])
    p["pool_share"] = p["o"] / p["tot"].clip(lower=1)
    return p[["team", "position", "player_id", "pool_share"]]


# --------------------------------------------------------------------------- #
#  The snapshot                                                                #
# --------------------------------------------------------------------------- #
def snapshot(season: int, week: int) -> pd.DataFrame:
    prior = season_stats(season - 1)
    cur = season_stats(season)
    ytd = cur[cur["week"] < week]
    ros = cur[cur["week"] >= week]

    # ---- universe: active on a roster going into `week` -----------------------
    ros_raw = nflverse.weekly_roster(season)
    ros_raw = ros_raw[ros_raw["position"].isin(config.SKILL_POSITIONS)]
    if ros_raw.empty:
        return pd.DataFrame()
    wk_avail = sorted(ros_raw["week"].unique())
    rw = max([w for w in wk_avail if w <= week] or [wk_avail[0]])
    roster = ros_raw[ros_raw["week"] == rw].dropna(subset=["gsis_id"])
    roster = roster.drop_duplicates("gsis_id", keep="last")
    active = roster[roster["status"].isin(ACTIVE)]
    df = active[["gsis_id", "full_name", "position", "team", "sleeper_id", "espn_id",
                 "birth_date", "rookie_year", "entry_year", "draft_number",
                 "headshot_url"]].rename(columns={"full_name": "name"}).copy()
    on_team = set(zip(active["gsis_id"], active["team"]))

    # ---- last season ----------------------------------------------------------
    pu = _usage(prior)
    p_tot = pu.groupby("player_id").agg(prior_games=("games", "sum"), prior_ppr=("ppr", "sum"),
                                        prior_opp=("opp", "sum"))
    # primary team = most games; share measured with that team
    p_main = pu.sort_values("games").groupby("player_id").last()
    p_tot["prior_team"] = p_main["team"]
    p_tot["prior_share"] = p_main["share"]
    df = df.join(p_tot, on="gsis_id")

    # ---- this season to date -------------------------------------------------
    yu = _usage(ytd)
    y_tot = yu.groupby("player_id").agg(ytd_games=("games", "sum"), ytd_ppr=("ppr", "sum"),
                                        ytd_opp=("opp", "sum"))
    df = df.join(y_tot, on="gsis_id")
    yu_cur = yu.set_index(["player_id", "team"])["share"]
    df["ytd_share"] = pd.Series(list(zip(df["gsis_id"], df["team"]))).map(yu_cur).values

    # recent role: share over his team's last two games
    if not ytd.empty:
        team_last = ytd.groupby("team")["week"].apply(lambda w: set(sorted(w.unique())[-2:]))
        rec = ytd[[wk in team_last.get(t, ()) for t, wk in zip(ytd["team"], ytd["week"])]]
        ru = _usage(rec).set_index(["player_id", "team"])["opp"]
        rtot = rec.groupby(["team", "position"])["opp"].sum()
        key = list(zip(df["gsis_id"], df["team"]))
        df["recent_opp"] = pd.Series(key).map(ru).values
        df["recent_tot"] = [rtot.get((t, p), np.nan) for t, p in zip(df["team"], df["position"])]
        df["recent_share"] = df["recent_opp"].fillna(0) / df["recent_tot"].clip(lower=1)
        df.loc[df["recent_tot"].isna(), "recent_share"] = np.nan
    else:
        df["recent_share"] = np.nan

    num = ["prior_games", "prior_ppr", "prior_opp", "prior_share", "ytd_games",
           "ytd_ppr", "ytd_opp", "ytd_share"]
    df[num] = df[num].astype(float).fillna(0)

    # ---- open opportunity on his team ---------------------------------------
    # Workload from last season (and this season so far) that belonged to
    # players NOT active on this team now: departures, injuries, cuts, trades.
    in_season_w = min(1.0, (week - 1) / 6)  # how much to trust YTD over last year
    pool = []
    for block, wgt in ((prior, 1 - in_season_w), (ytd, in_season_w)):
        if wgt > 0 and not block.empty:
            b = _team_blocks(block)
            b["w"] = wgt
            pool.append(b)
    if pool:
        pool = pd.concat(pool)
        pool["gone"] = [(pid, t) not in on_team for pid, t in zip(pool["player_id"], pool["team"])]
        pool["v"] = pool["pool_share"] * pool["w"] * pool["gone"]
        open_opp = pool.groupby(["team", "position"])["v"].sum()
        df["open_opp"] = [open_opp.get((t, p), 0.0) for t, p in zip(df["team"], df["position"])]
    else:
        df["open_opp"] = 0.0
    df["open_opp"] = df["open_opp"].clip(0, 1)

    # blended personal share (how much of the pie he already eats)
    df["own_share"] = ((1 - in_season_w) * df["prior_share"] * (df["prior_team"] == df["team"])
                       + in_season_w * df["ytd_share"])
    if week > 1:
        df["recent_delta"] = (df["recent_share"] - df["ytd_share"]).fillna(0)
    else:
        df["recent_delta"] = 0.0

    # ---- depth chart ---------------------------------------------------------
    dep = depth.depth_asof(season, week).set_index("gsis_id")["depth_tier"]
    df["depth_tier"] = df["gsis_id"].map(dep)

    # ---- bio + draft capital --------------------------------------------------
    pl = _players()
    bd = pd.to_datetime(df["birth_date"], errors="coerce").fillna(
        pd.to_datetime(df["gsis_id"].map(pl["birth_date"]), errors="coerce"))
    asof = depth.week_start(season, week).tz_localize(None)
    df["age"] = (asof - bd).dt.days / 365.25
    rookie = pd.to_numeric(df["gsis_id"].map(pl["rookie_season"]), errors="coerce")
    rookie = rookie.fillna(pd.to_numeric(df["rookie_year"], errors="coerce"))
    rookie = rookie.fillna(pd.to_numeric(df["entry_year"], errors="coerce")).fillna(season)
    df["exp"] = (season - rookie).clip(lower=0)
    pick = pd.to_numeric(df["gsis_id"].map(pl["draft_pick"]), errors="coerce")
    df["draft_pick"] = pick.fillna(pd.to_numeric(df["draft_number"], errors="coerce"))
    df["age"] = df["age"].fillna(21.5 + df["exp"])  # rookies w/o birth date
    df["headshot"] = df["headshot_url"].fillna(df["gsis_id"].map(pl["headshot"]))

    # ---- established level (the bar a breakout must clear) -------------------
    prior_ppg = df["prior_ppr"] / df["prior_games"].clip(lower=1)
    ytd_ppg = df["ytd_ppr"] / df["ytd_games"].clip(lower=1)
    k = np.where(df["prior_games"] > 0, 4.0, 0.0)
    df["prior_ppg"] = prior_ppg
    df["ytd_ppg"] = ytd_ppg
    blend = np.where(df["ytd_games"] + k > 0,
                     (df["ytd_ppr"] + k * prior_ppg) / (df["ytd_games"] + k), 0.0)
    # A healthy season two years back counts too, so a star returning from an
    # injury-wrecked year is a bounce-back, not a breakout.
    two = _usage(season_stats(season - 2)).groupby("player_id")[["games", "ppr"]].sum()
    two = two[two["games"] >= 6]
    two_ppg = df["gsis_id"].map(two["ppr"] / two["games"])
    df["baseline_ppg"] = np.fmax(blend, two_ppg.fillna(-99).to_numpy())

    # efficiency: points per unit of workload, shrunk toward the position norm
    both = pd.concat([prior, ytd])
    rates = both.groupby(["player_id", "position"])[["ppr", "opp"]].sum().reset_index()
    rates = rates[rates["opp"] >= 40]
    norm = (rates["ppr"].groupby(rates["position"]).sum()
            / rates["opp"].groupby(rates["position"]).sum())
    m = df["position"].map(norm)
    K = 40.0
    tot_ppr, tot_opp = df["prior_ppr"] + df["ytd_ppr"], df["prior_opp"] + df["ytd_opp"]
    df["eff_rel"] = ((tot_ppr + K * m) / (tot_opp + K)) / m

    start, jump = thresholds()
    mult = config.model_config()["breakout"].get("established_mult", 1.25)
    df["eligible"] = df["baseline_ppg"] < df["position"].map(start) * mult

    df["new_team"] = ((df["prior_games"] > 0) & (df["prior_team"] != df["team"])).astype(float)
    df["season"], df["week"] = season, week

    # ---- outcome (when the rest of the season is in the books) ---------------
    if not ros.empty:
        o = ros.groupby("player_id").agg(ros_games=("week", "nunique"), ros_ppr=("ppr", "sum"))
        df = df.join(o, on="gsis_id")
        df[["ros_games", "ros_ppr"]] = df[["ros_games", "ros_ppr"]].fillna(0)
        df["ros_ppg"] = df["ros_ppr"] / df["ros_games"].clip(lower=1)
        last_wk = int(cur["week"].max())
        min_g = 5 if week == 1 else max(2, (last_wk - week + 1) // 3)
        st_, jp = df["position"].map(start), df["position"].map(jump)
        df["breakout"] = ((df["ros_games"] >= min_g) & (df["ros_ppg"] >= st_)
                          & (df["ros_ppg"] - df["baseline_ppg"] >= jp)).astype(int)
        df["startable"] = ((df["ros_games"] >= min_g) & (df["ros_ppg"] >= st_)).astype(int)
        df["complete"] = last_wk >= 17
    nxt = season_stats(season + 1) if season + 1 <= config.CURRENT_SEASON else pd.DataFrame()
    if len(nxt) and nxt["week"].max() >= 17:
        n = nxt.groupby("player_id").agg(next_games=("week", "nunique"), next_ppr=("ppr", "sum"))
        df = df.join(n, on="gsis_id")
        df["next_ppg"] = df["next_ppr"] / df["next_games"].clip(lower=1)

    return df.reset_index(drop=True)
