"""Hall of Fame (leaderboard sidebar -> Hall of Fame; the page is ../hof.html, its data ../season_data/hof.js).

Who gets in: a first-team All-State player (Gold or Hall of Fame All-State badge) whose career is over (not on a
current-season roster at that school) with a resume score of RESUME_CUT or better (the top 2% of players through
2025-26) and a top-25% scoring season (FLOOR_PPG) unless he's a role-player Hall of Famer (a defensive / sixth-man /
Player of the Year award, a Gold+ Glue Guy or Rim Protector season, Defensive Anchor, or a state title / Final Four);
automatically as a Region Player of the Year, a two-time first-team All-State or a top-1% scorer (SCORER_PPG+). Badges don't decide it: the resume does. Once in, always in: hall_of_fame.json keeps every inductee and a
later build never drops one; the cut stays fixed, so new seasons add players without pushing anyone out.

Resume score (the order): winning 35% (team win %, net rank and deepest state run each season, scaled by his place
on his own team), impact 30% (state percentile on PRPG! + BPM; per-game estimate for teams without real minutes),
honors 20% (awards and All-State / All-Conference picks), big games 15% (quad results, Q1A to Q4, and his Game Score
against Q1A-Q2). All against CCCAA opponents only.

Also built here: team titles (conference = best conference record; state rounds from the box scores), State
Tournament MVP (a blend over the champion's last three games), Conference Freshman of the Year (inferred: a name not
seen in any earlier season; FRESHMAN_NOT holds confirmed sophomores), signature games and career averages."""

import bisect
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

CUR = "2627"                       # the season being played: its players aren't eligible yet
LOCKED = True                      # True: once in, always in (hall_of_fame.json keeps every inductee); False: the rule alone decides
EST_CAP = 0.90                     # an estimated impact (no real minutes) ranks no higher than this percentile, for the order
JERSEYS_MAX = 999
COY_W = (.60, .15, .15, .10)     # Coach of the Year: over-achievement, WAB, conference (strength), run                  # Retired Jerseys: no cap a school (everyone who qualifies; every Hall of Famer too)
SCORER_PPG = 19.8                  # a top-1% scoring season (pooled 10+ game careers, 2017-18 to 2025-26)
FLOOR_PPG = 10.4                   # a top-25% scoring season
RESUME_CUT = 43.2                  # resume score to get in: the top 2% of players (134 of 6,716) through 2025-26; kept fixed
FRESHMAN_NOT = {("2223", "Javohn Garcia"), ("2122", "Jonathan Ogugua"), ("2122", "Conner Jackson"), ("2122", "Scott Ator"), ("2223", "Sebastian Mendoza"), ("2324", "Alex Crawford"), ("2425", "Tyler Isaak"), ("2324", "KJay Bradley"), ("2425", "Zoe Holman"), ("2526", "Yoda Oke"), ("2526", "Leo Ricketts"), ("2526", "Dayvon Gates"), ("2526", "Mason Dorsey"), ("2526", "Snookey Wigington")}   # confirmed not freshmen that season
STORE = Path(__file__).with_name("hall_of_fame.json")
GS = lambda r: (r["pts"] + 0.4 * r["fgm"] - 0.7 * r["fga"] - 0.4 * (r["fta"] - r["ftm"]) + 0.7 * r["or"] + 0.3 * r["dr"]
                + r["stl"] + 0.7 * r["ast"] + 0.7 * r["blk"] - 0.4 * r["pf"] - r["to"])
QTH = {"1A": (15, 40), "1": (30, 75), "2": (75, 135), "3": (160, 240)}   # NCAA (home, away) cutoffs of 353, as the Quads tab
QWIN = {"1A": 1, "1": .8, "2": .6, "3": .35, "4": .15}
QLOSS = {"1A": 0, "1": .1, "2": .25, "3": .5, "4": .75}
REC_CATS = {"PTS": "points", "FGM": "field goals made", "3PM": "threes made", "FTM": "free throws made",
            "OREB": "offensive rebounds", "DREB": "defensive rebounds", "REB": "rebounds", "AST": "assists",
            "STL": "steals", "BLK": "blocks"}


def _obj(js):
    return json.loads(js[js.index("{"):js.rindex("}") + 1])


def _rows(v):
    return [dict(zip(v["__c"], r)) for r in v["__r"]] if isinstance(v, dict) and "__c" in v else (v or [])


def _first(d, pat):
    for k, v in d.items():
        if re.fullmatch(pat, k):
            return _rows(v)
    return []


def _date(s):
    for f in ("%m/%d/%Y", "%m-%d-%y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    return datetime(1900, 1, 1)


def _pct_fn(vals):
    v = sorted(vals)
    return lambda x: bisect.bisect_right(v, x) / len(v) if v else .5


def _z(vals):
    vals = [x for x in vals if x is not None]
    if not vals:
        return lambda x: 0
    m = sum(vals) / len(vals)
    sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** .5 or 1
    return lambda x: (x - m) / sd


def build(season_files):
    try:
        from record_book import NAME_FIX
    except Exception:
        NAME_FIX = {}
    M = lambda n: NAME_FIX.get(n, n)
    seasons = sorted(re.search(r"season_(\d+)", k).group(1) for k in season_files if re.fullmatch(r"season_\d+\.js", k))
    past = [s for s in seasons if s != CUR]
    SD = {s: _obj(season_files[f"season_{s}.js"]) for s in past}
    BX = {s: _obj(season_files[f"boxes_{s}.js"]) for s in past if f"boxes_{s}.js" in season_files}
    players = {s: _first(SD[s], r"DATA_\d+") for s in past}
    teams = {s: _first(SD[s], r"TEAM_DATA_\d+") for s in past}

    # --- teams: CCCAA set, net ranks, records ---
    CCC, RANK, TEAM = {}, {}, {}
    for s in past:
        CCC[s] = {t["team"] for t in teams[s]}
        ok = sorted([t for t in teams[s] if (t.get("ortg") or 0) > 0], key=lambda t: -(t.get("net_rtg") or -99))
        RANK[s] = ({t["team"]: i + 1 for i, t in enumerate(ok)}, len(ok))
        for i, t in enumerate(ok):
            m = re.match(r"(\d+)-(\d+)", t.get("record") or "")
            w, l = (int(m[1]), int(m[2])) if m else (0, 0)
            TEAM[(s, t["team"])] = {"wp": w / (w + l) if w + l else .5, "netp": 1 - i / len(ok)}

    # --- team titles: conference (best conference record) and the state tournament rounds (box scores) ---
    TITLES = defaultdict(lambda: defaultdict(list))
    TOUR = {}                      # season -> (Elite Eight date, last date, the Elite Eight teams)
    for s in past:
        conf = defaultdict(list)
        for t in teams[s]:
            m = re.match(r"(\d+)-(\d+)", t.get("conf") or "")
            if m and int(m[1]) + int(m[2]):
                conf[t.get("conference")].append((int(m[1]) / (int(m[1]) + int(m[2])), t["team"]))
        for c, l in conf.items():
            best = max(x[0] for x in l)
            ch = [x[1] for x in l if x[0] == best]
            for tm in ch:
                TITLES[s][tm].append(["conf", c + (" Co-Champions" if len(ch) > 1 else " Champions")])
        end = datetime(2000 + int(s[2:]), 3, 31)
        allg = []
        for g in BX.get(s, {}).values():
            sc = g.get("sc") or {}
            if len(sc) != 2 or _date(g["d"]) > end:
                continue
            a, b = list(sc)
            w = a if sc[a] > sc[b] else b
            for tm in (a, b):
                allg.append((_date(g["d"]), tm, "W" if tm == w else "L"))
        if not allg:
            continue
        last = max(x[0] for x in allg)
        fin = [x for x in allg if x[0] == last]
        winners = [x[1] for x in fin if x[2] == "W"]
        if s == "1920":     # the state tournament was canceled (COVID): the regional final winners made the Elite Eight
            for tm in winners:
                TITLES[s][tm].append(["e8", "Elite Eight (state tournament canceled, COVID)"])
            continue
        prev = lambda tms, before: max([x[0] for x in allg if x[1] in tms and x[0] < before], default=None)
        finalists = {x[1] for x in fin}
        sd = prev(finalists, last)
        ff = {x[1] for x in allg if x[0] == sd}
        qd = prev(ff, sd) if sd else None
        e8 = {x[1] for x in allg if x[0] == qd}
        TOUR[s] = (qd, last, e8)
        for tm in e8:
            TITLES[s][tm].append(["e8", "Elite Eight"])
        for tm in ff:
            TITLES[s][tm].append(["f4", "Final Four"])
        for tm in finalists:
            TITLES[s][tm].append(["fin", "State Championship Game"])
        for tm in winners:
            TITLES[s][tm].append(["state", "State Champions"])

    # --- every player-season: badges, first-team All-State, awards ---
    P = defaultdict(lambda: {"seasons": {}, "as1": [], "hofb": [], "aw": 0, "poy": []})
    AWP = {"poy": 6, "cpoy": 3, "copoy": 2, "cdpoy": 2, "c6moy": 1}
    all_names = set()
    for s in past:
        for p in players[s]:
            k = M(p["name"]) + "|" + p["school"]
            all_names.add(k)
            x = P[k]
            x["seasons"][s] = p
            for b in p.get("bdg") or []:
                if b[0] == "allstate" and b[1] >= 3:
                    x["as1"].append(s)
                if b[0] == "poy":
                    x["poy"].append(s)
                if b[1] == 4:
                    x["hofb"].append((s, b[0]))
                if b[0] in AWP:
                    x["aw"] += AWP[b[0]]
                elif b[0] == "allstate":
                    x["aw"] += {4: 4, 3: 4, 2: 2}.get(b[1], 0)
                elif b[0] == "allconf":
                    x["aw"] += {3: 2, 2: 1}.get(b[1], 0)

    # --- per-game rows from the box scores (CCCAA opponents get a rank, a tier and a quad) ---
    GAMES = defaultdict(list)      # name|school -> rows
    all_gs, all_bpm = [], []
    for s, bx in BX.items():
        rk, N = RANK[s]
        for g in bx.values():
            sc = g.get("sc") or {}
            for team, tb in g["t"].items():
                if not isinstance(tb, dict):
                    continue
                opp = next((x for x in g["t"] if x != team), None)
                r0 = rk.get(opp)
                home = team == g.get("h")
                tier = quad = None
                if r0:
                    adj = r0 * (50 / 90 if not home else 50 / 20)
                    tier = "A" if adj <= 15 else "B" if adj <= 30 else None
                    quad = next((q for q in ("1A", "1", "2", "3") if r0 <= N * QTH[q][0 if home else 1] / 353), "4")
                won = len(sc) == 2 and sc.get(team, 0) > sc.get(opp, 0)
                for row in tb["__r"]:
                    r = dict(zip(tb["__c"], row))
                    if not (r.get("min") or r["fga"] or r["pts"] or r["or"] + r["dr"]):
                        continue
                    gs = GS(r)
                    all_gs.append(gs)
                    if r.get("bpm") is not None and (r.get("min") or 0) >= 15:
                        all_bpm.append(r["bpm"])
                    GAMES[M(r["n"]) + "|" + team].append({
                        "s": s, "d": g["d"], "opp": opp, "ccc": opp in CCC[s], "net": next((t.get("net_rtg") for t in teams[s] if t["team"] == opp), None) if r0 else None,
                        "rk": r0, "N": N, "tier": tier, "quad": quad, "w": won, "score": f"{sc.get(team)}-{sc.get(opp)}",
                        "j": r.get("j"), "gs": round(gs, 1), "bpm": r.get("bpm"), "min": r.get("min"), "pts": r["pts"], "reb": r["or"] + r["dr"],
                        "or": r["or"], "dr": r["dr"], "ast": r["ast"], "stl": r["stl"], "blk": r["blk"], "tpm": r["tpm"],
                        "fgm": r["fgm"], "fga": r["fga"], "ftm": r["ftm"], "fta": r["fta"], "twom": r["fgm"] - r["tpm"],
                        "twoa": r["fga"] - r["tpa"], "tpa": r["tpa"], "to": r["to"], "pf": r["pf"]})
    all_gs.sort()
    all_bpm.sort()
    P99 = all_gs[int(.99 * len(all_gs))] if all_gs else 99
    B99 = all_bpm[int(.99 * len(all_bpm))] if all_bpm else 99

    # --- active players (this season's roster or box scores, same school) ---
    active = set()
    if f"rosters_{CUR}.js" in season_files:
        for team, v in _obj(season_files[f"rosters_{CUR}.js"]).items():
            if isinstance(v, dict) and "players" in v:
                for r in _rows(v["players"]):
                    active.add(M(r["name"]) + "|" + team)
    if f"boxes_{CUR}.js" in season_files:
        for g in _obj(season_files[f"boxes_{CUR}.js"]).values():
            for team, tb in g["t"].items():
                if isinstance(tb, dict):
                    for row in tb["__r"]:
                        active.add(M(row[0]) + "|" + team)

    def runs(s, school):
        return {x[0] for x in TITLES.get(s, {}).get(school, [])}

    try:
        store = json.loads(STORE.read_text())
    except Exception:
        store = {"inducted": {}}
    prev = store["inducted"]
    if not LOCKED:          # unlocked: re-decided from scratch each build (an inductee's first date kept)
        store = {"inducted": {}}
    # the pool scored: every first-team All-State player whose career is over, plus everyone already inducted
    cands = [k for k, v in P.items() if v["as1"] and k not in active]
    cands += [k for k in store["inducted"] if k in P and k not in cands]
    HOFC = set(cands)
    # Retired Jerseys candidates (scored on the same scale, never part of the Hall's own percentiles): finished careers
    # with All-State (any) or All-Conference 1st Team at that school
    JC = [k for k, v in P.items() if k not in active and k not in HOFC and any(
        b[0] == "allstate" or (b[0] == "allconf" and b[1] >= 3) for p_ in v["seasons"].values() for b in (p_.get("bdg") or []))]

    # --- Conference Freshman of the Year (inferred) ---
    FOY, seen = {}, set()
    for s in past:
        names = {M(p["name"]) for p in players[s]}
        if s != past[0]:
            fr = names - seen
            cp, ct = _first(SD[s], r"CONF_DATA_\d+"), _first(SD[s], r"CONF_TEAM_DATA_\d+")
            cg = Counter()
            for p in cp:
                cg[p["school"]] = max(cg[p["school"]], p.get("gp") or 0)
            cq = [p for p in cp if p.get("gp") and not p.get("fm") and p.get("porp") is not None
                  and p["gp"] >= .5 * cg[p["school"]] and (p.get("min_pct") or 0) >= 30]
            if cq:
                zp = _z([p["porp"] for p in cq])
                ctn = {t["team"]: t.get("net_rtg") or 0 for t in ct}
                zn = _z(list(ctn.values()))
                byc = defaultdict(list)
                for p in cq:
                    if M(p["name"]) in fr and (s, M(p["name"])) not in FRESHMAN_NOT:
                        byc[p["conference"]].append(p)
                for c, ps in byc.items():
                    w = max(ps, key=lambda p: .5 * zp(p["porp"]) + .5 * zn(ctn.get(p["school"], 0)))
                    FOY[(s, M(w["name"]) + "|" + w["school"])] = c
        seen |= names

    # --- resume score ---
    IMP = {}
    import numpy as np
    feats = lambda p, s: [p.get("ppg") or 0, p.get("rpg") or 0, p.get("apg") or 0, p.get("spg") or 0, p.get("bpg") or 0,
                          p.get("topg") or 0, (p.get("ts_pct") or 0) / 100, TEAM.get((s, p["school"]), {"netp": .5})["netp"], 1]
    for s in past:
        q = [p for p in players[s] if p.get("q") and p.get("gp")]
        real = [p for p in q if not p.get("fm") and p.get("porp") is not None and p.get("bpm") is not None]
        zp, zb = _z([p["porp"] for p in real]), _z([p["bpm"] for p in real])
        rv = _pct_fn([zp(p["porp"]) + zb(p["bpm"]) for p in real])
        # players without real minutes: their impact percentile predicted from what doesn't need minutes (per-game box
        # numbers, true shooting, the team's strength), fitted on this season's real-minutes players, so an estimate sits
        # on the same scale as a real one (the old per-game Game Score percentile ran low: San Francisco's stars ~0.9)
        if real:
            A = np.array([feats(p, s) for p in real])
            coef = np.linalg.lstsq(A, np.array([rv(zp(p["porp"]) + zb(p["bpm"])) for p in real]), rcond=None)[0]
        est = lambda p: float(min(1, max(0, np.dot(feats(p, s), coef)))) if real else .5
        imp_of = {id(p): (rv(zp(p["porp"]) + zb(p["bpm"])) if p in real else est(p)) for p in q}
        # his place on his own team by impact (points + rebounds + assists favored bigs: rebounds made the center the
        # "best player" and handed him the team's winning)
        place = {}
        for sch in {p["school"] for p in q}:
            for i, p in enumerate(sorted([x for x in q if x["school"] == sch], key=lambda x: -imp_of[id(x)])):
                place[id(p)] = i
        for p in q:
            # (impact, place, impact for the order: an estimate capped at EST_CAP, so a prediction never outranks a
            # measured PRPG! + BPM; who gets in uses the uncapped one, so the cap only orders the Hall)
            IMP[(s, M(p["name"]) + "|" + p["school"])] = (imp_of[id(p)], place[id(p)],
                                                          imp_of[id(p)] if p in real else min(EST_CAP, imp_of[id(p)]))
    # --- Most Improved Player: the biggest jump in impact (the resume's PRPG! + BPM percentile) from the season before
    # at the same school, both seasons qualified; statewide and in each conference (a tie: the bigger jump in points a game)
    MIP, MIP_ST = {}, {}
    for i, s in enumerate(past[1:], 1):
        pv = past[i - 1]
        if int(s[:2]) != int(pv[:2]) + 1:
            continue
        cand = []
        for p in players[s]:
            k = M(p["name"]) + "|" + p["school"]
            if (s, k) in IMP and (pv, k) in IMP:
                cand.append((IMP[(s, k)][0] - IMP[(pv, k)][0],
                             (p.get("ppg") or 0) - (P[k]["seasons"][pv].get("ppg") or 0), k, p.get("conference")))
        if cand:
            MIP_ST[s] = max(cand)[2]
            byc = defaultdict(list)
            for x in cand:
                if x[3]:
                    byc[x[3]].append(x)
            for c, xs in byc.items():
                MIP[(s, max(xs)[2])] = c
    # Freshman of the Year and Most Improved count in honors like Sixth Man (1); the statewide Most Improved 1 more
    for (s, k) in list(FOY) + list(MIP):
        if k in P:
            P[k]["aw"] += 1
    for s, k in MIP_ST.items():
        P[k]["aw"] += 1
    rows = []
    for k in cands + JC:
        school = k.split("|")[1]
        ss = [(s, IMP[(s, k)]) for s in P[k]["seasons"] if (s, k) in IMP]
        if not ss:
            ss = [(s, (.5, 3, .5)) for s in P[k]["seasons"]]
        imps = sorted((x[1][0] for x in ss), reverse=True)
        impact = (2 * imps[0] + (imps[1] if len(imps) > 1 else imps[0])) / 3
        ic = sorted((x[1][2] for x in ss), reverse=True)
        impact_c = (2 * ic[0] + (ic[1] if len(ic) > 1 else ic[0])) / 3
        win = 0
        for s, (_, pl, _c) in ss:
            role = [1, .9, .8, .7][pl] if pl < 4 else .6
            tm = TEAM.get((s, school), {"wp": .5, "netp": .5})
            r_ = runs(s, school)
            run = 1 if "state" in r_ else .7 if "fin" in r_ else .5 if "f4" in r_ else .3 if "e8" in r_ else 0
            win += role * (.4 * tm["wp"] + .3 * tm["netp"] + .3 * run)
        win /= max(1, len(ss)) ** .5
        Q = {q: [0, 0, 0.0] for q in ("1A", "1", "2", "3", "4")}
        for r in GAMES.get(k, []):
            if r["quad"]:
                Q[r["quad"]][0 if r["w"] else 1] += 1
                Q[r["quad"]][2] += r["gs"]
        n = sum(x[0] + x[1] for x in Q.values())
        qval = sum(x[0] * QWIN[q] - x[1] * QLOSS[q] for q, x in Q.items()) / n if n else 0
        t12 = [Q[q] for q in ("1A", "1", "2")]
        n12 = sum(x[0] + x[1] for x in t12)
        rows.append({"k": k, "impact": impact, "impact_c": impact_c, "win": win, "qval": qval, "bgs": sum(x[2] for x in t12) / n12 if n12 else 0,
                     "bgn": n12, "hon": P[k]["aw"], "quads": {q: Q[q][:2] for q in Q}})
    for c in ("impact", "impact_c", "win", "qval", "bgs", "hon"):
        f = _pct_fn([r[c] for r in rows if r["k"] in HOFC])
        for r in rows:
            r[c + "_p"] = f(r[c])
    for r in rows:
        rel = min(1, r["bgn"] / 10)
        r["big"] = .6 * r["qval_p"] + .4 * (rel * r["bgs_p"] + (1 - rel) * .5)
    f = _pct_fn([r["big"] for r in rows if r["k"] in HOFC])
    for r in rows:
        r["big_p"] = f(r["big"])
        r["score"] = 100 * (.35 * r["win_p"] + .30 * r["impact_p"] + .20 * r["hon_p"] + .15 * r["big_p"])
        r["score_o"] = 100 * (.35 * r["win_p"] + .30 * r["impact_c_p"] + .20 * r["hon_p"] + .15 * r["big_p"])
    JROWS = [r for r in rows if r["k"] not in HOFC]
    rows = [r for r in rows if r["k"] in HOFC]
    rows.sort(key=lambda r: -r["score"])
    for r in rows:          # in: a resume at the cut or better; once in, always in
        v, school = P[r["k"]], r["k"].split("|")[1]
        ppg = max((p_.get("ppg") or 0) for p_ in v["seasons"].values())
        # automatic (the NBA's MVP / multi-time All-Star / elite-scorer pattern): Region Player of the Year, two
        # first-team All-States, or a top-1% scoring season (SCORER_PPG+) as a first-team All-State
        auto = v["poy"] or len(v["as1"]) >= 2 or ppg >= SCORER_PPG
        # the scoring floor: a top-25% scoring season (FLOOR_PPG+), unless he's a role-player Hall of Famer (the
        # Naismith's Cooper / Rodman / Ginobili / K.C. Jones): a defensive, sixth-man or Player of the Year award, a Gold
        # or Hall of Fame Glue Guy / Rim Protector season, Defensive Anchor, or a state title / Final Four
        bd = [b for p_ in v["seasons"].values() for b in (p_.get("bdg") or [])]
        role = (any(b[0] in ("cdpoy", "c6moy", "cpoy", "anchor") for b in bd)
                or any(b[0] in ("glue", "rimprot") and b[1] >= 3 for b in bd)
                or any(runs(s, school) & {"state", "fin", "f4"} for s in v["seasons"]))
        if auto or (r["score"] >= RESUME_CUT and (ppg >= FLOOR_PPG or role)):
            store["inducted"].setdefault(r["k"], prev.get(r["k"]) or {"since": datetime.now().strftime("%Y-%m-%d")})
    STORE.write_text(json.dumps(store, indent=1, sort_keys=True) + "\n")
    rows = [r for r in rows if r["k"] in store["inducted"]]
    for r in rows:          # the order (and the score shown): the capped estimate
        r["score_o"] = 100 * (.35 * r["win_p"] + .30 * r["impact_c_p"] + .20 * r["hon_p"] + .15 * r["big_p"])
    rows.sort(key=lambda r: -r["score_o"])
    keys = [r["k"] for r in rows]
    K = set(keys)

    # --- State Tournament MVP: the champion's last three games, a blend (Game Score is one part) ---
    MVP = {}
    for s in past:
        champ = next((t for t, a in TITLES.get(s, {}).items() if any(x[0] == "state" for x in a)), None)
        if not champ:
            continue
        gs3 = sorted([g for g in BX.get(s, {}).values() if isinstance(g["t"].get(champ), dict) and len(g.get("sc") or {}) == 2],
                     key=lambda g: _date(g["d"]))[-3:]
        tot = defaultdict(Counter)
        for g in gs3:
            tb = g["t"][champ]
            for row in tb["__r"]:
                r = dict(zip(tb["__c"], row))
                c = tot[M(r["n"])]
                gs = GS(r)
                c["gs"] += gs
                c["g"] += 1
                for f in ("pts", "or", "dr", "ast", "stl", "blk", "fgm", "fga", "fta"):
                    c[f] += r[f]
                if r.get("bpm") is not None and (r.get("min") or 0) > 0:
                    c["bm"] += r["bpm"] * r["min"]
                    c["m"] += r["min"]
                if g is gs3[-1]:
                    c["fin"] += gs
        pool = {n: c for n, c in tot.items() if c["g"] >= 2}
        if not pool:
            continue
        met = {n: {"gs": c["gs"], "pts": c["pts"], "reb": c["or"] + c["dr"], "ast": c["ast"], "stk": c["stl"] + c["blk"],
                   "ts": (c["pts"] / (2 * (c["fga"] + .44 * c["fta"])) if c["fga"] + c["fta"] else 0) * min(1, (c["fga"] + .44 * c["fta"]) / 20),
                   "bpm": c["bm"] / c["m"] if c["m"] else None, "fin": c["fin"]} for n, c in pool.items()}
        W = {"gs": .25, "pts": .15, "reb": .1, "ast": .1, "stk": .05, "ts": .1, "bpm": .1, "fin": .15}
        Z = {f: _z([m[f] for m in met.values()]) for f in W}

        def blend(n):
            num = den = 0
            for f, w in W.items():
                if met[n][f] is not None:
                    num += w * Z[f](met[n][f])
                    den += w
            return num / den
        n = max(pool, key=blend)
        c = pool[n]
        MVP[s] = {"name": n, "team": champ, "line": f"{c['pts'] / c['g']:.1f} pts, {(c['or'] + c['dr']) / c['g']:.1f} reb, "
                                                    f"{c['ast'] / c['g']:.1f} ast a game, {c['fgm']}-{c['fga']} FG"}

    # --- State All-Tournament Team: the five best players of the state tournament (Elite Eight on, every team), the
    # MVP aside; the same blend as the MVP, totals and per game both counting ---
    ALLT = {}
    for s, (qd, last, e8) in TOUR.items():
        if not qd:
            continue
        tot = defaultdict(Counter)
        for g in BX.get(s, {}).values():
            if len(g.get("sc") or {}) != 2 or not set(g["sc"]) <= e8 or not qd <= _date(g["d"]) <= last:
                continue
            for team, tb in g["t"].items():
                if not isinstance(tb, dict):
                    continue
                for row in tb["__r"]:
                    r = dict(zip(tb["__c"], row))
                    c = tot[M(r["n"]) + "|" + team]
                    c["g"] += 1
                    c["gs"] += GS(r)
                    for f in ("pts", "or", "dr", "ast", "stl", "blk", "fga", "fta"):
                        c[f] += r[f]
                    if r.get("bpm") is not None and (r.get("min") or 0) > 0:
                        c["bm"] += r["bpm"] * r["min"]
                        c["m"] += r["min"]
        mv = MVP.get(s)
        pool = {k: c for k, c in tot.items() if c["gs"] > 0 and not (mv and k == mv["name"] + "|" + mv["team"])}
        if not pool:
            continue
        met = {k: {"gs": c["gs"], "gpg": c["gs"] / c["g"], "pts": c["pts"] / c["g"], "reb": (c["or"] + c["dr"]) / c["g"],
                   "ast": c["ast"] / c["g"], "stk": (c["stl"] + c["blk"]) / c["g"],
                   "ts": (c["pts"] / (2 * (c["fga"] + .44 * c["fta"])) if c["fga"] + c["fta"] else 0) * min(1, (c["fga"] + .44 * c["fta"]) / (7 * c["g"])),
                   "bpm": c["bm"] / c["m"] if c["m"] else None} for k, c in pool.items()}
        W = {"gs": .2, "gpg": .2, "pts": .15, "reb": .1, "ast": .1, "stk": .05, "ts": .1, "bpm": .1}
        Z = {f: _z([m[f] for m in met.values()]) for f in W}
        sc = {k: sum(w * Z[f](met[k][f]) for f, w in W.items() if met[k][f] is not None)
              / sum(w for f, w in W.items() if met[k][f] is not None) for k in met}
        ALLT[s] = sorted(sc, key=lambda k: -sc[k])[:5]

    # --- records (Record Book #1s, ties included) for the signature-game tags ---
    REC = defaultdict(list)
    RECOPP = {}

    def tops(lst):
        return [x for x in lst if lst and x[0] == lst[0][0]]
    if "records_state.js" in season_files:
        st = _obj(season_files["records_state.js"])["lists"]
        for per, lab in [("all", "State record")] + [(p, "State season high") for p in st if p != "all"]:
            for c, nm in REC_CATS.items():
                tl = tops(st.get(per, {}).get("ig_" + c, []))
                for x in tl:     # shared with someone else: "Tied ..."
                    RECOPP[(M(x[1]) + "|" + x[2], x[4])] = x[3]
                    REC[(M(x[1]) + "|" + x[2], x[4])].append(f"{'Tied ' + lab[0].lower() + lab[1:] if len(tl) > 1 else lab}: {x[0]} {nm}")
    for fn, js in season_files.items():
        if fn.startswith("records_") and fn != "records_state.js" and not fn.endswith("_cur.js") and fn.endswith(".js"):
            a = _obj(js)["lists"].get("all", {})
            for c, nm in REC_CATS.items():
                tl = tops(a.get("ig_" + c, []))
                for x in tl:
                    RECOPP[(M(x[1]) + "|" + x[2], x[4])] = x[3]
                    REC[(M(x[1]) + "|" + x[2], x[4])].append(f"{'Tied school record' if len(tl) > 1 else 'School record'}: {x[0]} {nm}")

    # --- per inductee: Hall of Fame badge lines, honors by season, signature games, career averages ---
    STAT = ["gp", "ppg", "rpg", "apg", "spg", "bpg", "tpm", "tpa", "tpp", "twom", "twoa", "twop", "ftm", "fta", "ftp", "bpm",
            "obpm", "dbpm", "ws", "usage_pct", "shot_pct", "stl_pct", "blk_pct", "ast_rate", "oreb_pct", "dreb_pct"]
    # height (typed in, else the 2025-26 roster pages) and box-score position(s) for the plaque
    try:
        HT = json.loads(Path(__file__).with_name("hall_of_fame_heights.json").read_text())
    except Exception:
        HT = {}
    roster_ht = []
    try:
        import csv
        for r in csv.DictReader(open(Path(__file__).with_name("internal_data") / "roster_heights_2025_26.csv", encoding="utf-8")):
            m = re.search(r"([4-7])\s*['’\-]\s*(\d{1,2})", r.get("height") or "")
            if m:
                roster_ht.append((r["player"].lower(), r["team"].lower(), f"{m[1]}'{int(m[2])}\""))
    except Exception:
        pass

    def height(k, v):
        if HT.get(k):
            return HT[k]
        name, school = k.split("|")
        if "2526" not in v["seasons"]:
            return None
        hits = {h for p_, t_, h in roster_ht if name.lower() in p_ and (school.lower() in t_ or school.split()[0].lower() in t_)}
        if not hits:     # team names on the roster pages vary ("West Valley Basketball"): the name alone, if only one
            hits = {h for p_, t_, h in roster_ht if name.lower() in p_}
        return hits.pop() if len(hits) == 1 else None
    bio = {}
    hof, hon, games, career, car = [], {}, {}, {}, {}
    for k in keys:
        name, school = k.split("|")
        v = P[k]
        car[k] = {"as1": v["as1"], "poy": v["poy"]}
        # one position: the season he played the most games (the later one on a tie)
        ps = [(p_.get("gp") or 0, s, p_.get("pos")) for s, p_ in v["seasons"].items() if p_.get("pos")]
        bio[k] = {"ht": height(k, v), "pos": [max(ps)[2]] if ps else []}
        hon[k] = []
        for s in sorted(v["seasons"]):
            p = v["seasons"][s]
            for b in p.get("bdg") or []:
                if b[1] == 4:
                    hof.append(dict({f: p.get(f) for f in STAT}, season=s, code=b[0], name=name, school=school))
            bd = [list(b) for b in p.get("bdg") or []]
            if (s, k) in FOY:
                bd.insert(0, ["cfoy", 3, 0, FOY[(s, k)]])
            if (s, k) in MIP:
                bd.insert(0, ["cmip", 3, 0, MIP[(s, k)]])
            if MIP_ST.get(s) == k:
                bd.insert(0, ["mip", 3, 0, "State"])
            hon[k].append({"s": s, "region": p.get("region"), "conf": p.get("conference"), "b": bd,
                           "team": TITLES.get(s, {}).get(school, []), "gp": p.get("gp")})
        gl = [g for g in GAMES.get(k, []) if g["ccc"]]
        okb = [g for g in gl if g["bpm"] is not None and (g["min"] or 0) >= 15]
        hiG = max(gl, key=lambda g: g["gs"]) if gl else None
        hiB = max(okb, key=lambda g: g["bpm"]) if okb else None
        sel = []
        for g in gl:
            tags = list(dict.fromkeys(REC.get((k, g["d"]), [])))
            if sum(x >= 10 for x in (g["pts"], g["reb"], g["ast"], g["stl"], g["blk"])) >= 3:
                tags.insert(0, "Triple-double")
            if g is hiB:
                tags.insert(0, "Career-high BPM")
            if g is hiG:
                tags.insert(0, "Career-high Game Score")
            if g["gs"] >= P99 or (g in okb and g["bpm"] >= B99) or tags:
                sel.append(dict(g, tags=tags))
        if len(sel) < 3:
            have = {(g["d"], g["opp"]) for g in sel}
            for g in sorted(gl, key=lambda g: -g["gs"]):
                if len(sel) >= 3:
                    break
                if (g["d"], g["opp"]) not in have:
                    sel.append(dict(g, tags=[]))
        sel.sort(key=lambda g: (g["net"] is None, -(g["net"] or 0)))
        keep = ("s", "d", "opp", "net", "rk", "N", "w", "score", "gs", "bpm", "pts", "reb", "ast", "stl", "blk", "tpm",
                "fgm", "fga", "tags")
        games[k] = [{f: g[f] for f in keep} for g in sel]
        c = Counter()
        for g in gl:
            c["gp"] += 1
            c["pts"] += g["pts"]
            c["reb"] += g["reb"]
            c["ast"] += g["ast"]
            c["stl"] += g["stl"]
            c["blk"] += g["blk"]
            c["tpm"] += g["tpm"]
            tens = sum(x >= 10 for x in (g["pts"], g["reb"], g["ast"], g["stl"], g["blk"]))
            c["dd"] += tens >= 2
            c["td"] += tens >= 3
            if g["bpm"] is not None and (g["min"] or 0) > 0:
                c["bm"] += g["bpm"] * g["min"]
                c["m"] += g["min"]
        if c["gp"]:
            career[k] = {"gp": c["gp"], "ppg": round(c["pts"] / c["gp"], 1), "rpg": round(c["reb"] / c["gp"], 1),
                         "apg": round(c["ast"] / c["gp"], 1), "bpm": (lambda ss: round(sum(p_["bpm"] * p_["gp"] * (p_.get("mpg") or 1) for p_ in ss) / sum(p_["gp"] * (p_.get("mpg") or 1) for p_ in ss), 1) if ss else None)(
                             [p_ for p_ in P[k]["seasons"].values() if p_.get("bpm") is not None and p_.get("gp")]),
                         "dd": c["dd"], "td": c["td"],
                         # career totals (CCCAA games)
                         "tot": {f: c[f] for f in ("pts", "reb", "ast", "stl", "blk", "tpm")}}
    res = {r["k"]: {"score": round(r["score_o"], 1), "win": round(100 * r["win_p"]), "impact": round(100 * r["impact_c_p"]),
                    "hon": round(100 * r["hon_p"]), "big": round(100 * r["big_p"]), "quads": r["quads"]} for r in rows}
    # --- Retired Jerseys: each school's best careers, judged against its own players (less strict than the Hall):
    # every Hall of Famer from the school, then its best other resumes, JERSEYS_MAX in all ---
    try:
        from generate_team_pages import SCHOOL_COLORS, SCHOOL_SECONDARY_COLORS
    except Exception:
        SCHOOL_COLORS, SCHOOL_SECONDARY_COLORS = {}, {}
    sc_of = {r["k"]: r["score_o"] for r in rows + JROWS}
    by_school = defaultdict(list)
    for k in keys:
        by_school[k.split("|")[1]].append(k)
    def jersey_worthy(k):
        """All-State (any), a Player of the Year award (region / conference / offensive / defensive / sixth man), two
        All-Conference 1st Teams, or a state title at that school."""
        v, school = P[k], k.split("|")[1]
        bd = [b for p_ in v["seasons"].values() for b in (p_.get("bdg") or [])]
        return (any(b[0] == "allstate" for b in bd) or any(b[0] in ("poy", "cpoy", "copoy", "cdpoy", "c6moy") for b in bd)
                or sum(1 for b in bd if b[0] == "allconf" and b[1] >= 3) >= 2
                or any("state" in runs(s, school) for s in v["seasons"]))
    for r in sorted(JROWS, key=lambda r: -r["score_o"]):
        sch = r["k"].split("|")[1]
        if len(by_school[sch]) < JERSEYS_MAX and jersey_worthy(r["k"]):
            by_school[sch].append(r["k"])

    def jersey(k):
        name, school = k.split("|")
        v = P[k]
        # the number he wore in the most games (a tie: the later season's)
        nums = Counter(str(g["j"]).lstrip("#") for g in GAMES.get(k, []) if g.get("j") not in (None, ""))
        last = {str(g["j"]).lstrip("#"): g["s"] for g in sorted(GAMES.get(k, []), key=lambda g: g["s"]) if g.get("j") not in (None, "")}
        nums = Counter({n_: (c_, last.get(n_, "")) for n_, c_ in nums.items()})
        bd = [(s, b) for s, p_ in v["seasons"].items() for b in (p_.get("bdg") or [])]
        Y = lambda ss: ", ".join("20" + s[:2] + "-" + s[2:] for s in sorted(set(ss)))
        yrs_of = lambda f: [s for s, b in bd if f(b)]
        parts = []      # each award with the season(s) in front, named for its region / conference:
        # "2019-20 North Region Player of the Year", "2023-24 WSC North Defensive Player of the Year"
        named = defaultdict(list)
        for s, b in bd:
            conf = b[3] if len(b) > 3 and b[3] else (v["seasons"][s].get("conference") or "Conference")
            lab = {"poy": f"{v['seasons'][s].get('region') or ''} Region Player of the Year".strip(),
                   "cpoy": f"{conf} Player of the Year", "cdpoy": f"{conf} Defensive Player of the Year",
                   "copoy": f"{conf} Offensive Player of the Year", "c6moy": f"{conf} Sixth Man of the Year"}.get(b[0])
            if lab:
                named[lab].append(s)
        for s in v["seasons"]:
            if (s, k) in FOY:
                named[f"{FOY[(s, k)]} Freshman of the Year"].append(s)
            if (s, k) in MIP:
                named[f"{MIP[(s, k)]} Most Improved Player"].append(s)
            if MIP_ST.get(s) == k:
                named["State Most Improved Player"].append(s)
        for lab, ss in sorted(named.items(), key=lambda x: (min(x[1]), "Region" not in x[0])):
            parts.append(f"{Y(ss)} {lab}")
        for label, ss in (("All-State 1st Team", yrs_of(lambda b: b[0] == "allstate" and b[1] >= 3)),
                          ("All-State Honorable Mention", yrs_of(lambda b: b[0] == "allstate" and b[1] == 2)),
                          ):
            if ss:
                parts.append(f"{Y(ss)} {label}")
        cf = defaultdict(list)      # All-Conference and conference titles named too: "All-WSC North 1st Team"
        for s in yrs_of(lambda b: b[0] == "allconf" and b[1] >= 3):
            cf[f"All-{v['seasons'][s].get('conference') or 'Conference'} 1st Team"].append(s)
        for lab, ss in cf.items():
            parts.append(f"{Y(ss)} {lab}")
        for code, label in (("state", "State Champion"), ("f4", "Final Four")):
            ss = [s for s in v["seasons"] if any(x[0] == code for x in TITLES.get(s, {}).get(school, []))]
            if ss:
                parts.append(f"{Y(ss)} {label}")
        ct = defaultdict(list)
        for s in v["seasons"]:
            for x in TITLES.get(s, {}).get(school, []):
                if x[0] == "conf":
                    ct[x[1]].append(s)     # "WSC North Champions" / "Co-Champions"
        for lab, ss in ct.items():
            parts.append(f"{Y(ss)} {lab}")
        # each record with its opponent and date: "School record: 42 points vs Santa Ana, 12/15/2023"
        recs = sorted({f"{tg} vs {RECOPP.get((kk, d), '?')}, {d}" for (kk, d), tags in REC.items() if kk == k for tg in tags
                       if tg.startswith(("School record", "Tied school", "State record", "Tied state"))})
        gl = [g for g in GAMES.get(k, []) if g["ccc"]]
        gp = len(gl)

        def stat_line(g):
            s_ = [f"{g['pts']} pts"] + [f"{g[f]} {lab}" for f, lab, m in (("reb", "reb", 5), ("ast", "ast", 4), ("stl", "stl", 3),
                                                                        ("blk", "blk", 3), ("tpm", "3PM", 4)) if g[f] >= m]
            return f"{', '.join(s_)} vs {g['opp']}, {g['d']} ({'W' if g['w'] else 'L'} {g['score']})"
        best = [stat_line(g) for g in sorted(gl, key=lambda g: -g["gs"])[:3]]   # his three best games (Game Score)
        ps = [(p_.get("gp") or 0, s, p_.get("pos")) for s, p_ in v["seasons"].items() if p_.get("pos")]
        return {"k": k, "name": name, "j": nums.most_common(1)[0][0] if nums else "", "hof": k in K,
                "ht": height(k, v), "pos": max(ps)[2] if ps else "",
                "yrs": sorted(v["seasons"]), "why": parts, "recs": recs, "best": best, "score": round(sc_of.get(k, 0), 1),
                "tot": {f: sum(g[f] for g in gl) for f in ("pts", "reb", "ast", "stl", "blk", "tpm")} | {"gp": gp},
                "line": (f"{sum(g['pts'] for g in gl) / gp:.1f} pts, {sum(g['reb'] for g in gl) / gp:.1f} reb, "
                         f"{sum(g['ast'] for g in gl) / gp:.1f} ast") if gp else ""}
    jerseys = {s: sorted([jersey(k) for k in ks], key=lambda j: (not j["hof"], -j["score"])) for s, ks in by_school.items()}
    colors = {s: [SCHOOL_COLORS.get(s), SCHOOL_SECONDARY_COLORS.get(s)] for s in jerseys}

    # --- Awards (the Hall of Fame page's Awards view): every season's champions, state tournament, Players of the
    # Year, All-State and each conference's awards and All-Conference teams (our picks) ---
    awards = {}
    for s in past:
        A = {"state": {}, "poy": {}, "allstate": {"first": [], "hm": []}, "conf": {}}
        ttl = TITLES.get(s, {})
        for code, key in (("state", "champ"), ("fin", "final"), ("f4", "f4"), ("e8", "e8")):
            A["state"][key] = sorted(tm for tm, l in ttl.items() if any(x[0] == code for x in l))
        A["state"]["runner"] = sorted(set(A["state"]["final"]) - set(A["state"]["champ"]))
        A["state"]["canceled"] = s == "1920"
        if s in MVP:
            A["state"]["mvp"] = MVP[s]["name"] + "|" + MVP[s]["team"]
        A["state"]["allt"] = ALLT.get(s, [])
        A["mip"] = MIP_ST.get(s)
        conf = defaultdict(lambda: {"champ": [], "first": [], "second": []})
        for tm, l in ttl.items():
            for x in l:
                if x[0] == "conf":
                    conf[x[1].replace(" Co-Champions", "").replace(" Champions", "")]["champ"].append(tm)
        champ_conf = {tm: c for c, d in conf.items() for tm in d["champ"]}
        for pl in players[s]:
            k = M(pl["name"]) + "|" + pl["school"]
            c = pl.get("conference") or "?"
            for b in pl.get("bdg") or []:
                if b[0] == "poy":
                    A["poy"][pl.get("region") or "?"] = k
                elif b[0] == "allstate":
                    A["allstate"]["first" if b[1] >= 3 else "hm"].append(k)
                elif b[0] in ("cpoy", "copoy", "cdpoy", "c6moy"):
                    conf[c][b[0]] = k
                elif b[0] == "allconf":
                    conf[c]["first" if b[1] >= 3 else "second"].append(k)
            if (s, k) in FOY:
                conf[c]["cfoy"] = k
            if (s, k) in MIP:
                conf[c]["cmip"] = k
        # a first-team All-State fills his All-Conference spot but shows All-State: list him on the first team too
        for k in A["allstate"]["first"]:
            pl = P[k]["seasons"].get(s, {})
            c = pl.get("conference")
            if c and k not in conf[c]["first"] and conf[c]["first"]:
                conf[c]["first"].append(k)
        A["conf"] = {c: dict(d) for c, d in sorted(conf.items()) if c != "?"}
        awards[s] = A

    # --- Coach of the Year (North / South and each conference, 2021-22 on): the most with the least, and success.
    # Over-achievement 40%: his net rating above what the roster he came in with predicted (last season's net rating and
    # the share of last season's points that came back, fitted on every team, every season); success 60%: WAB 25%
    # (winning against the schedule played: strength of schedule built in), conference win % lifted by the conference's
    # strength 15%, the run 20% (conference title, Elite Eight, Final Four, title game, state title). A .600 record or
    # better (and .600 in conference or its title) to be considered; z-scores within the season. Names: coaches.json, else
    # the Keys tenures; none = the page shows the school's head coach as TBD. ---
    import numpy as np
    try:
        COACH = json.loads((Path(__file__).resolve().parent / "coaches.json").read_text())
    except Exception:
        COACH = {}
    # past seasons' coaches from the Keys tab's tenures (generate_leaderboard KEYS_TEAMS: "seasons", else the whole
    # 2021-22 on window for a "5yr" coach); coaches.json wins where it names one
    try:
        import ast
        src = (Path(__file__).resolve().parent / "generate_leaderboard.py").read_text()
        i0 = src.index("KEYS_TEAMS = [")
        i1, depth = i0 + len("KEYS_TEAMS = "), 0
        for j in range(i1, len(src)):
            depth += {"[": 1, "]": -1}.get(src[j], 0)
            if depth == 0:
                break
        for e in ast.literal_eval(src[i1:j + 1]):
            if "5yr" in e.get("windows", []):
                for sy_ in e.get("seasons") or ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]:
                    COACH.setdefault(e["team"], {})
                    COACH[e["team"]][sy_] = COACH[e["team"]].get(sy_) or e["coach"]
    except Exception as ex:
        print("  Coach of the Year: Keys tenures not read:", ex)
    rec = lambda x: (lambda m: (int(m[1]), int(m[2])) if m else (0, 0))(re.match(r"(\d+)-(\d+)", x or ""))
    def pts_by(s, school):
        return {M(p_["name"]): (p_.get("ppg") or 0) * (p_.get("gp") or 0) for p_ in players[s] if p_["school"] == school}
    X, Y, KEY = [], [], []
    for i, s in enumerate(past[1:], 1):
        pv = past[i - 1]
        prev = {t_["team"]: t_ for t_ in teams[pv]}
        for t_ in teams[s]:
            tp = prev.get(t_["team"])
            if not tp or not (t_.get("ortg") or 0) or (t_.get("gp") or 0) < 15:
                continue
            a, b = pts_by(pv, t_["team"]), pts_by(s, t_["team"])
            ret = sum(v_ for n_, v_ in a.items() if n_ in b) / (sum(a.values()) or 1)
            X.append([tp.get("net_rtg") or 0, ret, (tp.get("net_rtg") or 0) * ret, 1])
            Y.append(t_.get("net_rtg") or 0)
            KEY.append((s, t_["team"]))
    coef = np.linalg.lstsq(np.array(X), np.array(Y), rcond=None)[0] if X else None
    OVER = {k_: (y_ - float(np.dot(x_, coef)), float(np.dot(x_, coef)), x_[1]) for k_, x_, y_ in zip(KEY, X, Y)}
    COY = {}
    for s in [x for x in past if x >= "2122"]:
        sy = "20" + s[:2] + "-" + s[2:]
        try:
            wf = Path(__file__).resolve().parent / (f"wab_results_{sy.replace('-', '_')}.json" if s != "2526" else "wab_results.json")
            WAB = {w["team"]: w["wab"] for w in json.loads(wf.read_text())}
        except Exception:
            WAB = {}
        cnet = defaultdict(list)
        for t_ in teams[s]:
            if (t_.get("ortg") or 0) and t_.get("conference"):
                cnet[t_["conference"]].append(t_.get("net_rtg") or 0)
        cstr = {c: sum(v_) / len(v_) for c, v_ in cnet.items()}
        zc = _z(list(cstr.values()))
        rows_ = []
        for t_ in teams[s]:
            tm = t_["team"]
            if (s, tm) not in OVER:
                continue
            w, l = rec(t_.get("record"))
            cw, cl = rec(t_.get("conf"))
            r_ = runs(s, tm) | ({"conf"} if any(x[0] == "conf" for x in TITLES.get(s, {}).get(tm, [])) else set())
            run = ("conf" in r_) + max([4 if "state" in r_ else 3 if "fin" in r_ else 2 if "f4" in r_ else 1 if "e8" in r_ else 0])
            rows_.append({"team": tm, "region": t_.get("region"), "conf": t_.get("conference"), "wp": w / (w + l) if w + l else 0,
                          "record": t_.get("record"), "crec": t_.get("conf"), "over": OVER[(s, tm)][0], "exp": OVER[(s, tm)][1],
                          "ret": OVER[(s, tm)][2], "net": t_.get("net_rtg") or 0, "wab": WAB.get(tm),
                          "cwp": cw / (cw + cl) if cw + cl else 0, "cq": (cw / (cw + cl) if cw + cl else 0) + .25 * zc(cstr.get(t_.get("conference"), 0)), "run": run,
                          "stage": "State Champions" if "state" in r_ else "State Runner-up" if "fin" in r_ else
                                   "Final Four" if "f4" in r_ else "Elite Eight" if "e8" in r_ else "",
                          "ctitle": "conf" in r_})
        if not rows_:
            continue
        zo, zw, zq, zr = (_z([r[f] for r in rows_ if r[f] is not None]) for f in ("over", "wab", "cq", "run"))
        for r in rows_:
            r["score"] = COY_W[0] * zo(r["over"]) + COY_W[1] * (zw(r["wab"]) if r["wab"] is not None else 0) + COY_W[2] * zq(r["cq"]) + COY_W[3] * zr(r["run"])
        # success to be considered: a .600 record and a .600 conference record (or the conference title)
        ok = [r for r in rows_ if r["wp"] >= .6 and (r["ctitle"] or r["cwp"] >= .6)]
        out = {"region": {}, "conf": {}}
        for key_, grp in (("region", lambda r: r["region"]), ("conf", lambda r: r["conf"])):
            by = defaultdict(list)
            for r in ok:
                if grp(r):
                    by[grp(r)].append(r)
            for g, rs in by.items():
                b = max(rs, key=lambda r: r["score"])
                why = [b["record"] + (f" ({b['crec']} conf)" if b["crec"] else ""),
                       f"net {b['net']:+.1f}, {b['over']:+.1f} over the {b['exp']:+.1f} his roster projected ({round(100 * b['ret'])}% of last season's points back)"]
                if b["wab"] is not None:
                    why.append(f"WAB {b['wab']:+.1f}")
                why += [x for x in (b["stage"], "conference champions" if b["ctitle"] else "") if x]
                out[key_][g] = {"team": b["team"], "coach": (COACH.get(b["team"]) or {}).get(sy) or "", "why": why}
        COY[s] = out
    for s, A in awards.items():
        if s in COY:
            A["coy"] = COY[s]["region"]
            for c, d in A["conf"].items():
                if c in COY[s]["conf"]:
                    d["coy"] = COY[s]["conf"][c]

    return {"awards": awards, "jerseys": jerseys, "colors": colors, "order": keys, "bio": bio, "hof": hof, "car": car, "hon": hon, "games": games, "career": career, "res": res,
            "mvp": MVP, "allt": ALLT, "players": len(all_names)}


def write(season_files):
    """{'hof.js': ...} for season_data (the Hall of Fame page reads it). A --fast build carries only the current
    season's files: the past seasons (season_, boxes_, records_) are read from the saved season_data then."""
    files = dict(season_files)
    sd = Path(__file__).resolve().parent.parent / "season_data"
    for f in sd.glob("*.js"):
        if f.name.startswith(("season_", "boxes_", "records_", "rosters_")) and (
                f.name not in files or len(files[f.name]) < f.stat().st_size // 2):   # --fast: past seasons left empty
            files[f.name] = f.read_text(encoding="utf-8")
    data = build(files)
    if not data["order"]:
        print("  Hall of Fame: no data, season_data/hof.js left as it was")
        return {}
    print(f"  Hall of Fame: {len(data['order'])} inductees of {data['players']} players")
    return {"hof.js": "__installHof(" + json.dumps(data, separators=(",", ":")) + ");\n"}
