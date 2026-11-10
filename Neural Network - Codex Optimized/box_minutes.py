#!/usr/bin/env python3
"""Real minutes from the play-by-play, for box scores whose minutes column is wrong in one tell-tale way: the starters
at 40 and the bench at 0, though the bench players have stats (11/6 Santa Ana at Los Angeles City). The column adds up
to 200, so it passes for real minutes, but every per-minute stat (usage, rebound %, ORtg, per-40...) is then off: the
starters' spread over 40 minutes they didn't play, the bench's over none.

The fix: who was on the floor comes from the game's play-by-play (compute_pbp_lineups.game_units, the same
substitution repair the lineups use); each player's seconds on the floor, scaled to the game's minutes (200, +25 an
overtime), replace the box score's MIN. The box score's own number is kept on the player as "min_box", and the side's
minutes_quality says {"minutes": "PBP", "box": "BENCH_ZERO"}. Nothing is changed unless the play-by-play is usable:
a full game followed, 75%+ of its time placed, and every player with a stat on the floor at some point.

scrape.save_box runs it as each box score is saved. For box scores already saved (no request to the site):
    python3 box_minutes.py [--season 2026-27] [--dry-run]     # then: python3 scrape.py rebuild
"""
import argparse
import json
import re
from pathlib import Path

from ccc_config import DEFAULT_SEASON

ACTIVE = ("FGM-A", "3PM-A", "FTM-A", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS")
MIN_PLACED = 0.75   # share of the game's time the play-by-play has to place for its minutes to be used


def _int(v):
    try:
        return int(str(v).split(":")[0].strip() or 0)
    except ValueError:
        return 0


def _active(stats):
    for k in ACTIVE:
        v = str((stats or {}).get(k) or "").strip()
        if "-" in v:
            try:
                if int(v.split("-")[1]) > 0:
                    return True
            except ValueError:
                pass
        elif _int(v) > 0:
            return True
    return False


def bench_zero(players):
    """True when the side's minutes are the starters-at-40 / bench-at-0 kind: a player listed at 0 minutes has a stat,
    while the column still adds up to a game (190+)."""
    rows = [p for p in players or [] if not str(p.get("name", "")).upper().startswith(("TM", "TEAM"))]
    total = sum(_int((p.get("stats") or {}).get("MIN")) for p in rows)
    return total >= 190 and any(_int((p.get("stats") or {}).get("MIN")) == 0 and _active(p.get("stats")) for p in rows)


def _labels(box, pbp):
    """The box score's team label for the play-by-play's visitor and home."""
    teams = box.get("teams") or {}
    out = []
    for name in (pbp.get("visitor"), pbp.get("home")):
        out.append(name if name in teams else next((k for k in teams if k.lower() == str(name).lower()), None))
    return out


def repair(box, pbp):
    """Replace bench-zero minutes in box (in place) with the play-by-play's. Returns the team labels fixed."""
    if not (pbp or {}).get("plays"):
        return []
    labels = _labels(box, pbp)
    if None in labels or not any(bench_zero(box["teams"][lab]) for lab in labels):
        return []
    import compute_pbp_lineups as cpl
    import play_by_play
    pbp = play_by_play.fix_plays(json.loads(json.dumps(pbp)))
    rows = [box["teams"][lab] for lab in labels]
    rosters = [cpl.Roster(r) for r in rows]
    try:
        res, why = cpl.game_units(pbp, rosters)
    except Exception:
        return []
    if res is None:
        return []
    stints = why["stints"]
    game_secs = sum(s["secs"] for s in stints)
    periods = max(p[0] for p in pbp["plays"])
    full = 2400 + 300 * max(0, periods - 2)
    if game_secs < MIN_PLACED * full:
        return []
    fixed = []
    for side, (lab, roster) in enumerate(zip(labels, rosters)):
        players = box["teams"][lab]
        if not bench_zero(players):
            continue
        secs = {}
        for s in stints:
            for n in s["vh"[side]]:
                secs[n] = secs.get(n, 0) + s["secs"]
        names = [rp["name"] for rp in roster.players]
        # every player with a stat has to have been on the floor, or the play-by-play can't be trusted for this side
        if any(_active(p.get("stats")) and not secs.get(names[i]) for i, p in enumerate(players)):
            continue
        target = 5 * full // 60   # player-minutes in the game: 200, +25 an overtime
        raw = [(full / 60) * secs.get(names[i], 0) / game_secs for i in range(len(players))]   # his share of 40
        mins = [int(x) for x in raw]
        for i in sorted(range(len(raw)), key=lambda i: raw[i] - mins[i], reverse=True)[:target - sum(mins)]:
            mins[i] += 1   # whole minutes that still add up to the game
        for p, m in zip(players, mins):
            st = p.setdefault("stats", {})
            p["min_box"] = st.get("MIN")
            st["MIN"] = str(m)
        box.setdefault("minutes_quality", {})[lab] = {"minutes": "PBP", "total": target, "box": "BENCH_ZERO"}
        fixed.append(lab)
    return fixed


def _slug(text):
    return re.sub(r"[^a-zA-Z0-9]", "_", text or "").lower().strip("_")


def backfill(season, dry_run=False):
    pdir = Path(f"{season} Play by Play")
    changed, teams = 0, set()
    for f in sorted(Path(f"{season} Teams Schedules").glob("*/*/*/*.json")):
        try:
            box = json.load(open(f))
        except (OSError, ValueError):
            continue
        if not isinstance(box, dict) or not box.get("teams") or "min_box" in json.dumps(box):
            continue
        day = f.parent.name[:8]
        pf = pdir / f"{day}_{_slug(box.get('visitor'))}_at_{_slug(box.get('home'))}.json"
        if not pf.exists():
            continue
        fixed = repair(box, json.load(open(pf)))
        if fixed:
            changed += 1
            teams.add(f.parent.parent.name)
            print(f"  {f.parent.name} ({f.parent.parent.name}): minutes from the play-by-play for {', '.join(fixed)}")
            if not dry_run:
                json.dump(box, open(f, "w"), indent=2)
    print(f"{changed} box score files {'would change' if dry_run else 'changed'}; teams: {', '.join(sorted(teams)) or '-'}")
    return teams


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", default=DEFAULT_SEASON)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    backfill(a.season, a.dry_run)
