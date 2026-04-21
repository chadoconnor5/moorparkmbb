#!/usr/bin/env python3
"""
Generate individual team pages (KenPom-style) for every team.
Each page has a Scouting Report and Schedule section.
"""

from pathlib import Path
import json
import re
import os
import math
from datetime import datetime

STATS_DIR = Path("2025-26 Team Statistics")
OUTPUT_DIR = Path("team_pages")

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

SCHOOL_COLORS = {
    "Moorpark": "#B9D9EB", "Ventura": "#F58120", "Allan Hancock": "#003399",
    "Santa Barbara": "#A6192E", "Cuesta": "#056B41", "Oxnard": "#2BB673",
    "LA Pierce": "#BF2116", "Citrus": "#004371", "West LA": "#000080",
    "Bakersfield": "#CC0000", "Antelope Valley": "#003366", "Canyons": "#ffcf0a",
    "Glendale": "#800000", "LA Valley": "#006341", "Santa Monica": "#003DA5",
    "Fullerton": "#00274C", "Santiago Canyon": "#003B5C", "Riverside": "#F47920",
    "Cypress": "#006747", "Santa Ana": "#002855", "Irvine Valley": "#006B3F",
    "Saddleback": "#CC0000", "Orange Coast": "#F26522", "San Diego City": "#003DA5",
    "Southwestern": "#00573F", "Palomar": "#003366", "San Diego Miramar": "#003B5C",
    "Grossmont": "#002855", "San Diego Mesa": "#003DA5", "Cuyamaca": "#006747",
    "MiraCosta": "#00274C", "Imperial Valley": "#CC0000", "Cerritos": "#003366",
    "LA Southwest": "#8B0000", "Compton": "#003DA5", "El Camino": "#F47920",
    "LA Harbor": "#003B5C", "Long Beach": "#000000", "East Los Angeles": "#CC0000",
    "LA Trade Tech": "#003DA5", "Los Angeles City": "#000000",
    "Mt. San Antonio": "#003366", "Pasadena City": "#CC0000", "Rio Hondo": "#003B5C",
    "San Bernardino Valley": "#003DA5", "Mt. San Jacinto": "#CC0000",
    "Chaffey": "#006747", "Copper Mountain": "#003B5C", "Barstow": "#CC0000",
    "Cerro Coso": "#003366", "Victor Valley": "#CC0000", "Desert": "#003366",
    "Palo Verde": "#006747", "San Francisco": "#006341", "Las Positas": "#003DA5",
    "Chabot": "#CC0000", "Canada": "#003366", "San Mateo": "#003B5C",
    "Ohlone": "#006747", "De Anza": "#003DA5", "Skyline": "#003366",
    "Santa Rosa": "#003DA5", "Cosumnes River": "#006341", "Sierra": "#003366",
    "Modesto": "#003DA5", "San Joaquin Delta": "#006747", "Diablo Valley": "#003B5C",
    "Sacramento City": "#006341", "Folsom Lake": "#003366", "American River": "#CC0000",
    "San Jose": "#003DA5", "West Valley": "#006747", "Cabrillo": "#003366",
    "Foothill": "#CC0000", "Monterey Peninsula": "#003B5C", "Gavilan": "#CC0000",
    "Hartnell": "#003366", "Yuba": "#003DA5", "Marin": "#006341",
    "Contra Costa": "#CC0000", "Merritt": "#003366", "Los Medanos": "#003B5C",
    "Napa Valley": "#006747", "Alameda": "#003DA5", "Mendocino": "#006341",
    "Solano": "#CC0000", "Columbia": "#003366", "Sequoias": "#006747",
    "Merced": "#003DA5", "Lemoore": "#003366", "Reedley": "#CC0000",
    "Fresno": "#CC0000", "Porterville": "#003B5C", "Coalinga": "#003366",
    "Feather River": "#006341", "Redwoods": "#006747", "Butte": "#CC0000",
    "Shasta": "#003366", "Siskiyous": "#003DA5", "Lassen": "#CC0000",
}


def team_slug(name):
    """Convert team name to URL-friendly slug."""
    if not name:
        return "unknown"
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def load_all_teams():
    """Load all team data for rankings and averages."""
    teams = {}
    for conf_name, conf_info in CONFERENCES.items():
        region = conf_info["region"]
        for team_name in conf_info["teams"]:
            team_dir = STATS_DIR / conf_name / team_name
            summary_path = team_dir / "team_summary.json"
            adv_path = team_dir / "advanced_analytics.json"
            gl_path = team_dir / "game_log.json"

            if not summary_path.exists():
                continue

            summary = json.load(open(summary_path))
            adv = json.load(open(adv_path)) if adv_path.exists() else {"team": {}}
            gl = json.load(open(gl_path)) if gl_path.exists() else {"games": []}

            ta = adv.get("team", {})
            avgs = summary.get("averages", {})
            opp_avgs = summary.get("opponent_averages", {})
            totals = summary.get("totals", {})
            opp_totals = summary.get("opponent_totals", {})
            rec = summary.get("record", {})

            overall = ""
            conf_rec = ""
            for k, v in rec.items():
                if "Overall" in k:
                    overall = v
                elif "Conference" in k:
                    conf_rec = v

            teams[team_name] = {
                "team": team_name,
                "conference": conf_name,
                "region": region,
                "record": overall,
                "conf_rec": conf_rec,
                "gp": summary.get("games_played", 0),
                "avgs": avgs,
                "opp_avgs": opp_avgs,
                "totals": totals,
                "opp_totals": opp_totals,
                "advanced": ta,
                "game_ratings": ta.get("game_ratings", []),
                "game_log": gl.get("games", []),
            }
    return teams


def compute_league_averages(all_teams):
    """Compute league-wide averages for all stats."""
    adv_keys = ['efg_pct', 'tov_pct', 'oreb_pct', 'ft_rate', 'ts_pct',
                'tempo', 'ortg', 'drtg', 'net_rtg',
                'opp_efg_pct', 'dreb_pct', 'opp_tov_pct', 'opp_ft_rate', 'opp_ts_pct',
                'sos', 'ncsos', 'possessions']

    sums = {k: 0.0 for k in adv_keys}
    count = 0
    for t in all_teams.values():
        ta = t["advanced"]
        if ta.get("ortg", 0) == 0:
            continue
        count += 1
        for k in adv_keys:
            sums[k] += ta.get(k, 0)

    avg = {k: round(sums[k] / max(count, 1), 1) for k in adv_keys}

    # Shooting averages from totals
    total_fgm = sum(t["totals"].get("FGM", 0) for t in all_teams.values())
    total_fga = sum(t["totals"].get("FGA", 0) for t in all_teams.values())
    total_3pm = sum(t["totals"].get("3PM", 0) for t in all_teams.values())
    total_3pa = sum(t["totals"].get("3PA", 0) for t in all_teams.values())
    total_ftm = sum(t["totals"].get("FTM", 0) for t in all_teams.values())
    total_fta = sum(t["totals"].get("FTA", 0) for t in all_teams.values())
    total_stl = sum(t["totals"].get("STL", 0) for t in all_teams.values())
    total_blk = sum(t["totals"].get("BLK", 0) for t in all_teams.values())
    total_to = sum(t["totals"].get("TO", 0) for t in all_teams.values())

    avg["fg_pct"] = round(total_fgm / max(total_fga, 1) * 100, 1)
    avg["3p_pct"] = round(total_3pm / max(total_3pa, 1) * 100, 1)
    avg["ft_pct"] = round(total_ftm / max(total_fta, 1) * 100, 1)
    avg["2p_pct"] = round((total_fgm - total_3pm) / max(total_fga - total_3pa, 1) * 100, 1)
    avg["3pa_rate"] = round(total_3pa / max(total_fga, 1) * 100, 1)

    # Per-game averages
    total_games = sum(t["gp"] for t in all_teams.values())
    avg["ppg"] = round(sum(t["totals"].get("PTS", 0) for t in all_teams.values()) / max(total_games, 1), 1)
    avg["opp_ppg"] = round(sum(t["opp_totals"].get("PTS", 0) for t in all_teams.values()) / max(total_games, 1), 1)
    avg["stl_pct"] = round(total_stl / max(sum(t["advanced"].get("possessions", 0) * t["gp"] for t in all_teams.values() if t["advanced"].get("possessions", 0) > 0), 1) * 100, 1)
    avg["blk_pct"] = round(total_blk / max(sum(t["opp_totals"].get("FGA", 0) - t["opp_totals"].get("3PA", 0) for t in all_teams.values()), 1) * 100, 1)

    return avg


def compute_net_rtg_rankings(all_teams):
    """Rank all teams by net_rtg, return dict of team -> rank."""
    valid = [(name, t["advanced"].get("net_rtg", 0))
             for name, t in all_teams.items() if t["advanced"].get("ortg", 0) > 0]
    valid.sort(key=lambda x: -x[1])
    return {name: i + 1 for i, (name, _) in enumerate(valid)}


def compute_stat_rankings(all_teams, key, low_is_better=False):
    """Rank all teams by a specific stat."""
    valid = [(name, t["advanced"].get(key, 0))
             for name, t in all_teams.items() if t["advanced"].get("ortg", 0) > 0]
    valid.sort(key=lambda x: x[1] if low_is_better else -x[1])
    return {name: i + 1 for i, (name, _) in enumerate(valid)}


def color_cell(value, rank, total, fmt=".1f", low_is_better=False):
    """Return HTML for a colored cell based on rank (green=best, red=worst)."""
    t_val = (rank - 1) / max(total - 1, 1)
    if t_val <= 0.5:
        p = t_val / 0.5
        r = int(255 * p)
        g = 255
        b = int(255 * p)
    else:
        p = (t_val - 0.5) / 0.5
        r = 255
        g = int(255 * (1 - p))
        b = int(255 * (1 - p))
    bg = f"rgb({r},{g},{b})"
    formatted = f"{value:{fmt}}" if isinstance(value, float) else str(value)
    return f'<td style="background:{bg};text-align:center;font-weight:700">{formatted} <sub>{rank}</sub></td>'


def plain_cell(value, fmt=".1f"):
    formatted = f"{value:{fmt}}" if isinstance(value, float) else str(value)
    return f'<td style="text-align:center">{formatted}</td>'


# ── Game Plan helpers ────────────────────────────────────────────────────────

def pearson_corr(xs, ys):
    n = len(xs)
    if n < 4:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return num / (sx * sy)


def corr_tooltip_text(r100, stat_label, is_ortg):
    if r100 is None:
        return "Not enough games to calculate"
    abs_r = abs(r100) / 100
    r = r100 / 100
    if abs_r < 0.10:
        eff = "offensive" if is_ortg else "defensive"
        return f"{stat_label}: essentially no relationship with {eff} efficiency this season"
    if abs_r >= 0.70:
        strength = "very strong"
    elif abs_r >= 0.50:
        strength = "moderate"
    elif abs_r >= 0.30:
        strength = "mild"
    else:
        strength = "weak"
    if is_ortg:
        if r > 0:
            return f"{stat_label}: {strength} positive link — when this is high, offensive efficiency tends to be high too"
        else:
            return f"{stat_label}: {strength} negative link — when this is high, offensive efficiency tends to suffer"
    else:
        if r < 0:
            return f"{stat_label}: {strength} positive link — when this is high, defensive efficiency tends to improve (DRTG drops)"
        else:
            return f"{stat_label}: {strength} negative link — when this is high, defensive efficiency tends to worsen (DRTG rises)"


def compute_game_ff(game):
    ts = game.get('team_stats', {})
    os_ = game.get('opponent_stats', {})
    if not ts or not os_:
        return None
    fga = ts.get('FGA', 0)
    if fga == 0:
        return None
    fgm = ts.get('FGM', 0)
    tpm = ts.get('3PM', 0)
    tpa = ts.get('3PA', 0)
    fta = ts.get('FTA', 0)
    oreb = ts.get('OREB', 0)
    dreb = ts.get('DREB', 0)
    to_ = ts.get('TO', 0)
    pts = ts.get('PTS', 0)

    o_fga = os_.get('FGA', 0)
    o_fgm = os_.get('FGM', 0)
    o_tpm = os_.get('3PM', 0)
    o_tpa = os_.get('3PA', 0)
    o_fta = os_.get('FTA', 0)
    o_oreb = os_.get('OREB', 0)
    o_dreb = os_.get('DREB', 0)
    o_to = os_.get('TO', 0)
    o_pts = os_.get('PTS', 0)

    min_ = max(game.get('MIN', 40), 40)
    t_poss = fga - oreb + to_ + 0.44 * fta
    o_poss = o_fga - o_oreb + o_to + 0.44 * o_fta
    poss = (t_poss + o_poss) / 2.0
    if poss <= 0:
        return None

    pace = round(poss * (40.0 / min_), 1)
    ortg = round(pts / poss * 100, 1)
    drtg = round(o_pts / poss * 100, 1)

    o_efg = round((fgm + 0.5 * tpm) / max(fga, 1) * 100, 1)
    o_tov = round(to_ / max(fga + 0.44 * fta + to_, 1) * 100, 1)
    o_or = round(oreb / max(oreb + o_dreb, 1) * 100, 1)
    o_ftr = round(fta / max(fga, 1) * 100, 1)
    o_2p = round((fgm - tpm) / max(fga - tpa, 1) * 100, 1) if (fga - tpa) > 0 else 0.0
    o_3p = round(tpm / max(tpa, 1) * 100, 1) if tpa > 0 else 0.0

    d_efg = round((o_fgm + 0.5 * o_tpm) / max(o_fga, 1) * 100, 1)
    d_tov = round(o_to / max(o_fga + 0.44 * o_fta + o_to, 1) * 100, 1)
    d_or = round(o_oreb / max(o_oreb + dreb, 1) * 100, 1)
    d_ftr = round(o_fta / max(o_fga, 1) * 100, 1)
    d_2p = round((o_fgm - o_tpm) / max(o_fga - o_tpa, 1) * 100, 1) if (o_fga - o_tpa) > 0 else 0.0
    d_3p = round(o_tpm / max(o_tpa, 1) * 100, 1) if o_tpa > 0 else 0.0

    return {
        'pace': pace, 'ortg': ortg, 'drtg': drtg,
        'o_efg': o_efg, 'o_tov': o_tov, 'o_or': o_or, 'o_ftr': o_ftr, 'o_2p': o_2p, 'o_3p': o_3p,
        'd_efg': d_efg, 'd_tov': d_tov, 'd_or': d_or, 'd_ftr': d_ftr, 'd_2p': d_2p, 'd_3p': d_3p,
    }

def generate_team_page(team_name, team_data, all_teams, league_avg, rankings, timestamp):
    """Generate HTML for a single team page."""
    ta = team_data["advanced"]
    avgs = team_data["avgs"]
    opp_avgs = team_data["opp_avgs"]
    totals = team_data["totals"]
    opp_totals = team_data["opp_totals"]
    gp = team_data["gp"]
    conference = team_data["conference"]
    region = team_data["region"]
    record = team_data["record"]
    conf_rec = team_data["conf_rec"]
    game_ratings = team_data["game_ratings"]
    game_log = team_data["game_log"]

    net_rank = rankings["net_rtg"].get(team_name, "—")
    total_teams = len([t for t in all_teams.values() if t["advanced"].get("ortg", 0) > 0])

    school_color = SCHOOL_COLORS.get(team_name, "#003DA5")
    slug = team_slug(team_name)

    # Compute team-specific stats
    fg_pct = round(totals.get("FGM", 0) / max(totals.get("FGA", 1), 1) * 100, 1)
    three_pct = round(totals.get("3PM", 0) / max(totals.get("3PA", 1), 1) * 100, 1)
    ft_pct = round(totals.get("FTM", 0) / max(totals.get("FTA", 1), 1) * 100, 1)
    two_pct = round((totals.get("FGM", 0) - totals.get("3PM", 0)) / max(totals.get("FGA", 0) - totals.get("3PA", 0), 1) * 100, 1)
    tpa_rate = round(totals.get("3PA", 0) / max(totals.get("FGA", 1), 1) * 100, 1)

    opp_fg_pct = round(opp_totals.get("FGM", 0) / max(opp_totals.get("FGA", 1), 1) * 100, 1)
    opp_three_pct = round(opp_totals.get("3PM", 0) / max(opp_totals.get("3PA", 1), 1) * 100, 1)
    opp_ft_pct = round(opp_totals.get("FTM", 0) / max(opp_totals.get("FTA", 1), 1) * 100, 1)
    opp_two_pct = round((opp_totals.get("FGM", 0) - opp_totals.get("3PM", 0)) / max(opp_totals.get("FGA", 0) - opp_totals.get("3PA", 0), 1) * 100, 1)
    opp_tpa_rate = round(opp_totals.get("3PA", 0) / max(opp_totals.get("FGA", 1), 1) * 100, 1)

    possessions = ta.get("possessions", 0)
    total_poss = possessions * gp if possessions > 0 else 1
    stl_pct = round(totals.get("STL", 0) / max(total_poss, 1) * 100, 1)
    blk_pct = round(totals.get("BLK", 0) / max(opp_totals.get("FGA", 0) - opp_totals.get("3PA", 0), 1) * 100, 1)
    opp_stl_pct = round(opp_totals.get("STL", 0) / max(total_poss, 1) * 100, 1)
    opp_blk_pct = round(opp_totals.get("BLK", 0) / max(totals.get("FGA", 0) - totals.get("3PA", 0), 1) * 100, 1)

    # Build schedule rows
    # We need to compute a running NET RTG rank for opponents at game time
    # For simplicity, use current rankings
    net_rtg_ranks = rankings["net_rtg"]

    schedule_rows = []
    wins = 0
    losses = 0
    conf_wins = 0
    conf_losses = 0

    for i, gr in enumerate(game_ratings):
        opp = gr.get("canonical_opponent", gr.get("opponent", ""))
        opp_rank = net_rtg_ranks.get(opp, "—")
        opp_net = all_teams[opp]["advanced"].get("net_rtg", 0) if opp in all_teams else None
        opp_net_str = f"{opp_net:+.1f}" if opp_net is not None else ""

        result = gr.get("result", "")
        team_score = gr.get("team_score", 0)
        opp_score = gr.get("opponent_score", 0)
        location = gr.get("location", "")
        is_conf = gr.get("is_conference", False)
        date_str = gr.get("date", "")

        if result == "W":
            wins += 1
            if is_conf:
                conf_wins += 1
        elif result == "L":
            losses += 1
            if is_conf:
                conf_losses += 1

        running_rec = f"{wins}-{losses}"
        running_conf = f"{conf_wins}-{conf_losses}" if is_conf or conf_wins + conf_losses > 0 else ""

        # Color the result
        if result == "W":
            result_color = "#2e7d32"
            result_str = f"W, {team_score}-{opp_score}"
        elif result == "L":
            result_color = "#c62828"
            result_str = f"L, {team_score}-{opp_score}"
        else:
            result_color = "#333"
            result_str = f"{team_score}-{opp_score}"

        loc_str = location
        opp_link = f'<a href="{team_slug(opp)}.html" style="color:#000;text-decoration:none;font-weight:600">{opp}</a>'
        opp_net_html = f' <span style="font-size:0.75rem;color:#666">{opp_net_str}</span>' if opp_net_str else ""
        conf_marker = " *" if is_conf else ""

        schedule_rows.append(f"""<tr>
  <td style="text-align:left;white-space:nowrap">{date_str}</td>
  <td style="text-align:center">{opp_rank if opp_rank != '—' else ''}</td>
  <td style="text-align:left">{opp_link}{opp_net_html}{conf_marker}</td>
  <td style="text-align:left;color:{result_color};font-weight:600">{result_str}</td>
  <td style="text-align:center">{loc_str}</td>
  <td style="text-align:center">{running_rec}</td>
  <td style="text-align:center">{running_conf}</td>
</tr>""")

    schedule_html = "\n".join(schedule_rows)

    # Scouting report rows
    def sr_row(label, off_val, def_val, avg_val, off_totals="", def_totals="", off_rank=None, def_rank=None, off_low=False, def_low=False):
        """Build a scouting report row with colored offense/defense cells."""
        if off_rank is not None:
            off_cell = color_cell(off_val, off_rank, total_teams, low_is_better=off_low)
        else:
            off_cell = plain_cell(off_val)

        if def_rank is not None:
            def_cell = color_cell(def_val, def_rank, total_teams, low_is_better=def_low)
        else:
            def_cell = plain_cell(def_val)

        return f"""<tr>
  <td style="text-align:right;font-weight:600;padding-right:12px">{label}</td>
  {off_cell}
  <td style="text-align:center;font-size:0.8rem;color:#888">{off_totals}</td>
  {def_cell}
  <td style="text-align:center;font-size:0.8rem;color:#888">{def_totals}</td>
  <td style="text-align:center;color:#666">{avg_val}</td>
</tr>"""

    # Rankings for each stat
    def get_rank(key, low=False):
        return rankings.get(key, {}).get(team_name, total_teams)

    ortg_rank = get_rank("ortg")
    drtg_rank = get_rank("drtg")
    tempo_rank = get_rank("tempo")
    net_rank_val = get_rank("net_rtg")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{team_name} - Team Profile 2025-26</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0a0a0a;
    color: #000;
    padding: 20px;
  }}
  a {{ text-decoration: none; }}
  .back-link {{
    color: #4fc3f7;
    font-size: 0.85rem;
    margin-bottom: 12px;
    display: inline-block;
  }}
  .back-link:hover {{ text-decoration: underline; }}
  .team-header {{
    text-align: center;
    background: #1a1a2e;
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 20px;
  }}
  .team-header h1 {{
    color: {school_color};
    font-size: 2rem;
    margin-bottom: 4px;
  }}
  .team-header .rank {{
    color: #4fc3f7;
    font-size: 1.1rem;
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .team-header .meta {{
    color: #ccc;
    font-size: 0.9rem;
  }}
  .team-header .record {{
    color: #fff;
    font-size: 1.2rem;
    font-weight: 700;
    margin-top: 6px;
  }}
  .content {{
    display: flex;
    gap: 24px;
    max-width: 1200px;
    margin: 0 auto;
    flex-wrap: wrap;
  }}
  .scouting-report {{
    flex: 0 0 480px;
    background: #fff;
    border-radius: 8px;
    padding: 16px;
    border: 1px solid #ccc;
  }}
  .schedule-section {{
    flex: 1;
    min-width: 400px;
    background: #fff;
    border-radius: 8px;
    padding: 16px;
    border: 1px solid #ccc;
  }}
  .section-title {{
    font-size: 1rem;
    font-weight: 700;
    text-align: center;
    margin-bottom: 10px;
    color: #000;
    border-bottom: 2px solid #333;
    padding-bottom: 6px;
  }}
  .sub-title {{
    font-size: 0.82rem;
    font-weight: 700;
    text-align: center;
    margin: 10px 0 4px;
    color: #444;
    border-bottom: 1px solid #ddd;
    padding-bottom: 3px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
  }}
  th {{
    background: #1a1a2e;
    color: #fff;
    padding: 6px 8px;
    text-align: center;
    font-size: 0.78rem;
    border-bottom: 2px solid #333;
  }}
  td {{
    padding: 5px 8px;
    border-bottom: 1px solid #eee;
    font-size: 0.82rem;
  }}
  tr:hover td {{ background: #f0f0f0; }}
  sub {{
    font-size: 0.65rem;
    color: #555;
  }}
  .scouting-report td {{ white-space: nowrap; }}
  .schedule-section td {{ white-space: nowrap; }}
  .generated {{
    text-align: center;
    color: #888;
    font-size: 0.75rem;
    margin-top: 16px;
  }}
  @media (max-width: 900px) {{
    .content {{ flex-direction: column; }}
    .scouting-report {{ flex: 1; }}
  }}
</style>
</head>
<body>

<a class="back-link" href="wsc_north_leaderboard.html">← Back to Leaderboard</a>

<div class="team-header">
  <div class="rank">#{net_rank_val} NET RTG</div>
  <h1>{team_name}</h1>
  <div class="meta">{conference} · {region} Region</div>
  <div class="record">{record} Overall &nbsp;|&nbsp; {conf_rec} Conference</div>
</div>

<div class="content">

<div class="scouting-report">
  <div class="section-title">Scouting Report &nbsp;<a href="{slug}_gameplan.html" style="color:#4fc3f7;font-size:0.8rem;font-weight:400">Game Plan</a></div>

  <table>
    <thead>
      <tr>
        <th style="text-align:right">Category</th>
        <th>Offense</th>
        <th></th>
        <th>Defense</th>
        <th></th>
        <th>Avg</th>
      </tr>
    </thead>
    <tbody>
      {sr_row("Adj. Efficiency",
              ta.get("ortg", 0), ta.get("drtg", 0), league_avg.get("ortg", 0),
              off_rank=get_rank("ortg"), def_rank=get_rank("drtg"),
              off_low=False, def_low=True)}
      {sr_row("Adj. Tempo",
              ta.get("tempo", 0), "", league_avg.get("tempo", 0),
              off_rank=get_rank("tempo"))}
    </tbody>
  </table>

  <div class="sub-title">Four Factors</div>
  <table>
    <tbody>
      {sr_row("Effective FG%",
              ta.get("efg_pct", 0), ta.get("opp_efg_pct", 0), league_avg.get("efg_pct", 0),
              off_rank=get_rank("efg_pct"), def_rank=get_rank("opp_efg_pct"),
              off_low=False, def_low=True)}
      {sr_row("Turnover %",
              ta.get("tov_pct", 0), ta.get("opp_tov_pct", 0), league_avg.get("tov_pct", 0),
              off_rank=get_rank("tov_pct"), def_rank=get_rank("opp_tov_pct"),
              off_low=True, def_low=False)}
      {sr_row("Off. Reb. %",
              ta.get("oreb_pct", 0), ta.get("dreb_pct", 0), league_avg.get("oreb_pct", 0),
              off_rank=get_rank("oreb_pct"), def_rank=get_rank("dreb_pct"),
              off_low=False, def_low=False)}
      {sr_row("FT Rate",
              ta.get("ft_rate", 0), ta.get("opp_ft_rate", 0), league_avg.get("ft_rate", 0),
              off_rank=get_rank("ft_rate"), def_rank=get_rank("opp_ft_rate"),
              off_low=False, def_low=True)}
    </tbody>
  </table>

  <div class="sub-title">Shooting</div>
  <table>
    <tbody>
      {sr_row("FG%", fg_pct, opp_fg_pct, league_avg.get("fg_pct", 0),
              off_totals=f"{totals.get('FGM',0)} {totals.get('FGA',0)}",
              def_totals=f"{opp_totals.get('FGM',0)} {opp_totals.get('FGA',0)}")}
      {sr_row("2P%", two_pct, opp_two_pct, league_avg.get("2p_pct", 0),
              off_totals=f"{totals.get('FGM',0)-totals.get('3PM',0)} {totals.get('FGA',0)-totals.get('3PA',0)}",
              def_totals=f"{opp_totals.get('FGM',0)-opp_totals.get('3PM',0)} {opp_totals.get('FGA',0)-opp_totals.get('3PA',0)}")}
      {sr_row("3P%", three_pct, opp_three_pct, league_avg.get("3p_pct", 0),
              off_totals=f"{totals.get('3PM',0)} {totals.get('3PA',0)}",
              def_totals=f"{opp_totals.get('3PM',0)} {opp_totals.get('3PA',0)}")}
      {sr_row("FT%", ft_pct, opp_ft_pct, league_avg.get("ft_pct", 0),
              off_totals=f"{totals.get('FTM',0)} {totals.get('FTA',0)}",
              def_totals=f"{opp_totals.get('FTM',0)} {opp_totals.get('FTA',0)}")}
      {sr_row("TS%", ta.get("ts_pct", 0), ta.get("opp_ts_pct", 0), league_avg.get("ts_pct", 0),
              off_rank=get_rank("ts_pct"), def_rank=get_rank("opp_ts_pct"),
              off_low=False, def_low=True)}
    </tbody>
  </table>

  <div class="sub-title">Style</div>
  <table>
    <tbody>
      {sr_row("3PA Rate", tpa_rate, opp_tpa_rate, league_avg.get("3pa_rate", 0))}
      {sr_row("Block%", blk_pct, opp_blk_pct, league_avg.get("blk_pct", 0))}
      {sr_row("Steal%", stl_pct, opp_stl_pct, league_avg.get("stl_pct", 0))}
    </tbody>
  </table>

  <div class="sub-title">Strength of Schedule</div>
  <table>
    <tbody>
      {sr_row("Overall", ta.get("sos", 0), "", league_avg.get("sos", 0),
              off_rank=get_rank("sos"))}
      {sr_row("Non-Conference", ta.get("ncsos", 0), "", league_avg.get("ncsos", 0),
              off_rank=get_rank("ncsos"))}
    </tbody>
  </table>
</div>

<div class="schedule-section">
  <div class="section-title">2025-26 Schedule</div>
  <table>
    <thead>
      <tr>
        <th style="text-align:left">Date</th>
        <th>Rk</th>
        <th style="text-align:left">Opponent</th>
        <th style="text-align:left">Result</th>
        <th>Loc</th>
        <th>Record</th>
        <th>Conf</th>
      </tr>
    </thead>
    <tbody>
{schedule_html}
    </tbody>
  </table>
  <div style="font-size:0.75rem;color:#888;margin-top:8px">
    Rk = Opponent's current NET RTG rank &nbsp;|&nbsp; * = Conference game
  </div>
</div>

</div>

<div class="generated">Generated {timestamp}</div>

</body>
</html>"""
    return html


def generate_gameplan_page(team_name, team_data, all_teams, rankings, timestamp):
    """Generate a KenPom-style game plan page with game-by-game four factors and correlations."""
    school_color = SCHOOL_COLORS.get(team_name, "#003DA5")
    conference = team_data["conference"]
    region = team_data["region"]
    record = team_data["record"]
    conf_rec = team_data["conf_rec"]
    game_log = team_data["game_log"]
    slug = team_slug(team_name)
    net_rank = rankings["net_rtg"].get(team_name, "—")
    net_rtg_ranks = rankings["net_rtg"]

    COL_KEYS = ['pace', 'ortg', 'o_efg', 'o_tov', 'o_or', 'o_ftr', 'o_2p', 'o_3p',
                'drtg', 'd_efg', 'd_tov', 'd_or', 'd_ftr', 'd_2p', 'd_3p']
    STAT_LABELS = {
        'pace': 'Pace', 'ortg': 'Off Eff', 'o_efg': 'Off eFG%', 'o_tov': 'Off TO%',
        'o_or': 'Off OR%', 'o_ftr': 'Off FTR', 'o_2p': 'Off 2P%', 'o_3p': 'Off 3P%',
        'drtg': 'Def Eff', 'd_efg': 'Def eFG%', 'd_tov': 'Def TO%',
        'd_or': 'Def OR%', 'd_ftr': 'Def FTR', 'd_2p': 'Def 2P%', 'd_3p': 'Def 3P%',
    }

    col_data = {k: [] for k in COL_KEYS}
    ortg_vals = []
    drtg_vals = []
    game_rows_html = []

    for game in game_log:
        ff = compute_game_ff(game)
        date_str = game.get('date', '')
        opp = game.get('opponent', '')
        result = game.get('result', '')
        t_score = game.get('team_score', 0)
        o_score = game.get('opponent_score', 0)
        is_conf = game.get('is_conference', False)

        opp_rank = net_rtg_ranks.get(opp, '')
        opp_link = f'<a href="{team_slug(opp)}.html" style="color:#000;text-decoration:none;font-weight:600">{opp}</a>'
        if is_conf:
            opp_link += ' <span style="color:#888">*</span>'

        if result == 'W':
            row_bg = 'background:#e8f5e9'
            result_cell = f'<td style="text-align:center"><span style="font-weight:700;color:#2e7d32">W</span>, {t_score}-{o_score}</td>'
        elif result == 'L':
            row_bg = 'background:#fce8e8'
            result_cell = f'<td style="text-align:center"><span style="font-weight:700;color:#c62828">L</span>, {t_score}-{o_score}</td>'
        else:
            row_bg = ''
            result_cell = f'<td style="text-align:center">{t_score}-{o_score}</td>'

        if ff:
            def _f(v): return f'{v:.1f}'
            cells = (
                f'<td style="text-align:center">{_f(ff["pace"])}</td>'
                f'<td style="text-align:center;font-weight:700">{_f(ff["ortg"])}</td>'
                f'<td style="text-align:center">{_f(ff["o_efg"])}</td>'
                f'<td style="text-align:center">{_f(ff["o_tov"])}</td>'
                f'<td style="text-align:center">{_f(ff["o_or"])}</td>'
                f'<td style="text-align:center">{_f(ff["o_ftr"])}</td>'
                f'<td style="text-align:center">{_f(ff["o_2p"])}</td>'
                f'<td style="text-align:center">{_f(ff["o_3p"])}</td>'
                f'<td style="text-align:center;font-weight:700">{_f(ff["drtg"])}</td>'
                f'<td style="text-align:center">{_f(ff["d_efg"])}</td>'
                f'<td style="text-align:center">{_f(ff["d_tov"])}</td>'
                f'<td style="text-align:center">{_f(ff["d_or"])}</td>'
                f'<td style="text-align:center">{_f(ff["d_ftr"])}</td>'
                f'<td style="text-align:center">{_f(ff["d_2p"])}</td>'
                f'<td style="text-align:center">{_f(ff["d_3p"])}</td>'
            )
            for k in COL_KEYS:
                col_data[k].append(ff[k])
            ortg_vals.append(ff['ortg'])
            drtg_vals.append(ff['drtg'])
        else:
            cells = '<td></td>' * 15

        game_rows_html.append(
            f'<tr style="{row_bg}">'
            f'<td style="text-align:left;white-space:nowrap;font-size:0.77rem">{date_str}</td>'
            f'<td style="text-align:center">{opp_rank}</td>'
            f'<td style="text-align:left">{opp_link}</td>'
            f'{result_cell}'
            f'{cells}'
            f'</tr>'
        )

    # ── Correlations ──────────────────────────────────────────────────────────
    # Only show correlations for the four factors (both sides); leave other columns blank
    FOUR_FACTORS = {'o_efg', 'o_tov', 'o_or', 'o_ftr', 'd_efg', 'd_tov', 'd_or', 'd_ftr'}

    def corr_cell(r, stat_key, is_ortg):
        if stat_key not in FOUR_FACTORS:
            return '<td></td>'
        if r is None:
            return '<td style="text-align:center;color:#aaa">—</td>'
        v = round(r * 100)
        tip = corr_tooltip_text(v, STAT_LABELS[stat_key], is_ortg).replace('"', '&quot;')
        sign = '+' if v >= 0 else ''
        return (f'<td style="text-align:center;font-weight:700;cursor:help" '
                f'class="corr-cell" data-tip="{tip}">{sign}{v}</td>')

    ortg_corr_cells = ''
    drtg_corr_cells = ''
    for k in COL_KEYS:
        vals = col_data[k]
        r_o = pearson_corr(vals, ortg_vals) if k != 'ortg' else (1.0 if len(ortg_vals) >= 4 else None)
        r_d = pearson_corr(vals, drtg_vals) if k != 'drtg' else (1.0 if len(drtg_vals) >= 4 else None)
        ortg_corr_cells += corr_cell(r_o, k, True)
        drtg_corr_cells += corr_cell(r_d, k, False)

    game_rows = '\n'.join(game_rows_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{team_name} - Game Plan 2025-26</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0a0a0a; color: #000; padding: 20px;
  }}
  a {{ text-decoration: none; }}
  .back-link {{ color: #4fc3f7; font-size: 0.85rem; margin-bottom: 12px; display: inline-block; margin-right: 16px; }}
  .back-link:hover {{ text-decoration: underline; }}
  .team-header {{ text-align: center; background: #1a1a2e; border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
  .team-header h1 {{ color: {school_color}; font-size: 2rem; margin-bottom: 4px; }}
  .team-header .rank {{ color: #4fc3f7; font-size: 1.1rem; font-weight: 700; margin-bottom: 4px; }}
  .team-header .meta {{ color: #ccc; font-size: 0.9rem; }}
  .team-header .record {{ color: #fff; font-size: 1.2rem; font-weight: 700; margin-top: 6px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 16px; border: 1px solid #ccc; max-width: 1500px; margin: 0 auto; overflow-x: auto; }}
  .section-title {{ font-size: 1rem; font-weight: 700; text-align: center; margin-bottom: 10px; color: #000; border-bottom: 2px solid #333; padding-bottom: 6px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; white-space: nowrap; }}
  th {{ background: #1a1a2e; color: #fff; padding: 5px 7px; text-align: center; font-size: 0.73rem; border-bottom: 2px solid #333; }}
  th.group-off {{ background: #1a3a5c; }}
  th.group-def {{ background: #3a1a1a; }}
  td {{ padding: 4px 7px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #f5f5f5; }}
  tfoot tr td {{ background: #f0f0f0; border-top: 2px solid #bbb; font-size: 0.75rem; }}
  .corr-label {{ text-align: right; font-style: italic; color: #555; padding-right: 10px; white-space: nowrap; font-weight: 600; }}
  .generated {{ text-align: center; color: #888; font-size: 0.75rem; margin-top: 16px; }}
  .corr-cell {{ position: relative; }}
  .corr-cell:hover::after {{
    content: attr(data-tip);
    position: absolute;
    bottom: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
    background: #1a1a2e;
    color: #fff;
    padding: 7px 10px;
    border-radius: 4px;
    font-size: 0.72rem;
    font-weight: 400;
    white-space: normal;
    width: 230px;
    z-index: 999;
    pointer-events: none;
    box-shadow: 0 2px 8px rgba(0,0,0,0.35);
    line-height: 1.45;
  }}
</style>
</head>
<body>

<a class="back-link" href="wsc_north_leaderboard.html">← Leaderboard</a>
<a class="back-link" href="{slug}.html">← {team_name}</a>

<div class="team-header">
  <div class="rank">#{net_rank} NET RTG</div>
  <h1>{team_name} — 2026 Game Plan</h1>
  <div class="meta">{conference} · {region} Region</div>
  <div class="record">{record} Overall &nbsp;|&nbsp; {conf_rec} Conference</div>
</div>

<div class="card">
  <div class="section-title">2025-26 Game Plan</div>
  <table>
    <thead>
      <tr>
        <th rowspan="2" style="text-align:left">Date</th>
        <th rowspan="2">Rk</th>
        <th rowspan="2" style="text-align:left">Opponent</th>
        <th rowspan="2">Result</th>
        <th rowspan="2">Pace</th>
        <th colspan="7" class="group-off">Offense</th>
        <th colspan="7" class="group-def">Defense</th>
      </tr>
      <tr>
        <th class="group-off">Eff</th>
        <th class="group-off">eFG%</th>
        <th class="group-off">TO%</th>
        <th class="group-off">OR%</th>
        <th class="group-off">FTR</th>
        <th class="group-off">2P%</th>
        <th class="group-off">3P%</th>
        <th class="group-def">Eff</th>
        <th class="group-def">eFG%</th>
        <th class="group-def">TO%</th>
        <th class="group-def">OR%</th>
        <th class="group-def">FTR</th>
        <th class="group-def">2P%</th>
        <th class="group-def">3P%</th>
      </tr>
    </thead>
    <tbody>
{game_rows}
    </tbody>
    <tfoot>
      <tr>
        <td colspan="4" class="corr-label">Correlations (R×100) to offensive efficiency:</td>
        {ortg_corr_cells}
      </tr>
      <tr>
        <td colspan="4" class="corr-label">Correlations (R×100) to defensive efficiency:</td>
        {drtg_corr_cells}
      </tr>
    </tfoot>
  </table>
  <div style="font-size:0.72rem;color:#888;margin-top:8px">
    Rk = opponent&rsquo;s current NET RTG rank &nbsp;|&nbsp; * = conference game &nbsp;|&nbsp; Pace = est. possessions per 40 min &nbsp;|&nbsp; Hover correlation values for interpretation
  </div>
</div>

<div class="generated">Generated {timestamp}</div>
</body>
</html>"""


def main():
    print("Loading all team data...")
    all_teams = load_all_teams()
    print(f"  {len(all_teams)} teams loaded")

    print("Computing league averages and rankings...")
    league_avg = compute_league_averages(all_teams)

    # Compute rankings for all relevant stats
    ranking_configs = [
        ("net_rtg", False), ("ortg", False), ("drtg", True), ("tempo", False),
        ("efg_pct", False), ("tov_pct", True), ("oreb_pct", False), ("ft_rate", False),
        ("ts_pct", False), ("opp_efg_pct", True), ("dreb_pct", False),
        ("opp_tov_pct", False), ("opp_ft_rate", True), ("opp_ts_pct", True),
        ("sos", False), ("ncsos", False),
    ]
    rankings = {}
    for key, low in ranking_configs:
        rankings[key] = compute_stat_rankings(all_teams, key, low)

    timestamp = datetime.now().strftime("%B %d, %Y %I:%M %p")
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("Generating team pages...")
    count = 0
    for team_name, team_data in all_teams.items():
        if team_data["advanced"].get("ortg", 0) == 0:
            print(f"  Skipping {team_name}: no advanced stats")
            continue

        html = generate_team_page(team_name, team_data, all_teams, league_avg, rankings, timestamp)
        out_path = OUTPUT_DIR / f"{team_slug(team_name)}.html"
        out_path.write_text(html)

        gp_html = generate_gameplan_page(team_name, team_data, all_teams, rankings, timestamp)
        gp_path = OUTPUT_DIR / f"{team_slug(team_name)}_gameplan.html"
        gp_path.write_text(gp_html)
        count += 1

    print(f"  Generated {count} team pages in {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
