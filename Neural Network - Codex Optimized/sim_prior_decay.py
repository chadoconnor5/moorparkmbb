#!/usr/bin/env python3
"""
Prior-decay simulation: blend 2024-25 NET ratings into 2025-26 iterative system.

Models the intuition that last season's performance is a meaningful prior for
this season, with that prior decaying as more 2025-26 games accumulate.

Approach (Bayesian prior in iterative framework):
  - Load 2024-25 final NET/ORTG/DRTG as a per-team prior
  - Apply PRIOR_DECAY to account for roster turnover (CC programs ~60-70% continuity)
  - In the regression step, regress toward each team's decayed prior (team-specific)
    rather than a flat league average (generic)
  - Prior contributes PRIOR_GAMES equivalent virtual observations
  - As actual 2025-26 games accumulate, the prior weight fades: w = P/(P+n)

Parameters:
  PRIOR_GAMES   how many virtual game-equivalents the 2024-25 prior is worth
  PRIOR_DECAY   fraction of 2024-25 NET retained (1.0 = full credit, 0.5 = half)
  HOME_ADVANTAGE, DAMPEN, MAX_ITER  — same as sim_iterative_normalized.py

Usage:
  python3 sim_prior_decay.py                  # default params
  python3 sim_prior_decay.py --prior-games 8  # weaker prior
  python3 sim_prior_decay.py --decay 0.75     # stronger carry-over
  python3 sim_prior_decay.py --conf "WSC North"
"""
import json
import argparse
from pathlib import Path
from collections import defaultdict

STATS_DIR_2026 = Path("2025-26 Team Statistics")
STATS_DIR_2024 = Path("2024-25 Team Statistics")

# --- Tunable parameters ---
HOME_ADVANTAGE = 3.0    # pts/100 possessions home edge
PRIOR_GAMES    = 10     # virtual game-equivalents the prior contributes
PRIOR_DECAY    = 0.60   # fraction of prior NET to carry over (roster turnover discount)
DAMPEN         = 0.5    # blend factor between iterations (prevents oscillation)
MAX_ITER       = 100    # max iterations before forced convergence
CONV_THRESHOLD = 0.01   # NET change per team below which we declare convergence


def load_2024_priors():
    """Load 2024-25 final NET/ORTG/DRTG for each team."""
    priors = {}
    for conf_dir in sorted(STATS_DIR_2024.iterdir()):
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
            if ta.get("ortg", 0) > 0 and ta.get("net_rtg") is not None:
                priors[team_dir.name] = {
                    "ortg":    ta["ortg"],
                    "drtg":    ta["drtg"],
                    "net_rtg": ta["net_rtg"],
                }
    return priors


def load_2026_teams():
    """Load 2025-26 game ratings and conferences."""
    team_game_ratings = {}
    team_conferences  = {}

    for conf_dir in sorted(STATS_DIR_2026.iterdir()):
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
            if ta.get("ortg", 0) > 0:
                team_game_ratings[team_dir.name] = ta.get("game_ratings", [])
                team_conferences[team_dir.name]  = conf_dir.name

    return team_game_ratings, team_conferences


def compute_raw_ratings(team_game_ratings):
    """Compute simple unweighted averages as the starting seed."""
    raw = {}
    for team, gr in team_game_ratings.items():
        in_sys = [g for g in gr if g.get("in_system")]
        if in_sys:
            raw[team] = {
                "ortg": sum(g["ortg"] for g in in_sys) / len(in_sys),
                "drtg": sum(g["drtg"] for g in in_sys) / len(in_sys),
            }
        else:
            raw[team] = {"ortg": 100.0, "drtg": 100.0}
    return raw


def run_iterative(team_game_ratings, priors_decayed, league_ortg, league_drtg,
                  prior_games, dampen, max_iter, conv_threshold):
    """
    Iterative opponent-adjusted efficiency with per-team prior regression.

    Returns dict: team -> {ortg, drtg, net_rtg}
    """
    # Seed with raw ratings
    current = compute_raw_ratings(team_game_ratings)

    # Games count per team
    games_count = {
        t: len([g for g in gr if g.get("in_system") and g.get("canonical_opponent")])
        for t, gr in team_game_ratings.items()
    }

    for iteration in range(1, max_iter + 1):
        new_ratings = {}

        for team, gr in team_game_ratings.items():
            in_sys = [g for g in gr if g.get("in_system") and g.get("canonical_opponent")]
            n = len(in_sys)

            if n == 0:
                # No games at all — fall back to prior or league average
                if team in priors_decayed:
                    p = priors_decayed[team]
                    new_ratings[team] = {"ortg": p["ortg"], "drtg": p["drtg"]}
                else:
                    new_ratings[team] = {"ortg": league_ortg, "drtg": league_drtg}
                continue

            # Opponent-adjusted game efficiencies
            adj_ortgs, adj_drtgs = [], []
            for g in in_sys:
                opp = g["canonical_opponent"]
                if opp not in current:
                    adj_ortgs.append(g["ortg"])
                    adj_drtgs.append(g["drtg"])
                    continue

                opp_drtg = current[opp]["drtg"]
                opp_ortg = current[opp]["ortg"]

                hca_o = hca_d = 0.0
                loc = g.get("location", "")
                if loc == "Home":
                    hca_o = -HOME_ADVANTAGE / 2
                    hca_d = +HOME_ADVANTAGE / 2
                elif loc == "Away":
                    hca_o = +HOME_ADVANTAGE / 2
                    hca_d = -HOME_ADVANTAGE / 2

                adj_ortgs.append(g["ortg"] + hca_o - opp_drtg + league_drtg)
                adj_drtgs.append(g["drtg"] + hca_d - opp_ortg + league_ortg)

            if not adj_ortgs:
                new_ratings[team] = current[team]
                continue

            game_ortg = sum(adj_ortgs) / len(adj_ortgs)
            game_drtg = sum(adj_drtgs) / len(adj_drtgs)

            # Regression target: team-specific prior (if available) else league avg
            if team in priors_decayed:
                p = priors_decayed[team]
                prior_o = p["ortg"]
                prior_d = p["drtg"]
            else:
                prior_o = league_ortg
                prior_d = league_drtg

            # Prior weight decays as games accumulate: w = P/(P+n)
            prior_weight = prior_games / (prior_games + n)
            blended_ortg = (1 - prior_weight) * game_ortg + prior_weight * prior_o
            blended_drtg = (1 - prior_weight) * game_drtg + prior_weight * prior_d

            # Dampen toward previous iteration
            new_ortg = dampen * blended_ortg + (1 - dampen) * current[team]["ortg"]
            new_drtg = dampen * blended_drtg + (1 - dampen) * current[team]["drtg"]

            new_ratings[team] = {"ortg": new_ortg, "drtg": new_drtg}

        # Normalize to preserve target league averages
        if new_ratings:
            avg_o = sum(r["ortg"] for r in new_ratings.values()) / len(new_ratings)
            avg_d = sum(r["drtg"] for r in new_ratings.values()) / len(new_ratings)
            offset_o = league_ortg - avg_o
            offset_d = league_drtg - avg_d
            for t in new_ratings:
                new_ratings[t]["ortg"] += offset_o
                new_ratings[t]["drtg"] += offset_d

        # Convergence check
        max_change = max(
            abs((new_ratings[t]["ortg"] - current[t]["ortg"]) -
                (new_ratings[t]["drtg"] - current[t]["drtg"]))
            for t in new_ratings if t in current
        ) if current else 999

        current = new_ratings

        if max_change < conv_threshold:
            print(f"  Converged after {iteration} iterations (max NET Δ = {max_change:.4f})")
            break
    else:
        print(f"  Did not fully converge after {max_iter} iterations")

    return {t: {"ortg": r["ortg"], "drtg": r["drtg"],
                "net_rtg": r["ortg"] - r["drtg"]}
            for t, r in current.items()}


def main():
    parser = argparse.ArgumentParser(description="Prior-decay simulation blending 2024-25 NET into 2025-26 ratings")
    parser.add_argument("--prior-games", type=float, default=PRIOR_GAMES,
                        help=f"Virtual game-equivalents the prior is worth (default {PRIOR_GAMES})")
    parser.add_argument("--decay", type=float, default=PRIOR_DECAY,
                        help=f"Fraction of 2024-25 NET to carry over (default {PRIOR_DECAY})")
    parser.add_argument("--conf", type=str, default=None,
                        help="Filter output to a single conference name")
    parser.add_argument("--top", type=int, default=None,
                        help="Show only top N teams overall")
    args = parser.parse_args()

    prior_games  = args.prior_games
    prior_decay  = args.decay
    conf_filter  = args.conf

    print(f"=== Prior-Decay Simulation ===")
    print(f"  Prior games equivalent : {prior_games}")
    print(f"  Prior decay factor     : {prior_decay}  (1.0 = full credit, 0.5 = half)")
    print(f"  Home advantage         : {HOME_ADVANTAGE} pts/100")
    print(f"  Dampening              : {DAMPEN}")
    print()

    # --- Load data ---
    priors_raw = load_2024_priors()
    team_game_ratings, team_conferences = load_2026_teams()

    print(f"  2024-25 priors available : {len(priors_raw)} teams")
    print(f"  2025-26 teams with data  : {len(team_game_ratings)} teams")

    # Teams in both seasons
    both = set(priors_raw) & set(team_game_ratings)
    only_new = set(team_game_ratings) - set(priors_raw)
    only_old = set(priors_raw) - set(team_game_ratings)
    print(f"  In both seasons          : {len(both)} teams")
    print(f"  New in 2025-26 (no prior): {len(only_new)} teams")
    if only_old:
        print(f"  In 2024-25 only          : {len(only_old)} teams — {sorted(only_old)}")
    print()

    # --- League averages from 2025-26 raw ratings ---
    raw_2026 = compute_raw_ratings(team_game_ratings)
    league_ortg = sum(r["ortg"] for r in raw_2026.values()) / len(raw_2026)
    league_drtg = sum(r["drtg"] for r in raw_2026.values()) / len(raw_2026)
    print(f"  2025-26 league avg ORTG : {league_ortg:.1f}")
    print(f"  2025-26 league avg DRTG : {league_drtg:.1f}")
    print()

    # --- Build decayed priors ---
    # Convert 2024-25 ratings to the 2025-26 scale (shift by league avg delta)
    prior_league_ortg = sum(p["ortg"] for p in priors_raw.values()) / len(priors_raw)
    prior_league_drtg = sum(p["drtg"] for p in priors_raw.values()) / len(priors_raw)
    ortg_shift = league_ortg - prior_league_ortg
    drtg_shift = league_drtg - prior_league_drtg

    priors_decayed = {}
    for team, p in priors_raw.items():
        # Decay the advantage/disadvantage vs league, then re-anchor to current scale
        prior_net  = p["net_rtg"] * prior_decay
        prior_o_excess = (p["ortg"] - prior_league_ortg) * prior_decay
        prior_d_excess = (p["drtg"] - prior_league_drtg) * prior_decay
        priors_decayed[team] = {
            "ortg":    league_ortg + prior_o_excess,
            "drtg":    league_drtg + prior_d_excess,
            "net_rtg": prior_net,
        }

    # --- Run pure 2025-26 iterative (no prior, regress to league avg) ---
    print("Running pure 2025-26 iterative (baseline)...")
    # Build neutral priors mapping to league avg for every team
    neutral_priors = {t: {"ortg": league_ortg, "drtg": league_drtg}
                      for t in team_game_ratings}
    pure_2026 = run_iterative(
        team_game_ratings, neutral_priors,
        league_ortg, league_drtg,
        prior_games, DAMPEN, MAX_ITER, CONV_THRESHOLD
    )

    # --- Run prior-decay iterative ---
    print("Running prior-decay iterative...")
    prior_informed = run_iterative(
        team_game_ratings, priors_decayed,
        league_ortg, league_drtg,
        prior_games, DAMPEN, MAX_ITER, CONV_THRESHOLD
    )

    # --- Build results table ---
    results = []
    for team in sorted(team_game_ratings):
        in_sys_games = [g for g in team_game_ratings[team]
                        if g.get("in_system") and g.get("canonical_opponent")]
        n_games = len(in_sys_games)
        prior_w = prior_games / (prior_games + n_games) if n_games > 0 else 1.0
        conf = team_conferences.get(team, "")

        p24_net = priors_raw[team]["net_rtg"] if team in priors_raw else None
        p24_dec = round(p24_net * prior_decay, 1) if p24_net is not None else None

        raw26   = raw_2026[team]
        raw_net = raw26["ortg"] - raw26["drtg"]

        b = pure_2026[team]
        pd = prior_informed[team]

        results.append({
            "team":      team,
            "conf":      conf,
            "games":     n_games,
            "prior_w":   round(prior_w, 2),
            "prior_24":  round(p24_net, 1) if p24_net is not None else None,
            "prior_dec": p24_dec,
            "raw_net":   round(raw_net, 1),
            "base_ortg": round(b["ortg"], 1),
            "base_drtg": round(b["drtg"], 1),
            "base_net":  round(b["net_rtg"], 1),
            "pd_ortg":   round(pd["ortg"], 1),
            "pd_drtg":   round(pd["drtg"], 1),
            "pd_net":    round(pd["net_rtg"], 1),
            "net_delta": round(pd["net_rtg"] - b["net_rtg"], 1),
        })

    # Rank by prior-decay NET
    results.sort(key=lambda x: x["base_net"], reverse=True)
    for i, r in enumerate(results):
        r["base_rank"] = i + 1
    results.sort(key=lambda x: x["pd_net"], reverse=True)
    for i, r in enumerate(results):
        r["pd_rank"] = i + 1
        r["rank_delta"] = r["base_rank"] - r["pd_rank"]

    # --- Filter ---
    display = results
    if conf_filter:
        display = [r for r in results if conf_filter.lower() in r["conf"].lower()]
    if args.top:
        display = results[:args.top]

    # --- Print full table ---
    print()
    print(f"{'Rk':>3} {'was':>4} {'Team':<22} {'PD-NET':>7} {'Base':>6} {'Δ':>5} "
          f"{'Prior24':>8} {'Decay':>6} {'PriorW':>7} {'Gms':>4}  {'Conf'}")
    print("-" * 100)
    for r in display:
        was_str = str(r["base_rank"]) if r["rank_delta"] != 0 else ""
        prior_str = f"{r['prior_24']:>+.1f}" if r["prior_24"] is not None else "  N/A"
        dec_str   = f"{r['prior_dec']:>+.1f}" if r["prior_dec"] is not None else "  N/A"
        print(f"{r['pd_rank']:>3} {was_str:>4} {r['team']:<22} "
              f"{r['pd_net']:>+7.1f} {r['base_net']:>+6.1f} {r['net_delta']:>+5.1f} "
              f"{prior_str:>8} {dec_str:>6} "
              f"{r['prior_w']:>6.0%} {r['games']:>4}  {r['conf']}")

    # --- Biggest movers (prior vs pure 2025-26) ---
    if not conf_filter and not args.top:
        print(f"\n--- BIGGEST RISERS (prior pushes them up) ---")
        for r in sorted(results, key=lambda x: x["rank_delta"], reverse=True)[:12]:
            print(f"  {r['team']:<22}  #{r['base_rank']:>2} -> #{r['pd_rank']:>2} ({r['rank_delta']:>+3d})"
                  f"  Prior24={r['prior_24']:>+5.1f}  Base={r['base_net']:>+5.1f} -> PD={r['pd_net']:>+5.1f}"
                  f"  Δ={r['net_delta']:>+4.1f}")

        print(f"\n--- BIGGEST FALLERS (prior drags them down) ---")
        for r in sorted(results, key=lambda x: x["rank_delta"])[:12]:
            print(f"  {r['team']:<22}  #{r['base_rank']:>2} -> #{r['pd_rank']:>2} ({r['rank_delta']:>+3d})"
                  f"  Prior24={r['prior_24']:>+5.1f}  Base={r['base_net']:>+5.1f} -> PD={r['pd_net']:>+5.1f}"
                  f"  Δ={r['net_delta']:>+4.1f}")

        # Distribution
        deltas = [r["net_delta"] for r in results]
        print(f"\n--- DISTRIBUTION ---")
        print(f"  NET change range : {min(deltas):>+.1f} to {max(deltas):>+.1f}")
        print(f"  Mean |NET Δ|     : {sum(abs(d) for d in deltas)/len(deltas):.2f}")
        print(f"  Teams pushed up  : {sum(1 for d in deltas if d > 0.5)}")
        print(f"  Teams pushed down: {sum(1 for d in deltas if d < -0.5)}")
        print(f"  Teams ~unchanged : {sum(1 for d in deltas if abs(d) <= 0.5)}")

    # --- WSC North spotlight ---
    wsc_teams = {"Moorpark", "Ventura", "Allan Hancock", "Cuesta", "Oxnard", "Santa Barbara", "LA Pierce"}
    wsc = [r for r in results if r["team"] in wsc_teams]
    if wsc:
        print(f"\n--- WSC NORTH ---")
        print(f"{'Rk':>3} {'was':>4} {'Team':<22} {'PD-NET':>7} {'Base':>6} {'Δ':>5} "
              f"{'Prior24':>8} {'Decay':>6} {'PriorW':>7} {'Gms':>4}")
        print("-" * 75)
        for r in sorted(wsc, key=lambda x: x["pd_rank"]):
            was_str   = str(r["base_rank"]) if r["rank_delta"] != 0 else ""
            prior_str = f"{r['prior_24']:>+.1f}" if r["prior_24"] is not None else "  N/A"
            dec_str   = f"{r['prior_dec']:>+.1f}" if r["prior_dec"] is not None else "  N/A"
            print(f"{r['pd_rank']:>3} {was_str:>4} {r['team']:<22} "
                  f"{r['pd_net']:>+7.1f} {r['base_net']:>+6.1f} {r['net_delta']:>+5.1f} "
                  f"{prior_str:>8} {dec_str:>6} "
                  f"{r['prior_w']:>6.0%} {r['games']:>4}")

    print(f"\nNote: 'Base' = pure 2025-26 iterative (no prior). 'PD-NET' = prior-decay hybrid.")
    print(f"      'Prior24' = 2024-25 raw NET. 'Decay' = prior after {prior_decay:.0%} decay.")
    print(f"      'PriorW' = prior weight remaining given games played ({prior_games:.0f} virtual games).")


if __name__ == "__main__":
    main()
