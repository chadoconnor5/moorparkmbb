"""
Partial schedules for every team from the schedules we already have (typed in from CCCMBCA screenshots).

Every game a team lists is also its opponent's game, so each schedule.json in
"<season> Schedule Screenshots/<Conference>/<Team>/" adds that game, mirrored (home <-> away, neutral stays
neutral), to the opponent. For a team with no schedule of its own yet this writes
    <season> Schedule Screenshots/<Conference>/<Team>/schedule_from_opponents.json
(same game format as scrape_team.py's schedule.json, each game with "from": the team(s) whose page listed it; a page's
"other_games" - matchups between two other teams named in its notes, like its tournament's - count too), so
those schedules fill in before anyone screenshots them. For a team that HAS its own schedule, its opponents' pages
are checked against it (a game only one side lists, or a different time / home-away), and that goes in the report:
    <season> Schedule Screenshots/assembled_schedules_report.txt

Games before Oct 29 are scrimmages and left out. Only games against teams in ccc_config.CONFERENCES are used (TBA, tournament placeholders, out-of-state and
four-year opponents are left out). Safe to re-run: every derived file is rebuilt from the typed-in ones.

Usage:
    python3 assemble_schedules.py                  # DEFAULT_SEASON
    python3 assemble_schedules.py --season 2026-27
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ccc_config import CONFERENCES, DEFAULT_SEASON, get_conference

CANON = {t.lower(): t for teams in CONFERENCES.values() for t in teams}
MONTHS = ["Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"]
FLIP = {"home": "away", "away": "home", "neutral": "neutral"}


def canon(name):
    return CANON.get(str(name or "").strip().lower())


def order(g):
    """Season order of a 'Nov 05' date."""
    m, _, d = g["date"].partition(" ")
    return (MONTHS.index(m) if m in MONTHS else 99, int(d) if d.isdigit() else 0)


def is_scrimmage(d):
    """Games before Oct 29 (the season's first regular-season date) are scrimmages / jamborees."""
    m, _, day = d.partition(" ")
    return m in ("Jul", "Aug", "Sep") or (m == "Oct" and day.isdigit() and int(day) < 29)


def mirror(team, g):
    ha = FLIP.get(g.get("home_away", ""), "")
    return {"date": g["date"], "opponent": team, "home_away": ha, "location_tag": "at" if ha == "away" else "vs",
            "result": "", "status": g.get("status", ""), "time": g.get("time", ""), "notes": g.get("notes", ""),
            "is_conference": bool(g.get("is_conference")), "boxscore_url": "", "video_url": "", "has_boxscore": False,
            "from": [team]}


def assemble(season, root=Path(".")):
    base = root / f"{season} Schedule Screenshots"
    own = {}
    for f in sorted(base.glob("*/*/schedule.json")):
        d = json.load(open(f))
        own[canon(d.get("team_name")) or d.get("team_name")] = d
    derived = defaultdict(dict)     # team -> {(date, opponent): game}
    issues = []
    for team, d in own.items():
        for g in d.get("games", []):
            if is_scrimmage(g["date"]):
                continue
            opp = canon(g.get("opponent"))
            if not opp:
                continue
            if opp in own:   # both typed in: check they agree
                m = [x for x in own[opp]["games"] if canon(x.get("opponent")) == team and x["date"] == g["date"]]
                if not m:
                    issues.append(f"{team} lists {g['date']} {g['location_tag']} {opp}; {opp}'s page doesn't")
                elif team < opp:   # each pair once
                    x = m[0]
                    if g.get("time") and x.get("time") and g["time"] != x["time"]:
                        issues.append(f"{g['date']} {team} vs {opp}: time {g['time']} vs {x['time']}")
                    if FLIP.get(g.get("home_away")) != x.get("home_away"):
                        issues.append(f"{g['date']} {team} vs {opp}: {team} says {g.get('home_away')}, {opp} says {x.get('home_away')}")
                continue
            k = (g["date"], team)
            if k in derived[opp]:
                derived[opp][k]["from"].append(team)
            else:
                derived[opp][k] = mirror(team, g)
        # Other teams' games a page names (e.g. its tournament's other matchups): both teams get it, neutral site.
        for o in d.get("other_games", []):
            a, b = (canon(t) for t in o["teams"])
            for t, u in ((a, b), (b, a)):
                if t and u and t not in own and (o["date"], u) not in derived[t]:
                    derived[t][(o["date"], u)] = mirror(u, {"date": o["date"], "home_away": "neutral", "time": o.get("time", ""),
                                                            "status": o.get("time", ""), "notes": o.get("notes", "")})
                    derived[t][(o["date"], u)]["from"] = [team]
    written = []
    for team, games in sorted(derived.items()):
        G = sorted(games.values(), key=order)
        d = base / get_conference(team) / team
        d.mkdir(parents=True, exist_ok=True)
        json.dump({"team_name": team, "season": season, "partial": True,
                   "source": "assembled from the schedules of the teams it plays (assemble_schedules.py); "
                             "only games against those teams, until its own page is typed in",
                   "from_teams": sorted({t for g in G for t in g["from"]}),
                   "last_updated": datetime.now().isoformat(timespec="seconds"), "games": G},
                  open(d / "schedule_from_opponents.json", "w"), indent=2)
        written.append((team, len(G)))
    # Drop stale derived files for teams that now have their own schedule.
    for f in base.glob("*/*/schedule_from_opponents.json"):
        if f.parent.name in own:
            f.unlink()
    all_teams = sorted(t for L in CONFERENCES.values() for t in L)
    have = dict(written)
    L = [f"ASSEMBLED SCHEDULES {season}  ({datetime.now().isoformat(timespec='seconds')})", "",
         f"Own schedule typed in: {len(own)} teams ({', '.join(sorted(own))})",
         f"Partial schedule from opponents: {len(written)} teams", f"Nothing yet: {len([t for t in all_teams if t not in own and t not in have])} teams", ""]
    for conf, teams in CONFERENCES.items():
        L.append(conf)
        for t in teams:
            L.append(f"  {t:<24}" + (f"own schedule ({len(own[t]['games'])} games)" if t in own else
                                       f"{have[t]} games from opponents" if t in have else "—"))
    L += ["", f"Checks between typed-in teams: {len(issues)} issue(s)"] + [f"  {i}" for i in issues]
    (base / "assembled_schedules_report.txt").write_text("\n".join(L) + "\n")
    return own, written, issues


def main():
    ap = argparse.ArgumentParser(description="Partial schedules for every team from the typed-in schedules")
    ap.add_argument("--season", default=DEFAULT_SEASON)
    a = ap.parse_args()
    own, written, issues = assemble(a.season)
    print(f"{len(own)} typed-in schedules -> partial schedules for {len(written)} teams; {len(issues)} issue(s). "
          f"Report: {a.season} Schedule Screenshots/assembled_schedules_report.txt")


if __name__ == "__main__":
    main()
