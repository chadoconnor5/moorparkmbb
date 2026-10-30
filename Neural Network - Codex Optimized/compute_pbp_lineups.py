#!/usr/bin/env python3
"""Every team's lineups from the play-by-play ("<season> Play by Play/", saved by scrape.py with each box score).

For each game the substitutions say who was on the floor for every play, so each team's five-man units get what the
possession tracker records for Moorpark: time, possessions (FGA - OREB + TO + 0.475 FTA on each side), points for and
against, and the four-factor counts, split by leverage the tracker's way (HIGH within 3 / MEDIUM 4-12 and still
catchable / LOW; CLUTCH the last 5:00 or overtime within 5; garbage time out, sticky from the first play past
30 / 25 at 8:00 / 20 at 5:00 / 15 at 3:00 / 10 at 1:00). The units then go through adjust_lineups.adjust - the
same opponent adjustment (ratings, home court, four factors, time of season) as Moorpark's tracker lineups.

A game is used only when its play-by-play holds together: five on the floor for each team (substitutions can't be
followed otherwise), every player's minutes within a couple of minutes of the box score, the final score matching.
The rest are listed with the reason; nothing is estimated for them.

    python3 compute_pbp_lineups.py                 # current season -> internal_data/pbp_lineups/<season>/<team>.json
    python3 compute_pbp_lineups.py --season 2025-26 --team Citrus --verbose
"""
import argparse
import json
import math
import re
import unicodedata
from datetime import date
from pathlib import Path

import adjust_lineups as al
import update_advanced_analytics as uaa
from ccc_config import DEFAULT_SEASON

OUT = Path("internal_data/pbp_lineups")
MIN_GAMES = 1          # a team's page needs at least this many usable games (the page shows the count)
MIN_TOL = 2.5          # minutes: a player's play-by-play minutes vs the box score
BAD_FIVE_SHARE = 0.03  # share of plays with other than five on the floor before a game is set aside


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _key(name):
    """'RICKETTS,LEO' / '#1 Leo Ricketts' / 'Leo Ricketts Jr.' -> ('ricketts', 'leo')."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"^#\S+\s+", "", n).strip()
    n = re.sub(r"\b(jr|sr|ii|iii|iv)\.?$", "", n).strip(" ,.")
    if "," in n:
        last, first = (x.strip() for x in n.split(",", 1))
    else:
        parts = n.split()
        first, last = (parts[0], " ".join(parts[1:])) if len(parts) > 1 else ("", n)
    clean = lambda x: re.sub(r"[^a-z]", "", x)
    return clean(last), clean(first)


class Roster:
    """A team's box score players, matched to the play-by-play's 'LAST,FIRST' names."""

    def __init__(self, rows):
        self.players = []
        for r in rows:
            raw = r.get("name", "")
            m = re.match(r"^#(\S+)\s+(.*)$", raw)
            num, name = (m.group(1), m.group(2)) if m else ("", raw)
            st = r.get("stats") or {}
            try:
                mins = int(str(st.get("MIN") or "0").strip() or 0)
            except ValueError:
                mins = 0
            self.players.append({"name": name.strip(), "num": num, "key": _key(raw), "min": mins,
                                 "starter": bool(r.get("is_starter"))})
        self.cache = {}

    def find(self, pbp_name):
        if pbp_name in self.cache:
            return self.cache[pbp_name]
        last, first = _key(pbp_name)
        hit = [p for p in self.players if p["key"] == (last, first)] or \
              [p for p in self.players if p["key"][0] == last and p["key"][1][:1] == first[:1]] or \
              [p for p in self.players if p["key"][0] == last]
        p = hit[0] if len(hit) == 1 else None
        self.cache[pbp_name] = p
        return p


def _clock(period, mmss):
    """Seconds elapsed in the game at a play."""
    m = re.match(r"(\d+):(\d+)", mmss or "")
    left = int(m.group(1)) * 60 + int(m.group(2)) if m else 0
    if period <= 2:
        return (period - 1) * 1200 + (1200 - left)
    return 2400 + (period - 3) * 300 + (300 - left)


def _end(periods):
    return 2400 + max(0, periods - 2) * 300


GT_REQ = lambda min_left: 10 if min_left <= 1 else 15 if min_left <= 3 else 20 if min_left <= 5 else 25 if min_left <= 8 else 30


def _tier(d, trail_left):
    if d >= 13 or d > 3 * trail_left:
        return "low"
    return "high" if d <= 3 else "med"


def _counts(action):
    """The four-factor counts an action adds for the team that made it."""
    a = action.lower()
    c = {}
    if "free throw" in a:
        c["fta"] = 1
        if a.startswith("made"):
            c["ftm"] = 1
    elif a.startswith(("made", "missed")) and any(w in a for w in ("shot", "layup", "dunk", "tip", "jumper", "hook", "3-pt")):
        c["fga"] = 1
        three = "3-pt" in a or "three" in a
        if three:
            c["fg3a"] = 1
        if a.startswith("made"):
            c["fgm"] = 1
            if three:
                c["fg3m"] = 1
    elif a == "offensive rebound":
        c["oreb"] = 1
    elif a == "defensive rebound":
        c["dreb"] = 1
    elif a.startswith("turnover"):
        c["tov"] = 1
    elif a.startswith("assist"):
        c["ast"] = 1
    elif a.startswith("steal"):
        c["stl"] = 1
    elif a.startswith("block"):
        c["blk"] = 1
    elif a.startswith("foul"):
        c["pf"] = 1
    return c


def _poss(c):
    return c.get("fga", 0) - c.get("oreb", 0) + c.get("tov", 0) + 0.475 * c.get("fta", 0)


def game_units(pbp, rosters):
    """{side: units} for both teams of one game, or (None, reason). rosters: [visitor Roster, home Roster]."""
    cols = pbp.get("cols") or ["period", "clock", "team", "player", "action", "v", "h"]
    plays = [dict(zip(cols, p)) for p in pbp["plays"]]
    periods = max(p["period"] for p in plays)
    end = _end(periods)
    on = [set(), set()]
    for s in (0, 1):
        on[s] = {p["name"] for p in rosters[s].players if p["starter"]}
        if len(on[s]) != 5:
            return None, f"{len(on[s])} starters in the box score"
    unknown = set()
    # Who starts each later period: the play-by-play doesn't log halftime changes, so a player whose first entry in the
    # period is anything but "enters the game" was on the floor when it began (then those still on from the last period
    # who never show up in it, if that's what it takes to make five).
    first_seen = {}
    for p in plays:
        r = rosters[p["team"]].find(p["player"]) if p["player"] else None
        if r is not None:
            first_seen.setdefault((p["period"], p["team"]), {}).setdefault(r["name"], p["action"])
    # Each player's entries in order (play index, period, action), to repair half-logged substitutions.
    seq = {}
    for j, p in enumerate(plays):
        r = rosters[p["team"]].find(p["player"]) if p["player"] else None
        if r is not None:
            seq.setdefault((p["team"], r["name"]), []).append((j, p["period"], p["action"]))

    def next_act(s, name, j, per):
        for k, pr, act in seq.get((s, name), []):
            if k > j and pr == per:
                return k, act
        return None, None

    last_seen = {}
    fixes = [0]

    def reconcile(s, j, per, actor):
        """Five on the floor for team s at play j: the player acting is on; someone whose next entry is 'enters the
        game' was off; someone whose next entry is anything else (an action, 'goes to the bench') was on."""
        if actor and actor not in on[s]:
            on[s].add(actor); fixes[0] += 1
        while len(on[s]) > 5:
            cand = [n for n in on[s] if n != actor]
            nxt = {n: next_act(s, n, j, per) for n in cand}
            out = [n for n in cand if nxt[n][1] == "enters the game"] or [n for n in cand if nxt[n][0] is None] or cand
            on[s].discard(min(out, key=lambda n: last_seen.get((s, n), -1))); fixes[0] += 1
        while len(on[s]) < 5:
            cand = []
            for p2 in rosters[s].players:
                n = p2["name"]
                if n in on[s]:
                    continue
                k, act = next_act(s, n, j, per)
                if k is not None and act != "enters the game":
                    cand.append((k, n))
            if not cand:
                break
            on[s].add(min(cand)[1]); fixes[0] += 1

    secs_on = [{}, {}]
    # Possessions in the game (both teams), for leverage's "trips left": the box score formula on the whole game.
    tot = [{}, {}]
    for p in plays:
        for k, v in _counts(p["action"]).items():
            tot[p["team"]][k] = tot[p["team"]].get(k, 0) + v
    game_poss = max(_poss(tot[0]) + _poss(tot[1]), 60)
    spt = end / game_poss   # seconds per possession

    units = [{}, {}]
    # Stints for BPR (compute_bpr.py): each stretch with the same ten on the floor - both fives, time, and each
    # side's counts and points. Garbage time is kept but flagged.
    stints, cur = [], None
    gt = False
    bad_five, checked = 0, 0
    last_t, v_prev, h_prev = 0, 0, 0
    band, clutch = "high", False   # 0-0 at the tip
    i = 0
    period = 1
    while i < len(plays):
        p = plays[i]
        t = _clock(p["period"], p["clock"])
        if p["period"] != period:   # a new period: set each five from who shows up first in it
            if last_t < _clock(p["period"], "20:00" if p["period"] <= 2 else "05:00"):
                gap = _clock(p["period"], "20:00" if p["period"] <= 2 else "05:00") - last_t
                for s2 in (0, 1):
                    for n in on[s2]:
                        secs_on[s2][n] = secs_on[s2].get(n, 0) + gap
                    if not gt:
                        _unit(units[s2], on[s2], rosters[s2])["secs"] += gap
                last_t += gap
            period = p["period"]
            for s2 in (0, 1):
                seen = first_seen.get((period, s2), {})
                start = {n for n, act in seen.items() if act != "enters the game"}
                for n in sorted(on[s2]):
                    if len(start) >= 5:
                        break
                    if n not in seen:
                        start.add(n)
                if len(start) == 5:
                    on[s2] = start
        # the time since the last play belongs to whoever was on the floor
        if t > last_t:
            for s in (0, 1):
                for n in on[s]:
                    secs_on[s][n] = secs_on[s].get(n, 0) + (t - last_t)
                if not gt:
                    _unit(units[s], on[s], rosters[s])["secs"] += t - last_t
                    if band:
                        _unit(units[s], on[s], rosters[s])["lev"].setdefault(band, _blk())["secs"] += t - last_t
                    if clutch:
                        _unit(units[s], on[s], rosters[s])["lev"].setdefault("clutch", _blk())["secs"] += t - last_t
            if cur is not None and len(on[0]) == 5 and len(on[1]) == 5:
                cur["secs"] += t - last_t
            last_t = t
        # substitutions at this moment, all together
        if p["action"] in ("enters the game", "goes to the bench"):
            r = rosters[p["team"]].find(p["player"])
            if r is None:
                unknown.add(p["player"])
            elif p["action"] == "enters the game":
                on[p["team"]].add(r["name"])
                last_seen[(p["team"], r["name"])] = i
            else:
                on[p["team"]].discard(r["name"])
            i += 1
            continue
        # where the game stands before this play (leverage / garbage time)
        left = max(end - t, 0)
        ot = p["period"] > 2
        d = abs(v_prev - h_prev)
        trail_left = max(left / spt / 2, 0.5)
        tier = _tier(d, trail_left)
        clutch = tier != "low" and d <= 5 and (ot or left <= 300)
        if not ot and not gt and d >= GT_REQ(left / 60):
            gt = True
        band = None if gt and not ot else tier
        if gt and ot:
            gt = False
        actor = rosters[p["team"]].find(p["player"]) if p["player"] else None
        for s2 in (0, 1):
            reconcile(s2, i, p["period"], actor["name"] if actor and s2 == p["team"] else None)
        if actor:
            last_seen[(p["team"], actor["name"])] = i
        checked += 1
        if len(on[0]) != 5 or len(on[1]) != 5:
            bad_five += 1
        # the play's counts, for the five of each team
        s = p["team"]
        c = _counts(p["action"])
        pts = (p["v"] - v_prev, p["h"] - h_prev)
        if len(on[0]) == 5 and len(on[1]) == 5:
            key = (tuple(sorted(on[0])), tuple(sorted(on[1])))
            if cur is None or cur["key"] != key:
                cur = {"key": key, "secs": 0, "c": [{}, {}], "pts": [0, 0], "gt": False, "lev": {}}
                stints.append(cur)
            for k, v in c.items():
                cur["c"][s][k] = cur["c"][s].get(k, 0) + v
            cur["pts"][0] += pts[0]; cur["pts"][1] += pts[1]
            cur["gt"] = cur["gt"] or (gt and not ot)
            if band:
                cur["lev"][band] = cur["lev"].get(band, 0) + 1
        if not gt and len(on[0]) == 5 and len(on[1]) == 5:
            for side in (0, 1):
                u = _unit(units[side], on[side], rosters[side])
                blocks = [u, u["lev"].setdefault(band, _blk())] + ([u["lev"].setdefault("clutch", _blk())] if clutch else [])
                for b in blocks:
                    tgt = b["o"] if side == s else b["d"]
                    for k, v in c.items():
                        tgt[k] = tgt.get(k, 0) + v
                    b["pf"] += pts[side] if side == 0 else pts[1]
                    b["pa"] += pts[1] if side == 0 else pts[0]
        v_prev, h_prev = p["v"], p["h"]
        i += 1
    # the last stretch to the final horn
    for s in (0, 1):
        for n in on[s]:
            secs_on[s][n] = secs_on[s].get(n, 0) + max(end - last_t, 0)

    if checked and bad_five / checked > BAD_FIVE_SHARE:
        return None, f"five on the floor could not be followed ({bad_five} of {checked} plays)"
    if unknown:
        return None, "play-by-play names not in the box score: " + ", ".join(sorted(unknown))
    for s in (0, 1):
        real = sum(p["min"] for p in rosters[s].players) >= 150
        if real:
            off = [f"{p['name']} {secs_on[s].get(p['name'], 0) / 60:.0f} vs {p['min']}" for p in rosters[s].players
                   if abs(secs_on[s].get(p["name"], 0) / 60 - p["min"]) > MIN_TOL]
            if off:
                return None, "minutes don't match the box score: " + "; ".join(off[:3])
    out = []
    for s in (0, 1):
        us = []
        for u in units[s].values():
            for b in [u] + list(u["lev"].values()):
                b["oT"] = round(_poss(b["o"]), 2)
                b["dT"] = round(_poss(b["d"]), 2)
            if u["secs"] > 0 or u["oT"] or u["dT"]:
                us.append(u)
        out.append(us)
    st = [{"v": list(x["key"][0]), "h": list(x["key"][1]), "secs": x["secs"],
           "poss": [round(_poss(x["c"][0]), 2), round(_poss(x["c"][1]), 2)], "pts": x["pts"], "gt": x["gt"],
           "lev": max(x["lev"], key=x["lev"].get) if x["lev"] else None}
          for x in stints if x["secs"] > 0 or any(x["c"][0].values()) or any(x["c"][1].values())]
    return out, {"fixes": fixes[0], "stints": st}


def _blk():
    return {"secs": 0, "pf": 0, "pa": 0, "o": {}, "d": {}}


def _unit(units, on, roster):
    key = "|".join(sorted(on))
    if key not in units:
        by = {p["name"]: p for p in roster.players}
        players = sorted(({"name": n, "num": by[n]["num"] if n in by else ""} for n in on), key=lambda x: (int(x["num"]) if x["num"].isdigit() else 99, x["name"]))
        units[key] = dict(_blk(), key=key, players=players, lev={})
    return units[key]


# ---------------------------------------------------------------------------
def box_for(season, team, d):
    """The team's saved box score for date d (the first one that day)."""
    for f in sorted(Path(f"{season} Teams Schedules").glob(f"*/{team}/{d:%Y%m%d}_*/*.json")):
        try:
            return json.load(open(f))
        except (OSError, ValueError):
            pass
    return None


def site_for(season, team, d):
    """home / away / neutral from the team's game log (the stats' own call, tournaments included)."""
    p = uaa.find_team_stats(team)
    try:
        for g in json.load(open(p / "game_log.json")).get("games", []):
            m, dd, y = (int(x) for x in g["date"].split("/"))
            if date(y, m, dd) == d:
                return (g.get("location") or "neutral").lower()
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return "neutral"


def build(season, only=None, verbose=False):
    pdir = Path(f"{season} Play by Play")
    ratings = al.load_ratings(season)     # also points uaa at this season's stats
    factors = al.load_factors(season) if ratings else {}
    phase = al.season_phase()
    teams = {}
    all_stints = []
    for f in sorted(pdir.glob("*.json")) if pdir.exists() else []:
        d = date(int(f.name[:4]), int(f.name[4:6]), int(f.name[6:8]))
        pbp = json.load(open(f))
        if not pbp.get("plays"):
            continue   # half box scores only, no play-by-play
        names = [uaa.resolve_opponent(pbp["visitor"]) or pbp["visitor"], uaa.resolve_opponent(pbp["home"]) or pbp["home"]]
        boxes = [box_for(season, n, d) for n in names]
        box = next((b for b in boxes if b), None)
        rows = []
        for side, label in ((0, pbp["visitor"]), (1, pbp["home"])):
            rows.append(Roster(((box or {}).get("teams") or {}).get(label) or []))
        res, why = (None, "no box score saved for it") if box is None else game_units(pbp, rows)
        if res is not None:
            if verbose:
                print(f"  {d} {pbp['visitor']} at {pbp['home']}: used ({why['fixes']} substitution repairs)")
            all_stints.append({"date": d.isoformat(), "visitor": names[0], "home": names[1],
                               "site": site_for(season, names[1], d), "stints": why["stints"]})
            why = None
        for s, team in enumerate(names):
            if only and team != only:
                continue
            if team not in uaa.all_stat_teams():
                continue
            opp = names[1 - s]
            entry = teams.setdefault(team, {"games": [], "skipped": []})
            gid = f"{d:%Y%m%d}_{slug(opp)}"
            if res is None:
                entry["skipped"].append({"date": d.isoformat(), "opponent": opp, "why": why})
                if verbose:
                    print(f"  {team} {d} vs {opp}: skipped ({why})")
                continue
            entry["games"].append({"id": gid, "date": d.isoformat(), "opponent": opp, "site": site_for(season, team, d),
                                   "units": res[s]})
    out_dir = OUT / season
    out_dir.mkdir(parents=True, exist_ok=True)
    # Every usable game's stints, for compute_bpr.py (internal: not published)
    sdir = Path("internal_data/pbp_stints")
    sdir.mkdir(parents=True, exist_ok=True)
    json.dump({"season": season, "games": all_stints}, open(sdir / f"{season}.json", "w"), separators=(",", ":"))
    written = 0
    for team, entry in sorted(teams.items()):
        if len(entry["games"]) < MIN_GAMES or not ratings:
            continue
        adj = al.adjust({"games": entry["games"]}, ratings, season, factors, phase)
        secs = {}   # time on the floor by leverage band (adjust_lineups keeps possessions, not time)
        for g in entry["games"]:
            for u in g["units"]:
                for b, blk in u["lev"].items():
                    secs.setdefault(u["key"], {}).setdefault(b, 0)
                    secs[u["key"]][b] += blk["secs"]
        for u in adj["units"]:
            u["levSecs"] = secs.get(u["key"], {})
            u["gp"] = u.get("gp", 0)
        gl = uaa.find_team_stats(team) / "game_log.json"
        try:
            total = len(json.load(open(gl)).get("games", []))
        except (OSError, ValueError):
            total = len(entry["games"]) + len(entry["skipped"])
        adj.update({"team": team, "season": season, "source": "play-by-play",
                    "pbpGames": len(entry["games"]), "teamGames": total, "skippedGames": entry["skipped"]})
        json.dump(adj, open(out_dir / f"{slug(team)}.json", "w"), separators=(",", ":"))
        written += 1
        if verbose:
            print(f"{team}: {len(entry['games'])} games used of {total}, {len(adj['units'])} fives")
    print(f"Play-by-play lineups: {written} teams -> {out_dir}")
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", default=DEFAULT_SEASON)
    ap.add_argument("--team")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    build(a.season, a.team, a.verbose)


if __name__ == "__main__":
    main()
