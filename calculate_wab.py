#!/usr/bin/env python3
"""
Calculate Wins Above Bubble (WAB) for CCCAA basketball teams.

Adapted from Her Hoop Stats methodology for community college basketball.
Uses team NET ratings to determine expected performance vs. "bubble" teams.
"""

import json
import os
import math
from pathlib import Path
from typing import Dict, List, Tuple


def load_team_data(year: str) -> Dict[str, Dict]:
    """Load all team game logs for a given year."""
    teams = {}
    stats_dir = Path(f"{year} Team Statistics")
    
    if not stats_dir.exists():
        print(f"Directory not found: {stats_dir}")
        return teams
    
    for conf_dir in stats_dir.iterdir():
        if not conf_dir.is_dir():
            continue
        for team_dir in conf_dir.iterdir():
            if not team_dir.is_dir():
                continue
            game_log_path = team_dir / "game_log.json"
            if game_log_path.exists():
                try:
                    with open(game_log_path) as f:
                        data = json.load(f)
                        teams[team_dir.name] = {
                            'games': data.get('games', []),
                            'conference': conf_dir.name
                        }
                except Exception as e:
                    print(f"Error loading {team_dir.name}: {e}")
    
    print(f"Loaded {len(teams)} teams for {year}")
    return teams


def calculate_possessions(team_stats: Dict, opp_stats: Dict) -> float:
    """Calculate estimated possessions using standard basketball formula."""
    team_fga = team_stats.get('FGA', 0)
    team_to = team_stats.get('TO', 0)
    team_fta = team_stats.get('FTA', 0)
    team_oreb = team_stats.get('OREB', 0)
    
    opp_fga = opp_stats.get('FGA', 0) 
    opp_to = opp_stats.get('TO', 0)
    opp_fta = opp_stats.get('FTA', 0)
    opp_oreb = opp_stats.get('OREB', 0)
    
    team_poss = team_fga + 0.44 * team_fta + team_to - team_oreb
    opp_poss = opp_fga + 0.44 * opp_fta + opp_to - opp_oreb
    
    return (team_poss + opp_poss) / 2.0


def calculate_team_ratings(teams: Dict[str, Dict]) -> Dict[str, Dict]:
    """Calculate offensive/defensive ratings for each team."""
    ratings = {}
    
    for team_name, team_data in teams.items():
        games = team_data['games']
        if not games:
            continue
            
        total_ortg = 0
        total_drtg = 0
        game_count = 0
        
        for game in games:
            team_stats = game.get('team_stats', {})
            opp_stats = game.get('opponent_stats', {})
            
            if not team_stats or not opp_stats:
                continue
                
            team_pts = team_stats.get('PTS', 0)
            opp_pts = opp_stats.get('PTS', 0)
            
            possessions = calculate_possessions(team_stats, opp_stats)
            
            if possessions > 0:
                ortg = (team_pts / possessions) * 100  # Points per 100 possessions
                drtg = (opp_pts / possessions) * 100   # Opponent points per 100 possessions
                
                total_ortg += ortg
                total_drtg += drtg
                game_count += 1
        
        if game_count > 0:
            avg_ortg = total_ortg / game_count
            avg_drtg = total_drtg / game_count
            net_rating = avg_ortg - avg_drtg
            
            ratings[team_name] = {
                'ortg': avg_ortg,
                'drtg': avg_drtg, 
                'net': net_rating,
                'games': game_count,
                'conference': team_data['conference']
            }
    
    return ratings


def pythagorean_expectation(ortg: float, drtg: float, exponent: float = 11.5) -> float:
    """Calculate expected winning percentage using Pythagorean expectation."""
    if ortg <= 0 or drtg <= 0:
        return 0.5
    
    ortg_exp = ortg ** exponent
    drtg_exp = drtg ** exponent
    
    return ortg_exp / (ortg_exp + drtg_exp)


def log5(prob_a: float, prob_b: float) -> float:
    """Calculate probability that team A beats team B using log5 formula."""
    if prob_a == 0.5 and prob_b == 0.5:
        return 0.5
    
    numerator = prob_a - (prob_a * prob_b)
    denominator = prob_a + prob_b - (2 * prob_a * prob_b)
    
    if denominator == 0:
        return 0.5
    
    return numerator / denominator


def determine_bubble_rating(ratings: Dict[str, Dict]) -> Dict[str, float]:
    """Determine the ORTG/DRTG of the bubble team (60th percentile by NET)."""
    qualified = [(t['net'], t['ortg'], t['drtg']) for t in ratings.values() if t['games'] >= 10]
    
    if not qualified:
        return {'net': 0.0, 'ortg': 100.0, 'drtg': 100.0}
    
    qualified.sort(key=lambda x: x[0], reverse=True)
    
    # Use 60th percentile as "bubble" (teams that might make conference tournaments)
    bubble_index = int(len(qualified) * 0.60)
    bubble_net, bubble_ortg, bubble_drtg = qualified[bubble_index]
    
    print(f"Bubble NET rating (60th percentile): {bubble_net:.2f}")
    print(f"Bubble ORTG: {bubble_ortg:.1f}, DRTG: {bubble_drtg:.1f}")
    print(f"Based on {len(qualified)} teams with 10+ games")
    
    return {'net': bubble_net, 'ortg': bubble_ortg, 'drtg': bubble_drtg}


def calculate_wab_for_team(team_name: str, team_data: Dict, team_ratings: Dict[str, Dict], bubble: Dict[str, float]) -> float:
    """Calculate WAB for a single team."""
    if team_name not in team_ratings:
        return 0.0
    
    games = team_data['games']
    
    bubble_ortg = bubble['ortg']
    bubble_drtg = bubble['drtg']
    
    total_wab = 0.0
    hca_adjustment = 2.2  # Points per 100 possessions
    
    for game in games:
        opponent = game.get('opponent', '')
        location = game.get('location', 'Neutral')
        result = game.get('result', 'L')
        
        if opponent not in team_ratings:
            continue  # Skip games vs teams we don't have ratings for
        
        opp_rating = team_ratings[opponent]
        
        # Adjust opponent ratings for home court advantage
        opp_ortg = opp_rating['ortg']
        opp_drtg = opp_rating['drtg'] 
        
        if location == 'Home':
            # Opponent is visiting, so they're worse
            opp_ortg -= hca_adjustment
            opp_drtg += hca_adjustment
        elif location == 'Away':
            # Opponent has HCA
            opp_ortg += hca_adjustment
            opp_drtg -= hca_adjustment
        
        # Calculate bubble team's win probability vs this opponent at this location
        if location == 'Home':
            bubble_ortg_adj = bubble_ortg + hca_adjustment
            bubble_drtg_adj = bubble_drtg - hca_adjustment
        elif location == 'Away':
            bubble_ortg_adj = bubble_ortg - hca_adjustment
            bubble_drtg_adj = bubble_drtg + hca_adjustment
        else:
            bubble_ortg_adj = bubble_ortg
            bubble_drtg_adj = bubble_drtg
        
        bubble_win_prob_game = pythagorean_expectation(bubble_ortg_adj, bubble_drtg_adj)
        opp_win_prob_game = pythagorean_expectation(opp_ortg, opp_drtg)
        
        # Use log5 to get probability bubble team beats this opponent
        bubble_beats_opp = log5(bubble_win_prob_game, opp_win_prob_game)
        
        # Calculate WAB for this game
        if result == 'W':
            game_wab = 1 - bubble_beats_opp  # Actual win - expected bubble win probability
        else:
            game_wab = 0 - bubble_beats_opp  # Actual loss - expected bubble win probability
        
        total_wab += game_wab
    
    return total_wab


def main():
    """Main function to calculate WAB for all teams."""
    import argparse
    parser = argparse.ArgumentParser(description="Calculate WAB for CCCAA basketball teams")
    parser.add_argument("--season", default="2025-26", help="Season year prefix, e.g. 2024-25 or 2025-26")
    args = parser.parse_args()

    season = args.season
    print(f"Loading team data for {season}...")

    # Load season data
    current_teams = load_team_data(season)
    
    if not current_teams:
        print("No current season data found!")
        return
    
    print("\nCalculating team ratings...")
    current_ratings = calculate_team_ratings(current_teams)
    
    print(f"Calculated ratings for {len(current_ratings)} teams")
    
    # Determine bubble team benchmark
    bubble = determine_bubble_rating(current_ratings)
    
    print("\nCalculating WAB for each team...")
    wab_results = []
    
    for team_name, team_data in current_teams.items():
        if team_name in current_ratings and current_ratings[team_name]['games'] >= 5:
            wab = calculate_wab_for_team(team_name, team_data, current_ratings, bubble)
            
            team_rating = current_ratings[team_name]
            wab_results.append({
                'team': team_name,
                'conference': team_rating['conference'],
                'wab': wab,
                'net': team_rating['net'],
                'games': team_rating['games'],
                'ortg': team_rating['ortg'],
                'drtg': team_rating['drtg']
            })
    
    # Sort by WAB (highest first)
    wab_results.sort(key=lambda x: x['wab'], reverse=True)
    
    print(f"\n{'Rank':<4} {'Team':<25} {'Conference':<20} {'WAB':<6} {'NET':<6} {'Games':<6}")
    print("-" * 80)
    
    for i, result in enumerate(wab_results[:25]):  # Top 25
        print(f"{i+1:<4} {result['team']:<25} {result['conference']:<20} {result['wab']:<6.2f} {result['net']:<6.1f} {result['games']:<6}")
    
    # Save results — use season-specific filename for non-current seasons
    if season == "2025-26":
        output_file = "wab_results.json"
    else:
        safe = season.replace("-", "_")
        output_file = f"wab_results_{safe}.json"
    with open(output_file, 'w') as f:
        json.dump(wab_results, f, indent=2)

    print(f"\nFull results saved to {output_file}")
    
    # Show some interesting stats
    print(f"\nWAB Statistics:")
    wab_values = [r['wab'] for r in wab_results]
    print(f"Highest WAB: {max(wab_values):.2f}")
    print(f"Lowest WAB: {min(wab_values):.2f}")
    print(f"Average WAB: {sum(wab_values) / len(wab_values):.2f}")


if __name__ == "__main__":
    main()