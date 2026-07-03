"""
Moorpark College 2025-26 — Scouting Report PROTOTYPE
Auto strengths/weaknesses engine: ranks the team across the FULL team-metric
universe (the same ~chart metrics — efficiency, four factors BOTH sides, shooting
splits, rate stats, ratios, per-100 box, NST%, schedule strength) statewide, then
writes the strengths/weaknesses narrative directly from those ranks.

Original generator is preserved as generate_moorpark_scouting_report.backup.py.
Run: /usr/local/bin/python3 generate_moorpark_scouting_report_prototype.py
"""
import json, os
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable, KeepTogether)

BLUE=colors.HexColor('#003087'); GOLD=colors.HexColor('#C4922A')
DARK=colors.HexColor('#1a1a2e'); MID=colors.HexColor('#555577')
LGRAY=colors.HexColor('#f2f3f7'); MGRAY=colors.HexColor('#dde0ea')
GREEN_BG=colors.HexColor('#d4edda'); RED_BG=colors.HexColor('#f8d7da')
YELLOW_BG=colors.HexColor('#fff3cd'); GREEN_TXT=colors.HexColor('#1a5c30')
RED_TXT=colors.HexColor('#7b1b1b'); WHITE=colors.white
BASE='/Users/chadoconnor/Neural Network'
TEAM='Moorpark'

def jload(p): return json.load(open(p))

# ── Unified team-metric builder (the full applicable chart universe) ──────────
def build_metrics(a, s):
    av, op = s['averages'], s['opponent_averages']
    poss = max(a.get('possessions', 0.01), 0.01)          # per-game possessions
    def twop(d):
        fa = d['FGA'] - d['3PA']; fm = d['FGM'] - d['3PM']
        return round(fm / fa * 100, 1) if fa > 0 else 0.0
    r = lambda x: round(x, 1)
    return {
        # efficiency
        'ortg': a.get('ortg', 0), 'drtg': a.get('drtg', 0), 'net_rtg': a.get('net_rtg', 0),
        'tempo': r(poss),
        # offense shooting
        'efg_pct': a.get('efg_pct', 0), 'ts_pct': a.get('ts_pct', 0),
        'fg_pct': av['FG%'], 'twop': twop(av), 'tp_pct': av['3P%'], 'ft_pct': av['FT%'],
        'tpa_rate': r(av['3PA'] / av['FGA'] * 100) if av['FGA'] else 0,
        # offense four factors / rates
        'tov_pct': a.get('tov_pct', 0),
        'nst_pct': r(max(av['TO'] - op['STL'], 0) / poss * 100),
        'oreb_pct': a.get('oreb_pct', 0), 'ft_rate': a.get('ft_rate', 0),
        'ast_pct': a.get('ast_rate', 0), 'ast_tov': r(av['AST'] / av['TO']) if av['TO'] else 0,
        # defense shooting (opp)
        'opp_efg_pct': a.get('opp_efg_pct', 0), 'opp_ts_pct': a.get('opp_ts_pct', 0),
        'opp_fg_pct': op['FG%'], 'opp_twop': twop(op), 'opp_tp_pct': op['3P%'], 'opp_ft_pct': op['FT%'],
        # defense four factors / rates
        'opp_tov_pct': a.get('opp_tov_pct', 0),
        'opp_nst_pct': r(max(op['TO'] - av['STL'], 0) / poss * 100),
        'dreb_pct': a.get('dreb_pct', 0), 'opp_oreb_pct': r(100 - a.get('dreb_pct', 0)),
        'opp_ft_rate': a.get('opp_ft_rate', 0),
        'stl_pct': a.get('stl_pct', 0), 'blk_pct': a.get('blk_pct', 0),
        'stl_to': r(av['STL'] / op['TO']) if op['TO'] else 0,
        # per-100 box
        'pts100': r(av['PTS'] / poss * 100), 'reb100': r(av['REB'] / poss * 100),
        'ast100': r(av['AST'] / poss * 100), 'stl100': r(av['STL'] / poss * 100),
        'blk100': r(av['BLK'] / poss * 100), 'tov100': r(av['TO'] / poss * 100),
        'oreb100': r(av['OREB'] / poss * 100), 'dreb100': r(av['DREB'] / poss * 100),
        # differentials
        'pts_diff': r(av['PTS'] - op['PTS']), 'reb_diff': r(av['REB'] - op['REB']),
        'ast_diff': r(av['AST'] - op['AST']), 'tov_diff': r(av['TO'] - op['TO']),
        # schedule / context
        'sos': a.get('sos', 0), 'ncsos': a.get('ncsos', 0),
        'opp_adjust': a.get('opp_adjust', 0), 'pace_adjust': a.get('pace_adjust', 0),
    }

# metric metadata: key -> (label, category, direction, unit)
#   direction: 'H' higher better, 'L' lower better, 'C' context (not graded)
M = [
    ('net_rtg', 'Net Rating', 'Efficiency', 'H', ''),
    ('ortg', 'Offensive Rating', 'Efficiency', 'H', ''),
    ('drtg', 'Defensive Rating', 'Efficiency', 'L', ''),
    ('tempo', 'Tempo (poss/g)', 'Efficiency', 'C', ''),
    ('efg_pct', 'Effective FG%', 'Offense — Shooting', 'H', '%'),
    ('ts_pct', 'True Shooting%', 'Offense — Shooting', 'H', '%'),
    ('fg_pct', 'Field Goal%', 'Offense — Shooting', 'H', '%'),
    ('twop', 'Two-Point%', 'Offense — Shooting', 'H', '%'),
    ('tp_pct', 'Three-Point%', 'Offense — Shooting', 'H', '%'),
    ('ft_pct', 'Free Throw%', 'Offense — Shooting', 'H', '%'),
    ('tpa_rate', 'Three-Point Attempt Rate', 'Offense — Shooting', 'C', '%'),
    ('tov_pct', 'Turnover%', 'Offense — Ball Control', 'L', '%'),
    ('nst_pct', 'Non-Steal Turnover%', 'Offense — Ball Control', 'L', '%'),
    ('ast_pct', 'Assist Rate', 'Offense — Ball Control', 'H', '%'),
    ('ast_tov', 'Assist-to-Turnover', 'Offense — Ball Control', 'H', ''),
    ('oreb_pct', 'Offensive Rebound%', 'Offense — Rebounding', 'H', '%'),
    ('ft_rate', 'Free Throw Rate', 'Offense — Getting to Line', 'H', ''),
    ('opp_efg_pct', 'Opp Effective FG%', 'Defense — Shooting', 'L', '%'),
    ('opp_ts_pct', 'Opp True Shooting%', 'Defense — Shooting', 'L', '%'),
    ('opp_fg_pct', 'Opp Field Goal%', 'Defense — Shooting', 'L', '%'),
    ('opp_twop', 'Opp Two-Point%', 'Defense — Shooting', 'L', '%'),
    ('opp_tp_pct', 'Opp Three-Point%', 'Defense — Shooting', 'L', '%'),
    ('opp_tov_pct', 'Opp Turnover% (forced)', 'Defense — Disruption', 'H', '%'),
    ('opp_nst_pct', 'Opp Non-Steal Turnover%', 'Defense — Disruption', 'H', '%'),
    ('stl_pct', 'Steal%', 'Defense — Disruption', 'H', '%'),
    ('blk_pct', 'Block%', 'Defense — Disruption', 'H', '%'),
    ('stl_to', 'Steals-to-Opp-TO', 'Defense — Disruption', 'H', ''),
    ('dreb_pct', 'Defensive Rebound%', 'Defense — Rebounding', 'H', '%'),
    ('opp_ft_rate', 'Opp Free Throw Rate', 'Defense — Fouling', 'L', ''),
    ('pts_diff', 'Scoring Margin', 'Box — Differentials', 'H', ''),
    ('reb_diff', 'Rebound Margin', 'Box — Differentials', 'H', ''),
    ('ast_diff', 'Assist Margin', 'Box — Differentials', 'H', ''),
    ('pts100', 'Points / 100', 'Box — Per 100', 'H', ''),
    ('ast100', 'Assists / 100', 'Box — Per 100', 'H', ''),
    ('stl100', 'Steals / 100', 'Box — Per 100', 'H', ''),
    ('blk100', 'Blocks / 100', 'Box — Per 100', 'H', ''),
    ('tov100', 'Turnovers / 100', 'Box — Per 100', 'L', ''),
    ('sos', 'Strength of Schedule', 'Context', 'C', ''),
    ('ncsos', 'Non-Conf SOS', 'Context', 'C', ''),
]
META = {k: (lab, cat, d, u) for k, lab, cat, d, u in M}

# ── Load Moorpark + statewide pool ───────────────────────────────────────────
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

ALL = load_all()
ME = ALL[TEAM]
N = len(ALL)

def rank(key):
    """Return (rank, n, avg, pctile). Rank 1 = best given the metric's direction."""
    d = META[key][2]
    hb = d != 'L'   # 'H'/'C' rank high-first; 'L' rank low-first
    vals = [v[key] for v in ALL.values() if isinstance(v.get(key), (int, float))]
    val = ME[key]
    ordered = sorted(vals, reverse=hb)
    r = next((i + 1 for i, v in enumerate(ordered)
              if (hb and v <= val) or (not hb and v >= val)), len(ordered))
    avg = round(sum(vals) / len(vals), 1)
    pct = round((1 - (r - 1) / max(len(ordered) - 1, 1)) * 100)   # 100 = best
    return r, len(ordered), avg, pct

def tier(pct):
    if pct >= 95: return 'elite', GREEN_TXT
    if pct >= 80: return 'excellent', GREEN_TXT
    if pct >= 60: return 'above average', GREEN_TXT
    if pct >= 40: return 'average', MID
    if pct >= 20: return 'below average', RED_TXT
    if pct >= 5:  return 'poor', RED_TXT
    return 'among the worst', RED_TXT

# ── Auto strengths / weaknesses (graded metrics only) ────────────────────────
graded = [k for k, (lab, cat, d, u) in META.items() if d in ('H', 'L')]
scored = []
for k in graded:
    r, tot, avg, pct = rank(k)
    scored.append({'key': k, 'rank': r, 'n': tot, 'avg': avg, 'pct': pct,
                   'val': ME[k], 'label': META[k][0], 'cat': META[k][1],
                   'dir': META[k][2], 'unit': META[k][3]})
strengths = sorted([m for m in scored if m['pct'] >= 70], key=lambda m: -m['pct'])[:8]
weaknesses = sorted([m for m in scored if m['pct'] <= 30], key=lambda m: m['pct'])[:8]

# ── Narrative sentence per metric (auto, category-aware) ─────────────────────
CLAUSE = {
    'Offense — Shooting': ('shoot the ball', 'put it in the basket'),
    'Offense — Ball Control': ('take care of the ball', 'protect possessions'),
    'Offense — Rebounding': ('crash the offensive glass', 'create second chances'),
    'Offense — Getting to Line': ('get to the foul line', 'draw fouls'),
    'Defense — Shooting': ('contest shots', 'defend the field'),
    'Defense — Disruption': ('force turnovers and disrupt', 'generate live-ball chaos'),
    'Defense — Rebounding': ('secure the defensive glass', 'end possessions with a rebound'),
    'Defense — Fouling': ('stay out of foul trouble', 'avoid sending opponents to the line'),
    'Efficiency': ('score and prevent points per possession', 'win the per-possession battle'),
    'Box — Differentials': ('out-produce opponents', 'win the box-score battle'),
    'Box — Per 100': ('generate volume per possession', 'produce at pace'),
}
def sentence(m):
    t, _ = tier(m['pct'])
    verb, _alt = CLAUSE.get(m['cat'], ('perform', 'execute'))
    diff = round(m['val'] - m['avg'], 1)
    sign = '+' if diff > 0 else ''
    u = m['unit']
    return (f"<b>{m['label']}: {m['val']}{u}</b> — #{m['rank']}/{m['n']} statewide "
            f"({t}, {sign}{diff} vs state avg {m['avg']}{u}). They {verb} at a {t} level.")

# ── PDF ──────────────────────────────────────────────────────────────────────
def S(sz, bold=False, color=DARK, align=TA_LEFT, sa=4, lead=None):
    return ParagraphStyle('s', fontName='Helvetica-Bold' if bold else 'Helvetica',
                          fontSize=sz, textColor=color, alignment=align,
                          spaceAfter=sa, leading=lead or sz + 3)

def metric_rows(cat):
    out = []
    for k in [x[0] for x in M if META[x[0]][1] == cat]:
        md = META[k]; val = ME[k]; u = md[3]
        if md[2] == 'C':
            out.append([md[0], f'{val}{u}', '—', '—', 'context', None])
            continue
        r, tot, avg, pct = rank(k); t, col = tier(pct)
        out.append([md[0], f'{val}{u}', f'#{r}/{tot}', f'{avg}{u}', t, col])
    return out

doc = SimpleDocTemplate(f'{BASE.rstrip("/")}/Moorpark_Scouting_Report_Prototype.pdf'.replace(BASE, BASE),
                        pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                        leftMargin=0.55 * inch, rightMargin=0.55 * inch)
E = []
E.append(Paragraph('MOORPARK COLLEGE — 2025-26', S(22, True, BLUE, TA_CENTER, 2)))
E.append(Paragraph('Data-Driven Scouting Report &nbsp;·&nbsp; PROTOTYPE (auto strengths/weaknesses)',
                   S(11, False, GOLD, TA_CENTER, 8)))
nr, _, navg, npct = rank('net_rtg')
E.append(Paragraph(f"Ranked across all {N} CCCAA programs on {len(graded)} graded metrics. "
                   f"Net Rating {ME['net_rtg']:+.1f} ranks #{nr}/{N} statewide.",
                   S(9.5, False, MID, TA_CENTER, 10)))
E.append(HRFlowable(width='100%', color=MGRAY, spaceAfter=10))

def section(title, color=BLUE):
    return Paragraph(title.upper(), S(13, True, color, TA_LEFT, 6))

# strengths
E.append(section('Team Strengths — auto-detected', GREEN_TXT))
for m in strengths:
    E.append(Paragraph('▲ ' + sentence(m), S(9.5, False, DARK, TA_JUSTIFY, 5, 13)))
E.append(Spacer(1, 8))
# weaknesses
E.append(section('Team Weaknesses — auto-detected', RED_TXT))
for m in weaknesses:
    E.append(Paragraph('▼ ' + sentence(m), S(9.5, False, DARK, TA_JUSTIFY, 5, 13)))
E.append(Spacer(1, 10))
E.append(HRFlowable(width='100%', color=MGRAY, spaceAfter=10))

# full profile, grouped by category
E.append(section('Full Metric Profile (vs all CCCAA)', BLUE))
cats = []
for k, lab, cat, d, u in M:
    if cat not in cats: cats.append(cat)
for cat in cats:
    rows = metric_rows(cat)
    data = [['Metric', 'Value', 'Rank', 'State Avg', 'Tier']] + [r[:5] for r in rows]
    tbl = Table(data, colWidths=[2.6 * inch, 1.0 * inch, 1.1 * inch, 1.1 * inch, 1.4 * inch])
    sty = [('BACKGROUND', (0, 0), (-1, 0), BLUE), ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
           ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8),
           ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'), ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
           ('GRID', (0, 0), (-1, -1), 0.4, MGRAY), ('TOPPADDING', (0, 0), (-1, -1), 3),
           ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
           ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, LGRAY])]
    for i, r in enumerate(rows, start=1):
        if r[5] is not None:
            sty.append(('TEXTCOLOR', (4, i), (4, i), r[5]))
    tbl.setStyle(TableStyle(sty))
    E.append(Paragraph(cat, S(10, True, DARK, TA_LEFT, 3)))
    E.append(KeepTogether([tbl]))
    E.append(Spacer(1, 7))

doc.build(E)
print(f"Strengths: {[m['label'] for m in strengths]}")
print(f"Weaknesses: {[m['label'] for m in weaknesses]}")
print(f"Wrote {BASE}/Moorpark_Scouting_Report_Prototype.pdf ({N} teams, {len(graded)} graded metrics)")
