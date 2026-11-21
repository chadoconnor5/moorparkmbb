"""Record Book (leaderboard Misc -> Record Book): statewide and per-team records from every box score, 2017-18 on.

    Individual   single game (box score lines) · season (summed from the season's box scores) · career (same team,
                 every season with that name)
    Team         single game · season (the team's box-score games and results)

Each category keeps the top TOP entries statewide and the top TOP for each team (ties at the cut kept up to TIE_MAX).
Players are told apart by team and name only (box scores carry no IDs), so two players with the same name on the same
team in different years share a career line: rare at a two-year school and accepted. Forfeits count as played (the
box score is the game on the court). Percentages need attempts (season minimums scale with the team's games, of 28).

    python3 record_book.py            # prints the statewide #1 of every category
"""
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEASONS = ["2017-18", "2018-19", "2019-20", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "2026-27"]
TOP = 10
TIE_MAX = 15
FULL_G = 28

STATS = ["PTS", "REB", "OREB", "DREB", "AST", "STL", "BLK", "3PM", "FGM", "FTM"]
LABEL = {"PTS": "Points", "REB": "Rebounds", "OREB": "Offensive rebounds", "DREB": "Defensive rebounds", "AST": "Assists",
         "STL": "Steals", "BLK": "Blocks", "3PM": "3-pointers made", "FGM": "Field goals made", "FTM": "Free throws made"}
# season percentages: (made, attempts, attempts needed over a full season)
PCTS = {"FG%": ("FGM", "FGA", 150), "3P%": ("3PM", "3PA", 60), "FT%": ("FTM", "FTA", 60)}
PER_GAME = ["PTS", "REB", "AST", "STL", "BLK", "3PM"]
# Old names of today's teams (records follow the school)
TEAM_RENAME = {"West Hills Coalinga": "Coalinga", "West Hills Lemoore": "Lemoore"}
# A box score line past these is a typo in the box (2/13/2023 Shasta: one player with 61 assists, the team 84), not a record
SANE = {"PTS": 75, "REB": 35, "OREB": 20, "DREB": 28, "AST": 25, "STL": 14, "BLK": 15, "3PM": 16, "FGM": 30, "FTM": 30}
SANE_TEAM = {"AST": 45, "REB": 85, "STL": 35, "BLK": 22, "3PM": 30, "FGM": 70}
MIN_G_SEASON = 10        # per-game season records: 10+ games and half the team's
MIN_G_TEAM = 15          # team per-game season records: 15+ games
MAX_CAREER_G = 72        # more games than this on one name = two players sharing it (left out of career records)


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
    reb = _i(stats.get("REB")) or o + d
    return {"PTS": _i(stats.get("PTS")), "REB": reb, "OREB": o, "DREB": d, "AST": _i(stats.get("AST")),
            "STL": _i(stats.get("STL")), "BLK": _i(stats.get("BLK")), "3PM": tp[0], "3PA": tp[1], "FGM": fg[0],
            "FGA": fg[1], "FTM": ft[0], "FTA": ft[1]}


def _name(raw):
    n = re.sub(r"^#\s*\d+\s*", "", str(raw or "")).strip()
    n = re.sub(r"^(?:(?:[GFC]|PG|SG|SF|PF|G/F|F/C)\s+)?\d+\s+", "", n)      # "G 00 Uriyah Rojas"
    n = re.sub(r"\s*\(.*?\)\s*", " ", n).strip()
    if "," in n:                                   # LAST,FIRST
        last, first = [x.strip() for x in n.split(",", 1)]
        n = f"{first} {last}".strip()
    return " ".join(w.capitalize() if (w.isupper() and len(w) > 2) or w.islower() else w for w in n.split())


def _key(name):
    return re.sub(r"[^a-z]", "", name.lower().replace(" jr", "").replace(" iii", "").replace(" ii", ""))


def _date(folder, raw):
    m = re.match(r"(\d{4})(\d{2})(\d{2})", folder)
    return f"{int(m.group(2))}/{int(m.group(3))}/{m.group(1)}" if m else str(raw or "")


class Top:
    """The top TOP of a category (ties at the cut kept up to TIE_MAX)."""
    def __init__(self, low=False):
        self.rows, self.low = [], low

    def add(self, val, row):
        self.rows.append((val, row))

    def out(self):
        rs = sorted(self.rows, key=lambda r: r[0] if self.low else -r[0])
        if len(rs) > TOP:
            cut = rs[TOP - 1][0]
            rs = [r for i, r in enumerate(rs) if i < TOP or (r[0] == cut and i < TIE_MAX)]
        return [[v] + row for v, row in rs]


def build():
    from generate_team_stats import _find_team_key
    from update_advanced_analytics import resolve_opponent
    state = defaultdict(Top)
    team = defaultdict(lambda: defaultdict(Top))
    low_cats = {"tg_fewest_allowed", "ts_opp_ppg"}

    def put(cat, tm, val, row):
        if cat in low_cats:
            state[cat].low = True
            team[tm][cat].low = True
        state[cat].add(val, row)
        team[tm][cat].add(val, row)

    career = defaultdict(lambda: {"G": 0, "seasons": set(), **{s: 0 for s in STATS}, "FGA": 0, "3PA": 0, "FTA": 0,
                                  "name": ""})
    for season in SEASONS:
        sched = HERE / f"{season} Teams Schedules"
        if not sched.exists():
            continue
        pseason = defaultdict(lambda: {"G": 0, **{s: 0 for s in STATS}, "FGA": 0, "3PA": 0, "FTA": 0, "name": ""})
        tseason = defaultdict(lambda: {"G": 0, "W": 0, "L": 0, "PF": 0, "PA": 0, **{s: 0 for s in STATS}})
        seen = set()
        for f in sorted(sched.glob("*/*/*/*.json")):
            tm, folder = f.parent.parent.name, f.parent.name
            if (tm, folder) in seen:          # some seasons list a team under two conference folders
                continue
            seen.add((tm, folder))
            folder_team = tm
            tm = TEAM_RENAME.get(tm, tm)
            try:
                box = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            teams = box.get("teams") or {}
            if not isinstance(teams, dict) or len(teams) != 2:
                continue
            mine = _find_team_key(folder_team, box) or _find_team_key(tm, box)
            if not mine or mine not in teams:
                continue
            opp_key = next(k for k in teams if k != mine)
            rows = [r for r in teams[mine] or [] if not str(r.get("name", "")).upper().startswith(("TM", "TEAM"))]
            if not rows:
                continue
            opp_rows = teams[opp_key] or []
            date = _date(folder, box.get("date"))
            sc = box.get("score") or {}
            pf, pa = _i(sc.get(mine)), _i(sc.get(opp_key))
            if not pf and not pa:
                continue
            opp_name = resolve_opponent(opp_key) or (opp_key.title() if opp_key.isupper() else opp_key)
            opp_name = TEAM_RENAME.get(opp_name, opp_name)
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
                        put("ig_" + s, tm, ln[s], [nm, tm, opp_name, date, season])
                ps = pseason[(tm, pk)]
                ps["G"] += 1
                ps["name"] = ps["name"] or nm
                for s in STATS + ["FGA", "3PA", "FTA"]:
                    ps[s] += ln[s]
            opp_tot = defaultdict(int)
            for r in opp_rows:
                for k, v in _line(r.get("stats") or {}).items():
                    opp_tot[k] += v
            row = [tm, opp_name, date, season, f"{pf}-{pa}"]
            put("tg_points", tm, pf, row)
            if opp_rows and pa:
                put("tg_fewest_allowed", tm, pa, row)
            put("tg_margin", tm, pf - pa, row)
            for s in ("3PM", "FGM", "REB", "AST", "STL", "BLK"):
                if tot[s] and tot[s] <= SANE_TEAM[s]:
                    put("tg_" + s, tm, tot[s], row)
            ts = tseason[tm]
            ts["G"] += 1
            ts["W" if pf > pa else "L"] += 1
            ts["PF"] += pf
            ts["PA"] += pa
            for s in STATS:
                ts[s] += tot[s]
        # season records
        for (tm, pk), ps in pseason.items():
            tg = tseason[tm]["G"] or 1
            row = [ps["name"], tm, season, ps["G"]]
            for s in STATS:
                if ps[s]:
                    put("is_" + s, tm, ps[s], row)
            if ps["G"] >= max(MIN_G_SEASON, tg / 2):
                for s in PER_GAME:
                    put("ipg_" + s, tm, round(ps[s] / ps["G"], 1), row)
            for lab, (m, a, need) in PCTS.items():
                if ps[a] >= max(need / 2, need * tg / FULL_G):
                    put("ipct_" + lab, tm, round(100 * ps[m] / ps[a], 1), row + [f"{ps[m]}-{ps[a]}"])
            c = career[(tm, pk)]
            c["name"] = ps["name"]
            c["G"] += ps["G"]
            c["seasons"].add(season)
            for s in STATS + ["FGA", "3PA", "FTA"]:
                c[s] += ps[s]
        for tm, ts in tseason.items():
            g = ts["G"]
            if g < 5:
                continue
            row = [tm, season, f"{ts['W']}-{ts['L']}", g]
            put("ts_wins", tm, ts["W"], row)
            if g < MIN_G_TEAM:
                continue
            put("ts_winpct", tm, round(100 * ts["W"] / g, 1), row)
            put("ts_ppg", tm, round(ts["PF"] / g, 1), row)
            put("ts_opp_ppg", tm, round(ts["PA"] / g, 1), row)
            put("ts_margin", tm, round((ts["PF"] - ts["PA"]) / g, 1), row)
            for s in ("3PM", "REB", "AST", "STL", "BLK"):
                put("tspg_" + s, tm, round(ts[s] / g, 1), row)
    for (tm, pk), c in career.items():
        span = sorted(c["seasons"])
        if c["G"] > MAX_CAREER_G or len(span) > 3:
            continue
        row = [c["name"], tm, span[0] if len(span) == 1 else f"{span[0][:4]}-{span[-1][-2:]}", c["G"]]
        for s in STATS:
            if c[s]:
                put("ic_" + s, tm, c[s], row)
        put("ic_G", tm, c["G"], row)
    cats = {}
    for s in STATS:
        cats["ig_" + s] = ("Individual · Single game", LABEL[s])
    for s in STATS:
        cats["is_" + s] = ("Individual · Season", LABEL[s])
    for s in PER_GAME:
        cats["ipg_" + s] = ("Individual · Season", LABEL[s] + " per game")
    for lab in PCTS:
        cats["ipct_" + lab] = ("Individual · Season", lab)
    for s in STATS:
        cats["ic_" + s] = ("Individual · Career", LABEL[s])
    cats["ic_G"] = ("Individual · Career", "Games played")
    cats.update({"tg_points": ("Team · Single game", "Points"), "tg_fewest_allowed": ("Team · Single game", "Fewest points allowed"),
                 "tg_margin": ("Team · Single game", "Margin of victory")})
    for s in ("3PM", "FGM", "REB", "AST", "STL", "BLK"):
        cats["tg_" + s] = ("Team · Single game", LABEL[s])
    cats.update({"ts_wins": ("Team · Season", "Wins"), "ts_winpct": ("Team · Season", "Win %"),
                 "ts_ppg": ("Team · Season", "Points per game"), "ts_opp_ppg": ("Team · Season", "Fewest points allowed per game"),
                 "ts_margin": ("Team · Season", "Scoring margin")})
    for s in ("3PM", "REB", "AST", "STL", "BLK"):
        cats["tspg_" + s] = ("Team · Season", LABEL[s] + " per game")
    return {"cats": [[k, g, l] for k, (g, l) in cats.items()],
            "state": {k: state[k].out() for k in cats if k in state},
            "team": {tm: {k: v.out() for k, v in d.items()} for tm, d in sorted(team.items())},
            "seasons": SEASONS}


if __name__ == "__main__":
    rb = build()
    for k, g, l in rb["cats"]:
        top = (rb["state"].get(k) or [[None]])[0]
        print(f"{g:28} {l:32} {top}")
