#!/usr/bin/env python3
"""
Internal-only player role classification for 2025-26.

This script builds position probabilities (PG/SG/SF/PF/C) and a derived role label
using season player box score aggregates from `2025-26 Team Statistics/*/*/player_stats.json`.

It is intentionally decoupled from leaderboard generation.

Optional height integration:
- If a height CSV is provided, probabilities are adjusted via a Bayesian-style
  multiplier using class-conditional normal densities (similar in spirit to
  the Hoop Explorer height addendum).

Usage:
  python3 internal_build_player_roles_2025.py
  python3 internal_build_player_roles_2025.py --height-csv internal_data/roster_heights_2025_26.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev

STATS_ROOT = Path("2025-26 Team Statistics")
OUT_DIR = Path("internal_analysis")

POS_CLASSES = ["PG", "SG", "SF", "PF", "C"]

# High-major-ish means/std from Hoop Explorer addendum (inches), PG..C order.
HEIGHT_MEAN_STD = {
    "PG": (73.57716289697129, 2.5561436676424854),
    "SG": (75.23626157179437, 2.539520215232971),
    "SF": (77.73867983130089, 2.286685273859796),
    "PF": (79.14888834651121, 2.0930557964524996),
    "C": (80.2680159415085, 2.014906878530024),
}


@dataclass
class PlayerRow:
    conference: str
    team: str
    player: str
    games: int
    minutes: int
    fgm: int
    fga: int
    tpm: int
    tpa: int
    ftm: int
    fta: int
    oreb: int
    dreb: int
    reb: int
    ast: int
    stl: int
    blk: int
    tov: int
    pf: int
    pts: int
    fg_pct: float
    tp_pct: float
    ft_pct: float


def safe_div(num: float, den: float, default: float = 0.0) -> float:
    return num / den if den else default


def softmax(scores: dict[str, float]) -> dict[str, float]:
    max_v = max(scores.values())
    exps = {k: math.exp(v - max_v) for k, v in scores.items()}
    denom = sum(exps.values())
    return {k: exps[k] / denom for k in scores}


def parse_height_to_inches(raw: str) -> int | None:
    if not raw:
        return None
    s = raw.strip().lower()

    # Common forms: 6-7, 6'7, 6' 7", 79
    m = re.match(r"^(\d)\s*[-']\s*(\d{1,2})", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))

    m = re.match(r"^(\d{2,3})$", s)
    if m:
        val = int(m.group(1))
        if 60 <= val <= 90:
            return val

    m = re.search(r"(\d)\s*ft\s*(\d{1,2})", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))

    return None


def normalize_player_key(name: str) -> str:
    s = (name or "").strip().lower()
    # Remove leading jersey token like '#12 ' if present.
    s = re.sub(r"^#\d+\s+", "", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = " ".join(s.split())
    return s


def norm_pdf(x: float, mu: float, sigma: float) -> float:
    if sigma <= 0:
        return 0.0
    z = (x - mu) / sigma
    return math.exp(-0.5 * z * z) / (sigma * math.sqrt(2.0 * math.pi))


def load_player_rows(stats_root: Path) -> list[PlayerRow]:
    rows: list[PlayerRow] = []
    for conf_dir in sorted(stats_root.iterdir()):
        if not conf_dir.is_dir():
            continue
        conference = conf_dir.name
        for team_dir in sorted(conf_dir.iterdir()):
            if not team_dir.is_dir():
                continue
            team = team_dir.name
            p_path = team_dir / "player_stats.json"
            if not p_path.exists():
                continue
            data = json.loads(p_path.read_text())
            for p in data.get("players", []):
                t = p.get("totals", {})
                a = p.get("averages", {})
                games = int(t.get("games", 0) or 0)
                minutes = int(t.get("MIN", 0) or 0)
                if games < 5 or minutes <= 0:
                    continue
                rows.append(
                    PlayerRow(
                        conference=conference,
                        team=team,
                        player=str(p.get("name", "")).strip(),
                        games=games,
                        minutes=minutes,
                        fgm=int(t.get("FGM", 0) or 0),
                        fga=int(t.get("FGA", 0) or 0),
                        tpm=int(t.get("3PM", 0) or 0),
                        tpa=int(t.get("3PA", 0) or 0),
                        ftm=int(t.get("FTM", 0) or 0),
                        fta=int(t.get("FTA", 0) or 0),
                        oreb=int(t.get("OREB", 0) or 0),
                        dreb=int(t.get("DREB", 0) or 0),
                        reb=int(t.get("REB", 0) or 0),
                        ast=int(t.get("AST", 0) or 0),
                        stl=int(t.get("STL", 0) or 0),
                        blk=int(t.get("BLK", 0) or 0),
                        tov=int(t.get("TO", 0) or 0),
                        pf=int(t.get("PF", 0) or 0),
                        pts=int(t.get("PTS", 0) or 0),
                        fg_pct=float(a.get("FG%", 0.0) or 0.0),
                        tp_pct=float(a.get("3P%", 0.0) or 0.0),
                        ft_pct=float(a.get("FT%", 0.0) or 0.0),
                    )
                )
    return rows


def load_heights_csv(path: Path | None) -> tuple[dict[tuple[str, str], int], dict[str, int]]:
    if not path or not path.exists():
        return {}, {}
    out: dict[tuple[str, str], int] = {}
    by_name: dict[str, list[int]] = {}
    with path.open(newline="") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            team = str(row.get("team", "")).strip()
            player = str(row.get("player", "")).strip()
            h = parse_height_to_inches(str(row.get("height", "")).strip())
            if team and player and h:
                key_team = team.lower()
                key_name = normalize_player_key(player)
                out[(key_team, key_name)] = h
                by_name.setdefault(key_name, []).append(h)

    # Keep only unique player-name matches for safe fallback.
    unique_name_map = {
        name: vals[0]
        for name, vals in by_name.items()
        if len(set(vals)) == 1
    }
    return out, unique_name_map


def compute_feature_vectors(rows: list[PlayerRow]) -> tuple[list[str], list[dict[str, float]]]:
    feature_names = [
        "ast_per40",
        "tov_per40",
        "ast_tov",
        "three_rate",
        "ft_rate",
        "orb_per40",
        "drb_per40",
        "stl_per40",
        "blk_per40",
        "pts_per40",
        "fg_pct",
        "three_pct",
    ]
    vectors: list[dict[str, float]] = []
    for r in rows:
        min_scale = safe_div(40.0, r.minutes)
        ast_per40 = r.ast * min_scale
        tov_per40 = r.tov * min_scale
        orb_per40 = r.oreb * min_scale
        drb_per40 = r.dreb * min_scale
        stl_per40 = r.stl * min_scale
        blk_per40 = r.blk * min_scale
        pts_per40 = r.pts * min_scale
        v = {
            "ast_per40": ast_per40,
            "tov_per40": tov_per40,
            "ast_tov": safe_div(r.ast, r.tov, default=float(r.ast)),
            "three_rate": safe_div(r.tpa, r.fga),
            "ft_rate": safe_div(r.fta, r.fga),
            "orb_per40": orb_per40,
            "drb_per40": drb_per40,
            "stl_per40": stl_per40,
            "blk_per40": blk_per40,
            "pts_per40": pts_per40,
            "fg_pct": r.fg_pct,
            "three_pct": r.tp_pct,
        }
        vectors.append(v)
    return feature_names, vectors


def zscore_features(feature_names: list[str], vectors: list[dict[str, float]]) -> list[dict[str, float]]:
    means = {f: mean(v[f] for v in vectors) for f in feature_names}
    stds = {f: pstdev(v[f] for v in vectors) for f in feature_names}
    out: list[dict[str, float]] = []
    for v in vectors:
        zv = {}
        for f in feature_names:
            sd = stds[f]
            zv[f] = (v[f] - means[f]) / sd if sd > 1e-9 else 0.0
        out.append(zv)
    return out


def base_position_scores(z: dict[str, float]) -> dict[str, float]:
    # Linear scorecards tuned to create guard-wing-big separation using available data.
    return {
        "PG": (
            1.25 * z["ast_per40"]
            + 0.80 * z["ast_tov"]
            + 0.45 * z["stl_per40"]
            + 0.15 * z["three_rate"]
            + 0.10 * z["three_pct"]
            - 0.55 * z["orb_per40"]
            - 0.70 * z["blk_per40"]
        ),
        "SG": (
            0.85 * z["three_rate"]
            + 0.55 * z["three_pct"]
            + 0.50 * z["pts_per40"]
            + 0.20 * z["stl_per40"]
            + 0.10 * z["ast_per40"]
            - 0.25 * z["orb_per40"]
            - 0.45 * z["blk_per40"]
        ),
        "SF": (
            0.35 * z["three_rate"]
            + 0.30 * z["pts_per40"]
            + 0.35 * z["drb_per40"]
            + 0.25 * z["stl_per40"]
            + 0.20 * z["ast_per40"]
            + 0.15 * z["ft_rate"]
            + 0.10 * z["blk_per40"]
        ),
        "PF": (
            0.85 * z["orb_per40"]
            + 0.95 * z["drb_per40"]
            + 0.40 * z["blk_per40"]
            + 0.35 * z["ft_rate"]
            + 0.20 * z["fg_pct"]
            - 0.35 * z["three_rate"]
            - 0.35 * z["ast_per40"]
        ),
        "C": (
            1.00 * z["orb_per40"]
            + 1.10 * z["drb_per40"]
            + 1.10 * z["blk_per40"]
            + 0.40 * z["fg_pct"]
            + 0.20 * z["ft_rate"]
            - 0.95 * z["three_rate"]
            - 0.50 * z["ast_per40"]
            - 0.15 * z["stl_per40"]
        ),
    }


def apply_height_bayes(base_probs: dict[str, float], height_in: int | None) -> dict[str, float]:
    if height_in is None:
        return base_probs
    weighted = {}
    for pos in POS_CLASSES:
        mu, sd = HEIGHT_MEAN_STD[pos]
        weighted[pos] = base_probs[pos] * norm_pdf(height_in, mu, sd)
    denom = sum(weighted.values())
    if denom <= 0:
        return base_probs
    return {k: v / denom for k, v in weighted.items()}


def classify_role(probs: dict[str, float]) -> str:
    p_pg = probs["PG"]
    p_sg = probs["SG"]
    p_sf = probs["SF"]
    p_pf = probs["PF"]
    p_c = probs["C"]

    top = max(probs, key=probs.get)

    if p_pg >= 0.85:
        return "Pure PG"
    if p_pg >= 0.50:
        return "Scoring PG"

    if top == "SG":
        if p_pg >= (p_sf + p_pf + p_c):
            return "Combo Guard"
        return "Wing Guard"

    if top == "SF":
        if (p_pg + p_sg) >= (p_pf + p_c):
            return "Wing Guard"
        return "Wing Forward"

    if p_c >= 0.85:
        return "Center"

    if top == "PF":
        if p_pf >= 0.85:
            return "PF/C"
        if (p_pg + p_sg + p_sf) >= p_c:
            return "Stretch PF"
        return "PF/C"

    if top == "C":
        return "PF/C"

    return "Wing Forward"


def build_rows(
    rows: list[PlayerRow],
    z_rows: list[dict[str, float]],
    heights_by_team_name: dict[tuple[str, str], int],
    heights_by_unique_name: dict[str, int],
) -> list[dict]:
    output: list[dict] = []
    for r, z in zip(rows, z_rows):
        base_scores = base_position_scores(z)
        base_probs = softmax(base_scores)
        name_key = normalize_player_key(r.player)
        h = heights_by_team_name.get((r.team.lower(), name_key))
        if h is None:
            h = heights_by_unique_name.get(name_key)
        adj_probs = apply_height_bayes(base_probs, h)

        role_no_h = classify_role(base_probs)
        role_h = classify_role(adj_probs)

        output.append(
            {
                "conference": r.conference,
                "team": r.team,
                "player": r.player,
                "games": r.games,
                "minutes": r.minutes,
                "height_in": h,
                "height_str": f"{h // 12}-{h % 12}" if h else None,
                "base_position_probs": {k: round(base_probs[k], 4) for k in POS_CLASSES},
                "height_adj_position_probs": {k: round(adj_probs[k], 4) for k in POS_CLASSES},
                "role_no_height": role_no_h,
                "role_with_height": role_h,
                "role_changed_by_height": role_no_h != role_h if h else False,
                "top_position": max(adj_probs, key=adj_probs.get),
                "features": {
                    "pts_per_game": round(safe_div(r.pts, r.games), 2),
                    "ast_per_game": round(safe_div(r.ast, r.games), 2),
                    "reb_per_game": round(safe_div(r.reb, r.games), 2),
                    "three_rate": round(safe_div(r.tpa, r.fga), 4),
                    "ft_rate": round(safe_div(r.fta, r.fga), 4),
                },
            }
        )

    output.sort(key=lambda x: (x["team"], x["player"]))
    return output


def write_outputs(rows: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "player_role_classification_2025_26.json"
    json_path.write_text(json.dumps(rows, indent=2))

    csv_path = out_dir / "player_role_classification_2025_26.csv"
    with csv_path.open("w", newline="") as f:
        fieldnames = [
            "conference",
            "team",
            "player",
            "games",
            "minutes",
            "height_str",
            "role_no_height",
            "role_with_height",
            "role_changed_by_height",
            "top_position",
            "P_PG",
            "P_SG",
            "P_SF",
            "P_PF",
            "P_C",
            "three_rate",
            "ft_rate",
            "pts_per_game",
            "ast_per_game",
            "reb_per_game",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            p = r["height_adj_position_probs"]
            feat = r["features"]
            w.writerow(
                {
                    "conference": r["conference"],
                    "team": r["team"],
                    "player": r["player"],
                    "games": r["games"],
                    "minutes": r["minutes"],
                    "height_str": r["height_str"] or "",
                    "role_no_height": r["role_no_height"],
                    "role_with_height": r["role_with_height"],
                    "role_changed_by_height": r["role_changed_by_height"],
                    "top_position": r["top_position"],
                    "P_PG": round(p["PG"], 4),
                    "P_SG": round(p["SG"], 4),
                    "P_SF": round(p["SF"], 4),
                    "P_PF": round(p["PF"], 4),
                    "P_C": round(p["C"], 4),
                    "three_rate": feat["three_rate"],
                    "ft_rate": feat["ft_rate"],
                    "pts_per_game": feat["pts_per_game"],
                    "ast_per_game": feat["ast_per_game"],
                    "reb_per_game": feat["reb_per_game"],
                }
            )

    summary = {
        "players": len(rows),
        "with_height": sum(1 for r in rows if r["height_in"] is not None),
        "role_changes_from_height": sum(1 for r in rows if r["role_changed_by_height"]),
    }
    (out_dir / "player_role_classification_2025_26_summary.json").write_text(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Internal player role classification for 2025-26")
    parser.add_argument(
        "--height-csv",
        default="internal_data/roster_heights_2025_26.csv",
        help="CSV with columns: team,player,height (height like 6-7)",
    )
    args = parser.parse_args()

    rows = load_player_rows(STATS_ROOT)
    if not rows:
        raise SystemExit("No players found in 2025-26 Team Statistics")

    heights_by_team_name, heights_by_unique_name = load_heights_csv(Path(args.height_csv))

    feature_names, vectors = compute_feature_vectors(rows)
    z_rows = zscore_features(feature_names, vectors)
    output_rows = build_rows(rows, z_rows, heights_by_team_name, heights_by_unique_name)
    write_outputs(output_rows, OUT_DIR)

    print(f"Wrote internal outputs to {OUT_DIR}")
    print(f"Players classified: {len(output_rows)}")
    print(f"Players with height: {sum(1 for r in output_rows if r['height_in'] is not None)}")


if __name__ == "__main__":
    main()
