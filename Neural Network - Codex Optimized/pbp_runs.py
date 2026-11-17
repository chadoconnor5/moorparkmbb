"""Kill shots and kills from the play-by-play (2026-27 on), per team, for the leaderboard's Misc -> Kills table.

    kill shot   a 10-0 run: a team scores 10 straight points (free throws count) before the other team scores; one per
                run however long it goes. Runs carry across halftime.
    kill        three straight defensive stops: three opponent possessions in a row without a point. The count starts
                over after each kill (six straight stops = 2) and at each half.

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


def season_runs(season="2026-27"):
    """{team: {"g", "ks", "ks_a", "kills", "kills_a", "stops", "poss_d"}} for our teams with play-by-play."""
    import import_synergy_leaderboard as isl
    import play_by_play
    ours, out = isl.our_teams(), {}
    for f in sorted((HERE / f"{season} Play by Play").glob("*.json")):
        try:
            g = play_by_play.fix_plays(json.load(open(f, encoding="utf-8")))
        except (OSError, ValueError):
            continue
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
