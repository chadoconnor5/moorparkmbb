#!/usr/bin/env python3
"""
Simulate single-pass opponent-adjusted efficiency ratings (read-only).

For each game:
  Adj ORTG = game_ortg - opp_season_drtg + league_avg_drtg
  Adj DRTG = game_drtg - opp_season_ortg + league_avg_ortg

This is a simplified version that uses raw opponent ratings as baselines.
It produces real movement but understates effects for teams deep in
weak/strong conferences (because their opponents' raw ratings are biased too).
"""
import json
from pathlib import Path
from collections import defaultdict

STATS_DIR = Path("2025-26 Team Statistics")


def load_all_teams():
    """Load all team ratings and game logs."""
    team_ratings = {}
    team_game_ratings = {}
    team_conferences = {}

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
            team_ratings[team_dir.name] = {
                "ortg": ta.get("ortg", 0),
                "drtg": ta.get("drtg", 0),
                "net_rtg": ta.get("net_rtg", 0),
            }
            team_game_ratings[team_dir.name] = ta.get("game_ratings", [])
            team_conferences[team_dir.name] = conf_dir.name

    return team_ratings, team_game_ratings, team_conferences


def main():
    team_ratings, team_game_ratings, team_conferences = load_all_teams()

    # League averages
    valid = [r for r in team_ratings.values() if r["ortg"] > 0]
    league_avg_ortg = sum(r["ortg"] for r in valid) / len(valid)
    league_avg_drtg = sum(r["drtg"] for r in valid) / len(valid)
    print(f"League average ORTG: {league_avg_ortg:.1f}")
    print(f"League average DRTG: {league_avg_drtg:.1f}")
    print(f"Teams with ratings: {len(valid)}")

    # Compute opponent-adjusted ratings
    results = []
    for team_name, gr in team_game_ratings.items():
        in_sys = [g for g in gr if g.get("in_system") and g.get("canonical_opponent")]
        if not in_sys:
            continue

        curr_ortg = sum(g["ortg"] for g in in_sys) / len(in_sys)
        curr_drtg = sum(g["drtg"] for g in in_sys) / len(in_sys)
        curr_net = curr_ortg - curr_drtg

        adj_ortgs = []
        adj_drtgs = []

        for g in in_sys:
            opp = g["canonical_opponent"]
            if opp not in team_ratings or team_ratings[opp]["ortg"] == 0:
                adj_ortgs.append(g["ortg"])
                adj_drtgs.append(g["drtg"])
                continue

            opp_drtg = team_ratings[opp]["drtg"]
            opp_ortg = team_ratings[opp]["ortg"]

            adj_o = g["ortg"] - opp_drtg + league_avg_drtg
            adj_d = g["drtg"] - opp_ortg + league_avg_ortg

            adj_ortgs.append(adj_o)
            adj_drtgs.append(adj_d)

        if not adj_ortgs:
            continue

        adj_ortg = sum(adj_ortgs) / len(adj_ortgs)
        adj_drtg = sum(adj_drtgs) / len(adj_drtgs)
        adj_net = adj_ortg - adj_drtg

        results.append({
            "team": team_name,
            "conf": team_conferences.get(team_name, ""),
            "games": len(in_sys),
            "curr_ortg": round(curr_ortg, 1),
            "curr_drtg": round(curr_drtg, 1),
            "curr_net": round(curr_net, 1),
            "adj_ortg": round(adj_ortg, 1),
            "adj_drtg": round(adj_drtg, 1),
            "adj_net": round(adj_net, 1),
            "net_delta": round(adj_net - curr_net, 1),
        })

    # Rank
    results.sort(key=lambda x: x["curr_net"], reverse=True)
    for i, r in enumerate(results):
        r["curr_rank"] = i + 1
    results.sort(key=lambda x: x["adj_net"], reverse=True)
    for i, r in enumerate(results):
        r["adj_rank"] = i + 1
        r["rank_delta"] = r["curr_rank"] - r["adj_rank"]

    # Top 30
    print(f"\n{'Rk':>3} {'Team':<22} {'AdjNET':>7} {'CurNET':>7} {'delta':>6} "
          f"{'RkChg':>6} {'AdjO':>6} {'AdjD':>6}")
    print("-" * 70)
    for i, r in enumerate(results[:30]):
        print(f"{i+1:>3} {r['team']:<22} {r['adj_net']:>+7.1f} {r['curr_net']:>+7.1f} "
              f"{r['net_delta']:>+6.1f} {r['rank_delta']:>+6d} "
              f"{r['adj_ortg']:>6.1f} {r['adj_drtg']:>6.1f}")

    # Biggest movers
    print(f"\n--- BIGGEST RISERS ---")
    risers = sorted(results, key=lambda x: x["rank_delta"], reverse=True)[:15]
    for r in risers:
        print(f"  {r['team']:<22} #{r['curr_rank']:>2} -> #{r['adj_rank']:>2} "
              f"({r['rank_delta']:>+3d})  NET: {r['curr_net']:>+6.1f} -> {r['adj_net']:>+6.1f}")

    print(f"\n--- BIGGEST FALLERS ---")
    fallers = sorted(results, key=lambda x: x["rank_delta"])[:15]
    for r in fallers:
        print(f"  {r['team']:<22} #{r['curr_rank']:>2} -> #{r['adj_rank']:>2} "
              f"({r['rank_delta']:>+3d})  NET: {r['curr_net']:>+6.1f} -> {r['adj_net']:>+6.1f}")

    # Distribution
    deltas = [r["net_delta"] for r in results]
    rank_deltas = [abs(r["rank_delta"]) for r in results]
    print(f"\n--- DISTRIBUTION ---")
    print(f"  NET change range: {min(deltas):>+.1f} to {max(deltas):>+.1f}")
    print(f"  Mean |NET change|: {sum(abs(d) for d in deltas)/len(deltas):.2f}")
    print(f"  Mean |rank change|: {sum(rank_deltas)/len(rank_deltas):.1f}")
    print(f"  Max rank change: {max(rank_deltas)}")


if __name__ == "__main__":
    main()
