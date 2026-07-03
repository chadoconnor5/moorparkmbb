"""
CCCAA Opponent Scouting Report — team-agnostic, condensed.

Builds an essential scouting packet for ANY CCCAA team from league-wide data
only (advanced_analytics, team_summary, player_stats, game_log, schedule box
scores). No Synergy / hand-written content — that lives only in the deep
Moorpark report (generate_moorpark_scouting_report.py).

    /usr/local/bin/python3 generate_scouting_report.py "Ventura"
    /usr/local/bin/python3 generate_scouting_report.py              # defaults to Ventura
    /usr/local/bin/python3 generate_scouting_report.py --list

Output: <Team>_scouting_report_2025_26.pdf
Sections: 1) Identity + Statistical Identity  2) Four Factors & Efficiency
          3) Keys to Victory  4) Personnel (PPG > 5.9 or recent starter)
"""

import sys, json, os, csv, re
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, CondPageBreak
)

# ─── Palette ─────────────────────────────────────────────────────────────────
BLUE      = colors.HexColor('#003087')
GOLD      = colors.HexColor('#C4922A')
DARK      = colors.HexColor('#1a1a2e')
MID       = colors.HexColor('#555577')
LGRAY     = colors.HexColor('#f2f3f7')
MGRAY     = colors.HexColor('#dde0ea')
GREEN_BG  = colors.HexColor('#d4edda')
RED_BG    = colors.HexColor('#f8d7da')
GREEN_TXT = colors.HexColor('#1a5c30')
RED_TXT   = colors.HexColor('#7b1b1b')
TH_BG     = colors.HexColor('#1a3a6e')
ALT       = colors.HexColor('#e8ecf5')
WHITE     = colors.white
BLACK     = colors.black

BASE  = '/Users/chadoconnor/Neural Network'
CODEX = os.path.dirname(os.path.abspath(__file__))

def jload(p): return json.load(open(p))

# ─── Resolve the requested team ───────────────────────────────────────────────
def find_team_dir(team):
    root = f'{BASE}/2025-26 Team Statistics'
    for conf in sorted(os.listdir(root)):
        d = f'{root}/{conf}/{team}'
        if os.path.isdir(d) and os.path.exists(f'{d}/advanced_analytics.json'):
            return conf, d
    return None, None

def list_teams():
    root = f'{BASE}/2025-26 Team Statistics'
    for conf in sorted(os.listdir(root)):
        cp = f'{root}/{conf}'
        if not os.path.isdir(cp): continue
        teams = sorted(t for t in os.listdir(cp)
                       if os.path.exists(f'{cp}/{t}/advanced_analytics.json'))
        if teams:
            print(f"\n{conf}:")
            for t in teams: print(f"  {t}")

# Arg parsing (positional team name, or --list)
_args = [a for a in sys.argv[1:] if a != '--team' and a != '--conference']
if '--list' in sys.argv:
    list_teams(); sys.exit(0)
TEAM = _args[0] if _args else 'Ventura'

CONF, TDIR = find_team_dir(TEAM)
if not TDIR:
    print(f"Team '{TEAM}' not found. Run with --list to see available teams.")
    sys.exit(1)

team_sum   = jload(f'{TDIR}/team_summary.json')
adv_json   = jload(f'{TDIR}/advanced_analytics.json')
plyr_stats = jload(f'{TDIR}/player_stats.json')
ta         = adv_json['team']
plyr_adv   = {p['name']: p for p in adv_json.get('players', [])}

try:
    conf_stats = jload(f'{TDIR}/conference_stats.json')
    CONF_LABEL = conf_stats.get('conference', CONF)
    _cr = conf_stats.get('record', {})
    CONF_REC = next((v for k, v in _cr.items() if k.startswith('Conference')), '—')
except Exception:
    CONF_LABEL, CONF_REC = CONF, '—'

_rec = team_sum.get('record', {})
OVR_REC = next((v for k, v in _rec.items() if k.startswith('Overall')), '—')

pos_map = {}
try:
    with open(f'{BASE}/internal_data/player_positions_2025_26.csv') as f:
        for row in csv.DictReader(f):
            if row['team'] == TEAM:
                pos_map[row['name']] = row['pos_class']
except Exception:
    pass
pos_full = {
    'PG':'Point Guard','s-PG':'Scoring PG','CG':'Combo Guard','WG':'Wing Guard',
    'WF':'Wing Forward','S-PF':'Stretch PF','PF/C':'PF / Center','C':'Center'
}

# Roster heights (scraped). Team name in the CSV is the full program name
# (e.g. "Ventura College Pirate"), so match on a startswith of the folder name.
height_map = {}
try:
    with open(f'{BASE}/internal_data/roster_heights_2025_26.csv') as f:
        for row in csv.DictReader(f):
            if (row.get('team', '') or '').lower().startswith(TEAM.lower()):
                height_map[row['player']] = (row.get('height', '') or '').strip()
except Exception:
    pass

# ─── Statewide team pool ──────────────────────────────────────────────────────
all_teams = []
for conf in os.listdir(f'{BASE}/2025-26 Team Statistics'):
    cp = f'{BASE}/2025-26 Team Statistics/{conf}'
    if not os.path.isdir(cp): continue
    for team in os.listdir(cp):
        ap = f'{cp}/{team}/advanced_analytics.json'
        sp = f'{cp}/{team}/team_summary.json'
        if not (os.path.exists(ap) and os.path.exists(sp)): continue
        try:
            a = jload(ap)['team']; s = jload(sp)
            _to   = s['averages'].get('TO', 0)
            _ostl = s['opponent_averages'].get('STL', 0)
            _poss = max(a.get('possessions', 0.01), 0.01)
            all_teams.append({
                'team': team,
                'net_rtg': a.get('net_rtg', 0), 'ortg': a.get('ortg', 0), 'drtg': a.get('drtg', 0),
                'efg_pct': a.get('efg_pct', 0), 'opp_efg_pct': a.get('opp_efg_pct', 0),
                'tov_pct': a.get('tov_pct', 0), 'opp_tov_pct': a.get('opp_tov_pct', 0),
                'oreb_pct': a.get('oreb_pct', 0), 'dreb_pct': a.get('dreb_pct', 0),
                'ft_rate': a.get('ft_rate', 0), 'opp_ft_rate': a.get('opp_ft_rate', 0),
                'ts_pct': a.get('ts_pct', 0), 'opp_ts_pct': a.get('opp_ts_pct', 0),
                'possessions': a.get('possessions', 0),
                'ppg': s['averages']['PTS'], 'oppg': s['opponent_averages']['PTS'],
                'nst_pct': round(max(_to - _ostl, 0) / _poss * 100, 1),
                'opp_nst_pct': round(max(s['opponent_averages'].get('TO', 0) - s['averages'].get('STL', 0), 0) / _poss * 100, 1),
                'tpa_rate': round(s['averages'].get('3PA', 0) / s['averages']['FGA'] * 100, 1) if s['averages'].get('FGA') else 0,
                'ast_rate': a.get('ast_rate', 0),
                'stl_pct': a.get('stl_pct', 0), 'blk_pct': a.get('blk_pct', 0),
                'ast_tov': round(s['averages']['AST'] / s['averages']['TO'], 2) if s['averages'].get('TO') else 0,
                'sos': a.get('sos', 0),
            })
        except Exception:
            pass
n = len(all_teams)
_team_row = next((t for t in all_teams if t['team'] == TEAM), None)

# Bench scoring % statewide (depth ranking)
BENCH = {}
try:
    from generate_leaderboard import load_all_bench_points
    _bp = load_all_bench_points("2025-26", base_dir=CODEX)
    for _t in all_teams:
        _bd = _bp.get(_t['team'])
        if _bd and _bd.get('total_pts'):
            _t['bench_pct'] = round(_bd['bench_pts'] / _bd['total_pts'] * 100, 1)
    BENCH = {t['team']: t.get('bench_pct') for t in all_teams if 'bench_pct' in t}
except Exception:
    BENCH = {}
_team_bench = BENCH.get(TEAM)

def state_rank(key, val, higher_better=True):
    vals = sorted([t[key] for t in all_teams if t.get(key, 0) != 0], reverse=higher_better)
    rank = next((i+1 for i, v in enumerate(vals)
                 if (higher_better and v <= val) or (not higher_better and v >= val)), len(vals))
    avg = sum(t.get(key, 0) for t in all_teams) / n if n else 0
    return rank, n, round(avg, 1), round(val - avg, 1)

# ─── Statewide player pool (Min% > 10%) ───────────────────────────────────────
all_players = []
for conf in os.listdir(f'{BASE}/2025-26 Team Statistics'):
    cp = f'{BASE}/2025-26 Team Statistics/{conf}'
    if not os.path.isdir(cp): continue
    for team in os.listdir(cp):
        pp = f'{cp}/{team}/player_stats.json'
        ap = f'{cp}/{team}/advanced_analytics.json'
        if not (os.path.exists(pp) and os.path.exists(ap)): continue
        try:
            ps = jload(pp); adv = jload(ap)
            am = {q['name']: q for q in adv.get('players', [])}
            for p in ps['players']:
                a2 = p['averages']; tt = p['totals']
                if a2.get('MIN', 0) <= 4.0 or a2.get('games', 0) < 10: continue
                ad = am.get(p['name'], {})
                _2a = (tt.get('FGA', 0) - tt.get('3PA', 0))
                _2m = (tt.get('FGM', 0) - tt.get('3PM', 0))
                all_players.append({
                    'ppg': a2.get('PTS', 0), 'rpg': a2.get('REB', 0), 'apg': a2.get('AST', 0),
                    'spg': a2.get('STL', 0), 'bpg': a2.get('BLK', 0), 'mpg': a2.get('MIN', 0),
                    'tpp': a2.get('3P%', 0), 'fgp': a2.get('FG%', 0), 'ftp': a2.get('FT%', 0),
                    'twop': round(_2m/_2a*100, 1) if _2a > 0 else 0,
                    'ts_pct': ad.get('ts_pct', 0), 'efg_pct': ad.get('efg_pct', 0),
                    'usage_pct': ad.get('usage_pct', 0), 'ast_rate': ad.get('ast_rate', 0),
                    'tov_pct': ad.get('tov_pct', 0), 'oreb_pct': ad.get('oreb_pct', 0),
                    'dreb_pct': ad.get('dreb_pct', 0), 'stl_pct': ad.get('stl_pct', 0),
                    'blk_pct': ad.get('blk_pct', 0), 'ft_rate': ad.get('ft_rate', 0),
                    'ind_ortg': ad.get('ind_ortg', 0), 'ind_drtg': ad.get('ind_drtg', 0),
                    'fc_per_40': ad.get('fc_per_40', 0), 'fd_per_40': ad.get('fd_per_40', 0),
                    'shot_pct': ad.get('shot_pct', 0), 'min_pct': a2.get('MIN', 0) / 40.0 * 100,
                })
        except Exception:
            pass

def plyr_rank(key, val, hb=True):
    vals = sorted([p[key] for p in all_players if p[key] > 0], reverse=hb)
    r = next((i+1 for i, v in enumerate(vals) if (hb and v <= val) or (not hb and v >= val)), len(vals))
    return r, len(vals)

# Advanced-metric ranks over the rotation pool (Min% ≥ 30%, i.e. MPG ≥ 12)
_adv_pool = [p for p in all_players if p['mpg'] >= 12.0]
def adv_rank(key, val, hb=True):
    vals = sorted([p[key] for p in _adv_pool if p[key] > 0], reverse=hb)
    r = next((i+1 for i, v in enumerate(vals) if (hb and v <= val) or (not hb and v >= val)), len(vals))
    return r, len(vals)

# ─── Player roles / box archetype ─────────────────────────────────────────────
_BIG_POS = {'S-PF', 'PF/C', 'C'}
_GUARD_POS = {'PG', 's-PG', 'CG'}

# ── Synergy archetype classifiers (ported from the Moorpark report) — COMPUTED ─
# from the real Synergy play-type mix + shot profile, never hand-typed. Gated:
# only players with a Synergy export get a label.
_BI_PATS = [('spotup', r'spot ?up|spots up'), ('pnr_bh', r'p&?r bh|pick.?and.?roll bh'),
            ('postup', r'post.?up'), ('iso', r'isolation|iso\b'), ('transition', r'transition'),
            ('offscreen', r'off.?screen'), ('handoff', r'hand.?off|dho'), ('cut', r'\bcut'),
            ('roll', r'roll man|p&?r man'), ('putback', r'put.?back')]

def _parse_playtypes(summary):
    s = (summary or '').lower(); out = {}
    for k, pat in _BI_PATS:
        m = re.search('(?:' + pat + r')[^0-9]{0,18}?(\d+)\s*%', s)
        if m and m.group(1):
            out[k] = int(m.group(1))
    return out

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
        if rim >= 45 or pt.get('cut', 0) + pt.get('roll', 0) + pt.get('putback', 0) >= 18:
            return 'Roll + Cut Big'
        return 'Versatile Big'
    creator = pt.get('pnr_bh', 0) + pt.get('iso', 0)
    # Rim-finishers go to the slasher/finisher branch first: a player taking 45%+
    # of his shots at the rim is not a ball handler even if his AST% nicks the gate.
    if rim >= 45:
        return 'Slasher' if (ftr >= 20 or pt.get('iso', 0) >= 6) else 'Athletic Finisher'
    if ast >= 22 and (creator >= 6 or usg >= 18):
        return 'Primary Ball Handler' if usg >= 22 else 'Secondary Ball Handler'
    if (usg >= 23 and (creator >= 14 or pullup >= 45)) or creator >= 22:
        return 'Primary Ball Handler' if ast >= 18 else 'Shot Creator'
    has_shots = bool(st)
    if (has_shots and js >= 50 and cs >= 50) or (not has_shots and pt.get('spotup', 0) >= 28):
        if move >= 10: return 'Movement Shooter'
        if pt.get('spotup', 0) >= 30: return 'Stationary Shooter'
        return 'Off-Ball Shooter'
    if rim >= 30 or ftr >= 28 or pt.get('iso', 0) >= 10:
        return 'Slasher' if (ftr >= 25 or pt.get('iso', 0) >= 8) else 'Athletic Finisher'
    if ast >= 15 and creator >= 8: return 'Secondary Ball Handler'
    if cs >= 48 and js >= 45: return 'Off-Ball Shooter'
    return 'Connector / Role'

# Synergy player exports for this team, keyed by name (gated: empty if none)
SYNERGY_PLAYERS = {}
_synp = f"{CODEX}/internal_data/synergy_players_{TEAM.lower().replace(' ', '_')}_2025_26.json"
if os.path.exists(_synp):
    try:
        SYNERGY_PLAYERS = {r['name']: r for r in jload(_synp)}
    except Exception:
        SYNERGY_PLAYERS = {}

# Players who have left the program — excluded from the personnel section even if
# their box stats still qualify. One name per line in the JSON list.
REMOVED_PLAYERS = set()
_rmp = f"{CODEX}/internal_data/removed_players_{TEAM.lower().replace(' ', '_')}_2025_26.json"
if os.path.exists(_rmp):
    try:
        REMOVED_PLAYERS = set(jload(_rmp))
    except Exception:
        REMOVED_PLAYERS = set()

def kenpom_player_role(usage_pct, mpg):
    min_pct = mpg / 40.0 * 100
    if min_pct < 10.0:    return 'Benchwarmer', '#777777'
    if usage_pct >= 28.0: return 'Go-to Guy', '#b8860b'
    if usage_pct >= 24.0: return 'Major Contributor', '#1a7a3a'
    if usage_pct >= 20.0: return 'Significant Contributor', '#cc7a00'
    if usage_pct >= 16.0: return 'Role Player', '#2a5db0'
    if usage_pct >= 12.0: return 'Limited Role Player', '#8a2be2'
    return 'Nearly Invisible', '#999999'

# NOTE: no box-derived "archetype" label here — those fabricate a Synergy-style
# tag the box score can't support. Box position lives in the player header; the
# narrative describes the shot diet from real numbers instead.

# ─── Starter detection from box scores (first 5 rows = starters) ──────────────
def _compute_starter_data(team, conf):
    sched_root = f'{BASE}/2025-26 Teams Schedules/{conf}/{team}'
    gs_count, game_dates = {}, []
    if not os.path.isdir(sched_root):
        return gs_count, {}, 0
    for game_folder in sorted(os.listdir(sched_root)):
        fp = os.path.join(sched_root, game_folder)
        if not os.path.isdir(fp): continue
        for fname in os.listdir(fp):
            if not fname.endswith('.json'): continue
            try:
                box = jload(os.path.join(fp, fname))
            except Exception:
                continue
            rows = box.get('teams', {}).get(team, [])
            if not rows: continue
            def clean(r):
                nm = r.get('name', '')
                return nm.split(' ', 1)[1] if nm and nm[0] == '#' else nm
            starters = {clean(r) for r in rows[:5]}
            entry = {}
            for r in rows:
                c = clean(r); st = c in starters
                entry[c] = st
                if st: gs_count[c] = gs_count.get(c, 0) + 1
            game_dates.append(entry)
    last5 = game_dates[-5:]
    last5_gs = {}
    for entry in last5:
        for nm, st in entry.items():
            if st: last5_gs[nm] = last5_gs.get(nm, 0) + 1
    return gs_count, last5_gs, len(game_dates)

_gs_count, _last5_gs, _total_games = _compute_starter_data(TEAM, CONF)

def is_starter(name):
    gs = _gs_count.get(name, 0); l5 = _last5_gs.get(name, 0)
    return (gs / _total_games >= 0.5 if _total_games > 0 else False) or l5 >= 3

def started_recently(name):
    return _last5_gs.get(name, 0) >= 3

# ─── Styles ───────────────────────────────────────────────────────────────────
SS = getSampleStyleSheet()
def S(size=10, bold=False, color=BLACK, align=TA_LEFT, italic=False, leading=None, space_after=2):
    fname = ('Helvetica-BoldOblique' if bold and italic else
             'Helvetica-Bold' if bold else
             'Helvetica-Oblique' if italic else 'Helvetica')
    return ParagraphStyle('_', parent=SS['Normal'], fontSize=size, fontName=fname,
                          textColor=color, alignment=align,
                          leading=leading or size*1.45, spaceAfter=space_after)

def HR(color=GOLD, thick=1.5, before=4, after=8):
    return HRFlowable(width='100%', thickness=thick, color=color, spaceBefore=before, spaceAfter=after)

def section(title, subtitle=None):
    items = [CondPageBreak(2.0*inch), Spacer(1, 10),
             Paragraph(title.upper(), S(13, True, BLUE, TA_LEFT)), HR(GOLD, 2, 2, 6)]
    if subtitle:
        items.append(Paragraph(subtitle, S(9, False, MID, TA_LEFT, space_after=6)))
    return items

def metric_table(headers, rows, col_widths=None, bold_col=None):
    col_widths = col_widths or [7.0*inch/len(headers)]*len(headers)
    data = [headers] + rows
    style = [
        ('BACKGROUND', (0,0), (-1,0), TH_BG), ('TEXTCOLOR', (0,0), (-1,0), WHITE),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('FONTSIZE', (0,0), (-1,0), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('ALIGN', (1,1), (1,-1), 'LEFT'),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, ALT]),
        ('INNERGRID', (0,0), (-1,-1), 0.3, MGRAY), ('BOX', (0,0), (-1,-1), 0.5, TH_BG),
        ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 4), ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]
    if bold_col is not None:
        style += [('FONTNAME', (bold_col,1),(bold_col,-1),'Helvetica-Bold'),
                  ('TEXTCOLOR', (bold_col,1),(bold_col,-1), BLUE)]
    t = Table(data, colWidths=col_widths); t.setStyle(TableStyle(style))
    return t

def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BLUE)
    canvas.rect(0.5*inch, 10.32*inch, 7.5*inch, 0.28*inch, fill=1, stroke=0)
    canvas.setFillColor(WHITE); canvas.setFont('Helvetica-Bold', 7.5)
    canvas.drawString(0.62*inch, 10.39*inch,
                      f'{TEAM.upper()}  |  2025–26 MEN\'S BASKETBALL  |  OPPONENT SCOUTING REPORT')
    canvas.setFont('Helvetica', 7.5)
    canvas.drawRightString(7.9*inch, 10.39*inch, f'Page {doc.page}')
    canvas.setFillColor(MID); canvas.setFont('Helvetica', 6.5)
    canvas.drawCentredString(4.25*inch, 0.35*inch,
                             'Internal Use Only  |  Data: CCCMBCA box scores + internal analytics pipeline')
    canvas.restoreState()

net_rank, _, _, _ = state_rank('net_rtg', ta['net_rtg'], True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — IDENTITY
# ═══════════════════════════════════════════════════════════════════════════════
def page_identity():
    e = []
    for i, (txt, sz, c, bg) in enumerate([
        (TEAM.upper(), 26, WHITE, BLUE),
        ('2025–26 MEN\'S BASKETBALL  ·  OPPONENT SCOUTING REPORT', 11, GOLD, DARK)]):
        t = Table([[txt]], colWidths=[7.5*inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), bg), ('TEXTCOLOR', (0,0), (-1,-1), c),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'), ('FONTSIZE', (0,0), (-1,-1), sz),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('TOPPADDING', (0,0), (-1,-1), 14 if i==0 else 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 14 if i==0 else 8),
        ]))
        e.append(t)
    e.append(Spacer(1, 12))

    def hcell(top, mid, bot, top_color=BLUE):
        return [Paragraph(top, S(14, True, top_color, TA_CENTER)),
                Paragraph(mid, S(7.5, False, MID, TA_CENTER)),
                Paragraph(bot, S(7, False, MID, TA_CENTER))]
    ortg_r, _, _, _ = state_rank('ortg', ta['ortg'], True)
    drtg_r, _, _, _ = state_rank('drtg', ta['drtg'], False)
    sos_r,  _, _, _ = state_rank('sos',  ta.get('sos', 0), True)
    nsign = '+' if ta['net_rtg'] >= 0 else ''
    ssign = '+' if ta.get('sos', 0) >= 0 else ''
    best = min((net_rank, 2), (ortg_r, 3), (drtg_r, 4))[1]   # highlight best rating
    cells = [
        hcell(OVR_REC, 'RECORD', 'Overall'),
        hcell(CONF_REC, 'CONF. RECORD', CONF_LABEL),
        hcell(f'{nsign}{ta["net_rtg"]:.1f}', 'NET', f'#{net_rank}/{n} Statewide',
              GREEN_TXT if best==2 else BLUE),
        hcell(f'{ta["ortg"]:.1f}', 'ORTG', f'#{ortg_r}/{n} Statewide',
              GREEN_TXT if best==3 else BLUE),
        hcell(f'{ta["drtg"]:.1f}', 'DRTG', f'#{drtg_r}/{n} Statewide',
              GREEN_TXT if best==4 else BLUE),
        hcell(f'{ssign}{ta.get("sos", 0):.1f}', 'SOS', f'#{sos_r}/{n} Statewide'),
    ]
    t2 = Table([cells], colWidths=[1.25*inch]*6)
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), LGRAY),
        ('BACKGROUND', (best,0), (best,0), GREEN_BG),
        ('INNERGRID', (0,0), (-1,-1), 0.5, MGRAY), ('BOX', (0,0), (-1,-1), 1.5, BLUE),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 8), ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    e.append(t2); e.append(Spacer(1, 14))

    # ── Statistical Identity ──────────────────────────────────────────────────
    e += section(f'Who Is {TEAM}?', 'Team identity, ranked against the CCCAA field')
    IDM = [
        ('ortg', 'Offensive Rating', 'O', True, ''), ('efg_pct', 'Effective FG%', 'O', True, '%'),
        ('ts_pct', 'True Shooting%', 'O', True, '%'), ('tov_pct', 'Turnover%', 'O', False, '%'),
        ('nst_pct', 'Non-Steal Turnover%', 'O', False, '%'), ('oreb_pct', 'Offensive Rebound%', 'O', True, '%'),
        ('ft_rate', 'Free Throw Rate', 'O', True, ''), ('tpa_rate', '3PA Rate', 'O', True, '%'),
        ('ast_rate', 'Assist Rate', 'O', True, '%'), ('ast_tov', 'Assist-to-Turnover', 'O', True, ''),
        ('bench_pct', 'Bench Points%', 'O', True, '%'),
        ('drtg', 'Defensive Rating', 'D', False, ''), ('opp_efg_pct', 'Opp Effective FG%', 'D', False, '%'),
        ('opp_ts_pct', 'Opp True Shooting%', 'D', False, '%'), ('opp_tov_pct', 'Opp Turnover% forced', 'D', True, '%'),
        ('opp_nst_pct', 'Opp Non-Steal TO% forced', 'D', True, '%'), ('dreb_pct', 'Defensive Rebound%', 'D', True, '%'),
        ('opp_ft_rate', 'Opp Free Throw Rate', 'D', False, ''), ('stl_pct', 'Steal%', 'D', True, '%'),
        ('blk_pct', 'Block%', 'D', True, '%'),
    ]
    flags = {'O': {'s': [], 'w': []}, 'D': {'s': [], 'w': []}}
    for k, lab, side, hb, u in IDM:
        if k == 'bench_pct':
            if _team_bench is None or not BENCH: continue
            vals = sorted(BENCH.values(), reverse=True)
            r = next((i+1 for i, v in enumerate(vals) if v <= _team_bench), len(vals)); tot = len(vals)
            v = _team_bench
        else:
            v = (_team_row or {}).get(k, ta.get(k))
            if v is None: continue
            r, tot, _, _ = state_rank(k, v, hb)
        cut = max(round(tot * 0.25), 1)
        entry = (r, f"{lab} {v:.1f}{u} (#{r}/{tot})")
        if r <= cut:               flags[side]['s'].append(entry)
        elif r >= tot - cut + 1:   flags[side]['w'].append(entry)

    def flagcell(title, items, hexc):
        body = '<br/>'.join('•&nbsp; ' + t for _, t in sorted(items)) if items else '<i>none</i>'
        return Paragraph(f'<font color="{hexc}"><b>{title}</b></font><br/>{body}', S(8.5, leading=12))
    id_tbl = Table([
        [flagcell('OFFENSE — Strengths (top 25%)', flags['O']['s'], GREEN_TXT),
         flagcell('OFFENSE — Weaknesses (bottom 25%)', flags['O']['w'], RED_TXT)],
        [flagcell('DEFENSE — Strengths (top 25%)', flags['D']['s'], GREEN_TXT),
         flagcell('DEFENSE — Weaknesses (bottom 25%)', flags['D']['w'], RED_TXT)],
    ], colWidths=[3.75*inch, 3.75*inch])
    id_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), GREEN_BG), ('BACKGROUND', (1,0), (1,-1), RED_BG),
        ('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOX', (0,0), (-1,-1), 0.5, BLUE),
        ('INNERGRID', (0,0), (-1,-1), 0.3, MGRAY),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8), ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    e.append(Paragraph(
        '<b>Statistical Identity</b> — every metric ranked against the CCCAA field; '
        'top-quartile ranks are flagged as strengths, bottom-quartile as weaknesses.',
        S(9, space_after=4)))
    e.append(id_tbl); e.append(Spacer(1, 10))

    # ── Auto-generated identity narrative (data-driven, no film claims) ────────
    # paras = [Core, Offense (four factors), Defense (four factors), Pace, Bottom line]
    paras = _identity_prose()
    for para in paras[:3]:
        e.append(Paragraph(para, S(9.5, False, DARK, TA_JUSTIFY, space_after=6)))
    # The four-factors numbers, in-line right under the prose that analyzes them
    e += _four_factor_tables()
    for para in paras[3:]:
        e.append(Paragraph(para, S(9.5, False, DARK, TA_JUSTIFY, space_after=6)))
    e.append(Spacer(1, 8))
    return e

def _four_factor_tables():
    e = [Spacer(1, 4),
         Paragraph('<b>Four Factors &amp; Efficiency — the numbers</b> (rank #1 = best in the CCCAA)',
                   S(9.5, True, BLUE, space_after=4))]
    head = ['Factor', TEAM, 'Rank', 'State Avg']; w = [2.6*inch, 1.4*inch, 1.4*inch, 1.6*inch]
    e.append(Paragraph('Offense', S(8.5, True, MID, space_after=2)))
    e.append(metric_table(head, [
        _ff_row('Offensive Rating', 'ortg', True, '', 1),
        _ff_row('Effective FG%', 'efg_pct', True),
        _ff_row('Turnover%', 'tov_pct', False),
        _ff_row('Offensive Rebound%', 'oreb_pct', True),
        _ff_row('Free Throw Rate', 'ft_rate', True, '', 1),
        _ff_row('3PA Rate', 'tpa_rate', True),
    ], w, bold_col=2)); e.append(Spacer(1, 8))
    e.append(Paragraph('Defense &amp; Tempo', S(8.5, True, MID, space_after=2)))
    e.append(metric_table(head, [
        _ff_row('Defensive Rating', 'drtg', False, '', 1),
        _ff_row('Opp Effective FG%', 'opp_efg_pct', False),
        _ff_row('Opp Turnover% forced', 'opp_tov_pct', True),
        _ff_row('Defensive Rebound%', 'dreb_pct', True),
        _ff_row('Opp Free Throw Rate', 'opp_ft_rate', False, '', 1),
        _ff_row('Pace (poss/game)', 'possessions', True, '', 1),
    ], w, bold_col=2)); e.append(Spacer(1, 8))
    return e

# ─── Rank → plain-language tier (drives the auto narrative adjectives) ─────────
def _tier(r, tot, lower_is_better_rank=True):
    """r is a rank where 1 = best. Returns a descriptive word for that standing."""
    p = r / tot
    if p <= 0.10: return 'elite'
    if p <= 0.25: return 'strong'
    if p <= 0.45: return 'above-average'
    if p <= 0.60: return 'average'
    if p <= 0.75: return 'below-average'
    if p <= 0.90: return 'weak'
    return 'bottom-tier'

def _R(key, hb, unit='%', dec=1):
    """Return (value, rank, n, avg, tier_word, formatted-value-string)."""
    v = (_team_row or {}).get(key, ta.get(key, 0))
    r, tot, avg, _ = state_rank(key, v, hb)
    return v, r, tot, avg, _tier(r, tot), f'{v:.{dec}f}{unit}'

def _art(w):
    return 'an' if w[:1].lower() in 'aeiou' else 'a'

def _emph(rank, tot):
    """Light interpretive tag for how extreme a rank is — factual, stat-anchored."""
    p = rank / tot
    if p <= 0.05:  return f"one of the {max(round(tot*0.05),3)} best marks in the CCCAA"
    if p <= 0.10:  return "a top-ten-percent figure statewide"
    if p <= 0.25:  return "comfortably top-quartile"
    if p >= 0.95:  return f"one of the {max(round(tot*0.05),3)} worst marks in the CCCAA"
    if p >= 0.90:  return "a bottom-ten-percent figure statewide"
    if p >= 0.75:  return "down in the bottom quartile"
    return "right around the statewide median"

def _identity_prose():
    paras = []
    o_v, o_r, o_n, o_avg, o_t, o_s = _R('ortg', True, '', 1)
    d_v, d_r, d_n, d_avg, d_t, d_s = _R('drtg', False, '', 1)
    ppg = (_team_row or {}).get('ppg', 0); oppg = (_team_row or {}).get('oppg', 0)
    net = ta['net_rtg']; nsign = '+' if net >= 0 else ''
    gap = d_r - o_r                     # >0 ⇒ offense ranks better ⇒ offense-first
    if gap >= 15:    ident, edge = 'an offense-first team', 'offensive'
    elif gap <= -15: ident, edge = 'a defense-first team',  'defensive'
    elif o_r <= o_n*0.25 and d_r <= d_n*0.25: ident, edge = 'a genuine two-way team', 'both ends'
    else:            ident, edge = 'a balanced team', 'neither end disproportionately'
    if edge in ('offensive', 'defensive'):
        edge_line = (f"The separation between those two ranks is the whole story: their measurable "
                     f"edge is on the {edge} end — that is the end that defines this team.")
    elif edge == 'both ends':
        edge_line = ("They rank top-quartile on both ends — there is no obvious soft side to attack; "
                     "the margins have to be found inside the four factors below.")
    else:
        edge_line = ("Neither end carries them — they win or lose on the margins (the four factors "
                     "and the matchups below).")
    paras.append(
        f"<b>Core identity.</b> {TEAM} finished the season <b>{OVR_REC}</b> ({CONF_REC} in "
        f"{CONF_LABEL}) and grades out as {ident}, ranked <b>#{net_rank}/{o_n}</b> statewide in net "
        f"rating at <b>{nsign}{net:.1f} per 100 possessions</b>. They score {ppg:.1f} points a game "
        f"and allow {oppg:.1f}. Their offense rates #{o_r}/{o_n} ({o_s} points per 100, against a "
        f"state average of {o_avg:.1f}) and their defense #{d_r}/{d_n} ({d_s}, avg {d_avg:.1f}). "
        f"{edge_line}")

    # Offense
    _, efg_r, _, efg_avg, efg_t, efg_s = _R('efg_pct', True)
    _, ts_r,  _, ts_avg,  ts_t,  ts_s  = _R('ts_pct', True)
    _, tpar_r,_, tpar_avg,tpar_t, tpar_s = _R('tpa_rate', True)
    _, ftr_r, _, ftr_avg, ftr_t, ftr_s = _R('ft_rate', True, '', 1)
    _, oreb_r,_, oreb_avg,oreb_t, oreb_s = _R('oreb_pct', True)
    _, ar_r,  _, ar_avg,  ar_t,  ar_s  = _R('ast_rate', True)
    _, at_r,  _, at_avg,  at_t,  at_s  = _R('ast_tov', True, '', 2)
    _, tov_r, _, tov_avg, tov_t, tov_s = _R('tov_pct', False)
    _, nst_r, _, nst_avg, nst_t, nst_s = _R('nst_pct', False)
    paras.append(
        f"<b>Offense — the four factors.</b> They post a {efg_s} effective field-goal percentage "
        f"(#{efg_r}/{o_n}, {efg_t}; state avg {efg_avg:.1f}%) and {ts_s} true shooting "
        f"(#{ts_r}/{o_n}). Their shot diet leans on a 3-point attempt rate of {tpar_s} "
        f"(#{tpar_r}/{o_n}, avg {tpar_avg:.1f}%) — {tpar_t} three-point volume, {_emph(tpar_r, o_n)}. "
        f"They get to the foul line at {_art(ftr_t)} {ftr_t} rate ({ftr_s}, #{ftr_r}/{o_n}) and rebound {oreb_s} "
        f"of their own misses (#{oreb_r}/{o_n}, {oreb_t}) to manufacture second chances. Ball movement "
        f"runs through a {ar_s} assist rate (#{ar_r}/{o_n}) and a {at_s} assist-to-turnover ratio "
        f"(#{at_r}/{o_n}); they cough it up on {tov_s} of possessions ({tov_t}, #{tov_r}/{o_n}), of "
        f"which the non-steal share is {nst_s} (#{nst_r}/{o_n}).")

    # Defense
    _, oefg_r, _, oefg_avg, oefg_t, oefg_s = _R('opp_efg_pct', False)
    _, ots_r,  _, ots_avg,  ots_t,  ots_s  = _R('opp_ts_pct', False)
    _, otov_r, _, otov_avg, otov_t, otov_s = _R('opp_tov_pct', True)
    _, dreb_r, _, dreb_avg, dreb_t, dreb_s = _R('dreb_pct', True)
    _, oftr_r, _, oftr_avg, oftr_t, oftr_s = _R('opp_ft_rate', False, '', 1)
    _, stl_r,  _, _, stl_t, stl_s = _R('stl_pct', True)
    _, blk_r,  _, _, blk_t, blk_s = _R('blk_pct', True)
    paras.append(
        f"<b>Defense — the four factors.</b> Opponents manage {oefg_s} effective FG ({oefg_t}, "
        f"#{oefg_r}/{d_n}, avg {oefg_avg:.1f}%) and {ots_s} true shooting (#{ots_r}/{d_n}) against "
        f"them — {_emph(oefg_r, d_n)} on shot defense. They force turnovers on {otov_s} of possessions "
        f"({otov_t}, #{otov_r}/{d_n}) and control the defensive glass at {dreb_s} (#{dreb_r}/{d_n}, "
        f"{dreb_t}). They keep opponents off the line at {_art(oftr_t)} {oftr_t} rate (opp FT rate {oftr_s}, "
        f"#{oftr_r}/{d_n}). The takeaways, though, are {stl_t}/{blk_t}: a {stl_s} steal rate (#{stl_r}/{d_n}) "
        f"and {blk_s} block rate (#{blk_r}/{d_n}) — the shot defense shows up as lower opponent "
        f"percentages rather than as steals or blocks.")

    # Pace, depth & bottom line
    _, pace_r, _, pace_avg, _, pace_s = _R('possessions', True, '', 1)
    pace_word = ('an up-tempo' if pace_r <= o_n*0.33 else 'a deliberate, slow' if pace_r >= o_n*0.67 else 'a middle-of-the-road')
    depth = ''
    if _team_bench is not None and BENCH:
        bvals = sorted(BENCH.values(), reverse=True)
        br = next((i+1 for i, x in enumerate(bvals) if x <= _team_bench), len(bvals))
        depth = (f" Their bench accounts for {_team_bench:.1f}% of total points "
                 f"(#{br}/{len(bvals)}, {_tier(br, len(bvals))}) — "
                 f"{'a deep rotation' if br <= len(bvals)*0.25 else 'a starter-reliant rotation' if br >= len(bvals)*0.6 else 'an average rotation depth'}.")
    # Bottom line — synthesize the single biggest strength and softest spot
    strengths, weaks = [], []
    for k, lab, hb in [('efg_pct','their shooting efficiency',True),('opp_efg_pct','their shot defense',False),
                       ('oreb_pct','offensive rebounding',True),('opp_tov_pct','forcing turnovers',True),
                       ('tpa_rate','three-point volume',True),('dreb_pct','defensive rebounding',True),
                       ('ft_rate','getting to the line',True),('opp_ft_rate','keeping opponents off the line',False)]:
        v = (_team_row or {}).get(k, ta.get(k, 0)); r, tot, _, _ = state_rank(k, v, hb)
        if r <= tot*0.20: strengths.append((r/tot, lab))
        elif r >= tot*0.80: weaks.append((-(1-r/tot), lab))   # closest to bottom first
    strengths.sort(); weaks.sort()
    bl = "<b>Bottom line.</b> "
    if strengths: bl += f"They are at their best through {strengths[0][1]}"
    if len(strengths) > 1: bl += f" and {strengths[1][1]}"
    bl += "." if strengths else "They have no single dominant strength."
    if weaks: bl += f" The clearest place they can be gotten to is {weaks[0][1]}"
    if len(weaks) > 1: bl += f", with {weaks[1][1]} a secondary soft spot"
    bl += "." if weaks else ""
    paras.append(
        f"<b>Pace &amp; depth.</b> They play {pace_word} brand at {pace_s} possessions per game "
        f"(#{pace_r}/{o_n}, state avg {pace_avg:.1f}).{depth}")
    paras.append(bl)
    return paras

# Four-factors row helper (tables now rendered inside the identity section via
# _four_factor_tables()).
def _ff_row(label, key, hb, unit='%', dec=1):
    v = (_team_row or {}).get(key, ta.get(key, 0))
    r, tot, avg, _ = state_rank(key, v, hb)
    return [label, f'{v:.{dec}f}{unit}', f'#{r}/{tot}', f'{avg:.{dec}f}{unit}']

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — KEYS TO VICTORY
# ═══════════════════════════════════════════════════════════════════════════════
def _team_head_coach(team, season="2025-26"):
    """Current head coach for a team from coaches.json, or None if unknown/vacant."""
    try:
        c = jload(f"{CODEX}/coaches.json")
        v = c.get(team)
        hc = v.get(season) if isinstance(v, dict) else v
        return hc if (hc and str(hc).strip()) else None
    except Exception:
        return None

# A team with no head coach on file has no coaching-continuity anchor, so prior
# seasons can't be attributed to the current staff — pull keys from this year only.
HEAD_COACH = _team_head_coach(TEAM, "2025-26")
KEYS_SCOPE = 'multi-season' if HEAD_COACH else 'current season'
_key_seasons = (["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
                if HEAD_COACH else ["2025-26"])
try:
    from compute_team_keys import load_team_games, analyze as _kanalyze
    _kgames = load_team_games(TEAM, _key_seasons, base_dir=CODEX, with_bench=True)
    KEYS = _kanalyze(_kgames, n_targets=3) if _kgames else None
except Exception:
    KEYS = None

def page_keys():
    e = []
    e += section('Keys to Victory',
                 f'The metrics that most separate {TEAM} wins from losses (point-biserial '
                 f'correlation, {KEYS_SCOPE}), with the targets-hit payoff.')
    if not KEYS or not KEYS.get('keys'):
        e.append(Paragraph('Insufficient game history for keys analysis.', S(9, False, MID)))
        e.append(Spacer(1, 14)); return e
    rec = KEYS['record']
    e.append(Paragraph(
        f"From {KEYS['n_games']} games ({rec[0]}-{rec[1]}): each key is the threshold that best "
        f"splits wins from losses, with {TEAM}'s average when winning vs. losing.",
        S(9.5, False, DARK, space_after=10)))
    ar = {'>=': '≥', '<=': '≤'}
    rows = [[k.metric, f"{ar.get(k.direction, k.direction)} {k.target:g}",
             f"{k.avg_win:g}", f"{k.avg_loss:g}", f"{k.r:+.2f}"] for k in KEYS['keys']]
    e.append(metric_table(['Key Metric', 'Target', 'Avg in Wins', 'Avg in Losses', 'r'],
                          rows, [2.3*inch, 1.2*inch, 1.3*inch, 1.3*inch, 0.9*inch], bold_col=0))
    e.append(Spacer(1, 14))
    e.append(Paragraph(f"<b>The payoff</b> — {TEAM}'s record by how many of the keys they hit:",
                       S(10, False, DARK, space_after=6)))
    tt = KEYS['targets_table']; nk = len(KEYS['keys']); prows = []
    for i in range(nk, -1, -1):
        r = tt.get(i, {})
        g = r.get('games', 0) or 0
        rec = f"{r.get('w', 0)}-{r.get('l', 0)}" if g else '—'
        wp = f"{r['win_pct']}%" if r.get('win_pct') is not None else '—'
        mov = f"{r['avg_mov']:+.1f}" if r.get('avg_mov') is not None else '—'
        prows.append([f"{i} of {nk}", str(g), rec, wp, mov])
    e.append(metric_table(['Keys Hit', 'Games', 'Record', 'Win %', 'Avg Margin'],
                          prows, [1.3*inch, 1.1*inch, 1.2*inch, 1.1*inch, 1.3*inch], bold_col=3))
    top = tt.get(nk, {}); bot = tt.get(0, {})
    if top.get('games') and bot.get('games'):
        e.append(Spacer(1, 12))
        e.append(Paragraph(
            f"<b>Bottom line:</b> hit all {nk} keys and {TEAM} is <b>{top['w']}-{top['l']}</b> "
            f"({top['win_pct']}%, {top['avg_mov']:+.1f} margin); hit none and they fall to "
            f"<b>{bot['w']}-{bot['l']}</b> ({bot['win_pct']}%).", S(9.5, False, DARK, TA_JUSTIFY)))
    e.append(Spacer(1, 14))
    return e

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4+ — PERSONNEL
# ═══════════════════════════════════════════════════════════════════════════════
def _cap(s):
    return s[0].upper() + s[1:] if s else s

def _lower_rt(r):
    """Lowercase a Synergy rating word for prose ('Below Average' -> 'below-average')."""
    r = (r or '').strip()
    return {'Below Average': 'below-average', 'Above Average': 'above-average'}.get(r, r.lower())

_RT_ORDER = {'poor': 0, 'below average': 1, 'below-average': 1, 'average': 2,
             'good': 3, 'very good': 4, 'excellent': 5}

# Rating words for prose — 'Very Good' becomes 'strong' so the page isn't littered
# with "very good ... very good ... very good".
_RT_PROSE = {5: 'excellent', 4: 'strong', 3: 'good', 2: 'average',
             1: 'below-average', 0: 'poor'}

def _rt_prose(rating):
    return _RT_PROSE.get(_RT_ORDER.get((rating or '').lower(), 2), 'average')

def _finish_desc(rating):
    """Natural noun phrase for rim finishing, no rating word dropped in as an adverb."""
    return {5: 'an elite finisher', 4: 'a strong finisher', 3: 'a capable finisher',
            2: 'a middling finisher', 1: 'a below-average finisher',
            0: 'a poor finisher'}[_RT_ORDER.get((rating or '').lower(), 2)]

def _catch_vs_pullup(csr, csfg, djr, djfg):
    """Describe a player's catch-and-shoot vs. pull-up split honestly, scaled to the
    actual gap — not a canned 'far less so'. Returns a sentence (leading space)."""
    cs_t = _RT_ORDER.get((csr or '').lower(), 2)
    dj_t = _RT_ORDER.get((djr or '').lower(), 2)
    diff = cs_t - dj_t            # >0 = better catching
    gap = csfg - djfg            # FG% points
    cs = f"{_rt_prose(csr)} on catch-and-shoot ({csfg:.0f}%)"
    pu = f"{djfg:.0f}% pull-up"
    if diff >= 2 or gap >= 12:
        return f" He is far more dangerous with his feet set — {cs} but markedly weaker off the bounce ({pu})."
    if gap >= 6:
        return f" He is at his best with feet set — {cs} — and a step down, though still useful, off the dribble ({pu})."
    if diff <= -1 or gap <= -6:
        return f" He is {cs} and, if anything, sharper off the dribble ({pu})."
    return f" He shoots it well both ways — {cs} and nearly as effective off the bounce ({pu})."

def _synergy_shot_clause(sa):
    """Flowing, scout-voice description of a player's Synergy shot profile —
    catch-and-shoot vs. pull-up, rim finishing, perimeter lean. Returns '' when
    no Synergy shot-type data exists (so box-only teams are unaffected)."""
    st = (sa or {}).get('shot_types') or {}
    if not st:
        return ''
    js    = st.get('jump_shot_pct_fga', 0) or 0
    rimp  = st.get('at_rim_pct_fga', 0) or 0
    rimfg = st.get('at_rim_fg_pct', 0) or 0
    rima  = st.get('at_rim_att', 0) or 0
    rimr  = st.get('at_rim_pps_rating', '') or ''
    csfg  = st.get('catch_shoot_fg_pct', 0) or 0
    csr   = st.get('catch_shoot_pps_rating', '') or ''
    djfg  = st.get('dribble_jumper_fg_pct', 0) or 0
    djr   = st.get('dribble_jumper_pps_rating', '') or ''
    ta    = st.get('three_pt_att', 0) or 0
    tfg   = st.get('three_pt_fg_pct', 0) or 0
    tr    = st.get('three_pt_pps_rating', '') or ''
    long3 = st.get('long_3_pct_of_jumpers', 0) or 0

    def rim_sent():
        if rima < 12:
            return ''
        if rimr:
            return f" At the rim he is {_finish_desc(rimr)} ({rimfg:.0f}% on {rima} attempts)."
        return f" He shoots {rimfg:.0f}% at the rim on {rima} attempts."

    # Perimeter-shooter-led profile (guards/wings who live on the jumper)
    if js >= 55 and ta >= 30:
        s = f" His offense runs through his jumper — {js:.0f}% of his shots come from the perimeter"
        if long3:
            s += f", {long3:.0f}% of them long threes"
        s += f", and he hits <b>{tfg:.0f}% on {ta} threes</b>."
        if csr and djr:
            s += _catch_vs_pullup(csr, csfg, djr, djfg)
        elif csr:
            s += f" He is {_rt_prose(csr)} on catch-and-shoot looks ({csfg:.0f}%)."
        return s + rim_sent()

    # Rim/finisher-led profile (bigs, slashers)
    if rimp >= 45:
        s = f" He scores almost entirely around the basket — {rimp:.0f}% of his attempts come at the rim"
        if rimr:
            s += f", where he is {_finish_desc(rimr)} (<b>{rimfg:.0f}%</b> on {rima})."
        else:
            s += f" (<b>{rimfg:.0f}%</b> on {rima})."
        if ta and ta <= 20:
            s += f" He offers little from the perimeter ({ta} three{'s' if ta != 1 else ''} all year)."
        return s

    # Mixed / lower-volume profile
    bits = []
    rs = rim_sent().strip()
    if rs:
        bits.append(rs)
    if csr:
        bits.append(f"He is {_rt_prose(csr)} on catch-and-shoot looks ({csfg:.0f}%).")
    if ta >= 20:
        bits.append(f"He takes {ta} threes at {tfg:.0f}%.")
    return (" " + " ".join(bits)) if bits else ''

def _player_narrative(name, avg, tot, adv, pos, mpg, gp, sa=None):
    """Flowing, scout-voice profile generated from box + advanced data, enriched
    with the player's Synergy shot profile when available. Leads with the
    defining trait; numbers woven into prose. Two paragraphs. Statewide ranks
    only; no film inference, no directives."""
    first = name.split()[-1] if name else name
    usg = adv.get('usage_pct', 0) or 0
    role, _ = kenpom_player_role(usg, mpg)
    is_big = pos in _BIG_POS
    ppg = avg.get('PTS', 0); apg = avg.get('AST', 0); rpg = avg.get('REB', 0)
    spg = avg.get('STL', 0); bpg = avg.get('BLK', 0)
    tpa = avg.get('3PA', 0); fta = avg.get('FTA', 0)
    tpp = avg.get('3P%', 0); ftp = avg.get('FT%', 0)
    ts = adv.get('ts_pct', 0) or 0
    tov = adv.get('tov_pct', 0) or 0; ast_rate = adv.get('ast_rate', 0) or 0
    oreb = adv.get('oreb_pct', 0) or 0; dreb = adv.get('dreb_pct', 0) or 0
    stlp = adv.get('stl_pct', 0) or 0; blkp = adv.get('blk_pct', 0) or 0
    fd40 = adv.get('fd_per_40', 0) or 0
    io = adv.get('ind_ortg', 0) or 0; idd = adv.get('ind_drtg', 0) or 0
    net = io - idd if (io and idd) else 0
    tot_fga = tot.get('FGA', 0) or 0
    tpa_rate = (tot.get('3PA', 0) / tot_fga * 100) if tot_fga else 0
    ft_rate  = (tot.get('FTA', 0) / tot_fga * 100) if tot_fga else 0
    two_a = (tot.get('FGA', 0) - tot.get('3PA', 0))
    two_m = (tot.get('FGM', 0) - tot.get('3PM', 0))
    twop = (two_m / two_a * 100) if two_a > 0 else 0

    pr, pn = plyr_rank('ppg', ppg, True)
    ur, un = adv_rank('usage_pct', usg, True)
    tsr, tsn = adv_rank('ts_pct', ts, True)
    ts_t = _tier(tsr, tsn) if tsn else 'average'
    arr, arn = adv_rank('ast_rate', ast_rate, True)
    elite_ts = tsn and tsr <= tsn * 0.12

    # Synergy shot profile (empty for box-only players); computed up front so the
    # lead can defer the 3P% to it and avoid a double, slightly-inconsistent mention.
    syn_shot = _synergy_shot_clause(sa)

    # ── Opening characterization — varies by what defines the player ──────────
    if ast_rate >= 20 and apg >= 3.5:
        lead = (f"{first} is the engine of {TEAM}'s offense — a {usg:.0f}%-usage lead guard who "
                f"averages <b>{apg:.1f} assists</b> a night ({ast_rate:.0f}% assist rate, "
                f"#{arr}/{arn} statewide) to go with {ppg:.1f} points across {mpg:.1f} minutes in {gp} games.")
    elif usg >= 26 and ppg >= 12:
        lead = (f"{first} is {TEAM}'s go-to scorer, shouldering a heavy <b>{usg:.0f}% of the offense</b> "
                f"(#{ur}/{un} statewide in usage) and pouring in <b>{ppg:.1f} points</b> a game "
                f"(#{pr}/{pn}) over {mpg:.1f} minutes across {gp} games.")
    elif tpa >= 3.5 and tpa_rate >= 45:
        tr, tn = plyr_rank('tpp', tpp, True)
        pct_txt = '' if syn_shot else f" at {tpp:.0f}%"
        lead = (f"{first} is {TEAM}'s floor-spacer, a {role.lower()} who launches <b>{tpa:.1f} threes</b> "
                f"a game{pct_txt} (#{tr}/{tn}) and averages {ppg:.1f} points in {mpg:.1f} minutes.")
    elif is_big and (rpg >= 6 or blkp >= 2.0):
        lead = (f"{first} is {TEAM}'s frontcourt presence, a {role.lower()} who scores {ppg:.1f} and "
                f"pulls down <b>{rpg:.1f} rebounds</b> a night across {mpg:.1f} minutes in {gp} games.")
    elif elite_ts and ppg >= 8:
        lead = (f"{first} is one of {TEAM}'s most efficient weapons, a {role.lower()} averaging "
                f"{ppg:.1f} points (#{pr}/{pn}) on {mpg:.1f} minutes a game.")
    elif ppg >= 6:
        lead = (f"{first} is a secondary scoring option for {TEAM}, a {role.lower()} good for "
                f"{ppg:.1f} points in {mpg:.1f} minutes a night ({usg:.0f}% usage).")
    else:
        lead = (f"{first} is a rotation {role.lower()} for {TEAM} — {ppg:.1f} points and {rpg:.1f} "
                f"rebounds in {mpg:.1f} minutes a game ({usg:.0f}% usage) across {gp} games.")

    # ── Shot diet + efficiency, woven into prose (no "He is a X:" label) ──────
    drawn = f", {fd40:.1f} fouls drawn per 40" if fd40 >= 5 else ""
    if tpa_rate <= 20 and ft_rate >= 35:
        shot = (f" Nearly all of his offense comes inside the arc — just {tpa_rate:.0f}% of his "
                f"attempts are threes — and he lives at the foul line ({ft_rate:.0f} free-throw rate{drawn}). "
                f"He finishes {twop:.0f}% on twos and {ftp:.0f}% at the stripe, netting "
                f"<b>{ts:.1f}% true shooting</b> (#{tsr}/{tsn}, {ts_t}).")
    elif tpa_rate <= 20:
        shot = (f" He scores mostly inside — only {tpa_rate:.0f}% of his shots are threes — hitting "
                f"{twop:.0f}% on twos" + (f" and {ftp:.0f}% at the line" if fta >= 1 else "") +
                f" for <b>{ts:.1f}% true shooting</b> (#{tsr}/{tsn}, {ts_t}).")
    elif tpa_rate >= 45:
        tr, tn = plyr_rank('tpp', tpp, True)
        shot = (f" He makes his living behind the arc: {tpa_rate:.0f}% of his attempts are threes, and "
                f"he knocks them down at {tpp:.0f}% on {tpa:.1f} a game (#{tr}/{tn}), good for "
                f"<b>{ts:.1f}% true shooting</b> (#{tsr}/{tsn}, {ts_t}).")
    else:
        tr, tn = plyr_rank('tpp', tpp, True)
        shot = (f" His shot diet splits inside and out ({tpa_rate:.0f}% threes): {twop:.0f}% on twos, "
                f"{tpp:.0f}% from deep on {tpa:.1f} a game (#{tr}/{tn})" +
                (f", {ftp:.0f}% at the line" if fta >= 1 else "") +
                f" — <b>{ts:.1f}% true shooting</b> overall (#{tsr}/{tsn}, {ts_t}).")
    para1 = lead + (syn_shot if syn_shot else shot)

    # ── Secondary skills + ball security + impact, flowing ────────────────────
    sents = []
    if apg >= 2.5 and not (ast_rate >= 20 and apg >= 3.5):
        sents.append(f"He moves the ball as a secondary creator ({apg:.1f} APG, {ast_rate:.0f}% assist rate, #{arr}/{arn}).")
    if is_big or rpg >= 5:
        orr, orn = adv_rank('oreb_pct', oreb, True)
        drr, drn = adv_rank('dreb_pct', dreb, True)
        sents.append(f"On the glass he grabs {rpg:.1f} a game ({oreb:.0f}% of offensive boards, "
                     f"#{orr}/{orn}; {dreb:.0f}% defensive, #{drr}/{drn}).")
    dfn = []
    if spg >= 1.0 or stlp >= 2.0:
        sr, sn = adv_rank('stl_pct', stlp, True)
        dfn.append(f"{spg:.1f} steals a game ({stlp:.1f}% steal rate, #{sr}/{sn})")
    if bpg >= 0.6 or blkp >= 1.5:
        br, bn = adv_rank('blk_pct', blkp, True)
        dfn.append(f"{bpg:.1f} blocks ({blkp:.1f}% block rate, #{br}/{bn})")
    if dfn:
        sents.append("Defensively he produces " + " and ".join(dfn) + ".")
    if tov:
        tvr, tvn = adv_rank('tov_pct', tov, False)
        tv_word = ('takes good care of the ball' if tov < 13 else
                   'can be loose with the ball' if tov > 20 else 'is about average with the ball')
        sents.append(f"He {tv_word} ({tov:.0f}% turnover rate, #{tvr}/{tvn}).")
    if io and idd:
        nsign = '+' if net >= 0 else ''
        impact = ('the team is markedly better with him on the floor' if net > 10 else
                  'the team is meaningfully worse with him on the floor' if net < -5 else
                  'a roughly neutral on-court impact')
        sents.append(f"His individual efficiency margin is <b>{nsign}{net:.1f}</b> "
                     f"(offensive rating {io:.0f}, defensive rating {idd:.0f}) — {impact}.")
    para2 = " ".join(sents)
    return [p for p in (para1, para2) if p.strip()]

# ═══════════════════════════════════════════════════════════════════════════════
# SYNERGY TEAM PLAY-TYPES  (only renders if a Synergy export exists for the team)
# ═══════════════════════════════════════════════════════════════════════════════
def page_synergy_team():
    path = f"{CODEX}/internal_data/synergy_team_{TEAM.lower().replace(' ', '_')}_2025_26.json"
    if not os.path.exists(path):
        return []
    syn = jload(path)
    e = []
    e += section('Synergy Play-Types',
                 'Per-possession efficiency by play type (Synergy logged data). Pctile and rating '
                 'are vs. the Synergy field; eFG% is the shooting on that play type.')

    def _ptable(side_key, title, ppp_higher_better):
        s = syn.get(side_key, {})
        pts = s.get('play_types', [])
        sign = '+' if False else ''
        hdr_line = (f"<b>{title}</b> — {s.get('ppp',0):.3f} PPP "
                    f"({s.get('ppp_pctile',0)}th pctile, {s.get('rating','')}), "
                    f"{s.get('efg',0):.1f}% eFG, "
                    f"{('TOV ' if side_key=='offense' else 'forced TOV ')}"
                    f"{s.get('tov', s.get('tov_forced',0)):.1f}%")
        block = [Paragraph(hdr_line, S(9.5, True, BLUE, space_after=4))]
        rows = [[p['name'], f"{p['pct_time']:.1f}%", str(p['poss']),
                 f"{p['ppp']:.3f}", f"{p['pctile']}", p['rating'], f"{p['efg']:.1f}%"]
                for p in pts]
        block.append(metric_table(
            ['Play Type', '%Time', 'Poss', 'PPP', 'Pctile', 'Rating', 'eFG%'],
            rows, [2.1*inch, 0.8*inch, 0.7*inch, 0.8*inch, 0.8*inch, 1.2*inch, 0.8*inch], bold_col=3))
        block.append(Spacer(1, 12))
        return block

    e += _ptable('offense', f'{TEAM} Offense', True)
    e += _ptable('defense', f'{TEAM} Defense (opponents vs. them)', False)
    e.append(Spacer(1, 6))
    return e

def page_personnel():
    e = []
    e += section('Personnel',
                 'Players averaging 6+ PPG, plus recent starters. Box stats and statewide '
                 'ranks only; no film-derived claims.')
    pmap = {p['name']: {'avg': p['averages'], 'tot': p['totals'],
                        'adv': plyr_adv.get(p['name'], {})} for p in plyr_stats['players']}
    profiled = [nm for nm in pmap
                if (pmap[nm]['avg'].get('PTS', 0) > 5.9 or is_starter(nm))
                and nm not in REMOVED_PLAYERS]
    profiled.sort(key=lambda nm: pmap[nm]['avg'].get('MIN', 0), reverse=True)

    for nm in profiled:
        mark = len(e)
        d = pmap[nm]; avg = d['avg']; tot = d['tot']; adv = d['adv']
        mpg = avg.get('MIN', 0); gp = avg.get('games', 0)
        pos = pos_map.get(nm, '—'); usg = adv.get('usage_pct', 0) or 0
        role, rcolor = kenpom_player_role(usg, mpg)
        ind_o = adv.get('ind_ortg', 0); ind_d = adv.get('ind_drtg', 0)
        net = (ind_o - ind_d) if (ind_o and ind_d) else 0
        nsign = '+' if net >= 0 else ''
        ncol = '#1a5c30' if net > 10 else ('#7b1b1b' if net < 0 else '#555577')
        start_tag = '  ·  <font color="#C4922A">recent starter</font>' if started_recently(nm) else ''
        ht = height_map.get(nm, '')
        ht_txt = f'  ·  <font color="#ffffff"><b>{ht}</b></font>' if ht else ''
        p_hdr = Table([[
            Paragraph(nm.upper(), S(11, True, WHITE)),
            Paragraph(f'{pos}  ·  {pos_full.get(pos, pos)}{ht_txt}<br/>'
                      f'<font color="{rcolor}"><b>{role}</b></font> '
                      f'<font color="{rcolor}">({usg:.0f}% poss)</font>{start_tag}',
                      S(8.5, False, GOLD, TA_CENTER)),
            Paragraph(f'{gp} GP  ·  {mpg:.1f} MPG<br/>'
                      f'<font color="#888888">ORtg {ind_o:.0f} · DRtg {ind_d:.0f} · </font>'
                      f'<font color="{ncol}"><b>Net {nsign}{net:.1f}</b></font>',
                      S(8.5, False, colors.HexColor('#aaaaaa'), TA_RIGHT)),
        ]], colWidths=[2.7*inch, 2.6*inch, 2.2*inch])
        p_hdr.setStyle(TableStyle([
            ('BACKGROUND', (0,0),(-1,-1), DARK),
            ('TOPPADDING', (0,0),(-1,-1), 7), ('BOTTOMPADDING', (0,0),(-1,-1), 7),
            ('LEFTPADDING', (0,0),(-1,-1), 10), ('RIGHTPADDING', (0,0),(-1,-1), 10),
            ('VALIGN', (0,0),(-1,-1), 'MIDDLE'),
        ]))
        e.append(p_hdr)
        # ── Synergy profile (gated) — matches the Moorpark generator's layout:
        #    archetype row → left-drive flag → shot table → note, right under the
        #    header and BEFORE the narrative. ───────────────────────────────────
        sa = SYNERGY_PLAYERS.get(nm)
        if sa:
            spos = sa.get('pos') or pos
            syn = synergy_archetype(spos, sa, tot, avg.get('AST', 0))
            bi = bball_index_archetype(spos, adv, tot, sa)
            arch_cells = []
            if syn: arch_cells.append(Paragraph(f'<b>Synergy Archetype:</b>  {syn}', S(8.5, False, GOLD)))
            if bi:  arch_cells.append(Paragraph(f'<b>bball-index Archetype:</b>  {bi}',
                                                S(8.5, False, colors.HexColor('#6fa8ff'))))
            if sa.get('scoring_summary'):
                arch_cells.append(Paragraph(sa['scoring_summary'], S(7.5, False, colors.HexColor('#aab8d0'))))
            if arch_cells:
                arch_row = Table([[c] for c in arch_cells], colWidths=[7.5*inch])
                arch_row.setStyle(TableStyle([
                    ('BACKGROUND', (0,0),(-1,-1), colors.HexColor('#0d1a2e')),
                    ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
                    ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
                    ('BOX',(0,0),(-1,-1),0.5,BLUE)]))
                e.append(arch_row)
            dd = sa.get('drive_direction')
            if dd:
                lp = dd.get('drives_left_poss', 0); rp = dd.get('drives_right_poss', 0)
                mid = dd.get('drives_straight_poss', 0); dtot = lp + rp
                if dtot >= 10 and lp > rp and (lp / dtot) >= 0.55:
                    share = round(lp / dtot * 100)
                    lppp = dd.get('drives_left_ppp', 0) or 0; rppp = dd.get('drives_right_ppp', 0) or 0
                    eff = ('  He is also more efficient going left.' if lppp > rppp + 0.05
                           else '  He is less efficient going left.' if rppp > lppp + 0.05 else '')
                    midtxt = f', {mid} middle' if mid else ''; note = dd.get('scouting_note', '')
                    flag_txt = (f'<b>&#9668; LEFT-HAND DOMINANT DRIVER &mdash;</b>  '
                                f'Of his directional drives, {share}% go left ({lp} left vs {rp} right{midtxt}).' + eff
                                + (f'<br/><i>{note}</i>' if note else ''))
                    dd_row = Table([[Paragraph(flag_txt, S(8, False, colors.HexColor('#ffd54f')))]], colWidths=[7.5*inch])
                    dd_row.setStyle(TableStyle([
                        ('BACKGROUND', (0,0),(-1,-1), colors.HexColor('#2a1500')),
                        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
                        ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
                        ('BOX',(0,0),(-1,-1),0.8,colors.HexColor('#e8a000'))]))
                    e.append(dd_row)
            st_data = sa.get('shot_types') or {}
            if st_data:
                _TEAL = colors.HexColor('#b2dfdb'); _TEAL_DK = colors.HexColor('#001a18'); _TEAL_BD = colors.HexColor('#26a69a')
                rim_att = st_data.get('at_rim_att', 0); thr_att = st_data.get('three_pt_att', 0)
                rim_lbl = f'AT RIM ({rim_att} att)' if rim_att else 'AT RIM'
                thr_lbl = f'3-PT ({thr_att} att)' if thr_att else '3-PT'
                shot_inner = Table([
                    [Paragraph(rim_lbl, S(6.5, True, _TEAL, TA_CENTER)),
                     Paragraph('CATCH & SHOOT', S(6.5, True, _TEAL, TA_CENTER)),
                     Paragraph('DRIB. JUMPER', S(6.5, True, _TEAL, TA_CENTER)),
                     Paragraph(thr_lbl, S(6.5, True, _TEAL, TA_CENTER))],
                    [Paragraph(f"<b>{st_data.get('at_rim_fg_pct',0):.1f}%</b>  <font color='#b2dfdb'>{st_data.get('at_rim_pps_rating','')}</font>", S(8.5, False, WHITE, TA_CENTER)),
                     Paragraph(f"<b>{st_data.get('catch_shoot_fg_pct',0):.1f}%</b>  <font color='#b2dfdb'>{st_data.get('catch_shoot_pps_rating','')}</font>", S(8.5, False, WHITE, TA_CENTER)),
                     Paragraph(f"<b>{st_data.get('dribble_jumper_fg_pct',0):.1f}%</b>  <font color='#b2dfdb'>{st_data.get('dribble_jumper_pps_rating','')}</font>", S(8.5, False, WHITE, TA_CENTER)),
                     Paragraph(f"<b>{st_data.get('three_pt_fg_pct',0):.1f}%</b>  <font color='#b2dfdb'>{st_data.get('three_pt_pps_rating','')}</font>", S(8.5, False, WHITE, TA_CENTER))],
                ], colWidths=[1.875*inch]*4)
                shot_inner.setStyle(TableStyle([
                    ('BACKGROUND',(0,0),(-1,-1),_TEAL_DK), ('INNERGRID',(0,0),(-1,-1),0.3,_TEAL_BD),
                    ('BOX',(0,0),(-1,-1),0.5,_TEAL_BD), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                    ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
                    ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4)]))
                e.append(shot_inner)
                if st_data.get('scouting_note'):
                    note_row = Table([[Paragraph(f"<i>{st_data['scouting_note']}</i>", S(7.5, False, _TEAL))]], colWidths=[7.5*inch])
                    note_row.setStyle(TableStyle([
                        ('BACKGROUND',(0,0),(-1,-1),_TEAL_DK), ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),4),
                        ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
                        ('BOX',(0,0),(-1,-1),0.5,_TEAL_BD)]))
                    e.append(note_row)
            e.append(Spacer(1, 4))
        for para in _player_narrative(nm, avg, tot, adv, pos, mpg, gp, sa):
            e.append(Paragraph(para, S(9.5, False, DARK, TA_JUSTIFY, space_after=5)))
        # Advanced analytics prose line (statewide ranks over the Min% ≥30% pool)
        if mpg >= 12.0 and (adv.get('ind_ortg', 0) or 0) > 0:
            ind_o_v = adv.get('ind_ortg', 0); ind_d_v = adv.get('ind_drtg', 0)
            ast_v = adv.get('ast_rate', 0); tov_v = adv.get('tov_pct', 0)
            oreb_v = adv.get('oreb_pct', 0); dreb_v = adv.get('dreb_pct', 0)
            stl_v = adv.get('stl_pct', 0); blk_v = adv.get('blk_pct', 0)
            ftr_v = adv.get('ft_rate', 0)
            _2a = tot.get('FGA', 0) - tot.get('3PA', 0)
            _2m = tot.get('FGM', 0) - tot.get('3PM', 0)
            twop_v = round(_2m / _2a * 100, 1) if _2a > 0 else 0
            tpp_v = avg.get('3P%', 0); ftp_v = avg.get('FT%', 0)
            _ior, _n = adv_rank('ind_ortg', ind_o_v)
            _idr, _ = adv_rank('ind_drtg', ind_d_v, False)
            _ar, _ = adv_rank('ast_rate', ast_v)
            _tvr, _ = adv_rank('tov_pct', tov_v, False)
            _orr, _ = adv_rank('oreb_pct', oreb_v)
            _drr, _ = adv_rank('dreb_pct', dreb_v)
            _sr, _ = adv_rank('stl_pct', stl_v)
            _br, _ = adv_rank('blk_pct', blk_v)
            _2pr, _ = adv_rank('twop', twop_v) if twop_v > 0 else (0, _n)
            _3pr, _ = adv_rank('tpp', tpp_v) if tpp_v > 0 else (0, _n)
            _ftr, _ = adv_rank('ftp', ftp_v) if ftp_v > 0 else (0, _n)
            _upr, _ = adv_rank('usage_pct', usg) if usg > 0 else (0, _n)
            _ftrr, _ = adv_rank('ft_rate', ftr_v) if ftr_v > 0 else (0, _n)
            efg_v = adv.get('efg_pct', 0); ts_v = adv.get('ts_pct', 0)
            _efr, _ = adv_rank('efg_pct', efg_v) if efg_v > 0 else (0, _n)
            _tsr, _ = adv_rank('ts_pct', ts_v) if ts_v > 0 else (0, _n)
            fc_v = adv.get('fc_per_40', 0); fd_v = adv.get('fd_per_40', 0)
            _fcr, _ = adv_rank('fc_per_40', fc_v, False) if fc_v > 0 else (0, _n)
            _fdr, _ = adv_rank('fd_per_40', fd_v) if fd_v > 0 else (0, _n)
            shp_v = adv.get('shot_pct', 0)
            _shr, _ = adv_rank('shot_pct', shp_v) if shp_v > 0 else (0, _n)
            minp_v = mpg / 40.0 * 100
            _mnr, _ = adv_rank('min_pct', minp_v) if minp_v > 0 else (0, _n)
            adv_prose = (
                f'<i>Advanced analytics ({_n} qualified players, Min% &ge;30%): '
                f'Ind ORtg <b>{ind_o_v:.1f}</b> (#{_ior})  &middot;  '
                f'Ind DRtg <b>{ind_d_v:.1f}</b> (#{_idr})  &middot;  '
                + (f'eFG% <b>{efg_v:.1f}%</b> (#{_efr})  &middot;  ' if efg_v > 0 else '')
                + (f'TS% <b>{ts_v:.1f}%</b> (#{_tsr})  &middot;  ' if ts_v > 0 else '')
                + f'Min% <b>{minp_v:.1f}%</b>' + (f' (#{_mnr})' if minp_v > 0 else '') + '  &middot;  '
                + f'%Poss <b>{usg:.1f}%</b>' + (f' (#{_upr})' if usg > 0 else '') + '  &middot;  '
                + (f'%Shots <b>{shp_v:.1f}%</b> (#{_shr})  &middot;  ' if shp_v > 0 else '')
                + f'AST Rate <b>{ast_v:.1f}%</b> (#{_ar})  &middot;  '
                f'TOV% <b>{tov_v:.1f}%</b> (#{_tvr})  &middot;  '
                f'OREB% <b>{oreb_v:.1f}%</b> (#{_orr})  &middot;  '
                f'DREB% <b>{dreb_v:.1f}%</b> (#{_drr})  &middot;  '
                f'STL% <b>{stl_v:.1f}%</b> (#{_sr})  &middot;  '
                f'BLK% <b>{blk_v:.1f}%</b> (#{_br})  &middot;  '
                f'FT Rate <b>{ftr_v:.1f}</b>' + (f' (#{_ftrr})' if ftr_v > 0 else '')
                + (f'  &middot;  FC/40 <b>{fc_v:.1f}</b> (#{_fcr})' if fc_v > 0 else '')
                + (f'  &middot;  FD/40 <b>{fd_v:.1f}</b> (#{_fdr})' if fd_v > 0 else '')
                + (f'  &middot;  2P% <b>{twop_v:.1f}%</b> (#{_2pr})' if twop_v > 0 else '')
                + (f'  &middot;  3P% <b>{tpp_v:.1f}%</b> (#{_3pr})' if tpp_v > 0 else '')
                + (f'  &middot;  FT% <b>{ftp_v:.1f}%</b> (#{_ftr})' if ftp_v > 0 else '')
                + '</i>'
            )
            e.append(Paragraph(adv_prose, S(7.5, False, colors.HexColor('#aab8d0'), space_after=4)))
        top = [Paragraph(v, S(12, True, BLUE, TA_CENTER)) for v in [
            f"{avg.get('PTS',0):.1f}", f"{avg.get('REB',0):.1f}", f"{avg.get('AST',0):.1f}",
            f"{avg.get('STL',0):.1f}", f"{avg.get('BLK',0):.1f}", f"{avg.get('FG%',0):.0f}%",
            f"{avg.get('3P%',0):.0f}%", f"{avg.get('FT%',0):.0f}%",
            f"{adv.get('ts_pct',0):.0f}%", f"{usg:.0f}%"]]
        bot = [Paragraph(l, S(6.5, False, MID, TA_CENTER)) for l in
               ['PPG','RPG','APG','SPG','BPG','FG%','3P%','FT%','TS%','USG']]
        st = Table([top, bot], colWidths=[0.75*inch]*10)
        st.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),LGRAY), ('INNERGRID',(0,0),(-1,-1),0.3,MGRAY),
            ('BOX',(0,0),(-1,-1),0.5,BLUE), ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,0),4), ('BOTTOMPADDING',(0,1),(-1,1),4),
        ]))
        e.append(st)
        if mpg > 4.0:
            pr, pn = plyr_rank('ppg', avg.get('PTS',0), True)
            tr, tn = plyr_rank('ts_pct', adv.get('ts_pct',0), True)
            tpr, tpn = plyr_rank('tpp', avg.get('3P%',0), True)
            e.append(Paragraph(
                f'State context ({pn} qualifying players): '
                f'PPG #{pr}/{pn}  ·  TS% #{tr}/{tn}  ·  3P% #{tpr}/{tpn}',
                S(7.5, italic=True, color=MID)))
        block = e[mark:]; del e[mark:]
        e.append(KeepTogether(block)); e.append(Spacer(1, 12))
    return e

# ═══════════════════════════════════════════════════════════════════════════════
def build():
    out = f'{BASE}/{TEAM.replace(" ", "_")}_scouting_report_2025_26.pdf'
    doc = SimpleDocTemplate(out, pagesize=letter,
                            topMargin=0.75*inch, bottomMargin=0.6*inch,
                            leftMargin=0.5*inch, rightMargin=0.5*inch)
    story = page_identity() + page_keys() + page_synergy_team() + page_personnel()
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"Saved: {out} ({os.path.getsize(out)//1024} KB)")

if __name__ == '__main__':
    build()
