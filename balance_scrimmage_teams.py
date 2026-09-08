#!/usr/bin/env python3
"""
Build the most even scrimmage teams from practice tracker data.

Reads tracker/pt_data.json and splits the available players into two sides that
are as close to a coin flip as the data allows.

Why not just use plus/minus: White has won all seven tracked sessions and several
players have been locked to one side the whole fall (Claiborne is 7-for-7 on Black,
Wilson 6-for-6 on White), so raw +/- mostly measures which jersey you were handed.
The player rating here is 70% box-score value per 100 possessions (team independent)
and 30% ridge-regularized adjusted plus/minus, which explicitly solves for a player's
effect with teammates and opponents held constant. Ratings are then shrunk toward the
pool average in proportion to minutes played, so a two-session sample cannot drift far
from average.

Usage:
    python3 balance_scrimmage_teams.py [--exclude "Name One,Name Two"] [--min-minutes N]
"""

import argparse
import itertools
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent / "tracker" / "pt_data.json"

POINTS = {"2fg_make": 2, "3fg_make": 3, "ft_make": 1}

# Value of a non-scoring event, in points. An extra possession is worth roughly one
# point at this scrimmage's efficiency; defensive rebounds and blocks are discounted
# because they are partly credited to the team's scheme rather than the individual.
EVENT_VALUE = {
    "oreb": 0.70, "dreb": 0.30, "ast": 0.50, "tov": -1.00,
    "stl": 1.00, "blk": 0.50, "defl": 0.30, "pf": -0.30,
}

BLEND_BOX = 0.70          # box score share of the rating; the rest is RAPM
SHRINK_K = 45.0           # minutes at which a player is halfway off the pool prior
ESTABLISHED_MIN = 45      # below this a player is a bench unknown, not an opening-five option
ROTATION_WEIGHTS = [1.25, 1.15, 1.05, 1.00, 0.95, 0.90, 0.85, 0.85]


def load_sessions():
    data = json.loads(DATA.read_text())
    sessions = sorted(
        (s for s in data["sessions"] if not s.get("excludeFromStats")),
        key=lambda s: s["date"],
    )
    hidden = {p["name"] for p in data["roster"] if p.get("hidden")}
    return data, sessions, hidden


def build_stints(sessions):
    """Replay each event log, cutting a new stint at every substitution.

    Returns (stints, possessions_on_floor). A stint carries the ten players on the
    court, the points each side scored, and a possession count. Verified against the
    published teamStats: the replayed scores match every session exactly.
    """
    stints, poss_on = [], defaultdict(float)
    for s in sessions:
        on = {"a": set(s["startersA"]), "b": set(s["startersB"])}
        cur = {"a": set(on["a"]), "b": set(on["b"]), "ptsA": 0, "ptsB": 0, "poss": 0.0}

        def close(st):
            if st["poss"] > 0:
                stints.append(st)
                for p in st["a"] | st["b"]:
                    poss_on[p] += st["poss"]

        for e in s["eventLog"]:
            if e.get("type") == "sub":
                close(cur)
                subs = e.get("subs") or [
                    {"team": e["team"], "playerOut": e["playerOut"], "playerIn": e["playerIn"]}
                ]
                for sub in subs:
                    on[sub["team"]].discard(sub["playerOut"])
                    on[sub["team"]].add(sub["playerIn"])
                cur = {"a": set(on["a"]), "b": set(on["b"]), "ptsA": 0, "ptsB": 0, "poss": 0.0}
                continue
            stat, team = e.get("stat"), e.get("team")
            if stat in POINTS:
                cur["ptsA" if team == "a" else "ptsB"] += POINTS[stat]
                if stat != "ft_make":
                    cur["poss"] += 0.5
            elif stat in ("tov", "dreb"):
                cur["poss"] += 0.5      # a turnover or a defensive board ends a possession
        close(cur)
    return stints, poss_on


def box_totals(sessions):
    fields = ["pts", "fga", "fta", "fg3a", "oreb", "dreb", "reb",
              "ast", "tov", "blk", "stl", "defl", "pf", "min"]
    tot = defaultdict(lambda: defaultdict(float))
    games = defaultdict(int)
    for s in sessions:
        for p in s["playerStats"]:
            games[p["name"]] += 1
            for f in fields:
                tot[p["name"]][f] += p.get(f) or 0
    return tot, games


def box_rating(tot, poss_on):
    """Points added per 100 possessions, relative to an average shot at this scrimmage."""
    total_pts = sum(t["pts"] for t in tot.values())
    total_tsa = sum(t["fga"] + 0.44 * t["fta"] for t in tot.values())
    pts_per_attempt = total_pts / total_tsa
    out = {}
    for name, t in tot.items():
        value = t["pts"] - pts_per_attempt * (t["fga"] + 0.44 * t["fta"])
        for stat, weight in EVENT_VALUE.items():
            value += weight * t[stat]
        out[name] = 100.0 * value / poss_on[name] if poss_on.get(name) else 0.0
    return out, pts_per_attempt


def rapm(stints, players, lam=None):
    """Ridge-regularized adjusted plus/minus, possession weighted.

    Each stint is one observation: +1 for the five in white, -1 for the five in black,
    response is point margin per 100 possessions. Ridge keeps the fit stable when two
    players are almost never separated, which is the whole problem with this sample.
    """
    idx = {p: i for i, p in enumerate(players)}
    rows, y, w = [], [], []
    for st in stints:
        row = np.zeros(len(players))
        for p in st["a"]:
            row[idx[p]] += 1
        for p in st["b"]:
            row[idx[p]] -= 1
        rows.append(row)
        y.append(100.0 * (st["ptsA"] - st["ptsB"]) / st["poss"])
        w.append(st["poss"])
    X, y, w = np.array(rows), np.array(y), np.array(w)
    Xw, yw = X * np.sqrt(w)[:, None], y * np.sqrt(w)

    def fit(l, Xm=Xw, ym=yw):
        return np.linalg.solve(Xm.T @ Xm + l * np.eye(len(players)), Xm.T @ ym)

    if lam is None:                                  # leave-one-stint-out cross validation
        best = None
        for candidate in (100, 200, 400, 800, 1500, 3000, 6000, 12000):
            err = 0.0
            for i in range(len(y)):
                keep = np.ones(len(y), bool)
                keep[i] = False
                beta = fit(candidate, X[keep] * np.sqrt(w[keep])[:, None], y[keep] * np.sqrt(w[keep]))
                err += w[i] * (y[i] - X[i] @ beta) ** 2
            mse = err / w.sum()
            if best is None or mse < best[1]:
                best = (candidate, mse)
        lam = best[0]
    beta = fit(lam)
    return {p: beta[idx[p]] for p in players}, lam


def classify(role):
    """Interior orientation: rebounds and blocks up, three-point volume down."""
    lean = role["reb100"] + 4 * role["blk100"] - 9 * role["tp_rate"]
    return "BIG" if lean >= 11 else "WING" if lean >= 5 else "GUARD"


def analyze(exclude=(), min_minutes=0, split_unknowns=False):
    """Rate every available player and rank the splits from most to least even.

    Returns a dict with the ratings, the per-player detail behind them, and the
    candidate splits already ordered. `split_unknowns` forces thin-sample players
    onto opposite teams so the uncertainty does not stack on one side.
    """
    data, sessions, hidden = load_sessions()
    excluded = hidden | {n.strip() for n in exclude if n and n.strip()}

    stints, poss_on = build_stints(sessions)
    tot, games = box_totals(sessions)
    box, pts_per_attempt = box_rating(tot, poss_on)
    everyone = sorted(poss_on)
    adj, lam = rapm(stints, everyone)

    pool = [p for p in everyone
            if p not in excluded and tot[p]["min"] >= min_minutes]
    if len(pool) < 4:
        raise SystemExit("not enough players to build two teams")

    mins = {p: tot[p]["min"] for p in pool}
    raw = {p: BLEND_BOX * box[p] + (1 - BLEND_BOX) * adj[p] for p in pool}
    prior = float(np.mean([raw[p] for p in pool if mins[p] >= ESTABLISHED_MIN] or list(raw.values())))
    # Regress toward the pool average by minutes played, so 0.00 means "average for this group".
    rate = {p: mins[p] * (raw[p] - prior) / (mins[p] + SHRINK_K) for p in pool}

    role, pos = {}, {}
    for p in pool:
        t, pp = tot[p], max(poss_on[p], 1)
        role[p] = dict(
            pts100=100 * t["pts"] / pp, reb100=100 * t["reb"] / pp,
            ast100=100 * t["ast"] / pp, blk100=100 * t["blk"] / pp,
            stl100=100 * (t["stl"] + t["defl"]) / pp,
            usg=100 * (t["fga"] + 0.44 * t["fta"] + t["tov"]) / pp,
            tp_rate=t["fg3a"] / t["fga"] if t["fga"] else 0.0,
            ts=t["pts"] / (2 * (t["fga"] + 0.44 * t["fta"])) if (t["fga"] + 0.44 * t["fta"]) else 0.0,
        )
        pos[p] = classify(role[p])

    established = {p for p in pool if mins[p] >= ESTABLISHED_MIN}
    comps = {p: dict(reb=role[p]["reb100"], ast=role[p]["ast100"],
                     shoot=role[p]["pts100"] * role[p]["ts"],
                     stocks=role[p]["stl100"] + role[p]["blk100"], usg=role[p]["usg"])
             for p in pool}
    keys = ["reb", "ast", "shoot", "stocks", "usg"]
    spread = {k: np.std([comps[p][k] for p in pool]) or 1.0 for k in keys}

    def opening_five(team):
        legal = [(sum(rate[p] for p in c), c) for c in itertools.combinations(team, 5)
                 if all(p in established for p in c)
                 and any(pos[p] == "BIG" for p in c) and any(pos[p] == "GUARD" for p in c)]
        return max(legal, key=lambda x: x[0]) if legal else (None, None)

    def rotation(team):
        """Expected points per 100 possessions from the five on the floor, minutes weighted.
        Unknowns sort to the back of the rotation rather than into the opening five."""
        order = sorted(team, key=lambda p: (-(rate[p] if p in established else -99), p))
        w = ROTATION_WEIGHTS[:len(order)]
        w = [x / sum(w) * len(order) for x in w]
        return 5 * sum(rate[p] * wi for p, wi in zip(order, w)) / len(order)

    def role_gap(a, b):
        pen = sum((abs(sum(comps[p][k] for p in a) / len(a)
                       - sum(comps[p][k] for p in b) / len(b)) / spread[k]) ** 2 for k in keys)
        for group in ("BIG", "WING", "GUARD"):
            ca = sum(pos[p] == group for p in a)
            cb = sum(pos[p] == group for p in b)
            pen += 0.35 * (ca * len(b) - cb * len(a)) ** 2 / (len(a) * len(b))
        return pen

    size = len(pool) // 2
    anchor, rest = pool[0], pool[1:]
    unknown = {p for p in pool if p not in established}
    splits, seen = [], set()
    for combo in itertools.combinations(rest, size - 1):
        team_a = frozenset((anchor,) + combo)
        if team_a in seen:
            continue
        seen.add(team_a)
        team_b = frozenset(p for p in pool if p not in team_a)
        if split_unknowns and len(unknown) == 2 and len(unknown & team_a) != 1:
            continue
        fa, five_a = opening_five(team_a)
        fb, five_b = opening_five(team_b)
        if five_a is None or five_b is None:
            continue
        ra, rb = rotation(team_a), rotation(team_b)
        splits.append(dict(a=team_a, b=team_b, five_a=five_a, five_b=five_b,
                           rot=abs(ra - rb), start=abs(fa - fb), ra=ra, rb=rb, fa=fa, fb=fb))
    if not splits:
        raise SystemExit("no split leaves both sides a legal opening five")

    # Even rotations and even opening fives both matter; role balance breaks the near ties.
    for s in splits:
        s["obj"] = s["rot"] ** 2 + (0.55 * s["start"]) ** 2
    splits.sort(key=lambda s: s["obj"])
    tier = [s for s in splits if s["obj"] <= splits[0]["obj"] + 0.55]
    tier.sort(key=lambda s: role_gap(s["a"], s["b"]))
    for s in tier:
        s["role"] = role_gap(s["a"], s["b"])

    return dict(sessions=sessions, stints=stints, pool=pool, rate=rate, pos=pos, role=role,
                mins=mins, games=games, box=box, rapm=adj, lam=lam, excluded=excluded, hidden=hidden,
                established=established, comps=comps, keys=keys,
                pts_per_attempt=pts_per_attempt, splits=tier, rotation=rotation)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude", default="", help="comma separated names to leave out")
    ap.add_argument("--min-minutes", type=int, default=0,
                    help="only consider players with at least this many practice minutes")
    ap.add_argument("--options", type=int, default=2, help="how many splits to print")
    ap.add_argument("--split-unknowns", action="store_true",
                    help="keep the two thin-sample players on opposite teams")
    args = ap.parse_args()

    r = analyze(args.exclude.split(","), args.min_minutes, args.split_unknowns)
    sessions, pool, rate, pos = r["sessions"], r["pool"], r["rate"], r["pos"]
    established, comps, keys = r["established"], r["comps"], r["keys"]

    print(f"{len(sessions)} sessions ({sessions[0]['date']} to {sessions[-1]['date']}), "
          f"{len(r['stints'])} stints, {sum(s['poss'] for s in r['stints']):.0f} possessions")
    print(f"baseline {r['pts_per_attempt']:.3f} pts per true-shooting attempt | RAPM lambda {r['lam']}")
    print(f"excluded: {', '.join(sorted(r['excluded'])) or 'none'}")
    print(f"\n{'Player':26}{'G':>3}{'MIN':>5}{'pos':>7}{'Box/100':>9}{'RAPM':>7}{'RATING':>8}")
    print("-" * 65)
    for p in sorted(pool, key=lambda x: -rate[x]):
        flag = " ~" if p not in established else ""
        print(f"{p:26}{r['games'][p]:>3}{r['mins'][p]:>5.0f}{pos[p]:>7}"
              f"{r['box'][p]:>+9.1f}{r['rapm'][p]:>+7.1f}{rate[p]:>+8.2f}{flag}")
    print("~ = thin sample, regressed hard toward the pool average")

    for n, s in enumerate(r["splits"][:args.options], 1):
        a = sorted(s["a"], key=lambda p: (p not in s["five_a"], -rate[p]))
        b = sorted(s["b"], key=lambda p: (p not in s["five_b"], -rate[p]))
        print(f"\n{'=' * 78}\nOPTION {n}   rotation gap {s['rot']:.2f} | "
              f"opening-five gap {s['start']:.2f} | role gap {s['role']:.2f}\n{'=' * 78}")
        print(f"  {'WHITE':<26}{'pos':<7}{'rtg':>6}   | {'BLACK':<26}{'pos':<7}{'rtg':>6}")
        for i in range(max(len(a), len(b))):
            def cell(team, i):
                if i >= len(team):
                    return " " * 40
                p = team[i]
                mark = "~" if p not in established else " "
                return f"{p + mark:<26}{pos[p]:<7}{rate[p]:>+6.2f} "
            print(f"  {cell(a, i)}{' S |' if i < 5 else '   |'} {cell(b, i)}")
        print("  " + "-" * 76)
        for k in keys:
            va = sum(comps[p][k] for p in s["a"]) / len(s["a"])
            vb = sum(comps[p][k] for p in s["b"]) / len(s["b"])
            print(f"    {k:7} per player   W {va:>6.1f}   B {vb:>6.1f}   diff {va - vb:>+6.1f}")
        counts = lambda t: "/".join(str(sum(pos[p] == g for p in t)) for g in ("BIG", "WING", "GUARD"))
        print(f"    {'pos':7}              W {counts(s['a']):>6}   B {counts(s['b']):>6}   (BIG/WING/GUARD)")
        print(f"    opening five   W {s['fa']:+6.2f}  B {s['fb']:+6.2f}"
              f"   ->{0.35 * (s['fa'] - s['fb']):+5.1f} pts over 35 possessions")
        print(f"    full rotation  W {s['ra']:+6.2f}  B {s['rb']:+6.2f}"
              f"   ->{0.35 * (s['ra'] - s['rb']):+5.1f} pts over 35 possessions")


if __name__ == "__main__":
    main()
