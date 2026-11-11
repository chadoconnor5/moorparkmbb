"""How each player's shots come, from the play-by-play (2026-27 on): made shots assisted or not, putbacks and transition
shots, by zone (rim = layups, dunks, tip-ins; jumper = 2-pt jump shots; three). Used to back up the Synergy roles
(synergy_roles: creators make shots on their own, shooters and finishers are set up).

    assisted        a made shot followed by "Assist by" (same team, same clock): the site logs the assist right after it
    putback         a shot by a team within 3 seconds of its own offensive rebound
    transition      a shot within 8 seconds of the team getting the ball off a defensive rebound, steal or the other
                    team's turnover (same half)

Scorekeepers log some layups as jump shots, so the zones lean toward jumpers; assists are logged loosely by some home
scorers. Counts only, no rates below a sample: synergy_roles decides how many it needs.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
_CACHE = {}


def words(n):
    """A name as its set of words (LAST,FIRST and First Last match)."""
    return frozenset(re.sub(r"[^A-Z ]+", " ", str(n or "").upper().replace(",", " ")).split())


def _secs(clock):
    try:
        m, s = str(clock).split(":")
        return int(m) * 60 + float(s)
    except ValueError:
        return None


def _zone(act):
    if any(w in act for w in ("layup", "dunk", "tip-in")):
        return "rim"
    return "three" if "3-pt" in act else "jumper"


def creation(season):
    """{(team, name words): {"fga", "fgm", "ast_m", "unast_m", "rim_m", "rim_ast", "three_m", "three_ast", "jumper_m",
    "jumper_ast", "putback_a", "trans_a", "games"}} for every player in the season's play-by-play."""
    if season in _CACHE:
        return _CACHE[season]
    import import_synergy_leaderboard as isl
    import play_by_play
    ours, out = isl.our_teams(), {}
    for f in sorted((HERE / f"{season} Play by Play").glob("*.json")):
        try:
            g = play_by_play.fix_plays(json.load(open(f, encoding="utf-8")))
        except (OSError, ValueError):
            continue
        sides = [n if n in ours else isl.map_team(str(n), ours) for n in (g.get("visitor"), g.get("home"))]
        plays = g.get("plays") or []
        gained = [None, None]   # (period, clock secs) the team last got the ball off a stop
        oreb = [None, None]     # (period, clock secs) of the team's last offensive rebound
        seen = set()
        for i, pl in enumerate(plays):
            per, clk, t, who, act = pl[0], _secs(pl[1]), pl[2], pl[3], pl[4] or ""
            if t not in (0, 1) or clk is None:
                continue
            if act == "defensive rebound" or act.startswith("Steal by"):
                gained[t] = (per, clk)
            elif act.startswith("Turnover by"):
                gained[1 - t] = (per, clk)
            elif act == "offensive rebound":
                oreb[t] = (per, clk)
            if not act.startswith(("made ", "missed ")) or "free throw" in act or not sides[t] or not who:
                continue
            k = (sides[t], words(who))
            c = out.setdefault(k, {"fga": 0, "fgm": 0, "ast_m": 0, "unast_m": 0, "rim_m": 0, "rim_ast": 0, "three_m": 0,
                                   "three_ast": 0, "jumper_m": 0, "jumper_ast": 0, "putback_a": 0, "trans_a": 0, "games": 0})
            if (f.name, k) not in seen:
                seen.add((f.name, k))
                c["games"] += 1
            c["fga"] += 1
            if oreb[t] and oreb[t][0] == per and 0 <= oreb[t][1] - clk <= 3:
                c["putback_a"] += 1
            elif gained[t] and gained[t][0] == per and 0 <= gained[t][1] - clk <= 8:
                c["trans_a"] += 1
            if act.startswith("made "):
                z = _zone(act)
                nxt = plays[i + 1] if i + 1 < len(plays) else None
                ast = bool(nxt and nxt[2] == t and (nxt[4] or "").startswith("Assist by") and nxt[1] == pl[1])
                c["fgm"] += 1
                c[z + "_m"] += 1
                c["ast_m" if ast else "unast_m"] += 1
                if ast:
                    c[z + "_ast"] += 1
    _CACHE[season] = out
    return out


def player(season, team, name):
    """One player's counts, or None (no play-by-play for him)."""
    return creation(season).get((team, words(name)))
