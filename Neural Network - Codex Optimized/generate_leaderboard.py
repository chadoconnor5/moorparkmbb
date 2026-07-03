from __future__ import annotations

from pathlib import Path
import argparse
import csv
import json
import math
import re
import shutil
from dataclasses import dataclass
from datetime import datetime

from generate_team_pages import SCHOOL_COLORS, SCHOOL_SECONDARY_COLORS
from update_advanced_analytics import STAT_DEFINITIONS
from compute_ccc_bpm import (
    BPM_COEFFS, BPM_ROLE_COEFFS, OBPM_COEFFS, OBPM_ROLE_COEFFS, raw_metric,
)
from compute_moorpark_lineups import build_moorpark_lineups
from compute_team_keys import build_keys, load_all_games as load_all_games_keys, LAST_5 as LAST_5_KEYS


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
_CACHE_DIR = Path("internal_data/cache/leaderboard")
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
_HEIGHTS_CSV = Path("internal_data/roster_heights_2025_26.csv")
_BPM_CSV = Path("internal_data/ccc_bpm_2025_26.csv")


_POS_MAP_CACHE = {}


def _load_player_positions(season="2025-26"):
    """Load a season's position classifications. Returns {(team, name): pos_class}.

    Each season has its own internal_data/player_positions_<season>.csv (the
    current season is height-adjusted; prior seasons are box-score-only from the
    same trained model). Results are cached per season.
    """
    import csv
    if season in _POS_MAP_CACHE:
        return _POS_MAP_CACHE[season]
    pos_map = {}
    csv_path = Path(f"internal_data/player_positions_{season.replace('-', '_')}.csv")
    if csv_path.exists():
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pos_map[(row["team"].strip(), row["name"].strip())] = row["pos_class"].strip()
    _POS_MAP_CACHE[season] = pos_map
    return pos_map


def _bpm_player_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _load_bpm_rows(season="2025-26"):
    """Load in-house strict BPM 2.0 rows for a given season.

    Each season has its own internal_data/ccc_bpm_<season>.csv (generated by
    compute_ccc_bpm.py --season <season>). Returns {} if that season's CSV is
    missing so older seasons simply show no BPM rather than erroring."""
    bpm_map = {}
    bpm_csv = Path(f"internal_data/ccc_bpm_{season.replace('-', '_')}.csv")
    if not bpm_csv.exists():
        return bpm_map
    with bpm_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if str(row.get("qualifies_minutes", "")).lower() != "true":
                continue
            key = ((row.get("team") or "").strip(), _bpm_player_key(row.get("player") or ""))
            try:
                bpm_map[key] = {
                    "bpm_gp": int(float(row.get("games") or 0)),
                    "obpm": float(row.get("obpm") or 0),
                    "dbpm": float(row.get("dbpm") or 0),
                    "bpm": float(row.get("bpm") or 0),
                    "vorp": float(row.get("vorp_style") or 0),
                }
            except ValueError:
                continue
    return bpm_map


def _parse_height_to_inches(raw: str) -> int | None:
    """Parse common roster height formats into inches."""
    s = (raw or "").lower()
    s = s.replace("ht.:", "").replace("ht:", "").replace("height", "")
    s = s.replace("″", '"').strip()
    m = re.search(r'(\d)\s*[\'’"]\s*(\d{1,2})', s)
    if not m:
        m = re.search(r"\b(\d)\s*-\s*(\d{1,2})\b", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    m = re.search(r"\b(\d{2})\b", s)
    if m:
        inches = int(m.group(1))
        if 55 <= inches <= 90:
            return inches
    return None


def _fmt_height_inches(inches: float | int | None) -> str:
    if inches is None:
        return ""
    rounded = int(round(inches))
    return f"{rounded // 12}'{rounded % 12}\""


def _height_team_key(name: str) -> str:
    s = name.lower().replace("los angeles", "la").replace("mt san", "mt. san")
    s = s.replace("men’s", "mens")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    drop = {
        "basketball", "bobcats", "cc", "chargers", "city", "college",
        "community", "dons", "falcons", "giants", "hawks", "home",
        "junior", "knights", "official", "of", "panthers", "pirate",
        "pirates", "spartan", "spartans", "the", "viking", "vikings",
    }
    return " ".join(tok for tok in s.split() if tok not in drop)


def _height_player_key(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"^#\d+\s+", "", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    parts = s.split()
    if len(parts) % 2 == 0 and parts[: len(parts) // 2] == parts[len(parts) // 2 :]:
        parts = parts[: len(parts) // 2]
    roster_pos_suffixes = {
        "g", "f", "c", "gf", "fg", "fc", "cf",
        "pg", "sg", "sf", "pf",
    }
    if len(parts) > 1 and parts[-1] in roster_pos_suffixes:
        parts = parts[:-1]
    return " ".join(parts)


def _load_position_groups() -> dict[tuple[str, str], str]:
    """Return {(team, player): guard|forward} from the 2025-26 position CSV."""
    groups = {}
    if not _POSITIONS_CSV.exists():
        return groups
    guard_labels = {"PG", "s-PG", "CG", "WG"}
    forward_labels = {"WF", "S-PF", "PF/C", "C"}
    with open(_POSITIONS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pos = (row.get("pos_class") or "").strip()
            if pos in guard_labels:
                group = "guard"
            elif pos in forward_labels:
                group = "forward"
            else:
                continue
            groups[(row.get("team", "").strip(), _height_player_key(row.get("name", "")))] = group
    return groups


def _load_position_scoring(teams: list[dict], position_groups: dict[tuple[str, str], str]) -> dict[str, dict]:
    """Return team scoring totals split into guard/forward position groups."""
    scoring: dict[str, dict] = {}
    for team in teams:
        team_name = team.get("team", "")
        conf_name = team.get("conference", "")
        if not team_name or not conf_name:
            continue
        player_path = _find_team_stats_dir(STATS_DIR, conf_name, team_name) / "player_stats.json"
        if not player_path.exists():
            continue
        try:
            pdata = json.load(open(player_path))
        except Exception:
            continue
        totals = {"guard": 0, "forward": 0, "total": 0}
        for player in pdata.get("players", []):
            pts = int(player.get("totals", {}).get("PTS", 0) or 0)
            totals["total"] += pts
            player_key = _height_player_key(player.get("name", ""))
            group = position_groups.get((team_name, player_key))
            if group in ("guard", "forward"):
                totals[group] += pts
        scoring[team_name] = totals
    return scoring


def load_height_data(teams: list[dict]) -> dict:
    """Load 2025-26 roster heights and rank teams by average inches."""
    canonical = {t["team"]: t for t in teams}
    canonical_by_key = {_height_team_key(name): name for name in canonical}
    position_groups = _load_position_groups()
    position_scoring = _load_position_scoring(teams, position_groups)
    manual_team_map = {
        "2025": "Irvine Valley",
        "Men’s Basketball": "Los Medanos",
        "Team": "Monterey Peninsula",
    }

    def resolve_team(raw_team: str) -> str | None:
        if raw_team in manual_team_map:
            return manual_team_map[raw_team]
        raw_key = _height_team_key(raw_team)
        if raw_key in canonical_by_key:
            return canonical_by_key[raw_key]
        candidates = []
        for key, team_name in canonical_by_key.items():
            if key and (key in raw_key or raw_key in key):
                candidates.append((len(key), team_name))
        if candidates:
            return sorted(candidates, reverse=True)[0][1]
        return None

    heights_by_team: dict[str, list[int]] = {}
    grouped_heights: dict[str, dict[str, list[int]]] = {}
    if _HEIGHTS_CSV.exists():
        with open(_HEIGHTS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                team_name = resolve_team(row.get("team", ""))
                inches = _parse_height_to_inches(row.get("height", ""))
                if team_name and inches:
                    heights_by_team.setdefault(team_name, []).append(inches)
                    player_key = _height_player_key(row.get("player", ""))
                    group = position_groups.get((team_name, player_key))
                    if group:
                        grouped_heights.setdefault(team_name, {"guard": [], "forward": []})[group].append(inches)

    ranked = []
    for team_name, values in heights_by_team.items():
        team = canonical.get(team_name, {})
        avg = sum(values) / len(values)
        guard_values = grouped_heights.get(team_name, {}).get("guard", [])
        forward_values = grouped_heights.get(team_name, {}).get("forward", [])
        guard_avg = sum(guard_values) / len(guard_values) if guard_values else None
        forward_avg = sum(forward_values) / len(forward_values) if forward_values else None
        scoring = position_scoring.get(team_name, {})
        total_pts = scoring.get("total", 0) or 0
        guard_pts = scoring.get("guard", 0) or 0
        forward_pts = scoring.get("forward", 0) or 0
        guard_scoring_pct = guard_pts / total_pts * 100 if total_pts else None
        forward_scoring_pct = forward_pts / total_pts * 100 if total_pts else None
        ranked.append({
            "team": team_name,
            "conference": team.get("conference", ""),
            "region": team.get("region", ""),
            "avg_inches": round(avg, 2),
            "avg_height": _fmt_height_inches(avg),
            "avg_guard_inches": round(guard_avg, 2) if guard_avg is not None else None,
            "avg_guard_height": _fmt_height_inches(guard_avg) if guard_avg is not None else "",
            "guard_players": len(guard_values),
            "avg_forward_inches": round(forward_avg, 2) if forward_avg is not None else None,
            "avg_forward_height": _fmt_height_inches(forward_avg) if forward_avg is not None else "",
            "forward_players": len(forward_values),
            "guard_points": guard_pts,
            "forward_points": forward_pts,
            "total_points": total_pts,
            "guard_scoring_pct": round(guard_scoring_pct, 1) if guard_scoring_pct is not None else None,
            "forward_scoring_pct": round(forward_scoring_pct, 1) if forward_scoring_pct is not None else None,
            "players": len(values),
            "min_inches": min(values),
            "max_inches": max(values),
            "min_height": _fmt_height_inches(min(values)),
            "max_height": _fmt_height_inches(max(values)),
        })
    ranked.sort(key=lambda r: (-r["avg_inches"], r["team"]))
    for i, row in enumerate(ranked, 1):
        row["rank"] = i

    missing = []
    for team_name, team in canonical.items():
        if team_name not in heights_by_team:
            missing.append({
                "team": team_name,
                "conference": team.get("conference", ""),
                "region": team.get("region", ""),
            })
    missing.sort(key=lambda r: (r["conference"], r["team"]))
    return {"ranked": ranked, "missing": missing}


def _cached_json(name: str, builder, refresh: bool = False):
    """Load a generated dataset from cache or rebuild it."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{name}.json"
    if path.exists() and not refresh:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = builder()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data
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

Loads player stats from all 7 WSC North teams, filters by 30% minutes
played threshold, and outputs a sortable HTML table.
"""


# Players exempted from the 30% minutes threshold
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


_GS_CACHE = {}


def _team_games_started(stats_team_dir):
    """Count games started per player (clean name) for a team, from box scores.

    Uses the scraped is_starter / role flag when present; otherwise falls back
    to the CCCMBCA convention that the first five listed players are starters.
    Cached per team directory.
    """
    key = str(stats_team_dir)
    if key in _GS_CACHE:
        return _GS_CACHE[key]
    sched_dir = Path(key.replace(" Team Statistics", " Teams Schedules"))
    counts = {}
    if sched_dir.exists():
        tnorm = _box_norm(stats_team_dir.name)
        for game_dir in sorted(sched_dir.iterdir()):
            if not game_dir.is_dir():
                continue
            box = None
            for f in sorted(game_dir.glob("*.json")):
                try:
                    box = json.load(open(f))
                except Exception:
                    box = None
                break
            if not box:
                continue
            plist = None
            for tn, rows in (box.get("teams") or {}).items():
                if _box_norm(tn) == tnorm:
                    plist = rows
                    break
            if not plist:
                continue
            has_flags = any(r.get("is_starter") is not None or r.get("role") for r in plist)
            for idx, r in enumerate(plist):
                started = (bool(r.get("is_starter") or r.get("role") == "starter")
                           if has_flags else idx < 5)
                if started:
                    nm = re.sub(r"^#\d+\s+", "", r.get("name", ""))
                    counts[nm] = counts.get(nm, 0) + 1
    _GS_CACHE[key] = counts
    return counts


def _display_name(name):
    """Normalize ALL-CAPS scraped names (e.g. 'RAYSHAUD BRADLEY') to Title Case
    for display. Names with any lowercase letters are left untouched, so only the
    fully-uppercase outliers get fixed."""
    s = (name or "").strip()
    letters = [c for c in s if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return s.title()
    return s


def load_players(stats_dir=None):
    """Load all qualified players from all teams."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    pos_map = _load_player_positions(_STATS_DIR_TO_SEASON.get(str(stats_dir), "2025-26"))
    bpm_map = _load_bpm_rows(_STATS_DIR_TO_SEASON.get(str(stats_dir), "2025-26"))
    # Roster class (Fr/So) is current-season only (scraped 2025-26 rosters).
    class_map = _load_player_class() if Path(stats_dir) == Path(STATS_DIR) else {}
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
            gs_map = _team_games_started(team_dir)

            team_total_min = summary["totals"]["MIN"]
            min_threshold = team_total_min * 0.30    # leaderboard qualification (>=30% of minutes)
            cover_threshold = team_total_min * 0.10  # comp-coverage floor (>=10%, no deep bench)
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
                # Proportional MPG cutoff: same 30% ratio scaled to fake minutes
                fake_mpg_cutoff = avg_player_min_pg / 5 * 0.30

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
                elif clean_name not in PLAYER_EXEMPTIONS and t["MIN"] < cover_threshold:
                    continue

                # q = leaderboard-qualified (>=30% of minutes). Players at
                # 10-30% are loaded for similar-player comps but flagged q=0 so
                # the leaderboard tables/charts filter them out.
                qualified = 1 if (is_fake or clean_name in PLAYER_EXEMPTIONS
                                  or t["MIN"] >= min_threshold) else 0
                _adv = adv_map.get(clean_name, {}) if adv_eligible else {}
                # eFG%, TS%, and FT rate depend only on box-score totals (not
                # minutes), so compute them directly when the team fails the
                # clean-minutes checks and ships no advanced player data.
                # Formulas match STAT_DEFINITIONS in update_advanced_analytics.py.
                _fga, _fta = t["FGA"], t["FTA"]
                _efg = _adv.get("efg_pct")
                if _efg is None:
                    _efg = round((t["FGM"] + 0.5 * t["3PM"]) / _fga * 100, 1) if _fga > 0 else 0.0
                _ts = _adv.get("ts_pct")
                if _ts is None:
                    _ts_denom = 2 * (_fga + 0.475 * _fta)
                    _ts = round(t["PTS"] / _ts_denom * 100, 1) if _ts_denom > 0 else 0.0
                _ftr = _adv.get("ft_rate")
                if _ftr is None:
                    _ftr = round(_fta / _fga * 100, 1) if _fga > 0 else 0.0
                bpm_row = bpm_map.get((team, _bpm_player_key(clean_name)), {})
                players.append({
                    "name": _display_name(clean_name),
                    "school": team,
                    "region": region,
                    "q": qualified,
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
                    "tpa_rate": round(t["3PA"] / t["FGA"] * 100, 1) if t["FGA"] else None,
                    "ftm": t["FTM"], "fta": t["FTA"],
                    "ftp": round(t["FTM"] / t["FTA"] * 100, 1) if t["FTA"] else 0.0,
                    "pts": t["PTS"],
                    "reb": t["REB"],
                    "ast": t["AST"],
                    "pos": pos_map.get((team, clean_name), ""),
                    "cls": class_map.get((team, _height_player_key(clean_name)), ""),
                    "fm": 0 if adv_eligible else 1,  # 1 = unreliable ("false") minutes team
                    "ind_ortg": _adv.get("ind_ortg"),
                    "ind_drtg": _adv.get("ind_drtg"),
                    "efg_pct": _efg,
                    "ts_pct": _ts,
                    "usage_pct": _adv.get("usage_pct"),
                    "shot_pct": _adv.get("shot_pct"),
                    "oreb_pct": _adv.get("oreb_pct"),
                    "dreb_pct": _adv.get("dreb_pct"),
                    "tov_pct": _adv.get("tov_pct"),
                    "ast_rate": _adv.get("ast_rate"),
                    "blk_pct": _adv.get("blk_pct"),
                    "stl_pct": _adv.get("stl_pct"),
                    "ft_rate": _ftr,
                    "fc_per_40": _adv.get("fc_per_40"),
                    "fd_per_40": _adv.get("fd_per_40"),
                    "bpm_gp": bpm_row.get("bpm_gp"),
                    "obpm": bpm_row.get("obpm"),
                    "dbpm": bpm_row.get("dbpm"),
                    "bpm": bpm_row.get("bpm"),
                    "vorp": bpm_row.get("vorp"),
                    "pprod": _adv.get("pprod"), "scposs": _adv.get("scposs"),
                    "_wsb": t,  # raw totals for Win Shares / PER; removed after attach_win_shares_per
                    "gs": gs_map.get(clean_name, 0),
                })

    # Default sort by PPG descending
    players.sort(key=lambda x: -x["ppg"])
    return players


def _load_player_heights() -> dict:
    """(team, height-player-key) -> formatted height from the 2025-26 CSV."""
    out = {}
    if not _HEIGHTS_CSV.exists():
        return out
    all_teams = [t for info in CONFERENCES.values() for t in info["teams"]]
    canonical_by_key = {_height_team_key(name): name for name in all_teams}
    manual_team_map = {
        "2025": "Irvine Valley",
        "Men’s Basketball": "Los Medanos",
        "Team": "Monterey Peninsula",
    }

    def resolve_team(raw_team):
        if raw_team in manual_team_map:
            return manual_team_map[raw_team]
        raw_key = _height_team_key(raw_team)
        if raw_key in canonical_by_key:
            return canonical_by_key[raw_key]
        candidates = [(len(k), t) for k, t in canonical_by_key.items()
                      if k and (k in raw_key or raw_key in k)]
        return sorted(candidates, reverse=True)[0][1] if candidates else None

    with open(_HEIGHTS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            team_name = resolve_team(row.get("team", ""))
            inches = _parse_height_to_inches(row.get("height", ""))
            if team_name and inches:
                out[(team_name, _height_player_key(row.get("player", "")))] = _fmt_height_inches(inches)
    return out


_CLASS_CSV = Path("internal_data/player_class_2025_26.csv")


def _load_player_class() -> dict:
    """(team, height-player-key) -> roster class ('Fr'/'So') from the 2025-26 CSV.

    Reads the dedicated internal_data/player_class_2025_26.csv (team, player,
    class), reusing the same team/name reconciliation as heights since both come
    from the same scraped roster source. Class is current-season only and covers
    only the teams whose roster pages were scrapeable (AWS WAF blocks some), so
    players without a class entry simply have cls=''."""
    out = {}
    if not _CLASS_CSV.exists():
        return out
    all_teams = [t for info in CONFERENCES.values() for t in info["teams"]]
    canonical_by_key = {_height_team_key(name): name for name in all_teams}
    manual_team_map = {
        "2025": "Irvine Valley",
        "Men’s Basketball": "Los Medanos",
        "Team": "Monterey Peninsula",
    }

    def resolve_team(raw_team):
        if raw_team in manual_team_map:
            return manual_team_map[raw_team]
        raw_key = _height_team_key(raw_team)
        if raw_key in canonical_by_key:
            return canonical_by_key[raw_key]
        candidates = [(len(k), t) for k, t in canonical_by_key.items()
                      if k and (k in raw_key or raw_key in k)]
        return sorted(candidates, reverse=True)[0][1] if candidates else None

    with open(_CLASS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            klass = (row.get("class") or "").strip()
            if not klass:
                continue
            team_name = resolve_team(row.get("team", ""))
            if team_name:
                out[(team_name, _height_player_key(row.get("player", "")))] = klass
    return out


def load_full_rosters(stats_dir=None):
    """Every player on every team, no minutes qualification (Team Stats panel).

    Advanced fields ship only for teams passing the same 18-clean-game /
    real-minutes checks the leaderboards use; other teams get adv: 0 and the
    panel renders '—' for every advanced column.
    """
    if stats_dir is None:
        stats_dir = STATS_DIR
    heights = _load_player_heights() if Path(stats_dir) == Path(STATS_DIR) else {}
    rosters = {}
    for conf_name, conf_info in CONFERENCES.items():
        for team in conf_info["teams"]:
            team_dir = _find_team_stats_dir(stats_dir, conf_name, team)
            summary_path = team_dir / "team_summary.json"
            player_path = team_dir / "player_stats.json"
            if not summary_path.exists() or not player_path.exists():
                continue
            summary = json.load(open(summary_path))
            pdata = json.load(open(player_path))
            adv_path = team_dir / "advanced_analytics.json"
            adv_data = json.load(open(adv_path)) if adv_path.exists() else {"players": []}
            adv_map = {re.sub(r'^#\d+\s+', '', p["name"]): p for p in adv_data.get("players", [])}

            games_played = summary["games_played"]
            total_player_min = sum(p["totals"]["MIN"] for p in pdata["players"])
            avg_player_min_pg = total_player_min / games_played if games_played > 0 else 0
            is_fake = avg_player_min_pg < 100
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
            adv_eligible = not is_fake and clean_games >= 18

            rows = []
            for p in pdata["players"]:
                t = p["totals"]
                g = t["games"]
                if g == 0:
                    continue
                clean_name = re.sub(r'^#\d+\s+', '', p["name"])
                _adv = adv_map.get(clean_name, {}) if adv_eligible else {}
                # eFG%/TS% are minutes-independent: always computable for the
                # Basic table even when the team fails the clean-minutes
                # checks (the Advanced table still dashes them via adv: 0).
                _efg = _adv.get("efg_pct")
                if _efg is None:
                    _efg = round((t["FGM"] + 0.5 * t["3PM"]) / t["FGA"] * 100, 1) if t["FGA"] > 0 else 0.0
                _ts = _adv.get("ts_pct")
                if _ts is None:
                    _ts_denom = 2 * (t["FGA"] + 0.475 * t["FTA"])
                    _ts = round(t["PTS"] / _ts_denom * 100, 1) if _ts_denom > 0 else 0.0
                rows.append({
                    "name": _display_name(clean_name),
                    "ht": heights.get((team, _height_player_key(clean_name)), ""),
                    "gp": g,
                    "mpg": round(t["MIN"] / g, 1),
                    "min_pct": round(t["MIN"] / (40 * games_played) * 100, 1) if games_played > 0 else None,
                    "ppg": round(t["PTS"] / g, 1),
                    "orpg": round(t["OREB"] / g, 1), "drpg": round(t["DREB"] / g, 1),
                    "rpg": round(t["REB"] / g, 1), "apg": round(t["AST"] / g, 1),
                    "spg": round(t["STL"] / g, 1), "bpg": round(t["BLK"] / g, 1),
                    "topg": round(t["TO"] / g, 1),
                    "fgm": t["FGM"], "fga": t["FGA"],
                    "fgp": round(t["FGM"] / t["FGA"] * 100, 1) if t["FGA"] else 0.0,
                    "twom": t["FGM"] - t["3PM"], "twoa": t["FGA"] - t["3PA"],
                    "twop": round((t["FGM"] - t["3PM"]) / (t["FGA"] - t["3PA"]) * 100, 1) if (t["FGA"] - t["3PA"]) > 0 else 0.0,
                    "tpm": t["3PM"], "tpa": t["3PA"],
                    "tpp": round(t["3PM"] / t["3PA"] * 100, 1) if t["3PA"] else 0.0,
                    "ftm": t["FTM"], "fta": t["FTA"],
                    "ftp": round(t["FTM"] / t["FTA"] * 100, 1) if t["FTA"] else 0.0,
                    "ind_ortg": _adv.get("ind_ortg"), "usage_pct": _adv.get("usage_pct"),
                    "shot_pct": _adv.get("shot_pct"), "efg_pct": _efg,
                    "ts_pct": _ts, "oreb_pct": _adv.get("oreb_pct"),
                    "dreb_pct": _adv.get("dreb_pct"), "ast_rate": _adv.get("ast_rate"),
                    "tov_pct": _adv.get("tov_pct"), "blk_pct": _adv.get("blk_pct"),
                    "stl_pct": _adv.get("stl_pct"), "fc_per_40": _adv.get("fc_per_40"),
                    "fd_per_40": _adv.get("fd_per_40"), "ft_rate": _adv.get("ft_rate"),
                })
            rows.sort(key=lambda r: -r["ppg"])
            rosters[team] = {"adv": 1 if adv_eligible else 0, "players": rows}
    return rosters


_BENCH_POINTS_CACHE = {}


def load_all_bench_points(season="2025-26", base_dir="."):
    """League-wide SEASON bench scoring in one pass over the box scores.
    Returns {team: {bench_pts, total_pts, games, clean_bench_pts, clean_bench_min,
    clean_games}} from non-starter PTS, using only games that carry is_starter flags.
    Per-40 projection uses ONLY "clean-minutes" games (team MIN sum >= 150 and no
    player who scored with 0 minutes) since box-score minutes are often missing.
    Dedups by (team, date) since each box file appears under both teams' folders."""
    if season in _BENCH_POINTS_CACHE:
        return _BENCH_POINTS_CACHE[season]
    import glob as _glob
    import os as _os
    out, seen = {}, {}
    pattern = _os.path.join(base_dir, f"{season} Teams Schedules", "**", "*", "[0-9]*.json")
    for f in _glob.glob(pattern, recursive=True):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        teams = d.get("teams")
        if not isinstance(teams, dict):
            continue
        base = _os.path.basename(f)
        key = base[:8] if base[:8].isdigit() else ""
        if not key:
            continue
        for tname, roster in teams.items():
            if not isinstance(roster, list) or not any("is_starter" in p for p in roster):
                continue
            if key in seen.get(tname, set()):
                continue
            seen.setdefault(tname, set()).add(key)
            tot = bench = bmin = tmin = 0
            zero_scorer = False
            for p in roster:
                st = p.get("stats", {}) or {}
                try:
                    pts = int(st.get("PTS", 0) or 0)
                except (ValueError, TypeError):
                    pts = 0
                try:
                    mn = float(st.get("MIN", 0) or 0)
                except (ValueError, TypeError):
                    mn = 0
                tot += pts
                tmin += mn
                if pts > 0 and mn == 0:
                    zero_scorer = True   # scored but no minutes recorded -> dirty minutes
                if not p.get("is_starter"):
                    bench += pts
                    bmin += mn
            if tot <= 0:
                continue
            a = out.setdefault(tname, {"bench_pts": 0, "total_pts": 0, "games": 0,
                                       "clean_bench_pts": 0, "clean_bench_min": 0, "clean_games": 0})
            a["bench_pts"] += bench
            a["total_pts"] += tot
            a["games"] += 1
            if tmin >= 150 and not zero_scorer:   # clean-minutes game
                a["clean_bench_pts"] += bench
                a["clean_bench_min"] += bmin
                a["clean_games"] += 1
    _BENCH_POINTS_CACHE[season] = out
    return out


def load_teams(stats_dir=None):
    """Load team-level stats and advanced analytics for all teams."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    teams = []
    _sm = re.search(r'(\d{4}-\d{2})', str(stats_dir))
    bench_points = load_all_bench_points(_sm.group(1) if _sm else "2025-26")
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

            _bp = bench_points.get(team, {})
            _bpts, _btot = _bp.get("bench_pts", 0), _bp.get("total_pts", 0)
            _bg = _bp.get("games", 0) or 1
            _cbpts, _cbmin = _bp.get("clean_bench_pts", 0), _bp.get("clean_bench_min", 0)
            _poss_pg = ta.get("possessions", 0)
            bench_fields = {
                "bench_pts": _bpts,                                            # season total
                "bench_ppg": round(_bpts / _bg, 1),                            # per game
                "bench_pct": round(100 * _bpts / _btot, 1) if _btot else 0.0,  # % of team points
                "bench_per100": round(_bpts / (_poss_pg * _bg) * 100, 1) if (_poss_pg * _bg) > 0 else 0.0,
                # projected over 40 min of bench court time, CLEAN-minutes games only (null if none)
                "bench_per40": round(_cbpts / _cbmin * 40, 1) if _cbmin > 0 else None,
                "bench_clean_games": _bp.get("clean_games", 0),
            }
            teams.append({
                "team": team,
                **bench_fields,
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

    # Center OPP ADJ on the league. The raw slope (from advanced_analytics.json)
    # is systematically negative for ~all teams because the expected-margin model
    # under-predicts how much margins move with opponent quality, so ~96/100 land
    # negative. OPP ADJ is a comparative metric — re-center on the league mean so
    # positive = plays UP to competition MORE than a typical team (≈half each).
    _oa = [t["opp_adjust"] for t in teams if t.get("opp_adjust")]
    if _oa:
        _oa_mean = sum(_oa) / len(_oa)
        for t in teams:
            if t.get("opp_adjust"):
                t["opp_adjust"] = round(t["opp_adjust"] - _oa_mean, 3)

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
    """Load conference-only qualified players from all teams (30% minutes threshold)."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    pos_map = _load_player_positions(_STATS_DIR_TO_SEASON.get(str(stats_dir), "2025-26"))
    class_map = _load_player_class() if Path(stats_dir) == Path(STATS_DIR) else {}
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
            min_threshold = team_total_min * 0.30

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
                fake_mpg_cutoff = avg_player_min_pg / 5 * 0.30

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
                # Same minutes-independent fallbacks as load_players: eFG%,
                # TS%, and FT rate are computed from conference totals when the
                # team fails the clean-minutes checks.
                _fga, _fta = t["FGA"], t["FTA"]
                _efg = _adv.get("efg_pct")
                if _efg is None:
                    _efg = round((t["FGM"] + 0.5 * t["3PM"]) / _fga * 100, 1) if _fga > 0 else 0.0
                _ts = _adv.get("ts_pct")
                if _ts is None:
                    _ts_denom = 2 * (_fga + 0.475 * _fta)
                    _ts = round(t["PTS"] / _ts_denom * 100, 1) if _ts_denom > 0 else 0.0
                _ftr = _adv.get("ft_rate")
                if _ftr is None:
                    _ftr = round(_fta / _fga * 100, 1) if _fga > 0 else 0.0
                players.append({
                    "name": _display_name(clean_name),
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
                    "tpa_rate": round(t["3PA"] / t["FGA"] * 100, 1) if t["FGA"] else None,
                    "ftm": t["FTM"], "fta": t["FTA"],
                    "ftp": round(t["FTM"] / t["FTA"] * 100, 1) if t["FTA"] else 0.0,
                    "pts": t["PTS"],
                    "reb": t["REB"],
                    "ast": t["AST"],
                    "pos": pos_map.get((team, clean_name), ""),
                    "cls": class_map.get((team, _height_player_key(clean_name)), ""),
                    "fm": 0 if adv_eligible else 1,  # 1 = unreliable ("false") minutes team
                    "ind_ortg": _adv.get("ind_ortg"),
                    "ind_drtg": _adv.get("ind_drtg"),
                    "efg_pct": _efg,
                    "ts_pct": _ts,
                    "usage_pct": _adv.get("usage_pct"),
                    "shot_pct": _adv.get("shot_pct"),
                    "oreb_pct": _adv.get("oreb_pct"),
                    "dreb_pct": _adv.get("dreb_pct"),
                    "tov_pct": _adv.get("tov_pct"),
                    "ast_rate": _adv.get("ast_rate"),
                    "blk_pct": _adv.get("blk_pct"),
                    "stl_pct": _adv.get("stl_pct"),
                    "ft_rate": _ftr,
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
            "opp_adjust_n": len(_opp_pairs),
            "pace_adjust": _reg_slope(_pace_pairs),
        }

    # Center opp_adjust on the league. The raw slope = slope(actual margin vs opp
    # strength) + 0.67; because actual margins are ~1.05x as opponent-sensitive as
    # the 0.67 model assumes, the raw slope is systematically negative for almost
    # every team (96/100 in 2025-26). OPP ADJ is a *comparative* metric (red/blue
    # bars), so subtract the league-mean slope: positive = plays UP to competition
    # MORE than a typical team, negative = plays down more. Teams with <5 conf
    # games (no reliable slope) are left at 0 / neutral.
    _oa_valid = [v["opp_adjust"] for v in conf_adjustments.values() if v["opp_adjust_n"] >= 5]
    if _oa_valid:
        _oa_mean = sum(_oa_valid) / len(_oa_valid)
        for v in conf_adjustments.values():
            v["opp_adjust"] = round(v["opp_adjust"] - _oa_mean, 3) if v["opp_adjust_n"] >= 5 else 0.0

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


_BOX_KEYS = ["FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "OREB", "DREB", "REB",
             "AST", "STL", "BLK", "TO", "PF", "PTS"]


def _subset_games(games, subset):
    """Pick a subset of ordered game_log entries. Playoffs = games after the last
    conference game; last5/last10 = the most recent N games."""
    if not games:
        return []
    if subset == "last5":
        return games[-5:]
    if subset == "last10":
        return games[-10:]
    if subset == "playoffs":
        last_conf = -1
        for i, g in enumerate(games):
            if g.get("is_conference"):
                last_conf = i
        return games[last_conf + 1:] if 0 <= last_conf < len(games) - 1 else []
    return []


def load_subset_teams(stats_dir=None, subset="last10"):
    """Box-derived team dataset over a game subset, recomputed from game_log
    per-game team + opponent box totals. Reliable (no minutes/model dependency):
    ratings, four factors, and per-game/per-100 box stats — the full team chart pool."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    teams = []
    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team in conf_info["teams"]:
            team_dir = _find_team_stats_dir(stats_dir, conf_name, team)
            gl_path = team_dir / "game_log.json"
            if not gl_path.exists():
                continue
            try:
                games = json.load(open(gl_path)).get("games", [])
            except Exception:
                continue
            sub = _subset_games(games, subset)
            if not sub:
                continue
            gp = len(sub)
            tt = {k: 0 for k in _BOX_KEYS}
            ot = {k: 0 for k in _BOX_KEYS}
            for g in sub:
                ts, os_ = g.get("team_stats") or {}, g.get("opponent_stats") or {}
                for k in _BOX_KEYS:
                    tt[k] += ts.get(k, 0) or 0
                    ot[k] += os_.get(k, 0) or 0
            poss = max(tt["FGA"] - tt["OREB"] + tt["TO"] + 0.475 * tt["FTA"], 1.0)
            opp_poss = max(ot["FGA"] - ot["OREB"] + ot["TO"] + 0.475 * ot["FTA"], 1.0)
            ortg = round(tt["PTS"] / poss * 100, 1)
            drtg = round(ot["PTS"] / opp_poss * 100, 1)
            pg = lambda v: round(v / gp, 1)

            def _shoot(t):
                return {
                    "efg": round((t["FGM"] + 0.5 * t["3PM"]) / t["FGA"] * 100, 1) if t["FGA"] else 0.0,
                    "ts": round(t["PTS"] / (2 * (t["FGA"] + 0.44 * t["FTA"])) * 100, 1) if (t["FGA"] + t["FTA"]) else 0.0,
                    "twop": round((t["FGM"] - t["3PM"]) / (t["FGA"] - t["3PA"]) * 100, 1) if (t["FGA"] - t["3PA"]) > 0 else 0.0,
                    "tpp": round(t["3PM"] / t["3PA"] * 100, 1) if t["3PA"] else 0.0,
                    "ftp": round(t["FTM"] / t["FTA"] * 100, 1) if t["FTA"] else 0.0,
                    "ftr": round(t["FTA"] / t["FGA"] * 100, 1) if t["FGA"] else 0.0,
                    "tpar": round(t["3PA"] / t["FGA"] * 100, 1) if t["FGA"] else 0.0,
                }
            sh, osh = _shoot(tt), _shoot(ot)
            teams.append({
                "team": team, "region": region, "conference": conf_name, "gp": gp,
                "ppg": pg(tt["PTS"]), "opp_ppg": pg(ot["PTS"]),
                "rpg": pg(tt["REB"]), "opp_rpg": pg(ot["REB"]),
                "orebpg": pg(tt["OREB"]), "opp_orebpg": pg(ot["OREB"]),
                "drebpg": pg(tt["DREB"]), "opp_drebpg": pg(ot["DREB"]),
                "apg": pg(tt["AST"]), "opp_apg": pg(ot["AST"]),
                "spg": pg(tt["STL"]), "opp_spg": pg(ot["STL"]),
                "bpg": pg(tt["BLK"]), "opp_bpg": pg(ot["BLK"]),
                "topg": pg(tt["TO"]), "opp_topg": pg(ot["TO"]),
                "pfpg": pg(tt["PF"]), "opp_pfpg": pg(ot["PF"]),
                "totals": tt, "opp_totals": ot,
                "possessions": round((poss + opp_poss) / 2 / gp, 1),
                "ortg": ortg, "drtg": drtg, "net_rtg": round(ortg - drtg, 1),
                "tempo": round((poss + opp_poss) / 2 / gp, 1),
                "ts_pct": sh["ts"], "efg_pct": sh["efg"], "twop": sh["twop"], "tpp": sh["tpp"], "ftp": sh["ftp"],
                "ft_rate": sh["ftr"], "tpa_pct": sh["tpar"],
                "ast_pct": round(tt["AST"] / poss * 100, 1),
                "tov_pct": round(tt["TO"] / poss * 100, 1),
                "oreb_pct": round(tt["OREB"] / (tt["OREB"] + ot["DREB"]) * 100, 1) if (tt["OREB"] + ot["DREB"]) else 0.0,
                "dreb_pct": round(tt["DREB"] / (tt["DREB"] + ot["OREB"]) * 100, 1) if (tt["DREB"] + ot["OREB"]) else 0.0,
                "stl_pct": round(tt["STL"] / opp_poss * 100, 1),
                "blk_pct": round(tt["BLK"] / ot["FGA"] * 100, 1) if ot["FGA"] else 0.0,
                "opp_ts_pct": osh["ts"], "opp_efg_pct": osh["efg"], "opp_twop": osh["twop"], "opp_tpp": osh["tpp"], "opp_ftp": osh["ftp"],
                "opp_ft_rate": osh["ftr"], "opp_tpa_pct": osh["tpar"],
                "opp_tov_pct": round(ot["TO"] / opp_poss * 100, 1),
            })
    teams.sort(key=lambda x: -x["net_rtg"])
    return teams


def _parse_ma(s):
    """Parse a 'made-att' box field like '3-6' -> (3.0, 6.0)."""
    try:
        a, b = str(s or "0-0").split("-")
        return float(a or 0), float(b or 0)
    except Exception:
        return 0.0, 0.0


def load_subset_players(stats_dir=None, subset="last10"):
    """Box-derived player dataset over a game subset. Recomputes the
    minutes-independent box stats (per-game counting, shooting %s, eFG/TS/FT-rate,
    ratios) from the subset's box scores. Model/minutes metrics (usage, BPM, PER,
    WS) are intentionally absent here — they don't subset reliably over 5-10 games."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    import glob as _glob
    season = _STATS_DIR_TO_SEASON.get(str(stats_dir), "2025-26")
    pos_map = _load_player_positions(season)
    def _dkey(yyyymmdd):
        return yyyymmdd if (yyyymmdd or "").isdigit() else ""
    players = []
    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team in conf_info["teams"]:
            team_dir = _find_team_stats_dir(stats_dir, conf_name, team)
            gl_path = team_dir / "game_log.json"
            if not gl_path.exists():
                continue
            try:
                games = json.load(open(gl_path)).get("games", [])
            except Exception:
                continue
            sub = _subset_games(games, subset)
            if not sub:
                continue
            # dates of the subset games, normalized to YYYYMMDD
            want = set()
            for g in sub:
                p = (g.get("date") or "").split("/")
                if len(p) == 3:
                    want.add(f"{int(p[2]):04d}{int(p[0]):02d}{int(p[1]):02d}")
            if not want:
                continue
            # aggregate player box stats over the subset's box scores
            agg = {}
            for f in _glob.glob(f"{season} Teams Schedules/**/{team}/*/[0-9]*.json", recursive=True):
                import os as _os
                d8 = _os.path.basename(_os.path.dirname(f))[:8]
                if d8 not in want:
                    continue
                try:
                    box = json.load(open(f))
                except Exception:
                    continue
                roster = (box.get("teams") or {}).get(team)
                if not isinstance(roster, list):
                    continue
                for pl in roster:
                    nm = re.sub(r'^#\d+\s+', '', pl.get("name", "")).strip()
                    if not nm:
                        continue
                    st = pl.get("stats", {}) or {}
                    a = agg.setdefault(nm, {k: 0.0 for k in ["g", "MIN", "PTS", "REB", "OREB", "DREB", "AST", "STL", "BLK", "TO", "PF", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA"]})
                    a["g"] += 1
                    try:
                        a["MIN"] += float(st.get("MIN", 0) or 0)
                    except Exception:
                        pass
                    for k in ["PTS", "REB", "OREB", "DREB", "AST", "STL", "BLK", "TO", "PF"]:
                        try:
                            a[k] += float(st.get(k, 0) or 0)
                        except Exception:
                            pass
                    fgm, fga = _parse_ma(st.get("FGM-A")); a["FGM"] += fgm; a["FGA"] += fga
                    tpm, tpa = _parse_ma(st.get("3PM-A")); a["3PM"] += tpm; a["3PA"] += tpa
                    ftm, fta = _parse_ma(st.get("FTM-A")); a["FTM"] += ftm; a["FTA"] += fta
            gp_sub = len(sub)
            for nm, t in agg.items():
                g = t["g"]
                if g == 0:
                    continue
                fga, fta = t["FGA"], t["FTA"]
                pg = lambda v: round(v / g, 1)
                players.append({
                    "name": _display_name(nm), "school": team, "region": region, "conference": conf_name,
                    "q": 1 if g >= max(1, gp_sub // 2) else 0,   # rotation player in the window
                    "gp": int(g), "mpg": round(t["MIN"] / g, 1) if t["MIN"] else 0,
                    "ppg": pg(t["PTS"]), "rpg": pg(t["REB"]), "orpg": pg(t["OREB"]), "drpg": pg(t["DREB"]),
                    "apg": pg(t["AST"]), "spg": pg(t["STL"]), "bpg": pg(t["BLK"]), "topg": pg(t["TO"]),
                    "fgm": t["FGM"], "fga": fga,
                    "fgp": round(t["FGM"] / fga * 100, 1) if fga else 0.0,
                    "twom": t["FGM"] - t["3PM"], "twoa": fga - t["3PA"],
                    "twop": round((t["FGM"] - t["3PM"]) / (fga - t["3PA"]) * 100, 1) if (fga - t["3PA"]) > 0 else 0.0,
                    "tpm": t["3PM"], "tpa": t["3PA"],
                    "tpp": round(t["3PM"] / t["3PA"] * 100, 1) if t["3PA"] else 0.0,
                    "tpa_rate": round(t["3PA"] / fga * 100, 1) if fga else None,
                    "ftm": t["FTM"], "fta": fta,
                    "ftp": round(t["FTM"] / fta * 100, 1) if fta else 0.0,
                    "ft_rate": round(fta / fga * 100, 1) if fga else 0.0,
                    "efg_pct": round((t["FGM"] + 0.5 * t["3PM"]) / fga * 100, 1) if fga else 0.0,
                    "ts_pct": round(t["PTS"] / (2 * (fga + 0.475 * fta)) * 100, 1) if (fga + fta) else 0.0,
                    "ast_tov": round(t["AST"] / t["TO"], 2) if t["TO"] else 0.0,
                    "stl_tov": round(t["STL"] / t["TO"], 2) if t["TO"] else 0.0,
                    "pts": t["PTS"], "reb": t["REB"], "ast": t["AST"],
                    "pos": pos_map.get((team, nm), ""), "fm": 0,
                })
    players.sort(key=lambda x: -x["ppg"])
    return players


def build_conference_four_factors(stats_dir) -> dict:
    """Aggregate team box totals by conference for the Conferences sub-tab.

    For each conference, sum raw box totals across all member teams' games,
    split into three scopes (nonconf / conf / full), then compute team and
    opponent Four Factors + ORtg/DRtg/NetRtg + W/L from the summed totals.
    Possessions use the project-standard 0.475-FTA formula. Returns
    {scope: [conf_row, ...]} sorted by net rating descending."""
    scopes = ("nonconf", "conf", "full")
    keys = ("FGM", "FGA", "3PM", "FTA", "OREB", "DREB", "TO", "PTS",
            "oFGM", "oFGA", "o3PM", "oFTA", "oOREB", "oDREB", "oTO", "oPTS", "w", "l")
    acc = {s: {} for s in scopes}
    for conf_name, conf_info in CONFERENCES.items():
        for team in conf_info["teams"]:
            team_dir = _find_team_stats_dir(stats_dir, conf_name, team)
            gl = team_dir / "game_log.json"
            if not gl.exists():
                continue
            try:
                games = json.load(open(gl)).get("games", [])
            except Exception:
                continue
            for g in games:
                ts = g.get("team_stats") or {}
                os_ = g.get("opponent_stats") or {}
                is_conf = bool(g.get("is_conference", False))
                r = g.get("result")
                # W/L is a fact regardless of box availability — count it for every
                # game so the conference record stays complete and balanced (within
                # a conference every win is a member's loss). Four-factor box totals
                # only accumulate from games that actually have usable box scores.
                usable = bool(ts) and bool(os_) and ts.get("FGA", 0) > 0
                for s in ("full", "conf" if is_conf else "nonconf"):
                    a = acc[s].setdefault(conf_name, {k: 0.0 for k in keys})
                    if r == "W":
                        a["w"] += 1
                    elif r == "L":
                        a["l"] += 1
                    if not usable:
                        continue
                    for k in ("FGM", "FGA", "3PM", "FTA", "OREB", "DREB", "TO", "PTS"):
                        a[k] += ts.get(k, 0)
                    for k, sk in (("oFGM", "FGM"), ("oFGA", "FGA"), ("o3PM", "3PM"),
                                  ("oFTA", "FTA"), ("oOREB", "OREB"), ("oDREB", "DREB"),
                                  ("oTO", "TO"), ("oPTS", "PTS")):
                        a[k] += os_.get(sk, 0)

    def pct(n, d):
        return round(n / d * 100, 1) if d else 0.0

    out = {}
    for s in scopes:
        rows = []
        for conf_name, a in acc[s].items():
            poss = a["FGA"] - a["OREB"] + a["TO"] + 0.475 * a["FTA"]
            opp_poss = a["oFGA"] - a["oOREB"] + a["oTO"] + 0.475 * a["oFTA"]
            if poss <= 0 or opp_poss <= 0:
                continue
            w, l = int(a["w"]), int(a["l"])
            g = w + l
            rows.append({
                "conf": conf_name,
                "region": CONFERENCES[conf_name]["region"],
                "w": w, "l": l,
                "win_pct": round(w / g, 3) if g else 0.0,
                "ortg": round(a["PTS"] / poss * 100, 1),
                "drtg": round(a["oPTS"] / opp_poss * 100, 1),
                "net": round((a["PTS"] / poss - a["oPTS"] / opp_poss) * 100, 1),
                "efg": pct(a["FGM"] + 0.5 * a["3PM"], a["FGA"]),
                "orb": pct(a["OREB"], a["OREB"] + a["oDREB"]),
                "tov": pct(a["TO"], a["FGA"] + 0.475 * a["FTA"] + a["TO"]),
                "ftr": pct(a["FTA"], a["FGA"]),
                "d_efg": pct(a["oFGM"] + 0.5 * a["o3PM"], a["oFGA"]),
                "d_orb": pct(a["oOREB"], a["oOREB"] + a["DREB"]),
                "d_tov": pct(a["oTO"], a["oFGA"] + 0.475 * a["oFTA"] + a["oTO"]),
                "d_ftr": pct(a["oFTA"], a["oFGA"]),
            })
        rows.sort(key=lambda r: r["net"], reverse=True)
        out[s] = rows
    return out


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


def infer_champion(stats_dir: Path) -> str | None:
    """Infer the champion from the winner of the final dated game in the season data."""
    if stats_dir == STATS_DIR_2019:
        return None
    try:
        m = re.match(r"(\d{4})-(\d{2})", stats_dir.name)
        expected_final_year = int(m.group(1)[:2] + m.group(2)) if m else None
        by_team, team_names = _sl_load_games(stats_dir)
        games = _sl_dedupe(by_team, team_names, exclude_zero=True)
        if expected_final_year:
            games = [g for g in games if g["date_obj"].year == expected_final_year]
        if not games:
            return None
        final_date = max(g["date_obj"] for g in games)
        final_games = [g for g in games if g["date_obj"] == final_date]
        if len(final_games) != 1:
            return None
        return final_games[0].get("winner")
    except Exception:
        return None


def _player_key(name: str) -> str:
    cleaned = re.sub(r"^#\s*\d+\s+", "", str(name or "")).strip()
    cleaned = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?$", "", cleaned, flags=re.I).strip()
    return re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()


def attach_player_jerseys(players, season_dir="2025-26 Teams Schedules"):
    """Add jersey numbers to aggregate player rows from the saved box scores."""
    if not players:
        return
    schedule_root = Path(season_dir)
    if not schedule_root.exists():
        return
    jersey_by_team_player = {}
    for path in schedule_root.rglob("*.json"):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        teams = data.get("teams") if isinstance(data, dict) else None
        if not isinstance(teams, dict):
            continue
        for team_name, team_players in teams.items():
            if not isinstance(team_players, list):
                continue
            for row in team_players:
                raw_name = str(row.get("name", "") if isinstance(row, dict) else "")
                match = re.match(r"^#\s*(\d+)\s+(.+)$", raw_name.strip())
                if not match:
                    continue
                key = (team_name, _player_key(match.group(2)))
                jersey_by_team_player.setdefault(key, match.group(1))
    for player in players:
        if not isinstance(player, dict) or player.get("jersey"):
            continue
        jersey = jersey_by_team_player.get((player.get("school"), _player_key(player.get("name"))))
        if jersey is not None:
            player["jersey"] = jersey


SEASON_DATA_DIR = "season_data"

# Shooting-qualification thresholds for the eFG% / TS% leaderboards and charts.
# Intent: a floor that simulates the shot volume of a typical player at the
# 50% min% standard those categories use. Derived June 2026 as the MEDIAN
# attempts per game of players in the 45-55% min% band, clean-minutes teams
# only, across all eight scraped seasons with the corrected (rescraped)
# 2018-19 data (n=750 player-seasons):
#   median FGA per game         = 6.98  -> 7.0
#   median (FGA + FTA) per game = 9.18  -> 9.2
# Recompute when a season is added: median of fga/gp and (fga+fta)/gp over
# players with 45 <= min_pct <= 55 and fm == 0 in the season player datasets.
EFG_FGA_PER_GAME_MIN = 7.0
TS_ATT_PER_GAME_MIN = 9.2


def _jc(obj):
    """Compact JSON (no whitespace) for embedding in generated HTML/JS."""
    return json.dumps(obj, separators=(",", ":"))


def _pack_rows(node):
    """Recursively pack uniform lists of dicts into a columnar form.

    A list of >=4 dicts that all share the same key order becomes
    {"__c": [keys], "__r": [[values], ...]} so the key names are stored once
    instead of once per row. The JS __unpack() helper reverses this exactly,
    so the encoding is lossless (values, nulls, and key order preserved).
    Non-uniform lists are left as plain objects.
    """
    if isinstance(node, list):
        items = [_pack_rows(x) for x in node]
        if len(items) >= 4 and all(isinstance(x, dict) and "__c" not in x for x in items):
            keys = tuple(items[0].keys())
            if all(tuple(x.keys()) == keys for x in items[1:]):
                return {"__c": list(keys), "__r": [[x[k] for k in keys] for x in items]}
        return items
    if isinstance(node, dict):
        return {k: _pack_rows(v) for k, v in node.items()}
    return node


def _embed(obj):
    """Serialize a dataset for embedding: columnar-packed + compact JSON."""
    return _jc(_pack_rows(obj))


def _slim_games(teams):
    """Null out per-game fields the JS side can re-derive (__fixGames).

    pace/tempo are nulled when equal to possessions, canonical_opponent when
    equal to opponent, and result when it matches the score comparison. Only
    redundant values are dropped; the rare games where these fields genuinely
    differ keep their original values.
    """
    out = []
    for t in teams or []:
        grs = t.get("game_ratings")
        if not isinstance(grs, list):
            out.append(t)
            continue
        t = dict(t)
        slim = []
        for g in grs:
            g = dict(g)
            poss = g.get("possessions")
            if poss is not None and g.get("pace") == poss:
                g["pace"] = None
            if poss is not None and g.get("tempo") == poss:
                g["tempo"] = None
            if g.get("canonical_opponent") == g.get("opponent"):
                g["canonical_opponent"] = None
            ts, os_ = g.get("team_score"), g.get("opponent_score")
            if isinstance(ts, (int, float)) and isinstance(os_, (int, float)):
                if g.get("result") == ("W" if ts > os_ else "L"):
                    g["result"] = None
            slim.append(g)
        t["game_ratings"] = slim
        out.append(t)
    return out


def _strip_conf_games(conf_teams):
    """Drop game_ratings from conference-only team records.

    Verified across all seasons: every conference game_ratings entry is an
    exact projection of the full team's game_ratings filtered to
    is_conference, so the JS side rebuilds them (__deriveConfGames) from the
    full team data instead of shipping them twice.
    """
    out = []
    for t in conf_teams or []:
        if "game_ratings" in t:
            t = {k: v for k, v in t.items() if k != "game_ratings"}
        out.append(t)
    return out


def attach_porpagatu(players, teams):
    """Attach Torvik's PORPAGATU! to player rows (field: porp).

    Implements the final 2019 formula from barttorvik.com/porpagatu.html
    verbatim, with CCC league context:
        o_adj    = avg_eff / opponents' avg defensive efficiency
        uFactor  = Usage * -0.144 + 13.023
        xORtg    = avg_eff + (ORtg - avg_eff) / uFactor * 10.143
        adjoe    = (xORtg + (Usage - 20) * slope) * o_adj
                   slope = 1.25 above 20 usage, 1.5 below
        porp     = (adjoe + (104.9 - avg_eff) - 88) * Min% * 69.4 / 500
    The 104.9 normalization / 88 replacement / 69.4 tempo constants are kept
    verbatim so CCC values land on the same scale as T-Rank's. avg_eff is the
    CCC season's mean team efficiency; SOS uses opponents' season defensive
    efficiency (in-system games). Null for players without reliable minutes.
    """
    valid = [t for t in (teams or []) if (t.get("ortg") or 0) > 0 and (t.get("drtg") or 0) > 0]
    if not valid or not players:
        return
    avg_eff = sum(t["ortg"] for t in valid) / len(valid)
    drtg_by_team = {t["team"]: t["drtg"] for t in valid}
    sos = {}
    for t in valid:
        opp_des = []
        for g in t.get("game_ratings", []):
            d = drtg_by_team.get(g.get("canonical_opponent") or g.get("opponent"))
            if d:
                opp_des.append(d)
        sos[t["team"]] = (avg_eff / (sum(opp_des) / len(opp_des))) if opp_des else 1.0
    for p in players:
        ortg, usg, minp = p.get("ind_ortg"), p.get("usage_pct"), p.get("min_pct")
        if not ortg or not usg or minp is None or p.get("fm"):
            p["porp"] = None
            continue
        ufactor = usg * -0.144 + 13.023
        if ufactor <= 0:
            p["porp"] = None
            continue
        x_ortg = avg_eff + (ortg - avg_eff) / ufactor * 10.143
        slope = 1.25 if usg > 20 else 1.5
        adjoe = (x_ortg + (usg - 20) * slope) * sos.get(p["school"], 1.0)
        p["porp"] = round((adjoe + (104.9 - avg_eff) - 88.0) * (minp / 100.0) * 69.4 / 500.0, 2)


def attach_win_shares_per(players, teams):
    """Box-score Win Shares (Off/Def/Total + per-40) and Hollinger PER.

    OWS uses Dean Oliver Points Produced / Scoring Possessions (precomputed in
    update_advanced_analytics as pprod/scposs); DWS uses individual DRtg; both
    use league/team pace + points context. PER follows Hollinger with league
    factors, pace adjustment, and normalization to a league average of 15.
    Team/league totals are summed from each player's raw box (_wsb). Null for
    fake-minutes players (unreliable minutes). The temp _wsb is removed here.
    """
    if not players:
        for p in players or []:
            p.pop("_wsb", None)
        return
    team_games = {t["team"]: (t.get("gp") or 0) for t in (teams or [])}
    team_wins = {}
    for t in (teams or []):
        m = re.match(r"(\d+)-(\d+)", str(t.get("record") or ""))
        if m:
            team_wins[t["team"]] = int(m.group(1))
    KEYS = ("MIN", "FGM", "FGA", "3PM", "FTM", "FTA", "OREB", "DREB",
            "REB", "AST", "STL", "BLK", "TO", "PF", "PTS")

    # Aggregate team + league box totals from players' raw box scores.
    team_tot, lg = {}, {k: 0.0 for k in KEYS}
    for p in players:
        b = p.get("_wsb")
        if not b or p.get("fm"):
            continue
        tt = team_tot.setdefault(p["school"], {k: 0.0 for k in KEYS})
        for k in KEYS:
            v = b.get(k) or 0
            tt[k] += v
            lg[k] += v

    def _poss(tt):
        return (tt["FGA"] - tt["OREB"]) + tt["TO"] + 0.475 * tt["FTA"]

    # Use only teams that contributed totals (non-fake-minutes) so games/poss
    # stay consistent.
    lg_games = sum(team_games.get(t, 0) for t in team_tot) or 1
    lg_poss = sum(_poss(tt) for tt in team_tot.values()) or 1.0
    lg_pts = lg["PTS"] or 1.0
    lg_pp_poss = lg_pts / lg_poss          # league points per possession
    lg_pace = lg_poss / lg_games           # league possessions per game

    # Hollinger PER league factors.
    lg_fg, lg_ft, lg_ast = lg["FGM"], lg["FTM"], lg["AST"]
    lg_fga, lg_orb, lg_tov, lg_fta = lg["FGA"], lg["OREB"], lg["TO"], lg["FTA"]
    lg_trb, lg_pf = lg["REB"], lg["PF"]
    factor = ((2.0 / 3.0) - (0.5 * (lg_ast / lg_fg)) / (2.0 * (lg_fg / lg_ft))
              if lg_fg and lg_ft else 0.0)
    _vop_den = lg_fga - lg_orb + lg_tov + 0.44 * lg_fta
    vop = lg_pts / _vop_den if _vop_den > 0 else 0.0
    drbp = (lg_trb - lg_orb) / lg_trb if lg_trb else 0.0

    aper_num = aper_den = 0.0
    for p in players:
        p["ws"] = p["ows"] = p["dws"] = p["ws40"] = p["per"] = None
        p["_aper"] = None
        b = p.get("_wsb")
        tt = team_tot.get(p["school"])
        if not b or p.get("fm") or not tt or tt["FGM"] <= 0:
            continue
        mp = b["MIN"]
        g_team = team_games.get(p["school"], 0)
        team_poss = _poss(tt)
        if mp <= 0 or g_team <= 0 or team_poss <= 0:
            continue
        tm_pace = team_poss / g_team
        # Marginal points per win = 0.32 * lgPtsPerGame * (TmPace/lgPace);
        # lgPtsPerGame = lgPP_poss * lgPace, so the lgPace terms cancel.
        mppw = 0.32 * lg_pp_poss * tm_pace

        # Win Shares. OWS baseline uses TOTAL possessions (TotPoss = 100*PProd/ORtg).
        pprod, drtg, ortg = p.get("pprod"), p.get("ind_drtg"), p.get("ind_ortg")
        if mppw > 0 and pprod is not None and drtg and ortg and ortg > 0:
            tot_poss = 100.0 * pprod / ortg
            ows = (pprod - 0.92 * lg_pp_poss * tot_poss) / mppw
            dws = ((mp / tt["MIN"]) * team_poss * (1.08 * lg_pp_poss - drtg / 100.0)) / mppw
            ws = ows + dws
            p["ows"], p["dws"], p["ws"] = round(ows, 2), round(dws, 2), round(ws, 2)
            p["ws40"] = round(ws / mp * 40.0, 3)

        # Hollinger PER (unadjusted, then pace-adjusted; normalized in pass 2)
        asum = tt["AST"] / tt["FGM"]
        pf_term = (b["PF"] * ((lg_ft / lg_pf) - 0.44 * (lg_fta / lg_pf) * vop)
                   if lg_pf else 0.0)
        uper = (1.0 / mp) * (
            b["3PM"]
            + (2.0 / 3.0) * b["AST"]
            + (2 - factor * asum) * b["FGM"]
            + b["FTM"] * 0.5 * (1 + (1 - asum) + (2.0 / 3.0) * asum)
            - vop * b["TO"]
            - vop * drbp * (b["FGA"] - b["FGM"])
            - vop * 0.44 * (0.44 + 0.56 * drbp) * (b["FTA"] - b["FTM"])
            + vop * (1 - drbp) * (b["REB"] - b["OREB"])
            + vop * drbp * b["OREB"]
            + vop * b["STL"]
            + vop * drbp * b["BLK"]
            - pf_term)
        aper = (lg_pace / tm_pace) * uper if tm_pace > 0 else uper
        p["_aper"] = aper
        aper_num += aper * mp
        aper_den += mp

    # League normalization: scale Win Shares so the league total equals total
    # team wins (the defining property of WS). Keeps the metric textbook-shaped
    # and removes the ~20% raw overshoot. PER is normalized separately (avg 15).
    total_ws = sum(p["ws"] for p in players if p.get("ws") is not None)
    total_wins = sum(team_wins.get(t, 0) for t in team_tot)
    ws_factor = (total_wins / total_ws) if total_ws > 0 and total_wins > 0 else 1.0

    lg_aper = (aper_num / aper_den) if aper_den > 0 else 0.0
    for p in players:
        ap = p.pop("_aper", None)
        if ap is not None and lg_aper > 0:
            p["per"] = round(ap * (15.0 / lg_aper), 1)
        if p.get("ws") is not None:
            mp = (p.get("_wsb") or {}).get("MIN") or 0
            p["ows"] = round(p["ows"] * ws_factor, 2)
            p["dws"] = round(p["dws"] * ws_factor, 2)
            p["ws"] = round(p["ws"] * ws_factor, 2)
            p["ws40"] = round(p["ws"] / mp * 40.0, 3) if mp > 0 else None
        p.pop("_wsb", None)
        p.pop("pprod", None)
        p.pop("scposs", None)


# ── Position-aware player similarity ────────────────────────────────────────
# The full feature space. Each player is standardized across the pool on these,
# then a POSITION-SPECIFIC weight vector defines the distance — so a PF/C is
# matched on 2P%/rebounding/rim-protection (3PA% weighted to zero), while a
# stretch PF keeps the 3-point emphasis. Pool eligibility only needs the role
# stats (_SIM_CORE_KEYS); any feature that is missing — or a shooting % below
# its attempt-volume floor — is treated as neutral (imputed to the league mean).
_SIM_FEATURES = [
    "usage_pct", "shot_pct", "ts_pct", "ind_ortg",      # volume / efficiency
    "tpa_rate", "tpp", "twop", "ft_rate", "fd_per_40",  # shot profile
    "ast_rate", "tov_pct",                              # playmaking / security
    "oreb_pct", "dreb_pct", "stl_pct", "blk_pct",       # rebounding / defense
    "min_pct",
]
_SIM_CORE_KEYS = ["usage_pct", "min_pct", "ind_ortg", "ast_rate",
                  "oreb_pct", "dreb_pct", "stl_pct", "blk_pct", "tov_pct"]
# A shooting % only counts when the player clears this many attempts per game;
# below it the % is too noisy and is treated as neutral.
_SIM_2PA_PG_MIN = 2.5
_SIM_3PA_PG_MIN = 2.5

# Per-position weights over _SIM_FEATURES. Missing keys fall back to the value
# in _SIM_DEFAULT_WEIGHTS. min_pct stays a light 0.5 tiebreaker everywhere.
_SIM_DEFAULT_WEIGHTS = {
    "usage_pct": 1.6, "shot_pct": 0.8, "ts_pct": 1.5, "ind_ortg": 1.2,
    "tpa_rate": 1.2, "tpp": 0.8, "twop": 0.8, "ft_rate": 1.0, "fd_per_40": 0.6,
    "ast_rate": 1.0, "tov_pct": 0.9, "oreb_pct": 0.8, "dreb_pct": 0.8,
    "stl_pct": 0.7, "blk_pct": 0.7, "min_pct": 0.5,
}
_SIM_POS_WEIGHTS = {
    "PG": {"ast_rate": 2.0, "tov_pct": 1.5, "usage_pct": 1.0, "stl_pct": 1.0,
           "ts_pct": 1.0, "ind_ortg": 0.8, "fd_per_40": 0.6, "tpp": 0.5,
           "twop": 0.5, "ft_rate": 0.5, "shot_pct": 0.4, "tpa_rate": 0.3,
           "dreb_pct": 0.4, "oreb_pct": 0.2, "blk_pct": 0.0, "min_pct": 0.5},
    "s-PG": {"usage_pct": 1.8, "shot_pct": 1.6, "ts_pct": 1.5, "ind_ortg": 1.2,
             "tpa_rate": 1.0, "tpp": 1.0, "ast_rate": 0.9, "ft_rate": 0.9,
             "fd_per_40": 0.8, "twop": 0.7, "tov_pct": 0.7, "stl_pct": 0.6,
             "dreb_pct": 0.3, "oreb_pct": 0.1, "blk_pct": 0.0, "min_pct": 0.5},
    "CG": {"usage_pct": 1.3, "ts_pct": 1.3, "ast_rate": 1.2, "tpp": 1.2,
           "shot_pct": 1.2, "tpa_rate": 1.0, "ind_ortg": 1.0, "tov_pct": 0.9,
           "stl_pct": 0.8, "ft_rate": 0.7, "twop": 0.7, "fd_per_40": 0.6,
           "dreb_pct": 0.4, "oreb_pct": 0.2, "blk_pct": 0.0, "min_pct": 0.5},
    "WG": {"twop": 1.4, "ts_pct": 1.4, "ft_rate": 1.3, "fd_per_40": 1.2,
           "tpa_rate": 1.0, "tpp": 1.0, "shot_pct": 1.0, "usage_pct": 1.0,
           "stl_pct": 0.9, "ind_ortg": 0.9, "dreb_pct": 0.7, "tov_pct": 0.6,
           "ast_rate": 0.5, "oreb_pct": 0.3, "blk_pct": 0.2, "min_pct": 0.5},
    "WF": {"twop": 1.3, "ts_pct": 1.3, "ft_rate": 1.2, "fd_per_40": 1.2,
           "dreb_pct": 1.1, "usage_pct": 1.0, "oreb_pct": 0.9, "ind_ortg": 0.9,
           "tpa_rate": 0.8, "tpp": 0.8, "shot_pct": 0.8, "stl_pct": 0.7,
           "tov_pct": 0.6, "ast_rate": 0.6, "blk_pct": 0.5, "min_pct": 0.5},
    "S-PF": {"tpa_rate": 1.8, "tpp": 1.4, "ts_pct": 1.4, "dreb_pct": 1.2,
             "usage_pct": 1.0, "ind_ortg": 1.0, "oreb_pct": 0.8, "twop": 0.8,
             "ft_rate": 0.8, "shot_pct": 0.7, "fd_per_40": 0.7, "blk_pct": 0.6,
             "tov_pct": 0.5, "stl_pct": 0.4, "ast_rate": 0.3, "min_pct": 0.5},
    "PF/C": {"twop": 1.8, "oreb_pct": 1.5, "dreb_pct": 1.5, "blk_pct": 1.4,
             "ts_pct": 1.2, "ft_rate": 1.1, "fd_per_40": 1.1, "usage_pct": 1.0,
             "ind_ortg": 0.9, "shot_pct": 0.7, "stl_pct": 0.4, "ast_rate": 0.3,
             "tov_pct": 0.5, "tpa_rate": 0.0, "tpp": 0.0, "min_pct": 0.5},
    "C": {"twop": 1.8, "blk_pct": 1.7, "oreb_pct": 1.7, "dreb_pct": 1.5,
          "ts_pct": 1.2, "ft_rate": 1.1, "fd_per_40": 1.1, "ind_ortg": 0.9,
          "usage_pct": 0.9, "shot_pct": 0.6, "stl_pct": 0.3, "ast_rate": 0.2,
          "tov_pct": 0.4, "tpa_rate": 0.0, "tpp": 0.0, "min_pct": 0.5},
}

# The handful of stats that DEFINE each archetype. A candidate must land within
# _SIM_BAND_STD standard deviations of the target on EVERY one of these (a hard
# band, not a soft average) before it's eligible — so the important ranges stay
# tight. Among in-band candidates, the weighted distance above ranks them; if
# too few clear the band, the least-out-of-band fill the rest. A key stat that
# is gated/missing for either player (e.g. 3P% under the attempt floor) is
# skipped for that pair rather than counted as a miss.
_SIM_BAND_STD = 0.75
_SIM_POS_KEYS = {
    "PG":   ["ast_rate", "tov_pct", "usage_pct"],
    "s-PG": ["usage_pct", "shot_pct", "ts_pct"],
    "CG":   ["usage_pct", "ast_rate", "tpp", "ts_pct"],
    "WG":   ["twop", "ft_rate", "ts_pct", "usage_pct"],
    "WF":   ["twop", "dreb_pct", "ft_rate", "usage_pct"],
    "S-PF": ["tpa_rate", "tpp", "ts_pct", "dreb_pct"],
    "PF/C": ["twop", "oreb_pct", "dreb_pct", "blk_pct", "usage_pct"],
    "C":    ["twop", "oreb_pct", "dreb_pct", "blk_pct", "usage_pct"],
}
_SIM_DEFAULT_KEYS = ["usage_pct", "ts_pct", "tpa_rate"]

# Basic-profile fallback feature space, for players whose minutes aren't
# reliably tracked (no usage%/possession-rate stats). Every stat here comes
# straight from box-score totals / per-game counts — shot profile, shooting
# efficiency, AND basic rebounding / playmaking — so these players still get a
# meaningful comp on what we DO know about them (not shooting alone). Compared
# against the full qualified pool on these same minutes-independent stats.
_SIM_SHOOT_KEYS = ["ts_pct", "efg_pct", "tpa_rate", "ft_rate",
                   "orpg", "drpg", "apg", "topg", "spg", "bpg"]
_SIM_SHOOT_WEIGHTS = {"ts_pct": 1.4, "efg_pct": 1.0, "tpa_rate": 1.5, "ft_rate": 1.0,
                      "orpg": 1.2, "drpg": 1.2, "apg": 1.3, "topg": 1.0,
                      "spg": 0.8, "bpg": 0.9}
_SIM_SHOOT_MIN_FGA = 50  # volume floor so percentages are stable
# Candidate pool (who can be a neighbor) stays at min_pct >= 30. Targets (who
# get a comp list) are eligible down to this floor — but, like KenPom, deep
# bench players (under 10% of minutes) get no comps at all.
_SIM_TARGET_MIN_PCT = 10


def attach_similar_players(season_players: dict, team_rosters: dict):
    """Cross-season statistical nearest neighbors for player profiles.

    Pool = every qualified player (min_pct >= 30, all _SIM_CORE_KEYS present)
    across every season. The distance is POSITION-AWARE: each player is
    standardized on _SIM_FEATURES, then the target's position picks the weight
    vector (_SIM_POS_WEIGHTS), so a big is judged on interior stats and a guard
    on playmaking/shooting. Each roster player gets a "sim" list of their 6
    nearest neighbors and a "sim_mode" of "full". Players who lack reliable
    minutes/role stats can't enter the pool; they get a "shoot" fallback —
    nearest neighbors by shot profile alone (still drawn from the full pool).

    Neighbor tuple (positional), shipped in the lazy roster files:
      0 name  1 school  2 season  3 ortg  4 usg  5 min%  6 porp  7 3pa%  8 ts%
      9 pos  10 2p%  11 3p%  12 ftr  13 fd/40  14 oreb%  15 dreb%  16 blk%
      17 arate  18 to%  19 stl%  20 %shots
      21 orpg  22 drpg  23 apg  24 topg  25 ppg  26 efg%   (basic, for fallback)
    Full (role) matches render a POSITION-SPECIFIC subset of the advanced
    columns; "shoot" fallback matches render the basic per-game columns (21-26)
    since the target lacks reliable minutes. 2P%/3P% are nulled for neighbors
    below their per-game attempt floor (shown as "—").
    """
    import numpy as np
    entries = []  # candidate pool: leaderboard-qualified players only (q==1)
    for skey, players in season_players.items():
        for p in players or []:
            if p.get("q") and all(p.get(k) is not None for k in _SIM_CORE_KEYS):
                entries.append((skey, p))
    if len(entries) < 10:
        return

    # Build the feature matrix, nulling (NaN) shooting %s below their per-game
    # attempt floor so they don't distort the match on a noisy percentage.
    def _gated(p, key):
        v = p.get(key)
        gp = p.get("gp") or 0
        if key == "twop" and (gp == 0 or (p.get("twoa") or 0) / gp < _SIM_2PA_PG_MIN):
            return np.nan
        if key == "tpp" and (gp == 0 or (p.get("tpa") or 0) / gp < _SIM_3PA_PG_MIN):
            return np.nan
        return np.nan if v is None else v

    mat = np.array([[_gated(p, k) for k in _SIM_FEATURES] for _, p in entries], dtype=np.float64)
    mean = np.nanmean(mat, axis=0)
    sd = np.nanstd(mat, axis=0)
    sd[sd == 0] = 1.0
    # Standardize; remember which cells were missing/gated, then make those
    # neutral (z=0 = league average) so they don't distort distances.
    z = (mat - mean) / sd
    nanmask = np.isnan(z)
    z = np.where(nanmask, 0.0, z)
    index = {(skey, p["school"], p["name"]): i for i, (skey, p) in enumerate(entries)}

    _feat_idx = {f: i for i, f in enumerate(_SIM_FEATURES)}
    _wvec_cache, _keyidx_cache = {}, {}
    def _wvec(pos):
        if pos not in _wvec_cache:
            wd = _SIM_POS_WEIGHTS.get(pos, _SIM_DEFAULT_WEIGHTS)
            _wvec_cache[pos] = np.array(
                [wd.get(f, _SIM_DEFAULT_WEIGHTS.get(f, 1.0)) for f in _SIM_FEATURES],
                dtype=np.float64)
        return _wvec_cache[pos]
    def _keyidx(pos):
        if pos not in _keyidx_cache:
            keys = _SIM_POS_KEYS.get(pos, _SIM_DEFAULT_KEYS)
            _keyidx_cache[pos] = np.array([_feat_idx[k] for k in keys], dtype=int)
        return _keyidx_cache[pos]

    # Every player (any minutes) is an eligible TARGET; the candidate pool above
    # stays the quality references. Look up each target's full stat dict here.
    all_src = {}
    for skey, players in season_players.items():
        for p in players or []:
            all_src[(skey, p["school"], p["name"])] = p

    def _zvec(p):
        """Standardize an arbitrary player into the pool's feature space."""
        raw = np.array([_gated(p, k) for k in _SIM_FEATURES], dtype=np.float64)
        nan = np.isnan(raw)
        return np.where(nan, 0.0, (raw - mean) / sd), nan

    # Shooting-only fallback space (for players with no role stats at all).
    sm = np.array([[p[k] for k in _SIM_SHOOT_KEYS] for _, p in entries], dtype=np.float64)
    smean, ssd = sm.mean(axis=0), sm.std(axis=0)
    ssd[ssd == 0] = 1.0
    sw = np.array([_SIM_SHOOT_WEIGHTS.get(k, 1.0) for k in _SIM_SHOOT_KEYS], dtype=np.float64)
    sz = ((sm - smean) / ssd) * np.sqrt(sw)        # candidates, weighted shooting space
    pos_arr = np.array([(p.get("pos") or "") for _, p in entries])

    def _emit(order):
        out = []
        for j in order:
            sk, q = entries[int(j)]
            gp = q.get("gp") or 0
            twop = q.get("twop") if gp and (q.get("twoa") or 0) / gp >= _SIM_2PA_PG_MIN else None
            tpp = q.get("tpp") if gp and (q.get("tpa") or 0) / gp >= _SIM_3PA_PG_MIN else None
            out.append([q["name"], q["school"], sk,
                        q.get("ind_ortg"), q.get("usage_pct"), q.get("min_pct"),
                        q.get("porp"), q.get("tpa_rate"), q.get("ts_pct"),
                        q.get("pos") or "", twop, tpp, q.get("ft_rate"),
                        q.get("fd_per_40"), q.get("oreb_pct"), q.get("dreb_pct"),
                        q.get("blk_pct"), q.get("ast_rate"), q.get("tov_pct"),
                        q.get("stl_pct"), q.get("shot_pct"),
                        # 21-26: basic per-game / minutes-independent (fallback display)
                        q.get("orpg"), q.get("drpg"), q.get("apg"), q.get("topg"),
                        q.get("ppg"), q.get("efg_pct"),
                        # 27-28: ungated 2P%/3P% for DISPLAY only. The gated values
                        # (10/11) keep noisy low-volume %s out of the *match*, but the
                        # scouting card should show the player's real season percentage
                        # (e.g. s-PGs are mostly sub-2.5 3PA/g, so gated 3P% is blank
                        # for everyone). Display columns point here instead.
                        q.get("twop"), q.get("tpp")])
        return out

    def _nearest(d, mask, self_i):
        """6 nearest among the same-position candidates, excluding self."""
        idx = np.where(mask)[0]
        if self_i is not None:
            idx = idx[idx != self_i]
        return idx[np.argsort(d[idx])][:6] if len(idx) else idx

    for skey, roster in (team_rosters or {}).items():
        for team, rec in (roster or {}).items():
            for row in rec.get("players", []):
                row["sim"] = None       # uniform key set keeps columnar packing intact
                row["sim_mode"] = None  # "full" (role-based) or "shoot" (fallback)
                key = (skey, team, row["name"])
                p = all_src.get(key)
                if p is None:
                    continue
                self_i = index.get(key)
                pos = p.get("pos") or ""
                # KenPom-style: candidates are the SAME position; rank holistically
                # by weighted distance (no per-stat bands). Unclassified targets
                # fall back to the whole pool.
                same_pos = (pos_arr == pos) if pos else np.ones(len(entries), bool)
                # Role-based match for rotation players (>= target min%; no deep
                # bench, like KenPom) — matched against the quality pool.
                if (p.get("min_pct") or 0) >= _SIM_TARGET_MIN_PCT and \
                        all(p.get(k) is not None for k in _SIM_CORE_KEYS):
                    tz, _ = _zvec(p)
                    d = np.sqrt(((z - tz) ** 2) @ _wvec(pos))
                    order = _nearest(d, same_pos, self_i)
                    if len(order):
                        row["sim"] = _emit(order)
                        row["sim_mode"] = "full"
                    continue
                # No reliable role stats — shooting-only fallback, same position.
                if (p.get("fga") or 0) >= _SIM_SHOOT_MIN_FGA and all(p.get(k) is not None for k in _SIM_SHOOT_KEYS):
                    tv = (np.array([p[k] for k in _SIM_SHOOT_KEYS], dtype=np.float64) - smean) / ssd
                    d = np.sqrt(((sz - tv * np.sqrt(sw)) ** 2).sum(axis=1))
                    order = _nearest(d, same_pos, self_i)
                    if len(order):
                        row["sim"] = _emit(order)
                        row["sim_mode"] = "shoot"


def _box_norm(name: str) -> str:
    """Normalize a team name for game-box lookup keys.

    Must stay in sync with the JS __boxNorm() in the page template: lowercase,
    strip a trailing ' College', drop all non-alphanumerics.
    """
    n = (name or "").strip().lower()
    if n.endswith(" college"):
        n = n[:-8]
    return re.sub(r"[^a-z0-9]", "", n)


def _box_game_key(date: str, team_a: str, team_b: str) -> str:
    return date + "|" + "|".join(sorted([_box_norm(team_a), _box_norm(team_b)]))


# Per-game advanced stats shipped in the box score files, with per-stat
# reliability requirements: stats are nulled (shown as "—") when an input
# they depend on clearly wasn't tracked for that game — implausible minutes
# totals, team turnovers of 0, or team fouls of 0. Basic stats always ship.
_BOX_STATS = {"efg": "efg_pct", "ts": "ts_pct", "top": "tov_pct",
              "ortg": "ind_ortg", "drtg": "ind_drtg", "usg": "usage_pct",
              "orp": "oreb_pct", "drp": "dreb_pct", "ap": "ast_rate",
              "stp": "stl_pct", "blp": "blk_pct"}


def _load_bpm_priors(stats_dir) -> dict:
    """Season BPM context per (team, normalized player name).

    Single-game BPM 2.0 (Daniel Myers' calculator) uses each player's season
    position, offensive role, and season OBPM/DBPM as priors. Those come from
    the compute_ccc_bpm output (internal_data/ccc_bpm_<season>.json, generated
    per season); players/seasons without it fall back to neutral values
    (pos 3, role 3, priors 0) inside the game calculation.
    """
    season = _STATS_DIR_TO_SEASON.get(str(stats_dir), "")
    if not season:
        return {}
    path = Path(f"internal_data/ccc_bpm_{season.replace('-', '_')}.json")
    if not path.exists():
        return {}
    try:
        data = json.load(open(path))
    except Exception:
        return {}
    priors = {}
    for row in data.get("players", []):
        key = (row.get("team", ""), _bpm_player_key(row.get("player", "")))
        priors[key] = (
            row.get("position_scale", 3.0) or 3.0,
            row.get("creation_role", 3.0) or 3.0,
            row.get("obpm", 0.0) or 0.0,
            row.get("dbpm", 0.0) or 0.0,
        )
    return priors


def _game_bpm(side_tot, opp_tot, rows, opp_rows, team, opp, lg_ortg, priors):
    """Single-game BPM/OBPM/DBPM per Daniel Myers' BPM 2.0 calculator sheet.

    Mirrors the 'BPM 2.0 Single Game' sheet exactly: per-100 stats on
    adjusted points, position/role-interpolated coefficients (shared with
    compute_ccc_bpm), then a team adjustment that blends the lead-adjusted
    game ratings with the lineups' season OBPM/DBPM priors.
    Returns {player_name: (bpm, obpm, dbpm)}.
    """
    team_clock = side_tot["MIN"] / 5.0
    opp_clock = opp_tot["MIN"] / 5.0
    if team_clock <= 0 or side_tot["POSS"] <= 0 or opp_tot["POSS"] <= 0:
        return {}
    # Team scoring context: points per true-shot attempt (sheet T9, base 1.0)
    tsa_team = side_tot["FGA"] + 0.44 * side_tot["FTA"]
    pts_per_tsa = side_tot["PTS"] / tsa_team if tsa_team > 0 else 1.0

    def side_inputs(rs, tot, prior_team):
        out = []
        clock = tot["MIN"] / 5.0
        for r in rs:
            if r["MIN"] <= 0:
                out.append((r, None, 0.0, None))
                continue
            poss = r["MIN"] * tot["POSS"] / clock
            pct_min = r["MIN"] / clock
            tsa = r["FGA"] + 0.44 * r["FTA"]
            t_tsa = tot["FGA"] + 0.44 * tot["FTA"]
            t_ppt = tot["PTS"] / t_tsa if t_tsa > 0 else 1.0
            adj_pts = r["PTS"] + (1.0 - t_ppt) * tsa
            per100 = {
                "PTS": 100.0 * adj_pts / poss,
                "FGA": 100.0 * r["FGA"] / poss, "FTA": 100.0 * r["FTA"] / poss,
                "3PM": 100.0 * r["3PM"] / poss, "AST": 100.0 * r["AST"] / poss,
                "TO": 100.0 * r["TO"] / poss, "OREB": 100.0 * r["OREB"] / poss,
                "DREB": 100.0 * r["DREB"] / poss, "STL": 100.0 * r["STL"] / poss,
                "BLK": 100.0 * r["BLK"] / poss, "PF": 100.0 * r["PF"] / poss,
            }
            pos, role, s_obpm, s_dbpm = priors.get(
                (prior_team, _bpm_player_key(r["name"])), (3.0, 3.0, 0.0, 0.0))
            raw_bpm = raw_metric(per100, pos, role, BPM_COEFFS, BPM_ROLE_COEFFS, -0.818, 2.774)
            raw_obpm = raw_metric(per100, pos, role, OBPM_COEFFS, OBPM_ROLE_COEFFS, -1.698, 0.860)
            out.append((r, (raw_bpm, raw_obpm), pct_min, (s_obpm, s_dbpm)))
        return out

    own = side_inputs(rows, side_tot, team)
    other = side_inputs(opp_rows, opp_tot, opp)

    def lineup_sums(items):
        sb = so = po = pd = 0.0
        for _r, raws, pct, sp in items:
            if raws is None:
                continue
            sb += pct * raws[0]
            so += pct * raws[1]
            po += pct * sp[0]
            pd += pct * sp[1]
        return sb, so, po, pd

    own_raw_bpm, own_raw_obpm, own_prior_o, own_prior_d = lineup_sums(own)
    _ob, _oo, opp_prior_o, opp_prior_d = lineup_sums(other)

    # Lead-adjusted game ratings (sheet L8/M8/N8): lead = margin/2,
    # bonus = 0.35/2 * lead
    margin = side_tot["PTS"] - opp_tot["PTS"]
    own_n = 100.0 * side_tot["PTS"] / side_tot["POSS"] + 0.175 * (margin / 2.0)
    opp_n = 100.0 * opp_tot["PTS"] / opp_tot["POSS"] + 0.175 * (-margin / 2.0)
    own_o = (own_n - lg_ortg) / 2.0 + (own_prior_o + opp_prior_d) / 2.0
    own_p = (lg_ortg - opp_n) / 2.0 + (opp_prior_o + own_prior_d) / 2.0

    bpm_adj = (own_o + own_p - own_raw_bpm) / 5.0
    obpm_adj = (own_o - own_raw_obpm) / 5.0

    result = {}
    for r, raws, _pct, _sp in own:
        if raws is None:
            continue
        bpm = raws[0] + bpm_adj
        obpm = raws[1] + obpm_adj
        result[r["name"]] = (round(bpm, 1), round(obpm, 1), round(bpm - obpm, 1))
    return result


def build_game_boxes(stats_dir) -> dict:
    """Build per-game player box scores (Torvik-style) for one season.

    Walks every box score JSON under the season's schedules folder and returns
    {game_key: game_record}. Advanced stats reuse STAT_DEFINITIONS from
    update_advanced_analytics so per-game numbers use the exact formulas the
    season leaderboards use.

    Some scraped boxes label the teams with site abbreviation codes or
    nickname/long-form variants ("LASW-M", "Barstow Vikings", "College of the
    Canyons") instead of the names the page looks games up by. Those labels
    are remapped using the owning team's schedule entry: the folder gives the
    owning team and opponent slug, and the schedule's win/loss plus the box's
    score pair identify which label is which side.
    """
    sched_dir = Path(str(stats_dir).replace(" Team Statistics", " Teams Schedules"))
    games = {}
    if not sched_dir.exists():
        return games

    bpm_priors = _load_bpm_priors(stats_dir)
    pending = []
    lg_pts = lg_poss = 0.0

    canon_by_norm = {}
    for info in CONFERENCES.values():
        for t in info["teams"]:
            canon_by_norm[_box_norm(t)] = t

    def parse_ma(s):
        try:
            m, a = str(s).split("-")
            return int(m), int(a)
        except Exception:
            return 0, 0

    def parse_int(s):
        try:
            return int(str(s).strip())
        except Exception:
            return 0

    def slugify(name):
        return re.sub(r"[^a-zA-Z0-9]", "_", str(name)).lower().strip("_")

    _sched_cache = {}

    def team_schedule(team_dir: Path):
        if team_dir not in _sched_cache:
            try:
                _sched_cache[team_dir] = json.load(open(team_dir / "schedule.json")).get("games", [])
            except Exception:
                _sched_cache[team_dir] = []
        return _sched_cache[team_dir]

    def resolve_labels(box, box_path, names):
        """Map box team labels -> display names the page can look up."""
        if all(_box_norm(n) in canon_by_norm for n in names):
            return {n: canon_by_norm[_box_norm(n)] for n in names}
        owning = box_path.parts[-3]
        game_dir = box_path.parts[-2]
        date_stamp = game_dir.split("_")[0]
        opp_slug = game_dir[len(date_stamp) + 1:]
        entry = None
        for g in team_schedule(box_path.parent.parent):
            if slugify(g.get("opponent", "")) == opp_slug and date_stamp in (g.get("boxscore_url") or ""):
                entry = g
                break
        if entry is None or entry.get("win_loss") not in ("W", "L"):
            return None
        opp_name = entry.get("opponent", "")
        opp_name = canon_by_norm.get(_box_norm(opp_name), opp_name)
        sc = box.get("score", {})
        if len(sc) != 2 or len(set(sc.values())) != 2:
            return None
        by_score = sorted(names, key=lambda n: sc.get(n, 0))
        owning_label = by_score[1] if entry["win_loss"] == "W" else by_score[0]
        opp_label = [n for n in names if n != owning_label][0]
        return {owning_label: owning, opp_label: opp_name}

    for box_path in sched_dir.glob("*/*/*/*.json"):
        try:
            box = json.load(open(box_path))
        except Exception:
            continue
        if not isinstance(box, dict) or "teams" not in box or len(box.get("teams", {})) != 2:
            continue
        date = box.get("date", "")
        raw_names = list(box["teams"].keys())
        rename = resolve_labels(box, box_path, raw_names)
        if rename:
            box["teams"] = {rename[n]: box["teams"][n] for n in raw_names}
            box["score"] = {rename.get(k, k): v for k, v in box.get("score", {}).items()}
            box["home"] = rename.get(box.get("home"), box.get("home"))
            box["visitor"] = rename.get(box.get("visitor"), box.get("visitor"))
        names = list(box["teams"].keys())
        key = _box_game_key(date, names[0], names[1])
        if key in games:
            continue  # already built from the other team's copy

        # Parse raw player lines and team totals for both sides
        sides = {}
        ok = True
        for tn in names:
            plist = box["teams"][tn]
            # Starter flags: use scraped roles when present; otherwise the
            # first five listed in the box score are the starters.
            has_flags = any(p.get("is_starter") is not None or p.get("role") for p in plist)
            rows = []
            for idx, p in enumerate(plist):
                s = p.get("stats", {})
                fgm, fga = parse_ma(s.get("FGM-A", "0-0"))
                tpm, tpa = parse_ma(s.get("3PM-A", "0-0"))
                ftm, fta = parse_ma(s.get("FTM-A", "0-0"))
                if has_flags:
                    starter = 1 if (p.get("is_starter") or p.get("role") == "starter") else 0
                else:
                    starter = 1 if idx < 5 else 0
                raw_name = p.get("name", "")
                jm = re.match(r"^[a-z]?\s*#?(\d+)\s+(.*)$", raw_name)
                rows.append({
                    "name": jm.group(2) if jm else raw_name,
                    "JER": jm.group(1) if jm else "",
                    "ST": starter,
                    "MIN": parse_int(s.get("MIN", 0)),
                    "FGM": fgm, "FGA": fga, "3PM": tpm, "3PA": tpa,
                    "FTM": ftm, "FTA": fta,
                    "OREB": parse_int(s.get("OREB", 0)), "DREB": parse_int(s.get("DREB", 0)),
                    "AST": parse_int(s.get("AST", 0)), "STL": parse_int(s.get("STL", 0)),
                    "BLK": parse_int(s.get("BLK", 0)), "TO": parse_int(s.get("TO", 0)),
                    "PF": parse_int(s.get("PF", 0)), "PTS": parse_int(s.get("PTS", 0)),
                })
            if not rows:
                ok = False
                break
            tot = {k: sum(r[k] for r in rows) for k in
                   ("MIN", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "OREB", "DREB",
                    "AST", "STL", "BLK", "TO", "PF", "PTS")}
            tot["POSS"] = tot["FGA"] + 0.475 * tot["FTA"] - tot["OREB"] + tot["TO"]
            sides[tn] = {"rows": rows, "tot": tot}
        if not ok:
            continue

        record = {"d": date, "h": box.get("home", ""), "v": box.get("visitor", ""),
                  "sc": box.get("score", {}), "t": {}}
        poss_vals = []
        flags = {}
        for tn in names:
            opp = [x for x in names if x != tn][0]
            tot, opp_tot = sides[tn]["tot"], sides[opp]["tot"]
            poss_vals.append(tot["POSS"])
            # 5 players x game clock => team_min is total player minutes / 5
            min_ok = 150 <= tot["MIN"] <= 290
            to_ok = tot["TO"] > 0
            pf_ok = tot["PF"] > 0
            opp_to_ok = opp_tot["TO"] > 0
            flags[tn] = (min_ok, to_ok, pf_ok)
            if min_ok and to_ok:
                lg_pts += tot["PTS"]
                lg_poss += tot["POSS"]
            # Per-stat reliability: a stat is only computed when every game
            # input it depends on was actually tracked.
            gates = {
                "efg": True, "ts": True,
                "top": to_ok,
                "usg": min_ok and to_ok,
                "ortg": min_ok and to_ok,
                "drtg": min_ok and to_ok and pf_ok and opp_to_ok,
                "stp": min_ok and to_ok,
                "orp": min_ok, "drp": min_ok, "ap": min_ok, "blp": min_ok,
            }
            ctx = {
                "team_min": tot["MIN"] / 5.0, "team_fgm": tot["FGM"], "team_fga": tot["FGA"],
                "team_fta": tot["FTA"], "team_ftm": tot["FTM"], "team_to": tot["TO"],
                "team_oreb": tot["OREB"], "team_dreb": tot["DREB"], "team_ast": tot["AST"],
                "team_pts": tot["PTS"], "team_3pm": tot["3PM"], "team_blk": tot["BLK"],
                "team_stl": tot["STL"], "team_pf": tot["PF"], "team_poss": tot["POSS"],
                "opp_dreb": opp_tot["DREB"], "opp_fga": opp_tot["FGA"], "opp_fgm": opp_tot["FGM"],
                "opp_fta": opp_tot["FTA"], "opp_ftm": opp_tot["FTM"], "opp_oreb": opp_tot["OREB"],
                "opp_to": opp_tot["TO"], "opp_pts": opp_tot["PTS"], "opp_3pa": opp_tot["3PA"],
            }
            out_rows = []
            min_dep = {"usg", "ortg", "drtg", "stp", "orp", "drp", "ap", "blp"}
            for r in sides[tn]["rows"]:
                row = {
                    "n": r["name"], "j": r["JER"], "st": r["ST"], "min": r["MIN"],
                    "fgm": r["FGM"], "fga": r["FGA"], "tpm": r["3PM"], "tpa": r["3PA"],
                    "ftm": r["FTM"], "fta": r["FTA"], "or": r["OREB"], "dr": r["DREB"],
                    "ast": r["AST"], "stl": r["STL"], "blk": r["BLK"], "to": r["TO"],
                    "pf": r["PF"], "pts": r["PTS"],
                    "bpm": None, "obpm": None, "dbpm": None,
                }
                for short, stat in _BOX_STATS.items():
                    if not gates[short] or (short in min_dep and r["MIN"] <= 0):
                        row[short] = None
                        continue
                    try:
                        row[short] = STAT_DEFINITIONS[stat]["compute"](r, ctx)
                    except Exception:
                        row[short] = None
                out_rows.append(row)
            # Starters first, then bench, each sorted by minutes
            out_rows.sort(key=lambda x: (-x["st"], -x["min"]))
            record["t"][tn] = out_rows
        record["p"] = round(sum(poss_vals) / len(poss_vals), 1) if poss_vals else None
        games[key] = record
        pending.append((record, names, sides, flags))
        # Safety net: when the game folder's date stamp disagrees with the
        # box's internal date (e.g. a manually re-dated game), register the
        # folder-date key too so schedule-driven lookups still find the game.
        stamp = box_path.parts[-2].split("_")[0]
        if len(stamp) == 8 and stamp.isdigit():
            fdate = f"{int(stamp[4:6])}/{int(stamp[6:8])}/{stamp[:4]}"
            if fdate != date:
                games.setdefault(_box_game_key(fdate, names[0], names[1]), record)

    # Second pass: single-game BPM 2.0 once the league-average ORtg is known.
    lg_ortg = 100.0 * lg_pts / lg_poss if lg_poss > 0 else 100.0
    for record, names, sides, flags in pending:
        for tn in names:
            opp = [x for x in names if x != tn][0]
            own_min, own_to, own_pf = flags[tn]
            opp_min, opp_to, _ = flags[opp]
            # Own side needs full tracking; the opponent side supplies its
            # game rating, so its minutes/turnovers must be tracked too.
            if not (own_min and own_to and own_pf and opp_min and opp_to):
                continue
            res = _game_bpm(sides[tn]["tot"], sides[opp]["tot"],
                            sides[tn]["rows"], sides[opp]["rows"],
                            tn, opp, lg_ortg, bpm_priors)
            for row in record["t"][tn]:
                if row["n"] in res:
                    row["bpm"], row["obpm"], row["dbpm"] = res[row["n"]]
    return games


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
                  rpi_data_1819=None, rpi_data_1718=None, height_data=None,
                  storylines_current=None, champion_data=None, game_boxes=None,
                  team_rosters=None, conf_ff=None, moorpark_lineups=None,
                  team_keys=None,
                  subset_by_season=None):
    """Generate a self-contained sortable HTML leaderboard with team/individual toggle."""
    subset_by_season = subset_by_season or {}
    _cur_sub = subset_by_season.get("2526", {})
    last5_teams = _cur_sub.get("last5_teams", [])
    last10_teams = _cur_sub.get("last10_teams", [])
    playoff_teams = _cur_sub.get("playoff_teams", [])
    last5_players = _cur_sub.get("last5_players", [])
    last10_players = _cur_sub.get("last10_players", [])
    playoff_players = _cur_sub.get("playoff_players", [])
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
    if height_data is None:
        height_data = {"ranked": [], "missing": []}
    if champion_data is None:
        champion_data = {}
    def _team_logo_slug(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    team_logo_names = sorted({
        *(t.get("team", "") for t in teams),
        *(t.get("team", "") for t in teams_2024),
        *(t.get("team", "") for t in teams_2023),
        *(t.get("team", "") for t in teams_2022),
        *(t.get("team", "") for t in teams_2021),
        *(t.get("team", "") for t in teams_2019),
        *(t.get("team", "") for t in teams_1819),
        *(t.get("team", "") for t in teams_1718),
    } - {""})
    team_logos_json = _embed({name: f"team_logos/{_team_logo_slug(name)}.png" for name in team_logo_names})
    attach_player_jerseys(players)
    attach_player_jerseys(conf_players)
    # Jerseys for every season (box scores live in each season's schedules dir)
    for _pl, _cpl, _dir in [
        (players_2024, conf_players_2024, "2024-25 Teams Schedules"),
        (players_2023, conf_players_2023, "2023-24 Teams Schedules"),
        (players_2022, conf_players_2022, "2022-23 Teams Schedules"),
        (players_2021, conf_players_2021, "2021-22 Teams Schedules"),
        (players_2019, conf_players_2019, "2019-20 Teams Schedules"),
        (players_1819, conf_players_1819, "2018-19 Teams Schedules"),
        (players_1718, conf_players_1718, "2017-18 Teams Schedules"),
    ]:
        attach_player_jerseys(_pl, _dir)
        attach_player_jerseys(_cpl, _dir)
    # PORPAGATU! for every season (full + conference-only contexts)
    for _pl, _tm in [
        (players, teams), (conf_players, conf_teams),
        (players_2024, teams_2024), (conf_players_2024, conf_teams_2024),
        (players_2023, teams_2023), (conf_players_2023, conf_teams_2023),
        (players_2022, teams_2022), (conf_players_2022, conf_teams_2022),
        (players_2021, teams_2021), (conf_players_2021, conf_teams_2021),
        (players_2019, teams_2019), (conf_players_2019, conf_teams_2019),
        (players_1819, teams_1819), (conf_players_1819, conf_teams_1819),
        (players_1718, teams_1718), (conf_players_1718, conf_teams_1718),
    ]:
        attach_porpagatu(_pl, _tm)
        attach_win_shares_per(_pl, _tm)
    attach_similar_players(
        {"2526": players, "2425": players_2024, "2324": players_2023,
         "2223": players_2022, "2122": players_2021, "1920": players_2019,
         "1819": players_1819, "1718": players_1718},
        team_rosters)
    rpi_data_2526_json = _embed(rpi_data_2526)
    rpi_data_2425_json = _embed(rpi_data_2425)
    rpi_data_2324_json = _embed(rpi_data_2324)
    rpi_data_2223_json = _embed(rpi_data_2223)
    rpi_data_2122_json = _embed(rpi_data_2122)
    rpi_data_1920_json = _embed(rpi_data_1920)
    teams_2019_json = _embed(_slim_games(teams_2019))
    conf_teams_2019_json = _embed(_strip_conf_games(conf_teams_2019))
    players_2019_json = _embed(players_2019)
    conf_players_2019_json = _embed(conf_players_2019)
    storylines_2019_json = _embed(storylines_2019)
    rpi_data_1819_json = _embed(rpi_data_1819)
    rpi_data_1718_json = _embed(rpi_data_1718)
    height_data_json = _embed(height_data)
    champion_data_json = _embed(champion_data)
    conf_ff_json = _embed(conf_ff or {})
    moorpark_lineups_json = _embed(moorpark_lineups or {})
    team_keys_json = _embed(team_keys or {})
    school_colors_json = _embed(SCHOOL_COLORS)
    school_secondary_colors_json = _embed(SCHOOL_SECONDARY_COLORS)
    teams_1819_json = _embed(_slim_games(teams_1819))
    conf_teams_1819_json = _embed(_strip_conf_games(conf_teams_1819))
    players_1819_json = _embed(players_1819)
    conf_players_1819_json = _embed(conf_players_1819)
    storylines_1819_json = _embed(storylines_1819)
    teams_1718_json = _embed(_slim_games(teams_1718))
    conf_teams_1718_json = _embed(_strip_conf_games(conf_teams_1718))
    players_1718_json = _embed(players_1718)
    conf_players_1718_json = _embed(conf_players_1718)
    storylines_1718_json = _embed(storylines_1718)
    players_json = _embed(players)
    teams_json = _embed(_slim_games(teams))
    conf_players_json = _embed(conf_players)
    conf_teams_json = _embed(_strip_conf_games(conf_teams))
    last5_teams_json = _embed(last5_teams)
    last10_teams_json = _embed(last10_teams)
    playoff_teams_json = _embed(playoff_teams)
    last5_players_json = _embed(last5_players)
    last10_players_json = _embed(last10_players)
    playoff_players_json = _embed(playoff_players)
    conf_teams_2024_json = _embed(_strip_conf_games(conf_teams_2024))
    players_2024_json = _embed(players_2024)
    conf_players_2024_json = _embed(conf_players_2024)
    storylines_2024_json = _embed(storylines_2024)
    storylines_2023_json = _embed(storylines_2023)
    players_2023_json = _embed(players_2023)
    conf_players_2023_json = _embed(conf_players_2023)
    players_2022_json = _embed(players_2022)
    conf_players_2022_json = _embed(conf_players_2022)
    storylines_2022_json = _embed(storylines_2022)
    players_2021_json = _embed(players_2021)
    conf_players_2021_json = _embed(conf_players_2021)
    storylines_2021_json = _embed(storylines_2021)
    storylines = storylines_current if storylines_current is not None else load_storylines()
    storylines_json = _embed(storylines)
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
    wab_json = _embed(wab_data)

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
    wab_2024_json = _embed(wab_data_2024)

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
    wab_2023_json = _embed(wab_data_2023)

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
    wab_2022_json = _embed(wab_data_2022)

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
    wab_2021_json = _embed(wab_data_2021)

    # Load split WAB simulation data (North/South, bubble @24)
    wab_sim_2526 = {'north': [], 'south': []}
    sim_path_2526 = Path('wab_sim_split24.json')
    if sim_path_2526.exists():
        try:
            wab_sim_2526 = json.load(open(sim_path_2526))
        except Exception as e:
            print(f'  Warning: could not load wab_sim_split24.json: {e}')
    wab_sim_2526_json = _embed(wab_sim_2526)

    wab_sim_2425 = {'north': [], 'south': []}
    sim_path_2425 = Path('wab_sim_split24_2024_25.json')
    if sim_path_2425.exists():
        try:
            wab_sim_2425 = json.load(open(sim_path_2425))
        except Exception as e:
            print(f'  Warning: could not load wab_sim_split24_2024_25.json: {e}')
    wab_sim_2425_json = _embed(wab_sim_2425)

    wab_sim_2324 = {'north': [], 'south': []}
    sim_path_2324 = Path('wab_sim_split24_2023_24.json')
    if sim_path_2324.exists():
        try:
            wab_sim_2324 = json.load(open(sim_path_2324))
        except Exception as e:
            print(f'  Warning: could not load wab_sim_split24_2023_24.json: {e}')
    wab_sim_2324_json = _embed(wab_sim_2324)

    wab_sim_2223 = {'north': [], 'south': []}
    sim_path_2223 = Path('wab_sim_split24_2022_23.json')
    if sim_path_2223.exists():
        try:
            wab_sim_2223 = json.load(open(sim_path_2223))
        except Exception as e:
            print(f'  Warning: could not load wab_sim_split24_2022_23.json: {e}')
    wab_sim_2223_json = _embed(wab_sim_2223)

    wab_sim_2122 = {'north': [], 'south': []}
    wab_sim_2122_json = _embed(wab_sim_2122)

    wab_sim_1920 = {'north': [], 'south': []}
    wab_sim_1920_json = _embed(wab_sim_1920)

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
    daily_ranks_json = _embed(daily_ranks)

    # Compute 2024-25 daily rankings using the same helper
    daily_ranks_2024 = compute_daily_ranks(teams_2024 or [], prior_teams=teams_2023 or [])
    daily_ranks_2024_json = _embed(daily_ranks_2024)

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
    league_avg_json = _embed(league_avg)

    # Compute 2024-25 league averages for the season toggle
    teams_2024_json = _embed(_slim_games(teams_2024))
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
    league_avg_2024_json = _embed(league_avg_2024)

    # Compute 2023-24 league averages
    teams_2023_json = _embed(_slim_games(teams_2023))
    conf_teams_2023_json = _embed(_strip_conf_games(conf_teams_2023))
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
    daily_ranks_2023_json = _embed(daily_ranks_2023)
    league_avg_2023_json = _embed(league_avg_2023)

    # Compute 2022-23 league averages
    teams_2022_json = _embed(_slim_games(teams_2022))
    conf_teams_2022_json = _embed(_strip_conf_games(conf_teams_2022))
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
    daily_ranks_2022_json = _embed(daily_ranks_2022)
    league_avg_2022_json = _embed(league_avg_2022)

    # Compute 2021-22 league averages
    teams_2021_json = _embed(_slim_games(teams_2021))
    conf_teams_2021_json = _embed(_strip_conf_games(conf_teams_2021))
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
    daily_ranks_2021_json = _embed(daily_ranks_2021)
    league_avg_2021_json = _embed(league_avg_2021)

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
    league_avg_2019_json = _embed(league_avg_2019)

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
    league_avg_1819_json = _embed(league_avg_1819)

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
    league_avg_1718_json = _embed(league_avg_1718)

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
    rel_ratings_2526_json = _embed(rel_ratings_2526)
    rel_ratings_2425_json = _embed(rel_ratings_2425)
    rel_ratings_2324_json = _embed(rel_ratings_2324)
    rel_ratings_2223_json = _embed(rel_ratings_2223)
    rel_ratings_2122_json = _embed(rel_ratings_2122)
    rel_ratings_1920_json = _embed(rel_ratings_1920)
    rel_ratings_1819_json = _embed(rel_ratings_1819)
    rel_ratings_1718_json = _embed(rel_ratings_1718)
    daily_ranks_2019 = compute_daily_ranks(teams_2019 or [], prior_teams=teams_1819)
    daily_ranks_2019_json = _embed(daily_ranks_2019)
    daily_ranks_1819 = compute_daily_ranks(teams_1819 or [], prior_teams=teams_1718)
    daily_ranks_1819_json = _embed(daily_ranks_1819)
    daily_ranks_1718 = compute_daily_ranks(teams_1718 or [])
    daily_ranks_1718_json = _embed(daily_ranks_1718)

    # Past-season bulk datasets are written to sibling .js files and loaded
    # on demand by ensureSeason() in the page, keeping the HTML itself small.
    season_payloads = {
        "2425": {
            "DATA_2024": players_2024_json, "TEAM_DATA_2024": teams_2024_json,
            "CONF_DATA_2024": conf_players_2024_json, "CONF_TEAM_DATA_2024": conf_teams_2024_json,
            "STORYLINES_2024": storylines_2024_json, "DAILY_RANKS_2024": daily_ranks_2024_json,
        },
        "2324": {
            "DATA_2023": players_2023_json, "TEAM_DATA_2023": teams_2023_json,
            "CONF_DATA_2023": conf_players_2023_json, "CONF_TEAM_DATA_2023": conf_teams_2023_json,
            "STORYLINES_2023": storylines_2023_json, "DAILY_RANKS_2023": daily_ranks_2023_json,
        },
        "2223": {
            "DATA_2022": players_2022_json, "TEAM_DATA_2022": teams_2022_json,
            "CONF_DATA_2022": conf_players_2022_json, "CONF_TEAM_DATA_2022": conf_teams_2022_json,
            "STORYLINES_2022": storylines_2022_json, "DAILY_RANKS_2022": daily_ranks_2022_json,
        },
        "2122": {
            "DATA_2021": players_2021_json, "TEAM_DATA_2021": teams_2021_json,
            "CONF_DATA_2021": conf_players_2021_json, "CONF_TEAM_DATA_2021": conf_teams_2021_json,
            "STORYLINES_2021": storylines_2021_json, "DAILY_RANKS_2021": daily_ranks_2021_json,
        },
        "1920": {
            "DATA_1920": players_2019_json, "TEAM_DATA_1920": teams_2019_json,
            "CONF_DATA_1920": conf_players_2019_json, "CONF_TEAM_DATA_1920": conf_teams_2019_json,
            "STORYLINES_1920": storylines_2019_json, "DAILY_RANKS_1920": daily_ranks_2019_json,
        },
        "1819": {
            "DATA_1819": players_1819_json, "TEAM_DATA_1819": teams_1819_json,
            "CONF_DATA_1819": conf_players_1819_json, "CONF_TEAM_DATA_1819": conf_teams_1819_json,
            "STORYLINES_1819": storylines_1819_json, "DAILY_RANKS_1819": daily_ranks_1819_json,
        },
        "1718": {
            "DATA_1718": players_1718_json, "TEAM_DATA_1718": teams_1718_json,
            "CONF_DATA_1718": conf_players_1718_json, "CONF_TEAM_DATA_1718": conf_teams_1718_json,
            "STORYLINES_1718": storylines_1718_json, "DAILY_RANKS_1718": daily_ranks_1718_json,
        },
    }
    # Historical subset-scope datasets (Last 5/10/Playoffs) ride in each season's
    # lazy-loaded file as window globals LAST5_TEAM_DATA_<key> etc.
    for _skey, _sub in (subset_by_season or {}).items():
        if _skey == "2526" or _skey not in season_payloads:
            continue
        season_payloads[_skey][f"LAST5_TEAM_DATA_{_skey}"] = _embed(_sub.get("last5_teams", []))
        season_payloads[_skey][f"LAST10_TEAM_DATA_{_skey}"] = _embed(_sub.get("last10_teams", []))
        season_payloads[_skey][f"PLAYOFF_TEAM_DATA_{_skey}"] = _embed(_sub.get("playoff_teams", []))
        season_payloads[_skey][f"LAST5_DATA_{_skey}"] = _embed(_sub.get("last5_players", []))
        season_payloads[_skey][f"LAST10_DATA_{_skey}"] = _embed(_sub.get("last10_players", []))
        season_payloads[_skey][f"PLAYOFF_DATA_{_skey}"] = _embed(_sub.get("playoff_players", []))
    season_files = {
        f"season_{key}.js": "__installSeason('%s', {%s});\n" % (
            key, ",".join(f'"{name}":{payload}' for name, payload in datasets.items())
        )
        for key, datasets in season_payloads.items()
    }
    # Per-game player box scores, one lazy-loaded file per season (including
    # the current one — box data never rides in the initial HTML payload).
    for key, boxes in (game_boxes or {}).items():
        season_files[f"boxes_{key}.js"] = f"__installBoxes('{key}', {_embed(boxes)});\n"
    # Full team rosters (no minutes qualification) for the Team Stats panel.
    for key, rosters in (team_rosters or {}).items():
        season_files[f"rosters_{key}.js"] = f"__installRosters('{key}', {_embed(rosters)});\n"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WSC North Individual Statistics Leaderboard - 2025-26</title>
<script>try{{if(sessionStorage.getItem('lbNav'))document.documentElement.classList.add('lb-restoring');}}catch(e){{}}</script>
<style>
  /* When restoring a saved spot on refresh, hide all content until the restore runs
     so the default (Individual) page never flashes. Removed at DOMContentLoaded. */
  html.lb-restoring [id$="-view"], html.lb-restoring .filter-bar,
  html.lb-restoring #page-title, html.lb-restoring #page-subtitle,
  html.lb-restoring #page-info {{ display: none !important; }}
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

  /* Individual Basic Stats: cap the Name column so a long name can't stretch it */
  #leaderboard th:nth-child(2), #leaderboard td:nth-child(2) {{
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
  }}

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
    white-space: nowrap;
  }}
  .toggle-wrap button {{
    padding: 8px 20px;
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
  .td-logo-wrap {{
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 104px;
    margin: 0 auto 12px;
  }}
  .td-logo {{
    display: block;
    max-width: 150px;
    max-height: 112px;
    object-fit: contain;
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
    overflow-x: auto; /* keep the table inside the card instead of spilling out */
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
  .td-schedule td {{ padding: 5px 6px; border-bottom: 1px solid #eee; font-size: 0.8rem; white-space: nowrap; }}
  .td-schedule tr:hover td {{ background: #f0f0f0; }}
  .td-schedule tr.sched-win td {{ background: rgb(0,255,0) !important; color: #000 !important; }}
  .td-schedule tr.sched-loss td {{ background: rgb(255,0,0) !important; color: #000 !important; }}
  .td-schedule tr.sched-win:hover td {{ background: rgb(0,230,0) !important; }}
  .td-schedule tr.sched-loss:hover td {{ background: rgb(230,0,0) !important; }}
  .td-schedule tr.sched-win a, .td-schedule tr.sched-loss a {{ color: #000 !important; }}
  .td-schedule tr a.box-link {{ color: #0d47a1 !important; font-weight: 700; text-decoration: none; }}
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
  /* --- Charts --- */
  .charts-shell {{
    max-width: 1180px;
    margin: 0 auto;
    color: #111;
  }}
  .charts-toolbar {{
    display: flex;
    justify-content: center;
    align-items: flex-end;
    flex-wrap: wrap;
    gap: 14px;
    margin: 8px 0 14px;
  }}
  .charts-segment {{
    display: inline-flex;
    border: 1px solid #4fc3f7;
    border-radius: 6px;
    overflow: hidden;
  }}
  .charts-segment button {{
    border: 0;
    border-right: 1px solid #4fc3f7;
    background: transparent;
    color: #4fc3f7;
    padding: 7px 18px;
    font-weight: 700;
    cursor: pointer;
  }}
  .charts-segment button:last-child {{ border-right: 0; }}
  .charts-segment button.active {{
    background: #4fc3f7;
    color: #0a0a0a;
  }}
  .charts-segment button:disabled {{
    opacity: 0.45;
    cursor: default;
  }}
  .charts-control-grid {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: flex-end;
    justify-content: center;
  }}
  .charts-control-group {{
    display: flex;
    flex-direction: column;
    gap: 3px;
  }}
  .charts-control-group label {{
    color: #ddd;
    font-size: 0.74rem;
    font-weight: 700;
  }}
  .charts-control-group select {{
    min-width: 160px;
    background: #1a1a2e;
    color: #fff;
    border: 1px solid #4fc3f7;
    border-radius: 4px;
    padding: 6px 8px;
    font-size: 0.8rem;
  }}
  .metric-combo {{ position: relative; display: inline-block; }}
  .metric-combo-input {{
    min-width: 210px;
    background: #1a1a2e;
    color: #fff;
    border: 1px solid #4fc3f7;
    border-radius: 4px;
    padding: 6px 8px;
    font-size: 0.8rem;
  }}
  .metric-combo-input::placeholder {{ color: #6a6a85; }}
  .metric-combo-list {{
    position: absolute;
    z-index: 60;
    left: 0; right: 0; top: 100%;
    margin-top: 2px;
    max-height: 260px;
    overflow-y: auto;
    background: #13131f;
    border: 1px solid #4fc3f7;
    border-radius: 4px;
    box-shadow: 0 6px 18px rgba(0,0,0,0.55);
  }}
  .metric-combo-opt {{ padding: 6px 9px; font-size: 0.78rem; color: #dfeaff; cursor: pointer; white-space: nowrap; }}
  .metric-combo-opt:hover {{ background: #1d3a5c; }}
  .metric-combo-opt.sel {{ background: #24507a; font-weight: 700; }}
  .metric-combo-empty {{ padding: 6px 9px; font-size: 0.78rem; color: #888; }}
  .charts-action-row {{
    display: flex;
    gap: 5px;
  }}
  .charts-action-row button {{
    border: 1px solid #4fc3f7;
    border-radius: 4px;
    background: #111827;
    color: #dff4ff;
    padding: 6px 9px;
    font-size: 0.8rem;
    font-weight: 700;
    cursor: pointer;
  }}
  .charts-action-row button:hover {{
    background: #1d3557;
  }}
  .charts-panel {{
    background: #f7f7f7;
    border: 1px solid #d7d7d7;
    border-radius: 8px;
    padding: 18px;
    position: relative;
  }}
  .chart-heading {{
    text-align: center;
    color: #222;
    font-size: 1.35rem;
    font-weight: 800;
    margin-bottom: 2px;
  }}
  .chart-subheading {{
    text-align: center;
    color: #555;
    font-size: 0.9rem;
    font-style: italic;
    margin-bottom: 12px;
  }}
  .chart-note {{
    color: #666;
    font-size: 0.78rem;
    text-align: center;
    margin-bottom: 8px;
  }}
  .chart-svg-wrap {{
    position: relative;
    width: 100%;
    overflow: visible;
  }}
  #charts-scatter {{
    width: 100%;
    height: auto;
    display: block;
    background: #fff;
    border-radius: 6px;
  }}
  .chart-axis-label {{
    fill: #222;
    font-size: 15px;
    font-weight: 800;
  }}
  .chart-tick {{
    fill: #444;
    font-size: 12px;
  }}
  .chart-grid {{
    stroke: #e3e3e3;
    stroke-width: 1;
  }}
  .chart-axis {{
    stroke: #bdbdbd;
    stroke-width: 1.5;
  }}
  .chart-bubble circle {{
    stroke-width: 2;
    cursor: pointer;
  }}
  .chart-bubble text {{
    pointer-events: none;
    text-anchor: middle;
    dominant-baseline: middle;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0;
  }}
  .chart-bubble image {{
    cursor: pointer;
    pointer-events: auto;
  }}
  .chart-tooltip {{
    position: fixed;
    display: none;
    z-index: 9999;
    min-width: 230px;
    max-width: 280px;
    background: #2d2b78;
    color: #fff;
    border-radius: 4px;
    padding: 9px 11px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    pointer-events: none;
    font-size: 0.78rem;
    line-height: 1.45;
  }}
  .chart-tooltip strong {{
    display: block;
    margin-bottom: 5px;
    font-size: 0.82rem;
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
      <button id="btn-charts" onclick="showView('charts')">Charts</button>
      <button id="btn-keys" onclick="showView('keys')">Keys</button>
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
<div class="info" id="page-info">{len(players)} qualified players · 30% minutes played minimum · Click any column header to sort · Generated {timestamp}</div>

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
  <button class="adv-cat-btn" data-cat="bpm2" onclick="switchIndCat('bpm2')">BPM 2.0</button>
  <button class="adv-cat-btn" data-cat="porp" onclick="switchIndCat('porp')">PRPG!</button>
  <button class="adv-cat-btn" data-cat="per" onclick="switchIndCat('per')">PER</button>
  <button class="adv-cat-btn" data-cat="ws" onclick="switchIndCat('ws')">Win Shares</button>
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
  <th>Name</th>
  <th>School</th>
  <th style="width:34px">GP</th>
  <th id="adv-volume-th" style="display:none;min-width:76px">M-A</th>
  <th id="adv-stat-th" style="min-width:90px">Stat</th>
  <th class="bpm2-th" style="display:none;min-width:74px;cursor:pointer" onclick="sortBpm2('dbpm')">DBPM</th>
  <th class="bpm2-th" style="display:none;min-width:74px;cursor:pointer" onclick="sortBpm2('bpm')">BPM</th>
  <th class="bpm2-th" style="display:none;min-width:74px;cursor:pointer" onclick="sortBpm2('vorp')">VORP</th>
  <th class="ws-th" style="display:none;min-width:60px;cursor:pointer" onclick="sortWs('dws')">DWS</th>
  <th class="ws-th" style="display:none;min-width:60px;cursor:pointer" onclick="sortWs('ws')">WS</th>
  <th class="ws-th" style="display:none;min-width:64px;cursor:pointer" onclick="sortWs('ws40')">WS/40</th>
</tr></thead>
<tbody id="adv-tbody"></tbody>
</table>
</div>
</div>
</div>
</div>

<div id="charts-view" style="display:none;">
  <div class="charts-shell">
    <div class="charts-toolbar">
      <div class="charts-segment">
        <button id="chart-mode-individual" class="active" onclick="setChartMode('individual')">Individual</button>
        <button id="chart-mode-team" onclick="setChartMode('team')">Team</button>
      </div>
      <div class="charts-control-grid">
        <div class="charts-control-group">
          <label for="chart-preset">Suggestions:</label>
          <select id="chart-preset" onchange="onChartPresetChange()">
            <option value="" selected></option>
            <option value="shooting_3p">3P% vs 3PA Rate</option>
            <option value="ast_tov">AST Rate vs TOV%</option>
            <option value="stl_blk">Stl% vs Blk%</option>
            <option value="usage_ts">Usage vs TS%</option>
          </select>
        </div>
        <div class="charts-control-group">
          <label for="chart-stats-scope">Stats Scope:</label>
          <select id="chart-stats-scope" onchange="onChartControlsChange()">
            <option value="full">Full Season</option>
            <option value="conference">Conference Only</option>
            <option value="last5">Last 5 Games</option>
            <option value="last10">Last 10 Games</option>
            <option value="playoffs">Playoffs</option>
          </select>
        </div>
        <div class="charts-control-group">
          <label for="chart-region">Region:</label>
          <select id="chart-region" onchange="onChartControlsChange()">
            <option value="Both" selected>Both</option>
            <option value="South">South</option>
            <option value="North">North</option>
          </select>
        </div>
        <div class="charts-control-group">
          <label for="chart-filter-conf">Select Conferences:</label>
          <select id="chart-filter-conf" onchange="onChartControlsChange()"><option value="All">All</option></select>
        </div>
        <div class="charts-control-group">
          <label for="chart-filter-team">Filter By Teams:</label>
          <select id="chart-filter-team" onchange="onChartControlsChange()"><option value="All">All</option></select>
        </div>
        <div class="charts-control-group">
          <label for="chart-focus-conf">Focus Conferences:</label>
          <select id="chart-focus-conf" onchange="onChartControlsChange()"><option value="All">All</option></select>
        </div>
        <div class="charts-control-group">
          <label for="chart-focus-team">Focus Teams:</label>
          <select id="chart-focus-team" onchange="onChartControlsChange()"><option value="All">All</option></select>
        </div>
        <div class="charts-control-group">
          <label>X-Axis Metric:</label>
          <div class="metric-combo">
            <input id="chart-x-input" class="metric-combo-input" type="text" placeholder="Select or type to filter…" autocomplete="off"
                   oninput="comboFilter('x')" onfocus="comboOpen('x')" onblur="comboBlur('x')" onkeydown="comboKey(event,'x')">
            <div id="chart-x-list" class="metric-combo-list" style="display:none"></div>
          </div>
        </div>
        <div class="charts-control-group">
          <label>Y-Axis Metric:</label>
          <div class="metric-combo">
            <input id="chart-y-input" class="metric-combo-input" type="text" placeholder="Select or type to filter…" autocomplete="off"
                   oninput="comboFilter('y')" onfocus="comboOpen('y')" onblur="comboBlur('y')" onkeydown="comboKey(event,'y')">
            <div id="chart-y-list" class="metric-combo-list" style="display:none"></div>
          </div>
        </div>
        <div class="charts-action-row">
          <button onclick="flipChartAxes()">Flip Axes</button>
          <button onclick="randomizeChartMetrics()">Randomize</button>
        </div>
      </div>
    </div>
    <div class="charts-panel">
      <div class="chart-heading">3-Point Percentage vs Three Point Attempt Rate</div>
      <div class="chart-subheading" id="chart-subtitle">2025-26 Individual Players</div>
      <div class="chart-note" id="chart-note"></div>
      <div class="chart-svg-wrap">
        <svg id="charts-scatter" viewBox="0 0 980 620" role="img" aria-label="3-point percentage vs three point attempt rate scatter plot"></svg>
        <div class="chart-tooltip" id="chart-tooltip"></div>
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

<div id="minmatrix-view" style="display:none;">
  <span class="td-back" onclick="closeMinutesMatrix()">← Back to Team</span>
  <div id="minmatrix-content" style="margin-top:12px"></div>
</div>

<div id="teamstats-view" style="display:none;">
  <span class="td-back" onclick="closeTeamStats()">← Back to Team</span>
  <div id="teamstats-content" style="margin-top:12px"></div>
</div>

<div id="lineups-view" style="display:none;">
  <span class="td-back" onclick="closeLineups()">← Back to Team</span>
  <div id="lineups-content" style="margin-top:12px"></div>
</div>

<div id="keys-view" style="display:none;">
  <div id="keys-subtoggle" style="margin-top:12px"></div>
  <div id="keys-content"></div>
</div>

<div id="player-view" style="display:none;">
  <span class="td-back" onclick="closePlayerProfile()">← Back</span>
  <div id="player-content" style="margin-top:12px"></div>
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
    <div id="sl-tab-height" class="sl-tab-content" style="display:none">
      <div style="padding:6px 10px 10px;color:#aaa;font-size:0.75rem;text-align:center">Average roster height from stored 2025-26 roster-height data. Ranked by average inches.</div>
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table" id="height-table"><thead><tr>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('rank')">#</th>
        <th style="cursor:pointer" onclick="slSortHeight('team')">School</th>
        <th style="cursor:pointer" onclick="slSortHeight('conference')">Conference</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('avg_inches')">Avg Inches</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('avg_height')">Avg Height</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('avg_guard_inches')">Guard Inches</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('avg_guard_height')">Guard Height</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('avg_forward_inches')">Forward Inches</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('avg_forward_height')">Forward Height</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('guard_scoring_pct')">Guard Scoring %</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('forward_scoring_pct')">Forward Scoring %</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('players')">Players</th>
        <th class="sl-th-r" style="cursor:pointer" onclick="slSortHeight('range')">Range</th>
      </tr></thead><tbody id="sl-body-height"></tbody></table></div></div>
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
    <div id="sl-tab-conf" class="sl-tab-content" style="display:none">
      <div class="sl-wab-filter" style="display:flex;align-items:center;justify-content:center;gap:8px;padding:10px 0 14px">
        <span style="font-size:13px;color:#555;font-weight:600">Data scope:</span>
        <select id="conf-scope" onchange="slRenderConf()" style="font-size:13px;padding:4px 8px;border-radius:5px;border:1px solid #888;background:#1a1a2e;color:#fff">
          <option value="nonconf" selected>Non-Conference</option>
          <option value="conf">Conference</option>
          <option value="full">Full Season</option>
        </select>
        <span style="font-size:12px;color:#888">(season set by the year selector above)</span>
      </div>
      <div class="sl-table-outer"><div class="sl-table-wrap"><table class="sl-table" id="conf-table"><thead>
        <tr>
          <th rowspan="2" style="vertical-align:bottom;cursor:pointer" onclick="slSortConf('conf')">Conference</th>
          <th class="sl-th-r" rowspan="2" style="vertical-align:bottom;cursor:pointer" onclick="slSortConf('w')">W-L</th>
          <th class="sl-th-r" rowspan="2" style="vertical-align:bottom;cursor:pointer" onclick="slSortConf('win_pct')">Win%</th>
          <th class="sl-th-r" rowspan="2" style="vertical-align:bottom;background:#2a3a5c;cursor:pointer" onclick="slSortConf('net')" title="Net Rating: ORtg − DRtg (points per 100 possessions)">Net</th>
          <th class="sl-th-r" colspan="5" style="background:#1e3a5f;border-left:2px solid #555" title="Offensive Four Factors (this conference's teams)">Team Four Factors</th>
          <th class="sl-th-r" colspan="5" style="background:#5f1e1e;border-left:2px solid #555" title="Defensive Four Factors (what this conference's teams allowed)">Opponent Four Factors</th>
        </tr>
        <tr>
          <th class="sl-th-r" style="border-left:2px solid #555;cursor:pointer" onclick="slSortConf('ortg')" title="Offensive Rating: points scored per 100 possessions">ORtg</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortConf('efg')" title="Effective FG%">eFG%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortConf('orb')" title="Offensive Rebound %">ORB%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortConf('tov')" title="Turnover %">TOV%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortConf('ftr')" title="Free Throw Attempt Rate: FTA / FGA">FTr</th>
          <th class="sl-th-r" style="border-left:2px solid #555;cursor:pointer" onclick="slSortConf('drtg')" title="Defensive Rating: points allowed per 100 possessions">DRtg</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortConf('d_efg')" title="Opponent Effective FG%">eFG%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortConf('d_orb')" title="Opponent Offensive Rebound %">ORB%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortConf('d_tov')" title="Opponent Turnover % (forced)">TOV%</th>
          <th class="sl-th-r" style="cursor:pointer" onclick="slSortConf('d_ftr')" title="Opponent Free Throw Attempt Rate">FTr</th>
        </tr>
      </thead><tbody id="sl-body-conf"></tbody></table></div></div>
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
    <th class="sl-th-r">#</th><th>Date</th><th>Game</th><th>Box</th><th>Location</th><th class="sl-th-r">Win Prob</th><th class="sl-th-r">FanMatch</th><th class="sl-th-r" title="Upset score: reward for win probability gap">Upset</th><th class="sl-th-r" title="Dominance score: margin + strength gap">Dom.</th><th class="sl-th-r" title="Tension score: closeness, overtime, even matchup">Tension</th>
  </tr></thead><tbody id="sl-body-fanmatch"></tbody></table></div></div>
  <div id="sl-lotn"></div>
</div>

<div id="boxscore-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:2000;overflow-y:auto" onclick="if(event.target===this)closeBoxScore()">
  <style>
    .bx-card {{ max-width:1180px;margin:28px auto;background:#fff;border-radius:8px;padding:16px 20px 20px;box-shadow:0 8px 40px rgba(0,0,0,0.5); }}
    .bx-title {{ text-align:center;font-size:1.35rem;font-weight:800;color:#1a3e8f;margin:2px 0 0; }}
    .bx-date {{ text-align:center;font-size:0.95rem;font-weight:700;color:#1a3e8f;margin-bottom:8px; }}
    .bx-label {{ text-align:center;font-size:0.8rem;font-weight:700;color:#000;margin-bottom:10px; }}
    .bx-table-wrap {{ overflow-x:auto;margin-bottom:14px; }}
    .bx-table {{ width:100%;border-collapse:collapse;font-size:0.74rem;white-space:nowrap;color:#000; }}
    .bx-table th {{ background:#7da7d9;color:#000;padding:4px 6px;text-align:right;border-bottom:1px solid #5588bb;font-size:0.7rem; }}
    .bx-table th.bx-l, .bx-table td.bx-l {{ text-align:left; }}
    .bx-table td {{ padding:3px 6px;text-align:right;border-bottom:1px solid #d8e2f0; }}
    /* Neutralize the page-wide odd/even row striping inside the box score */
    .bx-table tbody tr:nth-child(odd) td, .bx-table tbody tr:nth-child(even) td {{ background:#fff; }}
    .bx-table tbody tr:nth-child(odd):hover td, .bx-table tbody tr:nth-child(even):hover td {{ background:#eaf1fb; }}
    .bx-table tbody tr.bx-low td {{ background:#d6d6d6; color:#666; }}
    .bx-table tr.bx-bench-sep td {{ border-top:3px solid #1a3e8f; }}
    .bx-table .bx-team-hdr {{ background:#1a3e8f;color:#fff;text-align:center;font-weight:800;padding:5px;font-size:0.8rem; }}
    .bx-table tfoot td {{ font-weight:700;border-top:2px solid #5588bb;background:#e6eef8; }}
    .bx-poss {{ text-align:center;font-size:0.8rem;color:#000;font-weight:600;margin-top:2px; }}
    .bx-close {{ background:none;border:1px solid #999;border-radius:4px;cursor:pointer;font-size:0.85rem;padding:4px 10px;color:#333; }}
    .bx-close:hover {{ border-color:#1a3e8f;color:#1a3e8f; }}
  </style>
  <div class="bx-card">
    <div style="display:flex;justify-content:flex-end"><button class="bx-close" onclick="closeBoxScore()">&#x2715; Close</button></div>
    <div class="bx-title" id="bx-title"></div>
    <div class="bx-date" id="bx-date"></div>
    <div class="bx-label">Advanced Stats Box Score</div>
    <div id="bx-content"></div>
    <div class="bx-poss" id="bx-poss"></div>
  </div>
</div>

<script>
// --- Data decoding & lazy season loading ---
// Datasets are embedded columnar: uniform lists of objects arrive as
// {{"__c": [keys], "__r": [[values], ...]}} and are expanded here.
function __unpack(node) {{
  if (Array.isArray(node)) return node.map(__unpack);
  if (node && typeof node === 'object') {{
    if (node.__c) {{
      const cols = node.__c, out = new Array(node.__r.length);
      for (let r = 0; r < node.__r.length; r++) {{
        const row = node.__r[r], o = {{}};
        for (let i = 0; i < cols.length; i++) o[cols[i]] = __unpack(row[i]);
        out[r] = o;
      }}
      return out;
    }}
    const o = {{}};
    for (const k in node) o[k] = __unpack(node[k]);
    return o;
  }}
  return node;
}}
// Restore per-game fields the generator nulls out when redundant.
function __fixGames(teams) {{
  for (const t of (teams || [])) {{
    for (const g of (t.game_ratings || [])) {{
      if (g.pace == null) g.pace = g.possessions;
      if (g.tempo == null) g.tempo = g.possessions;
      if (g.canonical_opponent == null) g.canonical_opponent = g.opponent;
      if (g.result == null) g.result = (g.team_score || 0) > (g.opponent_score || 0) ? 'W' : 'L';
    }}
  }}
  return teams;
}}
// Conference team game_ratings are an exact subset of the full team's, so
// they ship without them and are rebuilt here.
function __deriveConfGames(confTeams, fullTeams) {{
  const byTeam = {{}};
  for (const t of (fullTeams || [])) byTeam[t.team] = t;
  for (const ct of (confTeams || [])) {{
    const full = byTeam[ct.team];
    ct.game_ratings = full ? (full.game_ratings || []).filter(g => g.is_conference) : [];
  }}
  return confTeams;
}}
const SEASON_SOURCES = {{
  '2425': 'season_data/season_2425.js',
  '2324': 'season_data/season_2324.js',
  '2223': 'season_data/season_2223.js',
  '2122': 'season_data/season_2122.js',
  '1920': 'season_data/season_1920.js',
  '1819': 'season_data/season_1819.js',
  '1718': 'season_data/season_1718.js',
}};
const __loadedSeasons = new Set(['2526']);
const __seasonWaiters = {{}};
function __installSeason(key, payload) {{
  const vals = {{}};
  for (const name in payload) vals[name] = __unpack(payload[name]);
  for (const name in vals) if (name.startsWith('TEAM_DATA')) __fixGames(vals[name]);
  for (const name in vals) if (name.startsWith('CONF_TEAM_DATA')) __deriveConfGames(vals[name], vals[name.replace('CONF_', '')]);
  for (const name in vals) window[name] = vals[name];
  __loadedSeasons.add(key);
}}
function ensureSeason(key, cb) {{
  if (__loadedSeasons.has(key) || !SEASON_SOURCES[key]) {{ cb(); return; }}
  if (__seasonWaiters[key]) {{ __seasonWaiters[key].push(cb); return; }}
  __seasonWaiters[key] = [cb];
  const s = document.createElement('script');
  s.src = SEASON_SOURCES[key];
  s.onload = () => {{ const w = __seasonWaiters[key] || []; delete __seasonWaiters[key]; w.forEach(f => f()); }};
  s.onerror = () => {{ delete __seasonWaiters[key]; console.error('Season data file missing: ' + SEASON_SOURCES[key]); }};
  document.head.appendChild(s);
}}
function ensureSeasons(keys, cb) {{
  let left = keys.length;
  if (!left) {{ cb(); return; }}
  keys.forEach(k => ensureSeason(k, () => {{ if (--left === 0) cb(); }}));
}}

// --- Per-game box scores: lazy-loaded per season from season_data/boxes_<key>.js ---
var GAME_BOXES = {{}};
const __loadedBoxes = new Set();
const __boxWaiters = {{}};
function __installBoxes(key, payload) {{
  GAME_BOXES[key] = __unpack(payload);
  __loadedBoxes.add(key);
}}
function ensureBoxes(key, cb) {{
  if (__loadedBoxes.has(key)) {{ cb(); return; }}
  if (__boxWaiters[key]) {{ __boxWaiters[key].push(cb); return; }}
  __boxWaiters[key] = [cb];
  const s = document.createElement('script');
  s.src = 'season_data/boxes_' + key + '.js';
  s.onload = () => {{ const w = __boxWaiters[key] || []; delete __boxWaiters[key]; w.forEach(f => f()); }};
  s.onerror = () => {{ delete __boxWaiters[key]; console.error('Box score data file missing: boxes_' + key + '.js'); }};
  document.head.appendChild(s);
}}
// --- Full team rosters (no minutes qualification), lazy per season ---
var TEAM_ROSTERS = {{}};
const __loadedRosters = new Set();
const __rosterWaiters = {{}};
function __installRosters(key, payload) {{
  TEAM_ROSTERS[key] = __unpack(payload);
  __loadedRosters.add(key);
}}
function ensureRosters(key, cb) {{
  if (__loadedRosters.has(key)) {{ cb(); return; }}
  if (__rosterWaiters[key]) {{ __rosterWaiters[key].push(cb); return; }}
  __rosterWaiters[key] = [cb];
  const s = document.createElement('script');
  s.src = 'season_data/rosters_' + key + '.js';
  s.onload = () => {{ const w = __rosterWaiters[key] || []; delete __rosterWaiters[key]; w.forEach(f => f()); }};
  s.onerror = () => {{ delete __rosterWaiters[key]; console.error('Roster data file missing: rosters_' + key + '.js'); }};
  document.head.appendChild(s);
}}

// Must stay in sync with _box_norm() in generate_leaderboard.py
function __boxNorm(name) {{
  let n = String(name || '').trim().toLowerCase();
  if (n.endsWith(' college')) n = n.slice(0, -8);
  return n.replace(/[^a-z0-9]/g, '');
}}
function __boxKey(date, a, b) {{
  return date + '|' + [__boxNorm(a), __boxNorm(b)].sort().join('|');
}}

function openBoxScore(date, teamA, teamB) {{
  ensureBoxes(activeSeason, () => {{
    const g = (GAME_BOXES[activeSeason] || {{}})[__boxKey(date, teamA, teamB)];
    if (!g) {{ alert('No box score available for this game.'); return; }}
    renderBoxScore(g);
  }});
}}

function closeBoxScore() {{
  document.getElementById('boxscore-modal').style.display = 'none';
  document.body.style.overflow = '';
}}

function __bxF(v, d) {{
  return v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d == null ? 1 : d);
}}

function __bxTeamTable(name, rows, oppRows) {{
  const sum = (rs, k) => rs.reduce((s, r) => s + (r[k] || 0), 0);
  const tFgm = sum(rows, 'fgm'), tFga = sum(rows, 'fga'), tTpm = sum(rows, 'tpm'), tTpa = sum(rows, 'tpa');
  const tFtm = sum(rows, 'ftm'), tFta = sum(rows, 'fta'), tOr = sum(rows, 'or'), tDr = sum(rows, 'dr');
  const tAst = sum(rows, 'ast'), tTo = sum(rows, 'to'), tStl = sum(rows, 'stl'), tBlk = sum(rows, 'blk');
  const tPf = sum(rows, 'pf'), tPts = sum(rows, 'pts'), tMin = sum(rows, 'min');
  const oFga = sum(oppRows, 'fga'), oTpa = sum(oppRows, 'tpa'), oDr = sum(oppRows, 'dr'), oOr = sum(oppRows, 'or');
  const oFta = sum(oppRows, 'fta'), oTo = sum(oppRows, 'to');
  const tPoss = tFga + 0.475 * tFta - tOr + tTo;
  const oPoss = oFga + 0.475 * oFta - oOr + oTo;

  const cells = r => {{
    return '<td>' + (r.j || '') + '</td><td class="bx-l">' + playerLink(r.n, name) + '</td><td>' + r.min + '</td>'
      + '<td>' + __bxF(r.ortg) + '</td><td>' + __bxF(r.usg) + '</td>'
      + '<td>' + __bxF(r.efg) + '</td><td>' + __bxF(r.ts) + '</td>'
      + '<td>' + __bxF(r.orp) + '</td><td>' + __bxF(r.drp) + '</td>'
      + '<td>' + __bxF(r.ap) + '</td><td>' + __bxF(r.top) + '</td>'
      + '<td>' + __bxF(r.stp) + '</td><td>' + __bxF(r.blp) + '</td>'
      + '<td>' + (r.fgm - r.tpm) + '-' + (r.fga - r.tpa) + '</td>'
      + '<td>' + r.tpm + '-' + r.tpa + '</td>'
      + '<td>' + r.ftm + '-' + r.fta + '</td>'
      + '<td>' + r.ast + '</td><td>' + r.to + '</td><td>' + r.stl + '</td><td>' + r.blk + '</td>'
      + '<td>' + r.or + '</td><td>' + r.dr + '</td><td>' + r.pf + '</td>'
      + '<td>' + __bxF(r.bpm) + '</td><td>' + __bxF(r.obpm) + '</td><td>' + __bxF(r.dbpm) + '</td>'
      + '<td><b>' + r.pts + '</b></td>';
  }};

  // Totals respect the same reliability rules: team TO or opp TO of 0 means
  // those inputs weren't tracked, so dependent totals show as dashes too.
  const toOk = tTo > 0, oToOk = oTo > 0;
  const totOrtg = toOk && tPoss > 0 ? 100 * tPts / tPoss : null;
  const totEfg = tFga > 0 ? (tFgm + 0.5 * tTpm) / tFga * 100 : null;
  const totTsDen = 2 * (tFga + 0.475 * tFta);
  const totTs = totTsDen > 0 ? tPts / totTsDen * 100 : null;
  const totOrp = (tOr + oDr) > 0 ? tOr / (tOr + oDr) * 100 : null;
  const totDrp = (tDr + oOr) > 0 ? tDr / (tDr + oOr) * 100 : null;
  const totAp = tFgm > 0 ? tAst / tFgm * 100 : null;
  const totTop = toOk && (tFga + 0.475 * tFta + tTo) > 0 ? tTo / (tFga + 0.475 * tFta + tTo) * 100 : null;
  const totStp = oToOk && oPoss > 0 ? tStl / oPoss * 100 : null;
  const totBlp = (oFga - oTpa) > 0 ? tBlk / (oFga - oTpa) * 100 : null;

  // Grey out short-stint players (9 minutes or fewer) — but only when the
  // team's minutes are actually tracked; all-1-minute teams stay white.
  const minutesReal = tMin >= 150;
  const bodyHtml = rows.map((r, i) => {{
    const classes = [];
    if (r.st === 0 && i > 0 && rows[i - 1].st === 1) classes.push('bx-bench-sep');
    if (minutesReal && r.min <= 9) classes.push('bx-low');
    const cls = classes.length ? ' class="' + classes.join(' ') + '"' : '';
    return '<tr' + cls + '>' + cells(r) + '</tr>';
  }}).join('');

  return '<div class="bx-table-wrap"><table class="bx-table">'
    + '<thead><tr><th colspan="27" class="bx-team-hdr">' + name.toUpperCase() + '</th></tr>'
    + '<tr><th>#</th><th class="bx-l">Player</th><th>Min</th><th>ORtg</th><th>Usg</th><th>eFG</th><th>TS%</th>'
    + '<th>OR%</th><th>DR%</th><th>A%</th><th>TO%</th><th>Stl%</th><th>Blk%</th>'
    + '<th>2Pt</th><th>3Pt</th><th>FT</th><th>Ast</th><th>TO</th><th>Stl</th><th>Blk</th>'
    + '<th>OR</th><th>DR</th><th>PF</th><th>BPM</th><th>OBPM</th><th>DBPM</th><th>Pts</th></tr></thead>'
    + '<tbody>' + bodyHtml + '</tbody>'
    + '<tfoot><tr><td class="bx-l" colspan="2">Totals</td><td>' + tMin + '</td>'
    + '<td>' + __bxF(totOrtg) + '</td><td></td>'
    + '<td>' + __bxF(totEfg) + '</td><td>' + __bxF(totTs) + '</td>'
    + '<td>' + __bxF(totOrp) + '</td><td>' + __bxF(totDrp) + '</td>'
    + '<td>' + __bxF(totAp) + '</td><td>' + __bxF(totTop) + '</td>'
    + '<td>' + __bxF(totStp) + '</td><td>' + __bxF(totBlp) + '</td>'
    + '<td>' + (tFgm - tTpm) + '-' + (tFga - tTpa) + '</td>'
    + '<td>' + tTpm + '-' + tTpa + '</td><td>' + tFtm + '-' + tFta + '</td>'
    + '<td>' + tAst + '</td><td>' + tTo + '</td><td>' + tStl + '</td><td>' + tBlk + '</td>'
    + '<td>' + tOr + '</td><td>' + tDr + '</td><td>' + tPf + '</td>'
    + '<td></td><td></td><td></td><td><b>' + tPts + '</b></td></tr></tfoot>'
    + '</table></div>';
}}

function renderBoxScore(g) {{
  const names = Object.keys(g.t || {{}});
  if (names.length !== 2) return;
  const sc = g.sc || {{}};
  // Winner listed first, Torvik-style
  names.sort((a, b) => (sc[b] || 0) - (sc[a] || 0));
  const [w, l] = names;
  document.getElementById('bx-title').textContent = w + ' ' + (sc[w] != null ? sc[w] : '') + ', ' + l + ' ' + (sc[l] != null ? sc[l] : '');
  document.getElementById('bx-date').textContent = g.d || '';
  document.getElementById('bx-content').innerHTML =
    __bxTeamTable(w, g.t[w], g.t[l]) + __bxTeamTable(l, g.t[l], g.t[w]);
  document.getElementById('bx-poss').textContent = g.p != null ? g.p + ' possessions' : '';
  document.getElementById('boxscore-modal').style.display = 'block';
  document.body.style.overflow = 'hidden';
}}

// Current-season + shared data (inline)
const DATA = __unpack({players_json});
const TEAM_DATA = __fixGames(__unpack({teams_json}));
const LEAGUE_AVG = __unpack({league_avg_json});
const DAILY_RANKS = __unpack({daily_ranks_json});
const REL_RATINGS = __unpack({rel_ratings_2526_json});
const REL_RATINGS_2024 = __unpack({rel_ratings_2425_json});
const REL_RATINGS_2023 = __unpack({rel_ratings_2324_json});
const REL_RATINGS_2022 = __unpack({rel_ratings_2223_json});
const PLAYER_COUNT = {len(players)};
const TIMESTAMP = '{timestamp}';
// Multi-season average-player attempt rates used as eFG%/TS% qualification
// minimums (see EFG_FGA_PER_GAME_MIN in generate_leaderboard.py). Declared
// early because chart constants reference them at script load.
const EFG_FGA_PG_MIN = {EFG_FGA_PER_GAME_MIN};
const TS_ATT_PG_MIN = {TS_ATT_PER_GAME_MIN};
const HEIGHT_DATA = __unpack({height_data_json});
const TEAM_PRIMARY_COLORS = __unpack({school_colors_json});
const TEAM_SECONDARY_COLORS = __unpack({school_secondary_colors_json});
const TEAM_LOGOS = __unpack({team_logos_json});
const CHAMPIONS_BY_SEASON = __unpack({champion_data_json});
const CONF_FF = __unpack({conf_ff_json});
const MOORPARK_LINEUPS = __unpack({moorpark_lineups_json});
const TEAM_KEYS = __unpack({team_keys_json});
const STORYLINES = __unpack({storylines_json});
const WAB_DATA = __unpack({wab_json});
const WAB_DATA_2024 = __unpack({wab_2024_json});
const WAB_DATA_2023 = __unpack({wab_2023_json});
const WAB_DATA_2022 = __unpack({wab_2022_json});
const WAB_DATA_2021 = __unpack({wab_2021_json});
const WAB_SIM_2526 = __unpack({wab_sim_2526_json});
const WAB_SIM_2425 = __unpack({wab_sim_2425_json});
const WAB_SIM_2324 = __unpack({wab_sim_2324_json});
const WAB_SIM_2223 = __unpack({wab_sim_2223_json});
const WAB_SIM_2122 = __unpack({wab_sim_2122_json});
const WAB_SIM_1920 = __unpack({wab_sim_1920_json});

// Conference-only data (current season inline; past seasons lazy-loaded)
const CONF_DATA = __unpack({conf_players_json});
const CONF_TEAM_DATA = __deriveConfGames(__unpack({conf_teams_json}), TEAM_DATA);
// Box-derived subset scopes (current season only): Last 5 / Last 10 / Playoffs
const LAST5_TEAM_DATA = __unpack({last5_teams_json});
const LAST10_TEAM_DATA = __unpack({last10_teams_json});
const PLAYOFF_TEAM_DATA = __unpack({playoff_teams_json});
const LAST5_DATA = __unpack({last5_players_json});
const LAST10_DATA = __unpack({last10_players_json});
const PLAYOFF_DATA = __unpack({playoff_players_json});

// Small per-season data kept inline (used by sub-tab season filters)
const LEAGUE_AVG_2024 = __unpack({league_avg_2024_json});
const LEAGUE_AVG_2023 = __unpack({league_avg_2023_json});
const LEAGUE_AVG_2022 = __unpack({league_avg_2022_json});
const LEAGUE_AVG_2021 = __unpack({league_avg_2021_json});
const LEAGUE_AVG_1920 = __unpack({league_avg_2019_json});
const LEAGUE_AVG_1819 = __unpack({league_avg_1819_json});
const LEAGUE_AVG_1718 = __unpack({league_avg_1718_json});
const REL_RATINGS_2021 = __unpack({rel_ratings_2122_json});
const REL_RATINGS_1920 = __unpack({rel_ratings_1920_json});
const REL_RATINGS_1819 = __unpack({rel_ratings_1819_json});
const REL_RATINGS_1718 = __unpack({rel_ratings_1718_json});

// Past-season datasets: declared here, populated on demand by
// ensureSeason() from the SEASON_SOURCES files next to this page.
var DATA_2024, TEAM_DATA_2024, CONF_DATA_2024, CONF_TEAM_DATA_2024, STORYLINES_2024, DAILY_RANKS_2024;
var DATA_2023, TEAM_DATA_2023, CONF_DATA_2023, CONF_TEAM_DATA_2023, STORYLINES_2023, DAILY_RANKS_2023;
var DATA_2022, TEAM_DATA_2022, CONF_DATA_2022, CONF_TEAM_DATA_2022, STORYLINES_2022, DAILY_RANKS_2022;
var DATA_2021, TEAM_DATA_2021, CONF_DATA_2021, CONF_TEAM_DATA_2021, STORYLINES_2021, DAILY_RANKS_2021;
var DATA_1920, TEAM_DATA_1920, CONF_DATA_1920, CONF_TEAM_DATA_1920, STORYLINES_1920, DAILY_RANKS_1920;
var DATA_1819, TEAM_DATA_1819, CONF_DATA_1819, CONF_TEAM_DATA_1819, STORYLINES_1819, DAILY_RANKS_1819;
var DATA_1718, TEAM_DATA_1718, CONF_DATA_1718, CONF_TEAM_DATA_1718, STORYLINES_1718, DAILY_RANKS_1718;

// RPI data (Overall + Non-Conference) per season
const RPI_DATA_2526 = __unpack({rpi_data_2526_json});
const RPI_DATA_2425 = __unpack({rpi_data_2425_json});
const RPI_DATA_2324 = __unpack({rpi_data_2324_json});
const RPI_DATA_2223 = __unpack({rpi_data_2223_json});
const RPI_DATA_2122 = __unpack({rpi_data_2122_json});
const RPI_DATA_1920 = __unpack({rpi_data_1920_json});
const RPI_DATA_1819 = __unpack({rpi_data_1819_json});
const RPI_DATA_1718 = __unpack({rpi_data_1718_json});

// Active data references (swapped by toggle)
let activeData = DATA;
let activeTeamData = TEAM_DATA;
let activeLeagueAvg = LEAGUE_AVG;
let activeSeason = '2526';
let confMode = false;
let currentTeamMode = 'advanced';

// Filter configuration
const CONF_SECTIONS = {_jc({c: info["region"] for c, info in CONFERENCES.items()})};
const ALL_CONFS = {_jc(sorted(CONFERENCES.keys()))};
const TEAMS_BY_CONF = {_jc({c: sorted(info["teams"]) for c, info in CONFERENCES.items()})};

let curRegion = 'All';
let selConfs = new Set();   // empty = All
let selTeams = new Set();   // empty = All
let chartFilterConference = 'All';
let chartFilterTeam = 'All';
let chartRegion = 'Both';   // charts-only region filter: Both / South / North
let chartFocusConference = 'All';
let chartFocusTeam = 'All';
let chartMode = 'individual';
let chartStatsScope = 'full';
let chartPreset = '';
let chartXMetric = 'tpp';
let chartYMetric = 'tpa_rate';
let chartAnimateNext = false;

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
    if (p.q === 0) return false;  // sub-30% players: loaded for comps, hidden from leaderboard
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

function chartSeasonLabel() {{
  return activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26';
}}

function activeFullTeamData() {{
  return activeSeason === '1718' ? TEAM_DATA_1718
    : activeSeason === '1819' ? TEAM_DATA_1819
    : activeSeason === '1920' ? TEAM_DATA_1920
    : activeSeason === '2122' ? TEAM_DATA_2021
    : activeSeason === '2223' ? TEAM_DATA_2022
    : activeSeason === '2324' ? TEAM_DATA_2023
    : activeSeason === '2425' ? TEAM_DATA_2024
    : TEAM_DATA;
}}

function activeFullPlayerData() {{
  return activeSeason === '1718' ? DATA_1718
    : activeSeason === '1819' ? DATA_1819
    : activeSeason === '1920' ? DATA_1920
    : activeSeason === '2122' ? DATA_2021
    : activeSeason === '2223' ? DATA_2022
    : activeSeason === '2324' ? DATA_2023
    : activeSeason === '2425' ? DATA_2024
    : DATA;
}}

function activeConferencePlayerData() {{
  return activeSeason === '1718' ? CONF_DATA_1718
    : activeSeason === '1819' ? CONF_DATA_1819
    : activeSeason === '1920' ? CONF_DATA_1920
    : activeSeason === '2122' ? CONF_DATA_2021
    : activeSeason === '2223' ? CONF_DATA_2022
    : activeSeason === '2324' ? CONF_DATA_2023
    : activeSeason === '2425' ? CONF_DATA_2024
    : CONF_DATA;
}}

function activeConferenceTeamData() {{
  return activeSeason === '1718' ? CONF_TEAM_DATA_1718
    : activeSeason === '1819' ? CONF_TEAM_DATA_1819
    : activeSeason === '1920' ? CONF_TEAM_DATA_1920
    : activeSeason === '2122' ? CONF_TEAM_DATA_2021
    : activeSeason === '2223' ? CONF_TEAM_DATA_2022
    : activeSeason === '2324' ? CONF_TEAM_DATA_2023
    : activeSeason === '2425' ? CONF_TEAM_DATA_2024
    : CONF_TEAM_DATA;
}}

// Box-derived subset scopes are computed for the current season only.
const CHART_SUBSET_SCOPES = {{ last5: 1, last10: 1, playoffs: 1 }};
function chartScopeLabel() {{
  return chartStatsScope === 'conference' ? 'Conference Only'
    : chartStatsScope === 'last5' ? 'Last 5 Games'
    : chartStatsScope === 'last10' ? 'Last 10 Games'
    : chartStatsScope === 'playoffs' ? 'Playoffs' : 'Full Season';
}}
// Subset data: current season is in-scope consts (inline); historical seasons are
// window globals suffixed _<key> (lazy-loaded with the season file).
function _subsetVar(prefix) {{
  if (activeSeason === '2526') {{
    const m = {{ LAST5_TEAM_DATA, LAST10_TEAM_DATA, PLAYOFF_TEAM_DATA, LAST5_DATA, LAST10_DATA, PLAYOFF_DATA }};
    return m[prefix] || null;
  }}
  return window[prefix + '_' + activeSeason] || null;
}}
function chartSubsetTeamData() {{
  const p = chartStatsScope === 'last5' ? 'LAST5_TEAM_DATA'
    : chartStatsScope === 'last10' ? 'LAST10_TEAM_DATA'
    : chartStatsScope === 'playoffs' ? 'PLAYOFF_TEAM_DATA' : null;
  return p ? _subsetVar(p) : null;
}}
function chartSubsetPlayerData() {{
  const p = chartStatsScope === 'last5' ? 'LAST5_DATA'
    : chartStatsScope === 'last10' ? 'LAST10_DATA'
    : chartStatsScope === 'playoffs' ? 'PLAYOFF_DATA' : null;
  return p ? _subsetVar(p) : null;
}}

function chartPlayerDataSource() {{
  let src = null;
  if (CHART_SUBSET_SCOPES[chartStatsScope]) src = chartSubsetPlayerData();
  if (!src) src = chartStatsScope === 'conference' ? activeConferencePlayerData() : activeFullPlayerData();
  return src.filter(p => p.q !== 0);  // exclude sub-threshold players from charts
}}

function chartTeamDataSource() {{
  if (CHART_SUBSET_SCOPES[chartStatsScope]) {{ const d = chartSubsetTeamData(); if (d) return d; }}
  return chartStatsScope === 'conference' ? activeConferenceTeamData() : activeFullTeamData();
}}

function chartInitials(name) {{
  const parts = String(name || '').replace(/\\b(Jr|Sr|II|III|IV|V)\\.?$/i, '').trim().split(/\\s+/).filter(Boolean);
  if (parts.length === 0) return '';
  if (parts.length === 1) {{
    const hy = parts[0].split(/[-‐-―]/).filter(Boolean);
    if (hy.length > 1) return (hy[0][0] + hy[hy.length - 1][0]).toUpperCase();
    return parts[0].slice(0, 2).toUpperCase();
  }}
  // Hyphenated last names get a 3-letter initial (e.g. John Smith-Jones -> JSJ)
  const last = parts[parts.length - 1];
  const hy = last.split(/[-‐-―]/).filter(Boolean);
  if (hy.length > 1) return (parts[0][0] + hy[0][0] + hy[hy.length - 1][0]).toUpperCase();
  return (parts[0][0] + last[0]).toUpperCase();
}}

function chartTextColor(hex) {{
  const fallback = '#ffffff';
  if (!hex || !/^#?[0-9a-f]{{6}}$/i.test(hex)) return fallback;
  const clean = hex.replace('#', '');
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return (r * 0.299 + g * 0.587 + b * 0.114) > 160 ? '#111111' : '#ffffff';
}}

// null/undefined -> NaN so unplottable players drop out of charts entirely
// (Number(null) is 0, which would plot at the axis floor). Ratings also treat
// exact 0 as missing: the analytics emit 0.0 for degenerate/no-data cases.
function __cnum(v) {{
  return v == null ? NaN : Number(v);
}}
function __crating(v) {{
  const n = __cnum(v);
  return n === 0 ? NaN : n;
}}

const CHART_METRICS = {{
  tpp: {{ label: '3-Point Percentage', short: '3P%', unit: '%', value: p => __cnum(p.tpp), tickStep: 5 }},
  tpa_rate: {{ label: 'Three Point Attempt Rate', short: '3PA Rate', unit: '%', value: p => {{ const fga = Number(p.fga || 0); return fga > 0 ? Number(p.tpa || 0) / fga * 100 : NaN; }}, tickStep: 10 }},
  ts_pct: {{ label: 'True Shooting Percentage', short: 'TS%', unit: '%', value: p => __cnum(p.ts_pct), tickStep: 5 }},
  usage_pct: {{ label: 'Usage Percentage', short: '%Poss', unit: '%', value: p => __cnum(p.usage_pct), tickStep: 5 }},
  efg_pct: {{ label: 'Effective FG Percentage', short: 'eFG%', unit: '%', value: p => __cnum(p.efg_pct), tickStep: 5 }},
  twop: {{ label: 'Two Point Percentage', short: '2P%', unit: '%', value: p => __cnum(p.twop), tickStep: 5 }},
  ftp: {{ label: 'Free Throw Percentage', short: 'FT%', unit: '%', value: p => __cnum(p.ftp), tickStep: 10 }},
  ft_rate: {{ label: 'Free Throw Rate', short: 'FT Rate', unit: '', value: p => __cnum(p.ft_rate), tickStep: 10 }},
  ind_ortg: {{ label: 'Offensive Rating', short: 'ORtg', unit: '', value: p => __crating(p.ind_ortg), tickStep: 10 }},
  porp: {{ label: 'PORPAGATU!', short: 'PRPG!', unit: '', value: p => __cnum(p.porp), tickStep: 1 }},
  ind_drtg: {{ label: 'Defensive Rating', short: 'DRtg', unit: '', value: p => __crating(p.ind_drtg), tickStep: 10, lowerBetter: true }},
  min_pct: {{ label: 'Minutes Percentage', short: '%Min', unit: '%', value: p => __cnum(p.min_pct), tickStep: 10 }},
  ast_rate: {{ label: 'Assist Rate', short: 'ARate', unit: '%', value: p => __cnum(p.ast_rate), tickStep: 5 }},
  tov_pct: {{ label: 'Turnover Percentage', short: 'TO%', unit: '%', value: p => __cnum(p.tov_pct), tickStep: 5, lowerBetter: true }},
  oreb_pct: {{ label: 'Offensive Rebound Percentage', short: 'OREB%', unit: '%', value: p => __cnum(p.oreb_pct), tickStep: 5 }},
  dreb_pct: {{ label: 'Defensive Rebound Percentage', short: 'DREB%', unit: '%', value: p => __cnum(p.dreb_pct), tickStep: 5 }},
  stl_pct: {{ label: 'Steal Percentage', short: 'Stl%', unit: '%', value: p => __cnum(p.stl_pct), tickStep: 2 }},
  blk_pct: {{ label: 'Block Percentage', short: 'Blk%', unit: '%', value: p => __cnum(p.blk_pct), tickStep: 2 }},
  bpm: {{ label: 'BPM 2.0', short: 'BPM', unit: '', value: p => __cnum(p.bpm), tickStep: 2 }},
  per: {{ label: 'Player Efficiency Rating', short: 'PER', unit: '', value: p => __cnum(p.per), tickStep: 5 }},
  ws: {{ label: 'Win Shares', short: 'WS', unit: '', value: p => __cnum(p.ws), tickStep: 2 }},
  ows: {{ label: 'Offensive Win Shares', short: 'OWS', unit: '', value: p => __cnum(p.ows), tickStep: 2 }},
  dws: {{ label: 'Defensive Win Shares', short: 'DWS', unit: '', value: p => __cnum(p.dws), tickStep: 1 }},
  ws40: {{ label: 'Win Shares / 40', short: 'WS/40', unit: '', value: p => __cnum(p.ws40), tickStep: 0.1 }},
  // ── Per-game counting stats ──
  ppg: {{ label: 'Points / Game', short: 'PPG', unit: '', value: p => __cnum(p.ppg), tickStep: 5 }},
  rpg: {{ label: 'Rebounds / Game', short: 'RPG', unit: '', value: p => __cnum(p.rpg), tickStep: 2 }},
  orpg: {{ label: 'Off Rebounds / Game', short: 'OREB', unit: '', value: p => __cnum(p.orpg), tickStep: 1 }},
  drpg: {{ label: 'Def Rebounds / Game', short: 'DREB', unit: '', value: p => __cnum(p.drpg), tickStep: 1 }},
  apg: {{ label: 'Assists / Game', short: 'APG', unit: '', value: p => __cnum(p.apg), tickStep: 1 }},
  spg: {{ label: 'Steals / Game', short: 'SPG', unit: '', value: p => __cnum(p.spg), tickStep: 0.5 }},
  bpg: {{ label: 'Blocks / Game', short: 'BPG', unit: '', value: p => __cnum(p.bpg), tickStep: 0.5 }},
  topg: {{ label: 'Turnovers / Game', short: 'TO', unit: '', value: p => __cnum(p.topg), tickStep: 1, lowerBetter: true }},
  mpg: {{ label: 'Minutes / Game', short: 'MPG', unit: '', value: p => __cnum(p.mpg), tickStep: 5 }},
  gs: {{ label: 'Games Started', short: 'GS', unit: '', value: p => __cnum(p.gs), tickStep: 5 }},
  shot_pct: {{ label: 'Shot Percentage', short: '%Shots', unit: '%', value: p => __cnum(p.shot_pct), tickStep: 5 }},
  // ── Per-40 counting stats (per-game scaled to 40 minutes) ──
  pts40: {{ label: 'Points / 40', short: 'Pts/40', unit: '', value: p => __per40(p, 'ppg'), tickStep: 5 }},
  reb40: {{ label: 'Rebounds / 40', short: 'Reb/40', unit: '', value: p => __per40(p, 'rpg'), tickStep: 2 }},
  ast40: {{ label: 'Assists / 40', short: 'Ast/40', unit: '', value: p => __per40(p, 'apg'), tickStep: 1 }},
  stl40: {{ label: 'Steals / 40', short: 'Stl/40', unit: '', value: p => __per40(p, 'spg'), tickStep: 0.5 }},
  blk40: {{ label: 'Blocks / 40', short: 'Blk/40', unit: '', value: p => __per40(p, 'bpg'), tickStep: 0.5 }},
  to40: {{ label: 'Turnovers / 40', short: 'TO/40', unit: '', value: p => __per40(p, 'topg'), tickStep: 1, lowerBetter: true }},
  // ── Ratios & fouls ──
  ast_tov: {{ label: 'Assist / Turnover Ratio', short: 'AST/TO', unit: '', value: p => {{ const t = Number(p.topg || 0); return t > 0 ? Number(p.apg || 0) / t : NaN; }}, tickStep: 0.5 }},
  stl_tov: {{ label: 'Steal / Turnover Ratio', short: 'STL/TO', unit: '', value: p => {{ const t = Number(p.topg || 0); return t > 0 ? Number(p.spg || 0) / t : NaN; }}, tickStep: 0.25 }},
  fc_per_40: {{ label: 'Fouls Committed / 40', short: 'FC/40', unit: '', value: p => __cnum(p.fc_per_40), tickStep: 1, lowerBetter: true }},
  fd_per_40: {{ label: 'Fouls Drawn / 40', short: 'FD/40', unit: '', value: p => __cnum(p.fd_per_40), tickStep: 1 }},
  opf40: {{ label: 'Offensive Fouls / 40', short: 'OPF/40', unit: '', value: p => p.fc_per_40 != null ? Number(p.fc_per_40) * 0.163 : NaN, tickStep: 0.2, lowerBetter: true }},
  dpf40: {{ label: 'Defensive Fouls / 40', short: 'DPF/40', unit: '', value: p => p.fc_per_40 != null ? Number(p.fc_per_40) * 0.837 : NaN, tickStep: 1 }},
  hakeem: {{ label: 'Hakeem % (Stl% + Blk%)', short: 'Hakeem%', unit: '%', value: p => (p.stl_pct != null && p.blk_pct != null) ? Number(p.stl_pct) + Number(p.blk_pct) : NaN, tickStep: 2 }}
}};
function __per40(p, pgKey) {{
  const mpg = Number(p.mpg || 0);
  // Per-40 requires trustworthy minutes data. p.fm === 1 flags a "false minutes"
  // team (fewer than 18 clean box scores / fake minutes), where mpg is unreliable
  // and per-40 explodes (e.g. 20 pts in 1 min -> 800/40). Restrict those out.
  if (Number(p.fm) !== 0) return NaN;
  return mpg > 0 ? Number(p[pgKey] || 0) * 40 / mpg : NaN;
}}
const CHART_METRIC_ORDER = ['tpp','tpa_rate','ts_pct','usage_pct','shot_pct','efg_pct','twop','ftp','ft_rate','ind_ortg','ind_drtg','porp','bpm','per','ws','ows','dws','ws40','min_pct','mpg','gs','ast_rate','tov_pct','oreb_pct','dreb_pct','stl_pct','blk_pct','ppg','rpg','orpg','drpg','apg','spg','bpg','topg','pts40','reb40','ast40','stl40','blk40','to40','ast_tov','stl_tov','fc_per_40','fd_per_40','opf40','dpf40','hakeem'];
const TEAM_CHART_METRICS = {{
  ortg: {{ label: 'Offensive Rating', short: 'ORtg', unit: '', value: t => Number(t.ortg), tickStep: 5 }},
  drtg: {{ label: 'Defensive Rating', short: 'DRtg', unit: '', value: t => Number(t.drtg), tickStep: 5, lowerBetter: true }},
  net_rtg: {{ label: 'Net Rating', short: 'Net', unit: '', value: t => Number(t.net_rtg), tickStep: 5 }},
  tempo: {{ label: 'Tempo', short: 'Tempo', unit: '', value: t => Number(t.tempo), tickStep: 5 }},
  ts_pct: {{ label: 'True Shooting Percentage', short: 'TS%', unit: '%', value: t => Number(t.ts_pct), tickStep: 5 }},
  efg_pct: {{ label: 'Effective FG Percentage', short: 'eFG%', unit: '%', value: t => Number(t.efg_pct), tickStep: 5 }},
  twop: {{ label: 'Two Point Percentage', short: '2P%', unit: '%', value: t => Number(t.twop), tickStep: 5 }},
  tpp: {{ label: 'Three Point Percentage', short: '3P%', unit: '%', value: t => Number(t.tpp), tickStep: 5 }},
  ftp: {{ label: 'Free Throw Percentage', short: 'FT%', unit: '%', value: t => Number(t.ftp), tickStep: 5 }},
  ast_pct: {{ label: 'Assist Percentage', short: 'AST%', unit: '%', value: t => Number(t.ast_pct), tickStep: 5 }},
  tov_pct: {{ label: 'Turnover Percentage', short: 'TOV%', unit: '%', value: t => Number(t.tov_pct), tickStep: 5, lowerBetter: true }},
  nst_pct: {{ label: 'Non-Steal Turnover Percentage', short: 'NST%', unit: '%', value: t => Number(t.possessions) > 0 ? Math.max(Number(t.topg) - Number(t.opp_spg), 0) / Number(t.possessions) * 100 : NaN, tickStep: 2, lowerBetter: true }},
  oreb_pct: {{ label: 'Offensive Rebound Percentage', short: 'OREB%', unit: '%', value: t => Number(t.oreb_pct), tickStep: 5 }},
  dreb_pct: {{ label: 'Defensive Rebound Percentage', short: 'DREB%', unit: '%', value: t => Number(t.dreb_pct), tickStep: 5 }},
  ft_rate: {{ label: 'Free Throw Rate', short: 'FT Rate', unit: '', value: t => Number(t.ft_rate), tickStep: 5 }},
  tpa_pct: {{ label: 'Three Point Attempt Rate', short: '3PAr', unit: '%', value: t => Number(t.tpa_pct), tickStep: 5 }},
  stl_pct: {{ label: 'Steal Percentage', short: 'STL%', unit: '%', value: t => Number(t.stl_pct), tickStep: 2 }},
  blk_pct: {{ label: 'Block Percentage', short: 'BLK%', unit: '%', value: t => Number(t.blk_pct), tickStep: 2 }},
  opp_ts_pct: {{ label: 'Opponent True Shooting Percentage', short: 'Opp TS%', unit: '%', value: t => Number(t.opp_ts_pct), tickStep: 5, lowerBetter: true }},
  opp_efg_pct: {{ label: 'Opponent Effective FG Percentage', short: 'Opp eFG%', unit: '%', value: t => Number(t.opp_efg_pct), tickStep: 5, lowerBetter: true }},
  opp_twop: {{ label: 'Opponent Two Point Percentage', short: 'Opp 2P%', unit: '%', value: t => Number(t.opp_twop), tickStep: 5, lowerBetter: true }},
  opp_tpp: {{ label: 'Opponent Three Point Percentage', short: 'Opp 3P%', unit: '%', value: t => Number(t.opp_tpp), tickStep: 5, lowerBetter: true }},
  opp_ftp: {{ label: 'Opponent Free Throw Percentage', short: 'Opp FT%', unit: '%', value: t => Number(t.opp_ftp), tickStep: 5, lowerBetter: true }},
  opp_ast_pct: {{ label: 'Opponent Assist Percentage', short: 'Opp AST%', unit: '%', value: t => Number(t.possessions) > 0 ? Number(t.opp_apg || 0) / Number(t.possessions) * 100 : NaN, tickStep: 5, lowerBetter: true }},
  opp_tov_pct: {{ label: 'Opponent Turnover Percentage', short: 'Opp TOV%', unit: '%', value: t => Number(t.opp_tov_pct), tickStep: 5 }},
  opp_nst_pct: {{ label: 'Opponent Non-Steal Turnover Percentage', short: 'Opp NST%', unit: '%', value: t => Number(t.possessions) > 0 ? Math.max(Number(t.opp_topg) - Number(t.spg), 0) / Number(t.possessions) * 100 : NaN, tickStep: 2 }},
  opp_oreb_pct: {{ label: 'Opponent Offensive Rebound Percentage', short: 'Opp OREB%', unit: '%', value: t => 100 - Number(t.dreb_pct), tickStep: 5, lowerBetter: true }},
  opp_dreb_pct: {{ label: 'Opponent Defensive Rebound Percentage', short: 'Opp DREB%', unit: '%', value: t => 100 - Number(t.oreb_pct), tickStep: 5, lowerBetter: true }},
  opp_ft_rate: {{ label: 'Opponent Free Throw Rate', short: 'Opp FT Rate', unit: '', value: t => Number(t.opp_ft_rate), tickStep: 5, lowerBetter: true }},
  opp_tpa_pct: {{ label: 'Opponent Three Point Attempt Rate', short: 'Opp 3PAr', unit: '%', value: t => Number(t.opp_tpa_pct), tickStep: 5, lowerBetter: true }},
  opp_stl_pct: {{ label: 'Opponent Steal Percentage', short: 'Opp STL%', unit: '%', value: t => Number(t.possessions) > 0 ? Number(t.opp_spg || 0) / Number(t.possessions) * 100 : NaN, tickStep: 2, lowerBetter: true }},
  opp_blk_pct: {{ label: 'Opponent Block Percentage', short: 'Opp BLK%', unit: '%', value: t => Number((t.totals || {{}}).FGA || 0) > 0 ? Number(t.opp_bpg || 0) / Number((t.totals || {{}}).FGA) * 100 : NaN, tickStep: 2, lowerBetter: true }},
  bench_pts: {{ label: 'Bench Points (total)', short: 'Bench Pts', unit: '', value: t => Number(t.bench_pts), tickStep: 50 }},
  bench_ppg: {{ label: 'Bench Points / Game', short: 'Bench/G', unit: '', value: t => Number(t.bench_ppg), tickStep: 2 }},
  bench_pct: {{ label: 'Bench Points %', short: 'Bench%', unit: '%', value: t => Number(t.bench_pct), tickStep: 5 }},
  bench_per100: {{ label: 'Bench Points / 100 Poss', short: 'Bench/100', unit: '', value: t => Number(t.bench_per100), tickStep: 2 }},
  bench_per40: {{ label: 'Bench Points / 40 Min (projected, clean games)', short: 'Bench/40', unit: '', value: t => t.bench_per40 == null ? NaN : Number(t.bench_per40), tickStep: 2 }}
}};
const TEAM_CHART_METRIC_ORDER = ['ortg','drtg','net_rtg','tempo','ts_pct','efg_pct','twop','tpp','ftp','ast_pct','tov_pct','nst_pct','oreb_pct','dreb_pct','ft_rate','tpa_pct','stl_pct','blk_pct','opp_ts_pct','opp_efg_pct','opp_twop','opp_tpp','opp_ftp','opp_ast_pct','opp_tov_pct','opp_nst_pct','opp_oreb_pct','opp_dreb_pct','opp_ft_rate','opp_tpa_pct','opp_stl_pct','opp_blk_pct','bench_pts','bench_ppg','bench_pct','bench_per100','bench_per40'];
// Generate the full box-score-derived team metric universe (CBB-Analytics style):
// every counting stat as Team /Game, Opponent /Game, Differential, and /100 Poss,
// plus FG%/ratios/SOS extras. Keeps the curated rate stats above at the top.
(function() {{
  const T = TEAM_CHART_METRICS, ORD = TEAM_CHART_METRIC_ORDER;
  const gp = t => Math.max(Number(t.gp) || 1, 1);
  const sh = (o, k) => Number((o || {{}})[k]) || 0;
  // [key, label, team per-game getter, opp per-game getter, lowerBetter, tickStep]
  const C = [
    ['pts','Points', t=>Number(t.ppg), t=>Number(t.opp_ppg), false, 5],
    ['reb','Rebounds', t=>Number(t.rpg), t=>Number(t.opp_rpg), false, 3],
    ['oreb','Offensive Rebounds', t=>Number(t.orebpg), t=>Number(t.opp_orebpg), false, 2],
    ['dreb','Defensive Rebounds', t=>Number(t.drebpg), t=>Number(t.opp_drebpg), false, 3],
    ['ast','Assists', t=>Number(t.apg), t=>Number(t.opp_apg), false, 2],
    ['stl','Steals', t=>Number(t.spg), t=>Number(t.opp_spg), false, 1],
    ['blk','Blocks', t=>Number(t.bpg), t=>Number(t.opp_bpg), false, 1],
    ['tov','Turnovers', t=>Number(t.topg), t=>Number(t.opp_topg), true, 2],
    ['pf','Personal Fouls', t=>Number(t.pfpg), t=>Number(t.opp_pfpg), true, 2],
    ['fgm','FGs Made', t=>sh(t.totals,'FGM')/gp(t), t=>sh(t.opp_totals,'FGM')/gp(t), false, 3],
    ['fga','FG Attempts', t=>sh(t.totals,'FGA')/gp(t), t=>sh(t.opp_totals,'FGA')/gp(t), false, 3],
    ['tpm','Threes Made', t=>sh(t.totals,'3PM')/gp(t), t=>sh(t.opp_totals,'3PM')/gp(t), false, 1],
    ['tpa','Three Attempts', t=>sh(t.totals,'3PA')/gp(t), t=>sh(t.opp_totals,'3PA')/gp(t), false, 2],
    ['ftm','FTs Made', t=>sh(t.totals,'FTM')/gp(t), t=>sh(t.opp_totals,'FTM')/gp(t), false, 2],
    ['fta','FT Attempts', t=>sh(t.totals,'FTA')/gp(t), t=>sh(t.opp_totals,'FTA')/gp(t), false, 2],
  ];
  const reg = (key, label, short, value, unit, tickStep, lowerBetter) => {{
    if (T[key]) return;
    T[key] = {{ label, short, unit: unit || '', value, tickStep: tickStep || 5, lowerBetter: !!lowerBetter }};
    ORD.push(key);
  }};
  for (const row of C) {{
    const k = row[0], lab = row[1], tpg = row[2], opg = row[3], lb = row[4], ts = row[5];
    reg(k + '_pg', lab + ' / Game', lab + '/G', tpg, '', ts, lb);
    reg('opp_' + k + '_pg', 'Opponent ' + lab + ' / Game', 'Opp ' + lab + '/G', opg, '', ts, !lb);
    reg(k + '_diff', lab + ' Differential', lab + ' Diff', t => tpg(t) - opg(t), '', ts, lb);
    reg(k + '_p100', lab + ' / 100 Poss', lab + '/100', t => {{ const p = Number(t.possessions); return p > 0 ? tpg(t) / p * 100 : NaN; }}, '', ts, lb);
  }}
  // shooting %s, ratios, schedule strength not already in the curated set
  reg('fgp', 'Field Goal Percentage', 'FG%', t => Number(t.fgp), '%', 5, false);
  reg('opp_fgp', 'Opponent Field Goal Percentage', 'Opp FG%', t => Number(t.opp_fgp), '%', 5, true);
  reg('ast_tov', 'Assist-to-Turnover Ratio', 'AST/TO', t => Number(t.ast_tov), '', 1, false);
  reg('stl_to', 'Steals-to-Opp-TO Ratio', 'STL/TO', t => Number(t.stl_to), '', 1, false);
  reg('ast_ratio', 'Assist Ratio', 'AST Ratio', t => Number(t.ast_ratio), '', 5, false);
  reg('sos', 'Strength of Schedule', 'SOS', t => Number(t.sos), '', 2, false);
  reg('ncsos', 'Non-Conference SOS', 'NCSOS', t => Number(t.ncsos), '', 2, false);
  reg('pace_adjust', 'Pace Adjustment', 'Pace Adj', t => Number(t.pace_adjust), '', 2, false);
  reg('opp_adjust', 'Opponent Adjustment', 'Opp Adj', t => Number(t.opp_adjust), '', 2, false);
}})();
const CHART_PRESETS = {{
  shooting_3p: {{ label: '3P% vs 3PA Rate', x: 'tpp', y: 'tpa_rate', qualifier: 'Minimum: 20 GP and 2.5 3PA/G' }},
  ast_tov: {{ label: 'AST Rate vs TOV%', x: 'ast_rate', y: 'tov_pct', qualifier: 'Minimum: Min% above 30%; missing Min% excluded' }},
  stl_blk: {{ label: 'Stl% vs Blk%', x: 'stl_pct', y: 'blk_pct' }},
  usage_ts: {{ label: 'Usage vs TS%', x: 'usage_pct', y: 'ts_pct' }},
  team_ortg_drtg: {{ label: 'Team ORtg vs DRtg', x: 'ortg', y: 'drtg', mode: 'team', qualifier: 'All teams with ORtg and DRtg' }},
  team_2p_3p: {{ label: '2P% vs 3P%', x: 'twop', y: 'tpp', mode: 'team' }},
  team_3par_3p: {{ label: '3PA Rate vs 3P%', x: 'tpa_pct', y: 'tpp', mode: 'team' }},
  team_ast_tov: {{ label: 'AST% vs TOV%', x: 'ast_pct', y: 'tov_pct', mode: 'team' }},
  team_stl_blk: {{ label: 'Stl% vs Blk%', x: 'stl_pct', y: 'blk_pct', mode: 'team' }},
  team_dreb_oreb: {{ label: 'DREB% vs OREB%', x: 'dreb_pct', y: 'oreb_pct', mode: 'team' }},
  team_ff_efg: {{ label: 'eFG% vs Opp eFG%', x: 'efg_pct', y: 'opp_efg_pct', mode: 'team' }},
  team_ff_oreb: {{ label: 'OREB% vs Opp OREB%', x: 'oreb_pct', y: 'opp_oreb_pct', mode: 'team' }},
  team_ff_tov: {{ label: 'TO% vs Opp TO%', x: 'tov_pct', y: 'opp_tov_pct', mode: 'team' }},
  team_ff_ftr: {{ label: 'FTR vs Opp FTR', x: 'ft_rate', y: 'opp_ft_rate', mode: 'team' }},
  team_bench_usage_eff: {{ label: 'Bench% vs Bench Pts/40', x: 'bench_pct', y: 'bench_per40', mode: 'team' }},
  team_bench_net: {{ label: 'Bench% vs Net Rating', x: 'bench_pct', y: 'net_rtg', mode: 'team' }}
}};

// Per-game attempt minimums per shooting metric (with 20 GP in full season).
// eFG%/TS% use the multi-season average-player rates; the rest use 2.5/G.
const CHART_METRIC_ATTEMPT_MIN = {{
  tpp:      p => attemptsPerGame(p, 'tpa') >= 2.5,
  tpa_rate: p => attemptsPerGame(p, 'tpa') >= 2.5,
  twop:     p => attemptsPerGame(p, 'twoa') >= 2.5,
  ftp:      p => attemptsPerGame(p, 'fta') >= 2.5,
  efg_pct:  p => attemptsPerGame(p, 'fga') >= EFG_FGA_PG_MIN,
  ts_pct:   p => attemptsPerGame(p, 'fga') + attemptsPerGame(p, 'fta') >= TS_ATT_PG_MIN,
}};
const CHART_METRIC_MIN_LABEL = {{
  tpp: '2.5 3PA/G', tpa_rate: '2.5 3PA/G', twop: '2.5 2PA/G', ftp: '2.5 FTA/G',
  efg_pct: EFG_FGA_PG_MIN + ' FGA/G', ts_pct: TS_ATT_PG_MIN + ' FGA+FTA/G',
}};

function chartShootingMinsPass(p) {{
  return [chartXMetric, chartYMetric].every(k => !CHART_METRIC_ATTEMPT_MIN[k] || CHART_METRIC_ATTEMPT_MIN[k](p));
}}

function chartQualifierLabel() {{
  const preset = CHART_PRESETS[chartPreset];
  if (chartPreset === 'ast_tov' || chartPreset === 'team_ortg_drtg') return preset.qualifier;
  if (chartMode === 'team') return 'All teams with plotted values';
  const parts = [...new Set([chartXMetric, chartYMetric].map(k => CHART_METRIC_MIN_LABEL[k]).filter(Boolean))];
  if (chartStatsScope === 'conference') {{
    return 'Minimum: 75% of team conference games' + (parts.length ? ' and ' + parts.join(', ') : '');
  }}
  return 'Minimum: 20 GP' + (parts.length ? ' and ' + parts.join(', ') : '');
}}

function activeChartMetrics() {{
  return chartMode === 'team' ? TEAM_CHART_METRICS : CHART_METRICS;
}}

function activeChartMetricOrder() {{
  return chartMode === 'team' ? TEAM_CHART_METRIC_ORDER : CHART_METRIC_ORDER;
}}

function chartFmt(metricKey, value, digits=1) {{
  const metrics = activeChartMetrics();
  const metric = metrics[metricKey] || metrics[Object.keys(metrics)[0]];
  return Number.isFinite(value) ? value.toFixed(digits) + (metric.unit || '') : '--';
}}

function chartQualifies(p) {{
  if (chartPreset === 'ast_tov') {{
    // Minutes-dependent rate stats: require reliable minutes (Min% >= 30).
    if (p.min_pct === null || p.min_pct === undefined || p.min_pct === '') return false;
    if (!Number.isFinite(Number(p.min_pct)) || Number(p.min_pct) < 30) return false;
    if (chartStatsScope !== 'conference') return true;
    const team = activeConferenceTeamData().find(t => t.team === p.school);
    const teamConfGames = team ? Number(team.gp || 0) : 0;
    return teamConfGames > 0 ? Number(p.gp || 0) >= Math.ceil(teamConfGames * 0.75) : Number(p.gp || 0) > 0;
  }}
  if (chartStatsScope === 'conference') {{
    const team = activeConferenceTeamData().find(t => t.team === p.school);
    const teamConfGames = team ? Number(team.gp || 0) : 0;
    const playerGames = Number(p.gp || 0);
    if (teamConfGames > 0 && playerGames < Math.ceil(teamConfGames * 0.75)) return false;
    if (playerGames <= 0) return false;
    return chartShootingMinsPass(p);
  }}
  return Number(p.gp || 0) >= 20 && chartShootingMinsPass(p);
}}

function chartsTopFilteredPlayers() {{
  return chartPlayerDataSource().filter(p => {{
    if (chartRegion !== 'Both' && p.region !== chartRegion) return false;
    if (selConfs.size > 0 && !selConfs.has(p.conference)) return false;
    if (selTeams.size > 0 && !selTeams.has(p.school)) return false;
    if (!chartQualifies(p)) return false;
    return true;
  }});
}}

function chartsBasePlayers() {{
  return chartsTopFilteredPlayers().filter(p => {{
    if (chartFilterConference !== 'All' && p.conference !== chartFilterConference) return false;
    if (chartFilterTeam !== 'All' && p.school !== chartFilterTeam) return false;
    return true;
  }});
}}

function chartsTopFilteredTeams() {{
  return chartTeamDataSource().filter(t => {{
    if (chartRegion !== 'Both' && t.region !== chartRegion) return false;
    if (selConfs.size > 0 && !selConfs.has(t.conference)) return false;
    if (selTeams.size > 0 && !selTeams.has(t.team)) return false;
    return Number.isFinite(Number(t.ortg)) && Number.isFinite(Number(t.drtg));
  }});
}}

function chartsBaseTeams() {{
  return chartsTopFilteredTeams().filter(t => {{
    if (chartFilterConference !== 'All' && t.conference !== chartFilterConference) return false;
    if (chartFilterTeam !== 'All' && t.team !== chartFilterTeam) return false;
    return true;
  }});
}}

function chartsPointData() {{
  const metrics = activeChartMetrics();
  const metricOrder = activeChartMetricOrder();
  const xMetric = metrics[chartXMetric] || metrics[metricOrder[0]];
  const yMetric = metrics[chartYMetric] || metrics[metricOrder[1] || metricOrder[0]];
  if (chartMode === 'team') {{
    return chartsBaseTeams().map(t => {{
      return {{ team: t, x: xMetric.value(t), y: yMetric.value(t) }};
    }}).filter(d => Number.isFinite(d.x) && Number.isFinite(d.y));
  }}
  return chartsBasePlayers().map(p => {{
    return {{ player: p, x: xMetric.value(p), y: yMetric.value(p) }};
  }}).filter(d => Number.isFinite(d.x) && Number.isFinite(d.y));
}}

function setChartMode(mode) {{
  chartMode = mode === 'team' ? 'team' : 'individual';
  if (chartMode === 'team') {{
    chartPreset = '';
    chartXMetric = 'ortg';
    chartYMetric = 'drtg';
  }} else {{
    chartPreset = (CHART_PRESETS[chartPreset] && CHART_PRESETS[chartPreset].mode === 'team') ? '' : chartPreset;
    if (!CHART_METRICS[chartXMetric]) chartXMetric = 'tpp';
    if (!CHART_METRICS[chartYMetric]) chartYMetric = 'tpa_rate';
  }}
  document.getElementById('chart-mode-individual').classList.toggle('active', mode === 'individual');
  document.getElementById('chart-mode-team').classList.toggle('active', mode === 'team');
  populateChartMetricSelects();
  renderCharts();
}}

function populateChartMetricSelects() {{
  const presetSel = document.getElementById('chart-preset');
  if (presetSel) {{
    const presetHtml = chartMode === 'team'
      ? '<option value=""></option><option value="team_ortg_drtg">Team ORtg vs DRtg</option><option value="team_ff_efg">eFG% vs Opp eFG%</option><option value="team_ff_oreb">OREB% vs Opp OREB%</option><option value="team_ff_tov">TO% vs Opp TO%</option><option value="team_ff_ftr">FTR vs Opp FTR</option><option value="team_2p_3p">2P% vs 3P%</option><option value="team_3par_3p">3PA Rate vs 3P%</option><option value="team_ast_tov">AST% vs TOV%</option><option value="team_stl_blk">Stl% vs Blk%</option><option value="team_dreb_oreb">DREB% vs OREB%</option><option value="team_bench_usage_eff">Bench% vs Bench Pts/40</option><option value="team_bench_net">Bench% vs Net Rating</option>'
      : '<option value=""></option><option value="shooting_3p">3P% vs 3PA Rate</option><option value="ast_tov">AST Rate vs TOV%</option><option value="stl_blk">Stl% vs Blk%</option><option value="usage_ts">Usage vs TS%</option>';
    if (presetSel.dataset.lastModeHtml !== presetHtml) {{
      presetSel.innerHTML = presetHtml;
      presetSel.dataset.lastModeHtml = presetHtml;
    }}
    presetSel.value = chartPreset;
  }}
  comboRender('x');
  comboRender('y');
}}

// ── Metric combobox: one field that shows the full dropdown AND filters as you type ──
function comboMetricKey(which) {{ return which === 'x' ? chartXMetric : chartYMetric; }}
function comboEls(which) {{
  return {{ inp: document.getElementById(which === 'x' ? 'chart-x-input' : 'chart-y-input'),
            list: document.getElementById(which === 'x' ? 'chart-x-list' : 'chart-y-list') }};
}}
function comboMetricLabel(key) {{ const m = activeChartMetrics(); return (m[key] && m[key].label) || key; }}
// Show the current metric's label in the input and (re)build the dropdown list filtered by `q`.
function buildComboList(which, q) {{
  const {{ list }} = comboEls(which);
  if (!list) return;
  const norm = s => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '');  // ignore spaces/punctuation: "3p" matches "3-Point"
  const nq = norm(q);
  const metrics = activeChartMetrics();
  const cur = comboMetricKey(which);
  const keys = activeChartMetricOrder().filter(k =>
    !nq || norm(metrics[k].label).includes(nq) || norm(k).includes(nq));
  list.innerHTML = keys.length
    ? keys.map(k => '<div class="metric-combo-opt' + (k === cur ? ' sel' : '') + '" data-key="' + k +
        '" onmousedown="comboPick(event,\\'' + which + '\\',\\'' + k + '\\')">' + metrics[k].label + '</div>').join('')
    : '<div class="metric-combo-empty">no match</div>';
}}
function comboRender(which) {{   // sync input text to the selected metric (list stays hidden)
  const {{ inp }} = comboEls(which);
  if (inp) inp.value = comboMetricLabel(comboMetricKey(which));
}}
function comboOpen(which) {{     // focus: show full list, select text so typing replaces
  const {{ inp, list }} = comboEls(which);
  buildComboList(which, '');
  if (list) list.style.display = 'block';
  if (inp) inp.select();
}}
function comboFilter(which) {{   // typing: narrow the list
  const {{ inp, list }} = comboEls(which);
  buildComboList(which, inp ? inp.value : '');
  if (list) list.style.display = 'block';
}}
function comboPick(ev, which, key) {{   // mousedown fires before blur, so preventDefault keeps the click
  if (ev) ev.preventDefault();
  if (which === 'x') chartXMetric = key; else chartYMetric = key;
  chartPreset = '';
  const presetSel = document.getElementById('chart-preset'); if (presetSel) presetSel.value = '';
  const {{ list }} = comboEls(which); if (list) list.style.display = 'none';
  comboRender(which);
  renderCharts();
}}
function comboBlur(which) {{      // clicked away without picking: hide list, restore the label
  setTimeout(() => {{ const {{ list }} = comboEls(which); if (list) list.style.display = 'none'; comboRender(which); }}, 150);
}}
function comboKey(ev, which) {{
  const {{ list }} = comboEls(which);
  if (ev.key === 'Enter') {{ const first = list && list.querySelector('.metric-combo-opt'); if (first) {{ ev.preventDefault(); comboPick(null, which, first.dataset.key); }} }}
  else if (ev.key === 'Escape') {{ if (list) list.style.display = 'none'; comboRender(which); ev.target.blur(); }}
}}

function onChartPresetChange() {{
  const presetSel = document.getElementById('chart-preset');
  chartPreset = presetSel ? presetSel.value : chartPreset;
  const preset = CHART_PRESETS[chartPreset];
  if (preset) {{
    chartMode = preset.mode === 'team' ? 'team' : 'individual';
    chartXMetric = preset.x;
    chartYMetric = preset.y;
  }}
  document.getElementById('chart-mode-individual').classList.toggle('active', chartMode === 'individual');
  document.getElementById('chart-mode-team').classList.toggle('active', chartMode === 'team');
  populateChartMetricSelects();
  renderCharts();
}}

function onChartControlsChange() {{
  const scopeSel = document.getElementById('chart-stats-scope');
  const filterConfSel = document.getElementById('chart-filter-conf');
  const filterTeamSel = document.getElementById('chart-filter-team');
  const confSel = document.getElementById('chart-focus-conf');
  const teamSel = document.getElementById('chart-focus-team');
  const xSel = document.getElementById('chart-x-metric');
  const ySel = document.getElementById('chart-y-metric');
  chartStatsScope = scopeSel ? scopeSel.value : chartStatsScope;
  const regionSel = document.getElementById('chart-region');
  chartRegion = regionSel ? regionSel.value : chartRegion;
  chartFilterConference = filterConfSel ? filterConfSel.value : 'All';
  chartFilterTeam = filterTeamSel ? filterTeamSel.value : 'All';
  chartFocusConference = confSel ? confSel.value : 'All';
  chartFocusTeam = teamSel ? teamSel.value : 'All';
  const newX = xSel ? xSel.value : chartXMetric;
  const newY = ySel ? ySel.value : chartYMetric;
  // Manually changing a metric clears the suggestion so its qualification
  // minimums (e.g. 3PA per game) no longer apply to the new metrics.
  if (newX !== chartXMetric || newY !== chartYMetric) chartPreset = '';
  chartXMetric = newX;
  chartYMetric = newY;
  populateChartMetricSelects();
  renderCharts();
}}

function flipChartAxes() {{
  const oldX = chartXMetric;
  chartXMetric = chartYMetric;
  chartYMetric = oldX;
  chartAnimateNext = true;
  populateChartMetricSelects();
  renderCharts();
}}

function randomizeChartMetrics() {{
  const order = activeChartMetricOrder();
  chartXMetric = order[Math.floor(Math.random() * order.length)];
  do {{
    chartYMetric = order[Math.floor(Math.random() * order.length)];
  }} while (chartYMetric === chartXMetric && order.length > 1);
  populateChartMetricSelects();
  renderCharts();
}}

function syncChartControls() {{
  populateChartMetricSelects();
  const scopeSel = document.getElementById('chart-stats-scope');
  const filterConfSel = document.getElementById('chart-filter-conf');
  const filterTeamSel = document.getElementById('chart-filter-team');
  const confSel = document.getElementById('chart-focus-conf');
  const teamSel = document.getElementById('chart-focus-team');
  if (scopeSel) scopeSel.value = chartStatsScope;
  if (!filterConfSel || !filterTeamSel || !confSel || !teamSel) return;
  const topRows = chartMode === 'team' ? chartsTopFilteredTeams() : chartsTopFilteredPlayers();
  const topConfs = [...new Set(topRows.map(p => p.conference).filter(Boolean))].sort();
  if (chartFilterConference !== 'All' && !topConfs.includes(chartFilterConference)) chartFilterConference = 'All';
  const filterTeams = [...new Set(topRows.filter(p => chartFilterConference === 'All' || p.conference === chartFilterConference).map(p => chartMode === 'team' ? p.team : p.school).filter(Boolean))].sort();
  if (chartFilterTeam !== 'All' && !filterTeams.includes(chartFilterTeam)) chartFilterTeam = 'All';
  const baseRows = chartMode === 'team' ? chartsBaseTeams() : chartsBasePlayers();
  const confs = [...new Set(baseRows.map(p => p.conference).filter(Boolean))].sort();
  if (chartFocusConference !== 'All' && !confs.includes(chartFocusConference)) chartFocusConference = 'All';
  const teams = [...new Set(baseRows.filter(p => chartFocusConference === 'All' || p.conference === chartFocusConference).map(p => chartMode === 'team' ? p.team : p.school).filter(Boolean))].sort();
  if (chartFocusTeam !== 'All' && !teams.includes(chartFocusTeam)) chartFocusTeam = 'All';
  const renderOptions = (select, values, selected) => {{
    const current = select.value;
    const html = '<option value="All">All</option>' + values.map(v => '<option value="' + v.replace(/"/g, '&quot;') + '">' + v + '</option>').join('');
    if (select.dataset.lastHtml !== html) {{
      select.innerHTML = html;
      select.dataset.lastHtml = html;
    }}
    select.value = selected;
    if (current !== selected) select.value = selected;
  }};
  renderOptions(filterConfSel, topConfs, chartFilterConference);
  renderOptions(filterTeamSel, filterTeams, chartFilterTeam);
  renderOptions(confSel, confs, chartFocusConference);
  renderOptions(teamSel, teams, chartFocusTeam);
}}

function chartFocusLabel() {{
  const parts = [];
  if (chartFocusConference !== 'All') parts.push('Focus: ' + chartFocusConference);
  if (chartFocusTeam !== 'All') parts.push('Focus: ' + chartFocusTeam);
  return parts.join(' · ');
}}

function chartFilterLabel() {{
  const parts = [];
  if (chartFilterConference !== 'All') parts.push(chartFilterConference);
  if (chartFilterTeam !== 'All') parts.push(chartFilterTeam);
  return parts.join(' · ');
}}

function chartIsFocused(row) {{
  if (chartFocusConference !== 'All' && row.conference !== chartFocusConference) return false;
  const teamName = chartMode === 'team' ? row.team : row.school;
  if (chartFocusTeam !== 'All' && teamName !== chartFocusTeam) return false;
  return true;
}}

function setChartBubblePosition(g, x, y, animate) {{
  const fromX = Number(g.dataset.x);
  const fromY = Number(g.dataset.y);
  if (g._chartAnim) cancelAnimationFrame(g._chartAnim);
  const target = 'translate(' + x.toFixed(2) + ',' + y.toFixed(2) + ')';
  if (!animate || !Number.isFinite(fromX) || !Number.isFinite(fromY)) {{
    g.setAttribute('transform', target);
    g.dataset.x = x;
    g.dataset.y = y;
    return;
  }}
  const start = performance.now();
  const duration = 900;
  const ease = t => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  const step = now => {{
    const t = Math.min(1, (now - start) / duration);
    const e = ease(t);
    const cx = fromX + (x - fromX) * e;
    const cy = fromY + (y - fromY) * e;
    g.setAttribute('transform', 'translate(' + cx.toFixed(2) + ',' + cy.toFixed(2) + ')');
    if (t < 1) {{
      g._chartAnim = requestAnimationFrame(step);
    }} else {{
      g.setAttribute('transform', target);
      g.dataset.x = x;
      g.dataset.y = y;
      g._chartAnim = null;
    }}
  }};
  g._chartAnim = requestAnimationFrame(step);
}}

function renderCharts() {{
  const svg = document.getElementById('charts-scatter');
  if (!svg) return;
  const tooltip = document.getElementById('chart-tooltip');
  syncChartControls();
  const points = chartsPointData();
  const hasFocus = chartFocusConference !== 'All' || chartFocusTeam !== 'All';
  const plotPoints = points;
  const highlighted = hasFocus ? plotPoints.filter(d => chartIsFocused(chartMode === 'team' ? d.team : d.player)).length : plotPoints.length;
  const note = document.getElementById('chart-note');
  const subtitleEl = document.getElementById('chart-subtitle');
  const metrics = activeChartMetrics();
  const metricOrder = activeChartMetricOrder();
  const xMetric = metrics[chartXMetric] || metrics[metricOrder[0]];
  const yMetric = metrics[chartYMetric] || metrics[metricOrder[1] || metricOrder[0]];
  const heading = document.querySelector('#charts-view .chart-heading');
  if (heading) heading.textContent = xMetric.label + ' vs ' + yMetric.label;
  if (subtitleEl) subtitleEl.textContent = chartSeasonLabel() + ' · ' + (chartScopeLabel()) + (chartMode === 'team' ? ' Teams' : ' Individual Players');
  if (note) {{
    const filterLabel = [getFilterLabel(), chartFilterLabel()].filter(Boolean).join(' · ');
    const focusLabel = chartFocusLabel();
    const qualifier = chartQualifierLabel();
    const unitLabel = chartMode === 'team' ? 'teams' : 'players';
    const scopeLabel = chartScopeLabel();
    note.textContent = scopeLabel + ' · ' + (filterLabel ? 'Filter: ' + filterLabel + ' · ' : '') + (focusLabel ? focusLabel + ' · ' : '') + highlighted + ' highlighted ' + unitLabel + ' · ' + plotPoints.length + ' plotted ' + unitLabel + ' · ' + qualifier;
  }}
  let staticLayer = document.getElementById('charts-static-layer');
  let bubbleLayer = document.getElementById('charts-bubble-layer');
  if (!staticLayer || !bubbleLayer) {{
    svg.innerHTML = '';
    staticLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    staticLayer.setAttribute('id', 'charts-static-layer');
    bubbleLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    bubbleLayer.setAttribute('id', 'charts-bubble-layer');
    svg.appendChild(staticLayer);
    svg.appendChild(bubbleLayer);
  }}
  staticLayer.innerHTML = '';
  const W = 980, H = 620;
  const m = {{ left: 86, right: 34, top: 42, bottom: 76 }};
  const pw = W - m.left - m.right;
  const ph = H - m.top - m.bottom;
  if (plotPoints.length === 0) {{
    bubbleLayer.innerHTML = '';
    const empty = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    empty.setAttribute('x', W / 2);
    empty.setAttribute('y', H / 2);
    empty.setAttribute('text-anchor', 'middle');
    empty.setAttribute('fill', '#666');
    empty.setAttribute('font-size', '18');
    empty.textContent = 'No ' + (chartMode === 'team' ? 'teams' : 'players') + ' match the current filters';
    staticLayer.appendChild(empty);
    return;
  }}
  const xs = plotPoints.map(d => d.x);
  const ys = plotPoints.map(d => d.y);
  const roundDown = (v, step) => Math.floor(v / step) * step;
  const roundUp = (v, step) => Math.ceil(v / step) * step;
  const xStep = xMetric.tickStep || 5;
  const yStep = yMetric.tickStep || 5;
  let xMin = roundDown(Math.min(...xs) - xStep * 0.5, xStep);
  let xMax = roundUp(Math.max(...xs) + xStep * 0.5, xStep);
  let yMin = roundDown(Math.min(...ys) - yStep * 0.5, yStep);
  let yMax = roundUp(Math.max(...ys) + yStep * 0.5, yStep);
  if (Math.min(...xs) >= 0) xMin = Math.max(0, xMin);
  if (Math.min(...ys) >= 0) yMin = Math.max(0, yMin);
  if (xMax - xMin < 10) xMax = xMin + 10;
  if (yMax - yMin < 10) yMax = yMin + 10;
  const xLowerBetter = !!xMetric.lowerBetter;
  const yLowerBetter = !!yMetric.lowerBetter;
  const sx = v => xLowerBetter
    ? m.left + ((xMax - v) / (xMax - xMin)) * pw
    : m.left + ((v - xMin) / (xMax - xMin)) * pw;
  const sy = v => yLowerBetter
    ? m.top + ((v - yMin) / (yMax - yMin)) * ph
    : m.top + ph - ((v - yMin) / (yMax - yMin)) * ph;
  const addLine = (x1, y1, x2, y2, cls) => {{
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', x1); line.setAttribute('y1', y1);
    line.setAttribute('x2', x2); line.setAttribute('y2', y2);
    line.setAttribute('class', cls);
    staticLayer.appendChild(line);
  }};
  const addText = (x, y, text, cls, attrs={{}}) => {{
    const el = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    el.setAttribute('x', x); el.setAttribute('y', y);
    el.setAttribute('class', cls);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    el.textContent = text;
    staticLayer.appendChild(el);
    return el;
  }};
  for (let x = xMin; x <= xMax + 0.001; x += xStep) {{
    const px = sx(x);
    addLine(px, m.top, px, m.top + ph, 'chart-grid');
    addText(px, m.top + ph + 24, chartFmt(chartXMetric, x, Math.abs(xStep) < 5 ? 1 : 0), 'chart-tick', {{ 'text-anchor': 'middle' }});
  }}
  for (let y = yMin; y <= yMax + 0.001; y += yStep) {{
    const py = sy(y);
    addLine(m.left, py, m.left + pw, py, 'chart-grid');
    addText(m.left - 12, py + 4, chartFmt(chartYMetric, y, Math.abs(yStep) < 5 ? 1 : 0), 'chart-tick', {{ 'text-anchor': 'end' }});
  }}
  addLine(m.left, m.top + ph, m.left + pw, m.top + ph, 'chart-axis');
  addLine(m.left, m.top, m.left, m.top + ph, 'chart-axis');
  addText(m.left + pw / 2, H - 22, xMetric.label, 'chart-axis-label', {{ 'text-anchor': 'middle' }});
  addText(24, m.top + ph / 2, yMetric.label, 'chart-axis-label', {{ 'text-anchor': 'middle', transform: 'rotate(-90 24 ' + (m.top + ph / 2) + ')' }});
  const sorted = [...plotPoints].sort((a, b) => {{
    const ar = chartMode === 'team' ? a.team : a.player;
    const br = chartMode === 'team' ? b.team : b.player;
    return chartIsFocused(ar) === chartIsFocused(br) ? 0 : chartIsFocused(ar) ? 1 : -1;
  }});
  const existing = new Map([...bubbleLayer.querySelectorAll('.chart-bubble')].map(g => [g.dataset.key, g]));
  const seen = new Set();
  const animateBubbles = chartAnimateNext;
  sorted.forEach(d => {{
    const row = chartMode === 'team' ? d.team : d.player;
    const teamName = chartMode === 'team' ? row.team : row.school;
    const bubbleKey = chartMode + '|' + String(chartMode === 'team' ? row.team : row.name || '') + '|' + String(teamName || '');
    seen.add(bubbleKey);
    const selected = !hasFocus || chartIsFocused(row);
    const color = selected ? (TEAM_PRIMARY_COLORS[teamName] || '#2d5aa7') : '#d1d1d1';
    // Secondary color outlines the bubble and colors the initials/number.
    // A white secondary keeps white text but gets a black outline so the
    // bubble edge stays visible on the light chart background.
    const secondary = TEAM_SECONDARY_COLORS[teamName] || '';
    const secondaryIsWhite = /^#?FFFFFF$/i.test(secondary);
    const stroke = selected ? (secondary ? (secondaryIsWhite ? '#000000' : secondary) : '#333333') : '#777777';
    const textColor = selected ? (secondary || chartTextColor(color)) : 'transparent';
    let g = existing.get(bubbleKey);
    const isNew = !g;
    if (!g) g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('class', 'chart-bubble');
    g.dataset.key = bubbleKey;
    g.innerHTML = '';
    setChartBubblePosition(g, sx(d.x), sy(d.y), animateBubbles && !isNew);
    if (chartMode === 'team') {{
      const r = selected ? 21 : 15;
      const logo = TEAM_LOGOS[teamName];
      if (logo) {{
        const img = document.createElementNS('http://www.w3.org/2000/svg', 'image');
        img.setAttribute('href', logo);
        img.setAttribute('x', -r);
        img.setAttribute('y', -r);
        img.setAttribute('width', r * 2);
        img.setAttribute('height', r * 2);
        img.setAttribute('preserveAspectRatio', 'xMidYMid meet');
        img.setAttribute('opacity', selected ? '1' : '0.25');
        g.appendChild(img);
      }} else {{
        const fallback = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        fallback.setAttribute('y', '0');
        fallback.setAttribute('fill', selected ? '#111' : '#777');
        fallback.textContent = chartInitials(teamName);
        g.appendChild(fallback);
      }}
    }} else {{
      const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('r', selected ? 16 : 12);
      c.setAttribute('fill', color);
      c.setAttribute('stroke', stroke);
      c.setAttribute('opacity', selected ? '0.95' : '0.78');
      g.appendChild(c);
      if (selected) {{
        const p = row;
        const initials = chartInitials(p.name);
        const jersey = p.jersey || p.number || '';
        const t1 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        t1.setAttribute('y', jersey ? '-4' : '0');
        t1.setAttribute('fill', textColor);
        t1.textContent = initials;
        g.appendChild(t1);
        if (jersey) {{
          const t2 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
          t2.setAttribute('y', '8');
          t2.setAttribute('fill', textColor);
          t2.setAttribute('font-size', '9');
          t2.textContent = jersey;
          g.appendChild(t2);
        }}
      }}
    }}
    const showTip = evt => {{
      if (!tooltip) return;
      if (chartMode === 'team') {{
        tooltip.innerHTML =
          '<strong>' + row.team + '</strong>' +
          '<div>' + (row.gp || 0) + ' Games Played · ' + (row.record || '') + '</div>' +
          '<div>' + xMetric.label + ': ' + chartFmt(chartXMetric, d.x, 1) + '</div>' +
          '<div>' + yMetric.label + ': ' + chartFmt(chartYMetric, d.y, 1) + '</div>' +
          '<div>Net Rating: ' + chartFmt('net_rtg', Number(row.net_rtg), 1) + '</div>';
      }} else {{
        const p = row;
        const mins = Math.round(Number(p.mpg || 0) * Number(p.gp || 0));
        // Show a made-attempts line only for the shooting metric(s) actually
        // plotted — not a hardcoded 3PA on charts that don't use it.
        const ATT_CTX = {{
          tpp: ['3PM-3PA','tpm','tpa'], tpa_rate: ['3PM-3PA','tpm','tpa'],
          twop: ['2PM-2PA','twom','twoa'],
          ftp: ['FTM-FTA','ftm','fta'], ft_rate: ['FTM-FTA','ftm','fta'],
          efg_pct: ['FGM-FGA','fgm','fga'], ts_pct: ['FGM-FGA','fgm','fga'],
        }};
        let attHtml = '', seenAtt = new Set();
        [chartXMetric, chartYMetric].forEach(k => {{
          const c = ATT_CTX[k];
          if (c && !seenAtt.has(c[0])) {{ seenAtt.add(c[0]); attHtml += '<div>' + c[0] + ': ' + (p[c[1]] || 0) + '-' + (p[c[2]] || 0) + '</div>'; }}
        }});
        tooltip.innerHTML =
          '<strong>' + p.name + ' || ' + p.school + '</strong>' +
          '<div>' + (p.gp || 0) + ' Games Played, ' + mins + ' Minutes Played</div>' +
          '<div>' + xMetric.label + ': ' + chartFmt(chartXMetric, d.x, 1) + '</div>' +
          '<div>' + yMetric.label + ': ' + chartFmt(chartYMetric, d.y, 1) + '</div>' +
          attHtml;
      }}
      tooltip.style.display = 'block';
      tooltip.style.left = Math.min(window.innerWidth - 300, evt.clientX + 14) + 'px';
      tooltip.style.top = Math.max(8, evt.clientY - 10) + 'px';
    }};
    g.onmouseenter = showTip;
    g.onmousemove = showTip;
    g.onmouseleave = () => {{ if (tooltip) tooltip.style.display = 'none'; }};
    bubbleLayer.appendChild(g);
  }});
  existing.forEach((g, key) => {{
    if (!seen.has(key)) g.remove();
  }});
  chartAnimateNext = false;
}}

function applyFilters() {{
  refreshIndividual();
  renderTeams(getFilteredTeams());
  renderDefense(getFilteredTeams());
  renderCharts();
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
    activeData = checked ? CONF_DATA_2021 : DATA_2021;
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
  ensureSeason(season, () => __switchSeasonNow(season));
}}

function __switchSeasonNow(season) {{
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
              || (TEAM_DATA_2024 || []).find(d => d.team === teamName);
    if (newT) {{
      currentTeam = newT;
      document.getElementById('team-detail-content').innerHTML = buildTeamDetail(newT);
    }}
  }}
  // Team Stats / Minutes Matrix views stay open across a season switch:
  // re-render them with the new season's data (or bounce back to the team
  // page when the team/season combo has no data).
  const tsDiv = document.getElementById('teamstats-view');
  if (tsDiv && tsDiv.style.display !== 'none' && teamStatsReturnTeam) {{
    const tName = teamStatsReturnTeam;
    ensureRosters(activeSeason, () => {{
      if ((TEAM_ROSTERS[activeSeason] || {{}})[tName]) renderTeamStats(tName);
      else closeTeamStats();
    }});
  }}
  const ppDiv = document.getElementById('player-view');
  if (ppDiv && ppDiv.style.display !== 'none') {{
    closePlayerProfile();
  }}
  const mmDiv = document.getElementById('minmatrix-view');
  if (mmDiv && mmDiv.style.display !== 'none' && minMatrixReturnTeam) {{
    const mName = minMatrixReturnTeam;
    if (MM_SEASONS.has(activeSeason)) {{
      ensureBoxes(activeSeason, () => renderMinutesMatrix(mName));
    }} else {{
      closeMinutesMatrix();
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
  if (slActiveTab === 'conf') slSwitchTab('conf', 'Conferences');  // re-render + refresh season title
  // Refresh fanmatch if it's the active view (and storylines hasn't been init'd to cover it)
  const fmDiv2 = document.getElementById('fanmatch-view');
  if (fmDiv2 && fmDiv2.style.display !== 'none') slInitFanmatch();
  // Update individual view subtitle if active
  const indDiv2 = document.getElementById('individual-view');
  if (indDiv2 && indDiv2.style.display !== 'none') {{
    const yr2 = season === '1718' ? '2017-18' : season === '1819' ? '2018-19' : season === '1920' ? '2019-20' : season === '2122' ? '2021-22' : season === '2223' ? '2022-23' : season === '2324' ? '2023-24' : season === '2425' ? '2024-25' : '2025-26';
    document.getElementById('page-title').textContent = 'Individual Statistics Leaderboard';
    document.getElementById('page-subtitle').textContent = yr2 + ' Season \u2014 Per-Game Averages';
  }}
  const chartsDiv2 = document.getElementById('charts-view');
  if (chartsDiv2 && chartsDiv2.style.display !== 'none') {{
    document.getElementById('page-title').textContent = 'Charts';
    document.getElementById('page-subtitle').textContent = chartSeasonLabel() + ' Season \u2014 ' + (chartScopeLabel()) + ' Scatter';
    document.getElementById('page-info').textContent = 'Use Stats Scope for Full Season or Conference Only · Top filters remove bubbles; chart focus greys context · Generated ' + TIMESTAMP;
    renderCharts();
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
    info.textContent = cnt + ' qualified players \u00b7 30% minutes played minimum \u00b7 Click any column header to sort \u00b7 Generated ' + TIMESTAMP;
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
      <td>${{playerLink(p.name, p.school)}}${{p.pos ? `<span style="font-size:0.65rem;color:#888;margin-left:5px;vertical-align:middle">${{p.pos}}</span>` : ''}}</td>
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
  {{key:'porp',      label:'PRPG!',  desc:'PORPAGATU! — points over replacement per game at that usage (Torvik 2019 formula, SOS-adjusted)', asc:false}},
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
  {{key:'bpm2',      label:'OBPM',   desc:'In-house strict box-score BPM 2.0',                      asc:false}},
  {{key:'per',       label:'PER',    desc:'Player Efficiency Rating (Hollinger; league average = 15)', asc:false}},
  {{key:'ws',        label:'OWS',    desc:'Win Shares — OWS, DWS, WS and WS/40 (Dean Oliver box-score method, normalized so league total = total wins)', asc:false}},
];
let bpm2SortCol = 'bpm';
let bpm2SortDir = 'desc';
let wsSortCol = 'ws';
let wsSortDir = 'desc';
const POSS_BUCKETS = [
  {{min: 28, max: null, label: '28%+ %Poss'}},
  {{min: 24, max: 28,   label: '24\u201328% %Poss'}},
  {{min: 20, max: 24,   label: '20\u201324% %Poss'}},
  {{min: 16, max: 20,   label: '16\u201320% %Poss'}},
  {{min: 12, max: 16,   label: '12\u201316% %Poss'}},
  {{min:  0, max: 12,   label: 'Sub-12% %Poss'}},
];
const MIN_PCT_QUAL = 30;
const ADV_CAT_MIN_PCT = {{
  efg_pct: 50,
  ts_pct: 50,
  ft_rate: 50,
}};
const ADV_CAT_ATTEMPT_MIN = {{
  twop: 'twoa',
  tpp: 'tpa',
  ftp: 'fta',
}};
const ADV_RATE_GP_MIN = 20;
const ADV_RATE_ATTEMPTS_PER_GAME_MIN = 2.5;
const ADV_RELAXED_CAT_KEYS = new Set(['efg_pct', 'ts_pct', 'ft_rate', 'twop', 'tpp', 'ftp']);
const ADV_MAKE_ATTEMPT_CAT_KEYS = new Set(['efg_pct', 'ts_pct', 'twop', 'tpp', 'ftp']);
const ADV_RELAXED_SCHOOL_CAT_CACHE = {{}};

function attemptsPerGame(p, key) {{
  return p.gp ? ((p[key] || 0) / p.gp) : 0;
}}

function advCatValue(p, catKey) {{
  if (p[catKey] != null) return p[catKey];
  const fga = p.fga || 0;
  if (catKey === 'efg_pct' && fga > 0) {{
    return ((p.fgm || 0) + 0.5 * (p.tpm || 0)) / fga * 100;
  }}
  if (catKey === 'ts_pct') {{
    const denom = 2 * (fga + 0.44 * (p.fta || 0));
    return denom > 0 ? (p.pts || 0) / denom * 100 : null;
  }}
  if (catKey === 'ft_rate' && fga > 0) {{
    return (p.fta || 0) / fga * 100;
  }}
  return null;
}}

function advMakeAttemptText(p, catKey) {{
  if (catKey === 'efg_pct') return `${{p.fgm || 0}}-${{p.fga || 0}}`;
  if (catKey === 'ts_pct') return `${{(p.fgm || 0) + (p.ftm || 0)}}-${{(p.fga || 0) + (p.fta || 0)}}`;
  if (catKey === 'twop') return `${{p.twom || 0}}-${{p.twoa || 0}}`;
  if (catKey === 'tpp') return `${{p.tpm || 0}}-${{p.tpa || 0}}`;
  if (catKey === 'ftp') return `${{p.ftm || 0}}-${{p.fta || 0}}`;
  return '';
}}

function advCatStandardQualifies(p, catKey) {{
  const minPct = ADV_CAT_MIN_PCT[catKey] || MIN_PCT_QUAL;
  if ((p.min_pct || 0) < minPct) return false;
  const attemptKey = ADV_CAT_ATTEMPT_MIN[catKey];
  if (attemptKey && (attemptsPerGame(p, attemptKey) < ADV_RATE_ATTEMPTS_PER_GAME_MIN || (p.gp || 0) < ADV_RATE_GP_MIN)) return false;
  return true;
}}

function advCatRelaxedQualifies(p, catKey) {{
  if (catKey === 'efg_pct') {{
    return (p.gp || 0) >= ADV_RATE_GP_MIN && attemptsPerGame(p, 'fga') >= EFG_FGA_PG_MIN;
  }}
  if (catKey === 'ts_pct') {{
    return (p.gp || 0) >= ADV_RATE_GP_MIN && attemptsPerGame(p, 'fga') + attemptsPerGame(p, 'fta') >= TS_ATT_PG_MIN;
  }}
  if (catKey === 'ft_rate') {{
    return (p.gp || 0) >= ADV_RATE_GP_MIN;
  }}
  const attemptKey = ADV_CAT_ATTEMPT_MIN[catKey];
  if (attemptKey) {{
    return (p.gp || 0) >= ADV_RATE_GP_MIN && attemptsPerGame(p, attemptKey) >= ADV_RATE_ATTEMPTS_PER_GAME_MIN;
  }}
  return false;
}}

function advSchoolNeedsRelaxedCat(school, catKey) {{
  if (!ADV_RELAXED_CAT_KEYS.has(catKey)) return false;
  const cacheKey = school + '|' + catKey;
  if (cacheKey in ADV_RELAXED_SCHOOL_CAT_CACHE) return ADV_RELAXED_SCHOOL_CAT_CACHE[cacheKey];
  const schoolPlayers = DATA.filter(p => p.school === school);
  const northOrSouth = schoolPlayers.some(p => p.region === 'North' || p.region === 'South');
  if (!northOrSouth) {{
    ADV_RELAXED_SCHOOL_CAT_CACHE[cacheKey] = false;
    return false;
  }}
  // False-minutes teams always use the relaxed (attempts-based) path: their
  // min_pct values come from unreliable minutes, even though eFG%/TS%/FT rate
  // themselves are now computed from box totals.
  if (schoolPlayers.length && schoolPlayers.every(p => p.fm)) {{
    ADV_RELAXED_SCHOOL_CAT_CACHE[cacheKey] = true;
    return true;
  }}
  const hasStandardEligiblePlayer = schoolPlayers.some(p => advCatStandardQualifies(p, catKey) && advCatValue(p, catKey) != null);
  ADV_RELAXED_SCHOOL_CAT_CACHE[cacheKey] = !hasStandardEligiblePlayer;
  return !hasStandardEligiblePlayer;
}}

function advCatQualifies(p, catKey) {{
  if (advSchoolNeedsRelaxedCat(p.school, catKey)) {{
    return advCatRelaxedQualifies(p, catKey);
  }}
  return advCatStandardQualifies(p, catKey);
}}

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

function sortBpm2(col) {{
  if (bpm2SortCol === col) {{
    bpm2SortDir = bpm2SortDir === 'desc' ? 'asc' : 'desc';
  }} else {{
    bpm2SortCol = col;
    bpm2SortDir = col === 'school' || col === 'name' ? 'asc' : 'desc';
  }}
  if (indCat === 'bpm2') renderAdv(getFilteredPlayers(), 'bpm2');
}}

function sortWs(col) {{
  if (wsSortCol === col) {{
    wsSortDir = wsSortDir === 'desc' ? 'asc' : 'desc';
  }} else {{
    wsSortCol = col;
    wsSortDir = 'desc';
  }}
  if (indCat === 'ws') renderAdv(getFilteredPlayers(), 'ws');
}}

function renderWs(data) {{
  const tb = document.getElementById('adv-tbody');
  if (!tb) return;
  tb.innerHTML = '';
  document.querySelectorAll('.ws-th').forEach(th => th.style.display = '');
  const volumeTh = document.getElementById('adv-volume-th');
  if (volumeTh) volumeTh.style.display = 'none';
  const statTh = document.getElementById('adv-stat-th');
  if (statTh) {{
    statTh.textContent = 'OWS';
    statTh.title = 'Offensive Win Shares';
    statTh.style.cursor = 'pointer';
    statTh.onclick = () => sortWs('ows');
  }}
  const pool = data
    .filter(p => p.ws != null && p.ows != null && p.dws != null)
    .sort((a, b) => {{
      const va = Number(a[wsSortCol] ?? -Infinity);
      const vb = Number(b[wsSortCol] ?? -Infinity);
      return wsSortDir === 'asc' ? va - vb : vb - va;
    }});
  pool.forEach((p, i) => {{
    const tr = tb.insertRow();
    const schoolDisplay = p.school === 'La Pierce' ? 'LA Pierce' : p.school;
    tr.innerHTML = `<td>${{i+1}}</td><td>${{playerLink(p.name, p.school)}}${{p.pos ? `<span style="font-size:0.65rem;color:#888;margin-left:5px;vertical-align:middle">${{p.pos}}</span>` : ''}}</td><td>${{teamPageLink(p.school,'color:inherit;text-decoration:none',schoolDisplay)}}</td><td>${{p.gp}}</td><td>${{Number(p.ows).toFixed(2)}}</td><td>${{Number(p.dws).toFixed(2)}}</td><td>${{Number(p.ws).toFixed(2)}}</td><td>${{p.ws40 != null ? Number(p.ws40).toFixed(3) : '—'}}</td>`;
    if (p.school === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
  }});
}}

function renderBpm2(data) {{
  const tb = document.getElementById('adv-tbody');
  if (!tb) return;
  tb.innerHTML = '';
  document.querySelectorAll('.ws-th').forEach(th => th.style.display = 'none');
  document.querySelectorAll('.bpm2-th').forEach(th => th.style.display = '');
  const volumeTh = document.getElementById('adv-volume-th');
  if (volumeTh) volumeTh.style.display = 'none';
  const statTh = document.getElementById('adv-stat-th');
  if (statTh) {{
    statTh.textContent = 'OBPM';
    statTh.title = 'In-house strict offensive box plus-minus';
    statTh.style.cursor = 'pointer';
    statTh.onclick = () => sortBpm2('obpm');
  }}
  const pool = data
    .filter(p => p.bpm != null && p.obpm != null && p.dbpm != null && p.vorp != null)
    .sort((a, b) => {{
      let va = a[bpm2SortCol], vb = b[bpm2SortCol];
      if (bpm2SortCol === 'name' || bpm2SortCol === 'school') {{
        va = (va || '').toLowerCase();
        vb = (vb || '').toLowerCase();
        if (va < vb) return bpm2SortDir === 'asc' ? -1 : 1;
        if (va > vb) return bpm2SortDir === 'asc' ? 1 : -1;
        return 0;
      }}
      va = Number(va ?? -Infinity);
      vb = Number(vb ?? -Infinity);
      return bpm2SortDir === 'asc' ? va - vb : vb - va;
    }});
  pool.forEach((p, i) => {{
    const tr = tb.insertRow();
    const schoolDisplay = p.school === 'La Pierce' ? 'LA Pierce' : p.school;
    tr.innerHTML = `<td>${{i+1}}</td><td>${{playerLink(p.name, p.school)}}${{p.pos ? `<span style="font-size:0.65rem;color:#888;margin-left:5px;vertical-align:middle">${{p.pos}}</span>` : ''}}</td><td>${{teamPageLink(p.school,'color:inherit;text-decoration:none',schoolDisplay)}}</td><td>${{p.bpm_gp || p.gp}}</td><td>${{Number(p.obpm).toFixed(2)}}</td><td>${{Number(p.dbpm).toFixed(2)}}</td><td>${{Number(p.bpm).toFixed(2)}}</td><td>${{Number(p.vorp).toFixed(3)}}</td>`;
    if (p.school === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
  }});
}}

function renderAdv(data, catKey) {{
  const cat = ADV_CATS.find(c => c.key === catKey);
  if (!cat) return;
  const tb = document.getElementById('adv-tbody');
  if (!tb) return;
  tb.innerHTML = '';
  document.querySelectorAll('.bpm2-th').forEach(th => th.style.display = 'none');
  document.querySelectorAll('.ws-th').forEach(th => th.style.display = 'none');
  const statTh = document.getElementById('adv-stat-th');
  const volumeTh = document.getElementById('adv-volume-th');
  const showMakeAttempt = ADV_MAKE_ATTEMPT_CAT_KEYS.has(catKey);
  if (volumeTh) volumeTh.style.display = showMakeAttempt ? '' : 'none';
  if (statTh) {{
    statTh.style.cursor = '';
    statTh.onclick = null;
  }}
  if (catKey === 'bpm2') {{
    renderBpm2(data);
    return;
  }}
  if (catKey === 'ws') {{
    renderWs(data);
    return;
  }}
  const qualified = data.filter(p => advCatQualifies(p, catKey));
  if (cat.poss_buckets) {{
    POSS_BUCKETS.forEach(bucket => {{
      const pool = qualified
        .filter(p => advCatValue(p, catKey) != null && p.usage_pct != null && p.usage_pct <= 40 && p.usage_pct >= bucket.min && (bucket.max == null || p.usage_pct < bucket.max))
        .sort((a, b) => cat.asc ? advCatValue(a, catKey) - advCatValue(b, catKey) : advCatValue(b, catKey) - advCatValue(a, catKey))
        .slice(0, 100);
      if (pool.length === 0) return;
      const htr = tb.insertRow();
      const htd = htr.insertCell();
      htd.colSpan = showMakeAttempt ? 6 : 5;
      htd.className = 'adv-section-hdr';
      htd.textContent = bucket.label;
      pool.forEach((p, i) => {{
        const tr = tb.insertRow();
        const schoolDisplay = p.school === 'La Pierce' ? 'LA Pierce' : p.school;
        const val = advCatValue(p, catKey);
        const statVal = typeof val === 'number' ? val.toFixed(1) : '\u2014';
        const poss = p.usage_pct != null ? ` (${{p.usage_pct.toFixed(1)}})` : '';
        const maCell = showMakeAttempt ? `<td>${{advMakeAttemptText(p, catKey)}}</td>` : '';
        tr.innerHTML = `<td>${{i+1}}</td><td>${{playerLink(p.name, p.school)}}${{p.pos ? `<span style="font-size:0.65rem;color:#888;margin-left:5px;vertical-align:middle">${{p.pos}}</span>` : ''}}</td><td>${{teamPageLink(p.school,'color:inherit;text-decoration:none',schoolDisplay)}}</td><td>${{p.gp}}</td>${{maCell}}<td>${{statVal}}${{poss}}</td>`;
        if (p.school === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
      }});
    }});
  }} else {{
    const pool = qualified
      .filter(p => advCatValue(p, catKey) != null && (catKey !== 'usage_pct' || advCatValue(p, catKey) <= 40))
      .sort((a, b) => cat.asc ? advCatValue(a, catKey) - advCatValue(b, catKey) : advCatValue(b, catKey) - advCatValue(a, catKey))
      .slice(0, 100);
    pool.forEach((p, i) => {{
      const tr = tb.insertRow();
      const schoolDisplay = p.school === 'La Pierce' ? 'LA Pierce' : p.school;
      const val = advCatValue(p, catKey);
      const fmt = typeof val === 'number' ? val.toFixed(1) : '\u2014';
      const maCell = showMakeAttempt ? `<td>${{advMakeAttemptText(p, catKey)}}</td>` : '';
      tr.innerHTML = `<td>${{i+1}}</td><td>${{playerLink(p.name, p.school)}}${{p.pos ? `<span style="font-size:0.65rem;color:#888;margin-left:5px;vertical-align:middle">${{p.pos}}</span>` : ''}}</td><td>${{teamPageLink(p.school,'color:inherit;text-decoration:none',schoolDisplay)}}</td><td>${{p.gp}}</td>${{maCell}}<td>${{fmt}}</td>`;
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

// ── Keep your spot across a page refresh (view + scroll position) ──
// All guarded: any failure falls back to the normal default view below.
let __curView = 'team';
function __lbSnapshot() {{
  try {{
    const vis = (id) => {{ const e = document.getElementById(id); return e && e.style.display !== 'none'; }};
    let st;
    if (vis('lineups-view') && typeof lineupsReturnTeam !== 'undefined' && lineupsReturnTeam) st = {{ k: 'lineups', t: lineupsReturnTeam }};
    else if (vis('team-detail-view') && typeof currentTeam !== 'undefined' && currentTeam) st = {{ k: 'team', t: currentTeam.team }};
    else st = {{ k: 'view', v: __curView || 'team' }};
    st.y = window.scrollY || window.pageYOffset || 0;
    sessionStorage.setItem('lbNav', JSON.stringify(st));
  }} catch (e) {{}}
}}
let __lbThr = null;
function __lbThrottle() {{ if (__lbThr) return; __lbThr = setTimeout(() => {{ __lbThr = null; __lbSnapshot(); }}, 250); }}
function __lbRestore() {{
  try {{
    const raw = sessionStorage.getItem('lbNav'); if (!raw) return false;
    const st = JSON.parse(raw);
    if (st.k === 'lineups' && st.t && typeof showLineups === 'function') {{
      if (typeof showTeamDetail === 'function') showTeamDetail(st.t);  // hides main views first
      showLineups(st.t);
    }}
    else if (st.k === 'team' && st.t && typeof showTeamDetail === 'function') showTeamDetail(st.t);
    else if (st.k === 'view' && st.v && typeof showView === 'function') showView(st.v);
    else return false;
    const y = st.y || 0;  // re-apply scroll a few times to win over views' own scrollTo(0,0)
    if (y > 0) {{ let n = 0; const iv = setInterval(() => {{ window.scrollTo(0, y); if (++n >= 12) clearInterval(iv); }}, 50); }}
    return true;
  }} catch (e) {{ return false; }}
}}
window.addEventListener('scroll', __lbThrottle, {{ passive: true }});
window.addEventListener('beforeunload', __lbSnapshot);

// Initial render. If a saved spot exists, DON'T show the default view yet — wait
// for DOMContentLoaded and restore then (the deep-view render fns reference consts
// declared later in this script, so restoring at parse time hits the temporal dead
// zone). No saved spot → show the default immediately. Either way the main view
// never flashes before the restored deep view.
render(getFilteredPlayers());
if (sessionStorage.getItem('lbNav')) {{
  const __doRestore = () => {{
    document.documentElement.classList.remove('lb-restoring');  // re-enable normal display, then restore
    if (!__lbRestore()) showView('team');
  }};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', __doRestore);
  else __doRestore();
}} else {{
  document.documentElement.classList.remove('lb-restoring');
  showView('team');
}}

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
    applyTeamStatsRowColor(tr, t.team);
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
    applyTeamStatsRowColor(tr, t.team);
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
    applyTeamStatsRowColor(tr, t.team);
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
    applyTeamStatsRowColor(tr, t.team);
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
    // Fallback to this season's full-team data if conference-only mode filtered it out.
    const tf = activeFullTeamData().find(d => d.team === teamName);
    if (!tf) return;
    showTeamDetail_inner(tf, teamName);
    return;
  }}
  showTeamDetail_inner(t, teamName);
}}

function showTeamDetail_inner(t, teamName) {{
  // Remember current view to return to
  if (document.getElementById('individual-view').style.display !== 'none') prevView = 'individual';
  else if (
    document.getElementById('team-view').style.display !== 'none' ||
    document.getElementById('team-defense-view').style.display !== 'none' ||
    document.getElementById('team-adv-offense-view').style.display !== 'none' ||
    document.getElementById('team-adv-defense-view').style.display !== 'none'
  ) prevView = 'team';
  else if (document.getElementById('universe-view').style.display !== 'none') prevView = 'universe';
  else if (document.getElementById('storylines-view').style.display !== 'none') prevView = 'storylines';
  else if (document.getElementById('fanmatch-view').style.display !== 'none') prevView = 'fanmatch';

  // Hide everything
  document.getElementById('individual-view').style.display = 'none';
  document.getElementById('team-view').style.display = 'none';
  document.getElementById('team-defense-view').style.display = 'none';
  document.getElementById('team-adv-offense-view').style.display = 'none';
  document.getElementById('team-adv-defense-view').style.display = 'none';
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

function teamLogoHtml(teamName, className = 'td-logo') {{
  const src = TEAM_LOGOS[teamName];
  if (!src) return '';
  return `<div class="td-logo-wrap"><img class="${{className}}" src="${{src}}" alt="${{teamName}} logo"></div>`;
}}

function teamStatsRowColor(teamName) {{
  if (CHAMPIONS_BY_SEASON[activeSeason] === teamName) return '#FFCCCC';
  if (teamName === 'Moorpark') return '#ffe599';
  return '';
}}

function applyTeamStatsRowColor(tr, teamName) {{
  const color = teamStatsRowColor(teamName);
  if (color) tr.querySelectorAll('td').forEach(td => td.style.background = color);
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
  const t = activeFullTeamData().find(d => d.team === teamName);
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

/* ── Minutes Matrix (KenPom-style): per-game minutes per player, starters
   boxed, distinct starting lineups numbered. Seasons with box data only. ── */
let minMatrixReturnTeam = null;
const MM_SEASONS = new Set(['2324', '2425', '2526']);
const MM_LINEUP_COLORS = ['#c8960c', '#7b1fa2', '#2e7d32', '#c62828', '#1565c0', '#00838f', '#6d4c41', '#37474f', '#ad1457', '#558b2f'];

function showMinutesMatrix(teamName) {{
  minMatrixReturnTeam = teamName;
  ensureBoxes(activeSeason, () => renderMinutesMatrix(teamName));
}}

function closeMinutesMatrix() {{
  document.getElementById('minmatrix-view').style.display = 'none';
  if (minMatrixReturnTeam) {{ showTeamDetail(minMatrixReturnTeam); }}
}}

/* ── Team Stats panel: full roster, no minutes qualification.
   Basic mirrors the individual Basic table; Advanced follows KenPom's
   team player-stats layout with usage-band groupings. ── */
let teamStatsReturnTeam = null;
let teamStatsMode = 'basic';

function showTeamStats(teamName) {{
  teamStatsReturnTeam = teamName;
  ensureRosters(activeSeason, () => renderTeamStats(teamName));
}}

function closeTeamStats() {{
  document.getElementById('teamstats-view').style.display = 'none';
  if (teamStatsReturnTeam) {{ showTeamDetail(teamStatsReturnTeam); }}
}}

function setTeamStatsMode(mode) {{
  teamStatsMode = mode;
  if (teamStatsReturnTeam) {{
    ensureRosters(activeSeason, () => renderTeamStats(teamStatsReturnTeam));
  }}
}}

function __tsF(v, d) {{
  return v == null ? '—' : Number(v).toFixed(d == null ? 1 : d);
}}

let tsSortCol = 'ppg';
let tsSortDir = 'desc';

function tsSort(col) {{
  if (tsSortCol === col) {{
    tsSortDir = tsSortDir === 'desc' ? 'asc' : 'desc';
  }} else {{
    tsSortCol = col;
    tsSortDir = col === 'name' ? 'asc' : 'desc';
  }}
  if (teamStatsReturnTeam) renderTeamStats(teamStatsReturnTeam);
}}

const TS_BASIC_COLS = [
  ['name', 'Player'], ['gp', 'GP'], ['mpg', 'MPG'], ['ppg', 'PPG'],
  ['orpg', 'OREB'], ['drpg', 'DREB'], ['rpg', 'RPG'], ['apg', 'APG'],
  ['spg', 'SPG'], ['bpg', 'BPG'], ['topg', 'TO'],
  ['fgm', 'FGM-A'], ['fgp', 'FG%'], ['twom', '2PM-A'], ['twop', '2P%'],
  ['tpm', '3PM-A'], ['tpp', '3P%'], ['efg_pct', 'eFG%'],
  ['ftm', 'FTM-A'], ['ftp', 'FT%'], ['ts_pct', 'TS%'],
];

function __tsBasicTable(rows) {{
  const sorted = rows.slice().sort((a, b) => {{
    const av = a[tsSortCol], bv = b[tsSortCol];
    if (tsSortCol === 'name') {{
      return tsSortDir === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    }}
    const an = Number(av) || 0, bn = Number(bv) || 0;
    return tsSortDir === 'desc' ? bn - an : an - bn;
  }});
  const header = TS_BASIC_COLS.map(([key, label]) => {{
    const cls = (key === 'name' ? 'ts-l ' : '') + (tsSortCol === key ? 'active ' + tsSortDir : '');
    return '<th class="' + cls.trim() + '" onclick="tsSort(\\'' + key + '\\')">' + label + '</th>';
  }}).join('');
  const cells = r =>
    '<td class="ts-l">' + playerLink(r.name, teamStatsReturnTeam) + '</td><td>' + r.gp + '</td><td>' + __tsF(r.mpg) + '</td>'
    + '<td><b>' + __tsF(r.ppg) + '</b></td><td>' + __tsF(r.orpg) + '</td><td>' + __tsF(r.drpg) + '</td>'
    + '<td>' + __tsF(r.rpg) + '</td><td>' + __tsF(r.apg) + '</td><td>' + __tsF(r.spg) + '</td>'
    + '<td>' + __tsF(r.bpg) + '</td><td>' + __tsF(r.topg) + '</td>'
    + '<td>' + r.fgm + '-' + r.fga + '</td><td>' + __tsF(r.fgp) + '</td>'
    + '<td>' + r.twom + '-' + r.twoa + '</td><td>' + __tsF(r.twop) + '</td>'
    + '<td>' + r.tpm + '-' + r.tpa + '</td><td>' + __tsF(r.tpp) + '</td>'
    + '<td>' + __tsF(r.efg_pct) + '</td>'
    + '<td>' + r.ftm + '-' + r.fta + '</td><td>' + __tsF(r.ftp) + '</td>'
    + '<td>' + __tsF(r.ts_pct) + '</td>';
  return '<table class="ts-table ts-basic"><thead><tr>' + header + '</tr></thead><tbody>'
    + sorted.map(r => '<tr>' + cells(r) + '</tr>').join('')
    + '</tbody></table>';
}}

/* State-rank labels (KenPom-style): red rank under a stat when the player
   qualifies. eFG/TS/3P/2P/FT use their leaderboard qualifications
   (advCatQualifies); every other ranked stat qualifies at 30% minutes. */
const TS_RANK_STATS = [
  ['ind_ortg', 'min30', false], ['efg_pct', 'cat', false], ['ts_pct', 'cat', false],
  ['oreb_pct', 'min30', false], ['dreb_pct', 'min30', false], ['ast_rate', 'min30', false],
  ['tov_pct', 'min30', true], ['blk_pct', 'min30', false], ['stl_pct', 'min30', false],
  ['fc_per_40', 'min30', true], ['fd_per_40', 'min30', false], ['ft_rate', 'cat', false],
  ['ftp', 'cat', false], ['twop', 'cat', false], ['tpp', 'cat', false],
];

function __tsQualifies(p, key, mode) {{
  if (p[key] == null) return false;
  if (mode === 'cat') {{
    // eFG/TS/3P/2P/FT rank qualifier: schools without advanced stats use the
    // attempts + GP rule; schools with advanced stats use 50% min%.
    if (advSchoolNeedsRelaxedCat(p.school, key)) {{
      return advCatRelaxedQualifies(p, key);
    }}
    return (p.min_pct || 0) >= 50;
  }}
  return (p.min_pct || 0) >= 30;
}}

function __tsRankMaps() {{
  const pool = activeFullPlayerData() || [];
  const maps = {{}};
  for (const [key, mode, asc] of TS_RANK_STATS) {{
    const qualified = pool.filter(p => __tsQualifies(p, key, mode));
    qualified.sort((a, b) => asc ? a[key] - b[key] : b[key] - a[key]);
    const m = new Map();
    qualified.forEach((p, i) => m.set(p.name + '|' + p.school, i + 1));
    maps[key] = {{ map: m, total: qualified.length }};
  }}
  return maps;
}}

const TS_USAGE_BANDS = [
  [28, 'Go-to Guys (>28% of possessions used)'],
  [24, 'Major Contributors (24-28% of possessions used)'],
  [20, 'Significant Contributors (20-24% of possessions used)'],
  [16, 'Role Players (16-20% of possessions used)'],
  [12, 'Limited Roles (12-16% of possessions used)'],
  [-1, 'Nearly Invisible (<12% of possessions used)'],
];

function __tsRankRow(r, teamName, ranks) {{
  const cell = key => {{
    const info = ranks[key];
    const rk = info ? info.map.get(r.name + '|' + teamName) : null;
    return '<td>' + (rk || '') + '</td>';
  }};
  const cells = '<td class="ts-l ts-ranklabel">State Rank</td><td></td><td></td><td></td>'
    + cell('ind_ortg') + '<td></td><td></td>'
    + cell('efg_pct') + cell('ts_pct') + cell('oreb_pct') + cell('dreb_pct')
    + cell('ast_rate') + cell('tov_pct') + cell('blk_pct') + cell('stl_pct')
    + cell('fc_per_40') + cell('fd_per_40') + cell('ft_rate')
    + '<td></td>' + cell('ftp') + '<td></td>' + cell('twop') + '<td></td>' + cell('tpp');
  const hasAny = TS_RANK_STATS.some(([key]) => ranks[key] && ranks[key].map.has(r.name + '|' + teamName));
  return hasAny ? '<tr class="ts-rankrow">' + cells + '</tr>' : '';
}}

function __tsAdvTable(rows, advOk, teamName, ranks) {{
  const header = '<tr>'
    + '<th class="ts-l">Player</th><th>Ht</th><th>G</th><th>%Min</th><th>ORtg</th><th>%Poss</th><th>%Shots</th>'
    + '<th>eFG%</th><th>TS%</th><th>OR%</th><th>DR%</th><th>ARate</th><th>TORate</th>'
    + '<th>Blk%</th><th>Stl%</th><th>FC/40</th><th>FD/40</th><th>FTRate</th>'
    + '<th>FTM-A</th><th>Pct</th><th>2PM-A</th><th>Pct</th><th>3PM-A</th><th>Pct</th></tr>';
  const NCOLS = 24;
  const cells = r => {{
    const adv = k => advOk ? __tsF(r[k]) : '—';
    return '<td class="ts-l">' + playerLink(r.name, teamStatsReturnTeam) + '</td><td>' + (r.ht || '—') + '</td><td>' + r.gp + '</td>'
      + '<td>' + (advOk ? __tsF(r.min_pct) : '—') + '</td>'
      + '<td><b>' + adv('ind_ortg') + '</b></td><td>' + adv('usage_pct') + '</td><td>' + adv('shot_pct') + '</td>'
      + '<td>' + adv('efg_pct') + '</td><td>' + adv('ts_pct') + '</td>'
      + '<td>' + adv('oreb_pct') + '</td><td>' + adv('dreb_pct') + '</td>'
      + '<td>' + adv('ast_rate') + '</td><td>' + adv('tov_pct') + '</td>'
      + '<td>' + adv('blk_pct') + '</td><td>' + adv('stl_pct') + '</td>'
      + '<td>' + adv('fc_per_40') + '</td><td>' + adv('fd_per_40') + '</td><td>' + adv('ft_rate') + '</td>'
      + '<td>' + r.ftm + '-' + r.fta + '</td><td>' + __tsF(r.ftp) + '</td>'
      + '<td>' + r.twom + '-' + r.twoa + '</td><td>' + __tsF(r.twop) + '</td>'
      + '<td>' + r.tpm + '-' + r.tpa + '</td><td>' + __tsF(r.tpp) + '</td>';
  }};
  const playerRows = r => {{
    if (!advOk) return '<tr>' + cells(r) + '</tr>';
    const rankRow = __tsRankRow(r, teamName, ranks);
    return '<tr' + (rankRow ? ' class="ts-hasrank"' : '') + '>' + cells(r) + '</tr>' + rankRow;
  }};
  let body = '';
  if (!advOk) {{
    body = rows.map(playerRows).join('');
  }} else {{
    // KenPom usage bands; benchwarmers split out by minutes share
    const bench = rows.filter(r => (r.min_pct || 0) < 10);
    const main = rows.filter(r => (r.min_pct || 0) >= 10)
      .sort((a, b) => (b.usage_pct || 0) - (a.usage_pct || 0));
    for (const [floor, label] of TS_USAGE_BANDS) {{
      const band = main.filter(r => {{
        const u = r.usage_pct || 0;
        const idx = TS_USAGE_BANDS.findIndex(bb => u > bb[0]);
        return TS_USAGE_BANDS[idx] && TS_USAGE_BANDS[idx][1] === label;
      }});
      if (!band.length) continue;
      body += '<tr class="ts-band"><td colspan="' + NCOLS + '">' + label + '</td></tr>';
      band.sort((a, b) => (b.min_pct || 0) - (a.min_pct || 0));
      body += band.map(playerRows).join('');
    }}
    if (bench.length) {{
      body += '<tr class="ts-band"><td colspan="' + NCOLS + '">Benchwarmers (played in fewer than 10% of team\\'s minutes)</td></tr>';
      bench.sort((a, b) => (b.min_pct || 0) - (a.min_pct || 0));
      body += bench.map(playerRows).join('');
    }}
  }}
  return '<table class="ts-table"><thead>' + header + '</thead><tbody>' + body + '</tbody></table>';
}}

function renderTeamStats(teamName) {{
  const t = activeFullTeamData().find(d => d.team === teamName);
  const roster = (TEAM_ROSTERS[activeSeason] || {{}})[teamName];
  if (!t || !roster) {{ alert('No roster data for this team.'); return; }}
  const rows = roster.players || [];
  const advOk = roster.adv === 1;

  const netRtgRanks = {{}};
  activeTeamData.filter(d => d.ortg > 0).sort((a, b) => b.net_rtg - a.net_rtg)
    .forEach((d, i) => {{ netRtgRanks[d.team] = i + 1; }});

  const advNote = (teamStatsMode === 'advanced' && !advOk)
    ? '<div style="text-align:center;font-size:0.8rem;color:#b71c1c;font-weight:600;margin-bottom:8px">Advanced stats unavailable — this team does not have 18 clean games with reliable minutes.</div>'
    : '';

  document.getElementById('teamstats-content').innerHTML = `<style>
    #teamstats-content .ts-table {{ width: auto; border-collapse: collapse; font-size: 0.78rem; white-space: nowrap; margin: 0 auto; }}
    #teamstats-content .ts-table th {{ background: #1a1a2e; color: #fff; padding: 5px 7px; text-align: right; font-size: 0.72rem; border-bottom: 2px solid #333; }}
    #teamstats-content .ts-table th.ts-l, #teamstats-content .ts-table td.ts-l {{ text-align: left; }}
    #teamstats-content .ts-table td {{ padding: 4px 7px; border-bottom: 1px solid #ddd; text-align: right; color: #000; background: #fff; }}
    #teamstats-content .ts-table td.ts-l {{ font-weight: 600; }}
    #teamstats-content .ts-table tbody tr:nth-child(odd) td, #teamstats-content .ts-table tbody tr:nth-child(even) td {{ background: #fff; }}
    #teamstats-content .ts-table tbody tr:hover td {{ background: #eef4ff; }}
    #teamstats-content .ts-table tbody tr.ts-band td {{
      background: #c7d3e8; color: #122a52; font-weight: 800; font-size: 0.76rem;
      text-align: left; padding: 6px 8px;
      border-top: 12px solid #fff; border-bottom: 2px solid #1a3a6e;
    }}
    #teamstats-content .ts-table tbody tr.ts-band:hover td {{ background: #c7d3e8; }}
    #teamstats-content .ts-table tbody tr.ts-band:first-child td {{ border-top: none; }}
    #teamstats-content .ts-table.ts-basic {{ font-size: 0.92rem; }}
    #teamstats-content .ts-table.ts-basic th {{ font-size: 0.82rem; padding: 7px 10px; cursor: pointer; }}
    #teamstats-content .ts-table.ts-basic td {{ padding: 6px 10px; }}
    #teamstats-content .ts-table tbody tr.ts-hasrank td {{ border-bottom: none; padding-bottom: 1px; }}
    #teamstats-content .ts-table tbody tr.ts-rankrow td {{
      color: #c62828; font-size: 0.64rem; font-weight: 700;
      padding: 0 7px 4px; border-bottom: 1px solid #ddd; background: #fff;
    }}
    #teamstats-content .ts-table tbody tr.ts-rankrow:hover td {{ background: #fff; }}
    #teamstats-content .ts-table td.ts-ranklabel {{ font-weight: 700; font-style: italic; }}
    #teamstats-content .ts-mode {{ background: none; border: 1px solid #4fc3f7; color: #4fc3f7; font-weight: 700; padding: 3px 14px; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }}
    #teamstats-content .ts-mode.active {{ background: #4fc3f7; color: #1a1a2e; }}
  </style>
  <div style="background:#1a1a2e;border-radius:8px;padding:16px 20px;margin-bottom:16px;text-align:center">
    <div style="color:#4fc3f7;font-size:1.1rem;font-weight:700">#${{netRtgRanks[teamName] || '—'}} NET RTG</div>
    <h2 style="color:#B9D9EB;font-size:1.6rem;margin:4px 0">${{teamName}} — Team Stats</h2>
    <div style="color:#ccc;font-size:0.9rem">${{t.conference}} · ${{t.region}} Region</div>
    <div style="color:#fff;font-size:1.1rem;font-weight:700;margin-top:4px">${{t.record}} Overall &nbsp;|&nbsp; ${{t.conf}} Conference</div>
  </div>
  <div style="display:flex;justify-content:center;gap:10px;margin-bottom:12px">
    <button class="ts-mode${{teamStatsMode === 'basic' ? ' active' : ''}}" onclick="setTeamStatsMode('basic')">Basic</button>
    <button class="ts-mode${{teamStatsMode === 'advanced' ? ' active' : ''}}" onclick="setTeamStatsMode('advanced')">Advanced</button>
  </div>
  ${{advNote}}
  <div style="background:#fff;border-radius:8px;padding:16px;border:1px solid #ccc;overflow-x:auto;max-width:fit-content;margin:0 auto">
    ${{teamStatsMode === 'basic' ? __tsBasicTable(rows) : __tsAdvTable(rows, advOk, teamName, advOk ? __tsRankMaps() : {{}})}}
    <div style="font-size:0.72rem;color:#888;margin-top:8px">
      All players, no minutes qualification · ${{teamStatsMode === 'advanced' ? 'Layout follows KenPom team player stats; bands by %Poss used · ' : ''}}Season: ${{activeSeason === '2526' ? '2025-26' : activeSeason}}
    </div>
  </div>`;
  document.getElementById('team-detail-view').style.display = 'none';
  document.getElementById('teamstats-view').style.display = 'block';
  window.scrollTo(0, 0);
}}

/* ── Lineups panel (Synergy 5-man lineup data; Moorpark-only) ─────────── */
let lineupsReturnTeam = null;
function showLineups(teamName) {{ lineupsReturnTeam = teamName; renderLineups(teamName); }}
function closeLineups() {{
  document.getElementById('lineups-view').style.display = 'none';
  if (lineupsReturnTeam) showTeamDetail(lineupsReturnTeam);
}}
/* ═══ Keys to Victory ══════════════════════════════════════════════════
   EvanMiya-style "Keys to Victory Automated Team Report" (light theme).
   Three <select>s: Team, Seasons window (5yr / current), Number of Targets.
   Auto-generated narrative + Metric|Target table + Targets-Hit table (with
   Global columns), then a Style Metrics Report. Team targets-hit table is
   recomputed client-side from per-game hit flags; globals precomputed. */
let keysN = 3;
let currentKeysTeam = null;
let currentKeysWindow = '5yr';
function showKeys() {{ showView('keys'); }}
function keysSetN(n) {{ keysN = Number(n); renderKeys(); }}
function keysSetTeam(t) {{ currentKeysTeam = t; keysN = 3; renderKeys(); }}
function keysSetWindow(w) {{ currentKeysWindow = w; keysN = 3; renderKeys(); }}
function __kF(v, d) {{ return (v == null || isNaN(v)) ? '—' : Number(v).toFixed(d == null ? 1 : d); }}
function __kPn(v) {{ if (v == null || isNaN(v)) return '—'; const n = Number(v); return Number.isInteger(n) ? n.toString() : n.toFixed(1); }}
function __kPct(v) {{ return v == null || isNaN(v) ? '—' : __kPn(v) + '%'; }}
function __kNum(v) {{ return (v == null || isNaN(v)) ? '—' : Number(v).toFixed(1); }}

function __kIsPct(k) {{ return /Rate|Shooting|eFG|TS%|3P%|2P%|FG%|Ast%|%/.test(k.metric); }}
function __kPhrase(k) {{
  const t = k.target, u = __kIsPct(k) ? '%' : '', ge = k.dir === '>=';
  const longl = (k.long || k.label).toLowerCase();
  if (k.metric.indexOf('Opp') === 0) {{
    const noun = (k.long || k.label).replace(/^Opponent /i, '').replace(/^Opp /i, '').toLowerCase();
    return ge ? `force their opponent into at least ${{t}}${{u}} ${{noun}}`
              : `hold their opponent to a ${{noun}} of ${{t}}${{u}} or lower`;
  }}
  if (k.metric.indexOf('Margin') >= 0) return `have a ${{longl}} of ${{ge ? 'at least' : 'no more than'}} ${{t}}${{u}}`;
  if (!__kIsPct(k)) return `have at least ${{t}} ${{longl}}`;
  return `have a ${{longl}} of ${{ge ? 'at least' : 'no more than'}} ${{t}}${{u}}`;
}}
function __movPhrase(mov) {{
  if (mov == null || isNaN(mov)) return 'have an even scoring margin';
  const n = Number(mov);
  return n >= 0 ? `score ${{__kF(n,1)}} more points than their opponent on average`
                : `score ${{__kF(Math.abs(n),1)}} fewer points than their opponent on average`;
}}
const __STYLE_LONG = {{
  'Pace (Poss)': 'Pace', '3PA Rate (3PA/FGA)': 'Three Point Attempt Rate',
  'FT Rate (FTA/FGA)': 'Free Throw Rate', 'Assist %': 'Assist Percentage',
  'Bench Points %': 'Bench Points Percentage'
}};
function __stylePhrase(s) {{
  const t = s.target, ge = s.dir === '>=';
  const u = /%|Rate/.test(s.label) ? '%' : '';
  const lab = (__STYLE_LONG[s.label] || s.label).toLowerCase();
  if (s.metric === 'Bench Pts%') return {{ better: 'rely more heavily on bench scoring',
    hit: `their bench scores at least ${{t}}% of their points`,
    miss: `less than ${{t}}% of their scoring comes from their bench` }};
  if (s.metric === 'Poss') return {{ better: ge ? 'play at a faster pace' : 'play at a slower pace',
    hit: `they have ${{ge ? 'at least' : 'no more than'}} ${{t}} possessions`,
    miss: `they have ${{ge ? 'fewer than' : 'more than'}} ${{t}} possessions` }};
  return {{ better: ge ? `have a higher ${{lab}}` : `have a lower ${{lab}}`,
    hit: `they have a ${{lab}} of ${{ge ? 'at least' : 'no more than'}} ${{t}}${{u}}`,
    miss: `they have a ${{lab}} ${{ge ? 'less than' : 'greater than'}} ${{t}}${{u}}` }};
}}
function __englishList(arr) {{
  if (arr.length <= 1) return arr[0] || '';
  if (arr.length === 2) return arr[0] + ' and ' + arr[1];
  return arr.slice(0, -1).join(', ') + ', and ' + arr[arr.length - 1];
}}

/* ═══ KEY METRICS EXPLORER (2nd sub-tab of Keys) ═══════════════════════════
   Pick any 3 per-game metrics; auto-targets + targets-hit table + a games
   scatter, all computed in-browser from the last-5-season box scores. */
let keysSubTab = 'report';
let kxFilterHits = 'all';
let kxSearch = '';
let kxWindow = 'tenure';
let kxView = 'all';
let kxSel = [null, null, null];
let __kxPoolCache = {{}};
const KX_SEASON_KEY = {{'2025-26':'2526','2024-25':'2425','2023-24':'2324','2022-23':'2223','2021-22':'2122'}};
const KX_LAST5 = ['2025-26','2024-25','2023-24','2022-23','2021-22'];
const KX_LABELS = {{'eFG% Margin':'eFG% Margin','TS% Margin':'TS% Margin','3P% Margin':'3P% Margin','Opp AST':'Opp Assists','Reb Margin':'Reb Margin','TO Margin':'TO Margin','AST':'Assists','Ast%':'Assist %','Ast-TO':'Assist:TO','REB':'Rebounds','DREB':'Def Rebounds','OREB':'Off Rebounds','ORB%':'Off Reb %','DRB%':'Def Reb %','3PM':'Threes Made','FTM':'FTs Made','Stl':'Steals','Blk':'Blocks','TO':'Turnovers','3PA Rate':'3PA Rate','FT Rate':'FT Rate','TO%':'TO %','Poss':'Possessions'}};
function kxLabel(k){{ return KX_LABELS[k] || k; }}
function __kxTotals(players){{
  const s={{FGM:0,FGA:0,TPM:0,TPA:0,FTM:0,FTA:0,OREB:0,DREB:0,AST:0,STL:0,BLK:0,TO:0,PTS:0}};
  for(const p of (players||[])){{ s.FGM+=p.fgm||0;s.FGA+=p.fga||0;s.TPM+=p.tpm||0;s.TPA+=p.tpa||0;s.FTM+=p.ftm||0;s.FTA+=p.fta||0;s.OREB+=p.or||0;s.DREB+=p.dr||0;s.AST+=p.ast||0;s.STL+=p.stl||0;s.BLK+=p.blk||0;s.TO+=p.to||0;s.PTS+=p.pts||0; }}
  s.REB=s.OREB+s.DREB; return s;
}}
function __kxMetrics(t,o){{
  const safe=(n,d,sc)=>{{ sc=(sc==null?1:sc); return d?(n/d)*sc:0; }}; const r2=x=>Math.round(x*100)/100;
  const side=s=>{{ const tm=s.FGM-s.TPM, ta=s.FGA-s.TPA; return {{'FG%':safe(s.FGM,s.FGA,100),'3P%':safe(s.TPM,s.TPA,100),'2P%':safe(tm,ta,100),'FT%':safe(s.FTM,s.FTA,100),'eFG%':safe(s.FGM+0.5*s.TPM,s.FGA,100),'TS%':safe(s.PTS,2*(s.FGA+0.475*s.FTA),100),'3PA Rate':safe(s.TPA,s.FGA,100),'FT Rate':safe(s.FTA,s.FGA,100),'Ast%':safe(s.AST,s.FGM,100),'Ast-TO':safe(s.AST,s.TO),'TO%':safe(s.TO,s.FGA+0.475*s.FTA+s.TO,100),'Stl':s.STL,'Blk':s.BLK,'AST':s.AST,'TO':s.TO,'OREB':s.OREB,'DREB':s.DREB,'REB':s.REB,'3PM':s.TPM,'FTM':s.FTM}}; }};
  const T=side(t),O=side(o),m={{}};
  for(const k in T) m[k]=r2(T[k]); for(const k in O) m['Opp '+k]=r2(O[k]);
  m['ORB%']=r2(safe(t.OREB,t.OREB+o.DREB,100)); m['DRB%']=r2(safe(t.DREB,t.DREB+o.OREB,100));
  m['Reb Margin']=t.REB-o.REB; m['TO Margin']=o.TO-t.TO;
  m['eFG% Margin']=r2(T['eFG%']-O['eFG%']); m['TS% Margin']=r2(T['TS%']-O['TS%']); m['3P% Margin']=r2(T['3P%']-O['3P%']);
  m['Poss']=Math.round(((t.FGA-t.OREB)+t.TO+0.475*t.FTA)*10)/10; return m;
}}
function __kxBuildPool(sks){{
  const ck=sks.join(','); if(__kxPoolCache[ck]) return __kxPoolCache[ck];
  const pool=[];
  for(const sk of sks){{ const boxes=GAME_BOXES[sk]||{{}};
    for(const key in boxes){{ const g=boxes[key]; if(!g||!g.t) continue; const teams=Object.keys(g.t); if(teams.length!==2) continue; const sc=g.sc||{{}};
      for(let a=0;a<2;a++){{ const me=teams[a],op=teams[1-a],ms=sc[me],os=sc[op]; if(ms==null||os==null) continue;
        pool.push({{team:me,opp:op,sk,date:g.d,res:ms>os?1:0,margin:ms-os,pf:ms,pa:os,m:__kxMetrics(__kxTotals(g.t[me]),__kxTotals(g.t[op]))}}); }} }} }}
  __kxPoolCache[ck]=pool; return pool;
}}
function __kxEnsurePool(seasons,cb){{ const keys=seasons.map(s=>KX_SEASON_KEY[s]).filter(Boolean); let i=0; (function next(){{ if(i>=keys.length){{ cb(__kxBuildPool(keys)); return; }} ensureBoxes(keys[i++],next); }})(); }}
function __kxPB(vals,outs){{ const n=vals.length; if(n<3) return 0; const w=[],l=[]; for(let i=0;i<n;i++)(outs[i]?w:l).push(vals[i]); if(!w.length||!l.length) return 0; const mean=vals.reduce((a,b)=>a+b,0)/n; const sd=Math.sqrt(vals.reduce((a,v)=>a+(v-mean)*(v-mean),0)/n); if(sd===0) return 0; const mw=w.reduce((a,b)=>a+b,0)/w.length,ml=l.reduce((a,b)=>a+b,0)/l.length,p=w.length/n,q=l.length/n; return (mw-ml)/sd*Math.sqrt(p*q); }}
function __kxThresh(vals,outs,dir){{ const c=[...new Set(vals)].sort((a,b)=>a-b); if(c.length<2) return [c[0]||0,0]; const mids=[]; for(let i=1;i<c.length;i++) mids.push((c[i-1]+c[i])/2); const npos=outs.reduce((a,b)=>a+b,0),nneg=outs.length-npos; if(!npos||!nneg) return [mids[Math.floor(mids.length/2)],0]; let best=mids[0],bestJ=-1; for(const t of mids){{ let tp=0,fp=0; for(let i=0;i<vals.length;i++){{ const me=(dir==='>=')?(vals[i]>=t):(vals[i]<=t); if(me){{ if(outs[i])tp++; else fp++; }} }} const J=tp/npos-fp/nneg; if(J>bestJ){{ bestJ=J; best=t; }} }} return [best,bestJ]; }}
function __kxAutoTarget(games,k){{ const vals=[],outs=[]; for(const g of games){{ const v=g.m[k]; if(v!=null){{ vals.push(v); outs.push(g.res); }} }} if(vals.length<5) return null; const r=__kxPB(vals,outs),dir=r>=0?'>=':'<='; const [t]=__kxThresh(vals,outs,dir); return {{metric:k,dir,target:Math.round(t*10)/10,r:Math.round(r*100)/100}}; }}
function __kxHits(g,targets){{ let h=0; for(const tg of targets){{ if(!tg) continue; const v=g.m[tg.metric]; if(v==null) continue; if((tg.dir==='>='&&v>=tg.target)||(tg.dir==='<='&&v<=tg.target)) h++; }} return h; }}
function __kxHitTable(games,targets,n){{ const rows=[]; for(let i=0;i<=n;i++) rows.push({{g:0,w:0,mov:0}}); for(const g of games){{ const r=rows[__kxHits(g,targets)]; r.g++; r.w+=g.res; r.mov+=g.margin; }} return rows; }}
function kxSetTab(t){{ keysSubTab=t; renderKeysView(); }}
function kxSetWindow(w){{ kxWindow=w; kxView='all'; kxSel=[null,null,null]; renderKeysExplorer(); }}
function kxSetTeam(t){{ currentKeysTeam=t; kxView='all'; kxSel=[null,null,null]; renderKeysExplorer(); }}
function kxSetView(v){{ kxView=v; renderKeysExplorer(); }}
function kxSetMetric(i,k){{ kxSel[i]=k||null; renderKeysExplorer(); }}
function __kxApplyTableFilters(){{
  const fEl=document.getElementById('kxHitsFilter'), sEl=document.getElementById('kxSearch');
  const f=fEl?fEl.value:'all'; kxFilterHits=f; kxSearch=sEl?sEl.value:'';
  const s=kxSearch.trim().toLowerCase();
  document.querySelectorAll('#kxGameRows tr').forEach(r=>{{
    const okH=(f==='all'||r.getAttribute('data-h')===f);
    const okS=(!s||(r.getAttribute('data-s')||'').indexOf(s)>=0);
    r.style.display=(okH&&okS)?'':'none';
  }});
}}
function renderKeysView(){{
  const tb=document.getElementById('keys-subtoggle');
  if(tb){{ const btn=(id,lab)=>`<button onclick="kxSetTab('${{id}}')" style="background:${{keysSubTab===id?'#1a1f2e':'#fff'}};color:${{keysSubTab===id?'#fff':'#1a1f2e'}};border:1px solid #1a1f2e;font-weight:700;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:0.9rem">${{lab}}</button>`;
    tb.innerHTML=`<div style="display:flex;gap:10px;justify-content:center;margin:4px 0 14px">${{btn('report','Key Metrics Report')}}${{btn('table','Key Metrics Table')}}${{btn('explorer','Key Metrics Explorer')}}</div>`; }}
  if(keysSubTab==='explorer'||keysSubTab==='table') renderKeysExplorer(); else renderKeys();
}}
function renderKeysExplorer(){{
  const host=document.getElementById('keys-content');
  const MAP=(typeof TEAM_KEYS!=='undefined'&&TEAM_KEYS)?TEAM_KEYS:null;
  const teamNames=MAP?Object.keys(MAP).sort((a,b)=>a.localeCompare(b)):[];
  if(!MAP||!teamNames.length){{ host.innerHTML='<div style="text-align:center;color:#999;padding:50px">No keys data available.</div>'; return; }}
  if(!currentKeysTeam||!MAP[currentKeysTeam]) currentKeysTeam=MAP['Moorpark']?'Moorpark':teamNames[0];
  const entry=MAP[currentKeysTeam], w5=entry.windows['5yr'], wc=entry.windows['cur'];
  const tenureSeasons=(w5&&w5.seasons)?w5.seasons.filter(s=>KX_SEASON_KEY[s]):['2025-26'];
  const seasons=(kxWindow==='cur')?['2025-26']:tenureSeasons;
  const wEmbed=(kxWindow==='cur')?(wc||w5):(w5||wc);
  if(kxSel.every(x=>x==null)&&wEmbed&&wEmbed.keys){{ for(let i=0;i<3;i++) kxSel[i]=wEmbed.keys[i]?wEmbed.keys[i].metric:null; }}
  host.innerHTML='<div style="text-align:center;color:#999;padding:42px">Loading game data…</div>';
  __kxEnsurePool(KX_LAST5,(pool)=>__kxRenderExplorer(pool,entry,seasons,teamNames));
}}
function __kxRenderExplorer(pool,entry,seasons,teamNames){{
  const host=document.getElementById('keys-content');
  const isTbl=(keysSubTab==='table');
  const nrm=__boxNorm;
  const analyzeKeys=seasons.map(s=>KX_SEASON_KEY[s]);
  if(kxView!=='all' && seasons.indexOf(kxView)<0) kxView='all';
  const viewSeasons=(kxView==='all')?seasons:[kxView];
  const viewKeys=viewSeasons.map(s=>KX_SEASON_KEY[s]);
  const teamAnalyze=pool.filter(g=>nrm(g.team)===nrm(currentKeysTeam)&&analyzeKeys.indexOf(g.sk)>=0);
  const teamView=teamAnalyze.filter(g=>viewKeys.indexOf(g.sk)>=0);
  const globalView=pool.filter(g=>viewKeys.indexOf(g.sk)>=0);
  const targets=kxSel.map(k=>k?__kxAutoTarget(teamAnalyze,k):null);
  const nSel=Math.max(targets.filter(Boolean).length,1);
  const tt=__kxHitTable(teamView,targets,nSel), gt=__kxHitTable(globalView,targets,nSel);
  const allMetrics=pool.length?Object.keys(pool[0].m):[];
  // ── selects ──
  const seln=(html,oc)=>`<select onchange="${{oc}}" style="width:100%;padding:9px 13px;border:1px solid #cdd2da;border-radius:6px;background:#fff;color:#1a1f2e;font-size:0.9rem;cursor:pointer">${{html}}</select>`;
  const teamOpts=teamNames.map(t=>`<option value="${{t}}" ${{t===currentKeysTeam?'selected':''}}>${{t}}</option>`).join('');
  const tenSeasons=(entry.windows['5yr']&&entry.windows['5yr'].seasons)?entry.windows['5yr'].seasons.filter(s=>KX_SEASON_KEY[s]):['2025-26'];
  const span=tenSeasons.length>1?(tenSeasons[0]+' to '+tenSeasons[tenSeasons.length-1]):tenSeasons[0];
  const coach=entry.coach||'';
  const analyzeOpts=`<option value="tenure" ${{kxWindow==='tenure'?'selected':''}}>${{span}}${{coach?(' (all under '+coach+')'):''}}</option><option value="cur" ${{kxWindow==='cur'?'selected':''}}>2025-26 only</option>`;
  const viewOpts=['all'].concat(seasons).map(v=>`<option value="${{v}}" ${{kxView===v?'selected':''}}>${{v==='all'?'All Seasons':v}}</option>`).join('');
  const mSel=i=>seln('<option value="">— none —</option>'+allMetrics.map(k=>`<option value="${{k}}" ${{kxSel[i]===k?'selected':''}}>${{kxLabel(k)}}</option>`).join(''),`kxSetMetric(${{i}},this.value)`);
  const lbl=t=>`<div style="font-weight:700;color:#1a1f2e;font-size:0.82rem;margin:0 0 6px">${{t}}</div>`;
  // ── tables ──
  const th=(t,a)=>`<th style="padding:9px 16px;text-align:${{a||'left'}};background:#fff;border-bottom:2px solid #1a1f2e;color:#1a1f2e;font-size:0.84rem;font-weight:700;white-space:nowrap">${{t}}</th>`;
  const td=(t,a)=>`<td style="padding:8px 16px;text-align:${{a||'left'}};border-bottom:1px solid #edeff2;color:#2b3240;font-size:0.88rem;white-space:nowrap">${{t}}</td>`;
  const tgtRows=targets.map(tg=>tg?`<tr>${{td(kxLabel(tg.metric))}}${{td((tg.dir==='>='?'>= ':'<= ')+tg.target)}}</tr>`:'').join('');
  const tgtTbl=`<table style="border-collapse:collapse"><thead><tr>${{th('Metric')}}${{th('Target')}}</tr></thead><tbody>${{tgtRows}}</tbody></table>`;
  const pct=r=>{{ if(!r.g) return '—'; const p=100*r.w/r.g; return (Math.abs(p-Math.round(p))<0.05?Math.round(p):(Math.round(p*10)/10))+'%'; }};
  const mov=r=>r.g?(Math.round(10*r.mov/r.g)/10):'—';
  let hitRows='';
  for(let i=0;i<=nSel;i++){{ const r=tt[i],G=gt[i]; hitRows+=`<tr>${{td(i,'center')}}${{td(r.g,'center')}}${{td(pct(r),'center')}}${{td(r.w,'center')}}${{td(r.g-r.w,'center')}}${{td(mov(r),'center')}}${{td(pct(G),'center')}}${{td(mov(G),'center')}}</tr>`; }}
  const hitTbl=`<table style="border-collapse:collapse;min-width:680px"><thead><tr>${{th('Targets Hit','center')}}${{th('Num Games','center')}}${{th('Team Win Pct','center')}}${{th('W','center')}}${{th('L','center')}}${{th('Avg Margin of Victory','center')}}${{th('Global Win Pct','center')}}${{th('Global Avg MOV','center')}}</tr></thead><tbody>${{hitRows}}</tbody></table>`;
  // ── scatter ──
  const W=960,H=380,pL=40,pR=24,pT=22,pB=46;
  const mg=teamView.map(g=>g.margin); const mgs=mg.length?mg:[0];
  const minX=Math.min(-25,...mgs)-4,maxX=Math.max(25,...mgs)+4;
  const xS=v=>pL+((v-minX)/(maxX-minX))*(W-pL-pR);
  const yS=h=>pT+(1-h/nSel)*(H-pT-pB);
  let grid='';
  for(let h=0;h<=nSel;h++){{ const y=yS(h); grid+=`<line x1="${{pL}}" y1="${{y.toFixed(1)}}" x2="${{W-pR}}" y2="${{y.toFixed(1)}}" stroke="#edf0f3"/><text x="${{pL-10}}" y="${{(y+4).toFixed(1)}}" text-anchor="end" font-size="12" fill="#888">${{h}}</text>`; }}
  for(let v=Math.ceil(minX/10)*10;v<=maxX;v+=10){{ const x=xS(v); grid+=`<line x1="${{x.toFixed(1)}}" y1="${{pT}}" x2="${{x.toFixed(1)}}" y2="${{H-pB}}" stroke="${{v===0?'#cfd4da':'#f3f5f7'}}"/><text x="${{x.toFixed(1)}}" y="${{H-pB+18}}" text-anchor="middle" font-size="11" fill="#999">${{v}}</text>`; }}
  // Beeswarm: offset colliding dots up/down off their hit line so none overlap.
  const R=6, gap=2*R+0.5;
  const bandHalf=Math.min((H-pT-pB)/nSel/2*0.94, 70);
  const byH={{}};
  for(const g of teamView){{ const h=__kxHits(g,targets); (byH[h]=byH[h]||[]).push(g); }}
  let dots='';
  for(const hk in byH){{
    const baseY=yS(+hk), arr=byH[hk].slice().sort((a,b)=>a.margin-b.margin), placed=[];
    for(const g of arr){{
      const x=xS(g.margin);
      const collide=yy=>placed.some(p=>Math.abs(p.x-x)<gap && Math.abs(p.y-yy)<gap);
      let y=baseY;
      for(let i=0;i<80;i++){{ const o=(i%2?1:-1)*Math.ceil(i/2)*gap; if(Math.abs(o)>bandHalf) break; if(!collide(baseY+o)){{ y=baseY+o; break; }} y=baseY+o; }}
      placed.push({{x,y}});
      const tip=(g.res?'W ':'L ')+(g.margin>=0?'+':'')+g.margin+' vs '+g.opp+'  ('+g.date+')  |  '+targets.filter(Boolean).map(tg=>kxLabel(tg.metric)+': '+g.m[tg.metric]).join('   ');
      dots+=`<circle cx="${{x.toFixed(1)}}" cy="${{y.toFixed(1)}}" r="${{R}}" fill="${{g.res?'#21a05a':'#e23b3b'}}" fill-opacity="0.9" stroke="#fff" stroke-width="1"><title>${{tip.replace(/"/g,'&quot;')}}</title></circle>`;
    }}
  }}
  const scatter=`<svg viewBox="0 0 ${{W}} ${{H}}" style="width:100%;max-width:${{W}}px;height:auto;display:block;margin:0 auto">${{grid}}${{dots}}<text x="${{W/2}}" y="${{H-4}}" text-anchor="middle" font-size="12.5" fill="#555">Margin of Victory</text></svg>`;
  // ── game-by-game table (Key Metrics Table sub-tab) ──
  const selTargets=targets.filter(Boolean);
  const pd=s=>{{ const p=String(s).split('/'); return new Date(+p[2],+p[0]-1,+p[1]); }};
  const fmtv=(k,v)=>{{ if(v==null||isNaN(v)) return '—'; const n=Math.round(v*10)/10; return /%/.test(k)?(n+'%'):(''+n); }};
  const isHit=(g,tg)=>{{ const v=g.m[tg.metric]; if(v==null) return null; return (tg.dir==='>=')?(v>=tg.target):(v<=tg.target); }};
  const tdg=(t,a,bg)=>`<td style="padding:7px 14px;text-align:${{a||'left'}};border-bottom:1px solid #edeff2;color:#2b3240;font-size:0.86rem;white-space:nowrap;${{bg?('background:'+bg):''}}">${{t}}</td>`;
  let trows='';
  for(const g of teamView.slice().sort((a,b)=>pd(b.date)-pd(a.date))){{
    const h=__kxHits(g,targets); let mc='';
    for(const tg of selTargets){{ const hit=isHit(g,tg); const bg=(hit==null)?'':(hit?'#cdeccd':'#f3cccc'); mc+=tdg(fmtv(tg.metric,g.m[tg.metric]),'center',bg); }}
    trows+=`<tr data-h="${{h}}" data-s="${{(g.opp+' '+g.date).toLowerCase().replace(/"/g,'')}}">`+
      tdg(g.date)+tdg(currentKeysTeam)+tdg(g.opp)+tdg(g.pf,'center')+tdg(g.pa,'center')+
      tdg(g.res?'W':'L','center',g.res?'#cdeccd':'#f3cccc')+tdg(h,'center')+mc+`</tr>`;
  }}
  const mHeads=selTargets.map(tg=>th(kxLabel(tg.metric),'center')).join('');
  const gameTbl=`<div style="overflow-x:auto;margin-top:4px"><table style="border-collapse:collapse;width:100%;min-width:760px"><thead><tr>${{th('Date')}}${{th('Team')}}${{th('Opponent')}}${{th('Score','center')}}${{th('Opp Score','center')}}${{th('Result','center')}}${{th('Targets Hit','center')}}${{mHeads}}</tr></thead><tbody id="kxGameRows">${{trows}}</tbody></table></div>`;
  if(kxFilterHits!=='all'&&(+kxFilterHits>nSel||isNaN(+kxFilterHits))) kxFilterHits='all';
  const hitOpts=['all'].concat(Array.from({{length:nSel+1}},(_,i)=>''+i)).map(v=>`<option value="${{v}}" ${{v===kxFilterHits?'selected':''}}>${{v==='all'?'All':v}}</option>`).join('');
  // ── compose (EvanMiya layout) ──
  const card=(inner)=>`<div style="background:#fff;border:1px solid #e3e6ea;border-radius:8px;padding:24px 30px;margin:0 auto 22px;max-width:1240px;box-shadow:0 1px 3px rgba(0,0,0,0.05)">${{inner}}</div>`;
  const title=isTbl?'Keys to Victory Metrics Tables':'Key to Victory Metrics Explorer';
  if(!teamAnalyze.length){{ host.innerHTML=card(`<div style="font-weight:700;color:#1a1f2e;font-size:1.35rem;margin-bottom:12px">${{title}}</div><div style="display:flex;gap:26px;flex-wrap:wrap;align-items:flex-end"><div style="min-width:240px;flex:1">${{lbl('Team:')}}${{seln(teamOpts,'kxSetTeam(this.value)')}}</div></div>`)+card(`<div style="text-align:center;color:#999;padding:30px">No box-score games found for ${{currentKeysTeam}}.</div>`); return; }}
  const instr=isTbl
    ? `<b>Instructions:</b> This page lets you choose different game metrics (and their target values) and see how they have varied game-to-game. The metrics in the Key Metrics Report are here, along with others that are also important for the team. Select the team and seasons to analyze, then pick a target (one or more metrics). At the top you'll see the target value for each metric, along with stats on team performance based on those targets being met in each game. In the table, you'll see each game listed, with the values for each metric and how many targets were hit. If a value is colored <span style="color:#21a05a;font-weight:700">green</span>, the team hit that metric's target; if <span style="color:#e23b3b;font-weight:700">red</span>, it did not. You can also filter to only games where a specified number of targets were met.`
    : `<b>Instructions:</b> This graph lets you visualize the team's key-metric targets on a game-by-game basis. You can choose any of the targets listed in the Key Metrics Report, along with many others. Select the team and seasons to analyze, then pick a target (one or more metrics). At the top you'll see the target value for each metric along with the team's performance based on those targets being met in each game. On the graph, games are split by how many targets were met — games hitting more targets sit higher, fewer sit lower. Hover a point to see the game's result and how the team fared on the target metrics. <span style="color:#21a05a;font-weight:700">Green dots</span> indicate wins, and <span style="color:#e23b3b;font-weight:700">red dots</span> indicate losses. If a metric matters to the team's success, you'll see more green dots up top and more red dots down low.`;
  const header=card(
    `<div style="font-weight:700;color:#1a1f2e;font-size:1.35rem;padding-bottom:16px;border-bottom:1px solid #e3e6ea;margin-bottom:18px">${{title}}</div>`+
    `<p style="color:#3a4250;font-size:0.9rem;line-height:1.62;margin:0 0 20px">${{instr}}</p>`+
    `<div style="display:flex;gap:26px;flex-wrap:wrap;align-items:flex-end"><div style="min-width:240px;flex:1">${{lbl('Team:')}}${{seln(teamOpts,'kxSetTeam(this.value)')}}</div><div style="min-width:320px;flex:1.5">${{lbl('Choose Seasons to Analyze:')}}${{seln(analyzeOpts,'kxSetWindow(this.value)')}}</div></div>`);
  const tableBottom=
    `<div style="display:flex;gap:26px;flex-wrap:wrap;align-items:flex-end;margin:26px 0 6px"><div style="min-width:300px;flex:1">${{lbl('Choose Season To View')}}${{seln(viewOpts,'kxSetView(this.value)')}}</div><div style="min-width:300px;flex:1">${{lbl('Filter by Number of Targets Hit')}}<select id="kxHitsFilter" onchange="__kxApplyTableFilters()" style="width:100%;padding:9px 13px;border:1px solid #cdd2da;border-radius:6px;background:#fff;color:#1a1f2e;font-size:0.9rem;cursor:pointer">${{hitOpts}}</select></div></div>`+
    `<div style="display:flex;justify-content:flex-end;margin:14px 0 8px"><input id="kxSearch" placeholder="Search…" value="${{(kxSearch||'').replace(/"/g,'&quot;')}}" oninput="__kxApplyTableFilters()" style="min-width:220px;padding:8px 12px;border:1px solid #cdd2da;border-radius:6px;font-size:0.9rem"></div>`+
    gameTbl+
    `<div style="text-align:center;font-size:0.72rem;color:#aaa;margin-top:10px">A value is <span style="color:#1f8a4c;font-weight:700">green</span> when the team hit that metric's target, <span style="color:#c0392b;font-weight:700">red</span> when it missed. Targets auto-set over the analyze window (point-biserial direction + Youden's J).</div>`;
  const explorerBottom=
    `<div style="max-width:360px;margin:26px 0 6px">${{lbl('Choose Season To View')}}${{seln(viewOpts,'kxSetView(this.value)')}}</div>`+
    `<div style="text-align:center;font-weight:700;color:#1a1f2e;font-size:1.3rem;margin:20px 0 2px">Key Metrics Explorer</div>${{scatter}}`+
    `<div style="text-align:center;font-size:0.8rem;color:#777;margin-top:6px">Wins are in <span style="color:#21a05a;font-weight:700">green</span>, losses in <span style="color:#e23b3b;font-weight:700">red</span></div>`+
    `<div style="text-align:center;font-size:0.72rem;color:#aaa;margin-top:8px">Targets auto-set to the cut that best splits this team's wins from losses (point-biserial direction + Youden's J), over the analyze window. Global = all CCC teams over the 2021-22→2025-26 window (~${{globalView.length.toLocaleString()}} team-games, counted from both sides of each game), computed from box scores.</div>`;
  const body=card(
    `<div style="display:flex;gap:26px;flex-wrap:wrap;align-items:flex-end;margin-bottom:20px"><div style="min-width:210px;flex:1">${{lbl('Choose Metric #1')}}${{mSel(0)}}</div><div style="min-width:210px;flex:1">${{lbl('Choose Metric #2')}}${{mSel(1)}}</div><div style="min-width:210px;flex:1">${{lbl('Choose Metric #3')}}${{mSel(2)}}</div></div>`+
    `<div style="display:flex;gap:44px;flex-wrap:wrap;align-items:flex-start"><div>${{tgtTbl}}</div><div style="flex:1;min-width:620px;overflow-x:auto">${{hitTbl}}</div></div>`+
    (isTbl?tableBottom:explorerBottom));
  host.innerHTML=header+body;
  if(isTbl) __kxApplyTableFilters();
}}

function renderKeys() {{
  const host = document.getElementById('keys-content');
  const MAP = (typeof TEAM_KEYS !== 'undefined' && TEAM_KEYS) ? TEAM_KEYS : null;
  const teamNames = MAP ? Object.keys(MAP).sort((a, b) => a.localeCompare(b)) : [];
  if (!MAP || !teamNames.length) {{ host.innerHTML = '<div style="text-align:center;color:#999;padding:50px">No keys data available.</div>'; return; }}
  if (!currentKeysTeam || !MAP[currentKeysTeam]) currentKeysTeam = MAP['Moorpark'] ? 'Moorpark' : teamNames[0];
  const entry = MAP[currentKeysTeam];
  const coach = entry.coach || '';
  const windows = entry.windows || {{}};
  if (!windows[currentKeysWindow]) currentKeysWindow = Object.keys(windows)[0];
  const D = windows[currentKeysWindow];
  const maxN = D.max_targets || D.keys.length;
  if (keysN > maxN) keysN = maxN;
  const N = keysN;
  const keys = D.keys.slice(0, N);

  // team targets-hit table from per-game hit flags (first N keys)
  const team = [];
  for (let i = 0; i <= N; i++) team.push({{ g: 0, w: 0, l: 0, mov: 0 }});
  for (const gm of D.games) {{
    let h = 0; for (let i = 0; i < N; i++) if (gm.hits[i]) h++;
    const r = team[h]; r.g++; r.w += gm.res; r.l += (1 - gm.res); r.mov += gm.margin;
  }}
  const tPct = (r) => r.g ? (100 * r.w / r.g) : null;
  const tMov = (r) => r.g ? (r.mov / r.g) : null;
  const gl = (D.global && D.global[String(N)]) ? D.global[String(N)] : null;

  // ── light-theme building blocks ──
  const card = (inner) => `<div style="background:#fff;border:1px solid #e3e6ea;border-radius:7px;padding:20px 26px;margin:0 auto 18px;max-width:1180px;box-shadow:0 1px 2px rgba(0,0,0,0.04)">${{inner}}</div>`;
  const para = (t) => `<p style="color:#384150;font-size:0.93rem;line-height:1.6;margin:11px 0">${{t}}</p>`;
  const lbl = (t) => `<div style="font-weight:700;color:#1a1f2e;font-size:0.82rem;margin:0 0 5px">${{t}}</div>`;
  const sel = (opts, onchange) => `<select onchange="${{onchange}}" style="width:100%;padding:9px 12px;border:1px solid #cdd2da;border-radius:6px;background:#fff;color:#1a1f2e;font-size:0.9rem;cursor:pointer">${{opts}}</select>`;
  const th = (t, a) => `<th style="padding:8px 13px;text-align:${{a || 'center'}};border-bottom:2px solid #1a1f2e;background:#fff;color:#1a1f2e;font-size:0.82rem;font-weight:700;white-space:nowrap">${{t}}</th>`;
  const td = (t, a) => `<td style="padding:7px 13px;text-align:${{a || 'center'}};border-bottom:1px solid #edeff2;color:#2b3240;font-size:0.87rem;white-space:nowrap">${{t}}</td>`;
  const mtTable = (rows) => `<table style="border-collapse:collapse"><thead><tr>${{th('Metric','left')}}${{th('Target','left')}}</tr></thead><tbody>${{rows}}</tbody></table>`;
  const hitHead = `<thead><tr>${{th('Targets Hit')}}${{th('Num Games')}}${{th('Team Win Pct')}}${{th('W')}}${{th('L')}}${{th('Avg Margin of Victory')}}${{th('Global Win Pct')}}${{th('Global Avg MOV')}}</tr></thead>`;
  const twoCol = (a, b) => `<div style="display:flex;gap:34px;flex-wrap:wrap;align-items:flex-start;margin-top:8px"><div>${{a}}</div><div style="flex:1;min-width:520px;overflow-x:auto">${{b}}</div></div>`;

  // ── selects ──
  const teamOpts = teamNames.map(t => `<option value="${{t}}" ${{t === currentKeysTeam ? 'selected' : ''}}>${{t}}</option>`).join('');
  const winOpts = Object.keys(windows).map(w => `<option value="${{w}}" ${{w === currentKeysWindow ? 'selected' : ''}}>${{windows[w].label}}</option>`).join('');
  let nOptsHtml = ''; for (let k = 1; k <= maxN; k++) nOptsHtml += `<option value="${{k}}" ${{k === N ? 'selected' : ''}}>${{k}}</option>`;

  // ── narrative phrasing ──
  const __numWord = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight'];
  const __nSeasons = (D.seasons || []).length;
  const __seasonsWord = __numWord[__nSeasons] || __nSeasons;
  const winPhrase = currentKeysWindow !== '5yr'
    ? `in the ${{D.window}} season`
    : (__nSeasons === 1
        ? `in the ${{D.window}} season${{coach ? ' under ' + coach : ''}}`
        : `in the last ${{__seasonsWord}} seasons${{coach ? ' under ' + coach : ''}}`);
  const since = currentKeysWindow === '5yr' ? `since the start of the ${{D.seasons[0]}} season` : 'this season';
  const longs = keys.map(k => k.long || k.label);
  const listEng = __englishList(longs);
  const phrEng = __englishList(keys.map(__kPhrase));
  let hitSent = [];
  for (let h = N; h >= 1; h--) {{
    const r = team[h]; const rec = `${{r.w}}-${{r.l}} (${{__kPn(tPct(r))}}%)`;
    if (h === N) hitSent.push(`when they hit ${{N === 1 ? 'this target' : 'all of these marks'}} they have a record of ${{rec}} and ${{__movPhrase(tMov(r))}}`);
    else hitSent.push(`When they hit ${{h}} out of the ${{N}} goals, they have a record of ${{rec}}`);
  }}
  const r0 = team[0];
  const zero = `However, when they don't meet ${{N === 1 ? 'this target' : 'any of these target values'}}, they have a record of ${{r0.w}}-${{r0.l}} (${{__kPn(tPct(r0))}}%) and ${{__movPhrase(tMov(r0))}}`;
  const narrative = `The key metrics for ${{D.team}} ${{winPhrase}} are ${{listEng}}. They perform at their best when they ${{phrEng}}. In the ${{D.n_games}} games they have played ${{since}}, ${{hitSent[0]}}.${{hitSent.length > 1 ? ' ' + hitSent.slice(1).join('. ') + '.' : ''}} ${{zero}}.`;

  // ── key metrics tables ──
  const mtRows = keys.map(k => `<tr>${{td(k.label, 'left')}}${{td(k.dir + ' ' + k.target, 'left')}}</tr>`).join('');
  let hitRows = '';
  for (let h = 0; h <= N; h++) {{
    const r = team[h]; const gr = gl ? gl[h] : null;
    hitRows += `<tr>${{td(h)}}${{td(r.g)}}${{td(__kPct(tPct(r)))}}${{td(r.w)}}${{td(r.l)}}${{td(__kNum(tMov(r)))}}${{td(gr ? __kPct(gr.win_pct) : '—')}}${{td(gr ? __kNum(gr.avg_mov) : '—')}}</tr>`;
  }}
  const hitTable = `<table style="border-collapse:collapse;width:100%">${{hitHead}}<tbody>${{hitRows}}</tbody></table>`;

  // ── style metrics report ──
  const styleIntro = `In the Style Metrics section, we look at stats that identify a team's style of play or in-game strategy, and look at ones that are particularly interesting for ${{D.team}}, such as pace of play, emphasis on shooting threes, getting to the free throw line, assist percentage, and bench scoring.`;
  let styleHtml = `<div style="font-size:1.2rem;font-weight:600;color:#1a1f2e;margin:6px 0 2px">Style Metrics Report:</div>` + para(styleIntro);
  (D.style || []).forEach((s, i) => {{
    const p = __stylePhrase(s), hr = s.hit, mr = s.miss, gh = s.global_hit || {{}}, gm2 = s.global_miss || {{}};
    const sn = `${{D.team}} has performed better when they ${{p.better}}. In the ${{D.n_games}} games they have played ${{since}}, when ${{p.hit}} they have a record of ${{hr.w}}-${{hr.l}} (${{__kPn(hr.win_pct)}}%) and ${{__movPhrase(hr.avg_mov)}}. When ${{p.miss}} they have a record of ${{mr.w}}-${{mr.l}} (${{__kPn(mr.win_pct)}}%) and ${{__movPhrase(mr.avg_mov)}}.`;
    const smt = mtTable(`<tr>${{td(s.label, 'left')}}${{td(s.dir + ' ' + s.target, 'left')}}</tr>`);
    const sRows = [['0', mr, gm2], ['1', hr, gh]].map(row => {{
      const n = row[0], r = row[1], gr = row[2];
      return `<tr>${{td(n)}}${{td(r.games)}}${{td(__kPct(r.win_pct))}}${{td(r.w)}}${{td(r.l)}}${{td(__kNum(r.avg_mov))}}${{td(gr.win_pct != null ? __kPct(gr.win_pct) : '—')}}${{td(gr.avg_mov != null ? __kNum(gr.avg_mov) : '—')}}</tr>`;
    }}).join('');
    const sht = `<table style="border-collapse:collapse;width:100%">${{hitHead}}<tbody>${{sRows}}</tbody></table>`;
    styleHtml += `<div style="font-size:1.05rem;font-weight:600;color:#1a1f2e;margin:22px 0 2px">Style Metric ${{i + 1}}: ${{__STYLE_LONG[s.label] || s.label}}</div>` + para(sn) + twoCol(smt, sht);
  }});

  host.innerHTML = `
  <div style="background:#f3f4f6;padding:24px 18px 40px;border-radius:8px">
    ${{card(
      `<div style="font-size:1.3rem;font-weight:600;color:#1a1f2e;margin:0 0 2px">Keys to Victory Automated Team Report</div>` +
      para('<b>Instructions:</b> This report identifies certain metrics that have been important predictors of game success for each team. Select a team, then choose what seasons to analyze. You can either choose recent seasons under the current head coach (up to 5 years) or just the current season. Finally, choose a <b style="color:#2f6fed">Number of Targets</b> which determines the number of important metrics that will be identified together for the team. The report will also cover the key stylistic metrics for the team at the bottom.') +
      `<div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:10px"><div style="flex:1;min-width:240px">${{lbl('Team:')}}${{sel(teamOpts, 'keysSetTeam(this.value)')}}</div><div style="flex:2;min-width:320px">${{lbl('Choose Seasons to Analyze:')}}${{sel(winOpts, 'keysSetWindow(this.value)')}}</div></div>`
    )}}
    ${{card(
      `<div style="max-width:240px">${{lbl('Number of Targets:')}}${{sel(nOptsHtml, 'keysSetN(this.value)')}}</div>` +
      `<div style="font-size:1.15rem;font-weight:600;color:#1a1f2e;margin:20px 0 2px">Key Metrics: ${{listEng}}</div>` +
      para(narrative) +
      para("The tables below show the target values for each metric and how successful the team has been based on the number of targets that they hit in each game. Performances by similar teams historically are also included in the 'Global' columns in order to show how important these metrics are to " + D.team + "'s success, compared to other similar teams.") +
      twoCol(mtTable(mtRows), hitTable) +
      `<div style="height:24px"></div>` + styleHtml
    )}}
  </div>`;
  window.scrollTo(0, 0);
}}

function __luF(v, d) {{ return (v == null || isNaN(v)) ? '—' : Number(v).toFixed(d == null ? 1 : d); }}
function __luSign(v) {{ const n = Number(v) || 0; return (n > 0 ? '+' : '') + __luF(n, 1); }}
function __luCol(v, t) {{ const n = Number(v) || 0; return n >= t ? '#1a5c30' : (n <= -t ? '#7b1b1b' : '#555'); }}

// Combo metric columns: [key, label, decimals]. Every metric the lineup data
// supports (the team chart-metric set minus opponent-shooting splits Hudl lacks).
// Lineup metrics grouped into themed tables (no more one giant scroll table).
// [theme name, [[key,label,decimals], ...]]. CTX (Min/Poss/Net/ORtg/DRtg) leads
// every table for context; theme-specific columns follow.
const LU_CTX = [
  ['min','Min',0], ['poss','Poss',0], ['net100','Net/100',1], ['adj_net100','Adj Net/100',1],
  ['ortg','ORtg',1], ['drtg','DRtg',1]
];
const LU_THEMES = [
  ['Overview &amp; Margins', LU_CTX.concat([
    ['adj_ortg','Adj ORtg',1], ['adj_drtg','Adj DRtg',1], ['opp_net','Opp Net',1],
    ['net40','Net/40',1], ['pm','+/-',0], ['ppp','PPP',2], ['pace','Pace',1]
  ])],
  ['Shooting', LU_CTX.concat([
    ['efg','eFG%',1], ['ts','TS%',1], ['fgp','FG%',1],
    ['twop','2P%',1], ['tpp','3P%',1], ['ftp','FT%',1], ['tpar','3PAr',1], ['ftr','FTr',1]
  ])],
  ['Offense &amp; Scoring (per 40)', LU_CTX.concat([
    ['pts40','Pts/40',1], ['fgm40','FGM/40',1], ['fga40','FGA/40',1],
    ['tpm40','3PM/40',1], ['tpa40','3PA/40',1], ['ftm40','FTM/40',1], ['fta40','FTA/40',1],
    ['pip40','PiP/40',1], ['scp40','SCP/40',1], ['pot40','PoT/40',1]
  ])],
  ['Playmaking &amp; Ball Control', LU_CTX.concat([
    ['ast_pct','AST%',1], ['ast40','AST/40',1], ['atov','A:TO',2],
    ['tov','TOV%',1], ['to40','TO/40',1]
  ])],
  ['Rebounding', LU_CTX.concat([
    ['oreb_pct','OREB%',1], ['dreb_pct','DREB%',1], ['oreb40','OREB/40',1],
    ['dreb40','DREB/40',1], ['reb40','REB/40',1], ['reb_margin40','Reb Mgn/40',1]
  ])],
  ['Defense &amp; Activity', LU_CTX.concat([
    ['pa40','PA/40',1], ['stl40','STL/40',1],
    ['blk40','BLK/40',1], ['defl40','DEFL/40',1], ['chg40','CHG/40',2],
    ['opp_oreb40','OReb Allowed/40',1], ['foul40','Foul/40',1]
  ])]
];
// Player on-court table columns: [key, label, decimals, isString]
const LU_PCOLS = [
  ['min','Min',0], ['on_net40','On-Court Net/40',1], ['onoff','On/Off',1],
  ['on_net100','On Net/100',1], ['adj_net100','Adj Net/100',1], ['opp_net','Opp Net',1],
  ['on_ortg','On ORtg',1], ['on_drtg','On DRtg',1], ['apm','Adj +/-',1]
];
let luSize = '5', luPosMode = null, luSortKey = 'min', luSortDir = 'desc';
let luPKey = 'apm', luPDir = 'desc';
let luSubset = 'full';
let luNoGarbage = false;
// game-subset splits (sourced from per-game offensive logs)
const LU_SUBSETS = [['full','Full Season'],['conf','Conference'],['conf_wins','Conference Wins'],
  ['conf_losses','Conference Losses'],['nonconf','Non-Conference'],['nonconf_wins','Non-Conference Wins'],
  ['nonconf_losses','Non-Conference Losses'],['last5','Last 5 Games'],['last10','Last 10 Games'],
  ['home','Home'],['away','Away'],['neutral','Neutral'],['away_neutral','Away + Neutral'],
  ['wins','Wins'],['losses','Losses'],
  ['q1a','Quad 1A'],['q1','Quad 1'],['q2','Quad 2'],['q12','Quad 1+2'],['q3','Quad 3'],['q4','Quad 4']];
// Active dataset for the selected split. If "Remove Garbage Time" is on and a
// garbage-removed version exists for this split, use it; else fall back.
function __luData() {{
  if (typeof MOORPARK_LINEUPS === 'undefined' || !MOORPARK_LINEUPS) return null;
  if (luNoGarbage && MOORPARK_LINEUPS.subsets_ng && MOORPARK_LINEUPS.subsets_ng[luSubset]) {{
    return MOORPARK_LINEUPS.subsets_ng[luSubset];
  }}
  const subs = MOORPARK_LINEUPS.subsets;
  if (subs) return subs[luSubset] || null;
  return luSubset === 'full' ? MOORPARK_LINEUPS : null;
}}
// Does the current split have garbage-removed data available?
function __luHasNG() {{
  return !!(typeof MOORPARK_LINEUPS !== 'undefined' && MOORPARK_LINEUPS &&
            MOORPARK_LINEUPS.subsets_ng && MOORPARK_LINEUPS.subsets_ng[luSubset]);
}}
function luSetSubset(k) {{ luSubset = k; renderLineups(lineupsReturnTeam); }}
function luSetNoGarbage(on) {{ luNoGarbage = !!on; renderLineups(lineupsReturnTeam, true); }}
// positional toggles: [key, button label, table label]
const LU_POS = [['P','PG','Each guard (1 on floor)'],['backcourt','Backcourt','Backcourt (guard trios)'],
  ['guard_fwd','PG+C','Guard + Forward pairs'],['frontcourt','Frontcourt','Frontcourt (forward pairs)'],
  ['C','C','Each forward (1 on floor)']];
function luModeLabel(){{ if(!luPosMode) return luSize; const p=LU_POS.find(x=>x[0]===luPosMode); return p?p[2]:luPosMode; }}
function luModeBtns(){{
  ['2','3','4','5'].forEach(s => {{ const b=document.getElementById('lu-size-'+s);
    if(b){{ const act=(!luPosMode&&s===luSize); b.style.background=act?'#ffd700':'#2a2a40';
      b.style.color=act?'#1a1a2e':'#ffd700'; b.style.fontWeight=act?'700':'600'; }} }});
  LU_POS.forEach(([k]) => {{ const b=document.getElementById('lu-pos-'+k);
    if(b){{ const act=(luPosMode===k); b.style.background=act?'#4fc3f7':'#2a2a40';
      b.style.color=act?'#06243a':'#4fc3f7'; b.style.fontWeight=act?'700':'600'; }} }});
}}
function luSetSize(k) {{ luSize = k; luPosMode = null; luSortKey = 'min'; luSortDir = 'desc'; luTrimFilters(); luRenderPlayerFilters(); renderComboTable(); }}
function luSetPos(m) {{ luPosMode = m; luSortKey = 'min'; luSortDir = 'desc'; luTrimFilters(); luRenderPlayerFilters(); renderComboTable(); }}

// ── On-Court / Off-Court player filters for the combo tables ──
// Select up to (combo size) players who must be ON the floor, and up to that
// many who must be OFF it; the N-man combo tables filter to matching lineups.
let luOnCourt = [], luOffCourt = [], luRoster = [], luOpenPanel = null;
function luComboSize() {{
  if (luPosMode) return ({{ P: 1, backcourt: 3, guard_fwd: 2, frontcourt: 2, C: 1 }})[luPosMode] || 5;
  return parseInt(luSize, 10) || 5;
}}
function luTrimFilters() {{
  const m = luComboSize();
  if (luOnCourt.length > m) luOnCourt = luOnCourt.slice(0, m);
  if (luOffCourt.length > m) luOffCourt = luOffCourt.slice(0, m);
}}
function luTogglePanel(which) {{
  // Track which panel is open so it survives the re-render after a pick.
  luOpenPanel = (luOpenPanel === which) ? null : which;
  luRenderPlayerFilters();
}}
function luTogglePlayer(which, idx) {{
  const name = luRoster[idx]; if (name == null) return;
  const arr = which === 'on' ? luOnCourt : luOffCourt;
  const other = which === 'on' ? luOffCourt : luOnCourt;
  const i = arr.indexOf(name);
  if (i >= 0) arr.splice(i, 1);
  else {{
    if (arr.length >= luComboSize()) return;          // cap at combo size
    const j = other.indexOf(name); if (j >= 0) other.splice(j, 1);  // not in both lists
    arr.push(name);
  }}
  luRenderPlayerFilters(); renderComboTable();
}}
function luClearFilter(which) {{
  if (which === 'on') luOnCourt = []; else luOffCourt = [];
  luRenderPlayerFilters(); renderComboTable();
}}
function luRenderPlayerFilters() {{
  const host = document.getElementById('lu-player-filters'); if (!host) return;
  const full = (typeof MOORPARK_LINEUPS !== 'undefined' && MOORPARK_LINEUPS) ? MOORPARK_LINEUPS : null;
  luRoster = full ? (full.players || []).map(p => p.name).sort((a, b) => a.localeCompare(b)) : [];
  const max = luComboSize();
  const widget = (which, arr, label, color) => {{
    const sel = arr.length ? arr.join(', ') : 'Any';
    const items = luRoster.map((n, i) => {{
      const on = arr.includes(n);
      const dis = !on && arr.length >= max;
      return `<label style="display:flex;align-items:center;gap:7px;padding:4px 11px;cursor:${{dis ? 'not-allowed' : 'pointer'}};opacity:${{dis ? '0.4' : '1'}};color:#eee;font-size:0.82rem;white-space:nowrap"><input type="checkbox" ${{on ? 'checked' : ''}} ${{dis ? 'disabled' : ''}} onchange="luTogglePlayer('${{which}}',${{i}})">${{n}}</label>`;
    }}).join('');
    return `<div style="position:relative;display:inline-block;text-align:left">
      <button onclick="luTogglePanel('${{which}}')" style="background:#2a2a40;border:1px solid ${{color}};color:${{color}};font-weight:600;padding:5px 12px;border-radius:5px;cursor:pointer;font-size:0.82rem;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${{label}}: <span style="color:#fff">${{sel}}</span> &#9662;</button>
      <div id="lu-${{which}}-panel" style="display:${{luOpenPanel === which ? 'block' : 'none'}};position:absolute;z-index:60;top:34px;left:0;background:#161b2e;border:1px solid ${{color}};border-radius:6px;padding:2px 0;max-height:320px;overflow-y:auto;min-width:210px;box-shadow:0 6px 18px rgba(0,0,0,0.55)">
        <div style="padding:5px 11px 6px;border-bottom:1px solid #333;color:#999;font-size:0.72rem">Up to ${{max}} &middot; <span onclick="luClearFilter('${{which}}')" style="color:${{color}};cursor:pointer">clear</span></div>
        ${{items}}
      </div></div>`;
  }};
  const ngAvail = __luHasNG();
  const gbBox = `<label title="${{ngAvail ? 'Subtract logged garbage-time possessions from both ends' : 'No garbage-time possessions logged for this split yet'}}" style="display:inline-flex;align-items:center;gap:7px;cursor:${{ngAvail ? 'pointer' : 'not-allowed'}};color:${{ngAvail ? '#ffd700' : '#666'}};font-weight:600;font-size:0.85rem">`
    + `<input type="checkbox" ${{luNoGarbage ? 'checked' : ''}} ${{ngAvail ? '' : 'disabled'}} onchange="luSetNoGarbage(this.checked)" style="cursor:${{ngAvail ? 'pointer' : 'not-allowed'}}">`
    + `Remove Garbage Time${{ngAvail ? '' : ' <span style=\"color:#666;font-weight:400;font-size:0.78rem\">(none logged for this split)</span>'}}</label>`;
  host.innerHTML = `<div style="display:flex;gap:12px;justify-content:center;align-items:flex-start;flex-wrap:wrap">`
    + widget('on', luOnCourt, 'On Court', '#6ee7a0')
    + widget('off', luOffCourt, 'Off Court', '#fb923c')
    + `</div><div style="margin-top:9px;text-align:center">${{gbBox}}</div>`;
}}
function luSortCombo(key) {{
  if (luSortKey === key) luSortDir = luSortDir === 'desc' ? 'asc' : 'desc';
  else {{ luSortKey = key; luSortDir = key === 'players' ? 'asc' : 'desc'; }}
  renderComboTable();
}}
function renderComboTable() {{
  const D = __luData();
  luModeBtns();
  let rows = (luPosMode ? (((D || {{}}).pos_sets || {{}})[luPosMode] || [])
                        : (((D || {{}}).combos || {{}})[luSize] || [])).slice();
  const hasFilter = luOnCourt.length || luOffCourt.length;
  if (hasFilter) {{
    rows = rows.filter(r => {{
      const set = new Set(r.players);
      for (let p of luOnCourt) if (!set.has(p)) return false;
      for (let p of luOffCourt) if (set.has(p)) return false;
      return true;
    }});
  }}
  if (!rows.length) {{
    document.getElementById('lu-combo-table').innerHTML =
      `<div style="color:#777;padding:20px;text-align:center">No ${{luModeLabel()}} lineups ${{hasFilter ? 'match the selected players' : 'meet the minutes floor'}}.</div>`;
    return;
  }}
  rows.sort((a, b) => {{
    if (luSortKey === 'players') {{
      const an = a.players.join(' '), bn = b.players.join(' ');
      return luSortDir === 'asc' ? an.localeCompare(bn) : bn.localeCompare(an);
    }}
    const av = Number(a[luSortKey]) || 0, bv = Number(b[luSortKey]) || 0;
    return luSortDir === 'desc' ? (bv - av) : (av - bv);
  }});
  const lh = 'background:#1a1a2e;color:#fff;padding:6px 7px;text-align:right;font-size:0.7rem;white-space:nowrap;cursor:pointer';
  const td = 'padding:5px 7px;text-align:right;border-bottom:1px solid #e8e8e8;font-size:0.78rem;color:#000';
  const stickH = 'position:sticky;left:0;z-index:3;background:#1a1a2e;text-align:left;min-width:210px';
  const stickD = 'position:sticky;left:0;z-index:1;background:#fff;text-align:left;font-size:0.72rem;min-width:210px';
  const arrow = (k) => luSortKey === k ? (luSortDir === 'desc' ? ' ▼' : ' ▲') : '';
  // signed/colored metrics: key -> threshold for green/red shading
  const COLORED = {{ net100: 10, adj_net100: 10, net40: 5, pm: 5, reb_margin40: 3, opp_net: 5 }};
  const renderTbl = (cols) => {{
    const head = `<th style="${{lh}};${{stickH}}" onclick="luSortCombo('players')">Lineup (${{luModeLabel()}})</th>` +
      cols.map(c => `<th style="${{lh}}${{COLORED[c[0]] ? ';background:#2a3a5c' : ''}}" onclick="luSortCombo('${{c[0]}}')">${{c[1]}}${{arrow(c[0])}}</th>`).join('');
    const body = rows.map((r, i) => `<tr><td style="${{td}};${{stickD}};background:${{i % 2 === 0 ? '#d9d9d9' : '#fff'}}">${{r.players.join(' · ')}}</td>` +
      cols.map(c => {{
        const v = r[c[0]];
        const txt = (v == null || isNaN(v)) ? '—' : Number(v).toFixed(c[2]);
        const thr = COLORED[c[0]];
        const col = thr ? __luCol(v, thr) : '#000';
        return `<td style="${{td}};color:${{col}}${{thr ? ';font-weight:700' : ''}}">${{(thr && v > 0 ? '+' : '') + txt}}</td>`;
      }}).join('') + `</tr>`).join('');
    return `<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%"><thead><tr>${{head}}</tr></thead><tbody>${{body}}</tbody></table></div>`;
  }};
  // ── Top Lineups: fixed ranking by Net/100 (best units at a glance) ──
  const TOP_COLS = [['net100','Net/100',1],['adj_net100','Adj Net/100',1],['opp_net','Opp Net',1],
    ['min','Min',0],['poss','Poss',0],['ortg','ORtg',1],['drtg','DRtg',1],
    ['efg','eFG%',1],['ts','TS%',1],['oreb_pct','OREB%',1],['dreb_pct','DREB%',1],['tov','TOV%',1]];
  const top = rows.slice().sort((a, b) => (Number(b.net100) || 0) - (Number(a.net100) || 0)).slice(0, 10);
  const topHead = `<th style="${{lh}};text-align:center;min-width:28px">#</th><th style="${{lh}};${{stickH}}">Lineup (${{luModeLabel()}})</th>` +
    TOP_COLS.map(c => `<th style="${{lh}}${{COLORED[c[0]] ? ';background:#2a3a5c' : ''}}">${{c[1]}}</th>`).join('');
  const topBody = top.map((r, i) => `<tr><td style="${{td}};text-align:center;font-weight:700;color:#1a1a2e;background:${{i % 2 === 0 ? '#d9d9d9' : '#fff'}}">${{i + 1}}</td><td style="${{td}};${{stickD}};background:${{i % 2 === 0 ? '#d9d9d9' : '#fff'}}">${{r.players.join(' · ')}}</td>` +
    TOP_COLS.map(c => {{
      const v = r[c[0]];
      const txt = (v == null || isNaN(v)) ? '—' : Number(v).toFixed(c[2]);
      const thr = COLORED[c[0]];
      const col = thr ? __luCol(v, thr) : '#000';
      return `<td style="${{td}};color:${{col}}${{thr ? ';font-weight:700' : ''}}">${{(thr && v > 0 ? '+' : '') + txt}}</td>`;
    }}).join('') + `</tr>`).join('');
  const topTable = `<h4 style="color:#1a1a2e;font-size:1.05rem;margin:6px 0 4px;border-bottom:2px solid #ffd700;padding-bottom:3px">Top ${{luPosMode ? luModeLabel() : luSize + '-Man'}} Lineups <span style="color:#777;font-size:0.72rem;font-weight:400">ranked by Net/100 · weigh by Min/Poss</span></h4>` +
    `<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%"><thead><tr>${{topHead}}</tr></thead><tbody>${{topBody}}</tbody></table></div>`;

  document.getElementById('lu-combo-table').innerHTML = topTable + LU_THEMES.map(t =>
    `<h4 style="color:#1a1a2e;font-size:0.98rem;margin:20px 0 6px;border-bottom:1px solid #ffd700;padding-bottom:3px">${{t[0]}}</h4>` + renderTbl(t[1])
  ).join('');
}}
// ── Player On/Off cards (CBB-Analytics style: Core / Box / Offense / Defense,
//    each On · Off · Diff). Populated from p.onoff_adj; metrics we don't log yet
//    (box per-40, steals/blocks, pace) show "--" as placeholders. ──
let luPlayerCount = '6';
function luSetPlayerCount(v) {{ luPlayerCount = v; renderPlayerTable(); }}
// [label, path-in-onoff_adj, decimals, goodWhenHigher, suffix]; null path => "--"
const OO_CORE = [['Net Rating','eff.net',1,true,''],['Offensive Rating','eff.ortg',1,true,''],
  ['Defensive Rating','eff.drtg',1,false,''],['Pace','rate.pace',1,null,''],
  ['Effective FG%','off_ff.efg',1,true,'%'],['Off Rebound %','off_ff.oreb',1,true,'%'],
  ['Turnover %','off_ff.tov',1,false,'%'],['FT Attempt Rate','off_ff.ftr',1,true,'%']];
const OO_BOX = [['Points / 40','box.pts',1,true,''],['Assists / 40','box.ast',1,true,''],
  ['ORebs / 40','box.oreb',1,true,''],['DRebs / 40','box.dreb',1,true,''],
  ['Steals / 40','box.stl',1,true,''],['Blocks / 40','box.blk',1,true,''],
  ['Turnovers / 40','box.to',1,false,''],['PFs / 40','box.foul',1,false,'']];
const OO_OFF = [['Offensive Rating','eff.ortg',1,true,''],['True Shooting %','ts',1,true,'%'],
  ['3-Point Att Rate','rate.tpar',1,null,'%'],['FT Attempt Rate','off_ff.ftr',1,true,'%'],
  ['Assist %','rate.asp',1,true,'%'],['Turnover %','off_ff.tov',1,false,'%'],
  ['Ast/Tov Ratio','rate.ato',2,true,''],['Deflections / 40','defl40',1,true,'']];
const OO_DEF = [['Defensive Rating','eff.drtg',1,false,''],['Def Rebound %','def_reb',1,true,'%'],
  ['Steal %','rate.stl',1,true,'%'],['Block %','rate.blk',1,true,'%'],
  ['Hakeem %','hakeem',1,true,'%'],['PF Efficiency','pf_eff',2,true,''],
  ['Steals / PF','stl_pf',2,true,''],['Blocks / PF','blk_pf',2,true,'']];
function __ooGet(oo, path) {{ if (!path || !oo) return null; const a = path.split('.'); if (a.length === 1) return oo[a[0]] || null; const o = oo[a[0]]; return o ? o[a[1]] : null; }}
function __ooTbl(title, defs, oo) {{
  const hh = 'background:#1a3a6e;color:#fff;padding:5px 8px;font-size:0.7rem;white-space:nowrap';
  const td = 'padding:4px 8px;border-bottom:1px solid #eee;font-size:0.77rem;text-align:right;color:#000';
  const fmt = (v, d, s) => (v == null || isNaN(v)) ? '--' : (Number(v).toFixed(d) + (s || ''));
  const rows = defs.map(d => {{
    const cell = __ooGet(oo, d[1]); const dec = d[2] == null ? 1 : d[2]; const suf = d[4] || '';
    let on = '--', off = '--', diff = '--', dc = '#999';
    if (cell) {{
      on = fmt(cell.on, dec, suf); off = fmt(cell.off, dec, suf);
      const dv = cell.diff; diff = (dv > 0 ? '+' : '') + Number(dv).toFixed(dec) + suf;
      const good = (d[3] == null) ? null : (d[3] ? dv > 0 : dv < 0);
      dc = (dv === 0 || good == null) ? '#777' : (good ? '#1a7a3a' : '#b3261e');
    }}
    return `<tr><td style="${{td}};text-align:left;color:#333">${{d[0]}}</td>` +
      `<td style="${{td}}">${{on}}</td><td style="${{td}};color:#888">${{off}}</td>` +
      `<td style="${{td}};color:${{dc}};font-weight:700">${{diff}}</td></tr>`;
  }}).join('');
  return `<div style="flex:1;min-width:200px"><table style="border-collapse:collapse;width:100%">` +
    `<thead><tr><th style="${{hh}};text-align:left">${{title}}</th><th style="${{hh}};text-align:right">On</th>` +
    `<th style="${{hh}};text-align:right">Off</th><th style="${{hh}};text-align:right">Diff</th></tr></thead><tbody>${{rows}}</tbody></table></div>`;
}}
function renderPlayerTable() {{
  const D = __luData();
  const tg = ((D || {{}}).team_totals || {{}}).n_games || 0;
  const avail = tg * 40;  // available minutes per roster spot
  const mpct = (p) => avail ? (Number(p.min) || 0) / avail * 100 : 0;  // %Min
  const rows = ((D || {{}}).players || []).slice().filter(p => p.onoff_adj)
    .sort((a, b) => mpct(b) - mpct(a));
  const host = document.getElementById('lu-player-table');
  if (!rows.length) {{
    host.innerHTML = `<div style="color:#777;text-align:center;padding:26px;font-size:0.85rem">On/off splits are computed from the logged games (Full Season only) — switch the split back to <b>Full Season</b> to see player on-court impact.</div>`;
    return;
  }}
  const n = luPlayerCount === 'all' ? rows.length : Math.min(parseInt(luPlayerCount, 10), rows.length);
  const opts = ['6','7','8','9','10','11','12','all'].map(v =>
    `<option value="${{v}}" ${{luPlayerCount === v ? 'selected' : ''}}>${{v === 'all' ? 'All Players' : 'Top ' + v}}</option>`).join('');
  const sel = `<select onchange="luSetPlayerCount(this.value)" style="background:#2a2a40;border:1px solid #ffd700;color:#ffd700;font-weight:700;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:0.85rem">${{opts}}</select>`;
  let html = `<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 8px">` +
    `<div>${{sel}} <span style="color:#888;font-size:0.72rem">ranked by % of minutes</span></div>` +
    `<div style="color:#777;font-size:0.7rem;max-width:580px;text-align:right">Modeled on CBB Analytics. Most stats use <b>all logged Hudl games</b>; Steal%, Block% &amp; Hakeem% show <b>--</b> until every game's defense is logged. Diff = on minus off; green = team better with player on.</div></div>`;
  for (const p of rows.slice(0, n)) {{
    const oo = p.onoff_adj;
    const sub = `${{mpct(p).toFixed(0)}}% min · ${{oo.games || 0}} games · ${{oo.off_poss_on || 0}} off poss${{oo.def_complete ? (' / ' + (oo.def_poss_on || 0) + ' def poss') : ''}}`;
    html += `<div style="background:#fff;border:1px solid #ccc;border-radius:8px;padding:11px 14px;margin-bottom:13px">` +
      `<div style="font-size:1.08rem;font-weight:700;color:#1a1a2e;border-bottom:2px solid #ffd700;padding-bottom:3px;margin-bottom:8px">${{p.name}} <span style="color:#888;font-size:0.72rem;font-weight:400">${{sub}}</span></div>` +
      `<div style="display:flex;gap:14px;flex-wrap:wrap">${{__ooTbl('Core Stats', OO_CORE, oo)}}${{__ooTbl('Box Stats', OO_BOX, oo)}}${{__ooTbl('Offense', OO_OFF, oo)}}${{__ooTbl('Defense', OO_DEF, oo)}}</div></div>`;
  }}
  host.innerHTML = html;
}}

function renderLineups(teamName, keepView) {{
  const FULL = (typeof MOORPARK_LINEUPS !== 'undefined') ? MOORPARK_LINEUPS : null;
  if (!FULL || FULL.team !== teamName) {{ closeLineups(); return; }}
  const sec = (txt) => `<h3 style="color:#ffd700;font-size:1.05rem;margin:22px 0 8px;border-bottom:2px solid #ffd700;padding-bottom:3px">${{txt}}</h3>`;
  const sizeBtn = (k) => `<button id="lu-size-${{k}}" onclick="luSetSize('${{k}}')" style="background:${{k === '5' ? '#ffd700' : '#2a2a40'}};border:1px solid #ffd700;color:${{k === '5' ? '#1a1a2e' : '#ffd700'}};font-weight:${{k === '5' ? '700' : '600'}};padding:5px 16px;border-radius:5px;cursor:pointer;font-size:0.85rem">${{k}}-Man</button>`;
  const posBtn = (k, lab) => `<button id="lu-pos-${{k}}" onclick="luSetPos('${{k}}')" style="background:#2a2a40;border:1px solid #4fc3f7;color:#4fc3f7;font-weight:600;padding:5px 14px;border-radius:5px;cursor:pointer;font-size:0.85rem">${{lab}}</button>`;
  const subs = FULL.subsets || null;
  const subSel = subs ? (`<select onchange="luSetSubset(this.value)" style="background:#2a2a40;border:1px solid #ffd700;color:#ffd700;font-weight:700;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:0.9rem">` +
    LU_SUBSETS.map(s => {{ const sd = subs[s[0]]; const ng = sd ? (sd.team_totals.n_games || 0) : 0;
      return `<option value="${{s[0]}}" ${{luSubset === s[0] ? 'selected' : ''}} ${{sd ? '' : 'disabled'}}>${{s[1]}}${{sd ? ` (${{ng}}g)` : ' (0g)'}}</option>`; }}).join('') + `</select>`) : '';
  const D = subs ? __luData() : FULL;
  if (!D) {{
    document.getElementById('lineups-content').innerHTML = `
      <div style="background:#1a1a2e;border-radius:8px;padding:16px 20px;margin-bottom:8px;text-align:center">
        <h2 style="color:#ffd700;font-size:1.6rem;margin:4px 0">${{teamName}} — Lineups &amp; On/Off</h2>
        <div style="color:#ccc;font-size:0.9rem;margin-top:10px">Split: ${{subSel}}</div>
      </div>
      <div style="color:#999;text-align:center;padding:44px 0;font-size:0.95rem">No games logged for this split yet.</div>`;
    document.getElementById('team-detail-view').style.display = 'none';
    document.getElementById('lineups-view').style.display = 'block';
    if (!keepView) window.scrollTo(0, 0);
    return;
  }}
  const tt = D.team_totals;

  document.getElementById('lineups-content').innerHTML = `
    <div style="background:#1a1a2e;border-radius:8px;padding:16px 20px;margin-bottom:8px;text-align:center">
      <h2 style="color:#ffd700;font-size:1.6rem;margin:4px 0">${{teamName}} — Lineups &amp; On/Off</h2>
      <div style="color:#ccc;font-size:0.9rem">On-court net ${{__luSign(tt.net100)}}/100 &nbsp;·&nbsp; ${{tt.lineups_tracked}} units &nbsp;·&nbsp; ${{tt.n_games || 0}} game${{tt.n_games === 1 ? '' : 's'}}${{(luNoGarbage && __luHasNG()) ? ' &nbsp;·&nbsp; <span style="color:#ffd700">garbage removed</span>' : ''}}</div>
      ${{subSel ? `<div style="margin-top:10px">Split: ${{subSel}}</div>` : ''}}
    </div>
    <div style="color:#999;font-size:0.76rem;margin:0 0 10px;text-align:center;max-width:900px;margin-left:auto;margin-right:auto">
      Minutes ${{tt.min_reconciled ? 'are <b>reconciled to official CCCAA</b> box-score totals (Hudl over-counts).' : 'are raw Hudl.'}}
      ${{D.opp_adjusted ? '<b>Adj</b> columns are <b>opponent-adjusted</b> (KenPom-style: each stint weighted by the opponent\\'s season strength; Adj Net = raw Net + opponent Net). <b>Opp Net</b> = avg strength of opponents that unit faced.' : 'Ratings are <b>raw (not opponent-adjusted)</b>.'}}
      Small-minute rows are noisy, so weigh by Min. N-man combos are aggregated from the 5-man units. <b>Click any column header to sort.</b>
    </div>
    ${{sec('Player On-Court Impact')}}
    <div id="lu-player-table" style="background:#fff;border-radius:8px;border:1px solid #ccc;overflow-x:auto;padding:4px"></div>
    ${{sec('Lineup Combinations — Every Metric')}}
    <div style="display:flex;gap:8px;justify-content:center;margin:-2px 0 6px;flex-wrap:wrap">${{['2','3','4','5'].map(sizeBtn).join('')}}</div>
    <div style="display:flex;gap:8px;justify-content:center;margin:0 0 10px;flex-wrap:wrap">${{LU_POS.map(p => posBtn(p[0], p[1])).join('')}}</div>
    <div style="color:#999;font-size:0.72rem;text-align:center;margin-bottom:8px">N-man: lineup combos · Positional: P=guards on floor · Backcourt=guard trios · PG+C=guard+forward · Frontcourt=forward pairs · C=forwards on floor · click any header to sort</div>
    <div id="lu-player-filters" style="display:flex;gap:8px;justify-content:center;align-items:flex-start;margin:0 0 12px;flex-wrap:wrap"></div>
    <div id="lu-combo-table" style="background:#fff;border-radius:8px;border:1px solid #ccc;overflow-x:auto;padding:4px"></div>`;
  document.getElementById('team-detail-view').style.display = 'none';
  document.getElementById('lineups-view').style.display = 'block';
  if (!keepView) {{
    luSize = '5'; luPosMode = null; luSortKey = 'min'; luSortDir = 'desc'; luPKey = 'apm'; luPDir = 'desc';
    luOpenPanel = null;
  }}
  luTrimFilters();
  luRenderPlayerFilters();
  renderPlayerTable();
  renderComboTable();
  if (!keepView) window.scrollTo(0, 0);
}}

/* ═══ Player Profile ═══════════════════════════════════════════════════
   Opened by clicking any player name. Header + trending bar (last 5/10)
   + KenPom-style tier table (Season / Conference / Tier A / Tier B /
   A+B / Untiered) + game log. Tier and Conference lines are aggregated
   from per-game box data and run through the same formulas the season
   pipeline uses (Oliver ORtg/DRtg, usage, rates), so a tier line is
   methodologically identical to a season line. */
let playerReturnViewId = null;
let playerProfileCtx = null;
let playerTrendN = 5;
const __PP_VIEWS = ['individual-view', 'team-view', 'charts-view', 'universe-view',
  'team-detail-view', 'storylines-view', 'fanmatch-view', 'gameplan-view',
  'minmatrix-view', 'teamstats-view', 'lineups-view', 'keys-view', 'team-defense-view', 'team-basic-view',
  'team-basic-defense-view', 'team-adv-offense-view', 'team-adv-defense-view'];

function __ppEsc(s) {{
  return String(s || '').replace(/\\\\/g, '\\\\\\\\').replace(/'/g, "\\\\'").replace(/"/g, '&quot;');
}}

function playerLink(name, school, style) {{
  return '<a href="#" onclick="showPlayerProfile(\\'' + __ppEsc(name) + '\\',\\'' + __ppEsc(school) + '\\');return false" style="' + (style || 'color:inherit;text-decoration:none') + '">' + name + '</a>';
}}

function showPlayerProfile(name, school) {{
  playerProfileCtx = {{ name: name, school: school }};
  const visible = __PP_VIEWS.find(id => {{
    const el = document.getElementById(id);
    return el && el.style.display !== 'none';
  }});
  if (visible) playerReturnViewId = visible;
  closeBoxScore();
  ensureRosters(activeSeason, () => ensureBoxes(activeSeason, () => renderPlayerProfile()));
}}

function closePlayerProfile() {{
  document.getElementById('player-view').style.display = 'none';
  const back = playerReturnViewId || 'individual-view';
  const el = document.getElementById(back);
  if (el) el.style.display = 'block';
  // One player, one season: the season toggle returns with the main views
  document.getElementById('season-toggle').style.display =
    (back === 'individual-view' || back === 'team-view') ? 'flex' : 'none';
}}

function ppSetTrend(n) {{
  playerTrendN = n;
  renderPlayerProfile();
}}

/* ── aggregate engine: sum box totals over a game subset ── */
function __ppSum(rows) {{
  const out = {{ MIN: 0, FGM: 0, FGA: 0, TPM: 0, TPA: 0, FTM: 0, FTA: 0,
                 OREB: 0, DREB: 0, AST: 0, STL: 0, BLK: 0, TO: 0, PF: 0, PTS: 0 }};
  for (const r of rows) {{
    out.MIN += r.min || 0; out.FGM += r.fgm || 0; out.FGA += r.fga || 0;
    out.TPM += r.tpm || 0; out.TPA += r.tpa || 0; out.FTM += r.ftm || 0;
    out.FTA += r.fta || 0; out.OREB += r.or || 0; out.DREB += r.dr || 0;
    out.AST += r.ast || 0; out.STL += r.stl || 0; out.BLK += r.blk || 0;
    out.TO += r.to || 0; out.PF += r.pf || 0; out.PTS += r.pts || 0;
  }}
  return out;
}}

/* Oliver total possessions / ORtg / DRtg — faithful ports of
   update_advanced_analytics.py so subset lines match pipeline methodology. */
function __ppTotPoss(P, T, O) {{
  if (T.FGM === 0) return 0;
  const ftPct = P.FTA > 0 ? P.FTM / P.FTA : 0;
  const teamFtPct = T.FTA > 0 ? T.FTM / T.FTA : 0;
  const minFrac = P.MIN / (T.MIN / 5);
  const qastD2 = T.FGM * minFrac - P.FGM;
  const qast = Math.max(0, Math.min(1,
    minFrac * 1.14 * (T.AST - P.AST) / T.FGM +
    (qastD2 > 0 ? ((T.AST * minFrac - P.AST) / qastD2) * (1 - minFrac) : 0)));
  const fgEff = P.FGA > 0 ? (P.PTS - P.FTM) / (2 * P.FGA) : 0;
  const fgPart = P.FGM * (1 - 0.5 * fgEff * qast);
  const astDen = 2 * (T.FGA - P.FGA);
  const astPart = astDen > 0 ? 0.5 * (((T.PTS - T.FTM) - (P.PTS - P.FTM)) / astDen) * P.AST : 0;
  const ftPart = P.FTA > 0 ? (1 - Math.pow(1 - ftPct, 2)) * 0.475 * P.FTA : 0;
  const orbDen = T.OREB + O.DREB;
  const teamOrbPct = orbDen > 0 ? T.OREB / orbDen : 0;
  const teamScPoss = T.FGM + (1 - Math.pow(1 - teamFtPct, 2)) * T.FTA * 0.475;
  if (teamScPoss <= 0) return 0;
  const playDen = T.FGA + T.FTA * 0.475 + T.TO;
  const teamPlayPct = playDen > 0 ? teamScPoss / playDen : 0;
  const wNum = (1 - teamOrbPct) * teamPlayPct;
  const wDen = wNum + teamOrbPct * (1 - teamPlayPct);
  const orbWt = wDen > 0 ? wNum / wDen : 0;
  const orbPart = P.OREB * orbWt * teamPlayPct;
  const scFactor = 1 - (T.OREB / teamScPoss) * orbWt * teamPlayPct;
  const scPoss = (fgPart + astPart + ftPart) * scFactor + orbPart;
  const fgx = (P.FGA - P.FGM) * (1 - 1.07 * teamOrbPct);
  const ftx = P.FTA > 0 ? Math.pow(1 - ftPct, 2) * 0.475 * P.FTA : 0;
  return scPoss + fgx + ftx + P.TO;
}}

function __ppOrtg(P, T, O) {{
  if (T.MIN <= 0 || P.MIN <= 0 || (P.FGA === 0 && P.FTA === 0) || T.FGM === 0) return null;
  const ftPct = P.FTA > 0 ? P.FTM / P.FTA : 0;
  const teamFtPct = T.FTA > 0 ? T.FTM / T.FTA : 0;
  const minFrac = P.MIN / (T.MIN / 5);
  const qastD2 = T.FGM * minFrac - P.FGM;
  const qast = Math.max(0, Math.min(1,
    minFrac * 1.14 * (T.AST - P.AST) / T.FGM +
    (qastD2 > 0 ? ((T.AST * minFrac - P.AST) / qastD2) * (1 - minFrac) : 0)));
  const fgEff = P.FGA > 0 ? (P.PTS - P.FTM) / (2 * P.FGA) : 0;
  const fgPart = P.FGM * (1 - 0.5 * fgEff * qast);
  const astDen = 2 * (T.FGA - P.FGA);
  const astShare = astDen > 0 ? ((T.PTS - T.FTM) - (P.PTS - P.FTM)) / astDen : 0;
  const astPart = 0.5 * astShare * P.AST;
  const ftPart = P.FTA > 0 ? (1 - Math.pow(1 - ftPct, 2)) * 0.475 * P.FTA : 0;
  const orbDen = T.OREB + O.DREB;
  const teamOrbPct = orbDen > 0 ? T.OREB / orbDen : 0;
  const teamScPoss = T.FGM + (1 - Math.pow(1 - teamFtPct, 2)) * T.FTA * 0.475;
  if (teamScPoss <= 0) return null;
  const playDen = T.FGA + T.FTA * 0.475 + T.TO;
  const teamPlayPct = playDen > 0 ? teamScPoss / playDen : 0;
  const wNum = (1 - teamOrbPct) * teamPlayPct;
  const wDen = wNum + teamOrbPct * (1 - teamPlayPct);
  const orbWt = wDen > 0 ? wNum / wDen : 0;
  const orbPart = P.OREB * orbWt * teamPlayPct;
  const scFactor = 1 - (T.OREB / teamScPoss) * orbWt * teamPlayPct;
  const scPoss = (fgPart + astPart + ftPart) * scFactor + orbPart;
  const fgx = (P.FGA - P.FGM) * (1 - 1.07 * teamOrbPct);
  const ftx = P.FTA > 0 ? Math.pow(1 - ftPct, 2) * 0.475 * P.FTA : 0;
  const totPoss = scPoss + fgx + ftx + P.TO;
  if (totPoss <= 0) return null;
  const pprodFg = P.FGA > 0 ? 2 * (P.FGM + 0.5 * P.TPM) * (1 - 0.5 * fgEff * qast) : 0;
  const teamNonFg = T.FGM - P.FGM;
  const pprodAstFactor = teamNonFg > 0 ? (teamNonFg + 0.5 * (T.TPM - P.TPM)) / teamNonFg : 1;
  const pprodAst = 2 * pprodAstFactor * 0.5 * astShare * P.AST;
  const pprodOrbDen = T.FGM + (1 - Math.pow(1 - teamFtPct, 2)) * 0.475 * T.FTA;
  const pprodOrb = pprodOrbDen > 0 ? P.OREB * orbWt * teamPlayPct * (T.PTS / pprodOrbDen) : 0;
  const pprod = (pprodFg + pprodAst + P.FTM) * scFactor + pprodOrb;
  return Math.round(1000 * pprod / totPoss) / 10;
}}

function __ppDrtg(P, T, O) {{
  if (T.MIN <= 0 || P.MIN <= 0 || O.FGA === 0) return null;
  const teamPoss = T.FGA + 0.475 * T.FTA - T.OREB + T.TO;
  if (teamPoss <= 0) return null;
  const teamMin5 = T.MIN / 5;
  const oppFtPct = O.FTA > 0 ? O.FTM / O.FTA : 0;
  const dfgPct = O.FGM / O.FGA;
  const dorDen = O.OREB + T.DREB;
  const dorPct = dorDen > 0 ? O.OREB / dorDen : 0;
  const fmwtDen = dfgPct * (1 - dorPct) + (1 - dfgPct) * dorPct;
  const fmwt = fmwtDen > 0 ? dfgPct * (1 - dorPct) / fmwtDen : 0;
  const stops1 = P.STL + P.BLK * fmwt * (1 - 1.07 * dorPct) + P.DREB * (1 - fmwt);
  const rateMiss = ((O.FGA - O.FGM - T.BLK) / (5 * teamMin5)) * fmwt * (1 - 1.07 * dorPct);
  const rateTo = (O.TO - T.STL) / (5 * teamMin5);
  const stops2 = (rateMiss + rateTo) * P.MIN +
    (T.PF > 0 && O.FTA > 0 ? (P.PF / T.PF) * 0.475 * O.FTA * Math.pow(1 - oppFtPct, 2) : 0);
  const stopPct = (stops1 + stops2) * 5 * teamMin5 / (teamPoss * P.MIN);
  const teamDrtg = 100 * O.PTS / teamPoss;
  const oppScPoss = O.FGM + (1 - Math.pow(1 - oppFtPct, 2)) * O.FTA * 0.475;
  const dPtsPerSc = oppScPoss > 0 ? O.PTS / oppScPoss : 0;
  return Math.round(10 * (teamDrtg + 0.2 * (100 * dPtsPerSc * (1 - stopPct) - teamDrtg))) / 10;
}}

function __ppAdvLine(P, T, O, teamGames) {{
  const r = {{}};
  const minFrac100 = T.MIN > 0 && P.MIN > 0 ? P.MIN / (T.MIN / 5) / 100 : 0;
  const teamPoss = T.FGA + 0.475 * T.FTA - T.OREB + T.TO;
  r.gp = null; // filled by caller
  r.min_pct = teamGames > 0 ? Math.round(1000 * P.MIN / (40 * teamGames)) / 10 : null;
  r.ind_ortg = __ppOrtg(P, T, O);
  r.usage_pct = (minFrac100 > 0 && teamPoss > 0) ? Math.round(10 * __ppTotPoss(P, T, O) / (minFrac100 * teamPoss)) / 10 : null;
  r.shot_pct = (minFrac100 > 0 && T.FGA > 0) ? Math.round(10 * P.FGA / (minFrac100 * T.FGA)) / 10 : null;
  r.efg_pct = P.FGA > 0 ? Math.round(1000 * (P.FGM + 0.5 * P.TPM) / P.FGA) / 10 : null;
  const tsDen = 2 * (P.FGA + 0.475 * P.FTA);
  r.ts_pct = tsDen > 0 ? Math.round(1000 * P.PTS / tsDen) / 10 : null;
  r.oreb_pct = (minFrac100 > 0 && (T.OREB + O.DREB) > 0) ? Math.round(10 * P.OREB / (minFrac100 * (T.OREB + O.DREB))) / 10 : null;
  r.dreb_pct = (minFrac100 > 0 && (T.DREB + O.OREB) > 0) ? Math.round(10 * P.DREB / (minFrac100 * (T.DREB + O.OREB))) / 10 : null;
  const arDen = (P.MIN / ((T.MIN || 1) / 5)) * T.FGM - P.FGM;
  r.ast_rate = (T.MIN > 0 && P.MIN > 0 && arDen > 0) ? Math.round(1000 * P.AST / arDen) / 10 : null;
  const tovDen = (P.FGA - P.OREB) + P.TO + 0.475 * P.FTA;
  r.tov_pct = tovDen > 0 ? Math.round(1000 * P.TO / tovDen) / 10 : null;
  r.blk_pct = (minFrac100 > 0 && (O.FGA - O.TPA) > 0) ? Math.round(10 * P.BLK / (minFrac100 * (O.FGA - O.TPA))) / 10 : null;
  r.stl_pct = (minFrac100 > 0 && teamPoss > 0) ? Math.round(10 * P.STL / (minFrac100 * teamPoss)) / 10 : null;
  r.fc_per_40 = P.MIN > 0 ? Math.round(10 * P.PF * 40 / P.MIN) / 10 : null;
  r.fd_per_40 = (T.MIN > 0 && P.MIN > 0) ? Math.round(10 * (P.FTA / 1.8 + Math.max(0, O.PF * 0.837 - T.FTA / 1.8) * (P.MIN / (T.MIN / 5))) * 40 / P.MIN) / 10 : null;
  r.ft_rate = P.FGA > 0 ? Math.round(1000 * P.FTA / P.FGA) / 10 : null;
  r.ftm = P.FTM; r.fta = P.FTA; r.ftp = P.FTA > 0 ? Math.round(1000 * P.FTM / P.FTA) / 10 : null;
  r.twom = P.FGM - P.TPM; r.twoa = P.FGA - P.TPA;
  r.twop = r.twoa > 0 ? Math.round(1000 * r.twom / r.twoa) / 10 : null;
  r.tpm = P.TPM; r.tpa = P.TPA;
  r.tpp = P.TPA > 0 ? Math.round(1000 * P.TPM / P.TPA) / 10 : null;
  return r;
}}

/* ── collect the player's games with tier + full game context ── */
function __ppGames(name, school) {{
  const t = activeFullTeamData().find(d => d.team === school);
  if (!t) return [];
  const boxes = GAME_BOXES[activeSeason] || {{}};
  const netRtgRanks = {{}};
  activeTeamData.filter(d => d.ortg > 0).sort((a, b) => b.net_rtg - a.net_rtg)
    .forEach((d, i) => {{ netRtgRanks[d.team] = i + 1; }});
  const games = [];
  (t.game_ratings || []).forEach(gr => {{
    if (gr.result !== 'W' && gr.result !== 'L') return;
    const opp = gr.canonical_opponent || gr.opponent || '';
    const g = boxes[__boxKey(gr.date, school, opp)];
    if (!g) return;
    const tKey = Object.keys(g.t).find(k => __boxNorm(k) === __boxNorm(school));
    const oKey = Object.keys(g.t).find(k => __boxNorm(k) !== __boxNorm(school));
    if (!tKey || !oKey) return;
    const me = g.t[tKey].find(r => r.n === name);
    if (!me) return;
    // Tier: same rule as the schedule table
    let tier = '';
    const oppRank = netRtgRanks[opp];
    if (typeof oppRank === 'number') {{
      const adj = gr.location === 'Away' ? oppRank * 50 / 90
                : gr.location === 'Home' ? oppRank * 50 / 20 : oppRank;
      tier = adj <= 15 ? 'A' : adj <= 30 ? 'B' : '';
    }}
    games.push({{ gr, opp, oppRank: oppRank || '', tier, me,
                  team: g.t[tKey], oppRows: g.t[oKey] }});
  }});
  return games;
}}

function __ppLine(label, subset) {{
  if (!subset.length) return null;
  const P = __ppSum(subset.map(g => g.me));
  const T = __ppSum([].concat(...subset.map(g => g.team)));
  const O = __ppSum([].concat(...subset.map(g => g.oppRows)));
  const line = __ppAdvLine(P, T, O, subset.length);
  line.label = label;
  line.gp = subset.filter(g => (g.me.min || 0) > 0 || g.me.fga > 0 || g.me.pts > 0).length;
  line.P = P;
  return line;
}}

const PP_TIER_BADGE = {{
  A: '<span style="background:#c8960c;color:#fff;padding:1px 6px;border-radius:3px;font-size:0.7rem;font-weight:700">A</span>',
  B: '<span style="background:#546e7a;color:#fff;padding:1px 6px;border-radius:3px;font-size:0.7rem;font-weight:700">B</span>',
}};

function __ppF(v, d) {{
  return v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d == null ? 1 : d);
}}

function __ppAdvRow(line, extraCls) {{
  return '<tr class="' + (extraCls || '') + '"><td class="pp-l">' + line.label + '</td>'
    + '<td>' + line.gp + '</td><td>' + __ppF(line.min_pct) + '</td>'
    + '<td><b>' + __ppF(line.ind_ortg) + '</b></td><td>' + __ppF(line.usage_pct) + '</td><td>' + __ppF(line.shot_pct) + '</td>'
    + '<td>' + __ppF(line.efg_pct) + '</td><td>' + __ppF(line.ts_pct) + '</td>'
    + '<td>' + __ppF(line.oreb_pct) + '</td><td>' + __ppF(line.dreb_pct) + '</td>'
    + '<td>' + __ppF(line.ast_rate) + '</td><td>' + __ppF(line.tov_pct) + '</td>'
    + '<td>' + __ppF(line.blk_pct) + '</td><td>' + __ppF(line.stl_pct) + '</td>'
    + '<td>' + __ppF(line.fc_per_40) + '</td><td>' + __ppF(line.fd_per_40) + '</td><td>' + __ppF(line.ft_rate) + '</td>'
    + '<td>' + line.ftm + '-' + line.fta + '</td><td>' + __ppF(line.ftp) + '</td>'
    + '<td>' + line.twom + '-' + line.twoa + '</td><td>' + __ppF(line.twop) + '</td>'
    + '<td>' + line.tpm + '-' + line.tpa + '</td><td>' + __ppF(line.tpp) + '</td></tr>';
}}

function __ppBasicRow(line, ppgDen) {{
  const g = Math.max(line.gp, 1);
  const P = line.P;
  return '<tr><td class="pp-l">' + line.label + '</td>'
    + '<td>' + line.gp + '</td>'
    + '<td><b>' + __ppF(P.PTS / g) + '</b></td><td>' + __ppF((P.OREB + P.DREB) / g) + '</td>'
    + '<td>' + __ppF(P.AST / g) + '</td><td>' + __ppF(P.STL / g) + '</td>'
    + '<td>' + __ppF(P.BLK / g) + '</td><td>' + __ppF(P.TO / g) + '</td>'
    + '<td>' + P.FGM + '-' + P.FGA + '</td><td>' + (P.FGA > 0 ? __ppF(100 * P.FGM / P.FGA) : '—') + '</td>'
    + '<td>' + line.twom + '-' + line.twoa + '</td><td>' + __ppF(line.twop) + '</td>'
    + '<td>' + line.tpm + '-' + line.tpa + '</td><td>' + __ppF(line.tpp) + '</td>'
    + '<td>' + __ppF(line.efg_pct) + '</td>'
    + '<td>' + line.ftm + '-' + line.fta + '</td><td>' + __ppF(line.ftp) + '</td>'
    + '<td>' + __ppF(line.ts_pct) + '</td></tr>';
}}

const PP_CHART_STATS = [
  ['ortg', 'Offensive Rating'], ['usg', 'Usage'], ['efg', 'Effective FG %'],
  ['top', 'Turnover Rate'], ['orp', 'Offensive Rebounding %'], ['drp', 'Defensive Rebounding %'],
  ['p3', '3-Pt %'], ['pts', 'Points'], ['ast', 'Assists'], ['or', 'Off. Rebounds'],
  ['dr', 'Def. Rebounds'], ['stl', 'Steals'], ['blk', 'Blocks'], ['to', 'Turnovers'],
  ['min', 'Minutes'], ['bpm', 'Game BPM'],
];
let ppChartSeries = [];

function ppDrawChart() {{
  const sel = document.getElementById('pp-cstat');
  const box = document.getElementById('pp-chartbox');
  if (!sel || !box || !ppChartSeries.length) return;
  const key = sel.value;
  const pts = ppChartSeries.map((g, i) => ({{ i: i, v: g[key], res: g.res, d: g.d, opp: g.opp }}));
  const valid = pts.filter(p => p.v != null);
  if (!valid.length) {{ box.innerHTML = '<i style="color:#888">no data for this stat</i>'; return; }}
  const chartCard = box.closest('.pp-card');
  const statsCard = Array.from(document.querySelectorAll('#player-content .pp-card')).find(c => c.querySelector('.pp-sub') && c.querySelector('.pp-sub').textContent.includes('Season'));
  if (chartCard && statsCard) {{
    const w = statsCard.offsetWidth;
    chartCard.style.maxWidth = w + 'px';
    chartCard.style.width = w + 'px';
  }}
  const W = 940, H = 440, L = 44, R = 14, T = 14, B = 26;
  const mov = [], five = [], run = [];
  pts.forEach(p => {{
    if (p.v != null) run.push(p.v);
    mov.push(run.length ? run.reduce((a, b) => a + b, 0) / run.length : null);
    const tail = run.slice(-5);
    five.push(tail.length ? tail.reduce((a, b) => a + b, 0) / tail.length : null);
  }});
  const all = valid.map(p => p.v).concat(mov.filter(v => v != null), five.filter(v => v != null));
  let lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
  if (hi - lo < 2) {{ hi += 1; lo -= 1; }}
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const X = i => L + i * (W - L - R) / Math.max(ppChartSeries.length - 1, 1);
  const Y = v => T + (hi - v) * (H - T - B) / (hi - lo);
  let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" style="width:100%;display:block">';
  for (let k = 0; k <= 4; k++) {{
    const v = lo + k * (hi - lo) / 4;
    svg += '<line x1="' + L + '" y1="' + Y(v).toFixed(1) + '" x2="' + (W - R) + '" y2="' + Y(v).toFixed(1) + '" stroke="#eee"/>'
        + '<text x="' + (L - 4) + '" y="' + (Y(v) + 3).toFixed(1) + '" font-size="9" fill="#888" text-anchor="end">' + v.toFixed(1) + '</text>';
  }}
  const line = (arr, color, dash) => {{
    const seg = arr.map((v, i) => v == null ? null : X(i).toFixed(1) + ',' + Y(v).toFixed(1)).filter(Boolean).join(' ');
    return '<polyline points="' + seg + '" fill="none" stroke="' + color + '" stroke-width="2"' + (dash ? ' stroke-dasharray="6 4"' : '') + '/>';
  }};
  svg += line(mov, '#1a3e8f', false) + line(five, '#c8960c', true);
  // invisible hover dots on both average lines: every game has a tooltip
  const hover = (arr, label) => {{
    let out = '';
    arr.forEach((v, i) => {{
      if (v == null) return;
      out += '<circle cx="' + X(i).toFixed(1) + '" cy="' + Y(v).toFixed(1) + '" r="11" fill="transparent" style="cursor:help"><title>'
           + ppChartSeries[i].d + ' vs ' + ppChartSeries[i].opp + ' — ' + label + ': ' + v.toFixed(1) + '</title></circle>';
    }});
    return out;
  }};
  pts.forEach(p => {{
    if (p.v == null) return;
    svg += '<circle cx="' + X(p.i).toFixed(1) + '" cy="' + Y(p.v).toFixed(1) + '" r="6" fill="' + (p.res === 'W' ? '#2e7d32' : '#c62828') + '" opacity="0.85"><title>' + p.d + ' vs ' + p.opp + ': ' + p.v + '</title></circle>';
  }});
  svg += hover(mov, 'season avg') + hover(five, '5-game avg');
  box.innerHTML = svg + '</svg>';
}}

function ppFilterLog(value) {{
  const want = value.split(' ').filter(Boolean);
  document.querySelectorAll('#pp-log tr').forEach(r => {{
    const fl = (r.dataset.f || '').split(' ');
    r.style.display = !want.length || want.some(w => fl.includes(w)) ? '' : 'none';
  }});
}}

function renderPlayerProfile() {{
  const {{ name, school }} = playerProfileCtx || {{}};
  if (!name) return;
  const roster = (TEAM_ROSTERS[activeSeason] || {{}})[school];
  const rRow = roster ? (roster.players || []).find(p => p.name === name) : null;
  const dRow = activeFullPlayerData().find(p => p.name === name && p.school === school);
  const t = activeFullTeamData().find(d => d.team === school);
  if (!rRow || !t) {{ alert('No data for ' + name + ' (' + school + ').'); return; }}
  const advOk = roster.adv === 1;
  const games = __ppGames(name, school);

  // ── splits
  const lines = [];
  const seasonLine = __ppLine('Season', games);
  const MONTH_NAMES = {{ '11': 'November', '12': 'December', '1': 'January', '2': 'February', '3': 'March' }};
  const monthLines = ['11', '12', '1', '2', '3']
    .map(m => __ppLine(MONTH_NAMES[m], games.filter(g => (g.gr.date || '').split('/')[0] === m)));
  const lineDefs = [
    {{ band: 'Season & Competition' }},
    seasonLine,
    __ppLine('Conference', games.filter(g => g.gr.is_conference)),
    __ppLine('vs Tier A', games.filter(g => g.tier === 'A')),
    __ppLine('vs Tier B', games.filter(g => g.tier === 'B')),
    __ppLine('vs Tier A+B', games.filter(g => g.tier === 'A' || g.tier === 'B')),
    __ppLine('Untiered', games.filter(g => !g.tier)),
    {{ band: 'Situation' }},
    __ppLine('Home', games.filter(g => g.gr.location === 'Home')),
    __ppLine('Away', games.filter(g => g.gr.location === 'Away')),
    __ppLine('Neutral', games.filter(g => g.gr.location !== 'Home' && g.gr.location !== 'Away')),
    __ppLine('In Wins', games.filter(g => g.gr.result === 'W')),
    __ppLine('In Losses', games.filter(g => g.gr.result === 'L')),
    {{ band: 'By Month' }},
  ].concat(monthLines).concat([
    {{ band: 'Recent Form' }},
    __ppLine('Last 5', games.slice(-5)),
    __ppLine('Last 10', games.slice(-10)),
  ]);
  lineDefs.forEach(l => {{ if (l) lines.push(l); }});

  // ── trending (played games only, chronological)
  const played = games.filter(g => (g.me.min || 0) > 0 || g.me.pts > 0 || g.me.fga > 0);
  const lastN = played.slice(-playerTrendN);
  const trendLine = __ppLine('L' + playerTrendN, lastN);
  let trendHtml = '';
  if (seasonLine && trendLine && lastN.length >= 2) {{
    const chips = lastN.map(g =>
      '<div class="pp-chip ' + (g.gr.result === 'W' ? 'pp-w' : 'pp-lo') + '" title="' + g.gr.date + ' vs ' + __ppEsc(g.opp) + '">'
      + '<div class="pp-chip-pts">' + g.me.pts + '</div><div class="pp-chip-opp">' + g.opp.slice(0, 9) + '</div></div>').join('');
    const delta = (cur, base, label, dec) => {{
      if (cur == null || base == null) return '';
      const d = cur - base;
      const cls = d >= 0 ? 'pp-up' : 'pp-dn';
      return '<span class="pp-delta ' + cls + '">' + (d >= 0 ? '▲' : '▼') + ' ' + label + ' '
        + Number(cur).toFixed(dec == null ? 1 : dec) + ' <small>(' + (d >= 0 ? '+' : '') + d.toFixed(1) + ')</small></span>';
    }};
    const sg = Math.max(seasonLine.gp, 1), lg = Math.max(trendLine.gp, 1);
    let deltas = delta(trendLine.P.PTS / lg, seasonLine.P.PTS / sg, 'PPG');
    deltas += delta(trendLine.efg_pct, seasonLine.efg_pct, 'eFG%');
    if (advOk) {{
      deltas += delta(trendLine.ind_ortg, seasonLine.ind_ortg, 'ORtg');
      const bvals = lastN.map(g => g.me.bpm).filter(v => v != null);
      const sbvals = played.map(g => g.me.bpm).filter(v => v != null);
      if (bvals.length && sbvals.length) {{
        deltas += delta(bvals.reduce((a, b) => a + b, 0) / bvals.length,
                        sbvals.reduce((a, b) => a + b, 0) / sbvals.length, 'BPM');
      }}
    }}
    trendHtml = '<div class="pp-trend"><div class="pp-trend-head">FORM — LAST '
      + '<span class="pp-tn' + (playerTrendN === 5 ? ' on' : '') + '" onclick="ppSetTrend(5)">5</span> / '
      + '<span class="pp-tn' + (playerTrendN === 10 ? ' on' : '') + '" onclick="ppSetTrend(10)">10</span>'
      + ' GAMES <small>(vs season avg)</small></div>'
      + '<div class="pp-chips">' + chips + '</div><div class="pp-deltas">' + deltas + '</div></div>';
  }}

  // ── tier table
  let tierTable;
  if (advOk) {{
    tierTable = '<table class="pp-table"><thead><tr>'
      + '<th class="pp-l">Split</th><th>G</th><th>%Min</th><th>ORtg</th><th>%Poss</th><th>%Shots</th>'
      + '<th>eFG%</th><th>TS%</th><th>OR%</th><th>DR%</th><th>ARate</th><th>TORate</th>'
      + '<th>Blk%</th><th>Stl%</th><th>FC/40</th><th>FD/40</th><th>FTRate</th>'
      + '<th>FTM-A</th><th>Pct</th><th>2PM-A</th><th>Pct</th><th>3PM-A</th><th>Pct</th></tr></thead><tbody>'
      + lines.map(l => l.band ? '<tr class="pp-band"><td colspan="23">' + l.band + '</td></tr>' : __ppAdvRow(l, l.label === 'Season' ? 'pp-season' : '')).join('')
      + '</tbody></table>';
  }} else {{
    tierTable = '<table class="pp-table"><thead><tr>'
      + '<th class="pp-l">Split</th><th>G</th><th>PPG</th><th>RPG</th><th>APG</th><th>SPG</th><th>BPG</th><th>TO</th>'
      + '<th>FGM-A</th><th>FG%</th><th>2PM-A</th><th>2P%</th><th>3PM-A</th><th>3P%</th><th>eFG%</th>'
      + '<th>FTM-A</th><th>FT%</th><th>TS%</th></tr></thead><tbody>'
      + lines.map(l => l.band ? '<tr class="pp-band"><td colspan="18">' + l.band + '</td></tr>' : __ppBasicRow(l)).join('')
      + '</tbody></table>';
  }}

  // ── Torvik chart series
  const g3p = r => r.tpa ? Math.round(1000 * r.tpm / r.tpa) / 10 : null;
  ppChartSeries = played.map(g => ({{
    d: g.gr.date, opp: g.opp, res: g.gr.result,
    ortg: g.me.ortg, usg: g.me.usg, efg: g.me.efg, top: g.me.top,
    orp: g.me.orp, drp: g.me.drp, p3: g3p(g.me), pts: g.me.pts,
    ast: g.me.ast, or: g.me.or, dr: g.me.dr, stl: g.me.stl,
    blk: g.me.blk, to: g.me.to, min: g.me.min, bpm: g.me.bpm,
  }}));
  const chartOpts = PP_CHART_STATS.map(s => '<option value="' + s[0] + '">' + s[1] + '</option>').join('');

  // ── similar players (cross-season, precomputed at build)
  const SIM_SEASON_LABELS = {{ '2526': '2025-26', '2425': '2024-25', '2324': '2023-24', '2223': '2022-23', '2122': '2021-22', '1920': '2019-20', '1819': '2018-19', '1718': '2017-18' }};
  let simHtml = '';
  if (rRow.sim && rRow.sim.length) {{
    // Position-specific columns into the neighbor tuple (see attach_similar_players).
    const SIM_COLS = {{
      // 3P% -> index 28, 2P% -> index 27: ungated season % for display (see _emit).
      'PG':   [['ARate',17],['TO%',18],['%Poss',4],['Stl%',19],['TS%',8]],
      's-PG': [['%Poss',4],['%Shots',20],['TS%',8],['3P%',28],['ARate',17]],
      'CG':   [['%Poss',4],['ARate',17],['3P%',28],['TS%',8]],
      'WG':   [['2P%',27],['FTR',12],['FD/40',13],['TS%',8],['3P%',28]],
      'WF':   [['2P%',27],['FTR',12],['FD/40',13],['DREB%',15],['TS%',8]],
      'S-PF': [['3PA%',7],['3P%',28],['TS%',8],['DREB%',15],['OREB%',14]],
      'PF/C': [['2P%',27],['OREB%',14],['DREB%',15],['Blk%',16],['FD/40',13]],
      'C':    [['2P%',27],['OREB%',14],['DREB%',15],['Blk%',16],['FD/40',13]],
    }};
    const tgtPos = (dRow && dRow.pos) || (rRow.sim[0] && rRow.sim[0][9]) || '';
    const isShoot = rRow.sim_mode === 'shoot';
    // Fallback (minutes not tracked): show only basic, minutes-independent
    // box-score stats — no advanced rates, no PRPG!. Full match: position cols + PRPG!.
    const cols = isShoot
      ? [['OREB',21],['DREB',22],['APG',23],['TO',24],['eFG%',26],['TS%',8]]
      : (SIM_COLS[tgtPos] || [['%Poss',4],['3PA%',7],['TS%',8]]);
    const simRows = rRow.sim.map(s =>
      '<tr><td class="pp-l">' + s[0] + '</td><td class="pp-l">' + s[1] + '</td>'
      + '<td>' + (SIM_SEASON_LABELS[s[2]] || s[2]) + '</td>'
      + cols.map(c => '<td>' + __ppF(s[c[1]]) + '</td>').join('')
      + (isShoot ? '' : '<td>' + __ppF(s[6], 2) + '</td>') + '</tr>').join('');
    const simHead = isShoot
      ? 'Similar Players <small>(basic box-score profile — minutes not reliably tracked for this player)</small>'
      : 'Similar Players <small>(nearest neighbors by ' + (tgtPos || 'overall') + ' profile, all seasons)</small>';
    simHtml = '<div class="pp-card"><div class="pp-sub">' + simHead + '</div>'
      + '<table class="pp-table"><thead><tr><th class="pp-l">Player</th><th class="pp-l">School</th><th>Season</th>'
      + cols.map(c => '<th>' + c[0] + '</th>').join('')
      + (isShoot ? '' : '<th>PRPG!</th>') + '</tr></thead><tbody>' + simRows + '</tbody></table></div>';
  }}

  // ── game log flags (playoffs = after the last conference game)
  let lastConfIdx = -1;
  games.forEach((g, i) => {{ if (g.gr.is_conference) lastConfIdx = i; }});
  games.forEach((g, i) => {{
    const fl = [];
    if (g.gr.is_conference) fl.push('conf');
    if (g.tier === 'A') fl.push('ta');
    if (g.tier === 'B') fl.push('tb');
    if (lastConfIdx >= 0 && i > lastConfIdx) fl.push('po');
    g.flags = fl.join(' ');
  }});

  const logRows = games.map(g => {{
    const r = g.me;
    const st = r.st ? '<span class="pp-st">' + r.min + '</span>' : r.min;
    const res = '<a href="#" class="box-link" onclick="openBoxScore(\\'' + g.gr.date + '\\',\\'' + __ppEsc(school) + '\\',\\'' + __ppEsc(g.opp) + '\\');return false">'
      + g.gr.result + ', ' + g.gr.team_score + '-' + g.gr.opponent_score + '</a>';
    return '<tr class="' + (g.gr.result === 'W' ? 'pp-gw' : 'pp-gl') + '" data-f="' + g.flags + '"><td class="pp-l">' + g.gr.date + '</td><td>' + g.oppRank + '</td>'
      + '<td class="pp-l">' + g.opp + (g.gr.is_conference ? ' *' : '') + '</td>'
      + '<td>' + (PP_TIER_BADGE[g.tier] || '') + '</td>'
      + '<td class="pp-l">' + res + '</td>'
      + '<td>' + st + '</td><td><b>' + r.pts + '</b></td>'
      + '<td>' + (r.fgm - r.tpm) + '-' + (r.fga - r.tpa) + '</td>'
      + '<td>' + r.tpm + '-' + r.tpa + '</td><td>' + r.ftm + '-' + r.fta + '</td>'
      + '<td>' + r.or + '-' + r.dr + '</td><td>' + r.ast + '</td><td>' + r.to + '</td>'
      + '<td>' + r.stl + '</td><td>' + r.blk + '</td><td>' + r.pf + '</td>'
      + '<td>' + __ppF(r.ortg) + '</td><td>' + __ppF(r.usg) + '</td><td>' + __ppF(r.bpm) + '</td></tr>';
  }}).join('');

  // ── header bits
  const seasonLabel = activeSeason === '2526' ? '2025-26' : activeSeason === '2425' ? '2024-25' : activeSeason === '2324' ? '2023-24' : activeSeason === '2223' ? '2022-23' : activeSeason === '2122' ? '2021-22' : activeSeason === '1920' ? '2019-20' : activeSeason === '1819' ? '2018-19' : '2017-18';
  const starts = games.filter(g => g.me.st).length;
  const head = [];
  if (dRow && dRow.jersey) head.push('#' + dRow.jersey);
  if (dRow && dRow.pos) head.push(dRow.pos);
  if (rRow.ht) head.push(rRow.ht);
  const hl = [];
  hl.push('<b>' + __ppF(rRow.ppg) + '</b> PPG');
  if (advOk && rRow.ind_ortg != null) hl.push('<b>' + __ppF(rRow.ind_ortg) + '</b> ORtg');
  if (dRow && dRow.porp != null) hl.push('<b>' + __ppF(dRow.porp, 2) + '</b> PRPG!');
  if (dRow && dRow.bpm != null) hl.push('<b>' + __ppF(dRow.bpm, 2) + '</b> BPM');

  document.getElementById('player-content').innerHTML = `<style>
    #player-content .pp-table {{ width: auto; border-collapse: collapse; font-size: 0.8rem; white-space: nowrap; margin: 0 auto; }}
    #player-content .pp-table th {{ background: #1a1a2e; color: #fff; padding: 5px 8px; text-align: right; font-size: 0.72rem; border-bottom: 2px solid #333; }}
    #player-content .pp-table th.pp-l, #player-content .pp-table td.pp-l {{ text-align: left; }}
    #player-content .pp-table td {{ padding: 4px 8px; border-bottom: 1px solid #ddd; text-align: right; color: #000; background: #fff; }}
    #player-content .pp-table td.pp-l {{ font-weight: 600; }}
    #player-content .pp-table tbody tr:nth-child(odd) td, #player-content .pp-table tbody tr:nth-child(even) td {{ background: #fff; }}
    #player-content .pp-table tbody tr:hover td {{ background: #eef4ff; }}
    #player-content .pp-table tr.pp-season td {{ background: #eef3fb; border-bottom: 2px solid #1a3a6e; }}
    #player-content .pp-table tbody tr.pp-band td {{
      background: #c7d3e8; color: #122a52; font-weight: 800; font-size: 0.76rem;
      text-align: left; padding: 6px 8px;
      border-top: 12px solid #fff; border-bottom: 2px solid #1a3a6e;
    }}
    #player-content .pp-table tbody tr.pp-band:hover td {{ background: #c7d3e8; }}
    #player-content .pp-table tbody tr.pp-band:first-child td {{ border-top: none; }}
    #player-content .pp-table tbody tr.pp-gw td {{ background: rgb(0,255,0); color: #000; }}
    #player-content .pp-table tbody tr.pp-gl td {{ background: rgb(255,0,0); color: #000; }}
    #player-content .pp-table tbody tr.pp-gw:hover td {{ background: rgb(0,230,0); }}
    #player-content .pp-table tbody tr.pp-gl:hover td {{ background: rgb(230,0,0); }}
    #player-content .pp-st {{ display: inline-block; min-width: 18px; border: 1.6px solid #1a3e8f; border-radius: 2px; padding: 0 2px; font-weight: 700; }}
    #player-content .pp-trend {{ background: #fff; border: 1px solid #ccc; border-radius: 8px; padding: 12px 16px; max-width: fit-content; margin: 0 auto 16px; }}
    #player-content .pp-trend-head {{ font-size: 0.78rem; font-weight: 800; color: #1a3a6e; margin-bottom: 8px; text-align: center; letter-spacing: 0.04em; }}
    #player-content .pp-tn {{ cursor: pointer; color: #999; padding: 0 3px; }}
    #player-content .pp-tn.on {{ color: #1a3a6e; text-decoration: underline; }}
    #player-content .pp-chips {{ display: flex; gap: 6px; justify-content: center; margin-bottom: 8px; }}
    #player-content .pp-chip {{ border-radius: 6px; padding: 4px 8px; text-align: center; min-width: 52px; color: #fff; }}
    #player-content .pp-chip.pp-w {{ background: #2e7d32; }}
    #player-content .pp-chip.pp-lo {{ background: #c62828; }}
    #player-content .pp-chip-pts {{ font-size: 1.05rem; font-weight: 800; }}
    #player-content .pp-chip-opp {{ font-size: 0.62rem; opacity: 0.85; }}
    #player-content .pp-deltas {{ display: flex; gap: 16px; justify-content: center; font-size: 0.85rem; font-weight: 700; flex-wrap: wrap; }}
    #player-content .pp-up {{ color: #2e7d32; }}
    #player-content .pp-dn {{ color: #c62828; }}
    #player-content .pp-card {{ background: #fff; border: 1px solid #ccc; border-radius: 8px; padding: 16px; overflow-x: auto; max-width: fit-content; margin: 0 auto 16px; }}
    #player-content .pp-sub {{ font-size: 0.95rem; font-weight: 700; text-align: center; color: #000; border-bottom: 2px solid #333; padding-bottom: 5px; margin-bottom: 10px; }}
  </style>
  <div style="background:#1a1a2e;border-radius:8px;padding:16px 20px;margin-bottom:16px;text-align:center">
    <div style="color:#4fc3f7;font-size:0.95rem;font-weight:700">${{head.join(' · ')}}</div>
    <h2 style="color:#B9D9EB;font-size:1.7rem;margin:4px 0">${{name}}</h2>
    <div style="color:#ccc;font-size:0.9rem"><a href="#" onclick="closePlayerProfile();showTeamDetail('${{__ppEsc(school)}}');return false" style="color:#4fc3f7;text-decoration:none">${{school}}</a> · ${{t.conference}} · ${{seasonLabel}}</div>
    <div style="color:#fff;font-size:1rem;font-weight:600;margin-top:4px">${{rRow.gp}} GP · ${{starts}} starts &nbsp;|&nbsp; ${{hl.join(' &nbsp;·&nbsp; ')}}</div>
  </div>
  ${{trendHtml}}
  <div class="pp-card" style="width:900px">
    <div class="pp-sub">Game-by-Game <small>(dots = games · solid = season moving avg · dashed = 5-game avg)</small></div>
    <div style="text-align:center;margin-bottom:8px"><select id="pp-cstat" onchange="ppDrawChart()">${{chartOpts}}</select></div>
    <div id="pp-chartbox"></div>
  </div>
  <div class="pp-card">
    <div class="pp-sub">Season &amp; Split Stats${{advOk ? '' : ' <span style="color:#b71c1c;font-size:0.75rem">(basic only — minutes not reliably tracked)</span>'}}</div>
    ${{tierTable}}
    <div style="font-size:0.7rem;color:#888;margin-top:6px">Tier A/B per the schedule rule (opponent NET rank, location-adjusted) · splits aggregated from box scores with the same formulas as season stats</div>
  </div>
  ${{simHtml}}
  <div class="pp-card">
    <div class="pp-sub">Game Log</div>
    <div style="text-align:center;margin-bottom:8px"><select onchange="ppFilterLog(this.value)">
      <option value="">Full Season</option><option value="conf">Conference</option>
      <option value="ta">vs Tier A</option><option value="tb">vs Tier B</option>
      <option value="ta tb">vs Tier A+B</option><option value="po">Playoffs</option>
    </select></div>
    <table class="pp-table"><thead><tr>
      <th class="pp-l">Date</th><th>Rk</th><th class="pp-l">Opponent</th><th>Tier</th><th class="pp-l">Result</th>
      <th>Min</th><th>Pts</th><th>2P</th><th>3P</th><th>FT</th><th>OR-DR</th><th>A</th><th>TO</th><th>S</th><th>B</th><th>PF</th>
      <th>ORtg</th><th>%Poss</th><th>BPM</th>
    </tr></thead><tbody id="pp-log">${{logRows}}</tbody></table>
    <div style="font-size:0.7rem;color:#888;margin-top:6px">Boxed minutes = started &nbsp;|&nbsp; * = conference game &nbsp;|&nbsp; click a result for the full box score</div>
  </div>`;

  __PP_VIEWS.forEach(id => {{
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  }});
  document.getElementById('season-toggle').style.display = 'none';
  document.getElementById('player-view').style.display = 'block';
  ppDrawChart();
  window.scrollTo(0, 0);
}}

function renderMinutesMatrix(teamName) {{
  const t = activeFullTeamData().find(d => d.team === teamName);
  if (!t) return;
  const boxes = GAME_BOXES[activeSeason] || {{}};
  const _dayRanksSource = activeSeason === '2324' ? DAILY_RANKS_2023 : activeSeason === '2425' ? DAILY_RANKS_2024 : DAILY_RANKS;

  // Collect this team's games (schedule order) with their box rows
  const games = [];
  (t.game_ratings || []).forEach(gr => {{
    if (gr.result !== 'W' && gr.result !== 'L') return;
    const opp = gr.canonical_opponent || gr.opponent || '';
    const g = boxes[__boxKey(gr.date, teamName, opp)];
    let rows = null;
    if (g) {{
      const key = Object.keys(g.t).find(k => __boxNorm(k) === __boxNorm(teamName));
      rows = key ? g.t[key] : null;
    }}
    games.push({{ gr, opp, rows }});
  }});

  // Player columns: everyone who appears, starts first then minutes
  const agg = new Map();
  games.forEach(g => (g.rows || []).forEach(r => {{
    const a = agg.get(r.n) || {{ min: 0, starts: 0 }};
    a.min += r.min || 0;
    a.starts += r.st ? 1 : 0;
    agg.set(r.n, a);
  }}));
  const players = [...agg.keys()].sort((a, b) => {{
    const A = agg.get(a), B = agg.get(b);
    return (B.starts - A.starts) || (B.min - A.min);
  }});

  // Distinct starting lineups, numbered by first appearance
  const lineupNums = new Map();
  games.forEach(g => {{
    if (!g.rows) {{ g.lineup = null; return; }}
    const sig = g.rows.filter(r => r.st).map(r => r.n).sort().join('|');
    if (!sig) {{ g.lineup = null; return; }}
    if (!lineupNums.has(sig)) lineupNums.set(sig, lineupNums.size + 1);
    g.lineup = lineupNums.get(sig);
  }});

  const headCells = players.map(p =>
    '<th class="mm-p"><div>' + p + '</div></th>').join('');

  let rowsHtml = '';
  games.forEach(g => {{
    const dayRanks = _dayRanksSource[g.gr.date] || {{}};
    const oppRank = dayRanks[g.opp] || '';
    const resCls = g.gr.result === 'W' ? 'mm-w' : 'mm-l';
    const resStr = g.gr.result + ', ' + (g.gr.team_score || 0) + '-' + (g.gr.opponent_score || 0);
    const conf = g.gr.is_conference ? ' *' : '';
    let cells = '';
    if (!g.rows) {{
      cells = '<td class="mm-na" colspan="' + players.length + '">no box score</td>';
    }} else {{
      const teamMin = g.rows.reduce((s, r) => s + (r.min || 0), 0);
      const real = teamMin >= 150;
      const byName = new Map(g.rows.map(r => [r.n, r]));
      cells = players.map(p => {{
        const r = byName.get(p);
        if (!r || (!r.min && !r.st)) return '<td></td>';
        const val = real ? r.min : '–';
        return '<td>' + (r.st ? '<span class="mm-st">' + val + '</span>' : val) + '</td>';
      }}).join('');
    }}
    const lu = g.lineup
      ? '<td class="mm-lu" style="color:' + MM_LINEUP_COLORS[(g.lineup - 1) % MM_LINEUP_COLORS.length] + '">' + g.lineup + '</td>'
      : '<td></td>';
    rowsHtml += '<tr><td class="mm-date">' + g.gr.date + '</td>'
      + '<td class="mm-rk">' + oppRank + '</td>'
      + '<td class="mm-opp">' + g.opp + conf + '</td>'
      + '<td class="' + resCls + '">' + resStr + '</td>'
      + cells + lu + '</tr>';
  }});

  const netRtgRanks = {{}};
  activeTeamData.filter(d => d.ortg > 0).sort((a, b) => b.net_rtg - a.net_rtg)
    .forEach((d, i) => {{ netRtgRanks[d.team] = i + 1; }});

  document.getElementById('minmatrix-content').innerHTML = `<style>
    #minmatrix-content table {{ width: auto; border-collapse: collapse; font-size: 0.78rem; white-space: nowrap; margin: 0 auto; }}
    #minmatrix-content th {{ background: #1a1a2e; color: #fff; padding: 4px 6px; font-size: 0.72rem; border-bottom: 2px solid #333; }}
    #minmatrix-content th.mm-p {{ height: 120px; vertical-align: bottom; width: 26px; max-width: 26px; padding: 2px 0; position: relative; }}
    #minmatrix-content th.mm-p > div {{ writing-mode: vertical-rl; transform: rotate(180deg); margin: 0 auto; font-weight: 600; }}
    #minmatrix-content td {{ padding: 3px 6px; border-bottom: 1px solid #ddd; text-align: center; color: #000; background: #fff; }}
    #minmatrix-content td.mm-date {{ text-align: left; }}
    #minmatrix-content td.mm-opp {{ text-align: left; font-weight: 600; }}
    #minmatrix-content td.mm-w {{ color: #1b7e1b; font-weight: 700; text-align: left; }}
    #minmatrix-content td.mm-l {{ color: #c62828; font-weight: 700; text-align: left; }}
    #minmatrix-content td.mm-na {{ color: #999; font-style: italic; }}
    #minmatrix-content td.mm-lu {{ font-weight: 800; }}
    #minmatrix-content .mm-st {{ display: inline-block; min-width: 18px; border: 1.6px solid #1a3e8f; border-radius: 2px; padding: 0 2px; font-weight: 700; }}
    #minmatrix-content tr:hover td {{ background: #eef4ff; }}
  </style>
  <div style="background:#1a1a2e;border-radius:8px;padding:16px 20px;margin-bottom:16px;text-align:center">
    <div style="color:#4fc3f7;font-size:1.1rem;font-weight:700">#${{netRtgRanks[teamName] || '—'}} NET RTG</div>
    <h2 style="color:#B9D9EB;font-size:1.6rem;margin:4px 0">${{teamName}} — Minutes Matrix</h2>
    <div style="color:#ccc;font-size:0.9rem">${{t.conference}} · ${{t.region}} Region</div>
    <div style="color:#fff;font-size:1.1rem;font-weight:700;margin-top:4px">${{t.record}} Overall &nbsp;|&nbsp; ${{t.conf}} Conference</div>
  </div>
  <div style="background:#fff;border-radius:8px;padding:16px;border:1px solid #ccc;overflow-x:auto;max-width:fit-content;margin:0 auto">
    <table><thead><tr>
      <th style="text-align:left">Date</th><th>Rk</th><th style="text-align:left">Opponent</th><th style="text-align:left">Result</th>
      ${{headCells}}<th class="mm-p"><div>Lineup #</div></th>
    </tr></thead><tbody>${{rowsHtml}}</tbody></table>
    <div style="font-size:0.72rem;color:#888;margin-top:8px">
      Boxed number = started the game &nbsp;|&nbsp; Lineup # = distinct starting five, numbered by first appearance &nbsp;|&nbsp;
      – = minutes not tracked for that game &nbsp;|&nbsp; Rk = opponent NET RTG rank as of game date &nbsp;|&nbsp; * = conference game
    </div>
  </div>`;
  document.getElementById('team-detail-view').style.display = 'none';
  document.getElementById('minmatrix-view').style.display = 'block';
  window.scrollTo(0, 0);
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
    const boxCell = (result === 'W' || result === 'L')
      ? `<a href="#" class="box-link" onclick="openBoxScore('${{dateStr}}','${{t.team}}','${{opp}}');return false">Box</a>`
      : '';
    scheduleHtml += `<tr class="${{rowClass}}">
      <td style="text-align:left;white-space:nowrap;${{cellBg}}">${{dateStr}}</td>
      <td style="text-align:center;${{cellBg}}">${{teamRank}}</td>
      <td style="text-align:left;${{cellBg}}">${{oppLink}}${{oppRankHtml}}${{oppNetHtml}}${{confMarker}}</td>
      <td style="text-align:center;${{cellBg}}">${{boxCell}}</td>
      <td style="text-align:left;font-weight:600;${{cellBg}}">${{resultStr}}</td>
      <td style="text-align:center;${{cellBg}}">${{loc}}</td>
      <td style="text-align:center;${{cellBg}}">${{runRec}}</td>
      <td style="text-align:center;${{cellBg}}">${{runConf}}</td>
      <td style="text-align:center;${{cellBg}}">${{tierHtml}}</td>
    </tr>`;

    // Insert Playoffs banner after the last conference game
    if (idx === lastConfIdx && !playoffBannerInserted && lastConfIdx < games.length - 1) {{
      playoffBannerInserted = true;
      scheduleHtml += `<tr><td colspan="9" style="text-align:center;background:#888;color:#fff;font-weight:700;font-size:0.78rem;padding:4px;letter-spacing:1px">PLAYOFFS</td></tr>`;
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
      ${{teamLogoHtml(t.team)}}
      <div class="td-rank">#${{ranks.net_rtg}} NET RTG</div>
      <h1>${{t.team}}</h1>
      <div class="td-meta">${{t.conference}} · ${{t.region}} Region</div>
      <div class="td-record">${{fs.record}} Overall &nbsp;|&nbsp; ${{fs.conf}} Conference</div>
      ${{fs.coach ? `<div class="td-coach">HC: ${{fs.coach}}</div>` : ''}}
      ${{dataThruHtml}}
    </div>
    <div class="td-content">
      <div class="td-scouting">
        <div class="td-section-title">Scouting Report</div>
        <div style="display:flex;justify-content:center;gap:18px;font-size:0.8rem;margin:-4px 0 8px"><span onclick="showTeamStats('${{t.team}}')" style="color:#4fc3f7;cursor:pointer;font-weight:600">Team Stats →</span>${{MM_SEASONS.has(activeSeason) ? `<span onclick="showMinutesMatrix('${{t.team}}')" style="color:#4fc3f7;cursor:pointer;font-weight:600">Minutes Matrix →</span>` : ''}}<span onclick="showGamePlan('${{t.team}}')" style="color:#4fc3f7;cursor:pointer;font-weight:600">Game Plan →</span>${{(typeof MOORPARK_LINEUPS !== 'undefined' && MOORPARK_LINEUPS.team === t.team && activeSeason === '2526') ? `<span onclick="showLineups('${{t.team}}')" style="color:#ffd700;cursor:pointer;font-weight:600">Lineups →</span>` : ''}}</div>
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
          <th>Box</th><th style="text-align:left">Result</th><th>Loc</th><th>Record</th><th>Conf</th><th>Tier</th>
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
  try {{ __curView = view; }} catch (e) {{}}
  const indDiv = document.getElementById('individual-view');
  const teamDiv = document.getElementById('team-view');
  const chartsDiv = document.getElementById('charts-view');
  const uniDiv = document.getElementById('universe-view');
  const tdDiv = document.getElementById('team-detail-view');
  const slDiv = document.getElementById('storylines-view');
  const fmDiv = document.getElementById('fanmatch-view');
  const btnInd = document.getElementById('btn-individual');
  const btnTeam = document.getElementById('btn-team');
  const btnCharts = document.getElementById('btn-charts');
  const btnUni = document.getElementById('btn-universe');
  const btnSl = document.getElementById('btn-storylines');
  const btnFm = document.getElementById('btn-fanmatch');
  const btnKeys = document.getElementById('btn-keys');
  const title = document.getElementById('page-title');
  const subtitle = document.getElementById('page-subtitle');
  const info = document.getElementById('page-info');
  const filterBar = document.querySelector('.filter-bar');

  // Hide all
  indDiv.style.display = 'none';
  teamDiv.style.display = 'none';
  chartsDiv.style.display = 'none';
  uniDiv.style.display = 'none';
  tdDiv.style.display = 'none';
  slDiv.style.display = 'none';
  fmDiv.style.display = 'none';
  document.getElementById('keys-view').style.display = 'none';
  document.getElementById('lineups-view').style.display = 'none';
  document.getElementById('gameplan-view').style.display = 'none';
  document.getElementById('minmatrix-view').style.display = 'none';
  document.getElementById('teamstats-view').style.display = 'none';
  document.getElementById('player-view').style.display = 'none';
  document.getElementById('sub-toggle').style.display = 'none';
  document.getElementById('team-defense-view').style.display = 'none';
  document.getElementById('team-basic-view').style.display = 'none';
  document.getElementById('team-basic-defense-view').style.display = 'none';
  document.getElementById('team-adv-offense-view').style.display = 'none';
  document.getElementById('team-adv-defense-view').style.display = 'none';
  document.getElementById('season-toggle').style.display = 'none';
  btnInd.classList.remove('active');
  btnTeam.classList.remove('active');
  btnCharts.classList.remove('active');
  btnUni.classList.remove('active');
  btnSl.classList.remove('active');
  btnFm.classList.remove('active');
  if (btnKeys) btnKeys.classList.remove('active');

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
  }} else if (view === 'charts') {{
    chartsDiv.style.display = 'block';
    btnCharts.classList.add('active');
    filterBar.style.display = 'flex';
    document.getElementById('conf-toggle-wrap').style.display = 'none';
    document.getElementById('sub-toggle').style.display = 'none';
    document.getElementById('page-title').style.display = '';
    document.getElementById('page-subtitle').style.display = '';
    document.getElementById('page-info').style.display = '';
    document.getElementById('season-toggle').style.display = 'flex';
    title.textContent = 'Charts';
    subtitle.textContent = chartSeasonLabel() + ' Season \u2014 ' + (chartScopeLabel()) + ' Scatter';
    info.textContent = 'Use Stats Scope for Full Season or Conference Only · Top filters remove bubbles; chart focus greys context · Generated ' + TIMESTAMP;
    renderCharts();
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
  }} else if (view === 'keys') {{
    document.getElementById('keys-view').style.display = 'block';
    if (btnKeys) btnKeys.classList.add('active');
    filterBar.style.display = 'none';
    document.getElementById('page-title').style.display = 'none';
    document.getElementById('page-subtitle').style.display = 'none';
    document.getElementById('page-info').style.display = 'none';
    document.getElementById('conf-toggle-wrap').style.display = 'none';
    document.querySelector('.team-search-wrap').style.display = 'none';
    renderKeysView();
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
    title.textContent = 'Individual Statistics Leaderboard';
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
    applyTeamStatsRowColor(tr, t.team);
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
    applyTeamStatsRowColor(tr, t.team);
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
  {{ id: 'height',    label: 'Height' }},
  {{ id: 'wab',       label: 'WAB' }},
  {{ id: 'rate',      label: 'Rate' }},
  {{ id: 'tiers',     label: 'Tiers' }},
  {{ id: 'quads',     label: 'Quads' }},
  {{ id: 'trank',     label: 'T-Rank' }},
  {{ id: 'rpi',       label: 'RPI' }},
  {{ id: 'trends',    label: 'Trends' }},
  {{ id: 'conf',      label: 'Conferences' }},
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
  slRenderHeight();
  slInitFanmatch();
  slRenderWab(slWabRegion || 'North');
  slRenderRate(activeSeason);
  slRenderTiers('All');
  slRenderQuads();
  slRenderTrank();
  slRenderRpi();
  slBuildTrendsTeamList();
  slRenderTrends();
  slRenderConf();
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
  slRenderHeight();
  slRenderWab(slWabRegion || 'North');
  slRenderRate(activeSeason);
  slRenderTiers('All');
  slRenderQuads();
  slRenderTrank();
  slRenderRpi();
  slBuildTrendsTeamList();
  slRenderConf();
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
    }} else if (tab === 'height') {{
      title.textContent = '2025-26 Average Roster Height';
      if (countEl) countEl.style.display = 'none';
      slRenderHeight();
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
    }} else if (tab === 'conf') {{
      const confYr = activeSeason === '1718' ? '2017-18' : activeSeason === '1819' ? '2018-19' : activeSeason === '1920' ? '2019-20' : activeSeason === '2122' ? '2021-22' : activeSeason === '2223' ? '2022-23' : activeSeason === '2324' ? '2023-24' : activeSeason === '2425' ? '2024-25' : '2025-26';
      title.textContent = confYr + ' Conference Four Factors';
      if (countEl) countEl.style.display = 'none';
      slRenderConf();
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

let slHeightSortKey = 'avg_height';
let slHeightSortAsc = false;

function slSortHeight(key) {{
  if (slHeightSortKey === key) {{ slHeightSortAsc = !slHeightSortAsc; }}
  else {{
    slHeightSortKey = key;
    slHeightSortAsc = (key === 'team' || key === 'conference');
  }}
  slRenderHeight();
}}

function slHeightSortVal(r, key) {{
  if (key === 'rank') return r.rank || 9999;
  if (key === 'team') return (r.team || '').toLowerCase();
  if (key === 'conference') return (r.conference || '').toLowerCase();
  if (key === 'avg_height') return r.avg_inches == null ? -9999 : Number(r.avg_inches);
  if (key === 'avg_guard_height') return r.avg_guard_inches == null ? -9999 : Number(r.avg_guard_inches);
  if (key === 'avg_forward_height') return r.avg_forward_inches == null ? -9999 : Number(r.avg_forward_inches);
  if (key === 'range') {{
    const minVal = r.min_inches == null ? -9999 : Number(r.min_inches);
    const maxVal = r.max_inches == null ? -9999 : Number(r.max_inches);
    return maxVal * 100 + minVal;
  }}
  const v = r[key];
  return v == null ? -9999 : Number(v);
}}

function slRenderHeight() {{
  const body = document.getElementById('sl-body-height');
  if (!body) return;
  const ranked = (HEIGHT_DATA && HEIGHT_DATA.ranked) ? HEIGHT_DATA.ranked : [];
  const missing = (HEIGHT_DATA && HEIGHT_DATA.missing) ? HEIGHT_DATA.missing : [];
  if (!ranked.length && !missing.length) {{
    body.innerHTML = '<tr><td colspan="13" style="text-align:center;color:#555;padding:24px">No height data available</td></tr>';
    return;
  }}
  const sorted = ranked.slice().sort((a, b) => {{
    const av = slHeightSortVal(a, slHeightSortKey);
    const bv = slHeightSortVal(b, slHeightSortKey);
    let cmp;
    if (typeof av === 'string' || typeof bv === 'string') {{
      cmp = String(av).localeCompare(String(bv));
    }} else {{
      cmp = av - bv;
    }}
    if (cmp === 0) cmp = (a.rank || 9999) - (b.rank || 9999);
    return slHeightSortAsc ? cmp : -cmp;
  }});
  const rows = sorted.map((r, i) => {{
    const bg = r.team === 'Moorpark' ? 'background:#ffe599;' : '';
    const avg = Number(r.avg_inches || 0);
    const gAvg = r.avg_guard_inches == null ? null : Number(r.avg_guard_inches);
    const fAvg = r.avg_forward_inches == null ? null : Number(r.avg_forward_inches);
    const gScoring = r.guard_scoring_pct == null ? null : Number(r.guard_scoring_pct);
    const fScoring = r.forward_scoring_pct == null ? null : Number(r.forward_scoring_pct);
    const range = (r.min_height && r.max_height) ? r.min_height + '–' + r.max_height : '—';
    return `<tr>
      <td class="sl-th-r" style="${{bg}}color:#888;font-size:0.8rem">${{i + 1}}</td>
      <td style="${{bg}}">${{teamPageLink(r.team, 'color:#000;text-decoration:none;font-weight:600')}}</td>
      <td style="${{bg}}color:#555;font-size:0.82rem">${{r.conference || ''}}</td>
      <td class="sl-th-r" style="${{bg}}font-weight:700">${{avg.toFixed(2)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{r.avg_height || ''}}</td>
      <td class="sl-th-r" style="${{bg}}">${{gAvg == null ? '—' : gAvg.toFixed(2)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{r.avg_guard_height || '—'}}${{r.guard_players ? ` <span style="color:#777;font-size:0.72rem">(${{r.guard_players}})</span>` : ''}}</td>
      <td class="sl-th-r" style="${{bg}}">${{fAvg == null ? '—' : fAvg.toFixed(2)}}</td>
      <td class="sl-th-r" style="${{bg}}">${{r.avg_forward_height || '—'}}${{r.forward_players ? ` <span style="color:#777;font-size:0.72rem">(${{r.forward_players}})</span>` : ''}}</td>
      <td class="sl-th-r" style="${{bg}}">${{gScoring == null ? '—' : gScoring.toFixed(1) + '%'}}</td>
      <td class="sl-th-r" style="${{bg}}">${{fScoring == null ? '—' : fScoring.toFixed(1) + '%'}}</td>
      <td class="sl-th-r" style="${{bg}}">${{r.players || 0}}</td>
      <td class="sl-th-r" style="${{bg}}color:#555;font-size:0.82rem">${{range}}</td>
    </tr>`;
  }});
  if (missing.length) {{
    rows.push(`<tr><td colspan="13" style="text-align:center;background:#1a1a2e;color:#ddd;font-size:0.78rem;font-weight:700">Missing height scrape</td></tr>`);
    missing.forEach(r => {{
      rows.push(`<tr>
        <td class="sl-th-r" style="color:#888;font-size:0.8rem">—</td>
        <td>${{teamPageLink(r.team, 'color:#000;text-decoration:none;font-weight:600')}}</td>
        <td style="color:#555;font-size:0.82rem">${{r.conference || ''}}</td>
        <td class="sl-th-r">—</td>
        <td class="sl-th-r">—</td>
        <td class="sl-th-r">—</td>
        <td class="sl-th-r">—</td>
        <td class="sl-th-r">—</td>
        <td class="sl-th-r">—</td>
        <td class="sl-th-r">—</td>
        <td class="sl-th-r">—</td>
        <td class="sl-th-r">0</td>
        <td class="sl-th-r">—</td>
      </tr>`);
    }});
  }}
  body.innerHTML = rows.join('');
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

let slConfSortKey = 'net';
let slConfSortAsc = false;

function slSortConf(key) {{
  if (slConfSortKey === key) {{
    slConfSortAsc = !slConfSortAsc;
  }} else {{
    slConfSortKey = key;
    // Text column defaults A→Z; numeric columns default high→low.
    slConfSortAsc = (key === 'conf');
  }}
  slRenderConf();
}}

function slRenderConf() {{
  const body = document.getElementById('sl-body-conf');
  if (!body) return;
  const sel = document.getElementById('conf-scope');
  const scope = sel ? sel.value : 'nonconf';
  const bySeason = (typeof CONF_FF !== 'undefined' && CONF_FF[activeSeason]) || {{}};
  const rows = (bySeason[scope] || []).slice();
  if (!rows.length) {{
    body.innerHTML = '<tr><td colspan="14" style="text-align:center;color:#888;padding:18px">No conference data for this season / scope.</td></tr>';
    return;
  }}
  const k = slConfSortKey;
  rows.sort((a, b) => {{
    let av = a[k], bv = b[k];
    if (k === 'conf') {{ av = (av || '').toLowerCase(); bv = (bv || '').toLowerCase(); return slConfSortAsc ? (av < bv ? -1 : av > bv ? 1 : 0) : (av < bv ? 1 : av > bv ? -1 : 0); }}
    av = (av == null || isNaN(av)) ? -Infinity : av;
    bv = (bv == null || isNaN(bv)) ? -Infinity : bv;
    return slConfSortAsc ? av - bv : bv - av;
  }});
  const fmt = (v, d) => (v == null || isNaN(v)) ? '—' : Number(v).toFixed(d);
  body.innerHTML = rows.map(r => {{
    const td = (c, txt, extra) => `<td class="sl-th-r"${{extra ? ` style="${{extra}}"` : ''}}>${{txt}}</td>`;
    return '<tr>'
      + `<td style="text-align:left;font-weight:600">${{r.conf}}</td>`
      + `<td class="sl-th-r">${{r.w}}-${{r.l}}</td>`
      + td('win_pct', (r.win_pct != null ? (r.win_pct * 100).toFixed(1) : '—'))
      + td('net', fmt(r.net, 1), 'border-left:2px solid #555')
      + td('ortg', fmt(r.ortg, 1), 'border-left:2px solid #555')
      + td('efg', fmt(r.efg, 1))
      + td('orb', fmt(r.orb, 1))
      + td('tov', fmt(r.tov, 1))
      + td('ftr', fmt(r.ftr, 1))
      + td('drtg', fmt(r.drtg, 1), 'border-left:2px solid #555')
      + td('d_efg', fmt(r.d_efg, 1))
      + td('d_orb', fmt(r.d_orb, 1))
      + td('d_tov', fmt(r.d_tov, 1))
      + td('d_ftr', fmt(r.d_ftr, 1))
      + '</tr>';
  }}).join('');
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
  // Trends compares all seasons, so make sure they are all loaded first.
  ensureSeasons(Object.keys(SEASON_SOURCES), __slRenderTrendsNow);
}}

function __slRenderTrendsNow() {{
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
  const boxTd = cols === 'fanmatch'
    ? `<td style="text-align:center"><a href="#" onclick="openBoxScore('${{g.date}}','${{g.winner}}','${{g.loser}}');return false" style="color:#0d47a1;font-weight:700;text-decoration:none">Box</a></td>`
    : '';
  return `<tr${{gameGoldCls}}><td class="sl-rank">${{idx + 1}}</td>` +
         `<td class="sl-date-cell">${{g.date}}</td>` +
         slGameCell(g) +
         boxTd +
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
    : '<tr><td colspan="10" style="text-align:center;color:#555;padding:24px">No games on this date</td></tr>';

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
    return html, season_files


def main():
    parser = argparse.ArgumentParser(description="Generate the standalone CCC leaderboard HTML")
    parser.add_argument("--fast", action="store_true", help="Build current-season data only")
    parser.add_argument("--cache", action="store_true", help="Reuse cached datasets when available")
    parser.add_argument("--refresh-cache", action="store_true", help="Rebuild cached datasets")
    parser.add_argument("--output", default=str(OUTPUT), help="Output HTML path")
    args = parser.parse_args()

    use_cache = args.cache or args.refresh_cache

    def dataset(name, builder):
        if use_cache:
            return _cached_json(name, builder, refresh=args.refresh_cache)
        return builder()

    def log_count(label, data, suffix="loaded"):
        print(f"  {len(data)} {label} {suffix}")

    print("Loading current-season datasets...")
    players = dataset("2526_players", lambda: load_players())
    print(f"  {len(players)} players qualify (30% minutes threshold)")
    teams = dataset("2526_teams", lambda: load_teams())
    log_count("teams", teams)
    height_data = dataset("2526_height", lambda: load_height_data(teams))
    print(f"  {len(height_data.get('ranked', []))} teams with roster-height data loaded")
    conf_players = dataset("2526_conf_players", lambda: load_conf_players())
    log_count("conference-only players", conf_players)
    conf_teams = dataset("2526_conf_teams", lambda: load_conf_teams())
    log_count("conference-only teams", conf_teams)
    # Box-derived subset scopes (current season): Last 5 / Last 10 / Playoffs
    last5_teams = dataset("2526_last5_teams", lambda: load_subset_teams(None, "last5"))
    last10_teams = dataset("2526_last10_teams", lambda: load_subset_teams(None, "last10"))
    playoff_teams = dataset("2526_playoff_teams", lambda: load_subset_teams(None, "playoffs"))
    last5_players = dataset("2526_last5_players", lambda: load_subset_players(None, "last5"))
    last10_players = dataset("2526_last10_players", lambda: load_subset_players(None, "last10"))
    playoff_players = dataset("2526_playoff_players", lambda: load_subset_players(None, "playoffs"))
    log_count("last-10 teams", last10_teams)
    rpi_2526 = dataset("2526_rpi", lambda: compute_rpi(STATS_DIR))
    print(f"  {len(rpi_2526)} teams with 2025-26 RPI computed")
    storylines_current = dataset("2526_storylines", lambda: load_storylines())
    print(f"  {storylines_current.get('games_in_system', 0)} 2025-26 storyline games loaded")
    game_boxes = {"2526": dataset("2526_boxes", lambda: build_game_boxes(STATS_DIR))}
    print(f"  {len(game_boxes['2526'])} 2025-26 game box scores loaded")
    team_rosters = {"2526": dataset("2526_rosters", lambda: load_full_rosters(STATS_DIR))}
    print(f"  {len(team_rosters['2526'])} 2025-26 full team rosters loaded")
    conf_ff = {"2526": dataset("2526_conf_ff", lambda: build_conference_four_factors(STATS_DIR))}
    print(f"  {len(conf_ff['2526'].get('full', []))} 2025-26 conference four-factor rows")
    # opponent ratings (season ORtg/DRtg) for per-game lineup opponent adjustment
    _opp_ratings = {t["team"]: {"ortg": t.get("ortg", 0), "drtg": t.get("drtg", 0)}
                    for t in teams if t.get("ortg")}
    # NET ranks for quad classification (same basis as the leaderboard quad table:
    # rank teams with ORtg>0 by net_rtg desc).
    _ranked_net = sorted([t for t in teams if t.get("ortg", 0) > 0],
                         key=lambda t: -t.get("net_rtg", 0))
    _net_ranks = {t["team"]: i + 1 for i, t in enumerate(_ranked_net)}
    moorpark_lineups = build_moorpark_lineups(opp_ratings=_opp_ratings,
                                              net_ranks=_net_ranks, n_teams=len(_ranked_net))
    if moorpark_lineups:
        print(f"  Moorpark lineups: {moorpark_lineups['team_totals']['lineups_tracked']} units, "
              f"{len(moorpark_lineups['players'])} players")
    # Keys to Victory — one entry per team. "windows" picks which season ranges
    # to build: "5yr" = whole coach tenure (2021-26), "cur" = 2025-26 only.
    # Teams whose coach arrived recently / have no stable HC use "cur" only.
    KEYS_TEAMS = [
        {"team": "Moorpark", "coach": "Keith Higgins", "windows": ["5yr", "cur"]},
        {"team": "Allan Hancock", "coach": "Tyson Aye", "windows": ["5yr", "cur"]},
        {"team": "Fullerton", "coach": "Perry Webster", "windows": ["5yr", "cur"]},
        {"team": "San Francisco", "coach": "Justin Labagh", "windows": ["5yr", "cur"]},
        {"team": "Santa Barbara", "coach": "Devin Engebretsen", "windows": ["5yr", "cur"]},
        {"team": "Oxnard", "coach": "Ron McClurkin", "windows": ["5yr", "cur"]},
        {"team": "LA Pierce", "coach": "Charles White", "windows": ["5yr", "cur"]},
        {"team": "Citrus", "coach": "Brett Lauer", "windows": ["5yr", "cur"]},
        {"team": "San Bernardino Valley", "coach": "Quincy Brewer", "windows": ["5yr", "cur"]},
        {"team": "West LA", "coach": "Anthony Jones", "windows": ["5yr", "cur"]},
        {"team": "East Los Angeles", "coach": "John Mosley", "windows": ["5yr", "cur"]},
        {"team": "Mt. San Antonio", "coach": "Michael Fennison", "windows": ["5yr", "cur"]},
        {"team": "Cerritos", "coach": "Russ May", "windows": ["5yr", "cur"]},
        {"team": "Santiago Canyon", "coach": "Todd Dixon", "windows": ["5yr", "cur"]},
        {"team": "San Diego City", "coach": "Mitch Charlens", "windows": ["5yr", "cur"]},
        {"team": "West Valley", "coach": "Danny Yoshikawa", "windows": ["5yr", "cur"]},
        {"team": "Mt. San Jacinto", "coach": "Trent Skinner", "windows": ["5yr", "cur"],
         "seasons": ["2022-23", "2023-24", "2024-25", "2025-26"]},
        {"team": "Cypress", "coach": "Andrew Alhadeff", "windows": ["5yr", "cur"]},
        {"team": "Santa Ana", "coach": "David Breig", "windows": ["5yr", "cur"]},
        {"team": "San Diego Miramar", "coach": "Nick Gehler", "windows": ["5yr", "cur"]},
        {"team": "Palomar", "coach": "Ivan Patterson", "windows": ["5yr", "cur"],
         "seasons": ["2022-23", "2023-24", "2024-25", "2025-26"]},
        {"team": "MiraCosta", "coach": "Rob Robinson", "windows": ["5yr", "cur"],
         "seasons": ["2022-23", "2023-24", "2024-25", "2025-26"]},
        {"team": "Bakersfield", "coach": "Greg McCall", "windows": ["5yr", "cur"],
         "seasons": ["2024-25", "2025-26"]},
        {"team": "Southwestern", "coach": "Tyrone Shelley", "windows": ["5yr", "cur"],
         "seasons": ["2022-23", "2023-24", "2024-25", "2025-26"]},
        {"team": "Sequoias", "coach": "Dallas Jensen", "windows": ["5yr", "cur"]},
        {"team": "Las Positas", "coach": "James Giacomazzi", "windows": ["5yr", "cur"]},
        {"team": "Santa Rosa", "coach": "Craig McMillan", "windows": ["5yr", "cur"]},
        {"team": "Yuba", "coach": "Doug Cornelius", "windows": ["5yr", "cur"]},
        {"team": "Modesto", "coach": "Brice Fantazia", "windows": ["5yr", "cur"],
         "seasons": ["2024-25", "2025-26"]},
        {"team": "San Jose", "coach": "Devin Aye", "windows": ["5yr", "cur"]},
        {"team": "Cosumnes River", "coach": "Jonathan James", "windows": ["5yr", "cur"]},
        {"team": "Columbia", "coach": "Tomas Brock", "windows": ["5yr", "cur"]},
        {"team": "Foothill", "coach": "Mike Reynoso", "windows": ["5yr", "cur"]},
        {"team": "Sierra", "coach": "Aaron Lawrence", "windows": ["5yr", "cur"],
         "seasons": ["2024-25", "2025-26"]},
        {"team": "Chabot", "coach": "Marquis Glenn", "windows": ["5yr", "cur"],
         "seasons": ["2022-23", "2023-24", "2024-25", "2025-26"]},
        {"team": "Antelope Valley", "coach": "John Taylor", "windows": ["5yr", "cur"]},
        {"team": "Cerro Coso", "coach": "Chris Dugan", "windows": ["5yr", "cur"]},
        {"team": "Canyons", "coach": "Howard Fisher", "windows": ["5yr", "cur"]},
        {"team": "Glendale", "coach": "Vigen Jilizian", "windows": ["5yr", "cur"]},
        {"team": "LA Valley", "coach": "Virgil Watson", "windows": ["5yr", "cur"]},
        {"team": "Santa Monica", "coach": "Malik Bray", "windows": ["5yr", "cur"],
         "seasons": ["2023-24", "2024-25", "2025-26"]},
        {"team": "Irvine Valley", "coach": "Jason Garey", "windows": ["5yr", "cur"],
         "seasons": ["2024-25", "2025-26"]},
        {"team": "Saddleback", "coach": "Jeff Oliver", "windows": ["5yr", "cur"]},
        {"team": "Orange Coast", "coach": "Steve Spencer", "windows": ["5yr", "cur"]},
        {"team": "Riverside", "coach": "Andre Wilson", "windows": ["5yr", "cur"],
         "seasons": ["2025-26"]},
        {"team": "Copper Mountain", "coach": "JJ Santa Cruz", "windows": ["5yr", "cur"],
         "seasons": ["2023-24", "2024-25", "2025-26"]},
        {"team": "Desert", "coach": "Robert Romero", "windows": ["5yr", "cur"],
         "seasons": ["2022-23", "2023-24", "2024-25", "2025-26"]},
        {"team": "Victor Valley", "coach": "William Funn", "windows": ["5yr", "cur"],
         "seasons": ["2023-24", "2024-25", "2025-26"]},
        {"team": "Palo Verde", "coach": "Jason Billie", "windows": ["5yr", "cur"],
         "seasons": ["2024-25", "2025-26"]},
        {"team": "Barstow", "coach": "Nicholas Hilton", "windows": ["5yr", "cur"],
         "seasons": ["2025-26"]},
        # First-year coaches: tenure window = 2025-26 only, but still show both
        # dropdown options (tenure + current) even though the data is identical.
        {"team": "Cuesta", "coach": "Jamoni Barber", "windows": ["5yr", "cur"],
         "seasons": ["2025-26"]},
        {"team": "Chaffey", "coach": "Mateu Villakazi", "windows": ["5yr", "cur"],
         "seasons": ["2025-26"]},
        {"team": "Feather River", "coach": "Derek Jensen", "windows": ["5yr", "cur"],
         "seasons": ["2025-26"]},
        {"team": "LA Southwest", "coach": "Mack Cleveland", "windows": ["5yr", "cur"]},
        {"team": "Cabrillo", "coach": "James Page", "windows": ["5yr", "cur"]},
        {"team": "Marin", "coach": "LyRyan Russell", "windows": ["5yr", "cur"]},
        {"team": "San Mateo", "coach": "Mike Marcial", "windows": ["5yr", "cur"]},
        {"team": "Reedley", "coach": "Richard Jennings", "windows": ["5yr", "cur"]},
        {"team": "Ohlone", "coach": "Jordan Lee", "windows": ["5yr", "cur"],
         "seasons": ["2022-23", "2023-24", "2024-25", "2025-26"]},
        {"team": "Diablo Valley", "coach": "Ervin Anderson", "windows": ["5yr", "cur"],
         "seasons": ["2023-24", "2024-25", "2025-26"]},
        {"team": "Lemoore", "coach": "Jovan Joe", "windows": ["5yr", "cur"],
         "seasons": ["2024-25", "2025-26"]},
        {"team": "Redwoods", "coach": "Justin Claus", "windows": ["5yr", "cur"],
         "seasons": ["2025-26"]},
        # Coaches added 2026-06-23 from user (tenure ranges as given).
        {"team": "LA Trade Tech", "coach": "Sherwyn Morgan", "windows": ["5yr", "cur"]},
        {"team": "Contra Costa", "coach": "Miguel Johnson", "windows": ["5yr", "cur"]},
        {"team": "Canada", "coach": "Eddy Harris", "windows": ["5yr", "cur"]},
        {"team": "Los Medanos", "coach": "Derek Domenichelli", "windows": ["5yr", "cur"]},
        {"team": "LA Harbor", "coach": "Tony Carter-Loza", "windows": ["5yr", "cur"]},
        {"team": "Compton", "coach": "Keith Hollimon", "windows": ["5yr", "cur"],
         "seasons": ["2022-23", "2023-24", "2024-25", "2025-26"]},
        {"team": "Pasadena City", "coach": "Spenser Nunes", "windows": ["5yr", "cur"],
         "seasons": ["2025-26"]},
        {"team": "Ventura", "coach": "", "windows": ["cur"]},
    ]
    def _build_team_keys():
        # with_bench=True so the global pool has Bench Pts% → Style Metrics
        # "Bench Points %" gets its Global Win Pct / Global MOV columns too.
        pool5 = load_all_games_keys(LAST_5_KEYS, with_bench=True)
        poolc = load_all_games_keys(["2025-26"], with_bench=True)
        out = {}
        for cfg in KEYS_TEAMS:
            tname, coach = cfg["team"], cfg["coach"]
            windows = {}
            if "5yr" in cfg["windows"]:
                seasons5 = cfg.get("seasons", LAST_5_KEYS)
                o5 = build_keys(tname, seasons5, global_games=pool5)
                if o5:
                    span = (seasons5[0] if len(seasons5) == 1
                            else f"{seasons5[0]} to {seasons5[-1]}")
                    o5["label"] = f"{span} (all under {coach})" if coach else span
                    windows["5yr"] = o5
            if "cur" in cfg["windows"]:
                oc = build_keys(tname, ["2025-26"], global_games=poolc)
                if oc:
                    oc["label"] = "2025-26 only"
                    windows["cur"] = oc
            if windows:
                out[tname] = {"coach": coach, "windows": windows}
        return out
    team_keys = dataset("team_keys", _build_team_keys)
    if team_keys:
        for tname, entry in team_keys.items():
            o = entry["windows"].get("5yr") or entry["windows"].get("cur")
            print(f"  Keys [{tname} / {entry['coach'] or 'no coach'}]: "
                  f"{[k['label'] for k in o['keys']]} ({o['window']}, {o['n_games']} games)")

    empty = []
    empty_storylines = {}
    teams_2024 = conf_teams_2024 = players_2024 = conf_players_2024 = rpi_2425 = empty
    teams_2023 = conf_teams_2023 = players_2023 = conf_players_2023 = rpi_2324 = empty
    teams_2022 = conf_teams_2022 = players_2022 = conf_players_2022 = rpi_2223 = empty
    teams_2021 = conf_teams_2021 = players_2021 = conf_players_2021 = rpi_2122 = empty
    teams_2019 = conf_teams_2019 = players_2019 = conf_players_2019 = rpi_1920 = empty
    teams_1819 = conf_teams_1819 = players_1819 = conf_players_1819 = rpi_1819 = empty
    teams_1718 = conf_teams_1718 = players_1718 = conf_players_1718 = rpi_1718 = empty
    storylines_2024 = storylines_2023 = storylines_2022 = storylines_2021 = empty_storylines
    storylines_2019 = storylines_1819 = storylines_1718 = empty_storylines
    champion_data = {
        "2526": infer_champion(STATS_DIR),
        "2425": infer_champion(STATS_DIR_2024),
        "2324": infer_champion(STATS_DIR_2023),
        "2223": infer_champion(STATS_DIR_2022),
        "2122": infer_champion(STATS_DIR_2021),
        "1920": None,
        "1819": infer_champion(STATS_DIR_1819),
        "1718": infer_champion(STATS_DIR_1718),
    }

    if args.fast:
        print("Fast mode: skipping historical seasons.")
    else:
        season_specs = [
            ("2425", "2024-25", STATS_DIR_2024),
            ("2324", "2023-24", STATS_DIR_2023),
            ("2223", "2022-23", STATS_DIR_2022),
            ("2122", "2021-22", STATS_DIR_2021),
            ("1920", "2019-20", STATS_DIR_2019),
            ("1819", "2018-19", STATS_DIR_1819),
            ("1718", "2017-18", STATS_DIR_1718),
        ]
        loaded = {}
        for key, label, stats_dir in season_specs:
            print(f"Loading {label} datasets...")
            loaded[key] = {
                "teams": dataset(f"{key}_teams", lambda d=stats_dir: load_teams(d)),
                "conf_teams": dataset(f"{key}_conf_teams", lambda d=stats_dir: load_conf_teams(d)),
                "players": dataset(f"{key}_players", lambda d=stats_dir: load_players(d)),
                "conf_players": dataset(f"{key}_conf_players", lambda d=stats_dir: load_conf_players(d)),
                "storylines": dataset(f"{key}_storylines", lambda d=stats_dir: load_storylines(d)),
                "rpi": dataset(f"{key}_rpi", lambda d=stats_dir: compute_rpi(d)),
                "subsets": {
                    "last5_teams": dataset(f"{key}_last5_teams", lambda d=stats_dir: load_subset_teams(d, "last5")),
                    "last10_teams": dataset(f"{key}_last10_teams", lambda d=stats_dir: load_subset_teams(d, "last10")),
                    "playoff_teams": dataset(f"{key}_playoff_teams", lambda d=stats_dir: load_subset_teams(d, "playoffs")),
                    "last5_players": dataset(f"{key}_last5_players", lambda d=stats_dir: load_subset_players(d, "last5")),
                    "last10_players": dataset(f"{key}_last10_players", lambda d=stats_dir: load_subset_players(d, "last10")),
                    "playoff_players": dataset(f"{key}_playoff_players", lambda d=stats_dir: load_subset_players(d, "playoffs")),
                },
            }
            game_boxes[key] = dataset(f"{key}_boxes", lambda d=stats_dir: build_game_boxes(d))
            team_rosters[key] = dataset(f"{key}_rosters", lambda d=stats_dir: load_full_rosters(d))
            conf_ff[key] = dataset(f"{key}_conf_ff", lambda d=stats_dir: build_conference_four_factors(d))
            print(
                f"  {len(loaded[key]['teams'])} teams, "
                f"{len(loaded[key]['players'])} players, "
                f"{loaded[key]['storylines'].get('games_in_system', 0)} storyline games"
            )

        teams_2024 = loaded["2425"]["teams"]
        conf_teams_2024 = loaded["2425"]["conf_teams"]
        players_2024 = loaded["2425"]["players"]
        conf_players_2024 = loaded["2425"]["conf_players"]
        storylines_2024 = loaded["2425"]["storylines"]
        rpi_2425 = loaded["2425"]["rpi"]

        teams_2023 = loaded["2324"]["teams"]
        conf_teams_2023 = loaded["2324"]["conf_teams"]
        players_2023 = loaded["2324"]["players"]
        conf_players_2023 = loaded["2324"]["conf_players"]
        storylines_2023 = loaded["2324"]["storylines"]
        rpi_2324 = loaded["2324"]["rpi"]

        teams_2022 = loaded["2223"]["teams"]
        conf_teams_2022 = loaded["2223"]["conf_teams"]
        players_2022 = loaded["2223"]["players"]
        conf_players_2022 = loaded["2223"]["conf_players"]
        storylines_2022 = loaded["2223"]["storylines"]
        rpi_2223 = loaded["2223"]["rpi"]

        teams_2021 = loaded["2122"]["teams"]
        conf_teams_2021 = loaded["2122"]["conf_teams"]
        players_2021 = loaded["2122"]["players"]
        conf_players_2021 = loaded["2122"]["conf_players"]
        storylines_2021 = loaded["2122"]["storylines"]
        rpi_2122 = loaded["2122"]["rpi"]

        teams_2019 = loaded["1920"]["teams"]
        conf_teams_2019 = loaded["1920"]["conf_teams"]
        players_2019 = loaded["1920"]["players"]
        conf_players_2019 = loaded["1920"]["conf_players"]
        storylines_2019 = loaded["1920"]["storylines"]
        rpi_1920 = loaded["1920"]["rpi"]

        teams_1819 = loaded["1819"]["teams"]
        conf_teams_1819 = loaded["1819"]["conf_teams"]
        players_1819 = loaded["1819"]["players"]
        conf_players_1819 = loaded["1819"]["conf_players"]
        storylines_1819 = loaded["1819"]["storylines"]
        rpi_1819 = loaded["1819"]["rpi"]

        teams_1718 = loaded["1718"]["teams"]
        conf_teams_1718 = loaded["1718"]["conf_teams"]
        players_1718 = loaded["1718"]["players"]
        conf_players_1718 = loaded["1718"]["conf_players"]
        storylines_1718 = loaded["1718"]["storylines"]
        rpi_1718 = loaded["1718"]["rpi"]

    # Subset (Last 5 / Last 10 / Playoffs) datasets by season — current inline, historical lazy.
    subset_by_season = {"2526": {
        "last5_teams": last5_teams, "last10_teams": last10_teams, "playoff_teams": playoff_teams,
        "last5_players": last5_players, "last10_players": last10_players, "playoff_players": playoff_players,
    }}
    if not args.fast:
        for skey in loaded:
            subset_by_season[skey] = loaded[skey]["subsets"]

    html, season_files = generate_html(
        players, teams, conf_players, conf_teams,
        teams_2024=teams_2024, conf_teams_2024=conf_teams_2024,
        players_2024=players_2024, conf_players_2024=conf_players_2024,
        storylines_2024=storylines_2024,
        teams_2023=teams_2023, conf_teams_2023=conf_teams_2023,
        players_2023=players_2023, conf_players_2023=conf_players_2023,
        storylines_2023=storylines_2023,
        teams_2022=teams_2022, conf_teams_2022=conf_teams_2022,
        players_2022=players_2022, conf_players_2022=conf_players_2022,
        storylines_2022=storylines_2022,
        teams_2021=teams_2021, conf_teams_2021=conf_teams_2021,
        players_2021=players_2021, conf_players_2021=conf_players_2021,
        storylines_2021=storylines_2021,
        teams_2019=teams_2019, conf_teams_2019=conf_teams_2019,
        players_2019=players_2019, conf_players_2019=conf_players_2019,
        storylines_2019=storylines_2019,
        teams_1819=teams_1819, conf_teams_1819=conf_teams_1819,
        players_1819=players_1819, conf_players_1819=conf_players_1819,
        storylines_1819=storylines_1819,
        teams_1718=teams_1718, conf_teams_1718=conf_teams_1718,
        players_1718=players_1718, conf_players_1718=conf_players_1718,
        storylines_1718=storylines_1718,
        rpi_data_2526=rpi_2526, rpi_data_2425=rpi_2425,
        rpi_data_2324=rpi_2324, rpi_data_2223=rpi_2223,
        rpi_data_2122=rpi_2122, rpi_data_1920=rpi_1920,
        rpi_data_1819=rpi_1819, rpi_data_1718=rpi_1718,
        height_data=height_data, storylines_current=storylines_current,
        champion_data=champion_data, game_boxes=game_boxes,
        team_rosters=team_rosters, conf_ff=conf_ff,
        moorpark_lineups=moorpark_lineups,
        team_keys=team_keys,
        subset_by_season=subset_by_season,
    )
    output = Path(args.output)
    output.write_text(html)
    season_dir = output.parent / SEASON_DATA_DIR
    season_dir.mkdir(parents=True, exist_ok=True)
    if args.fast:
        # Fast mode only refreshes current-season files; existing past-season
        # files keep serving the other seasons.
        writable = {k: v for k, v in season_files.items()
                    if k in ("boxes_2526.js", "rosters_2526.js")}
        print("Fast mode: past-season data files not rewritten.")
    else:
        writable = season_files
    total = 0
    for filename, content in writable.items():
        (season_dir / filename).write_text(content)
        total += len(content)
    print(f"  Saved: {season_dir}/ ({len(writable)} files, {total // 1024} KB)")
    logo_src = Path("internal_data/team_logos/png")
    if logo_src.exists():
        logo_dest = output.parent / "team_logos"
        logo_dest.mkdir(parents=True, exist_ok=True)
        for logo in logo_src.glob("*.png"):
            shutil.copy2(logo, logo_dest / logo.name)
    print(f"  Saved: {output} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
