#!/usr/bin/env python3
"""PROTOTYPE: box-score offensive archetypes for CCC players.

bball-index's 12 offensive archetypes need play-type/tracking data we don't have.
This is a box-score-only approximation built from metrics we already compute
(usage, assist rate, 3PA-rate, FT-rate, OREB%, TS%, 2P/3P split) plus the size
position class. Rule-based with LEAGUE-RELATIVE (percentile) thresholds so it
adapts to the data distribution. Test harness only -- not wired into the build.

Run: /usr/local/bin/python3 prototype_offensive_archetypes.py
"""
import statistics
import generate_leaderboard as g

PERIM = {"PG", "s-PG", "CG", "WG", "WF"}
BIG = {"S-PF", "PF/C", "C"}


def pct_rank(value, sorted_vals):
    """Fraction of pool <= value (0..1)."""
    if value is None or not sorted_vals:
        return 0.0
    below = sum(1 for v in sorted_vals if v <= value)
    return below / len(sorted_vals)


def build_percentiles(players, keys):
    cols = {}
    for k in keys:
        cols[k] = sorted(float(p[k]) for p in players if p.get(k) is not None)
    return cols


def assign(p, P, Pbig):
    """Return an offensive archetype label for player p given percentile tables."""
    pos = p.get("pos", "")
    def pr(k, table=P):
        return pct_rank(_f(p.get(k)), table.get(k, []))

    if pos in BIG:
        tpa = pr("tpa_rate", Pbig)
        usg = pr("usage_pct", Pbig)
        oreb = pr("oreb_pct", Pbig)
        if tpa >= 0.70:
            return "Stretch Big"
        if usg >= 0.60 and tpa < 0.50:
            return "Post Scorer"
        if oreb >= 0.55 or usg < 0.45:
            return "Roll & Cut / Rim Big"
        return "Versatile Big"

    # Perimeter
    usg = pr("usage_pct")
    ast = pr("ast_rate")
    tpa = pr("tpa_rate")
    ftr = pr("ft_rate")
    if ast >= 0.70 and usg >= 0.55:
        return "Primary Creator"
    if usg >= 0.70 and ast < 0.50:
        return "Shot Creator"
    if tpa >= 0.65 and usg < 0.55:
        return "Off-Ball Shooter"
    if ftr >= 0.65 and tpa < 0.45:
        return "Slasher / Finisher"
    if ast >= 0.55:
        return "Secondary Handler"
    return "Role / Connector"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    players = [p for p in g.load_players()
               if p.get("q") == 1 and int(p.get("fm", 1)) == 0
               and p.get("usage_pct") is not None]
    print(f"\nQualified, real-minutes players: {len(players)}\n")

    keys = ["usage_pct", "ast_rate", "tpa_rate", "ft_rate", "oreb_pct", "ts_pct", "shot_pct"]
    perim = [p for p in players if p.get("pos") in PERIM]
    bigs = [p for p in players if p.get("pos") in BIG]
    P = build_percentiles(perim, keys)
    Pbig = build_percentiles(bigs, keys)

    for p in players:
        p["_arch"] = assign(p, P, Pbig)

    # Distribution
    from collections import Counter
    dist = Counter(p["_arch"] for p in players)
    print("ARCHETYPE DISTRIBUTION")
    print("-" * 40)
    for arch, n in dist.most_common():
        print(f"  {n:4d}  {arch}")

    # Profile + examples per archetype
    order = ["Primary Creator", "Shot Creator", "Secondary Handler", "Off-Ball Shooter",
             "Slasher / Finisher", "Role / Connector",
             "Post Scorer", "Stretch Big", "Roll & Cut / Rim Big", "Versatile Big"]
    print("\n\nARCHETYPE PROFILES (avg of members) + top examples by usage")
    print("=" * 96)
    for arch in order:
        members = [p for p in players if p["_arch"] == arch]
        if not members:
            continue
        def avg(k):
            xs = [_f(m.get(k)) for m in members if _f(m.get(k)) is not None]
            return statistics.mean(xs) if xs else float("nan")
        print(f"\n{arch}  (n={len(members)})")
        print(f"   usg {avg('usage_pct'):4.1f} | ast% {avg('ast_rate'):4.1f} | 3PArate {avg('tpa_rate'):4.1f} "
              f"| FTrate {avg('ft_rate'):4.1f} | OREB% {avg('oreb_pct'):4.1f} | TS% {avg('ts_pct'):4.1f} "
              f"| 3P% {avg('tpp'):4.1f}")
        top = sorted(members, key=lambda m: -_f(m.get("usage_pct") or 0))[:5]
        for m in top:
            print(f"     - {m['name']:<22} {m['school']:<18} {m.get('pos',''):<5} "
                  f"{m.get('ppg',0):4.1f}ppg {m.get('apg',0):4.1f}apg "
                  f"usg{_f(m.get('usage_pct')):4.0f} 3PAr{_f(m.get('tpa_rate')):3.0f} FTr{_f(m.get('ft_rate')):3.0f}")


if __name__ == "__main__":
    main()
