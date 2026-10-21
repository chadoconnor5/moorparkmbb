#!/usr/bin/env python3
"""Publish the team ratings the possession tracker adjusts Moorpark's games against.

Writes ../poss/ratings.json next to the possession tracker: every in-system team's current
opponent-adjusted ORtg / DRtg and four factors (advanced_analytics.json, from
update_advanced_analytics.py), games played, the name aliases, the home-court edge, and
Moorpark's player season lines (all games / quality games, from the public box scores).
These are the leaderboard's own public numbers; no tracker or lineup data goes in.

The teams we play or might play also get their own file, ../poss/teams/<team>.json, listed in ratings.json
under "teamFiles": Moorpark, every team on Moorpark's schedule.json ("scheduled"), and every team in
tracker_teams.txt (potential opponents: a tournament field, one per line, short names like RCC / CCSF work).
Files for teams that drop off both lists are removed.
  team    - its season stats: record, totals and averages for and against (team_summary.json) and the
            season's advanced numbers (advanced_analytics.json, without the per-game lists)
  players - every player: jersey number, box-score season lines (all games / quality games, the same shape
            as Moorpark's playerSeason) and his advanced numbers (eFG%, TS%, usage, ORtg/DRtg, rates...)
  table   - the leaderboard's Team Stats table: its Basic and Advanced rows (load_full_rosters) and each player's
            State Rank on the ranked stats, by the page's own qualification rules, and PORPAGATU! (porp, ranked
            statewide among players with 30%+ of minutes)
The tracker downloads the files for the opponents on its schedule (and keeps them for offline gyms), so an
opponent's five gets the same THIS FIVE labels as ours. Each file is ~10-20 KB.

The tracker downloads it when it opens online, keeps a copy for offline gyms, and
re-adjusts every tracked game against it, so a game from November is always graded against
what that opponent turned out to be. Run it after update_advanced_analytics.py --all;
generate_leaderboard.py runs it at the end of every build.

    python3 export_ratings.py
    python3 export_ratings.py --season 2026-27 --out ../poss/ratings.json
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import update_advanced_analytics as uaa
import adjust_lineups as al
from ccc_config import TRACKER_SEASON

OUT = Path(__file__).resolve().parent.parent / "poss" / "ratings.json"
SLUG = lambda t: re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")


def schedule_opponents(season, team="Moorpark"):
    """The in-system teams on Moorpark's schedule.json for the season (canonical names)."""
    out = []
    for f in Path(f"{season} Teams Schedules").glob(f"*/{team}/schedule.json"):
        try:
            games = json.load(open(f)).get("games") or []
        except (OSError, ValueError):
            continue
        for g in games:
            t = uaa.resolve_opponent(g.get("opponent") or "")
            if t and t != team and t not in out:
                out.append(t)
    return out


TRACKER_TEAMS = Path(__file__).resolve().parent / "tracker_teams.txt"
# Bracket / schedule short names (the tracker's TEAM_ABBR has the same ones).
SHORT = {"rcc": "Riverside", "ccsf": "San Francisco", "sbvc": "San Bernardino Valley", "east la": "East Los Angeles",
         "elac": "East Los Angeles", "west la": "West LA", "wlac": "West LA", "lacc": "Los Angeles City", "smc": "Santa Monica",
         "sbcc": "Santa Barbara", "mt sac": "Mt. San Antonio", "msjc": "Mt. San Jacinto", "avc": "Antelope Valley", "coc": "Canyons",
         "occ": "Orange Coast", "ivc": "Irvine Valley", "lbcc": "Long Beach", "pcc": "Pasadena City", "cos": "Sequoias", "fcc": "Fresno"}


def potential_opponents(ratings, path=TRACKER_TEAMS):
    """tracker_teams.txt: one team per line (# comments ok). Returns (teams found, lines not matched)."""
    found, missing = [], []
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return found, missing
    for ln in lines:
        n = ln.split("#")[0].strip()
        if not n:
            continue
        n2 = SHORT.get(re.sub(r"[.']", "", n).lower().strip(), n)
        t = n2 if n2 in ratings else uaa.resolve_opponent(n2)
        if t and t in ratings:
            if t not in found:
                found.append(t)
        else:
            missing.append(n)
    return found, missing


def _load(p):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return {}


# ---- The leaderboard's Team Stats table (Basic / Advanced, %Poss bands, State Rank rows), for the tracker ----
# Rows come from generate_leaderboard.load_full_rosters() and ranks from its player pool (load_players(), the
# page's DATA) with the page's own rules (TS_RANK_STATS / __tsQualifies / advSchoolNeedsRelaxedCat in
# generate_leaderboard.py) - keep these in step with that JS.
TS_RANK_STATS = [("ind_ortg", "min30", False), ("efg_pct", "cat", False), ("ts_pct", "cat", False),
                 ("oreb_pct", "min30", False), ("dreb_pct", "min30", False), ("ast_rate", "min30", False),
                 ("tov_pct", "min30", True), ("blk_pct", "min30", False), ("stl_pct", "min30", False),
                 ("fc_per_40", "min30", True), ("fd_per_40", "min30", False), ("ft_rate", "cat", False),
                 ("ftp", "cat", False), ("twop", "cat", False), ("tpp", "cat", False)]
ADV_CAT_MIN_PCT = {"efg_pct": 50, "ts_pct": 50, "ft_rate": 50}
ADV_CAT_ATTEMPT_MIN = {"twop": "twoa", "tpp": "tpa", "ftp": "fta"}
ADV_RATE_GP_MIN, ADV_RATE_ATTEMPTS_PER_GAME_MIN, MIN_PCT_QUAL = 20, 2.5, 30
ADV_RELAXED_CAT_KEYS = {"efg_pct", "ts_pct", "ft_rate", "twop", "tpp", "ftp"}
# %Poss bands (the page's TS_USAGE_BANDS): ORtg is ranked within the player's band.
USAGE_BANDS = [28, 24, 20, 16, 12, -1]
usage_band = lambda u: next((i for i, f in enumerate(USAGE_BANDS) if (u or 0) > f), len(USAGE_BANDS) - 1)


def state_ranks(pool):
    """{(name, school): {stat: rank}} plus {stat: number ranked}, as the leaderboard's Team Stats page ranks."""
    import generate_leaderboard as gl
    apg = lambda p, k: (p.get(k) or 0) / p["gp"] if p.get("gp") else 0

    def value(p, k):
        if p.get(k) is not None:
            return p[k]
        fga = p.get("fga") or 0
        if k == "efg_pct" and fga > 0:
            return ((p.get("fgm") or 0) + 0.5 * (p.get("tpm") or 0)) / fga * 100
        if k == "ts_pct":
            d = 2 * (fga + 0.44 * (p.get("fta") or 0))
            return (p.get("pts") or 0) / d * 100 if d > 0 else None
        if k == "ft_rate" and fga > 0:
            return (p.get("fta") or 0) / fga * 100
        return None

    def standard(p, k):
        if (p.get("min_pct") or 0) < ADV_CAT_MIN_PCT.get(k, MIN_PCT_QUAL):
            return False
        a = ADV_CAT_ATTEMPT_MIN.get(k)
        return not (a and (apg(p, a) < ADV_RATE_ATTEMPTS_PER_GAME_MIN or (p.get("gp") or 0) < ADV_RATE_GP_MIN))

    def relaxed(p, k):
        gp_ok = (p.get("gp") or 0) >= ADV_RATE_GP_MIN
        if k == "efg_pct":
            return gp_ok and apg(p, "fga") >= gl.EFG_FGA_PER_GAME_MIN
        if k == "ts_pct":
            return gp_ok and apg(p, "fga") + apg(p, "fta") >= gl.TS_ATT_PER_GAME_MIN
        if k == "ft_rate":
            return gp_ok
        a = ADV_CAT_ATTEMPT_MIN.get(k)
        return bool(a) and gp_ok and apg(p, a) >= ADV_RATE_ATTEMPTS_PER_GAME_MIN

    by_school, cache = {}, {}
    for p in pool:
        by_school.setdefault(p["school"], []).append(p)

    def needs_relaxed(school, k):
        if k not in ADV_RELAXED_CAT_KEYS:
            return False
        if (school, k) not in cache:
            sp = by_school.get(school, [])
            if not any(p.get("region") in ("North", "South") for p in sp):
                cache[(school, k)] = False
            elif sp and all(p.get("fm") for p in sp):
                cache[(school, k)] = True
            else:
                cache[(school, k)] = not any(standard(p, k) and value(p, k) is not None for p in sp)
        return cache[(school, k)]

    def qualifies(p, k, mode):
        if p.get(k) is None:
            return False
        if mode == "cat":
            return relaxed(p, k) if needs_relaxed(p["school"], k) else (p.get("min_pct") or 0) >= 50
        return (p.get("min_pct") or 0) >= 30

    ranks, totals = {}, {}
    for k, mode, asc in TS_RANK_STATS:
        q = [p for p in pool if qualifies(p, k, mode)]
        q.sort(key=lambda p: p[k] if asc else -p[k])   # stable, like the page's Array.sort
        totals[k] = len(q)
        seen = {}
        for i, p in enumerate(q):
            if k == "ind_ortg":   # ORtg: ranked within the player's %Poss band, statewide (the page's __tsUsageBand)
                b = usage_band(p.get("usage_pct"))
                seen[b] = seen.get(b, 0) + 1
                ranks.setdefault((p["name"], p["school"]), {})[k] = seen[b]
                ranks[(p["name"], p["school"])]["ortg_band"] = b
            else:
                ranks.setdefault((p["name"], p["school"]), {})[k] = i + 1
        if k == "ind_ortg":
            totals["ortg_band"] = [seen.get(b, 0) for b in range(len(USAGE_BANDS))]
    return ranks, totals


# ---- Composite role labels: each role blends the related factors, as 0-100 percentiles ----
# A factor is a percentile among the state's qualified players (30%+ of minutes): a ranked stat's State Rank turned
# into "how good" (ORtg within its %Poss band), or a raw share (usage, 3PA rate, attempts a game) by how much.
# When a Synergy export exists for the player (internal_data/synergy_players_<team>_<season>.json, or
# synergy_archetypes.json for Moorpark), its shot-type percentiles (at the rim, 3PT, catch-and-shoot, pull-up; already
# national percentiles) join the blend with their own weights. Each composite has a gate (who it can describe at all)
# and a cut calibrated on the state's box-score scores: the label goes to scores at or past that percentile of the
# gated, qualified pool (top = strengths, weak = shortcomings, scored as 100 - the blend). The tracker reads row["comp"]
# (scores, null when the gate fails) and rankOf["compCut"] (the cuts); sit.js autoLabels holds the why lines.
SYN_KEYS = {"syn_rim": "at_rim_pps_rank", "syn_three": "three_pt_pps_rank", "syn_cs": "catch_shoot_pps_rank",
            "syn_pull": "dribble_jumper_pps_rank"}
_pg = lambda p, k: (p.get(k) or 0) / p["gp"] if p.get("gp") else 0
_rate = lambda p: p["tpa_rate"] if p.get("tpa_rate") is not None else (100 * (p.get("tpa") or 0) / p["fga"] if p.get("fga") else None)
COMPOSITES = {
    # name: (gate, box factors, Synergy factors, cut, weak)
    "interior": (lambda p: (_rate(p) or 100) < 25 and _pg(p, "twoa") >= 3,
                 {"twop": 35, "inside": 20, "ft_rate": 20, "twoa_pg": 15, "oreb_pct": 10}, {"syn_rim": 40}, 0.20, False),
    "shooter": (lambda p: _pg(p, "tpa") >= 2 or (_rate(p) or 0) >= 35,
                {"tpp_vol": 60, "tpa_pg": 20, "tpa_rate": 20}, {"syn_three": 30, "syn_cs": 15, "syn_pull": 10}, 0.35, False),
    "elite_shooter": (lambda p: _pg(p, "tpa") >= 2 or (_rate(p) or 0) >= 35,
                      {"tpp_vol": 80, "tpa_pg": 10, "tpa_rate": 10}, {"syn_three": 30, "syn_cs": 15, "syn_pull": 10}, 0.10, False),   # the elite tier is about accuracy
    "poor3": (lambda p: _pg(p, "tpa") >= 2 or (_rate(p) or 0) >= 35, {"tpp_vol": 100}, {"syn_three": 30, "syn_cs": 10, "syn_pull": 10}, 0.30, True),
    "slasher": (lambda p: (_rate(p) or 100) < 25 and _pg(p, "twoa") >= 2,
                {"ft_rate": 35, "fd_per_40": 30, "twoa_pg": 20, "usage_pct": 15}, {"syn_rim": 25}, 0.25, False),
    "all_around": (lambda p: 25 <= (_rate(p) or 0) <= 55, {"ts_pct": 40, "ft_rate": 30, "balance": 30}, {"syn_rim": 15, "syn_three": 15}, 0.25, False),
    "draws": (lambda p: True, {"fd_per_40": 50, "ft_rate": 50}, {}, 0.20, False),
    "struggles_in": (lambda p: _pg(p, "twoa") >= 3, {"twop": 100}, {"syn_rim": 40}, 0.20, True),
    "eff_role": (lambda p: (p.get("usage_pct") or 99) < 20, {"ind_ortg": 50, "ts_pct": 30, "tov_pct": 20}, {}, 0.10, False),
    "ineff_vol": (lambda p: (p.get("usage_pct") or 0) >= 24, {"ts_pct": 50, "ind_ortg": 30, "tov_pct": 20}, {}, 0.30, True),
    "floor_gen": (lambda p: True, {"ast_rate": 60, "tov_pct": 25, "usage_pct": 15}, {}, 0.10, False),
    "rim_prot": (lambda p: True, {"blk_pct": 75, "dreb_pct": 25}, {}, 0.15, False),
    # Scorer: the volume scoring threat, whatever the style (points produced a game leads; points a game and usage back it)
    "scorer": (lambda p: True, {"pprod_pg": 60, "ppg": 20, "usage_pct": 20}, {}, 0.10, False),
}


def load_synergy(season):
    """{(name, team slug): Synergy shot_types} from every synergy_players_<team>_<season>.json and synergy_archetypes.json."""
    d, out = Path(__file__).resolve().parent / "internal_data", {}
    tag = (season or "").replace("-", "_")
    for f in d.glob(f"synergy_players_*_{tag}.json"):
        slug = f.name[len("synergy_players_"):-len(f"_{tag}.json")]
        for p in _load(f) if isinstance(_load(f), list) else []:
            out[(p["name"], slug)] = p
    a = d / "synergy_archetypes.json"
    if a.exists() and tag == "2025_26":   # the archetypes file is the 2025-26 Moorpark export
        for p in json.load(open(a)):
            out.setdefault((p["name"], SLUG(p.get("team") or "Moorpark")), p)
    return out


def syn_summary(p):
    """The compact Synergy line a team file carries for the why text: shares and FG% (no ranks)."""
    st = p.get("shot_types") or {}
    pt = [m.groups() for m in re.finditer(r"([A-Za-z&/\- ]+?) (\d+)% \(([^,)]*)(?:, ([\d.]+))?", p.get("scoring_summary") or "")]
    return {k: v for k, v in {
        "rim": [st.get("at_rim_pct_fga"), st.get("at_rim_fg_pct")] if st.get("at_rim_fg_pct") is not None else None,
        "three": [st.get("three_pt_att"), st.get("three_pt_fg_pct")] if st.get("three_pt_fg_pct") is not None else None,
        "cs": [st.get("catch_shoot_pct_of_js"), st.get("catch_shoot_fg_pct")] if st.get("catch_shoot_fg_pct") is not None else None,
        "pull": st.get("dribble_jumper_fg_pct"),
        "plays": [[n.strip(), int(s)] for n, s, _, _ in pt[:3]] or None}.items() if v is not None}


def composites(pool, ranks, totals, syn):
    """Adds {"comp": {name: score}} to ranks and {"compCut": {name: cut}} to totals (see COMPOSITES)."""
    qual = [p for p in pool if (p.get("min_pct") or 0) >= MIN_PCT_QUAL and p.get("gp")]

    def pct_of(vals):   # value -> 0-100 percentile (share of the pool at or below it)
        v = sorted(vals)
        n = len(v)
        import bisect
        return lambda x: None if x is None or not n else 100 * bisect.bisect_right(v, x) / n
    raw = {"usage_pct": lambda p: p.get("usage_pct"), "tpa_rate": _rate, "tpa_pg": lambda p: _pg(p, "tpa"),
           "twoa_pg": lambda p: _pg(p, "twoa"), "pprod_pg": lambda p: _pg(p, "pprod") if p.get("pprod") is not None else None,
           "ppg": lambda p: p.get("ppg")}
    pf = {k: pct_of([f(p) for p in qual if f(p) is not None]) for k, f in raw.items()}
    # Low-info players often miss the State Ranks' games bar for these (20 games): their value's percentile among the
    # qualified players stands in for the rank.
    CAT = ["efg_pct", "ts_pct", "ft_rate", "ftp", "twop", "tpp"]
    pcat = {k: pct_of([p[k] for p in qual if p.get(k) is not None]) for k in CAT}
    team_gp = {}
    for p in pool:
        if p.get("gp"):
            team_gp[p["school"]] = max(team_gp.get(p["school"], 0), p["gp"])
    # Volume by rate, so it works from week one: 2+ threes a game or 35%+ of his shots, in half his team's games, 10+ attempts.
    vol3 = lambda p: (p.get("tpa") or 0) >= 10 and p["gp"] >= 0.5 * team_gp.get(p["school"], 0) and (_pg(p, "tpa") >= 2 or (_rate(p) or 0) >= 35)
    shooters = [p for p in qual if vol3(p) and p.get("tpp") is not None]
    tpp_pct = (lambda P: lambda p: P(p.get("tpp")))(pct_of([p["tpp"] for p in shooters]))

    def factors(p):
        rk, f = ranks.get((p["name"], p["school"]), {}), {}
        for k, _, _ in TS_RANK_STATS:
            n = totals["ortg_band"][rk["ortg_band"]] if k == "ind_ortg" and "ortg_band" in rk else totals.get(k)
            if rk.get(k) is not None and n:
                f[k] = 100 * (1 - (rk[k] - 1) / max(1, n - 1))
        for k, fn in raw.items():
            f[k] = pf[k](fn(p))
        if p.get("fm"):
            for k in CAT:
                if f.get(k) is None and p.get(k) is not None:
                    f[k] = pcat[k](p[k])
        # 3P% for the shooting labels: ranked among every volume shooter with 30%+ of minutes (vol3), not only the State
        # Ranks' 50%+ minutes, so bench shooters and sixth men are judged too.
        f["tpp_vol"] = tpp_pct(p) if vol3(p) else None
        if f.get("tpa_rate") is not None:
            f["inside"] = 100 - f["tpa_rate"]
        if _rate(p) is not None:
            f["balance"] = max(0.0, 100 - 4 * abs(_rate(p) - 40))   # 40% threes is the even split; 15% or 65% is none
        s = (syn.get((p["name"], SLUG(p["school"]))) or {}).get("shot_types") or {}
        for k, sk in SYN_KEYS.items():
            if s.get(sk) is not None:
                f[k] = float(s[sk])
        return f

    def blend(f, w, need=0.6):   # weighted mean over the factors he has; None under 60% of the weight (50% low-info)
        have = {k: v for k, v in w.items() if f.get(k) is not None}
        if sum(have.values()) < need * sum(w.values()):
            return None
        return sum(f[k] * v for k, v in have.items()) / sum(have.values())
    F = {(p["name"], p["school"]): factors(p) for p in qual}
    # Players on low-info teams (no reliable minutes) are scored too, on the factors that need no minutes (TS%, 2P%,
    # FT rate, shot diet, 3P%...), against the same cuts; the cuts themselves come from the qualified players only.
    low = [p for p in pool if p.get("fm") and p.get("gp") and p["gp"] >= 0.5 * team_gp.get(p["school"], 0)]
    F.update({(p["name"], p["school"]): factors(p) for p in low})
    cuts = {}
    for name, (gate, box, sw, cut, weak) in COMPOSITES.items():
        box_scores = []
        for p in qual:
            if not gate(p):
                continue
            f = F[(p["name"], p["school"])]
            b = blend(f, box)
            if b is None:
                continue
            box_scores.append(100 - b if weak else b)
            full = blend(f, dict(box, **sw)) if any(f.get(k) is not None for k in sw) else b
            ranks.setdefault((p["name"], p["school"]), {}).setdefault("comp", {})[name] = round(100 - full if weak else full, 1)
        for p in low:
            if not gate(p):
                continue
            f = F[(p["name"], p["school"])]
            full = blend(f, dict(box, **sw), 0.5)   # no minutes: no fouls drawn per 40 or usage, so half the weight will do
            if full is not None:
                ranks.setdefault((p["name"], p["school"]), {}).setdefault("comp", {})[name] = round(100 - full if weak else full, 1)
        box_scores.sort(reverse=True)
        cuts[name] = round(box_scores[max(0, round(cut * len(box_scores)) - 1)], 1) if box_scores else None
    totals["compCut"] = cuts


def box_pct(pool, ranks):
    """rank["box"] for players on low-info teams (no reliable minutes, so no rebound / steal / block / assist rates):
    per-game numbers and minutes-free ratios as percentiles (0-100) against the state's qualified players (30%+ of
    minutes), so the tracker's Rebounder / Ball hawk / Rim protector / Passer / TO-prone use the same cuts.
    tor = turnovers per own possession used (TO / (FGA + 0.44 FTA + TO)); astr = assists per own possession used."""
    import bisect
    team_gp = {}
    for x in pool:
        if x.get("gp"):
            team_gp[x["school"]] = max(team_gp.get(x["school"], 0), x["gp"])
    use = lambda x: (x.get("fga") or 0) / x["gp"] + 0.44 * (x.get("fta") or 0) / x["gp"] + (x.get("topg") or 0)
    stat = {"spg": lambda x: x.get("spg"), "bpg": lambda x: x.get("bpg"), "orpg": lambda x: x.get("orpg"), "drpg": lambda x: x.get("drpg"),
            "apg": lambda x: x.get("apg"), "tor": lambda x: (x.get("topg") or 0) / use(x) if use(x) > 1 else None,
            "astr": lambda x: (x.get("apg") or 0) / use(x) if use(x) > 1 else None}
    qual = [x for x in pool if (x.get("min_pct") or 0) >= MIN_PCT_QUAL and x.get("gp") and not x.get("fm")]
    sv = {k: sorted(v for v in map(f, qual) if v is not None) for k, f in stat.items()}
    for x in pool:
        if not (x.get("fm") and x.get("gp") and x["gp"] >= 0.5 * team_gp[x["school"]]):
            continue
        b = {}
        for k, f in stat.items():
            v = f(x)
            if v is not None and sv[k]:
                b[k] = round(100 * bisect.bisect_right(sv[k], v) / len(sv[k]), 1)
        ranks.setdefault((x["name"], x["school"]), {})["box"] = b


# ---- Sixth man: each team's best bench player (rank["roles"] = ["Sixth man"]) ----
def recent_starts(team, n=10):
    """{player: (starts, games played)} over the team's last n box scores (from the box's starter flags; else the first
    five listed, as _team_games_started does)."""
    import generate_leaderboard as gl
    d = next((p for p in Path(gl.STATS_DIR).glob("*/*") if p.is_dir() and p.name == team), None)
    s = Path(str(d).replace(" Team Statistics", " Teams Schedules")) if d else None
    if not s or not s.exists():
        return {}
    games = []
    for g in sorted(x for x in s.iterdir() if x.is_dir()):
        f = next(iter(sorted(g.glob("*.json"))), None)
        try:
            box = json.load(open(f)) if f else None
        except Exception:
            box = None
        rows = next((r for tn, r in ((box or {}).get("teams") or {}).items() if gl._box_norm(tn) == gl._box_norm(team)), None)
        if rows:
            games.append(rows)
    out = {}
    for rows in games[-n:]:
        flags = any(r.get("is_starter") is not None or r.get("role") for r in rows)
        for i, r in enumerate(rows):
            nm = re.sub(r"^#\d+\s+", "", r.get("name", ""))
            st = bool(r.get("is_starter") or r.get("role") == "starter") if flags else i < 5
            a, b = out.get(nm, (0, 0))
            out[nm] = (a + st, b + 1)
    return out


def sixth_men(pool, ranks, teams):
    """Each team's Sixth man: the bench player who produces. Bench = started 35% or fewer of his games (GS / GP) and 3 or
    fewer of his last 10; a rotation player = in 60%+ of the team's games at 15+ minutes. The best of them by minutes 40 ·
    usage 30 · points produced a game 30 (state percentiles among players with 30%+ of minutes), at 30 or more (a bench
    whose best plays 15 minutes for 4 points has none)."""
    import bisect
    qual = [x for x in pool if (x.get("min_pct") or 0) >= MIN_PCT_QUAL and x.get("gp")]
    f = {"mpg": lambda x: x.get("mpg"), "usage_pct": lambda x: x.get("usage_pct"),
         "pprod_pg": lambda x: _pg(x, "pprod") if x.get("pprod") is not None else None}
    sv = {k: sorted(v for v in map(fn, qual) if v is not None) for k, fn in f.items()}
    pct = lambda x, k: 0 if f[k](x) is None or not sv[k] else 100 * bisect.bisect_right(sv[k], f[k](x)) / len(sv[k])
    score = lambda x: 0.4 * pct(x, "mpg") + 0.3 * pct(x, "usage_pct") + 0.3 * pct(x, "pprod_pg")
    for team in teams:
        T = [x for x in pool if x["school"] == team and x.get("gp")]
        if not T:
            continue
        G, rs = max(x["gp"] for x in T), recent_starts(team)
        bench = [x for x in T if x["gp"] >= 0.6 * G and (x.get("gs") or 0) <= 0.35 * x["gp"] and (x.get("mpg") or 0) >= 15
                 and rs.get(x["name"], (0, 0))[0] <= 3]
        best = max(bench, key=score, default=None)
        if best and score(best) >= 30:
            ranks.setdefault((best["name"], team), {}).setdefault("roles", []).append("Sixth man")


def game_score_pg(x):
    """Hollinger's Game Score per game, from the box score alone (no minutes): every player in the state has one."""
    g = x.get("gp") or 1
    n = lambda k: x.get(k) or 0
    return ((n("pts") + 0.4 * n("fgm") - 0.7 * n("fga") - 0.4 * (n("fta") - n("ftm"))) / g + 0.7 * n("orpg") + 0.3 * n("drpg")
            + n("spg") + 0.7 * n("apg") + 0.7 * n("bpg") - n("topg"))


STAR_TOP = 20


def tiers(pool, ranks, totals):
    """Star: the state's top 20, North and South together, in one list. Analytics players are ranked by PORPAGATU!
    (rank["porp"]); a player on a low-info team (no reliable minutes, so no PORPAGATU!) gets the rank his Game Score per
    game would have among the analytics players (rank["eqr"]). At the same rank the analytics player goes first (his
    number is the better-measured one), then Game Score. rank["tier"] = "Star", rank["srank"] = place on the list."""
    import bisect
    team_gp = {}
    for x in pool:
        if x.get("gp"):
            team_gp[x["school"]] = max(team_gp.get(x["school"], 0), x["gp"])
    played = [x for x in pool if x.get("gp") and x["gp"] >= 0.5 * team_gp[x["school"]]]
    ana = sorted(-game_score_pg(x) for x in played if ranks.get((x["name"], x["school"]), {}).get("porp"))
    eq, gsc = {}, {}
    for x in played:
        key, rk = (x["name"], x["school"]), ranks.get((x["name"], x["school"]), {})
        gsc[key] = game_score_pg(x)
        if rk.get("porp"):
            eq[key] = rk["porp"]
        elif x.get("fm"):
            eq[key] = bisect.bisect_left(ana, -gsc[key]) + 1
            ranks.setdefault(key, {})["eqr"] = eq[key]
            ranks[key]["gsc"] = round(gsc[key], 1)
    order = sorted(eq, key=lambda k: (eq[k], 0 if ranks.get(k, {}).get("porp") else 1, -gsc.get(k, 0)))
    for i, key in enumerate(order[:STAR_TOP]):
        ranks.setdefault(key, {})["tier"] = "Star"
        ranks[key]["srank"] = i + 1
    totals["starTop"] = STAR_TOP


def ft_volume(pool, ranks):
    """rank["ftv"] = 1 for players who get to the line at volume (that he gets there proves he plays, so no minutes bar and
    low-info teams count too), by rate so it works from week one:
    2+ attempts a game, in half or more of his team's games, 10+ attempts. The tracker labels them by fixed FT% (fouling is a
    points decision): FT shooter 75%+ (don't foul him), Bad FT under 65% (foul him). A bench guy who is
    9-for-11 over the season is no volume."""
    team_gp = {}
    for x in pool:
        if x.get("gp"):
            team_gp[x["school"]] = max(team_gp.get(x["school"], 0), x["gp"])
    for x in pool:
        if (x.get("gp") and x.get("ftp") is not None and (x.get("fta") or 0) >= 10
                and x["fta"] / x["gp"] >= 2 and x["gp"] >= 0.5 * team_gp[x["school"]]):
            ranks.setdefault((x["name"], x["school"]), {})["ftv"] = 1


def help_off(pool, ranks):
    """Help off: a starter who doesn't score, so the defense can sag off him from the opening tip to key on their scorers.
    Started 60%+ of his games, in half or more of the team's games, under 5 points a game, and (where usage is known) under
    16% of possessions."""
    games = {}
    for x in pool:
        if x.get("gp"):
            games[x["school"]] = max(games.get(x["school"], 0), x["gp"])
    for x in pool:
        if not x.get("gp") or x["gp"] < 0.5 * games[x["school"]] or (x.get("gs") or 0) < 0.6 * x["gp"]:
            continue
        if (x.get("ppg") or 0) < 5 and (x.get("usage_pct") is None or x["usage_pct"] < 16):
            ranks.setdefault((x["name"], x["school"]), {}).setdefault("roles", []).append("Help off")


def glue_guys(pool, ranks):
    """Glue guy: low usage, low scoring, but does the dirty work. Usage under 17% and top 30% of the state (players with
    30%+ of minutes) in at least three of offensive rebound %, defensive rebound %, steal %, block % and assist rate."""
    import bisect
    qual = [x for x in pool if (x.get("min_pct") or 0) >= MIN_PCT_QUAL and x.get("gp")]
    keys = ["oreb_pct", "dreb_pct", "stl_pct", "blk_pct", "ast_rate"]
    sv = {k: sorted(x[k] for x in qual if x.get(k) is not None) for k in keys}
    pct = lambda x, k: 0 if x.get(k) is None else 100 * bisect.bisect_right(sv[k], x[k]) / len(sv[k])
    for x in qual:
        if (x.get("usage_pct") or 99) < 17 and sum(pct(x, k) >= 70 for k in keys) >= 3:
            ranks.setdefault((x["name"], x["school"]), {}).setdefault("roles", []).append("Glue guy")


_TABLES = None


def leaderboard_tables(teams=()):
    """(full rosters, state ranks, totals) for the leaderboard's current season, built once per export."""
    global _TABLES
    if _TABLES is None:
        import generate_leaderboard as gl
        rosters = gl.load_full_rosters(gl.STATS_DIR)
        pool = gl.load_players()
        # PORPAGATU! (the leaderboard's attach_porpagatu, same team context): each player's value and statewide rank
        # among players with 30%+ of minutes, for the tracker's Star label.
        gl.attach_porpagatu(pool, gl.load_teams())
        ranks, totals = state_ranks(pool)
        q = sorted([p for p in pool if p.get("porp") is not None and (p.get("min_pct") or 0) >= 30], key=lambda p: -p["porp"])
        totals["porp"] = len(q)
        for i, p in enumerate(q):
            ranks.setdefault((p["name"], p["school"]), {})["porp"] = i + 1
        syn = load_synergy(gl._STATS_DIR_TO_SEASON.get(str(gl.STATS_DIR), ""))
        composites(pool, ranks, totals, syn)
        sixth_men(pool, ranks, {x["school"] for x in pool})
        glue_guys(pool, ranks)
        help_off(pool, ranks)
        ft_volume(pool, ranks)
        tiers(pool, ranks, totals)
        box_pct(pool, ranks)
        porp = {(p["name"], p["school"]): p.get("porp") for p in pool}
        for team, r in rosters.items():
            for row in r["players"]:
                row["porp"] = porp.get((row["name"], team))
                sp = syn.get((row["name"], SLUG(team)))
                if sp:
                    row["syn"] = syn_summary(sp)
        _TABLES = (rosters, ranks, totals)
    return _TABLES


def team_file(season, ratings, team):
    """One team's season stats and every player's lines, for the tracker."""
    d = uaa.find_team_stats(team)
    adv, summ = _load(d / "advanced_analytics.json"), _load(d / "team_summary.json")
    t_adv = {k: v for k, v in (adv.get("team") or {}).items() if k not in ("game_ratings", "game_ff")}
    players = al.load_players(season, ratings, team=team)
    for p in adv.get("players") or []:
        n = p.get("name")
        if n in players:
            players[n]["adv"] = {k: v for k, v in p.items() if k != "name"}
    body = {"team": dict({k: summ.get(k) for k in ("games_played", "record", "totals", "averages", "opponent_totals", "opponent_averages") if summ.get(k) is not None},
                         adv=t_adv), "players": players}
    # The leaderboard's Team Stats table for this team: Basic and Advanced rows, each with its State Ranks.
    try:
        rosters, ranks, totals = leaderboard_tables()
        r = rosters.get(team)
        if r:
            body["table"] = {"adv": r["adv"], "rankOf": totals,
                             "rows": [dict(p, rank=ranks.get((p["name"], team), {})) for p in r["players"]]}
    except Exception as ex:   # the table is extra: never lose the rest of the file over it
        print(f"export_ratings: no Team Stats table for {team}: {ex}")
    return body


def export_teams(season, ratings, out_dir, generated, teams):
    """../poss/teams/<team>.json for each of `teams`; other files in the folder are removed. Returns {team: path}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {}
    for t in teams:
        if t not in ratings:
            continue
        body = team_file(season, ratings, t)
        if not body["players"]:
            continue
        f = out_dir / f"{SLUG(t)}.json"
        json.dump(dict({"app": "moorpark-possession-tracker", "kind": "team-file", "version": 1, "name": t, "season": season,
                        "generatedAt": generated, "qualityMargin": al.QUALITY_MARGIN}, **body), open(f, "w"), separators=(",", ":"))
        index[t] = f"{out_dir.name}/{f.name}"
    keep = {Path(p).name for p in index.values()}
    for f in out_dir.glob("*.json"):
        if f.name not in keep:
            f.unlink()
    return index


def export(season=None, out=OUT):
    # Only the tracker's season (ccc_config.TRACKER_SEASON) is ever published. Before it has ratings the files are
    # written empty (and older team files removed), so the iPad never shows another season's numbers.
    season = season or TRACKER_SEASON
    ratings = al.load_ratings(season) if (Path(f"{season} Team Statistics").exists()) else {}
    if not ratings:
        out = Path(out)
        res = {"app": "moorpark-possession-tracker", "kind": "team-ratings", "version": 1,
               "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "season": season,
               "homeAdvantage": uaa.HOME_ADVANTAGE, "qualityMargin": al.QUALITY_MARGIN, "aliases": dict(uaa.OPPONENT_ALIASES),
               "teams": {}, "phase": al.season_phase(), "playerSeason": {}, "scheduled": [], "teamFiles": {}}
        export_teams(season, {}, out.parent / "teams", res["generatedAt"], [])
        out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(res, open(out, "w"), separators=(",", ":"))
        print(f"export_ratings: no {season} ratings yet: wrote an empty {out.name} and cleared the team files (the tracker shows {season} only)")
        return res
    factors = al.load_factors(season)
    teams = {}
    for team in uaa.all_stat_teams():
        p = uaa.find_team_stats(team) / "advanced_analytics.json"
        if team not in ratings or not p.exists():
            continue
        t = json.load(open(p)).get("team", {})
        o, d = ratings[team]
        f = factors.get(team) or {}
        teams[team] = {"ortg": round(o, 2), "drtg": round(d, 2), "games": len(t.get("game_ratings") or []) or None,
                       "ff": {k: f.get(k) for k in ("efg_pct", "tov_pct", "oreb_pct", "dreb_pct", "ft_rate",
                                                     "opp_efg_pct", "opp_tov_pct", "opp_ft_rate") if f.get(k) is not None}}
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sched = schedule_opponents(season)
    extra, missing = potential_opponents(ratings)
    if missing:
        print(f"export_ratings: tracker_teams.txt names not matched to a team: {', '.join(missing)}")
    out = Path(out)
    res = {
        "app": "moorpark-possession-tracker", "kind": "team-ratings", "version": 1,
        "generatedAt": generated,
        "season": season, "homeAdvantage": uaa.HOME_ADVANTAGE, "qualityMargin": al.QUALITY_MARGIN,
        "aliases": dict(uaa.OPPONENT_ALIASES), "teams": teams, "phase": al.season_phase(),
        "playerSeason": al.load_players(season, ratings),
        "scheduled": sched,
        "teamFiles": export_teams(season, ratings, out.parent / "teams", generated, ["Moorpark"] + sched + [t for t in extra if t not in sched]),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out, "w"), separators=(",", ":"))
    print(f"export_ratings: {season}, {len(teams)} teams, {len(res['playerSeason'])} Moorpark players, "
          f"{len(res['teamFiles'])} team files ({len(sched)} on our schedule, {len(extra)} in tracker_teams.txt) -> {out}")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", help="e.g. 2026-27 (default: ccc_config.TRACKER_SEASON)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    export(a.season, a.out)
