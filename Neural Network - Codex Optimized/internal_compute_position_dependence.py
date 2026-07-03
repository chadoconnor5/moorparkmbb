"""
Compute Guard/Forward/Big Dependence for all teams (2025-26).

Outputs: internal_data/position_dependence_2025_26.json

Methodology:
  - Load player_positions_2025_26.csv (p_pg, p_sg, p_sf, p_pf, p_c probabilities)
  - Join to player_stats.json (PTS, AST, REB totals)
  - Weight each player's contribution by position probability
  - Compute share of team PTS/AST/REB coming from guards, wings, and bigs
  - Guard Dependence Index (GDI) = avg(guard_pts_pct, guard_ast_pct)
  - Cross with ORTg, DRTg, net_rtg, win_pct from advanced_analytics + team_summary
"""

import csv
import json
import os
import re

BASE_STATS = "/Users/chadoconnor/Neural Network/2025-26 Team Statistics"
POS_CSV = "/Users/chadoconnor/Neural Network/internal_data/player_positions_2025_26.csv"
OUT_PATH = "/Users/chadoconnor/Neural Network/internal_data/position_dependence_2025_26.json"


def load_positions():
    pos_map = {}
    with open(POS_CSV) as f:
        for row in csv.DictReader(f):
            key = (row["team"].strip(), row["name"].strip())
            p_g = float(row["p_pg"]) + float(row["p_sg"])
            p_f = float(row["p_sf"])
            p_b = float(row["p_pf"]) + float(row["p_c"])
            pos_map[key] = {
                "pos_class": row["pos_class"],
                "p_g": p_g,
                "p_f": p_f,
                "p_b": p_b,
            }
    return pos_map


def parse_win_pct(record_dict):
    """Extract overall win% from team_summary record dict."""
    for key, val in record_dict.items():
        if "Overall" in key:
            m = re.search(r"\(([0-9.]+)\)", key)
            if m:
                return float(m.group(1))
            # fallback: parse W-L
            m2 = re.match(r"(\d+)-(\d+)", val)
            if m2:
                w, l = int(m2.group(1)), int(m2.group(2))
                return w / (w + l) if (w + l) else None
    return None


def get_outcomes(conf_path, team):
    """Compute ortg, drtg, net_rtg, win_pct from raw season_stats."""
    out = {}
    ss_path = os.path.join(conf_path, team, "season_stats.json")
    if not os.path.exists(ss_path):
        return out

    ss = json.load(open(ss_path))
    gp = ss.get("games_played", 0)
    if not gp:
        return out

    rec = ss.get("record", {})
    wp = parse_win_pct(rec)
    if wp is not None:
        out["win_pct"] = round(wp, 3)
    out["gp"] = gp
    for key, val in rec.items():
        if "Overall" in key:
            out["record"] = val
            break

    t = ss.get("team_totals", {})
    o = ss.get("opponent_totals", {})

    def possessions(totals):
        fga = totals.get("FGA", 0)
        oreb = totals.get("OREB", 0)
        tov = totals.get("TO", 0)
        fta = totals.get("FTA", 0)
        return ((fga - oreb) + tov + 0.475 * fta) / gp

    poss = possessions(t)
    if poss > 0:
        ppg = t.get("PTS", 0) / gp
        opp_ppg = o.get("PTS", 0) / gp
        ortg = round(ppg / poss * 100, 1)
        drtg = round(opp_ppg / poss * 100, 1)
        out["ortg"] = ortg
        out["drtg"] = drtg
        out["net_rtg"] = round(ortg - drtg, 1)

    return out


def compute_dependence(players, team, pos_map):
    buckets = {
        "g": {"pts": 0.0, "reb": 0.0, "ast": 0.0},
        "f": {"pts": 0.0, "reb": 0.0, "ast": 0.0},
        "b": {"pts": 0.0, "reb": 0.0, "ast": 0.0},
    }
    totals = {"pts": 0.0, "reb": 0.0, "ast": 0.0}
    unmatched = 0
    matched = 0

    for p in players:
        name = p["name"].strip()
        pts = p["totals"]["PTS"]
        reb = p["totals"]["REB"]
        ast = p["totals"]["AST"]
        totals["pts"] += pts
        totals["reb"] += reb
        totals["ast"] += ast

        key = (team, name)
        pm = pos_map.get(key)
        if pm:
            t = pm["p_g"] + pm["p_f"] + pm["p_b"]
            if t > 0:
                wg, wf, wb = pm["p_g"] / t, pm["p_f"] / t, pm["p_b"] / t
                for stat, val in [("pts", pts), ("reb", reb), ("ast", ast)]:
                    buckets["g"][stat] += val * wg
                    buckets["f"][stat] += val * wf
                    buckets["b"][stat] += val * wb
                matched += 1
                continue
        unmatched += 1

    def pct(x, t):
        return round(x / t * 100, 1) if t else 0.0

    gp = pct(buckets["g"]["pts"], totals["pts"])
    fp = pct(buckets["f"]["pts"], totals["pts"])
    bp = pct(buckets["b"]["pts"], totals["pts"])
    gr = pct(buckets["g"]["reb"], totals["reb"])
    fr = pct(buckets["f"]["reb"], totals["reb"])
    br = pct(buckets["b"]["reb"], totals["reb"])
    ga = pct(buckets["g"]["ast"], totals["ast"])
    fa = pct(buckets["f"]["ast"], totals["ast"])
    ba = pct(buckets["b"]["ast"], totals["ast"])

    gdi = round((gp + ga) / 2, 1)

    return {
        "guard_pts_pct": gp,
        "wing_pts_pct": fp,
        "big_pts_pct": bp,
        "guard_reb_pct": gr,
        "wing_reb_pct": fr,
        "big_reb_pct": br,
        "guard_ast_pct": ga,
        "wing_ast_pct": fa,
        "big_ast_pct": ba,
        "gdi": gdi,
        "matched_players": matched,
        "unmatched_players": unmatched,
    }


def main():
    pos_map = load_positions()
    results = []

    for conf in sorted(os.listdir(BASE_STATS)):
        conf_path = os.path.join(BASE_STATS, conf)
        if not os.path.isdir(conf_path):
            continue
        for team in sorted(os.listdir(conf_path)):
            team_path = os.path.join(conf_path, team)
            if not os.path.isdir(team_path):
                continue
            stats_path = os.path.join(team_path, "player_stats.json")
            if not os.path.exists(stats_path):
                continue

            data = json.load(open(stats_path))
            players = data.get("players", [])
            if not players:
                continue

            dep = compute_dependence(players, team, pos_map)
            outcomes = get_outcomes(conf_path, team)

            entry = {
                "conference": conf,
                "team": team,
                **outcomes,
                **dep,
            }
            results.append(entry)

    # Sort by GDI descending
    results.sort(key=lambda x: x["gdi"], reverse=True)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Wrote {len(results)} teams to {OUT_PATH}")
    print()

    # Summary stats
    gdis = [r["gdi"] for r in results]
    avg_gdi = sum(gdis) / len(gdis)
    print(f"League GDI range: {min(gdis):.1f} – {max(gdis):.1f}, avg {avg_gdi:.1f}")
    print()

    # Correlation: GDI vs win_pct
    pairs_wp = [(r["gdi"], r["win_pct"]) for r in results if "win_pct" in r]
    pairs_ortg = [(r["gdi"], r["ortg"]) for r in results if "ortg" in r]
    pairs_net = [(r["gdi"], r["net_rtg"]) for r in results if "net_rtg" in r]

    def pearson(pairs):
        n = len(pairs)
        if n < 2:
            return None
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        mx, my = sum(xs) / n, sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        denom = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        return round(num / denom, 3) if denom else None

    print(f"Pearson r  GDI vs win_pct:  {pearson(pairs_wp)} (n={len(pairs_wp)})")
    print(f"Pearson r  GDI vs ORTg:     {pearson(pairs_ortg)} (n={len(pairs_ortg)})")
    print(f"Pearson r  GDI vs Net RTG:  {pearson(pairs_net)} (n={len(pairs_net)})")
    print()

    # Quintile breakdown: win% by GDI quintile
    if pairs_wp:
        pairs_wp_sorted = sorted(pairs_wp, key=lambda x: x[0])
        n = len(pairs_wp_sorted)
        q = n // 5
        print("Win% by GDI quintile (low → high guard-dependence):")
        for i in range(5):
            start = i * q
            end = (i + 1) * q if i < 4 else n
            chunk = pairs_wp_sorted[start:end]
            avg_gdi_q = sum(c[0] for c in chunk) / len(chunk)
            avg_wp = sum(c[1] for c in chunk) / len(chunk)
            print(f"  Q{i+1} (GDI {chunk[0][0]:.0f}-{chunk[-1][0]:.0f}, avg {avg_gdi_q:.1f}): win% {avg_wp:.3f}")

    print()
    print("Top 10 most guard-dependent:")
    for r in results[:10]:
        print(f"  {r['team']:<22} {r['conference']:<28} GDI={r['gdi']} win%={r.get('win_pct','?')} ORTg={r.get('ortg','?')}")

    print()
    print("Top 10 most big-dependent (lowest GDI):")
    for r in results[-10:]:
        print(f"  {r['team']:<22} {r['conference']:<28} GDI={r['gdi']} win%={r.get('win_pct','?')} ORTg={r.get('ortg','?')}")


if __name__ == "__main__":
    main()
