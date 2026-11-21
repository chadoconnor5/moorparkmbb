"""Record Book (leaderboard Misc -> Record Book): statewide and per-team records from every box score, 2017-18 on.

Two periods: all-time (every season we have) and each season. Groups:
    Individual   single game (box score lines) · season totals / per game · career totals / per game (all-time only:
                 the same name on the same team)
    Team         single game · season totals / per game
Every basic box-score stat (points, FGM, FGA, 3PM, 3PA, FTM, FTA, OREB, DREB, REB, AST, STL, BLK, TO, PF) plus the
three shooting percentages for seasons and careers, and team wins / win % / points allowed / margin. Minutes are left
out: many box scores carry placeholder minutes.

Each list keeps the top TOP and every tie at the cut (up to TIE_MAX). Players are told apart by team and exact name
(after "#4" / "LAST,FIRST" clean-up): no spelling merges, so Dayvon Gates (Mt. San Antonio) and Dayvion Gates (Canyons)
stay two players, and a misspelt box line splits a player. A "career" past MAX_CAREER_G games or 3 seasons is two
players sharing a name and is left out. Box lines past SANE / SANE_TEAM are typos (2/13/2023 Shasta: 61 assists).

Output, one lazy file each in ../season_data: records_state.js and records_<team slug>.js
({cats, periods, lists: {period: {cat: rows}}}); the state file also lists the teams and their slugs.

    python3 record_book.py            # prints each category's all-time statewide #1
"""
import json
import math
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEASONS = ["2017-18", "2018-19", "2019-20", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "2026-27"]
TOP = 10
TIE_MAX = 25
FULL_G = 28

STATS = ["PTS", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF"]
LABEL = {"PTS": "Points", "FGM": "Field goals made", "FGA": "Field goals attempted", "3PM": "3-pointers made",
         "3PA": "3-pointers attempted", "FTM": "Free throws made", "FTA": "Free throws attempted",
         "OREB": "Offensive rebounds", "DREB": "Defensive rebounds", "REB": "Rebounds", "AST": "Assists",
         "STL": "Steals", "BLK": "Blocks", "TO": "Turnovers", "PF": "Personal fouls"}
# shooting percentages: (made, attempts, attempts needed over a full season, for a career)
PCTS = {"FG%": ("FGM", "FGA", 150, 250), "3P%": ("3PM", "3PA", 60, 100), "FT%": ("FTM", "FTA", 60, 100)}
TEAM_RENAME = {"West Hills Coalinga": "Coalinga", "West Hills Lemoore": "Lemoore"}
SANE = {"PTS": 75, "FGM": 30, "FGA": 50, "3PM": 16, "3PA": 30, "FTM": 30, "FTA": 35, "OREB": 20, "DREB": 28,
        "REB": 35, "AST": 25, "STL": 14, "BLK": 15, "TO": 15, "PF": 6}
SANE_TEAM = {"PTS": 170, "FGM": 70, "FGA": 120, "3PM": 30, "3PA": 70, "FTM": 60, "FTA": 75, "OREB": 40, "DREB": 65,
             "REB": 85, "AST": 45, "STL": 35, "BLK": 22, "TO": 45, "PF": 45}
MIN_G_SEASON = 10        # all-time per-game season records; a season's own list pro-rates it
MIN_G_CAREER = 20
MIN_G_TEAM = 15
MAX_CAREER_G = 72


def _i(v):
    try:
        return int(str(v).strip() or 0)
    except ValueError:
        return 0


def _pair(v):
    m = re.match(r"\s*(\d+)\s*-\s*(\d+)", str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _line(stats):
    fg, tp, ft = _pair(stats.get("FGM-A")), _pair(stats.get("3PM-A")), _pair(stats.get("FTM-A"))
    o, d = _i(stats.get("OREB")), _i(stats.get("DREB"))
    return {"PTS": _i(stats.get("PTS")), "FGM": fg[0], "FGA": fg[1], "3PM": tp[0], "3PA": tp[1], "FTM": ft[0],
            "FTA": ft[1], "OREB": o, "DREB": d, "REB": _i(stats.get("REB")) or o + d, "AST": _i(stats.get("AST")),
            "STL": _i(stats.get("STL")), "BLK": _i(stats.get("BLK")), "TO": _i(stats.get("TO")),
            "PF": _i(stats.get("PF"))}


def _name(raw):
    n = re.sub(r"^#\s*\d+\s*", "", str(raw or "")).strip()
    n = re.sub(r"^(?:(?:[GFC]|PG|SG|SF|PF|G/F|F/C)\s+)?\d+\s+", "", n, flags=re.I)      # "g 00 Uriyah Rojas"
    n = re.sub(r"\s*\(.*?\)\s*", " ", n).strip()
    if "," in n:                                                           # LAST,FIRST
        last, first = [x.strip() for x in n.split(",", 1)]
        n = f"{first} {last}".strip()
    return " ".join(w.capitalize() if (w.isupper() and len(w) > 2) or w.islower() else w for w in n.split())


def _key(name):
    return re.sub(r"[^a-z]", "", name.lower())


def _date(folder, raw):
    m = re.match(r"(\d{4})(\d{2})(\d{2})", folder)
    return f"{int(m.group(2))}/{int(m.group(3))}/{m.group(1)}" if m else str(raw or "")


def slug(team):
    return re.sub(r"[^a-z0-9]+", "_", team.lower()).strip("_")


class Top:
    """A category's list: the top TOP and the ties at the cut (to TIE_MAX); pruned as rows come in."""
    __slots__ = ("rows", "low")

    def __init__(self):
        self.rows, self.low = [], False

    def add(self, val, row):
        self.rows.append((val, row))
        if len(self.rows) > 4 * TIE_MAX:
            self.rows = self._cut()

    def _cut(self):
        rs = sorted(self.rows, key=lambda r: r[0] if self.low else -r[0])
        if len(rs) > TOP:
            cut = rs[TOP - 1][0]
            rs = [r for i, r in enumerate(rs) if i < TOP or (r[0] == cut and i < TIE_MAX)]
        return rs

    def out(self):
        return [[v] + row for v, row in self._cut()]


def _cats():
    c = []
    for s in STATS:
        c.append(("ig_" + s, "Individual · Single game", LABEL[s]))
    for s in STATS:
        c.append(("is_" + s, "Individual · Season", LABEL[s]))
    for s in STATS:
        c.append(("ipg_" + s, "Individual · Season per game", LABEL[s] + " per game"))
    for lab in PCTS:
        c.append(("ipct_" + lab, "Individual · Season per game", lab))
    for s in STATS:
        c.append(("ic_" + s, "Individual · Career", LABEL[s]))
    c.append(("ic_G", "Individual · Career", "Games played"))
    for s in STATS:
        c.append(("icpg_" + s, "Individual · Career per game", LABEL[s] + " per game"))
    for lab in PCTS:
        c.append(("icpct_" + lab, "Individual · Career per game", lab))
    c += [("tg_PTS", "Team · Single game", "Points"), ("tg_low_PA", "Team · Single game", "Fewest points allowed"),
          ("tg_margin", "Team · Single game", "Margin of victory")]
    for s in STATS[1:]:
        c.append(("tg_" + s, "Team · Single game", LABEL[s]))
    c += [("ts_W", "Team · Season", "Wins"), ("ts_PTS", "Team · Season", "Points")]
    for s in STATS[1:]:
        c.append(("ts_" + s, "Team · Season", LABEL[s]))
    c += [("tspg_winpct", "Team · Season per game", "Win %"), ("tspg_PTS", "Team · Season per game", "Points per game"),
          ("tspg_low_PA", "Team · Season per game", "Fewest points allowed per game"),
          ("tspg_margin", "Team · Season per game", "Scoring margin")]
    for s in STATS[1:]:
        c.append(("tspg_" + s, "Team · Season per game", LABEL[s] + " per game"))
    return c


def build():
    from generate_team_stats import _find_team_key
    from update_advanced_analytics import resolve_opponent
    lists = defaultdict(Top)          # (scope, period, cat) -> Top; scope "" = statewide

    def put(cat, tm, period, val, row, periods=None):
        for scope in ("", tm):
            for per in periods or (("all", period) if period else ("all",)):
                t = lists[(scope, per, cat)]
                t.low = "_low_" in cat
                t.add(val, row)

    career = defaultdict(lambda: {"G": 0, "seasons": set(), "name": "", **{s: 0 for s in STATS}})
    teams = set()
    for season in SEASONS:
        sched = HERE / f"{season} Teams Schedules"
        if not sched.exists():
            continue
        pseason = defaultdict(lambda: {"G": 0, "name": "", **{s: 0 for s in STATS}})
        tseason = defaultdict(lambda: {"G": 0, "W": 0, "L": 0, "PA": 0, **{s: 0 for s in STATS}})
        seen = set()
        for f in sorted(sched.glob("*/*/*/*.json")):
            folder_team, folder = f.parent.parent.name, f.parent.name
            if (folder_team, folder) in seen:          # some seasons list a team under two conference folders
                continue
            seen.add((folder_team, folder))
            tm = TEAM_RENAME.get(folder_team, folder_team)
            try:
                box = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            bt = box.get("teams") or {}
            if not isinstance(bt, dict) or len(bt) != 2:
                continue
            mine = _find_team_key(folder_team, box) or _find_team_key(tm, box)
            if not mine or mine not in bt:
                continue
            opp_key = next(k for k in bt if k != mine)
            rows = [r for r in bt[mine] or [] if not str(r.get("name", "")).upper().startswith(("TM", "TEAM"))]
            if not rows:
                continue
            sc = box.get("score") or {}
            pf, pa = _i(sc.get(mine)), _i(sc.get(opp_key))
            if not pf and not pa:
                continue
            teams.add(tm)
            date = _date(folder, box.get("date"))
            opp = resolve_opponent(opp_key) or (opp_key.title() if opp_key.isupper() else opp_key)
            opp = TEAM_RENAME.get(opp, opp)
            tot = defaultdict(int)
            for r in rows:
                ln = _line(r.get("stats") or {})
                for k, v in ln.items():
                    tot[k] += v
                if not any(ln.values()) or any(ln[s] > SANE[s] for s in SANE):
                    continue
                nm = _name(r.get("name"))
                pk = _key(nm)
                if not pk:
                    continue
                for s in STATS:
                    if ln[s] > 0:
                        put("ig_" + s, tm, season, ln[s], [nm, tm, opp, date])
                ps = pseason[(tm, pk)]
                ps["G"] += 1
                ps["name"] = ps["name"] or nm
                for s in STATS:
                    ps[s] += ln[s]
            row = [tm, opp, date, f"{pf}-{pa}"]
            put("tg_PTS", tm, season, pf, row)
            if bt[opp_key] and pa:
                put("tg_low_PA", tm, season, pa, row)
            if pf > pa:
                put("tg_margin", tm, season, pf - pa, row)
            for s in STATS[1:]:
                if 0 < tot[s] <= SANE_TEAM[s]:
                    put("tg_" + s, tm, season, tot[s], row)
            ts = tseason[tm]
            ts["G"] += 1
            ts["W" if pf > pa else "L"] += 1
            ts["PA"] += pa
            ts["PTS"] += pf
            for s in STATS[1:]:
                ts[s] += tot[s]
        max_tg = max((t["G"] for t in tseason.values()), default=0)
        g_season = min(MIN_G_SEASON, max(3, math.ceil(max_tg / 2)))     # a season's own list early in a season
        g_team = min(MIN_G_TEAM, max(3, math.ceil(max_tg / 2)))
        for (tm, pk), ps in pseason.items():
            tg = tseason[tm]["G"] or 1
            row = [ps["name"], tm, season, ps["G"]]
            for s in STATS:
                if ps[s]:
                    put("is_" + s, tm, season, ps[s], row)
            half = ps["G"] >= tg / 2
            for s in STATS:
                v = round(ps[s] / ps["G"], 1)
                if half and ps["G"] >= MIN_G_SEASON and v > 0:
                    put("ipg_" + s, tm, season, v, row)
                elif half and ps["G"] >= g_season and v > 0:
                    put("ipg_" + s, tm, season, v, row, periods=(season,))
            for lab, (m, a, need, _) in PCTS.items():
                if not ps[a]:
                    continue
                v, r2 = round(100 * ps[m] / ps[a], 1), row + [f"{ps[m]}-{ps[a]}"]
                if ps[a] >= max(need / 2, need * tg / FULL_G):
                    put("ipct_" + lab, tm, season, v, r2)
                elif ps[a] >= max(10, need * tg / FULL_G):
                    put("ipct_" + lab, tm, season, v, r2, periods=(season,))
            c = career[(tm, pk)]
            c["name"] = ps["name"]
            c["G"] += ps["G"]
            c["seasons"].add(season)
            for s in STATS:
                c[s] += ps[s]
        for tm, ts in tseason.items():
            g = ts["G"]
            if g < 3:
                continue
            row = [tm, season, f"{ts['W']}-{ts['L']}", g]
            put("ts_W", tm, season, ts["W"], row)
            for s in STATS:
                if ts[s]:
                    put("ts_" + s, tm, season, ts[s], row)
            per = {"tspg_winpct": round(100 * ts["W"] / g, 1), "tspg_PTS": round(ts["PTS"] / g, 1),
                   "tspg_low_PA": round(ts["PA"] / g, 1), "tspg_margin": round((ts["PTS"] - ts["PA"]) / g, 1)}
            for s in STATS[1:]:
                per["tspg_" + s] = round(ts[s] / g, 1)
            for cat, v in per.items():
                if g >= MIN_G_TEAM:
                    put(cat, tm, season, v, row)
                elif g >= g_team:
                    put(cat, tm, season, v, row, periods=(season,))
    for (tm, pk), c in career.items():
        span = sorted(c["seasons"])
        if c["G"] > MAX_CAREER_G or len(span) > 3:
            continue
        row = [c["name"], tm, span[0] if len(span) == 1 else f"{span[0][:4]}-{span[-1][-2:]}", c["G"]]
        for s in STATS:
            if c[s]:
                put("ic_" + s, tm, None, c[s], row)
            if c["G"] >= MIN_G_CAREER and c[s]:
                put("icpg_" + s, tm, None, round(c[s] / c["G"], 1), row)
        put("ic_G", tm, None, c["G"], row)
        for lab, (m, a, _, need) in PCTS.items():
            if c[a] >= need:
                put("icpct_" + lab, tm, None, round(100 * c[m] / c[a], 1), row + [f"{c[m]}-{c[a]}"])
    cats = _cats()
    periods = ["all"] + [s for s in SEASONS if (HERE / f"{s} Teams Schedules").exists()]

    def pack(scope):
        out = {}
        for per in periods:
            d = {k: lists[(scope, per, k)].out() for k, _, _ in cats if (scope, per, k) in lists}
            d = {k: v for k, v in d.items() if v}
            if d:
                out[per] = d
        return out
    return {"cats": [list(c) for c in cats], "periods": periods,
            "state": pack(""), "teams": {tm: pack(tm) for tm in sorted(teams)}}


def write():
    """{filename: js} for ../season_data: per scope (state, each team) two files, the current season's lists alone in
    records_<scope>_cur.js (rewritten every night) and everything else (all-time, past seasons) in records_<scope>.js,
    which changes only when a record falls, so a night's push stays small."""
    rb = build()
    cur = rb["periods"][-1]
    idx = {tm: slug(tm) for tm in rb["teams"]}
    files = {}

    def two(name, scope, lists, extra=None):
        js = lambda d: json.dumps(d, separators=(",", ":"))
        base = {"lists": {p: v for p, v in lists.items() if p != cur}, **(extra or {})}
        files[f"records_{name}.js"] = f"__installRecords({json.dumps(scope)}, {js(base)});\n"
        files[f"records_{name}_cur.js"] = f"__installRecords({json.dumps(scope)}, {js({'lists': {cur: lists.get(cur, {})}})});\n"
    two("state", "", rb["state"], {"cats": rb["cats"], "periods": rb["periods"], "teams": idx})
    for tm, lists in rb["teams"].items():
        two(idx[tm], tm, lists)
    return files


if __name__ == "__main__":
    rb = build()
    for k, g, l in rb["cats"]:
        top = (rb["state"].get("all", {}).get(k) or [[None]])[0]
        print(f"{g:30} {l:34} {top}")
