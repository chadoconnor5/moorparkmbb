from __future__ import annotations

from pathlib import Path
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime


# ---------------------------------------------------------------------------
# Storylines helpers (inlined from generate_game_storylines.py)
# ---------------------------------------------------------------------------

@dataclass
class _RunningRating:
    # Optionally seeded with a prior NET rating (e.g. decayed prior season) that
    # linearly fades to zero once `fade_games` real games have been played.
    def __init__(self, prior_net: float = 0.0, fade_games: int = 5):
        self.ortg_sum: float = 0.0
        self.drtg_sum: float = 0.0
        self.games: int = 0
        self.prior_net: float = prior_net
        self._fade_games: int = fade_games

    @property
    def net(self) -> float:
        if self.games == 0:
            return self.prior_net
        observed = (self.ortg_sum - self.drtg_sum) / self.games
        if self.games >= self._fade_games:
            return observed
        fade = 1.0 - self.games / self._fade_games
        return (1.0 - fade) * observed + fade * self.prior_net

    def update(self, ortg: float, drtg: float) -> None:
        self.ortg_sum += ortg
        self.drtg_sum += drtg
        self.games += 1


def _sl_parse_date(s: str) -> datetime:
    s = s.strip("'\"")
    if "-" in s and "/" not in s:
        # YYYY-MM-DD format
        y, m, d = s.split("-")
    else:
        m, d, y = s.split("/")
    return datetime(int(y), int(m), int(d))


def _sl_date_sort_key(date_str: str) -> tuple:
    try:
        s = date_str.strip("'\"")
        if "-" in s and "/" not in s:
            y, m, d = s.split("-")
        else:
            m, d, y = s.split("/")
        return (int(y), int(m), int(d))
    except Exception:
        return (0, 0, 0)


def _sl_logistic(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def _sl_safe_possessions(ts: dict, os_: dict):
    t_broken = ts.get("FGA", 0) == 0 and ts.get("PTS", 0) == 0
    o_broken = os_.get("FGA", 0) == 0 and os_.get("PTS", 0) == 0
    if t_broken and o_broken:
        return None
    def _poss(s): return (s.get("FGA", 0) - s.get("OREB", 0)) + s.get("TO", 0) + 0.475 * s.get("FTA", 0)
    tp, op = _poss(ts), _poss(os_)
    if t_broken or tp <= 0: return op if op > 0 else None
    if o_broken or op <= 0: return tp if tp > 0 else None
    return (tp + op) / 2


def _compute_game_ff(ts: dict, os_: dict, poss: float, game_min: int = 40) -> dict:
    """Compute per-game four-factor stats from box scores."""
    fga = ts.get('FGA', 0)
    if fga == 0 or poss <= 0:
        return {}
    fgm = ts.get('FGM', 0); tpm = ts.get('3PM', 0); tpa = ts.get('3PA', 0)
    fta = ts.get('FTA', 0); oreb = ts.get('OREB', 0); dreb = ts.get('DREB', 0)
    to_ = ts.get('TO', 0)
    o_fga = os_.get('FGA', 0); o_fgm = os_.get('FGM', 0); o_tpm = os_.get('3PM', 0)
    o_tpa = os_.get('3PA', 0); o_fta = os_.get('FTA', 0)
    o_oreb = os_.get('OREB', 0); o_to = os_.get('TO', 0)
    min_ = max(game_min, 40)
    pace = round(poss * (40.0 / min_), 1)
    return {
        'pace': pace,
        'o_efg': round((fgm + 0.5 * tpm) / max(fga, 1) * 100, 1),
        'o_tov': round(to_ / max(fga + 0.475 * fta + to_, 1) * 100, 1),
        'o_or':  round(oreb / max(oreb + o_oreb, 1) * 100, 1),  # opponent's OREB as def rebound
        'o_ftr': round(fta / max(fga, 1) * 100, 1),
        'o_2p':  round((fgm - tpm) / max(fga - tpa, 1) * 100, 1) if (fga - tpa) > 0 else 0.0,
        'o_3p':  round(tpm / max(tpa, 1) * 100, 1) if tpa > 0 else 0.0,
        'd_efg': round((o_fgm + 0.5 * o_tpm) / max(o_fga, 1) * 100, 1),
        'd_tov': round(o_to / max(o_fga + 0.475 * o_fta + o_to, 1) * 100, 1),
        'd_or':  round(o_oreb / max(o_oreb + dreb, 1) * 100, 1),
        'd_ftr': round(o_fta / max(o_fga, 1) * 100, 1),
        'd_2p':  round((o_fgm - o_tpm) / max(o_fga - o_tpa, 1) * 100, 1) if (o_fga - o_tpa) > 0 else 0.0,
        'd_3p':  round(o_tpm / max(o_tpa, 1) * 100, 1) if o_tpa > 0 else 0.0,
    }

    return (tp + op) / 2


def _sl_infer_ot(minutes) -> int:
    if minutes is None or minutes <= 40: return 0
    if minutes > 65: return 0  # corrupted MIN value, treat as regulation
    return max(0, int(round((minutes - 40) / 5)))


def _sl_load_games(stats_dir: Path) -> tuple[dict, set]:
    by_team: dict[str, list] = {}
    team_names: set[str] = set()
    for conf_dir in sorted(stats_dir.iterdir()):
        if not conf_dir.is_dir(): continue
        for team_dir in sorted(conf_dir.iterdir()):
            if not team_dir.is_dir(): continue
            gl = team_dir / "game_log.json"
            if not gl.exists(): continue
            data = json.load(open(gl))
            team = data.get("team", team_dir.name)
            by_team[team] = data.get("games", [])
            team_names.add(team)
    return by_team, team_names


def _sl_load_priors(prior_stats_dir: Path, decay: float = 0.60) -> dict:
    """Load decayed NET ratings from a prior season to seed _RunningRating."""
    priors: dict[str, float] = {}
    if not prior_stats_dir.exists():
        return priors
    for conf_dir in sorted(prior_stats_dir.iterdir()):
        if not conf_dir.is_dir(): continue
        for team_dir in sorted(conf_dir.iterdir()):
            if not team_dir.is_dir(): continue
            adv_path = team_dir / "advanced_analytics.json"
            if not adv_path.exists(): continue
            try:
                adv = json.load(open(adv_path))
                net = adv.get("team", {}).get("net_rtg")
                if net is not None:
                    priors[team_dir.name] = net * decay
            except Exception:
                pass
    return priors


def _sl_dedupe(by_team: dict, system_teams: set, exclude_zero: bool) -> list:
    unique: dict = {}
    for team in sorted(by_team):
        for g in by_team[team]:
            opp = g.get("opponent", "")
            if opp not in system_teams: continue
            date_str = g.get("date", "")
            pair = tuple(sorted([team, opp]))
            key = (date_str, pair[0], pair[1])
            if key in unique: continue
            ts = g.get("team_stats") or {}
            os_ = g.get("opponent_stats") or {}
            poss = _sl_safe_possessions(ts, os_)
            if not poss or poss <= 0: continue
            ts_, os = g.get("team_score", 0), g.get("opponent_score", 0)
            if exclude_zero and (ts_ == 0 or os == 0): continue
            mins = g.get("MIN", 40)
            t_ortg, t_drtg = (ts_ / poss) * 100, (os / poss) * 100
            o_ortg, o_drtg = (os / poss) * 100, (ts_ / poss) * 100
            if ts_ >= os:
                winner, loser, ws, ls = team, opp, ts_, os
                w_ortg, w_drtg = t_ortg, t_drtg
            else:
                winner, loser, ws, ls = opp, team, os, ts_
                w_ortg, w_drtg = o_ortg, o_drtg
            loc = (g.get("location") or "").strip().lower()
            home = team if loc == "home" else (opp if loc == "away" else None)
            unique[key] = {
                "date": date_str, "date_obj": _sl_parse_date(date_str),
                "team": team, "opponent": opp,
                "winner": winner, "loser": loser,
                "winner_score": ws, "loser_score": ls,
                "margin": abs(ws - ls), "minutes": mins,
                "overtimes": _sl_infer_ot(mins), "possessions": poss,
                "team_ortg": t_ortg, "team_drtg": t_drtg,
                "opp_ortg": o_ortg, "opp_drtg": o_drtg,
                "winner_ortg": w_ortg, "winner_drtg": w_drtg,
                "winner_game_net": w_ortg - w_drtg, "home_team": home,
            }
    games = list(unique.values())
    games.sort(key=lambda g: (g["date_obj"], min(g["team"], g["opponent"]), max(g["team"], g["opponent"])))
    return games


def _sl_enrich(games: list, teams: set, hca: float, wps: float, priors: dict = None) -> list:
    priors = priors or {}
    ratings = {t: _RunningRating(prior_net=priors.get(t, 0.0)) for t in teams}
    enriched = []
    for g in games:
        a, b = g["team"], g["opponent"]
        pre_a, pre_b = ratings[a].net, ratings[b].net
        games_a, games_b = ratings[a].games, ratings[b].games
        winner, loser = g["winner"], g["loser"]
        w_pre = pre_a if winner == a else pre_b
        l_pre = pre_b if winner == a else pre_a
        w_games = games_a if winner == a else games_b
        l_games = games_b if winner == a else games_a
        hca_a = hca if g.get("home_team") == a else (-hca if g.get("home_team") == b else 0.0)
        pred_a = (pre_a - pre_b) + hca_a
        wp_a = _sl_logistic(pred_a / max(wps, 1e-6))
        w_wp = wp_a if winner == a else (1.0 - wp_a)
        margin, w_net, ots = g["margin"], g["winner_game_net"], g["overtimes"]
        pre_gap = w_pre - l_pre
        closeness = 1.0 - abs(wp_a - 0.5) * 2.0
        enriched.append({
            "date": g["date"], "winner": winner, "loser": loser,
            "score": f"{g['winner_score']}-{g['loser_score']}",
            "margin": margin, "minutes": g["minutes"], "overtimes": ots,
            "possessions": round(g["possessions"], 1),
            "winner_ortg": round(g["winner_ortg"], 1), "winner_drtg": round(g["winner_drtg"], 1),
            "winner_game_net": round(w_net, 1),
            "pregame_winner_net": round(w_pre, 1), "pregame_loser_net": round(l_pre, 1),
            "pregame_winner_games": w_games, "pregame_loser_games": l_games,
            "pregame_gap": round(pre_gap, 1), "underdog_gap": round(max(0.0, l_pre - w_pre), 1),
            "pregame_model_margin_a": round(pred_a, 2), "pregame_model_wp_winner": round(w_wp, 3),
            "home_team": g.get("home_team"),
            "dominance_score": round(margin * (1.0 + math.tanh(l_pre / 20.0)) * 0.50 + w_net * 0.25, 2),
            "upset_score": round(100.0 * (1.0 - w_wp) + 0.20 * margin, 2),
            "tension_score": round(100.0 / (1.0 + abs(w_net)) + 40.0 / (1.0 + margin) + 12.0 * ots, 2),
            "bust_score": round(1.8 * margin * (1.0 + closeness) / (1.0 + abs(pred_a)), 2),
            "fanmatch_score": round(100.0 * closeness, 2),
        })
        ratings[a].update(g["team_ortg"], g["team_drtg"])
        ratings[b].update(g["opp_ortg"], g["opp_drtg"])
    return enriched


def _sl_top_n(rows: list, key: str, n: int, predicate=None) -> list:
    sel = rows if predicate is None else [r for r in rows if predicate(r)]
    return sorted(sel, key=lambda r: r[key], reverse=True)[:n]


def _sl_load_line_of_night(sched_dir: Path, game_dates: set) -> dict:
    """Find the best individual performance (Hollinger game score) per date."""
    import re
    lotn: dict = {}
    if not sched_dir.exists():
        return lotn

    def parse_split(s):
        parts = str(s).split('-')
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except Exception:
                pass
        return 0, 0

    seen_files: set = set()
    for conf_dir in sorted(sched_dir.iterdir()):
        if not conf_dir.is_dir():
            continue
        for team_dir in sorted(conf_dir.iterdir()):
            if not team_dir.is_dir():
                continue
            for game_dir in sorted(team_dir.iterdir()):
                if not game_dir.is_dir():
                    continue
                for json_file in game_dir.glob('*.json'):
                    canon = str(json_file.resolve())
                    if canon in seen_files:
                        continue
                    seen_files.add(canon)
                    try:
                        data = json.load(open(json_file))
                        date_str = data.get('date', '')
                        if not date_str or date_str not in game_dates:
                            continue
                        for team_name, players in data.get('teams', {}).items():
                            for p in players:
                                name_raw = p.get('name', '')
                                if name_raw.upper().startswith('TM '):
                                    continue
                                stats = p.get('stats', {})
                                try:
                                    pts  = int(stats.get('PTS', 0) or 0)
                                    oreb = int(stats.get('OREB', 0) or 0)
                                    dreb = int(stats.get('DREB', 0) or 0)
                                    reb  = int(stats.get('REB', 0) or 0)
                                    ast  = int(stats.get('AST', 0) or 0)
                                    stl  = int(stats.get('STL', 0) or 0)
                                    blk  = int(stats.get('BLK', 0) or 0)
                                    to_  = int(stats.get('TO', 0) or 0)
                                    pf   = int(stats.get('PF', 0) or 0)
                                except (ValueError, TypeError):
                                    continue
                                fgm, fga = parse_split(stats.get('FGM-A', '0-0'))
                                tpm, tpa = parse_split(stats.get('3PM-A', '0-0'))
                                ftm, fta = parse_split(stats.get('FTM-A', '0-0'))
                                twom = fgm - tpm
                                twoa = fga - tpa
                                # Hollinger game score
                                gs = (pts + 0.4 * fgm - 0.7 * fga - 0.4 * (fta - ftm)
                                      + 0.7 * oreb + 0.3 * dreb + stl
                                      + 0.7 * ast + 0.7 * blk - 0.4 * pf - to_)
                                if gs < 0:
                                    continue
                                name_clean = re.sub(r'^#\S+\s+', '', name_raw).strip()
                                rec = {
                                    'name': name_clean, 'team': team_name,
                                    'pts': pts, 'reb': reb, 'ast': ast,
                                    'stl': stl, 'blk': blk, 'to': to_,
                                    'fgm': fgm, 'fga': fga,
                                    'tpm': tpm, 'tpa': tpa,
                                    'ftm': ftm, 'fta': fta,
                                    'twom': twom, 'twoa': twoa,
                                    'game_score': round(gs, 1),
                                }
                                if date_str not in lotn or gs > lotn[date_str]['game_score']:
                                    lotn[date_str] = rec
                    except Exception:
                        pass
    return lotn


def build_storylines(stats_dir: Path, top: int = 100, exclude_zero_scores: bool = True,
                     hca_points: float = 3.0, wp_scale: float = 10.0,
                     prior_stats_dir: Path = None) -> dict:
    by_team, team_names = _sl_load_games(stats_dir)
    games = _sl_dedupe(by_team, team_names, exclude_zero_scores)
    priors = _sl_load_priors(prior_stats_dir) if prior_stats_dir is not None else {}
    rows = _sl_enrich(games, team_names, hca_points, wp_scale, priors)
    game_dates = {r["date"] for r in rows}
    sched_dir = Path(str(stats_dir).replace(" Team Statistics", " Teams Schedules"))
    lines_of_night = _sl_load_line_of_night(sched_dir, game_dates)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stats_dir": str(stats_dir),
        "games_in_system": len(rows),
        "dominant_wins":  _sl_top_n(rows, "dominance_score", top),
        "upsets":         _sl_top_n(rows, "upset_score", top, predicate=lambda r: r["underdog_gap"] > 0 and r["pregame_winner_games"] >= 5 and r["pregame_loser_games"] >= 5),
        "tension_games":  _sl_top_n(rows, "tension_score", top),
        "bust_games":     _sl_top_n(rows, "bust_score", top),
        "fanmatch_games": sorted(rows, key=lambda r: (_sl_date_sort_key(r["date"]), -r["fanmatch_score"])),
        "lines_of_night": lines_of_night,
    }

# ---------------------------------------------------------------------------

OUTPUT = Path("wsc_north_leaderboard.html")
STATS_DIR = Path("2025-26 Team Statistics")
STATS_DIR_2024 = Path("2024-25 Team Statistics")
STATS_DIR_2023 = Path("2023-24 Team Statistics")
STATS_DIR_2022 = Path("2022-23 Team Statistics")
STATS_DIR_2021 = Path("2021-22 Team Statistics")
STATS_DIR_2019 = Path("2019-20 Team Statistics")
STATS_DIR_1819 = Path("2018-19 Team Statistics")
STATS_DIR_1718 = Path("2017-18 Team Statistics")

# ---------------------------------------------------------------------------
# Coaches lookup: coaches.json maps {team_name: {season: coach_name_or_null}}
# ---------------------------------------------------------------------------
_COACHES_PATH = Path("coaches.json")
_POSITIONS_CSV = Path("internal_data/player_positions_2025_26.csv")


def _load_player_positions():
    """Load position classifications from CSV. Returns {(team, name): pos_class}."""
    import csv
    pos_map = {}
    if not _POSITIONS_CSV.exists():
        return pos_map
    with open(_POSITIONS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            team = row["team"].strip()
            name = row["name"].strip()
            pos = row["pos_class"].strip()
            pos_map[(team, name)] = pos
    return pos_map
_COACHES_DATA: dict = {}
if _COACHES_PATH.exists():
    with open(_COACHES_PATH) as _cf:
        _COACHES_DATA = json.load(_cf)

_STATS_DIR_TO_SEASON = {
    str(STATS_DIR):      "2025-26",
    str(STATS_DIR_2024): "2024-25",
    str(STATS_DIR_2023): "2023-24",
    str(STATS_DIR_2022): "2022-23",
    str(STATS_DIR_2021): "2021-22",
    str(STATS_DIR_2019): "2019-20",
    str(STATS_DIR_1819): "2018-19",
    str(STATS_DIR_1718): "2017-18",
}

def _get_coach(team_name: str, stats_dir) -> str:
    """Return head coach name for a team in a given season, or empty string."""
    season = _STATS_DIR_TO_SEASON.get(str(stats_dir), "")
    if not season:
        return ""
    return _COACHES_DATA.get(team_name, {}).get(season) or ""

CONFERENCES = {
    "WSC North": {
        "region": "South",
        "teams": ["Allan Hancock", "Cuesta", "LA Pierce", "Moorpark", "Oxnard", "Santa Barbara", "Ventura"],
    },
    "WSC South": {
        "region": "South",
        "teams": ["Antelope Valley", "Bakersfield", "Canyons", "Citrus", "Glendale", "LA Valley", "Santa Monica", "West LA"],
    },
    "Orange Empire Athletic": {
        "region": "South",
        "teams": ["Cypress", "Fullerton", "Golden West", "Irvine Valley", "Orange Coast", "Riverside", "Saddleback", "Santa Ana", "Santiago Canyon"],
    },
    "Pacific Coast Athletic": {
        "region": "South",
        "teams": ["Cuyamaca", "Grossmont", "Imperial Valley", "MiraCosta", "Palomar", "San Diego City", "San Diego Mesa", "San Diego Miramar", "Southwestern"],
    },
    "South Coast-South": {
        "region": "South",
        "teams": ["Cerritos", "Compton", "El Camino", "LA Harbor", "LA Southwest", "Long Beach"],
    },
    "South Coast-North": {
        "region": "South",
        "teams": ["East Los Angeles", "LA Trade Tech", "Los Angeles City", "Mt. San Antonio", "Pasadena City", "Rio Hondo"],
    },
    "Inland Empire Athletic": {
        "region": "South",
        "teams": ["San Bernardino Valley", "Mt. San Jacinto", "Chaffey", "Copper Mountain", "Barstow", "Cerro Coso", "Victor Valley", "Desert", "Palo Verde"],
    },
    "Coast-North": {
        "region": "North",
        "teams": ["San Francisco", "Las Positas", "Chabot", "Canada", "San Mateo", "Ohlone", "De Anza", "Skyline"],
    },
    "Big Eight": {
        "region": "North",
        "teams": ["Santa Rosa", "Cosumnes River", "Sierra", "Modesto", "San Joaquin Delta", "Diablo Valley", "Sacramento City", "Folsom Lake", "American River"],
    },
    "Coast-South": {
        "region": "North",
        "teams": ["San Jose", "West Valley", "Cabrillo", "Foothill", "Monterey Peninsula", "Gavilan", "Hartnell"],
    },
    "Bay Valley": {
        "region": "North",
        "teams": ["Yuba", "Marin", "Contra Costa", "Merritt", "Los Medanos", "Napa Valley", "Alameda", "Mendocino", "Solano"],
    },
    "Central Valley": {
        "region": "North",
        "teams": ["Columbia", "Sequoias", "Merced", "Lemoore", "Reedley", "Fresno", "Porterville", "Coalinga"],
    },
    "Golden Valley": {
        "region": "North",
        "teams": ["Feather River", "Redwoods", "Butte", "Shasta", "Siskiyous", "Lassen"],
    },
}

#!/usr/bin/env python3
"""
Generate a WSC North individual statistics leaderboard as a standalone HTML file.

Loads player stats from all 7 WSC North teams, filters by 40% minutes
played threshold, and outputs a sortable HTML table.
"""


# Players exempted from the 40% minutes threshold
PLAYER_EXEMPTIONS = {"Isaiah Sherrard"}

# Team name aliases for stats directories (current name -> directory name)
_TEAM_DIR_ALIASES_2023 = {
    "Lemoore": "West Hills Lemoore",
    "Coalinga": "West Hills Coalinga",
}
_TEAM_DIR_ALIASES_1819 = {
    "Lemoore": "West Hills Lemoore",
    "Coalinga": "West Hills Coalinga",
}
_TEAM_DIR_ALIASES_1718 = {
    "Coalinga": "West Hills Coalinga",
}
_SEASON_DIR_ALIASES = {
    str(STATS_DIR_2023): _TEAM_DIR_ALIASES_2023,
    str(STATS_DIR_1819): _TEAM_DIR_ALIASES_1819,
    str(STATS_DIR_1718): _TEAM_DIR_ALIASES_1718,
}

def _find_team_stats_dir(stats_dir, conf_name, team_name):
    """Locate the stats directory for a team, with fallback for renamed/moved teams."""
    # 1. Exact expected path
    p = stats_dir / conf_name / team_name
    if p.exists():
        return p
    # 2. Season-specific name alias (e.g. Coalinga -> West Hills Coalinga for 2017-18)
    aliases = _SEASON_DIR_ALIASES.get(str(stats_dir), {})
    if aliases and team_name in aliases:
        aliased = aliases[team_name]
        # Try all conference subdirs for the aliased name
        for conf_dir in stats_dir.iterdir():
            if conf_dir.is_dir():
                candidate = conf_dir / aliased
                if candidate.exists():
                    return candidate
    # 3. Scan all conference subdirs for exact team name (handles conference changes)
    for conf_dir in stats_dir.iterdir():
        if conf_dir.is_dir():
            candidate = conf_dir / team_name
            if candidate.exists():
                return candidate
    return p  # Return original (non-existent) path so callers can check .exists()

def compute_rpi(stats_dir=None):
    """Compute RPI and NC-RPI for all teams in a given stats directory.

    RPI = 0.25 * WP + 0.50 * OWP + 0.25 * OOWP
    NC-RPI = same formula restricted to non-conference games only.
    Returns a list of dicts sorted by rpi desc, each with:
      team, conference, region, record, nc_record, rpi, nc_rpi
    """
    if stats_dir is None:
        stats_dir = STATS_DIR

    # Case-insensitive name lookup so opponent strings match canonical names
    name_lower = {n.lower(): n for conf_info in CONFERENCES.values() for n in conf_info["teams"]}

    def normalize_opp(name):
        return name_lower.get(name.strip().lower(), name.strip())

    # Load every team's game log into a graph
    game_graph = {}   # canonical_name -> [(opp_canonical, win:bool, is_conf:bool), ...]
    team_records = {}  # canonical_name -> (wins, losses)
    nc_records = {}    # canonical_name -> (nc_wins, nc_losses)
    team_meta = {}     # canonical_name -> {conference, region}

    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team in conf_info["teams"]:
            team_dir = _find_team_stats_dir(stats_dir, conf_name, team)
            gl_path = team_dir / "game_log.json"
            if not gl_path.exists():
                continue
            try:
                gl = json.load(open(gl_path))
            except Exception:
                continue
            games = []
            wins = losses = nc_wins = nc_losses = 0
            for g in gl.get("games", []):
                opp = normalize_opp(g.get("opponent", ""))
                result = g.get("result", "")
                is_conf = bool(g.get("is_conference", False))
                if not opp or result not in ("W", "L"):
                    continue
                win = result == "W"
                games.append((opp, win, is_conf))
                if win:
                    wins += 1
                else:
                    losses += 1
                if not is_conf:
                    if win:
                        nc_wins += 1
                    else:
                        nc_losses += 1
            game_graph[team] = games
            team_records[team] = (wins, losses)
            nc_records[team] = (nc_wins, nc_losses)
            team_meta[team] = {"conference": conf_name, "region": region}

    if not game_graph:
        return []

    def get_wp(team, exclude_opp=None, nc_only=False):
        games = game_graph.get(team, [])
        if nc_only:
            games = [g for g in games if not g[2]]
        if exclude_opp:
            games = [g for g in games if g[0] != exclude_opp]
        if not games:
            return 0.5
        return sum(1 for g in games if g[1]) / len(games)

    rpi_list = []
    for team, games in game_graph.items():
        if not games:
            continue

        # Overall RPI
        wp = get_wp(team)
        owp_vals = [get_wp(opp, exclude_opp=team) for opp, _w, _c in games]
        owp = sum(owp_vals) / len(owp_vals) if owp_vals else 0.5
        oowp_vals = []
        for opp in set(g[0] for g in games):
            for opp2, _, _ in game_graph.get(opp, []):
                oowp_vals.append(get_wp(opp2, exclude_opp=opp))
        oowp = sum(oowp_vals) / len(oowp_vals) if oowp_vals else 0.5
        rpi = round(0.25 * wp + 0.50 * owp + 0.25 * oowp, 4)

        # NC RPI
        nc_games = [g for g in games if not g[2]]
        if nc_games:
            nc_wp = get_wp(team, nc_only=True)
            nc_owp_vals = [get_wp(opp, exclude_opp=team, nc_only=True) for opp, _w, _c in nc_games]
            nc_owp = sum(nc_owp_vals) / len(nc_owp_vals) if nc_owp_vals else 0.5
            nc_oowp_vals = []
            for opp in set(g[0] for g in nc_games):
                for opp2, _, is_c2 in game_graph.get(opp, []):
                    if not is_c2:
                        nc_oowp_vals.append(get_wp(opp2, exclude_opp=opp, nc_only=True))
            nc_oowp = sum(nc_oowp_vals) / len(nc_oowp_vals) if nc_oowp_vals else 0.5
            nc_rpi = round(0.25 * nc_wp + 0.50 * nc_owp + 0.25 * nc_oowp, 4)
        else:
            nc_rpi = rpi

        w, l = team_records.get(team, (0, 0))
        nc_w, nc_l = nc_records.get(team, (0, 0))
        meta = team_meta.get(team, {})
        rpi_list.append({
            "team": team,
            "conference": meta.get("conference", ""),
            "region": meta.get("region", ""),
            "record": f"{w}-{l}",
            "nc_record": f"{nc_w}-{nc_l}",
            "rpi": rpi,
            "nc_rpi": nc_rpi,
        })

    rpi_list.sort(key=lambda x: -x["rpi"])
    return rpi_list


def load_players(stats_dir=None):
    """Load all qualified players from all teams."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    pos_map = _load_player_positions()
    players = []
    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team in conf_info["teams"]:
            team_dir = _find_team_stats_dir(stats_dir, conf_name, team)
            summary_path = team_dir / "team_summary.json"
            player_path = team_dir / "player_stats.json"
            if not summary_path.exists() or not player_path.exists():
                print(f"  Skipping {team}: missing files")
                continue

            summary = json.load(open(summary_path))
            pdata = json.load(open(player_path))
            adv_path = team_dir / "advanced_analytics.json"
            adv_data = json.load(open(adv_path)) if adv_path.exists() else {"players": []}
            adv_map = {re.sub(r'^#\d+\s+', '', p["name"]): p for p in adv_data.get("players", [])}

            team_total_min = summary["totals"]["MIN"]
            min_threshold = team_total_min * 0.40
            games_played = summary["games_played"]

            # Detect fake-minutes teams by total player minutes per game
            total_player_min = sum(p["totals"]["MIN"] for p in pdata["players"])
            avg_player_min_pg = total_player_min / games_played if games_played > 0 else 0
            is_fake = avg_player_min_pg < 100

            # Count clean games: real box score (MIN>=30, FGA>0)
            gl_path = team_dir / "game_log.json"
            clean_games = 0
            if gl_path.exists():
                try:
                    gl_data = json.load(open(gl_path))
                    for gm in gl_data.get("games", []):
                        ts = gm.get("team_stats") or {}
                        if gm.get("MIN", 0) >= 30 and ts.get("FGA", 0) > 0:
                            clean_games += 1
                except Exception:
                    pass
            # Advanced stats require 18+ clean games and real minutes
            adv_eligible = not is_fake and clean_games >= 18

            # For fake teams, check if there's meaningful minute variance
            if is_fake:
                mpgs = [p["totals"]["MIN"] / max(p["totals"]["games"], 1)
                        for p in pdata["players"] if p["totals"]["games"] > 0]
                mpg_spread = max(mpgs) - min(mpgs) if mpgs else 0
                # Proportional MPG cutoff: same 40% ratio scaled to fake minutes
                fake_mpg_cutoff = avg_player_min_pg / 5 * 0.40

            for p in pdata["players"]:
                t = p["totals"]
                g = t["games"]
                if g == 0:
                    continue
                # Strip jersey number for display name (needed before exemption check)
                name = p["name"]
                clean_name = re.sub(r'^#\d+\s+', '', name)
                if is_fake:
                    if mpg_spread < 0.5:
                        pass  # zero-variance: include all players
                    elif t["MIN"] / g < fake_mpg_cutoff:
                        continue
                elif clean_name not in PLAYER_EXEMPTIONS and t["MIN"] < min_threshold:
                    continue

                _adv = adv_map.get(clean_name, {}) if adv_eligible else {}
                players.append({
                    "name": clean_name,
                    "school": team,
                    "region": region,
                    "conference": conf_name,
                    "gp": g,
                    "mpg": round(t["MIN"] / g, 1),
                    "min_pct": round(t["MIN"] / (40 * games_played) * 100, 1) if games_played > 0 else None,
                    "ppg": round(t["PTS"] / g, 1),
                    "orpg": round(t["OREB"] / g, 1),
                    "drpg": round(t["DREB"] / g, 1),
                    "rpg": round(t["REB"] / g, 1),
                    "apg": round(t["AST"] / g, 1),
                    "spg": round(t["STL"] / g, 1),
                    "bpg": round(t["BLK"] / g, 1),
                    "topg": round(t["TO"] / g, 1),
                    "fgm": t["FGM"], "fga": t["FGA"],
                    "fgp": round(t["FGM"] / t["FGA"] * 100, 1) if t["FGA"] else 0.0,
                    "twom": t["FGM"] - t["3PM"], "twoa": t["FGA"] - t["3PA"],
                    "twop": round((t["FGM"] - t["3PM"]) / (t["FGA"] - t["3PA"]) * 100, 1) if (t["FGA"] - t["3PA"]) > 0 else 0.0,
                    "tpm": t["3PM"], "tpa": t["3PA"],
                    "tpp": round(t["3PM"] / t["3PA"] * 100, 1) if t["3PA"] else 0.0,
                    "ftm": t["FTM"], "fta": t["FTA"],
                    "ftp": round(t["FTM"] / t["FTA"] * 100, 1) if t["FTA"] else 0.0,
                    "pts": t["PTS"],
                    "reb": t["REB"],
                    "ast": t["AST"],
                    "pos": pos_map.get((team, clean_name), ""),
                    "ind_ortg": _adv.get("ind_ortg"),
                    "ind_drtg": _adv.get("ind_drtg"),
                    "efg_pct": _adv.get("efg_pct"),
                    "ts_pct": _adv.get("ts_pct"),
                    "usage_pct": _adv.get("usage_pct"),
                    "shot_pct": _adv.get("shot_pct"),
                    "oreb_pct": _adv.get("oreb_pct"),
                    "dreb_pct": _adv.get("dreb_pct"),
                    "tov_pct": _adv.get("tov_pct"),
                    "ast_rate": _adv.get("ast_rate"),
                    "blk_pct": _adv.get("blk_pct"),
                    "stl_pct": _adv.get("stl_pct"),
                    "ft_rate": _adv.get("ft_rate"),
                    "fc_per_40": _adv.get("fc_per_40"),
                    "fd_per_40": _adv.get("fd_per_40"),
                })

    # Default sort by PPG descending
    players.sort(key=lambda x: -x["ppg"])
    return players


def load_teams(stats_dir=None):
    """Load team-level stats and advanced analytics for all teams."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    teams = []
    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team in conf_info["teams"]:
            team_dir = _find_team_stats_dir(stats_dir, conf_name, team)
            summary_path = team_dir / "team_summary.json"
            adv_path = team_dir / "advanced_analytics.json"
            if not summary_path.exists():
                continue

            summary = json.load(open(summary_path))
            adv = json.load(open(adv_path)) if adv_path.exists() else {"team": {}}

            avgs = summary.get("averages", {})
            opp_avgs = summary.get("opponent_averages", {})
            totals = summary.get("totals", {})
            opp_totals = summary.get("opponent_totals", {})
            rec = summary.get("record", {})
            overall = ""
            conf = ""
            for k, v in rec.items():
                if "Overall" in k:
                    overall = v
                elif "Conference" in k:
                    conf = v

            ta = adv.get("team", {})
            monthly_stats = adv.get("monthly_stats", {})

            # Load per-game box scores to compute four-factor stats for game plan
            gl_path = team_dir / "game_log.json"
            gl_by_date = {}
            if gl_path.exists():
                gl_data = json.load(open(gl_path))
                for g in gl_data.get("games", []):
                    d = g.get("date", "")
                    if d:
                        gl_by_date[d] = g

            raw_game_ratings = ta.get("game_ratings", [])
            enriched_game_ratings = []
            for gr in raw_game_ratings:
                entry = dict(gr)
                raw = gl_by_date.get(gr.get("date", ""))
                if raw:
                    ts = raw.get("team_stats") or {}
                    os_ = raw.get("opponent_stats") or {}
                    poss = gr.get("possessions", 0)
                    min_ = raw.get("MIN", 40) or 40
                    ff = _compute_game_ff(ts, os_, poss, min_)
                    if ff:
                        entry.update(ff)
                    # Raw per-game counting stats for month-level trend aggregation
                    if ts.get("FGA", 0) > 0:
                        _op = max(
                            (os_.get("FGA", 0) - os_.get("OREB", 0)) +
                            os_.get("TO", 0) + 0.475 * os_.get("FTA", 0), 0.1)
                        entry["g_ast"]      = ts.get("AST", 0)
                        entry["g_fgm"]      = ts.get("FGM", 0)
                        entry["g_fga"]      = ts.get("FGA", 0)
                        entry["g_3pa"]      = ts.get("3PA", 0)
                        entry["g_ftm"]      = ts.get("FTM", 0)
                        entry["g_fta"]      = ts.get("FTA", 0)
                        entry["g_blk"]      = ts.get("BLK", 0)
                        entry["g_stl"]      = ts.get("STL", 0)
                        entry["g_opp_fga"]  = os_.get("FGA", 0)
                        entry["g_opp_poss"] = round(_op, 1)
                enriched_game_ratings.append(entry)

            teams.append({
                "team": team,
                "coach": _get_coach(team, stats_dir),
                "region": region,
                "conference": conf_name,
                "record": overall,
                "conf": conf,
                "gp": (int(overall.split('-')[0]) + int(overall.split('-')[1])) if overall and '-' in overall and len(overall.split('-')) == 2 and all(x.isdigit() for x in overall.split('-')) else summary.get("games_played", 0),
                "ppg": avgs.get("PTS", 0),
                "opp_ppg": opp_avgs.get("PTS", 0),
                "rpg": avgs.get("REB", 0),
                "orebpg": avgs.get("OREB", 0),
                "drebpg": avgs.get("DREB", 0),
                "apg": avgs.get("AST", 0),
                "spg": avgs.get("STL", 0),
                "bpg": avgs.get("BLK", 0),
                "topg": avgs.get("TO", 0),
                "pfpg": avgs.get("PF", 0),
                "pf_unreliable": avgs.get("PF", 0) < 5.0,
                "opp_pfpg": opp_avgs.get("PF", 0),
                "fgp": round(avgs.get("FGM", 0) / avgs.get("FGA", 1) * 100, 1) if avgs.get("FGA", 0) > 0 else 0.0,
                "twop": round((avgs.get("FGM", 0) - avgs.get("3PM", 0)) / max(avgs.get("FGA", 0) - avgs.get("3PA", 0), 1) * 100, 1) if (avgs.get("FGA", 0) - avgs.get("3PA", 0)) > 0 else 0.0,
                "tpp": round(avgs.get("3PM", 0) / avgs.get("3PA", 1) * 100, 1) if avgs.get("3PA", 0) > 0 else 0.0,
                "ftp": round(avgs.get("FTM", 0) / avgs.get("FTA", 1) * 100, 1) if avgs.get("FTA", 0) > 0 else 0.0,
                "tpa_pct": round(avgs.get("3PA", 0) / avgs.get("FGA", 1) * 100, 1) if avgs.get("FGA", 0) > 0 else 0.0,
                "ast_pct": round(avgs.get("AST", 0) / max(ta.get("possessions", 1), 1) * 100, 1) if ta.get("possessions", 0) > 0 else 0.0,
                "ast_ratio": round(100 * avgs.get("AST", 0) / max(avgs.get("FGA", 0) + 0.475 * avgs.get("FTA", 0) + avgs.get("AST", 0) + avgs.get("TO", 0), 1), 1) if (avgs.get("FGA", 0) + avgs.get("FTA", 0)) > 0 else 0.0,
                "ast_tov": round(avgs.get("AST", 0) / max(avgs.get("TO", 0.01), 0.01), 2),
                "nst_pct": (round((avgs.get("TO", 0) - opp_avgs.get("STL", 0)) / max(ta.get("possessions", 0.01), 0.01) * 100, 1) if avgs.get("TO", 0) > opp_avgs.get("STL", 0) and ta.get("possessions", 0) > 0 else None),
                "stl_to": round(avgs.get("STL", 0) / max(opp_avgs.get("TO", 0.01), 0.01), 2),
                "ts_pct": ta.get("ts_pct", 0),
                "efg_pct": ta.get("efg_pct", 0),
                "tov_pct": ta.get("tov_pct", 0),
                "ft_rate": ta.get("ft_rate", 0),
                "oreb_pct": ta.get("oreb_pct", 0),
                "luck": (lambda p=avgs.get("PTS",0), o=opp_avgs.get("PTS",0), r=overall: (
                    round((lambda w,l,gp: w/gp - p**10.25/(p**10.25+o**10.25))(
                        int(r.split('-')[0]), int(r.split('-')[1]),
                        int(r.split('-')[0])+int(r.split('-')[1])
                    ), 4) if p > 0 and o > 0 and '-' in r and int(r.split('-')[0])+int(r.split('-')[1]) > 0 else 0.0
                ))(),
                "possessions": ta.get("possessions", 0),
                "ortg": ta.get("ortg", 0),
                "tempo": ta.get("tempo", 0),
                "drtg": ta.get("drtg", 0),
                "net_rtg": ta.get("net_rtg", 0),
                "opp_adjust": ta.get("opp_adjust", 0),
                "pace_adjust": ta.get("pace_adjust", 0),
                "opp_ortg": ta.get("opp_ortg", 0),
                "opp_drtg_sos": ta.get("opp_drtg", 0),
                "sos": ta.get("sos", 0),
                "ncsos": ta.get("ncsos", 0),
                # Defensive stats
                "opp_efg_pct": ta.get("opp_efg_pct", 0),
                "dreb_pct": ta.get("dreb_pct", 0),
                "opp_tov_pct": ta.get("opp_tov_pct", 0),
                "opp_ft_rate": ta.get("opp_ft_rate", 0),
                "opp_orebpg": opp_avgs.get("OREB", 0),
                "opp_drebpg": opp_avgs.get("DREB", 0),
                "opp_rpg": opp_avgs.get("REB", 0),
                "opp_apg": opp_avgs.get("AST", 0),
                "opp_topg": opp_avgs.get("TO", 0),
                "opp_spg": opp_avgs.get("STL", 0),
                "opp_bpg": opp_avgs.get("BLK", 0),
                "opp_fgp": round(opp_avgs.get("FGM", 0) / opp_avgs.get("FGA", 1) * 100, 1) if opp_avgs.get("FGA", 0) > 0 else 0.0,
                "opp_twop": round((opp_avgs.get("FGM", 0) - opp_avgs.get("3PM", 0)) / max(opp_avgs.get("FGA", 0) - opp_avgs.get("3PA", 0), 1) * 100, 1) if (opp_avgs.get("FGA", 0) - opp_avgs.get("3PA", 0)) > 0 else 0.0,
                "opp_tpp": round(opp_avgs.get("3PM", 0) / opp_avgs.get("3PA", 1) * 100, 1) if opp_avgs.get("3PA", 0) > 0 else 0.0,
                "opp_ftp": round(opp_avgs.get("FTM", 0) / opp_avgs.get("FTA", 1) * 100, 1) if opp_avgs.get("FTA", 0) > 0 else 0.0,
                "opp_tpa_pct": round(opp_avgs.get("3PA", 0) / opp_avgs.get("FGA", 1) * 100, 1) if opp_avgs.get("FGA", 0) > 0 else 0.0,
                "opp_ts_pct": ta.get("opp_ts_pct", 0),
                # Season-level rate stats for Trends tab
                "ast_pct": round(totals.get("AST", 0) / max(totals.get("FGM", 1), 1) * 100, 1),
                "blk_pct": round(totals.get("BLK", 0) / max(opp_totals.get("FGA", 1), 1) * 100, 1),
                "stl_pct": round(totals.get("STL", 0) / max(
                    (opp_totals.get("FGA", 0) - opp_totals.get("OREB", 0)) +
                    opp_totals.get("TO", 0) + 0.475 * opp_totals.get("FTA", 0), 0.1) * 100, 1),
                "hkm_pct": round(
                    round(totals.get("BLK", 0) / max(opp_totals.get("FGA", 1), 1) * 100, 1) +
                    round(totals.get("STL", 0) / max((opp_totals.get("FGA", 0) - opp_totals.get("OREB", 0)) + opp_totals.get("TO", 0) + 0.475 * opp_totals.get("FTA", 0), 0.1) * 100, 1), 1),
                "pf_total": totals.get("PF", 0),
                "pf_eff": round((totals.get("STL", 0) + totals.get("BLK", 0)) / max(totals.get("PF", 0.1), 0.1), 2),
                "stl_pf": round(totals.get("STL", 0) / max(totals.get("PF", 0.1), 0.1), 2),
                "blk_pf": round(totals.get("BLK", 0) / max(totals.get("PF", 0.1), 0.1), 2),
                # Totals for shooting breakdown
                "totals": {
                    "FGM": totals.get("FGM", 0), "FGA": totals.get("FGA", 0),
                    "3PM": totals.get("3PM", 0), "3PA": totals.get("3PA", 0),
                    "FTM": totals.get("FTM", 0), "FTA": totals.get("FTA", 0),
                    "STL": totals.get("STL", 0), "BLK": totals.get("BLK", 0),
                    "AST": totals.get("AST", 0),
                },
                "opp_totals": {
                    "FGM": opp_totals.get("FGM", 0), "FGA": opp_totals.get("FGA", 0),
                    "3PM": opp_totals.get("3PM", 0), "3PA": opp_totals.get("3PA", 0),
                    "FTM": opp_totals.get("FTM", 0), "FTA": opp_totals.get("FTA", 0),
                    "STL": opp_totals.get("STL", 0), "BLK": opp_totals.get("BLK", 0),
                },
                # Game ratings for schedule and game plan
                "game_ratings": enriched_game_ratings,
                "monthly_stats": monthly_stats,
            })

    teams.sort(key=lambda x: -x["net_rtg"])

    # Compute tier records (KenPom-scaled: A=top-15 adj, B=top-30 adj)
    _TIER_A = 15
    _TIER_B = 30
    _AWAY_F = 50 / 90
    _HOME_F = 50 / 20
    net_rtg_ranks = {t["team"]: i + 1 for i, t in enumerate(teams) if t.get("ortg", 0) > 0}
    for t in teams:
        aw, al, bw, bl = 0, 0, 0, 0
        for gr in t.get("game_ratings", []):
            opp = gr.get("canonical_opponent") or gr.get("opponent", "")
            opp_rank = net_rtg_ranks.get(opp)
            if not isinstance(opp_rank, int):
                continue
            loc = gr.get("location", "")
            adj = opp_rank * (_AWAY_F if loc == "Away" else _HOME_F if loc == "Home" else 1.0)
            tier = "A" if adj <= _TIER_A else ("B" if adj <= _TIER_B else "")
            result = gr.get("result", "")
            if tier == "A":
                if result == "W": aw += 1
                elif result == "L": al += 1
            elif tier == "B":
                if result == "W": bw += 1
                elif result == "L": bl += 1
        t["tier_a_rec"] = f"{aw}-{al}" if (aw + al) > 0 else ""
        t["tier_b_rec"] = f"{bw}-{bl}" if (bw + bl) > 0 else ""

    return teams


def load_conf_players(stats_dir=None):
    """Load conference-only qualified players from all teams (40% minutes threshold)."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    pos_map = _load_player_positions()
    players = []
    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team in conf_info["teams"]:
            team_dir = _find_team_stats_dir(stats_dir, conf_name, team)
            conf_path = team_dir / "conference_stats.json"
            if not conf_path.exists():
                continue
            cdata = json.load(open(conf_path))
            gp = cdata.get("games_played", 0)
            if gp == 0:
                continue
            adv_path = team_dir / "advanced_analytics.json"
            adv_data = json.load(open(adv_path)) if adv_path.exists() else {"players": []}
            adv_map = {re.sub(r'^#\d+\s+', '', p["name"]): p for p in adv_data.get("players", [])}

            team_total_min = cdata.get("totals", {}).get("MIN", 0)
            min_threshold = team_total_min * 0.40

            # Detect fake-minutes teams
            all_players = cdata.get("players", [])
            total_player_min = sum(p["totals"]["MIN"] for p in all_players)
            avg_player_min_pg = total_player_min / gp if gp > 0 else 0
            is_fake = avg_player_min_pg < 100

            # Count clean games from full-season game_log (MIN>=30, FGA>0)
            gl_path = team_dir / "game_log.json"
            clean_games = 0
            if gl_path.exists():
                try:
                    gl_data = json.load(open(gl_path))
                    for gm in gl_data.get("games", []):
                        ts = gm.get("team_stats") or {}
                        if gm.get("MIN", 0) >= 30 and ts.get("FGA", 0) > 0:
                            clean_games += 1
                except Exception:
                    pass
            # Advanced stats require 18+ clean games and real minutes
            adv_eligible = not is_fake and clean_games >= 18

            if is_fake:
                mpgs = [p["totals"]["MIN"] / max(p["totals"]["games"], 1)
                        for p in all_players if p["totals"]["games"] > 0]
                mpg_spread = max(mpgs) - min(mpgs) if mpgs else 0
                fake_mpg_cutoff = avg_player_min_pg / 5 * 0.40

            for p in all_players:
                t = p["totals"]
                g = t["games"]
                if g == 0:
                    continue
                if is_fake:
                    if mpg_spread < 0.5:
                        pass  # zero-variance: include all
                    elif t["MIN"] / g < fake_mpg_cutoff:
                        continue
                elif t["MIN"] < min_threshold:
                    continue

                name = p["name"]
                clean_name = re.sub(r'^#\d+\s+', '', name)
                _adv = adv_map.get(clean_name, {}) if adv_eligible else {}
                players.append({
                    "name": clean_name,
                    "school": team,
                    "region": region,
                    "conference": conf_name,
                    "gp": g,
                    "mpg": round(t["MIN"] / g, 1) if t.get("MIN") else 0,
                    "min_pct": round(t["MIN"] / (40 * gp) * 100, 1) if gp > 0 and t.get("MIN") else None,
                    "ppg": round(t["PTS"] / g, 1),
                    "orpg": round(t["OREB"] / g, 1),
                    "drpg": round(t["DREB"] / g, 1),
                    "rpg": round(t["REB"] / g, 1),
                    "apg": round(t["AST"] / g, 1),
                    "spg": round(t["STL"] / g, 1),
                    "bpg": round(t["BLK"] / g, 1),
                    "topg": round(t["TO"] / g, 1),
                    "fgm": t["FGM"], "fga": t["FGA"],
                    "fgp": round(t["FGM"] / t["FGA"] * 100, 1) if t["FGA"] else 0.0,
                    "twom": t["FGM"] - t["3PM"], "twoa": t["FGA"] - t["3PA"],
                    "twop": round((t["FGM"] - t["3PM"]) / (t["FGA"] - t["3PA"]) * 100, 1) if (t["FGA"] - t["3PA"]) > 0 else 0.0,
                    "tpm": t["3PM"], "tpa": t["3PA"],
                    "tpp": round(t["3PM"] / t["3PA"] * 100, 1) if t["3PA"] else 0.0,
                    "ftm": t["FTM"], "fta": t["FTA"],
                    "ftp": round(t["FTM"] / t["FTA"] * 100, 1) if t["FTA"] else 0.0,
                    "pts": t["PTS"],
                    "reb": t["REB"],
                    "ast": t["AST"],
                    "pos": pos_map.get((team, clean_name), ""),
                    "ind_ortg": _adv.get("ind_ortg"),
                    "ind_drtg": _adv.get("ind_drtg"),
                    "efg_pct": _adv.get("efg_pct"),
                    "ts_pct": _adv.get("ts_pct"),
                    "usage_pct": _adv.get("usage_pct"),
                    "shot_pct": _adv.get("shot_pct"),
                    "oreb_pct": _adv.get("oreb_pct"),
                    "dreb_pct": _adv.get("dreb_pct"),
                    "tov_pct": _adv.get("tov_pct"),
                    "ast_rate": _adv.get("ast_rate"),
                    "blk_pct": _adv.get("blk_pct"),
                    "stl_pct": _adv.get("stl_pct"),
                    "ft_rate": _adv.get("ft_rate"),
                    "fc_per_40": _adv.get("fc_per_40"),
                    "fd_per_40": _adv.get("fd_per_40"),
                })
    players.sort(key=lambda x: -x["ppg"])
    return players


def load_conf_teams(stats_dir=None):
    """Load conference-only team stats with iterative opponent-adjusted ratings."""
    if stats_dir is None:
        stats_dir = STATS_DIR

    # ── Phase 1 & 2: iterative conference-only opponent adjustment ───────────
    _HCA   = 3.0   # home court advantage (pts per 100 poss)
    _REGR  = 10    # prior games at league avg to regress toward
    _DAMP  = 0.5   # blend factor with previous iteration
    _MAXITER = 100

    # Collect conference in-system game ratings for every team
    _cgr = {}  # team -> list of conference in-system game rating dicts
    for _cn, _ci in CONFERENCES.items():
        for _t in _ci["teams"]:
            _td = _find_team_stats_dir(stats_dir, _cn, _t)
            _ap = _td / "advanced_analytics.json"
            _cp = _td / "conference_stats.json"
            if not _cp.exists() or not _ap.exists():
                continue
            _adv = json.load(open(_ap))
            _gr = [g for g in _adv.get("team", {}).get("game_ratings", [])
                   if g.get("is_conference") and g.get("in_system", True)]
            if _gr:
                _cgr[_t] = _gr

    # Seed raw ratings
    _raw = {}
    for _t, _gr in _cgr.items():
        _raw[_t] = {
            "ortg": sum(g["ortg"] for g in _gr) / len(_gr),
            "drtg": sum(g["drtg"] for g in _gr) / len(_gr),
        }
    if _raw:
        _tgt_o = sum(r["ortg"] for r in _raw.values()) / len(_raw)
        _tgt_d = sum(r["drtg"] for r in _raw.values()) / len(_raw)
    else:
        _tgt_o = _tgt_d = 100.0

    _cur = {t: dict(r) for t, r in _raw.items()}
    for _ in range(_MAXITER):
        _new = {}
        for _t, _gr in _cgr.items():
            _ao, _ad = [], []
            for g in _gr:
                _opp = g.get("canonical_opponent")
                if not _opp or _opp not in _cur:
                    _ao.append(g["ortg"])
                    _ad.append(g["drtg"])
                    continue
                _ho, _hd = 0.0, 0.0
                _loc = g.get("location", "")
                if _loc == "Home":   _ho, _hd = -_HCA/2, +_HCA/2
                elif _loc == "Away": _ho, _hd = +_HCA/2, -_HCA/2
                _ao.append(g["ortg"] + _ho - _cur[_opp]["drtg"] + _tgt_d)
                _ad.append(g["drtg"] + _hd - _cur[_opp]["ortg"] + _tgt_o)
            if _ao:
                _n = len(_ao)
                _w = _n / (_n + _REGR)
                _ro = _w * sum(_ao)/_n + (1-_w) * _tgt_o
                _rd = _w * sum(_ad)/_n + (1-_w) * _tgt_d
                _new[_t] = {
                    "ortg": _DAMP*_ro + (1-_DAMP)*_cur[_t]["ortg"],
                    "drtg": _DAMP*_rd + (1-_DAMP)*_cur[_t]["drtg"],
                }
            else:
                _new[_t] = {"ortg": _tgt_o, "drtg": _tgt_d}
        # Normalize to preserve league average
        if _new:
            _avg_o = sum(r["ortg"] for r in _new.values()) / len(_new)
            _avg_d = sum(r["drtg"] for r in _new.values()) / len(_new)
            _so, _sd = _tgt_o - _avg_o, _tgt_d - _avg_d
            for _t in _new:
                _new[_t]["ortg"] += _so
                _new[_t]["drtg"] += _sd
        _max_chg = max(
            (max(abs(_new[t]["ortg"]-_cur[t]["ortg"]), abs(_new[t]["drtg"]-_cur[t]["drtg"]))
             for t in _new if t in _cur),
            default=0
        )
        _cur = _new
        if _max_chg < 0.01:
            break
    adj_ratings = _cur  # final iterative-adjusted ortg/drtg per team

    # ── Phase 3: opp_adjust and pace_adjust from conference games ─────────────
    # Uses the same regression approach as compute_sos() in update_advanced_analytics.py
    # but restricted to conference games with conference-only opponent ratings.
    def _reg_slope(pairs):
        n = len(pairs)
        if n < 5:
            return 0.0
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        mx, my = sum(xs) / n, sum(ys) / n
        ssxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        ssxx = sum((x - mx) ** 2 for x in xs)
        return round(ssxy / ssxx, 3) if ssxx > 0 else 0.0

    conf_adjustments = {}
    for _t, _gr in _cgr.items():
        _my_net = adj_ratings[_t]["ortg"] - adj_ratings[_t]["drtg"] if _t in adj_ratings else 0
        _opp_pairs, _pace_pairs = [], []
        for g in _gr:
            if g.get("result") not in ("W", "L"):
                continue
            _opp = g.get("canonical_opponent")
            if not _opp or _opp not in adj_ratings:
                continue
            _opp_net = adj_ratings[_opp]["ortg"] - adj_ratings[_opp]["drtg"]
            _exp_margin = (_my_net - _opp_net) * 0.67
            _act_margin = g.get("team_score", 0) - g.get("opponent_score", 0)
            _resid = _act_margin - _exp_margin
            _opp_pairs.append((_opp_net, _resid))
            _poss = g.get("possessions", 0)
            if _poss > 0:
                _pace_pairs.append((_poss, _resid))
        conf_adjustments[_t] = {
            "opp_adjust": _reg_slope(_opp_pairs),
            "pace_adjust": _reg_slope(_pace_pairs),
        }

    teams = []
    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team in conf_info["teams"]:
            team_dir = _find_team_stats_dir(stats_dir, conf_name, team)
            conf_path = team_dir / "conference_stats.json"
            adv_path = team_dir / "advanced_analytics.json"
            if not conf_path.exists():
                continue
            cdata = json.load(open(conf_path))
            adv = json.load(open(adv_path)) if adv_path.exists() else {"team": {}}

            gp = cdata.get("games_played", 0)
            if gp == 0:
                continue

            totals = cdata.get("totals", {})
            opp_totals = cdata.get("opponent_totals", {})
            avgs = cdata.get("averages", {})
            opp_avgs = cdata.get("opponent_averages", {})

            # Conference record
            rec = cdata.get("record", {})
            conf_rec = ""
            for k, v in rec.items():
                if "Conference" in k:
                    conf_rec = v

            # Compute advanced analytics from conference games in game_ratings
            ta = adv.get("team", {})
            conf_game_ratings = [g for g in ta.get("game_ratings", []) if g.get("is_conference")]

            # Conference ortg/drtg: iterative opponent-adjusted ratings
            if conf_game_ratings:
                in_sys = [g for g in conf_game_ratings if g.get("in_system", True)]
                ratings = in_sys if in_sys else conf_game_ratings
                # poss/tempo from raw game averages
                poss = round(sum(g.get("possessions", 0) for g in ratings) / len(ratings), 1)
                tempo_games = [g.get("tempo", 0) for g in ratings if g.get("tempo", 0) > 0]
                tempo = round(sum(tempo_games) / len(tempo_games), 1) if tempo_games else 0
                # ortg/drtg from iterative adjustment (fall back to raw avg if missing)
                _raw_o = sum(g["ortg"] for g in ratings) / len(ratings)
                _raw_d = sum(g["drtg"] for g in ratings) / len(ratings)
                _adj = adj_ratings.get(team, {})
                ortg = round(_adj.get("ortg", _raw_o), 1)
                drtg = round(_adj.get("drtg", _raw_d), 1)
            else:
                # Fallback: compute from totals
                t_poss = (totals.get("FGA", 0) - totals.get("OREB", 0)) + totals.get("TO", 0) + 0.475 * totals.get("FTA", 0)
                o_poss = (opp_totals.get("FGA", 0) - opp_totals.get("OREB", 0)) + opp_totals.get("TO", 0) + 0.475 * opp_totals.get("FTA", 0)
                avg_poss = (t_poss + o_poss) / 2 if (t_poss + o_poss) > 0 else 1
                ortg = round(totals.get("PTS", 0) / avg_poss * 100, 1) if avg_poss > 0 else 0
                drtg = round(opp_totals.get("PTS", 0) / avg_poss * 100, 1) if avg_poss > 0 else 0
                poss = (t_poss + o_poss) / 2 / gp if gp > 0 else 0
                team_min = totals.get("MIN", 0)
                tempo = round((t_poss + o_poss) / 2 / team_min * 40, 1) if team_min > 0 else 0
            net_rtg = round(ortg - drtg, 1)

            # Four Factors
            fga = totals.get("FGA", 0)
            efg_pct = round((totals.get("FGM", 0) + 0.5 * totals.get("3PM", 0)) / fga * 100, 1) if fga > 0 else 0
            tov_denom = (fga - totals.get("OREB", 0)) + totals.get("TO", 0) + 0.475 * totals.get("FTA", 0)
            tov_pct = round(totals.get("TO", 0) / tov_denom * 100, 1) if tov_denom > 0 else 0
            oreb_total = totals.get("OREB", 0) + opp_totals.get("DREB", 0)
            oreb_pct = round(totals.get("OREB", 0) / oreb_total * 100, 1) if oreb_total > 0 else 0
            ft_rate = round(avgs.get("FTA", 0) / avgs.get("FGA", 1) * 100, 1) if avgs.get("FGA", 0) > 0 else 0
            ts_denom = 2 * (avgs.get("FGA", 0) + 0.475 * avgs.get("FTA", 0))
            ts_pct = round(avgs.get("PTS", 0) / ts_denom * 100, 1) if ts_denom > 0 else 0

            # Defensive Four Factors
            ofga = opp_totals.get("FGA", 0)
            opp_efg_pct = round((opp_totals.get("FGM", 0) + 0.5 * opp_totals.get("3PM", 0)) / ofga * 100, 1) if ofga > 0 else 0
            dreb_total = totals.get("DREB", 0) + opp_totals.get("OREB", 0)
            dreb_pct = round(totals.get("DREB", 0) / dreb_total * 100, 1) if dreb_total > 0 else 0
            opp_tov_denom = (ofga - opp_totals.get("OREB", 0)) + opp_totals.get("TO", 0) + 0.475 * opp_totals.get("FTA", 0)
            opp_tov_pct = round(opp_totals.get("TO", 0) / opp_tov_denom * 100, 1) if opp_tov_denom > 0 else 0
            opp_ft_rate = round(opp_avgs.get("FTA", 0) / opp_avgs.get("FGA", 1) * 100, 1) if opp_avgs.get("FGA", 0) > 0 else 0
            opp_ts_denom = 2 * (opp_avgs.get("FGA", 0) + 0.475 * opp_avgs.get("FTA", 0))
            opp_ts_pct = round(opp_avgs.get("PTS", 0) / opp_ts_denom * 100, 1) if opp_ts_denom > 0 else 0

            teams.append({
                "team": team,
                "region": region,
                "conference": conf_name,
                "record": conf_rec,
                "conf": conf_rec,
                "gp": gp,
                "ppg": avgs.get("PTS", 0),
                "opp_ppg": opp_avgs.get("PTS", 0),
                "rpg": avgs.get("REB", 0),
                "orebpg": avgs.get("OREB", 0),
                "drebpg": avgs.get("DREB", 0),
                "apg": avgs.get("AST", 0),
                "spg": avgs.get("STL", 0),
                "bpg": avgs.get("BLK", 0),
                "topg": avgs.get("TO", 0),
                "pfpg": avgs.get("PF", 0),
                "pf_unreliable": avgs.get("PF", 0) < 5.0,
                "opp_pfpg": opp_avgs.get("PF", 0),
                "fgp": round(avgs.get("FGM", 0) / avgs.get("FGA", 1) * 100, 1) if avgs.get("FGA", 0) > 0 else 0.0,
                "twop": round((avgs.get("FGM", 0) - avgs.get("3PM", 0)) / max(avgs.get("FGA", 0) - avgs.get("3PA", 0), 1) * 100, 1) if (avgs.get("FGA", 0) - avgs.get("3PA", 0)) > 0 else 0.0,
                "tpp": round(avgs.get("3PM", 0) / avgs.get("3PA", 1) * 100, 1) if avgs.get("3PA", 0) > 0 else 0.0,
                "ftp": round(avgs.get("FTM", 0) / avgs.get("FTA", 1) * 100, 1) if avgs.get("FTA", 0) > 0 else 0.0,
                "tpa_pct": round(avgs.get("3PA", 0) / avgs.get("FGA", 1) * 100, 1) if avgs.get("FGA", 0) > 0 else 0.0,
                "ast_pct": round(avgs.get("AST", 0) / max(poss, 1) * 100, 1) if poss > 0 else 0.0,
                "ast_ratio": round(100 * avgs.get("AST", 0) / max(avgs.get("FGA", 0) + 0.475 * avgs.get("FTA", 0) + avgs.get("AST", 0) + avgs.get("TO", 0), 1), 1) if (avgs.get("FGA", 0) + avgs.get("FTA", 0)) > 0 else 0.0,
                "ast_tov": round(avgs.get("AST", 0) / max(avgs.get("TO", 0.01), 0.01), 2),
                "nst_pct": (round((avgs.get("TO", 0) - opp_avgs.get("STL", 0)) / max(poss, 0.01) * 100, 1) if avgs.get("TO", 0) > opp_avgs.get("STL", 0) and poss > 0 else None),
                "stl_to": round(avgs.get("STL", 0) / max(opp_avgs.get("TO", 0.01), 0.01), 2),
                "ts_pct": ts_pct,
                "efg_pct": efg_pct,
                "tov_pct": tov_pct,
                "ft_rate": ft_rate,
                "oreb_pct": oreb_pct,
                "luck": (lambda p=avgs.get("PTS",0), o=opp_avgs.get("PTS",0), r=conf_rec: (
                    round((lambda w,l,gp: w/gp - p**10.25/(p**10.25+o**10.25))(
                        int(r.split('-')[0]), int(r.split('-')[1]),
                        int(r.split('-')[0])+int(r.split('-')[1])
                    ), 4) if p > 0 and o > 0 and '-' in r and int(r.split('-')[0])+int(r.split('-')[1]) > 0 else 0.0
                ))(),
                "possessions": round(poss, 1),
                "ortg": ortg,
                "tempo": tempo,
                "drtg": drtg,
                "net_rtg": net_rtg,
                "opp_adjust": conf_adjustments.get(team, {}).get("opp_adjust", 0),
                "pace_adjust": conf_adjustments.get(team, {}).get("pace_adjust", 0),
                "opp_ortg": 0,  # SOS not applicable for conf-only
                "opp_drtg_sos": 0,
                "sos": 0,
                "ncsos": 0,
                # Defensive stats
                "opp_efg_pct": opp_efg_pct,
                "dreb_pct": dreb_pct,
                "opp_tov_pct": opp_tov_pct,
                "opp_ft_rate": opp_ft_rate,
                "opp_orebpg": opp_avgs.get("OREB", 0),
                "opp_drebpg": opp_avgs.get("DREB", 0),
                "opp_rpg": opp_avgs.get("REB", 0),
                "opp_apg": opp_avgs.get("AST", 0),
                "opp_topg": opp_avgs.get("TO", 0),
                "opp_spg": opp_avgs.get("STL", 0),
                "opp_bpg": opp_avgs.get("BLK", 0),
                "opp_fgp": round(opp_avgs.get("FGM", 0) / opp_avgs.get("FGA", 1) * 100, 1) if opp_avgs.get("FGA", 0) > 0 else 0.0,
                "opp_twop": round((opp_avgs.get("FGM", 0) - opp_avgs.get("3PM", 0)) / max(opp_avgs.get("FGA", 0) - opp_avgs.get("3PA", 0), 1) * 100, 1) if (opp_avgs.get("FGA", 0) - opp_avgs.get("3PA", 0)) > 0 else 0.0,
                "opp_tpp": round(opp_avgs.get("3PM", 0) / opp_avgs.get("3PA", 1) * 100, 1) if opp_avgs.get("3PA", 0) > 0 else 0.0,
                "opp_ftp": round(opp_avgs.get("FTM", 0) / opp_avgs.get("FTA", 1) * 100, 1) if opp_avgs.get("FTA", 0) > 0 else 0.0,
                "opp_tpa_pct": round(opp_avgs.get("3PA", 0) / opp_avgs.get("FGA", 1) * 100, 1) if opp_avgs.get("FGA", 0) > 0 else 0.0,
                "opp_ts_pct": opp_ts_pct,
                "stl_pct": round(totals.get("STL", 0) / max((opp_totals.get("FGA", 0) - opp_totals.get("OREB", 0)) + opp_totals.get("TO", 0) + 0.475 * opp_totals.get("FTA", 0), 0.1) * 100, 1),
                "blk_pct": round(totals.get("BLK", 0) / max(opp_totals.get("FGA", 1), 1) * 100, 1),
                "hkm_pct": round(
                    round(totals.get("BLK", 0) / max(opp_totals.get("FGA", 1), 1) * 100, 1) +
                    round(totals.get("STL", 0) / max((opp_totals.get("FGA", 0) - opp_totals.get("OREB", 0)) + opp_totals.get("TO", 0) + 0.475 * opp_totals.get("FTA", 0), 0.1) * 100, 1), 1),
                "pf_total": totals.get("PF", 0),
                "pf_eff": round((totals.get("STL", 0) + totals.get("BLK", 0)) / max(totals.get("PF", 0.1), 0.1), 2),
                "stl_pf": round(totals.get("STL", 0) / max(totals.get("PF", 0.1), 0.1), 2),
                "blk_pf": round(totals.get("BLK", 0) / max(totals.get("PF", 0.1), 0.1), 2),
                "totals": {
                    "FGM": totals.get("FGM", 0), "FGA": totals.get("FGA", 0),
                    "3PM": totals.get("3PM", 0), "3PA": totals.get("3PA", 0),
                    "FTM": totals.get("FTM", 0), "FTA": totals.get("FTA", 0),
                    "STL": totals.get("STL", 0), "BLK": totals.get("BLK", 0),
                },
                "opp_totals": {
                    "FGM": opp_totals.get("FGM", 0), "FGA": opp_totals.get("FGA", 0),
                    "3PM": opp_totals.get("3PM", 0), "3PA": opp_totals.get("3PA", 0),
                    "FTM": opp_totals.get("FTM", 0), "FTA": opp_totals.get("FTA", 0),
                    "STL": opp_totals.get("STL", 0), "BLK": opp_totals.get("BLK", 0),
                },
                "game_ratings": [g for g in ta.get("game_ratings", []) if g.get("is_conference")],
            })

    teams.sort(key=lambda x: -x["net_rtg"])
    return teams


def load_storylines(stats_dir=None) -> dict:
    if stats_dir is None:
        stats_dir = STATS_DIR
    # Seed each season's storylines with decayed prior-season NET ratings so
    # early-season games have a meaningful baseline instead of 0.0.
    # 2025-26 → 2024-25; 2024-25 → 2023-24; 2023-24 → 2022-23; 2022-23 → 2021-22; others → no prior.
    if stats_dir == STATS_DIR:
        prior_dir = STATS_DIR_2024
    elif stats_dir == STATS_DIR_2024:
        prior_dir = STATS_DIR_2023
    elif stats_dir == STATS_DIR_2023:
        prior_dir = STATS_DIR_2022
    elif stats_dir == STATS_DIR_2022:
        prior_dir = STATS_DIR_2021
    elif stats_dir == STATS_DIR_2021:
        prior_dir = STATS_DIR_2019
    elif stats_dir == STATS_DIR_2019:
        prior_dir = STATS_DIR_1819
    elif stats_dir == STATS_DIR_1819:
        prior_dir = STATS_DIR_1718
    else:
        prior_dir = None
    try:
        return build_storylines(stats_dir=stats_dir, top=100, exclude_zero_scores=True,
                                hca_points=3.0, wp_scale=10.0, prior_stats_dir=prior_dir)
    except Exception as e:
        print(f"  Warning: could not load storylines: {e}")
        return {}


def generate_html(players, teams, conf_players, conf_teams, teams_2024=None, conf_teams_2024=None,
                  players_2024=None, conf_players_2024=None, storylines_2024=None,
                  teams_2023=None, conf_teams_2023=None,
                  players_2023=None, conf_players_2023=None, storylines_2023=None,
                  teams_2022=None, conf_teams_2022=None,
                  players_2022=None, conf_players_2022=None, storylines_2022=None,
                  teams_2021=None, conf_teams_2021=None,
                  players_2021=None, conf_players_2021=None, storylines_2021=None,
                  teams_2019=None, conf_teams_2019=None,
                  players_2019=None, conf_players_2019=None, storylines_2019=None,
                  rpi_data_2526=None, rpi_data_2425=None,
                  rpi_data_2324=None, rpi_data_2223=None, rpi_data_2122=None, rpi_data_1920=None,
                  teams_1819=None, conf_teams_1819=None,
                  players_1819=None, conf_players_1819=None, storylines_1819=None,
                  teams_1718=None, conf_teams_1718=None,
                  players_1718=None, conf_players_1718=None, storylines_1718=None,
                  rpi_data_1819=None, rpi_data_1718=None):
    """Generate a self-contained sortable HTML leaderboard with team/individual toggle."""
    if teams_2024 is None:
        teams_2024 = []
    if conf_teams_2024 is None:
        conf_teams_2024 = []
    if players_2024 is None:
        players_2024 = []
    if conf_players_2024 is None:
        conf_players_2024 = []
    if storylines_2024 is None:
        storylines_2024 = {}
    if teams_2023 is None:
        teams_2023 = []
    if conf_teams_2023 is None:
        conf_teams_2023 = []
    if players_2023 is None:
        players_2023 = []
    if conf_players_2023 is None:
        conf_players_2023 = []
    if storylines_2023 is None:
        storylines_2023 = {}
    if teams_2022 is None:
        teams_2022 = []
    if conf_teams_2022 is None:
        conf_teams_2022 = []
    if players_2022 is None:
        players_2022 = []
    if conf_players_2022 is None:
        conf_players_2022 = []
    if storylines_2022 is None:
        storylines_2022 = {}
    if teams_2021 is None:
        teams_2021 = []
    if conf_teams_2021 is None:
        conf_teams_2021 = []
    if players_2021 is None:
        players_2021 = []
    if conf_players_2021 is None:
        conf_players_2021 = []
    if storylines_2021 is None:
        storylines_2021 = {}
    if rpi_data_2526 is None:
        rpi_data_2526 = []
    if rpi_data_2425 is None:
        rpi_data_2425 = []
    if rpi_data_2324 is None:
        rpi_data_2324 = []
    if rpi_data_2223 is None:
        rpi_data_2223 = []
    if rpi_data_2122 is None:
        rpi_data_2122 = []
    if rpi_data_1920 is None:
        rpi_data_1920 = []
    if teams_2019 is None:
        teams_2019 = []
    if conf_teams_2019 is None:
        conf_teams_2019 = []
    if players_2019 is None:
        players_2019 = []
    if conf_players_2019 is None:
        conf_players_2019 = []
    if storylines_2019 is None:
        storylines_2019 = {}
    if teams_1819 is None:
        teams_1819 = []
    if conf_teams_1819 is None:
        conf_teams_1819 = []
    if players_1819 is None:
        players_1819 = []
    if conf_players_1819 is None:
        conf_players_1819 = []
    if storylines_1819 is None:
        storylines_1819 = {}
    if teams_1718 is None:
        teams_1718 = []
    if conf_teams_1718 is None:
        conf_teams_1718 = []
    if players_1718 is None:
        players_1718 = []
    if conf_players_1718 is None:
        conf_players_1718 = []
    if storylines_1718 is None:
        storylines_1718 = {}
    if rpi_data_1819 is None:
        rpi_data_1819 = []
    if rpi_data_1718 is None:
        rpi_data_1718 = []
    rpi_data_2526_json = json.dumps(rpi_data_2526)
    rpi_data_2425_json = json.dumps(rpi_data_2425)
    rpi_data_2324_json = json.dumps(rpi_data_2324)
    rpi_data_2223_json = json.dumps(rpi_data_2223)
    rpi_data_2122_json = json.dumps(rpi_data_2122)
    rpi_data_1920_json = json.dumps(rpi_data_1920)
    teams_2019_json = json.dumps(teams_2019)
    conf_teams_2019_json = json.dumps(conf_teams_2019)
    players_2019_json = json.dumps(players_2019)
    conf_players_2019_json = json.dumps(conf_players_2019)
    storylines_2019_json = json.dumps(storylines_2019)
    rpi_data_1819_json = json.dumps(rpi_data_1819)
    rpi_data_1718_json = json.dumps(rpi_data_1718)
    teams_1819_json = json.dumps(teams_1819)
    conf_teams_1819_json = json.dumps(conf_teams_1819)
    players_1819_json = json.dumps(players_1819)
    conf_players_1819_json = json.dumps(conf_players_1819)
    storylines_1819_json = json.dumps(storylines_1819)
    teams_1718_json = json.dumps(teams_1718)
    conf_teams_1718_json = json.dumps(conf_teams_1718)
    players_1718_json = json.dumps(players_1718)
    conf_players_1718_json = json.dumps(conf_players_1718)
    storylines_1718_json = json.dumps(storylines_1718)
    players_json = json.dumps(players)
    teams_json = json.dumps(teams)
    conf_players_json = json.dumps(conf_players)
    conf_teams_json = json.dumps(conf_teams)
    conf_teams_2024_json = json.dumps(conf_teams_2024)
    players_2024_json = json.dumps(players_2024)
    conf_players_2024_json = json.dumps(conf_players_2024)
    storylines_2024_json = json.dumps(storylines_2024)
    storylines_2023_json = json.dumps(storylines_2023)
    players_2023_json = json.dumps(players_2023)
    conf_players_2023_json = json.dumps(conf_players_2023)
    players_2022_json = json.dumps(players_2022)
    conf_players_2022_json = json.dumps(conf_players_2022)
    storylines_2022_json = json.dumps(storylines_2022)
    players_2021_json = json.dumps(players_2021)
    conf_players_2021_json = json.dumps(conf_players_2021)
    storylines_2021_json = json.dumps(storylines_2021)
    storylines = load_storylines()
    storylines_json = json.dumps(storylines)
    timestamp = datetime.now().strftime("%B %d, %Y %I:%M %p")

    # Load WAB results
    wab_path = Path("wab_results.json")
    wab_data = []
    if wab_path.exists():
        try:
            with open(wab_path) as f:
                raw = json.load(f)
            # Attach region from CONFERENCES lookup
            conf_to_region = {c: info["region"] for c, info in CONFERENCES.items()}
            for entry in raw:
                entry["region"] = conf_to_region.get(entry.get("conference", ""), "")
            wab_data = raw
        except Exception as e:
            print(f"  Warning: could not load wab_results.json: {e}")
    wab_json = json.dumps(wab_data)

    # Load 2024-25 WAB results
    wab_path_2024 = Path("wab_results_2024_25.json")
    wab_data_2024 = []
    if wab_path_2024.exists():
        try:
            with open(wab_path_2024) as f:
                raw2 = json.load(f)
            conf_to_region = {c: info["region"] for c, info in CONFERENCES.items()}
            for entry in raw2:
                entry["region"] = conf_to_region.get(entry.get("conference", ""), "")
            wab_data_2024 = raw2
        except Exception as e:
            print(f"  Warning: could not load wab_results_2024_25.json: {e}")
    wab_2024_json = json.dumps(wab_data_2024)

    # Load 2023-24 WAB results
    wab_path_2023 = Path("wab_results_2023_24.json")
    wab_data_2023 = []
    if wab_path_2023.exists():
        try:
            with open(wab_path_2023) as f:
                raw3 = json.load(f)
            conf_to_region = {c: info["region"] for c, info in CONFERENCES.items()}
            for entry in raw3:
                entry["region"] = conf_to_region.get(entry.get("conference", ""), "")
            wab_data_2023 = raw3
        except Exception as e:
            print(f"  Warning: could not load wab_results_2023_24.json: {e}")
    wab_2023_json = json.dumps(wab_data_2023)

    # Load 2022-23 WAB results
    wab_path_2022 = Path("wab_results_2022_23.json")
    wab_data_2022 = []
    if wab_path_2022.exists():
        try:
            with open(wab_path_2022) as f:
                raw4 = json.load(f)
            conf_to_region = {c: info["region"] for c, info in CONFERENCES.items()}
            for entry in raw4:
                entry["region"] = conf_to_region.get(entry.get("conference", ""), "")
            wab_data_2022 = raw4
        except Exception as e:
            print(f"  Warning: could not load wab_results_2022_23.json: {e}")
    wab_2022_json = json.dumps(wab_data_2022)

    # Load 2021-22 WAB results
    wab_path_2021 = Path("wab_results_2021_22.json")
    wab_data_2021 = []
    if wab_path_2021.exists():
        try:
            with open(wab_path_2021) as f:
                raw5 = json.load(f)
            conf_to_region = {c: info["region"] for c, info in CONFERENCES.items()}
            for entry in raw5:
                entry["region"] = conf_to_region.get(entry.get("conference", ""), "")
            wab_data_2021 = raw5
        except Exception as e:
            print(f"  Warning: could not load wab_results_2021_22.json: {e}")
    wab_2021_json = json.dumps(wab_data_2021)

    # Load split WAB simulation data (North/South, bubble @24)
    wab_sim_2526 = {'north': [], 'south': []}
    sim_path_2526 = Path('wab_sim_split24.json')
    if sim_path_2526.exists():
        try:
            wab_sim_2526 = json.load(open(sim_path_2526))
        except Exception as e:
            print(f'  Warning: could not load wab_sim_split24.json: {e}')
    wab_sim_2526_json = json.dumps(wab_sim_2526)

    wab_sim_2425 = {'north': [], 'south': []}
    sim_path_2425 = Path('wab_sim_split24_2024_25.json')
    if sim_path_2425.exists():
        try:
            wab_sim_2425 = json.load(open(sim_path_2425))
        except Exception as e:
            print(f'  Warning: could not load wab_sim_split24_2024_25.json: {e}')
    wab_sim_2425_json = json.dumps(wab_sim_2425)

    wab_sim_2324 = {'north': [], 'south': []}
    sim_path_2324 = Path('wab_sim_split24_2023_24.json')
    if sim_path_2324.exists():
        try:
            wab_sim_2324 = json.load(open(sim_path_2324))
        except Exception as e:
            print(f'  Warning: could not load wab_sim_split24_2023_24.json: {e}')
    wab_sim_2324_json = json.dumps(wab_sim_2324)

    wab_sim_2223 = {'north': [], 'south': []}
    sim_path_2223 = Path('wab_sim_split24_2022_23.json')
    if sim_path_2223.exists():
        try:
            wab_sim_2223 = json.load(open(sim_path_2223))
        except Exception as e:
            print(f'  Warning: could not load wab_sim_split24_2022_23.json: {e}')
    wab_sim_2223_json = json.dumps(wab_sim_2223)

    wab_sim_2122 = {'north': [], 'south': []}
    wab_sim_2122_json = json.dumps(wab_sim_2122)

    wab_sim_1920 = {'north': [], 'south': []}
    wab_sim_1920_json = json.dumps(wab_sim_1920)

    # Helper: compute historical daily NET RTG rankings from a teams list
    from collections import defaultdict
    from datetime import datetime as dt_parse
    _CDR_DECAY = 0.60
    _CDR_FADE  = 5
    _DR_HCA = 3.0
    _DR_REG_GAMES = 10
    _DR_DAMPEN = 0.5
    _DR_MAX_ITER = 25
    _DR_REC_MIN = 0.90
    _DR_REC_MAX = 1.10
    _DR_IMP_BASE = 0.95
    _DR_IMP_MARGIN = 0.05
    _DR_IMP_OPP = 0.03
    _DR_IMP_SCALE = 25.0
    def compute_daily_ranks(team_list, prior_teams=None):
        def parse_date(d):
            for fmt in ("%m/%d/%Y", "%m/%d/%y"):
                try:
                    return dt_parse.strptime(d, fmt)
                except ValueError:
                    continue
            return dt_parse(2099, 1, 1)
        team_names = [t.get("team") for t in team_list if t.get("team")]
        team_events = {name: [] for name in team_names}
        for t in team_list:
            tname = t.get("team")
            if not tname:
                continue
            for gr in t.get("game_ratings", []):
                if not (gr.get("ortg") and gr.get("drtg") and gr.get("date")):
                    continue
                canonical = gr.get("canonical_opponent")
                if not canonical or canonical not in team_events:
                    continue
                team_events[tname].append({
                    "date": gr["date"],
                    "date_obj": parse_date(gr["date"]),
                    "ortg": float(gr["ortg"]),
                    "drtg": float(gr["drtg"]),
                    "opp": canonical,
                    "loc": gr.get("location", ""),
                    "team_score": float(gr.get("team_score", 0) or 0),
                    "opp_score": float(gr.get("opponent_score", 0) or 0),
                })

        all_dates = sorted({e["date"] for vals in team_events.values() for e in vals}, key=parse_date)
        if not all_dates:
            return {}

        prior_seed = {}
        if prior_teams:
            _cur_v = [t for t in team_list if t.get("ortg", 0) > 0 and t.get("drtg", 0) > 0]
            _pri_v = [t for t in prior_teams if t.get("ortg", 0) > 0 and t.get("drtg", 0) > 0]
            if _cur_v and _pri_v:
                _lg_oc = sum(t["ortg"] for t in _cur_v) / len(_cur_v)
                _lg_dc = sum(t["drtg"] for t in _cur_v) / len(_cur_v)
                _lg_op = sum(t["ortg"] for t in _pri_v) / len(_pri_v)
                _lg_dp = sum(t["drtg"] for t in _pri_v) / len(_pri_v)
                _prior_map = {t["team"]: t for t in _pri_v}
                for t in _cur_v:
                    p = _prior_map.get(t["team"])
                    if not p:
                        continue
                    prior_seed[t["team"]] = {
                        "ortg": _lg_oc + (p["ortg"] - _lg_op) * _CDR_DECAY,
                        "drtg": _lg_dc + (p["drtg"] - _lg_dp) * _CDR_DECAY,
                    }

        ranks = {}
        for d_str in all_dates:
            cutoff = parse_date(d_str)
            games_up_to = {
                t: [e for e in evs if e["date_obj"] <= cutoff]
                for t, evs in team_events.items()
            }

            date_buckets = {}
            for evs in games_up_to.values():
                for e in evs:
                    b = date_buckets.setdefault(e["date"], {"o": [], "d": []})
                    b["o"].append(e["ortg"])
                    b["d"].append(e["drtg"])
            date_base = {
                ds: {
                    "ortg": (sum(v["o"]) / len(v["o"])) if v["o"] else 100.0,
                    "drtg": (sum(v["d"]) / len(v["d"])) if v["d"] else 100.0,
                }
                for ds, v in date_buckets.items()
            }

            seeds = {}
            for t in team_names:
                if t in prior_seed:
                    seeds[t] = dict(prior_seed[t])
                    continue
                evs = games_up_to.get(t, [])
                if evs:
                    seeds[t] = {
                        "ortg": sum(e["ortg"] for e in evs) / len(evs),
                        "drtg": sum(e["drtg"] for e in evs) / len(evs),
                    }
                else:
                    seeds[t] = {"ortg": 100.0, "drtg": 100.0}

            target_o = sum(v["ortg"] for v in seeds.values()) / max(len(seeds), 1)
            target_d = sum(v["drtg"] for v in seeds.values()) / max(len(seeds), 1)
            current = {t: dict(v) for t, v in seeds.items()}

            season_start = min((e["date_obj"] for evs in games_up_to.values() for e in evs), default=cutoff)
            season_end = cutoff

            def _game_weight(e, opp_net):
                rec = 1.0
                if season_end > season_start:
                    frac = (e["date_obj"] - season_start).days / (season_end - season_start).days
                    frac = max(0.0, min(1.0, frac))
                    rec = _DR_REC_MIN + (_DR_REC_MAX - _DR_REC_MIN) * frac
                margin = abs(e["team_score"] - e["opp_score"])
                margin_term = min(margin, _DR_IMP_SCALE) / _DR_IMP_SCALE
                opp_term = min(abs(opp_net), _DR_IMP_SCALE) / _DR_IMP_SCALE
                imp = _DR_IMP_BASE + _DR_IMP_MARGIN * margin_term + _DR_IMP_OPP * opp_term
                return rec * imp

            for _ in range(_DR_MAX_ITER):
                new_r = {}
                for t in team_names:
                    evs = games_up_to.get(t, [])
                    if not evs:
                        new_r[t] = {"ortg": target_o, "drtg": target_d}
                        continue
                    ao, ad = [], []
                    for e in evs:
                        opp = e["opp"]
                        if opp not in current:
                            ao.append((e["ortg"], 1.0))
                            ad.append((e["drtg"], 1.0))
                            continue
                        hco = hcd = 0.0
                        if e["loc"] == "Home":
                            hco = -_DR_HCA / 2
                            hcd = +_DR_HCA / 2
                        elif e["loc"] == "Away":
                            hco = +_DR_HCA / 2
                            hcd = -_DR_HCA / 2
                        opp_d = current[opp]["drtg"]
                        opp_o = current[opp]["ortg"]
                        opp_net = opp_o - opp_d
                        b = date_base.get(e["date"], {"ortg": target_o, "drtg": target_d})
                        w = _game_weight(e, opp_net)
                        ao.append((e["ortg"] + hco - opp_d + b["drtg"], w))
                        ad.append((e["drtg"] + hcd - opp_o + b["ortg"], w))

                    if ao and ad:
                        swo = sum(w for _, w in ao)
                        swd = sum(w for _, w in ad)
                        go = sum(v * w for v, w in ao) / swo if swo else target_o
                        gd = sum(v * w for v, w in ad) / swd if swd else target_d
                        n_eff = min(swo, swd)
                        blend = n_eff / (n_eff + _DR_REG_GAMES)
                        reg_o = blend * go + (1 - blend) * target_o
                        reg_d = blend * gd + (1 - blend) * target_d
                        new_r[t] = {
                            "ortg": _DR_DAMPEN * reg_o + (1 - _DR_DAMPEN) * current[t]["ortg"],
                            "drtg": _DR_DAMPEN * reg_d + (1 - _DR_DAMPEN) * current[t]["drtg"],
                        }
                    else:
                        new_r[t] = {"ortg": target_o, "drtg": target_d}

                avg_o = sum(v["ortg"] for v in new_r.values()) / max(len(new_r), 1)
                avg_d = sum(v["drtg"] for v in new_r.values()) / max(len(new_r), 1)
                so = target_o - avg_o
                sd = target_d - avg_d
                for t in new_r:
                    new_r[t]["ortg"] += so
                    new_r[t]["drtg"] += sd

                max_change = max(
                    max(abs(new_r[t]["ortg"] - current[t]["ortg"]), abs(new_r[t]["drtg"] - current[t]["drtg"]))
                    for t in team_names
                ) if team_names else 0.0
                current = new_r
                if max_change < 0.05:
                    break

            team_nets = [(t, current[t]["ortg"] - current[t]["drtg"]) for t in team_names]
            team_nets.sort(key=lambda x: -x[1])
            ranks[d_str] = {tname: i + 1 for i, (tname, _) in enumerate(team_nets)}

        return ranks

    # Compute current-season daily rankings with iterative as-of-date logic
    daily_ranks = compute_daily_ranks(teams or [], prior_teams=teams_2024 or [])
    daily_ranks_json = json.dumps(daily_ranks)

    # Compute 2024-25 daily rankings using the same helper
    daily_ranks_2024 = compute_daily_ranks(teams_2024 or [], prior_teams=teams_2023 or [])
    daily_ranks_2024_json = json.dumps(daily_ranks_2024)

    all_teams = []
    for conf_info in CONFERENCES.values():
        all_teams.extend(conf_info["teams"])
    all_teams.sort()

    # Compute league averages for team detail view
    valid_teams = [t for t in teams if t["ortg"] > 0]
    n = len(valid_teams) if valid_teams else 1
    league_avg = {}
    for key in ["ortg", "drtg", "tempo", "net_rtg", "efg_pct", "tov_pct", "oreb_pct",
                "ft_rate", "ts_pct", "opp_efg_pct", "dreb_pct", "opp_tov_pct",
                "opp_ft_rate", "opp_ts_pct", "sos", "ncsos"]:
        league_avg[key] = round(sum(t.get(key, 0) for t in valid_teams) / n, 1)
    # Shooting averages from totals
    tot_fgm = sum(t["totals"]["FGM"] for t in valid_teams)
    tot_fga = sum(t["totals"]["FGA"] for t in valid_teams)
    tot_3pm = sum(t["totals"]["3PM"] for t in valid_teams)
    tot_3pa = sum(t["totals"]["3PA"] for t in valid_teams)
    tot_ftm = sum(t["totals"]["FTM"] for t in valid_teams)
    tot_fta = sum(t["totals"]["FTA"] for t in valid_teams)
    league_avg["fg_pct"] = round(tot_fgm / max(tot_fga, 1) * 100, 1)
    league_avg["3p_pct"] = round(tot_3pm / max(tot_3pa, 1) * 100, 1)
    league_avg["ft_pct"] = round(tot_ftm / max(tot_fta, 1) * 100, 1)
    league_avg["2p_pct"] = round((tot_fgm - tot_3pm) / max(tot_fga - tot_3pa, 1) * 100, 1)
    league_avg["3pa_rate"] = round(tot_3pa / max(tot_fga, 1) * 100, 1)
    _sd_base = max(tot_fga + 0.475 * tot_fta, 1)
    league_avg["shot_dist_2pa"] = round((tot_fga - tot_3pa) / _sd_base * 100, 1)
    league_avg["shot_dist_3pa"] = round(tot_3pa / _sd_base * 100, 1)
    league_avg["shot_dist_fta"] = round(0.475 * tot_fta / _sd_base * 100, 1)
    league_avg_json = json.dumps(league_avg)

    # Compute 2024-25 league averages for the season toggle
    teams_2024_json = json.dumps(teams_2024)
    valid_2024 = [t for t in teams_2024 if t.get("ortg", 0) > 0]
    n24 = len(valid_2024) if valid_2024 else 1
    league_avg_2024 = {}
    for key in ["ortg", "drtg", "tempo", "net_rtg", "efg_pct", "tov_pct", "oreb_pct",
                "ft_rate", "ts_pct", "opp_efg_pct", "dreb_pct", "opp_tov_pct",
                "opp_ft_rate", "opp_ts_pct", "sos", "ncsos"]:
        league_avg_2024[key] = round(sum(t.get(key, 0) for t in valid_2024) / n24, 1)
    t24_fgm = sum(t["totals"]["FGM"] for t in valid_2024)
    t24_fga = sum(t["totals"]["FGA"] for t in valid_2024)
    t24_3pm = sum(t["totals"]["3PM"] for t in valid_2024)
    t24_3pa = sum(t["totals"]["3PA"] for t in valid_2024)
    t24_ftm = sum(t["totals"]["FTM"] for t in valid_2024)
    t24_fta = sum(t["totals"]["FTA"] for t in valid_2024)
    league_avg_2024["fg_pct"] = round(t24_fgm / max(t24_fga, 1) * 100, 1)
    league_avg_2024["3p_pct"] = round(t24_3pm / max(t24_3pa, 1) * 100, 1)
    league_avg_2024["ft_pct"] = round(t24_ftm / max(t24_fta, 1) * 100, 1)
    league_avg_2024["2p_pct"] = round((t24_fgm - t24_3pm) / max(t24_fga - t24_3pa, 1) * 100, 1)
    league_avg_2024["3pa_rate"] = round(t24_3pa / max(t24_fga, 1) * 100, 1)
    _sd24_base = max(t24_fga + 0.475 * t24_fta, 1)
    league_avg_2024["shot_dist_2pa"] = round((t24_fga - t24_3pa) / _sd24_base * 100, 1)
    league_avg_2024["shot_dist_3pa"] = round(t24_3pa / _sd24_base * 100, 1)
    league_avg_2024["shot_dist_fta"] = round(0.475 * t24_fta / _sd24_base * 100, 1)
    league_avg_2024_json = json.dumps(league_avg_2024)

    # Compute 2023-24 league averages
    teams_2023_json = json.dumps(teams_2023)
    conf_teams_2023_json = json.dumps(conf_teams_2023)
    valid_2023 = [t for t in teams_2023 if t.get("ortg", 0) > 0]
    n23 = len(valid_2023) if valid_2023 else 1
    league_avg_2023 = {}
    for key in ["ortg", "drtg", "tempo", "net_rtg", "efg_pct", "tov_pct", "oreb_pct",
                "ft_rate", "ts_pct", "opp_efg_pct", "dreb_pct", "opp_tov_pct",
                "opp_ft_rate", "opp_ts_pct", "sos", "ncsos"]:
        league_avg_2023[key] = round(sum(t.get(key, 0) for t in valid_2023) / n23, 1)
    t23_fgm = sum(t["totals"]["FGM"] for t in valid_2023)
    t23_fga = sum(t["totals"]["FGA"] for t in valid_2023)
    t23_3pm = sum(t["totals"]["3PM"] for t in valid_2023)
    t23_3pa = sum(t["totals"]["3PA"] for t in valid_2023)
    t23_ftm = sum(t["totals"]["FTM"] for t in valid_2023)
    t23_fta = sum(t["totals"]["FTA"] for t in valid_2023)
    league_avg_2023["fg_pct"] = round(t23_fgm / max(t23_fga, 1) * 100, 1)
    league_avg_2023["3p_pct"] = round(t23_3pm / max(t23_3pa, 1) * 100, 1)
    league_avg_2023["ft_pct"] = round(t23_ftm / max(t23_fta, 1) * 100, 1)
    league_avg_2023["2p_pct"] = round((t23_fgm - t23_3pm) / max(t23_fga - t23_3pa, 1) * 100, 1)
    league_avg_2023["3pa_rate"] = round(t23_3pa / max(t23_fga, 1) * 100, 1)
    _sd23_base = max(t23_fga + 0.475 * t23_fta, 1)
    league_avg_2023["shot_dist_2pa"] = round((t23_fga - t23_3pa) / _sd23_base * 100, 1)
    league_avg_2023["shot_dist_3pa"] = round(t23_3pa / _sd23_base * 100, 1)
    league_avg_2023["shot_dist_fta"] = round(0.475 * t23_fta / _sd23_base * 100, 1)
    daily_ranks_2023 = compute_daily_ranks(teams_2023 or [], prior_teams=teams_2022 or [])
    daily_ranks_2023_json = json.dumps(daily_ranks_2023)
    league_avg_2023_json = json.dumps(league_avg_2023)

    # Compute 2022-23 league averages
    teams_2022_json = json.dumps(teams_2022)
    conf_teams_2022_json = json.dumps(conf_teams_2022)
    valid_2022 = [t for t in teams_2022 if t.get("ortg", 0) > 0]
    n22 = len(valid_2022) if valid_2022 else 1
    league_avg_2022 = {}
    for key in ["ortg", "drtg", "tempo", "net_rtg", "efg_pct", "tov_pct", "oreb_pct",
                "ft_rate", "ts_pct", "opp_efg_pct", "dreb_pct", "opp_tov_pct",
                "opp_ft_rate", "opp_ts_pct", "sos", "ncsos"]:
        league_avg_2022[key] = round(sum(t.get(key, 0) for t in valid_2022) / n22, 1)
    t22_fgm = sum(t["totals"]["FGM"] for t in valid_2022)
    t22_fga = sum(t["totals"]["FGA"] for t in valid_2022)
    t22_3pm = sum(t["totals"]["3PM"] for t in valid_2022)
    t22_3pa = sum(t["totals"]["3PA"] for t in valid_2022)
    t22_ftm = sum(t["totals"]["FTM"] for t in valid_2022)
    t22_fta = sum(t["totals"]["FTA"] for t in valid_2022)
    league_avg_2022["fg_pct"] = round(t22_fgm / max(t22_fga, 1) * 100, 1)
    league_avg_2022["3p_pct"] = round(t22_3pm / max(t22_3pa, 1) * 100, 1)
    league_avg_2022["ft_pct"] = round(t22_ftm / max(t22_fta, 1) * 100, 1)
    league_avg_2022["2p_pct"] = round((t22_fgm - t22_3pm) / max(t22_fga - t22_3pa, 1) * 100, 1)
    league_avg_2022["3pa_rate"] = round(t22_3pa / max(t22_fga, 1) * 100, 1)
    _sd22_base = max(t22_fga + 0.475 * t22_fta, 1)
    league_avg_2022["shot_dist_2pa"] = round((t22_fga - t22_3pa) / _sd22_base * 100, 1)
    league_avg_2022["shot_dist_3pa"] = round(t22_3pa / _sd22_base * 100, 1)
    league_avg_2022["shot_dist_fta"] = round(0.475 * t22_fta / _sd22_base * 100, 1)
    daily_ranks_2022 = compute_daily_ranks(teams_2022 or [], prior_teams=teams_2021 or [])
    daily_ranks_2022_json = json.dumps(daily_ranks_2022)
    league_avg_2022_json = json.dumps(league_avg_2022)

    # Compute 2021-22 league averages
    teams_2021_json = json.dumps(teams_2021)
    conf_teams_2021_json = json.dumps(conf_teams_2021)
    valid_2021 = [t for t in teams_2021 if t.get("ortg", 0) > 0]
    n21 = len(valid_2021) if valid_2021 else 1
    league_avg_2021 = {}
    for key in ["ortg", "drtg", "tempo", "net_rtg", "efg_pct", "tov_pct", "oreb_pct",
                "ft_rate", "ts_pct", "opp_efg_pct", "dreb_pct", "opp_tov_pct",
                "opp_ft_rate", "opp_ts_pct", "sos", "ncsos"]:
        league_avg_2021[key] = round(sum(t.get(key, 0) for t in valid_2021) / n21, 1)
    t21_fgm = sum(t["totals"]["FGM"] for t in valid_2021)
    t21_fga = sum(t["totals"]["FGA"] for t in valid_2021)
    t21_3pm = sum(t["totals"]["3PM"] for t in valid_2021)
    t21_3pa = sum(t["totals"]["3PA"] for t in valid_2021)
    t21_ftm = sum(t["totals"]["FTM"] for t in valid_2021)
    t21_fta = sum(t["totals"]["FTA"] for t in valid_2021)
    league_avg_2021["fg_pct"] = round(t21_fgm / max(t21_fga, 1) * 100, 1)
    league_avg_2021["3p_pct"] = round(t21_3pm / max(t21_3pa, 1) * 100, 1)
    league_avg_2021["ft_pct"] = round(t21_ftm / max(t21_fta, 1) * 100, 1)
    league_avg_2021["2p_pct"] = round((t21_fgm - t21_3pm) / max(t21_fga - t21_3pa, 1) * 100, 1)
    league_avg_2021["3pa_rate"] = round(t21_3pa / max(t21_fga, 1) * 100, 1)
    _sd21_base = max(t21_fga + 0.475 * t21_fta, 1)
    league_avg_2021["shot_dist_2pa"] = round((t21_fga - t21_3pa) / _sd21_base * 100, 1)
    league_avg_2021["shot_dist_3pa"] = round(t21_3pa / _sd21_base * 100, 1)
    league_avg_2021["shot_dist_fta"] = round(0.475 * t21_fta / _sd21_base * 100, 1)
    daily_ranks_2021 = compute_daily_ranks(teams_2021 or [], prior_teams=teams_2019 or [])
    daily_ranks_2021_json = json.dumps(daily_ranks_2021)
    league_avg_2021_json = json.dumps(league_avg_2021)

    # Compute 2019-20 league averages
    valid_2019 = [t for t in teams_2019 if t.get("ortg", 0) > 0]
    n19 = len(valid_2019) if valid_2019 else 1
    league_avg_2019 = {}
    for key in ["ortg", "drtg", "tempo", "net_rtg", "efg_pct", "tov_pct", "oreb_pct",
                "ft_rate", "ts_pct", "opp_efg_pct", "dreb_pct", "opp_tov_pct",
                "opp_ft_rate", "opp_ts_pct", "sos", "ncsos"]:
        league_avg_2019[key] = round(sum(t.get(key, 0) for t in valid_2019) / n19, 1)
    t19_fgm = sum(t["totals"]["FGM"] for t in valid_2019)
    t19_fga = sum(t["totals"]["FGA"] for t in valid_2019)
    t19_3pm = sum(t["totals"]["3PM"] for t in valid_2019)
    t19_3pa = sum(t["totals"]["3PA"] for t in valid_2019)
    t19_ftm = sum(t["totals"]["FTM"] for t in valid_2019)
    t19_fta = sum(t["totals"]["FTA"] for t in valid_2019)
    league_avg_2019["fg_pct"] = round(t19_fgm / max(t19_fga, 1) * 100, 1)
    league_avg_2019["3p_pct"] = round(t19_3pm / max(t19_3pa, 1) * 100, 1)
    league_avg_2019["ft_pct"] = round(t19_ftm / max(t19_fta, 1) * 100, 1)
    league_avg_2019["2p_pct"] = round((t19_fgm - t19_3pm) / max(t19_fga - t19_3pa, 1) * 100, 1)
    league_avg_2019["3pa_rate"] = round(t19_3pa / max(t19_fga, 1) * 100, 1)
    _sd19_base = max(t19_fga + 0.475 * t19_fta, 1)
    league_avg_2019["shot_dist_2pa"] = round((t19_fga - t19_3pa) / _sd19_base * 100, 1)
    league_avg_2019["shot_dist_3pa"] = round(t19_3pa / _sd19_base * 100, 1)
    league_avg_2019["shot_dist_fta"] = round(0.475 * t19_fta / _sd19_base * 100, 1)
    league_avg_2019_json = json.dumps(league_avg_2019)

    # Compute 2018-19 league averages
    valid_1819 = [t for t in teams_1819 if t.get("ortg", 0) > 0]
    n1819 = len(valid_1819) if valid_1819 else 1
    league_avg_1819 = {}
    for key in ["ortg", "drtg", "tempo", "net_rtg", "efg_pct", "tov_pct", "oreb_pct",
                "ft_rate", "ts_pct", "opp_efg_pct", "dreb_pct", "opp_tov_pct",
                "opp_ft_rate", "opp_ts_pct", "sos", "ncsos"]:
        league_avg_1819[key] = round(sum(t.get(key, 0) for t in valid_1819) / n1819, 1)
    t1819_fgm = sum(t["totals"]["FGM"] for t in valid_1819)
    t1819_fga = sum(t["totals"]["FGA"] for t in valid_1819)
    t1819_3pm = sum(t["totals"]["3PM"] for t in valid_1819)
    t1819_3pa = sum(t["totals"]["3PA"] for t in valid_1819)
    t1819_ftm = sum(t["totals"]["FTM"] for t in valid_1819)
    t1819_fta = sum(t["totals"]["FTA"] for t in valid_1819)
    league_avg_1819["fg_pct"] = round(t1819_fgm / max(t1819_fga, 1) * 100, 1)
    league_avg_1819["3p_pct"] = round(t1819_3pm / max(t1819_3pa, 1) * 100, 1)
    league_avg_1819["ft_pct"] = round(t1819_ftm / max(t1819_fta, 1) * 100, 1)
    league_avg_1819["2p_pct"] = round((t1819_fgm - t1819_3pm) / max(t1819_fga - t1819_3pa, 1) * 100, 1)
    league_avg_1819["3pa_rate"] = round(t1819_3pa / max(t1819_fga, 1) * 100, 1)
    _sd1819_base = max(t1819_fga + 0.475 * t1819_fta, 1)
    league_avg_1819["shot_dist_2pa"] = round((t1819_fga - t1819_3pa) / _sd1819_base * 100, 1)
    league_avg_1819["shot_dist_3pa"] = round(t1819_3pa / _sd1819_base * 100, 1)
    league_avg_1819["shot_dist_fta"] = round(0.475 * t1819_fta / _sd1819_base * 100, 1)
    league_avg_1819_json = json.dumps(league_avg_1819)

    # Compute 2017-18 league averages
    valid_1718 = [t for t in teams_1718 if t.get("ortg", 0) > 0]
    n1718 = len(valid_1718) if valid_1718 else 1
    league_avg_1718 = {}
    for key in ["ortg", "drtg", "tempo", "net_rtg", "efg_pct", "tov_pct", "oreb_pct",
                "ft_rate", "ts_pct", "opp_efg_pct", "dreb_pct", "opp_tov_pct",
                "opp_ft_rate", "opp_ts_pct", "sos", "ncsos"]:
        league_avg_1718[key] = round(sum(t.get(key, 0) for t in valid_1718) / n1718, 1)
    t1718_fgm = sum(t["totals"]["FGM"] for t in valid_1718)
    t1718_fga = sum(t["totals"]["FGA"] for t in valid_1718)
    t1718_3pm = sum(t["totals"]["3PM"] for t in valid_1718)
    t1718_3pa = sum(t["totals"]["3PA"] for t in valid_1718)
    t1718_ftm = sum(t["totals"]["FTM"] for t in valid_1718)
    t1718_fta = sum(t["totals"]["FTA"] for t in valid_1718)
    league_avg_1718["fg_pct"] = round(t1718_fgm / max(t1718_fga, 1) * 100, 1)
    league_avg_1718["3p_pct"] = round(t1718_3pm / max(t1718_3pa, 1) * 100, 1)
    league_avg_1718["ft_pct"] = round(t1718_ftm / max(t1718_fta, 1) * 100, 1)
    league_avg_1718["2p_pct"] = round((t1718_fgm - t1718_3pm) / max(t1718_fga - t1718_3pa, 1) * 100, 1)
    league_avg_1718["3pa_rate"] = round(t1718_3pa / max(t1718_fga, 1) * 100, 1)
    _sd1718_base = max(t1718_fga + 0.475 * t1718_fta, 1)
    league_avg_1718["shot_dist_2pa"] = round((t1718_fga - t1718_3pa) / _sd1718_base * 100, 1)
    league_avg_1718["shot_dist_3pa"] = round(t1718_3pa / _sd1718_base * 100, 1)
    league_avg_1718["shot_dist_fta"] = round(0.475 * t1718_fta / _sd1718_base * 100, 1)
    league_avg_1718_json = json.dumps(league_avg_1718)

    # Compute Miyakawa-style Relative Ratings for both seasons
    def _compute_relative_ratings(team_list):
        """Iterative peer-adjusted relative rating (O-Rate, D-Rate, Rel-Rtg)."""
        valid = [t for t in team_list if t.get("ortg", 0) > 0]
        if not valid:
            return []
        N = len(valid)
        avg_ortg  = sum(t["ortg"]  for t in valid) / N
        avg_drtg  = sum(t["drtg"]  for t in valid) / N
        avg_tempo = sum(t.get("tempo", 68.0) for t in valid) / N
        avg_net   = avg_ortg - avg_drtg
        base = {t["team"]: t["net_rtg"] - avg_net for t in valid}
        scores = dict(base)
        PEER_K = 5
        def smooth(vals, idx):
            lo, hi = max(0, idx - PEER_K), min(len(vals) - 1, idx + PEER_K)
            w = vals[lo:hi+1]
            return sum(w) / len(w)
        for _ in range(50):
            srt = sorted(valid, key=lambda t: scores[t["team"]], reverse=True)
            s_scores = [scores[t["team"]] for t in srt]
            s_tempos = [t.get("tempo", 68.0) for t in srt]
            ns = {}
            for i, t in enumerate(srt):
                ps = smooth(s_scores, i)
                pt = smooth(s_tempos, i)
                adj = t.get("opp_adjust", 0) * ps + t.get("pace_adjust", 0) * (pt - avg_tempo)
                ns[t["team"]] = base[t["team"]] + adj
            mean_s = sum(ns.values()) / N
            ns = {k: v - mean_s for k, v in ns.items()}
            if max(abs(ns[t["team"]] - scores[t["team"]]) for t in valid) < 0.001:
                scores = ns
                break
            scores = ns
        srt_final = sorted(valid, key=lambda t: scores[t["team"]], reverse=True)
        results = []
        for idx, t in enumerate(srt_final):
            # Use the adj already encoded in the converged score so that
            # O-Rate + D-Rate == Rel-Rtg exactly (recomputing adj independently
            # diverges because of the mean re-centering done each iteration).
            adj_encoded = scores[t["team"]] - base[t["team"]]
            results.append({
                "team":        t["team"],
                "conference":  t["conference"],
                "o_rate":      round((t["ortg"] - avg_ortg) + adj_encoded / 2, 2),
                "d_rate":      round((avg_drtg - t["drtg"]) + adj_encoded / 2, 2),
                "rel_rating":  round(scores[t["team"]], 2),
                "net_rtg":     t["net_rtg"],
                "opp_adjust":  t.get("opp_adjust", 0),
                "pace_adjust": t.get("pace_adjust", 0),
                "rank_rel":    idx + 1,
            })
        net_sorted = sorted(results, key=lambda x: x["net_rtg"], reverse=True)
        for i, r in enumerate(net_sorted):
            r["rank_net"] = i + 1
        return results

    rel_ratings_2526 = _compute_relative_ratings(teams)
    rel_ratings_2425 = _compute_relative_ratings(teams_2024 or [])
    rel_ratings_2324 = _compute_relative_ratings(teams_2023 or [])
    rel_ratings_2223 = _compute_relative_ratings(teams_2022 or [])
    rel_ratings_2122 = _compute_relative_ratings(teams_2021 or [])
    rel_ratings_1920 = _compute_relative_ratings(teams_2019 or [])
    rel_ratings_1819 = _compute_relative_ratings(teams_1819 or [])
    rel_ratings_1718 = _compute_relative_ratings(teams_1718 or [])
    rel_ratings_2526_json = json.dumps(rel_ratings_2526)
    rel_ratings_2425_json = json.dumps(rel_ratings_2425)
    rel_ratings_2324_json = json.dumps(rel_ratings_2324)
    rel_ratings_2223_json = json.dumps(rel_ratings_2223)
    rel_ratings_2122_json = json.dumps(rel_ratings_2122)
    rel_ratings_1920_json = json.dumps(rel_ratings_1920)
    rel_ratings_1819_json = json.dumps(rel_ratings_1819)
    rel_ratings_1718_json = json.dumps(rel_ratings_1718)
    daily_ranks_2019 = compute_daily_ranks(teams_2019 or [], prior_teams=teams_1819)
    daily_ranks_2019_json = json.dumps(daily_ranks_2019)
    daily_ranks_1819 = compute_daily_ranks(teams_1819 or [], prior_teams=teams_1718)
    daily_ranks_1819_json = json.dumps(daily_ranks_1819)
    daily_ranks_1718 = compute_daily_ranks(teams_1718 or [])
    daily_ranks_1718_json = json.dumps(daily_ranks_1718)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WSC North Individual Statistics Leaderboard - 2025-26</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0a0a0a;
    color: #000;
    padding: 20px;
  }}
  h1 {{
    text-align: center;
    font-size: 1.6rem;
    margin-bottom: 4px;
    color: #fff;
  }}
  .subtitle {{
    text-align: center;
    font-size: 0.85rem;
    color: #fff;
    margin-bottom: 16px;
  }}
  .season-toggle {{
    display: none;
    justify-content: center;
    align-items: center;
    gap: 10px;
    margin: -8px 0 12px;
  }}
  .season-btn {{
    background: none;
    border: none;
    color: #4fc3f7;
    font-size: 1rem;
    font-weight: 700;
    cursor: pointer;
    padding: 2px 6px;
    border-radius: 4px;
    opacity: 0.45;
    transition: opacity 0.15s;
  }}
  .season-btn.active {{
    opacity: 1;
    text-decoration: underline;
  }}
  .adv-cat-btn {{
    background: none;
    border: 1px solid #555;
    color: #bbb;
    font-size: 0.77rem;
    font-weight: 600;
    cursor: pointer;
    padding: 2px 8px;
    border-radius: 4px;
    transition: all 0.15s;
    white-space: nowrap;
  }}
  .adv-cat-btn:hover {{
    border-color: #4fc3f7;
    color: #4fc3f7;
  }}
  .adv-cat-btn.active {{
    background: #4fc3f7;
    border-color: #4fc3f7;
    color: #1a1a2e;
  }}
  .adv-section-hdr {{
    background: #1e3a5f !important;
    text-align: center;
    font-weight: 600;
    font-size: 0.82rem;
    padding: 5px 8px;
    color: #eef4ff !important;
    letter-spacing: 0.03em;
    border-top: 2px solid #2a5a8a;
  }}
  .info {{
    text-align: center;
    font-size: 0.78rem;
    color: #fff;
    margin-bottom: 20px;
  }}
  .table-wrap {{
    overflow-x: auto;
    border-radius: 8px;
    border: 1px solid #bbb;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    white-space: nowrap;
  }}
  thead {{
    position: sticky;
    top: 0;
    z-index: 2;
  }}
  th {{
    background: #1a1a2e;
    color: #fff;
    padding: 10px 12px;
    text-align: right;
    cursor: pointer;
    user-select: none;
    border-bottom: 2px solid #333;
    transition: background 0.15s;
  }}
  th:hover {{ background: #252545; }}
  th.active {{ color: #4fc3f7; }}
  th.active.asc::after {{ content: ' ▲'; font-size: 0.7rem; }}
  th.active.desc::after {{ content: ' ▼'; font-size: 0.7rem; }}
  td.active-col {{ box-shadow: inset 0 0 0 100px rgba(79, 195, 247, 0.15); }}
  th:nth-child(1), th:nth-child(2), th:nth-child(3) {{
    text-align: left;
  }}
  td {{
    padding: 8px 12px;
    border-bottom: 1px solid #ccc;
    text-align: right;
    color: #000;
  }}
  td:nth-child(1) {{ text-align: center; color: #000; font-size: 0.8rem; }}
  td:nth-child(2) {{ text-align: left; font-weight: 600; color: #000; }}
  td:nth-child(3) {{ text-align: left; font-weight: 700; }}
  tr:hover td {{ background: #c0c0c0; }}
  tr:nth-child(odd) td {{ background: #d9d9d9; }}
  tr:nth-child(even) td {{ background: #fff; }}
  tr:nth-child(even):hover td {{ background: #c0c0c0; }}

  #team-adv-offense-leaderboard tbody td:nth-child(5),
  #team-adv-offense-leaderboard tbody td:nth-child(9),
  #team-adv-offense-leaderboard tbody td:nth-child(14) {{
    border-left: 2px solid #555;
  }}

  #team-adv-defense-leaderboard tbody td:nth-child(5),
  #team-adv-defense-leaderboard tbody td:nth-child(13) {{
    border-left: 2px solid #555;
  }}

  @media (max-width: 768px) {{
    body {{ padding: 8px; }}
    th, td {{ padding: 6px 8px; font-size: 0.78rem; }}
  }}

  .toggle-wrap {{
    text-align: center;
    margin-bottom: 16px;
  }}
  .toggle-wrap button {{
    padding: 8px 24px;
    font-size: 0.9rem;
    font-weight: 600;
    border: 2px solid #4fc3f7;
    background: transparent;
    color: #4fc3f7;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .toggle-wrap button:first-child {{
    border-radius: 6px 0 0 6px;
  }}
  .toggle-wrap button:last-child {{
    border-radius: 0 6px 6px 0;
  }}
  .toggle-wrap button:not(:first-child):not(:last-child) {{
    border-radius: 0;
  }}
  .toggle-wrap button.active {{
    background: #4fc3f7;
    color: #0a0a0a;
  }}

  .sub-toggle-wrap {{
    display: none;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;
    gap: 8px;
    padding: 4px 0;
    margin-bottom: 8px;
  }}
  #btn-offense, #btn-defense {{
    background: transparent;
    border: 2px solid #ffa726;
    color: #ffa726;
    padding: 4px 16px;
    border-radius: 20px;
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }}
  #btn-offense.active, #btn-defense.active {{
    background: #ffa726;
    color: #1a1a2e;
  }}
  .team-mode-wrap {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-left: 4px;
  }}
  .team-mode-wrap label {{
    font-size: 0.82rem;
    font-weight: 600;
    color: #ddd;
  }}
  .team-mode-wrap select {{
    padding: 4px 8px;
    font-size: 0.82rem;
    font-weight: 600;
    border: 2px solid #ffa726;
    border-radius: 6px;
    background: #161616;
    color: #ffa726;
    outline: none;
  }}
  .top-bar {{
    display: flex;
    align-items: flex-end;
    margin-bottom: 16px;
    flex-wrap: wrap;
    gap: 12px;
    position: relative;
    min-height: 44px;
  }}
  .team-search-wrap {{
    position: absolute;
    right: 0;
    bottom: 0;
  }}
  .team-search-wrap input {{
    background: #e8e8e8;
    border: 1px solid #ccc;
    border-radius: 4px;
    padding: 6px 12px;
    font-size: 0.82rem;
    width: 180px;
    color: #333;
  }}
  .team-search-wrap input::placeholder {{
    color: #999;
  }}
  .team-search-wrap .search-dropdown {{
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: #fff;
    border: 1px solid #ccc;
    border-top: none;
    border-radius: 0 0 4px 4px;
    max-height: 200px;
    overflow-y: auto;
    display: none;
    z-index: 1000;
    box-shadow: 0 4px 8px rgba(0,0,0,0.15);
  }}
  .team-search-wrap .search-dropdown div {{
    padding: 6px 12px;
    font-size: 0.82rem;
    cursor: pointer;
    color: #333;
  }}
  .team-search-wrap .search-dropdown div:hover {{
    background: #e0e0e0;
  }}
  .toggle-center {{
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
    bottom: 0;
  }}
  .conf-toggle-label {{
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 6px;
    justify-content: center;
    cursor: pointer;
  }}
  .conf-toggle-label input[type="checkbox"] {{
    width: 16px;
    height: 16px;
    accent-color: #4fc3f7;
    cursor: pointer;
  }}
  .conf-toggle-text {{
    color: #ccc;
    font-size: 0.82rem;
    font-weight: 500;
    user-select: none;
  }}
  .conf-toggle-label:hover .conf-toggle-text {{
    color: #fff;
  }}
  .filter-bar {{
    display: flex;
    gap: 16px;
    align-items: flex-end;
    flex-wrap: wrap;
  }}
  .filter-group {{
    display: flex;
    flex-direction: column;
    gap: 2px;
  }}
  .filter-bar label {{
    color: #fff;
    font-size: 0.78rem;
    font-weight: 600;
  }}
  .filter-bar select {{
    background: #1a1a2e;
    color: #fff;
    border: 1px solid #4fc3f7;
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 0.82rem;
    cursor: pointer;
  }}
  .filter-bar select:hover {{
    border-color: #81d4fa;
  }}
  .multi-select {{
    position: relative;
    display: inline-block;
  }}
  .multi-select .ms-btn {{
    background: #1a1a2e;
    color: #fff;
    border: 1px solid #4fc3f7;
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 0.82rem;
    cursor: pointer;
    min-width: 120px;
    text-align: left;
    white-space: nowrap;
  }}
  .multi-select .ms-btn:hover {{
    border-color: #81d4fa;
  }}
  .multi-select .ms-btn::after {{
    content: ' ▼';
    float: right;
    margin-left: 8px;
  }}
  .ms-panel {{
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    background: #1a1a2e;
    border: 1px solid #4fc3f7;
    border-radius: 4px;
    z-index: 100;
    min-width: 160px;
    max-height: 220px;
    overflow-y: auto;
    padding: 4px 0;
  }}
  .ms-panel.open {{
    display: block;
  }}
  .ms-panel label {{
    display: flex;
    align-items: center;
    padding: 4px 10px;
    cursor: pointer;
    font-size: 0.82rem;
    color: #fff;
    gap: 6px;
  }}
  .ms-panel label:hover {{
    background: #252545;
  }}
  .ms-panel input[type="checkbox"] {{
    accent-color: #4fc3f7;
  }}
  .ms-panel input[type="radio"] {{
    accent-color: #4fc3f7;
  }}

  /* Universe chart */
  .universe-container {{
    display: flex;
    gap: 0;
    max-width: 1100px;
    margin: 0 auto;
    background: #fff;
    border-radius: 8px;
    padding: 16px 12px 12px 12px;
  }}
  .universe-chart-area {{
    flex: 1;
    position: relative;
    min-width: 0;
  }}
  .universe-axis-labels {{
    display: flex;
    justify-content: center;
    gap: 140px;
    margin-bottom: 4px;
  }}
  .universe-axis-labels span {{
    color: #c0392b;
    font-size: 0.85rem;
  }}
  .universe-sidebar {{
    width: 250px;
    padding-left: 12px;
    display: flex;
    gap: 20px;
    font-size: 0.8rem;
    color: #000;
    flex-shrink: 0;
  }}
  .uni-stat-col {{
    display: flex;
    flex-direction: column;
    gap: 0;
  }}
  .uni-stat-header {{
    display: flex;
    gap: 10px;
    margin-bottom: 3px;
  }}
  .uni-stat-header span {{
    cursor: pointer;
    min-width: 44px;
    font-weight: 700;
    text-decoration: underline;
  }}
  .uni-stat-header span:not(.active) {{
    font-weight: 400;
    text-decoration: none;
  }}
  .uni-stat-row {{
    display: flex;
    gap: 10px;
    cursor: pointer;
    line-height: 1.6;
  }}
  .uni-stat-row span {{
    min-width: 44px;
  }}
  .uni-stat-row.active span {{
    font-weight: 700;
  }}
  .uni-section-label {{
    font-weight: 700;
    margin-top: 6px;
    margin-bottom: 1px;
    font-size: 0.82rem;
  }}
  .uni-conf-col {{
    display: flex;
    flex-direction: column;
    gap: 0;
  }}
  .uni-conf-item {{
    cursor: pointer;
    line-height: 1.6;
    font-size: 0.8rem;
  }}
  .uni-conf-item.active {{
    font-weight: 700;
  }}
  .uni-conf-item:hover {{
    text-decoration: underline;
  }}
  .uni-reset {{
    color: #c0392b;
    cursor: pointer;
    margin-top: 8px;
    font-size: 0.82rem;
  }}
  .uni-reset:hover {{
    text-decoration: underline;
  }}
  #universe-svg {{
    background: #fff;
    border: 1px solid #ccc;
    border-radius: 4px;
    width: 100%;
    height: auto;
  }}
  /* Team detail view */
  #team-detail-view {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 12px;
  }}
  .td-back {{
    color: #4fc3f7;
    font-size: 0.85rem;
    cursor: pointer;
    display: inline-block;
    margin-bottom: 12px;
  }}
  .td-back:hover {{ text-decoration: underline; }}
  .td-header {{
    text-align: center;
    background: #1a1a2e;
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 20px;
  }}
  .td-header h1 {{ font-size: 2rem; margin-bottom: 4px; }}
  .td-header .td-rank {{ color: #4fc3f7; font-size: 1.1rem; font-weight: 700; margin-bottom: 4px; }}
  .td-header .td-meta {{ color: #ccc; font-size: 0.9rem; }}
  .td-header .td-record {{ color: #fff; font-size: 1.2rem; font-weight: 700; margin-top: 6px; }}
  .td-header .td-coach {{ color: #aaa; font-size: 0.88rem; margin-top: 4px; }}
  .td-content {{
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
  }}
  .td-scouting {{
    flex: 0 0 480px;
    background: #fff;
    border-radius: 8px;
    padding: 16px;
    border: 1px solid #ccc;
  }}
  .td-schedule {{
    flex: 1;
    min-width: 400px;
    background: #fff;
    border-radius: 8px;
    padding: 16px;
    border: 1px solid #ccc;
  }}
  .td-section-title {{
    font-size: 1rem;
    font-weight: 700;
    text-align: center;
    margin-bottom: 10px;
    color: #000;
    border-bottom: 2px solid #333;
    padding-bottom: 6px;
  }}
  .td-sub-title {{
    font-size: 0.82rem;
    font-weight: 700;
    text-align: center;
    margin: 10px 0 4px;
    color: #444;
    border-bottom: 1px solid #ddd;
    padding-bottom: 3px;
  }}
  .td-scouting table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  .td-scouting th {{ background: #1a1a2e; color: #fff; padding: 6px 8px; text-align: center; font-size: 0.78rem; border-bottom: 2px solid #333; }}
  .td-scouting td {{ padding: 5px 8px; border-bottom: 1px solid #eee; font-size: 0.82rem; white-space: nowrap; }}
  .td-schedule table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  .td-schedule th {{ background: #1a1a2e; color: #fff; padding: 6px 8px; text-align: center; font-size: 0.78rem; border-bottom: 2px solid #333; }}
  .td-schedule td {{ padding: 5px 8px; border-bottom: 1px solid #eee; font-size: 0.82rem; white-space: nowrap; }}
  .td-schedule tr:hover td {{ background: #f0f0f0; }}
  .td-schedule tr.sched-win td {{ background: rgb(0,255,0) !important; color: #000 !important; }}
  .td-schedule tr.sched-loss td {{ background: rgb(255,0,0) !important; color: #000 !important; }}
  .td-schedule tr.sched-win:hover td {{ background: rgb(0,230,0) !important; }}
  .td-schedule tr.sched-loss:hover td {{ background: rgb(230,0,0) !important; }}
  .td-schedule tr.sched-win a, .td-schedule tr.sched-loss a {{ color: #000 !important; }}
  @media (max-width: 900px) {{
    .td-content {{ flex-direction: column; }}
    .td-scouting {{ flex: 1; }}
  }}
  /* OPP ADJ bar tooltip */
  .opp-bar-wrap {{
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    cursor: pointer;
  }}
  /* PACE ADJ bar tooltip */
  .pace-bar-wrap {{
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    cursor: pointer;
  }}
  #opp-float-tip, #pace-float-tip {{
    display: none;
    position: fixed;
    background: rgba(30,30,50,0.96);
    color: #fff;
    font-size: 0.78rem;
    line-height: 1.4;
    padding: 8px 12px;
    border-radius: 6px;
    width: 240px;
    text-align: center;
    white-space: normal;
    z-index: 9999;
    pointer-events: none;
    box-shadow: 0 4px 12px rgba(0,0,0,0.35);
  }}
  #opp-float-tip::after, #pace-float-tip::after {{
    content: '';
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
  }}
  #opp-float-tip.above::after, #pace-float-tip.above::after {{
    top: 100%;
    border-top-color: rgba(30,30,50,0.96);
  }}
  #opp-float-tip.below::after, #pace-float-tip.below::after {{
    bottom: 100%;
    border-bottom-color: rgba(30,30,50,0.96);
  }}

  /* --- Miscellaneous (Game Attribute Rankings) --- */
  .sl-nav {{
    font-size: 0.85rem;
    margin-bottom: 6px;
    letter-spacing: 0.01em;
    text-align: center;
  }}
  .sl-nav a {{
    color: #4fc3f7;
    text-decoration: none;
    cursor: pointer;
  }}
  .sl-nav a:hover {{ text-decoration: underline; }}
  .sl-nav a.sl-active {{
    color: #fff;
    font-weight: 700;
    text-decoration: underline;
    pointer-events: none;
  }}
  .sl-nav-sep {{ color: #444; margin: 0 6px; user-select: none; }}
  .sl-page-title {{
    font-size: 1.15rem;
    font-weight: 700;
    color: #fff;
    margin: 10px 0 4px;
    text-align: center;
  }}
  .sl-game-count {{
    font-size: 0.8rem;
    color: #ccc;
    text-align: center;
    margin: 0 0 14px;
  }}
  .sl-table-outer {{ text-align: center; }}
  .sl-table-wrap {{ display: inline-block; overflow-x: auto; border-radius: 8px; border: 1px solid #bbb; text-align: left; }}
  .sl-table {{
    width: auto;
    min-width: 560px;
    border-collapse: collapse;
    font-size: 0.82rem;
  }}
  .sl-table th {{
    padding: 7px 10px;
    text-align: left;
    font-weight: 600;
    color: #fff;
    white-space: nowrap;
    background: #1a1a2e;
    cursor: default;
    border-bottom: 2px solid #333;
  }}
  .sl-table th.sl-th-r {{ text-align: right; }}
  .sl-table td {{
    padding: 7px 10px;
    border-bottom: 1px solid #ccc;
    color: #000 !important;
    vertical-align: top;
    font-weight: 400 !important;
  }}
  .sl-table tbody tr:hover td {{ background: #c0c0c0; }}
  .mp-gold-row td {{ background: #ffe599 !important; }}
  .sl-rank {{
    text-align: right;
    padding-right: 14px !important;
    color: #888 !important;
    font-size: 0.78rem;
    width: 32px;
  }}
  .sl-date-cell {{ white-space: nowrap; color: #555 !important; font-size: 0.78rem; min-width: 70px; }}
  .sl-loc-cell {{ white-space: nowrap; font-size: 0.78rem; color: #555 !important; max-width: 150px; overflow: hidden; text-overflow: ellipsis; text-align: left; }}
  .sl-game-cell {{ min-width: 200px; max-width: 380px; white-space: nowrap; }}
  .sl-game-winner {{ font-weight: 700; color: #000 !important; }}
  .sl-game-loser {{ color: #555 !important; }}
  .sl-score {{ font-weight: 700; color: #000 !important; }}
  .sl-score-loser {{ color: #555 !important; }}
  .sl-net {{ font-size: 0.75rem; color: #777 !important; padding-left: 3px; }}
  .sl-ot {{ font-size: 0.75rem; color: #888 !important; padding-left: 4px; }}
  .sl-detail-cell {{
    text-align: right;
    color: #333 !important;
    white-space: nowrap;
    font-size: 0.8rem;
  }}
  .sl-val-cell {{
    text-align: right;
    font-weight: 700 !important;
    color: #1565c0 !important;
    white-space: nowrap;
  }}
  .sl-wp-low {{ color: #c62828 !important; }}
  .sl-cal-nav {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0;
    margin-bottom: 14px;
    font-size: 0.85rem;
  }}
  .sl-cal-btn {{
    background: #1a1a1a;
    border: 1px solid #333;
    color: #aaa;
    padding: 5px 12px;
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
    border-radius: 3px;
  }}
  .sl-cal-btn:hover {{ background: #262626; color: #fff; }}
  .sl-cal-btn:disabled {{ opacity: 0.25; cursor: default; }}
  .sl-cal-center {{
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 180px;
    margin: 0 10px;
  }}
  .sl-cal-date {{
    font-weight: 700;
    color: #fff;
    font-size: 0.95rem;
  }}
  .sl-cal-count {{ font-size: 0.75rem; color: #666; margin-top: 1px; }}
  #sl-date-input {{
    padding: 4px 8px;
    border: 1px solid #333;
    border-radius: 3px;
    background: #1a1a1a;
    color: #888;
    font-size: 0.78rem;
    cursor: pointer;
  }}
  .sl-wab-btn {{
    padding: 4px 12px;
    border: 1px solid #555;
    border-radius: 4px;
    background: #222;
    color: #aaa;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }}
  .sl-wab-btn:hover {{ background: #333; color: #fff; }}
  .sl-wab-btn.active {{ background: #1a1a2e; color: #fff; border-color: #4a6fa5; }}
  .lotn-wrap {{
    background: #141414;
    border: 1px solid #2a3a5a;
    border-radius: 6px;
    padding: 10px 16px;
    margin: 14px 0 0 0;
    font-size: 0.82rem;
    color: #ccc;
    text-align: center;
  }}
  .lotn-label {{
    display: block;
    color: #6a8fd8;
    font-weight: 700;
    margin-bottom: 6px;
    white-space: nowrap;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  .lotn-player {{ color: #f0f0f0; font-weight: 600; }}
  .lotn-pts {{ color: #f9c74f; font-weight: 700; }}
  .sl-wab-pos {{ color: #1565c0 !important; font-weight: 700; }}
  .sl-wab-neg {{ color: #c62828 !important; font-weight: 700; }}
  .sl-wab-bubble-line {{ pointer-events: none; }}
  .sl-wab-bubble-line td {{ background: transparent; border-top: 2px dashed #aaa; border-bottom: none; padding: 2px 8px; text-align: center; font-size: 0.72rem; color: #888; font-style: italic; }}
  .sl-wab-bar-wrap {{
    display: inline-block;
    width: 60px;
    height: 8px;
    background: #e0e0e0;
    border-radius: 4px;
    vertical-align: middle;
    margin-left: 6px;
    overflow: hidden;
    position: relative;
  }}
  .sl-wab-bar {{
    display: inline-block;
    height: 100%;
    border-radius: 4px;
    position: absolute;
    left: 0;
    top: 0;
  }}
  /* --- Quad game tooltip --- */
  #quad-tip {{
    position: fixed;
    display: none;
    background: #1a1a2e;
    border: 1px solid #444;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 0.78rem;
    color: #e0e0e0;
    pointer-events: none;
    z-index: 9999;
    min-width: 260px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.6);
    white-space: nowrap;
  }}
  #quad-tip table {{ border-collapse: collapse; width: 100%; }}
  #quad-tip td {{ padding: 2px 8px 2px 0; }}
  #quad-tip td:first-child {{ color: #888; font-size: 0.72rem; }}
  #quad-tip .qt-w {{ color: #6ee7a0; font-weight: 700; }}
  #quad-tip .qt-l {{ color: #f87171; font-weight: 700; }}
  /* --- Trends tab --- */
  .trends-controls {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px 20px;
    align-items: center;
    justify-content: center;
    padding: 10px 0 16px;
  }}
  .trends-ctl-group {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .trends-ctl-group label {{
    font-size: 12px;
    color: #aaa;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .trends-month-btn {{
    padding: 4px 10px;
    border-radius: 14px;
    border: 1px solid #555;
    background: #222;
    color: #ccc;
    cursor: pointer;
    font-size: 12px;
    transition: all 0.15s;
  }}
  .trends-month-btn:hover {{ background: #333; color: #fff; }}
  .trends-month-btn.active {{
    background: #1a1a2e;
    color: #fff;
    border-color: #4a6fa5;
    font-weight: 600;
  }}
  .trends-team-sel {{
    padding: 4px 8px;
    border-radius: 6px;
    border: 1px solid #555;
    background: #222;
    color: #ccc;
    font-size: 12px;
    max-width: 200px;
  }}
  .trends-team-card {{
    border: 1px solid #333;
    border-radius: 6px;
    padding: 10px 16px;
    margin-bottom: 14px;
    background: #111827;
    display: flex;
    flex-wrap: wrap;
    gap: 10px 20px;
    align-items: center;
  }}
  .trends-card-name {{
    font-size: 15px;
    font-weight: 700;
    color: #fff;
  }}
  .trends-card-season {{
    font-size: 12px;
    padding-left: 14px;
    border-left: 1px solid #333;
  }}
  .trends-table-outer {{
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }}
  .trends-tbl {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    white-space: nowrap;
  }}
  .trends-tbl thead th {{
    padding: 7px 10px;
    text-align: center;
    color: #888;
    font-weight: 600;
    font-size: 11px;
    border-bottom: 2px solid #333;
    cursor: default;
    white-space: nowrap;
  }}
  .trends-tbl thead th:first-child {{ text-align: left; }}
  .trends-tbl tbody td {{
    padding: 7px 10px;
    text-align: center;
    border-bottom: 1px solid #1e1e1e;
  }}
  .trends-tbl tbody td:first-child {{
    text-align: left;
    font-weight: 700;
    font-size: 13px;
  }}
  .trends-tbl tbody tr:hover td {{ background: rgba(255,255,255,0.05) !important; color: #e0e0e0 !important; }}
  .trends-tbl tbody tr:hover td.trends-td-good1 {{ color: #6ee7a0 !important; }}
  .trends-tbl tbody tr:hover td.trends-td-good2 {{ color: #22c55e !important; }}
  .trends-tbl tbody tr:hover td.trends-td-good3 {{ color: #4ade80 !important; }}
  .trends-tbl tbody tr:hover td.trends-td-bad1  {{ color: #fca5a5 !important; }}
  .trends-tbl tbody tr:hover td.trends-td-bad2  {{ color: #f87171 !important; }}
  .trends-tbl tbody tr:hover td.trends-td-bad3  {{ color: #ff4444 !important; }}
  .trends-tbl tbody tr:hover td.trends-td-na    {{ color: #444 !important; }}
  .trends-td-na {{ color: #444; }}
  .trends-td-good1 {{ color: #6ee7a0; }}
  .trends-td-good2 {{ color: #22c55e; font-weight: 600; }}
  .trends-td-good3 {{ color: #4ade80; font-weight: 700; }}
  .trends-td-bad1  {{ color: #fca5a5; }}
  .trends-td-bad2  {{ color: #f87171; font-weight: 600; }}
  .trends-td-bad3  {{ color: #ff4444; font-weight: 700; }}
  #trends-tooltip {{
    position: fixed;
    background: rgba(20,20,30,0.95);
    color: #fff;
    font-size: 12px;
    padding: 5px 10px;
    border-radius: 6px;
    pointer-events: none;
    display: none;
    z-index: 9999;
    border: 1px solid #555;
    white-space: nowrap;
  }}
</style>
</head>
<body>
<div id="opp-float-tip"></div>
<div id="pace-float-tip"></div>

<div class="top-bar">
  <div class="filter-bar">
    <div class="filter-group">
      <label>Region:</label>
      <div class="multi-select" id="ms-region">
        <button class="ms-btn" onclick="togglePanel('ms-region')">All</button>
        <div class="ms-panel" id="ms-region-panel">
          <label><input type="radio" name="region" value="All" checked onchange="onRegionChange()"> All</label>
          <label><input type="radio" name="region" value="South" onchange="onRegionChange()"> South</label>
          <label><input type="radio" name="region" value="North" onchange="onRegionChange()"> North</label>
        </div>
      </div>
    </div>
    <div class="filter-group">
      <label>Conference:</label>
      <div class="multi-select" id="ms-conf">
        <button class="ms-btn" onclick="togglePanel('ms-conf')">All</button>
        <div class="ms-panel" id="ms-conf-panel"></div>
      </div>
    </div>
    <div class="filter-group">
      <label>Team:</label>
      <div class="multi-select" id="ms-team">
        <button class="ms-btn" onclick="togglePanel('ms-team')">All</button>
        <div class="ms-panel" id="ms-team-panel"></div>
      </div>
    </div>
  </div>
  <div class="toggle-center">
    <div class="toggle-wrap" style="margin-bottom:0">
      <button id="btn-team" class="active" onclick="showView('team')">Team Stats</button>
      <button id="btn-individual" onclick="showView('individual')">Individual Stats</button>
      <button id="btn-fanmatch" onclick="showView('fanmatch')">FanMatch</button>
      <button id="btn-universe" onclick="showView('universe')">Universe</button>
      <button id="btn-storylines" onclick="showView('storylines')">Miscellaneous</button>
    </div>
    <label class="conf-toggle-label" id="conf-toggle-wrap">
      <input type="checkbox" id="conf-toggle" onchange="toggleConfMode(this.checked)">
      <span class="conf-toggle-text">Conference Only</span>
    </label>
  </div>
  <div class="team-search-wrap">
    <input type="text" id="team-search-input" placeholder="Search Teams" oninput="onTeamSearch()" onfocus="onTeamSearch()">
    <div class="search-dropdown" id="team-search-dropdown"></div>
  </div>
</div>
<div class="sub-toggle-wrap" id="sub-toggle">
  <button id="btn-offense" class="active" onclick="showTeamSub('offense')">Offense</button>
  <button id="btn-defense" onclick="showTeamSub('defense')">Defense</button>
  <div class="team-mode-wrap" id="team-mode-wrap">
    <label for="team-mode-select">Mode:</label>
    <select id="team-mode-select" onchange="onTeamModeChange(this.value)">
      <option value="advanced" selected>Advanced</option>
      <option value="basic">Basic</option>
      <option value="adv_offense">Adv. Offense</option>
      <option value="adv_defense">Adv. Defense</option>
    </select>
  </div>
  <div class="team-mode-wrap" id="ind-mode-wrap" style="display:none">
    <label for="ind-mode-select">Mode:</label>
    <select id="ind-mode-select" onchange="onIndModeChange(this.value)">
      <option value="basic" selected>Basic</option>
      <option value="advanced">Advanced</option>
    </select>
  </div>
</div>

<h1 id="page-title">Individual Statistics Leaderboard</h1>
<div class="subtitle" id="page-subtitle">2025-26 Season — Per-Game Averages</div>
<div class="season-toggle" id="season-toggle">
  <button class="season-btn" id="btn-season-18" onclick="switchSeason('1718')">18</button>
  <span style="color:#aaa;font-size:0.9rem">|</span>
  <button class="season-btn" id="btn-season-19" onclick="switchSeason('1819')">19</button>
  <span style="color:#aaa;font-size:0.9rem">|</span>
  <button class="season-btn" id="btn-season-20" onclick="switchSeason('1920')">20</button>
  <span style="color:#aaa;font-size:0.9rem">|</span>
  <button class="season-btn" id="btn-season-22" onclick="switchSeason('2122')">22</button>
  <span style="color:#aaa;font-size:0.9rem">|</span>
  <button class="season-btn" id="btn-season-23" onclick="switchSeason('2223')">23</button>
  <span style="color:#aaa;font-size:0.9rem">|</span>
  <button class="season-btn" id="btn-season-24" onclick="switchSeason('2324')">24</button>
  <span style="color:#aaa;font-size:0.9rem">|</span>
  <button class="season-btn" id="btn-season-25" onclick="switchSeason('2425')">25</button>
  <span style="color:#aaa;font-size:0.9rem">|</span>
  <button class="season-btn active" id="btn-season-26" onclick="switchSeason('2526')">26</button>
</div>
<div class="info" id="page-info">{len(players)} qualified players · 40% minutes played minimum · Click any column header to sort · Generated {timestamp}</div>

<div id="individual-view">
<div id="ind-adv-tabs" style="display:none;margin-bottom:14px">
  <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:5px">
  <button class="adv-cat-btn active" data-cat="ind_ortg" onclick="switchIndCat('ind_ortg')">ORtg</button>
  <button class="adv-cat-btn" data-cat="ind_drtg" onclick="switchIndCat('ind_drtg')">DRtg</button>
  <button class="adv-cat-btn" data-cat="efg_pct" onclick="switchIndCat('efg_pct')">eFG%</button>
  <button class="adv-cat-btn" data-cat="ts_pct" onclick="switchIndCat('ts_pct')">TS%</button>
  <button class="adv-cat-btn" data-cat="min_pct" onclick="switchIndCat('min_pct')">%Min</button>
  <button class="adv-cat-btn" data-cat="usage_pct" onclick="switchIndCat('usage_pct')">%Poss</button>
  <button class="adv-cat-btn" data-cat="shot_pct" onclick="switchIndCat('shot_pct')">%Shots</button>
  <button class="adv-cat-btn" data-cat="oreb_pct" onclick="switchIndCat('oreb_pct')">OREB%</button>
  <button class="adv-cat-btn" data-cat="dreb_pct" onclick="switchIndCat('dreb_pct')">DREB%</button>
  <button class="adv-cat-btn" data-cat="tov_pct" onclick="switchIndCat('tov_pct')">TO%</button>
  <button class="adv-cat-btn" data-cat="ast_rate" onclick="switchIndCat('ast_rate')">ARate</button>
  <button class="adv-cat-btn" data-cat="blk_pct" onclick="switchIndCat('blk_pct')">Blk%</button>
  <button class="adv-cat-btn" data-cat="stl_pct" onclick="switchIndCat('stl_pct')">Stl%</button>
  <button class="adv-cat-btn" data-cat="ft_rate" onclick="switchIndCat('ft_rate')">FTRate</button>
  <button class="adv-cat-btn" data-cat="fc_per_40" onclick="switchIndCat('fc_per_40')">FC/40</button>
  <button class="adv-cat-btn" data-cat="fd_per_40" onclick="switchIndCat('fd_per_40')">FD/40</button>
  <button class="adv-cat-btn" data-cat="twop" onclick="switchIndCat('twop')">2P%</button>
  <button class="adv-cat-btn" data-cat="tpp" onclick="switchIndCat('tpp')">3P%</button>
  <button class="adv-cat-btn" data-cat="ftp" onclick="switchIndCat('ftp')">FT%</button>
  </div>
</div>
<div id="basic-view">
<div class="table-wrap">
<table id="leaderboard">
<thead>
<tr>
  <th data-col="rank" data-type="num">#</th>
  <th data-col="name" data-type="str">Name</th>
  <th data-col="school" data-type="str">School</th>
  <th data-col="gp" data-type="num">GP</th>
  <th data-col="mpg" data-type="num">MPG</th>
  <th data-col="ppg" data-type="num" class="active desc">PPG</th>
  <th data-col="orpg" data-type="num">OREB</th>
  <th data-col="drpg" data-type="num">DREB</th>
  <th data-col="rpg" data-type="num">RPG</th>
  <th data-col="apg" data-type="num">APG</th>
  <th data-col="spg" data-type="num">SPG</th>
  <th data-col="bpg" data-type="num">BPG</th>
  <th data-col="topg" data-type="num">TO</th>
  <th data-col="fgm" data-type="num">FGM-A</th>
  <th data-col="fgp" data-type="num">FG%</th>
  <th data-col="twom" data-type="num">2PM-A</th>
  <th data-col="twop" data-type="num">2P%</th>
  <th data-col="tpm" data-type="num">3PM-A</th>
  <th data-col="tpp" data-type="num">3P%</th>
  <th data-col="ftm" data-type="num">FTM-A</th>
  <th data-col="ftp" data-type="num">FT%</th>
</tr>
</thead>
<tbody id="tbody"></tbody>
</table>
</div>
</div>
<div id="adv-view" style="display:none">
<div style="display:flex;justify-content:center">
<div class="table-wrap" style="width:auto;min-width:0;border:1px solid #bbb">
<table id="adv-leaderboard" style="width:auto">
<thead><tr>
  <th style="width:36px">#</th>
  <th>Player</th>
  <th>School</th>
  <th style="width:34px">GP</th>
  <th id="adv-stat-th" style="min-width:90px">Stat</th>
</tr></thead>
<tbody id="adv-tbody"></tbody>
</table>
</div>
</div>
</div>
</div>

<div id="team-view" style="display:none;">
<div class="table-wrap">
<table id="team-leaderboard">
<thead>
<tr>
  <th data-col="rank" data-type="num" data-table="team">#</th>
  <th data-col="team" data-type="str" data-table="team">Team</th>
  <th data-col="gp" data-type="num" data-table="team">GP</th>
  <th data-col="record" data-type="rec" data-table="team">Record</th>
  <th data-col="conf" data-type="rec" data-table="team">Conf</th>
  <th data-col="tempo" data-type="num" data-table="team">TEMPO</th>
  <th data-col="ortg" data-type="num" data-table="team">ORTG</th>
  <th data-col="drtg" data-type="num" data-table="team">DRTG</th>
  <th data-col="net_rtg" data-type="num" data-table="team" class="active desc">NET RTG</th>
  <th data-col="opp_adjust" data-type="num" data-table="team" title="Opponent Adjust: Red bar = plays UP to competition (better vs strong teams, worse vs weak). Blue bar = crushes weak opponents but disappoints vs strong. Near zero = consistent regardless of opponent.">OPP ADJ</th>
  <th data-col="pace_adjust" data-type="num" data-table="team" title="Pace Adjust: Measures how well each team performs above or below expectation in games played at a higher or lower pace than usual. Orange bar = better in up-tempo games. Blue bar = better in slow-paced games. Near zero = consistent regardless of pace.">PACE ADJ</th>
  <th data-col="opp_ortg" data-type="num" data-table="team">Opp ORTG</th>
  <th data-col="opp_drtg_sos" data-type="num" data-table="team">Opp DRTG</th>
  <th data-col="sos" data-type="num" data-table="team">SOS</th>
  <th data-col="ncsos" data-type="num" data-table="team">NCSOS</th>
  <th data-col="luck" data-type="num" data-table="team" title="Luck: Actual W% minus Pythagorean expected W% — positive means won more games than expected, negative means fewer">Luck</th>
  <th data-col="efg_pct" data-type="num" data-table="team">eFG%</th>
  <th data-col="oreb_pct" data-type="num" data-table="team">OREB%</th>
  <th data-col="tov_pct" data-type="num" data-table="team">TOV%</th>
  <th data-col="ft_rate" data-type="num" data-table="team">FTR</th>
</tr>
</thead>
<tbody id="team-tbody"></tbody>
</table>
</div>
</div>

<div id="team-defense-view" style="display:none;">
<div class="table-wrap">
<table id="team-defense-leaderboard">
<thead>
<tr>
  <th data-col="rank" data-type="num" data-table="def">#</th>
  <th data-col="team" data-type="str" data-table="def">Team</th>
  <th data-col="gp" data-type="num" data-table="def">GP</th>
  <th data-col="record" data-type="rec" data-table="def">Record</th>
  <th data-col="conf" data-type="rec" data-table="def">Conf</th>
  <th data-col="tempo" data-type="num" data-table="def">TEMPO</th>
  <th data-col="ortg" data-type="num" data-table="def">ORTG</th>
  <th data-col="drtg" data-type="num" data-table="def">DRTG</th>
  <th data-col="net_rtg" data-type="num" data-table="def" class="active desc">NET RTG</th>
  <th data-col="opp_adjust" data-type="num" data-table="def" title="Opponent Adjust: Red bar = plays UP to competition. Blue bar = crushes weak opponents but disappoints vs strong. Near zero = consistent.">OPP ADJ</th>
  <th data-col="pace_adjust" data-type="num" data-table="def" title="Pace Adjust: Orange bar = better in up-tempo games. Blue bar = better in slow-paced games. Near zero = consistent regardless of pace.">PACE ADJ</th>
  <th data-col="opp_ortg" data-type="num" data-table="def">Opp ORTG</th>
  <th data-col="opp_drtg_sos" data-type="num" data-table="def">Opp DRTG</th>
  <th data-col="sos" data-type="num" data-table="def">SOS</th>
  <th data-col="ncsos" data-type="num" data-table="def">NCSOS</th>
  <th data-col="opp_efg_pct" data-type="num" data-table="def">Opp eFG%</th>
  <th data-col="dreb_pct" data-type="num" data-table="def">DREB%</th>
  <th data-col="opp_tov_pct" data-type="num" data-table="def">Opp TOV%</th>
  <th data-col="opp_ft_rate" data-type="num" data-table="def">Opp FTR</th>
</tr>
</thead>
<tbody id="team-defense-tbody"></tbody>
</table>
</div>
</div>

<div id="team-basic-view" style="display:none;">
<div class="table-wrap">
<table id="team-basic-leaderboard">
<thead>
<tr>
  <th data-col="rank" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('rank','num')">#</th>
  <th data-col="team" data-type="str" data-table="basic" style="cursor:pointer" onclick="doBasicSort('team','str')">Team</th>
  <th data-col="gp" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('gp','num')">GP</th>
  <th data-col="record" data-type="rec" data-table="basic" style="cursor:pointer" onclick="doBasicSort('record','rec')">Record</th>
  <th data-col="conf" data-type="rec" data-table="basic" style="cursor:pointer" onclick="doBasicSort('conf','rec')">Conf</th>
  <th data-col="ppg" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('ppg','num')">PPG</th>
  <th data-col="opp_ppg" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('opp_ppg','num')">Opp PPG</th>
  <th data-col="fgp" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('fgp','num')">FG%</th>
  <th data-col="twop" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('twop','num')">2P%</th>
  <th data-col="tpp" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('tpp','num')">3P%</th>
  <th data-col="ftp" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('ftp','num')">FT%</th>
  <th data-col="orebpg" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('orebpg','num')">OREB</th>
  <th data-col="drebpg" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('drebpg','num')">DREB</th>
  <th data-col="rpg" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('rpg','num')">RPG</th>
  <th data-col="apg" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('apg','num')">APG</th>
  <th data-col="spg" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('spg','num')">SPG</th>
  <th data-col="bpg" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('bpg','num')">BPG</th>
  <th data-col="topg" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('topg','num')">TO</th>
  <th data-col="pfpg" data-type="num" data-table="basic" style="cursor:pointer" onclick="doBasicSort('pfpg','num')">PF</th>
</tr>
</thead>
<tbody id="team-basic-tbody"></tbody>
</table>
</div>
</div>

<div id="team-basic-defense-view" style="display:none;">
<div class="table-wrap">
<table id="team-basic-defense-leaderboard">
<thead>
<tr>
  <th data-col="rank" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('rank','num')">#</th>
  <th data-col="team" data-type="str" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('team','str')">Team</th>
  <th data-col="gp" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('gp','num')">GP</th>
  <th data-col="record" data-type="rec" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('record','rec')">Record</th>
  <th data-col="conf" data-type="rec" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('conf','rec')">Conf</th>
  <th data-col="opp_ppg" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_ppg','num')">Opp PPG</th>
  <th data-col="opp_fgp" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_fgp','num')">Opp FG%</th>
  <th data-col="opp_twop" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_twop','num')">Opp 2P%</th>
  <th data-col="opp_tpp" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_tpp','num')">Opp 3P%</th>
  <th data-col="opp_ftp" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_ftp','num')">Opp FT%</th>
  <th data-col="opp_orebpg" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_orebpg','num')">Opp OREB</th>
  <th data-col="opp_drebpg" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_drebpg','num')">Opp DREB</th>
  <th data-col="opp_rpg" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_rpg','num')">Opp RPG</th>
  <th data-col="opp_apg" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_apg','num')">Opp APG</th>
  <th data-col="opp_spg" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_spg','num')">Opp SPG</th>
  <th data-col="opp_bpg" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_bpg','num')">Opp BPG</th>
  <th data-col="opp_topg" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_topg','num')">Opp TO</th>
  <th data-col="opp_pfpg" data-type="num" data-table="bdef" style="cursor:pointer" onclick="doBasicDefSort('opp_pfpg','num')">Opp PF</th>
</tr>
</thead>
<tbody id="team-basic-defense-tbody"></tbody>
</table>
</div>
</div>

<div id="team-adv-offense-view" style="display:none;">
<div class="table-wrap">
<table id="team-adv-offense-leaderboard">
<thead>
<tr>
  <th rowspan="2" data-col="rank" data-type="num" data-table="advo" style="cursor:pointer;vertical-align:bottom" onclick="doAdvOffSort('rank','num')">#</th>
  <th rowspan="2" data-col="team" data-type="str" data-table="advo" style="cursor:pointer;vertical-align:bottom;text-align:left" onclick="doAdvOffSort('team','str')">Team</th>
  <th rowspan="2" data-col="gp" data-type="num" data-table="advo" style="cursor:pointer;vertical-align:bottom" onclick="doAdvOffSort('gp','num')">GP</th>
  <th rowspan="2" data-col="ortg" data-type="num" data-table="advo" style="cursor:pointer;vertical-align:bottom" onclick="doAdvOffSort('ortg','num')">ORTg</th>
  <th colspan="4" style="text-align:center;border-bottom:1px solid #555;border-left:2px solid #555;font-size:0.75rem;color:#aaa;font-weight:600">Shooting</th>
  <th colspan="5" style="text-align:center;border-bottom:1px solid #555;border-left:2px solid #555;font-size:0.75rem;color:#aaa;font-weight:600">Ball Handling</th>
  <th colspan="4" style="text-align:center;border-bottom:1px solid #555;border-left:2px solid #555;font-size:0.75rem;color:#aaa;font-weight:600">Play Style</th>
</tr>
<tr>
  <th data-col="ts_pct" data-type="num" data-table="advo" style="cursor:pointer;border-left:2px solid #555" onclick="doAdvOffSort('ts_pct','num')">TS%</th>
  <th data-col="twop" data-type="num" data-table="advo" style="cursor:pointer" onclick="doAdvOffSort('twop','num')">2P%</th>
  <th data-col="tpp" data-type="num" data-table="advo" style="cursor:pointer" onclick="doAdvOffSort('tpp','num')">3P%</th>
  <th data-col="ftp" data-type="num" data-table="advo" style="cursor:pointer" onclick="doAdvOffSort('ftp','num')">FT%</th>
  <th data-col="ast_pct" data-type="num" data-table="advo" style="cursor:pointer;border-left:2px solid #555" onclick="doAdvOffSort('ast_pct','num')">AST%</th>
  <th data-col="ast_ratio" data-type="num" data-table="advo" style="cursor:pointer" onclick="doAdvOffSort('ast_ratio','num')">AST Ratio</th>
  <th data-col="tov_pct" data-type="num" data-table="advo" style="cursor:pointer" onclick="doAdvOffSort('tov_pct','num')">TOV%</th>
  <th data-col="ast_tov" data-type="num" data-table="advo" style="cursor:pointer" onclick="doAdvOffSort('ast_tov','num')">AST/TOV</th>
  <th data-col="nst_pct" data-type="num" data-table="advo" style="cursor:pointer" onclick="doAdvOffSort('nst_pct','num')" title="Non-Steal Turnover %: (TO − Opp STL) / Possessions">NST%</th>
  <th data-col="oreb_pct" data-type="num" data-table="advo" style="cursor:pointer;border-left:2px solid #555" onclick="doAdvOffSort('oreb_pct','num')">ORB%</th>
  <th data-col="ft_rate" data-type="num" data-table="advo" style="cursor:pointer" onclick="doAdvOffSort('ft_rate','num')">FTA Rate</th>
  <th data-col="tpa_pct" data-type="num" data-table="advo" style="cursor:pointer" onclick="doAdvOffSort('tpa_pct','num')">3PAr</th>
  <th data-col="tempo" data-type="num" data-table="advo" style="cursor:pointer" onclick="doAdvOffSort('tempo','num')">Pace</th>
</tr>
</thead>
<tbody id="team-adv-offense-tbody"></tbody>
</table>
</div>
</div>

<div id="team-adv-defense-view" style="display:none;">
<div class="table-wrap">
<table id="team-adv-defense-leaderboard">
<thead>
<tr>
  <th rowspan="2" data-col="rank" data-type="num" data-table="advd" style="cursor:pointer;vertical-align:bottom" onclick="doAdvDefSort('rank','num')">#</th>
  <th rowspan="2" data-col="team" data-type="str" data-table="advd" style="cursor:pointer;vertical-align:bottom;text-align:left" onclick="doAdvDefSort('team','str')">Team</th>
  <th rowspan="2" data-col="gp" data-type="num" data-table="advd" style="cursor:pointer;vertical-align:bottom" onclick="doAdvDefSort('gp','num')">GP</th>
  <th rowspan="2" data-col="drtg" data-type="num" data-table="advd" style="cursor:pointer;vertical-align:bottom" onclick="doAdvDefSort('drtg','num')">DRTg</th>
  <th colspan="8" style="text-align:center;border-bottom:1px solid #555;border-left:2px solid #555;font-size:0.75rem;color:#aaa;font-weight:600">Defense Overall</th>
  <th colspan="5" style="text-align:center;border-bottom:1px solid #555;border-left:2px solid #555;font-size:0.75rem;color:#aaa;font-weight:600">Foul Tendencies</th>
</tr>
<tr>
  <th data-col="drebpg" data-type="num" data-table="advd" style="cursor:pointer;border-left:2px solid #555" onclick="doAdvDefSort('drebpg','num')">DRB</th>
  <th data-col="dreb_pct" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('dreb_pct','num')">DRB%</th>
  <th data-col="spg" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('spg','num')">STL</th>
  <th data-col="stl_pct" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('stl_pct','num')">STL%</th>
  <th data-col="stl_to" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('stl_to','num')">STL/TOV</th>
  <th data-col="bpg" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('bpg','num')">BLK</th>
  <th data-col="blk_pct" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('blk_pct','num')">BLK%</th>
  <th data-col="hkm_pct" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('hkm_pct','num')">HKM%</th>
  <th data-col="pf_total" data-type="num" data-table="advd" style="cursor:pointer;border-left:2px solid #555" onclick="doAdvDefSort('pf_total','num')">PF</th>
  <th data-col="pfpg" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('pfpg','num')">PF/G</th>
  <th data-col="pf_eff" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('pf_eff','num')">PF Eff</th>
  <th data-col="stl_pf" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('stl_pf','num')">STL/PF</th>
  <th data-col="blk_pf" data-type="num" data-table="advd" style="cursor:pointer" onclick="doAdvDefSort('blk_pf','num')">BLK/PF</th>
</tr>
</thead>
<tbody id="team-adv-defense-tbody"></tbody>
</table>
</div>
</div>

<div id="universe-view" style="display:none;">
  <div class="universe-container">
    <div class="universe-chart-area">
      <div class="universe-axis-labels">
        <span>Defense-dependent</span>
        <span>Offense-dependent</span>
      </div>
      <svg id="universe-svg" viewBox="0 0 750 700" preserveAspectRatio="xMidYMid meet"></svg>
    </div>
    <div class="universe-sidebar">
      <div class="uni-stat-col" id="uni-stat-col"></div>
      <div class="uni-conf-col" id="uni-conf-col"></div>
    </div>
  </div>
</div>

<div id="team-detail-view" style="display:none;">
  <div id="team-detail-content"></div>
</div>

<div id="gameplan-view" style="display:none;">
  <span class="td-back" onclick="closeGamePlan()">← Back to Team</span>
  <div id="gameplan-content" style="margin-top:12px"></div>
</div>

<div id="storylines-view" style="display:none;">
  <div style="padding:16px 0 24px">
    <div class="sl-nav" id="sl-nav"></div>
    <div class="sl-page-title" id="sl-page-title">2025-26 game attribute rankings</div>
    <div class="sl-game-count" id="sl-game-count" style="display:none"></div>
    <div id="sl-tab-dominance" class="sl-tab-content">
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table"><thead><tr>
        <th class="sl-th-r">#</th><th>Date</th><th>Game</th><th>Location</th><th class="sl-th-r">Margin</th><th class="sl-th-r">Value</th>
      </tr></thead><tbody id="sl-body-dominance"></tbody></table></div></div>
    </div>
    <div id="sl-tab-upsets" class="sl-tab-content" style="display:none">
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table"><thead><tr>
        <th class="sl-th-r">#</th><th>Date</th><th>Game</th><th>Location</th><th class="sl-th-r">Win Prob</th><th class="sl-th-r">Value</th>
      </tr></thead><tbody id="sl-body-upsets"></tbody></table></div></div>
    </div>
    <div id="sl-tab-tension" class="sl-tab-content" style="display:none">
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table"><thead><tr>
        <th class="sl-th-r">#</th><th>Date</th><th>Game</th><th>Location</th><th class="sl-th-r">Margin / OT</th><th class="sl-th-r">Value</th>
      </tr></thead><tbody id="sl-body-tension"></tbody></table></div></div>
    </div>
    <div id="sl-tab-busts" class="sl-tab-content" style="display:none">
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table"><thead><tr>
        <th class="sl-th-r">#</th><th>Date</th><th>Game</th><th>Location</th><th class="sl-th-r">Exp. Margin</th><th class="sl-th-r">Value</th>
      </tr></thead><tbody id="sl-body-busts"></tbody></table></div></div>
    </div>

    <div id="sl-tab-wab" class="sl-tab-content" style="display:none">
      <div class="sl-wab-filter" style="display:flex;align-items:center;justify-content:center;gap:8px;padding:10px 0 14px">
        <span style="font-size:13px;color:#555;font-weight:600">Region:</span>
        <button class="sl-wab-btn active" onclick="slWabFilter('North')">North</button>
        <button class="sl-wab-btn" onclick="slWabFilter('South')">South</button>
      </div>
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table"><thead><tr>
        <th class="sl-th-r">#</th><th>Team</th><th>Conference</th><th class="sl-th-r">NET</th><th class="sl-th-r">Games</th><th>WAB</th>
      </tr></thead><tbody id="sl-body-wab"></tbody></table></div></div>
    </div>
    <div id="sl-tab-rate" class="sl-tab-content" style="display:none">
      <div class="sl-wab-filter" style="display:flex;align-items:center;justify-content:center;gap:8px;padding:10px 0 14px">
        <span style="font-size:13px;color:#555;font-weight:600">Season:</span>
        <button class="sl-wab-btn" id="sl-rate-btn-18" onclick="slRateSeasonFilter('1718')">2017-18</button>
        <button class="sl-wab-btn" id="sl-rate-btn-19" onclick="slRateSeasonFilter('1819')">2018-19</button>
        <button class="sl-wab-btn" id="sl-rate-btn-20" onclick="slRateSeasonFilter('1920')">2019-20</button>
        <button class="sl-wab-btn" id="sl-rate-btn-22" onclick="slRateSeasonFilter('2122')">2021-22</button>
        <button class="sl-wab-btn" id="sl-rate-btn-23" onclick="slRateSeasonFilter('2223')">2022-23</button>
        <button class="sl-wab-btn" id="sl-rate-btn-24" onclick="slRateSeasonFilter('2324')">2023-24</button>
        <button class="sl-wab-btn" id="sl-rate-btn-25" onclick="slRateSeasonFilter('2425')">2024-25</button>
        <button class="sl-wab-btn active" id="sl-rate-btn-26" onclick="slRateSeasonFilter('2526')">2025-26</button>
      </div>
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table" id="rate-table"><thead><tr>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortRate('rank_rel')">Rk</th>
        <th style="cursor:pointer" onclick="slSortRate('team')">Team</th>
        <th style="cursor:pointer" onclick="slSortRate('conference')">Conference</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortRate('o_rate')" title="Offensive Efficiency Rating vs peer-ranked teams. Higher = better offense.">O-Rate</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortRate('d_rate')" title="Defensive Efficiency Rating vs peer-ranked teams. Higher = better defense.">D-Rate</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortRate('rel_rating')" title="Net Relative Rating: overall strength calibrated vs similarly-ranked opponents. Higher = better.">Rel-Rtg</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortRate('opp_adjust')" title="Opponent Adjust: Red bar (right) = plays UP to competition. Blue bar (left) = beats weak teams but struggles vs strong. Near zero = consistent.">OPP ADJ</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortRate('pace_adjust')" title="Pace Adjust: Orange bar (right) = better in up-tempo games. Blue bar (left) = better in slower games. Near zero = consistent regardless of pace.">PCE ADJ</th>
      </tr></thead><tbody id="sl-body-rate"></tbody></table></div></div>
    </div>
    <div id="sl-tab-tiers" class="sl-tab-content" style="display:none">
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table" id="tiers-table"><thead><tr>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortTiers('rank')">Rk</th>
        <th style="cursor:pointer" onclick="slSortTiers('team')">School</th>
        <th style="cursor:pointer" onclick="slSortTiers('conference')">Conference</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortTiers('record')" title="Overall record">Record</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortTiers('tier_a_rec')" title="Record vs location-adjusted top-15 opponents (Tier A)">vs Tier A</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortTiers('tier_b_rec')" title="Record vs location-adjusted top-16 to top-30 opponents (Tier B)">vs Tier B</th>
        <th class="sl-th-r" style="cursor:pointer;background:#555" onclick="slSortTiers('combined_pct')" title="Combined win% vs all Tier A and Tier B opponents (default sort)">A+B W%</th>
      </tr></thead><tbody id="sl-body-tiers"></tbody></table></div></div>
    </div>
    <div id="sl-tab-quads" class="sl-tab-content" style="display:none">
      <div id="quad-tip"></div>
      <div style="padding:6px 10px 4px;color:#aaa;font-size:0.75rem">Quadrant thresholds scaled from NCAA (353 teams) to ~100 CCC teams. Q1A = elite (top ~4% H / 7% N / 11% A). Q1 = top-tier (top ~9% H / 14% N / 21% A). Q2 = strong. Q3 = adequate. Q4 = lower-tier. Sorted by Q1A wins by default.</div>
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table" id="quads-table"><thead><tr>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortQuads('rank')">Rk</th>
        <th style="cursor:pointer" onclick="slSortQuads('team')">School</th>
        <th style="cursor:pointer" onclick="slSortQuads('conference')">Conference</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortQuads('record')" title="Overall record">Record</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortQuads('sos')" title="Strength of Schedule (RPI-based, higher = tougher schedule)">SOS</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortQuads('q1a')" title="Q1A — Elite opponents: Home top 4%, Neutral top 7%, Away top 11% (scaled from NCAA Q1A 15/25/40 of 353)">Q1A</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortQuads('q1')" title="Q1 — All Q1-or-better opponents (includes Q1A): Home top 9%, Neutral top 14%, Away top 21%">Q1</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortQuads('q2')" title="Q2 — Strong opponents: Home top 21%, Neutral top 28%, Away top 38% (scaled from NCAA Q2 75/100/135 of 353)">Q2</th>
        <th class="sl-th-r" style="cursor:pointer;background:#2a3a5c" onclick="slSortQuads('q12')" title="Q1+Q2 combined record — all Q1A+Q1+Q2 opponents combined">Q1+Q2</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortQuads('q3')" title="Q3 — Adequate opponents: Home top 45%, Neutral top 57%, Away top 68% (scaled from NCAA Q3 160/200/240 of 353)">Q3</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortQuads('q4')" title="Q4 — Lower-tier opponents: remaining teams">Q4</th>
      </tr></thead><tbody id="sl-body-quads"></tbody></table></div></div>
    </div>
    <div id="sl-tab-trank" class="sl-tab-content" style="display:none">
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table" id="trank-table"><thead>
        <tr id="trank-avg-row" style="background:#1a1a2e;color:#aaa;font-size:0.72rem;font-style:italic">
          <td colspan="4" style="text-align:right;padding:2px 6px;color:#666">Lg Avg &rarr;</td>
          <td class="sl-th-r" id="trank-avg-adjoe" style="padding:2px 6px"></td>
          <td class="sl-th-r" id="trank-avg-adjde" style="padding:2px 6px"></td>
          <td class="sl-th-r" id="trank-avg-barthag" style="padding:2px 6px"></td>
          <td class="sl-th-r" id="trank-avg-efg" style="padding:2px 6px"></td>
          <td class="sl-th-r" id="trank-avg-tov" style="padding:2px 6px"></td>
          <td class="sl-th-r" id="trank-avg-or" style="padding:2px 6px"></td>
          <td class="sl-th-r" id="trank-avg-ftr" style="padding:2px 6px"></td>
          <td class="sl-th-r" id="trank-avg-defg" style="padding:2px 6px"></td>
          <td class="sl-th-r" id="trank-avg-dtov" style="padding:2px 6px"></td>
          <td class="sl-th-r" id="trank-avg-dor" style="padding:2px 6px"></td>
          <td class="sl-th-r" id="trank-avg-dftr" style="padding:2px 6px"></td>
        </tr>
        <tr>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortTrank('rank')">T-Rk</th>
          <th style="cursor:pointer" onclick="slSortTrank('team')">School</th>
          <th style="cursor:pointer" onclick="slSortTrank('conference')">Conference</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortTrank('record')" title="Overall record">Record</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortTrank('ortg')" title="Adjusted Offensive Efficiency (points per 100 possessions, opponent-adjusted)">AdjO</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortTrank('drtg')" title="Adjusted Defensive Efficiency (points per 100 possessions, opponent-adjusted; lower is better)">AdjD</th>
          <th class="sl-th-r" style="cursor:pointer;background:#555" onclick="slSortTrank('barthag')" title="Pythagorean win probability vs average team — AdjOE^11.5 / (AdjOE^11.5 + AdjDE^11.5) — higher is better">Barthag</th>
          <th class="sl-th-r" style="cursor:pointer;border-left:2px solid #444" onclick="slSortTrank('efg_pct')" title="Effective Field Goal % — (FGM + 0.5×3PM) / FGA">eFG%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortTrank('tov_pct')" title="Turnover rate — turnovers per 100 possessions (lower is better)">TO%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortTrank('oreb_pct')" title="Offensive rebound rate">OR%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortTrank('ft_rate')" title="Free throw rate — FTA / FGA">FTR</th>
          <th class="sl-th-r" style="cursor:pointer;border-left:2px solid #444" onclick="slSortTrank('opp_efg_pct')" title="Opponent Effective Field Goal % (lower is better)">D-eFG%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortTrank('opp_tov_pct')" title="Opponent Turnover rate — forced turnovers per 100 possessions (higher is better)">D-TO%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortTrank('dreb_pct')" title="Defensive rebound rate (higher = fewer opp offensive boards)">DR%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortTrank('opp_ft_rate')" title="Opponent Free throw rate — opp FTA / FGA (lower is better)">D-FTR</th>
        </tr>
      </thead><tbody id="sl-body-trank"></tbody></table></div></div>
    </div>
    <div id="sl-tab-trends" class="sl-tab-content" style="display:none">
      <div class="trends-controls">
        <div class="trends-ctl-group">
          <label>Team</label>
          <select class="trends-team-sel" id="trends-team-sel" onchange="slTrendsSetTeam(this.value)">
            <option value="__league__">League Average</option>
          </select>
        </div>
        <div class="trends-ctl-group">
          <label>Season</label>
          <select class="trends-team-sel" id="trends-year-sel" onchange="slTrendsSetYear(this.value)">
            <option value="all">All Seasons</option>
            <option value="2526">2025-26</option>
            <option value="2425">2024-25</option>
            <option value="2324">2023-24</option>
            <option value="2223">2022-23</option>
            <option value="2122">2021-22</option>
            <option value="1920">2019-20</option>
          </select>
        </div>
        <div class="trends-ctl-group">
          <label>Month</label>
          <button class="trends-month-btn active" onclick="slTrendsSetMonth('all')">All</button>
          <button class="trends-month-btn" onclick="slTrendsSetMonth('Nov')">Nov</button>
          <button class="trends-month-btn" onclick="slTrendsSetMonth('Dec')">Dec</button>
          <button class="trends-month-btn" onclick="slTrendsSetMonth('Jan')">Jan</button>
          <button class="trends-month-btn" onclick="slTrendsSetMonth('Feb')">Feb</button>
          <button class="trends-month-btn" onclick="slTrendsSetMonth('Mar')">Mar</button>
        </div>
      </div>
      <div id="trends-team-card" class="trends-team-card" style="display:none"></div>
      <div class="trends-table-outer" id="trends-table-wrap"></div>
      <div id="trends-tooltip"></div>
    </div>
  </div>

    <div id="sl-tab-rpi" class="sl-tab-content" style="display:none">
      <div class="sl-wab-filter" style="display:flex;align-items:center;justify-content:center;gap:8px;padding:10px 0 14px">
        <span style="font-size:13px;color:#555;font-weight:600">Season:</span>
        <button class="sl-wab-btn" id="sl-rpi-btn-18" onclick="slRpiSeasonFilter('1718')">2017-18</button>
        <button class="sl-wab-btn" id="sl-rpi-btn-19" onclick="slRpiSeasonFilter('1819')">2018-19</button>
        <button class="sl-wab-btn" id="sl-rpi-btn-20" onclick="slRpiSeasonFilter('1920')">2019-20</button>
        <button class="sl-wab-btn" id="sl-rpi-btn-22" onclick="slRpiSeasonFilter('2122')">2021-22</button>
        <button class="sl-wab-btn" id="sl-rpi-btn-23" onclick="slRpiSeasonFilter('2223')">2022-23</button>
        <button class="sl-wab-btn" id="sl-rpi-btn-24" onclick="slRpiSeasonFilter('2324')">2023-24</button>
        <button class="sl-wab-btn" id="sl-rpi-btn-25" onclick="slRpiSeasonFilter('2425')">2024-25</button>
        <button class="sl-wab-btn active" id="sl-rpi-btn-26" onclick="slRpiSeasonFilter('2526')">2025-26</button>
      </div>
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table" id="rpi-table"><thead><tr>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortRpi('rank')">#</th>
        <th style="cursor:pointer" onclick="slSortRpi('team')">School</th>
        <th style="cursor:pointer" onclick="slSortRpi('conference')">Conference</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortRpi('record')" title="Overall record">Record</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortRpi('nc_record')" title="Non-conference record">NC Record</th>
        <th class="sl-th-r" id="rpi-th-rpi" style="cursor:pointer;background:#3a5db5;color:#fff" onclick="slSortRpi('rpi')" title="Rating Percentage Index: 0.25×WP + 0.50×OWP + 0.25×OOWP (all games)">Overall RPI ▼</th>
        <th class="sl-th-r" id="rpi-th-nc_rpi" style="cursor:pointer" onclick="slSortRpi('nc_rpi')" title="Non-Conference RPI: same formula restricted to non-conference games only">NC RPI</th>
      </tr></thead><tbody id="sl-body-rpi"></tbody></table></div></div>
    </div>
</div>

<div id="fanmatch-view" style="display:none;padding:16px 0 24px">
  <div class="sl-cal-nav">
    <button class="sl-cal-btn" id="sl-cal-prev" onclick="slCalStep(-1)">&#8592;</button>
    <div class="sl-cal-center">
      <span class="sl-cal-date" id="sl-cal-date-label"></span>
      <span class="sl-cal-count" id="sl-cal-count"></span>
    </div>
    <button class="sl-cal-btn" id="sl-cal-next" onclick="slCalStep(1)">&#8594;</button>
    <input type="date" id="sl-date-input" onchange="slCalJump()" title="Jump to date" style="margin-left:12px">
  </div>
  <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table"><thead><tr>
    <th class="sl-th-r">#</th><th>Date</th><th>Game</th><th>Location</th><th class="sl-th-r">Win Prob</th><th class="sl-th-r">FanMatch</th><th class="sl-th-r" title="Upset score: reward for win probability gap">Upset</th><th class="sl-th-r" title="Dominance score: margin + strength gap">Dom.</th><th class="sl-th-r" title="Tension score: closeness, overtime, even matchup">Tension</th>
  </tr></thead><tbody id="sl-body-fanmatch"></tbody></table></div></div>
  <div id="sl-lotn"></div>
</div>

<script>
const DATA = {players_json};
const TEAM_DATA = {teams_json};
const LEAGUE_AVG = {league_avg_json};
const TEAM_DATA_2024 = {teams_2024_json};
const LEAGUE_AVG_2024 = {league_avg_2024_json};
const DAILY_RANKS = {daily_ranks_json};
const DAILY_RANKS_2024 = {daily_ranks_2024_json};
const DAILY_RANKS_2023 = {daily_ranks_2023_json};
const DAILY_RANKS_2022 = {daily_ranks_2022_json};
const REL_RATINGS = {rel_ratings_2526_json};
const REL_RATINGS_2024 = {rel_ratings_2425_json};
const REL_RATINGS_2023 = {rel_ratings_2324_json};
const REL_RATINGS_2022 = {rel_ratings_2223_json};
const PLAYER_COUNT = {len(players)};
const TIMESTAMP = '{timestamp}';
const STORYLINES = {storylines_json};
const WAB_DATA = {wab_json};
const WAB_DATA_2024 = {wab_2024_json};
const WAB_DATA_2023 = {wab_2023_json};
const WAB_DATA_2022 = {wab_2022_json};
const WAB_SIM_2526 = {wab_sim_2526_json};
const WAB_SIM_2425 = {wab_sim_2425_json};
const WAB_SIM_2324 = {wab_sim_2324_json};
const WAB_SIM_2223 = {wab_sim_2223_json};

// Conference-only data
const CONF_DATA = {conf_players_json};
const CONF_TEAM_DATA = {conf_teams_json};
const CONF_TEAM_DATA_2024 = {conf_teams_2024_json};
const DATA_2024 = {players_2024_json};
const CONF_DATA_2024 = {conf_players_2024_json};
const STORYLINES_2024 = {storylines_2024_json};
const STORYLINES_2023 = {storylines_2023_json};
const TEAM_DATA_2023 = {teams_2023_json};
const CONF_TEAM_DATA_2023 = {conf_teams_2023_json};
const DATA_2023 = {players_2023_json};
const CONF_DATA_2023 = {conf_players_2023_json};
const LEAGUE_AVG_2023 = {league_avg_2023_json};
const TEAM_DATA_2022 = {teams_2022_json};
const CONF_TEAM_DATA_2022 = {conf_teams_2022_json};
const DATA_2022 = {players_2022_json};
const CONF_DATA_2022 = {conf_players_2022_json};
const STORYLINES_2022 = {storylines_2022_json};
const LEAGUE_AVG_2022 = {league_avg_2022_json};
const WAB_DATA_2021 = {wab_2021_json};
const TEAM_DATA_2021 = {teams_2021_json};
const CONF_TEAM_DATA_2021 = {conf_teams_2021_json};
const DATA_2021 = {players_2021_json};
const CONF_DATA_2021 = {conf_players_2021_json};
const STORYLINES_2021 = {storylines_2021_json};
const LEAGUE_AVG_2021 = {league_avg_2021_json};
const DAILY_RANKS_2021 = {daily_ranks_2021_json};
const REL_RATINGS_2021 = {rel_ratings_2122_json};
const WAB_SIM_2122 = {wab_sim_2122_json};
const WAB_SIM_1920 = {wab_sim_1920_json};
const TEAM_DATA_1920 = {teams_2019_json};
const CONF_TEAM_DATA_1920 = {conf_teams_2019_json};
const DATA_1920 = {players_2019_json};
const CONF_DATA_1920 = {conf_players_2019_json};
const STORYLINES_1920 = {storylines_2019_json};
const DAILY_RANKS_1920 = {daily_ranks_2019_json};
const REL_RATINGS_1920 = {rel_ratings_1920_json};
const LEAGUE_AVG_1920 = {league_avg_2019_json};
const TEAM_DATA_1819 = {teams_1819_json};
const CONF_TEAM_DATA_1819 = {conf_teams_1819_json};
const DATA_1819 = {players_1819_json};
const CONF_DATA_1819 = {conf_players_1819_json};
const STORYLINES_1819 = {storylines_1819_json};
const DAILY_RANKS_1819 = {daily_ranks_1819_json};
const REL_RATINGS_1819 = {rel_ratings_1819_json};
const LEAGUE_AVG_1819 = {league_avg_1819_json};
const TEAM_DATA_1718 = {teams_1718_json};
const CONF_TEAM_DATA_1718 = {conf_teams_1718_json};
const DATA_1718 = {players_1718_json};
const CONF_DATA_1718 = {conf_players_1718_json};
const STORYLINES_1718 = {storylines_1718_json};
const DAILY_RANKS_1718 = {daily_ranks_1718_json};
const REL_RATINGS_1718 = {rel_ratings_1718_json};
const LEAGUE_AVG_1718 = {league_avg_1718_json};

// RPI data (Overall + Non-Conference) per season
const RPI_DATA_2526 = {rpi_data_2526_json};
const RPI_DATA_2425 = {rpi_data_2425_json};
const RPI_DATA_2324 = {rpi_data_2324_json};
const RPI_DATA_2223 = {rpi_data_2223_json};
const RPI_DATA_2122 = {rpi_data_2122_json};
const RPI_DATA_1920 = {rpi_data_1920_json};
const RPI_DATA_1819 = {rpi_data_1819_json};
const RPI_DATA_1718 = {rpi_data_1718_json};

// Active data references (swapped by toggle)
let activeData = DATA;
let activeTeamData = TEAM_DATA;
let activeLeagueAvg = LEAGUE_AVG;
let activeSeason = '2526';
let confMode = false;
let currentTeamMode = 'advanced';

// Filter configuration
const CONF_SECTIONS = {json.dumps({c: info["region"] for c, info in CONFERENCES.items()})};
const ALL_CONFS = {json.dumps(sorted(CONFERENCES.keys()))};
const TEAMS_BY_CONF = {json.dumps({c: sorted(info["teams"]) for c, info in CONFERENCES.items()})};

let curRegion = 'All';
let selConfs = new Set();   // empty = All
let selTeams = new Set();   // empty = All

function togglePanel(id) {{
  const panel = document.getElementById(id + '-panel');
  document.querySelectorAll('.ms-panel.open').forEach(p => {{ if (p.id !== id + '-panel') p.classList.remove('open'); }});
  panel.classList.toggle('open');
}}
document.addEventListener('click', e => {{
  if (!e.target.closest('.multi-select')) document.querySelectorAll('.ms-panel.open').forEach(p => p.classList.remove('open'));
}});

function buildConfPanel() {{
  const panel = document.getElementById('ms-conf-panel');
  panel.innerHTML = '';
  const available = ALL_CONFS.filter(c => curRegion === 'All' || CONF_SECTIONS[c] === curRegion);
  available.forEach(c => {{
    const lbl = document.createElement('label');
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.value = c;
    cb.checked = selConfs.has(c);
    cb.addEventListener('change', () => {{ if (cb.checked) selConfs.add(c); else selConfs.delete(c); onConfsChanged(); }});
    lbl.appendChild(cb); lbl.appendChild(document.createTextNode(c)); panel.appendChild(lbl);
  }});
  // prune stale
  selConfs.forEach(c => {{ if (!available.includes(c)) selConfs.delete(c); }});
  updateMsBtn('ms-conf', selConfs);
}}

function buildTeamPanel() {{
  const panel = document.getElementById('ms-team-panel');
  panel.innerHTML = '';
  const validConfs = selConfs.size > 0 ? [...selConfs] : ALL_CONFS.filter(c => curRegion === 'All' || CONF_SECTIONS[c] === curRegion);
  const available = [];
  validConfs.forEach(c => {{ (TEAMS_BY_CONF[c] || []).forEach(t => available.push(t)); }});
  available.forEach(t => {{
    const lbl = document.createElement('label');
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.value = t;
    cb.checked = selTeams.has(t);
    cb.addEventListener('change', () => {{ if (cb.checked) selTeams.add(t); else selTeams.delete(t); onTeamsChanged(); }});
    lbl.appendChild(cb); lbl.appendChild(document.createTextNode(t)); panel.appendChild(lbl);
  }});
  // prune stale
  selTeams.forEach(t => {{ if (!available.includes(t)) selTeams.delete(t); }});
  updateMsBtn('ms-team', selTeams);
}}

function updateMsBtn(id, set) {{
  const btn = document.querySelector('#' + id + ' .ms-btn');
  if (set.size === 0) btn.textContent = 'All';
  else if (set.size === 1) btn.textContent = [...set][0];
  else btn.textContent = set.size + ' selected';
}}

function onRegionChange() {{
  const checked = document.querySelector('input[name="region"]:checked');
  curRegion = checked ? checked.value : 'All';
  const btn = document.querySelector('#ms-region .ms-btn');
  btn.textContent = curRegion;
  document.getElementById('ms-region-panel').classList.remove('open');
  buildConfPanel();
  buildTeamPanel();
  applyFilters();
}}

function onConfsChanged() {{
  updateMsBtn('ms-conf', selConfs);
  buildTeamPanel();
  applyFilters();
}}

function onTeamsChanged() {{
  updateMsBtn('ms-team', selTeams);
  applyFilters();
}}

function getFilteredPlayers() {{
  return activeData.filter(p => {{
    if (curRegion !== 'All' && p.region !== curRegion) return false;
    if (selConfs.size > 0 && !selConfs.has(p.conference)) return false;
    if (selTeams.size > 0 && !selTeams.has(p.school)) return false;
    if (sortCol === 'tpp' && p.tpa <= 10) return false;
    return true;
  }});
}}

function getFilteredTeams() {{
  return activeTeamData.filter(t => {{
    if (curRegion !== 'All' && t.region !== curRegion) return false;
    if (selConfs.size > 0 && !selConfs.has(t.conference)) return false;
    if (selTeams.size > 0 && !selTeams.has(t.team)) return false;
    return true;
  }});
}}

function applyFilters() {{
  refreshIndividual();
  renderTeams(getFilteredTeams());
  renderDefense(getFilteredTeams());
  updateInfo();
}}

function toggleConfMode(checked) {{
  confMode = checked;
  if (activeSeason === '1718') {{
    activeData = checked ? CONF_DATA_1718 : DATA_1718;
  }} else if (activeSeason === '1819') {{
    activeData = checked ? CONF_DATA_1819 : DATA_1819;
  }} else if (activeSeason === '1920') {{
    activeData = checked ? CONF_DATA_1920 : DATA_1920;
  }} else if (activeSeason === '2122') {{
  }} else if (activeSeason === '2223') {{
    activeData = checked ? CONF_DATA_2022 : DATA_2022;
  }} else if (activeSeason === '2324') {{
    activeData = checked ? CONF_DATA_2023 : DATA_2023;
  }} else if (activeSeason === '2425') {{
    activeData = checked ? CONF_DATA_2024 : DATA_2024;
  }} else {{
    activeData = checked ? CONF_DATA : DATA;
  }}
  if (activeSeason === '1718') {{
    activeTeamData = checked ? CONF_TEAM_DATA_1718 : TEAM_DATA_1718;
  }} else if (activeSeason === '1819') {{
    activeTeamData = checked ? CONF_TEAM_DATA_1819 : TEAM_DATA_1819;
  }} else if (activeSeason === '1920') {{
    activeTeamData = checked ? CONF_TEAM_DATA_1920 : TEAM_DATA_1920;
  }} else if (activeSeason === '2122') {{
    activeTeamData = checked ? CONF_TEAM_DATA_2021 : TEAM_DATA_2021;
  }} else if (activeSeason === '2223') {{
    activeTeamData = checked ? CONF_TEAM_DATA_2022 : TEAM_DATA_2022;
  }} else if (activeSeason === '2324') {{
    activeTeamData = checked ? CONF_TEAM_DATA_2023 : TEAM_DATA_2023;
  }} else if (activeSeason === '2425') {{
    activeTeamData = checked ? CONF_TEAM_DATA_2024 : TEAM_DATA_2024;
  }} else {{
    activeTeamData = checked ? CONF_TEAM_DATA : TEAM_DATA;
  }}
  applyFilters();
  // If in team detail view, re-render it
  const tdDiv = document.getElementById('team-detail-view');
  if (tdDiv.style.display !== 'none' && tdDiv.dataset.team) {{
    showTeamDetail(tdDiv.dataset.team);
  }}
  // Re-render universe if visible
  const uniDiv = document.getElementById('universe-view');
  if (uniDiv.style.display !== 'none') {{
    renderUniverse();
  }}
}}

function switchSeason(season) {{
  activeSeason = season;
  const modeSel = document.getElementById('team-mode-select');
  const mode = modeSel ? modeSel.value : 'advanced';
  const isDefense = document.getElementById('btn-defense') && document.getElementById('btn-defense').classList.contains('active');
  const subLabel = isDefense
    ? 'Opponent Per-Game Averages & Defensive Analytics'
    : (mode === 'basic' ? 'Per-Game Averages' : 'Per-Game Averages & Advanced Analytics');
  document.getElementById('btn-season-18').classList.remove('active');
  document.getElementById('btn-season-19').classList.remove('active');
  document.getElementById('btn-season-20').classList.remove('active');
  document.getElementById('btn-season-22').classList.remove('active');
  document.getElementById('btn-season-23').classList.remove('active');
  document.getElementById('btn-season-24').classList.remove('active');
  document.getElementById('btn-season-25').classList.remove('active');
  document.getElementById('btn-season-26').classList.remove('active');
  if (season === '1718') {{
    activeTeamData = confMode ? CONF_TEAM_DATA_1718 : TEAM_DATA_1718;
    activeData = confMode ? CONF_DATA_1718 : DATA_1718;
    activeLeagueAvg = LEAGUE_AVG_1718;
    document.getElementById('btn-season-18').classList.add('active');
    document.getElementById('page-subtitle').textContent = '2017-18 Season \u2014 ' + subLabel;
  }} else if (season === '1819') {{
    activeTeamData = confMode ? CONF_TEAM_DATA_1819 : TEAM_DATA_1819;
    activeData = confMode ? CONF_DATA_1819 : DATA_1819;
    activeLeagueAvg = LEAGUE_AVG_1819;
    document.getElementById('btn-season-19').classList.add('active');
    document.getElementById('page-subtitle').textContent = '2018-19 Season \u2014 ' + subLabel;
  }} else if (season === '1920') {{
    activeTeamData = confMode ? CONF_TEAM_DATA_1920 : TEAM_DATA_1920;
    activeData = confMode ? CONF_DATA_1920 : DATA_1920;
    activeLeagueAvg = LEAGUE_AVG_1920;
    document.getElementById('btn-season-20').classList.add('active');
    document.getElementById('page-subtitle').textContent = '2019-20 Season \u2014 ' + subLabel;
  }} else if (season === '2122') {{
    activeTeamData = confMode ? CONF_TEAM_DATA_2021 : TEAM_DATA_2021;
    activeData = confMode ? CONF_DATA_2021 : DATA_2021;
    activeLeagueAvg = LEAGUE_AVG_2021;
    document.getElementById('btn-season-22').classList.add('active');
    document.getElementById('page-subtitle').textContent = '2021-22 Season \u2014 ' + subLabel;
  }} else if (season === '2223') {{
    activeTeamData = confMode ? CONF_TEAM_DATA_2022 : TEAM_DATA_2022;
    activeData = confMode ? CONF_DATA_2022 : DATA_2022;
    activeLeagueAvg = LEAGUE_AVG_2022;
    document.getElementById('btn-season-23').classList.add('active');
    document.getElementById('page-subtitle').textContent = '2022-23 Season \u2014 ' + subLabel;
  }} else if (season === '2324') {{
    activeTeamData = confMode ? CONF_TEAM_DATA_2023 : TEAM_DATA_2023;
    activeData = confMode ? CONF_DATA_2023 : DATA_2023;
    activeLeagueAvg = LEAGUE_AVG_2023;
    document.getElementById('btn-season-24').classList.add('active');
    document.getElementById('page-subtitle').textContent = '2023-24 Season \u2014 ' + subLabel;
  }} else if (season === '2425') {{
    activeTeamData = confMode ? CONF_TEAM_DATA_2024 : TEAM_DATA_2024;
    activeData = confMode ? CONF_DATA_2024 : DATA_2024;
    activeLeagueAvg = LEAGUE_AVG_2024;
    document.getElementById('btn-season-25').classList.add('active');
    document.getElementById('page-subtitle').textContent = '2024-25 Season \u2014 ' + subLabel;
  }} else {{
    activeTeamData = confMode ? CONF_TEAM_DATA : TEAM_DATA;
    activeData = confMode ? CONF_DATA : DATA;
    activeLeagueAvg = LEAGUE_AVG;
    document.getElementById('btn-season-26').classList.add('active');
    document.getElementById('page-subtitle').textContent = '2025-26 Season \u2014 ' + subLabel;
  }}
  renderTeams(getFilteredTeams());
  renderDefense(getFilteredTeams());
  refreshIndividual();
  buildUniSidebar();
  renderUniverse();
  // If team detail is open, re-render it with new season data
  const tdDiv = document.getElementById('team-detail-view');
  if (tdDiv && tdDiv.style.display !== 'none' && currentTeam) {{
    const teamName = currentTeam.team;
    // Look up team in the new season data
    const newT = activeTeamData.find(d => d.team === teamName)
              || TEAM_DATA.find(d => d.team === teamName)
              || TEAM_DATA_2024.find(d => d.team === teamName);
    if (newT) {{
      currentTeam = newT;
      document.getElementById('team-detail-content').innerHTML = buildTeamDetail(newT);
    }}
  }}
  // Sync Rate tab season filter buttons and re-render if active
  slRateSeason = season;
  const rb18 = document.getElementById('sl-rate-btn-18');
  const rb19 = document.getElementById('sl-rate-btn-19');
  const rb20 = document.getElementById('sl-rate-btn-20');
  const rb22 = document.getElementById('sl-rate-btn-22');
  const rb23 = document.getElementById('sl-rate-btn-23');
  const rb24 = document.getElementById('sl-rate-btn-24');
  const rb25 = document.getElementById('sl-rate-btn-25');
  const rb26 = document.getElementById('sl-rate-btn-26');
  if (rb18) rb18.classList.toggle('active', season === '1718');
  if (rb19) rb19.classList.toggle('active', season === '1819');
  if (rb20) rb20.classList.toggle('active', season === '1920');
  if (rb22) rb22.classList.toggle('active', season === '2122');
  if (rb23) rb23.classList.toggle('active', season === '2223');
  if (rb24) rb24.classList.toggle('active', season === '2324');
  if (rb25) rb25.classList.toggle('active', season === '2425');
  if (rb26) rb26.classList.toggle('active', season === '2526');
  if (slActiveTab === 'rate') slRenderRate(season);
  // Refresh fanmatch if it's the active view (and storylines hasn't been init'd to cover it)
  const fmDiv2 = document.getElementById('fanmatch-view');
  if (fmDiv2 && fmDiv2.style.display !== 'none') slInitFanmatch();
  // Update individual view subtitle if active
  const indDiv2 = document.getElementById('individual-view');
  if (indDiv2 && indDiv2.style.display !== 'none') {{
    const yr2 = season === '1718' ? '2017-18' : season === '1819' ? '2018-19' : season === '1920' ? '2019-20' : season === '2122' ? '2021-22' : season === '2223' ? '2022-23' : season === '2324' ? '2023-24' : season === '2425' ? '2024-25' : '2025-26';
    document.getElementById('page-subtitle').textContent = yr2 + ' Season \u2014 Per-Game Averages';
  }}
  if (slInitialized) slReinit();
}}

function getFilterLabel() {{
  if (selTeams.size === 1) return [...selTeams][0];
  if (selConfs.size === 1) return [...selConfs][0];
  if (selTeams.size > 1) return selTeams.size + ' Teams';
  if (selConfs.size > 1) return selConfs.size + ' Conferences';
  if (curRegion !== 'All') return curRegion;
  return '';
}}

function updateTitle() {{
  const title = document.getElementById('page-title');
  const indDiv = document.getElementById('individual-view');
  const label = getFilterLabel();
  const prefix = label ? label + ' ' : '';
  if (indDiv.style.display !== 'none') {{
    title.textContent = prefix + 'Individual Statistics Leaderboard';
  }} else {{
    title.textContent = prefix + 'Team Statistics';
  }}
}}

function updateInfo() {{
  const info = document.getElementById('page-info');
  const indDiv = document.getElementById('individual-view');
  if (indDiv.style.display !== 'none') {{
    const cnt = getFilteredPlayers().length;
    info.textContent = cnt + ' qualified players \u00b7 40% minutes played minimum \u00b7 Click any column header to sort \u00b7 Generated ' + TIMESTAMP;
  }} else {{
    const cnt = getFilteredTeams().length;
    info.textContent = cnt + ' teams \u00b7 Click any column header to sort \u00b7 Generated ' + TIMESTAMP;
  }}
  updateTitle();
}}

buildConfPanel();
buildTeamPanel();

// Which columns are "lower is better" — everything else defaults to "higher is better"
const LOW = new Set([
  'drtg', 'tov_pct', 'topg', 'opp_drtg_sos',
  'opp_efg_pct', 'opp_ft_rate',
  'opp_fgp', 'opp_twop', 'opp_tpp', 'opp_ftp', 'opp_ts_pct',
]);
function bestDir(col) {{ return LOW.has(col) ? 'asc' : 'desc'; }}

function parseWins(rec) {{
  const m = (rec || '').match(/^(\\d+)/);
  return m ? parseInt(m[1], 10) : 0;
}}
const MP_GOLD = '#ffe599';
function mpGold(team) {{ return team === 'Moorpark' ? `background:${{MP_GOLD}}` : ''; }}
function mpGoldGame(g) {{ return (g.winner === 'Moorpark' || g.loser === 'Moorpark') ? `background:${{MP_GOLD}}` : ''; }}

function highlightCol(tbody, col) {{
  const table = tbody.closest('table');
  const ths = Array.from(table.querySelectorAll('thead th'));
  const idx = ths.findIndex(th => th.dataset.col === col);
  if (idx < 0) return;
  tbody.querySelectorAll('tr').forEach(tr => {{
    const tds = tr.children;
    for (let j = 0; j < tds.length; j++) {{
      tds[j].classList.toggle('active-col', j === idx);
    }}
  }});
}}

function render(data) {{
  const tb = document.getElementById('tbody');
  tb.innerHTML = '';
  const invert = sortType !== 'str' && sortDir !== sortBest;
  data.forEach((p, i) => {{
    const rank = invert ? data.length - i : i + 1;
    const tr = document.createElement('tr');
    // Always display 'LA Pierce' in uppercase
    const schoolDisplay = p.school === 'La Pierce' ? 'LA Pierce' : p.school;
    tr.innerHTML = `
      <td>${{rank}}</td>
      <td>${{p.name}}${{p.pos ? `<span style="font-size:0.65rem;color:#888;margin-left:5px;vertical-align:middle">${{p.pos}}</span>` : ''}}</td>
      <td>${{teamPageLink(p.school, 'color:inherit;text-decoration:none', schoolDisplay)}}</td>
      <td>${{p.gp}}</td>
      <td>${{p.mpg.toFixed(1)}}</td>
      <td>${{p.ppg.toFixed(1)}}</td>
      <td>${{p.orpg.toFixed(1)}}</td>
      <td>${{p.drpg.toFixed(1)}}</td>
      <td>${{p.rpg.toFixed(1)}}</td>
      <td>${{p.apg.toFixed(1)}}</td>
      <td>${{p.spg.toFixed(1)}}</td>
      <td>${{p.bpg.toFixed(1)}}</td>
      <td>${{p.topg.toFixed(1)}}</td>
      <td>${{p.fgm}}-${{p.fga}}</td>
      <td>${{p.fgp.toFixed(1)}}</td>
      <td>${{p.twom}}-${{p.twoa}}</td>
      <td>${{p.twop.toFixed(1)}}</td>
      <td>${{p.tpm}}-${{p.tpa}}</td>
      <td>${{p.tpp.toFixed(1)}}</td>
      <td>${{p.ftm}}-${{p.fta}}</td>
      <td>${{p.ftp.toFixed(1)}}</td>
    `;
    if (p.school === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
    tb.appendChild(tr);
  }});
  highlightCol(tb, sortCol);
}}

// ── Advanced individual stats ────────────────────────────────────────────────
let indCat = null;
let indMode = 'basic';

function onIndModeChange(mode) {{
  indMode = mode;
  const advTabs = document.getElementById('ind-adv-tabs');
  const basicView = document.getElementById('basic-view');
  const advView = document.getElementById('adv-view');
  if (mode === 'advanced') {{
    if (advTabs) advTabs.style.display = '';
    basicView.style.display = 'none';
    advView.style.display = '';
    if (!indCat) {{
      const firstBtn = advTabs && advTabs.querySelector('.adv-cat-btn');
      if (firstBtn) switchIndCat(firstBtn.dataset.cat);
    }} else {{
      renderAdv(getFilteredPlayers(), indCat);
    }}
  }} else {{
    if (advTabs) advTabs.style.display = 'none';
    basicView.style.display = '';
    advView.style.display = 'none';
    indCat = null;
    render(getFilteredPlayers());
  }}
}}
const ADV_CATS = [
  {{key:'ind_ortg',  label:'ORtg',   desc:'Individual Offensive Rating (pts per 100 poss used)',    asc:false, poss_buckets:true}},
  {{key:'ind_drtg',  label:'DRtg',   desc:'Individual Defensive Rating (pts allowed per 100 poss)', asc:true}},
  {{key:'efg_pct',   label:'eFG%',   desc:'Effective Field Goal % (3-pointers worth 1.5x)',         asc:false}},
  {{key:'ts_pct',    label:'TS%',    desc:'True Shooting % (2s, 3s, and FTs)',                      asc:false}},
  {{key:'min_pct',   label:'%Min',   desc:'Minutes played % \u2014 player MIN / (40 \u00d7 GP)',    asc:false}},
  {{key:'usage_pct', label:'%Poss',  desc:'% of team possessions used while on floor',              asc:false}},
  {{key:'shot_pct',  label:'%Shots', desc:'% of team field goal attempts taken',                    asc:false}},
  {{key:'oreb_pct',  label:'OREB%',  desc:'Offensive Rebound % (of available offensive boards)',    asc:false}},
  {{key:'dreb_pct',  label:'DREB%',  desc:'Defensive Rebound % (of available defensive boards)',    asc:false}},
  {{key:'tov_pct',   label:'TO%',    desc:'Turnover % per possession used',                        asc:true}},
  {{key:'ast_rate',  label:'ARate',  desc:'Assist Rate \u2014 % of teammate FGs assisted',          asc:false}},
  {{key:'blk_pct',   label:'Blk%',   desc:'Block % \u2014 % of opponent 2-pt attempts blocked',    asc:false}},
  {{key:'stl_pct',   label:'Stl%',   desc:'Steal % \u2014 % of opp possessions ended with steal',  asc:false}},
  {{key:'ft_rate',   label:'FTRate', desc:'Free Throw Rate \u2014 FTA per FGA',                     asc:false}},
  {{key:'fc_per_40', label:'FC/40',  desc:'Personal fouls committed per 40 minutes',               asc:true}},
  {{key:'fd_per_40', label:'FD/40',  desc:'Personal fouls drawn per 40 minutes',                   asc:false}},
  {{key:'twop',      label:'2P%',    desc:'2-point field goal percentage',                         asc:false}},
  {{key:'tpp',       label:'3P%',    desc:'3-point field goal percentage',                         asc:false}},
  {{key:'ftp',       label:'FT%',    desc:'Free throw percentage',                                 asc:false}},
];
const POSS_BUCKETS = [
  {{min: 28, max: null, label: '28%+ %Poss'}},
  {{min: 24, max: 28,   label: '24\u201328% %Poss'}},
  {{min: 20, max: 24,   label: '20\u201324% %Poss'}},
  {{min: 16, max: 20,   label: '16\u201320% %Poss'}},
  {{min: 12, max: 16,   label: '12\u201316% %Poss'}},
  {{min:  0, max: 12,   label: 'Sub-12% %Poss'}},
];
const MIN_PCT_QUAL = 30;

function switchIndCat(key) {{
  indCat = key;
  document.querySelectorAll('.adv-cat-btn').forEach(btn => {{
    btn.classList.toggle('active', btn.dataset.cat === key);
  }});
  const cat = ADV_CATS.find(c => c.key === key);
  if (cat) {{
    const th = document.getElementById('adv-stat-th');
    if (th) {{ th.textContent = cat.label; th.title = cat.desc; }}
  }}
  renderAdv(getFilteredPlayers(), key);
}}

function renderAdv(data, catKey) {{
  const cat = ADV_CATS.find(c => c.key === catKey);
  if (!cat) return;
  const tb = document.getElementById('adv-tbody');
  if (!tb) return;
  tb.innerHTML = '';
  const qualified = data.filter(p => (p.min_pct || 0) >= MIN_PCT_QUAL);
  if (cat.poss_buckets) {{
    POSS_BUCKETS.forEach(bucket => {{
      const pool = qualified
        .filter(p => p[catKey] != null && p.usage_pct != null && p.usage_pct <= 40 && p.usage_pct >= bucket.min && (bucket.max == null || p.usage_pct < bucket.max))
        .sort((a, b) => cat.asc ? a[catKey] - b[catKey] : b[catKey] - a[catKey])
        .slice(0, 100);
      if (pool.length === 0) return;
      const htr = tb.insertRow();
      const htd = htr.insertCell();
      htd.colSpan = 5;
      htd.className = 'adv-section-hdr';
      htd.textContent = bucket.label;
      pool.forEach((p, i) => {{
        const tr = tb.insertRow();
        const schoolDisplay = p.school === 'La Pierce' ? 'LA Pierce' : p.school;
        const statVal = typeof p[catKey] === 'number' ? p[catKey].toFixed(1) : '\u2014';
        const poss = p.usage_pct != null ? ` (${{p.usage_pct.toFixed(1)}})` : '';
        tr.innerHTML = `<td>${{i+1}}</td><td>${{p.name}}${{p.pos ? `<span style="font-size:0.65rem;color:#888;margin-left:5px;vertical-align:middle">${{p.pos}}</span>` : ''}}</td><td>${{teamPageLink(p.school,'color:inherit;text-decoration:none',schoolDisplay)}}</td><td>${{p.gp}}</td><td>${{statVal}}${{poss}}</td>`;
        if (p.school === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
      }});
    }});
  }} else {{
    const pool = qualified
      .filter(p => p[catKey] != null && (catKey !== 'usage_pct' || p[catKey] <= 40))
      .sort((a, b) => cat.asc ? a[catKey] - b[catKey] : b[catKey] - a[catKey])
      .slice(0, 100);
    pool.forEach((p, i) => {{
      const tr = tb.insertRow();
      const schoolDisplay = p.school === 'La Pierce' ? 'LA Pierce' : p.school;
      const fmt = typeof p[catKey] === 'number' ? p[catKey].toFixed(1) : '\u2014';
      tr.innerHTML = `<td>${{i+1}}</td><td>${{p.name}}${{p.pos ? `<span style="font-size:0.65rem;color:#888;margin-left:5px;vertical-align:middle">${{p.pos}}</span>` : ''}}</td><td>${{teamPageLink(p.school,'color:inherit;text-decoration:none',schoolDisplay)}}</td><td>${{p.gp}}</td><td>${{fmt}}</td>`;
      if (p.school === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
    }});
  }}
}}

function refreshIndividual() {{
  if (indMode === 'advanced' && indCat !== null) {{
    renderAdv(getFilteredPlayers(), indCat);
  }} else if (indMode !== 'advanced') {{
    render(getFilteredPlayers());
  }}
}}

let sortCol = 'ppg';
let sortDir = 'desc';
let sortType = 'num';
let sortBest = 'desc';

function doSort(col, type) {{
  if (col === sortCol) {{
    sortDir = sortDir === 'desc' ? 'asc' : 'desc';
  }} else {{
    sortCol = col;
    sortType = type;
    const bd = bestDir(col);
    sortDir = type === 'str' ? 'asc' : bd;
    sortBest = type === 'str' ? 'asc' : bd;
  }}

  activeData.sort((a, b) => {{
    let va = a[col], vb = b[col];
    if (type === 'str') {{
      va = (va || '').toLowerCase();
      vb = (vb || '').toLowerCase();
      return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
    }}
    return sortDir === 'asc' ? va - vb : vb - va;
  }});

  // Update header styles
  document.querySelectorAll('th').forEach(th => {{
    th.classList.remove('active', 'asc', 'desc');
    if (th.dataset.col === col) {{
      th.classList.add('active', sortDir);
    }}
  }});

  refreshIndividual();
}}

// Click handlers
document.querySelectorAll('th[data-col]').forEach(th => {{
  if (th.dataset.col === 'rank') return;
  th.addEventListener('click', () => doSort(th.dataset.col, th.dataset.type));
}});

// Initial render
render(getFilteredPlayers());
showView('team');

function getOppAdjMsg(team, val) {{
  const abs = Math.abs(val);
  if (abs < 0.05) {{
    return team + ' performs at a similar level against both good and bad teams.';
  }} else if (val > 0 && abs < 0.15) {{
    return team + ' plays a little better against good teams than bad teams. They are slightly better than expected against tough opposition but are slightly worse against weaker opponents.';
  }} else if (val > 0) {{
    return team + ' plays much better against good teams than bad teams. They tend to have their best performances against stronger opponents and really thrive when facing tougher competition.';
  }} else if (abs < 0.15) {{
    return team + ' plays a little worse against good teams than bad teams. They tend to play slightly better than expected against weaker opposition but are slightly worse against tougher opponents.';
  }} else {{
    return team + ' plays much worse against good teams than bad teams. They tend to have their best performances against weaker opponents but really struggle against stronger teams on their schedule.';
  }}
}}

function getPaceAdjMsg(team, val) {{
  const abs = Math.abs(val);
  if (abs < 0.05) {{
    return team + ' performs at a similar level regardless of the pace of the game.';
  }} else if (val > 0 && abs < 0.15) {{
    return team + ' plays a little better in faster paced games. They have slightly stronger performances in games with more possessions but are a little worse in games with less possessions.';
  }} else if (val > 0) {{
    return team + ' plays much better in faster paced games. They have stronger performances in games with more possessions but are worse in games with less possessions.';
  }} else if (abs < 0.15) {{
    return team + ' plays a little better in slower paced games. They have slightly stronger performances in games with less possessions but are a little worse in games with more possessions.';
  }} else {{
    return team + ' plays much better in slower paced games. They have stronger performances in games with less possessions but are worse in games with more possessions.';
  }}
}}

// --- Team table ---
function buildColRanks() {{
  const _fsBR = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  const valid = activeTeamData.filter(d => d.ortg > 0);
  const fsValid = _fsBR.filter(d => d.ortg > 0);
  function rankCol(pool, key, lowBetter) {{
    const sorted = [...pool].filter(d => d[key] != null).sort((a,b) => lowBetter ? a[key]-b[key] : b[key]-a[key]);
    const map = {{}};
    sorted.forEach((d,i) => {{ map[d.team] = i+1; }});
    return map;
  }}
  return {{
    tempo: rankCol(valid, 'tempo', false),
    ortg: rankCol(valid, 'ortg', false),
    drtg: rankCol(valid, 'drtg', true),
    net_rtg: rankCol(valid, 'net_rtg', false),
    efg_pct: rankCol(valid, 'efg_pct', false),
    oreb_pct: rankCol(valid, 'oreb_pct', false),
    tov_pct: rankCol(valid, 'tov_pct', true),
    ft_rate: rankCol(valid, 'ft_rate', false),
    luck: rankCol(valid, 'luck', false),
    opp_ortg: rankCol(fsValid, 'opp_ortg', false),
    opp_drtg_sos: rankCol(fsValid, 'opp_drtg_sos', true),
    sos: rankCol(fsValid, 'sos', false),
    ncsos: rankCol(fsValid, 'ncsos', false),
    opp_efg_pct: rankCol(valid, 'opp_efg_pct', true),
    dreb_pct: rankCol(valid, 'dreb_pct', false),
    opp_tov_pct: rankCol(valid, 'opp_tov_pct', false),
    opp_ft_rate: rankCol(valid, 'opp_ft_rate', true),
    ts_pct:  rankCol(valid, 'ts_pct',  false),
    twop:    rankCol(valid, 'twop',    false),
    tpp:     rankCol(valid, 'tpp',     false),
    ftp:     rankCol(valid, 'ftp',     false),
    ast_pct:   rankCol(valid, 'ast_pct',   false),
    ast_ratio: rankCol(valid, 'ast_ratio', false),
    ast_tov:   rankCol(valid, 'ast_tov',   false),
    nst_pct:   rankCol(valid, 'nst_pct',   true),
    tpa_pct:   rankCol(valid, 'tpa_pct',   false),
    stl_to:    rankCol(valid, 'stl_to',    false),
    stl_pct:   rankCol(valid, 'stl_pct',   false),
    blk_pct:   rankCol(valid, 'blk_pct',   false),
    hkm_pct:   rankCol(valid, 'hkm_pct',   false),
    drebpg:    rankCol(valid, 'drebpg',    false),
    spg:       rankCol(valid, 'spg',       false),
    bpg:       rankCol(valid, 'bpg',       false),
    opp_tpa_pct: rankCol(valid, 'opp_tpa_pct', false),
    pfpg:      rankCol(valid.filter(d => !d.pf_unreliable), 'pfpg',   true),
    pf_eff:    rankCol(valid.filter(d => !d.pf_unreliable), 'pf_eff', false),
    stl_pf:    rankCol(valid.filter(d => !d.pf_unreliable), 'stl_pf', false),
    blk_pf:    rankCol(valid.filter(d => !d.pf_unreliable), 'blk_pf', false),
  }};
}}

function renderTeams(data) {{
  const tb = document.getElementById('team-tbody');
  tb.innerHTML = '';
  const colRanks = buildColRanks();
  const rk = (col, team) => {{ const r = colRanks[col]?.[team]; return r ? `<span style="font-size:0.65rem;color:#000;margin-left:4px;vertical-align:middle">${{r}}</span>` : ''; }};
  const invert = teamSortType !== 'str' && teamSortDir !== teamSortBest;
  data.forEach((t, i) => {{
    const rank = invert ? data.length - i : i + 1;
    const tr = document.createElement('tr');
    // Always use full-season data for Record, Conf, Opp ORTG, Opp DRTG, SOS, NCSOS
    const _fsPool = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
    const fs = _fsPool.find(d => d.team === t.team) || t;
    tr.innerHTML = `
      <td>${{rank}}</td>
      <td style="text-align:left;font-weight:700">${{teamPageLink(t.team)}}</td>
      <td>${{t.gp}}</td>
      <td>${{fs.record}}</td>
      <td>${{fs.conf}}</td>
      <td>${{Number(t.tempo).toFixed(1)}}${{rk('tempo',t.team)}}</td>
      <td>${{Number(t.ortg).toFixed(1)}}${{rk('ortg',t.team)}}</td>
      <td>${{Number(t.drtg).toFixed(1)}}${{rk('drtg',t.team)}}</td>
      <td>${{Number(t.net_rtg).toFixed(1)}}${{rk('net_rtg',t.team)}}</td>
      <td style="padding:0 4px"><div class="opp-bar-wrap" data-opptip="${{getOppAdjMsg(t.team, t.opp_adjust)}}"><div style="position:relative;width:50px;height:14px;background:transparent;border-radius:2px"><div style="position:absolute;top:0;height:100%;border-radius:2px;${{t.opp_adjust >= 0 ? `left:50%;width:${{Math.min(Math.abs(t.opp_adjust)/0.35*50,50)}}%;background:#e74c3c` : `right:50%;width:${{Math.min(Math.abs(t.opp_adjust)/0.35*50,50)}}%;background:#3498db`}}"></div><div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:#666"></div></div></div></td>
      <td style="padding:0 4px"><div class="pace-bar-wrap" data-pacetip="${{getPaceAdjMsg(t.team, t.pace_adjust)}}"><div style="position:relative;width:50px;height:14px;background:transparent;border-radius:2px"><div style="position:absolute;top:0;height:100%;border-radius:2px;${{t.pace_adjust >= 0 ? `left:50%;width:${{Math.min(Math.abs(t.pace_adjust)/0.35*50,50)}}%;background:#e67e22` : `right:50%;width:${{Math.min(Math.abs(t.pace_adjust)/0.35*50,50)}}%;background:#3498db`}}"></div><div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:#666"></div></div></div></td>
      <td>${{Number(fs.opp_ortg).toFixed(1)}}${{rk('opp_ortg',t.team)}}</td>
      <td>${{Number(fs.opp_drtg_sos).toFixed(1)}}${{rk('opp_drtg_sos',t.team)}}</td>
      <td>${{Number(fs.sos).toFixed(1)}}${{rk('sos',t.team)}}</td>
      <td>${{Number(fs.ncsos).toFixed(1)}}${{rk('ncsos',t.team)}}</td>
      <td>${{t.luck != null ? (t.luck >= 0 ? '+' : '') + t.luck.toFixed(2) : '—'}}${{rk('luck',t.team)}}</td>
      <td>${{Number(t.efg_pct).toFixed(1)}}${{rk('efg_pct',t.team)}}</td>
      <td>${{Number(t.oreb_pct).toFixed(1)}}${{rk('oreb_pct',t.team)}}</td>
      <td>${{Number(t.tov_pct).toFixed(1)}}${{rk('tov_pct',t.team)}}</td>
      <td>${{Number(t.ft_rate).toFixed(1)}}${{rk('ft_rate',t.team)}}</td>
    `;
    if (t.team === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
    tb.appendChild(tr);
  }});
  highlightCol(tb, teamSortCol);
  applyTeamModeOffenseColumns();
  renderTeamsBasic(data);
  renderTeamsBasicDefense(data);
  renderTeamsAdvOffense(data);
  renderTeamsAdvDefense(data);
}}

function renderTeamsBasic(data) {{
  const tb = document.getElementById('team-basic-tbody');
  if (!tb) return;
  tb.innerHTML = '';
  const _fsPool = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  data.forEach((t, i) => {{
    const fs = _fsPool.find(d => d.team === t.team) || t;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${{i + 1}}</td>
      <td style="text-align:left;font-weight:700">${{teamPageLink(t.team)}}</td>
      <td>${{t.gp}}</td>
      <td>${{fs.record}}</td>
      <td>${{fs.conf}}</td>
      <td>${{Number(t.ppg).toFixed(1)}}</td>
      <td>${{Number(t.opp_ppg).toFixed(1)}}</td>
      <td>${{Number(t.fgp).toFixed(1)}}%</td>
      <td>${{Number(t.twop).toFixed(1)}}%</td>
      <td>${{Number(t.tpp).toFixed(1)}}%</td>
      <td>${{Number(t.ftp).toFixed(1)}}%</td>
      <td>${{Number(t.orebpg).toFixed(1)}}</td>
      <td>${{Number(t.drebpg).toFixed(1)}}</td>
      <td>${{Number(t.rpg).toFixed(1)}}</td>
      <td>${{Number(t.apg).toFixed(1)}}</td>
      <td>${{Number(t.spg).toFixed(1)}}</td>
      <td>${{Number(t.bpg).toFixed(1)}}</td>
      <td>${{Number(t.topg).toFixed(1)}}</td>
      <td>${{Number(t.pfpg).toFixed(1)}}</td>
    `;
    if (t.team === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
    tb.appendChild(tr);
  }});
}}

function renderTeamsBasicDefense(data) {{
  const tb = document.getElementById('team-basic-defense-tbody');
  if (!tb) return;
  tb.innerHTML = '';
  const _fsPool = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  data.forEach((t, i) => {{
    const fs = _fsPool.find(d => d.team === t.team) || t;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${{i + 1}}</td>
      <td style="text-align:left;font-weight:700">${{teamPageLink(t.team)}}</td>
      <td>${{t.gp}}</td>
      <td>${{fs.record}}</td>
      <td>${{fs.conf}}</td>
      <td>${{Number(t.opp_ppg).toFixed(1)}}</td>
      <td>${{Number(t.opp_fgp).toFixed(1)}}%</td>
      <td>${{Number(t.opp_twop).toFixed(1)}}%</td>
      <td>${{Number(t.opp_tpp).toFixed(1)}}%</td>
      <td>${{Number(t.opp_ftp).toFixed(1)}}%</td>
      <td>${{Number(t.opp_orebpg).toFixed(1)}}</td>
      <td>${{Number(t.opp_drebpg).toFixed(1)}}</td>
      <td>${{Number(t.opp_rpg).toFixed(1)}}</td>
      <td>${{Number(t.opp_apg).toFixed(1)}}</td>
      <td>${{Number(t.opp_spg).toFixed(1)}}</td>
      <td>${{Number(t.opp_bpg).toFixed(1)}}</td>
      <td>${{Number(t.opp_topg).toFixed(1)}}</td>
      <td>${{Number(t.opp_pfpg).toFixed(1)}}</td>
    `;
    if (t.team === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
    tb.appendChild(tr);
  }});
}}

function applyTeamModeOffenseColumns() {{
  const table = document.getElementById('team-leaderboard');
  if (!table) return;
  const hideCols = currentTeamMode === 'basic' ? new Set([10, 11, 12, 13, 14, 15, 16]) : new Set();
  table.querySelectorAll('thead th').forEach((th, idx) => {{
    th.style.display = hideCols.has(idx + 1) ? 'none' : '';
  }});
  table.querySelectorAll('tbody tr').forEach(tr => {{
    Array.from(tr.children).forEach((td, idx) => {{
      td.style.display = hideCols.has(idx + 1) ? 'none' : '';
    }});
  }});
}}

let teamSortCol = 'net_rtg';
let teamSortDir = 'desc';
let teamSortType = 'num';
let teamSortBest = 'desc';
let basicSortCol = 'net_rtg';
let basicSortDir = 'desc';
let basicDefSortCol = 'net_rtg';
let basicDefSortDir = 'desc';
let advOffSortCol = 'net_rtg';
let advOffSortDir = 'desc';
let advDefSortCol = 'drtg';
let advDefSortDir = 'asc';

function doTeamSort(col, type) {{
  if (col === teamSortCol) {{
    teamSortDir = teamSortDir === 'desc' ? 'asc' : 'desc';
  }} else {{
    teamSortCol = col;
    teamSortType = type;
    const bd = bestDir(col);
    teamSortDir = type === 'str' ? 'asc' : bd;
    teamSortBest = type === 'str' ? 'asc' : bd;
  }}
  const FS_COLS = new Set(['gp','record','conf','opp_ortg','opp_drtg_sos','sos','ncsos','team']);
  const _fsSortPool = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  activeTeamData.sort((a, b) => {{
    let sa = a, sb = b;
    if (FS_COLS.has(col)) {{
      sa = _fsSortPool.find(d => d.team === a.team) || a;
      sb = _fsSortPool.find(d => d.team === b.team) || b;
    }}
    let va = sa[col], vb = sb[col];
    if (type === 'rec') {{
      va = parseWins(va); vb = parseWins(vb);
      return teamSortDir === 'asc' ? va - vb : vb - va;
    }}
    if (type === 'str') {{
      va = (va || '').toLowerCase();
      vb = (vb || '').toLowerCase();
      return teamSortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
    }}
    return teamSortDir === 'asc' ? va - vb : vb - va;
  }});
  document.querySelectorAll('th[data-table="team"]').forEach(th => {{
    th.classList.remove('active', 'asc', 'desc');
    if (th.dataset.col === col) th.classList.add('active', teamSortDir);
  }});
  renderTeams(getFilteredTeams());
}}

document.querySelectorAll('th[data-table="team"]').forEach(th => {{
  if (th.dataset.col === 'rank') return;
  th.addEventListener('click', () => doTeamSort(th.dataset.col, th.dataset.type));
}});

renderTeams(getFilteredTeams());

// --- Defense table ---
function renderDefense(data) {{
  const tb = document.getElementById('team-defense-tbody');
  tb.innerHTML = '';
  const colRanks = buildColRanks();
  const rk = (col, team) => {{ const r = colRanks[col]?.[team]; return r ? `<span style="font-size:0.65rem;color:#000;margin-left:4px;vertical-align:middle">${{r}}</span>` : ''; }};
  const invert = defSortType !== 'str' && defSortDir !== defSortBest;
  data.forEach((t, i) => {{
    const rank = invert ? data.length - i : i + 1;
    const tr = document.createElement('tr');
    // Always use full-season data for Record, Conf, Opp ORTG, Opp DRTG, SOS, NCSOS
    const _fsPool2 = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
    const fs = _fsPool2.find(d => d.team === t.team) || t;
    tr.innerHTML = `
      <td>${{rank}}</td>
      <td style="text-align:left;font-weight:700">${{teamPageLink(t.team)}}</td>
      <td>${{t.gp}}</td>
      <td>${{fs.record}}</td>
      <td>${{fs.conf}}</td>
      <td>${{Number(t.tempo).toFixed(1)}}${{rk('tempo',t.team)}}</td>
      <td>${{Number(t.ortg).toFixed(1)}}${{rk('ortg',t.team)}}</td>
      <td>${{Number(t.drtg).toFixed(1)}}${{rk('drtg',t.team)}}</td>
      <td>${{Number(t.net_rtg).toFixed(1)}}${{rk('net_rtg',t.team)}}</td>
      <td style="padding:0 4px"><div class="opp-bar-wrap" data-opptip="${{getOppAdjMsg(t.team, t.opp_adjust)}}"><div style="position:relative;width:50px;height:14px;background:transparent;border-radius:2px"><div style="position:absolute;top:0;height:100%;border-radius:2px;${{t.opp_adjust >= 0 ? `left:50%;width:${{Math.min(Math.abs(t.opp_adjust)/0.35*50,50)}}%;background:#e74c3c` : `right:50%;width:${{Math.min(Math.abs(t.opp_adjust)/0.35*50,50)}}%;background:#3498db`}}"></div><div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:#666"></div></div></div></td>
      <td style="padding:0 4px"><div class="pace-bar-wrap" data-pacetip="${{getPaceAdjMsg(t.team, t.pace_adjust)}}"><div style="position:relative;width:50px;height:14px;background:transparent;border-radius:2px"><div style="position:absolute;top:0;height:100%;border-radius:2px;${{t.pace_adjust >= 0 ? `left:50%;width:${{Math.min(Math.abs(t.pace_adjust)/0.35*50,50)}}%;background:#e67e22` : `right:50%;width:${{Math.min(Math.abs(t.pace_adjust)/0.35*50,50)}}%;background:#3498db`}}"></div><div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:#666"></div></div></div></td>
      <td>${{Number(fs.opp_ortg).toFixed(1)}}${{rk('opp_ortg',t.team)}}</td>
      <td>${{Number(fs.opp_drtg_sos).toFixed(1)}}${{rk('opp_drtg_sos',t.team)}}</td>
      <td>${{Number(fs.sos).toFixed(1)}}${{rk('sos',t.team)}}</td>
      <td>${{Number(fs.ncsos).toFixed(1)}}${{rk('ncsos',t.team)}}</td>
      <td>${{Number(t.opp_efg_pct).toFixed(1)}}${{rk('opp_efg_pct',t.team)}}</td>
      <td>${{Number(t.dreb_pct).toFixed(1)}}${{rk('dreb_pct',t.team)}}</td>
      <td>${{Number(t.opp_tov_pct).toFixed(1)}}${{rk('opp_tov_pct',t.team)}}</td>
      <td>${{Number(t.opp_ft_rate).toFixed(1)}}${{rk('opp_ft_rate',t.team)}}</td>
    `;
    if (t.team === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
    tb.appendChild(tr);
  }});
  highlightCol(tb, defSortCol);
}}

let defSortCol = 'net_rtg';
let defSortDir = 'desc';
let defSortType = 'num';
let defSortBest = 'desc';

function doDefSort(col, type) {{
  if (col === defSortCol) {{
    defSortDir = defSortDir === 'desc' ? 'asc' : 'desc';
  }} else {{
    defSortCol = col;
    defSortType = type;
    const bd = bestDir(col);
    defSortDir = type === 'str' ? 'asc' : bd;
    defSortBest = type === 'str' ? 'asc' : bd;
  }}
  const FS_COLS2 = new Set(['gp','record','conf','opp_ortg','opp_drtg_sos','sos','ncsos','team']);
  const _fsSortPool2 = activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  activeTeamData.sort((a, b) => {{
    let sa = a, sb = b;
    if (FS_COLS2.has(col)) {{
      sa = _fsSortPool2.find(d => d.team === a.team) || a;
      sb = _fsSortPool2.find(d => d.team === b.team) || b;
    }}
    let va = sa[col], vb = sb[col];
    if (type === 'rec') {{
      va = parseWins(va); vb = parseWins(vb);
      return defSortDir === 'asc' ? va - vb : vb - va;
    }}
    if (type === 'str') {{
      va = (va || '').toLowerCase();
      vb = (vb || '').toLowerCase();
      return defSortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
    }}
    return defSortDir === 'asc' ? va - vb : vb - va;
  }});
  document.querySelectorAll('th[data-table="def"]').forEach(th => {{
    th.classList.remove('active', 'asc', 'desc');
    if (th.dataset.col === col) th.classList.add('active', defSortDir);
  }});
  renderDefense(getFilteredTeams());
}}

document.querySelectorAll('th[data-table="def"]').forEach(th => {{
  if (th.dataset.col === 'rank') return;
  th.addEventListener('click', () => doDefSort(th.dataset.col, th.dataset.type));
}});

renderDefense(getFilteredTeams());

// --- Universe Chart ---
const CONF_ABBREV = {{
  'WSC North': 'WSN', 'WSC South': 'WSS',
  'Orange Empire Athletic': 'OEA', 'Pacific Coast Athletic': 'PCA',
  'South Coast-South': 'SCS', 'South Coast-North': 'SCN',
  'Inland Empire Athletic': 'IEA', 'Coast-North': 'CN',
  'Big Eight': 'Big8', 'Coast-South': 'CS',
  'Bay Valley': 'BV', 'Central Valley': 'CV', 'Golden Valley': 'GV',
}};

const UNI_STATS = [
  {{ key: 'net_rtg', label: 'NetRtg', low: false, section: 'main' }},
  {{ key: 'ortg', label: 'ORtg', low: false, section: 'main' }},
  {{ key: 'drtg', label: 'DRtg', low: true, section: 'main' }},
  {{ key: 'tempo', label: 'Tempo', low: false, section: 'main' }},
  {{ key: 'efg_pct', label: 'eFG%', low: false, section: 'offense' }},
  {{ key: 'tov_pct', label: 'TO%', low: true, section: 'offense' }},
  {{ key: 'oreb_pct', label: 'OR%', low: false, section: 'offense' }},
  {{ key: 'ft_rate', label: 'FTR', low: false, section: 'offense' }},
  {{ key: 'ftp', label: 'FT%', low: false, section: 'offense2' }},
  {{ key: 'twop', label: '2P%', low: false, section: 'offense2' }},
  {{ key: 'tpp', label: '3P%', low: false, section: 'offense2' }},
  {{ key: 'tpa_pct', label: '3PA%', low: false, section: 'offense2' }},
  {{ key: 'ts_pct', label: 'TS%', low: false, section: 'offense2' }},
  {{ key: 'opp_efg_pct', label: 'eFG%', low: true, section: 'defense' }},
  {{ key: 'opp_tov_pct', label: 'TO%', low: false, section: 'defense' }},
  {{ key: 'dreb_pct', label: 'DR%', low: false, section: 'defense' }},
  {{ key: 'opp_ft_rate', label: 'FTR', low: true, section: 'defense' }},
  {{ key: 'opp_ftp', label: 'FT%', low: true, section: 'defense2' }},
  {{ key: 'opp_twop', label: '2P%', low: true, section: 'defense2' }},
  {{ key: 'opp_tpp', label: '3P%', low: true, section: 'defense2' }},
  {{ key: 'opp_tpa_pct', label: '3PA%', low: true, section: 'defense2' }},
  {{ key: 'opp_ts_pct', label: 'TS%', low: true, section: 'defense2' }},
];

let uniMode = 'ranks';
let uniStat = 'net_rtg';
let uniHighlightConfs = new Set();
let uniLabelTeams = new Set();
let uniHighlightRegion = null;

// Color gradient: neon green (#1) -> white (middle) -> neon red (last)
function rankToColor(rank, total) {{
  const t = (rank - 1) / Math.max(total - 1, 1);
  let r, g, b;
  if (t <= 0.5) {{
    const p = t / 0.5;
    r = Math.round(255 * p);
    g = 255;
    b = Math.round(255 * p);
  }} else {{
    const p = (t - 0.5) / 0.5;
    r = 255;
    g = Math.round(255 * (1 - p));
    b = Math.round(255 * (1 - p));
  }}
  return 'rgb(' + r + ',' + g + ',' + b + ')';
}}
function rankToStroke(rank, total) {{
  const t = (rank - 1) / Math.max(total - 1, 1);
  let r, g, b;
  if (t <= 0.5) {{
    const p = t / 0.5;
    r = Math.round(180 * p);
    g = 180;
    b = Math.round(180 * p);
  }} else {{
    const p = (t - 0.5) / 0.5;
    r = 180;
    g = Math.round(180 * (1 - p));
    b = Math.round(180 * (1 - p));
  }}
  return 'rgb(' + r + ',' + g + ',' + b + ')';
}}

function buildUniSidebar() {{
  const col = document.getElementById('uni-stat-col');
  col.innerHTML = '';
  // Header (static labels, not clickable)
  const hdr = document.createElement('div');
  hdr.className = 'uni-stat-header';
  const rH = document.createElement('span');
  rH.textContent = 'Ranks';
  rH.style.fontWeight = '700';
  const vH = document.createElement('span');
  vH.textContent = 'Values';
  vH.style.fontWeight = '700';
  hdr.appendChild(rH); hdr.appendChild(vH);
  col.appendChild(hdr);

  let lastSection = '';
  UNI_STATS.forEach(s => {{
    if (s.section !== lastSection) {{
      lastSection = s.section;
      if (s.section === 'offense') {{
        const lbl = document.createElement('div');
        lbl.className = 'uni-section-label';
        lbl.textContent = 'Offense';
        col.appendChild(lbl);
      }} else if (s.section === 'defense') {{
        const lbl = document.createElement('div');
        lbl.className = 'uni-section-label';
        lbl.textContent = 'Defense';
        col.appendChild(lbl);
      }}
    }}
    const row = document.createElement('div');
    row.className = 'uni-stat-row';
    const rSpan = document.createElement('span');
    rSpan.textContent = s.label;
    rSpan.style.cursor = 'pointer';
    rSpan.style.fontWeight = (uniStat === s.key && uniMode === 'ranks') ? '700' : '400';
    rSpan.onclick = (e) => {{
      e.stopPropagation();
      uniStat = s.key; uniMode = 'ranks';
      buildUniSidebar(); renderUniverse();
    }};
    const vSpan = document.createElement('span');
    vSpan.textContent = s.label;
    vSpan.style.cursor = 'pointer';
    vSpan.style.fontWeight = (uniStat === s.key && uniMode === 'values') ? '700' : '400';
    vSpan.onclick = (e) => {{
      e.stopPropagation();
      uniStat = s.key; uniMode = 'values';
      buildUniSidebar(); renderUniverse();
    }};
    row.appendChild(rSpan); row.appendChild(vSpan);
    col.appendChild(row);
  }});

  // Conference & Region list
  const confCol = document.getElementById('uni-conf-col');
  confCol.innerHTML = '';

  // "Conference:" header
  const confHeader = document.createElement('div');
  confHeader.className = 'uni-section-label';
  confHeader.style.marginTop = '0';
  confHeader.style.marginBottom = '3px';
  confHeader.textContent = 'Conference:';
  confCol.appendChild(confHeader);

  // Compute avg net_rtg per conference from active data, sort desc
  const confNetMap = {{}};
  ALL_CONFS.forEach(c => {{
    const members = activeTeamData.filter(t => t.conference === c && t.net_rtg != null);
    confNetMap[c] = members.length ? members.reduce((s, t) => s + t.net_rtg, 0) / members.length : null;
  }});
  const sortedConfs = [...ALL_CONFS].sort((a, b) => {{
    const av = confNetMap[a], bv = confNetMap[b];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return bv - av;
  }});

  sortedConfs.forEach(c => {{
    const div = document.createElement('div');
    div.className = 'uni-conf-item' + (uniHighlightConfs.has(c) ? ' active' : '');
    div.style.display = 'flex';
    div.style.justifyContent = 'space-between';
    div.style.gap = '6px';
    const abbr = document.createElement('span');
    abbr.textContent = CONF_ABBREV[c] || c;
    const netLbl = document.createElement('span');
    const nv = confNetMap[c];
    netLbl.textContent = nv != null ? (nv >= 0 ? '+' : '') + nv.toFixed(1) : '';
    netLbl.style.color = '#999';
    netLbl.style.fontSize = '10px';
    netLbl.style.alignSelf = 'center';
    div.appendChild(abbr);
    div.appendChild(netLbl);
    div.onclick = () => {{
      uniHighlightRegion = null;
      if (uniHighlightConfs.has(c)) {{
        uniHighlightConfs.delete(c);
      }} else {{
        uniHighlightConfs.add(c);
      }}
      uniLabelTeams.clear();
      buildUniSidebar();
      renderUniverse();
    }};
    confCol.appendChild(div);
  }});

  // "Region:" header
  const regHeader = document.createElement('div');
  regHeader.className = 'uni-section-label';
  regHeader.style.marginTop = '12px';
  regHeader.textContent = 'Region:';
  confCol.appendChild(regHeader);

  ['North', 'South'].forEach(region => {{
    const div = document.createElement('div');
    div.className = 'uni-conf-item' + (uniHighlightRegion === region ? ' active' : '');
    div.textContent = region;
    div.onclick = () => {{
      if (uniHighlightRegion === region) {{
        uniHighlightRegion = null;
        uniHighlightConfs.clear();
      }} else {{
        uniHighlightRegion = region;
        uniHighlightConfs.clear();
        ALL_CONFS.forEach(c => {{
          if (CONF_SECTIONS[c] === region) uniHighlightConfs.add(c);
        }});
      }}
      uniLabelTeams.clear();
      buildUniSidebar();
      renderUniverse();
    }};
    confCol.appendChild(div);
  }});

  const resetDiv = document.createElement('div');
  resetDiv.className = 'uni-reset';
  resetDiv.textContent = 'Reset';
  resetDiv.style.display = (uniHighlightConfs.size > 0 || uniHighlightRegion) ? 'block' : 'none';
  resetDiv.onclick = () => {{
    uniHighlightConfs.clear();
    uniHighlightRegion = null;
    uniLabelTeams.clear();
    buildUniSidebar();
    renderUniverse();
  }};
  confCol.appendChild(resetDiv);
}}

function computeUniRanks(data, key, lowIsBetter) {{
  const valid = data.filter(t => t[key] != null);
  valid.sort((a, b) => lowIsBetter ? a[key] - b[key] : b[key] - a[key]);
  const ranks = {{}};
  valid.forEach((t, i) => {{ ranks[t.team] = i + 1; }});
  data.forEach(t => {{ if (!(t.team in ranks)) ranks[t.team] = data.length; }});
  return ranks;
}}

function renderUniverse() {{
  const svg = document.getElementById('universe-svg');
  if (!svg) return;
  svg.innerHTML = '';

  const data = activeTeamData.filter(t => t.ortg > 0 && t.drtg > 0);
  if (data.length === 0) return;

  const W = 750, H = 700;
  const margin = {{ top: 25, right: 20, bottom: 25, left: 90 }};
  const plotW = W - margin.left - margin.right;
  const plotH = H - margin.top - margin.bottom;

  // Averages
  const avgOrtg = data.reduce((s, t) => s + t.ortg, 0) / data.length;
  const avgDrtg = data.reduce((s, t) => s + t.drtg, 0) / data.length;

  // Compute plot coordinates
  const points = data.map(t => ({{
    ...t,
    ux: (t.ortg - avgOrtg) - (avgDrtg - t.drtg),
    uy: t.net_rtg
  }}));

  const xs = points.map(p => p.ux);
  const ys = points.map(p => p.uy);
  const xRange = Math.max(Math.abs(Math.min(...xs)), Math.abs(Math.max(...xs))) * 1.2;
  const yPad = (Math.max(...ys) - Math.min(...ys)) * 0.06;
  const yGridMin = Math.floor((Math.min(...ys) - yPad) / 10) * 10;
  const yGridMax = Math.ceil((Math.max(...ys) + yPad) / 10) * 10;

  const scaleX = v => margin.left + (v + xRange) / (2 * xRange) * plotW;
  const scaleY = v => margin.top + (yGridMax - v) / (yGridMax - yGridMin) * plotH;

  const ns = 'http://www.w3.org/2000/svg';

  // Horizontal grid lines
  for (let gy = yGridMin; gy <= yGridMax; gy += 10) {{
    const y = scaleY(gy);
    const line = document.createElementNS(ns, 'line');
    line.setAttribute('x1', margin.left);
    line.setAttribute('x2', W - margin.right);
    line.setAttribute('y1', y); line.setAttribute('y2', y);
    line.setAttribute('stroke', gy === 0 ? '#999' : '#ddd');
    line.setAttribute('stroke-width', gy === 0 ? '1.5' : '0.5');
    svg.appendChild(line);

    const txt = document.createElementNS(ns, 'text');
    txt.setAttribute('x', margin.left - 6);
    txt.setAttribute('y', y + 4);
    txt.setAttribute('text-anchor', 'end');
    txt.setAttribute('font-size', '11');
    txt.setAttribute('fill', '#666');
    txt.textContent = 'NetRtg=' + gy;
    svg.appendChild(txt);
  }}

  // Vertical center line
  const cx = scaleX(0);
  const cLine = document.createElementNS(ns, 'line');
  cLine.setAttribute('x1', cx); cLine.setAttribute('x2', cx);
  cLine.setAttribute('y1', margin.top);
  cLine.setAttribute('y2', H - margin.bottom);
  cLine.setAttribute('stroke', '#c0392b');
  cLine.setAttribute('stroke-width', '1');
  cLine.setAttribute('stroke-dasharray', '5,3');
  svg.appendChild(cLine);

  // Ranks
  const statInfo = UNI_STATS.find(s => s.key === uniStat);
  const ranks = computeUniRanks(data, uniStat, statInfo ? statInfo.low : false);

  const R = 15;
  const GAP_PAD = 0; // line gaps cut exactly to bubble edge

  // Conference avg NetRtg lines — rendered BEFORE bubbles so dots sit on top
  if (uniHighlightConfs.size > 0) {{
    uniHighlightConfs.forEach(conf => {{
      const confTeams = points.filter(p => p.conference === conf);
      if (confTeams.length === 0) return;
      const avgNet = confTeams.reduce((s, p) => s + p.net_rtg, 0) / confTeams.length;
      const ly = scaleY(avgNet);
      const x1 = margin.left, x2 = W - margin.right;

      // Compute gap intervals from ALL highlighted bubbles near this line
      const gaps = [];
      points.forEach(p => {{
        if (!(uniHighlightConfs.has(p.conference))) return;
        const px = scaleX(p.ux);
        const py = scaleY(p.uy);
        const dy = Math.abs(py - ly);
        const r = R + GAP_PAD;
        if (dy < r) {{
          const hw = Math.sqrt(r * r - dy * dy);
          gaps.push([px - hw, px + hw]);
        }}
      }});

      // Merge overlapping gaps
      gaps.sort((a, b) => a[0] - b[0]);
      const merged = [];
      for (const g of gaps) {{
        if (merged.length && g[0] <= merged[merged.length-1][1]) {{
          merged[merged.length-1][1] = Math.max(merged[merged.length-1][1], g[1]);
        }} else {{
          merged.push([...g]);
        }}
      }}

      // Draw line segments between gaps
      const drawSeg = (sx, ex) => {{
        if (ex <= sx) return;
        const seg = document.createElementNS(ns, 'line');
        seg.setAttribute('x1', sx); seg.setAttribute('x2', ex);
        seg.setAttribute('y1', ly); seg.setAttribute('y2', ly);
        seg.setAttribute('stroke', '#27ae60');
        seg.setAttribute('stroke-width', '1.5');
        svg.appendChild(seg);
      }};

      let cur = x1;
      for (const [gx1, gx2] of merged) {{
        drawSeg(cur, Math.max(cur, gx1));
        cur = Math.max(cur, gx2);
      }}
      drawSeg(cur, x2);
    }});
  }}

  // Sort so highlighted bubbles render on top
  const sorted = [...points].sort((a, b) => {{
    const aH = uniHighlightConfs.size === 0 || uniHighlightConfs.has(a.conference);
    const bH = uniHighlightConfs.size === 0 || uniHighlightConfs.has(b.conference);
    return (aH ? 1 : 0) - (bH ? 1 : 0);
  }});

  sorted.forEach(p => {{
    const px = scaleX(p.ux);
    const py = scaleY(p.uy);
    const highlighted = uniHighlightConfs.size === 0 || uniHighlightConfs.has(p.conference);
    const dimmed = !highlighted;

    const g = document.createElementNS(ns, 'g');
    g.style.cursor = dimmed ? 'default' : 'pointer';

    const circle = document.createElementNS(ns, 'circle');
    circle.setAttribute('cx', px); circle.setAttribute('cy', py);
    circle.setAttribute('r', R);
    circle.setAttribute('opacity', '0.75');
    if (dimmed) {{
      circle.setAttribute('fill', '#e0e0e0');
      circle.setAttribute('stroke', '#ccc');
      circle.setAttribute('opacity', '0.5');
    }} else {{
      const rk = ranks[p.team] || data.length;
      circle.setAttribute('fill', rankToColor(rk, data.length));
      if (p.team === 'Moorpark') {{
        circle.setAttribute('stroke', '#d4a017');
        circle.setAttribute('stroke-width', '3');
      }} else {{
        circle.setAttribute('stroke', rankToStroke(rk, data.length));
      }}
    }}
    circle.setAttribute('stroke-width', '1.5');
    g.appendChild(circle);

    // Bubble text
    const txt = document.createElementNS(ns, 'text');
    txt.setAttribute('x', px); txt.setAttribute('y', py + 4);
    txt.setAttribute('text-anchor', 'middle');
    txt.setAttribute('font-size', uniMode === 'values' ? '9' : '10');
    txt.setAttribute('font-weight', '700');
    txt.setAttribute('fill', dimmed ? '#aaa' : '#000');
    txt.setAttribute('pointer-events', 'none');

    let displayVal;
    if (uniMode === 'ranks') {{
      displayVal = ranks[p.team] || '';
    }} else {{
      const v = p[uniStat];
      if (v == null) displayVal = '';
      else {{
        const s = v.toFixed(1);
        displayVal = s.length > 5 ? Math.round(v).toString() : s;
      }}
    }}
    txt.textContent = displayVal;
    g.appendChild(txt);

    // Click to show/hide team name
    if (!dimmed) {{
      g.addEventListener('click', () => {{
        if (uniLabelTeams.has(p.team)) {{
          uniLabelTeams.delete(p.team);
        }} else {{
          uniLabelTeams.add(p.team);
        }}
        renderUniverse();
      }});
    }}
    svg.appendChild(g);

    // Show label if team is clicked, conference filter is active, or region selected
    const showLabel = highlighted && (uniLabelTeams.has(p.team) || uniHighlightConfs.size > 0 || uniHighlightRegion);
    if (showLabel) {{
      const label = document.createElementNS(ns, 'text');
      label.setAttribute('x', px); label.setAttribute('y', py - R - 4);
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('font-size', '11');
      label.setAttribute('font-weight', '700');
      label.setAttribute('fill', '#000');
      label.setAttribute('style', 'cursor:pointer');
      label.textContent = p.team;
      label.addEventListener('click', (e) => {{
        e.stopPropagation();
        showTeamDetail(p.team);
      }});
      svg.appendChild(label);
    }}
  }});
}}

buildUniSidebar();

// --- Team Search ---
const allTeamNames = TEAM_DATA.map(d => d.team).sort();
function onTeamSearch() {{
  const input = document.getElementById('team-search-input');
  const dropdown = document.getElementById('team-search-dropdown');
  const query = input.value.trim().toLowerCase();
  if (!query) {{ dropdown.style.display = 'none'; return; }}
  const matches = allTeamNames.filter(name => name.toLowerCase().includes(query));
  if (matches.length === 0) {{ dropdown.style.display = 'none'; return; }}
  dropdown.innerHTML = matches.map(name =>
    `<div onclick="selectSearchTeam('${{name}}')">${{name}}</div>`
  ).join('');
  dropdown.style.display = 'block';
}}
function selectSearchTeam(name) {{
  document.getElementById('team-search-input').value = '';
  document.getElementById('team-search-dropdown').style.display = 'none';
  showTeamDetail(name);
}}
document.addEventListener('click', function(e) {{
  if (!e.target.closest('.team-search-wrap')) {{
    document.getElementById('team-search-dropdown').style.display = 'none';
  }}
}});

// --- Team Detail View ---
let prevView = 'individual';
let currentTeam = null;

function showTeamDetail(teamName) {{
  // Find team data
  const t = activeTeamData.find(d => d.team === teamName);
  if (!t) {{
    // Fallback to full-season data if team not found in conference mode
    const tf = TEAM_DATA.find(d => d.team === teamName);
    if (!tf) return;
    showTeamDetail_inner(tf, teamName);
    return;
  }}
  showTeamDetail_inner(t, teamName);
}}

function showTeamDetail_inner(t, teamName) {{
  // Remember current view to return to
  if (document.getElementById('individual-view').style.display !== 'none') prevView = 'individual';
  else if (document.getElementById('team-view').style.display !== 'none' || document.getElementById('team-defense-view').style.display !== 'none') prevView = 'team';
  else if (document.getElementById('universe-view').style.display !== 'none') prevView = 'universe';
  else if (document.getElementById('storylines-view').style.display !== 'none') prevView = 'storylines';
  else if (document.getElementById('fanmatch-view').style.display !== 'none') prevView = 'fanmatch';

  // Hide everything
  document.getElementById('individual-view').style.display = 'none';
  document.getElementById('team-view').style.display = 'none';
  document.getElementById('team-defense-view').style.display = 'none';
  document.getElementById('universe-view').style.display = 'none';
  document.getElementById('storylines-view').style.display = 'none';
  document.getElementById('fanmatch-view').style.display = 'none';
  document.getElementById('sub-toggle').style.display = 'none';
  document.querySelector('.filter-bar').style.display = 'none';
  document.getElementById('page-title').style.display = 'none';
  document.getElementById('page-subtitle').style.display = 'none';
  document.getElementById('page-info').style.display = 'none';
  document.getElementById('season-toggle').style.display = 'none';
  document.querySelectorAll('.top-bar .tab').forEach(b => b.classList.remove('active'));

  // Show team detail
  currentTeam = t;
  const tdDiv = document.getElementById('team-detail-view');
  tdDiv.style.display = 'block';
  tdDiv.dataset.team = teamName;
  document.getElementById('team-detail-content').innerHTML = buildTeamDetail(t);
  document.getElementById('season-toggle').style.display = 'flex';
  window.scrollTo(0, 0);
}}

function toSlug(name) {{
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
}}

function teamPageHref(teamName) {{
  return `team_pages/${{toSlug(teamName)}}.html`;
}}

function teamPageLink(teamName, style = 'color:inherit;text-decoration:none', label = null) {{
  const text = label || teamName;
  return `<a href="#" onclick="showTeamDetail('${{teamName}}');return false" style="${{style}}">${{text}}</a>`;
}}

function pearsonCorrJS(xs, ys) {{
  const n = xs.length;
  if (n < 4) return null;
  const mx = xs.reduce((a,b)=>a+b,0)/n, my = ys.reduce((a,b)=>a+b,0)/n;
  let num=0, dx2=0, dy2=0;
  for (let i=0;i<n;i++){{const a=xs[i]-mx,b=ys[i]-my;num+=a*b;dx2+=a*a;dy2+=b*b;}}
  return (dx2>0&&dy2>0) ? num/Math.sqrt(dx2*dy2) : null;
}}

function corrTipText(r100, label, isOrtg) {{
  const a = Math.abs(r100);
  if (a < 10) return label + ': essentially no relationship with ' + (isOrtg?'offensive':'defensive') + ' efficiency this season';
  const strength = a>=80?'very strong':a>=60?'strong':a>=45?'moderate':a>=25?'mild':'weak';
  const dir = isOrtg ? (r100>=0?'positive':'negative') : (r100<=0?'positive':'negative');
  if (isOrtg) {{
    const outcome = r100>=0 ? 'offensive efficiency tends to be high too' : 'offensive efficiency tends to suffer';
    return label + ': ' + strength + ' ' + dir + ' link — when this is high, ' + outcome;
  }} else {{
    const outcome = r100<=0 ? 'defensive efficiency tends to improve (DRTG drops)' : 'defensive efficiency tends to worsen (DRTG rises)';
    return label + ': ' + strength + ' ' + dir + ' link — when this is high, ' + outcome;
  }}
}}

let gamePlanReturnTeam = null;

function showGamePlan(teamName) {{
  gamePlanReturnTeam = teamName;
  const t = (activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA).find(d => d.team === teamName)
         || TEAM_DATA.find(d => d.team === teamName) || TEAM_DATA_2024.find(d => d.team === teamName) || TEAM_DATA_2023.find(d => d.team === teamName) || TEAM_DATA_2022.find(d => d.team === teamName);
  if (!t) return;
  const content = document.getElementById('gameplan-content');
  document.getElementById('team-detail-view').style.display = 'none';
  document.getElementById('gameplan-view').style.display = 'block';
  window.scrollTo(0, 0);
  const netRtgRanks = {{}};
  const validT = (activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : TEAM_DATA).filter(d => d.ortg > 0).sort((a,b) => b.net_rtg - a.net_rtg);
  validT.forEach((d,i) => {{ netRtgRanks[d.team] = i+1; }});
  const FOUR_FACTORS = ['o_efg','o_tov','o_or','o_ftr','d_efg','d_tov','d_or','d_ftr'];
  const STAT_LABELS = {{pace:'Pace',ortg:'Off Eff',o_efg:'Off eFG%',o_tov:'Off TO%',o_or:'Off OR%',o_ftr:'Off FTR',o_2p:'Off 2P%',o_3p:'Off 3P%',drtg:'Def Eff',d_efg:'Def eFG%',d_tov:'Def TO%',d_or:'Def OR%',d_ftr:'Def FTR',d_2p:'Def 2P%',d_3p:'Def 3P%'}};
  const COL_KEYS = ['pace','ortg','o_efg','o_tov','o_or','o_ftr','o_2p','o_3p','drtg','d_efg','d_tov','d_or','d_ftr','d_2p','d_3p'];
  const colData = {{}}; COL_KEYS.forEach(k => colData[k]=[]);
  const ortgVals=[], drtgVals=[];
  const ff = (v) => (typeof v === 'number') ? v.toFixed(1) : '—';
  let rowsHtml = '';
  const games = t.game_ratings || [];
  games.forEach(gr => {{
    const opp = gr.canonical_opponent || gr.opponent || '';
    const slug = toSlug(opp);
    const rk = netRtgRanks[opp] || '';
    const isConf = gr.is_conference;
    const oppLink = `<a href="#" onclick="showTeamDetail('${{opp}}');return false" style="color:#000;text-decoration:none;font-weight:600">${{opp}}</a>${{isConf?' <span style="color:#888">*</span>':''}}`;
    const rowCls = gr.result==='W' ? 'gp-win' : (gr.result==='L' ? 'gp-loss' : '');
    const resTxt = (gr.result==='W'||gr.result==='L') ? `${{gr.result}}, ${{gr.team_score}}-${{gr.opponent_score}}` : `${{gr.team_score}}-${{gr.opponent_score}}`;
    const winLabel = gr.result==='W' ? '<span style="font-weight:700;color:#2e7d32">W</span>' : (gr.result==='L' ? '<span style="font-weight:700;color:#c62828">L</span>' : '');
    const resDisplay = (gr.result==='W'||gr.result==='L') ? `${{winLabel}}, ${{gr.team_score}}-${{gr.opponent_score}}` : resTxt;
    const hasFf = gr.o_efg !== undefined;
    let cells = '';
    if (hasFf) {{
      cells = `<td style="text-align:center">${{ff(gr.pace)}}</td><td style="text-align:center;font-weight:700">${{ff(gr.ortg)}}</td><td style="text-align:center">${{ff(gr.o_efg)}}</td><td style="text-align:center">${{ff(gr.o_tov)}}</td><td style="text-align:center">${{ff(gr.o_or)}}</td><td style="text-align:center">${{ff(gr.o_ftr)}}</td><td style="text-align:center">${{ff(gr.o_2p)}}</td><td style="text-align:center">${{ff(gr.o_3p)}}</td><td style="text-align:center;font-weight:700">${{ff(gr.drtg)}}</td><td style="text-align:center">${{ff(gr.d_efg)}}</td><td style="text-align:center">${{ff(gr.d_tov)}}</td><td style="text-align:center">${{ff(gr.d_or)}}</td><td style="text-align:center">${{ff(gr.d_ftr)}}</td><td style="text-align:center">${{ff(gr.d_2p)}}</td><td style="text-align:center">${{ff(gr.d_3p)}}</td>`;
      COL_KEYS.forEach(k => {{ if (gr[k] !== undefined) colData[k].push(gr[k]); }});
      ortgVals.push(gr.ortg); drtgVals.push(gr.drtg);
    }} else {{ cells = '<td></td>'.repeat(15); }}
    rowsHtml += `<tr class="${{rowCls}}"><td style="text-align:left;white-space:nowrap;font-size:0.77rem;width:1%">${{gr.date||''}}</td><td style="text-align:center">${{rk}}</td><td style="text-align:left">${{oppLink}}</td><td style="text-align:center">${{resDisplay}}</td>${{cells}}</tr>`;
  }});
  function corrCell(r, key, isOrtg) {{
    if (!FOUR_FACTORS.includes(key)) return '<td></td>';
    if (r === null) return '<td style="text-align:center;color:#aaa">—</td>';
    const v = Math.round(r * 100);
    const sign = v >= 0 ? '+' : '';
    const tip = corrTipText(v, STAT_LABELS[key], isOrtg).replace(/"/g,'&quot;');
    return `<td style="text-align:center;font-weight:700;cursor:help" class="gp-corr-cell" data-tip="${{tip}}">${{sign}}${{v}}</td>`;
  }}
  let ortgRow = '<td colspan="4" style="text-align:right;font-style:italic;color:#555;padding-right:10px;white-space:nowrap;font-weight:600">Correlations (R×100) to offensive efficiency:</td>';
  let drtgRow = '<td colspan="4" style="text-align:right;font-style:italic;color:#555;padding-right:10px;white-space:nowrap;font-weight:600">Correlations (R×100) to defensive efficiency:</td>';
  COL_KEYS.forEach(k => {{
    const vals = colData[k];
    const r_o = k==='ortg' ? (ortgVals.length>=4?1.0:null) : pearsonCorrJS(vals, ortgVals);
    const r_d = k==='drtg' ? (drtgVals.length>=4?1.0:null) : pearsonCorrJS(vals, drtgVals);
    ortgRow += corrCell(r_o, k, true);
    drtgRow += corrCell(r_d, k, false);
  }});
  content.innerHTML = `<style>#gameplan-content table{{width:100%;border-collapse:collapse;font-size:0.78rem;white-space:nowrap}}#gameplan-content th{{background:#1a1a2e;color:#fff;padding:5px 7px;text-align:center;font-size:0.73rem;border-bottom:2px solid #333}}#gameplan-content th.gp-off{{background:#1a3a5c}}#gameplan-content th.gp-def{{background:#3a1a1a}}#gameplan-content td{{padding:4px 7px;border-bottom:1px solid #eee}}#gameplan-content tr.gp-win td{{background:rgb(0,255,0);color:#000}}#gameplan-content tr.gp-loss td{{background:rgb(255,0,0);color:#000}}#gameplan-content tr.gp-win a,#gameplan-content tr.gp-loss a{{color:#000}}#gameplan-content tr.gp-win:hover td{{background:rgb(0,230,0)}}#gameplan-content tr.gp-loss:hover td{{background:rgb(230,0,0)}}#gameplan-content tr:not(.gp-win):not(.gp-loss):hover td{{background:#f0f0f0}}#gameplan-content tfoot tr td{{background:#f0f0f0;border-top:2px solid #bbb;font-size:0.75rem}}.gp-corr-cell{{position:relative}}.gp-corr-cell:hover::after{{content:attr(data-tip);position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);background:#1a1a2e;color:#fff;padding:7px 10px;border-radius:4px;font-size:0.72rem;white-space:normal;width:230px;z-index:999;pointer-events:none;box-shadow:0 2px 8px rgba(0,0,0,0.35);line-height:1.45}}</style><div style="background:#1a1a2e;border-radius:8px;padding:16px 20px;margin-bottom:16px;text-align:center"><div style="color:#4fc3f7;font-size:1.1rem;font-weight:700">#${{netRtgRanks[teamName]||'—'}} NET RTG</div><h2 style="color:#B9D9EB;font-size:1.6rem;margin:4px 0">${{teamName}} — Game Plan</h2><div style="color:#ccc;font-size:0.9rem">${{t.conference}} · ${{t.region}} Region</div><div style="color:#fff;font-size:1.1rem;font-weight:700;margin-top:4px">${{t.record}} Overall &nbsp;|&nbsp; ${{t.conf}} Conference</div></div><div style="background:#fff;border-radius:8px;padding:16px;border:1px solid #ccc;overflow-x:auto"><div style="font-size:1rem;font-weight:700;text-align:center;margin-bottom:10px;color:#000;border-bottom:2px solid #333;padding-bottom:6px">Game Plan</div><table><thead><tr><th rowspan="2" style="text-align:left">Date</th><th rowspan="2">Rk</th><th rowspan="2" style="text-align:left">Opponent</th><th rowspan="2">Result</th><th rowspan="2">Pace</th><th colspan="7" class="gp-off">Offense</th><th colspan="7" class="gp-def">Defense</th></tr><tr><th class="gp-off">Eff</th><th class="gp-off">eFG%</th><th class="gp-off">TO%</th><th class="gp-off">OR%</th><th class="gp-off">FTR</th><th class="gp-off">2P%</th><th class="gp-off">3P%</th><th class="gp-def">Eff</th><th class="gp-def">eFG%</th><th class="gp-def">TO%</th><th class="gp-def">OR%</th><th class="gp-def">FTR</th><th class="gp-def">2P%</th><th class="gp-def">3P%</th></tr></thead><tbody>${{rowsHtml}}</tbody><tfoot><tr>${{ortgRow}}</tr><tr>${{drtgRow}}</tr></tfoot></table><div style="font-size:0.72rem;color:#888;margin-top:8px">Rk = opponent's current NET RTG rank &nbsp;|&nbsp; * = conference game &nbsp;|&nbsp; Pace = est. possessions per 40 min &nbsp;|&nbsp; Hover correlation values for interpretation</div></div>`;
}}

function closeGamePlan() {{
  document.getElementById('gameplan-view').style.display = 'none';
  if (gamePlanReturnTeam) {{ showTeamDetail(gamePlanReturnTeam); }}
}}

function tdColorCell(value, rank, total, fmt, lowIsBetter) {{
  const tv = (rank - 1) / Math.max(total - 1, 1);
  let r, g, b;
  if (tv <= 0.5) {{
    const p = tv / 0.5;
    r = Math.round(255 * p); g = 255; b = Math.round(255 * p);
  }} else {{
    const p = (tv - 0.5) / 0.5;
    r = 255; g = Math.round(255 * (1 - p)); b = Math.round(255 * (1 - p));
  }}
  const bg = `rgb(${{r}},${{g}},${{b}})`;
  const formatted = typeof value === 'number' ? value.toFixed(fmt) : value;
  return `<td style="background:${{bg}};text-align:center;font-weight:700">${{formatted}} <sub>${{rank}}</sub></td>`;
}}

function tdRank(key, lowIsBetter) {{
  // Sort activeTeamData to find rank
  const valid = activeTeamData.filter(d => d.ortg > 0 && d[key] != null);
  valid.sort((a, b) => lowIsBetter ? a[key] - b[key] : b[key] - a[key]);
  const idx = valid.findIndex(d => d.team === arguments[2]);
  return idx >= 0 ? idx + 1 : valid.length;
}}

function computeRanks(teamName) {{
  const valid = activeTeamData.filter(d => d.ortg > 0);
  const total = valid.length;
  const rankFor = (key, low) => {{
    const sorted = [...valid].sort((a, b) => low ? a[key] - b[key] : b[key] - a[key]);
    const idx = sorted.findIndex(d => d.team === teamName);
    return idx >= 0 ? idx + 1 : total;
  }};
  // Always rank SOS fields against full-season data for active season
  const _fsData = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  const fsValid = _fsData.filter(d => d.ortg > 0);
  const fsTotal = fsValid.length;
  const rankForFS = (key, low) => {{
    const sorted = [...fsValid].sort((a, b) => low ? a[key] - b[key] : b[key] - a[key]);
    const idx = sorted.findIndex(d => d.team === teamName);
    return idx >= 0 ? idx + 1 : fsTotal;
  }};
  // Rank by computed shooting pct from totals
  const rankShoot = (numKey, denKey, src, low) => {{
    const vals = valid.map(d => {{
      const s = src === 'opp' ? d.opp_totals : d.totals;
      const den = s[denKey] || 1;
      return {{ team: d.team, v: s[numKey] / den * 100 }};
    }});
    vals.sort((a, b) => low ? a.v - b.v : b.v - a.v);
    const idx = vals.findIndex(d => d.team === teamName);
    return idx >= 0 ? idx + 1 : total;
  }};
  return {{
    total,
    ortg: rankFor('ortg', false),
    drtg: rankFor('drtg', true),
    tempo: rankFor('tempo', false),
    net_rtg: rankFor('net_rtg', false),
    efg_pct: rankFor('efg_pct', false),
    tov_pct: rankFor('tov_pct', true),
    oreb_pct: rankFor('oreb_pct', false),
    ft_rate: rankFor('ft_rate', false),
    ts_pct: rankFor('ts_pct', false),
    opp_efg_pct: rankFor('opp_efg_pct', true),
    dreb_pct: rankFor('dreb_pct', false),
    opp_tov_pct: rankFor('opp_tov_pct', false),
    opp_ft_rate: rankFor('opp_ft_rate', true),
    opp_ts_pct: rankFor('opp_ts_pct', true),
    sos: rankForFS('sos', false),
    ncsos: rankForFS('ncsos', false),
    fg_pct: rankShoot('FGM', 'FGA', 'team', false),
    opp_fg_pct: rankShoot('FGM', 'FGA', 'opp', true),
    two_pct: rankFor('twop', false),
    opp_two_pct: rankFor('opp_twop', true),
    three_pct: rankFor('tpp', false),
    opp_three_pct: rankFor('opp_tpp', true),
    ft_pct: rankShoot('FTM', 'FTA', 'team', false),
    opp_ft_pct: rankShoot('FTM', 'FTA', 'opp', true),
    tpa_rate: rankFor('tpa_pct', false),
    opp_tpa_rate: rankFor('opp_tpa_pct', false),
    blk_pct: (() => {{
      const vals = valid.map(d => {{
        const ofa = (d.opp_totals.FGA - d.opp_totals['3PA']) || 1;
        return {{ team: d.team, v: d.totals.BLK / ofa * 100 }};
      }});
      vals.sort((a, b) => b.v - a.v);
      const idx = vals.findIndex(d => d.team === teamName);
      return idx >= 0 ? idx + 1 : total;
    }})(),
    opp_blk_pct: (() => {{
      const vals = valid.map(d => {{
        const fa = (d.totals.FGA - d.totals['3PA']) || 1;
        return {{ team: d.team, v: d.opp_totals.BLK / fa * 100 }};
      }});
      vals.sort((a, b) => a.v - b.v);
      const idx = vals.findIndex(d => d.team === teamName);
      return idx >= 0 ? idx + 1 : total;
    }})(),
    stl_pct: (() => {{
      const vals = valid.map(d => {{
        const tp = (d.possessions || 1) * d.gp;
        return {{ team: d.team, v: d.totals.STL / tp * 100 }};
      }});
      vals.sort((a, b) => b.v - a.v);
      const idx = vals.findIndex(d => d.team === teamName);
      return idx >= 0 ? idx + 1 : total;
    }})(),
    opp_stl_pct: (() => {{
      const vals = valid.map(d => {{
        const tp = (d.possessions || 1) * d.gp;
        return {{ team: d.team, v: d.opp_totals.STL / tp * 100 }};
      }});
      vals.sort((a, b) => a.v - b.v);
      const idx = vals.findIndex(d => d.team === teamName);
      return idx >= 0 ? idx + 1 : total;
    }})(),
    opp_ortg: rankForFS('opp_ortg', false),
    opp_drtg_sos: rankForFS('opp_drtg_sos', true),
    shot_dist_2pa: (() => {{
      const vals = valid.map(d => {{
        const base = (d.totals.FGA + 0.475 * d.totals.FTA) || 1;
        return {{ team: d.team, v: (d.totals.FGA - d.totals['3PA']) / base * 100 }};
      }});
      vals.sort((a, b) => b.v - a.v);
      const idx = vals.findIndex(d => d.team === teamName);
      return idx >= 0 ? idx + 1 : total;
    }})(),
    opp_shot_dist_2pa: (() => {{
      const vals = valid.map(d => {{
        const base = (d.opp_totals.FGA + 0.475 * d.opp_totals.FTA) || 1;
        return {{ team: d.team, v: (d.opp_totals.FGA - d.opp_totals['3PA']) / base * 100 }};
      }});
      vals.sort((a, b) => b.v - a.v);
      const idx = vals.findIndex(d => d.team === teamName);
      return idx >= 0 ? idx + 1 : total;
    }})(),
    shot_dist_3pa: (() => {{
      const vals = valid.map(d => {{
        const base = (d.totals.FGA + 0.475 * d.totals.FTA) || 1;
        return {{ team: d.team, v: d.totals['3PA'] / base * 100 }};
      }});
      vals.sort((a, b) => b.v - a.v);
      const idx = vals.findIndex(d => d.team === teamName);
      return idx >= 0 ? idx + 1 : total;
    }})(),
    opp_shot_dist_3pa: (() => {{
      const vals = valid.map(d => {{
        const base = (d.opp_totals.FGA + 0.475 * d.opp_totals.FTA) || 1;
        return {{ team: d.team, v: d.opp_totals['3PA'] / base * 100 }};
      }});
      vals.sort((a, b) => b.v - a.v);
      const idx = vals.findIndex(d => d.team === teamName);
      return idx >= 0 ? idx + 1 : total;
    }})(),
    shot_dist_fta: (() => {{
      const vals = valid.map(d => {{
        const base = (d.totals.FGA + 0.475 * d.totals.FTA) || 1;
        return {{ team: d.team, v: 0.475 * d.totals.FTA / base * 100 }};
      }});
      vals.sort((a, b) => b.v - a.v);
      const idx = vals.findIndex(d => d.team === teamName);
      return idx >= 0 ? idx + 1 : total;
    }})(),
    opp_shot_dist_fta: (() => {{
      const vals = valid.map(d => {{
        const base = (d.opp_totals.FGA + 0.475 * d.opp_totals.FTA) || 1;
        return {{ team: d.team, v: 0.475 * d.opp_totals.FTA / base * 100 }};
      }});
      vals.sort((a, b) => a.v - b.v);
      const idx = vals.findIndex(d => d.team === teamName);
      return idx >= 0 ? idx + 1 : total;
    }})(),
  }};
}}

function buildTeamDetail(t) {{
  const ranks = computeRanks(t.team);
  const total = ranks.total;

  // Full-season data for record and SOS (use active season's full data)
  const _fsSource = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  const fs = _fsSource.find(d => d.team === t.team) || t;

  // Compute shooting stats from totals
  const tot = t.totals;
  const oTot = t.opp_totals;
  const fgPct = (tot.FGA > 0) ? (tot.FGM / tot.FGA * 100).toFixed(1) : '0.0';
  const twoPct = ((tot.FGA - tot['3PA']) > 0) ? ((tot.FGM - tot['3PM']) / (tot.FGA - tot['3PA']) * 100).toFixed(1) : '0.0';
  const tpPct = (tot['3PA'] > 0) ? (tot['3PM'] / tot['3PA'] * 100).toFixed(1) : '0.0';
  const ftPct = (tot.FTA > 0) ? (tot.FTM / tot.FTA * 100).toFixed(1) : '0.0';
  const tpaRate = (tot.FGA > 0) ? (tot['3PA'] / tot.FGA * 100).toFixed(1) : '0.0';
  const poss = t.possessions || 1;
  const totalPoss = poss * t.gp;
  const stlPct = (totalPoss > 0) ? (tot.STL / totalPoss * 100).toFixed(1) : '0.0';
  const blkPct = ((oTot.FGA - oTot['3PA']) > 0) ? (tot.BLK / (oTot.FGA - oTot['3PA']) * 100).toFixed(1) : '0.0';

  const oFgPct = (oTot.FGA > 0) ? (oTot.FGM / oTot.FGA * 100).toFixed(1) : '0.0';
  const oTwoPct = ((oTot.FGA - oTot['3PA']) > 0) ? ((oTot.FGM - oTot['3PM']) / (oTot.FGA - oTot['3PA']) * 100).toFixed(1) : '0.0';
  const oTpPct = (oTot['3PA'] > 0) ? (oTot['3PM'] / oTot['3PA'] * 100).toFixed(1) : '0.0';
  const oFtPct = (oTot.FTA > 0) ? (oTot.FTM / oTot.FTA * 100).toFixed(1) : '0.0';
  const oTpaRate = (oTot.FGA > 0) ? (oTot['3PA'] / oTot.FGA * 100).toFixed(1) : '0.0';
  const oStlPct = (totalPoss > 0) ? (oTot.STL / totalPoss * 100).toFixed(1) : '0.0';
  const oBlkPct = ((tot.FGA - tot['3PA']) > 0) ? (oTot.BLK / (tot.FGA - tot['3PA']) * 100).toFixed(1) : '0.0';
  const shotBase = (tot.FGA + 0.475 * tot.FTA) || 1;
  const dist2pa = ((tot.FGA - tot['3PA']) / shotBase * 100).toFixed(1);
  const dist3pa = (tot['3PA'] / shotBase * 100).toFixed(1);
  const distFta = (0.475 * tot.FTA / shotBase * 100).toFixed(1);
  const oShotBase = (oTot.FGA + 0.475 * oTot.FTA) || 1;
  const oDist2pa = ((oTot.FGA - oTot['3PA']) / oShotBase * 100).toFixed(1);
  const oDist3pa = (oTot['3PA'] / oShotBase * 100).toFixed(1);
  const oDistFta = (0.475 * oTot.FTA / oShotBase * 100).toFixed(1);

  function srRow(label, offVal, defVal, avgVal, offRank, defRank, offTotals, defTotals, offLow, defLow) {{
    const offCell = offRank != null
      ? tdColorCell(offVal, offRank, total, 1, offLow)
      : `<td style="text-align:center">${{typeof offVal === 'number' ? offVal.toFixed(1) : offVal}}</td>`;
    const defCell = (defRank != null && defVal !== '')
      ? tdColorCell(defVal, defRank, total, 1, defLow)
      : (defVal !== '' ? `<td style="text-align:center">${{typeof defVal === 'number' ? defVal.toFixed(1) : defVal}}</td>` : '<td></td>');
    return `<tr>
      <td style="text-align:right;font-weight:600;padding-right:12px">${{label}}</td>
      ${{offCell}}
      <td style="text-align:center;font-size:0.8rem;color:#888">${{offTotals||''}}</td>
      ${{defCell}}
      <td style="text-align:center;font-size:0.8rem;color:#888">${{defTotals||''}}</td>
    </tr>`;
  }}

  // Schedule rows
  let scheduleHtml = '';
  let wins = 0, losses = 0, confWins = 0, confLosses = 0;
  let unplayedIdx = 0;
  const netRtgRanks = {{}};
  const validT = activeTeamData.filter(d => d.ortg > 0).sort((a,b) => b.net_rtg - a.net_rtg);
  validT.forEach((d, i) => {{ netRtgRanks[d.team] = i + 1; }});

  // Find index of last conference game to insert Playoffs banner
  const games = t.game_ratings || [];
  let lastConfIdx = -1;
  games.forEach((gr, idx) => {{ if (gr.is_conference) lastConfIdx = idx; }});
  let playoffBannerInserted = false;

  games.forEach((gr, idx) => {{
    const opp = gr.canonical_opponent || gr.opponent || '';
    const oppData = activeTeamData.find(d => d.team === opp);
    const oppNet = oppData ? oppData.net_rtg.toFixed(1) : '';
    const result = gr.result || '';
    const teamScore = gr.team_score || 0;
    const oppScore = gr.opponent_score || 0;
    const loc = gr.location || '';
    const isConf = gr.is_conference || false;
    const dateStr = gr.date || '';

    // Team's own historical rank as of this game date
    const _dayRanksSource = activeSeason === '1718' ? DAILY_RANKS_1718 : activeSeason === '1819' ? DAILY_RANKS_1819 : activeSeason === '1920' ? DAILY_RANKS_1920 : activeSeason === '2122' ? DAILY_RANKS_2021 : activeSeason === '2223' ? DAILY_RANKS_2022 : activeSeason === '2324' ? DAILY_RANKS_2023 : activeSeason === '2425' ? DAILY_RANKS_2024 : DAILY_RANKS;
    const dayRanks = _dayRanksSource[dateStr] || {{}};
    const teamRank = dayRanks[t.team] || '';

    // Opponent's historical rank as of this game date
    const oppRank = dayRanks[opp] || '';

    if (result === 'W') {{ wins++; if (isConf) confWins++; }}
    else if (result === 'L') {{ losses++; if (isConf) confLosses++; }}

    const runRec = `${{wins}}-${{losses}}`;
    const runConf = (isConf || confWins + confLosses > 0) ? `${{confWins}}-${{confLosses}}` : '';

    let resultStr = `${{teamScore}}-${{oppScore}}`;
    if (result === 'W') {{ resultStr = `W, ${{teamScore}}-${{oppScore}}`; }}
    else if (result === 'L') {{ resultStr = `L, ${{teamScore}}-${{oppScore}}`; }}

    const confMarker = isConf ? ' *' : '';
    const oppNetHtml = oppNet ? ` <span style="font-size:0.75rem;color:#444">${{oppNet > 0 ? '+' : ''}}${{oppNet}}</span>` : '';
    const oppRankHtml = oppRank ? ` <span style="font-size:0.75rem;color:#333">(#${{oppRank}})</span>` : '';
    const oppLink = oppData
      ? `<a href="#" onclick="showTeamDetail('${{opp}}');return false" style="color:#000;text-decoration:none;font-weight:600">${{opp}}</a>`
      : `<span style="font-weight:600">${{opp}}</span>`;

    // Compute tier using current net_rtg ranks
    const _tierAway = 50/90, _tierHome = 50/20;
    const _oppRankCur = netRtgRanks[opp];
    let tierHtml = '';
    if (typeof _oppRankCur === 'number') {{
      const _adj = loc === 'Away' ? _oppRankCur * _tierAway : loc === 'Home' ? _oppRankCur * _tierHome : _oppRankCur;
      if (_adj <= 15) tierHtml = '<span style="background:#c8960c;color:#fff;padding:1px 6px;border-radius:3px;font-size:0.75rem;font-weight:700">A</span>';
      else if (_adj <= 30) tierHtml = '<span style="background:#546e7a;color:#fff;padding:1px 6px;border-radius:3px;font-size:0.75rem;font-weight:700">B</span>';
    }}

    let rowClass = '';
    let rowBg = '';
    if (result === 'W') {{ rowClass = 'sched-win'; }}
    else if (result === 'L') {{ rowClass = 'sched-loss'; }}
    else {{ rowBg = unplayedIdx % 2 === 0 ? 'background:#f5f5f5;' : 'background:#e8e8e8;'; unplayedIdx++; }}

    const cellBg = rowClass ? '' : rowBg;
    scheduleHtml += `<tr class="${{rowClass}}">
      <td style="text-align:left;white-space:nowrap;${{cellBg}}">${{dateStr}}</td>
      <td style="text-align:center;${{cellBg}}">${{teamRank}}</td>
      <td style="text-align:left;${{cellBg}}">${{oppLink}}${{oppRankHtml}}${{oppNetHtml}}${{confMarker}}</td>
      <td style="text-align:left;font-weight:600;${{cellBg}}">${{resultStr}}</td>
      <td style="text-align:center;${{cellBg}}">${{loc}}</td>
      <td style="text-align:center;${{cellBg}}">${{runRec}}</td>
      <td style="text-align:center;${{cellBg}}">${{runConf}}</td>
      <td style="text-align:center;${{cellBg}}">${{tierHtml}}</td>
    </tr>`;

    // Insert Playoffs banner after the last conference game
    if (idx === lastConfIdx && !playoffBannerInserted && lastConfIdx < games.length - 1) {{
      playoffBannerInserted = true;
      scheduleHtml += `<tr><td colspan="8" style="text-align:center;background:#888;color:#fff;font-weight:700;font-size:0.78rem;padding:4px;letter-spacing:1px">PLAYOFFS</td></tr>`;
    }}
  }});

  // Find last game with data
  let lastGameDate = '';
  for (let i = games.length - 1; i >= 0; i--) {{
    if (games[i].result === 'W' || games[i].result === 'L') {{
      const d = games[i].date || '';
      // Parse and format as "Day, Month Date"
      const parts = d.split('/');
      if (parts.length === 3) {{
        const dt = new Date(parseInt(parts[2]), parseInt(parts[0]) - 1, parseInt(parts[1]));
        const days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
        const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
        lastGameDate = days[dt.getDay()] + ', ' + months[dt.getMonth()] + ' ' + dt.getDate();
      }} else {{
        lastGameDate = d;
      }}
      break;
    }}
  }}
  const dataThruHtml = lastGameDate ? `<div style="text-align:center;color:#aaa;font-size:0.82rem;margin-top:8px">Data through games of ${{lastGameDate}}</div>` : '';

  return `
    <span class="td-back" onclick="showView('${{prevView}}')">← Back to Leaderboard</span>
    <div class="td-header">
      <div class="td-rank">#${{ranks.net_rtg}} NET RTG</div>
      <h1>${{t.team}}</h1>
      <div class="td-meta">${{t.conference}} · ${{t.region}} Region</div>
      <div class="td-record">${{fs.record}} Overall &nbsp;|&nbsp; ${{fs.conf}} Conference</div>
      ${{fs.coach ? `<div class="td-coach">HC: ${{fs.coach}}</div>` : ''}}
      ${{dataThruHtml}}
    </div>
    <div class="td-content">
      <div class="td-scouting">
        <div class="td-section-title" style="position:relative;display:flex;align-items:center;justify-content:center">Scouting Report<span onclick="showGamePlan('${{t.team}}')" style="position:absolute;right:0;color:#4fc3f7;font-size:0.8rem;font-weight:400;cursor:pointer">Game Plan →</span></div>
        <table><thead><tr>
          <th style="text-align:right">Category</th><th>Offense</th><th></th><th>Defense</th><th></th>
        </tr></thead><tbody>
          ${{srRow('Adj. Efficiency', t.ortg, t.drtg, activeLeagueAvg.ortg, ranks.ortg, ranks.drtg, '', '', false, true)}}
          ${{srRow('Adj. Tempo', t.tempo, '', activeLeagueAvg.tempo, ranks.tempo, null, '', '', false, false)}}
        </tbody></table>
        <div class="td-sub-title">Four Factors</div>
        <table><thead><tr>
          <th style="text-align:right"></th><th>Offense</th><th></th><th>Defense</th><th></th>
        </tr></thead><tbody>
          ${{srRow('Effective FG%', t.efg_pct, t.opp_efg_pct, activeLeagueAvg.efg_pct, ranks.efg_pct, ranks.opp_efg_pct, '', '', false, true)}}
          ${{srRow('Turnover %', t.tov_pct, t.opp_tov_pct, activeLeagueAvg.tov_pct, ranks.tov_pct, ranks.opp_tov_pct, '', '', true, false)}}
          ${{srRow('Off. Reb. %', t.oreb_pct, t.dreb_pct, activeLeagueAvg.oreb_pct, ranks.oreb_pct, ranks.dreb_pct, '', '', false, false)}}
          ${{srRow('FT Rate', t.ft_rate, t.opp_ft_rate, activeLeagueAvg.ft_rate, ranks.ft_rate, ranks.opp_ft_rate, '', '', false, true)}}
        </tbody></table>
        <div class="td-sub-title">Shooting</div>
        <table><thead><tr>
          <th style="text-align:right"></th><th>Offense</th><th></th><th>Defense</th><th></th>
        </tr></thead><tbody>
          ${{srRow('FG%', parseFloat(fgPct), parseFloat(oFgPct), activeLeagueAvg.fg_pct, ranks.fg_pct, ranks.opp_fg_pct, `${{tot.FGM}} ${{tot.FGA}}`, `${{oTot.FGM}} ${{oTot.FGA}}`, false, true)}}
          ${{srRow('2P%', parseFloat(twoPct), parseFloat(oTwoPct), activeLeagueAvg['2p_pct'], ranks.two_pct, ranks.opp_two_pct, `${{tot.FGM-tot['3PM']}} ${{tot.FGA-tot['3PA']}}`, `${{oTot.FGM-oTot['3PM']}} ${{oTot.FGA-oTot['3PA']}}`, false, true)}}
          ${{srRow('3P%', parseFloat(tpPct), parseFloat(oTpPct), activeLeagueAvg['3p_pct'], ranks.three_pct, ranks.opp_three_pct, `${{tot['3PM']}} ${{tot['3PA']}}`, `${{oTot['3PM']}} ${{oTot['3PA']}}`, false, true)}}
          ${{srRow('FT%', parseFloat(ftPct), parseFloat(oFtPct), activeLeagueAvg.ft_pct, ranks.ft_pct, ranks.opp_ft_pct, `${{tot.FTM}} ${{tot.FTA}}`, `${{oTot.FTM}} ${{oTot.FTA}}`, false, true)}}
          ${{srRow('TS%', t.ts_pct, t.opp_ts_pct, activeLeagueAvg.ts_pct, ranks.ts_pct, ranks.opp_ts_pct, '', '', false, true)}}
        </tbody></table>
        <div class="td-sub-title">Style</div>
        <table><thead><tr>
          <th style="text-align:right"></th><th>Offense</th><th></th><th>Defense</th><th></th>
        </tr></thead><tbody>
          ${{srRow('3PA Rate', parseFloat(tpaRate), parseFloat(oTpaRate), activeLeagueAvg['3pa_rate'], ranks.tpa_rate, ranks.opp_tpa_rate, '', '', false, false)}}
          ${{srRow('Block%', parseFloat(blkPct), parseFloat(oBlkPct), 0, ranks.blk_pct, ranks.opp_blk_pct, '', '', false, true)}}
          ${{srRow('Steal%', parseFloat(stlPct), parseFloat(oStlPct), 0, ranks.stl_pct, ranks.opp_stl_pct, '', '', false, true)}}
        </tbody></table>
        <div class="td-sub-title">Shot Distribution</div>
        <table><thead><tr>
          <th style="text-align:right"></th><th>Offense</th><th></th><th>Defense</th><th></th>
        </tr></thead><tbody>
          ${{srRow('2PA %', parseFloat(dist2pa), parseFloat(oDist2pa), activeLeagueAvg.shot_dist_2pa, ranks.shot_dist_2pa, ranks.opp_shot_dist_2pa, `${{tot.FGA - tot['3PA']}} att`, `${{oTot.FGA - oTot['3PA']}} att`, false, false)}}
          ${{srRow('3PA %', parseFloat(dist3pa), parseFloat(oDist3pa), activeLeagueAvg.shot_dist_3pa, ranks.shot_dist_3pa, ranks.opp_shot_dist_3pa, `${{tot['3PA']}} att`, `${{oTot['3PA']}} att`, false, false)}}
          ${{srRow('FTA %', parseFloat(distFta), parseFloat(oDistFta), activeLeagueAvg.shot_dist_fta, ranks.shot_dist_fta, ranks.opp_shot_dist_fta, `${{tot.FTA}} att`, `${{oTot.FTA}} att`, false, true)}}
        </tbody></table>
        <div class="td-sub-title">Strength of Schedule</div>
        <table><tbody>
          ${{srRow('Opp. ORTG', fs.opp_ortg, '', activeLeagueAvg.ortg, ranks.opp_ortg, null, '', '', false, false)}}
          ${{srRow('Opp. DRTG', fs.opp_drtg_sos, '', activeLeagueAvg.drtg, ranks.opp_drtg_sos, null, '', '', false, false)}}
          ${{srRow('Overall', fs.sos, '', activeLeagueAvg.sos, ranks.sos, null, '', '', false, false)}}
          ${{srRow('Non-Conference', fs.ncsos, '', activeLeagueAvg.ncsos, ranks.ncsos, null, '', '', false, false)}}
        </tbody></table>
      </div>
      <div class="td-schedule">
        <div class="td-section-title">${{activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26'}} Schedule</div>
        <table><thead><tr>
          <th style="text-align:left">Date</th><th>Rk</th><th style="text-align:left">Opponent</th>
          <th style="text-align:left">Result</th><th>Loc</th><th>Record</th><th>Conf</th><th>Tier</th>
        </tr></thead><tbody>${{scheduleHtml}}</tbody></table>
        <div style="font-size:0.75rem;color:#888;margin-top:8px">
          Rk = Team's NET RTG rank as of game date &nbsp;|&nbsp; (#) = Opponent rank as of game date &nbsp;|&nbsp; * = Conference game
        </div>
      </div>
    </div>
  `;
}}

// --- Toggle ---
function showView(view) {{
  const indDiv = document.getElementById('individual-view');
  const teamDiv = document.getElementById('team-view');
  const uniDiv = document.getElementById('universe-view');
  const tdDiv = document.getElementById('team-detail-view');
  const slDiv = document.getElementById('storylines-view');
  const fmDiv = document.getElementById('fanmatch-view');
  const btnInd = document.getElementById('btn-individual');
  const btnTeam = document.getElementById('btn-team');
  const btnUni = document.getElementById('btn-universe');
  const btnSl = document.getElementById('btn-storylines');
  const btnFm = document.getElementById('btn-fanmatch');
  const title = document.getElementById('page-title');
  const subtitle = document.getElementById('page-subtitle');
  const info = document.getElementById('page-info');
  const filterBar = document.querySelector('.filter-bar');

  // Hide all
  indDiv.style.display = 'none';
  teamDiv.style.display = 'none';
  uniDiv.style.display = 'none';
  tdDiv.style.display = 'none';
  slDiv.style.display = 'none';
  fmDiv.style.display = 'none';
  document.getElementById('gameplan-view').style.display = 'none';
  document.getElementById('sub-toggle').style.display = 'none';
  document.getElementById('team-defense-view').style.display = 'none';
  document.getElementById('season-toggle').style.display = 'none';
  btnInd.classList.remove('active');
  btnTeam.classList.remove('active');
  btnUni.classList.remove('active');
  btnSl.classList.remove('active');
  btnFm.classList.remove('active');

  document.getElementById('conf-toggle-wrap').style.display = '';
  document.querySelector('.team-search-wrap').style.display = '';

  if (view === 'team') {{
    document.getElementById('sub-toggle').style.display = 'flex';
    const indMW2 = document.getElementById('ind-mode-wrap');
    if (indMW2) indMW2.style.display = 'none';
    const teamMW2 = document.getElementById('team-mode-wrap');
    if (teamMW2) teamMW2.style.display = '';
    btnTeam.classList.add('active');
    const defBtn = document.getElementById('btn-defense');
    onTeamModeChange(currentTeamMode);
    filterBar.style.display = 'flex';
    document.getElementById('page-title').style.display = '';
    document.getElementById('page-subtitle').style.display = '';
    document.getElementById('page-info').style.display = '';
    document.getElementById('season-toggle').style.display = 'flex';
    updateInfo();
  }} else if (view === 'universe') {{
    uniDiv.style.display = 'block';
    btnUni.classList.add('active');
    filterBar.style.display = 'none';
    document.getElementById('page-title').style.display = 'none';
    document.getElementById('page-subtitle').style.display = 'none';
    document.getElementById('page-info').style.display = 'none';
    document.getElementById('season-toggle').style.display = 'flex';
    renderUniverse();
  }} else if (view === 'fanmatch') {{
    fmDiv.style.display = 'block';
    btnFm.classList.add('active');
    filterBar.style.display = 'none';
    document.getElementById('page-title').style.display = 'none';
    document.getElementById('page-subtitle').style.display = 'none';
    document.getElementById('page-info').style.display = 'none';
    document.getElementById('conf-toggle-wrap').style.display = 'none';
    document.querySelector('.team-search-wrap').style.display = 'none';
    document.getElementById('season-toggle').style.display = 'flex';
    slInitFanmatch();
  }} else if (view === 'storylines') {{
    slDiv.style.display = 'block';
    btnSl.classList.add('active');
    filterBar.style.display = 'none';
    document.getElementById('page-title').style.display = 'none';
    document.getElementById('page-subtitle').style.display = 'none';
    document.getElementById('page-info').style.display = 'none';
    document.getElementById('conf-toggle-wrap').style.display = 'none';
    document.querySelector('.team-search-wrap').style.display = 'none';
    document.getElementById('season-toggle').style.display = 'flex';
    slInitOnce();
  }} else {{
    indDiv.style.display = 'block';
    btnInd.classList.add('active');
    document.getElementById('sub-toggle').style.display = 'flex';
    ['btn-offense','btn-defense','team-mode-wrap'].forEach(function(id) {{
      const el = document.getElementById(id); if (el) el.style.display = 'none';
    }});
    const indMW = document.getElementById('ind-mode-wrap');
    if (indMW) indMW.style.display = '';
    filterBar.style.display = 'flex';
    document.getElementById('page-title').style.display = '';
    document.getElementById('page-subtitle').style.display = '';
    document.getElementById('page-info').style.display = '';
    document.getElementById('season-toggle').style.display = 'flex';
    const indYr = activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26';
    subtitle.textContent = indYr + ' Season \u2014 Per-Game Averages';
    updateInfo();
  }}
}}

function showTeamSub(sub) {{
  const offDiv     = document.getElementById('team-view');
  const defDiv     = document.getElementById('team-defense-view');
  const basicOff   = document.getElementById('team-basic-view');
  const basicDef   = document.getElementById('team-basic-defense-view');
  const advOff     = document.getElementById('team-adv-offense-view');
  const advDef     = document.getElementById('team-adv-defense-view');
  const subtitle   = document.getElementById('page-subtitle');
  const btnOff     = document.getElementById('btn-offense');
  const btnDef     = document.getElementById('btn-defense');
  const yr = activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26';

  // Hide all tables first
  offDiv.style.display   = 'none';
  defDiv.style.display   = 'none';
  if (basicOff) basicOff.style.display = 'none';
  if (basicDef) basicDef.style.display = 'none';
  if (advOff)   advOff.style.display   = 'none';
  if (advDef)   advDef.style.display   = 'none';

  if (sub === 'defense') {{
    if (btnOff) btnOff.classList.remove('active');
    if (btnDef) btnDef.classList.add('active');
    if (currentTeamMode === 'basic') {{
      if (basicDef) {{ basicDef.style.display = 'block'; renderTeamsBasicDefense(getFilteredTeams()); }}
      subtitle.textContent = yr + ' Season \u2014 Opponent Per-Game Averages';
    }} else if (currentTeamMode === 'adv_defense') {{
      if (advDef) {{ advDef.style.display = 'block'; renderTeamsAdvDefense(getFilteredTeams()); }}
      subtitle.textContent = yr + ' Season \u2014 Advanced Defensive Analytics';
    }} else {{
      defDiv.style.display = 'block';
      subtitle.textContent = yr + ' Season \u2014 Opponent Per-Game Averages & Defensive Analytics';
    }}
  }} else {{
    if (btnOff) btnOff.classList.add('active');
    if (btnDef) btnDef.classList.remove('active');
    if (currentTeamMode === 'basic') {{
      if (basicOff) {{ basicOff.style.display = 'block'; renderTeamsBasic(getFilteredTeams()); }}
      subtitle.textContent = yr + ' Season \u2014 Per-Game Averages';
    }} else if (currentTeamMode === 'adv_offense') {{
      if (advOff) {{ advOff.style.display = 'block'; renderTeamsAdvOffense(getFilteredTeams()); }}
      subtitle.textContent = yr + ' Season \u2014 Advanced Offensive Analytics';
    }} else {{
      offDiv.style.display = 'block';
      subtitle.textContent = yr + ' Season \u2014 Per-Game Averages & Advanced Analytics';
      applyTeamModeOffenseColumns();
    }}
  }}
}}

function onTeamModeChange(mode) {{
  currentTeamMode = mode || 'advanced';
  const modeSel = document.getElementById('team-mode-select');
  if (modeSel && modeSel.value !== currentTeamMode) modeSel.value = currentTeamMode;
  const btnOff = document.getElementById('btn-offense');
  const btnDef = document.getElementById('btn-defense');
  if (currentTeamMode === 'adv_offense') {{
    if (btnOff) btnOff.style.display = 'none';
    if (btnDef) btnDef.style.display = 'none';
    showTeamSub('offense');
  }} else if (currentTeamMode === 'adv_defense') {{
    if (btnOff) btnOff.style.display = 'none';
    if (btnDef) btnDef.style.display = 'none';
    showTeamSub('defense');
  }} else {{
    if (btnOff) btnOff.style.display = '';
    if (btnDef) btnDef.style.display = '';
    const currentSub = (btnDef && btnDef.classList.contains('active')) ? 'defense' : 'offense';
    showTeamSub(currentSub);
  }}
}}

function _basicSortHelper(col, type, curSortCol, curSortDir) {{
  const lowBetter = new Set(['topg','opp_ppg','opp_fgp','opp_twop','opp_tpp','opp_ftp','opp_orebpg','opp_rpg','opp_apg','opp_spg','opp_bpg','pfpg','opp_pfpg']);
  let newDir;
  if (col === curSortCol) {{
    newDir = curSortDir === 'desc' ? 'asc' : 'desc';
  }} else {{
    newDir = type === 'str' ? 'asc' : (lowBetter.has(col) ? 'asc' : 'desc');
  }}
  const _fsPool = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  const FS_COLS = new Set(['gp','record','conf']);
  activeTeamData.sort((a, b) => {{
    const fa = _fsPool.find(d => d.team === a.team) || a;
    const fb = _fsPool.find(d => d.team === b.team) || b;
    let va = FS_COLS.has(col) ? fa[col] : a[col];
    let vb = FS_COLS.has(col) ? fb[col] : b[col];
    if (type === 'rec') {{ va = parseWins(va); vb = parseWins(vb); return newDir === 'asc' ? va - vb : vb - va; }}
    if (type === 'str') {{ va = (va||'').toLowerCase(); vb = (vb||'').toLowerCase(); return newDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va); }}
    return newDir === 'asc' ? va - vb : vb - va;
  }});
  return newDir;
}}

function doBasicSort(col, type) {{
  basicSortDir = _basicSortHelper(col, type, basicSortCol, basicSortDir);
  basicSortCol = col;
  document.querySelectorAll('#team-basic-leaderboard thead th').forEach(th => {{
    th.classList.remove('active','asc','desc');
    if (th.dataset.col === col) th.classList.add('active', basicSortDir);
  }});
  renderTeamsBasic(getFilteredTeams());
}}

function doBasicDefSort(col, type) {{
  basicDefSortDir = _basicSortHelper(col, type, basicDefSortCol, basicDefSortDir);
  basicDefSortCol = col;
  document.querySelectorAll('#team-basic-defense-leaderboard thead th').forEach(th => {{
    th.classList.remove('active','asc','desc');
    if (th.dataset.col === col) th.classList.add('active', basicDefSortDir);
  }});
  renderTeamsBasicDefense(getFilteredTeams());
}}

function renderTeamsAdvOffense(data) {{
  const tb = document.getElementById('team-adv-offense-tbody');
  if (!tb) return;
  tb.innerHTML = '';
  const colRanks = buildColRanks();
  const rk = (col, team) => {{ const r = colRanks[col]?.[team]; return r ? `<span style="font-size:0.65rem;color:#000;margin-left:3px;vertical-align:middle">${{r}}</span>` : ''; }};
  const _fsPool = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  data.forEach((t, i) => {{
    const fs = _fsPool.find(d => d.team === t.team) || t;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${{i + 1}}</td>
      <td style="text-align:left;font-weight:700">${{teamPageLink(t.team)}}</td>
      <td>${{fs.gp}}</td>
      <td>${{Number(t.ortg).toFixed(1)}}${{rk('ortg',t.team)}}</td>
      <td>${{Number(t.ts_pct).toFixed(1)}}${{rk('ts_pct',t.team)}}</td>
      <td>${{Number(t.twop).toFixed(1)}}${{rk('twop',t.team)}}</td>
      <td>${{Number(t.tpp).toFixed(1)}}${{rk('tpp',t.team)}}</td>
      <td>${{Number(t.ftp).toFixed(1)}}${{rk('ftp',t.team)}}</td>
      <td>${{Number(t.ast_pct || 0).toFixed(1)}}${{rk('ast_pct',t.team)}}</td>
      <td>${{Number(t.ast_ratio || 0).toFixed(1)}}${{rk('ast_ratio',t.team)}}</td>
      <td>${{Number(t.tov_pct).toFixed(1)}}${{rk('tov_pct',t.team)}}</td>
      <td>${{Number(t.ast_tov || 0).toFixed(2)}}${{rk('ast_tov',t.team)}}</td>
      <td>${{t.nst_pct != null ? Number(t.nst_pct).toFixed(1) + rk('nst_pct',t.team) : '<span style="color:#bbb">—</span>'}}</td>
      <td>${{Number(t.oreb_pct).toFixed(1)}}${{rk('oreb_pct',t.team)}}</td>
      <td>${{Number(t.ft_rate).toFixed(1)}}${{rk('ft_rate',t.team)}}</td>
      <td>${{Number(t.tpa_pct).toFixed(1)}}${{rk('tpa_pct',t.team)}}</td>
      <td>${{Number(t.tempo).toFixed(1)}}${{rk('tempo',t.team)}}</td>
    `;
    if (t.team === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
    tb.appendChild(tr);
  }});
}}

function doAdvOffSort(col, type) {{
  const lowBetter = new Set(['tov_pct', 'nst_pct']);
  let newDir;
  if (col === advOffSortCol) {{
    newDir = advOffSortDir === 'desc' ? 'asc' : 'desc';
  }} else {{
    newDir = type === 'str' ? 'asc' : (lowBetter.has(col) ? 'asc' : 'desc');
  }}
  advOffSortDir = newDir;
  advOffSortCol = col;
  const _fsPool = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  activeTeamData.sort((a, b) => {{
    const fa = _fsPool.find(d => d.team === a.team) || a;
    const fb = _fsPool.find(d => d.team === b.team) || b;
    let va = col === 'gp' ? fa[col] : a[col];
    let vb = col === 'gp' ? fb[col] : b[col];
    if (type === 'str') {{ va = (va||'').toLowerCase(); vb = (vb||'').toLowerCase(); return newDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va); }}
    return newDir === 'asc' ? va - vb : vb - va;
  }});
  document.querySelectorAll('#team-adv-offense-leaderboard thead th').forEach(th => {{
    th.classList.remove('active','asc','desc');
    if (th.dataset.col === col) th.classList.add('active', newDir);
  }});
  renderTeamsAdvOffense(getFilteredTeams());
}}

function renderTeamsAdvDefense(data) {{
  const tb = document.getElementById('team-adv-defense-tbody');
  if (!tb) return;
  tb.innerHTML = '';
  const colRanks = buildColRanks();
  const rk = (col, team) => {{ const r = colRanks[col]?.[team]; return r ? `<span style="font-size:0.65rem;color:#000;margin-left:3px;vertical-align:middle">${{r}}</span>` : ''; }};
  const _fsPool = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  data.forEach((t, i) => {{
    const fs = _fsPool.find(d => d.team === t.team) || t;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${{i + 1}}</td>
      <td style="text-align:left;font-weight:700">${{teamPageLink(t.team)}}</td>
      <td>${{fs.gp}}</td>
      <td>${{Number(t.drtg).toFixed(1)}}${{rk('drtg',t.team)}}</td>
      <td>${{Number(t.drebpg).toFixed(1)}}${{rk('drebpg',t.team)}}</td>
      <td>${{Number(t.dreb_pct).toFixed(1)}}${{rk('dreb_pct',t.team)}}</td>
      <td>${{Number(t.spg).toFixed(1)}}${{rk('spg',t.team)}}</td>
      <td>${{Number(t.stl_pct || 0).toFixed(1)}}${{rk('stl_pct',t.team)}}</td>
      <td>${{Number(t.stl_to || 0).toFixed(2)}}${{rk('stl_to',t.team)}}</td>
      <td>${{Number(t.bpg).toFixed(1)}}${{rk('bpg',t.team)}}</td>
      <td>${{Number(t.blk_pct || 0).toFixed(1)}}${{rk('blk_pct',t.team)}}</td>
      <td>${{Number(t.hkm_pct || 0).toFixed(1)}}${{rk('hkm_pct',t.team)}}</td>
      <td>${{t.pf_unreliable ? '<span style="color:#666">--</span>' : Number(t.pf_total || 0)}}</td>
      <td>${{t.pf_unreliable ? '<span style="color:#666">--</span>' : (Number(t.pfpg || 0).toFixed(1) + rk('pfpg',t.team))}}</td>
      <td>${{t.pf_unreliable ? '<span style="color:#666">--</span>' : (Number(t.pf_eff || 0).toFixed(2) + rk('pf_eff',t.team))}}</td>
      <td>${{t.pf_unreliable ? '<span style="color:#666">--</span>' : (Number(t.stl_pf || 0).toFixed(2) + rk('stl_pf',t.team))}}</td>
      <td>${{t.pf_unreliable ? '<span style="color:#666">--</span>' : (Number(t.blk_pf || 0).toFixed(2) + rk('blk_pf',t.team))}}</td>
    `;
    if (t.team === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
    tb.appendChild(tr);
  }});
}}

function doAdvDefSort(col, type) {{
  const lowBetter = new Set(['drtg','pf_total','pfpg']);
  let newDir;
  if (col === advDefSortCol) {{
    newDir = advDefSortDir === 'desc' ? 'asc' : 'desc';
  }} else {{
    newDir = type === 'str' ? 'asc' : (lowBetter.has(col) ? 'asc' : 'desc');
  }}
  advDefSortDir = newDir;
  advDefSortCol = col;
  const _fsPool = activeSeason === '1718' ? TEAM_DATA_1718 : activeSeason === '1819' ? TEAM_DATA_1819 : activeSeason === '1920' ? TEAM_DATA_1920 : activeSeason === '2122' ? TEAM_DATA_2021 : activeSeason === '2223' ? TEAM_DATA_2022 : activeSeason === '2324' ? TEAM_DATA_2023 : activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
  const PF_COLS = new Set(['pf_total','pfpg','pf_eff','stl_pf','blk_pf']);
  activeTeamData.sort((a, b) => {{
    if (PF_COLS.has(col)) {{
      if (a.pf_unreliable && !b.pf_unreliable) return 1;
      if (!a.pf_unreliable && b.pf_unreliable) return -1;
    }}
    const fa = _fsPool.find(d => d.team === a.team) || a;
    const fb = _fsPool.find(d => d.team === b.team) || b;
    let va = col === 'gp' ? fa[col] : a[col];
    let vb = col === 'gp' ? fb[col] : b[col];
    if (type === 'str') {{ va = (va||'').toLowerCase(); vb = (vb||'').toLowerCase(); return newDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va); }}
    return newDir === 'asc' ? va - vb : vb - va;
  }});
  document.querySelectorAll('#team-adv-defense-leaderboard thead th').forEach(th => {{
    th.classList.remove('active','asc','desc');
    if (th.dataset.col === col) th.classList.add('active', newDir);
  }});
  renderTeamsAdvDefense(getFilteredTeams());
}}

// ─── Miscellaneous (Game Attribute Rankings) ──────────────────────
const SL_TABS = [
  {{ id: 'dominance', label: 'Dominance' }},
  {{ id: 'upsets',    label: 'Upsets' }},
  {{ id: 'tension',   label: 'Tension' }},
  {{ id: 'busts',     label: 'Busts' }},
  {{ id: 'wab',       label: 'WAB' }},
  {{ id: 'rate',      label: 'Rate' }},
  {{ id: 'tiers',     label: 'Tiers' }},
  {{ id: 'quads',     label: 'Quads' }},
  {{ id: 'trank',     label: 'T-Rank' }},
  {{ id: 'rpi',       label: 'RPI' }},
  {{ id: 'trends',    label: 'Trends' }},
];
let slInitialized = false;
let slActiveTab = 'dominance';
let slFanmatchDates = [];
let slFanmatchIdx = 0;

function activeStorylines() {{
  if (activeSeason === '1718') return STORYLINES_1718;
  if (activeSeason === '1819') return STORYLINES_1819;
  if (activeSeason === '1920') return STORYLINES_1920;
  if (activeSeason === '2122') return STORYLINES_2021;
  if (activeSeason === '2223') return STORYLINES_2022;
  if (activeSeason === '2324') return STORYLINES_2023;
  if (activeSeason === '2425') return STORYLINES_2024;
  return STORYLINES;
}}

function slReinit() {{
  if (!slInitialized) return;
  slRenderTab('dominance');
  slRenderTab('upsets');
  slRenderTab('tension');
  slRenderTab('busts');
  slInitFanmatch();
  slRenderWab(slWabRegion || 'North');
  slRenderRate(activeSeason);
  slRenderTiers('All');
  slRenderQuads();
  slRenderTrank();
  slRenderRpi();
  slBuildTrendsTeamList();
  slRenderTrends();
  const tabInfo = SL_TABS.find(t => t.id === slActiveTab);
  slSwitchTab(slActiveTab, tabInfo ? tabInfo.label : slActiveTab);
}}

function slBuildNav() {{
  const nav = document.getElementById('sl-nav');
  if (!nav) return;
  nav.innerHTML = SL_TABS.map((t, i) => {{
    const sep = i < SL_TABS.length - 1 ? '<span class="sl-nav-sep">&middot;</span>' : '';
    const cls = t.id === slActiveTab ? 'sl-active' : '';
    return `<a class="${{cls}}" onclick="slSwitchTab('${{t.id}}','${{t.label}}')">${{t.label}}</a>${{sep}}`;
  }}).join('');
}}

function slInitOnce() {{
  if (slInitialized) return;
  slInitialized = true;
  slBuildNav();
  const sl = activeStorylines();
  if (sl && sl.dominant_wins) {{
    slRenderTab('dominance');
    slRenderTab('upsets');
    slRenderTab('tension');
    slRenderTab('busts');
    slInitFanmatch();
  }}
  slRenderWab(slWabRegion || 'North');
  slRenderRate(activeSeason);
  slRenderTiers('All');
  slRenderQuads();
  slRenderTrank();
  slRenderRpi();
  slBuildTrendsTeamList();
}}

function slSwitchTab(tab, label) {{
  slActiveTab = tab;
  slBuildNav();
  document.querySelectorAll('.sl-tab-content').forEach(d => d.style.display = 'none');
  document.getElementById('sl-tab-' + tab).style.display = 'block';
  const title = document.getElementById('sl-page-title');
  const countEl = document.getElementById('sl-game-count');
  if (title) {{
    if (tab === 'wab') {{
      const wabYr = activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26';
      title.textContent = wabYr + ' Wins Above Bubble';
      if (countEl) countEl.style.display = 'none';
    }} else if (tab === 'rate') {{
      const yr = activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26';
      title.textContent = yr + ' Relative Ratings (O-Rate / D-Rate / Rel-Rtg)';
      if (countEl) countEl.style.display = 'none';
    }} else if (tab === 'tiers') {{
      const tiersYr = activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26';
      title.textContent = tiersYr + ' Tier Records (KenPom Location-Adjusted)';
      if (countEl) countEl.style.display = 'none';
      slRenderTiers('All');
    }} else if (tab === 'quads') {{
      const quadsYr = activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26';
      title.textContent = quadsYr + ' Quadrant Records (NCAA-style, scaled for 100 teams)';
      if (countEl) countEl.style.display = 'none';
      slRenderQuads();
    }} else if (tab === 'trank') {{
      const trankYr = activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26';
      title.textContent = trankYr + ' T-Rank — Barthag (Bart Torvik Style)';
      if (countEl) countEl.style.display = 'none';
      slRenderTrank();
    }} else if (tab === 'trends') {{
      title.textContent = 'Year-over-Year Stat Trends';
      if (countEl) countEl.style.display = 'none';
      slRenderTrends();
    }} else {{
      const slYr = activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26';
      title.textContent = slYr + ' game attribute rankings (' + (label || tab) + ')';
      if (countEl) {{
        const n = activeStorylines().games_in_system || 0;
        countEl.textContent = n + ' game' + (n === 1 ? '' : 's') + ' played';
        countEl.style.display = 'block';
      }}
    }}
  }}
}}

let slTiersRegion = 'All';
let slTiersSortKey = 'combined_pct';
let slTiersSortAsc = false;

function slSortTiers(key) {{
  if (slTiersSortKey === key) {{ slTiersSortAsc = !slTiersSortAsc; }}
  else {{ slTiersSortKey = key; slTiersSortAsc = (key === 'team' || key === 'conference'); }}
  slRenderTiers('All');
}}

function _parseRec(s) {{
  if (!s) return {{ w: 0, l: 0, gp: 0 }};
  const m = s.match(/^(\\d+)-(\\d+)$/);
  if (!m) return {{ w: 0, l: 0, gp: 0 }};
  return {{ w: parseInt(m[1]), l: parseInt(m[2]), gp: parseInt(m[1]) + parseInt(m[2]) }};
}}

function slRenderTiers(region) {{
  const body = document.getElementById('sl-body-tiers');
  if (!body) return;
  const src = activeTeamData.filter(d => d.ortg > 0);
  const ranked = src.slice().sort((a,b) => b.net_rtg - a.net_rtg);
  const netRtgRanks = {{}};
  ranked.forEach((d, i) => {{ netRtgRanks[d.team] = i + 1; }});

  const _away = 50/90, _home = 50/20;
  let rows = src.map(t => {{
    const rank = netRtgRanks[t.team] || 999;
    let aw = 0, al = 0, bw = 0, bl = 0;
    (t.game_ratings || []).forEach(gr => {{
      const opp = gr.canonical_opponent || gr.opponent || '';
      const oppRank = netRtgRanks[opp];
      if (!oppRank) return;
      const loc = gr.location || '';
      const adj = loc === 'Away' ? oppRank * _away : loc === 'Home' ? oppRank * _home : oppRank;
      const res = gr.result || '';
      if (adj <= 15) {{ if (res === 'W') aw++; else if (res === 'L') al++; }}
      else if (adj <= 30) {{ if (res === 'W') bw++; else if (res === 'L') bl++; }}
    }});
    return {{ team: t.team, conference: t.conference || '', record: t.record || '', rank,
              aw, al, bw, bl,
              tier_a_rec: (aw + al > 0) ? aw + '-' + al : '',
              tier_b_rec: (bw + bl > 0) ? bw + '-' + bl : '',
              combined_pct: (aw + bw + al + bl > 0) ? (aw + bw) / (aw + bw + al + bl) : -1 }};
  }}).filter(Boolean);

  const k = slTiersSortKey;
  rows.sort((a, b) => {{
    let va, vb;
    if (k === 'rank') {{ va = a.rank; vb = b.rank; }}
    else if (k === 'team') {{ va = a.team.toLowerCase(); vb = b.team.toLowerCase(); }}
    else if (k === 'conference') {{ va = a.conference.toLowerCase(); vb = b.conference.toLowerCase(); }}
    else if (k === 'record') {{ va = _parseRec(a.record); vb = _parseRec(b.record); va = va.gp > 0 ? va.w / va.gp : -1; vb = vb.gp > 0 ? vb.w / vb.gp : -1; }}
    else if (k === 'tier_a_rec') {{ va = (a.aw + a.al > 0) ? a.aw / (a.aw + a.al) : -1; vb = (b.aw + b.al > 0) ? b.aw / (b.aw + b.al) : -1; }}
    else if (k === 'tier_b_rec') {{ va = (a.bw + a.bl > 0) ? a.bw / (a.bw + a.bl) : -1; vb = (b.bw + b.bl > 0) ? b.bw / (b.bw + b.bl) : -1; }}
    else if (k === 'combined_pct') {{ va = a.combined_pct; vb = b.combined_pct; }}
    else {{ va = 0; vb = 0; }}
    if (va < vb) return slTiersSortAsc ? -1 : 1;
    if (va > vb) return slTiersSortAsc ? 1 : -1;
    return 0;
  }});

  body.innerHTML = rows.map((r, i) => {{
    const bg = r.team === 'Moorpark' ? 'background:#ffe599;' : '';
    const aHtml = r.tier_a_rec ? `<span style="background:#c8960c;color:#fff;padding:1px 7px;border-radius:3px;font-size:0.78rem;font-weight:700">${{r.tier_a_rec}}</span>` : '<span style="color:#bbb">—</span>';
    const bHtml = r.tier_b_rec ? `<span style="background:#546e7a;color:#fff;padding:1px 7px;border-radius:3px;font-size:0.78rem;font-weight:700">${{r.tier_b_rec}}</span>` : '<span style="color:#bbb">—</span>';
    return `<tr>
      <td class="sl-th-r" style="${{bg}}color:#888;font-size:0.8rem">${{r.rank}}</td>
      <td style="${{bg}}">${{teamPageLink(r.team, 'color:#000;text-decoration:none;font-weight:600')}}</td>
      <td style="${{bg}}color:#555;font-size:0.82rem">${{r.conference}}</td>
      <td class="sl-th-r" style="${{bg}}">${{r.record}}</td>
      <td class="sl-th-r" style="${{bg}}">${{aHtml}}</td>
      <td class="sl-th-r" style="${{bg}}">${{bHtml}}</td>
      <td class="sl-th-r" style="${{bg}}font-weight:700">${{r.combined_pct >= 0 ? (r.combined_pct * 100).toFixed(1) + '%' : '<span style="color:#bbb">—</span>'}}</td>
    </tr>`;
  }}).join('');
}}

// ── Quadrant Records (NCAA-style, scaled) ────────────────────────────────────
let slQuadsSortKey = 'q1a';
let slQuadsSortAsc = false;

function slSortQuads(key) {{
  if (slQuadsSortKey === key) {{ slQuadsSortAsc = !slQuadsSortAsc; }}
  else {{ slQuadsSortKey = key; slQuadsSortAsc = (key === 'team' || key === 'conference' || key === 'rank'); }}
  slRenderQuads();
}}

function slRenderQuads() {{
  const body = document.getElementById('sl-body-quads');
  if (!body) return;
  const src = activeTeamData.filter(d => d.ortg > 0);
  const ranked = src.slice().sort((a, b) => b.net_rtg - a.net_rtg);
  const N = ranked.length;
  const netRanks = {{}};
  ranked.forEach((d, i) => {{ netRanks[d.team] = i + 1; }});

  // NCAA thresholds scaled proportionally: (NCAA cutoff / 353) * N
  // Q1A: H≤15, N≤25, A≤40   Q1: H≤30, N≤50, A≤75
  // Q2:  H≤75, N≤100, A≤135  Q3: H≤160, N≤200, A≤240
  function getQuad(oppRank, loc) {{
    const l = loc || 'Neutral';
    const tQ1A = {{ 'Home': N*15/353, 'Neutral': N*25/353, 'Away': N*40/353 }};
    const tQ1  = {{ 'Home': N*30/353, 'Neutral': N*50/353, 'Away': N*75/353 }};
    const tQ2  = {{ 'Home': N*75/353, 'Neutral': N*100/353, 'Away': N*135/353 }};
    const tQ3  = {{ 'Home': N*160/353, 'Neutral': N*200/353, 'Away': N*240/353 }};
    const th = (map) => map[l] != null ? map[l] : map['Neutral'];
    if (oppRank <= th(tQ1A)) return '1A';
    if (oppRank <= th(tQ1))  return '1';
    if (oppRank <= th(tQ2))  return '2';
    if (oppRank <= th(tQ3))  return '3';
    return '4';
  }}

  const rows = src.map(t => {{
    const netRank = netRanks[t.team] || 999;
    const rec   = {{ '1A': [0,0], '1': [0,0], '2': [0,0], '3': [0,0], '4': [0,0] }};
    const glist = {{ '1A': [],    '1': [],    '2': [],    '3': [],    '4': []    }};
    (t.game_ratings || []).forEach(gr => {{
      const opp = gr.canonical_opponent || gr.opponent || '';
      const oppRank = netRanks[opp];
      if (!oppRank) return;
      const q = getQuad(oppRank, gr.location);
      if (gr.result === 'W') rec[q][0]++;
      else if (gr.result === 'L') rec[q][1]++;
      glist[q].push({{ date: gr.date || '', opp: gr.opponent || opp, loc: gr.location || 'N', result: gr.result || '', ts: gr.team_score, os: gr.opponent_score }});
    }});
    // Q1 includes Q1A (cumulative); Q1+Q2 includes Q1A+Q1+Q2
    const q1_all_w  = rec['1A'][0] + rec['1'][0],  q1_all_l  = rec['1A'][1] + rec['1'][1];
    const q12_w     = rec['1A'][0] + rec['1'][0] + rec['2'][0];
    const q12_l     = rec['1A'][1] + rec['1'][1] + rec['2'][1];
    // Sort game lists chronologically
    const dateVal = d => {{
      if (!d) return 0;
      const iso = d.match(/^(\\d{{4}})-(\\d{{2}})-(\\d{{2}})$/);
      if (iso) return parseInt(iso[1])*10000 + parseInt(iso[2])*100 + parseInt(iso[3]);
      const mdy = d.match(/^(\\d{{1,2}})\\/(\\d{{1,2}})\\/(\\d{{4}})$/);
      if (mdy) return parseInt(mdy[3])*10000 + parseInt(mdy[1])*100 + parseInt(mdy[2]);
      return 0;
    }};
    const gsort = arr => arr.slice().sort((a,b) => dateVal(a.date) - dateVal(b.date));
    return {{ team: t.team, conference: t.conference || '', record: t.record || '',
              sos: t.sos || 0, netRank, rec,
              q1a_w: rec['1A'][0], q1a_l: rec['1A'][1], q1a_games: gsort(glist['1A']),
              q1_w:  q1_all_w,     q1_l:  q1_all_l,     q1_games:  gsort([...glist['1A'],...glist['1']]),
              q2_w:  rec['2'][0],  q2_l:  rec['2'][1],   q2_games:  gsort(glist['2']),
              q12_w, q12_l,                               q12_games: gsort([...glist['1A'],...glist['1'],...glist['2']]),
              q3_w:  rec['3'][0],  q3_l:  rec['3'][1],   q3_games:  gsort(glist['3']),
              q4_w:  rec['4'][0],  q4_l:  rec['4'][1],   q4_games:  gsort(glist['4']) }};
  }});

  function winPct(w, l) {{ return (w+l) > 0 ? w/(w+l) : -1; }}

  const k = slQuadsSortKey;
  rows.sort((a, b) => {{
    const dir = slQuadsSortAsc ? 1 : -1;
    // Quad sort: wins DESC → win% DESC → games played DESC → net rank ASC
    const qcmp = (aw, al, bw, bl) => {{
      if (aw !== bw) return dir * (aw - bw);
      const awp = (aw+al)>0 ? aw/(aw+al) : -1, bwp = (bw+bl)>0 ? bw/(bw+bl) : -1;
      if (awp !== bwp) return dir * (awp - bwp);
      return dir * ((aw+al) - (bw+bl));
    }};
    let va, vb;
    if (k === 'rank')       {{ va = a.netRank * (slQuadsSortAsc ? 1 : -1); vb = b.netRank * (slQuadsSortAsc ? 1 : -1);
                              return va - vb; }}
    else if (k === 'team')  {{ va = a.team.toLowerCase();            vb = b.team.toLowerCase(); }}
    else if (k === 'conference') {{ va = a.conference.toLowerCase(); vb = b.conference.toLowerCase(); }}
    else if (k === 'record') {{ const pa = _parseRec(a.record), pb = _parseRec(b.record);
                                va = pa.gp>0 ? pa.w/pa.gp : -1; vb = pb.gp>0 ? pb.w/pb.gp : -1; }}
    else if (k === 'sos')   {{ va = a.sos; vb = b.sos; }}
    else if (k === 'q1a')  {{ const c = qcmp(a.q1a_w,a.q1a_l,b.q1a_w,b.q1a_l); return c || a.netRank - b.netRank; }}
    else if (k === 'q1')   {{ const c = qcmp(a.q1_w, a.q1_l, b.q1_w, b.q1_l);  return c || a.netRank - b.netRank; }}
    else if (k === 'q2')   {{ const c = qcmp(a.q2_w, a.q2_l, b.q2_w, b.q2_l);  return c || a.netRank - b.netRank; }}
    else if (k === 'q12')  {{ const c = qcmp(a.q12_w,a.q12_l,b.q12_w,b.q12_l); return c || a.netRank - b.netRank; }}
    else if (k === 'q3')   {{ const c = qcmp(a.q3_w, a.q3_l, b.q3_w, b.q3_l);  return c || a.netRank - b.netRank; }}
    else if (k === 'q4')   {{ const c = qcmp(a.q4_w, a.q4_l, b.q4_w, b.q4_l);  return c || a.netRank - b.netRank; }}
    else {{ va = 0; vb = 0; }}
    if (va < vb) return slQuadsSortAsc ? -1 : 1;
    if (va > vb) return slQuadsSortAsc ? 1 : -1;
    return a.netRank - b.netRank;
  }});

  // Badge colors: Q1A=deep purple, Q1=dark green, Q2=steel blue, Q1+Q2=navy, Q3=burnt orange, Q4=dark red
  const QCOLORS = {{ '1A': '#6a0dad', '1': '#1a6b2a', '2': '#1a5c7c', '12': '#1a2a5c', '3': '#b85c00', '4': '#8c1a1a' }};
  function fmtDate(d) {{
    if (!d) return '';
    // Handle YYYY-MM-DD or M/D/YYYY
    const iso = d.match(/^(\\d{{4}})-(\\d{{2}})-(\\d{{2}})$/);
    if (iso) return `${{parseInt(iso[2])}}/${{parseInt(iso[3])}}/${{iso[1]}}`;
    return d;
  }}
  function badge(w, l, q, games) {{
    if (w + l === 0) return '<span style="color:#555">—</span>';
    const bg = QCOLORS[q];
    const pct = w / (w + l);
    const opacity = 0.45 + 0.55 * pct;
    const hasGames = games && games.length;
    const dataAttr = hasGames ? ` data-games='${{JSON.stringify(games).replace(/'/g, '&#39;')}}'` : '';
    return `<span${{dataAttr}} class="quad-badge" style="cursor:${{hasGames ? 'help' : 'default'}};background:${{bg}};opacity:${{opacity.toFixed(2)}};color:#fff;padding:1px 8px;border-radius:3px;font-size:0.78rem;font-weight:700;display:inline-block;min-width:40px;text-align:center">${{w}}-${{l}}</span>`;
  }}

  body.innerHTML = rows.map((r, i) => {{
    const bg = r.team === 'Moorpark' ? 'background:#ffe599;' : '';
    return `<tr>
      <td class="sl-th-r" style="${{bg}}color:#888;font-size:0.8rem">${{i + 1}}</td>
      <td style="${{bg}}">${{teamPageLink(r.team, 'color:#000;text-decoration:none;font-weight:600')}}</td>
      <td style="${{bg}}color:#555;font-size:0.82rem">${{r.conference}}</td>
      <td class="sl-th-r" style="${{bg}}">${{r.record}}</td>
      <td class="sl-th-r" style="${{bg}}color:#aaa;font-size:0.8rem">${{r.sos ? r.sos.toFixed(1) : '—'}}</td>
      <td class="sl-th-r" style="${{bg}}">${{badge(r.q1a_w, r.q1a_l, '1A', r.q1a_games)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{badge(r.q1_w,  r.q1_l,  '1',  r.q1_games)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{badge(r.q2_w,  r.q2_l,  '2',  r.q2_games)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{badge(r.q12_w, r.q12_l, '12', r.q12_games)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{badge(r.q3_w,  r.q3_l,  '3',  r.q3_games)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{badge(r.q4_w,  r.q4_l,  '4',  r.q4_games)}}</td>
    </tr>`;
  }}).join('');

  // Wire custom tooltip for quad badges
  const tip = document.getElementById('quad-tip');
  body.querySelectorAll('.quad-badge[data-games]').forEach(el => {{
    el.addEventListener('mouseenter', e => {{
      const games = JSON.parse(el.dataset.games);
      const rows = games.map(g => {{
        const score = (g.ts != null && g.os != null) ? `${{g.ts}}-${{g.os}}` : '';
        return `<tr><td>${{fmtDate(g.date)}}</td><td>${{g.opp}}</td><td>${{g.loc}}</td><td>${{g.result}} ${{score}}</td></tr>`;
      }}).join('');
      tip.innerHTML = `<table>${{rows}}</table>`;
      tip.style.display = 'block';
    }});
    el.addEventListener('mousemove', e => {{
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      let x = e.clientX + 14, y = e.clientY + 14;
      if (x + tw > window.innerWidth - 8)  x = e.clientX - tw - 14;
      if (y + th > window.innerHeight - 8) y = e.clientY - th - 14;
      tip.style.left = x + 'px';
      tip.style.top  = y + 'px';
    }});
    el.addEventListener('mouseleave', () => {{ tip.style.display = 'none'; }});
  }});
}}

let slWabRegion = 'North';

let slTrankSortKey = 'ortg';
let slTrankSortAsc = false;

function slSortTrank(key) {{
  if (slTrankSortKey === key) {{ slTrankSortAsc = !slTrankSortAsc; }}
  else {{
    slTrankSortKey = key;
    // lower-is-better columns default to ascending on first click
    slTrankSortAsc = (key === 'team' || key === 'conference' || key === 'drtg' || key === 'tov_pct' || key === 'opp_efg_pct' || key === 'opp_ft_rate');
  }}
  slRenderTrank();
}}

function slRenderTrank() {{
  const body = document.getElementById('sl-body-trank');
  if (!body) return;
  const src = activeTeamData.filter(d => d.ortg > 0 && d.drtg > 0);
  const la = activeLeagueAvg || {{}};

  // Update avg row
  const _avgCell = (id, val, dec) => {{
    const el = document.getElementById(id);
    if (el) el.textContent = val != null ? (typeof val === 'number' ? val.toFixed(dec) : val) : '—';
  }};
  const lgBarthag = la.ortg && la.drtg ? Math.pow(la.ortg, 11.5) / (Math.pow(la.ortg, 11.5) + Math.pow(la.drtg, 11.5)) : null;
  _avgCell('trank-avg-adjoe', la.ortg, 1);
  _avgCell('trank-avg-adjde', la.drtg, 1);
  _avgCell('trank-avg-barthag', lgBarthag, 3);
  _avgCell('trank-avg-efg', la.efg_pct, 1);
  _avgCell('trank-avg-tov', la.tov_pct, 1);
  _avgCell('trank-avg-or', la.oreb_pct, 1);
  _avgCell('trank-avg-ftr', la.ft_rate, 1);
  _avgCell('trank-avg-defg', la.opp_efg_pct, 1);
  _avgCell('trank-avg-dtov', la.opp_tov_pct, 1);
  const lgDor = la.dreb_pct != null ? (100 - la.dreb_pct) : null;
  _avgCell('trank-avg-dor', la.dreb_pct, 1);
  _avgCell('trank-avg-dftr', la.opp_ft_rate, 1);

  let rows = src.map(t => {{
    const adjoe = t.ortg;
    const adjde = t.drtg;
    const powOE = Math.pow(adjoe, 11.5);
    const powDE = Math.pow(adjde, 11.5);
    const barthag = powOE / (powOE + powDE);
    return {{ team: t.team, conference: t.conference || '', record: t.record || '',
              ortg: adjoe, drtg: adjde, barthag,
              efg_pct: t.efg_pct || 0, tov_pct: t.tov_pct || 0,
              oreb_pct: t.oreb_pct || 0, ft_rate: t.ft_rate || 0,
              opp_efg_pct: t.opp_efg_pct || 0, opp_tov_pct: t.opp_tov_pct || 0,
              dreb_pct: t.dreb_pct || 0, opp_ft_rate: t.opp_ft_rate || 0,
    }};
  }});

  // Apply user-selected sort
  const k = slTrankSortKey;
  rows.sort((a, b) => {{
    let va, vb;
    if (k === 'rank') {{ va = a.barthag; vb = b.barthag; }}
    else if (k === 'team') {{ va = a.team.toLowerCase(); vb = b.team.toLowerCase(); }}
    else if (k === 'conference') {{ va = a.conference.toLowerCase(); vb = b.conference.toLowerCase(); }}
    else if (k === 'record') {{
      const pr = s => {{ const m = s.match(/^(\\d+)-(\\d+)$/); return m ? parseInt(m[1]) / (parseInt(m[1]) + parseInt(m[2])) : -1; }};
      va = pr(a.record); vb = pr(b.record);
    }} else if (k === 'ortg') {{ va = a.ortg; vb = b.ortg; }}
    else if (k === 'drtg') {{ va = a.drtg; vb = b.drtg; }}
    else if (k === 'efg_pct') {{ va = a.efg_pct; vb = b.efg_pct; }}
    else if (k === 'tov_pct') {{ va = a.tov_pct; vb = b.tov_pct; }}
    else if (k === 'oreb_pct') {{ va = a.oreb_pct; vb = b.oreb_pct; }}
    else if (k === 'ft_rate') {{ va = a.ft_rate; vb = b.ft_rate; }}
    else if (k === 'opp_efg_pct') {{ va = a.opp_efg_pct; vb = b.opp_efg_pct; }}
    else if (k === 'opp_tov_pct') {{ va = a.opp_tov_pct; vb = b.opp_tov_pct; }}
    else if (k === 'dreb_pct') {{ va = a.dreb_pct; vb = b.dreb_pct; }}
    else if (k === 'opp_ft_rate') {{ va = a.opp_ft_rate; vb = b.opp_ft_rate; }}
    else {{ va = a.barthag; vb = b.barthag; }}
    if (va < vb) return slTrankSortAsc ? -1 : 1;
    if (va > vb) return slTrankSortAsc ? 1 : -1;
    return 0;
  }});

  // Helper: color a value above/below average (good = green, bad = red)
  // lowerBetter: red when above avg, green when below
  const _ff = (val, avg, lowerBetter, dec) => {{
    if (!val || !avg) return `<span style="color:#999">${{(val||0).toFixed(dec)}}</span>`;
    const diff = val - avg;
    const sig = Math.abs(diff) > (avg * 0.03); // >3% of avg = color
    let color = '';
    if (sig) color = (diff > 0) === !lowerBetter ? '#1a8c3a' : '#cc2222';
    return `<span style="${{color ? 'color:' + color + ';font-weight:600' : ''}}">${{val.toFixed(dec)}}</span>`;
  }};

  body.innerHTML = rows.map((r, i) => {{
    const bg = r.team === 'Moorpark' ? 'background:#ffe599;' : '';
    const adjoCls = r.ortg >= 110 ? 'color:#1a7a3a;font-weight:700' : r.ortg >= 105 ? 'color:#2a6f3a' : r.ortg < 95 ? 'color:#cc2222' : '';
    const adjdCls = r.drtg <= 95 ? 'color:#1a7a3a;font-weight:700' : r.drtg <= 100 ? 'color:#2a6f3a' : r.drtg > 110 ? 'color:#cc2222' : '';
    const bColor = r.barthag >= 0.75 ? '#1a6b2e' : r.barthag >= 0.60 ? '#2a7a3a' : r.barthag >= 0.40 ? '#546e7a' : r.barthag >= 0.25 ? '#b84a2a' : '#cc2222';
    const bBadge = `<span style="background:${{bColor}};color:#fff;padding:1px 8px;border-radius:3px;font-size:0.78rem;font-weight:700">${{r.barthag.toFixed(3)}}</span>`;
    const borderL = 'border-left:2px solid #e0e0e0;';
    return `<tr>
      <td class="sl-th-r" style="${{bg}}color:#888;font-size:0.8rem">${{i + 1}}</td>
      <td style="${{bg}}">${{teamPageLink(r.team, 'color:#000;text-decoration:none;font-weight:600')}}</td>
      <td style="${{bg}}color:#555;font-size:0.82rem">${{r.conference}}</td>
      <td class="sl-th-r" style="${{bg}}">${{r.record}}</td>
      <td class="sl-th-r" style="${{bg}};${{adjoCls}}">${{r.ortg.toFixed(1)}}</td>
      <td class="sl-th-r" style="${{bg}};${{adjdCls}}">${{r.drtg.toFixed(1)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{bBadge}}</td>
      <td class="sl-th-r" style="${{bg}};${{borderL}}">${{_ff(r.efg_pct, la.efg_pct, false, 1)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{_ff(r.tov_pct, la.tov_pct, true, 1)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{_ff(r.oreb_pct, la.oreb_pct, false, 1)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{_ff(r.ft_rate, la.ft_rate, false, 1)}}</td>
      <td class="sl-th-r" style="${{bg}};${{borderL}}">${{_ff(r.opp_efg_pct, la.opp_efg_pct, true, 1)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{_ff(r.opp_tov_pct, la.opp_tov_pct, false, 1)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{_ff(r.dreb_pct, la.dreb_pct, false, 1)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{_ff(r.opp_ft_rate, la.opp_ft_rate, true, 1)}}</td>
    </tr>`;
  }}).join('');
}}

// ─── RPI Tab ──────────────────────────────────────────────────────
let slRpiSeason = '2526';
let slRpiSortKey = 'rpi';
let slRpiSortAsc = false;  // false = descending (best first for numeric cols)

function slRpiSeasonFilter(season) {{
  slRpiSeason = season;
  document.getElementById('sl-rpi-btn-18').classList.toggle('active', season === '1718');
  document.getElementById('sl-rpi-btn-19').classList.toggle('active', season === '1819');
  document.getElementById('sl-rpi-btn-20').classList.toggle('active', season === '1920');
  document.getElementById('sl-rpi-btn-22').classList.toggle('active', season === '2122');
  document.getElementById('sl-rpi-btn-23').classList.toggle('active', season === '2223');
  document.getElementById('sl-rpi-btn-24').classList.toggle('active', season === '2324');
  document.getElementById('sl-rpi-btn-25').classList.toggle('active', season === '2425');
  document.getElementById('sl-rpi-btn-26').classList.toggle('active', season === '2526');
  slRenderRpi();
}}

function slSortRpi(col) {{
  const textCols = new Set(['team', 'conference']);
  if (slRpiSortKey === col) {{
    slRpiSortAsc = !slRpiSortAsc;
  }} else {{
    slRpiSortKey = col;
    slRpiSortAsc = textCols.has(col); // text: A-Z; numeric: highest first
  }}
  // Update header highlights
  ['rpi', 'nc_rpi'].forEach(k => {{
    const th = document.getElementById('rpi-th-' + k);
    if (!th) return;
    if (slRpiSortKey === k) {{
      th.style.background = '#3a5db5';
      th.style.color = '#fff';
      th.textContent = (k === 'rpi' ? 'Overall RPI' : 'NC RPI') + (slRpiSortAsc ? ' ▲' : ' ▼');
    }} else {{
      th.style.background = '';
      th.style.color = '';
      th.textContent = k === 'rpi' ? 'Overall RPI' : 'NC RPI';
    }}
  }});
  slRenderRpi();
}}

function slRenderRpi() {{
  const body = document.getElementById('sl-body-rpi');
  if (!body) return;
  const src = slRpiSeason === '1718' ? RPI_DATA_1718
    : slRpiSeason === '1819' ? RPI_DATA_1819
    : slRpiSeason === '1920' ? RPI_DATA_1920
    : slRpiSeason === '2122' ? RPI_DATA_2122
    : slRpiSeason === '2223' ? RPI_DATA_2223
    : slRpiSeason === '2324' ? RPI_DATA_2324
    : slRpiSeason === '2425' ? RPI_DATA_2425
    : RPI_DATA_2526;
  if (!src || !src.length) {{
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#555;padding:24px">No RPI data available</td></tr>';
    return;
  }}
  let rows = src.slice();
  const key = slRpiSortKey;
  // Pre-assign rank based on the active sort key (1 = best)
  const rankSortFn = (a, b) => {{
    const textCols = new Set(['team', 'conference']);
    if (key === 'record' || key === 'nc_record') {{
      const pw = s => {{ const p = (s||'0-0').split('-'); return parseInt(p[0]||0) + parseInt(p[1]||0) > 0 ? parseInt(p[0]||0) / (parseInt(p[0]||0) + parseInt(p[1]||0)) : 0; }};
      return pw(b[key]) - pw(a[key]);
    }}
    if (textCols.has(key)) return a[key] ? a[key].localeCompare(b[key]) : 0;
    return (b[key] || 0) - (a[key] || 0);
  }};
  const rpiRanked = rows.slice().sort(rankSortFn);
  const rpiRankMap = {{}};
  rpiRanked.forEach((r, i) => {{ rpiRankMap[r.team] = i + 1; }});
  rows.sort((a, b) => {{
    let av = a[key], bv = b[key];
    if (key === 'record' || key === 'nc_record') {{
      const pw = s => {{ const p = (s||'0-0').split('-'); return parseInt(p[0]||0) + parseInt(p[1]||0) > 0 ? parseInt(p[0]||0) / (parseInt(p[0]||0) + parseInt(p[1]||0)) : 0; }};
      av = pw(av); bv = pw(bv);
    }}
    if (typeof av === 'string') return slRpiSortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    return slRpiSortAsc ? av - bv : bv - av;
  }});
  const maxRpi = Math.max(...rows.map(r => r.rpi || 0));
  const minRpi = Math.min(...rows.map(r => r.rpi || 0));
  const range = maxRpi - minRpi || 0.001;
  body.innerHTML = rows.map((r, i) => {{
    const rpiRank = rpiRankMap[r.team] || (i + 1);
    const gold = r.team === 'Moorpark' ? ' class="mp-gold-row"' : '';
    const rpiPct = Math.round((r.rpi - minRpi) / range * 100);
    const ncRpiPct = Math.round((r.nc_rpi - minRpi) / range * 100);
    const rpiColor = '#333';
    const ncRpiColor = '#333';
    const teamLink = teamPageLink(r.team);
    return `<tr${{gold}}><td class="sl-rank">${{rpiRank}}</td><td style="font-weight:600">${{teamLink}}</td><td style="color:#555;font-size:12px">${{r.conference}}</td><td class="sl-val-cell">${{r.record}}</td><td class="sl-val-cell">${{r.nc_record}}</td><td class="sl-val-cell" style="color:${{rpiColor}} !important;font-weight:700 !important">${{r.rpi.toFixed(4)}}</td><td class="sl-val-cell" style="color:${{ncRpiColor}} !important;font-weight:700 !important">${{r.nc_rpi.toFixed(4)}}</td></tr>`;
  }}).join('');
}}

function slWabFilter(region) {{
  slWabRegion = region;
  document.querySelectorAll('.sl-wab-btn').forEach(b => {{
    b.classList.toggle('active', b.textContent.trim() === region);
  }});
  slRenderWab(region);
}}

function slRenderWab(region) {{
  const body = document.getElementById('sl-body-wab');
  if (!body) return;
  let rows;
  const useSplit = region === 'North' || region === 'South';
  if (useSplit) {{
    const simSrc = activeSeason === '1920' ? (WAB_SIM_1920 || {{}}) : activeSeason === '2122' ? (WAB_SIM_2122 || {{}}) : activeSeason === '2223' ? (WAB_SIM_2223 || {{}}) : activeSeason === '2324' ? (WAB_SIM_2324 || {{}}) : activeSeason === '2425' ? (WAB_SIM_2425 || {{}}) : (WAB_SIM_2526 || {{}});
    rows = (simSrc[region.toLowerCase()] || []).slice();
  }} else {{
    const src = activeSeason === '2122' ? (WAB_DATA_2021 || []) : activeSeason === '2223' ? (WAB_DATA_2022 || []) : activeSeason === '2324' ? (WAB_DATA_2023 || []) : activeSeason === '2425' ? (WAB_DATA_2024 || []) : (WAB_DATA || []);
    rows = src.filter(r => true);
    rows.sort((a, b) => b.wab - a.wab);
  }}
  if (!rows.length) {{
    body.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#555;padding:24px">No data available</td></tr>';
    return;
  }}
  const maxAbsWab = Math.max(...rows.map(r => Math.abs(r.wab)));
  const BUBBLE_RANK = 24;
  const teamSrc = activeSeason === '2122' ? (TEAM_DATA_2021 || []) : activeSeason === '2223' ? (TEAM_DATA_2022 || []) : activeSeason === '2324' ? (TEAM_DATA_2023 || []) : activeSeason === '2425' ? (TEAM_DATA_2024 || []) : (TEAM_DATA || []);
  const netMap = {{}};
  teamSrc.forEach(t => {{ netMap[t.team] = t.net_rtg; }});
  const relSrc = activeSeason === '2122' ? (REL_RATINGS_2021 || []) : activeSeason === '2223' ? (REL_RATINGS_2022 || []) : activeSeason === '2324' ? (REL_RATINGS_2023 || []) : activeSeason === '2425' ? (REL_RATINGS_2024 || []) : (REL_RATINGS || []);
  const relMap = {{}};
  relSrc.forEach(rr => {{ relMap[rr.team] = rr.rel_rating; }});
  let html = '';
  rows.forEach((r, i) => {{
    const wabVal = r.wab.toFixed(2);
    const wabCls = r.wab >= 0 ? 'sl-wab-pos' : 'sl-wab-neg';
    const barPct = Math.round(Math.abs(r.wab) / maxAbsWab * 100);
    const barColor = r.wab >= 0 ? '#2563eb' : '#dc2626';
    const bar = `<span class="sl-wab-bar" style="width:${{barPct}}%;background:${{barColor}}"></span>`;
    const netVal = netMap[r.team] != null ? netMap[r.team] : r.net;
    const netStr = (netVal >= 0 ? '+' : '') + netVal.toFixed(1);
    const teamLink = teamPageLink(r.team);
    const goldCls = r.team === 'Moorpark' ? ' class="mp-gold-row"' : '';
    html += `<tr${{goldCls}}><td class="sl-rank">${{i + 1}}</td><td style="font-weight:600">${{teamLink}}</td><td style="color:#555;font-size:12px">${{r.conference}}</td><td class="sl-val-cell">${{netStr}}</td><td class="sl-val-cell">${{r.games}}</td><td class="sl-val-cell" style="text-align:left"><span class="${{wabCls}}">${{wabVal}}</span> <span class="sl-wab-bar-wrap">${{bar}}</span></td></tr>`;
    if (useSplit && i + 1 === BUBBLE_RANK) {{
      html += '<tr class="sl-wab-bubble-line"><td colspan="6">— Bubble Line (#24) —</td></tr>';
    }}
  }});
  body.innerHTML = html;
}}

let slRateSeason = '2526';
let slRateSortCol = 'rank_rel';
let slRateSortDir = 1; // 1 = asc for rank_rel, -1 = desc for values

function slRateSeasonFilter(season) {{
  slRateSeason = season;
  const b18 = document.getElementById('sl-rate-btn-18');
  const b19 = document.getElementById('sl-rate-btn-19');
  const b20 = document.getElementById('sl-rate-btn-20');
  const b22 = document.getElementById('sl-rate-btn-22');
  const b23 = document.getElementById('sl-rate-btn-23');
  const b25 = document.getElementById('sl-rate-btn-25');
  const b26 = document.getElementById('sl-rate-btn-26');
  if (b18) b18.classList.toggle('active', season === '1718');
  if (b19) b19.classList.toggle('active', season === '1819');
  if (b20) b20.classList.toggle('active', season === '1920');
  if (b22) b22.classList.toggle('active', season === '2122');
  if (b23) b23.classList.toggle('active', season === '2223');
  if (b25) b25.classList.toggle('active', season === '2425');
  if (b26) b26.classList.toggle('active', season === '2526');
  slRenderRate(season);
  const title = document.getElementById('sl-page-title');
  if (title && slActiveTab === 'rate') {{
    const yr = season === '1718' ? '2017-18' : season === '1819' ? '2018-19' : season === '1920' ? '2019-20' : season === '2122' ? '2021-22' : season === '2223' ? '2022-23' : season === '2324' ? '2023-24' : season === '2425' ? '2024-25' : '2025-26';;
  }}
}}

function slSortRate(col) {{
  if (slRateSortCol === col) {{
    slRateSortDir *= -1;
  }} else {{
    slRateSortCol = col;
    // rank cols default asc (lower = better); value cols default desc (higher = better)
    slRateSortDir = col === 'rank_rel' || col === 'team' || col === 'conference' ? 1 : -1;
  }}
  slRenderRate(slRateSeason);
}}

function slRenderRate(season) {{
  const _s = season || slRateSeason;
  const src = _s === '1718' ? REL_RATINGS_1718 : _s === '1819' ? REL_RATINGS_1819 : _s === '1920' ? REL_RATINGS_1920 : _s === '2122' ? REL_RATINGS_2021 : _s === '2223' ? REL_RATINGS_2022 : _s === '2324' ? REL_RATINGS_2023 : _s === '2425' ? REL_RATINGS_2024 : REL_RATINGS;
  const body = document.getElementById('sl-body-rate');
  if (!body) return;
  if (!src || !src.length) {{
    body.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#555;padding:24px">No rating data available</td></tr>';
    return;
  }}
  const col = slRateSortCol;
  const dir = slRateSortDir;
  const rows = src.slice().sort((a, b) => {{
    const av = a[col], bv = b[col];
    if (typeof av === 'string') return dir * av.localeCompare(bv);
    return dir * ((av ?? 0) - (bv ?? 0));
  }});
  // Update header sort indicators
  const table = document.getElementById('rate-table');
  if (table) {{
    table.querySelectorAll('thead th').forEach(th => {{
      th.textContent = th.textContent.replace(/[ ▲▼]$/, '');
      const thCol = th.getAttribute('onclick') ? th.getAttribute('onclick').match(/slSortRate\\('(.*?)'\\)/)?.[1] : null;
      if (thCol === col) th.textContent += dir === 1 ? ' ▲' : ' ▼';
    }});
  }}
  body.innerHTML = rows.map((r, i) => {{
    const oppVal = r.opp_adjust != null ? parseFloat(r.opp_adjust) : 0;
    const pceVal = r.pace_adjust != null ? parseFloat(r.pace_adjust) : 0;
    const oppBar = `<div class="opp-bar-wrap" data-opptip="${{getOppAdjMsg(r.team, oppVal)}}"><div style="position:relative;width:50px;height:14px;background:transparent;border-radius:2px"><div style="position:absolute;top:0;height:100%;border-radius:2px;${{oppVal >= 0 ? `left:50%;width:${{Math.min(Math.abs(oppVal)/0.35*50,50)}}%;background:#e74c3c` : `right:50%;width:${{Math.min(Math.abs(oppVal)/0.35*50,50)}}%;background:#3498db`}}"></div><div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:#666"></div></div></div>`;
    const pceBar = `<div class="pace-bar-wrap" data-pacetip="${{getPaceAdjMsg(r.team, pceVal)}}"><div style="position:relative;width:50px;height:14px;background:transparent;border-radius:2px"><div style="position:absolute;top:0;height:100%;border-radius:2px;${{pceVal >= 0 ? `left:50%;width:${{Math.min(Math.abs(pceVal)/0.35*50,50)}}%;background:#e67e22` : `right:50%;width:${{Math.min(Math.abs(pceVal)/0.35*50,50)}}%;background:#3498db`}}"></div><div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:#666"></div></div></div>`;
    const hlStyle = mpGold(r.team);
    const oRate = typeof r.o_rate === 'number' ? r.o_rate.toFixed(1) : r.o_rate;
    const dRate = typeof r.d_rate === 'number' ? r.d_rate.toFixed(1) : r.d_rate;
    const relRtg = typeof r.rel_rating === 'number' ? r.rel_rating.toFixed(1) : r.rel_rating;
    const teamLink = teamPageLink(r.team, 'color:inherit;text-decoration:none;font-weight:600');
    const goldCls2 = r.team === 'Moorpark' ? ' class="mp-gold-row"' : '';
    return `<tr${{goldCls2}}>
      <td class="sl-rank">${{i + 1}}</td>
      <td>${{teamLink}}</td>
      <td style="color:#555;font-size:12px">${{r.conference}}</td>
      <td class="sl-val-cell">${{oRate}}</td>
      <td class="sl-val-cell">${{dRate}}</td>
      <td class="sl-val-cell" style="font-weight:700">${{relRtg}}</td>
      <td style="padding:0 4px;vertical-align:middle">${{oppBar}}</td>
      <td style="padding:0 4px;vertical-align:middle">${{pceBar}}</td>
    </tr>`;
  }}).join('');
}}

function slNetStr(n) {{
  if (n == null) return '';
  const v = parseFloat(n);
  return (v >= 0 ? '+' : '') + v.toFixed(1);
}}

// ─── Trends Tab ───────────────────────────────────────────────────
const TREND_MONTHS = ['Nov', 'Dec', 'Jan', 'Feb', 'Mar'];
const TREND_SEASON_CFG = [
  {{ key: '2526', label: '2025-26', color: '#d97706' }},
  {{ key: '2425', label: '2024-25', color: '#0891b2' }},
  {{ key: '2324', label: '2023-24', color: '#8b5cf6' }},
  {{ key: '2223', label: '2022-23', color: '#16a34a' }},
  {{ key: '2122', label: '2021-22', color: '#7c3aed' }},
  {{ key: '1920', label: '2019-20', color: '#dc2626' }},
];
const TREND_COLS = [
  {{ key: 'ortg',     label: 'AdjOE',    hb: true,  sign: false }},
  {{ key: 'drtg',     label: 'AdjDE',    hb: false, sign: false }},
  {{ key: 'tempo',    label: 'Tempo',    hb: null,  sign: false }},
  {{ key: 'efg_pct',  label: 'eFG%',     hb: true,  sign: false }},
  {{ key: 'tov_pct',  label: 'TO%',      hb: false, sign: false }},
  {{ key: 'oreb_pct', label: 'OR%',      hb: true,  sign: false }},
  {{ key: 'ft_rate',  label: 'FTRate',   hb: null,  sign: false }},
  {{ key: 'twop',     label: '2P%',      hb: true,  sign: false }},
  {{ key: 'tpp',      label: '3P%',      hb: true,  sign: false }},
  {{ key: 'tpa_pct',  label: '3PA%',     hb: null,  sign: false }},
  {{ key: 'ftp',      label: 'FT%',      hb: true,  sign: false }},
  {{ key: 'ast_pct',  label: 'A%',       hb: true,  sign: false }},
  {{ key: 'blk_pct',  label: 'Blk%',     hb: true,  sign: false }},
  {{ key: 'stl_pct',  label: 'Stl%',     hb: true,  sign: false }},
  {{ key: 'ppg',      label: 'PPG',      hb: true,  sign: false }},
];

let slTrendsStat  = 'net_rtg';
let slTrendsTeam  = '__league__';
let slTrendsMonth = 'all';
let slTrendsYear  = 'all';
const _trendLgCache = {{}};

function trendMonthBucket(dateStr) {{
  if (!dateStr) return null;
  const m = parseInt(dateStr.split('/')[0]);
  if (isNaN(m)) return null;
  if (m === 1)  return 'Jan';
  if (m === 2)  return 'Feb';
  if (m === 3)  return 'Mar';
  if (m === 12) return 'Dec';
  return 'Nov';  // Oct (10) and Nov (11)
}}

function trendGetSrc(key) {{
  if (key === '2526') return TEAM_DATA;
  if (key === '2425') return TEAM_DATA_2024;
  if (key === '2324') return TEAM_DATA_2023;
  if (key === '2223') return TEAM_DATA_2022;
  if (key === '2122') return TEAM_DATA_2021;
  if (key === '1920') return TEAM_DATA_1920;
  return [];
}}

function trendSeasonStats(t) {{
  return {{
    net_rtg: t.net_rtg, ortg: t.ortg, drtg: t.drtg,
    tempo:   t.tempo != null ? t.tempo : t.possessions,
    efg_pct: t.efg_pct, tov_pct: t.tov_pct, oreb_pct: t.oreb_pct, ft_rate: t.ft_rate,
    twop: t.twop, tpp: t.tpp, tpa_pct: t.tpa_pct, ftp: t.ftp,
    ast_pct: t.ast_pct, blk_pct: t.blk_pct, stl_pct: t.stl_pct, ppg: t.ppg,
  }};
}}

function trendMonthStats(t, month) {{
  // Use precomputed monthly_stats from advanced_analytics.json if available
  const ms = t.monthly_stats && t.monthly_stats[month];
  if (ms) {{
    return {{
      ortg:     ms.ortg,
      drtg:     ms.drtg,
      tempo:    ms.tempo,
      efg_pct:  ms.efg_pct,
      tov_pct:  ms.tov_pct,
      oreb_pct: ms.oreb_pct,
      ft_rate:  ms.ft_rate,
      twop:     ms.twop,
      tpp:      ms.tpp,
      tpa_pct:  ms.tpa_pct,
      ftp:      ms.ftp,
      ast_pct:  ms.ast_pct,
      blk_pct:  ms.blk_pct,
      stl_pct:  ms.stl_pct,
      ppg:      ms.ppg,
    }};
  }}
  // Fallback: compute on the fly from game_ratings
  return trendAggFromGames(t.game_ratings || [], month);
}}

function trendAggFromGames(games, month) {{
  const filtered = (games || []).filter(g => {{
    return month === 'all' ? true : trendMonthBucket(g.date) === month;
  }});
  if (!filtered.length) return null;
  const avg = k => {{
    const vals = filtered.map(g => g[k]).filter(v => v != null && !isNaN(v) && isFinite(v));
    return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null;
  }};
  const sumR = k => filtered.reduce((s, g) => s + (g[k] || 0), 0);
  const ortg = avg('ortg'), drtg = avg('drtg');
  const gFga = sumR('g_fga'), g3pa = sumR('g_3pa'), gFtm = sumR('g_ftm'), gFta = sumR('g_fta');
  const gAst = sumR('g_ast'), gFgm = sumR('g_fgm');
  const gBlk = sumR('g_blk'), gOppFga = sumR('g_opp_fga');
  const gStl = sumR('g_stl'), gOppPoss = sumR('g_opp_poss');
  return {{
    ortg, drtg,
    tempo:    avg('pace') != null ? avg('pace') : avg('possessions'),
    efg_pct:  avg('o_efg'),
    tov_pct:  avg('o_tov'),
    oreb_pct: avg('o_or'),
    ft_rate:  avg('o_ftr'),
    twop:     avg('o_2p'),
    tpp:      avg('o_3p'),
    tpa_pct:  gFga     > 0 ? g3pa  / gFga     * 100 : null,
    ftp:      gFta     > 0 ? gFtm  / gFta     * 100 : null,
    ast_pct:  gFgm     > 0 ? gAst  / gFgm     * 100 : null,
    blk_pct:  gOppFga  > 0 ? gBlk  / gOppFga  * 100 : null,
    stl_pct:  gOppPoss > 0 ? gStl  / gOppPoss * 100 : null,
    ppg:      avg('team_score'),
  }};
}}

function trendLeagueStats(seasonKey, month) {{
  const src = trendGetSrc(seasonKey) || [];
  const allStats = [];
  for (const t of src) {{
    const stats = month === 'all'
      ? trendSeasonStats(t)
      : trendMonthStats(t, month);
    if (stats) allStats.push(stats);
  }}
  if (!allStats.length) return null;
  const avg = {{}}, std = {{}};
  for (const col of TREND_COLS) {{
    const vals = allStats.map(s => s[col.key]).filter(v => v != null && !isNaN(v) && isFinite(v));
    if (!vals.length) {{ avg[col.key] = null; std[col.key] = 0; continue; }}
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    avg[col.key] = mean;
    const variance = vals.reduce((s, v) => s + (v - mean) ** 2, 0) / vals.length;
    std[col.key] = Math.sqrt(variance);
  }}
  return {{ avg, std }};
}}

function trendGetLeagueStats(seasonKey, month) {{
  const ckey = seasonKey + '|' + month;
  if (!_trendLgCache[ckey]) _trendLgCache[ckey] = trendLeagueStats(seasonKey, month);
  return _trendLgCache[ckey];
}}

function slBuildTrendsTeamList() {{
  const sel = document.getElementById('trends-team-sel');
  if (!sel || sel.dataset.built) return;
  sel.dataset.built = '1';
  const seen = new Set();
  for (const cfg of TREND_SEASON_CFG) {{
    for (const t of (trendGetSrc(cfg.key) || [])) {{
      if (t.team) seen.add(t.team);
    }}
  }}
  Array.from(seen).sort().forEach(name => {{
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    sel.appendChild(opt);
  }});
}}

function slTrendsSetTeam(name)  {{ slTrendsTeam  = name;  slRenderTrends(); }}
function slTrendsSetYear(yr)    {{ slTrendsYear  = yr;    slRenderTrends(); }}
function slTrendsSetMonth(month) {{
  slTrendsMonth = month;
  document.querySelectorAll('.trends-month-btn').forEach(b => {{
    b.classList.toggle('active', b.getAttribute('onclick').includes("'" + month + "'"));
  }});
  slRenderTrends();
}}

function slRenderTrends() {{
  slBuildTrendsTeamList();
  const tableWrap = document.getElementById('trends-table-wrap');
  const teamCard  = document.getElementById('trends-team-card');
  if (!tableWrap) return;

  const isLeague    = slTrendsTeam === '__league__';
  const showSeasons = slTrendsYear === 'all'
    ? TREND_SEASON_CFG
    : TREND_SEASON_CFG.filter(c => c.key === slTrendsYear);

  // ── Team info card ────────────────────────────────────────────────
  if (teamCard) {{
    if (!isLeague) {{
      let cardHtml = `<span class="trends-card-name">${{slTrendsTeam}}</span>`;
      for (const cfg of TREND_SEASON_CFG) {{
        const t = (trendGetSrc(cfg.key) || []).find(t => t.team === slTrendsTeam);
        if (t) {{
          cardHtml += `<span class="trends-card-season" style="color:${{cfg.color}}">` +
            `${{cfg.label}}: <strong>${{t.record || '—'}}</strong>` +
            `<span style="color:#777;font-size:11px"> · ${{t.conference}}</span></span>`;
        }}
      }}
      teamCard.innerHTML = cardHtml;
      teamCard.style.display = 'flex';
    }} else {{
      teamCard.style.display = 'none';
    }}
  }}

  // ── Stat table builder ───────────────────────────────────────────
  function buildTrendsTable(showSeasons, useTeam) {{
    let h = '<table class="trends-tbl"><thead><tr><th>' + (useTeam ? 'Season' : 'League Avg') + '</th>';
    for (const col of TREND_COLS) {{
      const dir = col.hb === true ? ' ▲' : col.hb === false ? ' ▼' : '';
      h += `<th title="${{col.label}}${{dir}}">${{col.label}}</th>`;
    }}
    h += '</tr></thead><tbody>';

    for (const cfg of showSeasons) {{
      const lg = trendGetLeagueStats(cfg.key, slTrendsMonth);
      let stats;
      if (useTeam) {{
        const t = (trendGetSrc(cfg.key) || []).find(t => t.team === slTrendsTeam);
        if (!t) {{
          h += `<tr><td style="color:${{cfg.color}}">${{cfg.label}}</td>`;
          for (const col of TREND_COLS) h += '<td class="trends-td-na">—</td>';
          h += '</tr>';
          continue;
        }}
        stats = slTrendsMonth === 'all'
          ? trendSeasonStats(t)
          : trendMonthStats(t, slTrendsMonth);
      }} else {{
        stats = lg ? lg.avg : null;
      }}

      h += `<tr><td style="color:${{cfg.color}}">${{cfg.label}}</td>`;
      for (const col of TREND_COLS) {{
        const val = stats ? stats[col.key] : null;
        if (val == null || isNaN(val) || !isFinite(val)) {{
          h += '<td class="trends-td-na">—</td>'; continue;
        }}
        const fmtV = col.sign
          ? (val >= 0 ? '+' : '') + val.toFixed(1)
          : val.toFixed(1);
        if (!useTeam || col.hb === null) {{
          h += `<td>${{fmtV}}</td>`; continue;
        }}
        const avg   = lg ? lg.avg[col.key] : null;
        const sigma = lg ? lg.std[col.key] : null;
        if (avg == null || sigma == null || sigma < 0.01) {{
          h += `<td>${{fmtV}}</td>`; continue;
        }}
        const z   = ((val - avg) / sigma) * (col.hb ? 1 : -1);
        const cls = z >=  1.5 ? 'trends-td-good3'
                  : z >=  0.7 ? 'trends-td-good2'
                  : z >= 0.25 ? 'trends-td-good1'
                  : z <= -1.5 ? 'trends-td-bad3'
                  : z <= -0.7 ? 'trends-td-bad2'
                  : z <= -0.25 ? 'trends-td-bad1' : '';
        const diff = `${{val >= avg ? '+' : ''}}${{(val - avg).toFixed(1)}} vs avg`;
        h += `<td class="${{cls}}" title="${{col.label}}: ${{fmtV}} (${{diff}})">${{fmtV}}</td>`;
      }}
      h += '</tr>';
    }}
    h += '</tbody></table>';
    return h;
  }}

  let html = '';
  if (!isLeague) {{
    html += '<div class="trends-section-label" style="color:#aaa;font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">'
          + slTrendsTeam + ' — ' + (slTrendsMonth === 'all' ? 'Full Season' : slTrendsMonth) + '</div>';
    html += buildTrendsTable(showSeasons, true);
    html += '<div class="trends-section-label" style="color:#aaa;font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin:16px 0 4px">League Average</div>';
  }}
  html += buildTrendsTable(showSeasons, false);
  tableWrap.innerHTML = html;

  // Tooltip on hover
  const tip = document.getElementById('trends-tooltip');
  if (tip) {{
    tableWrap.querySelectorAll('td[title]').forEach(td => {{
      td.addEventListener('mouseenter', () => {{
        tip.textContent = td.title; tip.style.display = 'block';
      }});
      td.addEventListener('mousemove', e => {{
        tip.style.left = (e.clientX + 14) + 'px';
        tip.style.top  = (e.clientY - 10) + 'px';
      }});
      td.addEventListener('mouseleave', () => {{ tip.style.display = 'none'; }});
    }});
  }}
}}

// ─── End Trends Tab ───────────────────────────────────────────────

function slGameCell(g) {{
  const parts = (g.score || '').split('-');
  const wScore = parts[0] || '', lScore = parts[1] || '';
  const otStr = g.overtimes > 0 ? '<span class="sl-ot"> (' + (g.overtimes > 1 ? g.overtimes : '') + 'OT)</span>' : '';
  const wNet = slNetStr(g.pregame_winner_net);
  const lNet = slNetStr(g.pregame_loser_net);
  const wLink = teamPageLink(g.winner);
  const lLink = teamPageLink(g.loser);
  return '<td class="sl-game-cell">' +
    '<span class="sl-game-winner">' + wLink + '</span>' +
    '<span class="sl-score"> ' + wScore + '</span>' +
    (wNet ? '<span class="sl-net">\u2009' + wNet + '</span>' : '') +
    ', ' +
    '<span class="sl-game-loser">' + lLink + '</span>' +
    '<span class="sl-score-loser"> ' + lScore + '</span>' +
    (lNet ? '<span class="sl-net">\u2009' + lNet + '</span>' : '') +
    otStr +
    '</td>';
}}

function slGameRow(g, idx, cols) {{
  const wpW = Math.round((g.pregame_model_wp_winner || 0) * 100);
  const wpL = 100 - wpW;
  let detail = '', value = '';
  if (cols === 'dominance') {{
    detail = '<td class="sl-detail-cell">' + g.margin + ' pts</td>';
    value  = '<td class="sl-val-cell">' + g.dominance_score + '</td>';
  }} else if (cols === 'upsets') {{
    const cls = wpW <= 35 ? ' sl-wp-low' : '';
    detail = '<td class="sl-detail-cell' + cls + '">' + wpW + '%</td>';
    value  = '<td class="sl-val-cell">' + g.upset_score + '</td>';
  }} else if (cols === 'tension') {{
    const ot = g.overtimes > 0 ? (g.overtimes > 1 ? g.overtimes + 'OT' : 'OT') : '\u2014';
    detail = '<td class="sl-detail-cell">' + g.margin + ' / ' + ot + '</td>';
    value  = '<td class="sl-val-cell">' + g.tension_score + '</td>';
  }} else if (cols === 'busts') {{
    const exp = g.pregame_model_margin_a != null ? Math.abs(g.pregame_model_margin_a).toFixed(1) : '\u2014';
    detail = '<td class="sl-detail-cell">\u00b1' + exp + '</td>';
    value  = '<td class="sl-val-cell">' + g.bust_score + '</td>';
  }} else if (cols === 'fanmatch') {{
    const cls = wpW <= 35 ? ' sl-wp-low' : '';
    const ot = g.overtimes > 0 ? (g.overtimes > 1 ? g.overtimes + 'OT' : 'OT') : '';
    const otTxt = ot ? ' <span style="font-size:0.7rem;color:#888">' + ot + '</span>' : '';
    detail = '<td class="sl-detail-cell' + cls + '">' + wpW + '% / ' + wpL + '%</td>';
    const upsetVal = (g.upset_score != null && g.upset_score > 0) ? g.upset_score : '\u2014';
    const domVal   = g.dominance_score != null ? g.dominance_score : '\u2014';
    const tenVal   = g.tension_score  != null ? g.tension_score   : '\u2014';
    value = '<td class="sl-val-cell">' + g.fanmatch_score + otTxt + '</td>'
          + '<td class="sl-val-cell" style="color:#aaa">' + upsetVal + '</td>'
          + '<td class="sl-val-cell" style="color:#aaa">' + domVal + '</td>'
          + '<td class="sl-val-cell" style="color:#aaa">' + tenVal + '</td>';
  }}
  const site = g.home_team || 'Neutral';
  const gameGoldCls = (g.winner === 'Moorpark' || g.loser === 'Moorpark') ? ' class="mp-gold-row"' : '';
  return `<tr${{gameGoldCls}}><td class="sl-rank">${{idx + 1}}</td>` +
         `<td class="sl-date-cell">${{g.date}}</td>` +
         slGameCell(g) +
         `<td class="sl-loc-cell">${{site}}</td>` +
         detail + value + '</tr>';
}}

function slRenderTab(tab) {{
  const sl = activeStorylines();
  const map = {{
    dominance: sl.dominant_wins,
    upsets:    sl.upsets,
    tension:   sl.tension_games,
    busts:     sl.bust_games,
  }};
  const games = map[tab] || [];
  const body = document.getElementById('sl-body-' + tab);
  if (!body) return;
  body.innerHTML = games.map((g, i) => slGameRow(g, i, tab)).join('');
}}

function slInitFanmatch() {{
  const fm = activeStorylines().fanmatch_games || [];
  // Build sorted unique date list (chronological)
  const seen = {{}};
  fm.forEach(g => seen[g.date] = true);
  slFanmatchDates = Object.keys(seen).sort((a, b) => {{
    const [am, ad, ay] = a.split('/').map(Number);
    const [bm, bd, by] = b.split('/').map(Number);
    return (ay * 10000 + am * 100 + ad) - (by * 10000 + bm * 100 + bd);
  }});
  // Default to most recent date
  slFanmatchIdx = slFanmatchDates.length - 1;
  slSetFanmatchDate(slFanmatchDates[slFanmatchIdx]);
}}

function slSetFanmatchDate(dateStr) {{
  const input = document.getElementById('sl-date-input');
  if (input && dateStr) {{
    const [m, d, y] = dateStr.split('/');
    input.value = y + '-' + m.padStart(2, '0') + '-' + d.padStart(2, '0');
  }}
  slRenderFanmatch(dateStr);
}}

function slCalStep(dir) {{
  slFanmatchIdx = Math.max(0, Math.min(slFanmatchDates.length - 1, slFanmatchIdx + dir));
  slSetFanmatchDate(slFanmatchDates[slFanmatchIdx]);
}}

function slCalJump() {{
  const val = document.getElementById('sl-date-input').value;
  if (!val) return;
  const [y, m, d] = val.split('-');
  const target = parseInt(m) + '/' + parseInt(d) + '/' + y;
  // Find nearest date in list
  let best = 0, bestDiff = Infinity;
  const [ty, tm, td] = [parseInt(y), parseInt(m), parseInt(d)];
  const tNum = ty * 10000 + tm * 100 + td;
  slFanmatchDates.forEach((s, i) => {{
    const [sm, sd, sy] = s.split('/').map(Number);
    const diff = Math.abs((sy * 10000 + sm * 100 + sd) - tNum);
    if (diff < bestDiff) {{ bestDiff = diff; best = i; }}
  }});
  slFanmatchIdx = best;
  slRenderFanmatch(slFanmatchDates[slFanmatchIdx]);
}}

function slRenderFanmatch(dateStr) {{
  const fm = (activeStorylines().fanmatch_games || []).filter(g => g.date === dateStr);
  const body = document.getElementById('sl-body-fanmatch');
  const lbl  = document.getElementById('sl-cal-date-label');
  const cnt  = document.getElementById('sl-cal-count');
  const prev = document.getElementById('sl-cal-prev');
  const next = document.getElementById('sl-cal-next');
  if (lbl) lbl.textContent = dateStr || '';
  if (cnt) cnt.textContent = fm.length + ' game' + (fm.length !== 1 ? 's' : '');
  if (prev) prev.disabled = slFanmatchIdx <= 0;
  if (next) next.disabled = slFanmatchIdx >= slFanmatchDates.length - 1;
  // Line o' the Night
  const lotnEl = document.getElementById('sl-lotn');
  if (lotnEl) {{
    const lotn = (activeStorylines().lines_of_night || {{}});
    const l = lotn[dateStr];
    if (l) {{
      const shotLine = l.twom + '-' + l.twoa + ' 2\\'s, ' + l.tpm + '-' + l.tpa + ' 3\\'s, ' + l.ftm + '-' + l.fta + ' FT\\'s';
      const extras = [];
      if (l.reb  > 0) extras.push(l.reb  + ' Reb'    + (l.reb  !== 1 ? 's' : ''));
      if (l.ast  > 0) extras.push(l.ast  + ' Assist'  + (l.ast  !== 1 ? 's' : ''));
      if (l.stl  > 0) extras.push(l.stl  + ' Stl'    + (l.stl  !== 1 ? 's' : ''));
      if (l.blk  > 0) extras.push(l.blk  + ' Blk'    + (l.blk  !== 1 ? 's' : ''));
      const extStr = extras.length ? ' \u2022 ' + extras.join(' \u2022 ') : '';
      lotnEl.innerHTML = '<div class="lotn-wrap"><span class="lotn-label">Line o\\' the Night:</span>'
        + '1. <span class="lotn-player">' + l.name + ', ' + l.team + '</span>'
        + ' \u2022 <span class="lotn-pts">' + l.pts + ' pts</span> (' + shotLine + ')'
        + extStr
        + ' \u2022 GS: ' + l.game_score
        + '</div>';
    }} else {{
      lotnEl.innerHTML = '';
    }}
  }}
  if (!body) return;
  body.innerHTML = fm.length
    ? fm.map((g, i) => slGameRow(g, i, 'fanmatch')).join('')
    : '<tr><td colspan="9" style="text-align:center;color:#555;padding:24px">No games on this date</td></tr>';

  // Daily summary stats
  const summaryEl = document.getElementById('sl-lotn');
  if (summaryEl && fm.length) {{
    // Favorites record
    const favWins = fm.filter(g => g.pregame_model_wp_winner >= 0.5).length;
    const favTotal = fm.length;
    // Expected wins = sum of win probabilities
    const expWins = fm.reduce((s, g) => s + (g.pregame_model_wp_winner || 0.5), 0);
    // MAE of predicted margin
    const gamesWithPred = fm.filter(g => g.pregame_model_margin_a != null);
    const mae = gamesWithPred.length
      ? (gamesWithPred.reduce((s, g) => s + Math.abs(Math.abs(g.pregame_model_margin_a) - g.margin), 0) / gamesWithPred.length).toFixed(1)
      : null;
    // Today's averages
    const avgPts = (fm.reduce((s, g) => {{
      const [ws, ls] = g.score.split('-').map(Number);
      return s + ws + ls;
    }}, 0) / fm.length).toFixed(1);
    const gamesWithPoss = fm.filter(g => g.possessions > 0);
    const avgPoss = gamesWithPoss.length
      ? (gamesWithPoss.reduce((s, g) => s + g.possessions, 0) / gamesWithPoss.length).toFixed(1)
      : null;
    const avgEff = gamesWithPoss.length
      ? (gamesWithPoss.reduce((s, g) => s + g.winner_ortg + g.winner_drtg, 0) / (2 * gamesWithPoss.length)).toFixed(1)
      : null;
    const bull = ' \u2022 ';
    let summaryHtml = summaryEl.innerHTML;
    // Append summary line after existing LOTN content
    const parts = [];
    if (mae != null) parts.push('Mean abs. error of predicted margin: <b>' + mae + '</b>');
    parts.push('Record of favorites: <b>' + favWins + '-' + (favTotal - favWins) + '</b> (expected: <b>' + expWins.toFixed(1) + '-' + (favTotal - expWins).toFixed(1) + '</b>)');
    const statParts = [];
    statParts.push('Pts/game: <b>' + avgPts + '</b>');
    if (avgEff) statParts.push('Avg efficiency: <b>' + avgEff + '</b>');
    if (avgPoss) statParts.push('Poss/40 min: <b>' + avgPoss + '</b>');
    const summaryLine = '<div class="lotn-wrap" style="margin-top:6px;font-size:0.78rem">'
      + '<span class="lotn-label" style="font-size:0.68rem">Today\\'s Summary:</span>'
      + parts.join(bull) + bull + statParts.join(bull)
      + '</div>';
    summaryEl.innerHTML = summaryHtml + summaryLine;
  }}
}}
// ─────────────────────────────────────────────────────────────────────

// --- Floating OPP ADJ tooltip ---
(function() {{
  const tip = document.getElementById('opp-float-tip');
  document.addEventListener('mouseenter', function(e) {{
    const wrap = e.target.closest('.opp-bar-wrap');
    if (!wrap) return;
    const msg = wrap.dataset.opptip;
    if (!msg) return;
    tip.textContent = msg;
    tip.style.display = 'block';
    const rect = wrap.getBoundingClientRect();
    const tipW = 240;
    let left = rect.left + rect.width / 2 - tipW / 2;
    if (left < 4) left = 4;
    if (left + tipW > window.innerWidth - 4) left = window.innerWidth - tipW - 4;
    tip.style.left = left + 'px';
    tip.style.width = tipW + 'px';
    tip.className = '';
    tip.style.top = '';
    const tipH = tip.offsetHeight;
    if (rect.top - tipH - 10 > 0) {{
      tip.classList.add('above');
      tip.style.top = (rect.top - tipH - 10) + 'px';
    }} else {{
      tip.classList.add('below');
      tip.style.top = (rect.bottom + 10) + 'px';
    }}
  }}, true);
  document.addEventListener('mouseleave', function(e) {{
    const wrap = e.target.closest('.opp-bar-wrap');
    if (!wrap) return;
    tip.style.display = 'none';
  }}, true);
}})();

// --- Floating PACE ADJ tooltip ---
(function() {{
  const tip = document.getElementById('pace-float-tip');
  document.addEventListener('mouseenter', function(e) {{
    const wrap = e.target.closest('.pace-bar-wrap');
    if (!wrap) return;
    const msg = wrap.dataset.pacetip;
    if (!msg) return;
    tip.textContent = msg;
    tip.style.display = 'block';
    const rect = wrap.getBoundingClientRect();
    const tipW = 240;
    let left = rect.left + rect.width / 2 - tipW / 2;
    if (left < 4) left = 4;
    if (left + tipW > window.innerWidth - 4) left = window.innerWidth - tipW - 4;
    tip.style.left = left + 'px';
    tip.style.width = tipW + 'px';
    tip.className = '';
    tip.style.top = '';
    const tipH = tip.offsetHeight;
    if (rect.top - tipH - 10 > 0) {{
      tip.classList.add('above');
      tip.style.top = (rect.top - tipH - 10) + 'px';
    }} else {{
      tip.classList.add('below');
      tip.style.top = (rect.bottom + 10) + 'px';
    }}
  }}, true);
  document.addEventListener('mouseleave', function(e) {{
    const wrap = e.target.closest('.pace-bar-wrap');
    if (!wrap) return;
    tip.style.display = 'none';
  }}, true);
}})();
</script>
</body>
</html>"""
    return html


def main():
    print("Loading player stats from all teams...")
    players = load_players()
    print(f"  {len(players)} players qualify (40% minutes threshold)")
    teams = load_teams()
    print(f"  {len(teams)} teams loaded")
    conf_players = load_conf_players()
    print(f"  {len(conf_players)} conference-only players loaded")
    conf_teams = load_conf_teams()
    print(f"  {len(conf_teams)} conference-only teams loaded")
    rpi_2526 = compute_rpi(STATS_DIR)
    print(f"  {len(rpi_2526)} teams with 2025-26 RPI computed")
    teams_2024 = load_teams(STATS_DIR_2024)
    print(f"  {len(teams_2024)} 2024-25 teams loaded")
    conf_teams_2024 = load_conf_teams(STATS_DIR_2024)
    print(f"  {len(conf_teams_2024)} 2024-25 conference-only teams loaded")
    players_2024 = load_players(STATS_DIR_2024)
    print(f"  {len(players_2024)} 2024-25 players loaded")
    conf_players_2024 = load_conf_players(STATS_DIR_2024)
    print(f"  {len(conf_players_2024)} 2024-25 conference-only players loaded")
    rpi_2425 = compute_rpi(STATS_DIR_2024)
    print(f"  {len(rpi_2425)} teams with 2024-25 RPI computed")
    storylines_2024 = load_storylines(STATS_DIR_2024)
    print(f"  {storylines_2024.get('games_in_system', 0)} 2024-25 storyline games loaded")
    storylines_2023 = load_storylines(STATS_DIR_2023)
    print(f"  {storylines_2023.get('games_in_system', 0)} 2023-24 storyline games loaded")
    storylines_2022 = load_storylines(STATS_DIR_2022)
    print(f"  {storylines_2022.get('games_in_system', 0)} 2022-23 storyline games loaded")
    storylines_2021 = load_storylines(STATS_DIR_2021)
    print(f"  {storylines_2021.get('games_in_system', 0)} 2021-22 storyline games loaded")

    teams_2023 = load_teams(STATS_DIR_2023)
    print(f"  {len(teams_2023)} 2023-24 teams loaded")
    conf_teams_2023 = load_conf_teams(STATS_DIR_2023)
    print(f"  {len(conf_teams_2023)} 2023-24 conference-only teams loaded")
    players_2023 = load_players(STATS_DIR_2023)
    print(f"  {len(players_2023)} 2023-24 players loaded")
    conf_players_2023 = load_conf_players(STATS_DIR_2023)
    print(f"  {len(conf_players_2023)} 2023-24 conference-only players loaded")
    rpi_2324 = compute_rpi(STATS_DIR_2023)
    print(f"  {len(rpi_2324)} teams with 2023-24 RPI computed")
    teams_2022 = load_teams(STATS_DIR_2022)
    print(f"  {len(teams_2022)} 2022-23 teams loaded")
    conf_teams_2022 = load_conf_teams(STATS_DIR_2022)
    print(f"  {len(conf_teams_2022)} 2022-23 conference-only teams loaded")
    players_2022 = load_players(STATS_DIR_2022)
    print(f"  {len(players_2022)} 2022-23 players loaded")
    conf_players_2022 = load_conf_players(STATS_DIR_2022)
    print(f"  {len(conf_players_2022)} 2022-23 conference-only players loaded")
    rpi_2223 = compute_rpi(STATS_DIR_2022)
    print(f"  {len(rpi_2223)} teams with 2022-23 RPI computed")
    teams_2021 = load_teams(STATS_DIR_2021)
    print(f"  {len(teams_2021)} 2021-22 teams loaded")
    conf_teams_2021 = load_conf_teams(STATS_DIR_2021)
    print(f"  {len(conf_teams_2021)} 2021-22 conference-only teams loaded")
    players_2021 = load_players(STATS_DIR_2021)
    print(f"  {len(players_2021)} 2021-22 players loaded")
    conf_players_2021 = load_conf_players(STATS_DIR_2021)
    print(f"  {len(conf_players_2021)} 2021-22 conference-only players loaded")
    rpi_2122 = compute_rpi(STATS_DIR_2021)
    print(f"  {len(rpi_2122)} teams with 2021-22 RPI computed")
    teams_2019 = load_teams(STATS_DIR_2019)
    print(f"  {len(teams_2019)} 2019-20 teams loaded")
    conf_teams_2019 = load_conf_teams(STATS_DIR_2019)
    print(f"  {len(conf_teams_2019)} 2019-20 conference-only teams loaded")
    players_2019 = load_players(STATS_DIR_2019)
    print(f"  {len(players_2019)} 2019-20 players loaded")
    conf_players_2019 = load_conf_players(STATS_DIR_2019)
    print(f"  {len(conf_players_2019)} 2019-20 conference-only players loaded")
    storylines_2019 = load_storylines(STATS_DIR_2019)
    print(f"  {storylines_2019.get('games_in_system', 0)} 2019-20 storyline games loaded")
    rpi_1920 = compute_rpi(STATS_DIR_2019)
    print(f"  {len(rpi_1920)} teams with 2019-20 RPI computed")
    teams_1819 = load_teams(STATS_DIR_1819)
    print(f"  {len(teams_1819)} 2018-19 teams loaded")
    conf_teams_1819 = load_conf_teams(STATS_DIR_1819)
    print(f"  {len(conf_teams_1819)} 2018-19 conference-only teams loaded")
    players_1819 = load_players(STATS_DIR_1819)
    print(f"  {len(players_1819)} 2018-19 players loaded")
    conf_players_1819 = load_conf_players(STATS_DIR_1819)
    print(f"  {len(conf_players_1819)} 2018-19 conference-only players loaded")
    storylines_1819 = load_storylines(STATS_DIR_1819)
    print(f"  {storylines_1819.get('games_in_system', 0)} 2018-19 storyline games loaded")
    rpi_1819 = compute_rpi(STATS_DIR_1819)
    print(f"  {len(rpi_1819)} teams with 2018-19 RPI computed")
    teams_1718 = load_teams(STATS_DIR_1718)
    print(f"  {len(teams_1718)} 2017-18 teams loaded")
    conf_teams_1718 = load_conf_teams(STATS_DIR_1718)
    print(f"  {len(conf_teams_1718)} 2017-18 conference-only teams loaded")
    players_1718 = load_players(STATS_DIR_1718)
    print(f"  {len(players_1718)} 2017-18 players loaded")
    conf_players_1718 = load_conf_players(STATS_DIR_1718)
    print(f"  {len(conf_players_1718)} 2017-18 conference-only players loaded")
    storylines_1718 = load_storylines(STATS_DIR_1718)
    print(f"  {storylines_1718.get('games_in_system', 0)} 2017-18 storyline games loaded")
    rpi_1718 = compute_rpi(STATS_DIR_1718)
    print(f"  {len(rpi_1718)} teams with 2017-18 RPI computed")

    html = generate_html(players, teams, conf_players, conf_teams, teams_2024=teams_2024, conf_teams_2024=conf_teams_2024,
                         players_2024=players_2024, conf_players_2024=conf_players_2024, storylines_2024=storylines_2024,
                         teams_2023=teams_2023, conf_teams_2023=conf_teams_2023,
                         players_2023=players_2023, conf_players_2023=conf_players_2023, storylines_2023=storylines_2023,
                         teams_2022=teams_2022, conf_teams_2022=conf_teams_2022,
                         players_2022=players_2022, conf_players_2022=conf_players_2022, storylines_2022=storylines_2022,
                         teams_2021=teams_2021, conf_teams_2021=conf_teams_2021,
                         players_2021=players_2021, conf_players_2021=conf_players_2021, storylines_2021=storylines_2021,
                         teams_2019=teams_2019, conf_teams_2019=conf_teams_2019,
                         players_2019=players_2019, conf_players_2019=conf_players_2019, storylines_2019=storylines_2019,
                         teams_1819=teams_1819, conf_teams_1819=conf_teams_1819,
                         players_1819=players_1819, conf_players_1819=conf_players_1819, storylines_1819=storylines_1819,
                         teams_1718=teams_1718, conf_teams_1718=conf_teams_1718,
                         players_1718=players_1718, conf_players_1718=conf_players_1718, storylines_1718=storylines_1718,
                         rpi_data_2526=rpi_2526, rpi_data_2425=rpi_2425,
                         rpi_data_2324=rpi_2324, rpi_data_2223=rpi_2223, rpi_data_2122=rpi_2122, rpi_data_1920=rpi_1920,
                         rpi_data_1819=rpi_1819, rpi_data_1718=rpi_1718)
    OUTPUT.write_text(html)
    print(f"  Saved: {OUTPUT} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
