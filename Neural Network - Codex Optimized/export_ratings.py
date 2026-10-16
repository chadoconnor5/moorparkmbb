#!/usr/bin/env python3
"""Publish the team ratings the possession tracker adjusts Moorpark's games against.

Writes ../poss/ratings.json next to the possession tracker: every in-system team's current
opponent-adjusted ORtg / DRtg and four factors (advanced_analytics.json, from
update_advanced_analytics.py), games played, the name aliases, the home-court edge, and
Moorpark's player season lines (all games / quality games, from the public box scores).
These are the leaderboard's own public numbers; no tracker or lineup data goes in.

The tracker downloads it when it opens online, keeps a copy for offline gyms, and
re-adjusts every tracked game against it, so a game from November is always graded against
what that opponent turned out to be. Run it after update_advanced_analytics.py --all;
generate_leaderboard.py runs it at the end of every build.

    python3 export_ratings.py
    python3 export_ratings.py --season 2026-27 --out ../poss/ratings.json
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import update_advanced_analytics as uaa
import adjust_lineups as al

OUT = Path(__file__).resolve().parent.parent / "poss" / "ratings.json"


def export(season=None, out=OUT):
    season = season or al.latest_ratings_season()
    if not season:
        print("export_ratings: no '<season> Team Statistics' folder with ratings; skipped.")
        return None
    ratings = al.load_ratings(season)
    if not ratings:
        print(f"export_ratings: no team ratings in '{season} Team Statistics'; skipped.")
        return None
    factors = al.load_factors(season)
    teams = {}
    for team in uaa.all_stat_teams():
        p = uaa.find_team_stats(team) / "advanced_analytics.json"
        if team not in ratings or not p.exists():
            continue
        t = json.load(open(p)).get("team", {})
        o, d = ratings[team]
        f = factors.get(team) or {}
        teams[team] = {"ortg": round(o, 2), "drtg": round(d, 2), "games": len(t.get("game_ratings") or []) or None,
                       "ff": {k: f.get(k) for k in ("efg_pct", "tov_pct", "oreb_pct", "dreb_pct", "ft_rate",
                                                     "opp_efg_pct", "opp_tov_pct", "opp_ft_rate") if f.get(k) is not None}}
    res = {
        "app": "moorpark-possession-tracker", "kind": "team-ratings", "version": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season, "homeAdvantage": uaa.HOME_ADVANTAGE, "qualityMargin": al.QUALITY_MARGIN,
        "aliases": dict(uaa.OPPONENT_ALIASES), "teams": teams, "phase": al.season_phase(),
        "playerSeason": al.load_players(season, ratings),
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out, "w"), separators=(",", ":"))
    print(f"export_ratings: {season}, {len(teams)} teams, {len(res['playerSeason'])} Moorpark players -> {out}")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", help="e.g. 2026-27 (default: newest with ratings)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    export(a.season, a.out)
