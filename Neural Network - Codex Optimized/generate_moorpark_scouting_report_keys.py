"""
Moorpark College 2025-26 — Scouting Report (MY VERSION: "What's Important")

Opinionated, not a metric dump. A scout wants four answers:
  1. Who are they?  2. What makes them win?  3. How do you beat them?  4. Bottom line.

Engine: build the full team-metric universe, rank statewide, then roll metrics up
into THEMES weighted toward the four factors (the pillars that actually predict
wins). The rank engine decides which themes are strengths vs cracks; a small
rules layer turns those into an actual game plan. Lean, editorial, decision-first.

Sibling of generate_moorpark_scouting_report_prototype.py (raw auto engine);
original hand-written report preserved as ...backup.py.
Run: /usr/local/bin/python3 generate_moorpark_scouting_report_keys.py [Team]
"""
import json, os, sys, re
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable, KeepTogether, PageBreak)

BLUE=colors.HexColor('#003087'); GOLD=colors.HexColor('#C4922A')
DARK=colors.HexColor('#1a1a2e'); MID=colors.HexColor('#555577')
LGRAY=colors.HexColor('#f2f3f7'); MGRAY=colors.HexColor('#dde0ea')
GREEN_BG=colors.HexColor('#e6f4ea'); RED_BG=colors.HexColor('#fbeaec')
GREEN=colors.HexColor('#1a5c30'); RED=colors.HexColor('#7b1b1b'); WHITE=colors.white
ALT=colors.HexColor('#e8ecf5')
BASE='/Users/chadoconnor/Neural Network'
_CODEX = os.path.dirname(os.path.abspath(__file__))   # box scores / leaderboard modules live here
TEAM = sys.argv[1] if len(sys.argv) > 1 else 'Moorpark'

def jload(p): return json.load(open(p))

def build_metrics(a, s):
    av, op = s['averages'], s['opponent_averages']
    poss = max(a.get('possessions', 0.01), 0.01)
    def twop(d):
        fa = d['FGA'] - d['3PA']; fm = d['FGM'] - d['3PM']
        return round(fm / fa * 100, 1) if fa > 0 else 0.0
    r = lambda x: round(x, 1)
    return {
        'ortg': a.get('ortg', 0), 'drtg': a.get('drtg', 0), 'net_rtg': a.get('net_rtg', 0),
        'tempo': r(poss),
        'efg_pct': a.get('efg_pct', 0), 'ts_pct': a.get('ts_pct', 0),
        'tp_pct': av['3P%'], 'twop': twop(av), 'ft_pct': av['FT%'],
        'tpa_rate': r(av['3PA'] / av['FGA'] * 100) if av['FGA'] else 0,
        'tov_pct': a.get('tov_pct', 0), 'nst_pct': r(max(av['TO'] - op['STL'], 0) / poss * 100),
        'oreb_pct': a.get('oreb_pct', 0), 'ft_rate': a.get('ft_rate', 0),
        'ast_pct': a.get('ast_rate', 0), 'ast_tov': r(av['AST'] / av['TO']) if av['TO'] else 0,
        'ast_diff': r(av['AST'] - op['AST']),
        'opp_efg_pct': a.get('opp_efg_pct', 0), 'opp_ts_pct': a.get('opp_ts_pct', 0),
        'opp_tp_pct': op['3P%'], 'opp_twop': twop(op),
        'opp_tov_pct': a.get('opp_tov_pct', 0), 'opp_nst_pct': r(max(op['TO'] - av['STL'], 0) / poss * 100),
        'dreb_pct': a.get('dreb_pct', 0), 'opp_ft_rate': a.get('opp_ft_rate', 0),
        'stl_pct': a.get('stl_pct', 0), 'blk_pct': a.get('blk_pct', 0),
    }

# direction: H higher better, L lower better
DIR = {'net_rtg':'H','ortg':'H','drtg':'L','efg_pct':'H','ts_pct':'H','tp_pct':'H','twop':'H',
       'ft_pct':'H','tov_pct':'L','nst_pct':'L','oreb_pct':'H','ft_rate':'H','ast_pct':'H',
       'ast_tov':'H','ast_diff':'H','opp_efg_pct':'L','opp_ts_pct':'L','opp_tp_pct':'L',
       'opp_twop':'L','opp_tov_pct':'H','opp_nst_pct':'H','dreb_pct':'H','opp_ft_rate':'L',
       'stl_pct':'H','blk_pct':'H'}
LAB = {'net_rtg':'Net Rating','ortg':'Off Rating','drtg':'Def Rating','efg_pct':'eFG%',
       'ts_pct':'TS%','tp_pct':'3P%','twop':'2P%','ft_pct':'FT%','tov_pct':'TOV%','nst_pct':'NST%',
       'oreb_pct':'OREB%','ft_rate':'FT Rate','ast_pct':'Assist Rate','ast_tov':'AST/TO',
       'ast_diff':'Assist Margin','opp_efg_pct':'Opp eFG%','opp_ts_pct':'Opp TS%','opp_tp_pct':'Opp 3P%',
       'opp_twop':'Opp 2P%','opp_tov_pct':'Opp TOV%','opp_nst_pct':'Opp NST%','dreb_pct':'DREB%',
       'opp_ft_rate':'Opp FT Rate','stl_pct':'Steal%','blk_pct':'Block%','tempo':'Tempo',
       'tpa_rate':'3PA Rate'}

def load_all():
    teams = {}
    for conf in os.listdir(f'{BASE}/2025-26 Team Statistics'):
        cp = f'{BASE}/2025-26 Team Statistics/{conf}'
        if not os.path.isdir(cp): continue
        for t in os.listdir(cp):
            ap, sp = f'{cp}/{t}/advanced_analytics.json', f'{cp}/{t}/team_summary.json'
            if not (os.path.exists(ap) and os.path.exists(sp)): continue
            try: teams[t] = build_metrics(jload(ap)['team'], jload(sp))
            except Exception: pass
    return teams

ALL = load_all(); ME = ALL[TEAM]; N = len(ALL)

def rank(key):
    hb = DIR.get(key, 'H') != 'L'
    vals = [v[key] for v in ALL.values() if isinstance(v.get(key), (int, float))]
    val = ME[key]; ordered = sorted(vals, reverse=hb)
    r = next((i + 1 for i, v in enumerate(ordered)
              if (hb and v <= val) or (not hb and v >= val)), len(ordered))
    avg = round(sum(vals) / len(vals), 1)
    pct = round((1 - (r - 1) / max(len(ordered) - 1, 1)) * 100)
    return r, len(ordered), avg, pct

def pct(key): return rank(key)[3]

# ── Keys to Victory — what this team has needed to win (compute_team_keys) ────
KEYS = None
try:
    from compute_team_keys import load_team_games, analyze
    _ks = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]   # last-5 / coach-era window
    _kgames = load_team_games(TEAM, _ks, base_dir=_CODEX, with_bench=True)
    KEYS = analyze(_kgames, n_targets=3) if _kgames else None
except Exception:
    KEYS = None

# ── Bench / depth — statewide ranks via the leaderboard's box-score loader ────
HAS_BENCH = False
try:
    from generate_leaderboard import load_all_bench_points
    _bench = load_all_bench_points("2025-26", base_dir=_CODEX)
    for t, m in ALL.items():
        bd = _bench.get(t)
        if bd and bd.get('total_pts'):
            m['bench_pct'] = round(bd['bench_pts'] / bd['total_pts'] * 100, 1)
            m['bench_ppg'] = round(bd['bench_pts'] / max(bd['games'], 1), 1)
            m['bench_per100'] = round(m['bench_ppg'] / max(m['tempo'], 0.01) * 100, 1)
            if bd.get('clean_bench_min'):
                m['bench_per40'] = round(bd['clean_bench_pts'] / bd['clean_bench_min'] * 40, 1)
    DIR.update({'bench_pct': 'H', 'bench_ppg': 'H', 'bench_per100': 'H', 'bench_per40': 'H'})
    LAB.update({'bench_pct': 'Bench Points %', 'bench_ppg': 'Bench Pts/G',
                'bench_per100': 'Bench Pts/100', 'bench_per40': 'Bench Pts/40'})
    HAS_BENCH = 'bench_pct' in ME
except Exception:
    HAS_BENCH = False

# ── THEMES: roll metrics up into scout-relevant pillars (four-factor weighted) ─
# (name, [keys], side, weight) — weight reflects four-factor importance.
THEMES = [
    ('Half-court shot defense', ['opp_efg_pct','opp_ts_pct','opp_twop','opp_tp_pct','drtg'], 'D', 1.0),
    ('Forcing turnovers',       ['opp_tov_pct','opp_nst_pct'],                                'D', 0.6),
    ('Defensive rebounding',    ['dreb_pct'],                                                 'D', 0.5),
    ('Rim protection & steals', ['stl_pct','blk_pct'],                                        'D', 0.4),
    ('Staying out of fouls',    ['opp_ft_rate'],                                              'D', 0.4),
    ('Scoring efficiency',      ['ortg','efg_pct','ts_pct'],                                  'O', 1.0),
    ('Ball movement',           ['ast_pct','ast_tov','ast_diff'],                             'O', 0.5),
    ('Taking care of the ball', ['tov_pct','nst_pct'],                                        'O', 0.6),
    ('Offensive rebounding',    ['oreb_pct'],                                                 'O', 0.5),
    ('Getting to the line',     ['ft_rate'],                                                  'O', 0.4),
]
if HAS_BENCH:
    THEMES.append(('Bench scoring & depth', ['bench_pct', 'bench_per100'], 'O', 0.5))
def theme_pct(keys): return round(sum(pct(k) for k in keys) / len(keys))

themed = []
for name, keys, side, w in THEMES:
    tp = theme_pct(keys)
    members = sorted(keys, key=lambda k: -pct(k))
    themed.append({'name': name, 'keys': keys, 'side': side, 'w': w, 'pct': tp,
                   'best': members[0], 'worst': members[-1]})
strength_themes = sorted([t for t in themed if t['pct'] >= 60], key=lambda t: -(t['pct'] * t['w']))
weakness_themes = sorted([t for t in themed if t['pct'] <= 40], key=lambda t: (t['pct'] / t['w']))

def cite(key):
    r, tot, avg, p = rank(key); u = '' if key in ('net_rtg','ortg','drtg','tempo','ast_tov','ast_diff','ft_rate','bench_per100') else '%'
    return f"{LAB[key]} {ME[key]}{u} (#{r}/{tot})"

# ── Identity line ────────────────────────────────────────────────────────────
off_p = round(sum(pct(k) for k in ['ortg','efg_pct','ts_pct']) / 3)
def_p = round(sum(pct(k) for k in ['drtg','opp_efg_pct','opp_ts_pct']) / 3)
lean = 'defense-first' if def_p - off_p >= 12 else 'offense-first' if off_p - def_p >= 12 else 'balanced'
pace_p = pct('tempo'); pace_word = 'up-tempo' if pace_p >= 67 else 'deliberate' if pace_p <= 33 else 'average-pace'
shotdiet = 'three-point-reliant' if pct('tpa_rate') >= 67 else 'paint-oriented' if pct('tpa_rate') <= 33 else 'balanced-diet'
_art = 'An' if pace_word[0] in 'aeiou' else 'A'
identity = f"{_art} {pace_word}, {lean}, {shotdiet} team."

# ── Game plan rules (how to beat them) ───────────────────────────────────────
plan = []
if pace_p >= 60: plan.append("<b>Control tempo.</b> They thrive in transition — shorten the game, get back on defense, and force them into the half court.")
if pct('opp_tp_pct') >= 60 or pct('opp_efg_pct') >= 60:
    plan.append("<b>Attack the paint, don't trade threes.</b> They contest the perimeter well — drive, draw help, and get to the rim/line instead of settling.")
if pct('ft_rate') <= 35:
    plan.append("<b>Make them earn it in the half court.</b> They rarely get to the foul line — wall up, contest cleanly, and they have few easy points.")
if pct('stl_pct') <= 40 and pct('blk_pct') <= 40:
    plan.append("<b>Value the ball and attack the rim.</b> They generate few steals and blocks — disciplined ball-handling neutralizes their disruption and the rim is open.")
if pct('nst_pct') <= 35 or pct('tov_pct') <= 40:
    plan.append("<b>Pressure the handle.</b> They give it away on their own (high live-ball turnovers) — ball pressure turns their offense into your transition.")
if pct('oreb_pct') <= 40:
    plan.append("<b>Don't fear the offensive glass.</b> They don't crash hard — leak out and run on their misses.")
if pct('dreb_pct') >= 60:
    plan.append("<b>Win on the offensive glass.</b> ... (only if they're weak here)") if False else None
plan = [p for p in plan if p][:5] or ["Play sound, balanced basketball — no single dimension is exploitable enough to scheme around."]

# ── Richer inputs (personnel, Synergy, splits) — gated to data availability ──
import csv
RICH = True
try:
    TS = f'{BASE}/2025-26 Team Statistics'
    tdir = next((f'{TS}/{c}/{TEAM}' for c in os.listdir(TS)
                 if os.path.isdir(f'{TS}/{c}/{TEAM}')), None)
    plyr_stats = jload(f'{tdir}/player_stats.json')
    adv_full = jload(f'{tdir}/advanced_analytics.json')
    plyr_adv = {p['name']: p for p in adv_full.get('players', [])}
    game_log = adv_full['team'].get('game_ratings', [])
    pos_map = {}
    pcsv = f'{BASE}/internal_data/player_positions_2025_26.csv'
    if os.path.exists(pcsv):
        for row in csv.DictReader(open(pcsv)):
            if row.get('team') == TEAM: pos_map[row['name']] = row['pos_class']
    syn_path = f'{BASE}/internal_data/synergy_team_{TEAM.lower().replace(" ", "_")}_2025_26.json'
    synergy_team = jload(syn_path) if os.path.exists(syn_path) else None
    _arch_path = f'{BASE}/internal_data/synergy_archetypes.json'
    synergy_arch = ({r['name']: r for r in jload(_arch_path) if r.get('team') == TEAM}
                    if os.path.exists(_arch_path) else {})
    wab_data = jload(f'{BASE}/wab_results.json')
    net_by_team = {t['team']: t.get('net', t.get('net_rtg', 0)) for t in wab_data}
except Exception:
    RICH = False; plyr_stats = synergy_team = game_log = None; synergy_arch = {}

def kenpom_role(usage_pct, mpg):
    if mpg / 40.0 * 100 < 10.0: return 'Benchwarmer'
    for thr, lab in [(28, 'Go-to Guy'), (24, 'Major Contributor'), (20, 'Significant Contributor'),
                     (16, 'Role Player'), (12, 'Limited Role')]:
        if usage_pct >= thr: return lab
    return 'Nearly Invisible'

_BIG = {'S-PF', 'PF/C', 'C'}
def box_archetype(pos, adv, tot):
    usg = adv.get('usage_pct', 0) or 0; ast = adv.get('ast_rate', 0) or 0
    oreb = adv.get('oreb_pct', 0) or 0; fga = tot.get('FGA', 0) or 0
    if usg <= 0 or fga <= 0: return '—'
    tpar = tot.get('3PA', 0) / fga * 100; ftr = tot.get('FTA', 0) / fga * 100
    if pos in _BIG:
        if tpar >= 20: return 'Stretch Big'
        if usg >= 26 and oreb >= 10: return 'Post Scorer'
        if oreb >= 10 or usg < 22: return 'Roll & Cut / Rim Big'
        return 'Versatile Big'
    if ast >= 22 and usg >= 24: return 'Primary Creator'
    if usg >= 24 and ast < 14: return 'Shot Creator'
    if tpar >= 50 and usg < 24: return 'Off-Ball Shooter'
    if tpar >= 60: return 'Off-Ball Shooter'
    if ftr >= 40 and tpar < 30: return 'Slasher / Finisher'
    if ast >= 16: return 'Secondary Handler'
    return 'Role / Connector'

# ── bball-index-style archetype (needs Synergy play-type + shot-type data) ────
# Adapts the Basketball Index offensive-archetype taxonomy to what Synergy gives
# us: play-type mix (parsed from scoring_summary) + structured shot-type profile.
# Returns a refined label only for Synergy-profiled players, else None.
_PT_PATS = [('spotup', r'spot ?up|spots up'), ('pnr_bh', r'p&?r bh|pick.?and.?roll bh|p&?r ball'),
            ('roll', r'roll man|p&?r man'), ('postup', r'post.?up'), ('iso', r'isolation|iso\b'),
            ('transition', r'transition'), ('offscreen', r'off.?screen'),
            ('handoff', r'hand.?off|dho'), ('cut', r'\bcut'), ('putback', r'put.?back|off(?:ensive)? reb')]
def parse_playtypes(summary):
    s = (summary or '').lower(); out = {}
    for k, pat in _PT_PATS:
        m = re.search('(?:' + pat + r')[^0-9]{0,18}?(\d+)\s*%', s)
        if m and m.group(1): out[k] = int(m.group(1))
    return out

def bball_index_archetype(pos, adv, tot, sa):
    if not sa: return None
    st = sa.get('shot_types') or {}; pt = parse_playtypes(sa.get('scoring_summary'))
    usg = adv.get('usage_pct', 0) or 0; ast = adv.get('ast_rate', 0) or 0
    fga = tot.get('FGA', 0) or 0
    ftr = (tot.get('FTA', 0) / fga * 100) if fga else 0
    tpar = (tot.get('3PA', 0) / fga * 100) if fga else 0
    rim = st.get('at_rim_pct_fga', 0) or 0
    js = st.get('jump_shot_pct_fga', 0) or 0
    cs = st.get('catch_shoot_pct_of_js', 0) or 0       # share of jumpers that are catch-and-shoot
    pullup = 100 - cs                                   # proxy for on-ball/self-created jumpers
    move = pt.get('offscreen', 0) + pt.get('handoff', 0)
    if pos in _BIG:
        if tpar >= 20: return 'Stretch Big'
        if pt.get('postup', 0) >= 15 or usg >= 24: return 'Post-Up Big'
        if rim >= 45 or pt.get('cut', 0) + pt.get('roll', 0) + pt.get('putback', 0) >= 18:
            return 'Roll + Cut Big'
        return 'Versatile Big'
    # perimeter
    creator = pt.get('pnr_bh', 0) + pt.get('iso', 0)        # on-ball shot-creation play-types
    if ast >= 22 and (creator >= 6 or usg >= 18):           # pass-first on-ball role
        return 'Primary Ball Handler' if usg >= 22 else 'Secondary Ball Handler'
    if (usg >= 23 and (creator >= 14 or pullup >= 45)) or creator >= 22:
        return 'Primary Ball Handler' if ast >= 18 else 'Shot Creator'
    if js >= 50 and cs >= 50 and rim < 32:                  # jump-shot, mostly catch-and-shoot
        if move >= 10: return 'Movement Shooter'            # runs off screens / hand-offs
        if pt.get('spotup', 0) >= 30: return 'Stationary Shooter'
        return 'Off-Ball Shooter'
    if rim >= 30 or ftr >= 28 or pt.get('iso', 0) >= 10:    # gets downhill / draws fouls
        return 'Slasher' if (ftr >= 25 or pt.get('iso', 0) >= 8) else 'Athletic Finisher'
    if ast >= 15 and creator >= 8: return 'Secondary Ball Handler'
    if cs >= 48 and js >= 45: return 'Off-Ball Shooter'     # softer catch for spot-up types
    return 'Connector / Role'

# ── PDF ──────────────────────────────────────────────────────────────────────
def S(sz, bold=False, color=DARK, align=TA_LEFT, sa=4, lead=None):
    return ParagraphStyle('s', fontName='Helvetica-Bold' if bold else 'Helvetica',
                          fontSize=sz, textColor=color, alignment=align, spaceAfter=sa, leading=lead or sz + 4)
def sec(title, color=BLUE):
    return Paragraph(title.upper(), S(13, True, color, TA_LEFT, 5))

nr, ntot, navg, npct = rank('net_rtg')
doc = SimpleDocTemplate(f'{BASE}/{TEAM}_Scouting_Report_Keys.pdf', pagesize=letter,
                        topMargin=0.5*inch, bottomMargin=0.5*inch, leftMargin=0.6*inch, rightMargin=0.6*inch)
E = []
E.append(Paragraph(f'{TEAM.upper()} — 2025-26 SCOUTING REPORT', S(20, True, BLUE, TA_CENTER, 2)))
E.append(Paragraph('What Matters &nbsp;·&nbsp; decision-first', S(10.5, False, GOLD, TA_CENTER, 6)))
E.append(Paragraph(f"<b>{identity}</b> &nbsp; Net Rating {ME['net_rtg']:+.1f} ranks #{nr}/{N} statewide "
                   f"(offense {off_p}th pctile, defense {def_p}th pctile).",
                   S(10.5, False, DARK, TA_CENTER, 9)))

# Headline stat strip
_glh = [g for g in (game_log or []) if g.get('in_system')] if RICH else []
def _rec(gs):
    w = sum(1 for g in gs if g['result'] == 'W'); return f"{w}-{len(gs)-w}"
_ov = _rec(_glh) if _glh else '—'
_cf = _rec([g for g in _glh if g.get('is_conference')]) if _glh else '—'
_bigs = [_ov, _cf, f'#{nr}/{N}', f"{ME['net_rtg']:+.1f}", f"{ME['drtg']:.1f}", f"{ME['ortg']:.1f}"]
_labs = ['Overall', 'Conference', 'Net Rank', 'Net Rating', f"Def Rtg #{rank('drtg')[0]}", f"Off Rtg #{rank('ortg')[0]}"]
strip = Table([[Paragraph(f'<b>{b}</b>', S(15, True, BLUE, TA_CENTER, 0)) for b in _bigs],
               [Paragraph(l, S(7.5, False, MID, TA_CENTER, 0)) for l in _labs]],
              colWidths=[1.18 * inch] * 6)
strip.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, -1), LGRAY), ('BACKGROUND', (2, 0), (2, 1), ALT),
    ('BACKGROUND', (3, 0), (3, 1), GREEN_BG), ('TEXTCOLOR', (3, 0), (3, 0), GREEN),
    ('GRID', (0, 0), (-1, -1), 0.5, MGRAY), ('BOX', (0, 0), (-1, -1), 1.2, BLUE),
    ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ('TOPPADDING', (0, 0), (-1, 0), 6), ('BOTTOMPADDING', (0, 0), (-1, 0), 1),
    ('TOPPADDING', (0, 1), (-1, 1), 0), ('BOTTOMPADDING', (0, 1), (-1, 1), 5)]))
E.append(strip)
E.append(Spacer(1, 10))
E.append(HRFlowable(width='100%', color=MGRAY, spaceAfter=9))

# What makes them win
E.append(sec('What Makes Them Win', GREEN))
for t in strength_themes[:4]:
    E.append(Paragraph(f"<b>▲ {t['name']} — {t['pct']}th percentile.</b> "
                       f"Anchored by {cite(t['best'])}; {cite(t['worst'])}.",
                       S(10, False, DARK, TA_JUSTIFY, 5, 14)))
if not strength_themes:
    E.append(Paragraph("No standout pillar — their value is balance, not dominance in any one area.", S(10, False, MID)))
E.append(Spacer(1, 7))

# How to beat them
E.append(sec('How To Beat Them', RED))
for t in weakness_themes[:4]:
    E.append(Paragraph(f"<b>▼ {t['name']} — {t['pct']}th percentile.</b> "
                       f"Exposed by {cite(t['worst'])}.", S(10, False, DARK, TA_JUSTIFY, 4, 14)))
E.append(Spacer(1, 4))
E.append(Paragraph('Game plan:', S(10, True, DARK, TA_LEFT, 3)))
for p in plan:
    E.append(Paragraph('•&nbsp; ' + p, S(9.5, False, DARK, TA_JUSTIFY, 4, 13)))
E.append(Spacer(1, 8))
E.append(HRFlowable(width='100%', color=MGRAY, spaceAfter=8))

# ── Keys to Victory — the statistical win formula (compute_team_keys) ─────────
if KEYS and KEYS.get('keys'):
    rec = KEYS.get('record', (0, 0))
    E.append(sec('Keys to Victory — What They Need to Win', BLUE))
    E.append(Paragraph(
        f"From {KEYS['n_games']} games over 2021-26 ({rec[0]}-{rec[1]}): the metrics that most "
        f"separate this team's <b>wins from losses</b> (point-biserial r). Each key has the target "
        f"that best splits W/L, and the team's average when winning vs losing.",
        S(9, False, MID, sa=5, lead=12)))
    arrow = {'>=': '≥', '<=': '≤'}
    kd = [['Key Metric', 'Target', 'In Wins', 'In Losses', 'r']]
    kcol = [None]
    for k in KEYS['keys']:
        kd.append([k.metric, f"{arrow.get(k.direction, k.direction)} {k.target:g}",
                   f"{k.avg_win:g}", f"{k.avg_loss:g}", f"{k.r:+.2f}"])
        kcol.append(GREEN if abs(k.r) >= 0.35 else MID)
    kt = Table(kd, colWidths=[2.3*inch, 1.15*inch, 1.0*inch, 1.0*inch, 0.7*inch])
    ksty = [('BACKGROUND',(0,0),(-1,0),BLUE),('TEXTCOLOR',(0,0),(-1,0),WHITE),
            ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8.5),
            ('ALIGN',(1,0),(-1,-1),'CENTER'),('ALIGN',(0,1),(0,-1),'LEFT'),
            ('GRID',(0,0),(-1,-1),0.4,MGRAY),('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,LGRAY]),
            ('TOPPADDING',(0,0),(-1,-1),2.5),('BOTTOMPADDING',(0,0),(-1,-1),2.5)]
    for i, c in enumerate(kcol):
        if c: ksty.append(('TEXTCOLOR',(0,i),(0,i),c)); ksty.append(('FONTNAME',(0,i),(0,i),'Helvetica-Bold'))
    kt.setStyle(TableStyle(ksty)); E.append(kt)
    # Targets-hit table: how often they win by # of keys hit
    tt = KEYS['targets_table']; nk = len(KEYS['keys'])
    E.append(Spacer(1, 5))
    E.append(Paragraph(f'<b>The payoff —</b> their record by how many of the {nk} keys they hit in a game:',
                       S(9, False, DARK, sa=3, lead=12)))
    hd = [['Keys Hit', 'Games', 'Record', 'Win %', 'Avg Margin']]; hcol = [None]
    for i in range(nk, -1, -1):
        row = tt.get(i, {})
        if row.get('games'):
            wp = row.get('win_pct')
            hd.append([f"{i} of {nk}", str(row['games']), f"{row['w']}-{row['l']}",
                       f"{wp}%" if wp is not None else '—',
                       f"{row['avg_mov']:+.1f}" if row.get('avg_mov') is not None else '—'])
            hcol.append(GREEN if (wp or 0) >= 60 else RED if (wp or 0) <= 40 else MID)
    ht = Table(hd, colWidths=[1.0*inch, 0.9*inch, 1.1*inch, 0.9*inch, 1.1*inch])
    hsty = [('BACKGROUND',(0,0),(-1,0),DARK),('TEXTCOLOR',(0,0),(-1,0),WHITE),
            ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8.5),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),('GRID',(0,0),(-1,-1),0.4,MGRAY),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,LGRAY]),
            ('TOPPADDING',(0,0),(-1,-1),2.5),('BOTTOMPADDING',(0,0),(-1,-1),2.5)]
    for i, c in enumerate(hcol):
        if c: hsty.append(('TEXTCOLOR',(3,i),(3,i),c)); hsty.append(('FONTNAME',(3,i),(3,i),'Helvetica-Bold'))
    ht.setStyle(TableStyle(hsty)); E.append(ht)
    E.append(Spacer(1, 8))
    E.append(HRFlowable(width='100%', color=MGRAY, spaceAfter=8))

# Key numbers — the four factors both sides + style (the predictive core only)
E.append(sec('The Numbers That Matter', BLUE))
def mrow(k):
    r, tot, avg, p = rank(k); u = '' if k in ('net_rtg','ortg','drtg','tempo','ast_tov','ft_rate','bench_per100') else '%'
    col = GREEN if p >= 60 else RED if p <= 40 else MID
    return [LAB[k], f'{ME[k]}{u}', f'#{r}/{tot}', f'{avg}{u}', col]
core = [
    ('— Efficiency —', None),
    ('net_rtg', 1), ('ortg', 1), ('drtg', 1),
    ('— Four Factors: Offense —', None),
    ('efg_pct', 1), ('tov_pct', 1), ('oreb_pct', 1), ('ft_rate', 1),
    ('— Four Factors: Defense —', None),
    ('opp_efg_pct', 1), ('opp_tov_pct', 1), ('dreb_pct', 1), ('opp_ft_rate', 1),
    ('— Style & Flaws —', None),
    ('tempo', 1), ('tpa_rate', 1), ('nst_pct', 1), ('ast_tov', 1),
]
if HAS_BENCH:
    core += [('— Bench & Depth —', None), ('bench_pct', 1), ('bench_per100', 1)]
data = [['Metric', 'Value', 'Rank', 'State Avg', '']]
colors_col = [None]
for k, flag in core:
    if flag is None:
        data.append([k, '', '', '', '']); colors_col.append('hdr'); continue
    rr = mrow(k); data.append(rr[:4] + ['']); colors_col.append(rr[4])
tbl = Table(data, colWidths=[2.2*inch, 1.1*inch, 1.1*inch, 1.2*inch, 0.2*inch])
sty = [('BACKGROUND',(0,0),(-1,0),BLUE),('TEXTCOLOR',(0,0),(-1,0),WHITE),
       ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8.5),
       ('ALIGN',(1,0),(-1,-1),'CENTER'),('GRID',(0,0),(-1,-1),0.4,MGRAY),
       ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]
for i, c in enumerate(colors_col):
    if c == 'hdr':
        sty += [('BACKGROUND',(0,i),(-1,i),LGRAY),('FONTNAME',(0,i),(-1,i),'Helvetica-BoldOblique'),
                ('TEXTCOLOR',(0,i),(-1,i),MID),('SPAN',(0,i),(-1,i))]
    elif c is not None:
        sty.append(('TEXTCOLOR',(2,i),(2,i),c))
tbl.setStyle(TableStyle(sty))
E.append(tbl)
E.append(Spacer(1, 6))

def simple_table(data, widths, hdr=BLUE, fs=8.5, lalign_col0=True):
    t = Table(data, colWidths=widths)
    st = [('BACKGROUND',(0,0),(-1,0),hdr),('TEXTCOLOR',(0,0),(-1,0),WHITE),
          ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),fs),
          ('ALIGN',(1,0),(-1,-1),'CENTER'),('GRID',(0,0),(-1,-1),0.4,MGRAY),
          ('TOPPADDING',(0,0),(-1,-1),2.5),('BOTTOMPADDING',(0,0),(-1,-1),2.5),
          ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,LGRAY])]
    if lalign_col0: st.append(('ALIGN',(0,1),(0,-1),'LEFT'))
    t.setStyle(TableStyle(st)); return t

# ── Personnel — rotation, roles, archetypes ──────────────────────────────────
if RICH and plyr_stats:
    E.append(PageBreak())
    E.append(sec('Personnel — Rotation, Roles & Archetypes', BLUE))
    pm = {p['name']: {'avg': p['averages'], 'tot': p['totals'],
                      'adv': plyr_adv.get(p['name'], {}), 'pos': pos_map.get(p['name'], '—')}
          for p in plyr_stats['players']}
    rot = [n for n in sorted(pm, key=lambda n: -pm[n]['avg'].get('MIN', 0))
           if pm[n]['avg'].get('MIN', 0) >= 8][:9]
    # Three levels of role: box POSITION (Pos) · SYNERGY label · BBALL-INDEX archetype
    cellP = lambda t, c=DARK, b=False: Paragraph(t, S(7.5, b, c, TA_LEFT, 0, 9))
    data = [['Player', 'Pos', 'Synergy / Box', 'B-Index Archetype', 'MIN', 'PTS', 'AST', '3P%', 'USG']]
    notes = []             # (name, scouting_note) for Synergy players
    for n in rot:
        d = pm[n]; a = d['avg']; adv = d['adv']; sa = synergy_arch.get(n)
        if sa:
            syn_lab = sa.get('short') or sa.get('archetype') or '—'
            note = (sa.get('shot_types') or {}).get('scouting_note') or sa.get('scoring_summary')
            if note: notes.append((n, note))
        else:
            syn_lab = box_archetype(d['pos'], adv, d['tot'])
        bi = bball_index_archetype(d['pos'], adv, d['tot'], sa)
        data.append([n, d['pos'],
                     cellP(syn_lab, GREEN if sa else DARK, bool(sa)),
                     cellP(bi or '—', BLUE if bi else MID, bool(bi)),
                     f"{a.get('MIN',0):.0f}", f"{a.get('PTS',0):.1f}",
                     f"{a.get('AST',0):.1f}", f"{a.get('3P%',0):.0f}", f"{(adv.get('usage_pct',0) or 0):.0f}"])
    ptbl = Table(data, colWidths=[1.35*inch,0.4*inch,1.2*inch,1.25*inch,0.4*inch,0.4*inch,0.4*inch,0.45*inch,0.4*inch])
    ptbl.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),BLUE),('TEXTCOLOR',(0,0),(-1,0),WHITE),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7.8),
        ('ALIGN',(1,0),(1,-1),'CENTER'),('ALIGN',(4,0),(-1,-1),'CENTER'),('ALIGN',(0,1),(0,-1),'LEFT'),
        ('GRID',(0,0),(-1,-1),0.4,MGRAY),('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,LGRAY]),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),2.5),('BOTTOMPADDING',(0,0),(-1,-1),2.5)]))
    E.append(ptbl)
    E.append(Paragraph('<font color="#1a5c30"><b>Green</b></font> = Synergy-profiled label · '
                       '<font color="#003087"><b>Blue B-Index</b></font> = bball-index-style archetype from Synergy '
                       'play-types + shot profile (— where no Synergy data) · others box-derived.',
                       S(7.5, False, MID, sa=4)))
    if notes:
        E.append(Spacer(1, 4))
        E.append(Paragraph('Synergy scouting notes:', S(9.5, True, DARK, sa=3)))
        for name, note in notes:
            E.append(Paragraph(f'<b>{name}:</b> {note}', S(8.5, False, DARK, TA_JUSTIFY, 4, 12)))
    E.append(Spacer(1, 9))

# ── Synergy play-types ───────────────────────────────────────────────────────
if RICH and synergy_team:
    E.append(sec('Synergy Play-Type Profile', BLUE))
    def play_tbl(pts):
        top = sorted(pts, key=lambda x: -x['poss'])[:8]
        data = [['Play Type', '%Time', 'PPP', 'Pctile', 'Rating', '2FG%', 'TO%']]
        for pt in top:
            data.append([pt['play_type'].replace('Offensive Rebounds (Put Backs)', 'OREB / Put Backs'),
                         f"{pt['pct_time']:.0f}%", f"{pt['ppp']:.2f}", str(pt['ppp_rank']),
                         pt.get('ppp_rating', ''), f"{(pt.get('two_fg_pct') or 0):.0f}%", f"{pt['to_pct']:.0f}%"])
        return simple_table(data, [2.0*inch,0.7*inch,0.7*inch,0.7*inch,1.1*inch,0.7*inch,0.6*inch], fs=8)
    E.append(Paragraph('Offense — how they create (higher PPP pctile = better)', S(9, True, GREEN, sa=3)))
    E.append(play_tbl(synergy_team['offense']['play_types']))
    E.append(Spacer(1, 6))
    E.append(Paragraph('Defense — how opponents score vs them (higher pctile = better defense)', S(9, True, RED, sa=3)))
    E.append(play_tbl(synergy_team['defense']['play_types']))
    E.append(Spacer(1, 9))

# ── Splits & schedule ────────────────────────────────────────────────────────
if RICH and game_log:
    E.append(sec('Splits & Schedule Context', BLUE))
    gl = [g for g in game_log if g.get('in_system')]
    def rec(gs):
        w = sum(1 for g in gs if g['result'] == 'W'); return f"{w}-{len(gs)-w}"
    def mar(gs): return round(sum(g['team_score'] - g['opponent_score'] for g in gs) / len(gs), 1) if gs else 0
    def onet(g): return net_by_team.get(g.get('canonical_opponent', g['opponent']), 0)
    splits = [
        ('Overall', gl), ('Home', [g for g in gl if g.get('location') == 'Home']),
        ('Away', [g for g in gl if g.get('location') == 'Away']),
        ('Neutral', [g for g in gl if g.get('location') == 'Neutral']),
        ('Conference', [g for g in gl if g.get('is_conference')]),
        ('Non-Conference', [g for g in gl if not g.get('is_conference')]),
        ('vs Quality (opp Net > 0)', [g for g in gl if onet(g) > 0]),
        ('vs Weak (opp Net ≤ 0)', [g for g in gl if onet(g) <= 0]),
        ('Close (≤ 8 pts)', [g for g in gl if abs(g['team_score'] - g['opponent_score']) <= 8]),
    ]
    data = [['Split', 'Record', 'Avg Margin']]; mcol = [None]
    for name, gs in splits:
        if gs:
            m = mar(gs); data.append([name, rec(gs), f"{m:+.1f}"])
            mcol.append(GREEN if m > 0 else RED if m < 0 else MID)
    st = Table(data, colWidths=[2.6*inch, 1.4*inch, 1.4*inch])
    sty = [('BACKGROUND',(0,0),(-1,0),BLUE),('TEXTCOLOR',(0,0),(-1,0),WHITE),
           ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8.5),
           ('ALIGN',(1,0),(-1,-1),'CENTER'),('ALIGN',(0,1),(0,-1),'LEFT'),
           ('GRID',(0,0),(-1,-1),0.4,MGRAY),('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,LGRAY]),
           ('TOPPADDING',(0,0),(-1,-1),2.5),('BOTTOMPADDING',(0,0),(-1,-1),2.5)]
    for i, c in enumerate(mcol):
        if c: sty.append(('TEXTCOLOR',(2,i),(2,i),c)); sty.append(('FONTNAME',(2,i),(2,i),'Helvetica-Bold'))
    st.setStyle(TableStyle(sty)); E.append(st)
    # Quad records
    ranked = sorted(net_by_team, key=lambda t: -net_by_team[t])
    netrank = {t: i + 1 for i, t in enumerate(ranked)}; _N = max(len(ranked), 1)
    def quad(r, loc):
        for q, m in [('Q1A', {'Home': 15, 'Neutral': 25, 'Away': 40}),
                     ('Q1', {'Home': 30, 'Neutral': 50, 'Away': 75}),
                     ('Q2', {'Home': 75, 'Neutral': 100, 'Away': 135}),
                     ('Q3', {'Home': 160, 'Neutral': 200, 'Away': 240})]:
            if r <= _N * m.get(loc, m['Neutral']) / 353: return q
        return 'Q4'
    qrec = {q: [0, 0] for q in ['Q1A', 'Q1', 'Q2', 'Q3', 'Q4']}
    for g in gl:
        r = netrank.get(g.get('canonical_opponent', g['opponent']))
        if not r: continue
        qrec[quad(r, g.get('location', 'Neutral'))][0 if g['result'] == 'W' else 1] += 1
    E.append(Spacer(1, 5))
    qdata = [['Quadrant'] + ['Q1A', 'Q1', 'Q2', 'Q3', 'Q4'],
             ['Record'] + [f"{qrec[q][0]}-{qrec[q][1]}" for q in ['Q1A', 'Q1', 'Q2', 'Q3', 'Q4']]]
    E.append(simple_table(qdata, [1.3*inch] + [1.0*inch]*5, lalign_col0=True))
    E.append(Spacer(1, 9))

# Bottom line
E.append(sec('Bottom Line', DARK))
bl = (f"{TEAM} is a <b>{identity.lower().rstrip('.')}</b> profile that wins on "
      f"<b>{(strength_themes[0]['name'].lower() if strength_themes else 'balance')}</b>"
      + (f" and {strength_themes[1]['name'].lower()}" if len(strength_themes) > 1 else "")
      + f". They are most vulnerable to <b>{(weakness_themes[0]['name'].lower() if weakness_themes else 'few clear weaknesses')}</b>"
      + (f" and {weakness_themes[1]['name'].lower()}" if len(weakness_themes) > 1 else "")
      + f". Beat them by controlling tempo and forcing them into the half court, where their "
      f"{'jump-shooting, line-averse offense' if pct('ft_rate') <= 40 else 'offense'} has limited counters.")
E.append(Paragraph(bl, S(10, False, DARK, TA_JUSTIFY, 4, 14)))

def _footer(canvas, d):
    canvas.saveState()
    canvas.setFont('Helvetica', 7); canvas.setFillColor(MID)
    canvas.drawString(0.6 * inch, 0.3 * inch,
                      f'{TEAM} 2025-26 — auto-generated scouting report (keys engine)')
    canvas.drawRightString(letter[0] - 0.6 * inch, 0.3 * inch, f'Page {d.page}')
    canvas.restoreState()
doc.build(E, onFirstPage=_footer, onLaterPages=_footer)
print(f"Identity: {identity}")
print(f"Strength themes: {[(t['name'], t['pct']) for t in strength_themes]}")
print(f"Weakness themes: {[(t['name'], t['pct']) for t in weakness_themes]}")
print(f"Game plan bullets: {len(plan)}")
print(f"Wrote {BASE}/{TEAM}_Scouting_Report_Keys.pdf")
