"""
Opponent Scouting Report — the standard report for any CCCAA team.

The Ventura report (generate_ventura_scouting_report.py) is the template: the same pages, tables, player cards and
order, at the same level of detail, for every team. Every sentence is written from the team's own numbers by fixed
rules (nothing typed per team), so two reports always say the same kind of thing about the same kind of number.

    python3 generate_opponent_report.py "Irvine Valley"
    python3 generate_opponent_report.py --team "Ventura" --season 2025-26
    python3 generate_opponent_report.py --list

Two editions, picked by the data in the repo: PRE-SYNERGY (box scores and the leaderboard) until the team's Synergy export
is in internal_data (synergy_team_<team>_<season>.json, synergy_players_<team>_<season>.json), then SYNERGY, which adds
the Moorpark report's Synergy layer: the play-type page (offense / defense tables, key takeaways), and on each player card
the Synergy and bball-index archetypes, play-type mix, the left-hand driver flag, the shot-profile strip, the export's
written scouting notes and Synergy sentences in his profile.

Output: scouting_reports/<team>_scouting_report_<season>_<pre_synergy|synergy>.pdf. An existing report is never
overwritten: the next free name gets _v2, _v3... (the hand-built reports elsewhere in the repo are never touched).

The build refuses to write a report that falls short of the standard (check_report): every section present, a card
with a written profile for every rotation player, and no coaching-scheme or film language (lint_scouting_prose.py's
patterns; the Keys to Victory may tell Moorpark what to do, nothing else may).

Pages: 1 cover, identity and the advanced offense / defense tables · 2 statewide context and the four factors vs
Moorpark · 3+ player profiles (rotation, by minutes) · situational splits, quadrant records and losses · head-to-head,
strengths and vulnerabilities, keys to victory.
"""

import argparse, csv, glob, json, os, re, sys
from datetime import date, datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, 'scouting_reports')

# ─── Palette (the Ventura report's; the opponent's color replaces Ventura orange) ──────
BLUE      = colors.HexColor('#003087')
GOLD      = colors.HexColor('#C4922A')
DARK      = colors.HexColor('#1a1a2e')
MID       = colors.HexColor('#555577')
LGRAY     = colors.HexColor('#f2f3f7')
MGRAY     = colors.HexColor('#dde0ea')
GREEN_BG  = colors.HexColor('#d4edda')
RED_BG    = colors.HexColor('#f8d7da')
YELLOW_BG = colors.HexColor('#fff3cd')
GREEN_TXT = colors.HexColor('#1a5c30')
RED_TXT   = colors.HexColor('#7b1b1b')
TH_BG     = colors.HexColor('#1a3a6e')
ALT       = colors.HexColor('#e8ecf5')
WHITE     = colors.white
BLACK     = colors.black

def jload(p): return json.load(open(p))
def slug(t): return re.sub(r'[^a-z0-9]+', '_', t.lower()).strip('_')

# ─── Team colors: the game tracker's TEAM_COLORS (game/index.html), one place for every team's color ─────
def team_color(team):
    try:
        html = open(os.path.join(REPO, 'game', 'index.html'), encoding='utf-8').read()
        m = re.search(r'const TEAM_COLORS = (\{[^;]*\});', html)
        hexv = json.loads(m.group(1)).get(slug(team))
    except Exception:
        hexv = None
    return hexv or '#444466'

def mix(hexv, other, t):
    a = [int(hexv[i:i + 2], 16) for i in (1, 3, 5)]; b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02X%02X%02X' % tuple(round(x + (y - x) * t) for x, y in zip(a, b))

def luminance(hexv):
    r, g, b = [int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

# ─── Data ─────────────────────────────────────────────────────────────────────────────
def stats_root(season): return os.path.join(HERE, f'{season} Team Statistics')

def _jersey(n):
    """A jersey number as worn: some box scores pad single digits ("03"); 0 and 00 are their own numbers."""
    n = str(n).strip()
    return n if n in ('0', '00') else (n.lstrip('0') or '0')

def find_team_dir(team, season):
    root = stats_root(season)
    for conf in sorted(os.listdir(root)):
        d = os.path.join(root, conf, team)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, 'advanced_analytics.json')):
            return conf, d
    return None, None

def list_teams(season):
    root = stats_root(season)
    for conf in sorted(os.listdir(root)):
        cp = os.path.join(root, conf)
        if not os.path.isdir(cp): continue
        teams = sorted(t for t in os.listdir(cp) if os.path.exists(os.path.join(cp, t, 'advanced_analytics.json')))
        if teams: print(f'\n{conf}:\n  ' + '\n  '.join(teams))

def _parse_height_in(h):
    h = (h or '').strip().replace('"', '').replace('Ht.: ', '')
    if h.isdigit(): return int(h)   # the position model's CSV keeps inches
    if "'" in h:
        ft, _, inc = h.partition("'")
        try: return int(ft.strip()) * 12 + (int(inc.strip()) if inc.strip().isdigit() else 0)
        except ValueError: return 0
    return 0

def _fmt_height(inches):
    return f"{inches // 12}'{inches % 12}\"" if inches > 0 else ''

POS_FULL = {'PG': 'Point Guard', 's-PG': 'Scoring PG', 'CG': 'Combo Guard', 'WG': 'Wing Guard', 'WF': 'Wing Forward',
            'S-PF': 'Stretch PF', 'PF/C': 'PF / Center', 'C': 'Center'}

def kenpom_player_role(usage_pct, mpg):
    if mpg / 40.0 * 100 < 10.0: return 'Benchwarmer', '#777777'
    if usage_pct >= 28.0: return 'Go-to Guy', '#ffd700'
    if usage_pct >= 24.0: return 'Major Contributor', '#34a853'
    if usage_pct >= 20.0: return 'Significant Contributor', '#ff9900'
    if usage_pct >= 16.0: return 'Role Player', '#4a86e8'
    if usage_pct >= 12.0: return 'Limited Role Player', '#ff00ff'
    return 'Nearly Invisible', '#d9d9d9'

# Rotation: the players who matter in a game, the Ventura report's "all meaningful rotation players": 10+ minutes a game
# in at least 40% of the team's games. A player who hasn't played in any of the team's last GONE_GAMES games is listed under
# the rotation, not profiled (the Ventura report dropped Christian Aukuso, who had left, by hand; this finds him).
# internal_data/scouting_exclusions.json ({team: [names]}) drops anyone else by hand.
ROT_MPG, ROT_GP_SHARE, GONE_GAMES = 10.0, 0.40, 6

# Tier words for a state rank (out of N teams / players): the Ventura report's tiers, one wording everywhere.
def tier_of(rank, n):
    pct = rank / max(n, 1) * 100
    return ('Elite' if pct <= 15 else 'Above Avg' if pct <= 35 else 'Average' if pct <= 65 else
            'Below Avg' if pct <= 85 else 'Poor')
TIER_WORD = {'Elite': 'elite', 'Above Avg': 'above average', 'Average': 'near average', 'Below Avg': 'below average',
             'Poor': 'well below average'}
def tw(rank, n): return TIER_WORD[tier_of(rank, n)]

class Ctx:
    """Everything one report reads, computed once."""

def load(team, season):
    c = Ctx(); c.team, c.season = team, season
    # the season still being played (the current season, before April): the report says "so far", not "finished"
    from ccc_config import DEFAULT_SEASON
    c.ongoing = season == DEFAULT_SEASON and date.today() < date(int(season[:4]) + 1, 4, 1)
    c.conf, d = find_team_dir(team, season)
    if not d: sys.exit(f'No {season} stats folder for "{team}" (try --list).')
    _, md = find_team_dir('Moorpark', season)
    c.team_sum, c.adv_json, c.plyr_stats = jload(f'{d}/team_summary.json'), jload(f'{d}/advanced_analytics.json'), jload(f'{d}/player_stats.json')
    c.mp_adv, c.mp_sum = jload(f'{md}/advanced_analytics.json'), jload(f'{md}/team_summary.json')
    # this season's WAB (calculate_wab.py writes wab_results.json for 2025-26, wab_results_<season>.json otherwise)
    wab_path = os.path.join(HERE, 'wab_results.json' if season == '2025-26' else f'wab_results_{season.replace("-", "_")}.json')
    c.wab_data = jload(wab_path) if os.path.exists(wab_path) else []
    c.avgs, c.opp_avgs, c.ta = c.team_sum['averages'], c.team_sum['opponent_averages'], c.adv_json['team']
    # Points from the final scores (a game whose box score only one team posted still has its score; that team's
    # averages can be empty): the same as the leaderboard
    try:
        _sc = [(g.get('team_score') or 0, g.get('opponent_score') or 0) for g in json.load(open(os.path.join(d, 'game_log.json'))).get('games', [])]
    except (OSError, ValueError):
        _sc = []
    _sc = [x for x in _sc if x[0] > 0 and x[1] > 0]
    if _sc:
        c.avgs = dict(c.avgs or {}, PTS=round(sum(a for a, _ in _sc) / len(_sc), 1))
        c.opp_avgs = dict(c.opp_avgs or {}, PTS=round(sum(b for _, b in _sc) / len(_sc), 1))
    c.game_log = c.ta.get('game_ratings', [])
    c.wab_map = {t['team']: t for t in c.wab_data}
    rec = c.team_sum.get('record', {})
    pick = lambda k: next((v for kk, v in rec.items() if kk.startswith(k)), None)
    c.rec_all = pick('Overall') or f"{sum(g['result'] == 'W' for g in c.game_log)}-{sum(g['result'] == 'L' for g in c.game_log)}"
    c.rec_conf = pick('Conference') or '—'
    c.n_games = len(c.game_log)

    ex_path = os.path.join(HERE, 'internal_data', 'scouting_exclusions.json')
    excluded = set(jload(ex_path).get(team, [])) if os.path.exists(ex_path) else set()
    c.players_raw = [p for p in c.plyr_stats['players'] if p['name'] not in excluded]
    c.plyr_adv = {p['name']: p for p in c.adv_json.get('players', []) if p['name'] not in excluded}
    team_g = max([c.n_games] + [p['averages'].get('games', 0) for p in c.players_raw])
    # Last game played, from the per-game logs ("#23 Christian Aukuso": also his jersey number).
    md = lambda d: tuple(int(x) for x in (d.split('/')[2], d.split('/')[0], d.split('/')[1]))
    c.num, last_g, logs_ok = {}, {}, False
    pgr = os.path.join(d, 'player_game_ratings.json')
    if os.path.exists(pgr):
        pj = jload(pgr)
        logs_ok = (pj.get('games_rated') or 0) >= 0.8 * max(c.n_games, 1)   # the logs skip games without minutes
        for k, v in pj.get('game_logs', {}).items():
            m = re.match(r'#(\S+)\s+(.*)', k); nm = m.group(2) if m else k
            if m: c.num[nm] = _jersey(m.group(1))
            if v: last_g[nm] = max(md(x['date']) for x in v)
    c.num_logs = set(c.num)
    # Jersey numbers also from the team's box scores ("#12 Dev Hamilton", some pages "F 31 Brandon Woodards"), for any
    # player the per-game logs don't number (2026-27 has no logs yet); the latest game's number wins
    names = {p['name'] for p in c.players_raw}
    for f in sorted(glob.glob(os.path.join(d.replace(' Team Statistics', ' Teams Schedules'), '*', '*.json'))):
        try:
            sides = (jload(f).get('teams') or {}).values()
        except Exception:
            continue
        for rows in sides:
            for r in rows or []:
                m = re.match(r'^(?:[A-Za-z]{1,2}\s+)?#?(\d+)\s+(.*)$', (r.get('name') or '').strip())
                if m and m.group(2).strip() in names and m.group(2).strip() not in c.num_logs:
                    c.num[m.group(2).strip()] = _jersey(m.group(1))
    dates = sorted(md(g['date']) for g in c.game_log)
    cut = dates[-GONE_GAMES] if logs_ok and len(dates) >= GONE_GAMES else None
    # Minutes are reliable when the box scores add up to most of a game's 200 player-minutes; on teams whose stat crews don't
    # keep minutes, the rotation is the players who score or rebound (4+ PPG or 3+ RPG, the tracker's low-info rule) and
    # nothing is shown per minute.
    c.min_ok = sum(p['totals'].get('MIN', 0) for p in c.players_raw) >= 0.75 * 200 * max(c.n_games, 1)
    plays = (lambda p: p['averages'].get('MIN', 0) >= ROT_MPG) if c.min_ok else (lambda p: p['averages'].get('PTS', 0) >= 4 or p['averages'].get('REB', 0) >= 3)
    regular = [p for p in c.players_raw if plays(p) and p['averages'].get('games', 0) >= ROT_GP_SHARE * team_g]
    c.gone = [p for p in regular if cut and p['name'] in last_g and last_g[p['name']] < cut]
    c.last_date = {p['name']: '%d/%d/%d' % (last_g[p['name']][1], last_g[p['name']][2], last_g[p['name']][0]) for p in c.gone}
    # Profiles run by share of the TEAM's possessions: %Poss (usage while on the floor) x share of the minutes, so a
    # high-usage bench player doesn't rank over the starters the offense runs through (by points where minutes, and so
    # usage, aren't kept).
    use = lambda p: (c.plyr_adv.get(p['name'], {}).get('usage_pct') or 0) * p['averages'].get('MIN', 0) / 40 if c.min_ok else p['averages'].get('PTS', 0)
    c.rotation = sorted([p for p in regular if p not in c.gone], key=lambda p: -use(p))

    # Positions and heights (the leaderboard's position model and the roster scrape).
    c.pos, c.height = {}, {}
    pos_csv = os.path.join(HERE, 'internal_data', f'player_positions_{season.replace("-", "_")}.csv')
    if os.path.exists(pos_csv):
        for r in csv.DictReader(open(pos_csv)):
            if r['team'].strip() == team:
                c.pos[r['name'].strip()] = r['pos_class']
                if _parse_height_in(r.get('height', '')) > 60: c.height[r['name'].strip()] = _parse_height_in(r['height'])
    # Heights: the leaderboard's own loader (generate_leaderboard._load_player_heights: the roster scrape, its team-name
    # matching and height formats), the position model's CSV filling in a player it misses.
    hk = lambda n: re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9\s]', ' ', (n or '').lower())).strip()
    try:
        sys.path.insert(0, HERE); import generate_leaderboard as gl
        H = {k: _parse_height_in(v) for k, v in gl._load_player_heights().items()}; hk = gl._height_player_key
    except Exception:
        H = {}
    for p in c.players_raw:
        h = H.get((team, hk(p['name'])))
        if h: c.height[p['name']] = h
    c.all_team_h = {}
    for (tn, _), h in H.items():
        if h > 60: c.all_team_h.setdefault(tn, []).append(h)
    all_h = [h for hs in c.all_team_h.values() for h in hs]
    team_h = c.all_team_h.get(team, [])
    c.state_avg_h = sum(all_h) / len(all_h) if all_h else 0
    c.avg_h = sum(team_h) / len(team_h) if len(team_h) >= 5 else 0
    team_avgs_h = sorted([sum(hs) / len(hs) for hs in c.all_team_h.values() if len(hs) >= 5], reverse=True)
    c.h_rank = next((i + 1 for i, a in enumerate(team_avgs_h) if a <= c.avg_h), len(team_avgs_h)) if c.avg_h else 0
    c.h_n = len(team_avgs_h)

    dep_path = os.path.join(HERE, 'internal_data', f'position_dependence_{season.replace("-", "_")}.json')
    dep_all = jload(dep_path) if os.path.exists(dep_path) else []
    c.dep = next((r for r in dep_all if r['team'] == team), {})
    gdis = sorted([r['gdi'] for r in dep_all if 'gdi' in r], reverse=True)
    c.gdi = c.dep.get('gdi', 0)
    c.gdi_rank = next((i + 1 for i, v in enumerate(gdis) if v <= c.gdi), len(gdis)) if c.dep else 0
    c.gdi_n = len(gdis); c.gdi_avg = round(sum(gdis) / len(gdis), 1) if gdis else 0

    # Games, splits, quadrants (the Ventura report's rules).
    c.games = []
    for g in c.game_log:
        od = c.wab_map.get(g.get('canonical_opponent', g['opponent']))
        c.games.append({**g, 'net': g['ortg'] - g['drtg'], 'margin': g['team_score'] - g['opponent_score'],
                        'opp_net': od['net'] if od else None})
    c.half = (len(c.games) + 1) // 2
    wab_ranked = sorted(c.wab_data, key=lambda x: -x.get('net', 0)); N = len(wab_ranked) or 100
    c.net_ranks = {t['team']: i + 1 for i, t in enumerate(wab_ranked)}
    def quad(rank, loc):
        th = lambda m: m.get(loc, m['Neutral'])
        for q, m in (('Q1A', {'Home': 15, 'Neutral': 25, 'Away': 40}), ('Q1', {'Home': 30, 'Neutral': 50, 'Away': 75}),
                     ('Q2', {'Home': 75, 'Neutral': 100, 'Away': 135}), ('Q3', {'Home': 160, 'Neutral': 200, 'Away': 240})):
            if rank <= N * th(m) / 353: return q
        return 'Q4'
    c.quad_rec = {q: [0, 0] for q in ('Q1A', 'Q1', 'Q2', 'Q3', 'Q4')}; c.quad_games = {q: [] for q in c.quad_rec}
    for g in c.games:
        r = c.net_ranks.get(g.get('canonical_opponent', g['opponent']))
        if not r: continue
        q = quad(r, g.get('location', 'Neutral'))
        c.quad_rec[q][0 if g['result'] == 'W' else 1] += 1; c.quad_games[q].append(dict(g, opp_rank=r))

    # Statewide team pool (same derived metrics as the Ventura report).
    c.all_teams = []
    root = stats_root(season)
    for conf in os.listdir(root):
        cp = os.path.join(root, conf)
        if not os.path.isdir(cp): continue
        for tn in os.listdir(cp):
            ap, sp = os.path.join(cp, tn, 'advanced_analytics.json'), os.path.join(cp, tn, 'team_summary.json')
            if not (os.path.exists(ap) and os.path.exists(sp)): continue
            try: c.all_teams.append(team_metrics(tn, jload(ap)['team'], jload(sp)))
            except Exception: pass
    c.n = len(c.all_teams)
    c.me = team_metrics(team, c.ta, c.team_sum)
    c.mp = team_metrics('Moorpark', c.mp_adv['team'], c.mp_sum)

    # Head-to-head, from Moorpark's game log.
    c.h2h = [g for g in c.mp_adv['team'].get('game_ratings', []) if team in (g.get('canonical_opponent', ''), g.get('opponent', ''))]

    # Statewide player pools (Min% > 10%, and Min% >= 30% for the advanced ranks).
    c.all_players, c.adv_players = [], []
    lg_raw, rated = [0, 0, 0, 0], []   # league PTS, true shot attempts, 3PM, 3PA (every player); pool entries to rate after
    for conf in os.listdir(root):
        cp = os.path.join(root, conf)
        if not os.path.isdir(cp): continue
        for tn in os.listdir(cp):
            pp, ap = os.path.join(cp, tn, 'player_stats.json'), os.path.join(cp, tn, 'advanced_analytics.json')
            if not (os.path.exists(pp) and os.path.exists(ap)): continue
            try:
                aj = jload(ap); ps, am = jload(pp), {p['name']: p for p in aj.get('players', [])}
                # 10+ games, or early in the season 60%+ of the team's games so far (the pool fills from the first game)
                tg = max([q['averages'].get('games', 0) for q in ps['players']] or [0])
                need = min(10, max(1, round(0.6 * tg)))
                # Per-100 box rates need the team's pace and real minutes (the same test as c.min_ok)
                pace = (aj.get('team') or {}).get('possessions', 0) or 0
                if sum(q['totals'].get('MIN', 0) for q in ps['players']) < 0.75 * 200 * max(tg, 1): pace = 0
                for p in ps['players']:
                    avg, tot = p['averages'], p['totals']; mpg, gp = avg.get('MIN', 0), avg.get('games', 0)
                    for i, v in enumerate((tot.get('PTS', 0), tot.get('FGA', 0) + 0.44 * tot.get('FTA', 0), tot.get('3PM', 0), tot.get('3PA', 0))): lg_raw[i] += v
                    if gp < need: continue
                    a2 = am.get(p['name'], {}); twoa = tot.get('FGA', 0) - tot.get('3PA', 0); twom = tot.get('FGM', 0) - tot.get('3PM', 0)
                    twop = round(twom / twoa * 100, 1) if twoa > 0 else 0
                    if mpg >= 4:
                        c.all_players.append({'name': p['name'], 'team': tn, 'ppg': avg.get('PTS', 0), 'rpg': avg.get('REB', 0),
                            'apg': avg.get('AST', 0), 'spg': avg.get('STL', 0), 'bpg': avg.get('BLK', 0), 'ts_pct': a2.get('ts_pct', 0),
                            'tpp': avg.get('3P%', 0), 'tpa': avg.get('3PA', 0), 'ftp': avg.get('FT%', 0), 'fga': avg.get('FGA', 0),
                            'twop': twop, 'tov_pct': a2.get('tov_pct', 0), 'oreb_pct': a2.get('oreb_pct', 0)})
                        rated.append((c.all_players[-1], tot, pace))
                    if mpg >= 12:
                        c.adv_players.append({'name': p['name'], 'team': tn, **{k: a2.get(k, 0) for k in
                            ('ind_ortg', 'ind_drtg', 'ast_rate', 'tov_pct', 'oreb_pct', 'dreb_pct', 'stl_pct', 'blk_pct', 'usage_pct',
                             'ft_rate', 'efg_pct', 'ts_pct')}, 'twop': twop, 'tpp': avg.get('3P%', 0), 'ftp': avg.get('FT%', 0)})
                        rated.append((c.adv_players[-1], tot, pace))
            except Exception: pass
    c.box_lg = (lg_raw[0] / (2 * lg_raw[1]) if lg_raw[1] else None, 1.5 * lg_raw[2] / lg_raw[3] if lg_raw[3] else None)
    for q, tot, pace in rated: q.update(box_rates(tot, pace, c.box_lg))

    # The opponent's color (header bars, title, table heads, the head-to-head box).
    hexv = team_color(team)
    c.OPP = colors.HexColor(hexv); c.OPP_TXT = WHITE if luminance(hexv) < 0.6 else DARK
    c.OPP_TINT = colors.HexColor(mix(hexv, '#FFFFFF', 0.9)); c.OPP_DEEP = colors.HexColor(mix(hexv, '#000000', 0.45))
    ini = ''.join(w[0] for w in team.replace('.', '').split())
    load_synergy(c)
    c.abbr = (ini + 'C' if len(ini) == 2 else ini if len(ini) > 2 else team[:3]).upper()[:4]   # IVC, SBC, VEN
    return c

def team_metrics(name, a, s):
    # .get throughout: a team with no games yet (Moorpark before its opener) has empty averages
    av, ov, tot, otot = s.get('averages') or {}, s.get('opponent_averages') or {}, s.get('totals', {}), s.get('opponent_totals', {})
    fga, poss, pf = max(av.get('FGA', 1), 1), max(a.get('possessions', 0.01), 0.01), max(tot.get('PF', 0.1), 0.1)
    stlt, blkt = tot.get('STL', 0), tot.get('BLK', 0)
    opp_poss = max((otot.get('FGA', 0) - otot.get('OREB', 0)) + otot.get('TO', 0) + 0.475 * otot.get('FTA', 0), 0.1)
    stl_pct, blk_pct = round(stlt / opp_poss * 100, 1), round(blkt / max(otot.get('FGA', 1), 1) * 100, 1)
    return {'team': name, 'net_rtg': a.get('net_rtg', 0), 'ortg': a.get('ortg', 0), 'drtg': a.get('drtg', 0),
            'efg_pct': a.get('efg_pct', 0), 'opp_efg_pct': a.get('opp_efg_pct', 0), 'tov_pct': a.get('tov_pct', 0),
            'opp_tov_pct': a.get('opp_tov_pct', 0), 'oreb_pct': a.get('oreb_pct', 0), 'dreb_pct': a.get('dreb_pct', 0),
            'ft_rate': a.get('ft_rate', 0), 'opp_ft_rate': a.get('opp_ft_rate', 0), 'ts_pct': a.get('ts_pct', 0),
            'opp_ts_pct': a.get('opp_ts_pct', 0), 'pace': a.get('possessions', 0), 'stl_pct': stl_pct, 'blk_pct': blk_pct,
            'hkm_pct': round(stl_pct + blk_pct, 1), 'stl_to': round(av.get('STL', 0) / max(ov.get('TO', 0.01), 0.01), 2),
            'pf_eff': round((stlt + blkt) / pf, 2), 'stl_pf': round(stlt / pf, 2), 'blk_pf': round(blkt / pf, 2),
            'ast_rate': a.get('ast_rate', 0),
            'ast_ratio': round(100 * av.get('AST', 0) / max(av.get('FGA', 0) + 0.475 * av.get('FTA', 0) + av.get('AST', 0) + av.get('TO', 0), 1), 1),
            'ast_to': round(av.get('AST', 0) / max(av.get('TO', 0.01), 0.01), 2),
            'nst_pct': round(max(av.get('TO', 0) - ov.get('STL', 0), 0) / poss * 100, 1),
            # Team fouls a game from the box totals (the advanced file's fc_per_40 and the minutes totals are unusable on
            # false-minutes teams).
            'fc_per_40': av.get('PF', 0),
            '3par': round(av.get('3PA', 0) / fga * 100, 1), 'ppg': av.get('PTS', 0), 'oppg': ov.get('PTS', 0),
            'stl': av.get('STL', 0), 'blk': av.get('BLK', 0), 'ast': av.get('AST', 0), 'tov': av.get('TO', 0)}

# ─── Ranks ────────────────────────────────────────────────────────────────────────────
HB = {'net_rtg': True, 'ortg': True, 'drtg': False, 'efg_pct': True, 'opp_efg_pct': False, 'tov_pct': False,
      'opp_tov_pct': True, 'oreb_pct': True, 'dreb_pct': True, 'ft_rate': True, 'opp_ft_rate': False, 'ts_pct': True,
      'opp_ts_pct': False, 'pace': True, 'stl_pct': True, 'blk_pct': True, 'hkm_pct': True, 'stl_to': True, 'pf_eff': True,
      'stl_pf': True, 'blk_pf': True, 'ast_rate': True, 'ast_ratio': True, 'ast_to': True, 'nst_pct': False,
      'fc_per_40': False, '3par': True, 'ppg': True, 'oppg': False, 'stl': True, 'blk': True, 'ast': True}

def state_rank(c, key, val=None, hb=None):
    val = c.me[key] if val is None else val; hb = HB[key] if hb is None else hb
    vals = sorted([t[key] for t in c.all_teams if t[key] != 0], reverse=hb)
    rank = next((i + 1 for i, v in enumerate(vals) if (hb and v <= val) or (not hb and v >= val)), len(vals))
    nz = [t[key] for t in c.all_teams if t[key] != 0]
    avg = sum(nz) / len(nz)
    return rank, len(vals), round(avg, 1), round(val - avg, 1)

def R(c, key): return state_rank(c, key)[0]
def AVG(c, key): return state_rank(c, key)[2]

# Box-score rate stats (Databallr's glossary; the same math as the leaderboard's boxRate):
#   rts       TS% minus the league's (points)            tsadd     points above a league-average shooter on the same
#   tp_rts    3-point TS (1.5 x 3P%) minus the league's            true shot attempts, per 100 possessions on the floor
#   tpr       3PA / FGA                                  shots100  true shot attempts (FGA + 0.44 FTA) per 100 possessions
#   stl100, blk100 per 100 possessions on the floor
# Possessions on the floor = the team's possessions a game x his minutes / 40; the per-100 ones need real minutes (pace 0
# otherwise). The league is every player in the season's data. The relative ones can be negative (SIGNED).
SIGNED = {'rts', 'tsadd', 'tp_rts'}
def box_rates(tot, pace, lg):
    fga, tpa, pts = tot.get('FGA', 0), tot.get('3PA', 0), tot.get('PTS', 0)
    tsa, on = fga + 0.44 * tot.get('FTA', 0), pace * tot.get('MIN', 0) / 40
    lts, ltp = lg
    r = {'rts': 100 * (pts / (2 * tsa) - lts) if tsa > 0 and lts else None,
         'tp_rts': 100 * (1.5 * tot.get('3PM', 0) / tpa - ltp) if tpa > 0 and ltp else None,
         'tpr': 100 * tpa / fga if fga > 0 else None}
    ok = on > 0
    r.update(tsadd=100 * (pts - lts * 2 * tsa) / on if ok and tsa > 0 and lts else None, shots100=100 * tsa / on if ok and tsa > 0 else None,
             stl100=100 * tot.get('STL', 0) / on if ok else None, blk100=100 * tot.get('BLK', 0) / on if ok else None)
    return r

def pool_rank(pool, key, val, hb=True, filt=None):
    p = [x for x in pool if x.get(key) is not None and (key in SIGNED or x[key] > 0) and (not filt or filt(x))]
    vals = sorted([x[key] for x in p], reverse=hb)
    return next((i + 1 for i, v in enumerate(vals) if (hb and v <= val) or (not hb and v >= val)), len(vals)), len(vals)

def get_top100(c, avg, adv_data, tot, mpg):
    findings, box = [], box_rates(tot, c.me['pace'] if c.min_ok else 0, c.box_lg)
    twoa = tot.get('FGA', 0) - tot.get('3PA', 0); twom = tot.get('FGM', 0) - tot.get('3PM', 0)
    twop = round(twom / twoa * 100, 1) if twoa > 0 else 0
    for key, val, label, unit, hb, pf in [
        ('ppg', avg.get('PTS', 0), 'PPG', '', True, None), ('rpg', avg.get('REB', 0), 'RPG', '', True, None),
        ('apg', avg.get('AST', 0), 'APG', '', True, None), ('spg', avg.get('STL', 0), 'SPG', '', True, None),
        ('bpg', avg.get('BLK', 0), 'BPG', '', True, None),
        ('tpp', avg.get('3P%', 0), '3P%', '%', True, lambda p: p.get('tpa', 0) >= 2),
        ('twop', twop, '2P%', '%', True, lambda p: p.get('fga', 0) >= 5),
        ('ftp', avg.get('FT%', 0), 'FT%', '%', True, lambda p: p.get('fga', 0) >= 2),
        ('tp_rts', (box.get('tp_rts') or 0) if avg.get('3PA', 0) >= 2 else 0, '3P rTS%', '', True, lambda p: p.get('tpa', 0) >= 2),
        ('tpr', (box.get('tpr') or 0) if avg.get('FGA', 0) >= 2 else 0, '3PR', '%', True, lambda p: p.get('fga', 0) >= 2)]:
        if val <= 0: continue
        r, n = pool_rank(c.all_players, key, val, hb, pf)
        if n and r <= 100: findings.append((label, val, unit, r, n))
    if mpg >= 12:
        for key, label, unit, hb in [('ind_ortg', 'Ind ORtg', '', True), ('ts_pct', 'TS%', '%', True), ('efg_pct', 'eFG%', '%', True),
                                     ('oreb_pct', 'OREB%', '%', True), ('dreb_pct', 'DREB%', '%', True), ('stl_pct', 'STL%', '%', True),
                                     ('blk_pct', 'BLK%', '%', True), ('ast_rate', 'AST Rate', '%', True), ('tov_pct', 'TOV%', '%', False)]:
            val = adv_data.get(key, 0)
            if val <= 0: continue
            r, n = pool_rank(c.adv_players, key, val, hb)
            if n and r <= 100: findings.append((label, val, unit, r, n))
        for key, label in (('rts', 'rTS%'), ('tsadd', 'TSAdd/100'), ('shots100', 'SHOTS/100'), ('stl100', 'STL/100'), ('blk100', 'BLK/100')):
            val = box.get(key) or 0
            if val <= 0: continue
            r, n = pool_rank(c.adv_players, key, val)
            if n and r <= 100: findings.append((label, val, '', r, n))
    return findings

# ─── Styles ───────────────────────────────────────────────────────────────────────────
SS = getSampleStyleSheet()
def S(size=10, bold=False, color=BLACK, align=TA_LEFT, italic=False, leading=None, space_after=2):
    fname = ('Helvetica-BoldOblique' if bold and italic else 'Helvetica-Bold' if bold else 'Helvetica-Oblique' if italic else 'Helvetica')
    return ParagraphStyle('_', parent=SS['Normal'], fontSize=size, fontName=fname, textColor=color, alignment=align,
                          leading=leading or size * 1.45, spaceAfter=space_after)
def HR(cl=GOLD, thick=1.5, before=4, after=8): return HRFlowable(width='100%', thickness=thick, color=cl, spaceBefore=before, spaceAfter=after)

# Every paragraph of prose goes through P() so check_report can read the whole report's text.
TEXT = []
def P(text, style, kind='prose'):
    TEXT.append((kind, re.sub(r'<[^>]+>', '', text)))
    return Paragraph(text, style)

SECTIONS = []
def section(title, subtitle=None):
    SECTIONS.append(title)
    items = [Spacer(1, 10), Paragraph(title.upper(), S(13, True, BLUE)), HR(GOLD, 2, 2, 6)]
    if subtitle: items.append(Paragraph(subtitle, S(9, False, MID, space_after=6)))
    return items

ARC_MIN_GAMES = 4   # the first-half / second-half split needs 2+ games a side

def splits_box(label, record_str, avg_net_val, extra=''):
    none = record_str == '0-0'   # no games in this split yet: "—", not a 0-0 record and a +0.0 net rating
    net_c = LGRAY if none else GREEN_BG if avg_net_val > 5 else (RED_BG if avg_net_val < -5 else YELLOW_BG)
    data = [[Paragraph(f'<b>{label}</b>', S(8, True, DARK)), Paragraph('\u2014' if none else record_str, S(11, True, BLUE, TA_CENTER)),
             Paragraph('\u2014' if none else f'{avg_net_val:+.1f} net rtg', S(9, False, MID, TA_CENTER)), Paragraph(extra, S(8, False, MID))]]
    t = Table(data, colWidths=[1.5 * inch, 1.2 * inch, 1.5 * inch, 2.8 * inch])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, 0), LGRAY), ('BACKGROUND', (2, 0), (2, 0), net_c),
        ('BOX', (0, 0), (-1, -1), 0.5, BLUE), ('INNERGRID', (0, 0), (-1, -1), 0.3, MGRAY), ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6)]))
    return t

def tier_p(r, n=100):
    t = tier_of(r, n); txt = {'Poor': 'Concern'}.get(t, t)
    col = {'Elite': GREEN_TXT, 'Above Avg': colors.HexColor('#1a5c20'), 'Average': MID, 'Below Avg': colors.HexColor('#7b3b00'), 'Poor': RED_TXT}[t]
    return Paragraph(f'<b>{txt}</b>', S(8, True, col))

def avg_net(lst): return sum(g['net'] for g in lst) / len(lst) if lst else 0
def rec(lst): w = sum(1 for g in lst if g['result'] == 'W'); return f'{w}-{len(lst) - w}'
def rec_or_dash(lst): return rec(lst) if lst else '\u2014'
def sg(v, d=1): return f'{v:+.{d}f}'
def last(n): return n.split()[-1]

# ─── Rotation helpers for the prose ───────────────────────────────────────────────────
def rot_by(c, f, rev=True): return sorted(c.rotation, key=f, reverse=rev)
def A(p): return p['averages']
def mins(c, p, pre=' in '): return f'{pre}{A(p).get("MIN", 0):.1f} MPG' if c.min_ok else ''
BOX_ONLY = ('efg_pct', 'ts_pct', 'ft_rate')   # the advanced numbers that don't need minutes
def ADV(c, p):
    a = c.plyr_adv.get(p['name'], {})
    return a if c.min_ok else {k: a[k] for k in BOX_ONLY if k in a}

# ═══════════════════════════════════════════════════════════════════════════════════════
# PAGE 1 — COVER + WHO ARE THEY + ADVANCED OFFENSE / DEFENSE
# ═══════════════════════════════════════════════════════════════════════════════════════
def page_cover(c):
    e, T, me = [], c.team, c.me
    season_d = c.season.replace('-', '–')
    for row, sz, bg, tc in [([T.upper()], 24, c.OPP, c.OPP_TXT),
                            ([f'{season_d}  ·  OPPONENT SCOUTING REPORT  ·  ' + ('SYNERGY EDITION' if c.syn_team else 'PRE-SYNERGY EDITION')
                              + '  ·  MOORPARK RAIDERS ANALYTICS'], 10, DARK, GOLD)]:
        t = Table([row], colWidths=[7.5 * inch])
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), bg), ('TEXTCOLOR', (0, 0), (-1, -1), tc), ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), sz), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('TOPPADDING', (0, 0), (-1, -1), 14), ('BOTTOMPADDING', (0, 0), (-1, -1), 14)]))
        e.append(t)
    e.append(Spacer(1, 12))
    net_r, ortg_r, drtg_r = R(c, 'net_rtg'), R(c, 'ortg'), R(c, 'drtg')
    def hcell(top, mid, bot, tc=BLUE):
        return [Paragraph(top, S(14, True, tc, TA_CENTER)), Paragraph(mid, S(7.5, False, MID, TA_CENTER)), Paragraph(bot, S(7, False, MID, TA_CENTER))]
    # Record, conference record, ORTg, DRTg, net rating, net rank (each rating with its state rank).
    strip = [hcell(c.rec_all, 'OVERALL', 'RECORD'), hcell(c.rec_conf, 'CONF. RECORD', c.conf),
             hcell(f'{c.ta["ortg"]:.1f}', 'OFF. RATING', f'#{ortg_r} of {c.n} CCCAA'),
             hcell(f'{c.ta["drtg"]:.1f}', 'DEF. RATING', f'#{drtg_r} of {c.n} CCCAA'),
             hcell(sg(c.ta['net_rtg']), 'NET RATING', 'Pts per 100 Poss', GREEN_TXT if c.ta['net_rtg'] >= 0 else RED_TXT),
             hcell(f'#{net_r}/{c.n}', 'NET RANK', 'Statewide')]
    t2 = Table([strip], colWidths=[1.25 * inch] * 6)
    t2.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), LGRAY), ('BACKGROUND', (4, 0), (4, 0), GREEN_BG if c.ta['net_rtg'] >= 0 else RED_BG),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, MGRAY), ('BOX', (0, 0), (-1, -1), 1.5, c.OPP), ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    e += [t2, Spacer(1, 14)]

    # Head-to-head alert box (always present: "no meetings" says so).
    w = sum(g['result'] == 'L' for g in c.h2h); l = len(c.h2h) - w
    if c.h2h:
        lines = '<br/>'.join(f"<b>{g['date']} — Moorpark {g['result']} {g['team_score']}–{g['opponent_score']} "
                             f"({'at ' + T if g['location'] == 'Away' else 'vs ' + T + (' (home)' if g['location'] == 'Home' else ' (neutral)')})</b>"
                             f"  |  Moorpark net: {sg(g['ortg'] - g['drtg'])}" for g in c.h2h)
        head = f'<b>HEAD-TO-HEAD THIS SEASON: {T} {w} – Moorpark {l}</b><br/>{lines}'
    else:
        head = f'<b>HEAD-TO-HEAD THIS SEASON:</b> Moorpark and {T} have not met in {c.season}.'
    hb = Table([[P(head, S(9, color=c.OPP_DEEP), 'data')]], colWidths=[7.5 * inch])
    hb.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), c.OPP_TINT), ('BOX', (0, 0), (-1, -1), 1.5, c.OPP),
        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8), ('LEFTPADDING', (0, 0), (-1, -1), 10)]))
    e += [hb, Spacer(1, 10)]

    e += section(f'Who Is {T}?', 'Team identity, style of play, and four-factors analysis.')
    o_t, d_t = tw(ortg_r, c.n), tw(drtg_r, c.n)
    if ortg_r <= 35 and drtg_r <= 35: ident = f'a two-way team — top 35 statewide at both ends'
    elif ortg_r <= 35 and ortg_r + 20 < drtg_r: ident = f'an offense-first team — they win by outscoring opponents, with a defense that is {d_t}'
    elif drtg_r <= 35 and drtg_r + 20 < ortg_r: ident = f'a defense-first team — they win by holding opponents down, with an offense that is {o_t}'
    elif ortg_r > 65 and drtg_r > 65: ident = 'a team in the bottom third of the state at both ends'
    else: ident = f'a balanced team — {o_t} on offense and {d_t} on defense'
    e.append(P(f'<b>Core Identity: {T} is {ident}.</b> {"They are " + c.rec_all + " so far" if c.ongoing else "They finished " + c.rec_all}, ranked <b>#{net_r}/{c.n} in Net Rating</b> '
               f'({sg(c.ta["net_rtg"])} pts per 100 possessions). Offensive Rating: {c.ta["ortg"]:.1f} (#{ortg_r}/{c.n} statewide, state avg '
               f'{AVG(c, "ortg")}) — {o_t}. Defensive Rating: {c.ta["drtg"]:.1f} (#{drtg_r}/{c.n} statewide, state avg {AVG(c, "drtg")}) '
               f'— {d_t}. Point differential: {sg(c.avgs["PTS"] - c.opp_avgs["PTS"])} PPG ({c.avgs["PTS"]:.1f} scored, {c.opp_avgs["PTS"]:.1f} allowed).',
               S(9.5, space_after=8)))

    e.append(Paragraph('<b>Roster Profile — Size and Scoring Structure</b>', S(9.5, True, BLUE, space_after=3)))
    tall = sorted([(c.height[p['name']], p['name']) for p in c.rotation if c.height.get(p['name'])], reverse=True)[:2]
    if c.avg_h:
        e.append(P(f'<b>Roster height:</b> {T}’s average roster height is {_fmt_height(round(c.avg_h))} — ranked <b>#{c.h_rank} of '
                   f'{c.h_n} teams statewide</b> (state average {_fmt_height(round(c.state_avg_h))}).'
                   + (f' Tallest in the rotation: ' + ' and '.join(f'{_fmt_height(h)} {n}' for h, n in tall) + '.' if tall else ''), S(9.5, space_after=6)))
    else:
        e.append(P(f'<b>Roster height:</b> no roster heights were published for {T}' + (f'; tallest in the rotation by the position model: '
                   + ' and '.join(f'{_fmt_height(h)} {n}' for h, n in tall) if tall else '') + '.', S(9.5, space_after=6)))
    if c.dep:
        more = 'more guard-reliant' if c.gdi > c.gdi_avg else 'more big-dependent'
        e.append(P(f'<b>Guard Dependence Index (GDI): {c.gdi:.1f} — #{c.gdi_rank}/{c.gdi_n} statewide (state avg {c.gdi_avg:.1f}).</b> '
                   f'GDI measures how reliant a team is on guards for scoring and playmaking. {T}’s {c.gdi:.1f} is '
                   f'<b>{"above" if c.gdi > c.gdi_avg else "below"} the state average</b> of {c.gdi_avg:.1f}, meaning they are {more} than a '
                   f'typical CCCAA team. Scoring breaks down as: <b>guards {c.dep.get("guard_pts_pct", 0):.1f}%</b> · <b>wings '
                   f'{c.dep.get("wing_pts_pct", 0):.1f}%</b> · <b>bigs {c.dep.get("big_pts_pct", 0):.1f}%</b>. Guards generate '
                   f'{c.dep.get("guard_ast_pct", 0):.1f}% of assists.', S(9.5, space_after=8)))

    efg_r, ts_r, ftr_r, tov_r, oreb_r = R(c, 'efg_pct'), R(c, 'ts_pct'), R(c, 'ft_rate'), R(c, 'tov_pct'), R(c, 'oreb_pct')
    e.append(Paragraph(f'<b>Offensive Profile — {tier_of(ortg_r, c.n).replace("Avg", "Average")} Efficiency (ORTg #{ortg_r}/{c.n})</b>', S(9.5, True, BLUE, space_after=3)))
    top = rot_by(c, lambda p: A(p).get('PTS', 0))[:1]
    eng = ''
    if top:
        p = top[0]; pr, pn = pool_rank(c.all_players, 'ppg', A(p)['PTS'])
        eng = f' Their leading scorer is {p["name"]} ({A(p)["PTS"]:.1f} PPG, #{pr}/{pn} statewide, {A(p).get("FG%", 0):.1f} FG%).'
    e.append(P(f'<b>Shooting efficiency (eFG% {me["efg_pct"]:.1f}%, #{efg_r}/{c.n}; TS% {me["ts_pct"]:.1f}%, #{ts_r}/{c.n}):</b> '
               f'The state average is {AVG(c, "efg_pct")}% eFG% and {AVG(c, "ts_pct")}% TS%; {T}’s shooting is {tw(efg_r, c.n)} by eFG% and '
               f'{tw(ts_r, c.n)} by TS% ({sg(me["ts_pct"] - AVG(c, "ts_pct"))} vs avg).{eng}', S(9.5, space_after=6)))
    vol = [p for p in rot_by(c, lambda p: A(p).get('3PA', 0)) if A(p).get('3PA', 0) >= 3.0]
    tpar_r = R(c, '3par')
    e.append(P(f'<b>Three-point profile (3PAR {me["3par"]:.1f}%, #{tpar_r}/{c.n}; team 3P% {c.avgs.get("3P%", 0):.1f}%):</b> '
               f'{"High" if tpar_r <= 35 else "Low" if tpar_r > 65 else "Average"} three-point volume: {c.avgs.get("3PA", 0):.1f} attempts a game. '
               + (f'{len(vol)} rotation player{"s" if len(vol) != 1 else ""} average 3.0+ attempts a game: '
                  + ', '.join(f'{last(p["name"])} {A(p).get("3P%", 0):.1f}% ({A(p)["3PA"]:.1f} 3PA)' for p in vol) + '.'
                  if vol else 'No rotation player averages 3.0+ attempts a game.'), S(9.5, space_after=6)))
    fta_top = rot_by(c, lambda p: A(p).get('FTA', 0))[:2]
    e.append(P(f'<b>FT Rate ({me["ft_rate"]:.1f}, #{ftr_r}/{c.n}, avg {AVG(c, "ft_rate")}):</b> {tw(ftr_r, c.n).capitalize()} access to the foul line. '
               + ('Most free-throw attempts: ' + ', '.join(f'{last(p["name"])} {A(p)["FTA"]:.1f} FTA/g at {A(p).get("FT%", 0):.1f}%' for p in fta_top) + '.' if fta_top else ''),
               S(9.5, space_after=6)))
    to_top = rot_by(c, lambda p: A(p).get('TO', 0))[:1]
    e.append(P(f'<b>Ball security (TOV% {me["tov_pct"]:.1f}%, #{tov_r}/{c.n}, avg {AVG(c, "tov_pct")}%):</b> {tw(tov_r, c.n).capitalize()} possession care '
               f'statewide. NST% {me["nst_pct"]:.1f}% (#{R(c, "nst_pct")}/{c.n}) counts the turnovers opponents did not create with a steal. '
               f'AST/TO {me["ast_to"]:.2f} (#{R(c, "ast_to")}/{c.n}) and AST Ratio {me["ast_ratio"]:.1f} (#{R(c, "ast_ratio")}/{c.n}) place them '
               f'{tw(R(c, "ast_to"), c.n)} in ball-sharing statewide.'
               + (f' Most turnovers: {to_top[0]["name"]}, {A(to_top[0])["TO"]:.1f} a game.' if to_top else ''), S(9.5, space_after=6)))
    or_top = [p for p in rot_by(c, lambda p: A(p).get('OREB', 0))[:2] if A(p).get('OREB', 0) >= 1.0]
    e.append(P(f'<b>Offensive rebounding (OREB% {me["oreb_pct"]:.1f}%, #{oreb_r}/{c.n}, avg {AVG(c, "oreb_pct")}%):</b> {tw(oreb_r, c.n).capitalize()} '
               f'on the offensive glass.' + (' Most offensive rebounds: ' + ', '.join(f'{last(p["name"])} {A(p)["OREB"]:.1f} a game' for p in or_top) + '.' if or_top else ''),
               S(9.5, space_after=8)))

    oefg_r, ots_r, otov_r, dreb_r, fc_r = R(c, 'opp_efg_pct'), R(c, 'opp_ts_pct'), R(c, 'opp_tov_pct'), R(c, 'dreb_pct'), R(c, 'fc_per_40')
    e.append(Paragraph(f'<b>Defensive Profile — {tier_of(drtg_r, c.n).replace("Avg", "Average")} (DRTg #{drtg_r}/{c.n})</b>', S(9.5, True, BLUE, space_after=3)))
    e.append(P(f'<b>Shooting suppression (Opp eFG% {me["opp_efg_pct"]:.1f}%, #{oefg_r}/{c.n}; Opp TS% {me["opp_ts_pct"]:.1f}%, #{ots_r}/{c.n}):</b> '
               f'State average is {AVG(c, "opp_efg_pct")}% Opp eFG% and {AVG(c, "opp_ts_pct")}% Opp TS%; opponents shoot {tw(oefg_r, c.n)} against them '
               f'by this measure (rank 1 = lowest opponent eFG%).', S(9.5, space_after=6)))
    stl_top = rot_by(c, lambda p: A(p).get('STL', 0))[:1]
    e.append(P(f'<b>Turnover pressure (Opp TOV% {me["opp_tov_pct"]:.1f}%, #{otov_r}/{c.n}, avg {AVG(c, "opp_tov_pct")}%):</b> {tw(otov_r, c.n).capitalize()} '
               f'at generating opponent turnovers. STL% {me["stl_pct"]:.1f}% (#{R(c, "stl_pct")}/{c.n}), BLK% {me["blk_pct"]:.1f}% (#{R(c, "blk_pct")}/{c.n}), '
               f'HKM% {me["hkm_pct"]:.1f}% (#{R(c, "hkm_pct")}/{c.n}), STL/TOV {me["stl_to"]:.2f} (#{R(c, "stl_to")}/{c.n}).'
               + (f' Most steals: {stl_top[0]["name"]}, {A(stl_top[0])["STL"]:.1f} a game.' if stl_top else ''), S(9.5, space_after=6)))
    e.append(P(f'<b>Defensive rebounding ({me["dreb_pct"]:.1f}%, #{dreb_r}/{c.n}, avg {AVG(c, "dreb_pct")}%) and foul discipline (PF/G '
               f'{me["fc_per_40"]:.1f}, #{fc_r}/{c.n}):</b> {tw(dreb_r, c.n).capitalize()} on the defensive glass. Foul rate is {tw(fc_r, c.n)} '
               f'(rank 1 = fewest fouls). PF Eff {me["pf_eff"]:.2f} (#{R(c, "pf_eff")}/{c.n}) — steals plus blocks per foul.', S(9.5, space_after=8)))

    pace_r = R(c, 'pace')
    e.append(Paragraph('<b>Pace and Style</b>', S(9.5, True, BLUE, space_after=3)))
    e.append(P(f'{T} plays at {"above-average" if pace_r <= 35 else "below-average" if pace_r > 65 else "near-average"} pace: '
               f'{c.ta["possessions"]:.1f} possessions per game (#{pace_r}/{c.n}, state avg {AVG(c, "pace")}). PPG: {c.avgs["PTS"]:.1f} '
               f'(#{R(c, "ppg")}/{c.n} statewide). Opp PPG allowed: {c.opp_avgs["PTS"]:.1f} (#{R(c, "oppg")}/{c.n}). Three-point attempts make up '
               f'{me["3par"]:.1f}% of their shots (#{tpar_r}/{c.n}).', S(9.5, space_after=8)))

    early, late = c.games[:c.half], c.games[c.half:]
    ea, la = avg_net(early), avg_net(late)
    arc = 'improved' if la - ea > 3 else 'declined' if ea - la > 3 else 'held steady'
    e.append(Paragraph('<b>Season Arc</b>', S(9.5, True, BLUE, space_after=3)))
    halves = (f'{T} {arc} as the season progressed. First half (games 1–{len(early)}): {rec(early)}, avg net rating {sg(ea)}. Second half '
              f'(games {len(early) + 1}–{len(c.games)}): {rec(late)}, avg net rating {sg(la)}. ') if len(c.games) >= ARC_MIN_GAMES else \
             f'First half / second half: \u2014 ({len(c.games)} game{"s" if len(c.games) != 1 else ""} so far). '
    e.append(P(halves + f'Conference: {rec_or_dash([g for g in c.games if g.get("is_conference")])}; '
               f'non-conference: {rec_or_dash([g for g in c.games if not g.get("is_conference")])}.', S(9.5, space_after=8)))

    e.append(Paragraph('<b>Moorpark-Specific Context</b>', S(9.5, True, BLUE, space_after=3)))
    if c.h2h:
        parts = [f'{g["date"]} ({g["location"]}, {g["result"]} {g["team_score"]}–{g["opponent_score"]}): Moorpark ORTg {g["ortg"]:.1f}, DRTg {g["drtg"]:.1f}' for g in c.h2h]
        above = sum(g['ortg'] > c.ta['drtg'] for g in c.h2h)
        e.append(P(f'Moorpark is {l}–{w} against {T} this season. ' + '; '.join(parts) + f'. Moorpark scored above {T}’s season DRTg '
                   f'({c.ta["drtg"]:.1f}) in {above} of {len(c.h2h)} meeting{"s" if len(c.h2h) != 1 else ""}.', S(9.5, space_after=8)))
    else:
        e.append(P(f'Moorpark and {T} have not met this season. Moorpark: ORTg {c.mp["ortg"]:.1f} (#{state_rank(c, "ortg", c.mp["ortg"])[0]}/{c.n}), '
                   f'DRTg {c.mp["drtg"]:.1f} (#{state_rank(c, "drtg", c.mp["drtg"])[0]}/{c.n}); {T}: ORTg {c.ta["ortg"]:.1f} (#{ortg_r}/{c.n}), '
                   f'DRTg {c.ta["drtg"]:.1f} (#{drtg_r}/{c.n}).', S(9.5, space_after=8)))

    def _tier_badge(rank, n):
        t = tier_of(rank, n)
        col = {'Elite': GREEN_TXT, 'Above Avg': colors.HexColor('#1a5c20'), 'Average': MID, 'Below Avg': colors.HexColor('#7b3b00'), 'Poor': RED_TXT}[t]
        return Paragraph(f'<b>{t}</b>', S(7.5, t != 'Average', col, TA_CENTER))
    def _adv_row(label, key, unit):
        r = R(c, key)
        return [Paragraph(label, S(7.5, False, DARK)), Paragraph(f'{me[key]:.1f}{unit}', S(8.5, True, BLUE, TA_CENTER)),
                Paragraph(f'#{r}/{c.n}', S(7.5, False, MID, TA_CENTER)), _tier_badge(r, c.n)]
    hdr = lambda t: [Paragraph(f'<b>{t}</b>', S(8, True, c.OPP_TXT, TA_CENTER))] + [Paragraph(f'<b>{x}</b>', S(7, True, c.OPP_TXT, TA_CENTER)) for x in ('VALUE', 'RANK', 'TIER')]
    off = [hdr('ADV OFFENSE')] + [_adv_row(*x) for x in [('ORtg', 'ortg', ''), ('eFG%', 'efg_pct', '%'), ('TS%', 'ts_pct', '%'), ('OREB%', 'oreb_pct', '%'),
        ('FT Rate', 'ft_rate', ''), ('3PAR', '3par', '%'), ('AST Rate', 'ast_rate', '%'), ('AST Ratio', 'ast_ratio', ''), ('AST/TO', 'ast_to', ''),
        ('TOV%', 'tov_pct', '%'), ('NST%', 'nst_pct', '%'), ('Tempo', 'pace', '')]]
    dfn = [hdr('ADV DEFENSE')] + [_adv_row(*x) for x in [('DRtg', 'drtg', ''), ('Opp eFG%', 'opp_efg_pct', '%'), ('Opp TS%', 'opp_ts_pct', '%'),
        ('DREB%', 'dreb_pct', '%'), ('Opp FT Rate', 'opp_ft_rate', ''), ('Opp TOV%', 'opp_tov_pct', '%'), ('STL%', 'stl_pct', '%'), ('BLK%', 'blk_pct', '%'),
        ('HKM%', 'hkm_pct', '%'), ('STL/TOV', 'stl_to', ''), ('PF Eff', 'pf_eff', ''), ('STL/PF', 'stl_pf', ''), ('BLK/PF', 'blk_pf', ''), ('PF/G', 'fc_per_40', '')]]
    def _mk(rows):
        t = Table(rows, colWidths=[1.5 * inch, 0.62 * inch, 0.62 * inch, 0.71 * inch])
        st = [('BACKGROUND', (0, 0), (-1, 0), c.OPP), ('INNERGRID', (0, 0), (-1, -1), 0.3, MGRAY), ('BOX', (0, 0), (-1, -1), 0.7, c.OPP),
              ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('ALIGN', (0, 1), (0, -1), 'LEFT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
              ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4), ('LEFTPADDING', (0, 0), (0, -1), 5)]
        st += [('BACKGROUND', (0, i), (-1, i), LGRAY if i % 2 == 1 else WHITE) for i in range(1, len(rows))]
        t.setStyle(TableStyle(st)); return t
    wr = Table([[_mk(off), '', _mk(dfn)]], colWidths=[3.45 * inch, 0.1 * inch, 3.45 * inch])
    wr.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    SECTIONS.append('Advanced Offense / Defense tables')
    e += [wr, Spacer(1, 6), PageBreak()]
    return e

def matchup_rows(c):
    """The four factors at both ends of this matchup. Each row puts an offense against the defense it faces: the
    expected value is the offense's number plus what the defense allows, minus the state average (an average offense
    against an average defense gets the average). The edge is that expected value against the state average, for the
    side it favors: a good offense against a defense that allows a lot is the offense's edge; a defense that allows
    little is the defense's. their = the edge for the opponent (negative = Moorpark's)."""
    me, mp, ab = c.me, c.mp, c.abbr
    out = []
    for side, (f, key, hb, off, dfn, offlab, deflab) in [(s_, r) for s_, rs in (
            ('them', [('eFG%', 'efg_pct', True, me['efg_pct'], mp['opp_efg_pct'], f'{ab} eFG%', 'Moorpark Opp eFG%'),
                      ('TOV%', 'tov_pct', False, me['tov_pct'], mp['opp_tov_pct'], f'{ab} TOV%', 'Moorpark Opp TOV%'),
                      ('OREB%', 'oreb_pct', True, me['oreb_pct'], 100 - mp['dreb_pct'], f'{ab} OREB%', 'Moorpark allows (100 - DREB%)'),
                      ('FT Rate', 'ft_rate', True, me['ft_rate'], mp['opp_ft_rate'], f'{ab} FT Rate', 'Moorpark Opp FT Rate')]),
            ('us', [('eFG%', 'efg_pct', True, mp['efg_pct'], me['opp_efg_pct'], 'Moorpark eFG%', f'{ab} Opp eFG%'),
                    ('TOV%', 'tov_pct', False, mp['tov_pct'], me['opp_tov_pct'], 'Moorpark TOV%', f'{ab} Opp TOV%'),
                    ('OREB%', 'oreb_pct', True, mp['oreb_pct'], 100 - me['dreb_pct'], 'Moorpark OREB%', f'{ab} allows (100 - DREB%)'),
                    ('FT Rate', 'ft_rate', True, mp['ft_rate'], me['opp_ft_rate'], 'Moorpark FT Rate', f'{ab} Opp FT Rate')])) for r in rs]:
        lg = AVG(c, key); exp = off + dfn - lg
        off_edge = (exp - lg) if hb else (lg - exp)
        out.append({'side': side, 'f': f, 'off': off, 'def': dfn, 'exp': exp, 'lg': lg, 'their': off_edge if side == 'them' else -off_edge,
                    'text': f'{offlab} {off:.1f} vs {deflab} {dfn:.1f} (state avg {lg:.1f}): expected {exp:.1f} in this matchup'})
    return out

# ═══════════════════════════════════════════════════════════════════════════════════════
# PAGE 2 — STATEWIDE CONTEXT + FOUR FACTORS VS MOORPARK
# ═══════════════════════════════════════════════════════════════════════════════════════
def page_analytics(c):
    e, T, me = [], c.team, c.me
    e += section('Advanced Analytics: Statewide Context', 'All key efficiency metrics with CCCAA state rank. Rank 1 = best in state.')
    def crow(label, key, val, unit, note):
        r, n, avg, diff = state_rank(c, key, val)
        return [Paragraph(label, S(8)), f'{val:.1f}{unit}', f'#{r}/{n}', f'{avg:.1f}{unit}', f'{diff:+.1f}{unit}', tier_p(r, n), Paragraph(note, S(8))]
    rows = [crow('Off. Rating (ORTg)', 'ortg', me['ortg'], '', 'Points scored per 100 possessions'),
            crow('Def. Rating (DRTg)', 'drtg', me['drtg'], '', 'Points allowed per 100 possessions'),
            crow('Net Rating', 'net_rtg', me['net_rtg'], '', 'ORTg minus DRTg'),
            crow('True Shooting%', 'ts_pct', me['ts_pct'], '%', 'Overall shooting efficiency (all types)'),
            crow('Opp True Shooting%', 'opp_ts_pct', me['opp_ts_pct'], '%', 'How well opponents shoot'),
            crow('eFG% (offense)', 'efg_pct', me['efg_pct'], '%', 'FG% adjusted for 3-point value'),
            crow('Opp eFG% (defense)', 'opp_efg_pct', me['opp_efg_pct'], '%', 'Opponent eFG%, shooting suppression'),
            crow('Turnover % (offense)', 'tov_pct', me['tov_pct'], '%', f'How often {T} turns it over'),
            crow('Opp Turnover % (def)', 'opp_tov_pct', me['opp_tov_pct'], '%', f'How often {T} forces opponent TOs'),
            crow('Off. Reb% (offense)', 'oreb_pct', me['oreb_pct'], '%', '% of own missed shots recovered'),
            crow('Def. Reb% (defense)', 'dreb_pct', me['dreb_pct'], '%', '% of opponent missed shots recovered'),
            crow('FT Rate (offense)', 'ft_rate', me['ft_rate'], '', 'FTA per FGA'),
            crow('Opp FT Rate (defense)', 'opp_ft_rate', me['opp_ft_rate'], '', 'How often opponents draw fouls'),
            crow('Pace (poss/game)', 'pace', me['pace'], '', 'Possessions per game'),
            crow('PPG', 'ppg', me['ppg'], '', 'Points per game'),
            crow('Opp PPG', 'oppg', me['oppg'], '', 'Points allowed per game')]
    rc = []
    for i, r in enumerate(rows):
        rv = int(r[2].split('/')[0][1:])
        if rv <= 15: rc.append(('BACKGROUND', (0, i + 1), (-1, i + 1), colors.HexColor('#f0fff4')))
        elif rv >= 86: rc.append(('BACKGROUND', (0, i + 1), (-1, i + 1), colors.HexColor('#fff0f0')))
    ct = Table([['METRIC', c.abbr, 'RANK', 'ST. AVG', 'VS AVG', 'TIER', 'CONTEXT']] + rows,
               colWidths=[1.65 * inch, 0.75 * inch, 0.7 * inch, 0.7 * inch, 0.7 * inch, 0.9 * inch, 1.55 * inch])
    ct.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), TH_BG), ('TEXTCOLOR', (0, 0), (-1, 0), WHITE), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('ALIGN', (0, 1), (0, -1), 'LEFT'), ('ALIGN', (6, 1), (6, -1), 'LEFT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, ALT]), ('INNERGRID', (0, 0), (-1, -1), 0.3, MGRAY), ('BOX', (0, 0), (-1, -1), 0.5, TH_BG),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3), ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4)] + rc))
    e += [ct, Spacer(1, 10)]

    e += section('Four Factors Comparison', f'{T} vs. Moorpark \u2014 the two matchup pillars. Expected = the offense\u2019s number + what the '
                 f'defense allows \u2212 the state average; the edge goes to the side it favors, by how far it lands from the average.')
    M, mp = matchup_rows(c), c.mp
    def edge(r):
        mine = r['their'] > 0; who = c.abbr if mine else 'MPC'
        return Paragraph(f'<b>{who} +{abs(r["their"]):.1f}</b>', S(8, True, RED_TXT if mine else GREEN_TXT, TA_CENTER))
    fmt = lambda v, f: f'{v:.1f}' + ('%' if f != 'FT Rate' else '')
    them, us = [r for r in M if r['side'] == 'them'], [r for r in M if r['side'] == 'us']
    ff = [[a['f'], fmt(me[k], a['f']), fmt(mpd, a['f']), edge(a), fmt(me[k2], a['f']), fmt(mpo, a['f']), edge(b)]
          for a, b, k, k2, mpd, mpo in zip(them, us, ['efg_pct', 'tov_pct', 'oreb_pct', 'ft_rate'], ['opp_efg_pct', 'opp_tov_pct', 'dreb_pct', 'opp_ft_rate'],
                                           [mp['opp_efg_pct'], mp['opp_tov_pct'], mp['dreb_pct'], mp['opp_ft_rate']], [mp['efg_pct'], mp['tov_pct'], mp['oreb_pct'], mp['ft_rate']])]
    ft = Table([['FACTOR', f'{c.abbr} OFF', 'MPC DEF', 'EDGE', f'{c.abbr} DEF', 'MPC OFF', 'EDGE']] + ff,
               colWidths=[1.0 * inch, 0.95 * inch, 0.95 * inch, 0.85 * inch, 0.95 * inch, 0.95 * inch, 0.85 * inch])
    ft.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), TH_BG), ('TEXTCOLOR', (0, 0), (-1, 0), WHITE), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, ALT]), ('INNERGRID', (0, 0), (-1, -1), 0.3, MGRAY), ('BOX', (0, 0), (-1, -1), 0.5, TH_BG),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4), ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4)]))
    e += [ft, PageBreak()]
    return e

# ═══════════════════════════════════════════════════════════════════════════════════════
# SYNERGY (the Moorpark report's Synergy layer, for any team with an export)
#   internal_data/synergy_team_<team>_<season>.json     play types, offense and defense
#   internal_data/synergy_players_<team>_<season>.json  players: scoring_summary, shot_types, drive_direction, notes
#   (players also come from synergy_archetypes.json rows whose "team" is this team)
# Both team-file layouts in use are read: Moorpark's (play_type, time_rank, ppp_rank, ppp_rating, two_fg_pct, to_pct)
# and Ventura's (name, pctile, rating, efg). A table shows the columns its file has.
# ═══════════════════════════════════════════════════════════════════════════════════════
def nkey(n): return re.sub(r'[^a-z0-9]', '', (n or '').lower())
def x_(t): return (t or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')   # export text into a Paragraph

def syn_path(kind, team, season):
    return os.path.join(HERE, 'internal_data', f'synergy_{kind}_{slug(team)}_{season.replace("-", "_")}.json')

def norm_pt(pt):
    return {'name': x_((pt.get('play_type') or pt.get('name') or '').replace('Offensive Rebounds (Put Backs)', 'OREB / Put Backs').replace('Miscellaneous Plays', 'Miscellaneous')),
            'poss': pt.get('poss', 0) or 0, 'pct_time': pt.get('pct_time'), 'time_rank': pt.get('time_rank'), 'ppp': pt.get('ppp'),
            'pctile': pt.get('ppp_rank', pt.get('pctile')), 'rating': pt.get('ppp_rating', pt.get('rating')) or '',
            'two_fg_pct': pt.get('two_fg_pct'), 'efg': pt.get('efg_pct', pt.get('efg')), 'to_pct': pt.get('to_pct')}

def load_team_syn(team, season):
    path = syn_path('team', team, season)
    if not os.path.exists(path): return None
    d = jload(path)
    return {'games': d.get('games_played', d.get('games')), 'off': [norm_pt(x) for x in d.get('offense', {}).get('play_types', [])],
            'def': [norm_pt(x) for x in d.get('defense', {}).get('play_types', [])], 'path': os.path.relpath(path, HERE)}

def load_synergy(c):
    c.syn_team, c.syn_mp, c.syn_players = load_team_syn(c.team, c.season), load_team_syn('Moorpark', c.season), {}
    arch = os.path.join(HERE, 'internal_data', 'synergy_archetypes.json')
    if os.path.exists(arch):
        for x in jload(arch):
            if x.get('team') == c.team: c.syn_players[nkey(x['name'])] = x
    pp = syn_path('players', c.team, c.season)
    if os.path.exists(pp):
        for x in jload(pp): c.syn_players[nkey(x['name'])] = x

def SYNP(c, p): return c.syn_players.get(nkey(p['name']))

def ordn(n):
    n = int(round(n)); return f'{n}{"th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")}'

# The Moorpark report's two archetypes, unchanged (generate_moorpark_scouting_report.py): computed from the Synergy
# play-type mix and shot profile; never shown without Synergy data.
_BIG_POS, _GUARD_POS = {'S-PF', 'PF/C', 'C'}, {'PG', 's-PG', 'CG'}
_BI_PATS = [('spotup', r'spot ?up|spots up'), ('pnr_bh', r'p&?r bh|pick.?and.?roll bh'),
            ('postup', r'post.?up'), ('iso', r'isolation|iso\b'), ('transition', r'transition'),
            ('offscreen', r'off.?screen'), ('handoff', r'hand.?off|dho'), ('cut', r'\bcut'),
            ('roll', r'roll man|p&?r man|p&?r roll'), ('putback', r'put.?back')]
def _parse_playtypes(summary):
    s_ = (summary or '').lower(); out = {}
    for k, pat in _BI_PATS:
        m = re.search('(?:' + pat + r')[^0-9]{0,18}?(\d+)\s*%', s_)
        if m and m.group(1): out[k] = int(m.group(1))
    return out

def bball_index_archetype(pos, adv, tot, sa):
    if not sa: return None
    st = sa.get('shot_types') or {}; pt = _parse_playtypes(sa.get('scoring_summary'))
    usg = adv.get('usage_pct', 0) or 0; ast = adv.get('ast_rate', 0) or 0
    fga = tot.get('FGA', 0) or 0
    ftr = (tot.get('FTA', 0) / fga * 100) if fga else 0
    tpar = (tot.get('3PA', 0) / fga * 100) if fga else 0
    rim = st.get('at_rim_pct_fga', 0) or 0; js = st.get('jump_shot_pct_fga', 0) or 0
    cs = st.get('catch_shoot_pct_of_js', 0) or 0; pullup = 100 - cs
    move = pt.get('offscreen', 0) + pt.get('handoff', 0)
    if pos in _BIG_POS:
        if tpar >= 20: return 'Stretch Big'
        if pt.get('postup', 0) >= 15 or usg >= 24: return 'Post-Up Big'
        if rim >= 45 or pt.get('cut', 0) + pt.get('roll', 0) + pt.get('putback', 0) >= 18: return 'Roll + Cut Big'
        return 'Versatile Big'
    creator = pt.get('pnr_bh', 0) + pt.get('iso', 0)
    if ast >= 22 and (creator >= 6 or usg >= 18): return 'Primary Ball Handler' if usg >= 22 else 'Secondary Ball Handler'
    if rim >= 45: return 'Slasher' if (ftr >= 20 or pt.get('iso', 0) >= 6) else 'Athletic Finisher'
    if (usg >= 23 and (creator >= 14 or pullup >= 45)) or creator >= 22: return 'Primary Ball Handler' if ast >= 18 else 'Shot Creator'
    has_shots = bool(st)
    if (has_shots and js >= 50 and cs >= 50) or (not has_shots and pt.get('spotup', 0) >= 28):
        if move >= 10: return 'Movement Shooter'
        if pt.get('spotup', 0) >= 30: return 'Stationary Shooter'
        return 'Off-Ball Shooter'
    if rim >= 30 or ftr >= 28 or pt.get('iso', 0) >= 10: return 'Slasher' if (ftr >= 25 or pt.get('iso', 0) >= 8) else 'Athletic Finisher'
    if ast >= 15 and creator >= 8: return 'Secondary Ball Handler'
    if cs >= 48 and js >= 45: return 'Off-Ball Shooter'
    return 'Connector / Role'

def synergy_archetype(pos, sa, tot, apg):
    if not sa: return None
    pt = _parse_playtypes(sa.get('scoring_summary'))
    fga = tot.get('FGA', 0) or 0
    tpar = (tot.get('3PA', 0) / fga * 100) if fga else 0
    ftar = (tot.get('FTA', 0) / fga * 100) if fga else 0
    spot = pt.get('spotup', 0); move = pt.get('offscreen', 0) + pt.get('handoff', 0)
    rim = (sa.get('shot_types') or {}).get('at_rim_pct_fga', 0) or 0
    if pos in _BIG_POS:
        if apg >= 2.0: return 'Playmaking Big'
        if ftar >= 40 and tpar <= 12: return 'Post-up Big'
        if tpar >= 18: return 'Stretch Big'
        return 'Rim-finishing'
    if pos in _GUARD_POS:
        if apg >= 3.5: return 'Playmaking Ball Handler'
        if tpar >= 45 or spot >= 30: return 'Secondary Ball Handler'
        return 'Scoring Ball Handler'
    if apg >= 2.5: return 'Playmaking Wing'
    if rim >= 45 or (ftar >= 28 and tpar <= 30): return 'Slashing Wing'
    if tpar >= 55 or spot >= 45: return 'Spot-up Wing'
    if tpar >= 22 or move >= 10: return 'Dynamic Wing'
    return 'Slashing Wing'

RATING_COLORS = {'Excellent': (GREEN_BG, GREEN_TXT), 'Very Good': (colors.HexColor('#c8e6c9'), GREEN_TXT),
                 'Good': (YELLOW_BG, colors.HexColor('#5c4200')), 'Average': (colors.HexColor('#f5f5f5'), MID),
                 'Below Average': (RED_BG, RED_TXT), 'Poor': (colors.HexColor('#f5c6cb'), RED_TXT)}

def pt_line(x, defense=False):
    pct = f'{x["pct_time"]:.1f}% of possessions, ' if x.get('pct_time') is not None else ''
    return (f'{x["name"]} ({pct}{x["ppp"]:.3f} PPP' + (f', {ordn(x["pctile"])} pctile' if x.get('pctile') is not None else '')
            + (f' — {x["rating"]}' if x.get('rating') else '') + ')')

def page_synergy(c):
    if not c.syn_team: return []   # the pre-Synergy edition has no Synergy section
    T = c.team
    e = section('Synergy Sports — Play Type Profile',
                (f'Play type breakdown across {c.syn_team["games"]} games. ' if c.syn_team and c.syn_team.get('games') else '')
                + f'Offense: how {T} generates offense by play type. Defense: how opponents score against {T} by play type. '
                'T-Rank = percentile for how often they run it vs. peers. Pctile = PPP percentile: on offense higher is better; '
                'on defense higher means opponents were held down (better defense).')
    def table(rows, defense):
        rows = sorted(rows, key=lambda x: -x['poss'])
        cols = [('Play Type', None, 2.1), ('Poss', lambda x: str(x['poss']), 0.6),
                ('%Time', lambda x: f'{x["pct_time"]:.1f}%' if x.get('pct_time') is not None else '—', 0.65)]
        if any(x.get('time_rank') is not None for x in rows): cols.append(('T-Rank', lambda x: str(x['time_rank']) if x.get('time_rank') is not None else '—', 0.6))
        cols += [('PPP', lambda x: f'{x["ppp"]:.3f}', 0.6), ('Pctile', lambda x: str(x['pctile']) if x.get('pctile') is not None else '—', 0.6), ('Rating', None, 1.1)]
        if any(x.get('two_fg_pct') is not None for x in rows): cols.append(('2FG%', lambda x: f'{x["two_fg_pct"]:.1f}%' if x.get('two_fg_pct') is not None else '—', 0.65))
        elif any(x.get('efg') is not None for x in rows): cols.append(('eFG%', lambda x: f'{x["efg"]:.1f}%' if x.get('efg') is not None else '—', 0.65))
        if any(x.get('to_pct') is not None for x in rows): cols.append(('TO%', lambda x: f'{x["to_pct"]:.1f}%' if x.get('to_pct') is not None else '—', 0.55))
        hdr = [Paragraph(h, S(8, True, WHITE, TA_CENTER)) for h, _, _ in cols]
        ri_rating, ri_ppp = [h for h, _, _ in cols].index('Rating'), [h for h, _, _ in cols].index('PPP')
        body, dyn = [], []
        for i, x in enumerate(rows, 1):
            bg, tc = RATING_COLORS.get(x['rating'], (WHITE, BLACK))
            dyn += [('BACKGROUND', (ri_rating, i), (ri_rating, i), bg)]
            if defense and x['ppp'] is not None:
                if x['ppp'] >= 1.0: dyn += [('TEXTCOLOR', (ri_ppp, i), (ri_ppp, i), RED_TXT), ('FONTNAME', (ri_ppp, i), (ri_ppp, i), 'Helvetica-Bold')]
                elif x['ppp'] < 0.75: dyn += [('TEXTCOLOR', (ri_ppp, i), (ri_ppp, i), GREEN_TXT), ('FONTNAME', (ri_ppp, i), (ri_ppp, i), 'Helvetica-Bold')]
            body.append([Paragraph(x['name'], S(8)) if h == 'Play Type' else Paragraph(x['rating'], S(8, True, tc, TA_CENTER)) if h == 'Rating' else f(x)
                         for h, f, _ in cols])
        widths = [w for _, _, w in cols]; k = 7.5 / sum(widths)
        t = Table([hdr] + body, colWidths=[w * k * inch for w in widths], repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), TH_BG), ('FONTSIZE', (0, 1), (-1, -1), 8), ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, ALT]), ('INNERGRID', (0, 0), (-1, -1), 0.3, MGRAY),
            ('BOX', (0, 0), (-1, -1), 0.5, TH_BG), ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')] + dyn))
        return t
    st = c.syn_team
    e += [Spacer(1, 8), Paragraph(f'OFFENSE — How {T} Creates', S(10, True, BLUE)), Spacer(1, 4), table(st['off'], False)]
    e += [Spacer(1, 10), Paragraph(f'DEFENSE — How Opponents Score Against {T}', S(10, True, BLUE)),
          Paragraph('Pctile = how well they hold opponents vs. other teams; higher = better defense. PPP of 1.0+ in red, under 0.75 in green.',
                    S(8, False, MID, space_after=4)), Spacer(1, 4), table(st['def'], True)]
    # Key takeaways: the Moorpark report's box, written by rule from the tables.
    sig = lambda rows: [x for x in rows if (x.get('pct_time') or 0) >= 5 and x.get('ppp') is not None and x['name'] != 'Miscellaneous']
    take = []
    off, dfn = sorted(st['off'], key=lambda x: -x['poss']), sorted(st['def'], key=lambda x: -x['poss'])
    so, sd = sig(st['off']), sig(st['def'])
    if off:
        best = max(so, key=lambda x: x['ppp']) if so else None; worst = min(so, key=lambda x: x['ppp']) if so else None
        take.append((f'<b>Offensive Identity:</b> {T}’s most-used play types are ' + ' and '.join(pt_line(x) for x in off[:2]) + '.'
                     + (f' Most efficient of their regular play types (5%+ of possessions): {pt_line(best)}.' if best else '')
                     + (f' Least efficient: {pt_line(worst)}.' if worst and worst is not best else ''), LGRAY))
    if dfn:
        sd_p = [x for x in sd if x.get('pctile') is not None]
        bd = max(sd_p, key=lambda x: x['pctile']) if sd_p else None; wd = min(sd_p, key=lambda x: x['pctile']) if sd_p else None
        take.append((f'<b>Defense:</b> Opponents most often score against {T} through ' + ' and '.join(pt_line(x, True) for x in dfn[:2]) + '.'
                     + (f' Best-defended play type: {pt_line(bd, True)}.' if bd else '') + (f' Weakest: {pt_line(wd, True)}.' if wd and wd is not bd else ''), LGRAY))
    if c.syn_mp and dfn:
        dmap = {nkey(x['name']): x for x in st['def']}
        mo = [x for x in sorted(c.syn_mp['off'], key=lambda x: -x['poss']) if nkey(x['name']) in dmap and x['name'] != 'Miscellaneous'][:3]
        if mo:
            take.append(('<b>Moorpark’s Offense vs. Their Defense:</b> Moorpark’s most-used play types against how ' + T + ' defends them: '
                         + '; '.join(f'{x["name"]} — Moorpark {x["ppp"]:.3f} PPP ({ordn(x["pctile"])} pctile), {T} allows '
                                     f'{dmap[nkey(x["name"])]["ppp"]:.3f} ({ordn(dmap[nkey(x["name"])]["pctile"])} pctile)' for x in mo) + '.', ALT))
    e += [Spacer(1, 10), Paragraph('KEY TAKEAWAYS', S(9, True, BLUE)), HR(GOLD, 1, 2, 4)]
    for txt, bg in take:
        t = Table([[P(txt, S(8.5))]], colWidths=[7.5 * inch])
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), bg), ('BOX', (0, 0), (-1, -1), 0.5, MGRAY), ('TOPPADDING', (0, 0), (-1, -1), 6),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 6), ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8)]))
        e += [t, Spacer(1, 4)]
    e.append(PageBreak())
    return e

SHOTS = [('at_rim', 'at the rim'), ('catch_shoot', 'catch-and-shoot'), ('dribble_jumper', 'off the dribble'), ('three_pt', 'from three')]

def syn_sentences(c, p):
    """The Moorpark report's Synergy narrative, written by rule: where his shots come from and how each grades."""
    sa = SYNP(c, p)
    if not sa: return []
    st, out = sa.get('shot_types') or {}, []
    if st.get('at_rim_pct_fga') is not None:
        out.append(f'Synergy shot data: {st["at_rim_pct_fga"]:.1f}% of his attempts come at the rim ({st.get("at_rim_fg_pct", 0):.1f}% FG, '
                   f'{ordn(st.get("at_rim_pps_rank", 0))} pctile — {st.get("at_rim_pps_rating", "")})'
                   + (f'; {st["jump_shot_pct_fga"]:.1f}% are jumpers, {st.get("catch_shoot_pct_of_js", 0):.1f}% of them catch-and-shoot' if st.get('jump_shot_pct_fga') is not None else '') + '.')
    graded = [(st.get(f'{k}_pps_rank'), lab, st.get(f'{k}_fg_pct'), st.get(f'{k}_pps_rating')) for k, lab in SHOTS if st.get(f'{k}_pps_rank') is not None]
    if len(graded) >= 2:
        hi, lo = max(graded, key=lambda x: x[0]), min(graded, key=lambda x: x[0])
        out.append(f'His best-graded shot is {hi[1]} ({hi[2]:.1f}% FG, {ordn(hi[0])} pctile — {hi[3]}); his lowest is {lo[1]} '
                   f'({lo[2]:.1f}% FG, {ordn(lo[0])} pctile — {lo[3]}).')
    pts = _parse_playtypes(sa.get('scoring_summary'))
    if pts:
        names = {'spotup': 'Spot Up', 'pnr_bh': 'P&amp;R ball handler', 'postup': 'Post-Up', 'iso': 'Isolation', 'transition': 'Transition',
                 'offscreen': 'Off Screen', 'handoff': 'Handoffs', 'cut': 'Cuts', 'roll': 'P&amp;R roll man', 'putback': 'Put Backs'}
        top = sorted(pts.items(), key=lambda kv: -kv[1])[:3]
        out.append('Most-used play types: ' + ', '.join(f'{names[k]} {v}%' for k, v in top) + ' of his possessions.')
    return out

def syn_rows(c, p):
    """The Moorpark report's Synergy rows under a player's header: archetypes and play-type mix, the left-hand driver flag,
    the shot profile strip, and the written scouting notes from the export."""
    sa = SYNP(c, p)
    if not sa: return []
    avg, tot, adv = A(p), p['totals'], ADV(c, p)
    pos = c.pos.get(p['name']) or sa.get('pos') or ''
    out = []
    cells = [Paragraph(f'<b>Synergy Archetype:</b>  {synergy_archetype(pos, sa, tot, avg.get("AST", 0))}', S(8.5, False, GOLD))]
    bi = bball_index_archetype(pos, adv, tot, sa)
    if bi: cells.append(Paragraph(f'<b>bball-index Archetype:</b>  {bi}', S(8.5, False, colors.HexColor('#6fa8ff'))))
    if sa.get('scoring_summary'): cells.append(P(x_(sa['scoring_summary']), S(7.5, False, colors.HexColor('#aab8d0')), 'note'))
    t = Table([[x] for x in cells], colWidths=[7.5 * inch])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0d1a2e')), ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                           ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10), ('BOX', (0, 0), (-1, -1), 0.5, BLUE)]))
    out.append(t)
    dd = sa.get('drive_direction')
    if dd:   # flagged only for LEFT-dominant drivers (right is the norm): 55%+ of 10+ left/right drives
        lp = dd.get('drives_left_poss', dd.get('spot_up_left_poss', 0) + dd.get('iso_left_poss', 0))
        rp = dd.get('drives_right_poss', dd.get('spot_up_right_poss', 0) + dd.get('iso_right_poss', 0))
        mid = dd.get('drives_straight_poss', 0); dt = lp + rp
        if dt >= 10 and lp > rp and lp / dt >= 0.55:
            lppp = dd.get('drives_left_ppp', dd.get('spot_up_left_ppp', 0)) or 0; rppp = dd.get('drives_right_ppp', dd.get('spot_up_right_ppp', 0)) or 0
            eff = '  He is also more efficient going left.' if lppp > rppp + 0.05 else '  He is less efficient going left.' if rppp > lppp + 0.05 else ''
            note = dd.get('scouting_note', '')
            TEXT.append(('note', note))
            ft = (f'<b>&#9668; LEFT-HAND DOMINANT DRIVER &mdash;</b>  Of his directional drives, {round(lp / dt * 100)}% go left ({lp} left vs {rp} right'
                  f'{f", {mid} middle" if mid else ""}).' + eff + (f'<br/><i>{x_(note)}</i>' if note else ''))
            r = Table([[Paragraph(ft, S(8, False, colors.HexColor('#ffd54f')))]], colWidths=[7.5 * inch])
            r.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#2a1500')), ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                                   ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10), ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#e8a000'))]))
            out.append(r)
    st = sa.get('shot_types')
    if st:
        TEAL, TEAL_DK, TEAL_BD = colors.HexColor('#b2dfdb'), colors.HexColor('#001a18'), colors.HexColor('#26a69a')
        labs = [f'AT RIM ({st["at_rim_att"]} att)' if st.get('at_rim_att') else 'AT RIM', 'CATCH & SHOOT', 'DRIB. JUMPER',
                f'3-PT ({st["three_pt_att"]} att)' if st.get('three_pt_att') else '3-PT']
        vals = [(st.get(f'{k}_fg_pct', 0) or 0, st.get(f'{k}_pps_rating', '')) for k, _ in SHOTS]
        inner = Table([[Paragraph(l, S(6.5, True, TEAL, TA_CENTER)) for l in labs],
                       [Paragraph(f'<b>{v:.1f}%</b>  <font color="#b2dfdb">{r_}</font>', S(8.5, False, WHITE, TA_CENTER)) for v, r_ in vals]], colWidths=[1.875 * inch] * 4)
        inner.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), TEAL_DK), ('INNERGRID', (0, 0), (-1, -1), 0.3, TEAL_BD), ('BOX', (0, 0), (-1, -1), 0.5, TEAL_BD),
                                   ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4), ('LEFTPADDING', (0, 0), (-1, -1), 4),
                                   ('RIGHTPADDING', (0, 0), (-1, -1), 4), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
        out.append(inner)
        if st.get('scouting_note'):
            TEXT.append(('note', st['scouting_note']))
            n = Table([[Paragraph(f'<i>{x_(st["scouting_note"])}</i>', S(7.5, False, TEAL))]], colWidths=[7.5 * inch])
            n.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), TEAL_DK), ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                                   ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10), ('BOX', (0, 0), (-1, -1), 0.5, TEAL_BD)]))
            out.append(n)
    return out

# ═══════════════════════════════════════════════════════════════════════════════════════
# PLAYER PROFILES
# ═══════════════════════════════════════════════════════════════════════════════════════
def narrative(c, p, idx):
    """The written profile: who he is in the offense, then each part of his game that stands out statewide."""
    avg, tot, adv = A(p), p['totals'], ADV(c, p)
    name, T = p['name'], c.team
    mpg, gp, ppg = avg.get('MIN', 0), avg.get('games', 0), avg.get('PTS', 0)
    usage = adv.get('usage_pct', 0)
    box = box_rates(tot, c.me['pace'] if c.min_ok else 0, c.box_lg)
    by_pts = rot_by(c, lambda q: A(q).get('PTS', 0)); prank = by_pts.index(p) + 1
    s = []
    pr, pn = pool_rank(c.all_players, 'ppg', ppg)
    mn = mins(c, p)
    if prank == 1: s.append(f'{name} is {T}’s leading scorer: {ppg:.1f} PPG (#{pr}/{pn} statewide){mn} ({gp} GP).')
    elif prank == 2: s.append(f'{name} is {T}’s second-leading scorer: {ppg:.1f} PPG (#{pr}/{pn} statewide){mn} ({gp} GP).')
    else: s.append(f'{name} averages {ppg:.1f} PPG (#{pr}/{pn} statewide){mn} ({gp} GP), #{prank} in scoring among {T}’s rotation players.')
    rpg, apg = avg.get('REB', 0), avg.get('AST', 0)
    if not c.min_ok:   # no rates on these teams: the per-game lines and their state ranks stand in
        rr, rn = pool_rank(c.all_players, 'rpg', rpg); ar_, an = pool_rank(c.all_players, 'apg', apg)
        s.append(f'He adds {rpg:.1f} RPG (#{rr}/{rn}) and {apg:.1f} APG (#{ar_}/{an}); {avg.get("STL", 0):.1f} steals and {avg.get("TO", 0):.1f} turnovers a game.')
    if usage: s.append(f'He uses {usage:.1f}% of {T}’s possessions while on the floor ({kenpom_player_role(usage, mpg)[0]}).')
    ts = adv.get('ts_pct', 0)
    if ts and mpg >= 12:
        r, n = pool_rank(c.adv_players, 'ts_pct', ts); s.append(f'TS% {ts:.1f}% (#{r}/{n}) — {tw(r, n)} shooting efficiency among qualified players.')
        rel = [f'{lab} {box[k]:+.1f} (#{r}/{n})' for k, lab in (('rts', 'rTS%'), ('tsadd', 'TSAdd/100')) if box.get(k) is not None
               for r, n in [pool_rank(c.adv_players, k, box[k])] if n]
        if rel: s.append('Against a league-average shooter: ' + ', '.join(rel) + '.')
    tpa, tpp = avg.get('3PA', 0), avg.get('3P%', 0)
    if tpa >= 1.0:
        r, n = pool_rank(c.all_players, 'tpp', tpp, True, lambda q: q.get('tpa', 0) >= 2) if tpa >= 2 else (0, 0)
        s.append(f'He shoots {tpp:.1f}% on {tpa:.1f} 3PA a game' + (f' (#{r}/{n} among players with 2+ 3PA a game, {tw(r, n)}).' if r else '.'))
        tr = []
        if tpa >= 2 and box.get('tp_rts') is not None:
            r, n = pool_rank(c.all_players, 'tp_rts', box['tp_rts'], True, lambda q: q.get('tpa', 0) >= 2); tr.append(f'3P rTS% {box["tp_rts"]:+.1f} (#{r}/{n})')
        if box.get('tpr') is not None:
            r, n = pool_rank(c.all_players, 'tpr', box['tpr'], True, lambda q: q.get('fga', 0) >= 2); tr.append(f'3PR {box["tpr"]:.1f}% of his shots from three (#{r}/{n})')
        if tr: s.append('; '.join(tr) + '.')
    elif tot.get('3PA', 0) <= 3: s.append(f'He has taken {tot.get("3PA", 0)} three-point attempt{"s" if tot.get("3PA", 0) != 1 else ""} {"so far this season" if c.ongoing else "all season"}.')
    twoa = tot.get('FGA', 0) - tot.get('3PA', 0)
    if twoa >= 40:
        twop = (tot.get('FGM', 0) - tot.get('3PM', 0)) / twoa * 100; r, n = pool_rank(c.all_players, 'twop', twop, True, lambda q: q.get('fga', 0) >= 5)
        s.append(f'Two-point FG%: {twop:.1f}% (#{r}/{n}) on {twoa / max(gp, 1):.1f} attempts a game.')
    fta, ftp = avg.get('FTA', 0), avg.get('FT%', 0)
    if fta >= 1.0: s.append(f'At the line: {ftp:.1f}% on {fta:.1f} FTA a game.')
    if mpg >= 12:
        for key, lab, word in (('oreb_pct', 'OREB%', 'offensive rebounding'), ('dreb_pct', 'DREB%', 'defensive rebounding'),
                               ('ast_rate', 'AST Rate', 'playmaking'), ('stl_pct', 'STL%', 'steals'), ('blk_pct', 'BLK%', 'shot-blocking')):
            v = adv.get(key, 0)
            if v > 0:
                r, n = pool_rank(c.adv_players, key, v)
                if n and r <= 0.25 * n: s.append(f'{lab} {v:.1f}% (#{r}/{n}) — top {max(1, round(100 * r / n))}% statewide in {word}.')
        for key, lab, word in (('shots100', 'SHOTS/100', 'shot volume'), ('stl100', 'STL/100', 'steals'), ('blk100', 'BLK/100', 'shot-blocking')):
            v = box.get(key) or 0
            if v > 0:
                r, n = pool_rank(c.adv_players, key, v)
                if n and r <= 0.25 * n: s.append(f'{lab} {v:.1f} (#{r}/{n}) — top {max(1, round(100 * r / n))}% statewide in {word} per 100 possessions.')
        tv = adv.get('tov_pct', 0)
        if tv > 0:
            r, n = pool_rank(c.adv_players, 'tov_pct', tv, False)
            if r >= 0.8 * n: s.append(f'TOV% {tv:.1f}% (#{r}/{n}) — among the highest turnover rates statewide.')
            elif r <= 0.2 * n: s.append(f'TOV% {tv:.1f}% (#{r}/{n}) — among the lowest turnover rates statewide.')
    s += syn_sentences(c, p)
    pf40 = 40 * tot.get('PF', 0) / max(tot.get('MIN', 1), 1) if c.min_ok else 0
    if pf40 >= 5.0: s.append(f'Fouls: {avg.get("PF", 0):.1f} PF a game in {mpg:.1f} MPG ({pf40:.1f} per 40 minutes).')
    if gp < 0.8 * c.n_games: s.append(f'Played in {gp} of {c.n_games} team games.')
    return ' '.join(s)

def player_card(c, p):
    avg, tot, adv = A(p), p['totals'], ADV(c, p)
    name, gp, mpg = p['name'], avg.get('games', 0), avg.get('MIN', 0)
    pos_code = c.pos.get(name, '—'); pos_name = POS_FULL.get(pos_code, '')
    usage = adv.get('usage_pct', 0); role_lbl, role_hex = kenpom_player_role(usage, mpg)
    role_s = f'<font color="{role_hex}"><b>{role_lbl}</b></font>  ' if c.min_ok else ''
    poss_s = f'  <font color="#ffd700">{usage:.1f}% poss</font>' if c.min_ok else ''
    io, idr = adv.get('ind_ortg', 0), adv.get('ind_drtg', 0); inet = io - idr
    net_c = '#34a853' if inet > 5 else '#e74c3c' if inet < -5 else '#aab8d0'
    ht = c.height.get(name, 0); ht_s = f' · {_fmt_height(ht)}' if ht else ''
    pos_tail = ' · ' + pos_name if pos_name else ''
    num = c.num.get(name); name_h = f'#{num} {name}' if num else name
    hdr = Table([[Paragraph(f'<b>{name_h}</b>', S(11, True, WHITE)),
                  Paragraph(f'{role_s}<font color="#aab8d0">{pos_code}{ht_s}'
                            f'{pos_tail}</font>{poss_s}', S(8, False, GOLD, TA_CENTER)),
                  Paragraph(f'<font color="#aab8d0">{gp} GP · ' + (f'{mpg:.1f} MPG' if c.min_ok else 'minutes not kept') + '</font>' + (f'<br/><font color="#aab8d0">ORtg</font> <b>{io:.1f}</b>  '
                            f'<font color="#aab8d0">DRtg</font> <b>{idr:.1f}</b>  <font color="{net_c}"><b>Net {inet:+.1f}</b></font>' if io > 0 else ''),
                            S(8, False, WHITE, TA_RIGHT))]], colWidths=[2.8 * inch, 2.5 * inch, 2.2 * inch])
    hdr.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), DARK), ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    items = [hdr] + syn_rows(c, p)
    txt = narrative(c, p, 0)
    top100 = get_top100(c, avg, adv, tot, mpg)
    if top100: txt += ' Ranks top 100 statewide in ' + ', '.join(f'<b>{l} {v:.1f}{u}</b> (#{r}/{n})' for l, v, u, r, n in top100) + '.'
    items.append(P(txt, S(8.5, space_after=3), 'player:' + name))
    if mpg >= 12 and io > 0:
        twoa = tot.get('FGA', 0) - tot.get('3PA', 0); twop = round((tot.get('FGM', 0) - tot.get('3PM', 0)) / twoa * 100, 1) if twoa > 0 else 0.0
        ar = lambda k, v, hb=True: (lambda r, n: f'#{r}/{n}' if v > 0 and n else '—')(*pool_rank(c.adv_players, k, v, hb))
        items.append(Paragraph(
            f'Ind ORtg {io:.1f} ({ar("ind_ortg", io)}) · Ind DRtg {idr:.1f} ({ar("ind_drtg", idr, False)}) · %Poss {usage:.1f}% · '
            f'AST Rate {adv.get("ast_rate", 0):.1f}% ({ar("ast_rate", adv.get("ast_rate", 0))}) · TOV% {adv.get("tov_pct", 0):.1f}% ({ar("tov_pct", adv.get("tov_pct", 0), False)}) · '
            f'OREB% {adv.get("oreb_pct", 0):.1f}% ({ar("oreb_pct", adv.get("oreb_pct", 0))}) · DREB% {adv.get("dreb_pct", 0):.1f}% ({ar("dreb_pct", adv.get("dreb_pct", 0))}) · '
            f'STL% {adv.get("stl_pct", 0):.1f}% ({ar("stl_pct", adv.get("stl_pct", 0))}) · BLK% {adv.get("blk_pct", 0):.1f}% ({ar("blk_pct", adv.get("blk_pct", 0))}) · '
            f'FT Rate {adv.get("ft_rate", 0):.2f} · 2P% {twop:.1f}% ({ar("twop", twop)}) · 3P% {avg.get("3P%", 0):.1f}% ({ar("tpp", avg.get("3P%", 0))}) · '
            f'FT% {avg.get("FT%", 0):.1f}% ({ar("ftp", avg.get("FT%", 0))})', S(7.5, italic=True, color=colors.HexColor('#aab8d0'), space_after=3)))
    sv = lambda v, l: Paragraph(f'<b>{v}</b><br/><font size="7">{l}</font>', S(13, False, DARK, TA_CENTER))
    strip = Table([[sv(f'{avg.get("PTS", 0):.1f}', 'PPG'), sv(f'{avg.get("REB", 0):.1f}', 'RPG'), sv(f'{avg.get("AST", 0):.1f}', 'APG'),
                    sv(f'{avg.get("STL", 0):.1f}', 'SPG'), sv(f'{avg.get("BLK", 0):.1f}', 'BPG'), sv(f'{avg.get("TO", 0):.1f}', 'TO/G'),
                    sv(f'{adv.get("efg_pct", 0):.1f}%', 'eFG%'), sv(f'{avg.get("3P%", 0):.1f}%', f'3P% ({avg.get("3PA", 0):.1f}/G)'),
                    sv(f'{avg.get("FT%", 0):.1f}%', 'FT%'), sv(f'{adv.get("ts_pct", 0):.1f}%', 'TS%')]], colWidths=[0.75 * inch] * 10)
    strip.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), LGRAY), ('INNERGRID', (0, 0), (-1, -1), 0.3, MGRAY), ('BOX', (0, 0), (-1, -1), 0.5, MGRAY),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    items.append(strip)
    parts = []
    for key, val, lab, hb in (('ppg', avg.get('PTS', 0), 'PPG', True), ('apg', avg.get('AST', 0), 'APG', True), ('ts_pct', adv.get('ts_pct', 0), 'TS%', True),
                              ('tpp', avg.get('3P%', 0), '3P%', True), ('tov_pct', adv.get('tov_pct', 0), 'TOV%', False)):
        if val > 0: r, n = pool_rank(c.all_players, key, val, hb); parts.append(f'{lab} #{r}/{n}')
    items.append(Paragraph(f'State context ({len(c.all_players)} players, Min% >10%): ' + ' · '.join(parts), S(7.5, italic=True, color=MID, space_after=4)))
    return KeepTogether(items + [Spacer(1, 10)])

def page_players(c):
    e = section(f'Player Profiles — {c.team} Rotation',
                (f'All rotation players ({ROT_MPG:.0f}+ MPG in {round(100 * ROT_GP_SHARE)}%+ of games), sorted by share of the team\u2019s possessions used (%Poss \u00d7 minutes).' if c.min_ok else
                 f'All rotation players (4+ PPG or 3+ RPG in {round(100 * ROT_GP_SHARE)}%+ of games; {c.team}’s box scores don’t keep reliable minutes), '
                 f'sorted by points.'))
    e += [player_card(c, p) for p in c.rotation]
    if c.gone:
        e.append(P('<b>Not in the last ' + str(GONE_GAMES) + ' games</b> (not profiled): ' + '; '.join(
            f'{p["name"]} — {A(p)["PTS"]:.1f} PPG{mins(c, p)} over {A(p)["games"]} games, last played {c.last_date[p["name"]]}' for p in c.gone) + '.',
            S(8.5, color=MID, space_after=6)))
    e.append(PageBreak())
    return e

# ═══════════════════════════════════════════════════════════════════════════════════════
# SITUATIONS + QUADRANTS + LOSSES
# ═══════════════════════════════════════════════════════════════════════════════════════
def page_situations(c):
    e, T, G = [], c.team, c.games
    e += section('Season Performance & Situational Analysis', f'How {T} performs by game type, opponent quality, and quadrant.')
    home = [g for g in G if g['location'] == 'Home']; away = [g for g in G if g['location'] == 'Away']; neut = [g for g in G if g['location'] == 'Neutral']
    conf = [g for g in G if g.get('is_conference')]; nconf = [g for g in G if not g.get('is_conference')]
    good = [g for g in G if g['opp_net'] is not None and g['opp_net'] > 0]; close = [g for g in G if abs(g['margin']) <= 8]
    early, late = G[:c.half], G[c.half:]
    worst_conf = sorted([g for g in conf if g['result'] == 'L'], key=lambda g: g['net'])[:1]
    for sp in [('OVERALL', rec(G), avg_net(G), f'{c.rec_all} overall record'), ('HOME', rec(home), avg_net(home), 'Home record'),
               ('AWAY', rec(away), avg_net(away), 'Away record'), ('NEUTRAL', rec(neut), avg_net(neut), 'Neutral-site record'),
               ('CONFERENCE', rec(conf), avg_net(conf), f'{c.conf}' + (f'; worst loss {worst_conf[0]["opponent"]} {worst_conf[0]["date"]}' if worst_conf else '')),
               ('NON-CONFERENCE', rec(nconf), avg_net(nconf), 'Non-conference record'),
               ('vs. QUALITY OPPS (net > 0)', rec(good), avg_net(good), f'{len(good)} games vs. opponents with positive net rating'),
               (f'FIRST HALF (G1-{len(early)})', rec(early), avg_net(early), f'Games 1-{len(early)}') if len(G) >= ARC_MIN_GAMES else
               ('FIRST HALF', '0-0', 0, f'Shown from game {ARC_MIN_GAMES}'),
               (f'SECOND HALF (G{len(early) + 1}-{len(G)})', rec(late), avg_net(late), f'Games {len(early) + 1}-{len(G)}') if len(G) >= ARC_MIN_GAMES else
               ('SECOND HALF', '0-0', 0, f'Shown from game {ARC_MIN_GAMES}'),
               ('CLOSE GAMES (≤8 pts)', rec(close), avg_net(close), f'{len(close)} games decided by 8 or fewer points')]:
        e += [splits_box(*sp), Spacer(1, 3)]
    e.append(Spacer(1, 10))
    e.append(Paragraph('<b>Quadrant Records (NCAA-style, scaled for 100 CCCAA teams)</b>', S(9, True, BLUE, space_after=3)))
    e.append(Paragraph('Q1A = elite (top ~4%). Q1 = top-tier (top ~9%). Q2 = strong (top ~21%). Q3 = adequate (top ~45%). Q4 = lower-tier. '
                       'Location-adjusted thresholds.', S(8, False, MID, space_after=4)))
    qr, qg = c.quad_rec, c.quad_games
    q1 = qg['Q1A'] + qg['Q1']; q12 = q1 + qg['Q2']
    q1w, q1l = qr['Q1A'][0] + qr['Q1'][0], qr['Q1A'][1] + qr['Q1'][1]; q12w, q12l = q1w + qr['Q2'][0], q1l + qr['Q2'][1]
    for ql, wr, lg, ex in [('Q1A (Elite — Top 4%)', f'{qr["Q1A"][0]}-{qr["Q1A"][1]}', qg['Q1A'], f'{len(qg["Q1A"])} game(s) vs elite opponents'),
                           ('Q1 (Top-Tier, incl. Q1A)', f'{q1w}-{q1l}', q1, f'{len(q1)} game(s) vs top-tier opponents'),
                           ('Q2 (Strong — Top 21%)', f'{qr["Q2"][0]}-{qr["Q2"][1]}', qg['Q2'], f'{len(qg["Q2"])} game(s) vs strong opponents'),
                           ('Q1+Q2 Combined', f'{q12w}-{q12l}', q12, f'{len(q12)} game(s) vs Q1 or Q2 opponents'),
                           ('Q3 (Adequate — Top 45%)', f'{qr["Q3"][0]}-{qr["Q3"][1]}', qg['Q3'], f'{len(qg["Q3"])} game(s) vs adequate opponents'),
                           ('Q4 (Lower-Tier)', f'{qr["Q4"][0]}-{qr["Q4"][1]}', qg['Q4'], f'{len(qg["Q4"])} game(s) vs lower-tier opponents')]:
        e += [splits_box(ql, wr, avg_net(lg), ex), Spacer(1, 3)]
    bad = sorted([g for g in qg['Q3'] + qg['Q4'] if g['result'] == 'L'], key=lambda g: g['opp_rank'])
    e.append(Spacer(1, 8))
    wl = lambda w, l: f'{w}-{l}' if w + l else '\u2014'   # no games in that quad yet
    e.append(P(f'<b>Quad Summary:</b> ' + (f'{T} {"is" if c.ongoing else "went"} <b>{wl(q1w, q1l)} in Q1 games</b> and <b>{wl(q12w, q12l)} in Q1+Q2 combined</b>{" so far" if c.ongoing else ""}. '
               if q12w + q12l else f'{T} has not played a Q1 or Q2 game{" yet" if c.ongoing else ""}. ') +
               f'Q3 record: {wl(*qr["Q3"])}. Q4 record: {wl(*qr["Q4"])}.'
               + (' Losses to Q3/Q4 opponents: ' + ', '.join(f'{g["opponent"]} (net rank #{g["opp_rank"]}, {g["date"]})' for g in bad) + '.' if bad else
                  ' No losses to Q3 or Q4 opponents.'), S(9, space_after=8)))
    losses = sorted([g for g in G if g['result'] == 'L'], key=lambda g: g['net'])
    head = section(f"{T}'s {len(losses)} Losses") + [Paragraph(f"{T}'s losses, sorted by {T} net rating:", S(9, False, MID, space_after=4))]
    lr = [['DATE', 'OPPONENT', 'SCORE', 'LOCATION', f'{c.abbr} NET', 'OPP NET RANK']] + [
        [g['date'], g['opponent'], f"{g['team_score']}-{g['opponent_score']}", g['location'], f"{g['net']:+.1f}",
         f"#{c.net_ranks.get(g.get('canonical_opponent', g['opponent']), '?')}"] for g in losses]
    lt = Table(lr, colWidths=[0.9 * inch, 2.0 * inch, 0.8 * inch, 0.8 * inch, 1.0 * inch, 2.0 * inch], repeatRows=1)
    lt.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), TH_BG), ('TEXTCOLOR', (0, 0), (-1, 0), WHITE), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, ALT]), ('INNERGRID', (0, 0), (-1, -1), 0.3, MGRAY), ('BOX', (0, 0), (-1, -1), 0.5, TH_BG),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4), ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4)]))
    if not losses:   # no table for none
        e += [KeepTogether(head + [Paragraph('No losses so far.' if c.ongoing else 'No losses.', S(9, space_after=8))]), PageBreak()]
    else:
        e += [KeepTogether(head + [lt]), PageBreak()]
    return e

# ═══════════════════════════════════════════════════════════════════════════════════════
# HEAD-TO-HEAD + STRENGTHS / VULNERABILITIES + KEYS TO VICTORY
# ═══════════════════════════════════════════════════════════════════════════════════════
TEAM_FACTS = [  # key, label, unit, what it means (strength / vulnerability wording comes from the rank)
    ('ortg', 'Offensive rating', '', 'points per 100 possessions'), ('drtg', 'Defensive rating', '', 'points allowed per 100 possessions'),
    ('efg_pct', 'Shooting (eFG%)', '%', 'effective FG%'), ('ts_pct', 'True shooting', '%', 'TS%'),
    ('opp_efg_pct', 'Shooting suppression (Opp eFG%)', '%', 'opponent eFG%'), ('tov_pct', 'Ball security (TOV%)', '%', 'turnovers per possession'),
    ('opp_tov_pct', 'Turnover generation (Opp TOV%)', '%', 'opponent turnovers per possession'), ('oreb_pct', 'Offensive rebounding', '%', 'OREB%'),
    ('dreb_pct', 'Defensive rebounding', '%', 'DREB%'), ('ft_rate', 'Getting to the line (FT Rate)', '', 'FTA per FGA'),
    ('opp_ft_rate', 'Fouling (Opp FT Rate)', '', 'opponent FTA per FGA'), ('fc_per_40', 'Foul discipline (PF/G)', '', 'team fouls a game')]

def page_scouting_guide(c):
    e, T, me, mp = [], c.team, c.me, c.mp
    e += section(f'Head-to-Head: Moorpark vs. {T} {c.season}', f'Every {c.season} meeting, from Moorpark’s perspective.')
    if c.h2h:
        for g in c.h2h:
            loc = {'Away': f'Away (at {T})', 'Home': 'Home (Moorpark)'}.get(g['location'], 'Neutral')
            e.append(P(f'<b>{g["date"]} — {g["result"]} {g["team_score"]}–{g["opponent_score"]}  |  {loc}</b>  |  Moorpark ORTg: {g["ortg"]:.1f}  '
                       f'DRTg: {g["drtg"]:.1f}  Net: {g["ortg"] - g["drtg"]:+.1f}', S(9, space_after=3), 'data'))
        tot_m = sum(g['team_score'] - g['opponent_score'] for g in c.h2h)
        e.append(P(f'<b>Analysis:</b> In {len(c.h2h)} meeting{"s" if len(c.h2h) != 1 else ""}, Moorpark’s ORTg against {T} averaged '
                   f'{sum(g["ortg"] for g in c.h2h) / len(c.h2h):.1f} against {T}’s season DRTg of {c.ta["drtg"]:.1f}, and {T} scored '
                   f'{sum(g["drtg"] for g in c.h2h) / len(c.h2h):.1f} per 100 against Moorpark against their season ORTg of {c.ta["ortg"]:.1f}. '
                   f'Combined margin: {tot_m:+d} for Moorpark.', S(9.5, space_after=10)))
    else:
        e.append(P(f'Moorpark and {T} have not met in {c.season}.', S(9.5, space_after=10)))

    e += section('Scouting Guide — Strengths, Vulnerabilities & Keys to Victory')
    ranked = [(R(c, k), k, lab, u, what) for k, lab, u, what in TEAM_FACTS]
    fact = lambda r, k, lab, u, what: (f'<b>{lab}: {me[k]:.1f}{u} (#{r}/{c.n})</b>', f'{tw(r, c.n).capitalize()} statewide; state average {AVG(c, k)}{u} ({what}).')
    best, worst = sorted(ranked), sorted(ranked, reverse=True)
    # Their four best and four worst team numbers (best = the top of the state, worst = the bottom), never the same one twice.
    strengths = [fact(*x) for x in best[:4] if x[0] <= 50]
    vulns = [fact(*x) for x in worst[:4] if x[0] > 50]
    scorers = rot_by(c, lambda p: A(p).get('PTS', 0))[:2]
    for p in scorers:
        a = A(p); strengths.append((f'<b>{p["name"]}: {a["PTS"]:.1f} PPG, {a.get("REB", 0):.1f} RPG, {a.get("FG%", 0):.1f} FG%</b>',
                                    f'{mins(c, p, "")}{", " if c.min_ok else ""}{a.get("games", 0)} GP; {a.get("3P%", 0):.1f}% on {a.get("3PA", 0):.1f} 3PA a game, {a.get("FT%", 0):.1f}% FT on {a.get("FTA", 0):.1f} FTA.'))
    ft_poor = [p for p in c.rotation if A(p).get('FTA', 0) >= 1.0 and A(p).get('FT%', 100) < 65]
    for p in sorted(ft_poor, key=lambda p: A(p)['FT%'])[:1]:
        vulns.append((f'<b>{p["name"]} FT%: {A(p)["FT%"]:.1f}% on {A(p)["FTA"]:.1f} FTA a game</b>', 'Lowest FT% among rotation players with 1+ FTA a game.'))
    to_hi = rot_by(c, lambda p: A(p).get('TO', 0))[:1]
    for p in to_hi:
        if A(p).get('TO', 0) >= 2.0:
            vulns.append((f'<b>{p["name"]} turnovers: {A(p)["TO"]:.1f} a game (team high)</b>', f'{A(p).get("AST", 0):.1f} assists a game{mins(c, p, "; ")}.'))
    pf_hi = sorted(c.rotation, key=lambda p: -40 * p['totals'].get('PF', 0) / max(p['totals'].get('MIN', 1), 1))[:1]
    for p in pf_hi:
        pf40 = 40 * p['totals'].get('PF', 0) / max(p['totals'].get('MIN', 1), 1)
        if c.min_ok and pf40 >= 4.5: vulns.append((f'<b>{p["name"]} fouls: {A(p).get("PF", 0):.1f} PF a game in {A(p).get("MIN", 0):.1f} MPG</b>',
                                      f'{pf40:.1f} fouls per 40 minutes, the highest rate in the rotation.'))
    n = max(len(strengths), len(vulns))
    strengths += [('', '')] * (n - len(strengths)); vulns += [('', '')] * (n - len(vulns))
    for sk, sv in strengths: TEXT.append(('prose', re.sub(r'<[^>]+>', '', sk + ' ' + sv)))
    for vk, vv in vulns: TEXT.append(('prose', re.sub(r'<[^>]+>', '', vk + ' ' + vv)))
    sv_t = Table([[[Paragraph(sk, S(8.5, True, GREEN_TXT)), Paragraph(sv, S(8))], [Paragraph(vk, S(8.5, True, RED_TXT)), Paragraph(vv, S(8))]]
                  for (sk, sv), (vk, vv) in zip(strengths, vulns)], colWidths=[3.6 * inch, 3.6 * inch])
    sv_t.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0fff4')), ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#fff5f5')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, MGRAY), ('BOX', (0, 0), (-1, -1), 0.5, BLUE), ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6), ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    e += [sv_t, Spacer(1, 14)]

    e += section('Keys to Victory — What Moorpark Must Do')
    keys = []
    for i, p in enumerate(scorers):
        a = A(p)
        keys.append((f'Contain {p["name"]} — {a["PTS"]:.1f} PPG.', f'{"Leading" if i == 0 else "Second-leading"} scorer: {a["PTS"]:.1f} PPG on {a.get("FG%", 0):.1f} FG% '
                     f'{mins(c, p, "in ")}{"; " if c.min_ok else ""}{a.get("3P%", 0):.1f}% on {a.get("3PA", 0):.1f} 3PA a game; {a.get("FT%", 0):.1f}% FT on {a.get("FTA", 0):.1f} FTA a game.'))
    # The four-factor table's eight rows (matchup_rows): their two biggest edges become keys (what Moorpark must fix) and
    # Moorpark's biggest edge the next (what to keep).
    word = {('them', 'eFG%'): 'Contest their shooting', ('them', 'TOV%'): 'Force turnovers', ('them', 'OREB%'): 'End their possessions with the rebound',
            ('them', 'FT Rate'): 'Defend without fouling', ('us', 'eFG%'): 'Shot quality', ('us', 'TOV%'): 'Protect the ball',
            ('us', 'OREB%'): 'Crash the offensive glass', ('us', 'FT Rate'): 'Get to the line'}
    keep = {('them', 'eFG%'): 'Keep their shooting down', ('them', 'TOV%'): 'Keep forcing turnovers', ('them', 'OREB%'): 'Keep winning the defensive glass',
            ('them', 'FT Rate'): 'Keep them off the line', ('us', 'eFG%'): 'Our shooting edge', ('us', 'TOV%'): 'Our ball-security edge',
            ('us', 'OREB%'): 'Our offensive-glass edge', ('us', 'FT Rate'): 'Our free-throw edge'}
    M = matchup_rows(c)
    for r in sorted(M, key=lambda r: -r['their'])[:2]:
        if r['their'] > 0: keys.append((f'{word[(r["side"], r["f"])]} ({r["f"]}).', f'{r["text"]} \u2014 {c.abbr} +{r["their"]:.1f}.'))
    for r in sorted(M, key=lambda r: r['their'])[:1]:
        if r['their'] < 0: keys.append((f'{keep[(r["side"], r["f"])]} ({r["f"]}).', f'{r["text"]} \u2014 Moorpark +{-r["their"]:.1f}.'))
    ft_lo = sorted(ft_poor, key=lambda p: A(p)['FT%'])[:1]
    if ft_lo:
        p = ft_lo[0]; keys.append((f'Late-game free throws: {p["name"]}.', f'{A(p)["FT%"]:.1f}% FT on {A(p)["FTA"]:.1f} FTA a game, the lowest among {T}’s rotation players with 1+ FTA a game.'))
    seen, uniq = set(), []
    for h, b in keys:
        if h not in seen: seen.add(h); uniq.append((h, b))
    blocks = []
    for i, (h, b) in enumerate(uniq[:6], 1):
        TEXT.append(('keys', h + ' ' + b))
        tbl = Table([[Paragraph(f'<b>{i}. {h}</b>', S(9, True, BLUE)), Paragraph(b, S(8.5))]], colWidths=[2.2 * inch, 5.3 * inch])
        tbl.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, 0), ALT), ('BOX', (0, 0), (-1, -1), 0.5, BLUE), ('INNERGRID', (0, 0), (-1, -1), 0.3, MGRAY),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6), ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        blocks.append([tbl, Spacer(1, 4)])
    c.n_keys = len(uniq[:6])
    for b in blocks[:-1]: e += b
    e.append(KeepTogether((blocks[-1] if blocks else []) + [Spacer(1, 6), P(f'<b>Summary:</b> {T} {"is " + c.rec_all + " so far" if c.ongoing else "finished " + c.rec_all} (Net Rating {sg(c.ta["net_rtg"])}, #{R(c, "net_rtg")}/{c.n} statewide). ORTg {c.ta["ortg"]:.1f} '
               f'(#{R(c, "ortg")}/{c.n}); DRTg {c.ta["drtg"]:.1f} (#{R(c, "drtg")}/{c.n}). Leading scorers: '
               + ', '.join(f'{p["name"]} ({A(p)["PTS"]:.1f} PPG)' for p in scorers) + f'. Moorpark’s offensive benchmark: an ORTg above {T}’s '
               f'season DRTg of {c.ta["drtg"]:.1f}.', S(10, space_after=0))]))
    return e

# ═══════════════════════════════════════════════════════════════════════════════════════
# THE STANDARD: a report that falls short is not written
# ═══════════════════════════════════════════════════════════════════════════════════════
REQUIRED = ['Who Is {T}?', 'Advanced Offense / Defense tables', 'Advanced Analytics: Statewide Context', 'Four Factors Comparison',
            'Player Profiles — {T} Rotation', 'Season Performance & Situational Analysis', "{T}'s {L} Losses",
            'Head-to-Head: Moorpark vs. {T} {S}', 'Scouting Guide — Strengths, Vulnerabilities & Keys to Victory', 'Keys to Victory — What Moorpark Must Do']

def check_report(c):
    probs = []
    L = sum(g['result'] == 'L' for g in c.games)
    for s in REQUIRED + (['Synergy Sports — Play Type Profile'] if c.syn_team else []):
        want = s.format(T=c.team, L=L, S=c.season)
        if want not in SECTIONS: probs.append(f'missing section: {want}')
    # How much data there is never stops a report (they're wanted from the first game): sections without enough show
    # "—"; the counts are printed as notes only.
    thin = []
    if len(c.rotation) < 5: thin.append(f'{len(c.rotation)} rotation players')
    for p in c.rotation:
        txt = next((t for k, t in TEXT if k == 'player:' + p['name']), '')
        if len(re.findall(r'[.!?](?:\s|$)', txt)) < 3: thin.append(f'short profile: {p["name"]}')
    if c.syn_team:
        miss = [p['name'] for p in c.rotation if not SYNP(c, p)]
        if miss: print(f'  note: {c.team} has a Synergy team export but no Synergy player data for: ' + ', '.join(miss))
    if getattr(c, 'n_keys', 0) < 4: thin.append(f'{getattr(c, "n_keys", 0)} keys to victory')
    if len(c.games) < 10: thin.append(f'{len(c.games)} games')
    if thin: print(f'  note: {c.team}: early-season report (' + ', '.join(thin) + ')')
    # Descriptive data only outside the Keys: lint_scouting_prose.py's patterns.
    sys.path.insert(0, HERE)
    import lint_scouting_prose as lint
    for kind, txt in TEXT:
        if kind in ('keys', 'note'): continue   # Keys may direct; the export's written notes are shown as submitted
        low = txt.lower()
        for label, pats in (('directive', lint.DIRECTIVE), ('film', lint.FILM), ('hedge', lint.HEDGE)):
            for pt in pats:
                m = re.search(pt, low)
                if m and not any(w in low[max(0, m.start() - 20):m.end() + 20] for w in lint.SAFE):
                    probs.append(f'{label} language "{m.group(0)}": {txt[:90]}')
    return probs

def next_free(path):
    if not os.path.exists(path): return path
    base, ext = os.path.splitext(path); i = 2
    while os.path.exists(f'{base}_v{i}{ext}'): i += 1
    return f'{base}_v{i}{ext}'

# The tracker's copies (--latest): one current report per team at ../poss/reports/<slug>.pdf, replaced each time, and
# ../poss/reports/index.json {team: {file, edition, generatedAt, season}}; the iPad downloads them and Scout opens them.
# The dated, never-overwritten archive in scouting_reports/ is for reports built by hand.
LATEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'poss', 'reports')

def tracker_teams(season):
    """The teams the tracker has files for (Moorpark's schedule + tracker_teams.txt): ../poss/ratings.json teamFiles."""
    try:
        R = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'poss', 'ratings.json')))
    except (OSError, ValueError):
        return []
    return [t for t in (R.get('teamFiles') or {}) if t != 'Moorpark'] if R.get('season') == season else []

def build_latest(teams, season):
    os.makedirs(LATEST_DIR, exist_ok=True)
    ip = os.path.join(LATEST_DIR, 'index.json')
    try: index = json.load(open(ip))
    except (OSError, ValueError): index = {}
    # Only this season's reports stay (the tracker shows one season): others leave the index and the folder.
    index = {t: e for t, e in index.items() if e.get('season') == season}
    done = []
    for t in teams:
        f = f'{slug(t)}.pdf'; p = os.path.join(LATEST_DIR, f)
        tmp = p + '.new'
        if build(t, season, tmp, replace=True):
            os.replace(tmp, p); ed = 'synergy' if LAST_ED[0] == 'synergy' else 'pre_synergy'
            index[t] = {'file': f, 'edition': ed, 'generatedAt': datetime.now().astimezone().isoformat(timespec='seconds'), 'season': season}
            done.append(t)
        elif os.path.exists(tmp): os.remove(tmp)
    keep = {e['file'] for e in index.values()}
    for f in os.listdir(LATEST_DIR):
        if f.endswith('.pdf') and f not in keep: os.remove(os.path.join(LATEST_DIR, f))
    json.dump(index, open(ip, 'w'), indent=1, sort_keys=True)
    print(f'{len(done)} of {len(teams)} tracker reports updated -> {os.path.normpath(LATEST_DIR)}')
    return done

LAST_ED = [None]

def build(team, season, out=None, out_dir=None, replace=False):
    TEXT.clear(); SECTIONS.clear()
    if team == 'Moorpark': sys.exit('Moorpark is the home team: scout an opponent.')
    c = load(team, season)
    story = page_cover(c) + page_analytics(c) + page_synergy(c) + page_players(c) + page_situations(c) + page_scouting_guide(c)
    probs = check_report(c)
    if probs:
        print(f'{team}: not written — below the report standard:\n  ' + '\n  '.join(probs)); return None
    od = out_dir or OUT_DIR; os.makedirs(od, exist_ok=True)
    # Two editions: pre-Synergy (box scores and leaderboard only) until the team's Synergy export is in internal_data, then
    # Synergy. Different file names, so the Synergy edition never replaces (or is mistaken for) the earlier one.
    ed = 'synergy' if c.syn_team else 'pre_synergy'
    LAST_ED[0] = ed
    path = out if (out and replace) else next_free(out or os.path.join(od, f'{slug(team)}_scouting_report_{season.replace("-", "_")}_{ed}.pdf'))
    today = date.today().strftime('%B ') + str(date.today().day) + date.today().strftime(', %Y')
    def on_page(canvas, doc):
        canvas.saveState(); canvas.setFillColor(c.OPP); canvas.rect(0.5 * inch, 10.32 * inch, 7.5 * inch, 0.28 * inch, fill=1, stroke=0)
        canvas.setFillColor(c.OPP_TXT); canvas.setFont('Helvetica-Bold', 7.5)
        canvas.drawString(0.62 * inch, 10.39 * inch, f'MOORPARK RAIDERS  |  OPPONENT SCOUTING REPORT  |  {team.upper()}  |  ' + season.replace('-', '–')
                          + ('  |  SYNERGY EDITION' if c.syn_team else '  |  PRE-SYNERGY EDITION'))
        canvas.setFont('Helvetica', 7.5); canvas.drawRightString(7.9 * inch, 10.39 * inch, f'Page {doc.page}')
        canvas.setFillColor(MID); canvas.setFont('Helvetica', 6.5)
        canvas.drawCentredString(4.25 * inch, 0.35 * inch, f'Internal Use Only  |  Moorpark Raiders Analytics  |  {today}')
        canvas.restoreState()
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch, topMargin=0.72 * inch, bottomMargin=0.55 * inch,
                            title=f'{team} Scouting Report {season}', author='Moorpark Raiders Analytics')
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f'Saved: {path} ({round(os.path.getsize(path) / 1024)} KB, {len(c.rotation)} rotation players, {ed.replace("_", "-")} edition)')
    return path

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='The standard opponent scouting report (Ventura layout) for any team.')
    ap.add_argument('team', nargs='?'); ap.add_argument('--team', dest='team_opt'); ap.add_argument('--season', default='2025-26')
    ap.add_argument('--out'); ap.add_argument('--out-dir'); ap.add_argument('--list', action='store_true')
    ap.add_argument('--all', action='store_true', help='every team in the season (Moorpark excluded)')
    ap.add_argument('--latest', action='store_true', help="the tracker's copies: every team it has files for (schedule + tracker_teams.txt), "
                    'or only those in --only, written to ../poss/reports/ (replaced each time) with index.json')
    ap.add_argument('--only', nargs='+', help='with --latest: just these teams (scrape.py passes the teams that played)')
    a = ap.parse_args()
    if a.list: list_teams(a.season); sys.exit(0)
    if a.latest:
        if '--season' not in sys.argv:   # the tracker's copies are always its season
            from ccc_config import TRACKER_SEASON; a.season = TRACKER_SEASON
        T = tracker_teams(a.season)
        if a.only: T = [t for t in T if t in set(a.only)]
        build_latest(T, a.season); sys.exit(0)
    if a.all:
        root = stats_root(a.season)
        teams = sorted(t for cf in os.listdir(root) if os.path.isdir(os.path.join(root, cf)) for t in os.listdir(os.path.join(root, cf))
                       if t != 'Moorpark' and os.path.exists(os.path.join(root, cf, t, 'advanced_analytics.json')))
        done = [t for t in teams if build(t, a.season, None, a.out_dir)]
        print(f'{len(done)} of {len(teams)} reports written'); sys.exit(0 if len(done) == len(teams) else 1)
    t = a.team_opt or a.team
    if not t: ap.error('name a team (or --list)')
    sys.exit(0 if build(t, a.season, a.out) else 1)
