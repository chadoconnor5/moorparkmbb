"""
Moorpark College 2025-26 Men's Basketball — Comprehensive Scouting Report PDF
Narrative-first, context-rich. Every number is explained.
"""

import json, os, csv, re
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether, CondPageBreak
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
YELLOW_BG = colors.HexColor('#fff3cd')
GREEN_TXT = colors.HexColor('#1a5c30')
RED_TXT   = colors.HexColor('#7b1b1b')
TH_BG     = colors.HexColor('#1a3a6e')
ALT       = colors.HexColor('#e8ecf5')
WHITE     = colors.white
BLACK     = colors.black

BASE = '/Users/chadoconnor/Neural Network'

# ─── Load Data ────────────────────────────────────────────────────────────────
def jload(p): return json.load(open(p))

team_sum   = jload(f'{BASE}/2025-26 Team Statistics/WSC North/Moorpark/team_summary.json')
adv_json   = jload(f'{BASE}/2025-26 Team Statistics/WSC North/Moorpark/advanced_analytics.json')
plyr_stats = jload(f'{BASE}/2025-26 Team Statistics/WSC North/Moorpark/player_stats.json')
plyr_rtgs  = jload(f'{BASE}/2025-26 Team Statistics/WSC North/Moorpark/player_game_ratings.json')
conf_stats = jload(f'{BASE}/2025-26 Team Statistics/WSC North/Moorpark/conference_stats.json')
wab_data   = jload(f'{BASE}/wab_results.json')

pos_map = {}
with open(f'{BASE}/internal_data/player_positions_2025_26.csv') as f:
    for row in csv.DictReader(f):
        if row['team'] == 'Moorpark':
            pos_map[row['name']] = row['pos_class']

pos_full = {
    'PG':'Point Guard','s-PG':'Scoring PG','CG':'Combo Guard',
    'WG':'Wing Guard','WF':'Wing Forward','S-PF':'Stretch PF',
    'PF/C':'PF / Center','C':'Center'
}

wab_map   = {t['team']: t for t in wab_data}
mp_wab    = wab_map.get('Moorpark', {})

synergy_arch     = {r['name']: r for r in jload(f'{BASE}/internal_data/synergy_archetypes.json')}
synergy_team     = jload(f'{BASE}/internal_data/synergy_team_moorpark_2025_26.json')

pos_dep_all = jload(f'{BASE}/internal_data/position_dependence_2025_26.json')
pos_dep_map = {r['team']: r for r in pos_dep_all}
mp_dep      = pos_dep_map.get('Moorpark', {})
wsc_dep     = sorted([r for r in pos_dep_all if r['conference'] == 'WSC North'],
                     key=lambda x: x['gdi'], reverse=True)
avgs      = team_sum['averages']
opp_avgs  = team_sum['opponent_averages']
ta        = adv_json['team']
monthly   = ta.get('monthly_stats', {})
game_log  = ta.get('game_ratings', [])
plyr_adv  = {p['name']: p for p in adv_json.get('players', [])}

# Build game context with opponent quality
quality_games = []
for g in game_log:
    opp = g.get('canonical_opponent', g['opponent'])
    od = wab_map.get(opp)
    net = g['ortg'] - g['drtg']
    margin = g['team_score'] - g['opponent_score']
    quality_games.append({**g, 'net': net, 'margin': margin,
        'opp_net': od['net'] if od else None,
        'opp_wab': od['wab'] if od else None})

def avg_net(lst):
    return sum(g['net'] for g in lst) / len(lst) if lst else 0
def rec(lst):
    w = sum(1 for g in lst if g['result'] == 'W')
    return f'{w}-{len(lst)-w}'

wins   = [g for g in quality_games if g['result'] == 'W']
losses = [g for g in quality_games if g['result'] == 'L']
conf_g = [g for g in quality_games if g.get('is_conference')]
nconf  = [g for g in quality_games if not g.get('is_conference')]
home_g = [g for g in quality_games if g['location'] == 'Home']
away_g = [g for g in quality_games if g['location'] == 'Away']
neut_g = [g for g in quality_games if g['location'] == 'Neutral']
good_opp = [g for g in quality_games if g['opp_net'] is not None and g['opp_net'] > 0]
bad_opp  = [g for g in quality_games if g['opp_net'] is not None and g['opp_net'] <= 0]
elite_opp = [g for g in quality_games if g['opp_net'] is not None and g['opp_net'] > 12]
close_g  = [g for g in quality_games if abs(g['margin']) <= 8]
early_g  = quality_games[:14]
late_g   = quality_games[14:]

# ── Quad records (same thresholds as leaderboard) ────────────────────────────
_wab_ranked = sorted(wab_data, key=lambda x: -x.get('net', 0))
_N = len(_wab_ranked)
_net_ranks = {t['team']: i+1 for i, t in enumerate(_wab_ranked)}

def _get_quad(opp_rank, loc):
    tQ1A = {'Home': _N*15/353, 'Neutral': _N*25/353, 'Away': _N*40/353}
    tQ1  = {'Home': _N*30/353, 'Neutral': _N*50/353, 'Away': _N*75/353}
    tQ2  = {'Home': _N*75/353, 'Neutral': _N*100/353,'Away': _N*135/353}
    tQ3  = {'Home': _N*160/353,'Neutral': _N*200/353,'Away': _N*240/353}
    th = lambda m: m.get(loc, m['Neutral'])
    if opp_rank <= th(tQ1A): return 'Q1A'
    if opp_rank <= th(tQ1):  return 'Q1'
    if opp_rank <= th(tQ2):  return 'Q2'
    if opp_rank <= th(tQ3):  return 'Q3'
    return 'Q4'

quad_rec   = {'Q1A':[0,0],'Q1':[0,0],'Q2':[0,0],'Q3':[0,0],'Q4':[0,0]}
quad_games = {'Q1A':[],'Q1':[],'Q2':[],'Q3':[],'Q4':[]}
for _g in quality_games:
    _opp  = _g.get('canonical_opponent', _g['opponent'])
    _loc  = _g.get('location','Neutral')
    _rank = _net_ranks.get(_opp)
    if not _rank:
        continue
    _g2 = dict(_g, opp_rank=_rank)
    _q = _get_quad(_rank, _loc)
    if _g['result'] == 'W':   quad_rec[_q][0] += 1
    elif _g['result'] == 'L': quad_rec[_q][1] += 1
    quad_games[_q].append(_g2)

# Statewide context: load all teams
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
            _to     = s['averages'].get('TO', 0)
            _ostl   = s['opponent_averages'].get('STL', 0)
            _poss   = max(a.get('possessions', 0.01), 0.01)
            all_teams.append({
                'team': team,
                'net_rtg': a.get('net_rtg', 0), 'ortg': a.get('ortg', 0), 'drtg': a.get('drtg', 0),
                'efg_pct': a.get('efg_pct', 0), 'opp_efg_pct': a.get('opp_efg_pct', 0),
                'tov_pct': a.get('tov_pct', 0), 'opp_tov_pct': a.get('opp_tov_pct', 0),
                'oreb_pct': a.get('oreb_pct', 0), 'dreb_pct': a.get('dreb_pct', 0),
                'ft_rate': a.get('ft_rate', 0), 'opp_ft_rate': a.get('opp_ft_rate', 0),
                'ts_pct': a.get('ts_pct', 0), 'opp_ts_pct': a.get('opp_ts_pct', 0),
                'pace': a.get('possessions', 0),
                'ppg': s['averages']['PTS'], 'oppg': s['opponent_averages']['PTS'],
                'stl': s['averages']['STL'], 'blk': s['averages']['BLK'],
                'ast': s['averages']['AST'], 'tov': s['averages']['TO'],
                'nst_pct': round(max(_to - _ostl, 0) / _poss * 100, 1),
                'opp_nst_pct': round(max(s['opponent_averages'].get('TO', 0) - s['averages'].get('STL', 0), 0) / _poss * 100, 1),
                'tpa_rate': round(s['averages'].get('3PA', 0) / s['averages']['FGA'] * 100, 1) if s['averages'].get('FGA') else 0,
                'ast_rate': a.get('ast_rate', 0),
                'stl_pct': a.get('stl_pct', 0), 'blk_pct': a.get('blk_pct', 0),
                'ast_tov': round(s['averages']['AST'] / s['averages']['TO'], 2) if s['averages'].get('TO') else 0,
                'sos': a.get('sos', 0),
            })
        except: pass

n = len(all_teams)

# Bench scoring % (statewide, for depth ranking) — via the leaderboard's box loader
BENCH = {}
try:
    from generate_leaderboard import load_all_bench_points
    _bp = load_all_bench_points("2025-26", base_dir=os.path.dirname(os.path.abspath(__file__)))
    for _t in all_teams:
        _bd = _bp.get(_t['team'])
        if _bd and _bd.get('total_pts'):
            _t['bench_pct'] = round(_bd['bench_pts'] / _bd['total_pts'] * 100, 1)
    BENCH = {t['team']: t.get('bench_pct') for t in all_teams if 'bench_pct' in t}
except Exception:
    BENCH = {}
_mp_bench = BENCH.get('Moorpark')

def state_rank(key, val, higher_better=True):
    """Return (rank, n, avg, diff). Rank 1 = best."""
    vals = sorted([t[key] for t in all_teams if t[key] != 0], reverse=higher_better)
    rank = next((i+1 for i,v in enumerate(vals) if (higher_better and v<=val) or (not higher_better and v>=val)), len(vals))
    avg = sum(t[key] for t in all_teams) / n
    return rank, n, round(avg, 1), round(val - avg, 1)

def rank_str(key, val, hb=True, show_avg=True):
    r, tot, avg, diff = state_rank(key, val, hb)
    sign = '+' if diff > 0 else ''
    avg_s = f'  statewide avg: {avg}' if show_avg else ''
    return f'#{r}/{tot}{avg_s}  ({sign}{diff} vs avg)'

# Statewide player pool
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
            am = {p['name']: p for p in adv.get('players', [])}
            for p in ps['players']:
                avg2 = p['averages']
                if avg2.get('MIN', 0) <= 4.0 or avg2.get('games', 0) < 10: continue  # Min% > 10%
                ap2 = am.get(p['name'], {})
                all_players.append({
                    'team': team, 'name': p['name'],
                    'ppg': avg2.get('PTS', 0), 'rpg': avg2.get('REB', 0),
                    'apg': avg2.get('AST', 0), 'mpg': avg2.get('MIN', 0),
                    'fg': avg2.get('FG%', 0), 'tpp': avg2.get('3P%', 0),
                    'ftp': avg2.get('FT%', 0), 'tpag': avg2.get('3PA', 0),
                    'ts_pct': ap2.get('ts_pct', 0), 'efg': ap2.get('efg_pct', 0),
                    'tov_pct': ap2.get('tov_pct', 0), 'oreb_pct': ap2.get('oreb_pct', 0),
                })
        except: pass

def plyr_rank(key, val, hb=True):
    vals = sorted([p[key] for p in all_players if p[key] > 0], reverse=hb)
    r = next((i+1 for i,v in enumerate(vals) if (hb and v<=val) or (not hb and v>=val)), len(vals))
    return r, len(vals)

# ── Advanced analytics ranked pool (Min% ≥30%, i.e. MPG ≥ 12) ─────────────────
adv_players = []
for _conf in os.listdir(BASE + '/2025-26 Team Statistics'):
    _cp = f"{BASE}/2025-26 Team Statistics/{_conf}"
    if not os.path.isdir(_cp): continue
    for _team in os.listdir(_cp):
        _pp = f'{_cp}/{_team}/player_stats.json'
        _ap = f'{_cp}/{_team}/advanced_analytics.json'
        if not (os.path.exists(_pp) and os.path.exists(_ap)): continue
        try:
            _ps = jload(_pp); _adv = jload(_ap)
            _am = {p['name']: p for p in _adv.get('players', [])}
            for _p in _ps['players']:
                _avg = _p['averages']
                if _avg.get('MIN', 0) < 12.0 or _avg.get('games', 0) < 10: continue
                _a2 = _am.get(_p['name'], {})
                _tot = _p['totals']
                _twoa = _tot.get('FGA', 0) - _tot.get('3PA', 0)
                _twom = _tot.get('FGM', 0) - _tot.get('3PM', 0)
                adv_players.append({
                    'name': _p['name'], 'team': _team,
                    'ind_ortg': _a2.get('ind_ortg', 0), 'ind_drtg': _a2.get('ind_drtg', 0),
                    'ast_rate': _a2.get('ast_rate', 0), 'tov_pct':  _a2.get('tov_pct', 0),
                    'oreb_pct': _a2.get('oreb_pct', 0), 'dreb_pct': _a2.get('dreb_pct', 0),
                    'stl_pct':  _a2.get('stl_pct', 0),  'blk_pct':  _a2.get('blk_pct', 0),
                    'usage_pct':_a2.get('usage_pct', 0), 'ft_rate': _a2.get('ft_rate', 0),
                    'ts_pct':   _a2.get('ts_pct', 0),   'efg_pct': _a2.get('efg_pct', 0),
                    'fc_per_40':_a2.get('fc_per_40', 0), 'fd_per_40': _a2.get('fd_per_40', 0),
                    'shot_pct': _a2.get('shot_pct', 0), 'min_pct': _avg.get('MIN', 0) / 40.0 * 100,
                    'twop': round(_twom / _twoa * 100, 1) if _twoa > 0 else 0,
                    'tpp':  _avg.get('3P%', 0),
                    'ftp':  _avg.get('FT%', 0),
                })
        except: pass

def adv_rank(key, val, hb=True):
    vals = sorted([p[key] for p in adv_players if p[key] > 0], reverse=hb)
    r = next((i+1 for i,v in enumerate(vals) if (hb and v<=val) or (not hb and v>=val)), len(vals))
    return r, len(vals)

# Statewide ranks
net_rank, _, _, _ = state_rank('net_rtg', ta['net_rtg'], True)
wab_all = sorted(wab_data, key=lambda x: x.get('wab', 0), reverse=True)
wab_rank = next((i+1 for i,t in enumerate(wab_all) if t.get('team') == 'Moorpark'), None)

# Regional WAB rank (North vs South) — derived from wab_sim_split24.json region mapping
_wab_split    = jload(f'{BASE}/wab_sim_split24.json')
_team_region  = {e['team']: 'North' for e in _wab_split.get('north', [])}
_team_region.update({e['team']: 'South' for e in _wab_split.get('south', [])})
mp_region     = _team_region.get('Moorpark', 'South')
_wab_regional = [t for t in wab_all if _team_region.get(t.get('team', '')) == mp_region]
wab_reg_rank  = next((i+1 for i,t in enumerate(_wab_regional) if t.get('team') == 'Moorpark'), None)
wab_reg_total = len(_wab_regional)

# ── KenPom-style player role from %Poss (usage) and Min% ──────────────────────
def kenpom_player_role(usage_pct: float, mpg: float) -> tuple[str, str]:
    """Return (role_label, hex_color) based on KenPom %Poss tiers.

    Min% = MPG / 40 * 100  (player share of a 40-minute game).
    Benchwarmer override fires when Min% < 10  (MPG < 4), regardless of usage.
    %Poss tiers (adjusted per user spec, highest first):
      >= 28  Go-to Guy
      24-28  Major Contributor
      20-24  Significant Contributor
      16-20  Role Player
      12-16  Limited Role Player
      < 12   Nearly Invisible
    """
    min_pct = mpg / 40.0 * 100  # = MPG / game_minutes * 100
    if min_pct < 10.0:
        return 'Benchwarmer', '#777777'
    if usage_pct >= 28.0:
        return 'Go-to Guy', '#ffd700'
    if usage_pct >= 24.0:
        return 'Major Contributor', '#34a853'
    if usage_pct >= 20.0:
        return 'Significant Contributor', '#ff9900'
    if usage_pct >= 16.0:
        return 'Role Player', '#4a86e8'
    if usage_pct >= 12.0:
        return 'Limited Role Player', '#ff00ff'
    return 'Nearly Invisible', '#d9d9d9'

# ── Box-score offensive archetype (fallback when no Synergy archetype) ────────
# Blend: Synergy archetypes are the base layer (richest, work even with no
# advanced data); this fills the gap for players who DO have advanced metrics
# but no Synergy profile. Absolute thresholds calibrated from the league archetype
# profiles in prototype_offensive_archetypes.py. The profiled pool already filters
# to real rotation minutes (MIN>=12, games>=10), which is the usage-outlier guard.
_PERIM_POS = {'PG', 's-PG', 'CG', 'WG', 'WF'}
_BIG_POS = {'S-PF', 'PF/C', 'C'}

def box_offensive_role(pos, adv, tot):
    """Return (role_label, tendency_summary), or (None, None) without advanced data."""
    usg = adv.get('usage_pct', 0) or 0
    ast = adv.get('ast_rate', 0) or 0
    oreb = adv.get('oreb_pct', 0) or 0
    fga = tot.get('FGA', 0) or 0
    if usg <= 0 or fga <= 0:
        return None, None
    tpa_rate = tot.get('3PA', 0) / fga * 100
    ft_rate = tot.get('FTA', 0) / fga * 100
    summ = f'{usg:.0f}% usage · {tpa_rate:.0f}% 3PA rate · {ft_rate:.0f}% FT rate · {ast:.0f}% ast rate'

    if pos in _BIG_POS:
        if tpa_rate >= 20:                      # absolute floor: a real floor-stretcher
            return 'Stretch Big', summ
        if usg >= 26 and oreb >= 10:
            return 'Post Scorer', summ
        if oreb >= 10 or usg < 22:
            return 'Roll & Cut / Rim Big', summ
        return 'Versatile Big', summ

    # Perimeter
    if ast >= 22 and usg >= 24:
        return 'Primary Creator', summ
    if usg >= 24 and ast < 14:
        return 'Shot Creator', summ
    if tpa_rate >= 60:                      # extreme 3PA volume = off-ball regardless of usage
        return 'Off-Ball Shooter', summ
    if tpa_rate >= 50 and usg < 24:
        return 'Off-Ball Shooter', summ
    if ft_rate >= 40 and tpa_rate < 30:
        return 'Slasher / Finisher', summ
    if ast >= 16:
        return 'Secondary Handler', summ
    return 'Role / Connector', summ

# ── bball-index-style archetype (needs Synergy play-type + shot-type data) ────
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

def bball_index_archetype(pos, adv, tot, sa):
    """Basketball-Index-adapted offensive archetype from Synergy play-types +
    shot profile. Returns None without Synergy data."""
    if not sa:
        return None
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
    if ast >= 22 and (creator >= 6 or usg >= 18):
        return 'Primary Ball Handler' if usg >= 22 else 'Secondary Ball Handler'
    if rim >= 45:                                   # rim-dominant: attacks the basket, not a pull-up creator
        return 'Slasher' if (ftr >= 20 or pt.get('iso', 0) >= 6) else 'Athletic Finisher'
    if (usg >= 23 and (creator >= 14 or pullup >= 45)) or creator >= 22:
        return 'Primary Ball Handler' if ast >= 18 else 'Shot Creator'
    has_shots = bool(st)
    # jump-shot dominant + catch-and-shoot heavy = a shooter (true slashers were caught by rim>=45 above)
    if (has_shots and js >= 50 and cs >= 50) or (not has_shots and pt.get('spotup', 0) >= 28):
        if move >= 10: return 'Movement Shooter'      # off-screen / hand-off heavy
        if pt.get('spotup', 0) >= 30: return 'Stationary Shooter'
        return 'Off-Ball Shooter'
    if rim >= 30 or ftr >= 28 or pt.get('iso', 0) >= 10:
        return 'Slasher' if (ftr >= 25 or pt.get('iso', 0) >= 8) else 'Athletic Finisher'
    if ast >= 15 and creator >= 8: return 'Secondary Ball Handler'
    if cs >= 48 and js >= 45: return 'Off-Ball Shooter'
    return 'Connector / Role'

# ── Synergy offensive archetype (11-category taxonomy) computed from the REAL ──
# Synergy play-type mix + position tier + box rate signals. Same taxonomy as
# internal_compute_archetypes.py, but driven by actual Synergy play-types here.
# Returns None without Synergy data — never invents a label.
_GUARD_POS = {'PG', 's-PG', 'CG'}
def synergy_archetype(pos, sa, tot, apg):
    if not sa:
        return None
    pt = _parse_playtypes(sa.get('scoring_summary'))
    fga = tot.get('FGA', 0) or 0
    tpar = (tot.get('3PA', 0) / fga * 100) if fga else 0
    ftar = (tot.get('FTA', 0) / fga * 100) if fga else 0
    spot = pt.get('spotup', 0)
    move = pt.get('offscreen', 0) + pt.get('handoff', 0)
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
    # wing tier
    if apg >= 2.5: return 'Playmaking Wing'
    if rim >= 45 or (ftar >= 28 and tpar <= 30): return 'Slashing Wing'
    if tpar >= 55 or spot >= 45: return 'Spot-up Wing'
    if tpar >= 22 or move >= 10: return 'Dynamic Wing'
    return 'Slashing Wing'

# Merge player map
player_map = {}
for p in plyr_stats['players']:
    player_map[p['name']] = {
        'avg': p['averages'], 'tot': p['totals'],
        'adv': plyr_adv.get(p['name'], {}),
        'pos': pos_map.get(p['name'], '—'),
        'rating': next((r for r in plyr_rtgs['season_ratings'] if p['name'] in r['name']), {})
    }
player_order = sorted(player_map, key=lambda n: player_map[n]['avg'].get('MIN', 0), reverse=True)
rotation = [n for n in player_order if player_map[n]['avg'].get('MIN', 0) >= 5.0]

# ─── Derive games-started from box scores (top-5 minutes per game = starter) ──
def _compute_starter_data():
    sched_root = f'{BASE}/2025-26 Teams Schedules/WSC North/Moorpark'
    gs_count = {}   # name → total games started
    game_dates = [] # chronological list of (date_str, {name: started bool})
    for game_folder in sorted(os.listdir(sched_root)):
        folder_path = os.path.join(sched_root, game_folder)
        if not os.path.isdir(folder_path):
            continue
        for fname in os.listdir(folder_path):
            if not fname.endswith('.json'):
                continue
            try:
                box = jload(os.path.join(folder_path, fname))
            except Exception:
                continue
            mp_players = box.get('teams', {}).get('Moorpark', [])
            if not mp_players:
                continue
            # CCCMBCA box scores list starters first — first 5 rows = starters
            starters = set()
            for row in mp_players[:5]:
                raw_name = row.get('name', '')
                clean = raw_name.split(' ', 1)[1] if raw_name and raw_name[0] == '#' else raw_name
                starters.add(clean)
            date_str = box.get('date', game_folder)
            game_entry = {}
            for row in mp_players:
                raw_name = row.get('name', '')
                clean = raw_name.split(' ', 1)[1] if raw_name and raw_name[0] == '#' else raw_name
                started = clean in starters
                game_entry[clean] = started
                if started:
                    gs_count[clean] = gs_count.get(clean, 0) + 1
            game_dates.append((date_str, game_entry))
    # Last-5-games starts
    last5 = game_dates[-5:] if len(game_dates) >= 5 else game_dates
    last5_gs = {}
    for _, entry in last5:
        for name, started in entry.items():
            if started:
                last5_gs[name] = last5_gs.get(name, 0) + 1
    total_games = len(game_dates)
    return gs_count, last5_gs, total_games

_gs_count, _last5_gs, _total_games = _compute_starter_data()

def is_starter(name):
    """True if player started ≥50% of season games OR ≥3 of the last 5."""
    gs = _gs_count.get(name, 0)
    l5 = _last5_gs.get(name, 0)
    return (gs / _total_games >= 0.5 if _total_games > 0 else False) or l5 >= 3

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
    return HRFlowable(width='100%', thickness=thick, color=color,
                      spaceBefore=before, spaceAfter=after)

def section(title, subtitle=None):
    # Only stay on the current page if ~2in of content can follow the heading;
    # otherwise break first so the title never strands at the bottom of a page.
    items = [CondPageBreak(2.0*inch),
             Spacer(1, 10),
             Paragraph(title.upper(), S(13, True, BLUE, TA_LEFT)),
             HR(GOLD, 2, 2, 6)]
    if subtitle:
        items.append(Paragraph(subtitle, S(9, False, MID, TA_LEFT, space_after=6)))
    return items

def kv_table(rows, col1=2.0, col2=5.0):
    """Two-column label: value table."""
    data = [[Paragraph(f'<b>{k}</b>', S(9, True, BLUE)),
             Paragraph(v, S(9, color=BLACK))] for k, v in rows]
    t = Table(data, colWidths=[col1*inch, col2*inch])
    t.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [WHITE, LGRAY]),
        ('INNERGRID', (0,0), (-1,-1), 0.3, MGRAY),
        ('BOX', (0,0), (-1,-1), 0.5, BLUE),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    return t

def metric_table(headers, rows, col_widths=None, bold_col=None, color_last=False):
    col_widths = col_widths or [7.0*inch/len(headers)]*len(headers)
    data = [headers] + rows
    style = [
        ('BACKGROUND', (0,0), (-1,0), TH_BG),
        ('TEXTCOLOR', (0,0), (-1,0), WHITE),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (1,1), (1,-1), 'LEFT'),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, ALT]),
        ('INNERGRID', (0,0), (-1,-1), 0.3, MGRAY),
        ('BOX', (0,0), (-1,-1), 0.5, TH_BG),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]
    if bold_col is not None:
        style += [('FONTNAME', (bold_col,1),(bold_col,-1),'Helvetica-Bold'),
                  ('TEXTCOLOR', (bold_col,1),(bold_col,-1), BLUE)]
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle(style))
    return t

def splits_box(label, record_str, avg_net_val, extra=''):
    net_c = GREEN_BG if avg_net_val > 5 else (RED_BG if avg_net_val < -5 else YELLOW_BG)
    sign = '+' if avg_net_val >= 0 else ''
    data = [[Paragraph(f'<b>{label}</b>', S(8, True, DARK)),
             Paragraph(record_str, S(11, True, BLUE, TA_CENTER)),
             Paragraph(f'{sign}{avg_net_val:.1f} net rtg', S(9, False, MID, TA_CENTER)),
             Paragraph(extra, S(8, False, MID))]]
    t = Table(data, colWidths=[1.5*inch, 1.2*inch, 1.5*inch, 2.8*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), LGRAY),
        ('BACKGROUND', (1,0), (1,0), WHITE),
        ('BACKGROUND', (2,0), (2,0), net_c),
        ('BACKGROUND', (3,0), (3,0), WHITE),
        ('BOX', (0,0), (-1,-1), 0.5, BLUE),
        ('INNERGRID', (0,0), (-1,-1), 0.3, MGRAY),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    return t

# ─── Page callbacks ───────────────────────────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BLUE)
    canvas.rect(0.5*inch, 10.32*inch, 7.5*inch, 0.28*inch, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont('Helvetica-Bold', 7.5)
    canvas.drawString(0.62*inch, 10.39*inch, 'MOORPARK COLLEGE RAIDERS  |  2025–26 MEN\'S BASKETBALL  |  COMPREHENSIVE SCOUTING REPORT')
    canvas.setFont('Helvetica', 7.5)
    canvas.drawRightString(7.9*inch, 10.39*inch, f'Page {doc.page}')
    canvas.setFillColor(MID)
    canvas.setFont('Helvetica', 6.5)
    canvas.drawCentredString(4.25*inch, 0.35*inch, 'Internal Use Only  |  Generated May 28, 2026  |  Data: CCCMBCA box scores + internal analytics pipeline')
    canvas.restoreState()

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — COVER + TEAM EXECUTIVE SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
# ── Keys to Victory (compute_team_keys) ──────────────────────────────────────
try:
    from compute_team_keys import load_team_games, analyze as _kanalyze
    _CODEX = os.path.dirname(os.path.abspath(__file__))
    _kgames = load_team_games('Moorpark', ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"],
                              base_dir=_CODEX, with_bench=True)
    KEYS = _kanalyze(_kgames, n_targets=3) if _kgames else None
except Exception:
    KEYS = None


def page_keys():
    e = []
    e += section('Keys to Victory',
                 'The win formula — the metrics that most separate Moorpark wins from losses across '
                 'the 2021-26 era (point-biserial correlation), with the targets-hit payoff.')
    if not KEYS or not KEYS.get('keys'):
        e.append(Paragraph('Insufficient game history for keys analysis.', S(9, False, MID)))
        return e
    rec = KEYS['record']
    e.append(Paragraph(
        f"From {KEYS['n_games']} games ({rec[0]}-{rec[1]}): each key is the threshold that best splits "
        f"wins from losses, with Moorpark's average when winning vs. losing. All three are "
        f"defense / rebounding metrics — statistical confirmation of a defense-first identity.",
        S(9.5, False, DARK, space_after=10)))
    ar = {'>=': '≥', '<=': '≤'}
    rows = [[k.metric, f"{ar.get(k.direction, k.direction)} {k.target:g}",
             f"{k.avg_win:g}", f"{k.avg_loss:g}", f"{k.r:+.2f}"] for k in KEYS['keys']]
    e.append(metric_table(['Key Metric', 'Target', 'Avg in Wins', 'Avg in Losses', 'r'],
                          rows, [2.3*inch, 1.2*inch, 1.3*inch, 1.3*inch, 0.9*inch], bold_col=0))
    e.append(Spacer(1, 14))
    e.append(Paragraph("<b>The payoff</b> — Moorpark's record by how many of the three keys they hit in a game:",
                       S(10, False, DARK, space_after=6)))
    tt = KEYS['targets_table']; nk = len(KEYS['keys'])
    prows = []
    for i in range(nk, -1, -1):
        r = tt.get(i, {})
        if r.get('games'):
            prows.append([f"{i} of {nk}", str(r['games']), f"{r['w']}-{r['l']}",
                          f"{r['win_pct']}%" if r.get('win_pct') is not None else '—',
                          f"{r['avg_mov']:+.1f}" if r.get('avg_mov') is not None else '—'])
    e.append(metric_table(['Keys Hit', 'Games', 'Record', 'Win %', 'Avg Margin'],
                          prows, [1.3*inch, 1.1*inch, 1.2*inch, 1.1*inch, 1.3*inch], bold_col=3))
    top = tt.get(nk, {}); bot = tt.get(0, {})
    if top.get('games') and bot.get('games'):
        e.append(Spacer(1, 12))
        e.append(Paragraph(
            f"<b>Bottom line:</b> hit all {nk} keys and Moorpark is <b>{top['w']}-{top['l']}</b> "
            f"({top['win_pct']}%, {top['avg_mov']:+.1f} margin); hit none and they fall to "
            f"<b>{bot['w']}-{bot['l']}</b> ({bot['win_pct']}%). The scouting directive is simple — "
            f"deny these three.", S(9.5, False, DARK, TA_JUSTIFY)))
    e.append(Spacer(1, 14))
    return e


def page_cover():
    e = []

    # Title block
    title_data = [
        ['MOORPARK COLLEGE RAIDERS'],
        ['2025–26 MEN\'S BASKETBALL  ·  COMPREHENSIVE SCOUTING REPORT'],
    ]
    for i, (row, sz, c) in enumerate(zip(title_data, [26, 11], [WHITE, GOLD])):
        t = Table([row], colWidths=[7.5*inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), BLUE if i==0 else DARK),
            ('TEXTCOLOR', (0,0), (-1,-1), c),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), sz),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('TOPPADDING', (0,0), (-1,-1), 14 if i==0 else 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 14 if i==0 else 8),
        ]))
        e.append(t)

    e.append(Spacer(1, 12))

    # Headline stat strip
    strip_data = [[
        f'19-10\nOverall', f'10-2\nWSC North\nConference',
        f'#{net_rank} / 100\nNet Rating\nStatewide',
        f'#{wab_reg_rank} / {wab_reg_total}\nWAB Rank\n{mp_region} Region',
        f'+{ta["net_rtg"]:.1f}\nNet Rating\nPts/100 Poss',
        f'{ta["drtg"]:.1f}\nDef. Rating\n#13 in CCCAA',
    ]]
    t = Table(strip_data, colWidths=[1.25*inch]*6)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), LGRAY),
        ('BACKGROUND', (2,0), (3,0), ALT),
        ('BACKGROUND', (5,0), (5,0), GREEN_BG),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 11),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('INNERGRID', (0,0), (-1,-1), 0.5, MGRAY),
        ('BOX', (0,0), (-1,-1), 1, BLUE),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    # Multi-line cell hack: rebuild with Paragraphs
    def hcell(top, mid, bot, bg=LGRAY, top_sz=14, top_color=BLUE):
        return [
            Paragraph(top, S(top_sz, True, top_color, TA_CENTER)),
            Paragraph(mid, S(7.5, False, MID, TA_CENTER)),
            Paragraph(bot, S(7, False, MID, TA_CENTER)),
        ]
    _ortg_r, _, _, _ = state_rank('ortg', ta['ortg'], True)
    _drtg_r, _, _, _ = state_rank('drtg', ta['drtg'], False)
    _sos_r,  _, _, _ = state_rank('sos',  ta.get('sos', 0), True)
    _net_sign = '+' if ta['net_rtg'] >= 0 else ''
    _sos_sign = '+' if ta.get('sos', 0) >= 0 else ''
    strip_cells = [
        hcell('19-10', 'RECORD', 'Overall'),
        hcell('10-2', 'CONF. RECORD', 'WSC North'),
        hcell(f'{_net_sign}{ta["net_rtg"]:.1f}', 'NET', f'#{net_rank}/100 Statewide'),
        hcell(f'{ta["ortg"]:.1f}', 'ORTG', f'#{_ortg_r}/100 Statewide'),
        hcell(f'{ta["drtg"]:.1f}', 'DRTG', f'#{_drtg_r}/100 Statewide', GREEN_BG, 14, GREEN_TXT),
        hcell(f'{_sos_sign}{ta.get("sos", 0):.1f}', 'SOS', f'#{_sos_r}/100 Statewide'),
    ]
    t2 = Table([strip_cells], colWidths=[1.25*inch]*6)
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), LGRAY),
        ('BACKGROUND', (4,0), (4,0), GREEN_BG),
        ('INNERGRID', (0,0), (-1,-1), 0.5, MGRAY),
        ('BOX', (0,0), (-1,-1), 1.5, BLUE),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    e.append(t2)
    e.append(Spacer(1, 14))

    # ── WHO IS MOORPARK? ──────────────────────────────────────────────────────
    e += section('Who Is Moorpark?', 'Team identity and style of play')

    # ── Data-driven identity: flag every metric in the top quartile (strength)
    # or bottom quartile (weakness) statewide, grouped by offense / defense. ──
    IDM = [  # key, label, side(O/D), higher_better, unit
        ('ortg', 'Offensive Rating', 'O', True, ''), ('efg_pct', 'Effective FG%', 'O', True, '%'),
        ('ts_pct', 'True Shooting%', 'O', True, '%'), ('tov_pct', 'Turnover%', 'O', False, '%'),
        ('nst_pct', 'Non-Steal Turnover%', 'O', False, '%'), ('oreb_pct', 'Offensive Rebound%', 'O', True, '%'),
        ('ft_rate', 'Free Throw Rate', 'O', True, ''), ('ast_rate', 'Assist Rate', 'O', True, '%'),
        ('ast_tov', 'Assist-to-Turnover', 'O', True, ''), ('bench_pct', 'Bench Points%', 'O', True, '%'),
        ('drtg', 'Defensive Rating', 'D', False, ''), ('opp_efg_pct', 'Opp Effective FG%', 'D', False, '%'),
        ('opp_ts_pct', 'Opp True Shooting%', 'D', False, '%'), ('opp_tov_pct', 'Opp Turnover% forced', 'D', True, '%'),
        ('opp_nst_pct', 'Opp Non-Steal TO% forced', 'D', True, '%'), ('dreb_pct', 'Defensive Rebound%', 'D', True, '%'),
        ('opp_ft_rate', 'Opp Free Throw Rate', 'D', False, ''), ('stl_pct', 'Steal%', 'D', True, '%'),
        ('blk_pct', 'Block%', 'D', True, '%'),
    ]
    _flags = {'O': {'s': [], 'w': []}, 'D': {'s': [], 'w': []}}
    for _k, _lab, _side, _hb, _u in IDM:
        if _k == 'bench_pct':
            if _mp_bench is None or not BENCH:
                continue
            _vals = sorted(BENCH.values(), reverse=True)
            _r = next((i + 1 for i, v in enumerate(_vals) if v <= _mp_bench), len(_vals)); _tot = len(_vals)
            _v = _mp_bench
        else:
            _v = ta.get(_k)
            if _v is None:
                continue
            _r, _tot, _, _ = state_rank(_k, _v, _hb)
        _cut = max(round(_tot * 0.25), 1)        # top / bottom quartile
        _entry = (_r, f"{_lab} {_v:.1f}{_u} (#{_r}/{_tot})")
        if _r <= _cut:
            _flags[_side]['s'].append(_entry)
        elif _r >= _tot - _cut + 1:
            _flags[_side]['w'].append(_entry)

    def _flagcell(title, items, hexcolor):
        body = '<br/>'.join('•&nbsp; ' + t for _, t in sorted(items)) if items else '<i>none</i>'
        return Paragraph(f'<font color="{hexcolor}"><b>{title}</b></font><br/>{body}', S(8.5, leading=12))
    _GH, _RH = '#1a5c30', '#7b1b1b'
    id_tbl = Table([
        [_flagcell('OFFENSE — Strengths (top 25%)', _flags['O']['s'], _GH),
         _flagcell('OFFENSE — Weaknesses (bottom 25%)', _flags['O']['w'], _RH)],
        [_flagcell('DEFENSE — Strengths (top 25%)', _flags['D']['s'], _GH),
         _flagcell('DEFENSE — Weaknesses (bottom 25%)', _flags['D']['w'], _RH)],
    ], colWidths=[3.75 * inch, 3.75 * inch])
    id_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), GREEN_BG), ('BACKGROUND', (1, 0), (1, -1), RED_BG),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOX', (0, 0), (-1, -1), 0.5, BLUE),
        ('INNERGRID', (0, 0), (-1, -1), 0.3, MGRAY),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    e.append(Paragraph('<b>Statistical Identity</b> — every metric ranked against all 100 CCCAA programs; '
                       'top-quartile ranks (#1–25) are flagged as strengths, bottom-quartile (#76–100) as weaknesses.',
                       S(9, space_after=4)))
    e.append(id_tbl)
    e.append(Spacer(1, 10))

    # Pull statewide ranks for all cited metrics
    drtg_r,  _, drtg_avg,  _ = state_rank('drtg',        ta['drtg'],        False)
    ortg_r,  _, ortg_avg,  _ = state_rank('ortg',        ta['ortg'],        True)
    oefg_r,  _, oefg_avg,  _ = state_rank('opp_efg_pct', ta['opp_efg_pct'], False)
    otov_r,  _, otov_avg,  _ = state_rank('opp_tov_pct', ta['opp_tov_pct'], True)
    dreb_r,  _, dreb_avg,  _ = state_rank('dreb_pct',    ta['dreb_pct'],    True)
    ots_r,   _, ots_avg,   _ = state_rank('opp_ts_pct',  ta['opp_ts_pct'],  False)
    efg_r,   _, efg_avg,   _ = state_rank('efg_pct',     ta['efg_pct'],     True)
    ts_r,    _, ts_avg,    _ = state_rank('ts_pct',       ta['ts_pct'],      True)
    tov_r,   _, tov_avg,   _ = state_rank('tov_pct',     ta['tov_pct'],     False)
    _mp_nst   = round(max(avgs['TO'] - opp_avgs['STL'], 0) / max(ta.get('possessions', 0.01), 0.01) * 100, 1)
    nst_r,   _, nst_avg,   _ = state_rank('nst_pct',     _mp_nst,           False)
    oreb_r,  _, oreb_avg,  _ = state_rank('oreb_pct',    ta['oreb_pct'],    True)
    ftr_r,   _, ftr_avg,   _ = state_rank('ft_rate',     ta['ft_rate'],     True)
    oftr_r,  _, oftr_avg,  _ = state_rank('opp_ft_rate', ta['opp_ft_rate'], False)
    pace_r,  _, pace_avg,  _ = state_rank('pace',        ta['possessions'], True)
    _mp_tpar  = round(avgs['3PA'] / avgs['FGA'] * 100, 1) if avgs.get('FGA') else 0
    tpar_r,  _, tpar_avg,  _ = state_rank('tpa_rate',    _mp_tpar,          True)
    _mp_opnst = round(max(opp_avgs['TO'] - avgs['STL'], 0) / max(ta.get('possessions', 0.01), 0.01) * 100, 1)
    opnst_r, _, opnst_avg, _ = state_rank('opp_nst_pct', _mp_opnst,         True)
    astr_r,  _, astr_avg,  _ = state_rank('ast_rate',    ta.get('ast_rate', 0), True)
    _mp_atov  = round(avgs['AST'] / avgs['TO'], 2) if avgs.get('TO') else 0
    atov_r,  _, atov_avg,  _ = state_rank('ast_tov',     _mp_atov,          True)
    stl_r,   _, stl_avg,   _ = state_rank('stl_pct',     ta.get('stl_pct', 0), True)
    blk_r,   _, blk_avg,   _ = state_rank('blk_pct',     ta.get('blk_pct', 0), True)
    _bench_r = _bench_tot = _bench_avg = None
    if _mp_bench is not None and BENCH:
        _bv = sorted(BENCH.values(), reverse=True)
        _bench_r = next((i + 1 for i, v in enumerate(_bv) if v <= _mp_bench), len(_bv))
        _bench_tot = len(_bv); _bench_avg = round(sum(_bv) / len(_bv), 1)

    e.append(Paragraph(
        '<b>Core Identity: A defensive program that wins games it cannot outscore.</b> '
        f'Moorpark finished 2025-26 ranked <b>#{drtg_r}/100 in Defensive Rating</b> '
        f'({ta["drtg"]:.1f} pts allowed per 100 possessions, state avg {drtg_avg:.1f}). '
        f'Their Offensive Rating of {ta["ortg"]:.1f} is #{ortg_r}/100 — exactly state-average. '
        'The gap between those two numbers is the entire story: Moorpark does not beat you with '
        'offense. They win by suppressing opponent shooting efficiency and forcing turnovers — their '
        'edge is measurably on the defensive end, not the offensive one. In a 12-game conference sample '
        'they posted a <b>+8.0 net rating</b>. Over the full 29-game season '
        'the number settles at +5.8 — a reflection of a slow start, not a false ceiling.',
        S(9.5, space_after=8)))

    e.append(Paragraph(
        '<b>Defensive Profile — Two Pillars: Shooting Suppression and Turnover Pressure</b>',
        S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        f'<b>Shooting suppression (Opp eFG% {ta["opp_efg_pct"]:.1f}%, #{oefg_r}/100)</b> is the '
        f'primary pillar. The state average is {oefg_avg:.1f}%; Moorpark holds opponents 2.4 '
        f'percentage points below that. With a low Block% (#{blk_r}/100), the suppression is not rim-protection '
        '— opponents simply convert at a lower rate against them. Opp True Shooting% agrees: '
        f'{ta["opp_ts_pct"]:.1f}% (#{ots_r}/100, avg {ots_avg:.1f}%). Opponents shoot worse against '
        'Moorpark across the board.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Forced turnovers (Opp TOV% {ta["opp_tov_pct"]:.1f}%, #{otov_r}/100)</b> are the '
        f'second pillar. The state average is {otov_avg:.1f}%; Moorpark forces opponents into '
        'miscues on roughly 1 in 5 possessions. Live-ball turnovers flow directly into transition '
        'offense, which is where this team — built on pace and perimeter shooting — is most dangerous. '
        f'Crucially, the turnovers are predominantly non-steal: opponents\' Non-Steal Turnover rate against '
        f'Moorpark ranks #{opnst_r}/100 ({_mp_opnst:.1f}%, vs {opnst_avg:.1f}% average), while Moorpark\'s own '
        f'Steal% (#{stl_r}/100) and Block% (#{blk_r}/100) are low. In other words, opponents give the ball '
        'away against Moorpark far more than Moorpark actively strips or blocks it.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Defensive rebounding ({ta["dreb_pct"]:.1f}%, #{dreb_r}/100, avg {dreb_avg:.1f}%)</b> '
        'is average. Moorpark does not dominate the defensive glass — opponents do collect second-chance '
        f'opportunities. Their Opp FT Rate of {ta["opp_ft_rate"]:.1f} (#{oftr_r}/100) is also near '
        'state average, meaning they do not survive on foul avoidance either. The defense is built '
        'entirely on the first two pillars: force bad shots, and take the ball away.',
        S(9.5, space_after=8)))

    e.append(Paragraph(
        '<b>Offensive Profile — Four Factors Analysis</b>',
        S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        f'<b>Shooting efficiency (eFG% {ta["efg_pct"]:.1f}%, #{efg_r}/100; TS% {ta["ts_pct"]:.1f}%, '
        f'#{ts_r}/100):</b> Marginally above state average in eFG% ({efg_avg:.1f}% avg) and essentially '
        f'at state average in TS% ({ts_avg:.1f}% avg). Their 3-point volume props up the eFG% figure: '
        f'a 3-Point Attempt Rate of {_mp_tpar:.1f}% (3PA/FGA) ranks <b>#{tpar_r}/100</b> — top-ten statewide and '
        f'far above the {tpar_avg:.1f}% average, the single most extreme number in their profile. '
        'When those shots fall their offense looks functional. '
        'When they do not fall, there is little to fall back on: a bottom-five free-throw rate (below) '
        'paired with top-ten three-point reliance describes a perimeter-first offense that, by the '
        'numbers, generates little scoring at the rim or the foul line.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Ball security — split verdict (TOV% {ta["tov_pct"]:.1f}%, #{tov_r}/100, avg {tov_avg:.1f}%):</b> '
        f'The aggregate number looks near average, but the composition tells a more specific story. '
        f'Opponents steal only {opp_avgs["STL"]:.1f} balls per game from them — not above average, meaning '
        f'defenses are not consistently picking their pockets. But of their {avgs["TO"]:.1f} turnovers per '
        f'game total, that leaves {avgs["TO"]-opp_avgs["STL"]:.1f} per game that opponents did not create. '
        f'Their Non-Steal Turnover rate (NST%) of {_mp_nst:.1f}% is #{nst_r}/100 statewide '
        f'(state avg {nst_avg:.1f}%) — bottom-ten in the CCCAA. These are turnovers no opponent steal '
        'created: a high rate of giveaways opponents did not force, which is a real ceiling on this offense.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Offensive rebounding (OREB% {ta["oreb_pct"]:.1f}%, #{oreb_r}/100, avg {oreb_avg:.1f}%):</b> '
        'A genuine strength. They crash the offensive glass at an above-average rate and convert misses '
        'into second-chance possessions. Given how often they miss — they are a jump-shooting team with '
        'modest eFG% — second-chance opportunities are a meaningful part of how this offense stays afloat. '
        'The rate is high enough to suggest a deliberate crash, but the box score alone cannot confirm how '
        'many players they commit to the offensive glass.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>FT Rate ({ta["ft_rate"]:.1f}, #{ftr_r}/100, avg {ftr_avg:.1f}) — The defining limitation.</b> '
        f'Only {100 - ftr_r} programs get to the foul line less often in the entire CCCAA. This is the '
        'clearest expression of what Moorpark is offensively: a perimeter-first, jump-shooting team '
        'that rarely draws contact or gets to the rim and generates almost no points at the '
        'stripe. Its efficiency is therefore tied tightly to perimeter shooting — when the three is '
        'not falling, the data shows few alternative sources of offense.',
        S(9.5, space_after=8)))

    e.append(Paragraph(
        '<b>Depth and Ball Movement</b>',
        S(9.5, True, BLUE, space_after=3)))

    _bench_txt = (f'non-starters account for <b>{_mp_bench:.1f}%</b> of Moorpark\'s points '
                  f'(#{_bench_r}/{_bench_tot}, avg {_bench_avg:.1f}%) — a genuinely deep rotation that sustains '
                  'pace and pressure without drop-off. ') if _bench_r else ''
    e.append(Paragraph(
        f'Two under-discussed strengths round out the identity. <b>Bench scoring:</b> {_bench_txt}'
        f'<b>Ball movement:</b> a {_mp_atov:.2f} assist-to-turnover ratio ranks #{atov_r}/100 — above average — '
        f'though raw Assist Rate (#{astr_r}/100) is more middling. When they avoid unforced errors they move '
        'the ball adequately and the offense hums in transition; the depth is the larger asset, and the '
        'live-ball turnovers covered above are the tax that caps the passing.',
        S(9.5, space_after=8)))

    e.append(Paragraph(
        '<b>Pace and Style</b>',
        S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        f'They play at above-average pace: {ta["possessions"]:.1f} possessions per game '
        f'(#{pace_r}/100, state avg {pace_avg:.1f}). A fast tempo paired with a top-ten three-point-attempt '
        'rate is the statistical signature of a transition-and-perimeter team; the Synergy play-type section '
        'that follows quantifies how much of their offense actually comes in transition versus the half court. '
        'The data-level read is consistent across the board: high pace, heavy threes, elite shooting defense, '
        'and a bottom-tier free-throw rate — a profile that has dominated weaker opponents (14-0 vs. sub-.500 '
        'net teams) but gone 5-10 against the top half of the field.',
        S(9.5, space_after=8)))

    e.append(Paragraph(
        '<b>Season Arc: A Team That Found Itself</b>',
        S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        'They went 8-6 in the first half of the season (games 1–14), average net rating +3.6. '
        'They went <b>11-4 in the second half (games 15–29), average net rating +13.7</b>. Monthly '
        'breakdowns: November -0.1 (4-4, early-season struggles), December +8.5 (4-2, finding form), '
        'January +13.9 (7-2, conference dominance beginning), February +13.5 (4-2). '
        'In WSC North conference play: <b>10-2, average net rating +8.0</b> — a strong conference '
        'record. The team that shows up in February is meaningfully better than the team that started '
        'November. Net rating improved from -0.1 to +13.5 in four months. TOV% fell from 16.9% to '
        '12.6% over the same arc. OREB% jumped from 51.2% to 55.7% late. This is a team that '
        'peaked at the right time.',
        S(9.5)))
    e.append(Spacer(1, 12))

    # ── QUICK REFERENCE: TEAM VS OPPONENTS ───────────────────────────────────
    e += section('Season Averages: Moorpark vs. Opponents')

    def diff_str(v, ov, hb=True):
        d = v - ov
        s = '+' if d > 0 else ''
        favor = 'MPC' if (d > 0) == hb else 'OPP'
        return f'{s}{d:.1f} ({favor})'

    cmp_h = ['CATEGORY', 'MOORPARK', 'OPPONENTS', 'EDGE']
    cmp_r = [
        ['Points / Game',      f"{avgs['PTS']:.1f}",  f"{opp_avgs['PTS']:.1f}",  diff_str(avgs['PTS'],opp_avgs['PTS'])],
        ['Rebounds / Game',    f"{avgs['REB']:.1f}",  f"{opp_avgs['REB']:.1f}",  diff_str(avgs['REB'],opp_avgs['REB'])],
        ['Assists / Game',     f"{avgs['AST']:.1f}",  f"{opp_avgs['AST']:.1f}",  diff_str(avgs['AST'],opp_avgs['AST'])],
        ['Steals / Game',      f"{avgs['STL']:.1f}",  f"{opp_avgs['STL']:.1f}",  diff_str(avgs['STL'],opp_avgs['STL'])],
        ['Blocks / Game',      f"{avgs['BLK']:.1f}",  f"{opp_avgs['BLK']:.1f}",  diff_str(avgs['BLK'],opp_avgs['BLK'])],
        ['Turnovers / Game',   f"{avgs['TO']:.1f}",   f"{opp_avgs['TO']:.1f}",   diff_str(avgs['TO'],opp_avgs['TO'],False)],
        ['Field Goal %',       f"{avgs['FG%']:.1f}%", f"{opp_avgs['FG%']:.1f}%", diff_str(avgs['FG%'],opp_avgs['FG%'])],
        ['3-Point %',          f"{avgs['3P%']:.1f}%", f"{opp_avgs['3P%']:.1f}%", diff_str(avgs['3P%'],opp_avgs['3P%'])],
        ['Free Throw %',       f"{avgs['FT%']:.1f}%", f"{opp_avgs['FT%']:.1f}%", diff_str(avgs['FT%'],opp_avgs['FT%'])],
        ['Off. Rebounds / G',  f"{avgs['OREB']:.1f}", f"{opp_avgs['OREB']:.1f}", diff_str(avgs['OREB'],opp_avgs['OREB'])],
        ['Fouls / Game',       f"{avgs['PF']:.1f}",   f"{opp_avgs['PF']:.1f}",   diff_str(avgs['PF'],opp_avgs['PF'],False)],
    ]
    e.append(metric_table(cmp_h, cmp_r, [2.4*inch,1.5*inch,1.5*inch,1.6*inch], bold_col=3))
    e.append(Spacer(1, 14))
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — CONTEXTUAL ADVANCED ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════
def page_analytics():
    e = []
    e += section('Advanced Analytics: In Context',
                 'Every metric is ranked against all 100 CCCAA programs. Statewide average shown for scale.')

    # Four Factors with narrative
    e.append(Paragraph('<b>The Four Factors</b>: the pillars that determine offensive/defensive efficiency:', S(9, space_after=4)))

    ff_h = ['FACTOR', 'MPC OFF.', 'MPC DEF.', 'OPP OFF.', 'STATE RANK (OFF)', 'STATE RANK (DEF)', 'WHAT IT MEANS']
    _rk = lambda t: Paragraph(str(t), S(7.5, align=TA_CENTER, leading=9))   # wrap rank cells
    _wm = lambda t: Paragraph(str(t), S(7.5, align=TA_LEFT, leading=9))     # wrap "what it means"
    ff_r = [
        ['Shooting (eFG%)',
         f"{ta['efg_pct']:.1f}%", f"{ta['opp_efg_pct']:.1f}%", f"avg {state_rank('efg_pct',ta['efg_pct'])[2]:.1f}%",
         _rk(rank_str('efg_pct', ta['efg_pct'], True, False)),
         _rk(rank_str('opp_efg_pct', ta['opp_efg_pct'], False, False)),
         _wm('Slightly above-avg shooting; elite at suppressing opp shots')],
        ['Turnovers (TOV%)',
         f"{ta['tov_pct']:.1f}%", f"{ta['opp_tov_pct']:.1f}%", f"avg {state_rank('tov_pct',ta['tov_pct'])[2]:.1f}%",
         _rk(rank_str('tov_pct', ta['tov_pct'], False, False)),
         _rk(rank_str('opp_tov_pct', ta['opp_tov_pct'], True, False)),
         _wm('Average ball security; forces opponent TOs at top-25% rate')],
        ['Off. Rebounding (OREB%)',
         f"{ta['oreb_pct']:.1f}%", f"{ta['dreb_pct']:.1f}%", f"avg {state_rank('oreb_pct',ta['oreb_pct'])[2]:.1f}%",
         _rk(rank_str('oreb_pct', ta['oreb_pct'], True, False)),
         _rk(rank_str('dreb_pct', ta['dreb_pct'], True, False)),
         _wm('Top-30% offensive rebounding; average on defensive glass')],
        ['Free Throws (FT Rate)',
         f"{ta['ft_rate']:.1f}", f"{ta['opp_ft_rate']:.1f}", f"avg {state_rank('ft_rate',ta['ft_rate'])[2]:.1f}",
         _rk(rank_str('ft_rate', ta['ft_rate'], True, False)),
         _rk(rank_str('opp_ft_rate', ta['opp_ft_rate'], False, False)),
         _wm('BOTTOM 5% getting to the line, perimeter-only offense')],
    ]
    ff_cw = [1.3*inch, 0.6*inch, 0.6*inch, 0.6*inch, 0.95*inch, 0.95*inch, 2.0*inch]
    t = Table([ff_h]+ff_r, colWidths=ff_cw)
    # Highlight FT Rate warning
    ft_row = 4
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), TH_BG),
        ('TEXTCOLOR', (0,0), (-1,0), WHITE),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 7.5),
        ('FONTSIZE', (0,1), (-1,-1), 7.5),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (0,1), (0,-1), 'LEFT'),
        ('ALIGN', (6,1), (6,-1), 'LEFT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, ALT]),
        ('INNERGRID', (0,0), (-1,-1), 0.3, MGRAY),
        ('BOX', (0,0), (-1,-1), 0.5, TH_BG),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND', (0,ft_row), (-1,ft_row), RED_BG),  # FT Rate warning
        ('TEXTCOLOR', (0,ft_row), (-1,ft_row), RED_TXT),
    ]))
    e.append(t)
    e.append(Spacer(1, 8))

    # Context bullets for four factors
    e.append(Paragraph(
        '<b>FT Rate:</b> Moorpark\'s 25.3 FT Rate (FTA/FGA) is the 95th-worst in '
        'the state. The statewide average is 33.9. This is the defining limitation of their offense: '
        'they are a jump-shooting team that rarely gets to the rim. Their offensive output tracks '
        'closely with perimeter shooting; the data shows limited scoring at the foul line to fall '
        'back on when the three is not falling.', S(8.5, italic=True, space_after=8)))

    # Full metric context table
    e += section('All Advanced Metrics: Statewide Rank', 'Rank 1 = best in CCCAA in each category.')

    def ctx_row(label, val, key, hb, unit='', note=''):
        r, tot, avg, diff = state_rank(key, val, hb)
        sign = '+' if diff > 0 else ''
        tier = ('Elite' if r <= 15 else 'Above Avg' if r <= 35 else
                'Average' if r <= 65 else 'Below Avg' if r <= 85 else 'Concern')
        tier_color = (GREEN_TXT if r <= 15 else colors.HexColor('#1a5c20') if r <= 35 else
                      colors.HexColor('#555500') if r <= 65 else colors.HexColor('#7b3b00') if r <= 85 else RED_TXT)
        return [label, f'{val:.1f}{unit}', f'#{r}/{tot}',
                f'{avg:.1f}{unit}', f'{sign}{diff:.1f}{unit}',
                Paragraph(f'<font color="#{tier_color.hexval()[1:] if hasattr(tier_color,"hexval") else "555555"}"><b>{tier}</b></font>', S(8)),
                note]

    ctx_h = ['METRIC', 'MOORPARK', 'RANK', 'ST. AVG', 'VS AVG', 'TIER', 'CONTEXT']

    # helper for tier coloring without hexval
    def tier_p(r):
        if r <= 15:    return Paragraph('<b>Elite</b>', S(8, True, GREEN_TXT))
        elif r <= 35:  return Paragraph('<b>Above Avg</b>', S(8, True, colors.HexColor('#1a5c20')))
        elif r <= 65:  return Paragraph('<b>Average</b>', S(8, True, MID))
        elif r <= 85:  return Paragraph('<b>Below Avg</b>', S(8, True, colors.HexColor('#7b3b00')))
        else:          return Paragraph('<b>Concern</b>', S(8, True, RED_TXT))

    def crow(label, val, key, hb, unit='', note=''):
        r, tot, avg, diff = state_rank(key, val, hb)
        sign = '+' if diff > 0 else ''
        return [Paragraph(label, S(8)), f'{val:.1f}{unit}', f'#{r}/{tot}',
                f'{avg:.1f}{unit}', f'{sign}{diff:.1f}{unit}',
                tier_p(r), Paragraph(note, S(8))]

    ctx_rows = [
        crow('Off. Rating (ORTg)', ta['ortg'], 'ortg', True, '', 'Points scored per 100 possessions'),
        crow('Def. Rating (DRTg)', ta['drtg'], 'drtg', False, '', 'Points allowed per 100 poss, #13 state'),
        crow('Net Rating', ta['net_rtg'], 'net_rtg', True, '', 'ORTg minus DRTg, overall team quality'),
        crow('True Shooting%', ta['ts_pct'], 'ts_pct', True, '%', 'Overall shooting efficiency (all shot types)'),
        crow('Opp True Shooting%', ta['opp_ts_pct'], 'opp_ts_pct', False, '%', 'How well opponents shoot vs MPC'),
        crow('eFG% (offense)', ta['efg_pct'], 'efg_pct', True, '%', 'FG% adjusted for 3pt value'),
        crow('Opp eFG% (defense)', ta['opp_efg_pct'], 'opp_efg_pct', False, '%', 'Opponent eFG%, shooting suppression'),
        crow('Turnover % (offense)', ta['tov_pct'], 'tov_pct', False, '%', 'How often MPC turns it over'),
        crow('Opp Turnover % (def)', ta['opp_tov_pct'], 'opp_tov_pct', True, '%', 'How often MPC forces opponent TOs'),
        crow('Off. Reb % (offense)', ta['oreb_pct'], 'oreb_pct', True, '%', '% of own missed shots recovered'),
        crow('Def. Reb % (defense)', ta['dreb_pct'], 'dreb_pct', True, '%', '% of opp missed shots recovered'),
        crow('FT Rate (offense)', ta['ft_rate'], 'ft_rate', True, '', 'FTA per FGA, how often they draw fouls'),
        crow('Opp FT Rate (defense)', ta['opp_ft_rate'], 'opp_ft_rate', False, '', 'How often opponents draw fouls vs MPC'),
        crow('Pace (possessions/g)', ta['possessions'], 'pace', True, '', '34th fastest of 100, above average tempo'),
        crow('3PA Rate (style)', round(avgs['3PA'] / avgs['FGA'] * 100, 1) if avgs.get('FGA') else 0,
             'tpa_rate', True, '%', '3PA/FGA — top-10 statewide, jump-shooting identity'),
        crow('Assist Rate', ta.get('ast_rate', 0), 'ast_rate', True, '%', 'Ball movement; share of made FGs assisted'),
        crow('Assist-to-Turnover', round(avgs['AST'] / avgs['TO'], 2) if avgs.get('TO') else 0,
             'ast_tov', True, '', 'Passing vs. giveaways'),
        crow('NST% (offense)', round(max(avgs['TO'] - opp_avgs['STL'], 0) / max(ta['possessions'], 0.01) * 100, 1),
             'nst_pct', False, '%', 'Live-ball / unforced TOs — bottom-10, real flaw'),
        crow('Opp NST% (forced)', round(max(opp_avgs['TO'] - avgs['STL'], 0) / max(ta['possessions'], 0.01) * 100, 1),
             'opp_nst_pct', True, '%', 'Non-steal TOs forced — systemic pressure, elite'),
        crow('Steal % (defense)', ta.get('stl_pct', 0), 'stl_pct', True, '%', 'Possessions ended by a Moorpark steal'),
        crow('Block % (defense)', ta.get('blk_pct', 0), 'blk_pct', True, '%', 'Opponent shots blocked — modest rim protection'),
        crow('PPG', avgs['PTS'], 'ppg', True, '', ''),
        crow('Opp PPG (def)', opp_avgs['PTS'], 'oppg', False, '', ''),
    ]
    if _mp_bench is not None and BENCH:
        _bv = sorted(BENCH.values(), reverse=True)
        _br = next((i + 1 for i, v in enumerate(_bv) if v <= _mp_bench), len(_bv))
        _bavg = round(sum(_bv) / len(_bv), 1); _bd = round(_mp_bench - _bavg, 1)
        ctx_rows.append([Paragraph('Bench Points %', S(8)), f'{_mp_bench:.1f}%', f'#{_br}/{len(_bv)}',
                         f'{_bavg:.1f}%', f'{"+" if _bd > 0 else ""}{_bd:.1f}%', tier_p(_br),
                         Paragraph('Share of points from non-starters — depth', S(8))])

    ctx_cw = [1.65*inch, 0.75*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.9*inch, 1.55*inch]
    ct = Table([ctx_h]+ctx_rows, colWidths=ctx_cw)
    # Row colors based on tier
    row_colors = []
    for i, r_data in enumerate(ctx_rows):
        r_val = int(r_data[2].split('/')[0][1:])
        row_i = i + 1
        if r_val <= 15:
            row_colors.append(('BACKGROUND', (0,row_i),(-1,row_i), colors.HexColor('#f0fff4')))
        elif r_val >= 86:
            row_colors.append(('BACKGROUND', (0,row_i),(-1,row_i), colors.HexColor('#fff0f0')))
    ct.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), TH_BG),
        ('TEXTCOLOR', (0,0), (-1,0), WHITE),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (0,1), (0,-1), 'LEFT'),
        ('ALIGN', (6,1), (6,-1), 'LEFT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, ALT]),
        ('INNERGRID', (0,0), (-1,-1), 0.3, MGRAY),
        ('BOX', (0,0), (-1,-1), 0.5, TH_BG),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ] + row_colors))
    e.append(ct)
    e.append(Spacer(1, 14))
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — SYNERGY PLAY TYPE PROFILE (OFFENSE + DEFENSE)
# ═══════════════════════════════════════════════════════════════════════════════
def page_synergy_team():
    e = []
    e += section(
        'Synergy Sports — Play Type Profile',
        f'Play type breakdown across all {synergy_team["games_played"]} games. '
        'Offense: how Moorpark generates offense by play type. '
        'Defense: how opponents score against Moorpark by play type. '
        'T-Rank = percentile for time allocation vs. peers (how often they run this play). '
        'Pctile = PPP percentile rank — on offense higher is better; on defense higher means '
        'opponents were suppressed (i.e., better defense).'
    )

    RATING_COLORS = {
        'Excellent':     (GREEN_BG,                      GREEN_TXT),
        'Very Good':     (colors.HexColor('#c8e6c9'),    GREEN_TXT),
        'Good':          (YELLOW_BG,                     colors.HexColor('#5c4200')),
        'Average':       (colors.HexColor('#f5f5f5'),    MID),
        'Below Average': (RED_BG,                        RED_TXT),
        'Poor':          (colors.HexColor('#f5c6cb'),    RED_TXT),
    }

    col_w = [2.1*inch, 0.6*inch, 0.65*inch, 0.65*inch, 0.6*inch, 0.65*inch, 1.1*inch, 0.75*inch, 0.4*inch]
    hdr_cells = [Paragraph(h, S(8, True, WHITE, TA_CENTER)) for h in
                 ['Play Type', 'Poss', '%Time', 'T-Rank', 'PPP', 'Pctile', 'Rating', '2FG%', 'TO%']]

    def build_play_table(play_types, is_defense=False):
        sorted_pt = sorted(play_types, key=lambda x: x['poss'], reverse=True)
        rows = []
        dyn_style = []
        for i, pt in enumerate(sorted_pt):
            name = (pt['play_type']
                    .replace('Offensive Rebounds (Put Backs)', 'OREB / Put Backs')
                    .replace('Miscellaneous Plays', 'Miscellaneous'))
            two  = f"{pt['two_fg_pct']:.1f}%" if pt.get('two_fg_pct') is not None else '—'
            rating = pt.get('ppp_rating', '')
            bg, tc = RATING_COLORS.get(rating, (WHITE, BLACK))
            ri = i + 1  # 1-indexed row in table (row 0 = header)

            dyn_style += [
                ('BACKGROUND', (6, ri), (6, ri), bg),
                ('TEXTCOLOR',  (6, ri), (6, ri), tc),
                ('FONTNAME',   (6, ri), (6, ri), 'Helvetica-Bold'),
            ]
            ppp_val = pt['ppp']
            if is_defense:
                if ppp_val >= 1.0:
                    dyn_style += [('TEXTCOLOR',  (4, ri), (4, ri), RED_TXT),
                                  ('FONTNAME',   (4, ri), (4, ri), 'Helvetica-Bold')]
                elif ppp_val < 0.75:
                    dyn_style += [('TEXTCOLOR',  (4, ri), (4, ri), GREEN_TXT),
                                  ('FONTNAME',   (4, ri), (4, ri), 'Helvetica-Bold')]

            rows.append([
                Paragraph(name, S(8, color=BLACK)),
                str(pt['poss']),
                f"{pt['pct_time']:.1f}%",
                str(pt['time_rank']),
                f"{ppp_val:.3f}",
                str(pt['ppp_rank']),
                Paragraph(rating, S(8, True, tc, TA_CENTER)),
                two,
                f"{pt['to_pct']:.1f}%",
            ])

        base_style = [
            ('BACKGROUND',  (0,0),  (-1,0),  TH_BG),
            ('FONTSIZE',    (0,1),  (-1,-1), 8),
            ('ALIGN',       (0,0),  (-1,-1), 'CENTER'),
            ('ALIGN',       (0,1),  (0,-1),  'LEFT'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, ALT]),
            ('INNERGRID',   (0,0),  (-1,-1), 0.3, MGRAY),
            ('BOX',         (0,0),  (-1,-1), 0.5, TH_BG),
            ('TOPPADDING',  (0,0),  (-1,-1), 3),
            ('BOTTOMPADDING',(0,0), (-1,-1), 3),
            ('LEFTPADDING', (0,0),  (-1,-1), 4),
            ('RIGHTPADDING',(0,0),  (-1,-1), 4),
            ('VALIGN',      (0,0),  (-1,-1), 'MIDDLE'),
        ] + dyn_style

        t = Table([hdr_cells] + rows, colWidths=col_w)
        t.setStyle(TableStyle(base_style))
        return t

    # ── Offense ──────────────────────────────────────────────────────────────
    e.append(Spacer(1, 8))
    e.append(Paragraph('OFFENSE — How Moorpark Creates', S(10, True, BLUE)))
    e.append(Spacer(1, 4))
    e.append(build_play_table(synergy_team['offense']['play_types'], is_defense=False))

    # ── Defense ──────────────────────────────────────────────────────────────
    e.append(Spacer(1, 10))
    e.append(Paragraph('DEFENSE — How Opponents Score Against Moorpark', S(10, True, BLUE)))
    e.append(Paragraph(
        'PPP percentile (Pctile) reflects how well Moorpark holds opponents vs. other teams — '
        'higher pctile = better defense on that play type. PPP ≥ 1.0 highlighted in red (vulnerability).',
        S(8, False, MID, space_after=4)))
    e.append(Spacer(1, 4))
    e.append(build_play_table(synergy_team['defense']['play_types'], is_defense=True))

    # ── Key Takeaways ─────────────────────────────────────────────────────────
    e.append(Spacer(1, 10))
    e.append(Paragraph('KEY TAKEAWAYS', S(9, True, BLUE)))
    e.append(HR(GOLD, 1, 2, 4))

    insights = [
        (
            '<b>Offensive Identity:</b> Moorpark is a spot-up shooting team above all else — nearly '
            '30% of possessions are Spot-Up plays (80th pctile usage) at a Very Good 0.915 PPP. '
            'Handoffs are run at an extremely high frequency (94th pctile) with Good efficiency. '
            'Cuts are under-utilized but lethal (63.7% 2FG%). '
            'P&R Roll Man is the offense\'s glaring weak point (Poor, 12th pctile).',
            LGRAY
        ),
        (
            '<b>Defensive Strength:</b> Perimeter defense is elite — opponents shoot just 28.7% on '
            'Spot-Up 3-point attempts (Excellent, 86th pctile). Post-up and handoff defense are also '
            'Very Good. Moorpark generates unusual turnover pressure on Misc plays (opponent TO% = 72.1%).',
            WHITE
        ),
        (
            '<b>Primary Defensive Vulnerability — Interior &amp; Second Chances:</b> Moorpark gives up '
            '1.157 PPP on cuts (Average, only 33rd pctile; 58.2% 2FG%), and opponents convert second-chance '
            'opportunities at 60.2% (Average, 43rd pctile). By the play-type data, the defense is weakest '
            'on interior and second-chance scoring rather than on the perimeter.',
            RED_BG
        ),
    ]
    for text, bg in insights:
        tbl = Table([[Paragraph(text, S(8, color=BLACK))]], colWidths=[7.5*inch])
        tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), bg),
            ('BOX',           (0,0), (-1,-1), 0.5, BLUE),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
            ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ]))
        e.append(tbl)
        e.append(Spacer(1, 3))

    e.append(Spacer(1, 14))
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — BIG GAME PERFORMANCE + SITUATIONAL ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════
def page_big_games():
    e = []
    e += section('Performance in Big Games & Situational Analysis',
                 'How Moorpark performs against quality opponents, in close games, at home vs. away, and across the season arc.')

    # Core narrative
    critical = (
        'The most important context for evaluating Moorpark is <b>their record against '
        'quality opponents</b>. Against teams with a positive Net Rating (the top half of '
        'the CCCAA field), they went <b>5-10</b> with an average net rating of <b>-5.7</b>. '
        'Against teams with a negative Net Rating, they went <b>14-0</b> with an average '
        'net rating of +24.4. The pattern is clear: <b>they dominate inferior competition '
        'and struggle against elite teams</b>. They did not beat a single team ranked '
        'above +12 Net Rating all season. They went 0-5 against that group, with losses to '
        'West Valley (-21.6 net, their worst game of the year), San Bernardino Valley, '
        'East Los Angeles, and Ventura (twice, both by single digits).'
    )
    e.append(Paragraph(critical, S(9.5, space_after=8)))

    ventura = (
        'Ventura College was the opponent Moorpark could not beat. They met twice in '
        'WSC North play: Moorpark lost 76-84 on the road in January and 85-90 at home '
        'in February, both single-digit games. Moorpark\'s net rating in the two losses was '
        '-11.0 and -6.6 — two competitive losses to the same opponent.'
    )
    e.append(Paragraph(ventura, S(9.5, space_after=10)))

    # Splits grid
    e.append(Paragraph('<b>Situational Splits: Record and Average Net Rating</b>', S(9, True, BLUE, space_after=6)))

    e.append(splits_box('OVERALL', '19-10', avg_net(quality_games), ''))
    e.append(Spacer(1, 3))
    e.append(splits_box('HOME', rec(home_g), avg_net(home_g), f'{rec(home_g)}, strong home environment'))
    e.append(Spacer(1, 3))
    e.append(splits_box('AWAY', rec(away_g), avg_net(away_g), '7-4 away, solid road team'))
    e.append(Spacer(1, 3))
    e.append(splits_box('NEUTRAL', rec(neut_g), avg_net(neut_g), '3-3 neutral, competitive at tournament sites'))
    e.append(Spacer(1, 3))
    e.append(splits_box('CONFERENCE', rec(conf_g), avg_net(conf_g), '10-2 in WSC North'))
    e.append(Spacer(1, 3))
    e.append(splits_box('NON-CONFERENCE', rec(nconf), avg_net(nconf), '9-8 non-conf, average outside the league'))
    e.append(Spacer(1, 3))
    e.append(splits_box('vs. QUALITY OPPS (net > 0)', rec(good_opp), avg_net(good_opp), '5-10 vs top half of field'))
    e.append(Spacer(1, 3))
    e.append(splits_box('vs. WEAK OPPS (net ≤ 0)', rec(bad_opp), avg_net(bad_opp), '14-0 vs bottom half of field'))
    e.append(Spacer(1, 3))
    e.append(splits_box('FIRST HALF (G1-14)', rec(early_g), avg_net(early_g), '8-6 first half of season'))
    e.append(Spacer(1, 3))
    e.append(splits_box('SECOND HALF (G15-29)', rec(late_g), avg_net(late_g), '11-4 second half of season'))
    e.append(Spacer(1, 3))
    close_w = sum(1 for g in close_g if g['result']=='W')
    e.append(splits_box('CLOSE GAMES (≤8 pts)', f'{close_w}-{len(close_g)-close_w}',
                        avg_net(close_g), f'{len(close_g)} games decided by 8 or fewer'))

    # ── Quad splits ──────────────────────────────────────────────────────────
    e.append(Spacer(1, 10))
    e.append(Paragraph('<b>Quadrant Records (NCAA-style, scaled for 100 CCCAA teams)</b>',
                       S(9, True, BLUE, space_after=3)))
    e.append(Paragraph(
        'Q1A = elite opponents (top ~4%). Q1 = top-tier (top ~9%). '
        'Q2 = strong (top ~21%). Q3 = adequate (top ~45%). Q4 = lower-tier. '
        'All thresholds are location-adjusted (harder to reach Q1 at Home than Away).',
        S(8, False, MID, space_after=4)))
    _q1_all = [g for g in quad_games['Q1A']+quad_games['Q1']]
    _q12    = _q1_all + quad_games['Q2']
    _q1_w   = quad_rec['Q1A'][0]+quad_rec['Q1'][0]
    _q1_l   = quad_rec['Q1A'][1]+quad_rec['Q1'][1]
    _q12_w  = _q1_w + quad_rec['Q2'][0]
    _q12_l  = _q1_l + quad_rec['Q2'][1]
    e.append(splits_box('Q1A (Elite — Top 4%)',
        f"{quad_rec['Q1A'][0]}-{quad_rec['Q1A'][1]}",
        avg_net(quad_games['Q1A']),
        f"{len(quad_games['Q1A'])} game(s) vs elite opponents"))
    e.append(Spacer(1, 3))
    e.append(splits_box('Q1 (Top-Tier — Top 9%, incl. Q1A)',
        f'{_q1_w}-{_q1_l}',
        avg_net(_q1_all),
        f'{len(_q1_all)} game(s) vs top-tier opponents'))
    e.append(Spacer(1, 3))
    e.append(splits_box('Q2 (Strong — Top 21%)',
        f"{quad_rec['Q2'][0]}-{quad_rec['Q2'][1]}",
        avg_net(quad_games['Q2']),
        f"{len(quad_games['Q2'])} game(s) vs strong opponents"))
    e.append(Spacer(1, 3))
    e.append(splits_box('Q1+Q2 Combined',
        f'{_q12_w}-{_q12_l}',
        avg_net(_q12),
        f'{len(_q12)} game(s) vs Q1 or Q2 opponents'))
    e.append(Spacer(1, 3))
    e.append(splits_box('Q3 (Adequate — Top 45%)',
        f"{quad_rec['Q3'][0]}-{quad_rec['Q3'][1]}",
        avg_net(quad_games['Q3']),
        f"{len(quad_games['Q3'])} game(s) vs adequate opponents"))
    e.append(Spacer(1, 3))
    e.append(splits_box('Q4 (Lower-Tier)',
        f"{quad_rec['Q4'][0]}-{quad_rec['Q4'][1]}",
        avg_net(quad_games['Q4']),
        f"{len(quad_games['Q4'])} game(s) vs lower-tier opponents"))

    e.append(Spacer(1, 8))
    # Quad narrative
    _q1a_opp = ', '.join(g['opponent'] for g in quad_games['Q1A']) or 'none'
    _q1_only_opp = ', '.join(g['opponent'] for g in quad_games['Q1']) or 'none'
    _q2_opp = ', '.join(g['opponent'] for g in quad_games['Q2']) or 'none'
    e.append(Paragraph(
        f'<b>Quad Context:</b> Moorpark went <b>{_q1_w}-{_q1_l} in Q1 games</b> and '
        f'<b>{_q12_w}-{_q12_l} in Q1+Q2 combined</b>. '
        f'Their lone Q1A game was a road loss at West Valley (#2 statewide). '
        f'Q1 losses: San Bernardino Valley (Away) and West Valley (Away) — both on the road against '
        f'top-10 programs. Q2 opponents were East Los Angeles (Neutral, L), Ventura (Away, L), '
        f'and Allan Hancock (Away, W). '
        f'They went <b>{quad_rec["Q3"][0]}-{quad_rec["Q3"][1]} in Q3</b> — a .500 record that '
        f'reflects real inconsistency against mid-tier competition (Palomar twice, Saddleback, Bakersfield, Ventura at home). '
        f'Their <b>{quad_rec["Q4"][0]}-{quad_rec["Q4"][1]} record in Q4</b> is dominant — one loss '
        f'(Irvine Valley at home, final game) the only blemish.',
        S(9, space_after=6)))

    e.append(Spacer(1, 14))

    # Quality wins table
    e += section('Best Wins: Opponent Quality Context')
    big_wins = sorted([g for g in quality_games if g['result']=='W'],
                      key=lambda x: x['opp_net'] or -999, reverse=True)
    bw_h = ['DATE', 'OPPONENT', 'SCORE', 'OPP NET RTG', 'MPC NET RTG', 'NOTES']
    bw_r = []
    for g in big_wins[:8]:
        opp_s = f"{g['opp_net']:+.1f}" if g['opp_net'] is not None else 'N/A'
        note = ''
        if g['opp_net'] and g['opp_net'] > 10:
            note = 'Quality Win'
        elif abs(g['margin']) <= 5:
            note = 'Close W'
        bw_r.append([g['date'], g['opponent'], f"{g['team_score']}-{g['opponent_score']}",
                     opp_s, f"{g['net']:+.1f}", note])
    bw_cw = [0.8*inch, 1.9*inch, 0.75*inch, 1.0*inch, 1.0*inch, 1.55*inch]
    e.append(metric_table(bw_h, bw_r, bw_cw))
    e.append(Spacer(1, 10))

    # Losses table
    e += section('All Losses')
    loss_h = ['DATE', 'OPPONENT', 'SCORE', 'OPP NET RTG', 'MPC NET RTG', 'LOCATION']
    loss_r = []
    for g in losses:
        opp_s = f"{g['opp_net']:+.1f}" if g['opp_net'] is not None else 'N/A'
        loss_r.append([g['date'], g['opponent'], f"{g['team_score']}-{g['opponent_score']}",
                       opp_s, f"{g['net']:+.1f}", g['location']])
    loss_cw = [0.8*inch, 1.9*inch, 0.8*inch, 1.0*inch, 1.0*inch, 1.5*inch]
    lt = metric_table(loss_h, loss_r, loss_cw)
    # Color the net rating column red for losses
    # (already in metric_table rowbackgrounds alternation)
    e.append(lt)
    e.append(Spacer(1, 8))
    e.append(Paragraph(
        '<i>Common thread in losses: every single loss came against a team with a positive '
        'Net Rating. Moorpark has zero losses to programs below the CCCAA midpoint. '
        'Their losses were not flukes. Every loss came against a team with a positive net rating.</i>',
        S(8.5, italic=True)))
    e.append(Spacer(1, 14))
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — FULL GAME LOG
# ═══════════════════════════════════════════════════════════════════════════════
def page_game_log():
    e = []
    e += section('Complete Game Log, 2025-26',
                 'All 29 games. Net Rtg = (MPC ORTg − MPC DRTg) on a per-100-possessions basis. Green = dominant win. Red = loss.')

    gl_h = ['#', 'DATE', 'OPPONENT', 'LOC', 'RES', 'SCORE', 'ORTg', 'DRTg', 'NET', 'PACE', 'CONF', 'OPP NET']
    gl_r, rc = [], []
    loc_map = {'Home':'H','Away':'A','Neutral':'N'}
    for i, g in enumerate(quality_games):
        net = g['net']
        opp_s = f"{g['opp_net']:+.1f}" if g['opp_net'] is not None else '—'
        gl_r.append([
            str(i+1), g['date'], g['opponent'][:22], loc_map.get(g['location'],''),
            g['result'], f"{g['team_score']}-{g['opponent_score']}",
            f"{g['ortg']:.1f}", f"{g['drtg']:.1f}",
            f"{net:+.1f}", f"{g['tempo']:.1f}",
            'Y' if g.get('is_conference') else '', opp_s
        ])
        ri = i + 1
        if g['result'] == 'W' and net > 20:
            rc.append(('BACKGROUND', (8,ri),(8,ri), GREEN_BG))
        elif g['result'] == 'L':
            rc.append(('BACKGROUND', (4,ri),(4,ri), RED_BG))
            rc.append(('BACKGROUND', (8,ri),(8,ri), RED_BG))
        if g.get('is_conference'):
            rc.append(('FONTNAME', (10,ri),(10,ri), 'Helvetica-Bold'))
            rc.append(('TEXTCOLOR', (10,ri),(10,ri), BLUE))

    gl_cw = [0.28*inch,0.72*inch,2.1*inch,0.32*inch,0.38*inch,0.65*inch,
             0.52*inch,0.52*inch,0.58*inch,0.52*inch,0.42*inch,0.72*inch]
    t = Table([gl_h]+gl_r, colWidths=gl_cw)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,0), TH_BG),
        ('TEXTCOLOR', (0,0),(-1,0), WHITE),
        ('FONTNAME', (0,0),(-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0),(-1,0), 7),
        ('FONTSIZE', (0,1),(-1,-1), 7),
        ('ALIGN', (0,0),(-1,-1), 'CENTER'),
        ('ALIGN', (2,1),(2,-1), 'LEFT'),
        ('ROWBACKGROUNDS', (0,1),(-1,-1), [WHITE, ALT]),
        ('INNERGRID', (0,0),(-1,-1), 0.25, MGRAY),
        ('BOX', (0,0),(-1,-1), 0.5, TH_BG),
        ('TOPPADDING', (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
        ('LEFTPADDING', (0,0),(-1,-1), 3),
        ('RIGHTPADDING', (0,0),(-1,-1), 3),
    ] + rc))
    e.append(t)
    e.append(Spacer(1, 10))

    # Monthly summary
    e += section('Monthly Performance Summary')
    mo_h = ['MONTH', 'GP', 'PPG', 'OPP PPG', 'MARGIN', 'ORTg', 'DRTg', 'NET', 'eFG%', 'TOV%', 'OREB%', 'TEMPO']
    mo_r = []
    for mo in ['Nov','Dec','Jan','Feb']:
        ms = monthly.get(mo, {})
        if not ms: continue
        net = ms.get('net_rtg', 0)
        mo_r.append([mo, str(ms.get('gp','')),
                     f"{ms.get('ppg',0):.1f}", f"{ms.get('oppg',0):.1f}",
                     f"{ms.get('margin',0):+.1f}",
                     f"{ms.get('ortg',0):.1f}", f"{ms.get('drtg',0):.1f}",
                     f"{net:+.1f}",
                     f"{ms.get('efg_pct',0):.1f}%", f"{ms.get('tov_pct',0):.1f}%",
                     f"{ms.get('oreb_pct',0):.1f}%", f"{ms.get('tempo',0):.1f}"])
    mo_cw = [0.55*inch,0.35*inch,0.6*inch,0.7*inch,0.65*inch,0.62*inch,
             0.62*inch,0.58*inch,0.62*inch,0.62*inch,0.68*inch,0.6*inch]
    e.append(metric_table(mo_h, mo_r, mo_cw))
    e.append(Paragraph(
        '<i>Net Rating improved from +0.8 in November to +14.9 in February. '
        'TOV% fell from 16.9% to 12.6%. OREB% jumped from 51.2% to 55.7%. '
        'Moorpark in February was a significantly better team than Moorpark in November.</i>',
        S(8.5, italic=True, space_after=0)))
    e.append(Spacer(1, 14))
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — PLAYER ROTATION + TABLES
# ═══════════════════════════════════════════════════════════════════════════════
def page_rotation():
    e = []
    e += section('Player Rotation & Impact Ratings',
                 'Individual ratings are box-score estimates (Dean Oliver method) of offensive and defensive efficiency per 100 possessions. '
                 'Net Rtg = individual ORtg minus individual DRtg.')

    rot_h = ['#', 'PLAYER', 'POS', 'GP', 'MPG', 'ON-CT ORTg', 'ON-CT DRTg', 'NET RTG', 'INTERP.']
    rot_r, rc = [], []
    rated = [n for n in rotation if player_map[n]['rating']]
    for i, name in enumerate(rated):
        p = player_map[name]
        r = p['rating']
        net = r.get('net', 0)
        rname = r.get('name', '')
        jersey = rname.split()[0] if rname.startswith('#') else '—'
        interp = ('Team dominant' if net > 20 else
                  'Solid positive' if net > 10 else
                  'Slight positive' if net > 0 else
                  'Neutral' if net > -5 else 'Negative impact')
        rot_r.append([jersey, Paragraph(name, S(8)), p['pos'],
                      str(r.get('games','')), f"{r.get('mpg',0):.1f}",
                      f"{r.get('ortg',0):.1f}", f"{r.get('drtg',0):.1f}",
                      f"{net:+.1f}", Paragraph(interp, S(8))])
        ri = i + 1
        if net > 20:
            rc.append(('BACKGROUND', (7,ri),(8,ri), GREEN_BG))
            rc.append(('FONTNAME', (7,ri),(7,ri), 'Helvetica-Bold'))
        elif net < 0:
            rc.append(('BACKGROUND', (7,ri),(8,ri), RED_BG))

    rot_cw = [0.45*inch,1.7*inch,0.55*inch,0.42*inch,0.55*inch,0.85*inch,0.85*inch,0.75*inch,1.35*inch]
    t = Table([rot_h]+rot_r, colWidths=rot_cw)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,0), TH_BG),
        ('TEXTCOLOR', (0,0),(-1,0), WHITE),
        ('FONTNAME', (0,0),(-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0),(-1,0), 8),
        ('FONTSIZE', (0,1),(-1,-1), 8),
        ('ALIGN', (0,0),(-1,-1), 'CENTER'),
        ('ALIGN', (1,1),(1,-1), 'LEFT'),
        ('ALIGN', (8,1),(8,-1), 'LEFT'),
        ('ROWBACKGROUNDS', (0,1),(-1,-1), [WHITE, ALT]),
        ('INNERGRID', (0,0),(-1,-1), 0.3, MGRAY),
        ('BOX', (0,0),(-1,-1), 0.5, TH_BG),
        ('TOPPADDING', (0,0),(-1,-1), 4),
        ('BOTTOMPADDING', (0,0),(-1,-1), 4),
        ('LEFTPADDING', (0,0),(-1,-1), 4),
        ('RIGHTPADDING', (0,0),(-1,-1), 4),
    ] + rc))
    e.append(t)
    e.append(Spacer(1, 6))
    e.append(Paragraph(
        '<b>Reading individual ratings:</b> ORtg (offensive rating) estimates points produced per 100 possessions '
        'based on a player\'s scoring, assists, and offensive rebounding. DRtg (defensive rating) estimates opponent '
        'points allowed per 100 possessions based on steals, blocks, and defensive rebounds. '
        'Net Rtg = ORtg minus DRtg. These are box-score estimates, not lineup-based on/off data.',
        S(8, italic=True, space_after=8)))

    # Shooting table
    e += section('Shooting Breakdown: All Rotation Players')
    sh_h = ['PLAYER', 'POS', 'PPG', 'FG%', '3P%', '3PA/G', '3PAr', 'FT%', 'eFG%', 'TS%']
    sh_r = []
    for name in rotation:
        p = player_map[name]
        avg = p['avg']; adv = p['adv']
        if avg.get('MIN',0) < 5: continue
        tpar = round(avg.get('3PA',0)/max(avg.get('FGA',0.01),0.01)*100,0)
        sh_r.append([name, p['pos'],
                     f"{avg.get('PTS',0):.1f}",
                     f"{avg.get('FG%',0):.1f}%",
                     f"{avg.get('3P%',0):.1f}%",
                     f"{avg.get('3PA',0):.1f}",
                     f"{tpar:.0f}%",
                     f"{avg.get('FT%',0):.1f}%",
                     f"{adv.get('efg_pct',0):.1f}%",
                     f"{adv.get('ts_pct',0):.1f}%"])
    sh_cw = [1.55*inch,0.52*inch,0.5*inch,0.58*inch,0.58*inch,0.6*inch,0.55*inch,0.58*inch,0.63*inch,0.62*inch]
    e.append(metric_table(sh_h, sh_r, sh_cw))
    e.append(Spacer(1, 8))

    # Defense/rebounding table
    e += section('Rebounding & Defense: All Rotation Players')
    def_h = ['PLAYER', 'POS', 'RPG', 'OREB', 'DREB', 'OREB%', 'STL', 'BLK', 'PF/G', 'TOV%']
    def_r = []
    for name in rotation:
        p = player_map[name]
        avg = p['avg']; adv = p['adv']
        if avg.get('MIN',0) < 5: continue
        def_r.append([name, p['pos'],
                      f"{avg.get('REB',0):.1f}",
                      f"{avg.get('OREB',0):.1f}",
                      f"{avg.get('DREB',0):.1f}",
                      f"{adv.get('oreb_pct',0):.1f}%",
                      f"{avg.get('STL',0):.1f}",
                      f"{avg.get('BLK',0):.1f}",
                      f"{avg.get('PF',0):.1f}",
                      f"{adv.get('tov_pct',0):.1f}%"])
    def_cw = [1.55*inch,0.52*inch,0.5*inch,0.55*inch,0.55*inch,0.65*inch,0.5*inch,0.5*inch,0.55*inch,0.62*inch]
    e.append(metric_table(def_h, def_r, def_cw))
    e.append(Spacer(1, 14))
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGES 6+ — INDIVIDUAL PLAYER PROFILES
# ═══════════════════════════════════════════════════════════════════════════════
def page_player_profiles():
    e = []
    e += section('Individual Player Profiles',
                 'Profiled players average 6+ PPG or start a majority of games. '
                 'Low-scoring starters are included so defenders know who they can help off of. '
                 'Each profile leads with a scouting narrative followed by complete stats.')

    profiled = [
        n for n in rotation
        if player_map[n]['avg'].get('PTS', 0) > 5.9 or is_starter(n)
    ]
    # Flag players who qualify only via starter status — low offensive threat
    starter_only = {
        n for n in profiled
        if player_map[n]['avg'].get('PTS', 0) <= 5.9 and is_starter(n)
    }

    # Pre-built narratives for key players
    narratives = {
        'Josh Castaniero': (
            'Castaniero is not a scorer (6.7 PPG, #291 statewide) '
            'but a <b>top-75 playmaker by assist rate</b> (4.9 APG, AST Rate 27.5% — #63 statewide among 467 Min% ≥30% players). '
            'Synergy shot data confirms he is a high-volume 3-point shooter: <b>88.8% of his '
            'jumpers are long 3s (95 attempts)</b>, but his efficiency is only <b>Average '
            '(27.4% FG, 35th pctile)</b> — opponents can sag slightly without fully conceding '
            'the perimeter. His catch-and-shoot (70.1% of jumpers) grades out Average as well '
            '(26.7% FG, 31st pctile). The hidden threat: when he does attack the basket, he is '
            '<b>Excellent at the rim (67.3% FG, 90th pctile, 1.35 PPS)</b> on 52 attempts — '
            'forcing him off his 3-point spot invites a dangerous drive. Short jumpers are '
            'exploitable (30.0% FG, 27th pctile — Below Average). '
            'He is the engine of the offense, setting everyone else up. His individual Net Rating '
            'of <b>+26.3</b> is the best on the roster. He also leads the team in rebounds for a '
            'guard (5.2 RPG). His turnover rate is high for a primary creator (21.1% TOV%), and the '
            'offense runs through him — the data ties his ball-handling directly to the team\'s output.'
        ),
        'Eric Kubel': (
            'Kubel is Moorpark\'s leading scorer at 13.8 PPG '
            '(<b>#66 statewide</b> among 394 qualifying players). He scores almost exclusively '
            'as an off-ball mover — his most common play types are <b>catch-and-shoot spot-up '
            '3s</b>, transition wing runs, and handoffs. His dribble creation is minimal: '
            'he is below average in isolation (3% of possessions) and almost never runs '
            'pick-and-roll. His play-types show <b>almost no self-created offense</b> — his scoring '
            'is essentially all catch-and-shoot and off-ball. '
            'His turnover rate is excellent (TOV% 11.5%, #42 statewide among 467 Min% ≥30% players) so he won\'t '
            'give the ball away, but he\'s not going to beat you off the dribble either.'
        ),
        'Roman Finney': (
            'Finney is Moorpark\'s second-most efficient contributor despite his unassuming '
            '10.0 PPG line. At 52.1% FG with virtually no three-point attempts (0.6 3PA/G), '
            'he is a <b>high-efficiency interior scorer</b> who gets to the line (3.2 FTA/G). '
            'Synergy data confirms his dominance in the paint: <b>67.9% of his attempts come '
            'at the rim (57.7% FG, 1.15 PPS — 60th pctile)</b>. He excels in transition '
            '(1.212 PPP, 86th pctile — Excellent) and runs P&R as a ball handler '
            '(47 poss, 16.6%, 70th pctile). His catch-and-shoot is exploitable (15th pctile, 25.0% FG). '
            'His TOV% of 12.3% ranks <b>#57 statewide</b> and his individual Net Rating of '
            '<b>+24.4</b> is second on the team. He also leads the team in steals at 1.2 SPG.'
        ),
        'Noah Cotton': (
            'Cotton is Moorpark\'s most dangerous perimeter shooter, despite only averaging '
            '8.7 PPG in 15.6 minutes. His <b>39.2% three-point shooting</b> ranks <b>#43 of 367 '
            'CCCAA players</b> with enough attempts to qualify. Elite shooter. '
            'He also has the best turnover rate on the roster (TOV% 9.9%, <b>#23 statewide</b>). '
            'In just 15.6 MPG, his individual Net Rating is <b>+18.4</b>. He is dangerous precisely '
            'because of his shooting efficiency. He is not high-volume, but he punishes you when '
            'he\'s open. Opponents must track him on every possession off the ball.'
        ),
        'Jake Field': (
            'Field is a do-everything wing who grades out as average across most metrics but '
            'provides reliability and versatility. He\'s a capable 3-point shooter (37.4%, '
            '<b>#68 statewide</b>) who also rebounds for his position (3.2 RPG). His individual '
            'Net Rating of +5.1 is the lowest among the top-6, suggesting he is the weakest '
            'link in the primary rotation. A turnover rate of 16.9% (slightly high) '
            'and good FT% (89.3%) show competitive instincts in close games. His individual ORtg of 96.2 '
            'is the lowest of any starter, reflecting below-average scoring efficiency.'
        ),
        'Dominique Brutus': (
            'Brutus shoots <b>61.1% FG</b> as a bench big in 14.3 minutes. He takes no 3-pointers, gets '
            'to the line at a high rate (FT Rate 77.8), and gobbles up offensive rebounds '
            '(OREB% 15.9%). His individual Net Rating of <b>+25.8</b> is second only to '
            'Castaniero, which raises the question of why he doesn\'t play more. Foul '
            'trouble is likely the answer (1.9 PF/G in 14 minutes = high foul rate). '
            'His high TOV% (30.0%) also limits his floor time. When he\'s on the court and '
            'not fouling, he is one of the most impactful players on the roster.'
        ),
        'Jozef Zlocha': (
            'Zlocha is a stretch big who provides a unique combination for a front-court '
            'player: <b>52% overall FG and 40.6% from 3</b> (1.2 3PA/G). He is a legitimate '
            'floor-spacer who can also operate in the post (3.3 RPG, 0.3 BLK/G). His TS% '
            'of 60.8% is the highest of any Moorpark player with significant minutes. '
            'Individual Net Rating of <b>+21.1</b> confirms he is one of the team\'s best '
            'contributors in limited time (13.0 MPG). The scouting challenge: you have to '
            'guard him at the 3-point line, which pulls his defender away from the paint.'
        ),
        'Tidiane Sy': (
            'Sy is a rotation combo guard who provides minutes and some scoring versatility '
            '(5.8 PPG in 16.0 MPG) but grades out as below average across most categories. '
            'His TS% of 48.7% (307th of 394 statewide) and 3P% of 28.2% indicate below-average '
            'shooting efficiency. His individual Net Rating of +8.3 is positive but modest. '
            'He is most useful as a defensive presence: 0.4 SPG relative to his limited '
            'offensive burden, while his offensive role is limited (low usage, below-average shooting).'
        ),
        'Markus Steele': (
            'Steele is a physical interior reserve who contributes almost nothing offensively '
            '(3.4 PPG, 46.4% FG primarily on dunks/layups, no 3-point game) but is a '
            'legitimate interior presence: 5.4 RPG and <b>0.8 BPG in only 14.1 minutes</b> '
            '(high block rate). His individual Net Rating of +18.8 reflects strong defensive '
            'efficiency estimates — his block and defensive rebounding rates are the primary driver. He\'s a limited-minutes energy big '
            'who shot 83.3% from the free throw line in small samples.'
        ),
    }

    default_narrative = (
        'Role player contributing bench minutes. See stat lines for individual performance details.'
    )

    for idx, name in enumerate(profiled):
        mark = len(e)                       # wrap this player's flowables as one unit
        p = player_map[name]
        avg = p['avg']; tot = p['tot']; adv = p['adv']; rat = p['rating']
        pos = p['pos']; gp = avg.get('games', 0); mpg = avg.get('MIN', 0)

        rname = rat.get('name', name) if rat else name
        jersey = rname.split()[0] if rname and rname.startswith('#') else ''
        net_val = rat.get('net', 0) if rat else 0
        ortg_val = rat.get('ortg', 0) if rat else 0
        drtg_val = rat.get('drtg', 0) if rat else 0

        # Player role label
        usage_pct = adv.get('usage_pct', 0)
        role_label, role_color = kenpom_player_role(usage_pct, mpg)

        # Player header (ORtg / DRtg / Net merged into right column)
        sign = '+' if net_val >= 0 else ''
        net_color_hex = '#1a5c30' if net_val > 10 else ('#7b1b1b' if net_val < 0 else '#555577')
        p_hdr = Table([[
            Paragraph(f'{jersey}  {name.upper()}', S(11, True, WHITE)),
            Paragraph(
                f'{pos}  ·  {pos_full.get(pos, pos)}<br/>'
                f'<font color="{role_color}"><b>{role_label}</b></font>  '
                f'<font color="{role_color}">({usage_pct:.1f}% poss)</font>',
                S(9, False, GOLD, TA_CENTER)
            ),
            Paragraph(
                f'{gp} GP  ·  {mpg:.1f} MPG<br/>'
                f'<font color="#888888">ORtg {ortg_val:.1f}  ·  DRtg {drtg_val:.1f}  ·  </font>'
                f'<font color="{net_color_hex}"><b>Net {sign}{net_val:.1f}</b></font>',
                S(8.5, False, colors.HexColor('#aaaaaa'), TA_RIGHT)
            ),
        ]], colWidths=[2.8*inch, 2.5*inch, 2.2*inch])
        p_hdr.setStyle(TableStyle([
            ('BACKGROUND', (0,0),(-1,-1), DARK),
            ('TOPPADDING', (0,0),(-1,-1), 8),
            ('BOTTOMPADDING', (0,0),(-1,-1), 8),
            ('LEFTPADDING', (0,0),(-1,-1), 10),
            ('RIGHTPADDING', (0,0),(-1,-1), 10),
            ('VALIGN', (0,0),(-1,-1), 'MIDDLE'),
        ]))
        e.append(p_hdr)

        # Archetype row — ONLY for players with real Synergy data. Two computed
        # labels: the Synergy archetype (from Synergy play-types) and the bball-index
        # archetype (from Synergy shot/play data). No box-score fallback: players
        # without Synergy data show their box-score position only (in the header above).
        arch = synergy_arch.get(name)
        if arch:
            syn_label = synergy_archetype(pos, arch, tot, player_map[name]['avg'].get('AST', 0))
            arch_cells = [Paragraph(f'<b>Synergy Archetype:</b>  {syn_label}', S(8.5, False, GOLD))]
            bi = bball_index_archetype(pos, adv, tot, arch)
            if bi:
                arch_cells.append(Paragraph(f'<b>bball-index Archetype:</b>  {bi}',
                                            S(8.5, False, colors.HexColor('#6fa8ff'))))
            if arch.get('scoring_summary'):
                arch_cells.append(Paragraph(arch['scoring_summary'], S(7.5, False, colors.HexColor('#aab8d0'))))
            arch_row = Table([[c] for c in arch_cells], colWidths=[7.5*inch])
            arch_row.setStyle(TableStyle([
                ('BACKGROUND', (0,0),(-1,-1), colors.HexColor('#0d1a2e')),
                ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
                ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
                ('BOX',(0,0),(-1,-1),0.5,BLUE),
            ]))
            e.append(arch_row)
            # Drive direction row (Synergy-only; box-score profiles have no PBP)
            # Drive-direction FLAG — only surfaced for LEFT-dominant drivers.
            # Right-hand dominance is the norm and not a useful tell, so it's never
            # flagged. Handles both Synergy schemas: overall (drives_left/right_poss)
            # and the spot-up/iso split (spot_up_/iso_left/right_poss).
            dd = arch.get('drive_direction') if arch else None
            if dd:
                lp = dd.get('drives_left_poss',
                            (dd.get('spot_up_left_poss', 0) + dd.get('iso_left_poss', 0)))
                rp = dd.get('drives_right_poss',
                            (dd.get('spot_up_right_poss', 0) + dd.get('iso_right_poss', 0)))
                mid = dd.get('drives_straight_poss', 0)        # middle/straight drives
                dtot = lp + rp                                  # left vs right only (middle excluded)
                if dtot >= 10 and lp > rp and (lp / dtot) >= 0.55:   # left-DOMINANT, not just >50% of all
                    share = round(lp / dtot * 100)
                    lppp = dd.get('drives_left_ppp', dd.get('spot_up_left_ppp', 0)) or 0
                    rppp = dd.get('drives_right_ppp', dd.get('spot_up_right_ppp', 0)) or 0
                    eff = ('  He is also more efficient going left.'
                           if lppp > rppp + 0.05 else
                           '  He is less efficient going left.'
                           if rppp > lppp + 0.05 else '')
                    note = dd.get('scouting_note', '')
                    midtxt = f', {mid} middle' if mid else ''
                    flag_txt = (f'<b>&#9668; LEFT-HAND DOMINANT DRIVER &mdash;</b>  '
                                f'Of his directional drives, {share}% go left ({lp} left vs {rp} right{midtxt}).' + eff
                                + (f'<br/><i>{note}</i>' if note else ''))
                    dd_row = Table([[Paragraph(flag_txt, S(8, False, colors.HexColor('#ffd54f')))]],
                                   colWidths=[7.5*inch])
                    dd_row.setStyle(TableStyle([
                        ('BACKGROUND', (0,0),(-1,-1), colors.HexColor('#2a1500')),
                        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
                        ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
                        ('BOX',(0,0),(-1,-1),0.8,colors.HexColor('#e8a000')),
                    ]))
                    e.append(dd_row)
            # Shot types row (Synergy-only)
            st_data = arch.get('shot_types') if arch else None
            if st_data:
                rim_fg   = st_data.get('at_rim_fg_pct', 0)
                rim_rank = st_data.get('at_rim_pps_rank', 0)
                rim_rtg  = st_data.get('at_rim_pps_rating', '')
                rim_att  = st_data.get('at_rim_att', 0)
                cs_fg    = st_data.get('catch_shoot_fg_pct', 0)
                cs_rank  = st_data.get('catch_shoot_pps_rank', 0)
                cs_rtg   = st_data.get('catch_shoot_pps_rating', '')
                dj_fg    = st_data.get('dribble_jumper_fg_pct', 0)
                dj_rank  = st_data.get('dribble_jumper_pps_rank', 0)
                dj_rtg   = st_data.get('dribble_jumper_pps_rating', '')
                thr_fg   = st_data.get('three_pt_fg_pct', 0)
                thr_rank = st_data.get('three_pt_pps_rank', 0)
                thr_rtg  = st_data.get('three_pt_pps_rating', '')
                thr_att  = st_data.get('three_pt_att', 0)
                st_note  = st_data.get('scouting_note', '')
                # Shot Profile — 4-column mini-table
                _TEAL     = colors.HexColor('#b2dfdb')
                _TEAL_DK  = colors.HexColor('#001a18')
                _TEAL_BD  = colors.HexColor('#26a69a')
                rim_lbl = f'AT RIM ({rim_att} att)' if rim_att else 'AT RIM'
                thr_lbl = f'3-PT ({thr_att} att)' if thr_att else '3-PT'
                shot_inner = Table([
                    [
                        Paragraph(rim_lbl,           S(6.5, True, _TEAL, TA_CENTER)),
                        Paragraph('CATCH & SHOOT',   S(6.5, True, _TEAL, TA_CENTER)),
                        Paragraph('DRIB. JUMPER',    S(6.5, True, _TEAL, TA_CENTER)),
                        Paragraph(thr_lbl,           S(6.5, True, _TEAL, TA_CENTER)),
                    ],
                    [
                        Paragraph(f'<b>{rim_fg:.1f}%</b>  <font color="#b2dfdb">{rim_rtg}</font>',  S(8.5, False, WHITE, TA_CENTER)),
                        Paragraph(f'<b>{cs_fg:.1f}%</b>  <font color="#b2dfdb">{cs_rtg}</font>',   S(8.5, False, WHITE, TA_CENTER)),
                        Paragraph(f'<b>{dj_fg:.1f}%</b>  <font color="#b2dfdb">{dj_rtg}</font>',   S(8.5, False, WHITE, TA_CENTER)),
                        Paragraph(f'<b>{thr_fg:.1f}%</b>  <font color="#b2dfdb">{thr_rtg}</font>', S(8.5, False, WHITE, TA_CENTER)),
                    ],
                ], colWidths=[1.875*inch]*4)
                shot_inner.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), _TEAL_DK),
                    ('INNERGRID',  (0,0), (-1,-1), 0.3, _TEAL_BD),
                    ('BOX',        (0,0), (-1,-1), 0.5, _TEAL_BD),
                    ('TOPPADDING',    (0,0), (-1,-1), 4),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                    ('LEFTPADDING',   (0,0), (-1,-1), 4),
                    ('RIGHTPADDING',  (0,0), (-1,-1), 4),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ]))
                e.append(shot_inner)
                if st_note:
                    note_row = Table([[Paragraph(f'<i>{st_note}</i>', S(7.5, False, _TEAL))]], colWidths=[7.5*inch])
                    note_row.setStyle(TableStyle([
                        ('BACKGROUND',    (0,0), (-1,-1), _TEAL_DK),
                        ('TOPPADDING',    (0,0), (-1,-1), 3),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                        ('LEFTPADDING',   (0,0), (-1,-1), 10),
                        ('RIGHTPADDING',  (0,0), (-1,-1), 10),
                        ('BOX',           (0,0), (-1,-1), 0.5, _TEAL_BD),
                    ]))
                    e.append(note_row)
        if name in starter_only:
            gs = _gs_count.get(name, 0)
            l5 = _last5_gs.get(name, 0)
            gs_note = f'Started {gs}/{_total_games} games this season'
            if l5 >= 3:
                gs_note += f' · started {l5} of last 5'
            warn_row = Table([[
                Paragraph(f'⚠  Low-scoring starter — {gs_note}', S(8.5, False, colors.HexColor('#e8a000'))),
                Paragraph('Opponents can help off this player aggressively.', S(8.5, italic=True, color=MID, align=TA_RIGHT)),
            ]], colWidths=[4.2*inch, 3.3*inch])
            warn_row.setStyle(TableStyle([
                ('BACKGROUND', (0,0),(-1,-1), colors.HexColor('#1a1200')),
                ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
                ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
                ('BOX',(0,0),(-1,-1),0.5,colors.HexColor('#e8a000')),
            ]))
            e.append(warn_row)

        # Advanced stat values used in both the dynamic context paragraph and removed adv_st row
        ind_ortg_v = adv.get('ind_ortg', 0)
        ind_drtg_v = adv.get('ind_drtg', 0)
        usage_v    = adv.get('usage_pct', 0)  # same as usage_pct above
        oreb_v     = adv.get('oreb_pct', 0)
        dreb_v     = adv.get('dreb_pct', 0)
        tov_v      = adv.get('tov_pct', 0)
        ast_v      = adv.get('ast_rate', 0)
        stl_v      = adv.get('stl_pct', 0)
        blk_v      = adv.get('blk_pct', 0)
        ftr_v      = adv.get('ft_rate', 0)
        twop_v     = round((tot.get('FGM',0)-tot.get('3PM',0))/(tot.get('FGA',0)-tot.get('3PA',0))*100,1) if (tot.get('FGA',0)-tot.get('3PA',0))>0 else 0
        tpp_v      = avg.get('3P%', 0)
        ftp_v      = avg.get('FT%', 0)

        # Narrative
        narrative = narratives.get(name, default_narrative)
        e.append(Paragraph(narrative, S(8.5, space_after=3)))

        # Dynamic advanced analytics paragraph (prose, not a table)
        if mpg >= 12.0 and ind_ortg_v > 0:
            _ior, _n = adv_rank('ind_ortg', ind_ortg_v)
            _idr, _  = adv_rank('ind_drtg', ind_drtg_v, False)
            _ar,  _  = adv_rank('ast_rate', ast_v)
            _tvr, _  = adv_rank('tov_pct',  tov_v, False)
            _orr, _  = adv_rank('oreb_pct', oreb_v)
            _drr, _  = adv_rank('dreb_pct', dreb_v)
            _sr,  _  = adv_rank('stl_pct',  stl_v)
            _br,  _  = adv_rank('blk_pct',  blk_v)
            _2pr, _  = adv_rank('twop', twop_v) if twop_v > 0 else (0, _n)
            _3pr, _  = adv_rank('tpp',  tpp_v)  if tpp_v  > 0 else (0, _n)
            _ftr, _  = adv_rank('ftp',  ftp_v)  if ftp_v  > 0 else (0, _n)
            _upr, _  = adv_rank('usage_pct', usage_v) if usage_v > 0 else (0, _n)
            _ftrr, _ = adv_rank('ft_rate',   ftr_v)   if ftr_v   > 0 else (0, _n)
            efg_v    = adv.get('efg_pct', 0); ts_v = adv.get('ts_pct', 0)
            _efr, _  = adv_rank('efg_pct', efg_v) if efg_v > 0 else (0, _n)
            _tsr, _  = adv_rank('ts_pct',  ts_v)  if ts_v  > 0 else (0, _n)
            fc_v     = adv.get('fc_per_40', 0); fd_v = adv.get('fd_per_40', 0)
            _fcr, _  = adv_rank('fc_per_40', fc_v, False) if fc_v > 0 else (0, _n)
            _fdr, _  = adv_rank('fd_per_40', fd_v) if fd_v > 0 else (0, _n)
            shp_v    = adv.get('shot_pct', 0)
            _shr, _  = adv_rank('shot_pct', shp_v) if shp_v > 0 else (0, _n)
            minp_v   = mpg / 40.0 * 100
            _mnr, _  = adv_rank('min_pct', minp_v) if minp_v > 0 else (0, _n)
            adv_prose = (
                f'<i>Advanced analytics ({_n} qualified players, Min% ≥30%): '
                f'Ind ORtg <b>{ind_ortg_v:.1f}</b> (#{_ior})  ·  '
                f'Ind DRtg <b>{ind_drtg_v:.1f}</b> (#{_idr})  ·  '
                + (f'eFG% <b>{efg_v:.1f}%</b> (#{_efr})  ·  ' if efg_v > 0 else '')
                + (f'TS% <b>{ts_v:.1f}%</b> (#{_tsr})  ·  ' if ts_v > 0 else '')
                + f'Min% <b>{minp_v:.1f}%</b>' + (f' (#{_mnr})' if minp_v > 0 else '') + '  ·  '
                + f'%Poss <b>{usage_v:.1f}%</b>' + (f' (#{_upr})' if usage_v > 0 else '') + '  ·  '
                + (f'%Shots <b>{shp_v:.1f}%</b> (#{_shr})  ·  ' if shp_v > 0 else '')
                + f'AST Rate <b>{ast_v:.1f}%</b> (#{_ar})  ·  '
                f'TOV% <b>{tov_v:.1f}%</b> (#{_tvr})  ·  '
                f'OREB% <b>{oreb_v:.1f}%</b> (#{_orr})  ·  '
                f'DREB% <b>{dreb_v:.1f}%</b> (#{_drr})  ·  '
                f'STL% <b>{stl_v:.1f}%</b> (#{_sr})  ·  '
                f'BLK% <b>{blk_v:.1f}%</b> (#{_br})  ·  '
                f'FT Rate <b>{ftr_v:.1f}</b>' + (f' (#{_ftrr})' if ftr_v > 0 else '')
                + (f'  ·  FC/40 <b>{fc_v:.1f}</b> (#{_fcr})' if fc_v > 0 else '')
                + (f'  ·  FD/40 <b>{fd_v:.1f}</b> (#{_fdr})' if fd_v > 0 else '')
                + (f'  ·  2P% <b>{twop_v:.1f}%</b> (#{_2pr})' if twop_v > 0 else '')
                + (f'  ·  3P% <b>{tpp_v:.1f}%</b> (#{_3pr})'  if tpp_v  > 0 else '')
                + (f'  ·  FT% <b>{ftp_v:.1f}%</b> (#{_ftr})'  if ftp_v  > 0 else '')
                + '</i>'
            )
            e.append(Paragraph(adv_prose, S(7.5, italic=False, color=colors.HexColor('#aab8d0'), space_after=4)))

        # Stat strip
        tpar = round(avg.get('3PA',0)/max(avg.get('FGA',0.01),0.01)*100,0)
        stat_cells = [
            [Paragraph(f"{avg.get('PTS',0):.1f}", S(13, True, BLUE, TA_CENTER)),
             Paragraph('PPG', S(7, False, MID, TA_CENTER))],
            [Paragraph(f"{avg.get('REB',0):.1f}", S(13, True, BLUE, TA_CENTER)),
             Paragraph('RPG', S(7, False, MID, TA_CENTER))],
            [Paragraph(f"{avg.get('AST',0):.1f}", S(13, True, BLUE, TA_CENTER)),
             Paragraph('APG', S(7, False, MID, TA_CENTER))],
            [Paragraph(f"{avg.get('STL',0):.1f}", S(13, True, BLUE, TA_CENTER)),
             Paragraph('SPG', S(7, False, MID, TA_CENTER))],
            [Paragraph(f"{avg.get('BLK',0):.1f}", S(13, True, BLUE, TA_CENTER)),
             Paragraph('BPG', S(7, False, MID, TA_CENTER))],
            [Paragraph(f"{avg.get('TO',0):.1f}", S(13, True, MID, TA_CENTER)),
             Paragraph('TO/G', S(7, False, MID, TA_CENTER))],
            [Paragraph(f"{adv.get('efg_pct',0):.1f}%", S(13, True, BLUE, TA_CENTER)),
             Paragraph('eFG%', S(7, False, MID, TA_CENTER))],
            [Paragraph(f"{avg.get('3P%',0):.1f}%", S(13, True, BLUE, TA_CENTER)),
             Paragraph(f"3P% ({avg.get('3PA',0):.1f}/G)", S(7, False, MID, TA_CENTER))],
            [Paragraph(f"{avg.get('FT%',0):.1f}%", S(13, True, BLUE, TA_CENTER)),
             Paragraph('FT%', S(7, False, MID, TA_CENTER))],
            [Paragraph(f"{adv.get('ts_pct',0):.1f}%", S(13, True, BLUE, TA_CENTER)),
             Paragraph('TS%', S(7, False, MID, TA_CENTER))],
        ]
        st = Table([stat_cells], colWidths=[0.75*inch]*10)
        st.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),LGRAY),
            ('INNERGRID',(0,0),(-1,-1),0.3,MGRAY),
            ('BOX',(0,0),(-1,-1),0.5,BLUE),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),3),
        ]))
        e.append(st)

        # State rank context (only for Min% > 10%)
        if mpg > 4.0:
            pr, pn = plyr_rank('ppg', avg.get('PTS',0), True)
            ar, an = plyr_rank('apg', avg.get('AST',0), True)
            tr, tn = plyr_rank('ts_pct', adv.get('ts_pct',0), True)
            tpr, tpn = plyr_rank('tpp', avg.get('3P%',0), True)
            tovr, tovn = plyr_rank('tov_pct', adv.get('tov_pct',0), False)
            ctx_line = (
                f'State context ({pn} qualifying players, Min% >10%): '
                f'PPG #{pr}/{pn}  ·  APG #{ar}/{an}  ·  TS% #{tr}/{tn}  ·  '
                f'3P% #{tpr}/{tpn}  ·  TOV% #{tovr}/{tovn}'
            )
            e.append(Paragraph(ctx_line, S(7.5, italic=True, color=MID)))

        # Keep each profile intact and let it flow to the next page only when it
        # won't fit — packs profiles tightly instead of a fixed 4-per-page break.
        block = e[mark:]
        del e[mark:]
        e.append(KeepTogether(block))
        e.append(Spacer(1, 12))

    return e


# ═══════════════════════════════════════════════════════════════════════════════
# FINAL PAGE — STRENGTHS, VULNERABILITIES, MATCHUP GUIDE
# ═══════════════════════════════════════════════════════════════════════════════
def page_position_dependence():
    e = []
    e += section(
        'Offensive Identity — Position Dependence Analysis',
        'Guard Dependence Index (GDI) = average of guard scoring share and guard assist share '
        '(0–100 scale). Higher = more reliant on guards for points and playmaking. '
        'Lower = more big-man / wing-forward driven offense.'
    )

    # Statewide context for Moorpark
    all_gdis = sorted([r['gdi'] for r in pos_dep_all if 'gdi' in r], reverse=True)
    mp_gdi   = mp_dep.get('gdi', 0)
    mp_state_rank = next((i+1 for i,v in enumerate(all_gdis) if v <= mp_gdi), len(all_gdis))
    mp_gpts  = mp_dep.get('guard_pts_pct', 0)
    mp_wpts  = mp_dep.get('wing_pts_pct', 0)
    mp_bpts  = mp_dep.get('big_pts_pct', 0)
    mp_gast  = mp_dep.get('guard_ast_pct', 0)
    mp_grb   = mp_dep.get('guard_reb_pct', 0)
    league_avg_gdi = round(sum(all_gdis) / len(all_gdis), 1)

    # Narrative box
    narrative = (
        f'Moorpark\'s offense is <b>guard-driven</b>: guards account for <b>{mp_gpts:.0f}%</b> '
        f'of scoring and <b>{mp_gast:.0f}%</b> of assists, yielding a Guard Dependence Index of '
        f'<b>{mp_gdi:.1f}</b> — ranked <b>#{mp_state_rank} of {len(all_gdis)} statewide</b> '
        f'(league avg {league_avg_gdi}). Wing forwards contribute {mp_wpts:.0f}% of scoring '
        f'and bigs {mp_bpts:.0f}%. Rebounding is more balanced: guards pull down {mp_grb:.0f}% '
        f'of total boards. '
        f'<b>Key implication:</b> Disrupting Moorpark\'s guard play — particularly '
        f'Castaniero\'s distribution and Kubel/Cotton\'s perimeter shooting — directly '
        f'attacks the primary scoring engine. Their bigs (Brutus, Zlocha, Finney) are '
        f'efficient but not heavy usage scorers.'
    )
    e.append(Paragraph(narrative, S(9, space_after=10)))
    e.append(Spacer(1, 8))

    # WSC North comparison table
    e.append(Paragraph('WSC North — Offensive Position Profile', S(10, True, BLUE, space_after=4)))
    hdr = ['Team', 'GDI', 'G Pts%', 'W Pts%', 'B Pts%', 'G Ast%', 'ORTg', 'Win%']
    rows = [[
        Paragraph(h, S(8, True, WHITE, TA_CENTER)) for h in hdr
    ]]
    for r in wsc_dep:
        is_mp = r['team'] == 'Moorpark'
        bg = GOLD if is_mp else WHITE
        tc = DARK if is_mp else BLACK
        gdi_str = f"{r.get('gdi','—')}"
        rows.append([
            Paragraph(f"<b>{r['team']}</b>" if is_mp else r['team'],
                      S(8.5, is_mp, tc)),
            Paragraph(gdi_str, S(8.5, is_mp, tc, TA_CENTER)),
            Paragraph(f"{r.get('guard_pts_pct','—')}",  S(8, is_mp, tc, TA_CENTER)),
            Paragraph(f"{r.get('wing_pts_pct','—')}",   S(8, is_mp, tc, TA_CENTER)),
            Paragraph(f"{r.get('big_pts_pct','—')}",    S(8, is_mp, tc, TA_CENTER)),
            Paragraph(f"{r.get('guard_ast_pct','—')}",  S(8, is_mp, tc, TA_CENTER)),
            Paragraph(f"{r.get('ortg','—')}",           S(8, is_mp, tc, TA_CENTER)),
            Paragraph(f"{r.get('win_pct', '—'):.3f}" if isinstance(r.get('win_pct'), float) else '—',
                      S(8, is_mp, tc, TA_CENTER)),
        ])
    cws = [1.4*inch, 0.5*inch, 0.65*inch, 0.65*inch, 0.65*inch, 0.65*inch, 0.6*inch, 0.55*inch]
    tbl = Table(rows, colWidths=cws)
    style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), TH_BG),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, ALT]),
        ('BOX', (0,0), (-1,-1), 1, BLUE),
        ('INNERGRID', (0,0), (-1,-1), 0.4, MGRAY),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ])
    # Highlight Moorpark row gold
    for i, r in enumerate(wsc_dep, start=1):
        if r['team'] == 'Moorpark':
            tbl.setStyle(TableStyle([
                ('BACKGROUND', (0,i), (-1,i), GOLD),
            ]))
    tbl.setStyle(style)
    e.append(tbl)
    e.append(Spacer(1, 10))

    # Statewide GDI distribution note
    q1 = sorted(all_gdis)[len(all_gdis)*4//5]   # 80th pctile = most big-heavy
    q4 = sorted(all_gdis)[len(all_gdis)*1//5]   # 20th pctile = most guard-heavy
    n_guard_heavy = sum(1 for v in all_gdis if v >= mp_gdi)
    # Compute avg win% for big-heavy vs guard-heavy tiers
    big_tier_wp  = [r['win_pct'] for r in pos_dep_all if r.get('gdi', 99) < 55 and 'win_pct' in r]
    grd_tier_wp  = [r['win_pct'] for r in pos_dep_all if r.get('gdi', 0) >= 70 and 'win_pct' in r]
    big_avg_wp   = round(sum(big_tier_wp) / len(big_tier_wp), 3) if big_tier_wp else 0
    grd_avg_wp   = round(sum(grd_tier_wp) / len(grd_tier_wp), 3) if grd_tier_wp else 0
    e.append(Paragraph(
        f'<b>Statewide context:</b> GDI ranges from {min(all_gdis):.0f} to {max(all_gdis):.0f} '
        f'(avg {league_avg_gdi:.0f}) across {len(all_gdis)} teams. '
        f'Only {n_guard_heavy - 1} programs are more guard-dependent than Moorpark. '
        f'Big-heavy teams (GDI &lt; 55) average a {big_avg_wp:.3f} win% vs. '
        f'{grd_avg_wp:.3f} for guard-heavy teams (GDI \u2265 70) \u2014 '
        f'position dependence does not predict winning; it reflects offensive <i>style</i>, not quality.',
        S(8.5, space_after=6)
    ))
    e.append(Spacer(1, 10))

    # Opponent breakdown: implications for defense
    e.append(Paragraph('Opponent Profile Notes', S(10, True, BLUE, space_after=4)))
    opp_notes = []
    for r in wsc_dep:
        if r['team'] == 'Moorpark':
            continue
        gdi = r.get('gdi', 0)
        gp  = r.get('guard_pts_pct', 0)
        bp  = r.get('big_pts_pct', 0)
        wp  = r.get('wing_pts_pct', 0)
        ga  = r.get('guard_ast_pct', 0)
        if gdi >= 70:
            profile = f'Guard-driven (GDI {gdi:.0f}): {gp:.0f}% of scoring + {ga:.0f}% of assists from guards. Defensive priority: perimeter containment.'
        elif bp >= 25:
            profile = f'Big-reliant (GDI {gdi:.0f}): {bp:.0f}% of scoring from bigs. Defensive priority: post defense + block-outs.'
        elif wp >= 25:
            profile = f'Wing-forward heavy (GDI {gdi:.0f}): {wp:.0f}% of scoring from wing Fs. Defensive priority: deny wing touches.'
        else:
            profile = f'Balanced offense (GDI {gdi:.0f}): distributed across guards ({gp:.0f}%), wings ({wp:.0f}%), bigs ({bp:.0f}%).'
        opp_notes.append((r['team'], profile))
    for team_name, note in opp_notes:
        row = [[Paragraph(f'<b>{team_name}</b>', S(8.5, True, BLUE)),
                Paragraph(note, S(8.5))]]
        nt = Table(row, colWidths=[1.3*inch, 6.2*inch])
        nt.setStyle(TableStyle([
            ('BACKGROUND', (0,0),(0,0), LGRAY),
            ('BOX', (0,0),(-1,-1), 0.4, BLUE),
            ('INNERGRID', (0,0),(-1,-1), 0.3, MGRAY),
            ('TOPPADDING', (0,0),(-1,-1), 5), ('BOTTOMPADDING', (0,0),(-1,-1), 5),
            ('LEFTPADDING', (0,0),(-1,-1), 7), ('RIGHTPADDING', (0,0),(-1,-1), 6),
            ('VALIGN', (0,0),(-1,-1), 'MIDDLE'),
        ]))
        e.append(nt)
        e.append(Spacer(1, 3))

    e.append(Spacer(1, 14))
    return e


def page_scouting_guide():
    e = []
    e += section('Scouting Summary — Strengths, Vulnerabilities & Matchup Keys')

    # S&V side by side
    strengths = [
        ('<b>Elite defense — #13 DRTg statewide</b>', 'Opponents shoot 47.3 eFG% vs. the CCCAA avg of 49.7%. They suppress shooting, force turnovers (opp TOV% 20.4%, #23 state), and protect the paint with blocks.'),
        ('<b>Offensive rebounding machine</b>', 'OREB% 32.6% (#28 state). They get multiple bites at the apple on nearly every miss. This is the single biggest threat to contain.'),
        ('<b>Dominant conference record</b>', '10-2 in WSC North with avg net +8.0 in conference games. They clearly understand and execute within this league better than most.'),
        ('<b>Late-season improvement</b>', 'Net +14.9 in February vs +0.8 in November. A team peaking at the right time.'),
        ('<b>Multiple perimeter threats</b>', 'Kubel (35.9%), Cotton (39.2%), Field (37.4%), Zlocha (40.6%) — every starter shoots 35%+ from three; there is no single shooter to key on.'),
        ('<b>Balanced attack</b>', 'No player exceeds 13.8 PPG. Cannot simply take one player away. Castaniero runs everything but doesn\'t need to score.'),
    ]
    vulnerabilities = [
        ('<b>Cannot get to the foul line</b>', 'FT Rate 25.3 (#95/100) — bottom 5% in the state. By the data, their scoring comes almost entirely from jump shots rather than at the rim or the line.'),
        ('<b>5-10 vs. positive Net Rtg teams</b>', '0-5 vs. teams rated above +12. Every single loss came against a winning-net-rating program. Their ceiling has a clear ceiling.'),
        ('<b>Free throw shooting 69.5%</b>', 'Below CCCAA average in late-game fouling situations. Intentionally foul in crunch time — they will miss.'),
        ('<b>Aiden Bitran — net -8.2</b>', 'His individual ratings show below-average offensive efficiency (89.8 ORtg) and a high DRtg (98.0). Attack mismatches when he\'s in the game.'),
        ('<b>Fouls at high rate</b>', '18.9 PF/G (opponents only 14.6). Get to the rim and draw fouls — Brutus and Steele in particular are foul-prone.'),
        ('<b>Ventura problem</b>', 'Lost to Ventura twice (both single-digit, net rating -11.0 and -6.6).'),
    ]
    sv_rows = []
    for (sk, sv), (vk, vv) in zip(strengths, vulnerabilities):
        sv_rows.append([
            [Paragraph(sk, S(8.5, True, GREEN_TXT)), Paragraph(sv, S(8))],
            [Paragraph(vk, S(8.5, True, RED_TXT)), Paragraph(vv, S(8))],
        ])
    sv_t = Table(sv_rows, colWidths=[3.6*inch, 3.6*inch])
    sv_t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f0fff4')),
        ('BACKGROUND', (1,0), (1,-1), colors.HexColor('#fff5f5')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, MGRAY),
        ('BOX', (0,0), (-1,-1), 1, BLUE),
        ('TOPPADDING', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))

    # Header row
    hdr_row = Table([[
        Paragraph('STRENGTHS', S(9, True, GREEN_TXT, TA_CENTER)),
        Paragraph('VULNERABILITIES', S(9, True, RED_TXT, TA_CENTER)),
    ]], colWidths=[3.6*inch, 3.6*inch])
    hdr_row.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(0,0), colors.HexColor('#d4edda')),
        ('BACKGROUND', (1,0),(1,0), colors.HexColor('#f8d7da')),
        ('BOX',(0,0),(-1,-1),1,BLUE),
        ('INNERGRID',(0,0),(-1,-1),0.5,MGRAY),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
    ]))
    e.append(hdr_row)
    e.append(sv_t)
    e.append(Spacer(1, 14))

    # Matchup keys
    e.append(Spacer(1, 12))
    e.append(HR(BLUE, 1, 4, 6))
    e.append(Paragraph(
        'Data sources: CCCMBCA official box scores, internal analytics pipeline. '
        'Advanced metrics (ORtg / DRtg / Net Rating) are individual box-score estimates via Dean Oliver method — '
        'not lineup-based on/off data. '
        'WAB = Wins Above Bubble (simulation-based). Statewide rankings computed across all 100 CCCAA programs, 2025-26 season.',
        S(7, False, MID, TA_CENTER)))
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    out = f'{BASE}/moorpark_scouting_report_2025_26.pdf'
    doc = SimpleDocTemplate(out, pagesize=letter,
                            topMargin=0.65*inch, bottomMargin=0.5*inch,
                            leftMargin=0.5*inch, rightMargin=0.5*inch)
    story = []
    story += page_cover()
    story += page_analytics()
    story += page_keys()
    story += page_synergy_team()
    story += page_big_games()
    story += page_game_log()
    story += page_rotation()
    story += page_player_profiles()
    story += page_position_dependence()
    story += page_scouting_guide()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    kb = os.path.getsize(out) // 1024
    print(f'Saved: {out} ({kb} KB)')

if __name__ == '__main__':
    main()
