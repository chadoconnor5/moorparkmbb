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
The four factors are adjusted the same way against the opponent's opponent-adjusted
factors (update_advanced_analytics.py's adj_ff): a five that out-rebounds a team that has
been a strong rebounding team against good opponents gets credit for it.
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


def load_factors(season):
    """{team: opponent-adjusted four factors} (update_advanced_analytics.py's adj_ff)."""
    out = {}
    for team in uaa.all_stat_teams():
        p = uaa.find_team_stats(team) / "advanced_analytics.json"
        if p.exists():
            f = json.load(open(p)).get("team", {}).get("adj_ff")
            if f:
                out[team] = f
    return out


# A five's factor in one game, adjusted against the opponent's adjusted factor on the
# other side of it, the way update_advanced_analytics adjusts a team's:
#     adj = game value - what the opponent usually does on it + league average
# o = our counts with that five on, d = theirs. Each entry: (key, the opponent's
# factor it is measured against, value(o, d, oT, dT), weight(o, d, oT, dT)).
def _pct(a, b):
    return 100 * a / b if b else None


FF_ADJ = [
    ("efg", "opp_efg_pct", lambda o, d, oT, dT: _pct(o.get("fgm", 0) + 0.5 * o.get("fg3m", 0), o.get("fga", 0)), lambda o, d, oT, dT: o.get("fga", 0)),
    ("tov", "opp_tov_pct", lambda o, d, oT, dT: _pct(o.get("tov", 0), oT), lambda o, d, oT, dT: oT),
    ("orb", "opp_orb_pct", lambda o, d, oT, dT: _pct(o.get("oreb", 0), o.get("oreb", 0) + d.get("dreb", 0)), lambda o, d, oT, dT: o.get("oreb", 0) + d.get("dreb", 0)),
    ("ftr", "opp_ft_rate", lambda o, d, oT, dT: _pct(o.get("fta", 0), o.get("fga", 0)), lambda o, d, oT, dT: o.get("fga", 0)),
    ("oefg", "efg_pct", lambda o, d, oT, dT: _pct(d.get("fgm", 0) + 0.5 * d.get("fg3m", 0), d.get("fga", 0)), lambda o, d, oT, dT: d.get("fga", 0)),
    ("otov", "tov_pct", lambda o, d, oT, dT: _pct(d.get("tov", 0), dT), lambda o, d, oT, dT: dT),
    ("oorb", "oreb_pct", lambda o, d, oT, dT: _pct(d.get("oreb", 0), d.get("oreb", 0) + o.get("dreb", 0)), lambda o, d, oT, dT: d.get("oreb", 0) + o.get("dreb", 0)),
    ("oftr", "ft_rate", lambda o, d, oT, dT: _pct(d.get("fta", 0), d.get("fga", 0)), lambda o, d, oT, dT: d.get("fga", 0)),
]


def _opp_factor(f, k):
    """The opponent's adjusted factor; their OReb% allowed is 100 - their DReb%."""
    return 100 - f["dreb_pct"] if k == "opp_orb_pct" else f.get(k)


QUALITY_MARGIN = 15   # a game decided by more is left out of the quality lines (too much garbage time)


def load_players(season, ratings, team="Moorpark"):
    """Moorpark's player season lines from the season's box scores (the schedules folder), twice:
    "all" games, and "quality" games only - against an in-system opponent with a positive adjusted
    net rating, decided by QUALITY_MARGIN or fewer - so a player's FT% isn't built on blowouts of weak
    teams. Box scores can't see leverage inside a game; that is the closest a box score gets.
    {name: {"all": {...}, "quality": {...}}}, keys games MIN FGM FGA FTM FTA 3PM 3PA OREB DREB AST
    STL BLK TO PF PTS."""
    root = Path(f"{season} Teams Schedules")
    dirs = [d for d in root.glob(f"*/{team}") if d.is_dir()]
    if not dirs:
        return {}
    lg_net = 0.0
    out = {}

    def num(v):
        try:
            return int(str(v).strip() or 0)
        except ValueError:
            return 0

    for f in sorted(dirs[0].glob("*/*.json")):
        try:
            box = json.load(open(f))
        except (OSError, ValueError):
            continue
        teams = box.get("teams") or {}
        mine = next((k for k in teams if k.lower().startswith(team.lower())), None)
        if not mine or not teams.get(mine):
            continue
        opp_label = next((k for k in teams if k != mine), "")
        opp = uaa.resolve_opponent(opp_label)
        r = ratings.get(opp) if opp else None
        sc = box.get("score") or {}
        margin = abs((sc.get(mine) or 0) - (sc.get(opp_label) or 0)) if sc else 99
        quality = r is not None and (r[0] - r[1]) > lg_net and margin <= QUALITY_MARGIN
        for pl in teams[mine]:
            name = re.sub(r"^#\S+\s+", "", pl.get("name") or "").strip()
            st = pl.get("stats") or {}
            if not name or num(st.get("MIN")) <= 0:
                continue
            fg, tp, ft = (str(st.get(k) or "0-0").split("-") for k in ("FGM-A", "3PM-A", "FTM-A"))
            line = {"games": 1, "MIN": num(st.get("MIN")), "FGM": num(fg[0]), "FGA": num(fg[-1]), "3PM": num(tp[0]), "3PA": num(tp[-1]),
                    "FTM": num(ft[0]), "FTA": num(ft[-1]), "OREB": num(st.get("OREB")), "DREB": num(st.get("DREB")), "AST": num(st.get("AST")),
                    "STL": num(st.get("STL")), "BLK": num(st.get("BLK")), "TO": num(st.get("TO")), "PF": num(st.get("PF")), "PTS": num(st.get("PTS"))}
            x = out.setdefault(name, {"all": {}, "quality": {}})
            for scope in ("all", "quality") if quality else ("all",):
                for k, v in line.items():
                    x[scope][k] = x[scope].get(k, 0) + v
    return out


def home_court(site):
    """Moorpark's venue -> (ORtg shift, DRtg shift), as update_advanced_analytics does."""
    h = uaa.HOME_ADVANTAGE / 2
    return {"home": (-h, +h), "away": (+h, -h)}.get((site or "").lower(), (0.0, 0.0))


# Leverage (from the possession tracker, which tags every possession High / Medium / Low and
# clutch, garbage time already out): each five is also adjusted within each bucket, within
# High+Med, and leverage-weighted, where a possession counts by how much it mattered.
LEV_W = {"high": 1.0, "med": 0.6, "low": 0.25}
LEV_SCOPES = ("high", "med", "low", "clutch", "hm", "w")


def _raw():
    return {"oT": 0, "dT": 0, "pf": 0, "pa": 0, "stops": 0, "fouls": 0, "o": {}, "d": {}}


def _acc():
    # q = the same raw counts from games against quality opponents only (positive adjusted net):
    # the situational stats that aren't opponent-adjusted (stop %, steals, fouls, 2P%, 3PA rate) use it.
    return dict(_raw(), q=_raw(), _ao=0.0, _ad=0.0, _aoT=0.0, _adT=0.0, _ff={})


def adjust(data, ratings, ratings_season, factors=None):
    lg_o = sum(o for o, _ in ratings.values()) / len(ratings)
    lg_d = sum(d for _, d in ratings.values()) / len(ratings)
    factors = factors or {}
    lg_f = {k: sum(_opp_factor(f, k) for f in factors.values()) / len(factors)
            for _, k, _, _ in FF_ADJ} if factors else {}

    def add(acc, blk, r, F, hc_o, hc_d, w=1.0):
        """One game's block of possessions (oT, dT, pf, pa, o, d) into acc, weighted by w."""
        quality = r is not None and r[0] - r[1] > 0
        for tgt in (acc, acc["q"]) if quality else (acc,):
            for k in ("oT", "dT", "pf", "pa", "stops", "fouls"):
                tgt[k] += blk.get(k, 0) or 0
            # Raw counts too (3PA, steals, ...): the situational stats that aren't opponent-adjusted.
            for side in ("o", "d"):
                for k, v in (blk.get(side) or {}).items():
                    tgt[side][k] = tgt[side].get(k, 0) + (v or 0)
        if r is None:
            return
        if F:  # four factors, each weighted by its own attempts (FGA, possessions, rebound chances)
            o, d = blk.get("o") or {}, blk.get("d") or {}
            for key, ok, val, wt in FF_ADJ:
                args = (o, d, blk.get("oT", 0), blk.get("dT", 0))
                v, n = val(*args), wt(*args)
                if v is None or not n:
                    continue
                a = acc["_ff"].setdefault(key, [0.0, 0.0])
                # A rate stays a rate: a tiny sample at 0% can't adjust below 0.
                a[0] += min(100.0, max(0.0, v - _opp_factor(F, ok) + lg_f[ok])) * n * w
                a[1] += n * w
        # Possession-weighted: sum (adjusted points per 100) * possessions.
        if blk.get("oT"):
            acc["_ao"] += (100 * blk["pf"] / blk["oT"] + hc_o - r[1] + lg_d) * blk["oT"] * w
            acc["_aoT"] += blk["oT"] * w
        if blk.get("dT"):
            acc["_ad"] += (100 * blk["pa"] / blk["dT"] + hc_d - r[0] + lg_o) * blk["dT"] * w
            acc["_adT"] += blk["dT"] * w

    rnd = lambda v: None if v is None else round(v, 1)

    def finish(acc):
        ao = acc["_ao"] / acc["_aoT"] if acc["_aoT"] else None
        ad = acc["_ad"] / acc["_adT"] if acc["_adT"] else None
        return {"oT": acc["oT"], "dT": acc["dT"], "pf": acc["pf"], "pa": acc["pa"],
                "stops": acc["stops"], "fouls": acc["fouls"], "o": acc["o"], "d": acc["d"], "q": acc["q"],
                "adjPossO": round(acc["_aoT"], 2), "adjPossD": round(acc["_adT"], 2),
                "adjOrtg": rnd(ao), "adjDrtg": rnd(ad), "adjNet": rnd(ao - ad) if ao is not None and ad is not None else None,
                "adjFF": {k: rnd(v[0] / v[1]) for k, v in acc["_ff"].items() if v[1]},
                "adjFFw": {k: round(v[1], 1) for k, v in acc["_ff"].items() if v[1]}}

    games, units, any_lev = [], {}, False
    for g in data.get("games", []):
        opp = None if g.get("scrimmage") else uaa.resolve_opponent(g.get("opponent", ""))
        r = ratings.get(opp) if opp else None
        why = "scrimmage" if g.get("scrimmage") else "not in the CCC system" if not opp else "no ratings" if not r else None
        games.append({"id": g.get("id"), "date": g.get("date"), "opponent": g.get("opponent"), "matched": opp,
                      "adjusted": why is None, "skipped": why,
                      "oppOrtg": r[0] if r else None, "oppDrtg": r[1] if r else None})
        hc_o, hc_d = home_court(g.get("site"))
        F = factors.get(opp) if r else None
        for u in g.get("units", []):
            x = units.setdefault(u["key"], {"key": u["key"], "players": u["players"], "gp": 0, "secs": 0,
                                            "o": {}, "d": {}, "all": _acc(), "lev": {}})
            x["gp"] += 1
            x["secs"] += u.get("secs", 0)
            for side in ("o", "d"):  # four-factor counts: ours (o) and theirs (d) while this five played
                for k, v in (u.get(side) or {}).items():
                    x[side][k] = x[side].get(k, 0) + v
            add(x["all"], u, r, F, hc_o, hc_d)
            lev = u.get("lev") or {}
            if lev:
                any_lev = True
            for b, blk in lev.items():
                add(x["lev"].setdefault(b, _acc()), blk, r, F, hc_o, hc_d)
                if b in ("high", "med"):
                    add(x["lev"].setdefault("hm", _acc()), blk, r, F, hc_o, hc_d)
                if b in LEV_W:
                    add(x["lev"].setdefault("w", _acc()), blk, r, F, hc_o, hc_d, LEV_W[b])
    out_units = []
    for x in units.values():
        A = finish(x["all"])
        o = 100 * A["pf"] / A["oT"] if A["oT"] else None
        d = 100 * A["pa"] / A["dT"] if A["dT"] else None
        poss = {b: x["lev"][b]["oT"] + x["lev"][b]["dT"] for b in ("high", "med", "low") if b in x["lev"]}
        tot = sum(poss.values())
        out_units.append({
            "key": x["key"], "names": [p["name"] for p in x["players"]], "players": x["players"],
            "gp": x["gp"], "secs": x["secs"], "oT": A["oT"], "dT": A["dT"], "pf": A["pf"], "pa": A["pa"],
            "stops": A["stops"], "fouls": A["fouls"], "q": A["q"],
            "o": x["o"], "d": x["d"],
            "ortg": rnd(o), "drtg": rnd(d), "net": rnd(o - d) if o is not None and d is not None else None,
            "adjPossO": A["adjPossO"], "adjPossD": A["adjPossD"],
            "adjOrtg": A["adjOrtg"], "adjDrtg": A["adjDrtg"], "adjNet": A["adjNet"],
            # Opponent-adjusted four factors (ours: efg tov orb ftr; theirs: oefg otov oorb oftr)
            # and the weight behind each, so groups of fives can be combined.
            "adjFF": A["adjFF"], "adjFFw": A["adjFFw"],
            # By leverage: high / med / low / clutch / hm (High+Med) / w (leverage-weighted),
            # and the share of possessions that were High, Medium and Low.
            "lev": {b: finish(x["lev"][b]) for b in LEV_SCOPES if b in x["lev"]},
            "levMix": {b: round(100 * n / tot, 1) for b, n in poss.items()} if tot else {},
        })
    out_units.sort(key=lambda u: -(u["oT"] + u["dT"]))
    return {
        "app": "moorpark-game-tracker", "kind": "lineups-adjusted", "version": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": data.get("exportedAt"), "ratingsSeason": ratings_season,
        "leagueAvg": {"ortg": round(lg_o, 1), "drtg": round(lg_d, 1)}, "homeAdvantage": uaa.HOME_ADVANTAGE,
        "factorsAdjusted": bool(factors), "leverage": any_lev, "levWeights": LEV_W,
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
    factors = load_factors(season)
    if not factors:
        print(f"No adjusted four factors in '{season} Team Statistics' (run update_advanced_analytics.py --all); ratings only.")
    res = adjust(data, ratings, season, factors)
    res["playerSeason"] = load_players(season, ratings)
    res["qualityMargin"] = QUALITY_MARGIN
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
