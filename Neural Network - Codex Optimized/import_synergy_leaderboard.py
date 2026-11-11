#!/usr/bin/env python3
"""Synergy leaderboard exports (.xlsx, any situation: At Rim, Long 3, Catch and Shoot, All Poss + Assists, Overall
Player Defensive, Transition Team Defensive...) -> internal_data/synergy_leaderboards/<season>/<situation>.json.

Internal only (never published). Synergy needs a login, so these come in by hand when we scout: each export replaces
the earlier one of the same situation and keeps the date it was taken (as_of). The labels lean on them over the
play-by-play (export_ratings: Finisher from At Rim).

Synergy's sheets are per game; counts (Poss, Pts, FG Att...) are stored as season totals (x GP), rates as they are.
Team names are mapped to ours ("Citrus CC" -> Citrus, "West Los Angeles College" -> West LA); unmatched ones are listed.

    python3 import_synergy_leaderboard.py <file.xlsx> [more.xlsx ...] [--as-of 2026-11-11]
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "internal_data" / "synergy_leaderboards"
COUNTS = {"Poss", "Pts", "FG Att", "FG Made", "FG Miss", "2 FG Att", "2 FG Made", "2 FG Miss", "3FG Att", "3 FG Made",
          "3 FG Miss", "Poss+Ast", "Ast"}
# Synergy's school names that don't start with ours once "CC" / "College" / the mascot are dropped
TEAM_FIX = {"west los angeles college": "West LA", "west hills coalinga cc": "Coalinga",
            "city college of san francisco": "San Francisco", "college of the canyons cougars": "Canyons",
            "college of marin mariners": "Marin", "college of marin": "Marin", "los angeles trade-technical college": "LA Trade Tech"}


def _norm(t):
    t = re.sub(r"\(ca\)", " ", t.lower())
    t = t.replace("los angeles", "la").replace("trade-technical", "trade tech").replace("mt.", "mt")
    return re.sub(r"[^a-z0-9 ]+", " ", t).split()


def our_teams():
    for season_dir in sorted(HERE.glob("20*-* Team Statistics"), reverse=True):
        names = sorted({p.name for p in season_dir.glob("*/*") if p.is_dir()})
        if names:
            return names
    return []


def map_team(syn, ours):
    if syn.lower() in TEAM_FIX:
        return TEAM_FIX[syn.lower()]
    s = _norm(syn)
    best = None
    for t in ours:
        n = _norm(t)
        if s[:len(n)] == n and (best is None or len(n) > len(_norm(best))):
            best = t
    return best


def situation(path):
    """('long_3_point_jump_shots__player_offensive', 'Long 3 point jump shots - Player Offensive', '2026-27')"""
    stem = re.sub(r"^[0-9a-f]{8}-", "", Path(path).stem)
    parts = stem.split("_-_")
    m = re.search(r"(\d{4})-(\d{2})(\d{2})", stem)
    season = f"{m.group(1)}-{m.group(3)}" if m else "unknown"
    title = " - ".join(p.replace("_", " ").strip() for p in parts[3:]) or stem
    title = re.sub(r"\s+\d+$", "", re.sub(r"\s+", " ", title))   # "Team Defensive 2" (a second download) -> same situation
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_"), title, season


def load(path, as_of, ours):
    try:
        import openpyxl
    except ImportError:
        sys.exit("needs openpyxl: pip install openpyxl")
    rows = list(openpyxl.load_workbook(path, read_only=True, data_only=True).active.iter_rows(values_only=True))
    head = [str(h).strip() if h is not None else "" for h in rows[0]]
    key, title, season = situation(path)
    out, unmatched = [], set()
    for r in rows[1:]:
        d = dict(zip(head, r))
        if not d.get("Team") or (("Player" in head) and not d.get("Player")):
            continue
        gp = d.get("GP") or 0
        rec = {}
        for h, v in d.items():
            if h in ("", "Rank"):
                continue
            if h in COUNTS and isinstance(v, (int, float)) and gp:
                v = round(v * gp, 1)
                v = int(round(v)) if abs(v - round(v)) < 0.05 else v
            elif isinstance(v, float):
                v = round(v, 4)
            rec[h] = v
        if rec.get("Player"):
            from ccc_config import fix_player_name   # Synergy spells some names as the stats site does (Matthew Wilson)
            rec["Player"] = fix_player_name(str(rec["Player"]).strip())
        rec["Synergy Team"] = d["Team"]
        rec["Team"] = map_team(str(d["Team"]), ours)
        if not rec["Team"]:
            unmatched.add(str(d["Team"]))
        out.append(rec)
    return key, {"situation": title, "season": season, "as_of": as_of, "source": Path(path).name.split("-", 1)[-1],
                 "per_player": "Player" in head, "rows": out}, unmatched


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--as-of", default=dt.date.today().isoformat(), help="the day the export was taken (default today)")
    a = ap.parse_args()
    ours = our_teams()
    for f in a.files:
        key, data, unmatched = load(f, a.as_of, ours)
        d = OUT / data["season"].replace("-", "_")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
        print(f"{data['situation']} ({data['season']}, as of {data['as_of']}): {len(data['rows'])} rows -> {d.name}/{key}.json"
              + (f"; teams not matched (left out of labels): {', '.join(sorted(unmatched))}" if unmatched else ""))


if __name__ == "__main__":
    main()
