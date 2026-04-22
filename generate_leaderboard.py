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
    m, d, y = s.split("/")
    return datetime(int(y), int(m), int(d))


def _sl_date_sort_key(date_str: str) -> tuple:
    try:
        m, d, y = date_str.split("/")
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
        'o_tov': round(to_ / max(fga + 0.44 * fta + to_, 1) * 100, 1),
        'o_or':  round(oreb / max(oreb + o_oreb, 1) * 100, 1),  # opponent's OREB as def rebound
        'o_ftr': round(fta / max(fga, 1) * 100, 1),
        'o_2p':  round((fgm - tpm) / max(fga - tpa, 1) * 100, 1) if (fga - tpa) > 0 else 0.0,
        'o_3p':  round(tpm / max(tpa, 1) * 100, 1) if tpa > 0 else 0.0,
        'd_efg': round((o_fgm + 0.5 * o_tpm) / max(o_fga, 1) * 100, 1),
        'd_tov': round(o_to / max(o_fga + 0.44 * o_fta + o_to, 1) * 100, 1),
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


def build_storylines(stats_dir: Path, top: int = 100, exclude_zero_scores: bool = True,
                     hca_points: float = 3.0, wp_scale: float = 10.0,
                     prior_stats_dir: Path = None) -> dict:
    by_team, team_names = _sl_load_games(stats_dir)
    games = _sl_dedupe(by_team, team_names, exclude_zero_scores)
    priors = _sl_load_priors(prior_stats_dir) if prior_stats_dir is not None else {}
    rows = _sl_enrich(games, team_names, hca_points, wp_scale, priors)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stats_dir": str(stats_dir),
        "games_in_system": len(rows),
        "dominant_wins":  _sl_top_n(rows, "dominance_score", top),
        "upsets":         _sl_top_n(rows, "upset_score", top, predicate=lambda r: r["underdog_gap"] > 0 and r["pregame_winner_games"] >= 5 and r["pregame_loser_games"] >= 5),
        "tension_games":  _sl_top_n(rows, "tension_score", top),
        "bust_games":     _sl_top_n(rows, "bust_score", top),
        "fanmatch_games": sorted(rows, key=lambda r: (_sl_date_sort_key(r["date"]), -r["fanmatch_score"])),
    }

# ---------------------------------------------------------------------------

OUTPUT = Path("wsc_north_leaderboard.html")
STATS_DIR = Path("2025-26 Team Statistics")
STATS_DIR_2024 = Path("2024-25 Team Statistics")
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
        "teams": ["Cypress", "Fullerton", "Irvine Valley", "Orange Coast", "Riverside", "Saddleback", "Santa Ana", "Santiago Canyon"],
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

def load_players(stats_dir=None):
    """Load all qualified players from all teams."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    players = []
    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team in conf_info["teams"]:
            team_dir = stats_dir / conf_name / team
            summary_path = team_dir / "team_summary.json"
            player_path = team_dir / "player_stats.json"
            if not summary_path.exists() or not player_path.exists():
                print(f"  Skipping {team}: missing files")
                continue

            summary = json.load(open(summary_path))
            pdata = json.load(open(player_path))

            team_total_min = summary["totals"]["MIN"]
            min_threshold = team_total_min * 0.40
            games_played = summary["games_played"]

            # Detect fake-minutes teams by total player minutes per game
            total_player_min = sum(p["totals"]["MIN"] for p in pdata["players"])
            avg_player_min_pg = total_player_min / games_played if games_played > 0 else 0
            is_fake = avg_player_min_pg < 100

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

                players.append({
                    "name": clean_name,
                    "school": team,
                    "region": region,
                    "conference": conf_name,
                    "gp": g,
                    "mpg": round(t["MIN"] / g, 1),
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
            team_dir = stats_dir / conf_name / team
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
                enriched_game_ratings.append(entry)

            teams.append({
                "team": team,
                "region": region,
                "conference": conf_name,
                "record": overall,
                "conf": conf,
                "gp": summary.get("games_played", 0),
                "ppg": avgs.get("PTS", 0),
                "opp_ppg": opp_avgs.get("PTS", 0),
                "rpg": avgs.get("REB", 0),
                "orebpg": avgs.get("OREB", 0),
                "drebpg": avgs.get("DREB", 0),
                "apg": avgs.get("AST", 0),
                "spg": avgs.get("STL", 0),
                "bpg": avgs.get("BLK", 0),
                "topg": avgs.get("TO", 0),
                "fgp": round(avgs.get("FGM", 0) / avgs.get("FGA", 1) * 100, 1) if avgs.get("FGA", 0) > 0 else 0.0,
                "twop": round((avgs.get("FGM", 0) - avgs.get("3PM", 0)) / max(avgs.get("FGA", 0) - avgs.get("3PA", 0), 1) * 100, 1) if (avgs.get("FGA", 0) - avgs.get("3PA", 0)) > 0 else 0.0,
                "tpp": round(avgs.get("3PM", 0) / avgs.get("3PA", 1) * 100, 1) if avgs.get("3PA", 0) > 0 else 0.0,
                "ftp": round(avgs.get("FTM", 0) / avgs.get("FTA", 1) * 100, 1) if avgs.get("FTA", 0) > 0 else 0.0,
                "tpa_pct": round(avgs.get("3PA", 0) / avgs.get("FGA", 1) * 100, 1) if avgs.get("FGA", 0) > 0 else 0.0,
                "ts_pct": ta.get("ts_pct", 0),
                "efg_pct": ta.get("efg_pct", 0),
                "tov_pct": ta.get("tov_pct", 0),
                "ft_rate": ta.get("ft_rate", 0),
                "oreb_pct": ta.get("oreb_pct", 0),
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
                # Totals for shooting breakdown
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
                # Game ratings for schedule and game plan
                "game_ratings": enriched_game_ratings,
            })

    teams.sort(key=lambda x: -x["net_rtg"])
    return teams


def load_conf_players(stats_dir=None):
    """Load conference-only qualified players from all teams (40% minutes threshold)."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    players = []
    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team in conf_info["teams"]:
            team_dir = stats_dir / conf_name / team
            conf_path = team_dir / "conference_stats.json"
            if not conf_path.exists():
                continue
            cdata = json.load(open(conf_path))
            gp = cdata.get("games_played", 0)
            if gp == 0:
                continue

            team_total_min = cdata.get("totals", {}).get("MIN", 0)
            min_threshold = team_total_min * 0.40

            # Detect fake-minutes teams
            all_players = cdata.get("players", [])
            total_player_min = sum(p["totals"]["MIN"] for p in all_players)
            avg_player_min_pg = total_player_min / gp if gp > 0 else 0
            is_fake = avg_player_min_pg < 100

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
                players.append({
                    "name": clean_name,
                    "school": team,
                    "region": region,
                    "conference": conf_name,
                    "gp": g,
                    "mpg": round(t["MIN"] / g, 1) if t.get("MIN") else 0,
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
                })
    players.sort(key=lambda x: -x["ppg"])
    return players


def load_conf_teams(stats_dir=None):
    """Load conference-only team stats with computed advanced analytics."""
    if stats_dir is None:
        stats_dir = STATS_DIR
    teams = []
    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team in conf_info["teams"]:
            team_dir = stats_dir / conf_name / team
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

            # Conference ortg/drtg: average of conference game ratings
            if conf_game_ratings:
                in_sys = [g for g in conf_game_ratings if g.get("in_system", True)]
                ratings = in_sys if in_sys else conf_game_ratings
                ortg = round(sum(g["ortg"] for g in ratings) / len(ratings), 1)
                drtg = round(sum(g["drtg"] for g in ratings) / len(ratings), 1)
                poss = round(sum(g.get("possessions", 0) for g in ratings) / len(ratings), 1)
                tempo_games = [g.get("tempo", 0) for g in ratings if g.get("tempo", 0) > 0]
                tempo = round(sum(tempo_games) / len(tempo_games), 1) if tempo_games else 0
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
                "fgp": round(avgs.get("FGM", 0) / avgs.get("FGA", 1) * 100, 1) if avgs.get("FGA", 0) > 0 else 0.0,
                "twop": round((avgs.get("FGM", 0) - avgs.get("3PM", 0)) / max(avgs.get("FGA", 0) - avgs.get("3PA", 0), 1) * 100, 1) if (avgs.get("FGA", 0) - avgs.get("3PA", 0)) > 0 else 0.0,
                "tpp": round(avgs.get("3PM", 0) / avgs.get("3PA", 1) * 100, 1) if avgs.get("3PA", 0) > 0 else 0.0,
                "ftp": round(avgs.get("FTM", 0) / avgs.get("FTA", 1) * 100, 1) if avgs.get("FTA", 0) > 0 else 0.0,
                "tpa_pct": round(avgs.get("3PA", 0) / avgs.get("FGA", 1) * 100, 1) if avgs.get("FGA", 0) > 0 else 0.0,
                "ts_pct": ts_pct,
                "efg_pct": efg_pct,
                "tov_pct": tov_pct,
                "ft_rate": ft_rate,
                "oreb_pct": oreb_pct,
                "possessions": round(poss, 1),
                "ortg": ortg,
                "tempo": tempo,
                "drtg": drtg,
                "net_rtg": net_rtg,
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
    # Seed 2025-26 storylines with decayed 2024-25 NET ratings so early-season
    # games have a meaningful baseline instead of 0.0. The prior fades to zero
    # by game 5 (see _RunningRating). No prior for 2024-25 (no 2023-24 data).
    prior_dir = STATS_DIR_2024 if stats_dir == STATS_DIR else None
    try:
        return build_storylines(stats_dir=stats_dir, top=100, exclude_zero_scores=True,
                                hca_points=3.0, wp_scale=10.0, prior_stats_dir=prior_dir)
    except Exception as e:
        print(f"  Warning: could not load storylines: {e}")
        return {}


def generate_html(players, teams, conf_players, conf_teams, teams_2024=None, conf_teams_2024=None,
                  players_2024=None, conf_players_2024=None, storylines_2024=None):
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
    players_json = json.dumps(players)
    teams_json = json.dumps(teams)
    conf_players_json = json.dumps(conf_players)
    conf_teams_json = json.dumps(conf_teams)
    conf_teams_2024_json = json.dumps(conf_teams_2024)
    players_2024_json = json.dumps(players_2024)
    conf_players_2024_json = json.dumps(conf_players_2024)
    storylines_2024_json = json.dumps(storylines_2024)
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

    # Helper: compute historical daily NET RTG rankings from a teams list
    from collections import defaultdict
    from datetime import datetime as dt_parse
    def compute_daily_ranks(team_list):
        def parse_date(d):
            for fmt in ("%m/%d/%Y", "%m/%d/%y"):
                try:
                    return dt_parse.strptime(d, fmt)
                except ValueError:
                    continue
            return dt_parse(2099, 1, 1)
        events = []
        for t in team_list:
            for gr in t.get("game_ratings", []):
                if gr.get("ortg") and gr.get("drtg") and gr.get("date"):
                    events.append({"date": gr["date"], "team": t["team"],
                                   "ortg": gr["ortg"], "drtg": gr["drtg"]})
        events.sort(key=lambda x: parse_date(x["date"]))
        team_cum = {}
        ranks = {}
        cur_date = None
        def flush(date_str):
            team_nets = []
            for tname, cum in team_cum.items():
                team_nets.append((tname, (cum["sum_ortg"] - cum["sum_drtg"]) / cum["games"]))
            team_nets.sort(key=lambda x: -x[1])
            ranks[date_str] = {tname: i + 1 for i, (tname, _) in enumerate(team_nets)}
        for evt in events:
            d = evt["date"]
            if cur_date is not None and d != cur_date:
                flush(cur_date)
            cur_date = d
            tname = evt["team"]
            if tname not in team_cum:
                team_cum[tname] = {"sum_ortg": 0.0, "sum_drtg": 0.0, "games": 0}
            team_cum[tname]["sum_ortg"] += evt["ortg"]
            team_cum[tname]["sum_drtg"] += evt["drtg"]
            team_cum[tname]["games"] += 1
        if cur_date is not None:
            flush(cur_date)
        return ranks

    # Compute historical daily rankings (team's NET RTG rank as of each game date)
    # Gather all game events: (date_str, team_name, ortg, drtg)
    all_game_events = []
    for t in teams:
        for gr in t.get("game_ratings", []):
            if gr.get("ortg") and gr.get("drtg") and gr.get("date"):
                all_game_events.append({
                    "date": gr["date"],
                    "team": t["team"],
                    "ortg": gr["ortg"],
                    "drtg": gr["drtg"],
                })
    # Parse dates and sort events chronologically
    from datetime import datetime as dt_parse
    def parse_date(d):
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                return dt_parse.strptime(d, fmt)
            except ValueError:
                continue
        return dt_parse(2099, 1, 1)
    all_game_events.sort(key=lambda x: parse_date(x["date"]))
    # Process events to build cumulative stats and daily ranks
    team_cumulative = {}  # team -> {"sum_ortg": float, "sum_drtg": float, "games": int}
    # Pre-seed with decayed 2024-25 priors so early-season ranks aren't purely 0-based.
    # Uses FADE_GAMES virtual prior entries per team, matching the _RunningRating fade window.
    _DR_DECAY = 0.60
    _DR_FADE  = 5
    if teams_2024:
        _v26 = [t for t in teams if t.get("ortg", 0) > 0]
        _v25 = [t for t in teams_2024 if t.get("ortg", 0) > 0]
        if _v26 and _v25:
            _lg_o26 = sum(t["ortg"] for t in _v26) / len(_v26)
            _lg_d26 = sum(t["drtg"] for t in _v26) / len(_v26)
            _lg_o25 = sum(t["ortg"] for t in _v25) / len(_v25)
            _lg_d25 = sum(t["drtg"] for t in _v25) / len(_v25)
            _prior_map = {t["team"]: t for t in _v25}
            for t in teams:
                tname = t["team"]
                if tname in _prior_map:
                    p = _prior_map[tname]
                    seed_o = _lg_o26 + (p["ortg"] - _lg_o25) * _DR_DECAY
                    seed_d = _lg_d26 + (p["drtg"] - _lg_d25) * _DR_DECAY
                    team_cumulative[tname] = {
                        "sum_ortg": seed_o * _DR_FADE,
                        "sum_drtg": seed_d * _DR_FADE,
                        "games":    _DR_FADE,
                    }
    daily_ranks = {}  # date_str -> {team_name: rank}
    current_date = None
    day_batch = []
    def flush_day(date_str):
        """After processing all games on a date, compute ranks for that date."""
        # Compute net_rtg for all teams that have played
        team_nets = []
        for tname, cum in team_cumulative.items():
            avg_net = (cum["sum_ortg"] - cum["sum_drtg"]) / cum["games"]
            team_nets.append((tname, avg_net))
        # Sort by net_rtg descending (best = rank 1)
        team_nets.sort(key=lambda x: -x[1])
        daily_ranks[date_str] = {tname: i + 1 for i, (tname, _) in enumerate(team_nets)}
    for evt in all_game_events:
        d = evt["date"]
        if current_date is not None and d != current_date:
            flush_day(current_date)
        current_date = d
        tname = evt["team"]
        if tname not in team_cumulative:
            team_cumulative[tname] = {"sum_ortg": 0.0, "sum_drtg": 0.0, "games": 0}
        team_cumulative[tname]["sum_ortg"] += evt["ortg"]
        team_cumulative[tname]["sum_drtg"] += evt["drtg"]
        team_cumulative[tname]["games"] += 1
    if current_date is not None:
        flush_day(current_date)
    daily_ranks_json = json.dumps(daily_ranks)

    # Compute 2024-25 daily rankings using the same helper
    daily_ranks_2024 = compute_daily_ranks(teams_2024 or [])
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
    league_avg_2024_json = json.dumps(league_avg_2024)

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
    rel_ratings_2526_json = json.dumps(rel_ratings_2526)
    rel_ratings_2425_json = json.dumps(rel_ratings_2425)

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
    text-align: center;
    margin-bottom: 12px;
    display: none;
  }}
  .sub-toggle-wrap button {{
    padding: 6px 20px;
    font-size: 0.82rem;
    font-weight: 600;
    border: 2px solid #ffa726;
    background: transparent;
    color: #ffa726;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .sub-toggle-wrap button:first-child {{
    border-radius: 6px 0 0 6px;
  }}
  .sub-toggle-wrap button:last-child {{
    border-radius: 0 6px 6px 0;
  }}
  .sub-toggle-wrap button.active {{
    background: #ffa726;
    color: #0a0a0a;
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
      <button id="btn-team" onclick="showView('team')">Team Stats</button>
      <button id="btn-individual" class="active" onclick="showView('individual')">Individual Stats</button>
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
</div>

<h1 id="page-title">Individual Statistics Leaderboard</h1>
<div class="subtitle" id="page-subtitle">2025-26 Season — Per-Game Averages</div>
<div class="season-toggle" id="season-toggle">
  <button class="season-btn" id="btn-season-25" onclick="switchSeason('2425')">25</button>
  <span style="color:#aaa;font-size:0.9rem">|</span>
  <button class="season-btn active" id="btn-season-26" onclick="switchSeason('2526')">26</button>
</div>
<div class="info" id="page-info">{len(players)} qualified players · 40% minutes played minimum · Click any column header to sort · Generated {timestamp}</div>

<div id="individual-view">
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
  <th data-col="efg_pct" data-type="num" data-table="team">eFG%</th>
  <th data-col="oreb_pct" data-type="num" data-table="team">OREB%</th>
  <th data-col="tov_pct" data-type="num" data-table="team">TOV%</th>
  <th data-col="ft_rate" data-type="num" data-table="team">FTR</th>

  <th data-col="fgp" data-type="num" data-table="team">FG%</th>
  <th data-col="twop" data-type="num" data-table="team">2PT%</th>
  <th data-col="tpp" data-type="num" data-table="team">3P%</th>
  <th data-col="ftp" data-type="num" data-table="team">FT%</th>
  <th data-col="ts_pct" data-type="num" data-table="team">TS%</th>
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

  <th data-col="opp_fgp" data-type="num" data-table="def">FG%</th>
  <th data-col="opp_twop" data-type="num" data-table="def">2PT%</th>
  <th data-col="opp_tpp" data-type="num" data-table="def">3P%</th>
  <th data-col="opp_ftp" data-type="num" data-table="def">FT%</th>
  <th data-col="opp_ts_pct" data-type="num" data-table="def">TS%</th>
</tr>
</thead>
<tbody id="team-defense-tbody"></tbody>
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
    <div id="sl-tab-fanmatch" class="sl-tab-content" style="display:none">
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
        <th class="sl-th-r">#</th><th>Date</th><th>Game</th><th>Location</th><th class="sl-th-r">Win Prob</th><th class="sl-th-r">FanMatch</th>
      </tr></thead><tbody id="sl-body-fanmatch"></tbody></table></div></div>
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
  </div>
</div>

<script>
const DATA = {players_json};
const TEAM_DATA = {teams_json};
const LEAGUE_AVG = {league_avg_json};
const TEAM_DATA_2024 = {teams_2024_json};
const LEAGUE_AVG_2024 = {league_avg_2024_json};
const DAILY_RANKS = {daily_ranks_json};
const DAILY_RANKS_2024 = {daily_ranks_2024_json};
const REL_RATINGS = {rel_ratings_2526_json};
const REL_RATINGS_2024 = {rel_ratings_2425_json};
const PLAYER_COUNT = {len(players)};
const TIMESTAMP = '{timestamp}';
const STORYLINES = {storylines_json};
const WAB_DATA = {wab_json};
const WAB_DATA_2024 = {wab_2024_json};
const WAB_SIM_2526 = {wab_sim_2526_json};
const WAB_SIM_2425 = {wab_sim_2425_json};

// Conference-only data
const CONF_DATA = {conf_players_json};
const CONF_TEAM_DATA = {conf_teams_json};
const CONF_TEAM_DATA_2024 = {conf_teams_2024_json};
const DATA_2024 = {players_2024_json};
const CONF_DATA_2024 = {conf_players_2024_json};
const STORYLINES_2024 = {storylines_2024_json};

// Active data references (swapped by toggle)
let activeData = DATA;
let activeTeamData = TEAM_DATA;
let activeLeagueAvg = LEAGUE_AVG;
let activeSeason = '2526';
let confMode = false;

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
  render(getFilteredPlayers());
  renderTeams(getFilteredTeams());
  renderDefense(getFilteredTeams());
  updateInfo();
}}

function toggleConfMode(checked) {{
  confMode = checked;
  if (activeSeason === '2425') {{
    activeData = checked ? CONF_DATA_2024 : DATA_2024;
  }} else {{
    activeData = checked ? CONF_DATA : DATA;
  }}
  if (activeSeason === '2425') {{
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
  const isOffense = document.getElementById('btn-offense') && document.getElementById('btn-offense').classList.contains('active');
  const subLabel = isOffense ? 'Per-Game Averages & Advanced Analytics' : 'Opponent Per-Game Averages & Defensive Analytics';
  if (season === '2425') {{
    activeTeamData = confMode ? CONF_TEAM_DATA_2024 : TEAM_DATA_2024;
    activeData = confMode ? CONF_DATA_2024 : DATA_2024;
    activeLeagueAvg = LEAGUE_AVG_2024;
    document.getElementById('btn-season-25').classList.add('active');
    document.getElementById('btn-season-26').classList.remove('active');
    document.getElementById('page-subtitle').textContent = '2024-25 Season \u2014 ' + subLabel;
  }} else {{
    activeTeamData = confMode ? CONF_TEAM_DATA : TEAM_DATA;
    activeData = confMode ? CONF_DATA : DATA;
    activeLeagueAvg = LEAGUE_AVG;
    document.getElementById('btn-season-25').classList.remove('active');
    document.getElementById('btn-season-26').classList.add('active');
    document.getElementById('page-subtitle').textContent = '2025-26 Season \u2014 ' + subLabel;
  }}
  renderTeams(getFilteredTeams());
  renderDefense(getFilteredTeams());
  render(getFilteredPlayers());
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
  const rb25 = document.getElementById('sl-rate-btn-25');
  const rb26 = document.getElementById('sl-rate-btn-26');
  if (rb25) rb25.classList.toggle('active', season === '2425');
  if (rb26) rb26.classList.toggle('active', season === '2526');
  if (slActiveTab === 'rate') slRenderRate(season);
  // Update individual view subtitle if active
  const indDiv2 = document.getElementById('individual-view');
  if (indDiv2 && indDiv2.style.display !== 'none') {{
    const yr2 = season === '2425' ? '2024-25' : '2025-26';
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
      <td>${{p.name}}</td>
      <td><a href="#" onclick="showTeamDetail('${{p.school}}');return false" style="color:inherit;text-decoration:none">${{schoolDisplay}}</a></td>
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

  render(getFilteredPlayers());
}}

// Click handlers
document.querySelectorAll('th[data-col]').forEach(th => {{
  if (th.dataset.col === 'rank') return;
  th.addEventListener('click', () => doSort(th.dataset.col, th.dataset.type));
}});

// Initial render
render(getFilteredPlayers());
showView('individual');

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
function renderTeams(data) {{
  const tb = document.getElementById('team-tbody');
  tb.innerHTML = '';
  const invert = teamSortType !== 'str' && teamSortDir !== teamSortBest;
  data.forEach((t, i) => {{
    const rank = invert ? data.length - i : i + 1;
    const tr = document.createElement('tr');
    // Always use full-season data for GP, Record, Conf, Opp ORTG, Opp DRTG, SOS, NCSOS
    const _fsPool = activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
    const fs = _fsPool.find(d => d.team === t.team) || t;
    tr.innerHTML = `
      <td>${{rank}}</td>
      <td style="text-align:left;font-weight:700"><a href="#" onclick="showTeamDetail('${{t.team}}');return false" style="color:inherit;text-decoration:none">${{t.team}}</a></td>
      <td>${{fs.gp}}</td>
      <td>${{fs.record}}</td>
      <td>${{fs.conf}}</td>
      <td>${{t.tempo}}</td>
      <td>${{t.ortg}}</td>
      <td>${{t.drtg}}</td>
      <td>${{t.net_rtg}}</td>
      <td style="padding:0 4px"><div class="opp-bar-wrap" data-opptip="${{getOppAdjMsg(t.team, t.opp_adjust)}}"><div style="position:relative;width:50px;height:14px;background:transparent;border-radius:2px"><div style="position:absolute;top:0;height:100%;border-radius:2px;${{t.opp_adjust >= 0 ? `left:50%;width:${{Math.min(Math.abs(t.opp_adjust)/0.35*50,50)}}%;background:#e74c3c` : `right:50%;width:${{Math.min(Math.abs(t.opp_adjust)/0.35*50,50)}}%;background:#3498db`}}"></div><div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:#666"></div></div></div></td>
      <td style="padding:0 4px"><div class="pace-bar-wrap" data-pacetip="${{getPaceAdjMsg(t.team, t.pace_adjust)}}"><div style="position:relative;width:50px;height:14px;background:transparent;border-radius:2px"><div style="position:absolute;top:0;height:100%;border-radius:2px;${{t.pace_adjust >= 0 ? `left:50%;width:${{Math.min(Math.abs(t.pace_adjust)/0.35*50,50)}}%;background:#e67e22` : `right:50%;width:${{Math.min(Math.abs(t.pace_adjust)/0.35*50,50)}}%;background:#3498db`}}"></div><div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:#666"></div></div></div></td>
      <td>${{fs.opp_ortg}}</td>
      <td>${{fs.opp_drtg_sos}}</td>
      <td>${{fs.sos}}</td>
      <td>${{fs.ncsos}}</td>
      <td>${{t.efg_pct}}</td>
      <td>${{t.oreb_pct}}</td>
      <td>${{t.tov_pct}}</td>
      <td>${{t.ft_rate}}</td>
      <td>${{t.fgp.toFixed(1)}}</td>
      <td>${{t.twop.toFixed(1)}}</td>
      <td>${{t.tpp.toFixed(1)}}</td>
      <td>${{t.ftp.toFixed(1)}}</td>
      <td>${{t.ts_pct.toFixed(1)}}</td>
    `;
    if (t.team === 'Moorpark') tr.querySelectorAll('td').forEach(td => td.style.background = '#ffe599');
    tb.appendChild(tr);
  }});
  highlightCol(tb, teamSortCol);
}}

let teamSortCol = 'net_rtg';
let teamSortDir = 'desc';
let teamSortType = 'num';
let teamSortBest = 'desc';

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
  const _fsSortPool = activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
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
  const invert = defSortType !== 'str' && defSortDir !== defSortBest;
  data.forEach((t, i) => {{
    const rank = invert ? data.length - i : i + 1;
    const tr = document.createElement('tr');
    // Always use full-season data for GP, Record, Conf, Opp ORTG, Opp DRTG, SOS, NCSOS
    const _fsPool2 = activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
    const fs = _fsPool2.find(d => d.team === t.team) || t;
    tr.innerHTML = `
      <td>${{rank}}</td>
      <td style="text-align:left;font-weight:700"><a href="#" onclick="showTeamDetail('${{t.team}}');return false" style="color:inherit;text-decoration:none">${{t.team}}</a></td>
      <td>${{fs.gp}}</td>
      <td>${{fs.record}}</td>
      <td>${{fs.conf}}</td>
      <td>${{t.tempo}}</td>
      <td>${{t.ortg}}</td>
      <td>${{t.drtg}}</td>
      <td>${{t.net_rtg}}</td>
      <td style="padding:0 4px"><div class="opp-bar-wrap" data-opptip="${{getOppAdjMsg(t.team, t.opp_adjust)}}"><div style="position:relative;width:50px;height:14px;background:transparent;border-radius:2px"><div style="position:absolute;top:0;height:100%;border-radius:2px;${{t.opp_adjust >= 0 ? `left:50%;width:${{Math.min(Math.abs(t.opp_adjust)/0.35*50,50)}}%;background:#e74c3c` : `right:50%;width:${{Math.min(Math.abs(t.opp_adjust)/0.35*50,50)}}%;background:#3498db`}}"></div><div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:#666"></div></div></div></td>
      <td style="padding:0 4px"><div class="pace-bar-wrap" data-pacetip="${{getPaceAdjMsg(t.team, t.pace_adjust)}}"><div style="position:relative;width:50px;height:14px;background:transparent;border-radius:2px"><div style="position:absolute;top:0;height:100%;border-radius:2px;${{t.pace_adjust >= 0 ? `left:50%;width:${{Math.min(Math.abs(t.pace_adjust)/0.35*50,50)}}%;background:#e67e22` : `right:50%;width:${{Math.min(Math.abs(t.pace_adjust)/0.35*50,50)}}%;background:#3498db`}}"></div><div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:#666"></div></div></div></td>
      <td>${{fs.opp_ortg}}</td>
      <td>${{fs.opp_drtg_sos}}</td>
      <td>${{fs.sos}}</td>
      <td>${{fs.ncsos}}</td>
      <td>${{t.opp_efg_pct}}</td>
      <td>${{t.dreb_pct}}</td>
      <td>${{t.opp_tov_pct}}</td>
      <td>${{t.opp_ft_rate}}</td>
      <td>${{t.opp_fgp.toFixed(1)}}</td>
      <td>${{t.opp_twop.toFixed(1)}}</td>
      <td>${{t.opp_tpp.toFixed(1)}}</td>
      <td>${{t.opp_ftp.toFixed(1)}}</td>
      <td>${{t.opp_ts_pct.toFixed(1)}}</td>
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

  // Hide everything
  document.getElementById('individual-view').style.display = 'none';
  document.getElementById('team-view').style.display = 'none';
  document.getElementById('team-defense-view').style.display = 'none';
  document.getElementById('universe-view').style.display = 'none';
  document.getElementById('storylines-view').style.display = 'none';
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
  const t = TEAM_DATA.find(d => d.team === teamName) || TEAM_DATA_2024.find(d => d.team === teamName);
  if (!t) return;
  const content = document.getElementById('gameplan-content');
  document.getElementById('team-detail-view').style.display = 'none';
  document.getElementById('gameplan-view').style.display = 'block';
  window.scrollTo(0, 0);
  const netRtgRanks = {{}};
  const validT = TEAM_DATA.filter(d => d.ortg > 0).sort((a,b) => b.net_rtg - a.net_rtg);
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
  const _fsData = activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
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
  }};
}}

function buildTeamDetail(t) {{
  const ranks = computeRanks(t.team);
  const total = ranks.total;

  // Full-season data for record and SOS (use active season's full data)
  const _fsSource = activeSeason === '2425' ? TEAM_DATA_2024 : TEAM_DATA;
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
    const _dayRanksSource = activeSeason === '2425' ? DAILY_RANKS_2024 : DAILY_RANKS;
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
    </tr>`;

    // Insert Playoffs banner after the last conference game
    if (idx === lastConfIdx && !playoffBannerInserted && lastConfIdx < games.length - 1) {{
      playoffBannerInserted = true;
      scheduleHtml += `<tr><td colspan="7" style="text-align:center;background:#888;color:#fff;font-weight:700;font-size:0.78rem;padding:4px;letter-spacing:1px">PLAYOFFS</td></tr>`;
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
        <div class="td-sub-title">Strength of Schedule</div>
        <table><tbody>
          ${{srRow('Opp. ORTG', fs.opp_ortg, '', activeLeagueAvg.ortg, ranks.opp_ortg, null, '', '', false, false)}}
          ${{srRow('Opp. DRTG', fs.opp_drtg_sos, '', activeLeagueAvg.drtg, ranks.opp_drtg_sos, null, '', '', false, false)}}
          ${{srRow('Overall', fs.sos, '', activeLeagueAvg.sos, ranks.sos, null, '', '', false, false)}}
          ${{srRow('Non-Conference', fs.ncsos, '', activeLeagueAvg.ncsos, ranks.ncsos, null, '', '', false, false)}}
        </tbody></table>
      </div>
      <div class="td-schedule">
        <div class="td-section-title">${{activeSeason === '2425' ? '2024-25' : '2025-26'}} Schedule</div>
        <table><thead><tr>
          <th style="text-align:left">Date</th><th>Rk</th><th style="text-align:left">Opponent</th>
          <th style="text-align:left">Result</th><th>Loc</th><th>Record</th><th>Conf</th>
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
  const btnInd = document.getElementById('btn-individual');
  const btnTeam = document.getElementById('btn-team');
  const btnUni = document.getElementById('btn-universe');
  const btnSl = document.getElementById('btn-storylines');
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
  document.getElementById('gameplan-view').style.display = 'none';
  document.getElementById('sub-toggle').style.display = 'none';
  document.getElementById('team-defense-view').style.display = 'none';
  document.getElementById('season-toggle').style.display = 'none';
  btnInd.classList.remove('active');
  btnTeam.classList.remove('active');
  btnUni.classList.remove('active');
  btnSl.classList.remove('active');

  document.getElementById('conf-toggle-wrap').style.display = '';
  document.querySelector('.team-search-wrap').style.display = '';

  if (view === 'team') {{
    teamDiv.style.display = 'block';
    btnTeam.classList.add('active');
    document.getElementById('sub-toggle').style.display = 'block';
    document.getElementById('btn-offense').classList.add('active');
    document.getElementById('btn-defense').classList.remove('active');
    filterBar.style.display = 'flex';
    document.getElementById('page-title').style.display = '';
    document.getElementById('page-subtitle').style.display = '';
    document.getElementById('page-info').style.display = '';
    document.getElementById('season-toggle').style.display = 'flex';
    const yr = activeSeason === '2425' ? '2024-25' : '2025-26';
    subtitle.textContent = yr + ' Season \u2014 Per-Game Averages & Advanced Analytics';
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
    filterBar.style.display = 'flex';
    document.getElementById('page-title').style.display = '';
    document.getElementById('page-subtitle').style.display = '';
    document.getElementById('page-info').style.display = '';
    document.getElementById('season-toggle').style.display = 'flex';
    const indYr = activeSeason === '2425' ? '2024-25' : '2025-26';
    subtitle.textContent = indYr + ' Season \u2014 Per-Game Averages';
    updateInfo();
  }}
}}

function showTeamSub(sub) {{
  const offDiv = document.getElementById('team-view');
  const defDiv = document.getElementById('team-defense-view');
  const btnOff = document.getElementById('btn-offense');
  const btnDef = document.getElementById('btn-defense');
  const subtitle = document.getElementById('page-subtitle');
  const yr = activeSeason === '2425' ? '2024-25' : '2025-26';

  if (sub === 'defense') {{
    offDiv.style.display = 'none';
    defDiv.style.display = 'block';
    btnDef.classList.add('active');
    btnOff.classList.remove('active');
    subtitle.textContent = yr + ' Season \u2014 Opponent Per-Game Averages & Defensive Analytics';
  }} else {{
    offDiv.style.display = 'block';
    defDiv.style.display = 'none';
    btnOff.classList.add('active');
    btnDef.classList.remove('active');
    subtitle.textContent = yr + ' Season \u2014 Per-Game Averages & Advanced Analytics';
  }}
}}

// ─── Miscellaneous (Game Attribute Rankings) ──────────────────────
const SL_TABS = [
  {{ id: 'dominance', label: 'Dominance' }},
  {{ id: 'upsets',    label: 'Upsets' }},
  {{ id: 'tension',   label: 'Tension' }},
  {{ id: 'busts',     label: 'Busts' }},
  {{ id: 'fanmatch',  label: 'FanMatch' }},
  {{ id: 'wab',       label: 'WAB' }},
  {{ id: 'rate',      label: 'Rate' }},
];
let slInitialized = false;
let slActiveTab = 'dominance';
let slFanmatchDates = [];
let slFanmatchIdx = 0;

function activeStorylines() {{
  return activeSeason === '2425' ? STORYLINES_2024 : STORYLINES;
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
      const wabYr = activeSeason === '2425' ? '2024-25' : '2025-26';
      title.textContent = wabYr + ' Wins Above Bubble';
      if (countEl) countEl.style.display = 'none';
    }} else if (tab === 'rate') {{
      const yr = activeSeason === '2425' ? '2024-25' : '2025-26';
      title.textContent = yr + ' Relative Ratings (O-Rate / D-Rate / Rel-Rtg)';
      if (countEl) countEl.style.display = 'none';
    }} else {{
      const slYr = activeSeason === '2425' ? '2024-25' : '2025-26';
      title.textContent = slYr + ' game attribute rankings (' + (label || tab) + ')';
      if (countEl) {{
        const n = activeStorylines().games_in_system || 0;
        countEl.textContent = n + ' game' + (n === 1 ? '' : 's') + ' played';
        countEl.style.display = 'block';
      }}
    }}
  }}
}}

let slWabRegion = 'North';
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
    const simSrc = activeSeason === '2425' ? (WAB_SIM_2425 || {{}}) : (WAB_SIM_2526 || {{}});
    rows = (simSrc[region.toLowerCase()] || []).slice();
  }} else {{
    const src = activeSeason === '2425' ? (WAB_DATA_2024 || []) : (WAB_DATA || []);
    rows = src.filter(r => true);
    rows.sort((a, b) => b.wab - a.wab);
  }}
  if (!rows.length) {{
    body.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#555;padding:24px">No data available</td></tr>';
    return;
  }}
  const maxAbsWab = Math.max(...rows.map(r => Math.abs(r.wab)));
  const BUBBLE_RANK = 24;
  const teamSrc = activeSeason === '2425' ? (TEAM_DATA_2024 || []) : (TEAM_DATA || []);
  const netMap = {{}};
  teamSrc.forEach(t => {{ netMap[t.team] = t.net_rtg; }});
  const relSrc = activeSeason === '2425' ? (REL_RATINGS_2024 || []) : (REL_RATINGS || []);
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
    const teamLink = `<a href="#" onclick="showTeamDetail('${{r.team}}');return false" style="color:inherit;text-decoration:none">${{r.team}}</a>`;
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
  const b25 = document.getElementById('sl-rate-btn-25');
  const b26 = document.getElementById('sl-rate-btn-26');
  if (b25) b25.classList.toggle('active', season === '2425');
  if (b26) b26.classList.toggle('active', season === '2526');
  slRenderRate(season);
  const title = document.getElementById('sl-page-title');
  if (title && slActiveTab === 'rate') {{
    const yr = season === '2425' ? '2024-25' : '2025-26';
    title.textContent = yr + ' Relative Ratings (O-Rate / D-Rate / Rel-Rtg)';
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
  const src = (season || slRateSeason) === '2425' ? REL_RATINGS_2024 : REL_RATINGS;
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
      const thCol = th.getAttribute('onclick') ? th.getAttribute('onclick').match(/slSortRate\('(.*?)'\)/)?.[1] : null;
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
    const teamLink = `<a href="#" onclick="showTeamDetail('${{r.team}}');return false" style="color:inherit;text-decoration:none;font-weight:600">${{r.team}}</a>`;
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

function slGameCell(g) {{
  const parts = (g.score || '').split('-');
  const wScore = parts[0] || '', lScore = parts[1] || '';
  const otStr = g.overtimes > 0 ? '<span class="sl-ot"> (' + (g.overtimes > 1 ? g.overtimes : '') + 'OT)</span>' : '';
  const wNet = slNetStr(g.pregame_winner_net);
  const lNet = slNetStr(g.pregame_loser_net);
  const wLink = `<a href="#" onclick="showTeamDetail('${{g.winner}}');return false" style="color:inherit;text-decoration:none">${{g.winner}}</a>`;
  const lLink = `<a href="#" onclick="showTeamDetail('${{g.loser}}');return false" style="color:inherit;text-decoration:none">${{g.loser}}</a>`;
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
    detail = '<td class="sl-detail-cell' + cls + '">' + wpW + '% / ' + wpL + '%</td>';
    value  = '<td class="sl-val-cell">' + g.fanmatch_score + '</td>';
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
  if (!body) return;
  body.innerHTML = fm.length
    ? fm.map((g, i) => slGameRow(g, i, 'fanmatch')).join('')
    : '<tr><td colspan="6" style="text-align:center;color:#555;padding:24px">No games on this date</td></tr>';
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
    teams_2024 = load_teams(STATS_DIR_2024)
    print(f"  {len(teams_2024)} 2024-25 teams loaded")
    conf_teams_2024 = load_conf_teams(STATS_DIR_2024)
    print(f"  {len(conf_teams_2024)} 2024-25 conference-only teams loaded")
    players_2024 = load_players(STATS_DIR_2024)
    print(f"  {len(players_2024)} 2024-25 players loaded")
    conf_players_2024 = load_conf_players(STATS_DIR_2024)
    print(f"  {len(conf_players_2024)} 2024-25 conference-only players loaded")
    storylines_2024 = load_storylines(STATS_DIR_2024)
    print(f"  {storylines_2024.get('games_in_system', 0)} 2024-25 storyline games loaded")

    html = generate_html(players, teams, conf_players, conf_teams, teams_2024=teams_2024, conf_teams_2024=conf_teams_2024,
                         players_2024=players_2024, conf_players_2024=conf_players_2024, storylines_2024=storylines_2024)
    OUTPUT.write_text(html)
    print(f"  Saved: {OUTPUT} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
