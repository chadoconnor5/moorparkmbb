#!/usr/bin/env python3
"""Backtest prior-season rating-decay schedules for the CCC rating system.

Motivation (kenpom.com/blog/preseason-ratings-why-weight): is "ditch last year's
rating by game 5" too aggressive for our system? KenPom argues ~5-10 games is too
small a sample, so zeroing the prior makes early ratings overreact then mean-revert.
JUCO roster turnover weakens the *team-specific* prior faster than D1, but the
*regression-to-mean / anti-overreaction* job should persist longer (~game 12-15).

Method: walk each season chronologically. Freeze every team's rating after its
first N games -- the current-season opponent-adjusted net blended with last
season's final net under a candidate decay schedule -- then predict every
remaining game and score out-of-sample error (RMSE of point margin + sign/win
accuracy). The schedule with the lowest early-season error wins.

Prior chain (roster turnover + COVID gap):
  2017-18 -> 2018-19 -> 2019-20 ;  [2020-21 COVID gap]  ;
  2021-22 -> 2022-23 -> 2023-24 -> 2024-25 -> 2025-26
2017-18 and 2021-22 are cold starts (no prior). Only seasons WITH a prior can
distinguish schedules, so only those are scored.

Run: /usr/local/bin/python3 backtest_prior_decay.py
"""
import json
import math
import re
from datetime import datetime
from pathlib import Path

# Season order and the prior each season decays from (None = cold start).
PRIOR = {
    "2017-18": None,
    "2018-19": "2017-18",
    "2019-20": "2018-19",
    "2021-22": None,        # COVID gap: do NOT chain 2019-20 -> 2021-22
    "2022-23": "2021-22",
    "2023-24": "2022-23",
    "2024-25": "2023-24",
    "2025-26": "2024-25",
}
SCORED_SEASONS = [s for s, p in PRIOR.items() if p]  # only seasons with a prior

HCA_NET = 3.5          # home-court edge, net points per 100 possessions
ADJ_ITERS = 15         # opponent-adjustment passes
CUTOFFS = [3, 5, 8, 10, 12, 15]   # freeze ratings after team's first N games

# Candidate prior-weight schedules: w(n) = virtual games of prior weight given the
# team has played n current-season games. Blend = (n*current + w*prior)/(n+w).
SCHEDULES = {
    "no_prior":            lambda n: 0.0,                       # KenPom strawman
    "cut_at_5_hard":       lambda n: 5.0 if n < 5 else 0.0,     # "ditch by game 5"
    "const_3":            lambda n: 3.0,
    "const_5_current":     lambda n: 5.0,                       # current system (5 virtual gms)
    "const_8":            lambda n: 8.0,
    "linear_to_0_by15":    lambda n: max(0.0, 8.0 * (1 - n / 15.0)),
    "linear_floor2_by15":  lambda n: max(2.0, 8.0 - (6.0 / 15.0) * n),
    "exp_decay_tau5":      lambda n: 8.0 * math.exp(-n / 5.0),
    "exp_decay_tau8":      lambda n: 8.0 * math.exp(-n / 8.0),
    "exp_decay_tau10":     lambda n: 8.0 * math.exp(-n / 10.0),
    "exp_decay_tau12":     lambda n: 8.0 * math.exp(-n / 12.0),
}


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _parse_date(d, season):
    """Parse 'M/D/YYYY' (or 'M/D/YY'); fall back to season-ordered index sort."""
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(d, fmt)
        except (ValueError, TypeError):
            pass
    return None


def load_season(season):
    """{team_norm: {name, net (final), all_games:[chronological]}}."""
    base = Path(f"{season} Team Statistics")
    teams = {}
    for aa in base.glob("**/advanced_analytics.json"):
        team_name = aa.parent.name
        try:
            d = json.load(open(aa))
        except Exception:
            continue
        t = d.get("team", {})
        games = []
        for i, g in enumerate(t.get("game_ratings", [])):
            if not g.get("in_system", True):
                continue
            try:
                net = float(g["ortg"]) - float(g["drtg"])
                poss = float(g.get("possessions") or 70.0)
            except (KeyError, TypeError, ValueError):
                continue
            ts, os_ = g.get("team_score"), g.get("opponent_score")
            if ts is None or os_ is None:
                continue
            dt = _parse_date(g.get("date", ""), season)
            games.append({
                "opp": _norm(g.get("canonical_opponent") or g.get("opponent")),
                "net": net, "poss": poss, "loc": g.get("location", "Neutral"),
                "margin": ts - os_, "dt": dt, "idx": i,
            })
        games.sort(key=lambda x: (x["dt"] is None, x["dt"] or datetime.min, x["idx"]))
        teams[_norm(team_name)] = {
            "name": team_name, "net": t.get("net_rtg"), "all_games": games,
        }
    return teams


def adjusted_nets(teams, N):
    """Opponent-adjusted net from each team's first N games (re-centered to 0)."""
    firstN = {tn: t["all_games"][:N] for tn, t in teams.items()}
    adj = {tn: (sum(g["net"] for g in gs) / len(gs) if gs else 0.0)
           for tn, gs in firstN.items()}
    for _ in range(ADJ_ITERS):
        nxt = {}
        for tn, gs in firstN.items():
            if not gs:
                nxt[tn] = adj.get(tn, 0.0)
                continue
            # adjusted performance = margin vs opp + that opponent's strength
            nxt[tn] = sum(g["net"] + adj.get(g["opp"], 0.0) for g in gs) / len(gs)
        m = sum(nxt.values()) / len(nxt) if nxt else 0.0
        adj = {tn: v - m for tn, v in nxt.items()}
    return adj


def blended_ratings(teams, adj, prior_nets, N, w_of_n):
    w = w_of_n(N)
    out = {}
    for tn, t in teams.items():
        n = min(N, len(t["all_games"]))
        cur = adj.get(tn, 0.0)
        pr = prior_nets.get(tn)
        if pr is None or w <= 0 or n == 0:
            out[tn] = cur if n > 0 else (pr if pr is not None else 0.0)
        else:
            out[tn] = (n * cur + w * pr) / (n + w)
    return out


def evaluate(teams, ratings, N):
    """Predict every game beyond each team's first N; return (sq_err_sum, n, correct)."""
    sse = 0.0
    n_pred = 0
    correct = 0
    for tn, t in teams.items():
        for i, g in enumerate(t["all_games"]):
            if i < N:
                continue
            if g["opp"] not in ratings or tn not in ratings:
                continue
            hca = HCA_NET if g["loc"] == "Home" else (-HCA_NET if g["loc"] == "Away" else 0.0)
            pred_net = ratings[tn] - ratings[g["opp"]] + hca
            pred_margin = pred_net * g["poss"] / 100.0
            sse += (pred_margin - g["margin"]) ** 2
            if (pred_margin > 0) == (g["margin"] > 0):
                correct += 1
            n_pred += 1
    return sse, n_pred, correct


def main():
    # Load all seasons once.
    loaded = {}
    for s in PRIOR:
        loaded[s] = load_season(s)
        print(f"Loaded {s}: {len(loaded[s])} teams")

    # Aggregate squared error + accuracy per (schedule, cutoff) across scored seasons.
    agg = {sch: {N: [0.0, 0, 0] for N in CUTOFFS} for sch in SCHEDULES}  # [sse, n, correct]

    for season in SCORED_SEASONS:
        teams = loaded[season]
        prior_teams = loaded[PRIOR[season]]
        prior_nets = {tn: pt["net"] for tn, pt in prior_teams.items() if pt["net"] is not None}
        for N in CUTOFFS:
            adj = adjusted_nets(teams, N)
            for sch, w_of_n in SCHEDULES.items():
                ratings = blended_ratings(teams, adj, prior_nets, N, w_of_n)
                sse, n, correct = evaluate(teams, ratings, N)
                agg[sch][N][0] += sse
                agg[sch][N][1] += n
                agg[sch][N][2] += correct

    def rmse(cell):
        return math.sqrt(cell[0] / cell[1]) if cell[1] else float("nan")

    def acc(cell):
        return cell[2] / cell[1] if cell[1] else float("nan")

    print("\n" + "=" * 78)
    print("PREDICTION RMSE (point margin) by schedule x freeze-after-game-N")
    print("Lower = better. Scored seasons (have a prior):", ", ".join(SCORED_SEASONS))
    print("=" * 78)
    hdr = f"{'schedule':<22}" + "".join(f"N={N:<5}" for N in CUTOFFS)
    print(hdr)
    print("-" * len(hdr))
    for sch in SCHEDULES:
        row = f"{sch:<22}" + "".join(f"{rmse(agg[sch][N]):<7.2f}" for N in CUTOFFS)
        print(row)

    print("\n" + "=" * 78)
    print("WIN-PREDICTION ACCURACY (sign of margin) by schedule x N   (higher = better)")
    print("=" * 78)
    print(hdr)
    print("-" * len(hdr))
    for sch in SCHEDULES:
        row = f"{sch:<22}" + "".join(f"{acc(agg[sch][N]) * 100:<7.1f}" for N in CUTOFFS)
        print(row)

    # Early-season summary (N <= 8): where the prior matters most.
    early = [N for N in CUTOFFS if N <= 8]
    print("\n" + "=" * 78)
    print(f"EARLY-SEASON RMSE (avg over N in {early}) -- the regime priors fix")
    print("=" * 78)
    ranked = []
    for sch in SCHEDULES:
        cells = [agg[sch][N] for N in early]
        sse = sum(c[0] for c in cells)
        n = sum(c[1] for c in cells)
        ranked.append((math.sqrt(sse / n) if n else float("nan"), sch))
    for r, sch in sorted(ranked):
        print(f"  {r:6.3f}   {sch}")
    best = min(ranked)[1]
    print(f"\nBest early-season schedule: {best}")


if __name__ == "__main__":
    main()
