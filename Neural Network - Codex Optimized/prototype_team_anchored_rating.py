#!/usr/bin/env python3
"""PROTOTYPE: team-anchored box rating ("Box BPR for CCC").

EvanMiya's Box BPR trains box-score weights to predict a ground-truth impact
target (RAPM from play-by-play). We have no PBP, but we DO have an opponent-
adjusted team net rating per team-season -- a coarse but legitimate stand-in.

So: regress team net rating on each team's minutes-weighted aggregate of the
per-100 box rates the BPM model already computes, learn CCC-specific weights,
then apply those weights at the player level. Reports honest out-of-sample fit
(leave-one-season-out CV) and shows the player leaderboard before/after.

Test harness only -- not wired into the build.
Run: /usr/local/bin/python3 prototype_team_anchored_rating.py
"""
import csv
import glob
import os
import numpy as np

SEASONS = ["2017-18", "2018-19", "2019-20", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
FEATURES = ["adj_pts_per100", "ast_per100", "reb_per100", "stl_per100", "blk_per100", "to_per100"]


def team_nets(season):
    out = {}
    for aa in glob.glob(f"{season} Team Statistics/**/advanced_analytics.json", recursive=True):
        import json
        try:
            t = json.load(open(aa)).get("team", {})
        except Exception:
            continue
        out[os.path.basename(os.path.dirname(aa))] = t.get("net_rtg")
    return out


def load_players(season):
    path = f"internal_data/ccc_bpm_{season.replace('-', '_')}.csv"
    if not os.path.exists(path):
        return []
    rows = []
    for r in csv.DictReader(open(path)):
        try:
            feat = [float(r[f]) for f in FEATURES]
            mn = float(r.get("minutes") or 0)
            bpm = float(r.get("bpm"))
        except (KeyError, TypeError, ValueError):
            continue
        if mn <= 0:
            continue
        rows.append({"team": r["team"], "player": r["player"], "season": season,
                     "min": mn, "bpm": bpm, "feat": feat,
                     "qual": str(r.get("qualifies_minutes", "")).lower() == "true"})
    return rows


def team_aggregate(rows, nets):
    """One row per team-season: minutes-weighted mean of features, target = net."""
    X, y, keys = [], [], []
    by_team = {}
    for r in rows:
        by_team.setdefault(r["team"], []).append(r)
    for team, plist in by_team.items():
        net = nets.get(team)
        if net is None:
            continue
        tot = sum(p["min"] for p in plist)
        if tot <= 0:
            continue
        agg = [sum(p["feat"][i] * p["min"] for p in plist) / tot for i in range(len(FEATURES))]
        X.append(agg)
        y.append(float(net))
        keys.append((rows[0]["season"], team))
    return np.array(X), np.array(y), keys


def fit(X, y):
    """OLS with intercept. Returns (coef, intercept)."""
    A = np.hstack([X, np.ones((len(X), 1))])
    sol, *_ = np.linalg.lstsq(A, y, rcond=None)
    return sol[:-1], sol[-1]


def corr(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return float(np.corrcoef(a, b)[0, 1])


def main():
    # Gather team-aggregate rows per season; keep player rows for leaderboard.
    all_X, all_y = [], []
    season_data = {}
    for s in SEASONS:
        rows = load_players(s)
        nets = team_nets(s)
        X, y, keys = team_aggregate(rows, nets)
        if len(X) == 0:
            continue
        season_data[s] = {"rows": rows, "nets": nets, "X": X, "y": y}
        all_X.append(X)
        all_y.append(y)
    all_X = np.vstack(all_X)
    all_y = np.concatenate(all_y)
    n_teams = len(all_y)

    # ---- Baseline: how well does current minutes-weighted team BPM track net? ----
    base_pred, base_actual = [], []
    for s, d in season_data.items():
        by_team = {}
        for r in d["rows"]:
            by_team.setdefault(r["team"], []).append(r)
        for team, plist in by_team.items():
            net = d["nets"].get(team)
            if net is None:
                continue
            tot = sum(p["min"] for p in plist)
            if tot <= 0:
                continue
            base_pred.append(sum(p["bpm"] * p["min"] for p in plist) / tot)
            base_actual.append(float(net))
    base_corr = corr(base_pred, base_actual)

    # ---- In-sample fit of the team-anchored model ----
    coef, intercept = fit(all_X, all_y)
    in_pred = all_X @ coef + intercept
    ss_res = float(np.sum((all_y - in_pred) ** 2))
    ss_tot = float(np.sum((all_y - all_y.mean()) ** 2))
    r2_in = 1 - ss_res / ss_tot
    corr_in = corr(in_pred, all_y)

    # ---- Honest out-of-sample: leave-one-season-out CV ----
    cv_pred, cv_actual = [], []
    for hold in season_data:
        tr_X = np.vstack([season_data[s]["X"] for s in season_data if s != hold])
        tr_y = np.concatenate([season_data[s]["y"] for s in season_data if s != hold])
        c, b = fit(tr_X, tr_y)
        p = season_data[hold]["X"] @ c + b
        cv_pred.extend(p.tolist())
        cv_actual.extend(season_data[hold]["y"].tolist())
    cv_corr = corr(cv_pred, cv_actual)
    cv_r2 = 1 - np.sum((np.array(cv_actual) - np.array(cv_pred)) ** 2) / \
            np.sum((np.array(cv_actual) - np.mean(cv_actual)) ** 2)

    print("=" * 70)
    print("TEAM-ANCHORED BOX RATING  (regress team net_rtg on team box rates)")
    print(f"Fit on {n_teams} team-seasons across {len(season_data)} seasons")
    print("=" * 70)
    print("\nLearned weights (points/100 of team net per unit of per-100 box rate):")
    for f, c in zip(FEATURES, coef):
        print(f"   {f:<16} {c:+.3f}")
    print(f"   {'(intercept)':<16} {intercept:+.3f}")

    print("\n--- TEAM-LEVEL RECONCILIATION (corr of minutes-wtd team rating vs net) ---")
    print(f"   BEFORE  current BPM 2.0:        {base_corr:.3f}")
    print(f"   AFTER   team-anchored (in-samp): {corr_in:.3f}   (R^2={r2_in:.3f})")
    print(f"   AFTER   team-anchored (LOSO CV): {cv_corr:.3f}   (R^2={cv_r2:.3f})  <- honest")

    # ---- Apply weights to players; compare leaderboards (2025-26 qualified) ----
    s = "2025-26"
    rows = [r for r in season_data[s]["rows"] if r["qual"]]
    # center the anchored player rating so the league (minutes-wtd) mean is ~0
    raw = {id(r): float(np.dot(r["feat"], coef) + intercept) for r in rows}
    tot_min = sum(r["min"] for r in rows)
    mean_anchor = sum(raw[id(r)] * r["min"] for r in rows) / tot_min
    for r in rows:
        r["anchor"] = raw[id(r)] - mean_anchor

    def table(key, label):
        top = sorted(rows, key=lambda r: -r[key])[:15]
        print(f"\nTop 15 by {label} (2025-26 qualified):")
        for i, r in enumerate(top, 1):
            print(f"  {i:2d}. {r['player']:<22} {r['team']:<18} "
                  f"BPM {r['bpm']:+5.1f}   anchored {r['anchor']:+5.1f}")
    table("bpm", "current BPM 2.0")
    table("anchor", "team-anchored rating")

    # biggest movers
    ranks_bpm = {id(r): i for i, r in enumerate(sorted(rows, key=lambda r: -r["bpm"]))}
    ranks_anc = {id(r): i for i, r in enumerate(sorted(rows, key=lambda r: -r["anchor"]))}
    movers = sorted(rows, key=lambda r: ranks_bpm[id(r)] - ranks_anc[id(r)])
    print("\nBiggest RISERS under team-anchored vs BPM (rank improvement):")
    for r in movers[:6]:
        print(f"   {r['player']:<22} {r['team']:<18} BPM#{ranks_bpm[id(r)]+1} -> anc#{ranks_anc[id(r)]+1}")
    print("Biggest FALLERS:")
    for r in movers[-6:][::-1]:
        print(f"   {r['player']:<22} {r['team']:<18} BPM#{ranks_bpm[id(r)]+1} -> anc#{ranks_anc[id(r)]+1}")


if __name__ == "__main__":
    main()
