#!/usr/bin/env python3
"""
Compute an in-house BPM-style player metric from strict full box scores.

This is intentionally written as a standalone experimental calculator. It does
not modify leaderboard inputs or published advanced_analytics.json files.

The regression coefficients follow Basketball-Reference BPM 2.0's public
description, adapted to CCC data availability:
  - rebuild player/team totals from per-game JSON box scores only
  - accept only games with full player minutes and box-score inputs
  - use existing internal position probabilities when available
  - estimate offensive creation role from assist share and threshold points
  - add calibrated team adjustments so OBPM/BPM reflect strict-sample team
    context without importing the full CCC team-rating spread onto an NBA-like
    BPM scale
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SEASON = "2025-26"
STATS_DIR = ROOT / "2025-26 Team Statistics"
SCHEDULES_DIR = ROOT / "2025-26 Teams Schedules"
POSITIONS_CSV = ROOT / "internal_data" / "player_positions_2025_26.csv"
OUT_DIR = ROOT / "internal_data"


def _set_season(season: str) -> Path:
    """Point the module-level paths at a given season and return the default
    output prefix (internal_data/ccc_bpm_<season>)."""
    global SEASON, STATS_DIR, SCHEDULES_DIR, POSITIONS_CSV
    SEASON = season
    sy = season.replace("-", "_")
    STATS_DIR = ROOT / f"{season} Team Statistics"
    SCHEDULES_DIR = ROOT / f"{season} Teams Schedules"
    POSITIONS_CSV = ROOT / "internal_data" / f"player_positions_{sy}.csv"
    return OUT_DIR / f"ccc_bpm_{sy}"

STAT_KEYS = ("MIN", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS")
SPLIT_KEYS = ("FGM-A", "3PM-A", "FTM-A")

BPM_COEFFS = {
    "PTS": (0.860, 0.860),
    "3PM": (0.389, 0.389),
    "AST": (0.580, 1.034),
    "TO": (-0.964, -0.964),
    "OREB": (0.613, 0.181),
    "DREB": (0.116, 0.181),
    "STL": (1.369, 1.008),
    "BLK": (1.327, 0.703),
    "PF": (-0.367, -0.367),
}
BPM_ROLE_COEFFS = {
    "FGA": (-0.560, -0.780),
    "FTA": (-0.246, -0.343),
}
OBPM_COEFFS = {
    "PTS": (0.605, 0.605),
    "3PM": (0.477, 0.477),
    "AST": (0.476, 0.476),
    "TO": (-0.579, -0.882),
    "OREB": (0.606, 0.422),
    "DREB": (-0.112, 0.103),
    "STL": (0.177, 0.294),
    "BLK": (0.725, 0.097),
    "PF": (-0.439, -0.439),
}
OBPM_ROLE_COEFFS = {
    "FGA": (-0.330, -0.472),
    "FTA": (-0.145, -0.208),
}

BASE_STATS = (
    "MIN",
    "FGM",
    "FGA",
    "3PM",
    "3PA",
    "FTM",
    "FTA",
    "OREB",
    "DREB",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TO",
    "PF",
    "PTS",
)


@dataclass
class PlayerTotals:
    name: str
    clean_name: str
    totals: dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in BASE_STATS})
    games: int = 0


@dataclass
class TeamSample:
    conference: str
    team: str
    games_checked: int = 0
    games_used: int = 0
    games_rejected: int = 0
    reject_reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    totals: dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in BASE_STATS})
    opp_totals: dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in BASE_STATS})
    players: dict[str, PlayerTotals] = field(default_factory=dict)


def clean_name(name: str) -> str:
    name = re.sub(r"^#\d+\s+", "", name or "").strip()
    name = re.sub(r"^(?:g|f|c|guard|forward|center)\s+\d+\s+", "", name, flags=re.I).strip()
    name = re.sub(r"^\d+\s+", "", name).strip()
    return re.sub(r"\s+", " ", name)


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_name(name).lower())


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "--", "-", "DNP"}:
        return None
    try:
        parsed = int(float(text))
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def parse_made_attempt(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", text)
    if not match:
        return None
    made, att = int(match.group(1)), int(match.group(2))
    if made < 0 or att < 0 or made > att:
        return None
    return made, att


def possessions(t: dict[str, float]) -> float:
    return (t.get("FGA", 0.0) - t.get("OREB", 0.0)) + t.get("TO", 0.0) + 0.475 * t.get("FTA", 0.0)


def safe_div(num: float, den: float, default: float = 0.0) -> float:
    return num / den if den else default


def interp(scale: float, pg_value: float, c_value: float) -> float:
    scale = min(5.0, max(1.0, scale))
    return pg_value + ((scale - 1.0) / 4.0) * (c_value - pg_value)


def position_constant(scale: float, pg_const: float) -> float:
    if scale >= 3.0:
        return 0.0
    return (3.0 - scale) * (pg_const / 2.0)


def role_constant(role: float, receiver_const: float) -> float:
    return (role - 3.0) * (receiver_const / 2.0)


def clamp_scale(value: float) -> float:
    return min(5.0, max(1.0, value))


def shifted_to_team_average(values: dict[str, float], weights: dict[str, float], target: float = 3.0) -> dict[str, float]:
    shifted = dict(values)
    for _ in range(12):
        total_w = sum(weights.get(k, 0.0) for k in shifted)
        if total_w <= 0:
            return {k: clamp_scale(v) for k, v in shifted.items()}
        avg = sum(clamp_scale(shifted[k]) * weights.get(k, 0.0) for k in shifted) / total_w
        delta = target - avg
        if abs(delta) < 0.0001:
            break
        for k in shifted:
            shifted[k] += delta
    return {k: clamp_scale(v) for k, v in shifted.items()}


def load_position_scales() -> dict[tuple[str, str], float]:
    positions: dict[tuple[str, str], float] = {}
    if not POSITIONS_CSV.exists():
        return positions
    with POSITIONS_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            probs = [
                float(row.get("p_pg") or 0),
                float(row.get("p_sg") or 0),
                float(row.get("p_sf") or 0),
                float(row.get("p_pf") or 0),
                float(row.get("p_c") or 0),
            ]
            denom = sum(probs)
            if denom <= 0:
                continue
            scale = sum((i + 1) * p for i, p in enumerate(probs)) / denom
            positions[(row["team"], norm_name(row["name"]))] = clamp_scale(scale)
    return positions


def iter_team_dirs(base: Path):
    for conf_dir in sorted(base.iterdir()):
        if not conf_dir.is_dir():
            continue
        for team_dir in sorted(conf_dir.iterdir()):
            if team_dir.is_dir():
                yield conf_dir.name, team_dir.name, team_dir


def parse_player_line(player: dict[str, Any]) -> tuple[str, dict[str, float]] | tuple[None, None]:
    name = clean_name(player.get("name", ""))
    stats = player.get("stats") or {}
    if not name:
        return None, None
    parsed: dict[str, float] = {}
    for key in STAT_KEYS:
        val = parse_int(stats.get(key))
        if val is None:
            return None, None
        parsed[key] = float(val)
    for split_key, made_key, att_key in (
        ("FGM-A", "FGM", "FGA"),
        ("3PM-A", "3PM", "3PA"),
        ("FTM-A", "FTM", "FTA"),
    ):
        made_attempt = parse_made_attempt(stats.get(split_key))
        if made_attempt is None:
            return None, None
        made, att = made_attempt
        parsed[made_key] = float(made)
        parsed[att_key] = float(att)
    if parsed["FGM"] < parsed["3PM"] or parsed["FGA"] < parsed["3PA"]:
        return None, None
    if parsed["REB"] != parsed["OREB"] + parsed["DREB"]:
        return None, None
    return name, parsed


def parse_team_box(players: list[dict[str, Any]]) -> tuple[dict[str, float], list[tuple[str, dict[str, float]]]] | tuple[None, None]:
    if not players:
        return None, None
    totals = {k: 0.0 for k in BASE_STATS}
    parsed_players: list[tuple[str, dict[str, float]]] = []
    for player in players:
        name, line = parse_player_line(player)
        if name is None or line is None:
            return None, None
        parsed_players.append((name, line))
        for key in BASE_STATS:
            totals[key] += line.get(key, 0.0)
    if totals["MIN"] <= 0 or totals["FGA"] <= 0:
        return None, None
    return totals, parsed_players


def add_totals(target: dict[str, float], source: dict[str, float]) -> None:
    for key in BASE_STATS:
        target[key] += source.get(key, 0.0)


def collect_strict_samples() -> dict[str, TeamSample]:
    samples: dict[str, TeamSample] = {}
    for conf, team, team_dir in iter_team_dirs(SCHEDULES_DIR):
        sample = TeamSample(conference=conf, team=team)
        samples[team] = sample
        for game_path in sorted(team_dir.glob("*/*.json")):
            sample.games_checked += 1
            try:
                game = json.load(game_path.open())
            except Exception:
                sample.games_rejected += 1
                sample.reject_reasons["invalid_json"] += 1
                continue
            teams = game.get("teams") or {}
            if team not in teams:
                sample.games_rejected += 1
                sample.reject_reasons["team_missing_from_box"] += 1
                continue
            opp = game.get("home") if game.get("visitor") == team else game.get("visitor")
            if not opp or opp not in teams:
                sample.games_rejected += 1
                sample.reject_reasons["opponent_missing_from_box"] += 1
                continue
            score = game.get("score") or {}
            if parse_int(score.get(team)) is None or parse_int(score.get(opp)) is None:
                sample.games_rejected += 1
                sample.reject_reasons["score_missing"] += 1
                continue

            team_totals, team_players = parse_team_box(teams[team])
            opp_totals, _opp_players = parse_team_box(teams[opp])
            if team_totals is None or team_players is None or opp_totals is None:
                sample.games_rejected += 1
                sample.reject_reasons["incomplete_player_box"] += 1
                continue
            if team_totals["MIN"] < 190 or opp_totals["MIN"] < 190 or abs(team_totals["MIN"] - opp_totals["MIN"]) > 15:
                sample.games_rejected += 1
                sample.reject_reasons["incomplete_minutes_total"] += 1
                continue

            team_score = float(parse_int(score[team]) or 0)
            opp_score = float(parse_int(score[opp]) or 0)
            if abs(team_totals["PTS"] - team_score) > 0.01 or abs(opp_totals["PTS"] - opp_score) > 0.01:
                sample.games_rejected += 1
                sample.reject_reasons["score_total_mismatch"] += 1
                continue

            sample.games_used += 1
            add_totals(sample.totals, team_totals)
            add_totals(sample.opp_totals, opp_totals)
            for raw_name, line in team_players:
                key = norm_name(raw_name)
                if key not in sample.players:
                    sample.players[key] = PlayerTotals(name=raw_name, clean_name=clean_name(raw_name))
                player = sample.players[key]
                player.games += 1
                for stat in BASE_STATS:
                    player.totals[stat] += line.get(stat, 0.0)
        if sample.games_checked == 0:
            sample.reject_reasons["no_game_files"] += 1
    return samples


def estimate_roles(sample: TeamSample) -> tuple[dict[str, float], dict[str, float]]:
    weights = {k: p.totals["MIN"] for k, p in sample.players.items()}

    role_raw: dict[str, float] = {}
    team_ast = sample.totals["AST"]
    team_tsa = sample.totals["FGA"] + 0.44 * sample.totals["FTA"]
    team_pts_per_tsa = safe_div(sample.totals["PTS"], team_tsa)
    threshold_pp_tsa = max(0.0, team_pts_per_tsa - 0.33)
    threshold_points_by_player: dict[str, float] = {}
    for key, player in sample.players.items():
        tsa = player.totals["FGA"] + 0.44 * player.totals["FTA"]
        threshold_points_by_player[key] = max(0.0, player.totals["PTS"] - threshold_pp_tsa * tsa)
    team_threshold_points = sum(threshold_points_by_player.values())
    for key, player in sample.players.items():
        ast_share = safe_div(player.totals["AST"], team_ast)
        threshold_share = safe_div(threshold_points_by_player[key], team_threshold_points)
        regressed = 6.00 - 6.642 * ast_share - 8.544 * threshold_share
        minutes = player.totals["MIN"]
        role_raw[key] = ((regressed * minutes) + (4.0 * 50.0)) / (minutes + 50.0)

    return shifted_to_team_average(role_raw, weights), weights


def fallback_position_from_box(player: PlayerTotals, sample: TeamSample) -> float:
    totals = player.totals
    team = sample.totals
    trb_share = safe_div(totals["REB"], team["REB"])
    stl_share = safe_div(totals["STL"], team["STL"])
    pf_share = safe_div(totals["PF"], team["PF"])
    ast_share = safe_div(totals["AST"], team["AST"])
    blk_share = safe_div(totals["BLK"], team["BLK"])
    regressed = 2.130 + 8.668 * trb_share - 2.486 * stl_share + 0.992 * pf_share - 3.536 * ast_share + 1.667 * blk_share
    minutes = totals["MIN"]
    return clamp_scale(((regressed * minutes) + (3.0 * 50.0)) / (minutes + 50.0))


def estimate_positions(sample: TeamSample, position_lookup: dict[tuple[str, str], float]) -> dict[str, float]:
    raw: dict[str, float] = {}
    weights = {k: p.totals["MIN"] for k, p in sample.players.items()}
    for key, player in sample.players.items():
        raw[key] = position_lookup.get((sample.team, key), fallback_position_from_box(player, sample))
    return shifted_to_team_average(raw, weights)


def raw_metric(per100: dict[str, float], position: float, role: float, coeffs: dict[str, tuple[float, float]], role_coeffs: dict[str, tuple[float, float]], pos_const_pg: float, role_const_receiver: float) -> float:
    value = 0.0
    for stat, (pg, c) in coeffs.items():
        value += interp(position, pg, c) * per100.get(stat, 0.0)
    for stat, (creator, receiver) in role_coeffs.items():
        value += interp(role, creator, receiver) * per100.get(stat, 0.0)
    value += position_constant(position, pos_const_pg)
    value += role_constant(role, role_const_receiver)
    return value


def calculate_bpm(
    samples: dict[str, TeamSample],
    min_minutes: float,
    min_pct: float,
    min_team_games: int,
    min_player_games: int,
    team_context_scale: float,
) -> dict[str, Any]:
    position_lookup = load_position_scales()
    usable_samples = {
        team: sample
        for team, sample in samples.items()
        if sample.games_used > 0 and possessions(sample.totals) > 0 and possessions(sample.opp_totals) > 0
    }
    league_points = sum(s.totals["PTS"] for s in usable_samples.values())
    league_possessions = sum(possessions(s.totals) for s in usable_samples.values())
    league_ortg = 100.0 * safe_div(league_points, league_possessions)

    rows: list[dict[str, Any]] = []
    teams_out: list[dict[str, Any]] = []
    for team, sample in sorted(usable_samples.items()):
        team_poss = possessions(sample.totals)
        opp_poss = possessions(sample.opp_totals)
        avg_poss = (team_poss + opp_poss) / 2.0
        team_ortg = 100.0 * safe_div(sample.totals["PTS"], avg_poss)
        team_drtg = 100.0 * safe_div(sample.opp_totals["PTS"], avg_poss)
        team_net = team_ortg - team_drtg
        team_bpm_target = team_net * team_context_scale
        team_off_target = (team_ortg - league_ortg) * team_context_scale

        positions = estimate_positions(sample, position_lookup)
        roles, _weights = estimate_roles(sample)

        player_calcs: list[dict[str, Any]] = []
        for key, player in sample.players.items():
            mp = player.totals["MIN"]
            poss_played = team_poss * safe_div(5.0 * mp, sample.totals["MIN"])
            if poss_played <= 0:
                continue
            per100 = {stat: 100.0 * safe_div(player.totals[stat], poss_played) for stat in BASE_STATS if stat != "MIN"}
            player_tsa = player.totals["FGA"] + 0.44 * player.totals["FTA"]
            team_tsa = sample.totals["FGA"] + 0.44 * sample.totals["FTA"]
            team_pts_per_tsa = safe_div(sample.totals["PTS"], team_tsa, 1.0)
            adjusted_points = player.totals["PTS"] + (1.0 - team_pts_per_tsa) * player_tsa
            per100["PTS"] = 100.0 * safe_div(adjusted_points, poss_played)
            position = positions[key]
            role = roles[key]
            raw_bpm = raw_metric(per100, position, role, BPM_COEFFS, BPM_ROLE_COEFFS, -0.818, 2.774)
            raw_obpm = raw_metric(per100, position, role, OBPM_COEFFS, OBPM_ROLE_COEFFS, -1.698, 0.860)
            player_calcs.append({
                "key": key,
                "player": player,
                "poss_played": poss_played,
                "mp_weight": safe_div(mp, sample.totals["MIN"]),
                "position": position,
                "role": role,
                "raw_bpm": raw_bpm,
                "raw_obpm": raw_obpm,
                "adjusted_points": adjusted_points,
            })

        raw_team_bpm = sum(p["raw_bpm"] * p["mp_weight"] for p in player_calcs)
        raw_team_obpm = sum(p["raw_obpm"] * p["mp_weight"] for p in player_calcs)
        team_bpm_adjust = team_bpm_target - raw_team_bpm
        team_obpm_adjust = team_off_target - raw_team_obpm

        teams_out.append({
            "conference": sample.conference,
            "team": team,
            "games_checked": sample.games_checked,
            "games_used": sample.games_used,
            "games_rejected": sample.games_rejected,
            "reject_reasons": dict(sample.reject_reasons),
            "strict_possessions": round(avg_poss, 1),
            "strict_ortg": round(team_ortg, 1),
            "strict_drtg": round(team_drtg, 1),
            "strict_net": round(team_net, 1),
            "bpm_team_target": round(team_bpm_target, 2),
            "obpm_team_target": round(team_off_target, 2),
            "team_bpm_adjustment": round(team_bpm_adjust, 3),
            "team_obpm_adjustment": round(team_obpm_adjust, 3),
        })

        for calc in player_calcs:
            player = calc["player"]
            mp = player.totals["MIN"]
            bpm = calc["raw_bpm"] + team_bpm_adjust
            obpm = calc["raw_obpm"] + team_obpm_adjust
            dbpm = bpm - obpm
            vorp = (bpm - (-2.0)) * (calc["poss_played"] / team_poss) * (sample.games_used / 82.0)
            rows.append({
                "conference": sample.conference,
                "team": team,
                "player": player.clean_name,
                "games": player.games,
                "strict_team_games": sample.games_used,
                "minutes": round(mp, 1),
                "mpg": round(safe_div(mp, player.games), 1),
                "min_pct": round(100.0 * safe_div(5.0 * mp, sample.totals["MIN"]), 1),
                "position_scale": round(calc["position"], 2),
                "creation_role": round(calc["role"], 2),
                "raw_bpm": round(calc["raw_bpm"], 2),
                "bpm": round(bpm, 2),
                "obpm": round(obpm, 2),
                "dbpm": round(dbpm, 2),
                "vorp_style": round(vorp, 3),
                "pts_per100": round(100.0 * safe_div(player.totals["PTS"], calc["poss_played"]), 1),
                "adj_pts_per100": round(100.0 * safe_div(calc["adjusted_points"], calc["poss_played"]), 1),
                "ast_per100": round(100.0 * safe_div(player.totals["AST"], calc["poss_played"]), 1),
                "reb_per100": round(100.0 * safe_div(player.totals["REB"], calc["poss_played"]), 1),
                "stl_per100": round(100.0 * safe_div(player.totals["STL"], calc["poss_played"]), 1),
                "blk_per100": round(100.0 * safe_div(player.totals["BLK"], calc["poss_played"]), 1),
                "to_per100": round(100.0 * safe_div(player.totals["TO"], calc["poss_played"]), 1),
                "qualifies_minutes": (
                    mp >= min_minutes
                    and (100.0 * safe_div(5.0 * mp, sample.totals["MIN"])) >= min_pct
                    and sample.games_used >= min_team_games
                    and player.games >= min_player_games
                ),
            })

    rows.sort(key=lambda r: (not r["qualifies_minutes"], -r["bpm"], -r["minutes"], r["team"], r["player"]))
    for i, row in enumerate([r for r in rows if r["qualifies_minutes"]], 1):
        row["rank"] = i
    for row in rows:
        row.setdefault("rank", None)
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "season": SEASON,
        "metric_name": "CCC BPM experimental",
        "strict_box_score_policy": {
            "accepted_game_requires": [
                "both teams present in game JSON",
                "score present for both teams",
                "every listed player has MIN, FGM-A, 3PM-A, FTM-A, OREB, DREB, REB, AST, STL, BLK, TO, PF, PTS",
                "made-attempt splits parse cleanly and makes do not exceed attempts",
                "player offensive + defensive rebounds equal total rebounds",
                "team player point totals match the listed final score",
            ],
            "note": "Season player/team totals are rebuilt only from accepted strict games.",
        },
        "league_context": {
            "teams_with_strict_games": len(usable_samples),
            "league_ortg_strict_sample": round(league_ortg, 3),
            "rank_qualification": {
                "min_strict_minutes": min_minutes,
                "min_strict_minutes_pct": min_pct,
                "min_strict_team_games": min_team_games,
                "min_strict_player_games": min_player_games,
            },
            "team_context_scale": team_context_scale,
            "scale_note": "Team net/offense targets are multiplied by team_context_scale before team adjustment so CCC sample extremes do not inflate BPM onto a non-comparable scale.",
        },
        "players": rows,
        "teams": sorted(teams_out, key=lambda x: (-x["games_used"], x["conference"], x["team"])),
    }


def write_outputs(result: dict[str, Any], output_prefix: Path) -> None:
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = output_prefix.with_suffix(".json")
    csv_path = output_prefix.with_suffix(".csv")
    teams_csv_path = output_prefix.parent / f"{output_prefix.name}_team_audit.csv"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    player_fields = [
        "rank", "conference", "team", "player", "games", "strict_team_games",
        "minutes", "mpg", "min_pct", "position_scale", "creation_role",
        "raw_bpm", "bpm", "obpm", "dbpm", "vorp_style",
        "pts_per100", "adj_pts_per100", "ast_per100", "reb_per100", "stl_per100", "blk_per100", "to_per100",
        "qualifies_minutes",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=player_fields)
        writer.writeheader()
        for row in result["players"]:
            writer.writerow({k: row.get(k) for k in player_fields})
    team_fields = [
        "conference", "team", "games_checked", "games_used", "games_rejected",
        "strict_possessions", "strict_ortg", "strict_drtg", "strict_net",
        "bpm_team_target", "obpm_team_target",
        "team_bpm_adjustment", "team_obpm_adjustment", "reject_reasons",
    ]
    with teams_csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=team_fields)
        writer.writeheader()
        for row in result["teams"]:
            writer.writerow({k: row.get(k) for k in team_fields})
    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"Saved: {teams_csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute strict in-house CCC BPM-style player ratings")
    parser.add_argument("--min-minutes", type=float, default=0.0, help="Minimum strict-sample minutes for ranked qualification")
    parser.add_argument("--min-pct", type=float, default=30.0, help="Minimum strict-sample team minutes percentage for ranked qualification")
    parser.add_argument("--min-team-games", type=int, default=18, help="Minimum accepted strict team games for ranked qualification")
    parser.add_argument("--min-player-games", type=int, default=5, help="Minimum accepted strict player games for ranked qualification")
    parser.add_argument("--team-context-scale", type=float, default=0.40, help="Scale strict team rating gaps before BPM team adjustment")
    parser.add_argument("--season", default="2025-26", help="Season year prefix, e.g. 2024-25 (points at that season's stats/schedules/positions)")
    parser.add_argument("--output-prefix", default=None, help="Output prefix for JSON/CSV (default: internal_data/ccc_bpm_<season>)")
    args = parser.parse_args()

    default_prefix = _set_season(args.season)
    out_prefix = Path(args.output_prefix) if args.output_prefix else default_prefix

    samples = collect_strict_samples()
    result = calculate_bpm(
        samples,
        args.min_minutes,
        args.min_pct,
        args.min_team_games,
        args.min_player_games,
        args.team_context_scale,
    )
    write_outputs(result, out_prefix)
    qualified = [p for p in result["players"] if p["qualifies_minutes"]]
    print(f"Strict teams: {result['league_context']['teams_with_strict_games']}")
    print(f"Players: {len(result['players'])}; qualified: {len(qualified)}")
    print("Top 10 qualified BPM:")
    for row in qualified[:10]:
        print(f"  {row['rank']:>2}. {row['player']} ({row['team']}) BPM {row['bpm']:+.2f}, OBPM {row['obpm']:+.2f}, DBPM {row['dbpm']:+.2f}")


if __name__ == "__main__":
    main()
