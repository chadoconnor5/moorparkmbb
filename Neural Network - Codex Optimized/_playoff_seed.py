#!/usr/bin/env python3
"""
2025-26 CCC Men's Basketball Playoff Re-seeding Simulation
24 North / 24 South
Composite score using: NET rating, Adjusted Efficiency (ortg-drtg), RPI, NC-RPI,
WAB, EvanMiya Rate, Tier-A record, Tier-B record, SOS
Conference champion tiebreak bonus.
"""
import json, math, re

html = open('wsc_north_leaderboard.html').read()

# ── Load data ────────────────────────────────────────────────────────────────
start = html.find('const TEAM_DATA = ') + 18
end   = html.find('\nconst LEAGUE_AVG', start)
teams = json.loads(html[start:end].rstrip().rstrip(';'))

start = html.find('const RPI_DATA_2526 = ') + 22
end   = html.find('\nconst RPI_DATA_2425', start)
rpi_map = {r['team']: r for r in json.loads(html[start:end].rstrip().rstrip(';'))}

start = html.find('const WAB_SIM_2526 = ') + 21
end   = html.find('\nconst WAB_SIM_2425', start)
wab_obj   = json.loads(html[start:end].rstrip().rstrip(';'))
wab_north = {t['team']: t for t in wab_obj.get('north', [])}
wab_south = {t['team']: t for t in wab_obj.get('south', [])}

start = html.find('const REL_RATINGS = ') + 20
nxt   = html.find('\nconst ', start)
rel_map = {r['team']: r for r in json.loads(html[start:nxt].rstrip().rstrip(';'))}

def parse_rec(s):
    if not s: return 0, 0, 0
    p = s.split('-')
    w = int(p[0]) if p else 0
    l = int(p[1]) if len(p) > 1 else 0
    return w, l, w + l

# ── Build rows ────────────────────────────────────────────────────────────────
rows = []
for t in teams:
    nm     = t['team']
    region = t['region']
    conf   = t['conference']
    w,  l,  gp  = parse_rec(t.get('record', ''))
    cw, cl, cgp = parse_rec(t.get('conf', ''))

    rpi_r = rpi_map.get(nm, {})
    wab_r = (wab_north if region == 'North' else wab_south).get(nm, {})
    rel_r = rel_map.get(nm, {})

    ta = t.get('tier_a_rec', ''); tb = t.get('tier_b_rec', '')
    def tier_pct(s):
        if not s or '-' not in s: return 0.0
        parts = [int(x) for x in s.split('-')]
        gp = sum(parts)
        return parts[0] / gp if gp else 0.0
    ta_pct = tier_pct(ta); tb_pct = tier_pct(tb)
    ta_gp  = sum(int(x) for x in ta.split('-')) if ta and '-' in ta else 0
    tb_gp  = sum(int(x) for x in tb.split('-')) if tb and '-' in tb else 0

    rows.append({
        'team': nm, 'region': region, 'conference': conf,
        'record': t.get('record',''), 'conf_rec': t.get('conf',''),
        'w': w, 'l': l, 'cw': cw, 'cl': cl, 'cgp': cgp,
        'net':  t.get('net_rtg', 0),
        'ortg': t.get('ortg', 0),
        'drtg': t.get('drtg', 0),
        'sos':  t.get('sos', 0),
        'ta_pct': ta_pct, 'ta_gp': ta_gp,
        'tb_pct': tb_pct, 'tb_gp': tb_gp,
        'rpi':    rpi_r.get('rpi',    0),
        'nc_rpi': rpi_r.get('nc_rpi', 0),
        'wab':    wab_r.get('wab',    0),
        'wab_net':wab_r.get('net',    0),
        'rate':   rel_r.get('rel_rating', 0),
        'rate_rk':rel_r.get('rank_rel', 9999),
    })

# ── Determine conference champions ───────────────────────────────────────────
# Champion = best conf_pct in each conference (ties broken by cw then net)
conf_groups = {}
for r in rows:
    conf_groups.setdefault(r['conference'], []).append(r)

champs = set()
for conf, members in conf_groups.items():
    ranked = sorted(members, key=lambda x: (-x['cw']/(x['cgp'] or 1), -x['cw'], -x['net']))
    champs.add(ranked[0]['team'])

for r in rows:
    r['is_champ'] = r['team'] in champs

# ── Percentile-rank helper ────────────────────────────────────────────────────
def pct_rank(values, v, higher_is_better=True):
    """Returns 0-100 percentile rank of v among values."""
    if not values: return 50.0
    below = sum(1 for x in values if x < v) if higher_is_better else sum(1 for x in values if x > v)
    return 100.0 * below / len(values)

# ── Compute composite score per region ───────────────────────────────────────
WEIGHTS = {
    'net':     0.22,   # KenPom-style adjusted NET
    'adj_eff': 0.16,   # ortg - drtg (Torvik-style adjusted efficiency)
    'rate':    0.18,   # EvanMiya Rate
    'rpi':     0.12,   # RPI
    'nc_rpi':  0.08,   # Non-conf RPI
    'wab':     0.12,   # WAB
    'ta_pct':  0.07,   # Tier-A win pct
    'tb_pct':  0.05,   # Tier-B win pct
}
# weights sum to 1.0

def score_region(region_rows):
    nets     = [r['net']  for r in region_rows]
    adj_effs = [r['ortg'] - r['drtg'] for r in region_rows]
    rates    = [r['rate'] for r in region_rows]
    rpis     = [r['rpi']  for r in region_rows]
    nc_rpis  = [r['nc_rpi'] for r in region_rows]
    wabs     = [r['wab']  for r in region_rows]
    ta_pcts  = [r['ta_pct'] for r in region_rows]
    tb_pcts  = [r['tb_pct'] for r in region_rows]

    for r in region_rows:
        ae = r['ortg'] - r['drtg']
        score = (
            WEIGHTS['net']     * pct_rank(nets,     r['net'])     +
            WEIGHTS['adj_eff'] * pct_rank(adj_effs, ae)           +
            WEIGHTS['rate']    * pct_rank(rates,    r['rate'])     +
            WEIGHTS['rpi']     * pct_rank(rpis,     r['rpi'])      +
            WEIGHTS['nc_rpi']  * pct_rank(nc_rpis,  r['nc_rpi'])   +
            WEIGHTS['wab']     * pct_rank(wabs,     r['wab'])      +
            WEIGHTS['ta_pct']  * pct_rank(ta_pcts,  r['ta_pct'])   +
            WEIGHTS['tb_pct']  * pct_rank(tb_pcts,  r['tb_pct'])
        )
        # Conference champion tiebreak bonus: +1.5 points (small, only matters at edge)
        if r['is_champ']:
            score += 1.5
        r['composite'] = round(score, 2)

north_rows = [r for r in rows if r['region'] == 'North']
south_rows = [r for r in rows if r['region'] == 'South']
score_region(north_rows)
score_region(south_rows)

north_sorted = sorted(north_rows, key=lambda x: -x['composite'])
south_sorted = sorted(south_rows, key=lambda x: -x['composite'])

# ── Print bracket ─────────────────────────────────────────────────────────────
def print_bracket(region_name, seeded):
    top24 = seeded[:24]
    print(f"\n{'='*72}")
    print(f"  2025-26 {region_name.upper()} REGION — 24-TEAM PLAYOFF BRACKET (Re-seeded)")
    print(f"{'='*72}")
    print(f"  {'Seed':<5} {'Team':<22} {'Conf':<24} {'Record':<8} {'Conf':<7} {'NET':>5} {'Rate':>5} {'RPI':>6} {'WAB':>6} {'Score':>6}  C*")
    print(f"  {'-'*5} {'-'*22} {'-'*24} {'-'*8} {'-'*7} {'-'*5} {'-'*5} {'-'*6} {'-'*6} {'-'*6}  --")
    for i, r in enumerate(top24, 1):
        champ_mark = '★' if r['is_champ'] else ''
        print(f"  {i:<5} {r['team']:<22} {r['conference']:<24} {r['record']:<8} {r['conf_rec']:<7} {r['net']:>5.1f} {r['rate']:>5.1f} {r['rpi']:>6.4f} {r['wab']:>6.2f} {r['composite']:>6.1f}  {champ_mark}")

    print(f"\n  ★ = Conference champion  |  Champ bonus: +1.5 composite pts")
    print(f"\n  {'─'*50}")
    print(f"  SEEDS 1-8: BYE")
    print(f"  {'─'*50}")
    for i in range(8):
        print(f"  ({i+1:2}) {top24[i]['team']:<22} {'★' if top24[i]['is_champ'] else ''}")
    print(f"\n  {'─'*50}")
    print(f"  FIRST ROUND  (seeds 9-24, higher seed hosts)")
    print(f"  {'─'*50}")
    for i in range(8):
        a, b = top24[8 + i], top24[23 - i]
        print(f"  ({8+i+1:2}) {a['team']:<22} vs ({24-i:2}) {b['team']}")
    print(f"\n  {'─'*50}")
    print(f"  SECOND ROUND  (bye teams enter; winners shown by potential opp)")
    print(f"  {'─'*50}")
    for i in range(8):
        bye = top24[i]
        lo, hi = top24[8 + i], top24[23 - i]
        print(f"  ({i+1:2}) {bye['team']:<22} vs winner of ({8+i+1}) {lo['team']} / ({24-i}) {hi['team']}")

    excl = seeded[24:]
    if excl:
        print(f"\n  --- BUBBLE / EXCLUDED (seeds 25+) ---")
        for i, r in enumerate(excl[:6], 25):
            champ_mark = '★' if r['is_champ'] else ''
            print(f"  {i:<5} {r['team']:<22} {r['conference']:<24} {r['record']:<8} {r['conf_rec']:<7} {r['net']:>5.1f} {r['composite']:>6.1f} {champ_mark}")

print_bracket("North", north_sorted)
print_bracket("South", south_sorted)

# Metric legend
print("""
COMPOSITE SCORE WEIGHTS:
  NET Rating     22%   (KenPom-style adjusted net efficiency)
  Adj Efficiency 16%   (Torvik-style: Ortg - Drtg)
  Rate           18%   (EvanMiya-style relative efficiency rating)
  RPI            12%
  NC-RPI          8%   (Non-conference RPI)
  WAB            12%   (Wins Above Bubble)
  Tier-A Win%     7%   (vs top-25% opponents)
  Tier-B Win%     5%   (vs top-50% opponents)
  Conf Champ    +1.5   (flat tiebreak bonus, not percentile)
""")
