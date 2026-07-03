#!/usr/bin/env python3
"""
Iterative opponent-adjusted efficiency with normalization + regression to mean.

KenPom-style approach:
1. Adjust each game's ORTG against opponent's adjusted DRTG (and vice versa)
2. Regress toward league average based on sample size (fewer games = more regression)
3. Dampen iteration updates to prevent oscillation
4. Normalize league averages after each pass to prevent inflation

Converges in ~14 iterations. Produces realistic ratings on the original scale.
"""
import json
from pathlib import Path
from collections import defaultdict

STATS_DIR = Path("2025-26 Team Statistics")
HOME_ADVANTAGE = 3.0   # pts per 100 possessions
REGRESSION_GAMES = 10  # prior games at league average to mix in
DAMPEN = 0.5           # blend factor with previous iteration
MAX_ITER = 100


def load_all_teams():
    """Load all team game ratings."""
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
            gr = ta.get("game_ratings", [])
            if ta.get("ortg", 0) > 0:
                team_game_ratings[team_dir.name] = gr
                team_conferences[team_dir.name] = conf_dir.name

    return team_game_ratings, team_conferences


def main():
    team_game_ratings, team_conferences = load_all_teams()
    teams = list(team_game_ratings.keys())
    print(f"Teams loaded: {len(teams)}")

    # Games per team
    games_count = {}
    for team_name, gr in team_game_ratings.items():
        games_count[team_name] = len([g for g in gr if g.get("in_system")
                                      and g.get("canonical_opponent")])
    avg_games = sum(games_count.values()) / len(games_count)
    print(f"Avg in-system games per team: {avg_games:.1f}")

    # Raw ratings (initial seed)
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

    # Target league averages (preserved through iterations)
    target_ortg = sum(r["ortg"] for r in raw_ratings.values()) / len(raw_ratings)
    target_drtg = sum(r["drtg"] for r in raw_ratings.values()) / len(raw_ratings)
    print(f"Target league avg ORTG: {target_ortg:.1f}")
    print(f"Target league avg DRTG: {target_drtg:.1f}")
    print(f"Home court advantage: {HOME_ADVANTAGE:.1f}")
    print(f"Regression prior games: {REGRESSION_GAMES}")
    print(f"Dampening factor: {DAMPEN}")

    # Iterate
    current_ratings = {t: dict(r) for t, r in raw_ratings.items()}
    print(f"\n--- CONVERGENCE ---")

    for iteration in range(1, MAX_ITER + 1):
        new_ratings = {}

        for team_name, gr in team_game_ratings.items():
            in_sys = [g for g in gr if g.get("in_system") and g.get("canonical_opponent")]
            if not in_sys:
                new_ratings[team_name] = {"ortg": target_ortg, "drtg": target_drtg}
                continue

            adj_ortgs = []
            adj_drtgs = []

            for g in in_sys:
                opp = g["canonical_opponent"]
                if opp not in current_ratings:
                    adj_ortgs.append(g["ortg"])
                    adj_drtgs.append(g["drtg"])
                    continue

                opp_drtg = current_ratings[opp]["drtg"]
                opp_ortg = current_ratings[opp]["ortg"]

                # Home court adjustment
                hca_o, hca_d = 0.0, 0.0
                loc = g.get("location", "")
                if loc == "Home":
                    hca_o = -HOME_ADVANTAGE / 2
                    hca_d = +HOME_ADVANTAGE / 2
                elif loc == "Away":
                    hca_o = +HOME_ADVANTAGE / 2
                    hca_d = -HOME_ADVANTAGE / 2

                adj_ortgs.append(g["ortg"] + hca_o - opp_drtg + target_drtg)
                adj_drtgs.append(g["drtg"] + hca_d - opp_ortg + target_ortg)

            if adj_ortgs:
                game_ortg = sum(adj_ortgs) / len(adj_ortgs)
                game_drtg = sum(adj_drtgs) / len(adj_drtgs)

                # Regression to mean
                n = len(adj_ortgs)
                weight = n / (n + REGRESSION_GAMES)
                reg_ortg = weight * game_ortg + (1 - weight) * target_ortg
                reg_drtg = weight * game_drtg + (1 - weight) * target_drtg

                # Dampening
                new_ortg = DAMPEN * reg_ortg + (1 - DAMPEN) * current_ratings[team_name]["ortg"]
                new_drtg = DAMPEN * reg_drtg + (1 - DAMPEN) * current_ratings[team_name]["drtg"]

                new_ratings[team_name] = {"ortg": new_ortg, "drtg": new_drtg}
            else:
                new_ratings[team_name] = {"ortg": target_ortg, "drtg": target_drtg}

        # Normalize league averages
        curr_avg_ortg = sum(r["ortg"] for r in new_ratings.values()) / len(new_ratings)
        curr_avg_drtg = sum(r["drtg"] for r in new_ratings.values()) / len(new_ratings)
        ortg_shift = target_ortg - curr_avg_ortg
        drtg_shift = target_drtg - curr_avg_drtg
        for t in new_ratings:
            new_ratings[t]["ortg"] += ortg_shift
            new_ratings[t]["drtg"] += drtg_shift

        # Measure convergence
        max_change = 0
        for team in teams:
            if team in new_ratings and team in current_ratings:
                change = max(abs(new_ratings[team]["ortg"] - current_ratings[team]["ortg"]),
                             abs(new_ratings[team]["drtg"] - current_ratings[team]["drtg"]))
                max_change = max(max_change, change)

        if iteration <= 10 or iteration % 10 == 0 or max_change < 0.01:
            print(f"  Iter {iteration:>2}: max_change={max_change:.4f}")

        current_ratings = new_ratings
        if max_change < 0.01:
            print(f"  Converged after {iteration} iterations!")
            break

    # Build results
    results = []
    for team_name in teams:
        raw = raw_ratings[team_name]
        adj = current_ratings[team_name]
        raw_net = raw["ortg"] - raw["drtg"]
        adj_net = adj["ortg"] - adj["drtg"]
        results.append({
            "team": team_name,
            "conf": team_conferences.get(team_name, ""),
            "games": games_count[team_name],
            "raw_ortg": round(raw["ortg"], 1),
            "raw_drtg": round(raw["drtg"], 1),
            "raw_net": round(raw_net, 1),
            "adj_ortg": round(adj["ortg"], 1),
            "adj_drtg": round(adj["drtg"], 1),
            "adj_net": round(adj_net, 1),
            "net_delta": round(adj_net - raw_net, 1),
        })

    # Rank
    results.sort(key=lambda x: x["raw_net"], reverse=True)
    for i, r in enumerate(results):
        r["raw_rank"] = i + 1
    results.sort(key=lambda x: x["adj_net"], reverse=True)
    for i, r in enumerate(results):
        r["adj_rank"] = i + 1
        r["rank_delta"] = r["raw_rank"] - r["adj_rank"]

    # Full rankings
    print(f"\n{'Rk':>3} {'was':>4} {'Team':<22} {'AdjNET':>7} {'RawNET':>7} {'Chg':>5} "
          f"{'AdjO':>6} {'AdjD':>6} {'Gms':>4}")
    print("-" * 75)
    for r in results:
        was = r['raw_rank'] if r['rank_delta'] != 0 else ""
        print(f"{r['adj_rank']:>3} {str(was):>4} {r['team']:<22} "
              f"{r['adj_net']:>+7.1f} {r['raw_net']:>+7.1f} "
              f"{r['rank_delta']:>+5d} {r['adj_ortg']:>6.1f} {r['adj_drtg']:>6.1f} "
              f"{r['games']:>4}")

    # Biggest movers
    print(f"\n--- BIGGEST RISERS ---")
    risers = sorted(results, key=lambda x: x["rank_delta"], reverse=True)[:12]
    for r in risers:
        print(f"  {r['team']:<22} #{r['raw_rank']:>2} -> #{r['adj_rank']:>2} ({r['rank_delta']:>+3d})  "
              f"NET: {r['raw_net']:>+6.1f} -> {r['adj_net']:>+6.1f}")

    print(f"\n--- BIGGEST FALLERS ---")
    fallers = sorted(results, key=lambda x: x["rank_delta"])[:12]
    for r in fallers:
        print(f"  {r['team']:<22} #{r['raw_rank']:>2} -> #{r['adj_rank']:>2} ({r['rank_delta']:>+3d})  "
              f"NET: {r['raw_net']:>+6.1f} -> {r['adj_net']:>+6.1f}")

    # Distribution
    deltas = [r["net_delta"] for r in results]
    rank_deltas = [abs(r["rank_delta"]) for r in results]
    print(f"\n--- DISTRIBUTION ---")
    print(f"  NET change range: {min(deltas):>+.1f} to {max(deltas):>+.1f}")
    print(f"  Mean |NET change|: {sum(abs(d) for d in deltas)/len(deltas):.2f}")
    print(f"  Mean |rank change|: {sum(rank_deltas)/len(rank_deltas):.1f}")
    print(f"  Max rank change: {max(rank_deltas)}")

    # WSC North
    print(f"\n--- WSC NORTH ---")
    wsc = sorted([r for r in results if r["team"] in
                  ["Moorpark", "Ventura", "Allan Hancock", "Cuesta",
                   "LA Pierce", "Oxnard", "Santa Barbara"]],
                 key=lambda x: x["adj_net"], reverse=True)
    for r in wsc:
        print(f"  {r['team']:<16} AdjNET:{r['adj_net']:>+6.1f} RawNET:{r['raw_net']:>+6.1f} "
              f"({r['net_delta']:>+4.1f})  Rk: #{r['raw_rank']} -> #{r['adj_rank']} "
              f"({r['rank_delta']:>+2d})")

    # Conference strength
    print(f"\n--- CONFERENCE STRENGTH (avg adjusted NET) ---")
    conf_nets = defaultdict(list)
    for r in results:
        conf_nets[r["conf"]].append(r["adj_net"])
    conf_avgs = [(c, sum(v)/len(v), len(v)) for c, v in conf_nets.items()]
    conf_avgs.sort(key=lambda x: x[1], reverse=True)
    for conf, avg, n in conf_avgs:
        print(f"  {conf:<28} {avg:>+5.1f} ({n} teams)")

    # Spread comparison
    raw_nets = sorted([r["raw_net"] for r in results], reverse=True)
    adj_nets = sorted([r["adj_net"] for r in results], reverse=True)
    print(f"\n--- SPREAD ---")
    print(f"  Raw: #1={raw_nets[0]:>+.1f}, #25={raw_nets[24]:>+.1f}, "
          f"#50={raw_nets[49]:>+.1f}, #75={raw_nets[74]:>+.1f}, #100={raw_nets[99]:>+.1f}")
    print(f"  Adj: #1={adj_nets[0]:>+.1f}, #25={adj_nets[24]:>+.1f}, "
          f"#50={adj_nets[49]:>+.1f}, #75={adj_nets[74]:>+.1f}, #100={adj_nets[99]:>+.1f}")
    print(f"  Raw 1-100 spread: {raw_nets[0] - raw_nets[99]:.1f}")
    print(f"  Adj 1-100 spread: {adj_nets[0] - adj_nets[99]:.1f}")


if __name__ == "__main__":
    main()
