"""Saved daily ranks for the current season: daily_ranks/<season>.json, one entry per update date
{"M/D/YYYY": {"saved": iso time, "ranks": {team: rank}, "net": {team: net}, "gp": {team: games dated on/before it}}}.

Each leaderboard build saves today's ranks (the leaderboard's net-rating order) under today's date (Pacific; a run
before 6am counts as the night before), replacing an earlier save that day, so a team's rank moves day by day up to
its game. A game on date D shows the latest save from before D: the rank it carried into tip-off, locked from then
on ("preseason", saved before the first game, for opening night). A saved day changes only when a game dated
on/before it turns up later (stats posted after the fact): then that day's ranks are recomputed from the games that should have been in it (compute_daily_ranks' as-of-date ranks)."""

import json
from datetime import datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _PT = ZoneInfo("America/Los_Angeles")
except Exception:   # no tz database: local time
    _PT = None

DIR = Path("daily_ranks")


def _key(d):
    m, dd, y = (int(x) for x in str(d).split("/"))
    return (y + 2000 if y < 100 else y) * 10000 + m * 100 + dd


def _today():
    now = datetime.now(_PT) if _PT else datetime.now()
    if now.hour < 6:
        now -= timedelta(days=1)
    return f"{now.month}/{now.day}/{now.year}", now.isoformat(timespec="seconds")


def _gp_through(teams, day):
    k = _key(day)
    return {t["team"]: sum(1 for g in t.get("game_ratings", []) if g.get("date") and _key(g["date"]) <= k)
            for t in teams}


def _as_of(reconstructed, day):
    k = _key(day)
    best = max((d for d in reconstructed if d != "preseason" and _key(d) <= k), key=_key, default=None)
    return reconstructed.get(best) if best else reconstructed.get("preseason", {})


def update(season, teams, reconstructed):
    """Save today's ranks, recompute any saved day a late game changed, and return the ranks for the page:
    {"_strict": 1, "preseason": {...}, date: {team: rank}} (the page reads a game's rank from the save before it)."""
    teams = [t for t in teams if t.get("team") and t.get("ortg", 0) > 0]
    path = DIR / f"{season}.json"
    hist = json.loads(path.read_text()) if path.exists() else {}
    today, stamp = _today()

    if "preseason" not in hist and not any(_gp_through(teams, today).values()):
        # before any game: the leaderboard's order (last season's ratings), what opening-night games carry in
        hist["preseason"] = {"saved": stamp, "ranks": {t["team"]: i + 1 for i, t in
                                                      enumerate(sorted(teams, key=lambda t: -t.get("net_rtg", 0)))}}
    for day, snap in hist.items():
        if day in (today, "preseason"):
            continue
        gp = _gp_through(teams, day)
        late = sorted(t for t, n in gp.items() if n > snap.get("gp", {}).get(t, 0))
        if late:   # games dated on/before this day that weren't in when it was saved
            snap["ranks"] = dict(_as_of(reconstructed, day))
            snap["gp"] = gp
            snap.setdefault("recomputed", []).append({"at": stamp, "late_games_for": late})

    order = sorted(teams, key=lambda t: -t.get("net_rtg", 0))
    hist[today] = {"saved": stamp,
                   "ranks": {t["team"]: i + 1 for i, t in enumerate(order)},
                   "net": {t["team"]: round(t.get("net_rtg", 0), 1) for t in order},
                   "gp": _gp_through(teams, today)}
    hist = dict(sorted(hist.items(), key=lambda kv: 0 if kv[0] == "preseason" else _key(kv[0])))
    DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(hist, indent=1))

    out = {"_strict": 1, "preseason": reconstructed.get("preseason", {})}
    out.update({d: s["ranks"] for d, s in hist.items()})   # a saved preseason replaces the reconstructed one
    return out
