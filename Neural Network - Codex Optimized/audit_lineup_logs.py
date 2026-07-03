#!/usr/bin/env python3
"""Audit the Moorpark defensive possession logs for score-update gaps.

The stint timeline (+/- per on-court span) is only as good as how often the
running scoreboard (mp_score/opp_score) was logged. This reports, per game:
  - possessions total / missing clock / missing score
  - distinct score snapshots and the worst stale run (poss between score changes)
  - biggest single score jump (points logged in one batch)
  - lineup changes (stints) and how many stints never see a score change
    (those can't get a reliable +/-)
Run from project root.
"""
import csv
import glob
import os

LOG_DIR = "internal_data/def_logs"


def to_int(x):
    try:
        return int(str(x).strip())
    except (ValueError, TypeError):
        return None


def possession_view(path):
    """Collapse event rows to one entry per possession (in file order)."""
    rows = list(csv.DictReader(open(path)))
    poss = []
    cur = None
    for r in rows:
        pid = (r.get("half", ""), r.get("poss", ""))
        if cur is None or pid != cur["pid"]:
            cur = {"pid": pid, "half": r.get("half", ""), "clock": "",
                   "mp": None, "opp": None, "lineup": r.get("lineup", ""),
                   "pts": 0}
            poss.append(cur)
        if not cur["clock"] and r.get("clock", "").strip():
            cur["clock"] = r["clock"].strip()
        if cur["mp"] is None and to_int(r.get("mp_score")) is not None:
            cur["mp"] = to_int(r["mp_score"])
            cur["opp"] = to_int(r.get("opp_score"))
        cur["pts"] += to_int(r.get("pts")) or 0
    return poss


def audit(path):
    poss = possession_view(path)
    n = len(poss)
    miss_clock = sum(1 for p in poss if not p["clock"])
    miss_score = sum(1 for p in poss if p["mp"] is None)

    # score snapshots in order
    snaps = [(i, p["mp"], p["opp"]) for i, p in enumerate(poss) if p["mp"] is not None]
    distinct = []
    for i, mp, opp in snaps:
        if not distinct or (mp, opp) != (distinct[-1][1], distinct[-1][2]):
            distinct.append((i, mp, opp))

    # worst stale run: max possessions spanned by a single (mp,opp) value
    worst_stale = 0
    if snaps:
        run_start = snaps[0][0]
        last = (snaps[0][1], snaps[0][2])
        for i, mp, opp in snaps[1:]:
            if (mp, opp) != last:
                worst_stale = max(worst_stale, i - run_start)
                run_start = i
                last = (mp, opp)
        worst_stale = max(worst_stale, snaps[-1][0] - run_start)

    # biggest combined-score jump between consecutive distinct snapshots
    big_jump = 0
    backwards = 0
    for a, b in zip(distinct, distinct[1:]):
        d = (b[1] + b[2]) - (a[1] + a[2])
        big_jump = max(big_jump, d)
        if d < 0:
            backwards += 1

    # stints (lineup spans) and how many never see a score change
    stints = []
    cur = None
    for i, p in enumerate(poss):
        if cur is None or p["lineup"] != cur["lineup"]:
            cur = {"lineup": p["lineup"], "i0": i, "i1": i}
            stints.append(cur)
        cur["i1"] = i
    # forward-filled score per possession
    ff = [None] * n
    last = None
    for i, p in enumerate(poss):
        if p["mp"] is not None:
            last = (p["mp"], p["opp"])
        ff[i] = last
    stints_no_change = 0
    for s in stints:
        a, b = ff[s["i0"]], ff[s["i1"]]
        if a is None or b is None or a == b:
            stints_no_change += 1

    return {
        "n": n, "miss_clock": miss_clock, "miss_score": miss_score,
        "snaps": len(distinct), "worst_stale": worst_stale,
        "big_jump": big_jump, "backwards": backwards,
        "stints": len(stints), "stints_no_change": stints_no_change,
        "final": distinct[-1][1:] if distinct else None,
    }


def short_lineup(lu):
    """'#1 Josh Castaniero / ...' -> '1/10/14/20/22' (jersey numbers)."""
    nums = []
    for part in lu.split("/"):
        part = part.strip()
        if part.startswith("#"):
            nums.append(part[1:].split()[0])
    return "-".join(nums) if nums else lu[:24]


def sub_gaps(path):
    """Flag lineup changes (substitutions) with no fresh score at the boundary.

    A boundary between poss[i] (end of stint A) and poss[i+1] (start of B) is
    'covered' if either possession carries its own logged score. Otherwise the
    score is only forward-filled and any points around the sub are unattributable
    — we report the ambiguity window and the points in limbo."""
    poss = possession_view(path)
    n = len(poss)
    has_score = [p["mp"] is not None for p in poss]
    # nearest fresh snapshot index <= i and >= i, with its combined score
    def nearest_before(i):
        for j in range(i, -1, -1):
            if has_score[j]:
                return j
        return None
    def nearest_after(i):
        for j in range(i, n):
            if has_score[j]:
                return j
        return None

    gaps = []
    for i in range(1, n):
        if poss[i]["lineup"] == poss[i - 1]["lineup"]:
            continue  # not a substitution
        # boundary is between i-1 (end A) and i (start B)
        covered = has_score[i - 1] or has_score[i]
        if covered:
            continue
        b = nearest_before(i - 1)
        a = nearest_after(i)
        before = (poss[b]["mp"], poss[b]["opp"]) if b is not None else None
        after = (poss[a]["mp"], poss[a]["opp"]) if a is not None else None
        limbo = None
        if before and after:
            limbo = (after[0] + after[1]) - (before[0] + before[1])
        span = ((i - 1) - b if b is not None else "?",
                (a - i) if a is not None else "?")
        clk = poss[i]["clock"] or poss[i - 1]["clock"] or "??:??"
        gaps.append({
            "half": poss[i]["half"], "clock": clk,
            "from": short_lineup(poss[i - 1]["lineup"]),
            "to": short_lineup(poss[i]["lineup"]),
            "before": f"{before[0]}-{before[1]}" if before else "?",
            "after": f"{after[0]}-{after[1]}" if after else "?",
            "limbo": limbo, "span": span,
        })
    return gaps


def main():
    files = sorted(f for f in glob.glob(os.path.join(LOG_DIR, "def_2025-*.csv"))
                   if not f.endswith(".bak"))
    print(f"{'game':<34}{'poss':>5}{'noClk':>6}{'noScr':>6}{'snaps':>6}"
          f"{'stale':>6}{'jump':>5}{'back':>5}{'stnt':>5}{'+/-?':>6}  final")
    print("-" * 110)
    for f in files:
        a = audit(f)
        name = os.path.basename(f).replace("def_2025-", "").replace(".csv", "")
        flag = " <-- " if (a["worst_stale"] >= 8 or a["miss_score"] >= 10
                           or a["big_jump"] >= 8 or a["backwards"]) else ""
        fin = f"{a['final'][0]}-{a['final'][1]}" if a["final"] else "?"
        print(f"{name:<34}{a['n']:>5}{a['miss_clock']:>6}{a['miss_score']:>6}"
              f"{a['snaps']:>6}{a['worst_stale']:>6}{a['big_jump']:>5}"
              f"{a['backwards']:>5}{a['stints']:>5}{a['stints_no_change']:>6}  {fin}{flag}")
    print("\nLegend: noClk/noScr = possessions missing clock/score; snaps = distinct "
          "score updates; stale = worst run of possessions with no score change; "
          "jump = biggest one-shot score jump (combined pts); back = score went "
          "backwards (logging error); stnt = lineup spans; +/-? = stints with NO "
          "score change inside them (can't get a reliable +/-).\n")

    print("=" * 78)
    print("SUBSTITUTIONS MISSING A SCORE  (log the score at these subs to fix +/-)")
    print("=" * 78)
    for f in files:
        gaps = sub_gaps(f)
        name = os.path.basename(f).replace("def_2025-", "").replace(".csv", "")
        print(f"\n{name}  — {len(gaps)} sub(s) need a score:")
        if not gaps:
            print("    (clean — every substitution has a score at the boundary)")
        for g in gaps:
            lm = f"{g['limbo']:+d} pts in limbo" if g["limbo"] is not None else "open"
            print(f"    H{g['half']} {g['clock']:>6}  {g['from']:>14} -> {g['to']:<14}"
                  f"  score {g['before']}…{g['after']}  ({lm}, span {g['span'][0]}/{g['span'][1]} poss)")


if __name__ == "__main__":
    main()
