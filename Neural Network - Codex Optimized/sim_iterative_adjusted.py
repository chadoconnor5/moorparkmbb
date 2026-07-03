#!/usr/bin/env python3
"""
Simulate iterative opponent-adjusted efficiency WITHOUT normalization (read-only).

Demonstrates the inflation problem: without normalizing league averages after
each pass, ratings spiral upward and don't converge. All teams gain 25-45 pts
of NET RTG. Relative ordering is still informative but absolute values are not.

This is the "broken" version — see sim_iterative_normalized.py for the fix.
"""
import json
from pathlib import Path
from collections import defaultdict

STATS_DIR = Path("2025-26 Team Statistics")
HOME_ADVANTAGE = 3.0


def load_all_teams():
    """Load all team game ratings."""
    team_game_ratings = {}

    for conf_dir in sorted(STATS_DIR.iterdir()):
        if not conf_dir.is_dir():
            continue
        for team_dir in sorted(conf_dir.iterdir()):
            if not team_dir.is_dir():
                continue
            adv_path = team_dir / "advanced_analytics.json"
            if not adv_path.exists():
                continue
            with open(adv_path) as f:
                adv = json.load(f)
            ta = adv.get("team", {})
            gr = ta.get("game_ratings", [])
            if ta.get("ortg", 0) > 0:
                team_game_ratings[team_dir.name] = gr

    return team_game_ratings


def compute_pass(team_game_ratings, opponent_ratings, league_avg_ortg, league_avg_drtg):
    """One iteration pass."""
    new_ratings = {}
    for team_name, gr in team_game_ratings.items():
        in_sys = [g for g in gr if g.get("in_system") and g.get("canonical_opponent")]
        if not in_sys:
            new_ratings[team_name] = {"ortg": league_avg_ortg, "drtg": league_avg_drtg}
            continue

        adj_ortgs = []
        adj_drtgs = []
        for g in in_sys:
            opp = g["canonical_opponent"]
            if opp not in opponent_ratings:
                adj_ortgs.append(g["ortg"])
                adj_drtgs.append(g["drtg"])
                continue

            opp_drtg = opponent_ratings[opp]["drtg"]
            opp_ortg = opponent_ratings[opp]["ortg"]

            hca_o, hca_d = 0.0, 0.0
            loc = g.get("location", "")
            if loc == "Home":
                hca_o = -HOME_ADVANTAGE / 2
                hca_d = +HOME_ADVANTAGE / 2
            elif loc == "Away":
                hca_o = +HOME_ADVANTAGE / 2
                hca_d = -HOME_ADVANTAGE / 2

            adj_ortgs.append(g["ortg"] + hca_o - opp_drtg + league_avg_drtg)
            adj_drtgs.append(g["drtg"] + hca_d - opp_ortg + league_avg_ortg)

        if adj_ortgs:
            new_ratings[team_name] = {
                "ortg": sum(adj_ortgs) / len(adj_ortgs),
                "drtg": sum(adj_drtgs) / len(adj_drtgs),
            }
        else:
            new_ratings[team_name] = {"ortg": league_avg_ortg, "drtg": league_avg_drtg}

    return new_ratings


def main():
    team_game_ratings = load_all_teams()
    teams = list(team_game_ratings.keys())
    print(f"Teams loaded: {len(teams)}")

    # Initial raw ratings
    raw_ratings = {}
    for team_name, gr in team_game_ratings.items():
        in_sys = [g for g in gr if g.get("in_system")]
        if in_sys:
            raw_ratings[team_name] = {
                "ortg": sum(g["ortg"] for g in in_sys) / len(in_sys),
                "drtg": sum(g["drtg"] for g in in_sys) / len(in_sys),
            }
        else:
            raw_ratings[team_name] = {"ortg": 100.0, "drtg": 100.0}

    league_avg_ortg = sum(r["ortg"] for r in raw_ratings.values()) / len(raw_ratings)
    league_avg_drtg = sum(r["drtg"] for r in raw_ratings.values()) / len(raw_ratings)
    print(f"League avg ORTG: {league_avg_ortg:.1f}")
    print(f"League avg DRTG: {league_avg_drtg:.1f}")

    # Iterate (will NOT converge properly)
    current_ratings = raw_ratings.copy()
    MAX_ITER = 50
    print(f"\n--- CONVERGENCE (expect failure) ---")

    for iteration in range(1, MAX_ITER + 1):
        new_ratings = compute_pass(team_game_ratings, current_ratings,
                                   league_avg_ortg, league_avg_drtg)
        max_change = 0
        for team in teams:
            if team in new_ratings and team in current_ratings:
                change = max(abs(new_ratings[team]["ortg"] - current_ratings[team]["ortg"]),
                             abs(new_ratings[team]["drtg"] - current_ratings[team]["drtg"]))
                max_change = max(max_change, change)

        if iteration <= 10 or iteration % 10 == 0:
            avg_ortg = sum(r["ortg"] for r in new_ratings.values()) / len(new_ratings)
            print(f"  Iter {iteration:>2}: max_change={max_change:.4f}, "
                  f"league_avg_ortg={avg_ortg:.1f} (drifting!)")

        current_ratings = new_ratings
        if max_change < 0.01:
            print(f"  Converged after {iteration} iterations")
            break

    # Show the inflation problem
    avg_ortg = sum(r["ortg"] for r in current_ratings.values()) / len(current_ratings)
    avg_drtg = sum(r["drtg"] for r in current_ratings.values()) / len(current_ratings)
    print(f"\n  Final league avg ORTG: {avg_ortg:.1f} (started at {league_avg_ortg:.1f})")
    print(f"  Final league avg DRTG: {avg_drtg:.1f} (started at {league_avg_drtg:.1f})")
    print(f"  PROBLEM: Ratings inflated without normalization!")
    print(f"  See sim_iterative_normalized.py for the proper version.")


if __name__ == "__main__":
    main()
