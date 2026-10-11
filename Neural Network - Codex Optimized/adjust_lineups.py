#!/usr/bin/env python3
"""Opponent-adjust Moorpark's lineups from the game tracker's lineup file.

The game tracker (game/index.html, Season page -> "Lineup file") exports every finished
game's five-man units with the opponent: possessions, points for/against, four-factor
counts. This script adjusts each unit's game against the leaderboard's team ratings
(advanced_analytics.json team ortg/drtg - already iteratively opponent-adjusted by
update_advanced_analytics.py), the same way that script adjusts a team's game:

    adj ORtg = game ORtg + home-court - opp DRtg + league avg DRtg
    adj DRtg = game DRtg + home-court - opp ORtg + league avg ORtg

then sums each five over the season, weighting each game by that five's possessions.
Opponents outside the CCC system (exhibitions like Mack Attack Prep) and scrimmages stay
in the raw numbers but are left out of the adjusted ones.

Output (default internal_data/moorpark_lineups_adj.json) is the file the tracker's
"Adjusted" button loads. It is Moorpark-internal - don't publish it.

    python3 adjust_lineups.py ~/Downloads/moorpark_lineups_2026-11-20.json
    python3 adjust_lineups.py lineups.json --ratings-season 2025-26 --out somewhere.json
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import update_advanced_analytics as uaa

OUT = Path("internal_data/moorpark_lineups_adj.json")


def latest_ratings_season():
    """Newest '<season> Team Statistics' folder that has team ratings in it."""
    seasons = []
    for d in Path(".").glob("* Team Statistics"):
        m = re.match(r"^(\d{4}-\d{2}) Team Statistics$", d.name)
        if m and any(d.glob("*/*/advanced_analytics.json")):
            seasons.append(m.group(1))
    return max(seasons) if seasons else None


def load_ratings(season):
    """{team: (ortg, drtg)} from every team's advanced_analytics.json for that season."""
    uaa.STATS_DIR = Path(f"{season} Team Statistics")
    uaa._CANONICAL_TEAMS = None
    out = {}
    for team in uaa.all_stat_teams():
        p = uaa.find_team_stats(team) / "advanced_analytics.json"
        if not p.exists():
            continue
        t = json.load(open(p)).get("team", {})
        if t.get("ortg") and t.get("drtg"):
            out[team] = (float(t["ortg"]), float(t["drtg"]))
    return out


def home_court(site):
    """Moorpark's venue -> (ORtg shift, DRtg shift), as update_advanced_analytics does."""
    h = uaa.HOME_ADVANTAGE / 2
    return {"home": (-h, +h), "away": (+h, -h)}.get((site or "").lower(), (0.0, 0.0))


def adjust(data, ratings, ratings_season):
    lg_o = sum(o for o, _ in ratings.values()) / len(ratings)
    lg_d = sum(d for _, d in ratings.values()) / len(ratings)
    games, units = [], {}
    for g in data.get("games", []):
        opp = None if g.get("scrimmage") else uaa.resolve_opponent(g.get("opponent", ""))
        r = ratings.get(opp) if opp else None
        why = "scrimmage" if g.get("scrimmage") else "not in the CCC system" if not opp else "no ratings" if not r else None
        games.append({"id": g.get("id"), "date": g.get("date"), "opponent": g.get("opponent"), "matched": opp,
                      "adjusted": why is None, "skipped": why,
                      "oppOrtg": r[0] if r else None, "oppDrtg": r[1] if r else None})
        hc_o, hc_d = home_court(g.get("site"))
        for u in g.get("units", []):
            x = units.setdefault(u["key"], {"key": u["key"], "players": u["players"], "gp": 0, "secs": 0,
                                            "oT": 0, "dT": 0, "pf": 0, "pa": 0, "o": {}, "d": {},
                                            "_ao": 0.0, "_ad": 0.0, "_aoT": 0, "_adT": 0})
            x["gp"] += 1
            for k in ("secs", "oT", "dT", "pf", "pa"):
                x[k] += u.get(k, 0)
            for side in ("o", "d"):  # four-factor counts: ours (o) and theirs (d) while this five played
                for k, v in (u.get(side) or {}).items():
                    x[side][k] = x[side].get(k, 0) + v
            if r is None:
                continue
            # Possession-weighted: sum (adjusted points per 100) * possessions.
            if u.get("oT"):
                x["_ao"] += (100 * u["pf"] / u["oT"] + hc_o - r[1] + lg_d) * u["oT"]
                x["_aoT"] += u["oT"]
            if u.get("dT"):
                x["_ad"] += (100 * u["pa"] / u["dT"] + hc_d - r[0] + lg_o) * u["dT"]
                x["_adT"] += u["dT"]
    out_units = []
    for x in units.values():
        ao = x["_ao"] / x["_aoT"] if x["_aoT"] else None
        ad = x["_ad"] / x["_adT"] if x["_adT"] else None
        o = 100 * x["pf"] / x["oT"] if x["oT"] else None
        d = 100 * x["pa"] / x["dT"] if x["dT"] else None
        rnd = lambda v: None if v is None else round(v, 1)
        out_units.append({
            "key": x["key"], "names": [p["name"] for p in x["players"]], "players": x["players"],
            "gp": x["gp"], "secs": x["secs"], "oT": x["oT"], "dT": x["dT"], "pf": x["pf"], "pa": x["pa"],
            "o": x["o"], "d": x["d"],
            "ortg": rnd(o), "drtg": rnd(d), "net": rnd(o - d) if o is not None and d is not None else None,
            "adjPossO": x["_aoT"], "adjPossD": x["_adT"],
            "adjOrtg": rnd(ao), "adjDrtg": rnd(ad), "adjNet": rnd(ao - ad) if ao is not None and ad is not None else None,
        })
    out_units.sort(key=lambda u: -(u["oT"] + u["dT"]))
    return {
        "app": "moorpark-game-tracker", "kind": "lineups-adjusted", "version": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": data.get("exportedAt"), "ratingsSeason": ratings_season,
        "leagueAvg": {"ortg": round(lg_o, 1), "drtg": round(lg_d, 1)}, "homeAdvantage": uaa.HOME_ADVANTAGE,
        "gamesTotal": len(games), "gamesAdjusted": sum(g["adjusted"] for g in games),
        "games": games, "units": out_units,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("lineup_file", help="the tracker's Lineup file (moorpark_lineups_<date>.json)")
    ap.add_argument("--ratings-season", help="team ratings to adjust against, e.g. 2026-27 (default: newest available)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    data = json.load(open(a.lineup_file))
    if data.get("kind") != "lineups":
        raise SystemExit("Not a tracker lineup file (expected kind 'lineups').")
    season = a.ratings_season or latest_ratings_season()
    if not season:
        raise SystemExit("No '<season> Team Statistics' folder with advanced_analytics.json found.")
    ratings = load_ratings(season)
    if not ratings:
        raise SystemExit(f"No team ratings in '{season} Team Statistics'.")
    res = adjust(data, ratings, season)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1)
    print(f"Ratings: {season} ({len(ratings)} teams; league avg ORtg {res['leagueAvg']['ortg']}, DRtg {res['leagueAvg']['drtg']})")
    print(f"Games: {res['gamesAdjusted']} of {res['gamesTotal']} adjusted")
    for g in res["games"]:
        if not g["adjusted"]:
            print(f"  skipped {g['date']} {g['opponent']}: {g['skipped']}")
    print(f"Fives: {len(res['units'])} -> {a.out}")


if __name__ == "__main__":
    main()
