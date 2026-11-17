"""Kill shots and kills from the play-by-play (2026-27 on), per team, for the leaderboard's Misc -> Kills table.

    kill shot   a 10-0 run: a team scores 10 straight points (free throws count) before the other team scores; one per
                run however long it goes. Runs carry across halftime.
    kill        three straight defensive stops: three opponent possessions in a row without a point. The count starts
                over after each kill (six straight stops = 2) and at each half.

Games whose play-by-play is empty can use a Synergy play log pasted in by hand
(internal_data/synergy_logs/<season>/<YYYYMMDD>_<visitor>_at_<home>.json: {"date", "left", "right", "log"}; "left" is the
team whose score the log lists first): synergy_plays turns it into the same plays (no clock, so it feeds only this
table, never the win-probability chart or lineups).

A possession is a stretch of plays where the same team has the ball: its shots, free throws, turnovers and offensive
rebounds (the defense's rebounds, steals, blocks and fouls don't decide who has it), so an offensive rebound keeps the
possession and an and-one's free throw belongs to it. Games without play-by-play aren't counted (g = games counted).
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = 10      # points in a row for a kill shot
STOPS = 3     # stops in a row for a kill

_OFF = ("made ", "missed ", "Turnover by", "offensive rebound")


def game_runs(plays):
    """[(kill shots, kills, stops, possessions) for visitor, same for home] from one game's plays (fix_plays format:
    period, clock, team 0/1, player, action, visitor score, home score)."""
    ks, kills, stops, poss = [0, 0], [0, 0], [0, 0], [0, 0]
    run_t, run_pts, counted = None, 0, False
    last = [0, 0]
    seg_t, seg_start, seg_per = None, None, None   # the possession being played: team, its score when it began, period
    streak = [0, 0]                                # stops in a row by each team's defense

    def close(score):
        if seg_t is None:
            return
        o = seg_t
        poss[o] += 1
        d = 1 - o
        if score[o] == seg_start:
            stops[d] += 1
            streak[d] += 1
            if streak[d] == STOPS:
                kills[d] += 1
                streak[d] = 0
        else:
            streak[d] = 0

    for pl in plays:
        per, t, act = pl[0], pl[2], str(pl[4] or "")
        try:
            score = [int(pl[5]), int(pl[6])]
        except (TypeError, ValueError, IndexError):
            continue
        # runs: points since the other team last scored
        for side in (0, 1):
            pts = score[side] - last[side]
            if pts > 0:
                if run_t == side:
                    run_pts += pts
                else:
                    run_t, run_pts, counted = side, pts, False
                if run_pts >= RUN and not counted:
                    ks[side] += 1
                    counted = True
        # possessions
        if t in (0, 1) and act.startswith(_OFF):
            if per != seg_per:
                close(last)
                seg_t = None
                streak[0] = streak[1] = 0
                seg_per = per
            if seg_t != t:
                close(last)
                seg_t, seg_start = t, last[t]
        last = score
    close(last)
    return [(ks[i], kills[i], stops[i], poss[i]) for i in (0, 1)]


_SYN_DET = ("Shot >", "Assist >", "Steal >", "Turnover >", "Foul >", "Free Throw Attempt >", "Defensive Rebound >",
            "Offensive Rebound >", "Block Shot >")


def synergy_plays(rec, rosters):
    """A Synergy play log as plays [period, "0:00", side 0 left / 1 right, player, action, left score, right score].
    The acting player is a chain line's last "N Name" (a pass ends "Ball Delivered > N Name > ..."), "Unknown Player"
    taking the name on the line above the chain, or rec["aliases"]; his side from the game's box score (rosters: {side:
    [name words]}; a name's words match by prefix, "Micah Coleman" = "Micah Cole", or last name and first initial,
    "Christan Pundt" = "Christian Pundt"), else, when one side's box is empty,
    the side that isn't the other team's. Plays of a player placed on neither side are left out. Shots and free throws
    from the detail lines."""
    import re
    words = lambda n: [w for w in re.sub(r"[^A-Z ]+", " ", str(n).upper().replace(",", " ")).split() if w not in ("JR", "II", "III", "SR")]
    def on(name, side):
        w = words(name)
        pre = lambda x, y: x.startswith(y) or y.startswith(x)
        return any(w and r and (sum(any(pre(x, y) for y in r) for x in w) >= min(2, len(w))
                                or len(w) > 1 and pre(w[-1], r[-1]) and w[0][0] == r[0][0]) for r in rosters[side])
    aliases = rec.get("aliases") or {}
    per, out, sc, side, name, prev = 1, [], [0, 0], None, None, ""
    for l in (x.strip() for x in rec["log"].splitlines()):
        if not l:
            continue
        if l.startswith(("Halftime ", "Overtime ")):
            per = int(l.split()[-1]) + (2 if l.startswith("Overtime") else 0)
        elif re.match(r"^\d+ .+ > ", l) and not l.startswith(_SYN_DET):
            segs = [x.strip() for x in l.split(">")]
            act = [x for x in segs if re.match(r"^\d+ \D", x) and not re.match(r"^\d+ Pts$", x)]
            name = act[-1].split(" ", 1)[1]
            if name in aliases:
                name = aliases[name]
            elif name == "Unknown Player" and prev and not re.match(r"^[\d#]", prev):
                name = prev
            hit = [k for k in (0, 1) if on(name, k)]
            if not hit:
                hit = [k for k in (0, 1) if not rosters[k] and rosters[1 - k]]
            side = hit[0] if len(hit) == 1 else None
            if side is not None and "Turnover" in segs[-1]:
                out.append([per, "0:00", side, name, "Turnover by", sc[0], sc[1]])
        elif side is None:
            pass
        elif l.startswith("Shot >"):
            made = "Make" in l
            if made:
                sc[side] += 3 if "3 Point" in l else 2
            out.append([per, "0:00", side, name, ("made " if made else "missed ") + ("3-pt. jump shot" if "3 Point" in l else "jump shot"), sc[0], sc[1]])
        elif l.startswith("Free Throw Attempt"):
            made = l.endswith("Made")
            sc[side] += made
            out.append([per, "0:00", side, name, ("made " if made else "missed ") + "free throw", sc[0], sc[1]])
        elif l.startswith("Offensive Rebound >"):
            out.append([per, "0:00", side, name, "offensive rebound", sc[0], sc[1]])
        prev = l
    return out


def _synergy_games(season, ours, isl):
    """{play-by-play file name: game} from the stored Synergy logs, rosters from the game's box score."""
    import glob
    out = {}
    for f in sorted((HERE / "internal_data" / "synergy_logs" / season).glob("*.json")):
        rec = json.load(open(f, encoding="utf-8"))
        rosters = {0: [], 1: []}
        for bf in glob.glob(str(HERE / f"{season} Teams Schedules" / "*" / "*" / (f.stem[:8] + "_*") / "*.json")):
            box = json.load(open(bf, encoding="utf-8"))
            if set(box.get("teams") or {}) != {rec["left"], rec["right"]}:
                continue
            for k, t in ((0, rec["left"]), (1, rec["right"])):
                import re
                rosters[k] = [[w for w in re.sub(r"[^A-Z ]+", " ", str(p.get("name", "")).upper()).split()]
                              for p in box["teams"][t] if any(str(v).strip() not in ("", "0", "0-0") for kk, v in (p.get("stats") or {}).items() if kk != "MIN") or True]
            break
        out[f.stem + ".json"] = {"visitor": rec["left"], "home": rec["right"], "plays": synergy_plays(rec, rosters)}
    return out


def season_runs(season="2026-27"):
    """{team: {"g", "ks", "ks_a", "kills", "kills_a", "stops", "poss_d"}} for our teams with play-by-play."""
    import import_synergy_leaderboard as isl
    import play_by_play
    ours, out = isl.our_teams(), {}
    syn = _synergy_games(season, ours, isl)
    files = {f.name: f for f in sorted((HERE / f"{season} Play by Play").glob("*.json"))}
    for name in sorted(set(files) | set(syn)):
        try:
            g = play_by_play.fix_plays(json.load(open(files[name], encoding="utf-8"))) if name in files else {}
        except (OSError, ValueError):
            g = {}
        if not (g.get("plays")) and name in syn:   # no play-by-play: the Synergy log
            g = syn[name]
        plays = g.get("plays") or []
        if not plays:
            continue
        sides = [n if n in ours else isl.map_team(str(n), ours) for n in (g.get("visitor"), g.get("home"))]
        R = game_runs(plays)
        for i in (0, 1):
            if not sides[i]:
                continue
            o = out.setdefault(sides[i], {"g": 0, "ks": 0, "ks_a": 0, "kills": 0, "kills_a": 0, "stops": 0, "poss_d": 0})
            o["g"] += 1
            o["ks"] += R[i][0]
            o["ks_a"] += R[1 - i][0]
            o["kills"] += R[i][1]
            o["kills_a"] += R[1 - i][1]
            o["stops"] += R[i][2]
            o["poss_d"] += R[1 - i][3]
    return out


if __name__ == "__main__":
    S = season_runs()
    for t, o in sorted(S.items(), key=lambda kv: -(kv[1]["ks"] - kv[1]["ks_a"]) / kv[1]["g"]):
        print(f"{t:24} g {o['g']:2}  KS {o['ks']:2}-{o['ks_a']:2}  kills {o['kills']:2}-{o['kills_a']:2}  "
              f"stop% {100 * o['stops'] / max(1, o['poss_d']):.1f}")
