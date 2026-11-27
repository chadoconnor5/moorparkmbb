"""Hall of Fame (leaderboard sidebar -> Hall of Fame; the page is ../hof.html, its data ../season_data/hof.js).

Who gets in: a first-team All-State player (Gold or Hall of Fame All-State badge) whose career is over (not on a
current-season roster at that school) with a resume score of RESUME_CUT or better (the top 2% of players through
2025-26). Badges don't decide it: the resume does. Once in, always in: hall_of_fame.json keeps every inductee and a
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
RESUME_CUT = 43.2                  # resume score to get in: the top 2% of players (134 of 6,716) through 2025-26; kept fixed
FRESHMAN_NOT = {("2223", "Javohn Garcia"), ("2122", "Jonathan Ogugua"), ("2122", "Conner Jackson"), ("2122", "Scott Ator")}   # confirmed not freshmen that season
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
                        "gs": round(gs, 1), "bpm": r.get("bpm"), "min": r.get("min"), "pts": r["pts"], "reb": r["or"] + r["dr"],
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
    # the pool scored: every first-team All-State player whose career is over, plus everyone already inducted
    cands = [k for k, v in P.items() if v["as1"] and k not in active]
    cands += [k for k in store["inducted"] if k in P and k not in cands]

    # --- resume score ---
    IMP = {}
    for s in past:
        q = [p for p in players[s] if p.get("q") and p.get("gp")]
        real = [p for p in q if not p.get("fm") and p.get("porp") is not None and p.get("bpm") is not None]
        zp, zb = _z([p["porp"] for p in real]), _z([p["bpm"] for p in real])
        rv = _pct_fn([zp(p["porp"]) + zb(p["bpm"]) for p in real])
        gsp = lambda p: ((p.get("ppg") or 0) + 0.7 * (p.get("apg") or 0) + 0.5 * (p.get("rpg") or 0) + (p.get("spg") or 0)
                         + 0.7 * (p.get("bpg") or 0) - (p.get("topg") or 0))
        fmv, allv = _pct_fn([gsp(p) for p in q if p.get("fm")]), _pct_fn([gsp(p) for p in q])
        pra = lambda p: (p.get("ppg") or 0) + (p.get("rpg") or 0) + (p.get("apg") or 0)
        place = {}
        for sch in {p["school"] for p in q}:
            for i, p in enumerate(sorted([x for x in q if x["school"] == sch], key=lambda x: -pra(x))):
                place[id(p)] = i
        for p in q:
            imp = rv(zp(p["porp"]) + zb(p["bpm"])) if p in real else fmv(gsp(p)) if p.get("fm") else allv(gsp(p))
            IMP[(s, M(p["name"]) + "|" + p["school"])] = (imp, place[id(p)])
    rows = []
    for k in cands:
        school = k.split("|")[1]
        ss = [(s, IMP[(s, k)]) for s in P[k]["seasons"] if (s, k) in IMP]
        if not ss:
            ss = [(s, (.5, 3)) for s in P[k]["seasons"]]
        imps = sorted((x[1][0] for x in ss), reverse=True)
        impact = (2 * imps[0] + (imps[1] if len(imps) > 1 else imps[0])) / 3
        win = 0
        for s, (_, pl) in ss:
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
        rows.append({"k": k, "impact": impact, "win": win, "qval": qval, "bgs": sum(x[2] for x in t12) / n12 if n12 else 0,
                     "bgn": n12, "hon": P[k]["aw"], "quads": {q: Q[q][:2] for q in Q}})
    for c in ("impact", "win", "qval", "bgs", "hon"):
        f = _pct_fn([r[c] for r in rows])
        for r in rows:
            r[c + "_p"] = f(r[c])
    for r in rows:
        rel = min(1, r["bgn"] / 10)
        r["big"] = .6 * r["qval_p"] + .4 * (rel * r["bgs_p"] + (1 - rel) * .5)
    f = _pct_fn([r["big"] for r in rows])
    for r in rows:
        r["big_p"] = f(r["big"])
        r["score"] = 100 * (.35 * r["win_p"] + .30 * r["impact_p"] + .20 * r["hon_p"] + .15 * r["big_p"])
    rows.sort(key=lambda r: -r["score"])
    for r in rows:          # in: a resume at the cut or better; once in, always in
        if r["score"] >= RESUME_CUT:
            store["inducted"].setdefault(r["k"], {"since": datetime.now().strftime("%Y-%m-%d")})
    STORE.write_text(json.dumps(store, indent=1, sort_keys=True) + "\n")
    rows = [r for r in rows if r["k"] in store["inducted"]]
    keys = [r["k"] for r in rows]
    K = set(keys)

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

    # --- records (Record Book #1s, ties included) for the signature-game tags ---
    REC = defaultdict(list)

    def tops(lst):
        return [x for x in lst if lst and x[0] == lst[0][0]]
    if "records_state.js" in season_files:
        st = _obj(season_files["records_state.js"])["lists"]
        for per, lab in [("all", "State record")] + [(p, "State season high") for p in st if p != "all"]:
            for c, nm in REC_CATS.items():
                for x in tops(st.get(per, {}).get("ig_" + c, [])):
                    REC[(M(x[1]) + "|" + x[2], x[4])].append(f"{lab}: {x[0]} {nm}")
    for fn, js in season_files.items():
        if fn.startswith("records_") and fn != "records_state.js" and not fn.endswith("_cur.js") and fn.endswith(".js"):
            a = _obj(js)["lists"].get("all", {})
            for c, nm in REC_CATS.items():
                for x in tops(a.get("ig_" + c, [])):
                    REC[(M(x[1]) + "|" + x[2], x[4])].append(f"School record: {x[0]} {nm}")

    # --- per inductee: Hall of Fame badge lines, honors by season, signature games, career averages ---
    STAT = ["gp", "ppg", "rpg", "apg", "spg", "bpg", "tpm", "tpa", "tpp", "twom", "twoa", "twop", "ftm", "fta", "ftp", "bpm",
            "obpm", "dbpm", "ws", "usage_pct", "shot_pct", "stl_pct", "blk_pct", "ast_rate", "oreb_pct", "dreb_pct"]
    hof, hon, games, career, car = [], {}, {}, {}, {}
    for k in keys:
        name, school = k.split("|")
        v = P[k]
        car[k] = {"as1": v["as1"], "poy": v["poy"]}
        hon[k] = []
        for s in sorted(v["seasons"]):
            p = v["seasons"][s]
            for b in p.get("bdg") or []:
                if b[1] == 4:
                    hof.append(dict({f: p.get(f) for f in STAT}, season=s, code=b[0], name=name, school=school))
            bd = [list(b) for b in p.get("bdg") or []]
            if (s, k) in FOY:
                bd.insert(0, ["cfoy", 3, 0, FOY[(s, k)]])
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
            if g["bpm"] is not None and (g["min"] or 0) > 0:
                c["bm"] += g["bpm"] * g["min"]
                c["m"] += g["min"]
        if c["gp"]:
            career[k] = {"gp": c["gp"], "ppg": round(c["pts"] / c["gp"], 1), "rpg": round(c["reb"] / c["gp"], 1),
                         "apg": round(c["ast"] / c["gp"], 1), "bpm": round(c["bm"] / c["m"], 1) if c["m"] else None}
    res = {r["k"]: {"score": round(r["score"], 1), "win": round(100 * r["win_p"]), "impact": round(100 * r["impact_p"]),
                    "hon": round(100 * r["hon_p"]), "big": round(100 * r["big_p"]), "quads": r["quads"]} for r in rows}
    return {"order": keys, "hof": hof, "car": car, "hon": hon, "games": games, "career": career, "res": res,
            "mvp": MVP, "players": len(all_names)}


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
