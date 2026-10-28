"""Bracket tournaments ("<season> Schedule Screenshots/brackets.json"): the later-round games of a bracket, linked to
the games that feed them, so FanMatch can list each prospective game ("Winner East LA/Riverside vs Winner San
Francisco/Chaffey") and a team's schedule can show where a win or a loss sends it. Results fill the teams in as
the games are played (generate_leaderboard.py passes the played games)."""

import json
from pathlib import Path

_MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _mdy(season, d):
    mon, _, day = d.partition(" ")
    m, y0 = _MONTHS[mon], int(season[:4])
    return f"{m}/{int(day)}/{y0 if m >= 7 else y0 + 1}"


def load(season):
    f = Path(f"{season} Schedule Screenshots") / "brackets.json"
    if not f.exists():
        return {}
    out = {}
    for name, t in json.load(open(f)).items():
        if name.startswith("_"):
            continue
        games = [dict(g, date=_mdy(season, g["date"])) for g in t["games"]]
        out[name] = {"host": t["host"], "games": games}
    return out


def _resolve(t, results):
    """Each game's teams (None until known) and winner, in bracket order. results: {(date, frozenset(pair)): winner}."""
    win, lose, sides = {}, {}, {}
    side = lambda ref: (win if ref[0] == "W" else lose).get(ref[2:]) if ref[:2] in ("W:", "L:") else ref
    for g in t["games"]:
        a, b = side(g["a"]), side(g["b"])
        sides[g["id"]] = (a, b)
        w = results.get((g["date"], frozenset((a, b)))) if a and b else None
        if w:
            win[g["id"]], lose[g["id"]] = w, b if w == a else a
    return sides, win, lose


def _desc(t, ref, sides, win, lose):
    if ref[:2] not in ("W:", "L:"):
        return ref
    k = ref[2:]
    got = (win if ref[0] == "W" else lose).get(k)
    if got:
        return got
    a, b = sides[k]
    word = "Winner" if ref[0] == "W" else "Loser"
    if a and b:
        return f"{word} {a}/{b}"
    g = next(x for x in t["games"] if x["id"] == k)
    return f"{word} of the {g['time']} game"


def fanmatch(season, results, existing):
    """(rows, covered): one FanMatch row for every later-round game not already on the schedules (existing:
    {(date, frozenset(pair))}), and the (team, date) pairs those rows stand for (their schedules' TBA rows)."""
    rows, covered = [], set()
    for name, t in load(season).items():
        sides, win, lose = _resolve(t, results)
        teams = {x for g in t["games"] for x in (g["a"], g["b"]) if x[:2] not in ("W:", "L:")}
        for g in t["games"]:
            if g["a"][:2] not in ("W:", "L:") and g["b"][:2] not in ("W:", "L:"):
                continue   # opening round: on the schedules
            covered |= {(x, g["date"]) for x in teams}
            a, b = sides[g["id"]]
            if a and b and (g["date"], frozenset((a, b))) in existing:
                continue
            home = a if a == t["host"] else b if b == t["host"] else None
            da, db = _desc(t, g["a"], sides, win, lose), _desc(t, g["b"], sides, win, lose)
            if home == da:
                da, db = db, da
            rows.append({"date": g["date"], "time": g["time"], "tournament": name, "label": g.get("label", ""),
                         "host": None if home else t["host"], "home_team": home,
                         "winner": da, "loser": db, "slot": not (a and b),
                         "result": results.get((g["date"], frozenset((a, b)))) if a and b else None})
    return rows, covered


def team_paths(season, results):
    """{team: {date: [{"cond", "opp", "time", "label"}]}}: where each result sends a team ("Win", "Loss",
    "Win, Loss"...), only the paths its results so far still allow."""
    out = {}
    for name, t in load(season).items():
        sides, win, lose = _resolve(t, results)
        first = {}
        for g in t["games"]:
            for x in (g["a"], g["b"]):
                if x[:2] not in ("W:", "L:"):
                    first[x] = g["id"]
        for team, g0 in first.items():
            reach = {g0: []}
            for g in t["games"]:
                for ref, other in ((g["a"], g["b"]), (g["b"], g["a"])):
                    if ref[:2] in ("W:", "L:") and ref[2:] in reach:
                        chain = reach[ref[2:]] + [(ref[2:], ref[0])]
                        if all(k not in win or (win[k] == team) == (o == "W") for k, o in chain):
                            reach[g["id"]] = chain
                            out.setdefault(team, {}).setdefault(g["date"], []).append({
                                "cond": ", ".join("Win" if o == "W" else "Loss" for _, o in chain),
                                "opp": _desc(t, other, sides, win, lose), "time": g["time"],
                                "label": g.get("label", "")})
    return out
