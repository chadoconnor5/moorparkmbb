"""
Preseason team ratings for a new season: last season's final ratings as every team's starting point.

For each team with a rating last season, writes "<season> Team Statistics/<Conference>/<Team>/":
    team_summary.json       0-0 record, no totals yet
    advanced_analytics.json ORtg / DRtg / net (and tempo) = last season's final numbers,
                            SOS / NCSOS / Opp ORtg / Opp DRtg = 0.0 (they build as games are played)
A team that already has games this season (its advanced_analytics.json has game_ratings) is left alone:
update_advanced_analytics.py owns it from the first game, blending last season's ratings in as decaying
virtual games (PRIOR_CHAIN / prior_weight), so the preseason numbers fade as real games come in.

The schedule is the typed-in one (assemble_schedules.py's "<season> Schedule Screenshots"), in-system games only,
scrimmages left out: scheduled_games counts it.

Usage:
    python3 build_preseason.py                       # DEFAULT_SEASON from last season
    python3 build_preseason.py --season 2026-27 --prior 2025-26
"""

import argparse
import json
from pathlib import Path

from assemble_schedules import canon, is_scrimmage
from ccc_config import CONFERENCES, DEFAULT_SEASON, fields_team

CARRY = ("ortg", "drtg", "net_rtg", "tempo", "possessions")


def prior_season(season):
    y = int(season[:4]) - 1
    return f"{y}-{str(y + 1)[2:]}"


def load_prior(prior):
    out = {}
    for f in Path(f"{prior} Team Statistics").glob("*/*/advanced_analytics.json"):
        t = json.load(open(f)).get("team", {})
        if t.get("ortg") and t.get("drtg"):
            out[f.parent.name] = {k: t.get(k) for k in CARRY}
    return out


def load_schedule(season, team, conf):
    f = Path(f"{season} Schedule Screenshots") / conf / team / "schedule.json"
    if not f.exists():
        return []
    games = []
    for g in json.load(open(f)).get("games", []):
        opp = canon(g.get("opponent"))
        if opp and not is_scrimmage(g["date"]):
            games.append((opp, bool(g.get("is_conference"))))
    return games


def build(season, prior):
    ratings = load_prior(prior)
    base = Path(f"{season} Team Statistics")
    written = kept = 0
    for conf, teams in CONFERENCES.items():
        for team in teams:
            if team not in ratings or not fields_team(team, season):
                continue
            d = base / conf / team
            adv_path = d / "advanced_analytics.json"
            if adv_path.exists() and json.load(open(adv_path)).get("team", {}).get("game_ratings"):
                kept += 1
                continue
            sched = [(o, c) for o, c in load_schedule(season, team, conf) if o in ratings]
            team_block = dict(ratings[team])
            team_block.update({
                # Strength of schedule starts the season at 0.0 and builds as games are played (compute_sos)
                "sos": 0.0, "ncsos": 0.0, "opp_ortg": 0.0, "opp_drtg": 0.0,
                "game_ratings": [],
                "preseason": True,
                "prior_season": prior,
                "scheduled_games": len(sched),
            })
            d.mkdir(parents=True, exist_ok=True)
            json.dump({"team": team_block, "players": [], "formulas": {}, "monthly_stats": {}},
                      open(adv_path, "w"), indent=2)
            json.dump({"team": team, "games_played": 0,
                       "record": {"Overall (.000)": "0-0", "Conference (.000)": "0-0"},
                       "totals": {}, "averages": {}, "opponent_totals": {}, "opponent_averages": {}},
                      open(d / "team_summary.json", "w"), indent=2)
            written += 1
    return written, kept


def main():
    ap = argparse.ArgumentParser(description="Preseason ratings (last season's) + SOS/NCSOS for a new season")
    ap.add_argument("--season", default=DEFAULT_SEASON)
    ap.add_argument("--prior", default=None, help="default: the season before --season")
    a = ap.parse_args()
    prior = a.prior or prior_season(a.season)
    written, kept = build(a.season, prior)
    print(f"{a.season}: preseason ratings from {prior} written for {written} teams; "
          f"{kept} already have games (left to update_advanced_analytics.py)")


if __name__ == "__main__":
    main()
