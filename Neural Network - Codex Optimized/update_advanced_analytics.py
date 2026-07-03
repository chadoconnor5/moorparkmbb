#!/usr/bin/env python3
"""
Compute advanced analytics from player_stats.json for any team.

Every stat is defined once in STAT_DEFINITIONS. Each definition contains:
  - formula: human-readable formula string
  - compute: a function that takes a player's totals dict and returns the value

All raw stats are pulled from player_stats.json by player name.

Usage:
    python update_advanced_analytics.py --teams Moorpark Ventura
    python update_advanced_analytics.py --all
"""

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path

STATS_DIR = Path("2025-26 Team Statistics")  # may be overridden by --season arg

# ---------------------------------------------------------------------------
# Prior-season blending: treat prior season ORTG/DRTG as virtual games that
# phase out as current-season in-system games accumulate.
#
# The weight is a slow exponential decay w(n) = PRIOR_W0 * exp(-n / PRIOR_TAU)
# in virtual games, where n = current-season in-system games played. Chosen from
# backtest_prior_decay.py (predict-rest-of-season RMSE across 2018-19..2025-26):
# zeroing the prior or hard-cutting it at game 5 overreacts early; this curve sits
# in the optimal basin and still carries ~2-3 prior games at ~game 12 (KenPom's
# "weight at Christmas"). PRIOR_GAMES is retained only for the old constant blend
# / help text; PRIOR_W0+PRIOR_TAU are the active mechanism.
# ---------------------------------------------------------------------------
PRIOR_GAMES = 5    # legacy constant-blend weight (superseded by the decay curve)
PRIOR_W0 = 8.0     # starting virtual-game weight of the prior (n = 0)
PRIOR_TAU = 10.0   # decay time-constant in games


def prior_weight(n_games: int) -> float:
    """Virtual-game weight of the prior after n current-season games."""
    return PRIOR_W0 * math.exp(-n_games / PRIOR_TAU)


# Season prior chain. Each season decays from the one before it, EXCEPT cold
# starts: 2017-18 (no prior season exists) and 2021-22 (the 2020-21 COVID gap
# means 2019-20 must NOT feed 2021-22). update_advanced_analytics auto-derives
# the prior season from --season via this map unless --prior-season is given.
PRIOR_CHAIN = {
    "2018-19": "2017-18",
    "2019-20": "2018-19",
    # "2021-22": cold start — COVID gap, no 2020-21 season
    "2022-23": "2021-22",
    "2023-24": "2022-23",
    "2024-25": "2023-24",
    "2025-26": "2024-25",
}

# ---------------------------------------------------------------------------
# Iterative opponent-adjusted efficiency defaults (KenPom-style)
# ---------------------------------------------------------------------------
HOME_ADVANTAGE = 3.0   # points per 100 possessions (split across O/D by venue)
REGRESSION_GAMES = 10  # prior games at league average for small samples
DAMPEN = 0.5           # blend factor each iteration to prevent oscillation
MAX_ITER = 100
RECENCY_MIN_WEIGHT = 0.90
RECENCY_MAX_WEIGHT = 1.10
IMPORTANCE_BASE = 0.95
IMPORTANCE_MARGIN_BONUS = 0.05
IMPORTANCE_OPP_BONUS = 0.03
IMPORTANCE_SCALE = 25.0

# ---------------------------------------------------------------------------
# In-system opponent resolver — maps variant opponent names to canonical names
# ---------------------------------------------------------------------------
OPPONENT_ALIASES = {
    "CANYONS": "Canyons",
    "CERRITOS": "Cerritos",
    "COD-M": "Desert",
    "CUYAMACA": "Cuyamaca",
    "College of the Canyo": "Canyons",
    "College of the Sequoias": "Sequoias",
    "HARBOR-M": "LA Harbor",
    "Los Angeles Valley": "LA Valley",
    "MIRAMAR": "San Diego Miramar",
    "MSJC-M": "Mt. San Jacinto",
    "Mt. SAC": "Mt. San Antonio",
    "Pasadena": "Pasadena City",
    "Riverside Tigers": "Riverside",
    "SANTAMON": "Santa Monica",
    "VENTURA": "Ventura",
    "Ventura Pirates": "Ventura",
}

_CANONICAL_TEAMS = None  # lazily built set of all in-system team names


def _build_canonical_teams():
    """Build set of all team names from stats directories."""
    global _CANONICAL_TEAMS
    if _CANONICAL_TEAMS is not None:
        return
    _CANONICAL_TEAMS = set()
    for conf_dir in STATS_DIR.iterdir():
        if conf_dir.is_dir():
            for team_dir in conf_dir.iterdir():
                if team_dir.is_dir():
                    _CANONICAL_TEAMS.add(team_dir.name)


def _normalize_team_name(name):
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _match_canonical_team_name(name):
    normalized_name = _normalize_team_name(name)
    for team_name in sorted(_CANONICAL_TEAMS, key=len, reverse=True):
        normalized_team = _normalize_team_name(team_name)
        if (
            normalized_name == normalized_team
            or normalized_name.startswith(normalized_team + " ")
            or normalized_team.endswith(" " + normalized_name)
        ):
            return team_name
    return None


def _resolve_canonical_team_name(opp_name):
    matched = _match_canonical_team_name(opp_name)
    if matched:
        return matched
    alias = OPPONENT_ALIASES.get(opp_name)
    if alias:
        matched = _match_canonical_team_name(alias)
        if matched:
            return matched
        return alias
    return opp_name


def resolve_opponent(opp_name):
    """Return canonical team name if in-system, else None."""
    _build_canonical_teams()
    canonical_name = _resolve_canonical_team_name(opp_name)
    if canonical_name in _CANONICAL_TEAMS:
        return canonical_name
    return None


def find_team_stats(team_name):
    """Find a team's stats directory (searching conference subfolders)."""
    for conf_dir in sorted(STATS_DIR.iterdir()):
        if conf_dir.is_dir():
            candidate = conf_dir / team_name
            if candidate.is_dir():
                return candidate
    return None


def all_stat_teams():
    """Yield team_name for all teams in stats folders."""
    for conf_dir in sorted(STATS_DIR.iterdir()):
        if conf_dir.is_dir():
            for team_dir in sorted(conf_dir.iterdir()):
                if team_dir.is_dir():
                    yield team_dir.name

# ---------------------------------------------------------------------------
# Individual ORtg / DRtg helper functions (Dean Oliver / BBRef formulas)
# ---------------------------------------------------------------------------

def _compute_tot_poss(t: dict, ctx: dict) -> float:
    """Compute individual TotPoss (Dean Oliver) — possessions used by player.

    TotPoss = ScPoss + FGxPoss + FTxPoss + TO
    Used for %Poss (usage) calculation.
    """
    if not ctx or ctx.get("team_min", 0) == 0 or t.get("MIN", 0) == 0:
        return 0.0
    if t.get("FGA", 0) == 0 and t.get("FTA", 0) == 0:
        return 0.0

    team_min  = ctx["team_min"]
    min_frac  = t["MIN"] / team_min

    team_fgm  = ctx["team_fgm"]
    team_fga  = ctx["team_fga"]
    team_fta  = ctx["team_fta"]
    team_ftm  = ctx["team_ftm"]
    team_to   = ctx["team_to"]
    team_oreb = ctx["team_oreb"]
    team_ast  = ctx["team_ast"]
    team_pts  = ctx["team_pts"]
    opp_dreb  = ctx["opp_dreb"]

    if team_fgm == 0:
        return 0.0

    ft_pct      = t["FTM"] / t["FTA"]   if t["FTA"]  > 0 else 0.0
    team_ft_pct = team_ftm / team_fta   if team_fta  > 0 else 0.0

    qast_p1   = min_frac * 1.14 * (team_ast - t["AST"]) / team_fgm
    qast_den2 = team_fgm * min_frac - t["FGM"]
    qast_p2   = ((team_ast * min_frac - t["AST"]) / qast_den2) * (1 - min_frac) if qast_den2 > 0 else 0.0
    qAST      = max(0.0, min(1.0, qast_p1 + qast_p2))

    fg_eff   = (t["PTS"] - t["FTM"]) / (2 * t["FGA"]) if t["FGA"] > 0 else 0.0
    FG_Part  = t["FGM"] * (1 - 0.5 * fg_eff * qAST)

    ast_num  = (team_pts - team_ftm) - (t["PTS"] - t["FTM"])
    ast_den  = 2 * (team_fga - t["FGA"])
    AST_Part = 0.5 * (ast_num / ast_den) * t["AST"] if ast_den > 0 else 0.0

    FT_Part  = (1 - (1 - ft_pct) ** 2) * 0.475 * t["FTA"] if t["FTA"] > 0 else 0.0

    team_orb_pct = team_oreb / (team_oreb + opp_dreb) if (team_oreb + opp_dreb) > 0 else 0.0
    team_sc_poss = team_fgm + (1 - (1 - team_ft_pct) ** 2) * team_fta * 0.475
    if team_sc_poss <= 0:
        return 0.0
    team_play_pct = team_sc_poss / (team_fga + team_fta * 0.475 + team_to) if (team_fga + team_fta * 0.475 + team_to) > 0 else 0.0
    orb_w_num     = (1 - team_orb_pct) * team_play_pct
    orb_w_den     = orb_w_num + team_orb_pct * (1 - team_play_pct)
    team_orb_wt   = orb_w_num / orb_w_den if orb_w_den > 0 else 0.0

    ORB_Part  = t["OREB"] * team_orb_wt * team_play_pct
    sc_factor = 1 - (team_oreb / team_sc_poss) * team_orb_wt * team_play_pct

    ScPoss  = (FG_Part + AST_Part + FT_Part) * sc_factor + ORB_Part
    FGxPoss = (t["FGA"] - t["FGM"]) * (1 - 1.07 * team_orb_pct)
    FTxPoss = ((1 - ft_pct) ** 2) * 0.475 * t["FTA"] if t["FTA"] > 0 else 0.0

    return ScPoss + FGxPoss + FTxPoss + t["TO"]


def _offense_components(t: dict, ctx: dict):
    """Dean Oliver individual offense pieces -> (PProd, ScPoss, TotPoss).

    Returns None when inputs are insufficient. These feed both Individual
    Offensive Rating (100*PProd/TotPoss) and Offensive Win Shares.
    Reference: https://www.basketball-reference.com/about/ratings.html
    """
    if not ctx or ctx.get("team_min", 0) == 0 or t.get("MIN", 0) == 0:
        return None
    if t.get("FGA", 0) == 0 and t.get("FTA", 0) == 0:
        return None

    team_min  = ctx["team_min"]
    min_frac  = t["MIN"] / team_min          # ≈ MP / (TmMP/5) where TmMP = game-clock min × 5

    team_fgm  = ctx["team_fgm"]
    team_fga  = ctx["team_fga"]
    team_fta  = ctx["team_fta"]
    team_ftm  = ctx["team_ftm"]
    team_to   = ctx["team_to"]
    team_oreb = ctx["team_oreb"]
    team_ast  = ctx["team_ast"]
    team_pts  = ctx["team_pts"]
    team_3pm  = ctx["team_3pm"]
    opp_dreb  = ctx["opp_dreb"]

    if team_fgm == 0:
        return None

    ft_pct      = t["FTM"] / t["FTA"] if t["FTA"] > 0 else 0.0
    team_ft_pct = team_ftm / team_fta  if team_fta  > 0 else 0.0

    # qAST — estimated fraction of FGM that were assisted
    qast_p1 = min_frac * 1.14 * (team_ast - t["AST"]) / team_fgm
    qast_den2 = team_fgm * min_frac - t["FGM"]
    if qast_den2 > 0:
        qast_p2 = ((team_ast * min_frac - t["AST"]) / qast_den2) * (1 - min_frac)
    else:
        qast_p2 = 0.0
    qAST = max(0.0, min(1.0, qast_p1 + qast_p2))

    fg_eff = (t["PTS"] - t["FTM"]) / (2 * t["FGA"]) if t["FGA"] > 0 else 0.0

    FG_Part  = t["FGM"] * (1 - 0.5 * fg_eff * qAST)

    ast_num = (team_pts - team_ftm) - (t["PTS"] - t["FTM"])
    ast_den = 2 * (team_fga - t["FGA"])
    AST_Part = 0.5 * (ast_num / ast_den) * t["AST"] if ast_den > 0 else 0.0

    FT_Part  = (1 - (1 - ft_pct) ** 2) * 0.475 * t["FTA"] if t["FTA"] > 0 else 0.0

    # Team-level rebound / scoring possession metrics
    team_orb_pct  = team_oreb / (team_oreb + opp_dreb) if (team_oreb + opp_dreb) > 0 else 0.0
    team_sc_poss  = team_fgm + (1 - (1 - team_ft_pct) ** 2) * team_fta * 0.475
    if team_sc_poss <= 0:
        return None
    team_play_pct = team_sc_poss / (team_fga + team_fta * 0.475 + team_to) if (team_fga + team_fta * 0.475 + team_to) > 0 else 0.0
    orb_w_num     = (1 - team_orb_pct) * team_play_pct
    orb_w_den     = orb_w_num + team_orb_pct * (1 - team_play_pct)
    team_orb_wt   = orb_w_num / orb_w_den if orb_w_den > 0 else 0.0

    ORB_Part  = t["OREB"] * team_orb_wt * team_play_pct
    sc_factor = 1 - (team_oreb / team_sc_poss) * team_orb_wt * team_play_pct

    ScPoss    = (FG_Part + AST_Part + FT_Part) * sc_factor + ORB_Part
    FGxPoss   = (t["FGA"] - t["FGM"]) * (1 - 1.07 * team_orb_pct)
    FTxPoss   = ((1 - ft_pct) ** 2) * 0.475 * t["FTA"] if t["FTA"] > 0 else 0.0
    TotPoss   = ScPoss + FGxPoss + FTxPoss + t["TO"]
    if TotPoss <= 0:
        return None

    # Points produced
    PProd_FG  = 2 * (t["FGM"] + 0.5 * t["3PM"]) * (1 - 0.5 * fg_eff * qAST)
    team_non_fg = team_fgm - t["FGM"]
    if team_non_fg > 0:
        pprod_ast_factor = (team_non_fg + 0.5 * (team_3pm - t["3PM"])) / team_non_fg
    else:
        pprod_ast_factor = 1.0
    PProd_AST = 2 * pprod_ast_factor * (0.5 * (ast_num / ast_den) if ast_den > 0 else 0.0) * t["AST"]

    pprod_orb_den = team_fgm + (1 - (1 - team_ft_pct) ** 2) * 0.475 * team_fta
    PProd_ORB = (
        t["OREB"] * team_orb_wt * team_play_pct * (team_pts / pprod_orb_den)
        if pprod_orb_den > 0 else 0.0
    )
    PProd = (PProd_FG + PProd_AST + t["FTM"]) * sc_factor + PProd_ORB

    return PProd, ScPoss, TotPoss


def _compute_ind_ortg(t: dict, ctx: dict) -> float:
    """Individual Offensive Rating: 100 * PProd / TotPoss (Dean Oliver)."""
    comp = _offense_components(t, ctx)
    if comp is None:
        return 0.0
    pprod, _scposs, tot_poss = comp
    return round(100 * pprod / tot_poss, 1) if tot_poss > 0 else 0.0


def _compute_pprod(t: dict, ctx: dict) -> float:
    """Points Produced (Dean Oliver) — feeds Offensive Win Shares."""
    comp = _offense_components(t, ctx)
    return round(comp[0], 2) if comp else 0.0


def _compute_scposs(t: dict, ctx: dict) -> float:
    """Scoring Possessions (Dean Oliver) — feeds Offensive Win Shares."""
    comp = _offense_components(t, ctx)
    return round(comp[1], 2) if comp else 0.0


def _compute_ind_drtg(t: dict, ctx: dict) -> float:
    """Individual Defensive Rating (Dean Oliver).

    Estimated points allowed by the player per 100 possessions faced.
    Reference: https://www.basketball-reference.com/about/ratings.html
    """
    if not ctx or ctx.get("team_min", 0) == 0 or t.get("MIN", 0) == 0:
        return 0.0

    team_min  = ctx["team_min"]
    team_poss = ctx["team_poss"]
    team_dreb = ctx["team_dreb"]
    team_blk  = ctx["team_blk"]
    team_stl  = ctx["team_stl"]
    team_pf   = ctx["team_pf"]

    opp_fga   = ctx["opp_fga"]
    opp_fgm   = ctx["opp_fgm"]
    opp_fta   = ctx["opp_fta"]
    opp_ftm   = ctx["opp_ftm"]
    opp_oreb  = ctx["opp_oreb"]
    opp_to    = ctx["opp_to"]
    opp_pts   = ctx["opp_pts"]

    if opp_fga == 0 or team_poss == 0:
        return 0.0

    opp_ft_pct = opp_ftm / opp_fta if opp_fta > 0 else 0.0
    dfg_pct    = opp_fgm / opp_fga
    dor_pct    = opp_oreb / (opp_oreb + team_dreb) if (opp_oreb + team_dreb) > 0 else 0.0

    fmwt_num = dfg_pct * (1 - dor_pct)
    fmwt_den = fmwt_num + (1 - dfg_pct) * dor_pct
    fmwt     = fmwt_num / fmwt_den if fmwt_den > 0 else 0.0

    # Stops1: individually tracked defensive stops (blocks, steals, defensive rebounds)
    stops1 = t["STL"] + t["BLK"] * fmwt * (1 - 1.07 * dor_pct) + t["DREB"] * (1 - fmwt)

    # Stops2: team-distributed stops (non-block misses, non-steal TOs, non-shooting fouls)
    # Team_MP = total player-minutes = 5 × game-clock minutes
    rate_miss = ((opp_fga - opp_fgm - team_blk) / (5 * team_min)) * fmwt * (1 - 1.07 * dor_pct)
    rate_to   = (opp_to - team_stl) / (5 * team_min)
    stops2_rate = (rate_miss + rate_to) * t["MIN"]
    stops2_foul = (
        (t["PF"] / team_pf) * 0.475 * opp_fta * (1 - opp_ft_pct) ** 2
        if team_pf > 0 and opp_fta > 0 else 0.0
    )
    stops2 = stops2_rate + stops2_foul

    stops    = stops1 + stops2
    # Stop% = (Stops × Opp_MP) / (Team_Possessions × MP)
    # Opp_MP = 5 × team_min (opponent total player-minutes, same game length)
    stop_pct = (stops * 5 * team_min) / (team_poss * t["MIN"]) if t["MIN"] > 0 else 0.0

    team_drtg_val  = 100 * opp_pts / team_poss
    opp_sc_poss    = opp_fgm + (1 - (1 - opp_ft_pct) ** 2) * opp_fta * 0.475
    d_pts_per_sc   = opp_pts / opp_sc_poss if opp_sc_poss > 0 else 0.0

    drtg = team_drtg_val + 0.2 * (100 * d_pts_per_sc * (1 - stop_pct) - team_drtg_val)
    return round(drtg, 1)


# ---------------------------------------------------------------------------
# Stat definitions — add new metrics here and they auto-propagate everywhere
# ---------------------------------------------------------------------------
STAT_DEFINITIONS = {
    "efg_pct": {
        "name": "Effective FG%",
        "formula": "(FGM + 0.5 * 3PM) / FGA * 100",
        "compute": lambda t, ctx=None: (
            round((t["FGM"] + 0.5 * t["3PM"]) / t["FGA"] * 100, 1)
            if t["FGA"] > 0 else 0.0
        ),
    },
    "tov_pct": {
        "name": "Turnover %",
        "formula": "TO / ((FGA - OREB) + TO + (0.475 * FTA)) * 100",
        "compute": lambda t, ctx=None: (
            round(t["TO"] / ((t["FGA"] - t["OREB"]) + t["TO"] + (0.475 * t["FTA"])) * 100, 1)
            if ((t["FGA"] - t["OREB"]) + t["TO"] + (0.475 * t["FTA"])) > 0 else 0.0
        ),
    },
    "oreb_pct": {
        "name": "Offensive Rebound %",
        "formula": "OREB / ((MIN% / 100) * (Team OREB + Opp DREB))",
        "compute": lambda t, ctx=None: (
            round(
                t["OREB"] / (
                    (t["MIN"] / ctx["team_min"] / 100)
                    * (ctx["team_oreb"] + ctx["opp_dreb"])
                ), 1
            )
            if ctx and ctx.get("team_min", 0) > 0
               and t.get("MIN", 0) > 0
               and (ctx.get("team_oreb", 0) + ctx.get("opp_dreb", 0)) > 0
            else 0.0
        ),
    },
    "ft_rate": {
        "name": "Free Throw Rate",
        "formula": "FTA / FGA * 100",
        "compute": lambda t, ctx=None: (
            round(t["FTA"] / t["FGA"] * 100, 1)
            if t["FGA"] > 0 else 0.0
        ),
    },
    "ts_pct": {
        "name": "True Shooting %",
        "formula": "PTS / (2 * (FGA + 0.475 * FTA)) * 100",
        "compute": lambda t, ctx=None: (
            round(t["PTS"] / (2 * (t["FGA"] + 0.475 * t["FTA"])) * 100, 1)
            if (t["FGA"] + 0.475 * t["FTA"]) > 0 else 0.0
        ),
    },
    "dreb_pct": {
        "name": "Defensive Rebound %",
        "formula": "100 * DREB / ((MIN / team_min / 100) * (team_dreb + opp_oreb))",
        "compute": lambda t, ctx=None: (
            round(
                t["DREB"] / (
                    (t["MIN"] / ctx["team_min"] / 100)
                    * (ctx["team_dreb"] + ctx["opp_oreb"])
                ), 1
            )
            if ctx and ctx.get("team_min", 0) > 0
               and t.get("MIN", 0) > 0
               and (ctx.get("team_dreb", 0) + ctx.get("opp_oreb", 0)) > 0
            else 0.0
        ),
    },
    "usage_pct": {
        "name": "%Poss",
        "formula": "TotPoss / ((MIN / team_min / 100) * team_poss)",
        "compute": lambda t, ctx=None: (
            round(
                _compute_tot_poss(t, ctx) / (
                    (t["MIN"] / ctx["team_min"] / 100)
                    * ctx["team_poss"]
                ), 1
            )
            if ctx and ctx.get("team_min", 0) > 0
               and t.get("MIN", 0) > 0
               and ctx.get("team_poss", 0) > 0
               and _compute_tot_poss(t, ctx) > 0
            else 0.0
        ),
    },
    "shot_pct": {
        "name": "Shot %",
        "formula": "100 * FGA / ((MIN / team_min / 100) * team_fga)",
        "compute": lambda t, ctx=None: (
            round(
                t["FGA"] / (
                    (t["MIN"] / ctx["team_min"] / 100) * ctx["team_fga"]
                ), 1
            )
            if ctx and ctx.get("team_min", 0) > 0
               and t.get("MIN", 0) > 0
               and ctx.get("team_fga", 0) > 0
            else 0.0
        ),
    },
    "ast_rate": {
        "name": "Assist Rate",
        "formula": "100 * AST / ((MIN / team_min * team_fgm) - FGM)",
        "compute": lambda t, ctx=None: (
            round(
                100 * t["AST"] / (
                    (t["MIN"] / ctx["team_min"]) * ctx["team_fgm"] - t["FGM"]
                ), 1
            )
            if ctx and ctx.get("team_min", 0) > 0
               and t.get("MIN", 0) > 0
               and ((t["MIN"] / ctx["team_min"]) * ctx.get("team_fgm", 0) - t.get("FGM", 0)) > 0
            else 0.0
        ),
    },
    "to_rate": {
        "name": "Turnover Rate",
        "formula": "100 * TO / (FGA + 0.475*FTA + TO)",
        "compute": lambda t, ctx=None: (
            round(100 * t["TO"] / (t["FGA"] + 0.475 * t["FTA"] + t["TO"]), 1)
            if (t["FGA"] + 0.475 * t["FTA"] + t["TO"]) > 0 else 0.0
        ),
    },
    "blk_pct": {
        "name": "Block %",
        "formula": "100 * BLK / ((MIN / team_min / 100) * (opp_fga - opp_3pa))",
        "compute": lambda t, ctx=None: (
            round(
                t["BLK"] / (
                    (t["MIN"] / ctx["team_min"] / 100)
                    * (ctx["opp_fga"] - ctx["opp_3pa"])
                ), 1
            )
            if ctx and ctx.get("team_min", 0) > 0
               and t.get("MIN", 0) > 0
               and (ctx.get("opp_fga", 0) - ctx.get("opp_3pa", 0)) > 0
            else 0.0
        ),
    },
    "stl_pct": {
        "name": "Steal %",
        "formula": "100 * STL / ((MIN / team_min / 100) * team_poss)",
        "compute": lambda t, ctx=None: (
            round(
                t["STL"] / (
                    (t["MIN"] / ctx["team_min"] / 100) * ctx["team_poss"]
                ), 1
            )
            if ctx and ctx.get("team_min", 0) > 0
               and t.get("MIN", 0) > 0
               and ctx.get("team_poss", 0) > 0
            else 0.0
        ),
    },
    "fc_per_40": {
        "name": "Fouls Committed per 40",
        "formula": "PF * 40 / MIN",
        "compute": lambda t, ctx=None: (
            round(t["PF"] * 40 / t["MIN"], 1)
            if t.get("MIN", 0) > 0 else 0.0
        ),
    },
    "fd_per_40": {
        "name": "Fouls Drawn per 40 (est.)",
        "formula": "(FTA/1.8 + max(0, opp_pf*0.837 - team_fta/1.8) * (MIN/team_min)) * 40/MIN",
        "compute": lambda t, ctx=None: (
            round(
                (
                    t["FTA"] / 1.8
                    + max(0.0, ctx["opp_pf"] * 0.837 - ctx["team_fta"] / 1.8)
                    * (t["MIN"] / ctx["team_min"])
                ) * 40 / t["MIN"],
                1
            )
            if ctx and ctx.get("team_min", 0) > 0 and t.get("MIN", 0) > 0
            else 0.0
        ),
    },
    "ind_ortg": {
        "name": "Individual Offensive Rating",
        "formula": "Dean Oliver: 100 * PProd / TotPoss (BBRef method)",
        "compute": _compute_ind_ortg,
    },
    "ind_drtg": {
        "name": "Individual Defensive Rating",
        "formula": "Dean Oliver: TmDRtg + 0.2*(100*D_Pts_per_ScPoss*(1-Stop%) - TmDRtg)",
        "compute": _compute_ind_drtg,
    },
    "pprod": {
        "name": "Points Produced",
        "formula": "Dean Oliver Points Produced (feeds Offensive Win Shares)",
        "compute": _compute_pprod,
    },
    "scposs": {
        "name": "Scoring Possessions",
        "formula": "Dean Oliver Scoring Possessions (feeds Offensive Win Shares)",
        "compute": _compute_scposs,
    },
}

# ---------------------------------------------------------------------------
# Team-only stat definitions — these need team_summary.json (PPG, OppPPG, GP)
# Each compute takes (team_totals, summary) where summary is team_summary.json
# ---------------------------------------------------------------------------
TEAM_STAT_DEFINITIONS = {
    "possessions": {
        "name": "Team Possessions",
        "formula": "((FGA - OREB) + TO + (0.475 * FTA)) / GP",
        "compute": lambda t, s: (
            round(((t["FGA"] - t["OREB"]) + t["TO"] + (0.475 * t["FTA"])) / s["games_played"], 1)
            if s.get("games_played", 0) > 0 else 0.0
        ),
    },
    "ortg": {
        "name": "Offensive Rating",
        "formula": "(PPG / Team Possessions) * 100",
        "compute": lambda t, s: None,  # computed after possessions
    },
    "drtg": {
        "name": "Defensive Rating",
        "formula": "(PPG Allowed / Team Possessions) * 100",
        "compute": lambda t, s: None,  # computed after possessions
    },
    "net_rtg": {
        "name": "Net Rating",
        "formula": "ORTG - DRTG",
        "compute": lambda t, s: None,  # computed after ortg/drtg
    },
    "oreb_pct": {
        "name": "Team Offensive Rebound %",
        "formula": "OREB / (OREB + Opp DREB) * 100",
        "compute": lambda t, s: None,  # computed in compute_team_only_analytics
    },
    "ft_rate": {
        "name": "Free Throw Rate",
        "formula": "(FTA per game / FGA per game) * 100",
        "compute": lambda t, s: None,  # computed in compute_team_only_analytics
    },
}

MONTH_ORDER = ["Nov", "Dec", "Jan", "Feb", "Mar"]

def _month_bucket(date_str: str) -> str | None:
    """Return month bucket name from a date string like M/D/YYYY."""
    if not date_str:
        return None
    try:
        m = int(date_str.split("/")[0])
    except (ValueError, IndexError):
        return None
    if m == 1:  return "Jan"
    if m == 2:  return "Feb"
    if m == 3:  return "Mar"
    if m == 12: return "Dec"
    return "Nov"  # Oct (10) and Nov (11)


def _ff_from_game(ts: dict, os_: dict, game_min: int = 40) -> dict | None:
    """Return four-factor stats for one game, or None if box score is unusable."""
    fga = ts.get("FGA", 0)
    if fga == 0:
        return None
    fgm  = ts.get("FGM", 0); tpm  = ts.get("3PM", 0); tpa  = ts.get("3PA", 0)
    fta  = ts.get("FTA", 0); oreb = ts.get("OREB", 0)
    to_  = ts.get("TO", 0);  ast  = ts.get("AST", 0)
    blk  = ts.get("BLK", 0); stl  = ts.get("STL", 0)
    o_fga  = os_.get("FGA", 0); o_fgm  = os_.get("FGM", 0)
    o_tpm  = os_.get("3PM", 0); o_tpa  = os_.get("3PA", 0)
    o_fta  = os_.get("FTA", 0); o_oreb = os_.get("OREB", 0)
    o_to   = os_.get("TO", 0)
    t_poss = (fga  - oreb)   + to_   + 0.475 * fta
    o_poss = (o_fga - o_oreb) + o_to + 0.475 * o_fta
    avg_poss = (t_poss + o_poss) / 2 if t_poss > 0 and o_poss > 0 else max(t_poss, o_poss)
    if avg_poss <= 0:
        return None
    min_ = max(game_min, 40) if game_min else 40
    return {
        "poss":    round(avg_poss, 1),
        "tempo":   round(avg_poss / min_ * 40, 1),
        "efg":     round((fgm + 0.5 * tpm) / fga * 100, 1),
        "tov":     round(to_  / max(fga + 0.475 * fta + to_, 1) * 100, 1),
        "oreb":    round(oreb / max(oreb + o_oreb, 1) * 100, 1),
        "ftr":     round(fta / fga * 100, 1),
        "two_p":   round((fgm - tpm) / max(fga - tpa, 1) * 100, 1) if (fga - tpa) > 0 else None,
        "three_p": round(tpm / tpa * 100, 1) if tpa > 0 else None,
        "three_pa":round(tpa / fga * 100, 1),
        "ft":      round(ts.get("FTM", 0) / fta * 100, 1) if fta > 0 else None,
        "ast":     round(ast / max(fgm, 1) * 100, 1),
        "blk":     round(blk / max(o_fga, 1) * 100, 1),
        "stl":     round(stl / max(o_poss, 0.1) * 100, 1),
    }


def compute_monthly_stats(game_log: list[dict]) -> dict:
    """
    Return per-month averaged stats from game_log entries.
    Structure: { "Nov": { "gp": n, "ppg": x, "ortg": x, ... }, ... }
    Only months with at least one game with box scores are included.
    """
    buckets: dict[str, list] = {m: [] for m in MONTH_ORDER}
    for g in game_log:
        mb = _month_bucket(g.get("date", ""))
        if not mb:
            continue
        ts  = g.get("team_stats") or {}
        os_ = g.get("opponent_stats") or {}
        ff  = _ff_from_game(ts, os_, g.get("MIN", 40))
        buckets[mb].append({
            "ff":      ff,
            "t_pts":   g.get("team_score", 0),
            "o_pts":   g.get("opponent_score", 0),
            "t_fga":   ts.get("FGA", 0),
            "t_poss":  ff["poss"] if ff else None,
        })

    result = {}
    for month in MONTH_ORDER:
        games = buckets[month]
        if not games:
            continue
        gp = len(games)
        ppg  = sum(g["t_pts"] for g in games) / gp
        oppg = sum(g["o_pts"] for g in games) / gp
        ff_games = [g["ff"] for g in games if g["ff"]]
        def _avg(key):
            vals = [f[key] for f in ff_games if f.get(key) is not None]
            return round(sum(vals) / len(vals), 1) if vals else None
        poss_avg = _avg("poss")
        ortg = round(ppg  / poss_avg * 100, 1) if poss_avg else None
        drtg = round(oppg / poss_avg * 100, 1) if poss_avg else None
        result[month] = {
            "gp":       gp,
            "ppg":      round(ppg, 1),
            "oppg":     round(oppg, 1),
            "margin":   round(ppg - oppg, 1),
            "ortg":     ortg,
            "drtg":     drtg,
            "net_rtg":  round(ortg - drtg, 1) if (ortg and drtg) else None,
            "tempo":    _avg("tempo"),
            "efg_pct":  _avg("efg"),
            "tov_pct":  _avg("tov"),
            "oreb_pct": _avg("oreb"),
            "ft_rate":  _avg("ftr"),
            "twop":     _avg("two_p"),
            "tpp":      _avg("three_p"),
            "tpa_pct":  _avg("three_pa"),
            "ftp":      _avg("ft"),
            "ast_pct":  _avg("ast"),
            "blk_pct":  _avg("blk"),
            "stl_pct":  _avg("stl"),
        }
    return result


def compute_team_only_analytics(team_totals: dict, summary: dict,
                                game_log: list[dict] = None,
                                prior: dict = None) -> dict:
    """Compute team-only stats that require team_summary.json data."""
    result = {}
    gp = summary.get("games_played", 0)
    if gp == 0:
        return {k: 0.0 for k in TEAM_STAT_DEFINITIONS}

    opp_totals = summary.get("opponent_totals", {})
    team_poss_total = ((team_totals["FGA"] - team_totals["OREB"]) + team_totals["TO"]
                       + (0.475 * team_totals["FTA"]))
    opp_poss_total = ((opp_totals.get("FGA", 0) - opp_totals.get("OREB", 0))
                      + opp_totals.get("TO", 0) + (0.475 * opp_totals.get("FTA", 0)))

    # Fallback season-average possessions from totals.
    poss = (team_poss_total + opp_poss_total) / 2 / gp

    # Per-game ORTG/DRTG: compute for each game, then average
    game_ratings = []
    if game_log:
        for g in game_log:
            ts = g.get("team_stats")
            os_ = g.get("opponent_stats")
            if not ts or not os_:
                continue
            # Skip games where either side has a broken box score (no shooting data)
            t_broken = ts.get("FGA", 0) == 0 and ts.get("PTS", 0) == 0
            o_broken = os_.get("FGA", 0) == 0 and os_.get("PTS", 0) == 0
            if t_broken and o_broken:
                continue
            t_poss = (ts["FGA"] - ts["OREB"]) + ts["TO"] + 0.475 * ts["FTA"]
            o_poss = (os_["FGA"] - os_["OREB"]) + os_["TO"] + 0.475 * os_["FTA"]
            # If one side has a broken box score, use the valid team's possessions
            if t_broken or t_poss <= 0:
                if o_poss > 0:
                    avg_poss = o_poss
                else:
                    continue
            elif o_broken or o_poss <= 0:
                avg_poss = t_poss
            else:
                avg_poss = (t_poss + o_poss) / 2
            if avg_poss > 0:
                # Use schedule scores when box score data is broken
                t_pts = g.get("team_score", 0) if t_broken else ts["PTS"]
                o_pts = g.get("opponent_score", 0) if o_broken else os_["PTS"]
                g_ortg = t_pts / avg_poss * 100
                g_drtg = o_pts / avg_poss * 100
                game_min = g.get("MIN", 0)
                g_tempo = avg_poss / game_min * 40 if game_min > 0 else 0.0
                # Determine if opponent is in-system (CA community college)
                opp_name = g.get("opponent", "")
                canonical = resolve_opponent(opp_name)
                game_ratings.append({
                    "date": g.get("date", ""),
                    "opponent": opp_name,
                    "canonical_opponent": canonical,
                    "in_system": canonical is not None,
                    "is_conference": g.get("is_conference", False),
                    "location": g.get("location", ""),
                    "team_score": g.get("team_score", 0),
                    "opponent_score": g.get("opponent_score", 0),
                    "result": g.get("result", ""),
                    "ortg": round(g_ortg, 1),
                    "drtg": round(g_drtg, 1),
                    "possessions": round(avg_poss, 1),
                    "tempo": round(g_tempo, 1),
                })

    seen_game_ratings = set()
    deduped_game_ratings = []
    for game in game_ratings:
        dedupe_key = (
            game.get("date", ""),
            game.get("canonical_opponent") or game.get("opponent", ""),
            game.get("location", ""),
            game.get("team_score", 0),
            game.get("opponent_score", 0),
        )
        if dedupe_key in seen_game_ratings:
            continue
        seen_game_ratings.add(dedupe_key)
        deduped_game_ratings.append(game)
    game_ratings = deduped_game_ratings

    # Season ORTG/DRTG: average of in-system games only
    in_system_ratings = [g for g in game_ratings if g["in_system"]]
    pace_ratings = in_system_ratings if in_system_ratings else game_ratings
    if pace_ratings:
        result["possessions"] = round(
            sum(g["possessions"] for g in pace_ratings) / len(pace_ratings), 1
        )
        tempo_games = [g["tempo"] for g in pace_ratings if g.get("tempo", 0) > 0]
        result["tempo"] = round(sum(tempo_games) / len(tempo_games), 1) if tempo_games else 0.0
    else:
        team_min = summary.get("totals", {}).get("MIN", 0)
        result["possessions"] = round(poss, 1)
        result["tempo"] = round((team_poss_total + opp_poss_total) / 2 / team_min * 40, 1) if team_min > 0 else 0.0

    if in_system_ratings:
        n_games = len(in_system_ratings)
        sum_ortg = sum(g["ortg"] for g in in_system_ratings)
        sum_drtg = sum(g["drtg"] for g in in_system_ratings)
        # Blend the prior season as exponentially-decaying virtual games: heavy
        # early (anti-overreaction shrinkage), nearly gone once a real sample
        # accumulates. See prior_weight() / backtest_prior_decay.py.
        if prior and prior.get("ortg") and prior.get("drtg"):
            w = prior_weight(n_games)
            total_w = n_games + w
            ortg = round((sum_ortg + prior["ortg"] * w) / total_w, 1)
            drtg = round((sum_drtg + prior["drtg"] * w) / total_w, 1)
        else:
            ortg = round(sum_ortg / n_games, 1)
            drtg = round(sum_drtg / n_games, 1)
    elif game_ratings:
        # Fallback: use all games if no in-system games exist
        ortg = round(sum(g["ortg"] for g in game_ratings) / len(game_ratings), 1)
        drtg = round(sum(g["drtg"] for g in game_ratings) / len(game_ratings), 1)
    else:
        ortg = round(summary.get("averages", {}).get("PTS", 0) / poss * 100, 1) if poss > 0 else 0.0
        drtg = round(summary.get("opponent_averages", {}).get("PTS", 0) / poss * 100, 1) if poss > 0 else 0.0

    result["ortg"] = ortg
    result["drtg"] = drtg
    result["net_rtg"] = round(ortg - drtg, 1)
    result["game_ratings"] = game_ratings

    ppg = summary.get("averages", {}).get("PTS", 0)
    opp_ppg = summary.get("opponent_averages", {}).get("PTS", 0)

    opp_dreb = summary.get("opponent_totals", {}).get("DREB", 0)
    total = team_totals["OREB"] + opp_dreb
    result["oreb_pct"] = round(team_totals["OREB"] / total * 100, 1) if total > 0 else 0.0

    fta_pg = summary.get("averages", {}).get("FTA", 0)
    fga_pg = summary.get("averages", {}).get("FGA", 0)
    result["ft_rate"] = round(fta_pg / fga_pg * 100, 1) if fga_pg > 0 else 0.0

    # TS%: PPG / (2 * (FGA_pg + 0.475 * FTA_pg)) * 100
    ts_denom = 2 * (fga_pg + 0.475 * fta_pg)
    result["ts_pct"] = round(ppg / ts_denom * 100, 1) if ts_denom > 0 else 0.0

    # --- Defensive stats ---
    opp = summary.get("opponent_totals", {})

    # Opp eFG%: (Opp FGM + 0.5 * Opp 3PM) / Opp FGA * 100
    opp_fga = opp.get("FGA", 0)
    result["opp_efg_pct"] = round(
        (opp.get("FGM", 0) + 0.5 * opp.get("3PM", 0)) / opp_fga * 100, 1
    ) if opp_fga > 0 else 0.0

    # DREB%: Team DREB / (Team DREB + Opp OREB) * 100
    team_dreb = team_totals["DREB"]
    opp_oreb = opp.get("OREB", 0)
    dreb_total = team_dreb + opp_oreb
    result["dreb_pct"] = round(team_dreb / dreb_total * 100, 1) if dreb_total > 0 else 0.0

    # Opp TOV%: Opp TO / ((Opp FGA - Opp OREB) + Opp TO + (0.475 * Opp FTA)) * 100
    opp_denom = (opp_fga - opp_oreb) + opp.get("TO", 0) + (0.475 * opp.get("FTA", 0))
    result["opp_tov_pct"] = round(opp.get("TO", 0) / opp_denom * 100, 1) if opp_denom > 0 else 0.0

    # Opp FTR: Opp FTA per game / Opp FGA per game * 100
    opp_avgs = summary.get("opponent_averages", {})
    opp_fta_pg = opp_avgs.get("FTA", 0)
    opp_fga_pg = opp_avgs.get("FGA", 0)
    result["opp_ft_rate"] = round(opp_fta_pg / opp_fga_pg * 100, 1) if opp_fga_pg > 0 else 0.0

    # Opp TS%: Opp PPG / (2 * (Opp FGA_pg + 0.475 * Opp FTA_pg)) * 100
    opp_ts_denom = 2 * (opp_fga_pg + 0.475 * opp_fta_pg)
    result["opp_ts_pct"] = round(opp_ppg / opp_ts_denom * 100, 1) if opp_ts_denom > 0 else 0.0

    return result


def compute_player_analytics(totals: dict, ctx: dict = None) -> dict:
    """Compute all defined stats for a single player's totals."""
    result = {}
    for key, defn in STAT_DEFINITIONS.items():
        result[key] = defn["compute"](totals, ctx)
    return result


def compute_team_analytics(team_totals: dict, ctx: dict = None) -> dict:
    """Compute all defined stats for team-level totals."""
    return compute_player_analytics(team_totals, ctx)


def _find_team_in_season(season_dir: Path, team_name: str):
    """Find a team's advanced_analytics.json in a given season directory."""
    for conf_dir in sorted(season_dir.iterdir()):
        if conf_dir.is_dir():
            candidate = conf_dir / team_name / "advanced_analytics.json"
            if candidate.exists():
                return candidate
    return None


def update_team(team_name: str, prior: dict = None):
    """Read player_stats.json, compute analytics, write advanced_analytics.json."""
    team_dir = find_team_stats(team_name)
    if not team_dir:
        print(f"No stats directory for {team_name}")
        return
    stats_path = team_dir / "player_stats.json"
    summary_path = team_dir / "team_summary.json"
    if not stats_path.exists():
        print(f"No player_stats.json for {team_name}")
        return

    with open(stats_path) as f:
        stats = json.load(f)

    summary = {}
    if summary_path.exists():
        with open(summary_path) as f:
            summary = json.load(f)

    game_log_path = team_dir / "game_log.json"
    game_log = []
    if game_log_path.exists():
        with open(game_log_path) as f:
            game_log = json.load(f).get("games", [])

    # First pass: accumulate team totals
    team_totals = {k: 0 for k in ["FGM", "FGA", "3PM", "3PA", "FTM", "FTA",
                                    "OREB", "DREB", "REB", "AST", "STL", "BLK",
                                    "TO", "PF", "PTS", "MIN"]}
    for p in stats["players"]:
        for k in team_totals:
            team_totals[k] += p["totals"].get(k, 0)

    # Build context for stats that need team/opponent data
    opp_totals = summary.get("opponent_totals", {})
    ctx = {
        "team_min":  summary.get("totals", {}).get("MIN", 0),
        "team_fgm":  team_totals["FGM"],
        "team_fga":  team_totals["FGA"],
        "team_fta":  team_totals["FTA"],
        "team_ftm":  team_totals["FTM"],
        "team_to":   team_totals["TO"],
        "team_oreb": team_totals["OREB"],
        "team_dreb": team_totals["DREB"],
        "team_ast":  team_totals["AST"],
        "team_pts":  team_totals["PTS"],
        "team_3pm":  team_totals["3PM"],
        "team_blk":  team_totals["BLK"],
        "team_stl":  team_totals["STL"],
        "team_pf":   team_totals["PF"],
        "team_poss": (
            team_totals["FGA"] - team_totals["OREB"]
            + team_totals["TO"] + 0.475 * team_totals["FTA"]
        ),
        "opp_fga":  opp_totals.get("FGA", 0),
        "opp_fgm":  opp_totals.get("FGM", 0),
        "opp_3pa":  opp_totals.get("3PA", 0),
        "opp_fta":  opp_totals.get("FTA", 0),
        "opp_ftm":  opp_totals.get("FTM", 0),
        "opp_to":   opp_totals.get("TO", 0),
        "opp_pts":  opp_totals.get("PTS", 0),
        "opp_oreb": opp_totals.get("OREB", 0),
        "opp_dreb": opp_totals.get("DREB", 0),
        "opp_pf":   opp_totals.get("PF", 0),
    }

    # Second pass: compute per-player analytics with context
    player_analytics = []
    for p in stats["players"]:
        name = p["name"]
        totals = p["totals"]
        entry = {"name": name}
        entry.update(compute_player_analytics(totals, ctx))
        player_analytics.append(entry)

    # Compute team-level analytics (shared with players)
    team_level = compute_team_analytics(team_totals, ctx)

    # Compute team-only analytics (possessions, ratings — per-game averaged)
    team_level.update(compute_team_only_analytics(team_totals, summary, game_log, prior=prior))

    # Build formulas dict
    all_formulas = {key: defn["formula"] for key, defn in STAT_DEFINITIONS.items()}
    all_formulas.update({key: defn["formula"] for key, defn in TEAM_STAT_DEFINITIONS.items()})

    output = {
        "team": team_level,
        "players": player_analytics,
        "formulas": all_formulas,
        "monthly_stats": compute_monthly_stats(game_log),
    }

    out_path = team_dir / "advanced_analytics.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"{team_name}: updated {len(player_analytics)} players, "
          f"{len(STAT_DEFINITIONS)} metrics each")


def lookup_player(name_query: str):
    """Search all teams for a player and print their analytics."""
    query = name_query.lower()
    found = False
    for team_dir in sorted(STATS_DIR.iterdir()):
        if not team_dir.is_dir():
            continue
        for sub_dir in sorted(team_dir.iterdir()):
            if not sub_dir.is_dir():
                continue
            adv_path = sub_dir / "advanced_analytics.json"
        if not adv_path.exists():
            continue
        with open(adv_path) as f:
            adv = json.load(f)
        for p in adv["players"]:
            if query in p["name"].lower():
                found = True
                print(f"\n{p['name']} — {sub_dir.name}")
                for k, v in p.items():
                    if k != "name":
                        label = STAT_DEFINITIONS.get(k, {}).get("name", k)
                        print(f"  {label}: {v}")
    if not found:
        print(f"No player matching '{name_query}' found.")


def _win_prob(rating_diff, c=18.0):
    """Logistic win probability given a rating difference."""
    return 1.0 / (1.0 + 10 ** (-rating_diff / c))


def _compute_win50(opp_ratings, c=18.0):
    """Find the rating R where expected wins against the schedule = 50%.

    Uses binary search over the logistic win probability model.
    c=18 is empirically calibrated to CCCAA game outcomes.
    """
    if not opp_ratings:
        return 0.0
    n = len(opp_ratings)
    target = n / 2.0
    lo, hi = -80.0, 80.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        expected_wins = sum(_win_prob(mid - opp_r, c) for opp_r in opp_ratings)
        if expected_wins < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def compute_sos(teams, ratings_override=None):
    """Pass 2: compute Opp ORTG, Opp DRTG, SOS (WIN50) for each team using opponents' ratings."""
    # Load all team ratings from pass 1
    team_ratings = {}
    for team_name in all_stat_teams():
        team_dir = find_team_stats(team_name)
        if not team_dir:
            continue
        adv_path = team_dir / "advanced_analytics.json"
        if not adv_path.exists():
            continue
        with open(adv_path) as f:
            adv = json.load(f)
        ta = adv.get("team", {})
        team_ratings[team_name] = {
            "ortg": ta.get("ortg", 0),
            "drtg": ta.get("drtg", 0),
            "net_rtg": ta.get("net_rtg", 0),
        }

    if ratings_override:
        for team_name, r in ratings_override.items():
            if not isinstance(r, dict):
                continue
            ortg = r.get("ortg")
            drtg = r.get("drtg")
            if ortg is None or drtg is None:
                continue
            team_ratings[team_name] = {
                "ortg": ortg,
                "drtg": drtg,
                "net_rtg": r.get("net_rtg", ortg - drtg),
            }

    # For each requested team, compute SOS from in-system opponents
    for team_name in teams:
        team_dir = find_team_stats(team_name)
        if not team_dir:
            continue
        adv_path = team_dir / "advanced_analytics.json"
        if not adv_path.exists():
            continue
        with open(adv_path) as f:
            adv = json.load(f)
        game_ratings = adv.get("team", {}).get("game_ratings", [])

        # Collect all in-system game appearances (repeats count each time)
        opp_ortgs = []
        opp_drtgs = []
        opp_nets = []
        for g in game_ratings:
            if g.get("in_system"):
                canonical = g.get("canonical_opponent")
                if canonical and canonical in team_ratings:
                    opp_ortgs.append(team_ratings[canonical]["ortg"])
                    opp_drtgs.append(team_ratings[canonical]["drtg"])
                    opp_nets.append(team_ratings[canonical]["net_rtg"])

        if opp_nets:
            adv["team"]["opp_ortg"] = round(sum(opp_ortgs) / len(opp_ortgs), 1)
            adv["team"]["opp_drtg"] = round(sum(opp_drtgs) / len(opp_drtgs), 1)
            adv["team"]["sos"] = round(_compute_win50(opp_nets), 1)
        else:
            adv["team"]["opp_ortg"] = 0.0
            adv["team"]["opp_drtg"] = 0.0
            adv["team"]["sos"] = 0.0

        # NCSOS: non-conference in-system games only
        nc_nets = []
        for g in game_ratings:
            if g.get("in_system") and not g.get("is_conference"):
                canonical = g.get("canonical_opponent")
                if canonical and canonical in team_ratings:
                    nc_nets.append(team_ratings[canonical]["net_rtg"])
        adv["team"]["ncsos"] = round(_compute_win50(nc_nets), 1) if nc_nets else 0.0

        # Opponent Adjust: regression slope of residuals vs opponent quality
        # Positive = plays UP to competition; Negative = crushes weak, disappoints vs strong
        my_net = team_ratings.get(team_name, {}).get("net_rtg", 0)
        opp_adjust_games = []
        for g in game_ratings:
            if not g.get("in_system") or g.get("result") not in ("W", "L"):
                continue
            canonical = g.get("canonical_opponent")
            if not canonical or canonical not in team_ratings:
                continue
            opp_net = team_ratings[canonical]["net_rtg"]
            expected_margin = (my_net - opp_net) * 0.67
            actual_margin = g.get("team_score", 0) - g.get("opponent_score", 0)
            opp_adjust_games.append((opp_net, actual_margin - expected_margin))

        if len(opp_adjust_games) >= 5:
            n = len(opp_adjust_games)
            xs = [g[0] for g in opp_adjust_games]
            ys = [g[1] for g in opp_adjust_games]
            mx = sum(xs) / n
            my_r = sum(ys) / n
            ssxy = sum((xi - mx) * (yi - my_r) for xi, yi in zip(xs, ys))
            ssxx = sum((xi - mx) ** 2 for xi in xs)
            adv["team"]["opp_adjust"] = round(ssxy / ssxx, 3) if ssxx > 0 else 0.0
        else:
            adv["team"]["opp_adjust"] = 0.0

        # Pace Adjust: regression slope of residuals vs game pace (possessions)
        # Positive = performs better in up-tempo games; Negative = performs better in slow-paced games
        pace_adjust_games = []
        for g in game_ratings:
            if not g.get("in_system") or g.get("result") not in ("W", "L"):
                continue
            canonical = g.get("canonical_opponent")
            if not canonical or canonical not in team_ratings:
                continue
            game_poss = g.get("possessions", 0)
            if game_poss <= 0:
                continue
            opp_net = team_ratings[canonical]["net_rtg"]
            expected_margin = (my_net - opp_net) * 0.67
            actual_margin = g.get("team_score", 0) - g.get("opponent_score", 0)
            pace_adjust_games.append((game_poss, actual_margin - expected_margin))

        if len(pace_adjust_games) >= 5:
            n_p = len(pace_adjust_games)
            pxs = [g[0] for g in pace_adjust_games]
            pys = [g[1] for g in pace_adjust_games]
            pmx = sum(pxs) / n_p
            pmy = sum(pys) / n_p
            pssxy = sum((xi - pmx) * (yi - pmy) for xi, yi in zip(pxs, pys))
            pssxx = sum((xi - pmx) ** 2 for xi in pxs)
            adv["team"]["pace_adjust"] = round(pssxy / pssxx, 3) if pssxx > 0 else 0.0
        else:
            adv["team"]["pace_adjust"] = 0.0

        with open(adv_path, "w") as f:
            json.dump(adv, f, indent=2)

    print(f"SOS computed for {len(teams)} teams (WIN50, c=18)")


def compute_iterative_adjusted_ratings(teams_to_update):
    """Compute and write iterative opponent-adjusted ORTG/DRTG/NET for teams.

    Uses all available in-system games from advanced_analytics game_ratings.
    Returns a ratings map for all teams included in the iterative pool.
    """
    pool_teams = []
    team_games = {}
    seed_ratings = {}

    for team_name in all_stat_teams():
        team_dir = find_team_stats(team_name)
        if not team_dir:
            continue
        adv_path = team_dir / "advanced_analytics.json"
        if not adv_path.exists():
            continue

        with open(adv_path) as f:
            adv = json.load(f)

        ta = adv.get("team", {})
        gr = ta.get("game_ratings", [])
        in_sys = [
            g for g in gr
            if g.get("in_system") and g.get("canonical_opponent")
        ]

        team_games[team_name] = in_sys
        seed_ratings[team_name] = {
            "ortg": float(ta.get("ortg", 100.0) or 100.0),
            "drtg": float(ta.get("drtg", 100.0) or 100.0),
        }
        pool_teams.append(team_name)

    if not pool_teams:
        return {}

    def _parse_game_date(raw):
        if not raw:
            return None
        s = str(raw).strip()
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    target_ortg = sum(r["ortg"] for r in seed_ratings.values()) / len(seed_ratings)
    target_drtg = sum(r["drtg"] for r in seed_ratings.values()) / len(seed_ratings)

    # KenPom-style date baseline: evaluate each game against league efficiency
    # level on the game date rather than a single full-season baseline.
    date_samples = {}
    all_dates = []
    for games in team_games.values():
        for g in games:
            d = _parse_game_date(g.get("date"))
            if d is None:
                continue
            if g.get("ortg", 0) <= 0 or g.get("drtg", 0) <= 0:
                continue
            bucket = date_samples.setdefault(d, {"ortg": [], "drtg": []})
            bucket["ortg"].append(float(g["ortg"]))
            bucket["drtg"].append(float(g["drtg"]))
            all_dates.append(d)

    date_baselines = {}
    for d, vals in date_samples.items():
        if vals["ortg"] and vals["drtg"]:
            date_baselines[d] = {
                "ortg": sum(vals["ortg"]) / len(vals["ortg"]),
                "drtg": sum(vals["drtg"]) / len(vals["drtg"]),
            }

    season_start = min(all_dates) if all_dates else None
    season_end = max(all_dates) if all_dates else None

    def _game_weight(game, opp_net):
        # Recency is present but intentionally modest.
        recency = 1.0
        d = _parse_game_date(game.get("date"))
        if d is not None and season_start is not None and season_end is not None and season_end > season_start:
            frac = (d - season_start).days / (season_end - season_start).days
            frac = max(0.0, min(1.0, frac))
            recency = RECENCY_MIN_WEIGHT + (RECENCY_MAX_WEIGHT - RECENCY_MIN_WEIGHT) * frac

        # Game-importance sensitivity is deliberately light.
        margin = abs(float(game.get("team_score", 0)) - float(game.get("opponent_score", 0)))
        margin_term = min(margin, IMPORTANCE_SCALE) / IMPORTANCE_SCALE
        opp_term = min(abs(float(opp_net)), IMPORTANCE_SCALE) / IMPORTANCE_SCALE
        importance = (
            IMPORTANCE_BASE
            + IMPORTANCE_MARGIN_BONUS * margin_term
            + IMPORTANCE_OPP_BONUS * opp_term
        )
        return recency * importance

    current = {t: dict(r) for t, r in seed_ratings.items()}
    for _iteration in range(1, MAX_ITER + 1):
        new_ratings = {}

        for team_name in pool_teams:
            in_sys = team_games.get(team_name, [])
            if not in_sys:
                new_ratings[team_name] = {"ortg": target_ortg, "drtg": target_drtg}
                continue

            adj_ortgs = []
            adj_drtgs = []

            for g in in_sys:
                opp = g.get("canonical_opponent")
                d = _parse_game_date(g.get("date"))
                date_base = date_baselines.get(d, {"ortg": target_ortg, "drtg": target_drtg})
                if opp not in current:
                    if g.get("ortg", 0) > 0:
                        adj_ortgs.append((float(g["ortg"]), 1.0))
                    if g.get("drtg", 0) > 0:
                        adj_drtgs.append((float(g["drtg"]), 1.0))
                    continue

                opp_drtg = current[opp]["drtg"]
                opp_ortg = current[opp]["ortg"]
                opp_net = opp_ortg - opp_drtg

                hca_o = 0.0
                hca_d = 0.0
                loc = g.get("location", "")
                if loc == "Home":
                    hca_o = -HOME_ADVANTAGE / 2
                    hca_d = +HOME_ADVANTAGE / 2
                elif loc == "Away":
                    hca_o = +HOME_ADVANTAGE / 2
                    hca_d = -HOME_ADVANTAGE / 2

                g_ortg = float(g.get("ortg", 0))
                g_drtg = float(g.get("drtg", 0))
                w = _game_weight(g, opp_net)
                adj_ortgs.append((g_ortg + hca_o - opp_drtg + date_base["drtg"], w))
                adj_drtgs.append((g_drtg + hca_d - opp_ortg + date_base["ortg"], w))

            if adj_ortgs and adj_drtgs:
                sum_w_o = sum(w for _, w in adj_ortgs)
                sum_w_d = sum(w for _, w in adj_drtgs)
                game_ortg = sum(v * w for v, w in adj_ortgs) / sum_w_o if sum_w_o > 0 else target_ortg
                game_drtg = sum(v * w for v, w in adj_drtgs) / sum_w_d if sum_w_d > 0 else target_drtg

                n = min(sum_w_o, sum_w_d)
                weight = n / (n + REGRESSION_GAMES)
                reg_ortg = weight * game_ortg + (1 - weight) * target_ortg
                reg_drtg = weight * game_drtg + (1 - weight) * target_drtg

                new_ortg = DAMPEN * reg_ortg + (1 - DAMPEN) * current[team_name]["ortg"]
                new_drtg = DAMPEN * reg_drtg + (1 - DAMPEN) * current[team_name]["drtg"]
                new_ratings[team_name] = {"ortg": new_ortg, "drtg": new_drtg}
            else:
                new_ratings[team_name] = {"ortg": target_ortg, "drtg": target_drtg}

        avg_ortg = sum(r["ortg"] for r in new_ratings.values()) / len(new_ratings)
        avg_drtg = sum(r["drtg"] for r in new_ratings.values()) / len(new_ratings)
        ortg_shift = target_ortg - avg_ortg
        drtg_shift = target_drtg - avg_drtg
        for team_name in new_ratings:
            new_ratings[team_name]["ortg"] += ortg_shift
            new_ratings[team_name]["drtg"] += drtg_shift

        max_change = 0.0
        for team_name in pool_teams:
            chg = max(
                abs(new_ratings[team_name]["ortg"] - current[team_name]["ortg"]),
                abs(new_ratings[team_name]["drtg"] - current[team_name]["drtg"]),
            )
            if chg > max_change:
                max_change = chg

        current = new_ratings
        if max_change < 0.01:
            break

    for team_name in teams_to_update:
        if team_name not in current:
            continue
        team_dir = find_team_stats(team_name)
        if not team_dir:
            continue
        adv_path = team_dir / "advanced_analytics.json"
        if not adv_path.exists():
            continue

        with open(adv_path) as f:
            adv = json.load(f)

        ortg = round(current[team_name]["ortg"], 1)
        drtg = round(current[team_name]["drtg"], 1)
        adv.setdefault("team", {})["ortg"] = ortg
        adv.setdefault("team", {})["drtg"] = drtg
        adv.setdefault("team", {})["net_rtg"] = round(ortg - drtg, 1)

        with open(adv_path, "w") as f:
            json.dump(adv, f, indent=2)

    adjusted = {
        t: {
            "ortg": round(r["ortg"], 1),
            "drtg": round(r["drtg"], 1),
            "net_rtg": round(r["ortg"] - r["drtg"], 1),
        }
        for t, r in current.items()
    }
    print(f"Iterative adjusted ratings computed for {len(pool_teams)} teams")
    return adjusted


def main():
    global STATS_DIR, _CANONICAL_TEAMS
    parser = argparse.ArgumentParser(description="Compute advanced analytics from player stats")
    parser.add_argument("--teams", nargs="+", help="Team names to update")
    parser.add_argument("--all", action="store_true", help="Update all teams in stats folder")
    parser.add_argument("--player", nargs="+", help="Look up a player by name")
    parser.add_argument("--season", default="2025-26", help="Season year prefix, e.g. 2024-25 or 2025-26")
    parser.add_argument("--prior-season", default=None,
                        help="Prior season to blend as starting ratings, e.g. 2023-24. "
                             "Default: auto-derived from the PRIOR_CHAIN (decays from the "
                             "previous season; cold start for 2017-18 and 2021-22 post-COVID). "
                             "Pass 'none' to disable prior blending.")
    args = parser.parse_args()

    # Auto-derive the prior season from the chain unless explicitly given.
    # 'none' disables blending; an explicit season overrides the chain.
    if args.prior_season is None:
        args.prior_season = PRIOR_CHAIN.get(args.season)
        if args.prior_season:
            print(f"Auto-chained prior season: {args.season} <- {args.prior_season}")
        else:
            print(f"No prior season for {args.season} (cold start).")
    elif args.prior_season.lower() == "none":
        args.prior_season = None
        print("Prior blending disabled (--prior-season none).")

    if args.season != "2025-26":
        STATS_DIR = Path(f"{args.season} Team Statistics")
        _CANONICAL_TEAMS = None  # reset so it rebuilds against correct dir

    if args.player:
        lookup_player(" ".join(args.player))
        return

    if args.all:
        teams = list(all_stat_teams())
    elif args.teams:
        teams = args.teams
    else:
        parser.print_help()
        return

    # Load prior-season ratings if requested
    prior_map = {}
    if args.prior_season:
        prior_dir = Path(f"{args.prior_season} Team Statistics")
        if not prior_dir.exists():
            print(f"Warning: prior season directory not found: {prior_dir}")
        else:
            loaded = 0
            for team_name in teams:
                adv_path = _find_team_in_season(prior_dir, team_name)
                if adv_path:
                    try:
                        adv = json.load(open(adv_path))
                        ta = adv.get("team", {})
                        if ta.get("ortg") and ta.get("drtg"):
                            prior_map[team_name] = {"ortg": ta["ortg"], "drtg": ta["drtg"]}
                            loaded += 1
                    except Exception:
                        pass
            print(f"Loaded prior ratings for {loaded}/{len(teams)} teams from {args.prior_season} "
                  f"(decay w(n)={PRIOR_W0:g}*exp(-n/{PRIOR_TAU:g}); ~{prior_weight(12):.1f} games @ game 12)")

    # Pass 1: compute per-team analytics (ORTG/DRTG/NET RTG filtered to in-system)
    for team in teams:
        update_team(team, prior=prior_map.get(team))

    # Pass 2: iterative opponent-adjusted ORTG/DRTG/NET (default)
    iter_ratings = compute_iterative_adjusted_ratings(teams)

    # Pass 3: compute SOS using iterative ratings
    compute_sos(teams, ratings_override=iter_ratings)


if __name__ == "__main__":
    main()
