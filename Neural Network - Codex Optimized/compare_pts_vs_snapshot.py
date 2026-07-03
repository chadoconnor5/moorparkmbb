#!/usr/bin/env python3
"""Compare stint +/- built two ways:
  A) SNAPSHOT  — opponent score from the logged scoreboard (current method)
  B) PTS       — opponent score rebuilt by summing the per-possession `pts`
Moorpark's score is the logged scoreboard in both. Reports per-game totals vs the
true final, and how many individual stints change between the two methods."""
import csv
import glob
import json
import os
import re

LOG_DIR = "internal_data/def_logs"


def secs(c, h):
    m = re.match(r"^\s*(\d+):(\d{1,2})\s*$", str(c or ""))
    if not m:
        return None
    return (int(h or 1) - 1) * 1200 + (1200 - (int(m.group(1)) * 60 + int(m.group(2))))


def ival(x):
    try:
        return int(str(x).strip())
    except (ValueError, TypeError):
        return None


def possessions(path):
    rows = list(csv.DictReader(open(path)))
    poss, cur = [], None
    for r in rows:
        pid = (r.get("half", ""), r.get("poss", ""))
        if cur is None or pid != cur["pid"]:
            cur = {"pid": pid, "half": r.get("half", ""), "clock": "",
                   "lineup": r.get("lineup", ""), "mp": None, "lopp": None, "pts": 0}
            poss.append(cur)
        cur["pts"] += ival(r.get("pts")) or 0
        if not cur["clock"] and r.get("clock", "").strip():
            cur["clock"] = r["clock"].strip()
        if cur["mp"] is None and ival(r.get("mp_score")) is not None:
            cur["mp"], cur["lopp"] = ival(r["mp_score"]), ival(r.get("opp_score"))
    last_el = 0
    for p in poss:
        el = secs(p["clock"], p["half"])
        p["el"] = el if el is not None else last_el
        last_el = p["el"]
    poss.sort(key=lambda p: p["el"])  # chronological (handles ghost-sub rows)
    # Moorpark forward-fill (seed 0-0 at tip); opponent both ways
    mp = 0
    cum = 0
    for p in poss:
        if p["mp"] is not None:
            mp = p["mp"]
        cum += p["pts"]
        p["smp"] = mp                       # Moorpark logged
        p["opp_snap"] = p["lopp"]           # opponent logged snapshot (may be None)
        p["opp_pts"] = cum                  # opponent from summed pts (ground truth)
    # forward-fill the snapshot opponent too (seed 0)
    o = 0
    for p in poss:
        if p["opp_snap"] is not None:
            o = p["opp_snap"]
        p["opp_snap"] = o
    return poss


def stints(poss, opp_key):
    groups = []
    for p in poss:
        if groups and p["lineup"] == groups[-1]["lineup"]:
            groups[-1]["end"] = p
        else:
            groups.append({"lineup": p["lineup"], "start": p, "end": p})
    out = []
    for i, g in enumerate(groups):
        nxt = groups[i + 1]["start"] if i + 1 < len(groups) else g["end"]
        pm = (nxt["smp"] - g["start"]["smp"]) - (nxt[opp_key] - g["start"][opp_key])
        mins = round(max(0, nxt["el"] - g["start"]["el"]) / 60.0, 1)
        out.append({"pm": pm, "mins": mins, "lineup": g["lineup"]})
    return out


def true_margin(date):
    for f in glob.glob("2025-26 Teams Schedules/**/Moorpark/*/*.json", recursive=True):
        if os.path.basename(f)[:8] == date.replace("-", ""):
            sc = json.load(open(f)).get("score", {})
            mp = sc.get("Moorpark")
            op = [v for k, v in sc.items() if k != "Moorpark"]
            if mp is not None and op:
                return mp - op[0]
    return None


def main():
    files = sorted(f for f in glob.glob(os.path.join(LOG_DIR, "def_2025-*.csv"))
                   if not f.endswith(".bak"))
    print(f"{'game':<30}{'true':>6}{'SNAPSHOT':>10}{'PTS':>7}"
          f"{'stints≠':>9}{'maxΔ':>6}")
    print("-" * 70)
    for f in files:
        poss = possessions(f)
        sa = stints(poss, "opp_snap")
        sb = stints(poss, "opp_pts")
        ta = sum(s["pm"] for s in sa)
        tb = sum(s["pm"] for s in sb)
        diff = sum(1 for a, b in zip(sa, sb) if a["pm"] != b["pm"])
        maxd = max((abs(a["pm"] - b["pm"]) for a, b in zip(sa, sb)), default=0)
        t = true_margin(os.path.basename(f)[4:14])  # 'def_2025-11-01...' -> '2025-11-01'
        name = os.path.basename(f).replace("def_2025-", "").replace(".csv", "")[:28]
        ts = f"{t:+d}" if t is not None else "?"
        print(f"{name:<30}{ts:>6}{ta:>+10}{tb:>+7}{diff:>9}{maxd:>6}")
    print("\nSNAPSHOT = current method (logged scoreboard). PTS = opponent score "
          "summed from per-possession pts.\nstints≠ = how many stints get a different "
          "+/- between the two. maxΔ = biggest single-stint change.")


if __name__ == "__main__":
    main()
