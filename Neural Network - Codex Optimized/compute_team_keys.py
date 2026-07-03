#!/usr/bin/env python3
"""
compute_team_keys.py — "Keys to Victory" analysis for CCC teams.

For a given team (optionally pooled across multiple seasons) this:
  1. Builds a per-game metric matrix from game_log.json (team + opponent box
     scores -> rates, four factors, margins).
  2. Ranks every metric by how strongly it separates wins from losses
     (point-biserial r between the metric value and the W/L outcome).
  3. Finds, for each candidate, the threshold + direction (>= / <=) that best
     splits wins from losses (Youden's J on a decision stump).
  4. Selects the top N *non-redundant* "keys" (greedy, dropping metrics highly
     correlated with an already-chosen key).
  5. Builds the targets-hit table: for games hitting 0..N keys, how many games,
     W-L, win%, and avg margin of victory.
  6. Reports the average value in wins vs losses for the full candidate list.

Run with /usr/local/bin/python3 (3.14 + numpy).
"""
from __future__ import annotations
import json
import math
import os
import glob
from dataclasses import dataclass, field

# Seasons we have game logs for (COVID gap: no 2020-21).
SEASONS = ["2017-18", "2018-19", "2019-20", "2021-22", "2022-23",
           "2023-24", "2024-25", "2025-26"]

# EvanMiya default analysis window: the most recent 5 seasons of data
# (the COVID-cancelled 2020-21 is absent, so this spans 2021-22..2025-26).
LAST_5 = SEASONS[-5:]

# Margin metrics (team - opponent) are mechanically tied to the final score —
# "did you outshoot/outrebound your opponent" is ~the definition of winning, so
# they top the W/L correlation for nearly EVERY team and crowd out each team's
# distinctive identity. Excluded from the keys finder (EvanMiya uses one-sided
# stats only, e.g. Twos%/Threes%/Opp TO). They remain in the metric universe.
KEY_EXCLUDE = {"eFG% Margin", "TS% Margin", "3P% Margin", "Reb Margin", "TO Margin"}


# ---------------------------------------------------------------------------
# Per-game metric computation
# ---------------------------------------------------------------------------
def _safe(n, d, scale=1.0):
    return (n / d) * scale if d else 0.0


def _poss(s):
    return (s.get("FGA", 0) - s.get("OREB", 0)) + s.get("TO", 0) + 0.475 * s.get("FTA", 0)


def _empty_box(s) -> bool:
    """True when a team's box totals are an all-zero placeholder (the individual
    box never scraped) — a real played game always has FGA > 0. Such rows give
    garbage metrics (DREB=0, Opp* fine) and must be skipped so the Report matches
    the box-derived Explorer."""
    return (s.get("FGA", 0) or 0) == 0 and (s.get("PTS", 0) or 0) == 0


def game_metrics(ts: dict, os_: dict) -> dict:
    """All candidate 'keys' for a single game, from team + opponent box totals."""
    tp = _poss(ts)
    op = _poss(os_)

    def side(s, p):
        fgm, fga = s.get("FGM", 0), s.get("FGA", 0)
        tpm, tpa = s.get("3PM", 0), s.get("3PA", 0)
        ftm, fta = s.get("FTM", 0), s.get("FTA", 0)
        twom, twoa = fgm - tpm, fga - tpa
        ast, to = s.get("AST", 0), s.get("TO", 0)
        oreb, dreb = s.get("OREB", 0), s.get("DREB", 0)
        return {
            "FG%": _safe(fgm, fga, 100),
            "3P%": _safe(tpm, tpa, 100),
            "2P%": _safe(twom, twoa, 100),
            "FT%": _safe(ftm, fta, 100),
            "eFG%": _safe(fgm + 0.5 * tpm, fga, 100),
            "TS%": _safe(s.get("PTS", 0), 2 * (fga + 0.475 * fta), 100),
            "3PA Rate": _safe(tpa, fga, 100),       # threes taken %
            "FT Rate": _safe(fta, fga, 100),
            "Ast%": _safe(ast, fgm, 100),
            "Ast-TO": _safe(ast, to),
            "TO%": _safe(to, fga + 0.475 * fta + to, 100),
            "Stl": s.get("STL", 0),
            "Blk": s.get("BLK", 0),
            "AST": ast,
            "TO": to,
            "OREB": oreb,
            "DREB": dreb,
            "REB": s.get("REB", 0),
            "3PM": tpm,
            "FTM": ftm,
        }

    t = side(ts, tp)
    o = side(os_, op)
    # Rebound four factors need both sides.
    t_orb = _safe(ts.get("OREB", 0), ts.get("OREB", 0) + os_.get("DREB", 0), 100)
    t_drb = _safe(ts.get("DREB", 0), ts.get("DREB", 0) + os_.get("OREB", 0), 100)

    m = {}
    for k, v in t.items():
        m[k] = round(v, 2) if isinstance(v, float) else v
    for k, v in o.items():
        m[f"Opp {k}"] = round(v, 2) if isinstance(v, float) else v
    m["ORB%"] = round(t_orb, 2)
    m["DRB%"] = round(t_drb, 2)
    m["Reb Margin"] = ts.get("REB", 0) - os_.get("REB", 0)
    m["TO Margin"] = os_.get("TO", 0) - ts.get("TO", 0)   # forcing more than committing = good
    m["eFG% Margin"] = round(t["eFG%"] - o["eFG%"], 2)
    m["TS% Margin"] = round(t["TS%"] - o["TS%"], 2)
    m["3P% Margin"] = round(t["3P%"] - o["3P%"], 2)
    m["Poss"] = round(tp, 1)
    return m


# ---------------------------------------------------------------------------
# Load games
# ---------------------------------------------------------------------------
@dataclass
class Game:
    season: str
    date: str
    opponent: str
    result: int          # 1 win / 0 loss
    margin: int          # team_score - opponent_score
    metrics: dict


def _norm_date(d: str) -> str:
    """'11/1/2025' -> '20251101' for matching box-score folders."""
    try:
        mo, da, yr = d.split("/")
        return f"{int(yr):04d}{int(mo):02d}{int(da):02d}"
    except Exception:
        return ""


def load_bench_pct(team: str, season: str, base_dir=".") -> dict:
    """
    Map normalized date -> bench points % (non-starter PTS / total team PTS)
    for `team` in `season`, read from box scores with `is_starter`.
    Games without starter flags are omitted (caller treats as missing).
    """
    out = {}
    pattern = os.path.join(base_dir, f"{season} Teams Schedules", "**",
                           team, "*", "[0-9]*.json")
    for f in glob.glob(pattern, recursive=True):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        roster = d.get("teams", {}).get(team)
        if not isinstance(roster, list) or not any("is_starter" in p for p in roster):
            continue
        tot = bench = 0
        for p in roster:
            try:
                pts = int(p.get("stats", {}).get("PTS", 0) or 0)
            except (ValueError, TypeError):
                continue
            tot += pts
            if not p.get("is_starter"):
                bench += pts
        if tot <= 0:
            continue
        # date from the file name prefix (YYYYMMDD)
        base = os.path.basename(f)
        key = base[:8] if base[:8].isdigit() else _norm_date(d.get("date", ""))
        if key:
            out[key] = round(100 * bench / tot, 2)
    return out


_BENCH_CACHE: dict = {}


def load_all_bench_pct(season: str, base_dir=".") -> dict:
    """League-wide bench% in a SINGLE pass over the season's box scores.

    Returns {team: {normdate: pct}}. Each box file holds both teams' rosters,
    so one walk covers every team — far cheaper than a recursive glob per team
    (which made the global pool build pathologically slow). Cached per season."""
    ck = (season, base_dir)
    if ck in _BENCH_CACHE:
        return _BENCH_CACHE[ck]
    out: dict = {}
    pattern = os.path.join(base_dir, f"{season} Teams Schedules", "**", "*", "[0-9]*.json")
    for f in glob.glob(pattern, recursive=True):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        teams = d.get("teams")
        if not isinstance(teams, dict):
            continue
        base = os.path.basename(f)
        key = base[:8] if base[:8].isdigit() else _norm_date(d.get("date", ""))
        if not key:
            continue
        for tname, roster in teams.items():
            if not isinstance(roster, list) or not any("is_starter" in p for p in roster):
                continue
            if key in out.get(tname, {}):
                continue  # already computed (box file appears under both teams)
            tot = bench = 0
            for p in roster:
                try:
                    pts = int(p.get("stats", {}).get("PTS", 0) or 0)
                except (ValueError, TypeError):
                    continue
                tot += pts
                if not p.get("is_starter"):
                    bench += pts
            if tot > 0:
                out.setdefault(tname, {})[key] = round(100 * bench / tot, 2)
    _BENCH_CACHE[ck] = out
    return out


def load_team_games(team: str, seasons, base_dir=".", with_bench=True) -> list[Game]:
    games: list[Game] = []
    for season in seasons:
        bench = load_all_bench_pct(season, base_dir).get(team, {}) if with_bench else {}
        pattern = os.path.join(base_dir, f"{season} Team Statistics", "**",
                               team, "game_log.json")
        # A team that switched conference DIVISIONS has duplicate game_log.json
        # files in two folders for a season — dedupe by (date, opponent).
        seen = set()
        for path in glob.glob(pattern, recursive=True):
            data = json.load(open(path))
            for g in data.get("games", []):
                ts, os_ = g.get("team_stats"), g.get("opponent_stats")
                if not ts or not os_:
                    continue
                if _empty_box(ts) or _empty_box(os_):
                    continue
                key = (season, g.get("date", ""), g.get("opponent", ""))
                if key in seen:
                    continue
                seen.add(key)
                res = 1 if g.get("result") == "W" else 0
                m = game_metrics(ts, os_)
                bp = bench.get(_norm_date(g.get("date", "")))
                if bp is not None:
                    m["Bench Pts%"] = bp
                games.append(Game(
                    season=season,
                    date=g.get("date", ""),
                    opponent=g.get("opponent", ""),
                    result=res,
                    margin=g.get("team_score", 0) - g.get("opponent_score", 0),
                    metrics=m,
                ))
    return games


def load_all_games(seasons, base_dir=".", with_bench=False) -> list[Game]:
    """Every team's games across the window — the 'global' peer pool.

    Bench% is skipped by default (it requires per-team box-score parsing and
    isn't needed unless a key is Bench Pts%)."""
    games: list[Game] = []
    for season in seasons:
        # one league-wide bench pass per season (cheap), not per-team globs
        bench_map = load_all_bench_pct(season, base_dir) if with_bench else {}
        seen = set()  # dedupe teams with duplicate game_log files (conf-division moves)
        for path in glob.glob(os.path.join(base_dir, f"{season} Team Statistics",
                                           "**", "game_log.json"), recursive=True):
            data = json.load(open(path))
            tm = data.get("team", "")
            bench = bench_map.get(tm, {})
            for g in data.get("games", []):
                ts, os_ = g.get("team_stats"), g.get("opponent_stats")
                if not ts or not os_:
                    continue
                if _empty_box(ts) or _empty_box(os_):
                    continue
                key = (tm, season, g.get("date", ""), g.get("opponent", ""))
                if key in seen:
                    continue
                seen.add(key)
                m = game_metrics(ts, os_)
                if with_bench:
                    bp = bench.get(_norm_date(g.get("date", "")))
                    if bp is not None:
                        m["Bench Pts%"] = bp
                games.append(Game(
                    season=season, date=g.get("date", ""),
                    opponent=g.get("opponent", ""),
                    result=1 if g.get("result") == "W" else 0,
                    margin=g.get("team_score", 0) - g.get("opponent_score", 0),
                    metrics=m,
                ))
    return games


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------
def point_biserial(values, outcomes):
    """Correlation between a continuous metric and a 0/1 outcome."""
    n = len(values)
    if n < 3:
        return 0.0
    w = [v for v, o in zip(values, outcomes) if o == 1]
    l = [v for v, o in zip(values, outcomes) if o == 0]
    if not w or not l:
        return 0.0
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    if sd == 0:
        return 0.0
    mw, ml = sum(w) / len(w), sum(l) / len(l)
    p, q = len(w) / n, len(l) / n
    return (mw - ml) / sd * math.sqrt(p * q)


def best_threshold(values, outcomes, direction):
    """
    Decision stump maximizing Youden's J (tpr - fpr).
    direction '>=' : meeting target = value >= t ; '<=' : value <= t.
    Returns (threshold, J).
    """
    cands = sorted(set(values))
    if len(cands) < 2:
        return cands[0] if cands else 0.0, 0.0
    # midpoints between distinct values
    mids = [(a + b) / 2 for a, b in zip(cands, cands[1:])]
    npos = sum(outcomes)
    nneg = len(outcomes) - npos
    if npos == 0 or nneg == 0:
        return mids[len(mids) // 2], 0.0
    best, bestJ = mids[0], -1.0
    for t in mids:
        if direction == ">=":
            meets = [(v >= t) for v in values]
        else:
            meets = [(v <= t) for v in values]
        tp = sum(1 for me, o in zip(meets, outcomes) if me and o == 1)
        fp = sum(1 for me, o in zip(meets, outcomes) if me and o == 0)
        J = tp / npos - fp / nneg
        if J > bestJ:
            bestJ, best = J, t
    return best, bestJ


def pearson(a, b):
    n = len(a)
    if n < 3:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else 0.0


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------
@dataclass
class Key:
    metric: str
    direction: str
    target: float
    r: float
    avg_win: float
    avg_loss: float
    j: float


def _key_hits(game: Game, keys: list["Key"]) -> int:
    hit = 0
    for k in keys:
        if k.metric not in game.metrics:
            continue
        v = game.metrics[k.metric]
        if (k.direction == ">=" and v >= k.target) or (k.direction == "<=" and v <= k.target):
            hit += 1
    return hit


def hit_table(games: list[Game], keys: list["Key"], n_targets: int) -> dict:
    """Targets-hit table: per hit-count 0..N → games, w, l, win%, avg MOV."""
    table = {i: {"games": 0, "w": 0, "l": 0, "mov": 0} for i in range(n_targets + 1)}
    for g in games:
        row = table[_key_hits(g, keys)]
        row["games"] += 1
        row["w"] += g.result
        row["l"] += 1 - g.result
        row["mov"] += g.margin
    for row in table.values():
        row["win_pct"] = round(100 * row["w"] / row["games"], 1) if row["games"] else None
        row["avg_mov"] = round(row["mov"] / row["games"], 1) if row["games"] else None
    return table


def analyze(games: list[Game], n_targets=3, redundancy=0.8, global_games=None):
    if not games:
        return None
    outcomes = [g.result for g in games]
    metric_names = list(games[0].metrics.keys())

    candidates = []
    for name in metric_names:
        if name in KEY_EXCLUDE:
            continue
        vals = [g.metrics.get(name, 0) for g in games]
        if len(set(vals)) < 2:
            continue
        r = point_biserial(vals, outcomes)
        direction = ">=" if r >= 0 else "<="
        t, j = best_threshold(vals, outcomes, direction)
        w = [v for v, o in zip(vals, outcomes) if o == 1]
        l = [v for v, o in zip(vals, outcomes) if o == 0]
        candidates.append((Key(
            metric=name, direction=direction, target=round(t, 2),
            r=round(r, 3),
            avg_win=round(sum(w) / len(w), 2) if w else 0.0,
            avg_loss=round(sum(l) / len(l), 2) if l else 0.0,
            j=round(j, 3),
        ), vals))

    # rank by |r|
    candidates.sort(key=lambda c: abs(c[0].r), reverse=True)

    # greedy non-redundant selection
    keys: list[Key] = []
    chosen_vals = []
    for key, vals in candidates:
        if any(abs(pearson(vals, cv)) > redundancy for cv in chosen_vals):
            continue
        keys.append(key)
        chosen_vals.append(vals)
        if len(keys) >= n_targets:
            break

    # targets-hit table (team) + optional global peer table using same keys
    table = hit_table(games, keys, n_targets)
    global_table = hit_table(global_games, keys, n_targets) if global_games else None
    if global_table:
        for i, row in table.items():
            g = global_table[i]
            row["global_win_pct"] = g["win_pct"]
            row["global_avg_mov"] = g["avg_mov"]
            row["global_games"] = g["games"]

    return {
        "keys": keys,
        "all_candidates": [c[0] for c in candidates],
        "targets_table": table,
        "global_table": global_table,
        "n_games": len(games),
        "record": (sum(outcomes), len(outcomes) - sum(outcomes)),
    }


# ---------------------------------------------------------------------------
# Style metrics — curated identity set (EvanMiya "Style Metrics" report)
# ---------------------------------------------------------------------------
# Each is an identity stat; the team-specific target is the cut that best
# separates the team's wins from losses, with a hit/miss split.
STYLE_METRICS = ["Poss", "3PA Rate", "FT Rate", "Ast%", "Bench Pts%"]
STYLE_LABELS = {"Poss": "Pace (Poss)", "3PA Rate": "3PA Rate (3PA/FGA)",
                "FT Rate": "FT Rate (FTA/FGA)", "Ast%": "Assist %",
                "Bench Pts%": "Bench Points %"}


@dataclass
class StyleRow:
    metric: str
    label: str
    direction: str
    target: float
    avg: float                # team's overall average (its identity level)
    hit: dict                 # games/w/l/win_pct/avg_mov when target met
    miss: dict                # when not met


def _split_row(games, predicate):
    g = [x for x in games if predicate(x)]
    if not g:
        return {"games": 0, "w": 0, "l": 0, "win_pct": None, "avg_mov": None}
    w = sum(x.result for x in g)
    return {"games": len(g), "w": w, "l": len(g) - w,
            "win_pct": round(100 * w / len(g), 1),
            "avg_mov": round(sum(x.margin for x in g) / len(g), 1)}


def style_metrics(games: list[Game], limit=2):
    """Curated identity stats, ranked by W/L separation; keep the top `limit`."""
    rows = []
    for name in STYLE_METRICS:
        vals = [g.metrics[name] for g in games if name in g.metrics]
        if len(set(vals)) < 2:
            continue
        sub = [g for g in games if name in g.metrics]
        outcomes = [g.result for g in sub]
        r = point_biserial(vals, outcomes)
        direction = ">=" if r >= 0 else "<="
        t, _ = best_threshold(vals, outcomes, direction)
        t = round(t, 2)
        meets = (lambda g, t=t, d=direction: (g.metrics[name] >= t) if d == ">="
                 else (g.metrics[name] <= t))
        rows.append((abs(r), StyleRow(
            metric=name, label=STYLE_LABELS.get(name, name),
            direction=direction, target=t,
            avg=round(sum(vals) / len(vals), 2),
            hit=_split_row(sub, meets),
            miss=_split_row(sub, lambda g, m=meets: not m(g)),
        )))
    rows.sort(key=lambda x: x[0], reverse=True)
    return [sr for _, sr in rows[:limit]]


# ---------------------------------------------------------------------------
# Serializer for the leaderboard UI
# ---------------------------------------------------------------------------
# Short labels for the metric keys used in the keys/candidate output.
METRIC_LABELS = {
    "eFG% Margin": "eFG% Margin", "TS% Margin": "TS% Margin",
    "3P% Margin": "3P% Margin", "Opp FG%": "Opp FG%", "Opp eFG%": "Opp eFG%",
    "Opp TS%": "Opp TS%", "Opp AST": "Opp Assists", "Opp 2P%": "Opp 2P%",
    "Opp 3P%": "Opp 3P%", "Reb Margin": "Reb Margin", "TO Margin": "TO Margin",
    "AST": "Assists", "Ast%": "Assist %", "FG%": "FG%", "eFG%": "eFG%",
    "TS%": "TS%", "3P%": "3P%", "2P%": "2P%", "REB": "Rebounds",
    "DREB": "Def Rebounds", "OREB": "Off Rebounds", "ORB%": "Off Reb %",
    "DRB%": "Def Reb %", "3PM": "Threes Made", "Bench Pts%": "Bench Points %",
}

# Full natural-language names for the narrative "Key Metrics: X, Y, Z" heading.
LONG_LABELS = {
    "eFG% Margin": "Effective FG% Margin", "TS% Margin": "True Shooting % Margin",
    "3P% Margin": "Three Point % Margin", "Opp FG%": "Opponent Field Goal Percentage",
    "Opp eFG%": "Opponent Effective FG%", "Opp TS%": "Opponent True Shooting %",
    "Opp AST": "Opponent Assists", "Opp 2P%": "Opponent Two Point Percentage",
    "Opp 3P%": "Opponent Three Point Percentage", "Reb Margin": "Rebound Margin",
    "TO Margin": "Turnover Margin", "AST": "Assists", "Ast%": "Assist Percentage",
    "FG%": "Field Goal Percentage", "eFG%": "Effective FG%", "TS%": "True Shooting %",
    "3P%": "Three Point Percentage", "2P%": "Two Point Percentage", "REB": "Total Rebounds",
    "DREB": "Defensive Rebounds", "OREB": "Offensive Rebounds", "ORB%": "Offensive Rebound %",
    "DRB%": "Defensive Rebound %", "3PM": "Threes Made", "Bench Pts%": "Bench Points Percentage",
}


def build_keys(team, seasons=None, base_dir=".", max_targets=3, global_games=None):
    """
    Produce a JSON-serializable dict for the leaderboard 'Keys' panel.

    Embeds the ordered top-N keys, per-game hit flags + values (so the N
    dropdown recomputes the team targets-hit table client-side), precomputed
    GLOBAL targets-hit tables for N=1..max_targets (the league pool isn't
    embedded, so global must be server-computed), the style-metrics report,
    and the full candidate avg-in-wins/avg-in-losses list.
    """
    seasons = seasons or LAST_5
    games = load_team_games(team, seasons, base_dir)
    if not games:
        return None
    res = analyze(games, n_targets=max_targets)
    keys = res["keys"]
    if global_games is None:
        global_games = load_all_games(seasons, base_dir)

    def row(t):
        return {"games": t["games"], "w": t["w"], "l": t["l"],
                "win_pct": t["win_pct"], "avg_mov": t["avg_mov"]}

    # global tables per N (nested: first n keys)
    global_by_n = {}
    for n in range(1, len(keys) + 1):
        gt = hit_table(global_games, keys[:n], n)
        global_by_n[str(n)] = [row(gt[i]) for i in range(n + 1)]

    # per-game records with hit flags + values for the top keys
    game_rows = []
    for g in games:
        hits, vals = [], []
        for k in keys:
            v = g.metrics.get(k.metric)
            vals.append(v)
            hits.append(bool(v is not None and (
                (k.direction == ">=" and v >= k.target) or
                (k.direction == "<=" and v <= k.target))))
        game_rows.append({
            "date": g.date, "season": g.season, "opp": g.opponent,
            "res": g.result, "margin": g.margin, "hits": hits, "vals": vals,
        })

    # global hit/miss split for a single metric+target (for style-metric tables)
    def _global_split(name, direction, target):
        meet, mis = [], []
        for g in global_games:
            v = g.metrics.get(name)
            if v is None:
                continue
            ok = (direction == ">=" and v >= target) or (direction == "<=" and v <= target)
            (meet if ok else mis).append(g)

        def agg(gs):
            if not gs:
                return {"games": 0, "win_pct": None, "avg_mov": None}
            wn = sum(x.result for x in gs)
            return {"games": len(gs), "win_pct": round(100 * wn / len(gs), 1),
                    "avg_mov": round(sum(x.margin for x in gs) / len(gs), 1)}
        return agg(meet), agg(mis)

    style_out = []
    for s in style_metrics(games):
        gh, gm = _global_split(s.metric, s.direction, s.target)
        style_out.append({
            "metric": s.metric, "label": s.label, "dir": s.direction,
            "target": s.target, "avg": s.avg,
            "hit": s.hit, "miss": s.miss,
            "global_hit": gh, "global_miss": gm,
        })

    w, l = res["record"]
    return {
        "team": team,
        "seasons": seasons,
        "window": f"{seasons[0]} to {seasons[-1]}" if len(seasons) > 1 else seasons[0],
        "record": {"w": w, "l": l},
        "n_games": res["n_games"],
        "max_targets": len(keys),
        "keys": [{
            "metric": k.metric, "label": METRIC_LABELS.get(k.metric, k.metric),
            "long": LONG_LABELS.get(k.metric, METRIC_LABELS.get(k.metric, k.metric)),
            "dir": k.direction, "target": k.target, "r": k.r,
            "avg_win": k.avg_win, "avg_loss": k.avg_loss,
        } for k in keys],
        "games": game_rows,
        "global": global_by_n,
        "style": style_out,
        "candidates": [{
            "metric": c.metric, "label": METRIC_LABELS.get(c.metric, c.metric),
            "r": c.r, "avg_win": c.avg_win, "avg_loss": c.avg_loss,
        } for c in res["all_candidates"]],
    }


# ---------------------------------------------------------------------------
# CLI / report
# ---------------------------------------------------------------------------
def print_report(team, seasons, n_targets, base_dir=".", show_global=True):
    games = load_team_games(team, seasons, base_dir)
    global_games = load_all_games(seasons, base_dir) if show_global else None
    res = analyze(games, n_targets=n_targets, global_games=global_games)
    if not res:
        print(f"No games found for {team} in {seasons}")
        return
    w, l = res["record"]
    print(f"\n{'='*70}\n{team}  |  seasons: {', '.join(seasons)}")
    print(f"Record: {w}-{l}  ({res['n_games']} games)\n{'='*70}")

    print(f"\nTOP {n_targets} KEYS (non-redundant, ranked by W/L separation):")
    print(f"{'Metric':<14}{'Target':>10}{'r':>8}{'AvgWin':>9}{'AvgLoss':>9}")
    for k in res["keys"]:
        print(f"{k.metric:<14}{k.direction+' '+str(k.target):>10}{k.r:>8}{k.avg_win:>9}{k.avg_loss:>9}")

    has_global = res.get("global_table") is not None
    print(f"\nTARGETS-HIT TABLE" + ("  (+ global = same keys, all CCC teams):" if has_global else ":"))
    hdr = f"{'Hit':>4}{'Games':>7}{'W':>5}{'L':>5}{'Win%':>8}{'AvgMOV':>9}"
    if has_global:
        hdr += f"{'GblWin%':>9}{'GblMOV':>9}{'GblGms':>8}"
    print(hdr)
    for i in range(n_targets, -1, -1):
        r = res["targets_table"][i]
        wp = r["win_pct"] if r["win_pct"] is not None else "-"
        mv = r["avg_mov"] if r["avg_mov"] is not None else "-"
        line = f"{i}/{n_targets:<2}{r['games']:>5}{r['w']:>5}{r['l']:>5}{str(wp):>8}{str(mv):>9}"
        if has_global:
            gwp = r.get("global_win_pct"); gmv = r.get("global_avg_mov"); gg = r.get("global_games")
            line += f"{str(gwp if gwp is not None else '-'):>9}{str(gmv if gmv is not None else '-'):>9}{str(gg):>8}"
        print(line)

    print(f"\nSTYLE METRICS (team identity — target + hit/miss split):")
    for sr in style_metrics(games):
        print(f"\n  {sr.label}:  avg {sr.avg}   target {sr.direction} {sr.target}")
        print(f"    {'':6}{'Games':>7}{'W':>5}{'L':>5}{'Win%':>8}{'AvgMOV':>9}")
        for lbl, row in (("HIT", sr.hit), ("MISS", sr.miss)):
            wp = row["win_pct"] if row["win_pct"] is not None else "-"
            mv = row["avg_mov"] if row["avg_mov"] is not None else "-"
            print(f"    {lbl:<6}{row['games']:>7}{row['w']:>5}{row['l']:>5}{str(wp):>8}{str(mv):>9}")

    print(f"\nALL CANDIDATE METRICS — avg in wins vs losses (ranked by |r|):")
    print(f"{'Metric':<14}{'r':>8}{'AvgWin':>10}{'AvgLoss':>10}{'Diff':>9}")
    for c in res["all_candidates"]:
        print(f"{c.metric:<14}{c.r:>8}{c.avg_win:>10}{c.avg_loss:>10}{round(c.avg_win-c.avg_loss,2):>9}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", required=True)
    ap.add_argument("--seasons", nargs="+", default=["last5"],
                    help="season list, or 'last5' (default, EvanMiya-style) or 'all'")
    ap.add_argument("--targets", type=int, default=3)
    ap.add_argument("--base-dir", default=".")
    ap.add_argument("--no-global", action="store_true", help="skip global peer columns")
    a = ap.parse_args()
    if a.seasons == ["all"]:
        seasons = SEASONS
    elif a.seasons == ["last5"]:
        seasons = LAST_5
    else:
        seasons = a.seasons
    print_report(a.team, seasons, a.targets, a.base_dir, show_global=not a.no_global)
