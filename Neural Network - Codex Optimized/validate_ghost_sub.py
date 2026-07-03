#!/usr/bin/env python3
"""Validate / recompute the DRIVER CELLS in a per_game_lineups CSV after a
ghost-sub edit.

The leaderboard lineups pipeline recomputes every shooting %, eFG/TS, TO%, ORtg,
DRtg, NET and per-40 rate from the row's RAW COUNTS — so those never need
hand-editing. But three cells are read DIRECTLY from the sheet and an edit has to
keep them consistent, or derived stats silently drift:

  * PPP         -> off_poss = PF / PPP   (the possession count; feeds ORtg/DRtg/NET/Pace)
  * +/-         -> Net/40                 (read straight from the column; Hudl's +/- is
                                           NOT simply PF-PA, so it can't be auto-derived)
  * OREB% / DREB% -> opponent rebounds are back-solved from these, then feed the
                     rebounding rates and reb margins

Usage
-----
  # Validate edited file(s): per-row driver-cell checks + team reconciliation
  python3 validate_ghost_sub.py "internal_data/per_game_lineups/2025-11-19_Palomar_Home.csv"
  python3 validate_ghost_sub.py internal_data/per_game_lineups/*.csv

  # Recompute the cells for ONE edited/added window from its authoritative numbers
  python3 validate_ghost_sub.py --recompute --pf 12 --poss 8 --pa 9 \
        --oreb 2 --opp-dreb 3 --dreb 4 --opp-oreb 1
"""
import csv
import argparse
from pathlib import Path

from compute_moorpark_lineups import C, _num, _is_num, _ft_poss, _parse_pg_name


def _lineup_rows(path):
    raw = list(csv.reader(open(path, encoding="utf-8-sig")))
    out = []
    for ln, row in enumerate(raw[2:], start=3):          # data starts on line 3
        if len(row) <= C["chg"] or not row[0].startswith("#"):
            continue
        if not (_is_num(row[C["mins"]]) and _is_num(row[C["pf"]]) and _is_num(row[C["pa"]])):
            continue
        out.append((ln, row))
    return out


def validate(path):
    p = Path(path)
    try:
        date, opp, venue = _parse_pg_name(p.stem)
    except Exception:
        date = opp = venue = "?"
    rows = _lineup_rows(path)
    print(f"\n=== {p.name}  ({opp} · {venue} · {date}) — {len(rows)} lineups ===")

    flags = []
    t_pf = t_pa = t_poss = t_formula = t_pm = 0.0
    drop_pf = drop_poss = 0.0
    drop_n = 0
    for ln, row in rows:
        g = {k: _num(row[i]) for k, i in C.items()}
        pf, pa, ppp, pm = g["pf"], g["pa"], g["ppp"], g["pm"]
        formula = g["fga"] - g["oreb"] + g["to"] + _ft_poss(g["fta"])   # KenPom poss est.
        stored = pf / ppp if ppp > 0 else formula                       # what the pipeline uses
        dropped = g["mins"] <= 0                                        # pipeline skips these
        if dropped:
            drop_n += 1; drop_pf += pf; drop_poss += stored
        else:
            t_pf += pf; t_pa += pa; t_poss += stored; t_formula += formula; t_pm += pm

        rf = []
        # The pipeline drops mins<=0 rows. That's fine for Hudl sub-minute noise,
        # but if such a row carries POINTS they vanish from the totals — almost
        # always an incomplete ghost-sub add (forgot to set MINS).
        if g["mins"] <= 0 and (pf > 0 or pa > 0):
            rf.append(f"CRITICAL: MINS≤0 but row scores PF={pf:.0f}/PA={pa:.0f} — the pipeline "
                      f"DROPS this row, losing those points. Set MINS to the window length.")
        if ppp <= 0 and pf > 0:
            rf.append("PPP is 0 — off_poss silently falls back to the formula estimate")
        elif stored <= 0 or stored > 2.5 * formula or (formula >= 2 and stored < 0.4 * formula):
            rf.append(f"PPP implies {stored:.1f} poss but formula est. is {formula:.1f} "
                      f"(Δ{stored - formula:+.1f}) — did PPP get updated?")
        if pf != pa and pm == 0:
            rf.append(f"+/- is 0 but PF({pf:.0f})≠PA({pa:.0f}) — missing plus/minus?")
        if g["oreb"] > 0 and g["oreb_pct"] <= 0:
            rf.append("OREB% is 0 but OREB>0 — opp DREB can't be back-solved")
        if g["dreb"] > 0 and g["dreb_pct"] <= 0:
            rf.append("DREB% is 0 but DREB>0 — opp OREB can't be back-solved")
        if not (0 <= g["oreb_pct"] <= 100):
            rf.append(f"OREB% out of range ({g['oreb_pct']})")
        if not (0 <= g["dreb_pct"] <= 100):
            rf.append(f"DREB% out of range ({g['dreb_pct']})")
        if rf:
            flags.append((ln, row[0], rf))

    print(f"  team (counted rows):  ΣPF={t_pf:.0f}  ΣPA={t_pa:.0f}   points margin = {t_pf - t_pa:+.0f}"
          f"   (Σ of +/- column = {t_pm:+.0f})")
    print(f"  poss:  Σ(PF/PPP)={t_poss:.1f}   Σformula={t_formula:.1f}   Δ={t_poss - t_formula:+.1f}")
    if drop_n:
        print(f"  ‼ {drop_n} row(s) with MINS≤0 will be DROPPED by the pipeline "
              f"(removing {drop_pf:.0f} pts / {drop_poss:.1f} poss from the totals above)")
    print(f"         → reconcile counted ΣPF/ΣPA against the official box final score.")
    if not flags:
        print("  ✓ no driver-cell issues")
    else:
        print(f"  ⚠ {len(flags)} row(s) flagged:")
        for ln, label, rf in flags:
            print(f"    line {ln}  {label}")
            for f in rf:
                print(f"        - {f}")
    return len(flags)


def recompute(a):
    print("\n=== recompute driver cells for one edited / added window ===")
    if a.poss and a.poss > 0:
        print(f"  PPP   = {a.pf / a.poss:.3f}     (PF {a.pf:g} ÷ {a.poss:g} possessions)")
        print(f"          → check: PF/PPP = {a.pf / (a.pf / a.poss):.1f} poss ✓")
    else:
        print("  PPP   : pass --poss <possessions in the window> to get PF/poss")
    if a.pa is not None:
        print(f"  +/-   = {a.pf - a.pa:+g}     (points margin PF−PA for the window)")
    if a.oreb is not None and a.opp_dreb is not None:
        den = a.oreb + a.opp_dreb
        print(f"  OREB% = {(a.oreb / den * 100 if den else 0):.1f}     "
              f"(OREB {a.oreb:g} ÷ (OREB + oppDREB {a.opp_dreb:g}))")
    if a.dreb is not None and a.opp_oreb is not None:
        den = a.dreb + a.opp_oreb
        print(f"  DREB% = {(a.dreb / den * 100 if den else 0):.1f}     "
              f"(DREB {a.dreb:g} ÷ (DREB + oppOREB {a.opp_oreb:g}))")
    print("  (FG%/eFG%/TS%/2P/3P/FT%/TO% are recomputed from raw counts — leave them.)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csvs", nargs="*", help="per_game_lineups CSV(s) to validate")
    ap.add_argument("--recompute", action="store_true",
                    help="print the correct PPP / +/- / OREB-pct / DREB-pct for one window")
    ap.add_argument("--pf", type=float, default=0, help="points FOR in the window")
    ap.add_argument("--pa", type=float, default=None, help="points AGAINST in the window")
    ap.add_argument("--poss", type=float, default=0, help="possessions in the window")
    ap.add_argument("--oreb", type=float, default=None)
    ap.add_argument("--opp-dreb", dest="opp_dreb", type=float, default=None)
    ap.add_argument("--dreb", type=float, default=None)
    ap.add_argument("--opp-oreb", dest="opp_oreb", type=float, default=None)
    a = ap.parse_args()

    if a.recompute:
        recompute(a)
        return
    if not a.csvs:
        ap.error("pass a CSV to validate, or --recompute with the window's numbers")
    total = sum(validate(c) for c in a.csvs)
    print(f"\n{'⚠ ' + str(total) + ' flagged row(s) total' if total else '✓ all clean'}")


if __name__ == "__main__":
    main()
