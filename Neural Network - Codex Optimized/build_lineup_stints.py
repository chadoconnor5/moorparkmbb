#!/usr/bin/env python3
"""Build per-game on-court stints for Moorpark from the defensive possession logs.

A 'stint' is a continuous span with the same 5 on the floor. For each we derive:
  half, start/end clock, minutes, and +/- (from the running scoreboard logged at
  each substitution). The score is snapshotted at every sub boundary, so a stint's
  +/- = (margin at next sub) - (margin at this sub) — all scoring in the span.

Ghost-sub ('GS') possessions are appended at file end but carry mid-game clocks,
so possessions are re-sorted by (half, descending clock) before stint detection.

Outputs internal_data/moorpark_stints_2025_26.json:
  {game_key: {date, opp, venue, players:[...], stints:[{half,start,end,mins,pm,lineup:[#..]}]}}
"""
import csv
import glob
import json
import os
import re

LOG_DIR = "internal_data/def_logs"
OUT = "internal_data/moorpark_stints_2025_26.json"


def to_int(x):
    try:
        return int(str(x).strip())
    except (ValueError, TypeError):
        return None


def clock_secs(c, half):
    """Game clock 'MM:SS' -> seconds elapsed since tip (for ordering & minutes).
    Each half is 20:00. elapsed = half_offset + (1200 - remaining)."""
    m = re.match(r"^\s*(\d+):(\d{1,2})\s*$", str(c or ""))
    if not m:
        return None
    remaining = int(m.group(1)) * 60 + int(m.group(2))
    hoff = (to_int(half) or 1) - 1
    return hoff * 1200 + (1200 - remaining)


def lineup_nums(lu):
    return [p.strip()[1:].split()[0] for p in lu.split("/") if p.strip().startswith("#")]


def possessions(path):
    """Collapse event rows to possessions, fill clock/score, sort by elapsed time."""
    rows = list(csv.DictReader(open(path)))
    poss, cur = [], None
    for r in rows:
        pid = (r.get("half", ""), r.get("poss", ""))
        if cur is None or pid != cur["pid"]:
            cur = {"pid": pid, "half": r.get("half", ""), "clock": "",
                   "lineup": r.get("lineup", ""), "mp": None, "opp": None}
            poss.append(cur)
        if not cur["clock"] and r.get("clock", "").strip():
            cur["clock"] = r["clock"].strip()
        if cur["mp"] is None and to_int(r.get("mp_score")) is not None:
            cur["mp"], cur["opp"] = to_int(r["mp_score"]), to_int(r.get("opp_score"))
    # elapsed time; possessions missing clock inherit the previous elapsed
    last_el = 0
    for p in poss:
        el = clock_secs(p["clock"], p["half"])
        if el is None:
            el = last_el
        p["elapsed"] = el
        last_el = el
    poss.sort(key=lambda p: p["elapsed"])  # stable -> file order preserved on ties
    # forward-fill score after sorting; seed 0-0 at tip so the opening (starters)
    # stint gets a real +/- even when the score wasn't logged until the first sub
    last = (0, 0)
    for p in poss:
        if p["mp"] is not None:
            last = (p["mp"], p["opp"])
        p["score"] = last
    return poss


def build_stints(path):
    poss = possessions(path)
    if not poss:
        return None
    # group consecutive same-lineup possessions
    groups = []
    for p in poss:
        if groups and p["lineup"] == groups[-1]["lineup"]:
            groups[-1]["end_el"] = p["elapsed"]
            groups[-1]["end_score"] = p["score"] or groups[-1]["end_score"]
        else:
            groups.append({"lineup": p["lineup"], "half": p["half"],
                           "start_el": p["elapsed"], "end_el": p["elapsed"],
                           "start_score": p["score"], "end_score": p["score"]})
    stints = []
    for i, g in enumerate(groups):
        # +/- = margin at next sub - margin at this sub (captures this stint's scoring)
        s0 = g["start_score"]
        s1 = groups[i + 1]["start_score"] if i + 1 < len(groups) else g["end_score"]
        pm = None
        if s0 and s1:
            pm = (s1[0] - s0[0]) - (s1[1] - s0[1])
        end_el = groups[i + 1]["start_el"] if i + 1 < len(groups) else g["end_el"]
        mins = round(max(0, end_el - g["start_el"]) / 60.0, 1)
        stints.append({"half": to_int(g["half"]) or 1,
                       "start": g["start_el"], "end": end_el, "mins": mins,
                       "pm": pm, "lineup": lineup_nums(g["lineup"])})
    return stints


def roster_map(files):
    """Jersey number -> player name, from '#N First Last' lineup tokens."""
    from collections import Counter
    seen = {}
    for f in files:
        for r in csv.DictReader(open(f)):
            for part in r.get("lineup", "").split("/"):
                part = part.strip()
                m = re.match(r"^#(\d+)\s+(.+)$", part)
                if m:
                    seen.setdefault(m.group(1), Counter())[m.group(2).strip()] += 1
    return {n: c.most_common(1)[0][0] for n, c in seen.items()}


def main():
    files = sorted(f for f in glob.glob(os.path.join(LOG_DIR, "def_2025-*.csv"))
                   if not f.endswith(".bak"))
    roster = roster_map(files)
    out = {"_roster": roster, "_games": {}}
    for f in files:
        rows = list(csv.DictReader(open(f)))
        if not rows:
            continue
        date, opp = rows[0]["date"], rows[0]["opponent"]
        venue = rows[0].get("venue", "")
        stints = build_stints(f)
        players = sorted({n for s in stints for n in s["lineup"]}, key=lambda x: int(x))
        key = f"{date}__{opp}"
        out["_games"][key] = {"date": date, "opp": opp, "venue": venue,
                              "players": players, "stints": stints}
    json.dump(out, open(OUT, "w"), indent=0)
    print(f"Wrote {OUT}: {len(out['_games'])} games, {len(roster)} players")
    # verification sample
    games = out["_games"]
    g = games.get("2025-11-19__Palomar") or next(iter(games.values()))
    print(f"\nSample {g['date']} vs {g['opp']} ({len(g['stints'])} stints, "
          f"players {','.join(g['players'])}):")
    tot = sum(s["pm"] for s in g["stints"] if s["pm"] is not None)
    tmin = sum(s["mins"] for s in g["stints"])
    for s in g["stints"][:8]:
        mm = lambda el: f"{el//60}:{el%60:02d}"
        print(f"  H{s['half']} {mm(s['start'])}->{mm(s['end'])} {s['mins']:>4}m "
              f"pm={s['pm'] if s['pm'] is not None else '?':>3}  {'-'.join(s['lineup'])}")
    print(f"  ... game +/- (sum of stints) = {tot:+d}, minutes logged = {tmin:.1f}")


if __name__ == "__main__":
    main()
