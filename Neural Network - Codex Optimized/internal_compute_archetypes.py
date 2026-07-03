"""
internal_compute_archetypes.py
Classify every CCCAA player (2025-26) into a Synergy-style offensive archetype.

Archetypes (11 total, matching Synergy categories):
  GUARD TIER:
    Playmaking BH   — high AST; on-ball scorer who also creates for teammates
    Secondary BH    — on-ball scorer with spot-up / catch-and-shoot element (high 3PAr)
    Scoring BH      — on-ball scorer with very little spot-up / catch-and-shoot (low 3PAr)

  WING TIER:
    Playmaking Wing — sets up teammates more than most other wings (high AST)
    Slashing Wing   — drives to the basket; high FTAr, low 3PAr
    Spot-up Wing    — predominantly catch-and-shoot; very high 3PAr
    Dynamic Wing    — off-ball screens, handoffs, dribble jumpers (moderate 3PAr, varied attack)

  BIG TIER:
    Playmaking Big  — passes out of the high/low post; high AST for a big
    Post-up Big     — scores / passes from the post; very high FTAr, near-zero 3PAr
    Stretch Big     — pop-and-shoot; high 3PAr for a big
    Rim-finishing   — rolls, cuts, offensive rebounds; low 3PAr, moderate-high OREB%

Position tier:  derived from position probability weights (p_pg/p_sg/p_sf/p_pf/p_c)
Min games: 8  Min MPG: 8  (lower samples are labelled "—")
"""

import csv
import json
import os

BASE      = "/Users/chadoconnor/Neural Network"
POS_CSV   = f"{BASE}/internal_data/player_positions_2025_26.csv"
STATS_DIR = f"{BASE}/2025-26 Team Statistics"
OUT_PATH  = f"{BASE}/internal_data/player_archetypes_2025_26.json"

MIN_GAMES = 8
MIN_MPG   = 8.0

# ─── Tier thresholds ──────────────────────────────────────────────────────────
# Guard tier
G_AST_PLAYMAKER   = 3.5   # AST/g → Playmaking BH  (P&R excellence + distribution)
G_3PAR_SECONDARY  = 45.0  # 3PAr% → Secondary BH   (spot-up element; no-dribble jumpers + creation)
G_FTAR_SCORING    = 30.0  # FTAr% floor for Scoring BH  (drive/contact first, little spot-up)
# Guards below both thresholds → Scoring BH (low spot-up, low drive/foul → balanced mid-range)
# Note: Post-Up activity for guards appears in FTAr but is NOT separated from P&R fouls
#       We fold post-active guards into "Scoring BH" if 3PAr is low

# Wing tier
W_AST_PLAYMAKER   = 2.5   # AST/g → Playmaking Wing
W_FTAR_SLASH      = 28.0  # FTAr% minimum for Slashing Wing
W_3PAR_SLASH_MAX  = 30.0  # 3PAr% ceiling for Slashing Wing
W_3PAR_SPOTUP     = 55.0  # 3PAr% → Spot-up Wing
W_3PAR_DYNAMIC    = 22.0  # 3PAr% floor for Dynamic Wing (off-ball + pull-ups)
# (below → Slashing Wing default)

# Big tier
B_AST_PLAYMAKER   = 2.0   # AST/g → Playmaking Big
B_3PAR_STRETCH    = 18.0  # 3PAr% → Stretch Big  (pop + catch-and-shoot)
B_FTAR_POST       = 40.0  # FTAr% floor for Post-up Big (back-to-basket contact)
B_3PAR_POST_MAX   = 12.0  # 3PAr% ceiling for Post-up Big
# (else → Rim-finishing Big)


def load_positions():
    pos_map = {}
    with open(POS_CSV) as f:
        for row in csv.DictReader(f):
            p_g = float(row["p_pg"]) + float(row["p_sg"])
            p_f = float(row["p_sf"])
            p_b = float(row["p_pf"]) + float(row["p_c"])
            pos_map[(row["team"].strip(), row["name"].strip())] = {
                "pos_class": row["pos_class"],
                "p_g": p_g, "p_f": p_f, "p_b": p_b,
            }
    return pos_map


def position_tier(pm, three_par=None, ftar=None):
    """Return 'guard', 'wing', or 'big' based on position probabilities + stat overrides."""
    pos_class = pm.get("pos_class", "")
    g, f, b = pm["p_g"], pm["p_f"], pm["p_b"]
    total = g + f + b
    if total == 0:
        return "guard"
    wg, wf, wb = g / total, f / total, b / total

    # Hard anchors: PG / s-PG are always guards; PF/C/S-PF are always bigs
    if pos_class in ("PG", "s-PG"):
        return "guard"
    if pos_class in ("PF", "PF/C", "C", "S-PF"):
        return "big"

    # WG and WF: use stats to resolve ambiguity
    # A WG/WF playing with very low 3PAr + high FTAr is a wing, not a guard
    if pos_class in ("WG", "WF", "SF"):
        if three_par is not None and ftar is not None:
            if three_par < 22 and ftar >= 22:
                return "wing"   # drives/slashes like a wing, not a guard
        # Default: use probability weights
        if wb >= 0.38:
            return "big"
        if wf >= wg:
            return "wing"
        # Borderline WG — treat as wing to get wing archetypes
        return "wing"

    # CG (combo guard): probabilities decide
    if wb >= 0.38:
        return "big"
    if wg >= wf and wg >= wb:
        return "guard"
    return "wing"


def classify(tier, ast_pg, three_par, ftar, oreb_pct):
    """Return (archetype_label, short_label)."""

    if tier == "guard":
        if ast_pg >= G_AST_PLAYMAKER:
            return "Playmaking Ball Handler", "Playmaking BH"
        if three_par >= G_3PAR_SECONDARY:
            return "Secondary Ball Handler", "Secondary BH"
        return "Scoring Ball Handler", "Scoring BH"

    if tier == "wing":
        if ast_pg >= W_AST_PLAYMAKER:
            return "Playmaking Wing", "Playmaking Wing"
        if ftar >= W_FTAR_SLASH and three_par < W_3PAR_SLASH_MAX:
            return "Slashing Wing", "Slashing Wing"
        if three_par >= W_3PAR_SPOTUP:
            return "Spot-up Wing", "Spot-up Wing"
        if three_par >= W_3PAR_DYNAMIC:
            return "Dynamic Shooting Wing", "Dynamic Wing"
        # Default: drives/slashes
        return "Slashing Wing", "Slashing Wing"

    # tier == "big"
    if ast_pg >= B_AST_PLAYMAKER:
        return "Playmaking Big", "Playmaking Big"
    if three_par >= B_3PAR_STRETCH:
        return "Stretch Big", "Stretch Big"
    if ftar >= B_FTAR_POST and three_par < B_3PAR_POST_MAX:
        return "Post-up Big", "Post-up Big"
    return "Rim-finishing Big", "Rim-finishing Big"


def main():
    pos_map = load_positions()
    results = []

    for conf in sorted(os.listdir(STATS_DIR)):
        conf_path = os.path.join(STATS_DIR, conf)
        if not os.path.isdir(conf_path):
            continue
        for team in sorted(os.listdir(conf_path)):
            team_path  = os.path.join(conf_path, team)
            stats_path = os.path.join(team_path, "player_stats.json")
            adv_path   = os.path.join(team_path, "advanced_analytics.json")
            if not os.path.exists(stats_path):
                continue

            ps_data  = json.load(open(stats_path))
            adv_data = json.load(open(adv_path)) if os.path.exists(adv_path) else {}
            adv_map  = {p["name"]: p for p in adv_data.get("players", [])}

            for p in ps_data.get("players", []):
                name = p["name"].strip()
                avg  = p["averages"]
                tot  = p["totals"]
                adv  = adv_map.get(name, {})

                gp  = avg.get("games", 0)
                mpg = avg.get("MIN", 0)

                if gp < MIN_GAMES or mpg < MIN_MPG:
                    archetype, short = "—", "—"
                    tier = "—"
                else:
                    fga = tot.get("FGA", 1) or 1
                    three_par = tot.get("3PA", 0) / fga * 100
                    ftar      = adv.get("ft_rate", 0)
                    ast_pg    = avg.get("AST", 0)
                    oreb_pct  = adv.get("oreb_pct", 0)

                    pm = pos_map.get((team, name))
                    if pm:
                        tier = position_tier(pm, three_par=three_par, ftar=ftar)
                        pos_class = pm["pos_class"]
                    else:
                        # Fallback: infer from 3PAr + FTAr heuristics
                        tier = "guard" if three_par >= 40 else ("big" if oreb_pct >= 12 else "wing")
                        pos_class = "?"

                    archetype, short = classify(tier, ast_pg, three_par, ftar, oreb_pct)

                results.append({
                    "conference": conf,
                    "team":       team,
                    "name":       name,
                    "pos_class":  pos_map.get((team, name), {}).get("pos_class", "?"),
                    "tier":       tier,
                    "archetype":  archetype,
                    "short":      short,
                    "gp":         gp,
                    "mpg":        round(mpg, 1),
                    "ppg":        avg.get("PTS", 0),
                    "ast_pg":     avg.get("AST", 0),
                    "reb_pg":     avg.get("REB", 0),
                    "three_par":  round(tot.get("3PA", 0) / (tot.get("FGA", 1) or 1) * 100, 1),
                    "ftar":       round(adv.get("ft_rate", 0), 1),
                    "oreb_pct":   round(adv.get("oreb_pct", 0), 1),
                    "fg_pct":     avg.get("FG%", 0),
                    "three_p_pct": avg.get("3P%", 0),
                })

    # Save
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {len(results)} players → {OUT_PATH}")
    print(f"  Classified: {sum(1 for r in results if r['archetype'] != '—')}")
    print()

    # Distribution
    from collections import Counter
    counts = Counter(r["archetype"] for r in results if r["archetype"] != "—")
    print("Archetype distribution (league-wide):")
    for arch, cnt in counts.most_common():
        print(f"  {arch:<28} {cnt:>4}")
    print()

    # WSC North Moorpark players
    print("Moorpark players:")
    mp = [r for r in results if r["team"] == "Moorpark" and r["archetype"] != "—"]
    mp.sort(key=lambda x: x["mpg"], reverse=True)
    for r in mp:
        print(f"  {r['name']:<22} {r['pos_class']:>6}  {r['tier']:>5}  {r['short']:<24}"
              f"  {r['ppg']:>5.1f}ppg  {r['ast_pg']:>4.1f}ast  3PAr:{r['three_par']:>4.0f}%  FTAr:{r['ftar']:>4.0f}%")


if __name__ == "__main__":
    main()
