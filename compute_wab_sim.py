#!/usr/bin/env python3
"""Compute simulated WAB: North/South split with bubble at rank 24 each."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from calculate_wab import (load_team_data, calculate_team_ratings, calculate_wab_for_team)

CONF_REGION = {
    'WSC North': 'South', 'WSC South': 'South', 'Orange Empire Athletic': 'South',
    'Pacific Coast Athletic': 'South', 'South Coast-South': 'South', 'South Coast-North': 'South',
    'Inland Empire Athletic': 'South', 'Coast-North': 'North', 'Big Eight': 'North',
    'Coast-South': 'North', 'Bay Valley': 'North', 'Central Valley': 'North', 'Golden Valley': 'North',
}

def sim_wab(ratings, teams, bubble_rank=24, region_filter=None):
    pool = {k: v for k, v in ratings.items()
            if region_filter is None or CONF_REGION.get(v['conference']) == region_filter}
    qualified = sorted([(v['net'], v['ortg'], v['drtg']) for v in pool.values() if v['games'] >= 10],
                        key=lambda x: -x[0])
    if not qualified:
        return []
    idx = min(bubble_rank - 1, len(qualified) - 1)
    bnet, bortg, bdrtg = qualified[idx]
    bubble = {'net': bnet, 'ortg': bortg, 'drtg': bdrtg}
    print(f"  Region={region_filter or 'All'}, bubble @{idx+1}: NET={bnet:.2f}, ORTG={bortg:.1f}, DRTG={bdrtg:.1f}")

    results = []
    for name, td in teams.items():
        r = ratings.get(name)
        if not r or r['games'] < 5:
            continue
        if region_filter and CONF_REGION.get(r['conference']) != region_filter:
            continue
        wab = calculate_wab_for_team(name, td, ratings, bubble)
        results.append({
            'team': name, 'conference': r['conference'],
            'region': CONF_REGION.get(r['conference'], ''),
            'wab': round(wab, 4), 'net': round(r['net'], 2),
            'games': r['games']
        })
    results.sort(key=lambda x: -x['wab'])
    return results

def run_for_season(season_dir, out_path):
    print(f"Loading {season_dir} team data...")
    teams = load_team_data(season_dir)
    ratings = calculate_team_ratings(teams)
    print(f"\nComputing simulation: split North/South, bubble @24")
    north = sim_wab(ratings, teams, bubble_rank=24, region_filter='North')
    south = sim_wab(ratings, teams, bubble_rank=24, region_filter='South')
    with open(out_path, 'w') as f:
        json.dump({'north': north, 'south': south}, f)
    print(f"Saved {out_path}")
    return north, south

if __name__ == '__main__':
    run_for_season('2025-26', 'wab_sim_split24.json')
    run_for_season('2024-25', 'wab_sim_split24_2024_25.json')
