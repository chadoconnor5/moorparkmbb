"""The typed-in rosters ("<season> Rosters/<Conference>/<Team>/roster.json", from the teams' roster pages).

Published before a season's box scores exist: the leaderboard's Team Stats panel shows them for teams with no
player stats yet, and export_ratings.py writes them to ../poss/rosters.json for the possession tracker.
"""

import json
import re
from pathlib import Path

from ccc_config import DEFAULT_SEASON


def _num_key(n):
    s = str(n)
    return (0, int(s), len(s)) if s.isdigit() else (1, 0, s)


def load(season=DEFAULT_SEASON):
    """{team: [{"num", "name", "pos", "ht", "yr"}, ...]} sorted by number."""
    out = {}
    for f in sorted(Path(f"{season} Rosters").glob("*/*/roster.json")):
        d = json.load(open(f))
        players = d.get("players", []) if isinstance(d, dict) else d
        rows = []
        for p in players:
            num = str(p.get("number") or "").strip()
            name = re.sub(r"\s+", " ", f"{p.get('first') or ''} {p.get('last') or ''}").strip()
            if not num or not name:
                continue
            rows.append({"num": num, "name": name, "pos": p.get("site_position") or "",
                         "ht": p.get("height") or "", "yr": p.get("year") or ""})
        if rows:
            out[f.parent.name] = sorted(rows, key=lambda r: _num_key(r["num"]))
    return out
