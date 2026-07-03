#!/usr/bin/env python3
"""
Miyakawa-style Relative Rating for CCCAA teams.

Algorithm (iterative, converges to fixed point):
  1. Initialize scores = centered net_rtg
  2. Sort teams by score → assign ranks 1..N
  3. For team at rank r:
       peer_strength(r)  = smoothed mean score of neighboring ranks (±5)
       peer_tempo(r)     = smoothed mean tempo of neighboring ranks (±5)
       adj = opp_adjust × peer_strength + pace_adjust × (peer_tempo - avg_tempo)
       new_score = base_net_rtg + adj
  4. Re-center mean to 0 → repeat until convergence

O-Rate  = (ortg - avg_ortg)   + adj/2   [higher = better offense vs peers]
D-Rate  = (avg_drtg - drtg)   + adj/2   [higher = better defense vs peers]
Rel-Rtg = O-Rate + D-Rate               [net efficiency vs average at same rank level]

Matchup prediction: team_A - team_B Rel-Rtg = expected pts/100 possessions advantage.
"""
import json
import argparse
from pathlib import Path

STATS_DIRS = {
    "2025-26": Path("2025-26 Team Statistics"),
    "2024-25": Path("2024-25 Team Statistics"),
}
PEER_WINDOW = 5    # ±5 ranks for peer smoothing
MAX_ITER    = 50
CONV_DELTA  = 0.001


def load_teams(season: str) -> list[dict]:
    stats_dir = STATS_DIRS[season]
    teams = []
    for conf_dir in sorted(stats_dir.iterdir()):
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
            if ta.get("ortg", 0) <= 0:
                continue
            teams.append({
                "team":        team_dir.name,
                "conference":  conf_dir.name,
                "ortg":        ta.get("ortg",        0.0),
                "drtg":        ta.get("drtg",        0.0),
                "net_rtg":     ta.get("net_rtg",     0.0),
                "tempo":       ta.get("tempo",       68.0),
                "opp_adjust":  ta.get("opp_adjust",  0.0),
                "pace_adjust": ta.get("pace_adjust", 0.0),
            })
    return teams


def smooth_window(vals: list[float], idx: int, k: int = PEER_WINDOW) -> float:
    lo = max(0, idx - k)
    hi = min(len(vals) - 1, idx + k)
    window = vals[lo : hi + 1]
    return sum(window) / len(window)


def run_relative_ratings(teams: list[dict], verbose: bool = False) -> list[dict]:
    N = len(teams)
    avg_ortg  = sum(t["ortg"]  for t in teams) / N
    avg_drtg  = sum(t["drtg"]  for t in teams) / N
    avg_tempo = sum(t["tempo"] for t in teams) / N
    avg_net   = avg_ortg - avg_drtg

    # Base (centered) NET RTG for each team — constant across iterations
    base = {t["team"]: t["net_rtg"] - avg_net for t in teams}

    # Initial scores = centered net_rtg
    scores = dict(base)

    for it in range(MAX_ITER):
        sorted_t = sorted(teams, key=lambda t: scores[t["team"]], reverse=True)
        s_scores  = [scores[t["team"]] for t in sorted_t]
        s_tempos  = [t["tempo"]        for t in sorted_t]

        new_scores = {}
        for idx, t in enumerate(sorted_t):
            peer_strength = smooth_window(s_scores, idx)
            peer_tempo    = smooth_window(s_tempos, idx)
            adj = (t["opp_adjust"]  * peer_strength
                 + t["pace_adjust"] * (peer_tempo - avg_tempo))
            new_scores[t["team"]] = base[t["team"]] + adj

        # Re-center to mean = 0
        mean_s = sum(new_scores.values()) / N
        new_scores = {k: v - mean_s for k, v in new_scores.items()}

        delta = max(abs(new_scores[t["team"]] - scores[t["team"]]) for t in teams)
        scores = new_scores

        if verbose:
            print(f"  iter {it+1:2d}  delta={delta:.5f}")
        if delta < CONV_DELTA:
            if not verbose:
                print(f"  Converged after {it+1} iterations (Δ={delta:.5f})")
            break

    # Final pass: compute O-Rate, D-Rate
    sorted_final = sorted(teams, key=lambda t: scores[t["team"]], reverse=True)
    s_scores_f   = [scores[t["team"]] for t in sorted_final]
    s_tempos_f   = [t["tempo"]        for t in sorted_final]

    results = []
    for idx, t in enumerate(sorted_final):
        peer_strength = smooth_window(s_scores_f, idx)
        peer_tempo    = smooth_window(s_tempos_f, idx)
        adj = (t["opp_adjust"]  * peer_strength
             + t["pace_adjust"] * (peer_tempo - avg_tempo))

        o_rate = (t["ortg"] - avg_ortg) + adj / 2
        d_rate = (avg_drtg  - t["drtg"]) + adj / 2

        results.append({
            "team":        t["team"],
            "conference":  t["conference"],
            "net_rtg":     t["net_rtg"],
            "o_rate":      round(o_rate,             2),
            "d_rate":      round(d_rate,             2),
            "rel_rating":  round(scores[t["team"]],  2),
            "opp_adjust":  t["opp_adjust"],
            "pace_adjust": t["pace_adjust"],
            "rank_rel":    idx + 1,
            "rank_net":    0,   # filled below
        })

    # NET RTG ranks for comparison
    for i, r in enumerate(sorted(results, key=lambda x: x["net_rtg"], reverse=True)):
        r["rank_net"] = i + 1

    return results


def print_table(results: list[dict], label: str = "", limit: int | None = None) -> None:
    hdr = (f"{'Rk':>3}  {'Team':<26} {'Conference':<24}"
           f"  {'O-Rate':>7} {'D-Rate':>7} {'Rel-Rtg':>8}"
           f"  {'NET RTG':>7} {'Rk Δ':>5}"
           f"  {'OPP-ADJ':>8} {'PCE-ADJ':>8}")
    sep = "─" * len(hdr)
    if label:
        print(f"\n{'═'*len(hdr)}")
        print(f"  {label}")
    print(sep)
    print(hdr)
    print(sep)
    shown = 0
    for r in results:
        rank_delta = r["rank_net"] - r["rank_rel"]
        dstr = (f"▲{rank_delta}" if rank_delta > 0
                else f"▼{abs(rank_delta)}" if rank_delta < 0
                else "—")
        print(f"{r['rank_rel']:>3}  {r['team']:<26} {r['conference']:<24}"
              f"  {r['o_rate']:>7.1f} {r['d_rate']:>7.1f} {r['rel_rating']:>8.1f}"
              f"  {r['net_rtg']:>7.1f} {dstr:>5}"
              f"  {r['opp_adjust']:>+8.3f} {r['pace_adjust']:>+8.3f}")
        shown += 1
        if limit and shown >= limit:
            break
    print(sep)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute Miyakawa-style Relative Ratings")
    parser.add_argument("--season",  default="2025-26", choices=list(STATS_DIRS))
    parser.add_argument("--top",     type=int, default=25,  help="Show top N (default 25)")
    parser.add_argument("--all",     action="store_true",   help="Show all 100 teams")
    parser.add_argument("--team",    default=None,          help="Filter to a specific team name")
    parser.add_argument("--verbose", action="store_true",   help="Print per-iteration delta")
    args = parser.parse_args()

    print(f"\nLoading {args.season} data …")
    teams = load_teams(args.season)
    if not teams:
        print("  No teams found — check that advanced_analytics.json files exist.")
        return
    print(f"  {len(teams)} teams")

    N = len(teams)
    avg_ortg  = sum(t["ortg"]  for t in teams) / N
    avg_drtg  = sum(t["drtg"]  for t in teams) / N
    avg_tempo = sum(t["tempo"] for t in teams) / N
    print(f"  League avg  ORTG={avg_ortg:.1f}  DRTG={avg_drtg:.1f}  Tempo={avg_tempo:.1f}")

    print(f"\nRunning iterative Relative Rating …")
    results = run_relative_ratings(teams, verbose=args.verbose)

    if args.team:
        filtered = [r for r in results if args.team.lower() in r["team"].lower()]
        if not filtered:
            print(f"  No team matching '{args.team}' found.")
        else:
            print_table(filtered, label=f"Results for '{args.team}'")
        return

    limit = None if args.all else args.top
    print_table(results, label=f"{args.season} — Top {limit or N} by Relative Rating", limit=limit)

    # Always show Moorpark regardless of --top
    moorpark = next((r for r in results if r["team"] == "Moorpark"), None)
    if moorpark and (limit is None or moorpark["rank_rel"] > limit):
        print(f"\n  Moorpark: Rel-Rtg rank #{moorpark['rank_rel']}  "
              f"(NET RTG rank #{moorpark['rank_net']}  "
              f"Δ={moorpark['rank_net']-moorpark['rank_rel']:+d})")

    # Summary: biggest movers
    movers_up   = sorted(results, key=lambda r: r["rank_net"] - r["rank_rel"], reverse=True)[:5]
    movers_down = sorted(results, key=lambda r: r["rank_net"] - r["rank_rel"])[:5]
    print(f"\n  Biggest movers UP   (Rel-Rtg >> NET RTG):")
    for r in movers_up:
        d = r["rank_net"] - r["rank_rel"]
        print(f"    ▲{d:2d}  #{r['rank_rel']:<3}  {r['team']:<26}  opp_adj={r['opp_adjust']:+.3f}")
    print(f"\n  Biggest movers DOWN (NET RTG >> Rel-Rtg):")
    for r in movers_down:
        d = r["rank_net"] - r["rank_rel"]
        print(f"    ▼{abs(d):2d}  #{r['rank_rel']:<3}  {r['team']:<26}  opp_adj={r['opp_adjust']:+.3f}")


if __name__ == "__main__":
    main()
