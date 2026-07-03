#!/usr/bin/env python3
"""
Blowout-Cap NET RTG Simulation — 2025-26 season.

Re-computes ORTG/DRTG/NET RTG for every team by capping the winning margin
at `cap` points while keeping possessions unchanged.  Scores are adjusted so
the losing team keeps their actual score and the winner is capped at
(loser_score + cap).

Usage:
    python sim_blowout_cap.py                  # caps: 15, 20, 25, 30
    python sim_blowout_cap.py --cap 20         # single cap
    python sim_blowout_cap.py --top 15         # show top N teams
    python sim_blowout_cap.py --all            # show all teams
    python sim_blowout_cap.py --team Moorpark  # focus on one team
"""

import argparse
import json
from pathlib import Path

STATS_DIR = Path("2025-26 Team Statistics")

OPPONENT_ALIASES = {
    "CANYONS": "Canyons", "CERRITOS": "Cerritos", "COD-M": "Desert",
    "CUYAMACA": "Cuyamaca", "College of the Canyo": "Canyons",
    "College of the Sequoias": "Sequoias", "HARBOR-M": "LA Harbor",
    "Los Angeles Valley": "LA Valley", "MIRAMAR": "San Diego Miramar",
    "MSJC-M": "Mt. San Jacinto", "Mt. SAC": "Mt. San Antonio",
    "Pasadena": "Pasadena City", "VENTURA": "Ventura",
}

_CANONICAL = None
def _canon_teams():
    global _CANONICAL
    if _CANONICAL is not None:
        return _CANONICAL
    _CANONICAL = set()
    for c in STATS_DIR.iterdir():
        if c.is_dir():
            for t in c.iterdir():
                if t.is_dir():
                    _CANONICAL.add(t.name)
    return _CANONICAL

def resolve(name):
    ct = _canon_teams()
    if name in ct: return name
    a = OPPONENT_ALIASES.get(name)
    return a if a and a in ct else None


def compute_team_net(team_name, cap=None):
    """Return (ortg, drtg, net_rtg) for a team, with optional blowout cap."""
    for conf_dir in sorted(STATS_DIR.iterdir()):
        if not conf_dir.is_dir(): continue
        td = conf_dir / team_name
        if not td.is_dir(): continue
        gl_path = td / "game_log.json"
        if not gl_path.exists(): continue
        games = json.loads(gl_path.read_text()).get("games", [])
        ortg_vals, drtg_vals = [], []
        for g in games:
            ts  = g.get("team_stats", {})
            os_ = g.get("opponent_stats", {})
            if not ts or not os_: continue
            # Skip broken box scores
            t_broken = ts.get("FGA", 0) == 0 and ts.get("PTS", 0) == 0
            o_broken = os_.get("FGA", 0) == 0 and os_.get("PTS", 0) == 0
            if t_broken and o_broken: continue
            # Must be in-system opponent
            opp = g.get("opponent", "")
            if resolve(opp) is None: continue
            # Compute possessions
            t_poss = (ts.get("FGA",0) - ts.get("OREB",0)) + ts.get("TO",0) + 0.475*ts.get("FTA",0)
            o_poss = (os_.get("FGA",0) - os_.get("OREB",0)) + os_.get("TO",0) + 0.475*os_.get("FTA",0)
            if t_broken or t_poss <= 0:
                avg_poss = o_poss if o_poss > 0 else None
            elif o_broken or o_poss <= 0:
                avg_poss = t_poss
            else:
                avg_poss = (t_poss + o_poss) / 2
            if not avg_poss or avg_poss <= 0: continue
            # Actual scores
            t_pts = g.get("team_score", 0) if t_broken else ts.get("PTS", 0)
            o_pts = g.get("opponent_score", 0) if o_broken else os_.get("PTS", 0)
            # Apply cap
            if cap is not None:
                margin = t_pts - o_pts
                if margin > cap:
                    t_pts = o_pts + cap
                elif margin < -cap:
                    o_pts = t_pts + cap
            ortg_vals.append(t_pts / avg_poss * 100)
            drtg_vals.append(o_pts / avg_poss * 100)
        if not ortg_vals:
            return None, None, None
        ortg = round(sum(ortg_vals) / len(ortg_vals), 1)
        drtg = round(sum(drtg_vals) / len(drtg_vals), 1)
        return ortg, drtg, round(ortg - drtg, 1)
    return None, None, None


def build_rankings(cap=None):
    teams = []
    for conf_dir in sorted(STATS_DIR.iterdir()):
        if not conf_dir.is_dir(): continue
        for td in sorted(conf_dir.iterdir()):
            if not td.is_dir(): continue
            ortg, drtg, net = compute_team_net(td.name, cap)
            if net is None: continue
            teams.append({
                "team": td.name,
                "conference": conf_dir.name,
                "ortg": ortg,
                "drtg": drtg,
                "net_rtg": net,
            })
    teams.sort(key=lambda x: x["net_rtg"], reverse=True)
    for i, t in enumerate(teams):
        t["rank"] = i + 1
    return teams


def main():
    parser = argparse.ArgumentParser(description="Blowout-cap NET RTG simulation")
    parser.add_argument("--cap",  type=int, default=None,
                        help="Single cap value (default: show 15/20/25/30)")
    parser.add_argument("--top",  type=int, default=25)
    parser.add_argument("--all",  action="store_true")
    parser.add_argument("--team", type=str, default=None)
    args = parser.parse_args()

    caps = [args.cap] if args.cap else [15, 20, 25, 30]
    baseline = build_rankings(cap=None)
    base_map = {t["team"]: t for t in baseline}

    if args.team:
        name = args.team
        if name not in base_map:
            print(f"Team '{name}' not found.")
            return
        b = base_map[name]
        print(f"\n{'─'*62}")
        print(f"  {name} — Blowout Cap Sensitivity")
        print(f"{'─'*62}")
        print(f"  {'Cap':>6}  {'ORTG':>6}  {'DRTG':>6}  {'NET':>6}  {'Rank':>5}  {'Δ Rank':>7}")
        print(f"  {'(none)':>6}  {b['ortg']:>6.1f}  {b['drtg']:>6.1f}  {b['net_rtg']:>+6.1f}  {b['rank']:>5}  {'—':>7}")
        for cap in caps:
            cm = {t["team"]: t for t in build_rankings(cap=cap)}
            if name in cm:
                c = cm[name]
                delta = b["rank"] - c["rank"]
                ds = f"+{delta}" if delta > 0 else str(delta)
                print(f"  {cap:>6}  {c['ortg']:>6.1f}  {c['drtg']:>6.1f}  {c['net_rtg']:>+6.1f}  {c['rank']:>5}  {ds:>7}")
        print()
        return

    cap_rankings = {cap: {t["team"]: t for t in build_rankings(cap=cap)} for cap in caps}
    n = len(baseline) if args.all else min(args.top, len(baseline))

    w = 6 + len(caps) * 15
    print(f"\n{'─'*80}")
    print(f"  2025-26 Blowout-Cap NET RTG Simulation")
    print(f"  Δ = rank change vs uncapped  (positive = moves UP when blowouts are capped)")
    print(f"{'─'*80}")
    cap_hdr = "   ".join(f"Cap-{c:>2}(Rk/Δ)" for c in caps)
    print(f"  {'Rk':>3}  {'Team':<22}  {'NET':>5}  {cap_hdr}")
    print(f"{'─'*80}")

    for t in baseline[:n]:
        name = t["team"]
        net_str = f"{t['net_rtg']:>+.1f}"
        cols = []
        for cap in caps:
            c = cap_rankings[cap].get(name)
            if c:
                delta = t["rank"] - c["rank"]
                ds = f"+{delta}" if delta > 0 else (f"{delta}" if delta != 0 else "±0")
                cols.append(f"{c['net_rtg']:>+5.1f} {c['rank']:>3}/{ds:<3}")
            else:
                cols.append("       n/a   ")
        print(f"  {t['rank']:>3}  {name:<22}  {net_str:>5}  {'   '.join(cols)}")

    print(f"{'─'*80}")
    print(f"  Top {n} of {len(baseline)} teams  |  Cap = max allowed winning margin (pts)\n")


if __name__ == "__main__":
    main()

