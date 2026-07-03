#!/usr/bin/env python3
"""
Generate season statistics from scraped box score data.

Reads box scores from '2022-23 Teams Schedules/<Team>/' and writes
aggregated stats to '2022-23 Team Statistics/<Team>/'.

Usage:
    python generate_team_stats_2022.py --teams Moorpark Ventura
    python generate_team_stats_2022.py --all
"""

import argparse
import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

SCHEDULES_DIR = Path("2022-23 Teams Schedules")
STATS_DIR = Path("2022-23 Team Statistics")

# Alias map: abbreviated box score keys -> canonical team names
# Add new entries here as unknown codes are encountered.
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
    "IVCMEN": "Irvine Valley",
    "SOUTHWES": "Southwestern",
    "MIRACOST": "MiraCosta",
    "CHAFFEYM": "Chaffey",
    "CMC-MBB": "Copper Mountain",
    "COSO-MB": "Cerro Coso",
    "LASW-MB": "LA Southwest",
    "MSJC-MB": "Mt. San Jacinto",
    "PALO-MB": "Palomar",
    "SADD-MB": "Saddleback",
    "SBVC-MB": "San Bernardino Valley",
    "VVC-MB": "Victor Valley",
    "BAR-MB": "Barstow",
    "LA City": "Los Angeles City",
    "LA City College": "Los Angeles City",
    "Long Beach City": "Long Beach",
    "Bakersfield College": "Bakersfield",
    "El Camino College": "El Camino",
    "Pasadena City College": "Pasadena City",
    "San Diego Mesa College": "San Diego Mesa",
    "College of the Canyons": "Canyons",
    "West Hills Coalinga": "Coalinga",
    "West Hills Lemoore": "Lemoore",
    # Additional display-name variants found in 2022-23 box scores
    "Copper Mountian": "Copper Mountain",
    "Goldenwest": "Golden West",
    "MSJC": "Mt. San Jacinto",
    "West Hills (Lemoore)": "West Hills Lemoore",
}

_CANONICAL_TEAMS = None


def _canonical_teams():
    """Return all canonical team names for the current season."""
    global _CANONICAL_TEAMS
    if _CANONICAL_TEAMS is None:
        _CANONICAL_TEAMS = sorted((team_name for team_name, _ in all_teams()), key=len, reverse=True)
    return _CANONICAL_TEAMS


def _normalize_team_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _resolve_team_name(name: str) -> str:
    normalized_name = _normalize_team_name(name)
    for team_name in _canonical_teams():
        normalized_team = _normalize_team_name(team_name)
        if (
            normalized_name == normalized_team
            or normalized_name.startswith(normalized_team + " ")
            or normalized_team.endswith(" " + normalized_name)
        ):
            return team_name
    alias = TEAM_ALIASES.get(name)
    if alias:
        return alias
    return name


def find_team_sched(team_name):
    """Find a team's schedule directory (searching conference subfolders)."""
    for conf_dir in sorted(SCHEDULES_DIR.iterdir()):
        if conf_dir.is_dir():
            candidate = conf_dir / team_name
            if candidate.is_dir():
                return candidate, conf_dir.name
    return None, None


def all_teams():
    """Yield (team_name, conference) for all teams in schedule folders."""
    for conf_dir in sorted(SCHEDULES_DIR.iterdir()):
        if conf_dir.is_dir():
            for team_dir in sorted(conf_dir.iterdir()):
                if team_dir.is_dir():
                    yield team_dir.name, conf_dir.name


def parse_made_att(val: str):
    """Parse '5-10' into (made, attempted)."""
    m = re.match(r"(\d+)-(\d+)", val)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def normalize_player_name(name: str) -> str:
    """Normalize player name: '#03 Smith' / 'g 03 Smith' / 'F 3 Smith' -> '#3 Smith'."""
    m = re.match(r'[gfc#]+\s*0*(\d+)\s+(.*)', name, re.IGNORECASE)
    if m:
        return f"#{m.group(1)} {m.group(2)}"
    if name.startswith("TM "):
        return name
    return name


def _player_merge_key(name: str) -> str:
    """Strip jersey number: '#23 Dylan Griffin' -> 'Dylan Griffin'."""
    m = re.match(r'#\d+\s+(.*)', name)
    return m.group(1) if m else name


def _game_minutes(bs: dict) -> int:
    """Determine game length in minutes: 40 for regulation + 5 per OT period."""
    if "game_minutes" in bs:
        return bs["game_minutes"]
    total_min = 0
    count = 0
    for team_players in bs.get("teams", {}).values():
        team_min = sum(
            int(p.get("stats", {}).get("MIN", "0"))
            for p in team_players
            if p.get("stats") and not p.get("name", "").startswith("TM")
        )
        total_min += team_min
        count += 1
    if count == 0:
        return 40
    avg_team_min = total_min / count
    ot_periods = max(0, round((avg_team_min - 200) / 25))
    return 40 + 5 * ot_periods


def _find_team_key(team_name: str, bs: dict) -> str | None:
    """Find the matching team key in a box score's teams dict."""
    for key in bs.get("teams", {}):
        if key.lower() == team_name.lower():
            return key
    for key in bs.get("teams", {}):
        if team_name.lower() in key.lower() or key.lower() in team_name.lower():
            return key
    for key in bs.get("teams", {}):
        if _resolve_team_name(key).lower() == team_name.lower():
            return key
    return None


def _find_opponent_key(team_name: str, bs: dict) -> str | None:
    """Find the opponent's team key in a box score's teams dict."""
    team_key = _find_team_key(team_name, bs)
    for key in bs.get("teams", {}):
        if key != team_key:
            return key
    return None


def _sum_team_box(players: list[dict]) -> dict:
    """Sum all player stats from a single box score into team totals for one game."""
    totals = {
        "FGM": 0, "FGA": 0, "3PM": 0, "3PA": 0, "FTM": 0, "FTA": 0,
        "OREB": 0, "DREB": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0,
        "TO": 0, "PF": 0, "PTS": 0,
    }
    for player in players:
        name = normalize_player_name(player.get("name", ""))
        if name.startswith("TM "):
            continue
        s = player.get("stats", {})
        if not s:
            continue
        fgm, fga = parse_made_att(s.get("FGM-A", "0-0"))
        tpm, tpa = parse_made_att(s.get("3PM-A", "0-0"))
        ftm, fta = parse_made_att(s.get("FTM-A", "0-0"))
        totals["FGM"] += fgm; totals["FGA"] += fga
        totals["3PM"] += tpm; totals["3PA"] += tpa
        totals["FTM"] += ftm; totals["FTA"] += fta
        for stat in ("OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS"):
            try:
                totals[stat] += int(s.get(stat, "0"))
            except ValueError:
                pass
    return totals


def aggregate_opponent_stats(team_name: str, boxscores: list[dict]) -> dict:
    """Aggregate opponent totals across all games."""
    season = {
        "games": 0,
        "FGM": 0, "FGA": 0, "3PM": 0, "3PA": 0, "FTM": 0, "FTA": 0,
        "OREB": 0, "DREB": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0,
        "TO": 0, "PF": 0, "PTS": 0,
    }
    for bs in boxscores:
        opp_key = _find_opponent_key(team_name, bs)
        if not opp_key:
            continue
        team_key = _find_team_key(team_name, bs)
        if not team_key or not bs["teams"].get(team_key):
            continue
        game_totals = _sum_team_box(bs["teams"][opp_key])
        if game_totals.get("FGA", 0) == 0 and game_totals.get("PTS", 0) == 0:
            continue
        season["games"] += 1
        for k in game_totals:
            season[k] += game_totals[k]
    return season


def aggregate_player_stats(team_name: str, boxscores: list[dict]) -> dict:
    """Aggregate per-player season stats from a list of box score dicts."""
    players = defaultdict(lambda: {
        "games": 0, "MIN": 0,
        "FGM": 0, "FGA": 0, "3PM": 0, "3PA": 0, "FTM": 0, "FTA": 0,
        "OREB": 0, "DREB": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0,
        "TO": 0, "PF": 0, "PTS": 0,
    })

    for bs in boxscores:
        team_key = _find_team_key(team_name, bs)
        if not team_key:
            continue

        for player in bs["teams"][team_key]:
            name = normalize_player_name(player["name"])
            if name.startswith("TM "):
                continue
            s = player.get("stats", {})
            if not s:
                continue

            key = _player_merge_key(name)
            p = players[key]
            p["games"] += 1

            try:
                p["MIN"] += int(s.get("MIN", "0"))
            except ValueError:
                pass

            fgm, fga = parse_made_att(s.get("FGM-A", "0-0"))
            tpm, tpa = parse_made_att(s.get("3PM-A", "0-0"))
            ftm, fta = parse_made_att(s.get("FTM-A", "0-0"))
            p["FGM"] += fgm; p["FGA"] += fga
            p["3PM"] += tpm; p["3PA"] += tpa
            p["FTM"] += ftm; p["FTA"] += fta

            for stat in ("OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS"):
                try:
                    p[stat] += int(s.get(stat, "0"))
                except ValueError:
                    pass

    return dict(players)


def compute_team_totals(player_stats: dict, boxscores: list[dict] | None = None) -> dict:
    """Sum all player stats into team totals."""
    totals = {
        "games": 0, "MIN": 0,
        "FGM": 0, "FGA": 0, "3PM": 0, "3PA": 0, "FTM": 0, "FTA": 0,
        "OREB": 0, "DREB": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0,
        "TO": 0, "PF": 0, "PTS": 0,
    }
    max_games = 0
    for p in player_stats.values():
        max_games = max(max_games, p["games"])
        for k in totals:
            if k not in ("games", "MIN"):
                totals[k] += p[k]
    totals["games"] = max_games
    if boxscores:
        totals["MIN"] = sum(_game_minutes(bs) for bs in boxscores)
    return totals


def compute_averages(stats: dict) -> dict:
    """Compute per-game averages."""
    g = stats["games"]
    if g == 0:
        return {}
    avgs = {}
    for k, v in stats.items():
        if k == "games":
            avgs[k] = g
        else:
            avgs[k] = round(v / g, 1)
    avgs["FG%"] = round(stats["FGM"] / stats["FGA"] * 100, 1) if stats["FGA"] else 0.0
    avgs["3P%"] = round(stats["3PM"] / stats["3PA"] * 100, 1) if stats["3PA"] else 0.0
    avgs["FT%"] = round(stats["FTM"] / stats["FTA"] * 100, 1) if stats["FTA"] else 0.0
    return avgs


def compute_game_log(team_name: str, boxscores: list[dict], schedule: dict) -> list[dict]:
    """Build a per-game log with team totals and opponent totals."""
    schedule_map = {}
    month_names = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                   "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    for g in schedule.get("games", []):
        raw = g.get("date", "")
        parts = raw.split()
        if len(parts) == 2 and parts[0].lower()[:3] in month_names:
            m = month_names[parts[0].lower()[:3]]
            d = int(parts[1])
            schedule_map[(m, d)] = g

    def _bs_date_key(date_str):
        parts = date_str.split("/")
        if len(parts) >= 2:
            return (int(parts[0]), int(parts[1]))
        return None

    def _resolve_alias(name):
        return _resolve_team_name(name)

    def _is_team(name):
        resolved = _resolve_alias(name)
        if resolved.lower() == team_name.lower():
            return True
        return team_name.lower() in resolved.lower() or resolved.lower() in team_name.lower()

    game_log = []
    for bs in boxscores:
        entry = {
            "date": bs.get("date", ""),
            "visitor": bs.get("visitor", ""),
            "home": bs.get("home", ""),
        }

        if _is_team(bs.get("home", "")):
            opponent = _resolve_alias(bs.get("visitor", ""))
            entry["location"] = "Home"
        elif _is_team(bs.get("visitor", "")):
            opponent = _resolve_alias(bs.get("home", ""))
            entry["location"] = "Away"
        else:
            opponent = _resolve_alias(bs.get("home", ""))
            entry["location"] = "Away"
        entry["opponent"] = opponent

        scores = bs.get("score", {})
        team_score = 0
        opp_score = 0
        for k, v in scores.items():
            if _is_team(k):
                team_score = v
            else:
                opp_score = v
        entry["team_score"] = team_score
        entry["opponent_score"] = opp_score
        entry["result"] = "W" if team_score > opp_score else "L" if team_score < opp_score else "T"

        entry["MIN"] = _game_minutes(bs)

        date_key = _bs_date_key(entry["date"])
        sched_entry = schedule_map.get(date_key, {}) if date_key else {}
        entry["is_conference"] = sched_entry.get("is_conference", False)
        ha = sched_entry.get("home_away", "")
        if ha == "neutral":
            entry["location"] = "Neutral"

        team_key = _find_team_key(team_name, bs)
        opp_key = _find_opponent_key(team_name, bs)
        if team_key:
            entry["team_stats"] = _sum_team_box(bs["teams"][team_key])
        if opp_key:
            entry["opponent_stats"] = _sum_team_box(bs["teams"][opp_key])

        sched_team_score = sched_entry.get("team_score")
        sched_opp_score = sched_entry.get("opponent_score")
        if (entry.get("team_score") in (0, None)) and isinstance(sched_team_score, int) and sched_team_score > 0:
            entry["team_score"] = sched_team_score
        if (entry.get("opponent_score") in (0, None)) and isinstance(sched_opp_score, int) and sched_opp_score > 0:
            entry["opponent_score"] = sched_opp_score

        team_pts = entry.get("team_stats", {}).get("PTS", 0)
        opp_pts = entry.get("opponent_stats", {}).get("PTS", 0)
        if (entry.get("team_score") in (0, None)) and team_pts > 0:
            entry["team_score"] = team_pts
        if (entry.get("opponent_score") in (0, None)) and opp_pts > 0:
            entry["opponent_score"] = opp_pts
        if entry["team_score"] > entry["opponent_score"]:
            entry["result"] = "W"
        elif entry["team_score"] < entry["opponent_score"]:
            entry["result"] = "L"
        else:
            entry["result"] = "T"

        game_log.append(entry)

    return game_log


def generate_stats(team_name: str, conference: str = None):
    """Generate all stats for a team and save to the stats directory."""
    if conference:
        team_sched_dir = SCHEDULES_DIR / conference / team_name
    else:
        team_sched_dir, conference = find_team_sched(team_name)
    if not team_sched_dir or not team_sched_dir.exists():
        print(f"No schedule data found for {team_name}")
        return

    schedule = {}
    sched_path = team_sched_dir / "schedule.json"
    if sched_path.exists():
        with open(sched_path) as f:
            schedule = json.load(f)

    boxscores = []
    for game_dir in sorted(team_sched_dir.iterdir()):
        if not game_dir.is_dir():
            continue
        for bs_file in game_dir.glob("*.json"):
            with open(bs_file) as f:
                boxscores.append(json.load(f))

    if not boxscores:
        print(f"No box scores found for {team_name}")
        return

    print(f"Processing {team_name}: {len(boxscores)} games...")

    month_names = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                   "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    schedule_map = {}
    for g in schedule.get("games", []):
        raw = g.get("date", "")
        parts = raw.split()
        if len(parts) == 2 and parts[0].lower()[:3] in month_names:
            m = month_names[parts[0].lower()[:3]]
            d = int(parts[1])
            schedule_map[(m, d)] = g

    def _bs_date_key(date_str):
        parts = date_str.split("/")
        if len(parts) >= 2:
            return (int(parts[0]), int(parts[1]))
        return None

    def _is_conference_game(bs):
        date_key = _bs_date_key(bs.get("date", ""))
        sched_entry = schedule_map.get(date_key, {}) if date_key else {}
        return sched_entry.get("is_conference", False)

    player_stats = aggregate_player_stats(team_name, boxscores)

    player_list = []
    for name, totals in sorted(player_stats.items(), key=lambda x: -x[1]["PTS"]):
        entry = {"name": name, "totals": totals, "averages": compute_averages(totals)}
        player_list.append(entry)

    team_totals = compute_team_totals(player_stats, boxscores)
    team_averages = compute_averages(team_totals)

    opp_totals = aggregate_opponent_stats(team_name, boxscores)
    if opp_totals["games"] > 0:
        opp_totals["MIN"] = team_totals["MIN"]
    opp_averages = compute_averages(opp_totals) if opp_totals["games"] > 0 else {}

    game_log = compute_game_log(team_name, boxscores, schedule)

    conf_boxscores = [bs for bs in boxscores if _is_conference_game(bs)]
    conf_player_stats = aggregate_player_stats(team_name, conf_boxscores)
    conf_player_list = []
    for name, totals in sorted(conf_player_stats.items(), key=lambda x: -x[1]["PTS"]):
        entry = {"name": name, "totals": totals, "averages": compute_averages(totals)}
        conf_player_list.append(entry)
    conf_team_totals = compute_team_totals(conf_player_stats, conf_boxscores)
    conf_team_averages = compute_averages(conf_team_totals)
    conf_opp_totals = aggregate_opponent_stats(team_name, conf_boxscores)
    if conf_opp_totals["games"] > 0:
        conf_opp_totals["MIN"] = conf_team_totals["MIN"]
    conf_opp_averages = compute_averages(conf_opp_totals) if conf_opp_totals["games"] > 0 else {}

    conf_record = {}
    for k, v in schedule.get("records", {}).items():
        if "conference" in k.lower():
            conf_record[k] = v

    output = {
        "team_name": team_name,
        "generated": datetime.now().isoformat(),
        "games_played": team_totals["games"],
        "record": schedule.get("records", {}),
        "team_totals": team_totals,
        "team_averages": team_averages,
        "opponent_totals": opp_totals,
        "opponent_averages": opp_averages,
        "players": player_list,
        "game_log": game_log,
    }

    team_stats_dir = STATS_DIR / conference / team_name
    team_stats_dir.mkdir(parents=True, exist_ok=True)

    with open(team_stats_dir / "season_stats.json", "w") as f:
        json.dump(output, f, indent=2)

    with open(team_stats_dir / "player_stats.json", "w") as f:
        json.dump({"team": team_name, "players": player_list}, f, indent=2)

    summary = {
        "team": team_name,
        "games_played": team_totals["games"],
        "record": schedule.get("records", {}),
        "totals": team_totals,
        "averages": team_averages,
        "opponent_totals": opp_totals,
        "opponent_averages": opp_averages,
    }
    with open(team_stats_dir / "team_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    with open(team_stats_dir / "game_log.json", "w") as f:
        json.dump({"team": team_name, "games": game_log}, f, indent=2)

    conf_output = {
        "team": team_name,
        "conference": conference,
        "games_played": conf_team_totals["games"],
        "record": conf_record,
        "totals": conf_team_totals,
        "averages": conf_team_averages,
        "opponent_totals": conf_opp_totals,
        "opponent_averages": conf_opp_averages,
        "players": conf_player_list,
    }
    with open(team_stats_dir / "conference_stats.json", "w") as f:
        json.dump(conf_output, f, indent=2)

    total_kb = sum(f.stat().st_size for f in team_stats_dir.glob("*.json")) / 1024
    conf_games = conf_team_totals["games"]
    print(f"  Saved: {team_stats_dir}/ — {len(player_list)} players, "
          f"{len(game_log)} games, {conf_games} conf games ({total_kb:.1f} KB)")


def main():
    parser = argparse.ArgumentParser(description="Generate 2023-24 team statistics from box scores")
    parser.add_argument("--teams", nargs="+", help="Team names to process")
    parser.add_argument("--all", action="store_true", help="Process all teams in schedules folder")
    args = parser.parse_args()

    if args.all:
        teams = list(all_teams())
    elif args.teams:
        teams = [(t, None) for t in args.teams]
    else:
        parser.print_help()
        return

    for team_name, conf in teams:
        generate_stats(team_name, conf)


if __name__ == "__main__":
    main()
