#!/usr/bin/env python3
"""
Compute individual Offensive Rating (ORtg) and Defensive Rating (DRtg)
per game and season totals for each player, using Dean Oliver's formulas
from Basketball on Paper (as published on basketball-reference.com).

A game is skipped if:
  - Any player on either team has MIN = 0 or missing (minutes not tracked)
  - Either team has total FGA = 0 (empty box score)
  - Either team has total PF = 0 (team fouls not tracked)

BLK = 0 for a team is treated as valid (could legitimately be zero).

Output per team: player_game_ratings.json in the team's stats folder.

Usage:
    python compute_player_ratings.py --teams Moorpark Ventura
    python compute_player_ratings.py --all
    python compute_player_ratings.py --all --season 2024-25
"""

import argparse
import json
import re
from pathlib import Path

SCHEDULES_DIR = Path("2025-26 Teams Schedules")
STATS_DIR = Path("2025-26 Team Statistics")

TEAM_ALIASES = {
    "MSJC-M": "Mt. San Jacinto",
    "HARBOR-M": "LA Harbor",
    "LASW-M": "LA Southwest",
    "COD-M": "Desert",
    "BAR-M": "Barstow",
    "SBVC-M": "San Bernardino Valley",
    "CHFFY-M": "Chaffey",
    "CMC-M": "Copper Mountain",
    "COSO-M": "Cerro Coso",
    "VVC-M": "Victor Valley",
    "MESA-M": "San Diego Mesa",
    "PAL-M": "Palomar",
    "SADD-M": "Saddleback",
    "IRVINE-M": "Irvine Valley",
    "AVC-M": "Antelope Valley",
    "College of the Canyo": "Canyons",
    "Los Angeles Valley": "LA Valley",
    "Mt. SAC": "Mt. San Antonio",
}


# ---------------------------------------------------------------------------
# Helpers shared with generate_team_stats
# ---------------------------------------------------------------------------

def parse_made_att(val: str):
    m = re.match(r"(\d+)-(\d+)", str(val))
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def normalize_player_name(name: str) -> str:
    m = re.match(r'[gfc#]+\s*0*(\d+)\s+(.*)', name, re.IGNORECASE)
    if m:
        return f"#{m.group(1)} {m.group(2)}"
    return name


def _game_minutes(bs: dict) -> int:
    if "game_minutes" in bs:
        return bs["game_minutes"]
    total_min = 0
    count = 0
    for team_players in bs.get("teams", {}).values():
        team_min = sum(
            int(p.get("stats", {}).get("MIN", "0") or 0)
            for p in team_players
            if p.get("stats") and not p.get("name", "").startswith("TM")
        )
        total_min += team_min
        count += 1
    if count == 0:
        return 40
    avg = total_min / count
    ot = max(0, round((avg - 200) / 25))
    return 40 + 5 * ot


def _find_team_key(team_name: str, bs: dict) -> str | None:
    for key in bs.get("teams", {}):
        if key.lower() == team_name.lower():
            return key
    for key in bs.get("teams", {}):
        if team_name.lower() in key.lower() or key.lower() in team_name.lower():
            return key
    for key in bs.get("teams", {}):
        if TEAM_ALIASES.get(key, "").lower() == team_name.lower():
            return key
    return None


def _find_opponent_key(team_name: str, bs: dict) -> str | None:
    team_key = _find_team_key(team_name, bs)
    for key in bs.get("teams", {}):
        if key != team_key:
            return key
    return None


def _parse_player_stats(raw: dict) -> dict:
    """Parse a player's raw stats dict into ints."""
    s = raw.get("stats", {})
    if not s:
        return None
    fgm, fga = parse_made_att(s.get("FGM-A", "0-0"))
    tpm, tpa = parse_made_att(s.get("3PM-A", "0-0"))
    ftm, fta = parse_made_att(s.get("FTM-A", "0-0"))
    try:
        mp = int(s.get("MIN", 0) or 0)
    except (ValueError, TypeError):
        mp = 0
    return {
        "name": normalize_player_name(raw.get("name", "")),
        "MP": mp,
        "FGM": fgm, "FGA": fga,
        "3PM": tpm, "3PA": tpa,
        "FTM": ftm, "FTA": fta,
        "ORB": int(s.get("OREB", 0) or 0),
        "DRB": int(s.get("DREB", 0) or 0),
        "TRB": int(s.get("REB", 0) or 0),
        "AST": int(s.get("AST", 0) or 0),
        "STL": int(s.get("STL", 0) or 0),
        "BLK": int(s.get("BLK", 0) or 0),
        "TOV": int(s.get("TO", 0) or 0),
        "PF":  int(s.get("PF", 0) or 0),
        "PTS": int(s.get("PTS", 0) or 0),
    }


def _sum_box(players_parsed: list) -> dict:
    """Sum parsed player stats into team totals."""
    t = {k: 0 for k in ("MP","FGM","FGA","3PM","3PA","FTM","FTA",
                          "ORB","DRB","TRB","AST","STL","BLK","TOV","PF","PTS")}
    for p in players_parsed:
        for k in t:
            t[k] += p[k]
    return t


# ---------------------------------------------------------------------------
# Game validity check
# ---------------------------------------------------------------------------

def _game_is_valid(team_players: list, opp_players: list) -> tuple[bool, str]:
    """Return (valid, reason). Checks both sides.

    Minutes check: skip only if ≥67% of a team's players show MIN=0,
    which indicates minutes were not tracked at all.  One or two DNP
    players with MIN=0 is normal and should not invalidate a game.
    """
    for side, label in [(team_players, "team"), (opp_players, "opponent")]:
        fga = sum(p["FGA"] for p in side)
        pf  = sum(p["PF"]  for p in side)
        if fga == 0:
            return False, f"{label} FGA=0"
        if pf == 0:
            return False, f"{label} team PF=0"
        n = len(side)
        if n > 0:
            zero_min = sum(1 for p in side if p["MP"] == 0)
            if zero_min / n >= 0.67:
                return False, f"{label} {zero_min}/{n} players have MIN=0 (minutes not tracked)"
    return True, ""


# ---------------------------------------------------------------------------
# Oliver ORtg / DRtg
# ---------------------------------------------------------------------------

def _safe_div(num, den, default=0.0):
    return num / den if den != 0 else default


def compute_ortg(p: dict, tm: dict, opp: dict, game_min: int) -> float | None:
    """Individual Offensive Rating (points produced per 100 possessions)."""
    mp = p["MP"]
    if mp == 0:
        return None

    team_mp = game_min * 5  # total player-minutes for 5-man team

    fgm, fga = p["FGM"], p["FGA"]
    ftm, fta = p["FTM"], p["FTA"]
    tpm      = p["3PM"]
    orb      = p["ORB"]
    ast      = p["AST"]
    pts      = p["PTS"]
    tov      = p["TOV"]

    # Team totals
    T_fgm, T_fga = tm["FGM"], tm["FGA"]
    T_ftm, T_fta = tm["FTM"], tm["FTA"]
    T_3pm        = tm["3PM"]
    T_orb        = tm["ORB"]
    T_ast        = tm["AST"]
    T_pts        = tm["PTS"]
    T_tov        = tm["TOV"]

    # Opponent totals (for ORB%)
    O_drb        = opp["DRB"]

    # Team scoring possessions
    ft_factor = (1 - _safe_div(T_ftm, T_fta)) ** 2 if T_fta > 0 else 0.0
    T_ScPoss = T_fgm + (1 - ft_factor) * T_fta * 0.4
    T_Play   = _safe_div(T_ScPoss, T_fga + T_fta * 0.4 + T_tov)

    # Team ORB%
    T_ORB_pct = _safe_div(T_orb, T_orb + O_drb)
    T_ORB_wt  = _safe_div(
        (1 - T_ORB_pct) * T_Play,
        (1 - T_ORB_pct) * T_Play + T_ORB_pct * (1 - T_Play)
    )

    # qAST
    mp_ratio = _safe_div(mp, team_mp / 5)
    qAST = (
        mp_ratio * (1.14 * _safe_div(T_ast - ast, T_fgm))
        + (_safe_div(
            (_safe_div(T_ast, team_mp) * mp * 5 - ast),
            (_safe_div(T_fgm, team_mp) * mp * 5 - fgm)
           ) * (1 - mp_ratio))
    ) if T_fgm > 0 else 0.0

    # FG_Part
    fg_part = fgm * (1 - 0.5 * _safe_div(pts - ftm, 2 * fga) * qAST) if fga > 0 else 0.0

    # AST_Part
    ast_part = (
        0.5
        * _safe_div((T_pts - T_ftm) - (pts - ftm), 2 * (T_fga - fga))
        * ast
    ) if (T_fga - fga) > 0 else 0.0

    # FT_Part
    ft_p_factor = (1 - _safe_div(ftm, fta)) ** 2 if fta > 0 else 0.0
    ft_part = (1 - ft_p_factor) * 0.4 * fta

    # ORB_Part
    orb_part = orb * T_ORB_wt * T_Play

    # ScPoss
    sc_poss = (fg_part + ast_part + ft_part) * (1 - _safe_div(T_orb, T_ScPoss) * T_ORB_wt * T_Play) + orb_part

    # Missed FG / FT Possessions
    fgx_poss = (fga - fgm) * (1 - 1.07 * T_ORB_pct)
    ftx_poss = ft_p_factor * 0.4 * fta

    tot_poss = sc_poss + fgx_poss + ftx_poss + tov
    if tot_poss <= 0:
        return None

    # PProd_FG_Part
    pprod_fg = 2 * (fgm + 0.5 * tpm) * (1 - 0.5 * _safe_div(pts - ftm, 2 * fga) * qAST) if fga > 0 else 0.0

    # PProd_AST_Part
    pprod_ast = (
        2 * _safe_div(T_fgm - fgm + 0.5 * (T_3pm - tpm), T_fgm - fgm)
        * 0.5
        * _safe_div((T_pts - T_ftm) - (pts - ftm), 2 * (T_fga - fga))
        * ast
    ) if (T_fgm - fgm) > 0 and (T_fga - fga) > 0 else 0.0

    # PProd_ORB_Part
    T_ScPoss_denom = T_fgm + (1 - ft_factor) * T_fta * 0.4
    pprod_orb = (
        orb * T_ORB_wt * T_Play
        * _safe_div(T_pts, T_ScPoss_denom)
    ) if T_ScPoss_denom > 0 else 0.0

    pprod = (pprod_fg + pprod_ast + ftm) * (1 - _safe_div(T_orb, T_ScPoss) * T_ORB_wt * T_Play) + pprod_orb

    return round(100 * pprod / tot_poss, 1)


def compute_drtg(p: dict, tm: dict, opp: dict, game_min: int) -> float | None:
    """Individual Defensive Rating (opponent points per 100 possessions faced)."""
    mp = p["MP"]
    if mp == 0:
        return None

    team_mp = game_min * 5

    stl = p["STL"]
    blk = p["BLK"]
    drb = p["DRB"]
    pf  = p["PF"]

    # Team totals
    T_drb = tm["DRB"]
    T_blk = tm["BLK"]
    T_stl = tm["STL"]
    T_pf  = tm["PF"]
    T_tov = tm["TOV"]    # team's turnovers (opponents' forced turnovers on defense)
    T_fgm = tm["FGM"]
    T_fga = tm["FGA"]

    # Opponent totals
    O_fgm, O_fga = opp["FGM"], opp["FGA"]
    O_ftm, O_fta = opp["FTM"], opp["FTA"]
    O_orb        = opp["ORB"]
    O_drb_t      = opp["DRB"]
    O_tov        = opp["TOV"]
    O_pts        = opp["PTS"]
    O_mp         = team_mp  # symmetric

    # DOR% (opponent's ORB%)
    DOR_pct = _safe_div(O_orb, O_orb + T_drb)

    # DFG% (opponent FG%)
    DFG_pct = _safe_div(O_fgm, O_fga)

    # FMwt
    FMwt = _safe_div(
        DFG_pct * (1 - DOR_pct),
        DFG_pct * (1 - DOR_pct) + (1 - DFG_pct) * DOR_pct
    )

    # Stops1
    stops1 = stl + blk * FMwt * (1 - 1.07 * DOR_pct) + drb * (1 - FMwt)

    # Stops2
    opp_ft_factor = (1 - _safe_div(O_ftm, O_fta)) ** 2 if O_fta > 0 else 0.0
    stops2 = (
        (
            _safe_div(O_fga - O_fgm - T_blk, team_mp) * FMwt * (1 - 1.07 * DOR_pct)
            + _safe_div(O_tov - T_stl, team_mp)
        ) * mp
        + _safe_div(pf, T_pf) * 0.4 * O_fta * opp_ft_factor
    ) if T_pf > 0 else 0.0

    stops = stops1 + stops2

    # Team possessions
    O_ScPoss = O_fgm + (1 - opp_ft_factor) * O_fta * 0.4
    team_poss = O_fga + O_fta * 0.4 + O_tov  # denominator for team defensive possessions

    # Stop%
    stop_pct = _safe_div(stops * O_mp, team_poss * mp)

    # Team Defensive Rating
    team_drtg = 100 * _safe_div(O_pts, team_poss)

    # D_Pts_per_ScPoss
    d_pts_sc = _safe_div(O_pts, O_ScPoss)

    # Individual DRtg
    drtg = team_drtg + 0.2 * (100 * d_pts_sc * (1 - stop_pct) - team_drtg)
    return round(drtg, 1)


# ---------------------------------------------------------------------------
# Per-game and season accumulation
# ---------------------------------------------------------------------------

def process_team(team_name: str, schedules_dir: Path, stats_dir: Path):
    """Compute player game ratings for one team, write player_game_ratings.json."""
    # Find schedule folder
    sched_path = None
    for conf_dir in sorted(schedules_dir.iterdir()):
        if conf_dir.is_dir():
            candidate = conf_dir / team_name
            if candidate.is_dir():
                sched_path = candidate
                break
    if sched_path is None:
        print(f"  [skip] No schedule folder for {team_name}")
        return

    # Find stats folder
    stats_path = None
    for conf_dir in sorted(stats_dir.iterdir()):
        if conf_dir.is_dir():
            candidate = conf_dir / team_name
            if candidate.is_dir():
                stats_path = candidate
                break
    if stats_path is None:
        print(f"  [skip] No stats folder for {team_name}")
        return

    # Load all box scores
    boxscores = []
    for game_dir in sorted(sched_path.iterdir()):
        if not game_dir.is_dir():
            continue
        for jf in game_dir.glob("*.json"):
            try:
                bs = json.loads(jf.read_text())
                boxscores.append(bs)
            except Exception:
                pass

    if not boxscores:
        print(f"  [skip] No box scores for {team_name}")
        return

    # Accumulate per-player: game logs and season totals
    player_games: dict[str, list] = {}      # name -> list of per-game dicts
    player_accum: dict[str, dict] = {}      # name -> running totals for season rating

    games_used = 0
    games_skipped = 0

    for bs in boxscores:
        game_min = _game_minutes(bs)
        t_key = _find_team_key(team_name, bs)
        o_key = _find_opponent_key(team_name, bs)
        if not t_key or not o_key:
            games_skipped += 1
            continue

        raw_team = [p for p in bs["teams"].get(t_key, [])
                    if not p.get("name", "").startswith("TM")]
        raw_opp  = [p for p in bs["teams"].get(o_key, [])
                    if not p.get("name", "").startswith("TM")]

        team_parsed = [_parse_player_stats(p) for p in raw_team]
        opp_parsed  = [_parse_player_stats(p) for p in raw_opp]
        team_parsed = [p for p in team_parsed if p]
        opp_parsed  = [p for p in opp_parsed if p]

        if not team_parsed or not opp_parsed:
            games_skipped += 1
            continue

        valid, reason = _game_is_valid(team_parsed, opp_parsed)
        if not valid:
            games_skipped += 1
            continue

        tm = _sum_box(team_parsed)
        op = _sum_box(opp_parsed)
        date = bs.get("date", "")
        opponent = o_key

        games_used += 1

        for p in team_parsed:
            if p["MP"] == 0:
                continue
            ortg = compute_ortg(p, tm, op, game_min)
            drtg = compute_drtg(p, tm, op, game_min)
            if ortg is None or drtg is None:
                continue

            name = p["name"]
            game_entry = {
                "date": date,
                "opponent": opponent,
                "MP": p["MP"],
                "ortg": ortg,
                "drtg": drtg,
                "net": round(ortg - drtg, 1),
                "pts": p["PTS"],
                "fgm": p["FGM"],
                "fga": p["FGA"],
                "ftm": p["FTM"],
                "fta": p["FTA"],
                "tpm": p["3PM"],
                "orb": p["ORB"],
                "drb": p["DRB"],
                "ast": p["AST"],
                "stl": p["STL"],
                "blk": p["BLK"],
                "tov": p["TOV"],
                "pf":  p["PF"],
            }

            if name not in player_games:
                player_games[name] = []
                player_accum[name] = {k: 0 for k in (
                    "games","MP","FGM","FGA","3PM","FTA","FTM","ORB","DRB",
                    "AST","STL","BLK","TOV","PF","PTS",
                    "ortg_sum","drtg_sum","net_sum",
                    "ast_rate_denom"
                )}

            # Assist Rate per game:
            # AST / (Min% × teammate FGM while on floor)
            # Min% = player MP / game_min  [fraction of one-player slot's minutes]
            # Consistent with KenPom: MP / (Team MP / 5) = MP / game_min
            # Teammate FGM = TmFGM - PlayerFGM  (can't assist yourself)
            _min_pct = p["MP"] / game_min if game_min > 0 else 0
            _tmmate_fgm = tm["FGM"] - p["FGM"]
            _ast_denom = _min_pct * _tmmate_fgm
            game_entry["ast_rate"] = (
                round(100 * p["AST"] / _ast_denom, 1)
                if _ast_denom > 0 else None
            )

            player_games[name].append(game_entry)

            acc = player_accum[name]
            acc["games"] += 1
            for stat in ("MP","FGM","FGA","3PM","FTA","FTM","ORB","DRB",
                         "AST","STL","BLK","TOV","PF","PTS"):
                acc[stat] += p[stat]
            # Simple averages of game ratings. Zero-rating games are included;
            # no minute weighting, trimming, or game removal is applied.
            acc["ortg_sum"] += ortg
            acc["drtg_sum"] += drtg
            acc["net_sum"]  += ortg - drtg
            # Assist rate denominator accumulation (season total)
            acc["ast_rate_denom"] += _ast_denom

    # Build season summary per player
    season_ratings = []
    for name, acc in player_accum.items():
        if acc["games"] == 0:
            continue
        w_ortg = round(acc["ortg_sum"] / acc["games"], 1)
        w_drtg = round(acc["drtg_sum"] / acc["games"], 1)
        w_net  = round(acc["net_sum"] / acc["games"], 1)
        # Season assist rate: total AST / total (Min% × teammate FGM) across all games
        w_ast_rate = (
            round(100 * acc["AST"] / acc["ast_rate_denom"], 1)
            if acc["ast_rate_denom"] > 0 else None
        )
        season_ratings.append({
            "name": name,
            "games": acc["games"],
            "MP":    acc["MP"],
            "mpg":   round(acc["MP"] / acc["games"], 1),
            "ortg":  w_ortg,
            "drtg":  w_drtg,
            "net":   w_net,
            "ast_rate": w_ast_rate,
        })

    season_ratings.sort(key=lambda x: x.get("MP", 0), reverse=True)

    output = {
        "team": team_name,
        "games_rated": games_used,
        "games_skipped": games_skipped,
        "season_ratings": season_ratings,
        "game_logs": {
            name: sorted(games, key=lambda g: g["date"])
            for name, games in player_games.items()
        },
    }

    out_path = stats_path / "player_game_ratings.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"  {team_name}: {games_used} games rated, {games_skipped} skipped → {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def all_teams(schedules_dir: Path):
    for conf_dir in sorted(schedules_dir.iterdir()):
        if conf_dir.is_dir():
            for team_dir in sorted(conf_dir.iterdir()):
                if team_dir.is_dir():
                    yield team_dir.name


def main():
    global SCHEDULES_DIR, STATS_DIR

    parser = argparse.ArgumentParser(description="Compute Oliver ORtg/DRtg per player per game")
    parser.add_argument("--teams", nargs="+", metavar="TEAM")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--season", default=None,
                        help="Season string e.g. 2024-25 (overrides default dirs)")
    args = parser.parse_args()

    if args.season:
        SCHEDULES_DIR = Path(f"{args.season} Teams Schedules")
        STATS_DIR     = Path(f"{args.season} Team Statistics")

    teams = list(all_teams(SCHEDULES_DIR)) if args.all else (args.teams or [])
    if not teams:
        parser.print_help()
        return

    print(f"Computing player ratings for {len(teams)} team(s) "
          f"[{SCHEDULES_DIR.name}]...")
    for team in teams:
        process_team(team, SCHEDULES_DIR, STATS_DIR)


if __name__ == "__main__":
    main()
