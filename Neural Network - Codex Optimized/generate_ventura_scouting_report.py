"""
Ventura College Pirates 2025-26 — Opponent Scouting Report
Prepared by: Moorpark College Raiders Analytics | Internal Use Only
"""

import json, os, csv
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)

# ─── Palette ─────────────────────────────────────────────────────────────────
BLUE      = colors.HexColor('#003087')
GOLD      = colors.HexColor('#C4922A')
OPP_HDR   = colors.HexColor('#FF6600')   # Ventura orange
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

def jload(p): return json.load(open(p))

# ─── Load Data ────────────────────────────────────────────────────────────────
team_sum   = jload(f'{BASE}/2025-26 Team Statistics/WSC North/Ventura/team_summary.json')
adv_json   = jload(f'{BASE}/2025-26 Team Statistics/WSC North/Ventura/advanced_analytics.json')
plyr_stats = jload(f'{BASE}/2025-26 Team Statistics/WSC North/Ventura/player_stats.json')
mp_adv     = jload(f'{BASE}/2025-26 Team Statistics/WSC North/Moorpark/advanced_analytics.json')
mp_sum     = jload(f'{BASE}/2025-26 Team Statistics/WSC North/Moorpark/team_summary.json')
wab_data   = jload(f'{BASE}/wab_results.json')

avgs      = team_sum['averages']
opp_avgs  = team_sum['opponent_averages']
ta        = adv_json['team']
game_log  = ta.get('game_ratings', [])
wab_map   = {t['team']: t for t in wab_data}
vc_wab    = wab_map.get('Ventura', {})
mp_wab    = wab_map.get('Moorpark', {})

# Players — exclude Aukuso (removed from team)
EXCLUDED = {'Christian Aukuso'}
players_raw = [p for p in plyr_stats['players'] if p['name'] not in EXCLUDED]
plyr_adv    = {p['name']: p for p in adv_json.get('players', []) if p['name'] not in EXCLUDED}

# ─── Height & position-dependence data ───────────────────────────────────────
def _parse_height_in(h):
    h = h.strip().replace('"', '').replace("Ht.: ", '')
    if "'" in h:
        parts = h.split("'")
        ft = int(parts[0].strip())
        inc = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else 0
        return ft * 12 + inc
    return 0

def _fmt_height(inches):
    return f"{inches // 12}'{inches % 12}\"" if inches > 0 else ''

_VC_TEAM_KEY = 'Ventura College Pirate'
vc_height_in = {}   # player name -> height in inches
_all_team_h  = {}   # team -> [inches, ...]
with open(f'{BASE}/internal_data/roster_heights_2025_26.csv') as _hf:
    for _hr in csv.DictReader(_hf):
        _hin  = _parse_height_in(_hr.get('height', ''))
        _hteam = _hr.get('team', '')
        _hname = _hr.get('player', '')
        if _hin > 60:
            _all_team_h.setdefault(_hteam, []).append(_hin)
            if _hteam == _VC_TEAM_KEY:
                vc_height_in[_hname] = _hin

_all_indiv_h = [h for hs in _all_team_h.values() for h in hs]
_state_avg_h = sum(_all_indiv_h) / len(_all_indiv_h) if _all_indiv_h else 74.8
_vc_h_list   = _all_team_h.get(_VC_TEAM_KEY, [])
_vc_avg_h    = sum(_vc_h_list) / len(_vc_h_list) if _vc_h_list else 0
_team_avgs_h = sorted(
    [(t, sum(hs) / len(hs)) for t, hs in _all_team_h.items() if len(hs) >= 5],
    key=lambda x: -x[1])
_vc_h_rank   = next((i+1 for i,(t,a) in enumerate(_team_avgs_h) if a <= _vc_avg_h), len(_team_avgs_h))
_vc_h_n      = len(_team_avgs_h)

_pos_dep_all  = json.load(open(f'{BASE}/internal_data/position_dependence_2025_26.json'))
_vc_dep       = next((r for r in _pos_dep_all if r['team'] == 'Ventura'), {})
_all_gdis_h   = sorted([r['gdi'] for r in _pos_dep_all if 'gdi' in r], reverse=True)
_vc_gdi       = _vc_dep.get('gdi', 0)
_vc_gdi_rank  = next((i+1 for i, v in enumerate(_all_gdis_h) if v <= _vc_gdi), len(_all_gdis_h))
_vc_gdi_n     = len(_all_gdis_h)
_league_avg_gdi = round(sum(_all_gdis_h) / len(_all_gdis_h), 1) if _all_gdis_h else 0
_vc_guard_pts = _vc_dep.get('guard_pts_pct', 0)
_vc_wing_pts  = _vc_dep.get('wing_pts_pct', 0)
_vc_big_pts   = _vc_dep.get('big_pts_pct', 0)
_vc_guard_ast = _vc_dep.get('guard_ast_pct', 0)

# ─── Quality games & splits ───────────────────────────────────────────────────
quality_games = []
for g in game_log:
    opp = g.get('canonical_opponent', g['opponent'])
    od  = wab_map.get(opp)
    quality_games.append({**g,
        'net':     g['ortg'] - g['drtg'],
        'margin':  g['team_score'] - g['opponent_score'],
        'opp_net': od['net'] if od else None,
        'opp_wab': od['wab'] if od else None,
    })

def avg_net(lst): return sum(g['net'] for g in lst) / len(lst) if lst else 0
def rec(lst):
    w = sum(1 for g in lst if g['result'] == 'W')
    return f'{w}-{len(lst)-w}'

wins    = [g for g in quality_games if g['result'] == 'W']
losses  = [g for g in quality_games if g['result'] == 'L']
conf_g  = [g for g in quality_games if g.get('is_conference')]
nconf   = [g for g in quality_games if not g.get('is_conference')]
home_g  = [g for g in quality_games if g['location'] == 'Home']
away_g  = [g for g in quality_games if g['location'] == 'Away']
neut_g  = [g for g in quality_games if g['location'] == 'Neutral']
good_opp= [g for g in quality_games if g['opp_net'] is not None and g['opp_net'] > 0]
close_g = [g for g in quality_games if abs(g['margin']) <= 8]
early_g = quality_games[:15]
late_g  = quality_games[15:]

# ─── Quad records ────────────────────────────────────────────────────────────
_wab_ranked = sorted(wab_data, key=lambda x: -x.get('net', 0))
_N = len(_wab_ranked)
_net_ranks  = {t['team']: i+1 for i, t in enumerate(_wab_ranked)}

def _get_quad(opp_rank, loc):
    tQ1A = {'Home': _N*15/353, 'Neutral': _N*25/353, 'Away': _N*40/353}
    tQ1  = {'Home': _N*30/353, 'Neutral': _N*50/353, 'Away': _N*75/353}
    tQ2  = {'Home': _N*75/353, 'Neutral': _N*100/353,'Away': _N*135/353}
    tQ3  = {'Home': _N*160/353,'Neutral': _N*200/353,'Away': _N*240/353}
    th   = lambda m: m.get(loc, m['Neutral'])
    if opp_rank <= th(tQ1A): return 'Q1A'
    if opp_rank <= th(tQ1):  return 'Q1'
    if opp_rank <= th(tQ2):  return 'Q2'
    if opp_rank <= th(tQ3):  return 'Q3'
    return 'Q4'

quad_rec   = {'Q1A':[0,0],'Q1':[0,0],'Q2':[0,0],'Q3':[0,0],'Q4':[0,0]}
quad_games = {'Q1A':[],'Q1':[],'Q2':[],'Q3':[],'Q4':[]}
for _g in quality_games:
    _opp  = _g.get('canonical_opponent', _g['opponent'])
    _loc  = _g.get('location', 'Neutral')
    _rank = _net_ranks.get(_opp)
    if not _rank: continue
    _q = _get_quad(_rank, _loc)
    if _g['result'] == 'W':   quad_rec[_q][0] += 1
    elif _g['result'] == 'L': quad_rec[_q][1] += 1
    quad_games[_q].append(dict(_g, opp_rank=_rank))

# ─── Statewide context ───────────────────────────────────────────────────────
all_teams = []
for _conf in os.listdir(f'{BASE}/2025-26 Team Statistics'):
    _cp = f'{BASE}/2025-26 Team Statistics/{_conf}'
    if not os.path.isdir(_cp): continue
    for _team in os.listdir(_cp):
        _ap = f'{_cp}/{_team}/advanced_analytics.json'
        _sp = f'{_cp}/{_team}/team_summary.json'
        if not (os.path.exists(_ap) and os.path.exists(_sp)): continue
        try:
            _a = jload(_ap)['team']; _s = jload(_sp)
            _av   = _s['averages']; _ov = _s['opponent_averages']
            _tot  = _s.get('totals', {}); _otot = _s.get('opponent_totals', {})
            _fga  = max(_av.get('FGA', 1), 1)
            _3pa  = _av.get('3PA', 0)
            _poss = max(_a.get('possessions', 0.01), 0.01)
            _pf   = max(_tot.get('PF', 0.1), 0.1)
            _stlt = _tot.get('STL', 0); _blkt = _tot.get('BLK', 0)
            _opp_fga = max(_otot.get('FGA', 1), 1)
            _opp_poss_denom = max(
                (_otot.get('FGA',0) - _otot.get('OREB',0)) +
                _otot.get('TO',0) + 0.475 * _otot.get('FTA',0), 0.1)
            _stl_pct_lb  = round(_stlt / _opp_poss_denom * 100, 1)
            _blk_pct_lb  = round(_blkt / _opp_fga * 100, 1)
            _stl_to_v    = round(_av.get('STL',0) / max(_ov.get('TO',0.01),0.01), 2)
            all_teams.append({
                'team': _team,
                'net_rtg':     _a.get('net_rtg', 0),
                'ortg':        _a.get('ortg', 0),
                'drtg':        _a.get('drtg', 0),
                'efg_pct':     _a.get('efg_pct', 0),
                'opp_efg_pct': _a.get('opp_efg_pct', 0),
                'tov_pct':     _a.get('tov_pct', 0),
                'opp_tov_pct': _a.get('opp_tov_pct', 0),
                'oreb_pct':    _a.get('oreb_pct', 0),
                'dreb_pct':    _a.get('dreb_pct', 0),
                'ft_rate':     _a.get('ft_rate', 0),
                'opp_ft_rate': _a.get('opp_ft_rate', 0),
                'ts_pct':      _a.get('ts_pct', 0),
                'opp_ts_pct':  _a.get('opp_ts_pct', 0),
                'pace':        _a.get('possessions', 0),
                'stl_pct':     _stl_pct_lb,
                'blk_pct':     _blk_pct_lb,
                'hkm_pct':     round(_stl_pct_lb + _blk_pct_lb, 1),
                'stl_to':      _stl_to_v,
                'pf_eff':      round((_stlt + _blkt) / _pf, 2),
                'stl_pf':      round(_stlt / _pf, 2),
                'blk_pf':      round(_blkt / _pf, 2),
                'ast_rate':    _a.get('ast_rate', 0),
                'ast_ratio':   round(100 * _av.get('AST',0) / max(_av.get('FGA',0) + 0.475*_av.get('FTA',0) + _av.get('AST',0) + _av.get('TO',0), 1), 1),
                'ast_to':      round(_av.get('AST',0) / max(_av.get('TO',0.01),0.01), 2),
                'nst_pct':     round(max(_av.get('TO',0) - _ov.get('STL',0), 0) / _poss * 100, 1),
                'fc_per_40':   _a.get('fc_per_40', 0),
                '3par':        round(_3pa / _fga * 100, 1),
                'ppg':         _av['PTS'],
                'oppg':        _ov['PTS'],
                'stl':         _av['STL'],
                'blk':         _av['BLK'],
                'ast':         _av['AST'],
                'tov':         _av['TO'],
            })
        except: pass

_n = len(all_teams)

def state_rank(key, val, higher_better=True):
    vals = sorted([t[key] for t in all_teams if t[key] != 0], reverse=higher_better)
    rank = next((i+1 for i,v in enumerate(vals) if (higher_better and v<=val) or (not higher_better and v>=val)), len(vals))
    avg  = sum(t[key] for t in all_teams) / _n
    return rank, _n, round(avg, 1), round(val - avg, 1)

# Pre-compute Ventura's key ranks
vc_net_rank, _, _, _  = state_rank('net_rtg',     ta['net_rtg'],     True)
ortg_r,  _, ortg_avg, _  = state_rank('ortg',        ta['ortg'],        True)
drtg_r,  _, drtg_avg, _  = state_rank('drtg',        ta['drtg'],        False)
efg_r,   _, efg_avg,  _  = state_rank('efg_pct',     ta['efg_pct'],     True)
ts_r,    _, ts_avg,   _  = state_rank('ts_pct',       ta['ts_pct'],      True)
oefg_r,  _, oefg_avg, _  = state_rank('opp_efg_pct', ta['opp_efg_pct'], False)
ots_r,   _, ots_avg,  _  = state_rank('opp_ts_pct',  ta['opp_ts_pct'],  False)
otov_r,  _, otov_avg, _  = state_rank('opp_tov_pct', ta['opp_tov_pct'], True)
tov_r,   _, tov_avg,  _  = state_rank('tov_pct',     ta['tov_pct'],     False)
oreb_r,  _, oreb_avg, _  = state_rank('oreb_pct',    ta['oreb_pct'],    True)
dreb_r,  _, dreb_avg, _  = state_rank('dreb_pct',    ta['dreb_pct'],    True)
ftr_r,   _, ftr_avg,  _  = state_rank('ft_rate',     ta['ft_rate'],     True)
oftr_r,  _, oftr_avg, _  = state_rank('opp_ft_rate', ta['opp_ft_rate'], False)
pace_r,   _, pace_avg,  _  = state_rank('pace',       ta['possessions'], True)
stl_r,    _, stl_avg,   _  = state_rank('stl',        avgs['STL'],       True)
blk_r,    _, blk_avg,   _  = state_rank('blk',        avgs['BLK'],       True)
ast_r,    _, ast_avg,   _  = state_rank('ast',        avgs['AST'],       True)
_vc_3par   = round(avgs.get('3PA', 0) / max(avgs.get('FGA', 1), 1) * 100, 1)
tpar_r,   _, tpar_avg,  _  = state_rank('3par',       _vc_3par,          True)
# Derived defensive metrics (leaderboard-matching formulas)
_vc_tot  = team_sum.get('totals', {})
_vc_otot = team_sum.get('opponent_totals', {})
_vc_poss = max(ta.get('possessions', 0.01), 0.01)
_vc_pf   = max(_vc_tot.get('PF', 0.1), 0.1)
_vc_stlt = _vc_tot.get('STL', 0); _vc_blkt = _vc_tot.get('BLK', 0)
_vc_opp_fga       = max(_vc_otot.get('FGA', 1), 1)
_vc_opp_poss_denom = max((_vc_otot.get('FGA',0)-_vc_otot.get('OREB',0)) + _vc_otot.get('TO',0) + 0.475*_vc_otot.get('FTA',0), 0.1)
_vc_stl_pct  = round(_vc_stlt / _vc_opp_poss_denom * 100, 1)
_vc_blk_pct  = round(_vc_blkt / _vc_opp_fga * 100, 1)
_vc_hkm_pct  = round(_vc_stl_pct + _vc_blk_pct, 1)
_vc_stl_to   = round(avgs['STL'] / max(opp_avgs.get('TO', 0.01), 0.01), 2)
_vc_pf_eff   = round((_vc_stlt + _vc_blkt) / _vc_pf, 2)
_vc_stl_pf   = round(_vc_stlt / _vc_pf, 2)
_vc_blk_pf   = round(_vc_blkt / _vc_pf, 2)
_vc_nst_pct  = round(max(avgs['TO'] - opp_avgs.get('STL',0), 0) / _vc_poss * 100, 1)
_vc_ast_to   = round(avgs['AST'] / max(avgs['TO'], 0.01), 2)
_vc_ast_ratio = round(100 * avgs['AST'] / max(avgs.get('FGA',0) + 0.475*avgs.get('FTA',0) + avgs['AST'] + avgs['TO'], 1), 1)
stlpct_r, _, _, _ = state_rank('stl_pct',  _vc_stl_pct,  True)
blkpct_r, _, _, _ = state_rank('blk_pct',  _vc_blk_pct,  True)
hkm_r,    _, _, _ = state_rank('hkm_pct',  _vc_hkm_pct,  True)
stlto_r,  _, _, _ = state_rank('stl_to',   _vc_stl_to,   True)
pfeff_r,  _, _, _ = state_rank('pf_eff',   _vc_pf_eff,   True)
stlpf_r,  _, _, _ = state_rank('stl_pf',   _vc_stl_pf,   True)
blkpf_r,  _, _, _ = state_rank('blk_pf',   _vc_blk_pf,   True)
nst_r,    _, _, _ = state_rank('nst_pct',  _vc_nst_pct,  False)
asto_r,   _, _, _ = state_rank('ast_to',   _vc_ast_to,   True)
astr_r,   _, _, _ = state_rank('ast_ratio',_vc_ast_ratio,True)
arate_r,  _, _, _ = state_rank('ast_rate', ta['ast_rate'],True)
fc40_r,   _, _, _ = state_rank('fc_per_40',ta['fc_per_40'],False)

wab_all      = sorted(wab_data, key=lambda x: x.get('wab', 0), reverse=True)
vc_wab_rank  = next((i+1 for i,t in enumerate(wab_all) if t.get('team') == 'Ventura'), None)
vc_wab_total = len(wab_all)

# Head-to-head from Moorpark's perspective
mp_game_log = mp_adv['team'].get('game_ratings', [])
h2h = [g for g in mp_game_log if 'Ventura' in g.get('canonical_opponent','') or 'Ventura' in g.get('opponent','')]

# ─── Statewide player pools ──────────────────────────────────────────────────
all_players = []   # Min% > 10% (MPG >= 4)
adv_players = []   # Min% >= 30% (MPG >= 12)
for _conf in os.listdir(f'{BASE}/2025-26 Team Statistics'):
    _cp = f'{BASE}/2025-26 Team Statistics/{_conf}'
    if not os.path.isdir(_cp): continue
    for _team in os.listdir(_cp):
        _pp = f'{_cp}/{_team}/player_stats.json'
        _ap = f'{_cp}/{_team}/advanced_analytics.json'
        if not (os.path.exists(_pp) and os.path.exists(_ap)): continue
        try:
            _ps = jload(_pp); _adv = jload(_ap)
            _am = {p['name']: p for p in _adv.get('players', [])}
            for _p in _ps['players']:
                _avg = _p['averages']; _tot = _p['totals']
                _mpg = _avg.get('MIN', 0); _gp = _avg.get('games', 0)
                if _gp < 10: continue
                _a2 = _am.get(_p['name'], {})
                if _mpg >= 4:
                    _twoa2 = _tot.get('FGA',0) - _tot.get('3PA',0)
                    _twom2 = _tot.get('FGM',0) - _tot.get('3PM',0)
                    all_players.append({
                        'name': _p['name'], 'team': _team,
                        'ppg':  _avg.get('PTS',0),  'rpg':  _avg.get('REB',0),
                        'apg':  _avg.get('AST',0),  'spg':  _avg.get('STL',0),
                        'bpg':  _avg.get('BLK',0),
                        'ts_pct':  _a2.get('ts_pct',0),
                        'tpp':     _avg.get('3P%',0), 'tpa': _avg.get('3PA',0),
                        'ftp':     _avg.get('FT%',0),
                        'fga':     _avg.get('FGA',0),
                        'twop':    round(_twom2/_twoa2*100,1) if _twoa2>0 else 0,
                        'tov_pct': _a2.get('tov_pct',0), 'oreb_pct': _a2.get('oreb_pct',0),
                    })
                if _mpg >= 12:
                    _twoa = _tot.get('FGA',0) - _tot.get('3PA',0)
                    _twom = _tot.get('FGM',0) - _tot.get('3PM',0)
                    adv_players.append({
                        'name': _p['name'], 'team': _team,
                        'ind_ortg': _a2.get('ind_ortg',0), 'ind_drtg': _a2.get('ind_drtg',0),
                        'ast_rate': _a2.get('ast_rate',0), 'tov_pct':  _a2.get('tov_pct',0),
                        'oreb_pct': _a2.get('oreb_pct',0), 'dreb_pct': _a2.get('dreb_pct',0),
                        'stl_pct':  _a2.get('stl_pct',0),  'blk_pct':  _a2.get('blk_pct',0),
                        'usage_pct':_a2.get('usage_pct',0), 'ft_rate': _a2.get('ft_rate',0),
                        'efg_pct':  _a2.get('efg_pct',0),
                        'twop': round(_twom/_twoa*100,1) if _twoa>0 else 0,
                        'tpp':  _avg.get('3P%',0), 'ftp': _avg.get('FT%',0),
                        'ts_pct': _a2.get('ts_pct',0),
                    })
        except: pass

def plyr_rank(key, val, hb=True):
    vals = sorted([p[key] for p in all_players if p[key] > 0], reverse=hb)
    r = next((i+1 for i,v in enumerate(vals) if (hb and v<=val) or (not hb and v>=val)), len(vals))
    return r, len(vals)

def adv_rank(key, val, hb=True):
    vals = sorted([p[key] for p in adv_players if p[key] > 0], reverse=hb)
    r = next((i+1 for i,v in enumerate(vals) if (hb and v<=val) or (not hb and v>=val)), len(vals))
    return r, len(vals)


def get_top100(avg, adv_data, tot, mpg):
    """Return list of (label, val, unit, rank, pool_n) for every stat ranked top 100."""
    findings = []
    tpa  = avg.get('3PA', 0)
    fga  = avg.get('FGA', 0)
    twoa = tot.get('FGA',0) - tot.get('3PA',0)
    twom = tot.get('FGM',0) - tot.get('3PM',0)
    twop = round(twom/twoa*100,1) if twoa > 0 else 0

    # All-players checks
    for key, val, label, unit, hb, pf in [
        ('ppg',  avg.get('PTS',0),  'PPG',  '',  True,  None),
        ('rpg',  avg.get('REB',0),  'RPG',  '',  True,  None),
        ('apg',  avg.get('AST',0),  'APG',  '',  True,  None),
        ('spg',  avg.get('STL',0),  'SPG',  '',  True,  None),
        ('bpg',  avg.get('BLK',0),  'BPG',  '',  True,  None),
        ('tpp',  avg.get('3P%',0),  '3P%',  '%', True,  lambda p: p.get('tpa',0) >= 2),
        ('twop', twop,              '2P%',  '%', True,  lambda p: p.get('fga',0) >= 5),
        ('ftp',  avg.get('FT%',0),  'FT%',  '%', True,  lambda p: p.get('fga',0) >= 2),
    ]:
        if val <= 0: continue
        pool = [p for p in all_players if p.get(key,0) > 0]
        if pf: pool = [p for p in pool if pf(p)]
        if not pool: continue
        vals = sorted([p[key] for p in pool], reverse=hb)
        r = next((i+1 for i,v in enumerate(vals) if (hb and v<=val) or (not hb and v>=val)), len(vals))
        if r <= 100:
            findings.append((label, val, unit, r, len(vals)))

    # Adv-players checks (MPG >= 12 only)
    if mpg >= 12:
        for key, val, label, unit, hb in [
            ('ind_ortg', adv_data.get('ind_ortg',0), 'Ind ORtg', '',  True),
            ('ts_pct',   adv_data.get('ts_pct',0),   'TS%',      '%', True),
            ('efg_pct',  adv_data.get('efg_pct',0),  'eFG%',     '%', True),
            ('oreb_pct', adv_data.get('oreb_pct',0), 'OREB%',    '%', True),
            ('dreb_pct', adv_data.get('dreb_pct',0), 'DREB%',    '%', True),
            ('stl_pct',  adv_data.get('stl_pct',0),  'STL%',     '%', True),
            ('blk_pct',  adv_data.get('blk_pct',0),  'BLK%',     '%', True),
            ('ast_rate', adv_data.get('ast_rate',0),  'AST Rate', '%', True),
            ('tov_pct',  adv_data.get('tov_pct',0),  'TOV%',     '%', False),
        ]:
            if val <= 0: continue
            pool_vals = sorted([p[key] for p in adv_players if p[key] > 0], reverse=hb)
            if not pool_vals: continue
            r = next((i+1 for i,v in enumerate(pool_vals) if (hb and v<=val) or (not hb and v>=val)), len(pool_vals))
            if r <= 100:
                findings.append((label, val, unit, r, len(pool_vals)))
    return findings

def kenpom_player_role(usage_pct, mpg):
    min_pct = mpg / 40.0 * 100
    if min_pct < 10.0:    return 'Benchwarmer',            '#777777'
    if usage_pct >= 28.0: return 'Go-to Guy',              '#ffd700'
    if usage_pct >= 24.0: return 'Major Contributor',      '#34a853'
    if usage_pct >= 20.0: return 'Significant Contributor','#ff9900'
    if usage_pct >= 16.0: return 'Role Player',            '#4a86e8'
    if usage_pct >= 12.0: return 'Limited Role Player',    '#ff00ff'
    return 'Nearly Invisible', '#d9d9d9'

pos_full = {
    'PG':'Point Guard','s-PG':'Scoring PG','CG':'Combo Guard',
    'WG':'Wing Guard','WF':'Wing Forward','S-PF':'Stretch PF',
    'PF/C':'PF / Center','C':'Center'
}

# Position assignments for Ventura rotation
vc_pos_map = {
    'Jerimiyah Smith':  'PF/C',
    'Snookey Wigington':'s-PG',
    "Kam'Ron Cigar":    'CG',
    'Baron Bellamy':    'WF',
    'Jeremiah Wilson':  'WG',
    'Kevin Anigbogu':   'C',
    'Dabe Princewill':  'WF',
    'Tong Tong':        'C',
}

# ─── Styles ───────────────────────────────────────────────────────────────────
SS = getSampleStyleSheet()

def S(size=10, bold=False, color=BLACK, align=TA_LEFT, italic=False, leading=None, space_after=2):
    fname = ('Helvetica-BoldOblique' if bold and italic else
             'Helvetica-Bold'        if bold         else
             'Helvetica-Oblique'     if italic        else 'Helvetica')
    return ParagraphStyle('_', parent=SS['Normal'], fontSize=size, fontName=fname,
                          textColor=color, alignment=align,
                          leading=leading or size*1.45, spaceAfter=space_after)

def HR(c=GOLD, thick=1.5, before=4, after=8):
    return HRFlowable(width='100%', thickness=thick, color=c, spaceBefore=before, spaceAfter=after)

def section(title, subtitle=None):
    items = [Spacer(1, 10),
             Paragraph(title.upper(), S(13, True, BLUE)),
             HR(GOLD, 2, 2, 6)]
    if subtitle:
        items.append(Paragraph(subtitle, S(9, False, MID, space_after=6)))
    return items

def splits_box(label, record_str, avg_net_val, extra=''):
    net_c = GREEN_BG if avg_net_val > 5 else (RED_BG if avg_net_val < -5 else YELLOW_BG)
    sign  = '+' if avg_net_val >= 0 else ''
    data  = [[Paragraph(f'<b>{label}</b>', S(8, True, DARK)),
              Paragraph(record_str, S(11, True, BLUE, TA_CENTER)),
              Paragraph(f'{sign}{avg_net_val:.1f} net rtg', S(9, False, MID, TA_CENTER)),
              Paragraph(extra, S(8, False, MID))]]
    t = Table(data, colWidths=[1.5*inch, 1.2*inch, 1.5*inch, 2.8*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(0,0), LGRAY), ('BACKGROUND',(1,0),(1,0), WHITE),
        ('BACKGROUND', (2,0),(2,0), net_c), ('BACKGROUND',(3,0),(3,0), WHITE),
        ('BOX',(0,0),(-1,-1),0.5,BLUE), ('INNERGRID',(0,0),(-1,-1),0.3,MGRAY),
        ('ALIGN',(0,0),(-1,-1),'CENTER'), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),6), ('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LEFTPADDING',(0,0),(-1,-1),6), ('RIGHTPADDING',(0,0),(-1,-1),6),
    ]))
    return t

def tier_p(r):
    if r <= 15:   return Paragraph('<b>Elite</b>',      S(8, True, GREEN_TXT))
    elif r <= 35: return Paragraph('<b>Above Avg</b>',  S(8, True, colors.HexColor('#1a5c20')))
    elif r <= 65: return Paragraph('<b>Average</b>',    S(8, True, MID))
    elif r <= 85: return Paragraph('<b>Below Avg</b>',  S(8, True, colors.HexColor('#7b3b00')))
    else:         return Paragraph('<b>Concern</b>',    S(8, True, RED_TXT))

def crow(label, val, key, hb, unit='', note=''):
    r, tot, avg, diff = state_rank(key, val, hb)
    sign = '+' if diff > 0 else ''
    return [Paragraph(label, S(8)), f'{val:.1f}{unit}', f'#{r}/{tot}',
            f'{avg:.1f}{unit}', f'{sign}{diff:.1f}{unit}',
            tier_p(r), Paragraph(note, S(8))]

# ─── Page header/footer ───────────────────────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(OPP_HDR)
    canvas.rect(0.5*inch, 10.32*inch, 7.5*inch, 0.28*inch, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont('Helvetica-Bold', 7.5)
    canvas.drawString(0.62*inch, 10.39*inch,
        'MOORPARK RAIDERS  |  OPPONENT SCOUTING REPORT  |  VENTURA COLLEGE PIRATES  |  2025\u201326')
    canvas.setFont('Helvetica', 7.5)
    canvas.drawRightString(7.9*inch, 10.39*inch, f'Page {doc.page}')
    canvas.setFillColor(MID)
    canvas.setFont('Helvetica', 6.5)
    canvas.drawCentredString(4.25*inch, 0.35*inch,
        'Internal Use Only  |  Moorpark Raiders Analytics  |  June 1, 2026')
    canvas.restoreState()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — COVER + EXECUTIVE SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
def page_cover():
    e = []

    # Title block
    for row, sz, bg, tc in [
        (['VENTURA COLLEGE PIRATES'],          24, OPP_HDR, WHITE),
        (['2025\u201326  \u00b7  OPPONENT SCOUTING REPORT  \u00b7  PREPARED BY MOORPARK RAIDERS ANALYTICS'], 10, DARK, GOLD),
    ]:
        t = Table([row], colWidths=[7.5*inch])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),bg), ('TEXTCOLOR',(0,0),(-1,-1),tc),
            ('FONTNAME',(0,0),(-1,-1),'Helvetica-Bold'), ('FONTSIZE',(0,0),(-1,-1),sz),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('TOPPADDING',(0,0),(-1,-1),14), ('BOTTOMPADDING',(0,0),(-1,-1),14),
        ]))
        e.append(t)

    e.append(Spacer(1, 12))

    # Headline stat strip
    def hcell(top, mid, bot, bg=LGRAY, tc=BLUE):
        return [Paragraph(top,  S(14, True,  tc,   TA_CENTER)),
                Paragraph(mid,  S(7.5, False, MID,  TA_CENTER)),
                Paragraph(bot,  S(7,   False, MID,  TA_CENTER))]

    strip = [
        hcell('25-5',              'OVERALL',      'RECORD'),
        hcell('11-1',              'CONF. RECORD',  'WSC North'),
        hcell(f'#{vc_net_rank}/100','NET RATING',   'Statewide Rank'),
        hcell(f'#{vc_wab_rank}/{vc_wab_total}', 'WAB RANK', 'Statewide'),
        hcell(f'+{ta["net_rtg"]:.1f}', 'NET RATING', 'Pts per 100 Poss', LGRAY, RED_TXT),
        hcell(f'{ta["ortg"]:.1f}', 'OFF. RATING',  f'#{ortg_r} of 100 CCCAA', GREEN_BG, GREEN_TXT),
    ]
    t2 = Table([strip], colWidths=[1.25*inch]*6)
    t2.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),LGRAY),
        ('BACKGROUND',(4,0),(4,0), RED_BG),
        ('BACKGROUND',(5,0),(5,0), GREEN_BG),
        ('INNERGRID',(0,0),(-1,-1),0.5,MGRAY),
        ('BOX',(0,0),(-1,-1),1.5,OPP_HDR),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),8), ('BOTTOMPADDING',(0,0),(-1,-1),8),
    ]))
    e.append(t2)
    e.append(Spacer(1, 14))

    # Head-to-head alert box
    if h2h:
        h2h_lines = []
        for g in h2h:
            loc_str = 'at Ventura' if g['location'] == 'Away' else 'vs Ventura (home)'
            net = g['ortg'] - g['drtg']
            h2h_lines.append(
                f"<b>{g['date']} \u2014 {g['result']} {g['team_score']}\u2013{g['opponent_score']} "
                f"({loc_str})</b>  |  Moorpark net: {'+' if net >= 0 else ''}{net:.1f}"
            )
        h2h_txt = '<br/>'.join(h2h_lines)
        h2h_tbl = Table([[Paragraph(
            f'<b>\u26a0 HEAD-TO-HEAD THIS SEASON: Ventura 2 \u2013 Moorpark 0</b><br/>{h2h_txt}',
            S(9, color=colors.HexColor('#7a3000')))]],
            colWidths=[7.5*inch])
        h2h_tbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), colors.HexColor('#fff1e6')),
            ('BOX',(0,0),(-1,-1),1.5, OPP_HDR),
            ('TOPPADDING',(0,0),(-1,-1),8),
            ('BOTTOMPADDING',(0,0),(-1,-1),8),
            ('LEFTPADDING',(0,0),(-1,-1),10),
        ]))
        e.append(h2h_tbl)
        e.append(Spacer(1, 10))

    # Team identity deep-dive
    e += section('Who Is Ventura?', 'Team identity, style of play, and four-factors analysis.')

    e.append(Paragraph(
        f'<b>Core Identity: An interior-anchored offense operating at the top of the CCCAA, '
        f'paired with a defense that is functional but not exceptional.</b> '
        f'Ventura finished 25-5, ranked <b>#{vc_net_rank}/100 in Net Rating</b> '
        f'(+{ta["net_rtg"]:.1f} pts per 100 possessions). Their offense is among the most efficient '
        f'in the state — eFG% {ta["efg_pct"]:.1f}% (#{efg_r}/100) and TS% {ta["ts_pct"]:.1f}% '
        f'(#{ts_r}/100) both rank top 5 statewide — while their defense sits in the middle third '
        f'on most metrics. They win by generating more high-quality possessions than opponents, not '
        f'by strangling them defensively. That asymmetry is the central fact Moorpark must internalize.',
        S(9.5, space_after=8)))

    e.append(Paragraph(
        '<b>Roster Profile \u2014 Size and Scoring Structure</b>',
        S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        f'<b>Roster height:</b> Ventura\u2019s average roster height is {_fmt_height(round(_vc_avg_h))} '
        f'\u2014 ranked <b>#{_vc_h_rank} of {_vc_h_n} teams statewide</b> '
        f'(state average {_fmt_height(round(_state_avg_h))}). They are one of the tallest rosters '
        f'in the CCCAA, anchored by 7\u20190\u2033 Tong Tong and 6\u201910\u2033 Kevin Anigbogu in '
        f'the frontcourt. The height advantage shapes both ends: interior scoring, defensive rebounding, '
        f'and shot-blocking all benefit from their size profile.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Guard Dependence Index (GDI): {_vc_gdi:.1f} \u2014 #{_vc_gdi_rank}/{_vc_gdi_n} statewide '
        f'(state avg {_league_avg_gdi:.1f}).</b> '
        f'GDI measures how reliant a team is on guards for scoring and playmaking. '
        f'Ventura\u2019s {_vc_gdi:.1f} is <b>below the state average</b> of {_league_avg_gdi:.1f}, '
        f'meaning they are more big-dependent than a typical CCCAA team. '
        f'Scoring breaks down as: <b>guards {_vc_guard_pts:.1f}%</b> \u00b7 '
        f'<b>wings {_vc_wing_pts:.1f}%</b> \u00b7 <b>bigs {_vc_big_pts:.1f}%</b>. '
        f'Guards generate {_vc_guard_ast:.1f}% of assists \u2014 Wigington is the primary creator \u2014 '
        f'but Smith and Tong Tong account for nearly a third of team scoring from the paint. '
        f'Defensively this means Moorpark must contest both perimeter shooters '
        f'and a physical frontcourt simultaneously.',
        S(9.5, space_after=8)))

    e.append(Paragraph(
        '<b>Offensive Profile \u2014 The Most Efficient Offense Moorpark Has Faced</b>',
        S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        f'<b>Shooting efficiency (eFG% {ta["efg_pct"]:.1f}%, #{efg_r}/100; TS% {ta["ts_pct"]:.1f}%, '
        f'#{ts_r}/100):</b> Both metrics rank top 5 in the CCCAA. The state average is {efg_avg:.1f}% '
        f'eFG% and {ts_avg:.1f}% TS%; Ventura exceeds both by a wide margin. The engine is Jerimiyah '
        f'Smith (63.6 FG%, TS% top 10 statewide), who generates elite efficiency at high volume from '
        f'the interior. Around him, a four-man three-point rotation creates spacing that makes the '
        f'entire offense difficult to guard. When the defense collapses on Smith, the kick-out '
        f'threes fall. When it doesn\u2019t, Smith scores anyway.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>FT Rate ({ta["ft_rate"]:.1f}, #{ftr_r}/100, avg {ftr_avg:.1f}):</b> '
        f'{"Above-average" if ftr_r <= 40 else "Near-average" if ftr_r <= 60 else "Below-average"} '
        f'access to the foul line. Smith\u2019s post game is the primary driver \u2014 he draws contact '
        f'on interior attempts and converts at the stripe. This distinguishes Ventura from Moorpark\'s '
        f'own offensive profile: they generate free points that perimeter-first teams cannot replicate.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Ball security (TOV% {ta["tov_pct"]:.1f}%, #{tov_r}/100, avg {tov_avg:.1f}%):</b> '
        f'{"Below-average" if tov_r > 60 else "Near-average" if tov_r > 40 else "Above-average"} '
        f'possession care statewide. NST% {_vc_nst_pct:.1f}% (#{nst_r}/100) captures unforced errors '
        f'\u2014 decisions and live-ball mistakes opponents did not directly create. AST/TO {_vc_ast_to:.2f} '
        f'(#{asto_r}/100) and AST Ratio {_vc_ast_ratio:.1f} (#{astr_r}/100) place them '
        f'{"above average" if asto_r <= 40 else "near average" if asto_r <= 60 else "below average"} '
        f'in ball-sharing quality statewide. Their offense is built on individual creation more than '
        f'ball movement \u2014 Smith and Wigington initiate and finish; the others spot up.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Offensive rebounding (OREB% {ta["oreb_pct"]:.1f}%, #{oreb_r}/100, avg {oreb_avg:.1f}%):</b> '
        f'{"Above average" if oreb_r <= 40 else "Near average" if oreb_r <= 60 else "Below average"} '
        f'on the offensive glass. Smith and Tong Tong (OREB% top 5 statewide) are the primary '
        f'crashers. Ventura converts misses into second-chance possessions at a real rate \u2014 '
        f'given Smith\u2019s interior volume, even average offensive rebounding translates to meaningful '
        f'extra production.',
        S(9.5, space_after=8)))

    e.append(Paragraph(
        '<b>Defensive Profile \u2014 Average Across the Board</b>',
        S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        f'<b>Shooting suppression (Opp eFG% {ta["opp_efg_pct"]:.1f}%, #{oefg_r}/100; '
        f'Opp TS% {ta["opp_ts_pct"]:.1f}%, #{ots_r}/100):</b> Both sit in the middle third '
        f'statewide. State average is {oefg_avg:.1f}% Opp eFG% and {ots_avg:.1f}% Opp TS%; '
        f'Ventura is not meaningfully below either. They do not systematically force poor shot '
        f'quality. Their defense holds you to ordinary efficiency, not below it \u2014 which means '
        f'Moorpark\u2019s offense, executing at its normal level, should be able to score.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Turnover pressure (Opp TOV% {ta["opp_tov_pct"]:.1f}%, #{otov_r}/100, '
        f'avg {otov_avg:.1f}%):</b> '
        f'{"Below average" if otov_r > 60 else "Near average" if otov_r > 40 else "Above average"} '
        f'at generating opponent turnovers. STL% {_vc_stl_pct:.1f}% (#{stlpct_r}/100) and '
        f'BLK% {_vc_blk_pct:.1f}% (#{blkpct_r}/100) are both outside the top 50 statewide; '
        f'HKM% {_vc_hkm_pct:.1f}% (#{hkm_r}/100) confirms this is a defense that does not disrupt '
        f'through steals or shot-blocking at above-average rates. STL/TOV {_vc_stl_to:.2f} '
        f'(#{stlto_r}/100). Their disruption numbers are ordinary.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Defensive rebounding ({ta["dreb_pct"]:.1f}%, #{dreb_r}/100, avg {dreb_avg:.1f}%) '
        f'and foul discipline (FC/40 {ta["fc_per_40"]:.1f}, #{fc40_r}/100):</b> '
        f'DREB% is {"above average" if dreb_r <= 40 else "near average" if dreb_r <= 60 else "below average"} '
        f'\u2014 they control the defensive glass at a reasonable level. Their foul rate is a '
        f'genuine strength: FC/40 {ta["fc_per_40"]:.1f} (#{fc40_r}/100) means they contest without '
        f'giving away free throws. PF Eff {_vc_pf_eff:.2f} (#{pfeff_r}/100) \u2014 steals plus blocks '
        f'per foul \u2014 reflects a disciplined scheme.',
        S(9.5, space_after=8)))

    e.append(Paragraph(
        '<b>Pace and Style</b>',
        S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        f'Ventura plays at {"above-average" if pace_r <= 40 else "near-average" if pace_r <= 60 else "below-average"} '
        f'pace: {ta["possessions"]:.1f} possessions per game (#{pace_r}/100, state avg {pace_avg:.1f}). '
        f'Their style is inside-out: establish Smith in the post or at the elbow, create kick-outs '
        f'for a four-man shooting rotation. This is not a transition team \u2014 their offense is most '
        f'dangerous in half-court settings where Smith can operate with space. The spacing created by '
        f'their perimeter shooters makes help defense extremely costly, which explains why their '
        f'efficiency numbers sit top 5 nationally despite modest ball-movement metrics.',
        S(9.5, space_after=8)))

    e.append(Paragraph(
        '<b>Moorpark-Specific Context</b>',
        S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        f'Ventura is 2\u20130 against Moorpark this season. Smith scored 17 pts (Jan 10, 76\u201384) '
        f'and 22 pts (Feb 4, 85\u201390) across both meetings. Moorpark posted ORTg of 104.2 and 112.6 '
        f'in those games \u2014 above average efficiency \u2014 but Ventura\u2019s DRTg in those '
        f'same matchups allowed 115.2 and 119.2, meaning neither defense was functional. Both games '
        f'were high-scoring affairs decided by single digits. Smith\'s efficiency advantage \u2014 '
        f'63.6 FG% and 6.3 FTA/g \u2014 was the decisive individual differential on the floor.',
        S(9.5, space_after=8)))

    # ── Two-column Adv Offense / Adv Defense tables ──────────────────────────
    def _tier_badge(rank, n):
        pct = rank / n * 100
        if pct <=  15: return Paragraph('<b>Elite</b>',      S(7.5, True, GREEN_TXT, TA_CENTER))
        if pct <=  35: return Paragraph('<b>Above Avg</b>',  S(7.5, True, colors.HexColor('#1a5c20'), TA_CENTER))
        if pct <=  65: return Paragraph('<b>Average</b>',    S(7.5, False, MID, TA_CENTER))
        if pct <=  85: return Paragraph('<b>Below Avg</b>',  S(7.5, True, colors.HexColor('#7b3b00'), TA_CENTER))
        return              Paragraph('<b>Poor</b>',         S(7.5, True, RED_TXT, TA_CENTER))

    def _adv_row(label, val, unit, rank, n):
        return [
            Paragraph(label, S(7.5, False, DARK)),
            Paragraph(f'{val:.1f}{unit}', S(8.5, True, BLUE, TA_CENTER)),
            Paragraph(f'#{rank}/{n}',     S(7.5, False, MID, TA_CENTER)),
            _tier_badge(rank, n),
        ]

    _N = _n  # 100 teams
    off_cw = [1.5*inch, 0.62*inch, 0.62*inch, 0.71*inch]
    def_cw = [1.5*inch, 0.62*inch, 0.62*inch, 0.71*inch]

    off_hdr = [Paragraph('<b>ADV OFFENSE</b>', S(8, True, WHITE, TA_CENTER)),
               Paragraph('<b>VALUE</b>',       S(7, True, WHITE, TA_CENTER)),
               Paragraph('<b>RANK</b>',        S(7, True, WHITE, TA_CENTER)),
               Paragraph('<b>TIER</b>',        S(7, True, WHITE, TA_CENTER))]
    def_hdr = [Paragraph('<b>ADV DEFENSE</b>', S(8, True, WHITE, TA_CENTER)),
               Paragraph('<b>VALUE</b>',       S(7, True, WHITE, TA_CENTER)),
               Paragraph('<b>RANK</b>',        S(7, True, WHITE, TA_CENTER)),
               Paragraph('<b>TIER</b>',        S(7, True, WHITE, TA_CENTER))]

    off_rows = [
        off_hdr,
        _adv_row('ORtg',         ta['ortg'],         '',  ortg_r,  _N),
        _adv_row('eFG%',         ta['efg_pct'],      '%', efg_r,   _N),
        _adv_row('TS%',          ta['ts_pct'],       '%', ts_r,    _N),
        _adv_row('OREB%',        ta['oreb_pct'],     '%', oreb_r,  _N),
        _adv_row('FT Rate',      ta['ft_rate'],      '',  ftr_r,   _N),
        _adv_row('3PAR',         _vc_3par,           '%', tpar_r,  _N),
        _adv_row('AST Rate',     ta['ast_rate'],     '%', arate_r, _N),
        _adv_row('AST Ratio',    _vc_ast_ratio,      '',  astr_r,  _N),
        _adv_row('AST/TO',       _vc_ast_to,         '',  asto_r,  _N),
        _adv_row('TOV%',         ta['tov_pct'],      '%', tov_r,   _N),
        _adv_row('NST%',         _vc_nst_pct,        '%', nst_r,   _N),
        _adv_row('Tempo',        ta['possessions'],  '',  pace_r,  _N),
    ]
    def_rows = [
        def_hdr,
        _adv_row('DRtg',         ta['drtg'],         '',  drtg_r,  _N),
        _adv_row('Opp eFG%',     ta['opp_efg_pct'],  '%', oefg_r,  _N),
        _adv_row('Opp TS%',      ta['opp_ts_pct'],   '%', ots_r,   _N),
        _adv_row('DREB%',        ta['dreb_pct'],     '%', dreb_r,  _N),
        _adv_row('Opp FT Rate',  ta['opp_ft_rate'],  '',  oftr_r,  _N),
        _adv_row('Opp TOV%',     ta['opp_tov_pct'],  '%', otov_r,  _N),
        _adv_row('STL%',         _vc_stl_pct,        '%', stlpct_r,_N),
        _adv_row('BLK%',         _vc_blk_pct,        '%', blkpct_r,_N),
        _adv_row('HKM%',         _vc_hkm_pct,        '%', hkm_r,   _N),
        _adv_row('STL/TOV',      _vc_stl_to,         '',  stlto_r, _N),
        _adv_row('PF Eff',       _vc_pf_eff,         '',  pfeff_r, _N),
        _adv_row('STL/PF',       _vc_stl_pf,         '',  stlpf_r, _N),
        _adv_row('BLK/PF',       _vc_blk_pf,         '',  blkpf_r, _N),
        _adv_row('FC/40',        ta['fc_per_40'],     '',  fc40_r,  _N),
    ]

    def _make_adv_table(rows, cw):
        t = Table(rows, colWidths=cw)
        style = [
            ('BACKGROUND', (0,0),(-1,0), OPP_HDR),
            ('INNERGRID',  (0,0),(-1,-1), 0.3, MGRAY),
            ('BOX',        (0,0),(-1,-1), 0.7, OPP_HDR),
            ('ALIGN',      (0,0),(-1,-1), 'CENTER'),
            ('ALIGN',      (0,1),(0,-1),  'LEFT'),
            ('VALIGN',     (0,0),(-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0),(-1,-1), 4),
            ('BOTTOMPADDING',(0,0),(-1,-1), 4),
            ('LEFTPADDING',(0,0),(0,-1),  5),
        ]
        for i in range(1, len(rows)):
            style.append(('BACKGROUND',(0,i),(-1,i), LGRAY if i%2==1 else WHITE))
        t.setStyle(TableStyle(style))
        return t

    off_tbl = _make_adv_table(off_rows, off_cw)
    def_tbl = _make_adv_table(def_rows, def_cw)
    wrapper = Table([[off_tbl, '', def_tbl]], colWidths=[3.45*inch, 0.1*inch, 3.45*inch])
    wrapper.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),0),
        ('RIGHTPADDING',(0,0),(-1,-1),0),
    ]))
    e.append(wrapper)
    e.append(Spacer(1, 6))

    e.append(PageBreak())
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — WHO IS VENTURA? (Team Identity + Four Factors)
# ═══════════════════════════════════════════════════════════════════════════════
def page_identity():
    e = []
    e += section('Who Is Ventura?', 'Team identity, system, and statistical profile.')

    e.append(Paragraph(
        f'Ventura finished 25-5, winning the WSC North at 11-1. '
        f'ORTg: {ta["ortg"]:.1f} (#{ortg_r}/100 statewide). '
        f'DRTg: {ta["drtg"]:.1f} (#{drtg_r}/100 statewide). '
        f'Net rating: +{ta["net_rtg"]:.1f} (#{vc_net_rank}/100). '
        f'Point differential: +{avgs["PTS"]-opp_avgs["PTS"]:.1f} PPG. '
        f'Smith leads the team at 20.1 PPG on 63.6 FG% in 29.0 MPG. '
        f'Wigington leads in assists at 7.3 APG. '
        f'Four rotation players averaged 3.0+ three-point attempts per game '
        f'(Wigington 4.9, Bellamy 5.0, Cigar 4.1, Wilson 4.0).',
        S(9.5, space_after=8)))

    e.append(Paragraph('<b>Offensive Profile — Elite Efficiency, High Tempo</b>',
                       S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        f'<b>Shooting efficiency (eFG% {ta["efg_pct"]:.1f}%, #{efg_r}/100; '
        f'TS% {ta["ts_pct"]:.1f}%, #{ts_r}/100):</b> '
        f'Both metrics rank top 5 statewide. State average eFG%: {efg_avg:.1f}%; '
        f'Ventura\'s {ta["efg_pct"]:.1f}% exceeds it by {ta["efg_pct"]-efg_avg:.1f} points. '
        f'State average TS%: {ts_avg:.1f}%; Ventura\'s {ta["ts_pct"]:.1f}% exceeds it by {ta["ts_pct"]-ts_avg:.1f} points. '
        f'Smith: 63.6 FG% on the team-highest FGA total. '
        f'Three-point rotation: Cigar 42.9% (4.1 3PA), Wigington 36.6% (4.9 3PA), '
        f'Wilson 36.4% (4.0 3PA), Bellamy 31.0% (5.0 3PA). '
        f'Team 3PA: {avgs.get("3PA", 22.2):.1f}/g; team 3P%: {avgs.get("3P%", 34.9):.1f}%.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Free throw rate (FT Rate {ta["ft_rate"]:.1f}, #{ftr_r}/100, avg {ftr_avg:.1f}):</b> '
        f'Above average. They get to the line, and Wigington (81.6 FT%) and Bellamy (86.3 FT%) '
        f'are reliable finishers. Smith (68.3 FT%) and Anigbogu (66.1 FT%) are exposed in '
        f'intentional-foul situations. Late game, attacking the free throw disparity is a real option.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Offensive rebounding (OREB% {ta["oreb_pct"]:.1f}%, #{oreb_r}/100, '
        f'avg {oreb_avg:.1f}%):</b> '
        f'Above average and dangerous. Smith (3.2 OREB/g), Tong Tong (2.2), and '
        f'Anigbogu (1.4) all crash consistently. They generate second-chance points '
        f'at a rate that meaningfully inflates their offensive output. '
        f'Moorpark must box out every single possession — this is not a team that '
        f'gives you easy defensive rebounds.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Turnover rate (TOV% {ta["tov_pct"]:.1f}%, #{tov_r}/100, avg {tov_avg:.1f}%):</b> '
        f'Team TOV%: {ta["tov_pct"]:.1f}% (#{tov_r}/100, state avg {tov_avg:.1f}%). '
        f'Wigington leads the roster with 3.8 TOV/g — the highest among all rotation players. '
        f'No other rotation player exceeds 2.0 TOV/g. '
        f'Opp TOV% (turnover generation): {ta["opp_tov_pct"]:.1f}% (#{otov_r}/100, state avg {otov_avg:.1f}%).',
        S(9.5, space_after=8)))

    e.append(Paragraph(f'<b>Defensive Profile — #{drtg_r}/100 DRTg Statewide</b>',
                       S(9.5, True, BLUE, space_after=3)))

    e.append(Paragraph(
        f'<b>Opponent eFG% ({ta["opp_efg_pct"]:.1f}%, #{oefg_r}/100):</b> '
        f'State average: {oefg_avg:.1f}%. Ventura\'s Opp eFG% ranks #{oefg_r}/100 — '
        f'outside the top 45 statewide for shooting suppression. '
        f'Opp TS%: {ta["opp_ts_pct"]:.1f}% (#{ots_r}/100). '
        f'In the two head-to-head games, Moorpark posted ORTg of 104.2 (Jan 10) and 112.6 (Feb 4).',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Forced turnovers (Opp TOV% {ta["opp_tov_pct"]:.1f}%, #{otov_r}/100):</b> '
        f'State average: {otov_avg:.1f}%. Ventura\'s Opp TOV% ranks #{otov_r}/100 — '
        f'outside the top 50 CCCAA teams in opponent turnover-forcing rate. '
        f'Turnovers committed by Moorpark in a head-to-head game are a '
        f'primary variable within Moorpark\'s control, not a product of elite defensive pressure.',
        S(9.5, space_after=6)))

    e.append(Paragraph(
        f'<b>Defensive rebounding (DREB% {ta["dreb_pct"]:.1f}%, #{dreb_r}/100, '
        f'state avg {dreb_avg:.1f}%):</b> '
        f'Ventura\'s DREB% of {ta["dreb_pct"]:.1f}% ranks #{dreb_r}/100. '
        f'Moorpark\'s OREB%: {mp_adv["team"].get("oreb_pct", 0):.1f}%. '
        f'Based on these figures, the majority of Ventura\'s missed shots '
        f'will be recovered by Ventura.',
        S(9.5, space_after=8)))

    e.append(Paragraph('<b>Season Arc</b>', S(9.5, True, BLUE, space_after=3)))

    early_nets = [g['net'] for g in early_g]
    late_nets  = [g['net'] for g in late_g]
    e_avg = sum(early_nets)/len(early_nets) if early_nets else 0
    l_avg = sum(late_nets)/len(late_nets) if late_nets else 0

    e.append(Paragraph(
        f'Ventura went 14-4 in non-conference play and 11-1 in WSC North conference play. '
        f'Their single conference loss was a home game against Allan Hancock (net rank #27) '
        f'on February 18. They were eliminated from the state playoffs by San Diego City. '
        f'Average net rating in games 1\u201315: {e_avg:+.1f}. '
        f'Average net rating in games 16\u201330: {l_avg:+.1f}. '
        f'Both Moorpark defeats (Jan 10 and Feb 4) occurred in the games 16\u201330 window.',
        S(9.5, space_after=6)))

    e.append(PageBreak())
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — ADVANCED METRICS TABLE
# ═══════════════════════════════════════════════════════════════════════════════
def page_analytics():
    e = []
    e += section('Advanced Analytics: Statewide Context',
                 'All key efficiency metrics with CCCAA state rank. Rank 1 = best in state.')

    ctx_cw = [1.65*inch, 0.75*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.9*inch, 1.55*inch]
    ctx_h  = ['METRIC', 'VENTURA', 'RANK', 'ST. AVG', 'VS AVG', 'TIER', 'CONTEXT']

    ctx_rows = [
        crow('Off. Rating (ORTg)',    ta['ortg'],        'ortg',        True,  '', 'Points scored per 100 possessions'),
        crow('Def. Rating (DRTg)',    ta['drtg'],        'drtg',        False, '', 'Points allowed per 100 possessions'),
        crow('Net Rating',            ta['net_rtg'],     'net_rtg',     True,  '', 'ORTg minus DRTg'),
        crow('True Shooting%',        ta['ts_pct'],      'ts_pct',      True,  '%','Overall shooting efficiency (all types)'),
        crow('Opp True Shooting%',    ta['opp_ts_pct'],  'opp_ts_pct',  False, '%','How well opponents shoot vs VCC'),
        crow('eFG% (offense)',         ta['efg_pct'],     'efg_pct',     True,  '%','FG% adjusted for 3-point value'),
        crow('Opp eFG% (defense)',     ta['opp_efg_pct'],'opp_efg_pct', False, '%','Opponent eFG%, shooting suppression'),
        crow('Turnover % (offense)',  ta['tov_pct'],     'tov_pct',     False, '%','How often Ventura turns it over'),
        crow('Opp Turnover % (def)',  ta['opp_tov_pct'], 'opp_tov_pct', True,  '%','How often Ventura forces opponent TOs'),
        crow('Off. Reb% (offense)',   ta['oreb_pct'],    'oreb_pct',    True,  '%','% of own missed shots recovered'),
        crow('Def. Reb% (defense)',   ta['dreb_pct'],    'dreb_pct',    True,  '%','% of opponent missed shots recovered'),
        crow('FT Rate (offense)',     ta['ft_rate'],     'ft_rate',     True,  '', 'FTA per FGA'),
        crow('Opp FT Rate (defense)', ta['opp_ft_rate'], 'opp_ft_rate', False, '', 'How often opponents draw fouls vs VCC'),
        crow('Pace (poss/game)',      ta['possessions'], 'pace',        True,  '', 'Possessions per game, above average'),
        crow('PPG',                   avgs['PTS'],       'ppg',         True,  '', 'Points per game'),
        crow('Opp PPG',               opp_avgs['PTS'],   'oppg',        False, '', 'Points allowed per game'),
    ]

    row_colors = []
    for i, r_data in enumerate(ctx_rows):
        r_val = int(r_data[2].split('/')[0][1:])
        if r_val <= 15:
            row_colors.append(('BACKGROUND', (0,i+1),(-1,i+1), colors.HexColor('#f0fff4')))
        elif r_val >= 86:
            row_colors.append(('BACKGROUND', (0,i+1),(-1,i+1), colors.HexColor('#fff0f0')))

    ct = Table([ctx_h]+ctx_rows, colWidths=ctx_cw)
    ct.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),TH_BG), ('TEXTCOLOR',(0,0),(-1,0),WHITE),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'), ('FONTSIZE',(0,0),(-1,0),8),
        ('FONTSIZE',(0,1),(-1,-1),8),
        ('ALIGN',(0,0),(-1,-1),'CENTER'), ('ALIGN',(0,1),(0,-1),'LEFT'),
        ('ALIGN',(6,1),(6,-1),'LEFT'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,ALT]),
        ('INNERGRID',(0,0),(-1,-1),0.3,MGRAY), ('BOX',(0,0),(-1,-1),0.5,TH_BG),
        ('TOPPADDING',(0,0),(-1,-1),3), ('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('LEFTPADDING',(0,0),(-1,-1),4), ('RIGHTPADDING',(0,0),(-1,-1),4),
    ] + row_colors))
    e.append(ct)
    e.append(Spacer(1, 10))

    # Four factors comparison
    e += section('Four Factors Comparison', 'Ventura vs. Moorpark — the two matchup pillars.')

    ff_h = ['FACTOR', 'VENTURA OFF', 'MOORPARK DEF', 'EDGE', 'VENTURA DEF', 'MOORPARK OFF', 'EDGE']
    mp_ta = mp_adv['team']

    def edge(v_val, m_val, hb=True):
        adv = (v_val > m_val) if hb else (v_val < m_val)
        s = 'VCC' if adv else 'MPC'
        diff = abs(v_val - m_val)
        return Paragraph(f'<b>{s} +{diff:.1f}</b>',
                         S(8, True, RED_TXT if s=='VCC' else GREEN_TXT, TA_CENTER))

    ff_r = [
        ['eFG%',
         f'{ta["efg_pct"]:.1f}%',      f'{mp_ta["opp_efg_pct"]:.1f}%',
         edge(ta['efg_pct'], mp_ta['opp_efg_pct']),
         f'{ta["opp_efg_pct"]:.1f}%',  f'{mp_ta["efg_pct"]:.1f}%',
         edge(mp_ta['efg_pct'], ta['opp_efg_pct'])],
        ['TOV%',
         f'{ta["tov_pct"]:.1f}%',      f'{mp_ta["opp_tov_pct"]:.1f}%',
         edge(mp_ta['opp_tov_pct'], ta['tov_pct']),
         f'{ta["opp_tov_pct"]:.1f}%',  f'{mp_ta["tov_pct"]:.1f}%',
         edge(ta['opp_tov_pct'], mp_ta['tov_pct'])],
        ['OREB%',
         f'{ta["oreb_pct"]:.1f}%',     f'{mp_ta["dreb_pct"]:.1f}%',
         edge(ta['oreb_pct'], 100-mp_ta['dreb_pct']),
         f'{ta["dreb_pct"]:.1f}%',     f'{mp_ta["oreb_pct"]:.1f}%',
         edge(mp_ta['oreb_pct'], 100-ta['dreb_pct'])],
        ['FT Rate',
         f'{ta["ft_rate"]:.1f}',       f'{mp_ta["opp_ft_rate"]:.1f}',
         edge(ta['ft_rate'], mp_ta['opp_ft_rate']),
         f'{ta["opp_ft_rate"]:.1f}',   f'{mp_ta["ft_rate"]:.1f}',
         edge(mp_ta['ft_rate'], ta['opp_ft_rate'])],
    ]
    ff_cw = [1.0*inch, 0.95*inch, 0.95*inch, 0.85*inch, 0.95*inch, 0.95*inch, 0.85*inch]
    ff_t = Table([ff_h]+ff_r, colWidths=ff_cw)
    ff_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),TH_BG), ('TEXTCOLOR',(0,0),(-1,0),WHITE),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'), ('FONTSIZE',(0,0),(-1,0),8),
        ('FONTSIZE',(0,1),(-1,-1),8),
        ('ALIGN',(0,0),(-1,-1),'CENTER'), ('ALIGN',(0,1),(0,-1),'LEFT'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,ALT]),
        ('INNERGRID',(0,0),(-1,-1),0.3,MGRAY), ('BOX',(0,0),(-1,-1),0.5,TH_BG),
        ('TOPPADDING',(0,0),(-1,-1),4), ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ('LEFTPADDING',(0,0),(-1,-1),4), ('RIGHTPADDING',(0,0),(-1,-1),4),
    ]))
    e.append(ff_t)
    e.append(PageBreak())
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — PLAYER PROFILES
# ═══════════════════════════════════════════════════════════════════════════════
def player_card(name, p_data, adv_data, narrative_txt):
    """Build a single player card in Moorpark report format."""
    avg  = p_data['averages']
    tot  = p_data['totals']
    gp   = avg.get('games', 0)
    mpg  = avg.get('MIN', 0)

    # Position & role
    pos_code  = vc_pos_map.get(name, '—')
    pos_name  = pos_full.get(pos_code, pos_code)
    usage     = adv_data.get('usage_pct', 0)
    role_lbl, role_hex = kenpom_player_role(usage, mpg)

    # Individual ratings
    ind_ortg = adv_data.get('ind_ortg', 0)
    ind_drtg = adv_data.get('ind_drtg', 0)
    ind_net  = ind_ortg - ind_drtg
    net_c    = ('#34a853' if ind_net > 5 else '#e74c3c' if ind_net < -5 else '#aab8d0')

    # Height
    _ht_in  = vc_height_in.get(name, 0)
    _ht_str = f' · {_fmt_height(_ht_in)}' if _ht_in else ''

    # ── Header ──
    hdr_left   = Paragraph(f'<b>{name}</b>', S(11, True, WHITE))
    hdr_center = Paragraph(
        f'<font color="{role_hex}"><b>{role_lbl}</b></font>  '
        f'<font color="#aab8d0">{pos_code}{_ht_str} · {pos_name}</font>  '
        f'<font color="#ffd700">{usage:.1f}% poss</font>',
        S(8, False, GOLD, TA_CENTER))
    if ind_ortg > 0:
        hdr_right = Paragraph(
            f'<font color="#aab8d0">{gp} GP · {mpg:.1f} MPG</font><br/>'
            f'<font color="#aab8d0">ORtg</font> <b>{ind_ortg:.1f}</b>  '
            f'<font color="#aab8d0">DRtg</font> <b>{ind_drtg:.1f}</b>  '
            f'<font color="{net_c}"><b>Net {ind_net:+.1f}</b></font>',
            S(8, False, WHITE, TA_RIGHT))
    else:
        hdr_right = Paragraph(
            f'<font color="#aab8d0">{gp} GP · {mpg:.1f} MPG</font>',
            S(8, False, WHITE, TA_RIGHT))

    hdr = Table([[hdr_left, hdr_center, hdr_right]],
                colWidths=[2.8*inch, 2.5*inch, 2.2*inch])
    hdr.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), DARK),
        ('TOPPADDING',(0,0),(-1,-1),8), ('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('LEFTPADDING',(0,0),(-1,-1),8), ('RIGHTPADDING',(0,0),(-1,-1),8),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
    ]))

    items = [hdr]

    # ── Narrative (with auto top-100 sentence woven in) ──
    top100 = get_top100(avg, adv_data, tot, mpg)
    full_narrative = narrative_txt or ''
    if top100:
        parts = ', '.join(
            f'<b>{lbl} {val:.1f}{unit}</b> (#{r}/{n})'
            for lbl, val, unit, r, n in top100
        )
        full_narrative = (full_narrative.rstrip() + ' ' if full_narrative else '') + \
            f'Ranks top 100 statewide in {parts}.'
    if full_narrative:
        items.append(Paragraph(full_narrative, S(8.5, space_after=3)))

    # ── Advanced analytics prose line (MPG ≥ 12 and ind_ortg > 0) ──
    if mpg >= 12 and ind_ortg > 0:
        ast_rate = adv_data.get('ast_rate', 0)
        tov_pct  = adv_data.get('tov_pct', 0)
        oreb_pct = adv_data.get('oreb_pct', 0)
        dreb_pct = adv_data.get('dreb_pct', 0)
        stl_pct  = adv_data.get('stl_pct', 0)
        blk_pct  = adv_data.get('blk_pct', 0)
        ft_rate  = adv_data.get('ft_rate', 0)
        twoa = tot.get('FGA',0) - tot.get('3PA',0)
        twom = tot.get('FGM',0) - tot.get('3PM',0)
        twop = round(twom/twoa*100, 1) if twoa > 0 else 0.0
        tpp  = avg.get('3P%', 0)
        ftp  = avg.get('FT%', 0)

        def _ar(r, n): return f'#{r}/{n}' if r > 0 else '—'
        r_ortg, n_ortg = adv_rank('ind_ortg', ind_ortg, True)
        r_drtg, n_drtg = adv_rank('ind_drtg', ind_drtg, False)
        r_ast,  n_ast  = adv_rank('ast_rate', ast_rate, True)
        r_tov,  n_tov  = adv_rank('tov_pct',  tov_pct,  False)
        r_oreb, n_oreb = adv_rank('oreb_pct', oreb_pct, True)
        r_dreb, n_dreb = adv_rank('dreb_pct', dreb_pct, True)
        r_stl,  n_stl  = adv_rank('stl_pct',  stl_pct,  True)
        r_blk,  n_blk  = adv_rank('blk_pct',  blk_pct,  True)
        r_2p = r_n2p = 0
        if twop > 0: r_2p, r_n2p = adv_rank('twop', twop, True)
        r_3p = r_n3p = 0
        if tpp > 0:  r_3p, r_n3p = adv_rank('tpp',  tpp,  True)
        r_ft = r_nft = 0
        if ftp > 0:  r_ft, r_nft = adv_rank('ftp',  ftp,  True)

        prose = (
            f'Ind ORtg {ind_ortg:.1f} ({_ar(r_ortg,n_ortg)}) · '
            f'Ind DRtg {ind_drtg:.1f} ({_ar(r_drtg,n_drtg)}) · '
            f'%Poss {usage:.1f}% · '
            f'AST Rate {ast_rate:.1f}% ({_ar(r_ast,n_ast)}) · '
            f'TOV% {tov_pct:.1f}% ({_ar(r_tov,n_tov)}) · '
            f'OREB% {oreb_pct:.1f}% ({_ar(r_oreb,n_oreb)}) · '
            f'DREB% {dreb_pct:.1f}% ({_ar(r_dreb,n_dreb)}) · '
            f'STL% {stl_pct:.1f}% ({_ar(r_stl,n_stl)}) · '
            f'BLK% {blk_pct:.1f}% ({_ar(r_blk,n_blk)}) · '
            f'FT Rate {ft_rate:.2f} · '
            f'2P% {twop:.1f}% ({_ar(r_2p,r_n2p)}) · '
            f'3P% {tpp:.1f}% ({_ar(r_3p,r_n3p)}) · '
            f'FT% {ftp:.1f}% ({_ar(r_ft,r_nft)})'
        )
        items.append(Paragraph(prose,
            S(7.5, italic=True, color=colors.HexColor('#aab8d0'), space_after=3)))

    # ── Stat strip (10 cols × 0.75") ──
    ppg  = avg.get('PTS', 0);  rpg = avg.get('REB', 0);  apg = avg.get('AST', 0)
    spg  = avg.get('STL', 0);  bpg = avg.get('BLK', 0);  topg = avg.get('TO', 0)
    efg  = adv_data.get('efg_pct', 0)
    tpp3 = avg.get('3P%', 0);  tpa = avg.get('3PA', 0)
    ftp2 = avg.get('FT%', 0);  tsp = adv_data.get('ts_pct', 0)

    def _sv(val, lbl):
        return Paragraph(f'<b>{val}</b><br/><font size="7">{lbl}</font>',
                         S(13, False, DARK, TA_CENTER))

    strip = Table([[
        _sv(f'{ppg:.1f}',        'PPG'),
        _sv(f'{rpg:.1f}',        'RPG'),
        _sv(f'{apg:.1f}',        'APG'),
        _sv(f'{spg:.1f}',        'SPG'),
        _sv(f'{bpg:.1f}',        'BPG'),
        _sv(f'{topg:.1f}',       'TO/G'),
        _sv(f'{efg:.1f}%',       'eFG%'),
        _sv(f'{tpp3:.1f}%',      f'3P% ({tpa:.1f}/G)'),
        _sv(f'{ftp2:.1f}%',      'FT%'),
        _sv(f'{tsp:.1f}%',       'TS%'),
    ]], colWidths=[0.75*inch]*10)
    strip.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), LGRAY),
        ('INNERGRID',(0,0),(-1,-1),0.3,MGRAY),
        ('BOX',(0,0),(-1,-1),0.5,MGRAY),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),6),
        ('BOTTOMPADDING',(0,0),(-1,-1),6),
    ]))
    items.append(strip)

    # ── State rank context ──
    r_ppg,  n_ppg  = plyr_rank('ppg',     ppg,  True)
    r_apg,  n_apg  = plyr_rank('apg',     apg,  True)
    r_ts,   n_ts   = plyr_rank('ts_pct',  tsp,  True)  if tsp  > 0 else (0, 0)
    r_tpp4, n_tpp4 = plyr_rank('tpp',     tpp3, True)  if tpp3 > 0 else (0, 0)
    tov_p  = adv_data.get('tov_pct', 0)
    r_tov2, n_tov2 = plyr_rank('tov_pct', tov_p, False) if tov_p > 0 else (0, 0)
    ctx_parts = [f'PPG #{r_ppg}/{n_ppg}', f'APG #{r_apg}/{n_apg}']
    if r_ts   > 0: ctx_parts.append(f'TS% #{r_ts}/{n_ts}')
    if r_tpp4 > 0: ctx_parts.append(f'3P% #{r_tpp4}/{n_tpp4}')
    if r_tov2 > 0: ctx_parts.append(f'TOV% #{r_tov2}/{n_tov2}')
    ctx_str = (f'State context ({len(all_players)} players, Min% >10%): '
               + ' · '.join(ctx_parts))
    items.append(Paragraph(ctx_str,
        S(7.5, italic=True, color=MID, space_after=4)))

    return KeepTogether(items + [Spacer(1, 10)])


def page_players():
    e = []
    e += section('Player Profiles — Ventura Rotation',
                 'All meaningful rotation players. Christian Aukuso is no longer on the roster.')

    pm = {p['name']: p for p in players_raw}

    # ── Jerimiyah Smith ──
    e.append(player_card(
        'Jerimiyah Smith', pm['Jerimiyah Smith'],
        plyr_adv.get('Jerimiyah Smith', {}),
        'Smith is Ventura\u2019s primary offensive engine and one of the most efficient high-volume '
        'scorers in the CCCAA this season. His 20.1 PPG ranks #6 statewide (840 qualified players) '
        'and his 63.6 FG% places him #12 among all players averaging 5+ FGA/g \u2014 a rare combination '
        'of volume and precision. His TS% of 67.1% ranks #8 among 467 players with Min% \u226530%, '
        'driven by elite interior efficiency and 6.3 FTA/g. At 9.7 RPG (#9 statewide) he is among '
        'the premier rebounders in the state in both directions: OREB% 13.7% (#49/467) and DREB% 27.0% '
        '(#37/467) \u2014 top 11% in offensive rebounding, top 8% in defensive rebounding among all '
        'qualified players statewide. He crashes both ends and converts second chances at an elite rate. '
        'In two meetings this season he scored 17 (Jan 10, 76\u201384 L for Ventura) '
        'and 22 (Feb 4, 85\u201390 L for Ventura).'
    ))

    # ── Snookey Wigington ──
    e.append(player_card(
        'Snookey Wigington', pm['Snookey Wigington'],
        plyr_adv.get('Snookey Wigington', {}),
        'Wigington is one of the highest-volume point guards in the state. His 7.3 APG ranks #3 '
        'among all 832 qualified passers statewide, and his 2.2 SPG ranks #12 among 826 qualified '
        'players \u2014 an unusual combination of elite playmaking and elite ball pressure. '
        'His usage rate of 31.2% (#41 statewide) reflects the degree to which Ventura\u2019s offense '
        'runs through him. The tradeoff is a team-high 3.8 TOV/g, producing an A/TO ratio of 1.92 '
        '\u2014 his passing creates more than it costs, but his turnovers are the highest on the roster. '
        '36.6 3P% on 4.9 3PA/g is functional; his primary value is pass creation and on-ball pressure.'
    ))

    # ── Kam\'Ron Cigar ──
    e.append(player_card(
        "Kam'Ron Cigar", pm["Kam'Ron Cigar"],
        plyr_adv.get("Kam'Ron Cigar", {}),
        'Cigar is the most efficient perimeter shooter in the Ventura rotation. His 42.9 3P% '
        'on 4.1 3PA/g ranks #45 among 720 qualified shooters statewide \u2014 top 7% by '
        'percentage on genuine volume. Overall FG% of 49.6% (top 12% statewide at his '
        'volume) reflects above-average two-point finishing as well. TS% 60.7% ranks #55 '
        'among 467 qualified players. His Ind ORtg of 112.9 (#95/467) is consistent with '
        'his efficiency numbers. He appeared in 27 of 30 team games; availability requires '
        'confirmation before each contest.'
    ))

    # ── Baron Bellamy ──
    e.append(player_card(
        'Baron Bellamy', pm['Baron Bellamy'],
        plyr_adv.get('Baron Bellamy', {}),
        'Bellamy generates the most three-point attempts on the roster at 5.0 3PA/g, but '
        'his 31.0 3P% ranks #345 among 720 statewide shooters \u2014 below average efficiency '
        'at high volume. His TS% of 50.7% (#300/467) is below the statewide median. '
        'The production of value comes elsewhere: 4.5 RPG with a 7.0% OREB rate, '
        '2.5 FTA/g at 86.3 FT%, and full-starter minutes (29.0 MPG, 30 GP). '
        'Despite the shooting inefficiency, Ventura plays him 29 minutes per game because '
        'of his rebounding, foul-drawing, and floor spacing role.'
    ))

    # ── Jeremiah Wilson ──
    e.append(player_card(
        'Jeremiah Wilson', pm['Jeremiah Wilson'],
        plyr_adv.get('Jeremiah Wilson', {}),
        'Wilson\u2019s per-game numbers (8.9 PPG, 20.0 MPG) understate his offensive impact. '
        'His Ind ORtg of 123.5 ranks #22 among 467 qualified players statewide \u2014 top 5% \u2014 '
        'indicating that Ventura scores at an elite rate when the ball goes through him. '
        'This efficiency is supported by a low turnover rate (0.7 TOV/g, the lowest in the '
        'rotation by a significant margin) and a 36.4 3P% on 4.0 3PA/g. He is a low-usage, '
        'high-efficiency complementary piece: his value scales when Smith and Wigington draw coverage.'
    ))

    # ── Kevin Anigbogu ──
    e.append(player_card(
        'Kevin Anigbogu', pm['Kevin Anigbogu'],
        plyr_adv.get('Kevin Anigbogu', {}),
        'Anigbogu is a limited-minute interior player with elite finishing efficiency. '
        'His TS% of 65.9% ranks #14 among 467 qualified players statewide \u2014 top 3% \u2014 '
        'and his 2P% of 65.5% ranks #24. In 14.9 MPG he produces 4.8 RPG and 1.0 BLK/g '
        'with a 12.1% OREB rate (#71 statewide). His playing time is constrained by '
        'a team-high 2.8 PF/g; he has fouled out or been limited in multiple games this '
        'season. No perimeter attempts: 0 three-point tries in 30 games.'
    ))

    # ── Dabe Princewill ──
    e.append(player_card(
        'Dabe Princewill', pm['Dabe Princewill'],
        plyr_adv.get('Dabe Princewill', {}),
        'Princewill\u2019s most notable attribute is a 6.3% STL rate that ranks #9 among '
        '467 qualified players statewide \u2014 top 2%. He generates steals at an elite rate '
        'in just 12.0 MPG. When he does score, he is efficient: 66.7 2P% ranks #14 statewide, '
        'and his TS% of 58.0% (#96/467) is above average. His 9.0% OREB rate (#104/467) '
        'reflects active glass presence for a wing. His offensive profile is supplementary \u2014 '
        '2.7 FGA/g, 3.9 PPG \u2014 but his impact on ball-pressure defense is disproportionate to his minutes.'
    ))

    # ── Tong Tong ──
    e.append(player_card(
        'Tong Tong', pm['Tong Tong'],
        plyr_adv.get('Tong Tong', {}),
        'Tong is a high-efficiency reserve big whose offensive rebounding rate is elite at the '
        'state level. His 21.5% OREB rate ranks #5 among 467 qualified players statewide \u2014 '
        'top 1%. In 13.3 MPG he averages 2.2 OREB/g. His finishing efficiency matches the '
        'rebounding: TS% 63.7% (#31/467), 2P% 64.3% (#30/467), and Ind ORtg 118.3 (#43/467). '
        'The limitation is free-throw shooting (51.9 FT%, lowest among rotation players with '
        '1+ FTA/g) and zero perimeter attempts. He is one of the more statistically impactful '
        'reserve bigs in the conference given his role size.'
    ))

    e.append(PageBreak())
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — SITUATIONAL ANALYSIS + QUAD RECORDS
# ═══════════════════════════════════════════════════════════════════════════════
def page_situations():
    e = []
    e += section('Season Performance & Situational Analysis',
                 'How Ventura performs by game type, opponent quality, and quadrant.')

    wins_g  = [g for g in quality_games if g['result']=='W']
    loss_g  = [g for g in quality_games if g['result']=='L']
    close_w = sum(1 for g in close_g if g['result']=='W')

    # Splits grid
    for sp in [
        ('OVERALL', rec(quality_games), avg_net(quality_games), '25-5 overall record'),
        ('HOME',    rec(home_g),  avg_net(home_g),  'Includes Feb 4 home win vs. Moorpark (90-85)'),
        ('AWAY',    rec(away_g),  avg_net(away_g),  'Away record, all games'),
        ('NEUTRAL', rec(neut_g),  avg_net(neut_g),  'Neutral-site record'),
        ('CONFERENCE', rec(conf_g), avg_net(conf_g), '11-1 WSC North; loss to Allan Hancock at home, Feb 18'),
        ('NON-CONFERENCE', rec(nconf), avg_net(nconf), '14-4 non-conference record'),
        ('vs. QUALITY OPPS (net > 0)', rec(good_opp), avg_net(good_opp), f'{len(good_opp)} games vs. opponents with positive net rating'),
        ('FIRST HALF (G1-15)', rec(early_g), avg_net(early_g), 'Games 1-15'),
        ('SECOND HALF (G16-30)', rec(late_g), avg_net(late_g), 'Games 16-30; includes both Moorpark losses'),
        (f'CLOSE GAMES (\u22648 pts)', f'{close_w}-{len(close_g)-close_w}', avg_net(close_g),
         f'{len(close_g)} games decided by 8 or fewer points'),
    ]:
        e.append(splits_box(*sp))
        e.append(Spacer(1, 3))

    # Quad section
    e.append(Spacer(1, 10))
    e.append(Paragraph('<b>Quadrant Records (NCAA-style, scaled for 100 CCCAA teams)</b>',
                       S(9, True, BLUE, space_after=3)))
    e.append(Paragraph(
        'Q1A = elite (top ~4%). Q1 = top-tier (top ~9%). Q2 = strong (top ~21%). '
        'Q3 = adequate (top ~45%). Q4 = lower-tier. Location-adjusted thresholds.',
        S(8, False, MID, space_after=4)))

    _q1_all = quad_games['Q1A'] + quad_games['Q1']
    _q12    = _q1_all + quad_games['Q2']
    _q1_w   = quad_rec['Q1A'][0] + quad_rec['Q1'][0]
    _q1_l   = quad_rec['Q1A'][1] + quad_rec['Q1'][1]
    _q12_w  = _q1_w + quad_rec['Q2'][0]
    _q12_l  = _q1_l + quad_rec['Q2'][1]

    for ql, wr, lg, ex in [
        ('Q1A (Elite \u2014 Top 4%)',
         f"{quad_rec['Q1A'][0]}-{quad_rec['Q1A'][1]}",
         quad_games['Q1A'],
         f"{len(quad_games['Q1A'])} game(s) vs elite opponents"),
        ('Q1 (Top-Tier, incl. Q1A)',
         f'{_q1_w}-{_q1_l}', _q1_all,
         f'{len(_q1_all)} game(s) vs top-tier opponents'),
        ('Q2 (Strong \u2014 Top 21%)',
         f"{quad_rec['Q2'][0]}-{quad_rec['Q2'][1]}",
         quad_games['Q2'],
         f"{len(quad_games['Q2'])} game(s) vs strong opponents"),
        ('Q1+Q2 Combined',
         f'{_q12_w}-{_q12_l}', _q12,
         f'{len(_q12)} game(s) vs Q1 or Q2 opponents'),
        ('Q3 (Adequate \u2014 Top 45%)',
         f"{quad_rec['Q3'][0]}-{quad_rec['Q3'][1]}",
         quad_games['Q3'],
         f"{len(quad_games['Q3'])} game(s) vs adequate opponents"),
        ('Q4 (Lower-Tier)',
         f"{quad_rec['Q4'][0]}-{quad_rec['Q4'][1]}",
         quad_games['Q4'],
         f"{len(quad_games['Q4'])} game(s) vs lower-tier opponents"),
    ]:
        e.append(splits_box(ql, wr, avg_net(lg), ex))
        e.append(Spacer(1, 3))

    e.append(Spacer(1, 8))
    e.append(Paragraph(
        f'<b>Quad Summary:</b> Ventura went <b>{_q1_w}-{_q1_l} in Q1 games</b> and '
        f'<b>{_q12_w}-{_q12_l} in Q1+Q2 combined</b>. '
        f'Q1A games occurred in non-conference play. '
        f'Q2 record: {quad_rec["Q2"][0]}-{quad_rec["Q2"][1]}. '
        f'Q3 record: {quad_rec["Q3"][0]}-{quad_rec["Q3"][1]} — includes the '
        f'February 18 home loss to Allan Hancock (net rank #27). '
        f'Q4 record: {quad_rec["Q4"][0]}-{quad_rec["Q4"][1]}.',
        S(9, space_after=8)))

    # Notable losses
    e += section("Ventura's 5 Losses")
    e.append(Paragraph(
        "Ventura's five losses, sorted by Ventura net rating:",
        S(9, False, MID, space_after=4)))

    loss_rows = [['DATE', 'OPPONENT', 'SCORE', 'LOCATION', 'MOORPARK NET', 'CONTEXT']]
    for g in sorted(loss_g, key=lambda x: x['net']):
        opp_r = _net_ranks.get(g.get('canonical_opponent', g['opponent']), '?')
        loss_rows.append([
            g['date'],
            g['opponent'],
            f"{g['team_score']}-{g['opponent_score']}",
            g['location'],
            f"{g['net']:+.1f}",
            f"Opp #{opp_r}",
        ])
    lt = Table(loss_rows, colWidths=[0.9*inch,2.0*inch,0.8*inch,0.8*inch,1.0*inch,2.0*inch])
    lt.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),TH_BG), ('TEXTCOLOR',(0,0),(-1,0),WHITE),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'), ('FONTSIZE',(0,0),(-1,0),8),
        ('FONTSIZE',(0,1),(-1,-1),8), ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('ALIGN',(1,1),(1,-1),'LEFT'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,ALT]),
        ('INNERGRID',(0,0),(-1,-1),0.3,MGRAY), ('BOX',(0,0),(-1,-1),0.5,TH_BG),
        ('TOPPADDING',(0,0),(-1,-1),4), ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ('LEFTPADDING',(0,0),(-1,-1),4), ('RIGHTPADDING',(0,0),(-1,-1),4),
    ]))
    e.append(lt)
    e.append(PageBreak())
    return e


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — HEAD-TO-HEAD + SCOUTING GUIDE
# ═══════════════════════════════════════════════════════════════════════════════
def page_scouting_guide():
    e = []

    # Head-to-head breakdown
    e += section('Head-to-Head: Moorpark vs. Ventura 2025-26',
                 'Both meetings from Moorpark\'s perspective.')

    mp_ta = mp_adv['team']
    for g in h2h:
        net = g['ortg'] - g['drtg']
        loc_str = 'Away (at Ventura)' if g['location'] == 'Away' else 'Home (Moorpark)'
        e.append(Paragraph(
            f'<b>{g["date"]} — {g["result"]} {g["team_score"]}\u2013{g["opponent_score"]}  |  '
            f'{loc_str}</b>  |  '
            f'Moorpark ORTg: {g["ortg"]:.1f}  DRTg: {g["drtg"]:.1f}  Net: {net:+.1f}',
            S(9, space_after=3)))
    e.append(Spacer(1, 4))
    e.append(Paragraph(
        '<b>Analysis:</b> '
        'January 10 (Away, L 76\u201384): Moorpark ORTg 104.2, DRTg 115.2, net \u221211.0. '
        'February 4 (Home, L 85\u201390): Moorpark ORTg 112.6, DRTg 119.2, net \u22126.6. '
        'In both games, Ventura\'s DRTg against Moorpark (115.2 and 119.2) exceeded '
        f'Ventura\'s own season DRTg of {ta["drtg"]:.1f}, indicating Moorpark '
        'scored above Ventura\'s typical defensive output in both meetings. '
        'Combined margin: 13 points across two games.',
        S(9.5, space_after=10)))

    # Strengths vs. Vulnerabilities
    e += section('Scouting Guide — Strengths, Vulnerabilities & Keys to Victory')

    strengths = [
        (f'<b>Offensive efficiency: eFG% {ta["efg_pct"]:.1f}% (#{efg_r}/100), TS% {ta["ts_pct"]:.1f}% (#{ts_r}/100)</b>',
         f'State averages: eFG% {efg_avg:.1f}%, TS% {ts_avg:.1f}%. ORTg {ta["ortg"]:.1f} ranks #{ortg_r}/100.'),
        ('<b>Jerimiyah Smith: 20.1 PPG, 9.7 RPG, 63.6 FG%, 29.0 MPG</b>',
         '6.3 FTA/g, 68.3 FT%, 3.2 OREB/g, 30 GP. Highest FG% among rotation players on the roster.'),
        ('<b>Four rotation players averaging 3+ three-point attempts per game</b>',
         'Wigington 36.6% (4.9 3PA), Cigar 42.9% (4.1 3PA), Wilson 36.4% (4.0 3PA), Bellamy 31.0% (5.0 3PA).'),
        (f'<b>Pace: 78.1 possessions/game (#{pace_r}/100 statewide, state avg {pace_avg:.1f})</b>',
         f'Team PPG: {avgs["PTS"]:.1f}. Opponent PPG allowed: {opp_avgs["PTS"]:.1f}.'),
        (f'<b>Offensive rebounding: OREB% {ta["oreb_pct"]:.1f}% (#{oreb_r}/100, state avg {oreb_avg:.1f}%)</b>',
         'Smith 3.2 OREB/g, Tong Tong 2.2 OREB/g (13.3 MPG), Bellamy 1.6 OREB/g.'),
    ]
    vulnerabilities = [
        (f'<b>Wigington turnovers: 3.8 TO/g (team-high); team TOV% {ta["tov_pct"]:.1f}% (#{tov_r}/100)</b>',
         '3.8 TOV/g leads all rotation players. Second-highest is 1.9 TO/g. '
         'Wigington also leads the team in assists at 7.3 APG.'),
        (f'<b>Defensive shooting suppression: Opp eFG% {ta["opp_efg_pct"]:.1f}% (#{oefg_r}/100), '
         f'Opp TS% {ta["opp_ts_pct"]:.1f}% (#{ots_r}/100)</b>',
         f'Both metrics rank outside the top 45 statewide. State average Opp eFG%: {oefg_avg:.1f}%.'),
        (f'<b>Anigbogu foul rate: 2.8 PF/g in 14.9 MPG; FT% 66.1%</b>',
         'Highest per-game foul rate among rotation players. Zero 3-point attempts all season. '
         '12.0 FTA over 30 GP.'),
        (f'<b>Turnover generation: Opp TOV% {ta["opp_tov_pct"]:.1f}% (#{otov_r}/100, state avg {otov_avg:.1f}%)</b>',
         f'Ranks outside the top 50 CCCAA teams in generating opponent turnovers.'),
        ('<b>Tong Tong FT%: 51.9% on 2.3 FTA/g</b>',
         'Lowest FT% among rotation players with 1+ FTA/g. '
         'Eligible for intentional-foul targeting in late-game bonus situations.'),
        ('<b>Conference loss: Home vs. Allan Hancock (net rank #27), Feb 18</b>',
         'Ventura home WSC North record: 5-1. Single conference loss of the season.'),
    ]

    sv_rows = []
    for (sk, sv), (vk, vv) in zip(strengths, vulnerabilities):
        sv_rows.append([
            [Paragraph(sk, S(8.5, True, GREEN_TXT)),  Paragraph(sv, S(8))],
            [Paragraph(vk, S(8.5, True, RED_TXT)),    Paragraph(vv, S(8))],
        ])
    sv_t = Table(sv_rows, colWidths=[3.6*inch, 3.6*inch])
    sv_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(0,-1), colors.HexColor('#f0fff4')),
        ('BACKGROUND',(1,0),(1,-1), colors.HexColor('#fff5f5')),
        ('INNERGRID',(0,0),(-1,-1),0.5,MGRAY),
        ('BOX',(0,0),(-1,-1),0.5,BLUE),
        ('TOPPADDING',(0,0),(-1,-1),6), ('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LEFTPADDING',(0,0),(-1,-1),6), ('RIGHTPADDING',(0,0),(-1,-1),6),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
    ]))
    e.append(sv_t)
    e.append(Spacer(1, 14))

    # Keys to Victory
    e += section('Keys to Victory — What Moorpark Must Do')
    keys = [
        ('<b>1. Deny and contest Smith on every possession.</b>',
         'Deny post feeds; front in the post with help-side support available. '
         'Contest every catch. Smith scored 17 (Jan 10) and 22 (Feb 4) in head-to-head play; '
         'season average is 20.1 PPG. '
         'FG%: 63.6%. FT%: 68.3% on 6.3 FTA/g — avoid fouling in post position.'),
        ('<b>2. Pressure Wigington on ball screens; track his assist-to-turnover ratio.</b>',
         'Wigington leads the team in assists (7.3 APG) and turnovers (3.8 TOV/g). '
         'Apply ball-screen pressure. FT%: 81.6% — do not foul outside the lane. '
         'Season assist-to-turnover ratio: 1.92 (7.3 / 3.8).'),
        ('<b>3. Generate early foul accumulation on Anigbogu.</b>',
         'Anigbogu averages 2.8 PF per game in 14.9 MPG — highest per-minute foul rate '
         'among rotation players. Zero 3-point attempts all season. '
         'FT%: 66.1% on 12.0 FTA over 30 GP. Initiate contact in pick-and-roll and post situations.'),
        (f'<b>4. Maintain shot selection discipline; Ventura Opp eFG% ranks #{oefg_r}/100.</b>',
         f'Ventura Opp eFG%: {ta["opp_efg_pct"]:.1f}% (#{oefg_r}/100, state avg {oefg_avg:.1f}%). '
         f'Opp TS%: {ta["opp_ts_pct"]:.1f}% (#{ots_r}/100). '
         f'Moorpark ORTg in head-to-head games: 104.2 (Jan 10) and 112.6 (Feb 4). '
         f'Shot selection and execution quality are the primary determinants of Moorpark\'s offensive efficiency in this matchup.'),
        (f'<b>5. Protect possession; Ventura Opp TOV% ranks #{otov_r}/100.</b>',
         f'Ventura Opp TOV%: {ta["opp_tov_pct"]:.1f}% (#{otov_r}/100, state avg {otov_avg:.1f}%). '
         f'Ranks outside the top 50 CCCAA teams in turnover-forcing rate. '
         f'Pace: 78.1 possessions/game (#{pace_r}/100) — each possession surrendered carries '
         f'proportionally higher marginal cost in a high-pace game.'),
        (f'<b>6. Execute full box-out contact on every Ventura shot attempt.</b>',
         f'Ventura OREB%: {ta["oreb_pct"]:.1f}% (#{oreb_r}/100, state avg {oreb_avg:.1f}%). '
         f'Smith: 3.2 OREB/g. Tong Tong: 2.2 OREB/g in 13.3 MPG. Bellamy: 1.6 OREB/g. '
         f'Moorpark DREB%: {mp_ta.get("dreb_pct", 0):.1f}%. '
         f'Holding Ventura below their {ta["oreb_pct"]:.1f}% OREB season average requires '
         f'full box-out contact on every possession.'),
    ]
    for header, body in keys:
        tbl = Table([[Paragraph(header, S(9, True, BLUE)),
                      Paragraph(body, S(8.5))]],
                    colWidths=[2.2*inch, 5.3*inch])
        tbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(0,0), ALT),
            ('BACKGROUND',(1,0),(1,0), WHITE),
            ('BOX',(0,0),(-1,-1),0.5,BLUE),
            ('INNERGRID',(0,0),(-1,-1),0.3,MGRAY),
            ('TOPPADDING',(0,0),(-1,-1),6), ('BOTTOMPADDING',(0,0),(-1,-1),6),
            ('LEFTPADDING',(0,0),(-1,-1),6), ('RIGHTPADDING',(0,0),(-1,-1),6),
            ('VALIGN',(0,0),(-1,-1),'TOP'),
        ]))
        e.append(tbl)
        e.append(Spacer(1, 4))

    e.append(Spacer(1, 10))
    e.append(Paragraph(
        '<b>Summary:</b> Ventura beat Moorpark twice in 2025-26: '
        'January 10 (Away, L 76\u201384, net \u221211.0) and February 4 (Home, L 85\u201390, net \u22126.6). '
        'Combined margin: 13 points. '
        'In both games, Ventura\'s DRTg against Moorpark (115.2, 119.2) exceeded '
        f'Ventura\'s own season DRTg of {ta["drtg"]:.1f}. '
        'Moorpark ORTg in those two games: 104.2 and 112.6. '
        'Primary defensive targets: Smith (20.1 PPG, 63.6 FG%) and Anigbogu '
        'foul accumulation (2.8 PF per game in 14.9 MPG). '
        f'Primary offensive benchmark: sustaining ORTg above Ventura\'s season DRTg of {ta["drtg"]:.1f}.',
        S(10, space_after=0)))

    return e


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD PDF
# ═══════════════════════════════════════════════════════════════════════════════
OUT = f'{BASE}/ventura_scouting_report_2025_26.pdf'

doc = SimpleDocTemplate(
    OUT, pagesize=letter,
    leftMargin=0.5*inch, rightMargin=0.5*inch,
    topMargin=0.72*inch, bottomMargin=0.55*inch,
)

story = (
    page_cover()
  + page_analytics()
  + page_players()
  + page_situations()
  + page_scouting_guide()
)

doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f'Saved: {OUT} ({round(os.path.getsize(OUT)/1024)} KB)')
