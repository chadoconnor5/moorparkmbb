#!/usr/bin/env python3
"""Publish the team ratings the possession tracker adjusts Moorpark's games against.

Writes ../poss/ratings.json next to the possession tracker: every in-system team's current
opponent-adjusted ORtg / DRtg and four factors (advanced_analytics.json, from
update_advanced_analytics.py), games played, the name aliases, the home-court edge, and
Moorpark's player season lines (all games / quality games, from the public box scores).
These are the leaderboard's own public numbers; no tracker or lineup data goes in.

Every in-system team (Moorpark included) also gets its own file, ../poss/teams/<team>.json, listed in
ratings.json under "teamFiles" (with the teams on Moorpark's schedule under "scheduled"):
  team    - its season stats: record, totals and averages for and against (team_summary.json) and the
            season's advanced numbers (advanced_analytics.json, without the per-game lists)
  players - every player: jersey number, box-score season lines (all games / quality games, the same shape
            as Moorpark's playerSeason) and his advanced numbers (eFG%, TS%, usage, ORtg/DRtg, rates...)
The tracker downloads the files for the opponents on its schedule (and keeps them for offline gyms), so an
opponent's five gets the same THIS FIVE labels as ours. Each file is ~5-10 KB.

The tracker downloads it when it opens online, keeps a copy for offline gyms, and
re-adjusts every tracked game against it, so a game from November is always graded against
what that opponent turned out to be. Run it after update_advanced_analytics.py --all;
generate_leaderboard.py runs it at the end of every build.

    python3 export_ratings.py
    python3 export_ratings.py --season 2026-27 --out ../poss/ratings.json
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import update_advanced_analytics as uaa
import adjust_lineups as al

OUT = Path(__file__).resolve().parent.parent / "poss" / "ratings.json"
SLUG = lambda t: re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")


def schedule_opponents(season, team="Moorpark"):
    """The in-system teams on Moorpark's schedule.json for the season (canonical names)."""
    out = []
    for f in Path(f"{season} Teams Schedules").glob(f"*/{team}/schedule.json"):
        try:
            games = json.load(open(f)).get("games") or []
        except (OSError, ValueError):
            continue
        for g in games:
            t = uaa.resolve_opponent(g.get("opponent") or "")
            if t and t != team and t not in out:
                out.append(t)
    return out


def _load(p):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return {}


def team_file(season, ratings, team):
    """One team's season stats and every player's lines, for the tracker."""
    d = uaa.find_team_stats(team)
    adv, summ = _load(d / "advanced_analytics.json"), _load(d / "team_summary.json")
    t_adv = {k: v for k, v in (adv.get("team") or {}).items() if k not in ("game_ratings", "game_ff")}
    players = al.load_players(season, ratings, team=team)
    for p in adv.get("players") or []:
        n = p.get("name")
        if n in players:
            players[n]["adv"] = {k: v for k, v in p.items() if k != "name"}
    return {"team": dict({k: summ.get(k) for k in ("games_played", "record", "totals", "averages", "opponent_totals", "opponent_averages") if summ.get(k) is not None},
                         adv=t_adv), "players": players}


def export_teams(season, ratings, out_dir, generated):
    """../poss/teams/<team>.json for every in-system team. Returns {team: path}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {}
    for t in sorted(ratings):
        body = team_file(season, ratings, t)
        if not body["players"]:
            continue
        f = out_dir / f"{SLUG(t)}.json"
        json.dump(dict({"app": "moorpark-possession-tracker", "kind": "team-file", "version": 1, "name": t, "season": season,
                        "generatedAt": generated, "qualityMargin": al.QUALITY_MARGIN}, **body), open(f, "w"), separators=(",", ":"))
        index[t] = f"{out_dir.name}/{f.name}"
    return index


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
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = Path(out)
    res = {
        "app": "moorpark-possession-tracker", "kind": "team-ratings", "version": 1,
        "generatedAt": generated,
        "season": season, "homeAdvantage": uaa.HOME_ADVANTAGE, "qualityMargin": al.QUALITY_MARGIN,
        "aliases": dict(uaa.OPPONENT_ALIASES), "teams": teams, "phase": al.season_phase(),
        "playerSeason": al.load_players(season, ratings),
        "teamFiles": export_teams(season, ratings, out.parent / "teams", generated),
        "scheduled": schedule_opponents(season),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out, "w"), separators=(",", ":"))
    print(f"export_ratings: {season}, {len(teams)} teams, {len(res['playerSeason'])} Moorpark players, "
          f"{len(res['teamFiles'])} team files ({len(res['scheduled'])} on our schedule) -> {out}")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", help="e.g. 2026-27 (default: newest with ratings)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    export(a.season, a.out)
