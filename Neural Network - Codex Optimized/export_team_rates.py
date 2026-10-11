#!/usr/bin/env python3
"""Write every team's season rates for the game tracker's Huddle ("season" column).

Reads <season> Team Statistics/*/<team>/season_stats.json (raw box totals, the scrape's
own output) and writes ../game/team_rates.json:

    {"season": "2026-27", "generatedAt": ..., "teams": {"Ventura": {"gp": 12, "ppp": 1.08,
      "tpar": 34.7, "ftr": 38.3, "orebPct": 37.2, "tovPct": 18.8, "astPct": 47.6}, ...}}

The same definitions the tracker uses for a game: points per possession (possessions =
FGA - OREB + TO + 0.475 FTA), 3PA / FGA, FTA / FGA, OREB / (OREB + opponent DREB),
TO / possessions, AST / FGM. Raw, not opponent-adjusted - they sit beside tonight's raw
numbers. The tracker only shows them for the game's own season and once a team has
played 3 games, so last season's file is never shown as this season.

scrape.py runs this after each rebuild; by hand:
    python3 export_team_rates.py --season 2026-27
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ccc_config import DEFAULT_SEASON

OUT = Path(__file__).resolve().parent.parent / "game" / "team_rates.json"


def rates(tt, ot):
    fga, fgm, oreb, tov, fta = tt.get("FGA", 0), tt.get("FGM", 0), tt.get("OREB", 0), tt.get("TO", 0), tt.get("FTA", 0)
    poss = fga - oreb + tov + 0.475 * fta
    pct = lambda n, d: round(100 * n / d, 1) if d else None
    return {
        "ppp": round(tt.get("PTS", 0) / poss, 3) if poss else None,
        "tpar": pct(tt.get("3PA", 0), fga),
        "ftr": pct(fta, fga),
        "orebPct": pct(oreb, oreb + ot.get("DREB", 0)),
        "tovPct": pct(tov, poss),
        "astPct": pct(tt.get("AST", 0), fgm),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", default=DEFAULT_SEASON)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    stats = Path(f"{a.season} Team Statistics")
    teams = {}
    for p in sorted(stats.glob("*/*/season_stats.json")):
        s = json.load(open(p))
        tt, ot = s.get("team_totals") or {}, s.get("opponent_totals") or {}
        if not tt.get("FGA"):
            continue
        teams[p.parent.name] = dict(gp=s.get("games_played") or tt.get("games") or 0, **rates(tt, ot))
    out = {"season": a.season, "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "teams": teams}
    Path(a.out).write_text(json.dumps(out, separators=(",", ":")))
    print(f"Team rates: {len(teams)} teams ({a.season}) -> {a.out}")


if __name__ == "__main__":
    main()
