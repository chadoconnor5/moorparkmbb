#!/usr/bin/env python3
"""How 'fresh' is the score at each substitution?

The defensive logs snapshot the scoreboard intermittently, so a sub's score can
trail the live score. The opponent side is verifiable: the per-possession `pts`
column cumulates to the opponent's true running total, so we compare logged
opp_score vs cumulative pts to measure the lag. Moorpark's own score can't be
checked from these files (offense isn't logged here) — we only flag subs where
mp_score didn't advance from the previous sub (possible forgotten update).
"""
import csv
import glob
import os
import re

LOG_DIR = "internal_data/def_logs"


def secs(c, h):
    m = re.match(r"^\s*(\d+):(\d{1,2})\s*$", str(c or ""))
    if not m:
        return None
    return (int(h or 1) - 1) * 1200 + (1200 - (int(m.group(1)) * 60 + int(m.group(2))))


def to_int(x):
    try:
        return int(str(x).strip())
    except (ValueError, TypeError):
        return None


def analyze(path):
    rows = list(csv.DictReader(open(path)))
    # possession view in file order, carrying cumulative opp pts + logged score
    poss, cur, cum = [], None, 0
    for r in rows:
        cum += to_int(r.get("pts")) or 0
        pid = (r.get("half", ""), r.get("poss", ""))
        if cur is None or pid != cur["pid"]:
            cur = {"pid": pid, "half": r.get("half", ""), "clock": "",
                   "lineup": r.get("lineup", ""), "mp": None, "opp": None,
                   "cum": cum}
            poss.append(cur)
        cur["cum"] = cum  # cumulative opp pts through end of this possession
        if not cur["clock"] and r.get("clock", "").strip():
            cur["clock"] = r["clock"].strip()
        if cur["mp"] is None and to_int(r.get("mp_score")) is not None:
            cur["mp"], cur["opp"] = to_int(r["mp_score"]), to_int(r.get("opp_score"))
    # order by elapsed (handles ghost-sub rows)
    last_el = 0
    for p in poss:
        el = secs(p["clock"], p["half"])
        p["el"] = el if el is not None else last_el
        last_el = p["el"]
    poss.sort(key=lambda p: p["el"])

    # forward-fill logged score
    mp = op = None
    for p in poss:
        if p["mp"] is not None:
            mp, op = p["mp"], p["opp"]
        p["lmp"], p["lopp"] = mp, op

    # final reconciliation: does cumulative opp pts == logged final opp?
    final_cum = poss[-1]["cum"]
    final_logged_opp = next((p["lopp"] for p in reversed(poss) if p["lopp"] is not None), None)

    # per-substitution freshness
    worst_opp_lag = 0
    mp_stale_subs = []
    prev_sub_mp = None
    for i in range(1, len(poss)):
        if poss[i]["lineup"] == poss[i - 1]["lineup"]:
            continue
        b = poss[i - 1]  # last possession of the ending stint
        true_opp = b["cum"]              # opp pts actually scored by the sub
        logged_opp = b["lopp"]           # what was logged
        if logged_opp is not None:
            worst_opp_lag = max(worst_opp_lag, true_opp - logged_opp)
        # Moorpark side: did mp_score advance since the previous sub?
        cur_mp = poss[i]["lmp"]
        if prev_sub_mp is not None and cur_mp is not None and cur_mp == prev_sub_mp:
            mins = ""
            mp_stale_subs.append((poss[i]["half"], poss[i]["clock"] or "??:??", cur_mp))
        prev_sub_mp = cur_mp

    return {
        "final_cum": final_cum, "final_logged_opp": final_logged_opp,
        "opp_reconciles": (final_cum == final_logged_opp),
        "worst_opp_lag": worst_opp_lag,
        "mp_stale": mp_stale_subs,
    }


def main():
    files = sorted(f for f in glob.glob(os.path.join(LOG_DIR, "def_2025-*.csv"))
                   if not f.endswith(".bak"))
    print(f"{'game':<32}{'oppFinal(pts/logged)':>22}{'recon':>7}{'maxOppLag':>11}"
          f"{'MPstaleSubs':>13}")
    print("-" * 96)
    for f in files:
        a = analyze(f)
        name = os.path.basename(f).replace("def_2025-", "").replace(".csv", "")
        recon = "yes" if a["opp_reconciles"] else "NO"
        fin = f"{a['final_cum']}/{a['final_logged_opp']}"
        print(f"{name:<32}{fin:>22}{recon:>7}"
              f"{a['worst_opp_lag']:>11}{len(a['mp_stale']):>13}")
    print("\nopp reconciles = cumulative logged points equal the logged final opponent "
          "score (proof no opponent points were missed).\nmaxOppLag = largest gap "
          "(in pts) between true opp score and the snapshot at a sub.\nMPstaleSubs = "
          "subs where Moorpark's score didn't advance since the prior sub (eyeball "
          "these — can't auto-verify Moorpark's offense from the def log).")
    # detail dump of MP-stale subs (the 'maybe forgot' list)
    print("\n" + "=" * 60 + "\nMoorpark-score 'maybe forgot to update' subs:")
    for f in files:
        a = analyze(f)
        name = os.path.basename(f).replace("def_2025-", "").replace(".csv", "")
        if a["mp_stale"]:
            spots = ", ".join(f"H{h} {c} (MP still {m})" for h, c, m in a["mp_stale"])
            print(f"  {name}: {spots}")


if __name__ == "__main__":
    main()
