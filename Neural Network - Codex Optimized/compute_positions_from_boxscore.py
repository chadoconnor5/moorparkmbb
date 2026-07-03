#!/usr/bin/env python3
"""
Compute position classifications for CCCAA players based on box score stats.

Methodology inspired by:
  https://hoop-explorer.blogspot.com/2020/05/classifying-college-basketball.html

The hoop-explorer method trains an LDA on height-partitioned players, then uses
the LDA confidence scores (softmaxed) plus heuristic rules to assign one of 8
position labels:
  Pure PG, Scoring PG, Combo Guard, Wing Guard, Wing Forward,
  Stretch PF, PF/C, Center

Implementation:
  - Trains sklearn LinearDiscriminantAnalysis on CCCAA players with known heights,
    using height-based class labels (per article methodology).
  - Features: ast_tov, three_relative, pfr, ast_fg, three_rate, oreb_per_game,
    dreb_per_game, blk_per_game, stl_per_game, pf_per_game
  - Height Bayesian adjustment uses the article's CCCAA-tier mean/std values.

Outputs:
  - internal_data/player_positions_2025_26.csv
"""

import csv
import json
import math
from pathlib import Path

import numpy as np
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# The LDA is trained on the only season with height data (2025-26), then that
# frozen model classifies every season's box scores. Prior-season labels are
# box-score-only (same quality as the ~95% of current players who also lack
# height); returning players reuse their 2025-26 height for the Bayesian touch-up.
TRAIN_SEASON = "2025-26"
SEASONS = ["2017-18", "2018-19", "2019-20", "2021-22",
           "2022-23", "2023-24", "2024-25", "2025-26"]
HEIGHTS_CSV = Path("internal_data/roster_heights_2025_26.csv")


def stats_root(season):
    return Path(f"{season} Team Statistics")


def output_csv(season):
    return Path(f"internal_data/player_positions_{season.replace('-', '_')}.csv")

# Minimum thresholds to qualify for classification. Kept low so any player with
# a usable box-score sample gets a position — the LDA leans on per-game
# rebounds/assists/blocks/steals (minutes-independent), not shot volume, so even
# low-FGA players classify reasonably. Below this it's genuinely too little data.
MIN_GAMES = 5
MIN_FGA = 5  # season total

POSITIONS = ["PG", "SG", "SF", "PF", "C"]

# Height thresholds for training labels (CCCAA-appropriate)
# Using midpoints of article's lower_half_mean_std position heights:
#   PG=73.27, SG=74.94, SF=77.43, PF=78.80, C=79.86
HEIGHT_THRESHOLDS = [74.1, 76.2, 78.1, 79.3]  # boundaries between PG/SG, SG/SF, SF/PF, PF/C

def height_to_label(height_in):
    """Assign a 0-4 class label (PG=0 ... C=4) from height in inches."""
    for i, thresh in enumerate(HEIGHT_THRESHOLDS):
        if height_in < thresh:
            return i
    return 4

# ---------------------------------------------------------------------------
# Height Bayesian parameters
# From the hoop-explorer article Height Addendum — lower-half conferences
# (these are more appropriate for CCCAA than the D1 high-major values)
# [mean_inches, std_inches] for [PG, SG, SF, PF, C]
# ---------------------------------------------------------------------------
HEIGHT_PARAMS = [
    [73.27044011081104, 2.597472107779799],    # PG
    [74.94432639101244, 2.572595243009809],    # SG
    [77.43267870969393, 2.2707678341558846],   # SF
    [78.80495520162182, 2.0639141194386132],   # PF
    [79.85597676319935, 2.016183337568703],    # C
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _norm_pdf(x, mu, sigma):
    """Standard normal probability density."""
    z = (x - mu) / sigma
    return math.exp(-0.5 * z * z) / (sigma * math.sqrt(2 * math.pi))


def softmax(scores):
    """Convert raw LDA scores to probabilities via softmax."""
    max_s = max(scores)
    exps = [math.exp(s - max_s) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


def build_height_adj_probs(height_in, lda_probs):
    """
    Bayesian height adjustment from the hoop-explorer article.
    Combines LDA probabilities with P(height | position) assuming
    heights are normally distributed per position class.
    Returns re-normalised probability array.
    """
    height_probs = [
        _norm_pdf(height_in, mu, sigma)
        for mu, sigma in HEIGHT_PARAMS
    ]
    combined = [p * h for p, h in zip(lda_probs, height_probs)]
    total = sum(combined)
    if total == 0:
        return lda_probs
    return [c / total for c in combined]


def classify(probs):
    """
    Apply the hoop-explorer heuristic rules (Table 2) to assign a position label.
    probs = [P(PG), P(SG), P(SF), P(PF), P(C)]
    """
    pg, sg, sf, pf, c = probs
    best = POSITIONS[probs.index(max(probs))]

    # Pure PG
    if pg >= 0.85:
        return "PG"
    # Scoring PG
    if pg >= 0.50:
        return "s-PG"
    # Combo Guard — two ways to get here
    if best == "PG":
        return "CG"
    if best == "SG" and pg >= sf + pf + c:
        return "CG"
    # Wing Guard — two ways
    if best == "SG" and pg < sf + pf + c:
        return "WG"
    if best == "SF" and pg + sg >= pf + c:
        return "WG"
    # Wing Forward
    if best == "SF":
        return "WF"
    # Center
    if c >= 0.85:
        return "C"
    # PF/C (pure PF subsumed here as in the article)
    if pf >= 0.85:
        return "PF/C"
    # Stretch PF
    if best == "PF" and pg + sg + sf >= c:
        return "S-PF"
    # PF/C fallback (PF or C is highest and we haven't hit other rules)
    if best in ("PF", "C"):
        return "PF/C"
    # Should not reach here, but safety net
    return "WF"


# ---------------------------------------------------------------------------
# Feature names — used by both compute_features() and the LDA
# ---------------------------------------------------------------------------
FEATURE_NAMES = [
    "ast_tov",        # AST / TO  (playmaking)
    "three_relative", # 1.5 * 3P% / eFG  (3P quality vs overall shooting)
    "pfr",            # FTA / FGA  (drawing fouls / interior aggression)
    "ast_fg",         # AST / FGM  (pass-first tendency)
    "three_rate",     # 3PA / FGA  (perimeter shooting frequency)
    "oreb_per_game",  # OREB / games  (interior offensive rebounding)
    "dreb_per_game",  # DREB / games  (interior defensive rebounding)
    "blk_per_game",   # BLK / games   (rim protection)
    "stl_per_game",   # STL / games   (perimeter defense)
    "pf_per_game",    # PF / games    (interior physical play)
]

# ---------------------------------------------------------------------------
# Feature computation per player
# ---------------------------------------------------------------------------

def _compute_features_core(totals):
    """Core feature computation shared by both threshold variants."""
    games = totals.get("games", 0)
    fga   = totals.get("FGA", 0)
    fgm   = totals.get("FGM", 0)
    tpa   = totals.get("3PA", 0)
    tpm   = totals.get("3PM", 0)
    fta   = totals.get("FTA", 0)
    oreb  = totals.get("OREB", 0)
    dreb  = totals.get("DREB", 0)
    ast   = totals.get("AST", 0)
    to    = totals.get("TO", 0)
    stl   = totals.get("STL", 0)
    blk   = totals.get("BLK", 0)
    pf    = totals.get("PF", 0)

    safe_fga   = max(fga, 1)
    safe_fgm   = max(fgm, 1)
    safe_to    = max(to, 0.5)
    safe_games = max(games, 1)

    efg = (fgm + 0.5 * tpm) / safe_fga
    if tpa > 0 and efg > 0:
        three_pct = tpm / tpa
        three_relative = 1.5 * three_pct / efg
    else:
        three_relative = 0.0

    return {
        "ast_tov":        ast / safe_to,
        "three_relative": three_relative,
        "pfr":            fta / safe_fga,
        "ast_fg":         ast / safe_fgm,
        "three_rate":     tpa / safe_fga,
        "oreb_per_game":  oreb / safe_games,
        "dreb_per_game":  dreb / safe_games,
        "blk_per_game":   blk / safe_games,
        "stl_per_game":   stl / safe_games,
        "pf_per_game":    pf / safe_games,
    }


def compute_features(totals):
    """Features for qualifying players (MIN_GAMES, MIN_FGA thresholds)."""
    if totals.get("games", 0) < MIN_GAMES or totals.get("FGA", 0) < MIN_FGA:
        return None
    return _compute_features_core(totals)


def compute_features_relaxed(totals):
    """Features for training-data players (relaxed: 3 games, 10 FGA)."""
    if totals.get("games", 0) < 3 or totals.get("FGA", 0) < 10:
        return None
    return _compute_features_core(totals)


# ---------------------------------------------------------------------------
# Load all players
# ---------------------------------------------------------------------------

def load_all_players(season):
    """
    Walk a season's Team Statistics and collect all players with stats.
    Returns list of dicts: {team, conference, name, totals}
    """
    players = []
    for stat_file in sorted(stats_root(season).rglob("player_stats.json")):
        team_dir = stat_file.parent
        conf_dir = team_dir.parent
        team = team_dir.name
        conference = conf_dir.name

        data = json.loads(stat_file.read_text())
        for p in data.get("players", []):
            players.append({
                "team": team,
                "conference": conference,
                "name": p["name"],
                "totals": p.get("totals", {}),
            })

    return players


def load_heights():
    """
    Load height CSV. Returns dict keyed by (team, player_name) -> height_inches.
    """
    heights = {}
    if not HEIGHTS_CSV.exists():
        return heights
    with open(HEIGHTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            team = row["team"].strip()
            player = row["player"].strip()
            try:
                ht = int(row["height"])
            except (ValueError, KeyError):
                continue
            heights[(team, player)] = ht
    return heights


def lookup_height(heights, team, name):
    """
    Look up height for a player. Tries exact match first, then last-name match.
    Returns height in inches or None.
    """
    if (team, name) in heights:
        return heights[(team, name)]
    # Last-name fallback
    last = name.split()[-1].lower() if name.split() else ""
    if last:
        for (t, p), h in heights.items():
            if t == team and p.split()[-1].lower() == last:
                return h
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def reorder_probs(proba_row, lda):
    """Return [P(PG), P(SG), P(SF), P(PF), P(C)] regardless of lda.classes_ order."""
    result = [0.0] * 5
    for j, cls in enumerate(lda.classes_):
        result[cls] = proba_row[j]
    return result


def train_model(heights):
    """Train scaler + LDA on the season that has height data (TRAIN_SEASON).

    Height labels the training classes; the resulting box-score model is then
    applied to every season. Returns (scaler, lda).
    """
    from collections import Counter
    all_players = load_all_players(TRAIN_SEASON)

    # Any height-matched player (relaxed volume thresholds) becomes a training
    # example, labeled 0-4 (PG..C) by height.
    train_X, train_y = [], []
    for p in all_players:
        ht = lookup_height(heights, p["team"], p["name"])
        if ht is None:
            continue
        feat = compute_features_relaxed(p["totals"])
        if feat is None:
            continue
        train_X.append([feat[fn] for fn in FEATURE_NAMES])
        train_y.append(height_to_label(ht))

    class_counts = Counter(train_y)
    print(f"Training LDA on {TRAIN_SEASON}: {len(train_y)} height-labeled samples")
    print("  class distribution: " +
          ", ".join(f"{POSITIONS[k]}={v}" for k, v in sorted(class_counts.items())))
    min_per_class = min(class_counts.values()) if class_counts else 0
    if len(class_counts) < 5 or min_per_class < 5:
        print("  WARNING: Too few training samples — LDA may be unreliable")

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(np.array(train_X))
    uniform_priors = np.ones(5) / 5  # prevent class imbalance from biasing
    lda = LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto",
                                     priors=uniform_priors)
    lda.fit(X_train_scaled, train_y)
    print(f"  LDA trained (classes: {[POSITIONS[i] for i in lda.classes_]})")
    return scaler, lda


def classify_season(season, scaler, lda, heights):
    """Apply the frozen model to one season's box scores; write its CSV."""
    from collections import Counter
    all_players = load_all_players(season)
    qualifying = []
    for p in all_players:
        feat = compute_features(p["totals"])
        if feat is not None:
            qualifying.append({**p, "features": feat})
    if not qualifying:
        print(f"{season}: no qualifying players, skipping")
        return

    X_all = np.array([[p["features"][fn] for fn in FEATURE_NAMES] for p in qualifying])
    raw_posteriors = lda.predict_proba(scaler.transform(X_all))

    results = []
    for i, player in enumerate(qualifying):
        lda_probs = reorder_probs(raw_posteriors[i], lda)
        pos_no_ht = classify(lda_probs)
        # Returning players reuse their (season-independent) height for the touch-up.
        height = lookup_height(heights, player["team"], player["name"])
        adj_probs = build_height_adj_probs(height, lda_probs) if height is not None else lda_probs
        pos_class = classify(adj_probs)
        results.append({
            "conference": player["conference"],
            "team":       player["team"],
            "name":       player["name"],
            "games":      player["totals"].get("games", 0),
            "pos_class":  pos_class,
            "pos_no_ht":  pos_no_ht,
            "height":     height if height is not None else "",
            "p_pg":       round(adj_probs[0] * 100, 1),
            "p_sg":       round(adj_probs[1] * 100, 1),
            "p_sf":       round(adj_probs[2] * 100, 1),
            "p_pf":       round(adj_probs[3] * 100, 1),
            "p_c":        round(adj_probs[4] * 100, 1),
        })

    results.sort(key=lambda r: (r["conference"], r["team"], r["name"]))
    out = output_csv(season)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["conference", "team", "name", "games", "pos_class", "pos_no_ht",
                  "height", "p_pg", "p_sg", "p_sf", "p_pf", "p_c"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    dist = Counter(r["pos_class"] for r in results)
    order = ["PG", "s-PG", "CG", "WG", "WF", "S-PF", "PF/C", "C"]
    summary = "  ".join(f"{pos}={dist.get(pos, 0)}" for pos in order)
    n_ht = sum(1 for r in results if r["height"] != "")
    print(f"{season}: wrote {len(results)} players ({n_ht} w/ height) -> {out.name}")
    print(f"   {summary}")


def main():
    heights = load_heights()
    print(f"Height records loaded: {len(heights)}\n")
    scaler, lda = train_model(heights)
    print()
    for season in SEASONS:
        classify_season(season, scaler, lda, heights)



if __name__ == "__main__":
    main()
