#!/usr/bin/env python3
"""Moorpark lineup analytics from the Synergy 5-man lineup export.

Source: internal_data/moorpark_lineups_2025_26.csv (per 5-man lineup: points for/
against, +/-, minutes, possessions-implied via PPP, four factors, shooting splits,
and event data). Any N-man combination's on-court totals = sum over all 5-man
lineups that contain those N players, so we derive 1/2/3/4/5-man combos.

Per combination we compute every metric the box-level lineup data supports:
ratings (ORtg/DRtg/Net/100, Net/40, +/-, PPP, pace), shooting (eFG/TS/FG/2P/3P/FT%,
3PAr, FTr), ball/possession (TOV%, AST/40, A:TO), rebounding (OREB%/DREB%,
back-solved from the per-lineup rates), and defensive events (STL/BLK/DEFL/CHG/40).

NOTE: ratings are RAW (not opponent-adjusted). True opponent adjustment needs
GAME-LEVEL lineup data (which lineup faced which opponent); this season-totals
export can't attribute schedule strength per lineup. The 1-man table also carries
a ridge-regularized one-team adjusted plus-minus (RAPM-lite).

Moorpark-only. build_moorpark_lineups() returns the embed dict, or None.
"""
import csv
import json
import re
from itertools import combinations
from pathlib import Path

import numpy as np

_CSV = Path("internal_data/moorpark_lineups_2025_26.csv")
_SCHED = Path("2025-26 Teams Schedules/WSC North/Moorpark")

# Fixed column indices (header row repeats labels, so address by position).
C = {"efg_ff": 2, "tov_ff": 3, "oreb_pct": 4, "dreb_pct": 5, "ftf": 6,
     "fgm": 9, "fga": 10, "t2m": 14, "t2a": 15, "t3m": 18, "t3a": 19,
     "ftm": 22, "fta": 23, "pf": 26, "pa": 27, "ppp": 28, "pm": 30, "mins": 31,
     "pot": 34, "scp": 35, "pip": 36, "oreb": 38, "dreb": 40, "ast": 44, "to": 45,
     "defl": 56, "stl": 57, "blk": 58, "foul": 59, "chg": 60}

# Raw fields summed when aggregating a combination across its lineups.
_SUM = ["mins", "pf", "pa", "pm", "off_poss", "fgm", "fga", "t2m", "t2a",
        "t3m", "t3a", "ftm", "fta", "oreb", "dreb", "opp_oreb", "opp_dreb",
        "ast", "to", "defl", "stl", "blk", "foul", "chg", "pip", "scp", "pot"]


def _ft_poss(fta):
    """Free-throw contribution to the possession estimate: KenPom 0.475*FTA.
    We deliberately do NOT try to count exact FT trips, because one trip can be
    1 FTA (one-and-one front-end miss), 2 (shooting foul / double bonus), or 3
    (fouled on a 3-pt attempt) — so no divisor/coefficient on *aggregated* FTA is
    correct for every case. 0.475 is the calibrated population average: wrong on
    any single row, right across many."""
    return 0.475 * fta


# Minimum minutes-together to include a combination, per size (full season).
_MIN_MINS = {2: 60, 3: 40, 4: 25, 5: 12}
# When a split covers fewer games, the floor scales down proportionally
# (base * games/full_games) but never below these absolute minutes, so small
# splits surface more lineups without dropping to pure noise.
_FLOOR_MIN = {1: 10, 2: 12, 3: 8, 4: 5, 5: 3}
_CAP = 90  # max combos kept per size (sorted by minutes)


def _num(s):
    # NB: the Hudl +/- column is formatted "- 4.0" / "+ 5.0" (sign, SPACE, number),
    # so strip internal spaces too or float() throws and negatives become 0.
    s = str(s).replace("%", "").replace("+", "").replace(",", "").replace(" ", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _is_num(s):
    """Strict numeric check — used to reject garbage rows from the sheet's other
    tables (which carry the same lineup label but values like '#N/A', 'DREB%')."""
    return bool(re.match(r"^\d+(\.\d+)?$", str(s).strip()))


def _load_official_minutes(jmap):
    """{jersey -> official CCCAA total minutes} from Moorpark player_stats. Hudl
    over-counts minutes vs the official box score (confirmed in 2023-24); we
    reconcile lineup minutes to these so Net/40 and pace are accurate."""
    import json as _json
    path = Path("2025-26 Team Statistics/WSC North/Moorpark/player_stats.json")
    if not path.exists():
        return {}
    name_to_jersey = {v: k for k, v in jmap.items()}
    out = {}
    try:
        for p in _json.load(open(path)).get("players", []):
            j = name_to_jersey.get(p.get("name", "").strip())
            if j:
                out[j] = float(p.get("totals", {}).get("MIN", 0) or 0)
    except Exception:
        pass
    return out


def _jersey_map():
    out = {}
    if not _SCHED.exists():
        return out
    for game in _SCHED.iterdir():
        if not game.is_dir():
            continue
        for f in game.glob("*.json"):
            try:
                box = json.load(open(f))
            except Exception:
                continue
            for tn, rows in (box.get("teams") or {}).items():
                if "moorpark" not in tn.lower():
                    continue
                for r in rows:
                    m = re.match(r"#(\d+)\s+(.+)", r.get("name", ""))
                    if m:
                        out.setdefault(m.group(1), m.group(2).strip())
    return out


GUARDS = {"PG", "s-PG", "CG", "WG"}
FORWARDS = {"WF", "S-PF", "PF/C", "C"}


def _load_positions(jmap):
    """{jersey -> pos_class} for Moorpark from the precomputed positions CSV
    (8-archetype scheme: PG/s-PG/CG/WG/WF/S-PF/PF-C/C)."""
    path = Path("internal_data/player_positions_2025_26.csv")
    if not path.exists():
        return {}
    def _norm(j):  # strip zero-padding so '01' and '1' match the lineup CSV
        try:
            return str(int(j))
        except (ValueError, TypeError):
            return j
    name_to_jersey = {v.strip(): _norm(k) for k, v in jmap.items()}
    out = {}
    try:
        for row in csv.DictReader(open(path, encoding="utf-8-sig")):
            if row.get("team") != "Moorpark":
                continue
            j = name_to_jersey.get((row.get("name") or "").strip())
            if j:
                out[j] = (row.get("pos_class") or "").strip()
    except Exception:
        pass
    return out


def _r(v, d=1):
    return round(v, d) if isinstance(v, (int, float)) and not (v != v) else 0.0


def _metrics(s):
    """Full metric dict from a dict of summed raw fields."""
    poss = s["off_poss"] or 1.0
    mins = s["mins"] or 1.0
    fga = s["fga"] or 1.0
    out = {
        "min": round(s["mins"]),
        "poss": round(s["off_poss"]),
        "pm": round(s["pm"]),
        "net100": _r((s["pf"] - s["pa"]) / poss * 100),
        "net40": _r(s["pm"] / mins * 40),
        "ortg": _r(s["pf"] / poss * 100),
        "drtg": _r(s["pa"] / poss * 100),
        "ppp": _r(s["pf"] / poss, 2),
        "pace": _r(poss / mins * 40),
        "efg": _r((s["fgm"] + 0.5 * s["t3m"]) / fga * 100),
        "ts": _r(s["pf"] / (2 * (s["fga"] + 0.44 * s["fta"])) * 100) if s["fga"] + s["fta"] else 0.0,
        "fgp": _r(s["fgm"] / fga * 100),
        "twop": _r(s["t2m"] / s["t2a"] * 100) if s["t2a"] else 0.0,
        "tpp": _r(s["t3m"] / s["t3a"] * 100) if s["t3a"] else 0.0,
        "ftp": _r(s["ftm"] / s["fta"] * 100) if s["fta"] else 0.0,
        "tpar": _r(s["t3a"] / fga * 100),
        "ftr": _r(s["fta"] / fga * 100),
        "tov": _r(s["to"] / (s["fga"] + 0.44 * s["fta"] + s["to"]) * 100) if (s["fga"] + s["to"]) else 0.0,
        "oreb_pct": _r(s["oreb"] / (s["oreb"] + s["opp_dreb"]) * 100) if (s["oreb"] + s["opp_dreb"]) else 0.0,
        "dreb_pct": _r(s["dreb"] / (s["dreb"] + s["opp_oreb"]) * 100) if (s["dreb"] + s["opp_oreb"]) else 0.0,
        "ast40": _r(s["ast"] / mins * 40),
        "ast_pct": _r(s["ast"] / s["fgm"] * 100) if s["fgm"] else 0.0,
        "atov": _r(s["ast"] / s["to"], 2) if s["to"] else 0.0,
        "stl40": _r(s["stl"] / mins * 40),
        "blk40": _r(s["blk"] / mins * 40),
        "defl40": _r(s["defl"] / mins * 40),
        "chg40": _r(s["chg"] / mins * 40, 2),
        "pip40": _r(s["pip"] / mins * 40),
        "scp40": _r(s["scp"] / mins * 40),
        # ── per-40 volume (offense) ──
        "pts40": _r(s["pf"] / mins * 40),
        "fgm40": _r(s["fgm"] / mins * 40),
        "fga40": _r(s["fga"] / mins * 40),
        "tpm40": _r(s["t3m"] / mins * 40),
        "tpa40": _r(s["t3a"] / mins * 40),
        "ftm40": _r(s["ftm"] / mins * 40),
        "fta40": _r(s["fta"] / mins * 40),
        "to40": _r(s["to"] / mins * 40),
        "pot40": _r(s["pot"] / mins * 40),
        "foul40": _r(s["foul"] / mins * 40),
        # ── per-40 rebounding ──
        "oreb40": _r(s["oreb"] / mins * 40),
        "dreb40": _r(s["dreb"] / mins * 40),
        "reb40": _r((s["oreb"] + s["dreb"]) / mins * 40),
        # ── per-40 defense allowed ──
        "pa40": _r(s["pa"] / mins * 40),
        "opp_oreb40": _r(s["opp_oreb"] / mins * 40),
        # ── margins (team − opponent, per 40) ──
        "reb_margin40": _r(((s["oreb"] + s["dreb"]) - (s["opp_oreb"] + s["opp_dreb"])) / mins * 40),
    }
    return out


_PG_DIR = Path("internal_data/per_game_lineups")


def _opp_adjustment(opp_ratings, allowed_files=None):
    """Per-game opponent adjustment maps from the per-game lineup CSVs.

    For each jersey-combo (k=1..5) returns possession-weighted average opponent
    ORtg/DRtg across the stints it played, so callers can compute KenPom-style
    additive adjustments: adj_ortg = ortg + (lg_avg - wOppDRtg),
    adj_drtg = drtg + (lg_avg - wOppORtg), adj_net = net + (wOppORtg - wOppDRtg).
    Pass `allowed_files` (a set of manifest filenames) to restrict the adjustment
    to a game subset; None = all games.

    Returns (maps, lg_avg) where maps[k][combo_tuple] = {poss, oO, oD} (oO/oD are
    possession-weighted sums; divide by poss for the average)."""
    manifest_path = _PG_DIR / "manifest.json"
    if not opp_ratings or not manifest_path.exists():
        return None, 0.0
    lg_avg = (sum(r.get("ortg", 0) for r in opp_ratings.values())
              / max(len(opp_ratings), 1))
    maps = {k: {} for k in (0, 1, 2, 3, 4, 5)}
    for e in json.load(open(manifest_path)):
        if allowed_files is not None and e["file"] not in allowed_files:
            continue
        opp = opp_ratings.get(e["opponent"])
        if not opp:
            continue
        oO, oD = opp.get("ortg", 0), opp.get("drtg", 0)
        try:
            rows = list(csv.reader(open(_PG_DIR / e["file"], encoding="utf-8-sig")))
        except Exception:
            continue
        seen = set()
        for row in rows[2:]:
            if not row or not row[0].startswith("#"):
                continue
            if not (_is_num(row[C["mins"]]) and _is_num(row[C["pf"]]) and _is_num(row[C["ppp"]])):
                continue
            jerseys = re.findall(r"#(\d+)", row[0])
            if len(jerseys) != 5:
                continue
            jkey = tuple(sorted(jerseys, key=int))
            if (e["file"], jkey) in seen:
                continue
            seen.add((e["file"], jkey))
            ppp = _num(row[C["ppp"]])
            poss = (_num(row[C["pf"]]) / ppp if ppp > 0
                    else _num(row[C["fga"]]) - _num(row[C["oreb"]])
                         + _num(row[C["to"]]) + _ft_poss(_num(row[C["fta"]])))   # scoreless: whole FT trips
            if poss <= 0:
                continue
            t = maps[0].setdefault((), {"poss": 0.0, "oO": 0.0, "oD": 0.0})
            t["poss"] += poss
            t["oO"] += poss * oO
            t["oD"] += poss * oD
            js = sorted(set(jerseys))
            for k in (1, 2, 3, 4, 5):
                if len(js) < k:
                    continue
                for combo in combinations(js, k):
                    a = maps[k].setdefault(combo, {"poss": 0.0, "oO": 0.0, "oD": 0.0})
                    a["poss"] += poss
                    a["oO"] += poss * oO
                    a["oD"] += poss * oD
    return maps, lg_avg


def _apply_adj(row, combo, k, adj_maps, lg_avg):
    """Attach adj_ortg/adj_drtg/adj_net100/opp_net to a metrics row in place."""
    if not adj_maps:
        return
    a = adj_maps.get(k, {}).get(tuple(combo))
    if not a or a["poss"] <= 0:
        return
    wO, wD = a["oO"] / a["poss"], a["oD"] / a["poss"]
    row["adj_ortg"] = _r(row["ortg"] + (lg_avg - wD))
    row["adj_drtg"] = _r(row["drtg"] + (lg_avg - wO))
    row["adj_net100"] = _r(row["net100"] + (wO - wD))
    row["opp_net"] = _r(wO - wD)


# ── Garbage-time removal ─────────────────────────────────────────────────────
# Garbage possessions are flagged per-possession in the off_/def_ logs. We
# aggregate them PER (game date, 5-man lineup) and subtract from that lineup's
# Hudl row to produce a competitive-only ("garbage removed") version. Logs are
# read BY HEADER NAME (column order varies between off and def files).
_GARB_FIELDS = ["pf", "pa", "fgm", "fga", "t2m", "t2a", "t3m", "t3a", "ftm",
                "fta", "oreb", "dreb", "to", "opp_oreb", "opp_dreb",
                "pip", "scp", "pot", "ast"]


def _read_log(path):
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    if not rows:
        return [], {}
    idx = {h.strip().lower(): i for i, h in enumerate(rows[0])}
    return rows[1:], idx


def _gjk(lineup_str):
    return tuple(sorted(re.findall(r"#(\d+)", lineup_str or ""), key=int))


def _load_garbage():
    """{date: {jersey_tuple: garbage stat dict}} from the logs' garbage rows."""
    garb = {}

    def cell(r, idx, name):
        i = idx.get(name)
        return r[i] if (i is not None and i < len(r)) else ""

    def acc(date, jkey):
        g = garb.setdefault(date, {})
        a = g.get(jkey)
        if a is None:
            a = {k: 0.0 for k in _GARB_FIELDS}
            a["_off"], a["_def"] = set(), set()
            g[jkey] = a
        return a

    # OFFENSE garbage (Moorpark on offense)
    for path in sorted(_DEFLOG_DIR.glob("off_*.csv")):
        rows, idx = _read_log(path)
        if "garbage" not in idx:
            continue
        for r in rows:
            if str(cell(r, idx, "garbage")).strip().lower() not in ("1", "1.0", "true", "yes"):
                continue
            jkey = _gjk(cell(r, idx, "lineup"))
            if len(jkey) != 5:
                continue
            a = acc(cell(r, idx, "date"), jkey)
            ev = cell(r, idx, "event").strip().lower()
            a["pf"] += _num(cell(r, idx, "pts"))
            a["ftm"] += _num(cell(r, idx, "ftm")); a["fta"] += _num(cell(r, idx, "fta"))
            a["pip"] += _num(cell(r, idx, "pip")); a["scp"] += _num(cell(r, idx, "scp"))
            a["pot"] += _num(cell(r, idx, "pot"))
            if cell(r, idx, "assisted").strip():
                a["ast"] += 1
            a["_off"].add(cell(r, idx, "poss"))
            if ev == "shot":
                made = cell(r, idx, "result").strip().lower() == "made"
                a["fga"] += 1; a["fgm"] += 1 if made else 0
                if cell(r, idx, "shot_type").strip().lower().startswith("3"):
                    a["t3a"] += 1; a["t3m"] += 1 if made else 0
                else:
                    a["t2a"] += 1; a["t2m"] += 1 if made else 0
            elif ev == "oreb":
                a["oreb"] += 1
            elif ev == "dreb":
                a["opp_dreb"] += 1          # opponent grabbed the defensive board
            elif ev == "turnover":
                a["to"] += 1

    # DEFENSE garbage (Moorpark on defense — finishing 5-man lineup)
    for path in sorted(_DEFLOG_DIR.glob("def_*.csv")):
        rows, idx = _read_log(path)
        if "garbage" not in idx:
            continue
        for r in rows:
            if str(cell(r, idx, "garbage")).strip().lower() not in ("1", "1.0", "true", "yes"):
                continue
            ev = cell(r, idx, "event").strip().lower()
            if ev == "ghost_sub":
                continue
            jkey = _gjk(cell(r, idx, "lineup"))
            if len(jkey) != 5:
                continue
            a = acc(cell(r, idx, "date"), jkey)
            a["pa"] += _num(cell(r, idx, "pts"))
            a["_def"].add(cell(r, idx, "poss"))
            if ev == "dreb":
                a["dreb"] += 1              # Moorpark defensive rebound
            elif ev == "oreb":
                a["opp_oreb"] += 1          # opponent offensive rebound

    for game in garb.values():
        for a in game.values():
            a["off_poss"] = float(len(a.pop("_off")))
            a["def_poss"] = float(len(a.pop("_def")))
    return garb


def _strip_garbage(lineup, g):
    """Return a copy of a Hudl lineup row with its garbage stats removed, or None
    if the lineup was entirely garbage (no competitive minutes/possessions left)."""
    ng = dict(lineup)
    for f in _GARB_FIELDS:
        ng[f] = max(ng.get(f, 0.0) - g.get(f, 0.0), 0.0)
    g_off = g.get("off_poss", 0.0)
    op0 = lineup.get("off_poss", 0.0)
    ng["off_poss"] = max(op0 - g_off, 0.0)
    # garbage minutes ~ proportional to garbage offensive possessions
    if op0 > 0 and g_off > 0:
        ng["mins"] = max(lineup.get("mins", 0.0) * (1 - g_off / op0), 0.0)
    if ng["mins"] <= 0 or ng["off_poss"] <= 0:
        return None
    ng["pm"] = ng["pf"] - ng["pa"]          # competitive points margin
    return ng


# ── Measured defense from defensive_logger.html CSV exports ──────────────────
_DEFLOG_DIR = Path("internal_data/def_logs")
_MD_FIELDS = ["def_poss", "opp_pts", "o2a", "o2m", "o3a", "o3m", "ofta", "oftm",
              "oto", "ooreb", "odreb", "pip", "scp", "pot"]


def _truthy(v):
    return str(v).strip().lower() in ("1", "1.0", "true", "yes")


def _load_logged_defense():
    """Aggregate COUNTED defensive data from the standalone logger's CSV exports
    (internal_data/def_logs/*.csv). Unlike the Hudl season CSV — where DRtg reuses
    the OFFENSIVE possession estimate (pf/ppp) as its denominator — this counts the
    actual opponent possessions each lineup faced, plus the opp shooting/TO/reb
    splits Hudl never breaks out per lineup. COMPETITIVE (non-garbage) possessions
    only. Possession-grain: each possession (def_poss + its opp points + event
    detail) is attributed to its FINISHING 5-man lineup, keeping the DRtg
    numerator and denominator at the same scope. Returns mdef[k][combo] for
    k=0..5 (0 = team), or {} when no logs exist (pipeline unchanged until then)."""
    if not _DEFLOG_DIR.exists():
        return {}
    base, games = {}, {}   # base[combo5] = sums; games[combo5] = {(date,opp,venue)}
    for f in sorted(_DEFLOG_DIR.glob("*.csv")):
        try:
            rows = list(csv.DictReader(open(f, encoding="utf-8-sig")))
        except Exception:
            continue
        poss = {}   # (date,opp,venue,poss) -> [event rows], insertion-ordered
        for r in rows:
            if (r.get("side") or "def") == "off" or r.get("event") == "ghost_sub":
                continue   # offense = separate stream; ghost_sub = a Hudl-missed-sub marker, not a possession
            poss.setdefault((r.get("date", ""), r.get("opponent", ""),
                             r.get("venue", ""), r.get("poss", "")), []).append(r)
        for key, evs in poss.items():
            if not evs or _truthy(evs[-1].get("garbage", "")):
                continue   # competitive only
            combo = tuple(sorted(set(re.findall(r"#(\d+)", evs[-1].get("lineup", "")))))
            if len(combo) != 5:
                continue
            b = base.setdefault(combo, {x: 0.0 for x in _MD_FIELDS})
            games.setdefault(combo, set()).add(key[:3])
            b["def_poss"] += 1
            for r in evs:
                b["opp_pts"] += _num(r.get("pts", "0"))
                ev = (r.get("event") or "").strip()
                if ev == "shot":
                    three = (r.get("shot_type") or "").strip() == "3pa"
                    made = (r.get("result") or "").strip() == "made"
                    b["o3a" if three else "o2a"] += 1
                    if made:
                        b["o3m" if three else "o2m"] += 1
                        pv = 3 if three else 2
                        for fl in ("pip", "scp", "pot"):
                            if _truthy(r.get(fl, "")):
                                b[fl] += pv
                elif ev == "foul":
                    b["ofta"] += _num(r.get("fta", "0"))
                    b["oftm"] += _num(r.get("ftm", "0"))
                elif ev == "turnover":
                    b["oto"] += 1
                elif ev == "oreb":
                    b["ooreb"] += 1
                elif ev == "dreb":
                    b["odreb"] += 1
    if not base:
        return {}
    # Roll the per-5-man sums up to every k-subset (and k=0 team total).
    mdef = {k: {} for k in range(6)}
    for combo5, b in base.items():
        gs = games.get(combo5, set())
        for k in range(6):
            for sub in (combinations(combo5, k) if k else [()]):
                a = mdef[k].get(sub)
                if a is None:
                    a = {x: 0.0 for x in _MD_FIELDS}
                    a["games"] = set()
                    mdef[k][sub] = a
                for x in _MD_FIELDS:
                    a[x] += b[x]
                a["games"] |= gs
    return mdef


def _measured_def_block(a):
    """Counted-possession defensive metrics for one combo's logged sums."""
    dp = a["def_poss"]
    if dp <= 0:
        return None
    ofga = a["o2a"] + a["o3a"]
    ofgm = a["o2m"] + a["o3m"]
    return {
        "def_poss": round(dp),
        "games": len(a.get("games", ())),
        "opp_pts": round(a["opp_pts"]),
        "drtg": _r(a["opp_pts"] / dp * 100),          # counted denominator
        "opp_efg": _r((ofgm + 0.5 * a["o3m"]) / ofga * 100) if ofga else 0.0,
        "opp_tov": _r(a["oto"] / (ofga + 0.44 * a["ofta"] + a["oto"]) * 100) if (ofga + a["oto"]) else 0.0,
        "opp_ftr": _r(a["ofta"] / ofga * 100) if ofga else 0.0,
        "opp_3par": _r(a["o3a"] / ofga * 100) if ofga else 0.0,
        "opp_2pp": _r(a["o2m"] / a["o2a"] * 100) if a["o2a"] else 0.0,
        "opp_3pp": _r(a["o3m"] / a["o3a"] * 100) if a["o3a"] else 0.0,
        "dreb_pct": _r(a["odreb"] / (a["odreb"] + a["ooreb"]) * 100) if (a["odreb"] + a["ooreb"]) else 0.0,
        "pip100": _r(a["pip"] / dp * 100),
        "scp100": _r(a["scp"] / dp * 100),
        "pot100": _r(a["pot"] / dp * 100),
    }


def _apply_measured_def(row, combo, k, mdef_maps):
    """Attach a `measured_def` block (counted def possessions as the DRtg
    denominator) wherever the logger covers this combo, and — for the lineups
    section — blend the possession COUNT as KenPom does: (offensive estimate from
    the Hudl CSV + counted defensive possessions) / 2. The two counts are kept
    independent (ORtg still divides by offensive possessions, measured DRtg by
    counted defensive); only the headline `poss`/`pace` use the average. NOTE:
    Hudl off_poss is a season total while def_poss covers only logged games, so
    the average is meaningful once a lineup's games are (mostly) all logged."""
    if not mdef_maps:
        return
    a = mdef_maps.get(k, {}).get(tuple(combo))
    if not a:
        return
    blk = _measured_def_block(a)
    if not blk:
        return
    row["measured_def"] = blk
    if "poss" in row and blk["def_poss"] > 0:
        off = row["poss"]                       # offensive possessions (Hudl est.)
        avg = (off + blk["def_poss"]) / 2
        row["poss_off"] = off                   # keep the offense-only count
        row["poss"] = round(avg)                # averaged count for the section
        if off > 0 and row.get("pace"):
            row["pace"] = _r(row["pace"] * avg / off)


# Hudl per-game column map (made-attempt fields already split into M/A columns).
_PG_COL = {"oreb_pct": 4, "fgm": 9, "fga": 10, "t3m": 18, "t3a": 19, "ftm": 22,
           "fta": 23, "pf": 26, "ppp": 28, "oreb": 38, "to": 45, "mins": 31}


def _ff_block(a, dreb_key):
    """Four factors (eFG, TOV%, OREB%, FTr) from raw box components."""
    fga = a["fga"]
    odr = a.get(dreb_key, 0)
    return {
        "efg": _r((a["fgm"] + 0.5 * a["t3m"]) / fga * 100) if fga else 0.0,
        "tov": _r(a["to"] / (fga + 0.44 * a["fta"] + a["to"]) * 100) if (fga + a["to"]) else 0.0,
        "oreb": _r(a["oreb"] / (a["oreb"] + odr) * 100) if (a["oreb"] + odr) else 0.0,
        "ftr": _r(a["fta"] / fga * 100) if fga else 0.0,
    }


def _load_oncourt_ff():
    """Per-PLAYER on-court four factors over LOGGED games (GARBAGE INCLUDED):
    DEFENSE (opponent four factors allowed) from the defensive logger, OFFENSE
    (Moorpark four factors) from the Hudl per-game lineup CSVs for those SAME games.
    Internal quantification that grows as games are logged — not surfaced in the UI.
    Returns {jersey: {games, def_poss, off_min, off:{...}, def:{...}}}."""
    deflog = sorted(p for p in _DEFLOG_DIR.glob("def_*.csv")) if _DEFLOG_DIR.exists() else []
    if not deflog:
        return {}
    F = ["fga", "fgm", "t3a", "t3m", "fta", "ftm", "to", "oreb", "dreb"]
    D, Dposs, games = {}, {}, set()
    for f in deflog:
        try:
            rows = list(csv.DictReader(open(f, encoding="utf-8-sig")))
        except Exception:
            continue
        for r in rows:
            if (r.get("side") or "def") != "def" or r.get("event") == "ghost_sub":
                continue
            games.add((r.get("date", ""), r.get("opponent", ""), r.get("venue", "")))
            ev = r.get("event")
            for j in re.findall(r"#(\d+)", r.get("lineup", "")):
                Dposs.setdefault(j, set()).add((str(f), r.get("poss")))
                a = D.setdefault(j, {k: 0.0 for k in F})
                if ev == "shot":
                    three = r.get("shot_type") == "3pa"
                    a["fga"] += 1
                    a["t3a"] += 1 if three else 0
                    if r.get("result") == "made":
                        a["fgm"] += 1
                        a["t3m"] += 1 if three else 0
                elif ev == "foul":
                    a["fta"] += _num(r.get("fta", "0")); a["ftm"] += _num(r.get("ftm", "0"))
                elif ev == "turnover":
                    a["to"] += 1
                elif ev == "oreb":
                    a["oreb"] += 1   # opponent offensive rebound
                elif ev == "dreb":
                    a["dreb"] += 1   # Moorpark defensive rebound
    if not games:
        return {}
    # Offense: Hudl per-game files for the same logged games (matched via manifest).
    file_by_game = {}
    mani = _PG_DIR / "manifest.json"
    if mani.exists():
        for e in json.load(open(mani)):
            file_by_game[(e.get("date", ""), e.get("opponent", ""), e.get("venue", ""))] = e.get("file")
    OF = ["fga", "fgm", "t3a", "t3m", "fta", "ftm", "to", "oreb", "opp_dreb", "off_poss"]
    O = {}
    for g in games:
        fn = file_by_game.get(g)
        path = (_PG_DIR / fn) if fn else None
        if not path or not path.exists():
            continue
        for row in list(csv.reader(open(path, encoding="utf-8-sig")))[2:]:
            if not row or not row[0].startswith("#"):
                continue
            if not (_is_num(row[_PG_COL["mins"]]) and _is_num(row[_PG_COL["pf"]]) and _is_num(row[_PG_COL["ppp"]])):
                continue
            js = re.findall(r"#(\d+)", row[0])
            if len(js) != 5:
                continue
            v = {k: _num(row[i]) for k, i in _PG_COL.items()}
            opp_dreb = v["oreb"] * (100 / v["oreb_pct"] - 1) if v["oreb_pct"] > 0 else 0.0
            off_poss = (v["pf"] / v["ppp"] if v["ppp"] > 0
                        else v["fga"] - v["oreb"] + v["to"] + _ft_poss(v["fta"]))   # scoreless: whole FT trips
            for j in js:
                a = O.setdefault(j, {k: 0.0 for k in OF})
                for k in ("fgm", "fga", "t3m", "t3a", "ftm", "fta", "oreb", "to"):
                    a[k] += v[k]
                a["opp_dreb"] += opp_dreb
                a["off_poss"] += off_poss
    out = {}
    for j in set(D) | set(O):
        op = O.get(j, {}).get("off_poss", 0.0)
        dp = len(Dposs.get(j, set()))
        out[j] = {
            "games": len(games),
            "poss": round((op + dp) / 2),   # single count = average of offensive & defensive possessions
            "off": _ff_block(O[j], "opp_dreb") if j in O else None,
            "def": _ff_block(D[j], "dreb") if j in D else None,
        }
    return out


_TEAMSTATS_DIR = Path("2025-26 Team Statistics")
_ONOFF_OUT = Path("internal_data/moorpark_onoff_adj.json")


def _opp_ff_ratings():
    """League averages + per-team season ratings/four-factors from the 2025-26
    advanced_analytics files, used to opponent-adjust the on/off table."""
    keys = ["ortg", "drtg", "efg_pct", "tov_pct", "oreb_pct", "dreb_pct",
            "ft_rate", "opp_efg_pct", "opp_tov_pct", "opp_ft_rate"]
    teams = {}
    for f in _TEAMSTATS_DIR.glob("*/*/advanced_analytics.json"):
        try:
            d = json.load(open(f, encoding="utf-8"))["team"]
        except Exception:
            continue
        teams[f.parent.name] = {k: d.get(k) for k in keys}
    lg = {}
    for m in ("ortg", "efg_pct", "tov_pct", "oreb_pct", "ft_rate"):
        vals = [v[m] for v in teams.values() if isinstance(v.get(m), (int, float))]
        lg[m] = round(sum(vals) / len(vals), 3) if vals else 0.0
    return lg, teams


def _load_oncourt_onoff(allowed_files=None, ratings=None, jmap=None):
    """Opponent-ADJUSTED ON/OFF. OFFENSE from the Hudl per-game lineups (all 29
    games), DEFENSE from the logger (per possession). ORtg/DRtg/Net + four factors
    are opponent-adjusted (each game's possessions shifted by league_avg − opponent
    strength, possession-weighted into ON/OFF). `allowed_files` (set of per-game
    lineup filenames) restricts to a split's games — None = full season. `ratings`
    (lg,AT) and `jmap` can be passed to avoid recomputing them per split. Only the
    full call (allowed_files None) writes internal_data/moorpark_onoff_adj.json.
    Returns {"players": {jersey: {...}}, "meta": {...}}."""
    deflog = sorted(p for p in _DEFLOG_DIR.glob("def_*.csv")) if _DEFLOG_DIR.exists() else []
    lg, AT = ratings if ratings is not None else _opp_ff_ratings()
    jmap = jmap if jmap is not None else _jersey_map()

    def adj_deltas(opp):
        """Per-metric additive adjustment for an opponent (league - their strength)."""
        v = AT.get(opp)
        if not v or any(v.get(k) is None for k in
                        ("drtg", "ortg", "efg_pct", "tov_pct", "oreb_pct", "dreb_pct",
                         "ft_rate", "opp_efg_pct", "opp_tov_pct", "opp_ft_rate")):
            return {k: 0.0 for k in ("ort", "drt", "oefg", "otov", "ooreb", "oftr",
                                     "defg", "dtov", "doreb", "dftr")}, False
        return dict(
            ort=lg["ortg"] - v["drtg"], drt=lg["ortg"] - v["ortg"],
            oefg=lg["efg_pct"] - v["opp_efg_pct"], otov=lg["tov_pct"] - v["opp_tov_pct"],
            ooreb=lg["oreb_pct"] - (100 - v["dreb_pct"]), oftr=lg["ft_rate"] - v["opp_ft_rate"],
            defg=lg["efg_pct"] - v["efg_pct"], dtov=lg["tov_pct"] - v["tov_pct"],
            doreb=lg["oreb_pct"] - v["oreb_pct"], dftr=lg["ft_rate"] - v["ft_rate"]), True

    man = {}
    mani = _PG_DIR / "manifest.json"
    if mani.exists():
        for e in json.load(open(mani)):
            man[(e.get("date", ""), e.get("opponent", ""), e.get("venue", ""))] = e.get("file")

    from collections import defaultdict
    OFFt = defaultdict(float); OFFon = defaultdict(lambda: defaultdict(float))
    DEFt = defaultdict(float); DEFon = defaultdict(lambda: defaultdict(float))
    num = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    den = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    # 'drt' (DRtg opp-adjustment) rides with OFFENSE now: DRtg comes from the Hudl
    # PA column over all 29 games, not the (partial) defensive logs.
    OFFMET = ["ort", "oefg", "otov", "ooreb", "oftr", "drt"]
    DEFMET = ["defg", "dtov", "doreb", "dftr"]
    allj, games, opps, unadj = set(), set(), set(), set()

    def acc_w(j_iter, won_map, team_w, mets, deltas):
        for j in set(j_iter) | allj:
            won = won_map.get(j, 0.0); woff = team_w - won
            for met in mets:
                num[j][met][0] += deltas[met] * won; den[j][met][0] += won
                num[j][met][1] += deltas[met] * woff; den[j][met][1] += woff

    # OFFENSE — over ALL Hudl per-game lineups (full season), independent of
    # whether a game's defensive possessions have been logged yet.
    off_games = set()
    for (d, o, v), fn in man.items():
        if not fn or not (_PG_DIR / fn).exists():
            continue
        if allowed_files is not None and fn not in allowed_files:
            continue
        off_games.add((d, o, v)); opps.add(o)
        deltas, ok = adj_deltas(o)
        if not ok:
            unadj.add(o)
        off_team = 0.0; off_on = defaultdict(float)
        for r in list(csv.reader(open(_PG_DIR / fn, encoding="utf-8-sig")))[2:]:
            if not r or not r[0].startswith("#"):
                continue
            if not (_is_num(r[C["mins"]]) and _is_num(r[C["pf"]]) and _is_num(r[C["pa"]])):
                continue
            jj = re.findall(r"#(\d+)", r[0])
            if len(jj) != 5:
                continue
            fga = _num(r[C["fga"]]); fgm = _num(r[C["fgm"]]); t3m = _num(r[C["t3m"]])
            fta = _num(r[C["fta"]]); to = _num(r[C["to"]]); oreb = _num(r[C["oreb"]])
            op = _num(r[C["oreb_pct"]]); odr = oreb * (100 / op - 1) if op > 0 else 0.0
            drv = _num(r[C["dreb"]]); dp = _num(r[C["dreb_pct"]])
            opp_oreb = drv * (100 / dp - 1) if dp > 0 else 0.0  # for Def Reb%
            comp = dict(pts=_num(r[C["pf"]]), pa=_num(r[C["pa"]]),
                        poss=fga - oreb + to + _ft_poss(fta),
                        fgm=fgm, fga=fga, t3m=t3m, t3a=_num(r[C["t3a"]]), fta=fta, to=to,
                        oreb=oreb, odr=odr, ast=_num(r[C["ast"]]), stl=_num(r[C["stl"]]),
                        blk=_num(r[C["blk"]]), foul=_num(r[C["foul"]]), dreb=drv,
                        defl=_num(r[C["defl"]]),
                        opp_oreb=opp_oreb, mins=_num(r[C["mins"]]))
            for k, val in comp.items():
                OFFt[k] += val
            off_team += comp["poss"]
            for j in jj:
                allj.add(j)
                for k, val in comp.items():
                    OFFon[j][k] += val
                off_on[j] += comp["poss"]
        acc_w(off_on.keys(), off_on, off_team, OFFMET, deltas)

    # DEFENSE — only games with logged defensive possessions (per-possession,
    # finishing lineup). Hidden in the UI ("--") until every offensive game's
    # defense is also logged.
    def_games = set()
    for f in deflog:
        rows = list(csv.DictReader(open(f, encoding="utf-8-sig")))
        if not rows:
            continue
        d, o, v = rows[0].get("date", ""), rows[0].get("opponent", ""), rows[0].get("venue", "")
        if allowed_files is not None and man.get((d, o, v)) not in allowed_files:
            continue
        def_games.add((d, o, v)); opps.add(o)
        deltas, ok = adj_deltas(o)
        byp = defaultdict(list)
        for r in rows:
            if (r.get("side") or "def") != "def" or r.get("event") in ("ghost_sub", "endgame"):
                continue
            byp[r.get("poss")].append(r)
        def_team = 0.0; def_on = defaultdict(float)
        for poss, evs in byp.items():
            five = re.findall(r"#(\d+)", evs[-1].get("lineup", ""))
            c = dict(pts=0.0, poss=1.0, fga=0.0, fgm=0.0, t3m=0.0, fta=0.0, to=0.0, oreb=0.0, dreb=0.0)
            for e in evs:
                ev = e.get("event"); c["pts"] += _num(e.get("pts", "0"))
                if ev == "shot":
                    three = e.get("shot_type") == "3pa"; c["fga"] += 1
                    if e.get("result") == "made":
                        c["fgm"] += 1; c["t3m"] += 1 if three else 0
                elif ev == "foul":
                    c["fta"] += _num(e.get("fta", "0"))
                elif ev == "turnover":
                    c["to"] += 1
                elif ev == "oreb":
                    c["oreb"] += 1
                elif ev == "dreb":
                    c["dreb"] += 1
            for k, val in c.items():
                DEFt[k] += val
            def_team += 1
            for j in five:
                allj.add(j)
                for k, val in c.items():
                    DEFon[j][k] += val
                def_on[j] += 1
        acc_w(def_on.keys(), def_on, def_team, DEFMET, deltas)

    # Defense is surfaced only once every offensive game also has its defense
    # logged; until then the def-derived metrics show "--". 'games' downstream
    # (the player "games" count) is the full Hudl offensive game set.
    def_complete = bool(off_games) and len(def_games) >= len(off_games)
    games = off_games

    def efg(a): return (a["fgm"] + 0.5 * a["t3m"]) / a["fga"] * 100 if a["fga"] else 0.0
    def tov(a): return a["to"] / (a["fga"] + 0.44 * a["fta"] + a["to"]) * 100 if (a["fga"] + a["to"]) else 0.0
    def orb(a): return a["oreb"] / (a["oreb"] + a["odr"]) * 100 if (a["oreb"] + a["odr"]) else 0.0
    def ftr(a): return a["fta"] / a["fga"] * 100 if a["fga"] else 0.0
    def dorb(a): return a["oreb"] / (a["oreb"] + a["dreb"]) * 100 if (a["oreb"] + a["dreb"]) else 0.0
    def rtg(p, n): return p / n * 100 if n else 0.0
    def wd(j, met, s):
        dd = den[j][met][s]; return num[j][met][s] / dd if dd else 0.0

    def split(raw_on, raw_off, j, met):
        on = _r(raw_on + wd(j, met, 0)); off = _r(raw_off + wd(j, met, 1))
        return {"on": on, "off": off, "diff": _r(on - off),
                "on_raw": _r(raw_on), "off_raw": _r(raw_off)}

    players = {}
    for j in allj:
        o_on = OFFon[j]; o_off = {k: OFFt[k] - OFFon[j][k] for k in OFFt}
        d_on = DEFon[j]; d_off = {k: DEFt[k] - DEFon[j][k] for k in DEFt}
        opn, opf = o_on.get("poss", 0.0), o_off.get("poss", 0.0)
        dpn, dpf = d_on.get("poss", 0.0), d_off.get("poss", 0.0)
        if opn < 1 and dpn < 1:
            continue
        eff = {
            "ortg": split(rtg(o_on["pts"], opn), rtg(o_off["pts"], opf), j, "ort"),
            "drtg": split(rtg(o_on["pa"], opn), rtg(o_off["pa"], opf), j, "drt"),  # Hudl PA / off-poss, 29 games
        }
        eff["net"] = {"on": _r(eff["ortg"]["on"] - eff["drtg"]["on"]),
                      "off": _r(eff["ortg"]["off"] - eff["drtg"]["off"]),
                      "diff": _r((eff["ortg"]["on"] - eff["drtg"]["on"])
                                 - (eff["ortg"]["off"] - eff["drtg"]["off"]))}
        def per40(stat):  # team box stat per 40 on-court min, on/off/diff (MINS sums ~40/game)
            on_ct = o_on.get(stat, 0.0); off_ct = o_off.get(stat, 0.0)
            on_m = o_on.get("mins", 0.0); off_m = o_off.get("mins", 0.0)
            on = on_ct / on_m * 40 if on_m else 0.0
            off = off_ct / off_m * 40 if off_m else 0.0
            return {"on": _r(on), "off": _r(off), "diff": _r(on - off)}
        box = {k: per40(k) for k in ("pts", "ast", "oreb", "dreb", "stl", "blk", "to", "foul")}
        defl40 = per40("defl")  # Deflections / 40 on-court min (Hudl, all games)

        def _rate(non, noff, don_, doff, sc):  # on/off ratio splits (Steal%, Assist%, …)
            on = non / don_ * sc if don_ else 0.0
            off = noff / doff * sc if doff else 0.0
            return {"on": _r(on), "off": _r(off), "diff": _r(on - off)}

        def _dreb_pct(a):
            den = a.get("dreb", 0.0) + a.get("oreb", 0.0)
            return a.get("dreb", 0.0) / den * 100 if den else 0.0
        # Offensive rates (always available from Hudl). DRtg/Net already use Hudl PA.
        rate = {
            "pace": _rate(o_on["poss"], o_off["poss"], o_on["mins"], o_off["mins"], 40),
            "tpar": _rate(o_on.get("t3a", 0.0), o_off.get("t3a", 0.0), o_on["fga"], o_off["fga"], 100),
            "asp": _rate(o_on["ast"], o_off["ast"], o_on["fgm"], o_off["fgm"], 100),
            "ato": _rate(o_on["ast"], o_off["ast"], o_on["to"], o_off["to"], 1),
            "stl": None, "blk": None, "dreb": None,
        }
        off_ff = {"efg": split(efg(o_on), efg(o_off), j, "oefg"),
                  "tov": split(tov(o_on), tov(o_off), j, "otov"),
                  "oreb": split(orb(o_on), orb(o_off), j, "ooreb"),
                  "ftr": split(ftr(o_on), ftr(o_off), j, "oftr")}
        # CBB-Analytics card metrics. From Hudl (all games): TS%, PPS, Def Reb%,
        # Steals/PF, Blocks/PF. Def-log-dependent ("--" until every game's defense
        # is logged): Steal%, Block%, Hakeem% (=Blk%+Stl%), PF Efficiency.
        def _ts(a):
            den = 2 * (a.get("fga", 0.0) + 0.44 * a.get("fta", 0.0))
            return a.get("pts", 0.0) / den * 100 if den else 0.0

        def _defreb(a):
            den = a.get("dreb", 0.0) + a.get("opp_oreb", 0.0)
            return a.get("dreb", 0.0) / den * 100 if den else 0.0
        ts = {"on": _r(_ts(o_on)), "off": _r(_ts(o_off)), "diff": _r(_ts(o_on) - _ts(o_off))}
        pps = _rate(o_on["pts"], o_off["pts"], o_on["fga"], o_off["fga"], 1)
        def_reb = {"on": _r(_defreb(o_on)), "off": _r(_defreb(o_off)),
                   "diff": _r(_defreb(o_on) - _defreb(o_off))}
        stl_pf = _rate(o_on["stl"], o_off["stl"], o_on["foul"], o_off["foul"], 1)
        blk_pf = _rate(o_on["blk"], o_off["blk"], o_on["foul"], o_off["foul"], 1)
        pf_eff = _rate(o_on["stl"] + o_on["blk"], o_off["stl"] + o_off["blk"],  # (STL+BLK)/PF, same as Adv. Defense
                       o_on["foul"], o_off["foul"], 1)
        hakeem = None
        def_ff = {k: None for k in ("efg", "tov", "oreb", "ftr")}
        if def_complete:
            rate["stl"] = _rate(o_on["stl"], o_off["stl"], d_on["poss"], d_off["poss"], 100)
            rate["blk"] = _rate(o_on["blk"], o_off["blk"], d_on["fga"], d_off["fga"], 100)
            rate["dreb"] = {"on": _r(_dreb_pct(d_on)), "off": _r(_dreb_pct(d_off)),
                            "diff": _r(_dreb_pct(d_on) - _dreb_pct(d_off))}
            hakeem = {s: _r((rate["stl"][s] or 0) + (rate["blk"][s] or 0))
                      for s in ("on", "off", "diff")}  # Hakeem% = Steal% + Block%
            def_ff = {"efg": split(efg(d_on), efg(d_off), j, "defg"),
                      "tov": split(tov(d_on), tov(d_off), j, "dtov"),
                      "oreb": split(dorb(d_on), dorb(d_off), j, "doreb"),
                      "ftr": split(ftr(d_on), ftr(d_off), j, "dftr")}
        players[j] = {
            "name": jmap.get(j, f"#{j}"), "jersey": j, "games": len(off_games),
            "off_poss_on": round(opn), "def_poss_on": round(dpn),
            "def_complete": def_complete,
            "eff": eff, "box": box, "rate": rate,
            "off_ff": off_ff, "def_ff": def_ff,
            "ts": ts, "pps": pps, "def_reb": def_reb, "defl40": defl40,
            "stl_pf": stl_pf, "blk_pf": blk_pf, "pf_eff": pf_eff, "hakeem": hakeem,
        }
    result = {
        "players": players,
        "meta": {
            "games": len(games), "opponents": sorted(opps),
            "league_avgs": lg, "garbage_included": True,
            "unadjusted_opponents": sorted(unadj),  # opponents missing season ratings
            "note": "Opponent-adjusted ON/OFF. Offense=Hudl per-game lineups, "
                    "defense=logger (per possession, finishing lineup). Recomputed "
                    "every build; grows as def_logs/ accumulates.",
        },
    }
    if allowed_files is None:  # only the full-season call persists the JSON
        try:
            _ONOFF_OUT.write_text(json.dumps(result, indent=1))
        except Exception:
            pass
    return result


# ── Game-subset support ──────────────────────────────────────────────────────
# Each file in per_game_lineups/ is a Hudl per-GAME export with the SAME column
# layout as the season CSV (PF, PA, FGM…), so we can rebuild the whole page from
# them and slice by Full Season / Conference / Last 5 / Last 10 / Home / Away /
# Neutral / Wins / Losses. (Offense-complete today; grows as more games log.)
_SUBSET_KEYS = ["full", "conf", "conf_wins", "conf_losses",
                "nonconf", "nonconf_wins", "nonconf_losses",
                "last5", "last10", "home", "away", "neutral", "away_neutral",
                "wins", "losses", "q1a", "q1", "q2", "q12", "q3", "q4"]


def _conf_teams():
    d = Path("2025-26 Team Statistics/WSC North")
    return {p.name for p in d.iterdir() if p.is_dir()} if d.exists() else set()


_MON = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"}


def _cccaa_venues():
    """{date_iso: 'Home'/'Away'/'Neutral'} from Moorpark's official CCCAA schedule —
    the authoritative home/away/neutral, used in preference to the Hudl filename."""
    try:
        sched = json.load(open(_SCHED / "schedule.json", encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for g in sched.get("games", []):
        ha = (g.get("home_away") or "").strip().lower()
        parts = (g.get("date") or "").split()
        if ha not in ("home", "away", "neutral") or len(parts) != 2:
            continue
        mon = _MON.get(parts[0][:3].lower())
        if not mon:
            continue
        year = "2025" if mon in ("09", "10", "11", "12") else "2026"
        out[f"{year}-{mon}-{parts[1].zfill(2)}"] = ha.capitalize()
    return out


def _get_quad(opp_rank, venue, n):
    """NCAA quadrant scaled to CCC, matching the leaderboard's quad table:
    cutoff = N * (NCAA cutoff) / 353, by venue. Returns '1A'/'1'/'2'/'3'/'4'."""
    if not opp_rank or not n:
        return None
    loc = venue if venue in ("Home", "Neutral", "Away") else "Neutral"
    tiers = (("1A", {"Home": n*15/353,  "Neutral": n*25/353,  "Away": n*40/353}),
             ("1",  {"Home": n*30/353,  "Neutral": n*50/353,  "Away": n*75/353}),
             ("2",  {"Home": n*75/353,  "Neutral": n*100/353, "Away": n*135/353}),
             ("3",  {"Home": n*160/353, "Neutral": n*200/353, "Away": n*240/353}))
    for q, mp in tiers:
        if opp_rank <= mp[loc]:
            return q
    return "4"


def _parse_pg_name(stem):
    """'2025-11-02_Los_Angeles_City_Home' -> (date, 'Los Angeles City', 'Home')."""
    parts = stem.split("_")
    return parts[0], " ".join(parts[1:-1]), parts[-1]


def _parse_lineup_row(row):
    """Parse one Hudl lineup row into the stat dict (or None to skip)."""
    if len(row) <= C["chg"] or not row[0].startswith("#"):
        return None
    # Reject garbage rows from the sheet's other tables (non-numeric stat cells).
    if not (_is_num(row[C["mins"]]) and _is_num(row[C["pf"]]) and _is_num(row[C["pa"]])):
        return None
    jerseys = re.findall(r"#(\d+)", row[0])
    if len(jerseys) != 5:
        return None
    g = {k: _num(row[i]) for k, i in C.items()}
    if g["mins"] <= 0:
        return None
    g["off_poss"] = (g["pf"] / g["ppp"] if g["ppp"] > 0
                     else g["fga"] - g["oreb"] + g["to"] + _ft_poss(g["fta"]))   # scoreless: whole FT trips
    # Back-solve opponent rebounds from the per-lineup OREB%/DREB% so aggregate
    # rebounding rates stay accurate: OREB% = OREB/(OREB+oppDREB).
    g["opp_dreb"] = g["oreb"] * (100 / g["oreb_pct"] - 1) if g["oreb_pct"] > 0 else 0.0
    g["opp_oreb"] = g["dreb"] * (100 / g["dreb_pct"] - 1) if g["dreb_pct"] > 0 else 0.0
    return {"jerseys": jerseys, **g}


def _load_pg_games(net_ranks=None, n_teams=0):
    """All per-game lineup files, each tagged with date/opp/venue/result/conf/quad.
    Opponent + venue come from the manifest (canonical names) when present."""
    conf = _conf_teams()
    garbage = _load_garbage()
    cccaa_venue = _cccaa_venues()        # official CCCAA home/away/neutral by date
    manifest = _PG_DIR / "manifest.json"
    if manifest.exists():
        entries = json.load(open(manifest))
    else:
        entries = [{"file": p.name, **dict(zip(("date", "opponent", "venue"),
                    _parse_pg_name(p.stem)))} for p in sorted(_PG_DIR.glob("*.csv"))]
    games = []
    for e in entries:
        path = _PG_DIR / e["file"]
        if not path.exists():
            continue
        raw = list(csv.reader(open(path, encoding="utf-8-sig")))
        lus, seen, pf, pa = [], set(), 0.0, 0.0
        for row in raw[2:]:
            l = _parse_lineup_row(row)
            if not l:
                continue
            key = tuple(sorted(l["jerseys"], key=int))
            if key in seen:       # keep first clean row per lineup
                continue
            seen.add(key)
            lus.append(l); pf += l["pf"]; pa += l["pa"]
        if not lus:
            continue
        # Competitive-only copy: subtract each lineup's logged garbage; drop
        # lineups that were entirely garbage.
        gday = garbage.get(e.get("date", ""), {})
        lus_ng = []
        for l in lus:
            jk = tuple(sorted(l["jerseys"], key=int))
            if jk in gday:
                ng = _strip_garbage(l, gday[jk])
                if ng is not None:
                    lus_ng.append(ng)
            else:
                lus_ng.append(dict(l))
        opp = e.get("opponent", "")
        # Prefer the official CCCAA venue; fall back to the Hudl/manifest label.
        venue = cccaa_venue.get(e.get("date", ""), e.get("venue", ""))
        games.append({"date": e.get("date", ""), "opp": opp, "venue": venue,
                      "file": e.get("file", ""),
                      "result": "W" if pf > pa else "L" if pf < pa else "T",
                      "conf": opp in conf, "has_garbage": bool(gday),
                      "quad": _get_quad((net_ranks or {}).get(opp), venue, n_teams),
                      "lineups": lus, "lineups_ng": lus_ng})
    games.sort(key=lambda gm: gm["date"])
    return games


def _subset_games(games, key):
    if key == "conf":            return [g for g in games if g["conf"]]
    if key == "conf_wins":       return [g for g in games if g["conf"] and g["result"] == "W"]
    if key == "conf_losses":     return [g for g in games if g["conf"] and g["result"] == "L"]
    if key == "nonconf":         return [g for g in games if not g["conf"]]
    if key == "nonconf_wins":    return [g for g in games if not g["conf"] and g["result"] == "W"]
    if key == "nonconf_losses":  return [g for g in games if not g["conf"] and g["result"] == "L"]
    if key == "home":         return [g for g in games if g["venue"] == "Home"]
    if key == "away":         return [g for g in games if g["venue"] == "Away"]
    if key == "neutral":      return [g for g in games if g["venue"] == "Neutral"]
    if key == "away_neutral": return [g for g in games if g["venue"] in ("Away", "Neutral")]
    if key == "wins":         return [g for g in games if g["result"] == "W"]
    if key == "losses":       return [g for g in games if g["result"] == "L"]
    if key == "q1a":          return [g for g in games if g.get("quad") == "1A"]
    if key == "q1":           return [g for g in games if g.get("quad") in ("1A", "1")]
    if key == "q2":           return [g for g in games if g.get("quad") == "2"]
    if key == "q12":          return [g for g in games if g.get("quad") in ("1A", "1", "2")]
    if key == "q3":           return [g for g in games if g.get("quad") == "3"]
    if key == "q4":           return [g for g in games if g.get("quad") == "4"]
    if key == "last5":        return games[-5:]
    if key == "last10":       return games[-10:]
    return games   # 'full'


def _aggregate_lineups(games, lkey="lineups"):
    """Sum each unique 5-man lineup's stats across the given games. lkey selects
    the full ('lineups') or garbage-removed ('lineups_ng') per-game rows."""
    acc = {}
    for gm in games:
        for l in gm.get(lkey, []):
            key = tuple(sorted(l["jerseys"], key=int))
            a = acc.get(key)
            if a is None:
                a = {"jerseys": l["jerseys"], **{k: 0.0 for k in _SUM}}
                acc[key] = a
            for k in _SUM:
                a[k] += l.get(k, 0.0)
    return list(acc.values())


def build_moorpark_lineups(opp_ratings=None, net_ranks=None, n_teams=0):
    """Build the full-season structure plus a `subsets` dict (Full / Conference /
    Last 5/10 / Home / Away / Neutral / Away+Neutral / Wins / Losses / Quad
    1A/1/2/1+2/3/4), all sourced from the per-game offensive logs (incl. Palomar
    3 + ghost-sub adjustments). Quads need net_ranks {team: rank} + n_teams."""
    games = _load_pg_games(net_ranks, n_teams)
    if not games:
        return None
    jmap = _jersey_map()
    official_min = _load_official_minutes(jmap)
    adj_maps, lg_avg = _opp_adjustment(opp_ratings)
    mdef_maps = _load_logged_defense()
    oncourt_ff = _load_oncourt_ff()
    onoff_ratings = _opp_ff_ratings()  # compute once, reuse for every split
    onoff_adj = _load_oncourt_onoff(None, onoff_ratings, jmap)

    full_games = len(games)

    # Per-split on/off so the cards react to the game-split dropdown — offense over
    # just that split's games (reuses ratings/jmap so it's cheap), keyed by subset.
    onoff_by_key = {}
    for _k in _SUBSET_KEYS:
        _gs = _subset_games(games, _k)
        onoff_by_key[_k] = onoff_adj if _k == "full" else (
            _load_oncourt_onoff({g["file"] for g in _gs}, onoff_ratings, jmap) if _gs else {})

    def _build_subsets(lkey, extras=False, ng=False):
        out = {}
        for key in _SUBSET_KEYS:
            gs = _subset_games(games, key)
            # Garbage-removed split is only worth shipping if the split contains a
            # game with logged garbage; otherwise it's identical to the regular
            # split and the page falls back to it (keeps the embed small).
            if ng and not any(g.get("has_garbage") for g in gs):
                out[key] = None
                continue
            lus = _aggregate_lineups(gs, lkey)
            if not lus:
                out[key] = None
                continue
            if key == "full" and extras:
                # Full season carries the season-wide extras (opponent-adjustment,
                # logged defense, persisted on/off, official-minute reconciliation).
                out[key] = _build_from_lineups(
                    lus, len(gs), jmap, official_min, adj_maps, lg_avg,
                    mdef_maps, oncourt_ff, onoff_by_key.get(key, {}), full_games)
            else:
                # Every other split (and all garbage-removed splits) gets its OWN
                # opponent-adjustment AND its own on/off over just its games.
                sub_adj, _ = _opp_adjustment(opp_ratings, {g["file"] for g in gs})
                out[key] = _build_from_lineups(
                    lus, len(gs), jmap, None, sub_adj, lg_avg, {}, {},
                    onoff_by_key.get(key, {}), full_games)
        return out

    subsets = _build_subsets("lineups", extras=True)
    subsets_ng = _build_subsets("lineups_ng", ng=True)   # only splits with logged garbage

    full = subsets.get("full")
    if full is None:
        return None
    result = dict(full)        # shallow copy avoids a self-referential cycle
    result["subsets"] = subsets
    result["subsets_ng"] = subsets_ng
    return result


def _build_from_lineups(lineups, n_games, jmap, official_min, adj_maps, lg_avg,
                        mdef_maps, oncourt_ff, onoff_adj, full_games=0):
    official_min = official_min or {}
    oncourt_ff = oncourt_ff or {}
    onoff_adj = onoff_adj or {}
    # Scale the minutes floor down for partial-season splits.
    _frac = (n_games / full_games) if (full_games and n_games < full_games) else 1.0
    def fl(k, base=None):
        base = _MIN_MINS.get(k, 12) if base is None else base
        return base if _frac >= 1.0 else max(base * _frac, _FLOOR_MIN.get(k, 3))
    def pname(j):
        return jmap.get(j, f"#{j}")

    # Team totals (lineup rows partition game time -> sums are season totals).
    tot = {k: sum(l.get(k, 0.0) for l in lineups) for k in _SUM}

    # ── Minute reconciliation: Hudl over-counts wall-clock minutes vs the official
    # CCCAA box score. Use official per-player minutes (we have them) for the 1-man
    # table, and a team-level scale for combo wall-clock. Per-possession ratings
    # (ORtg/DRtg/four factors) are possession-based and need no adjustment. ──
    hudl_wallclock = tot["mins"] or 1.0
    off_wallclock = (sum(official_min.values()) / 5.0) if official_min else hudl_wallclock
    min_scale = off_wallclock / hudl_wallclock

    # ── 1-man: on-court / off-court + ridge adjusted plus-minus ──
    onc = {}
    for l in lineups:
        for j in l["jerseys"]:
            a = onc.setdefault(j, {k: 0.0 for k in _SUM})
            for k in _SUM:
                a[k] += l.get(k, 0.0)
    # Player-table minutes floor also scales with split size (20 min full season,
    # never below 5), so the bench doesn't vanish on small splits.
    player_floor = 20.0 if _frac >= 1.0 else max(20.0 * _frac, 5.0)
    players = []
    for j, a in onc.items():
        if a["mins"] < player_floor:
            continue
        m = _metrics(a)
        # Official CCCAA minutes when available, else Hudl scaled to team total.
        on_min = official_min.get(j) or (a["mins"] * min_scale)
        off_min = max(off_wallclock - on_min, 1.0)
        on_net40 = a["pm"] / on_min * 40 if on_min else 0.0
        off_net40 = (tot["pm"] - a["pm"]) / off_min * 40
        pr = {
            "name": pname(j), "jersey": j, "min": round(on_min), "pm": m["pm"],
            "on_net40": _r(on_net40), "off_net40": _r(off_net40),
            "onoff": _r(on_net40 - off_net40),
            "on_ortg": m["ortg"], "on_drtg": m["drtg"], "on_net100": m["net100"],
        }
        if adj_maps:
            a = adj_maps.get(1, {}).get((j,))
            if a and a["poss"] > 0:
                wO, wD = a["oO"] / a["poss"], a["oD"] / a["poss"]
                pr["adj_net100"] = _r(m["net100"] + (wO - wD))
                pr["opp_net"] = _r(wO - wD)
        _apply_measured_def(pr, (j,), 1, mdef_maps)
        if oncourt_ff.get(j):
            pr["oncourt_ff"] = oncourt_ff[j]   # not surfaced in the UI yet
        if onoff_adj.get("players", {}).get(j):
            pr["onoff_adj"] = onoff_adj["players"][j]   # opponent-adjusted on/off
        players.append(pr)

    # Ridge RAPM split into offense / defense / total (one-team, relative to roster
    # avg, λ=50, minute-weighted). ORAPM regresses each lineup's offensive rating,
    # DRAPM the negated points allowed (so + = good defense); RAPM = the net
    # regression (== the existing `apm`). COMPUTED BUT NOT RENDERED ("don't publish").
    jlist = sorted(onc)
    jidx = {j: i for i, j in enumerate(jlist)}
    X, w, y_off, y_def = [], [], [], []
    for l in lineups:
        if l["off_poss"] < 4:
            continue
        vec = np.zeros(len(jlist))
        for j in l["jerseys"]:
            if j in jidx:
                vec[jidx[j]] = 1.0
        X.append(vec)
        w.append(l["mins"])
        y_off.append(l["pf"] / l["off_poss"] * 100)        # offensive rating
        y_def.append(-l["pa"] / l["off_poss"] * 100)       # neg pts allowed: + = better D
    apm = orapm = drapm = rapm = {}
    if X:
        X = np.array(X); w = np.sqrt(np.array(w))
        Xw = X * w[:, None]; I = np.eye(X.shape[1])

        def _ridge(yv):
            yv = np.array(yv); c = np.linalg.solve(Xw.T @ Xw + 50.0 * I, Xw.T @ (yv * w))
            return c - c.mean()
        co, cd = _ridge(y_off), _ridge(y_def)
        cn = co + cd  # RAPM = ORAPM + DRAPM (per the methodology)
        orapm = {jlist[i]: round(float(co[i]), 1) for i in range(len(jlist))}
        drapm = {jlist[i]: round(float(cd[i]), 1) for i in range(len(jlist))}
        rapm = {jlist[i]: round(float(cn[i]), 1) for i in range(len(jlist))}
        apm = rapm  # the existing 'apm' field == total RAPM (= ORAPM + DRAPM)
    for p in players:
        p["apm"] = apm.get(p["jersey"], 0.0)
        p["orapm"] = orapm.get(p["jersey"], 0.0)
        p["drapm"] = drapm.get(p["jersey"], 0.0)
        p["rapm"] = rapm.get(p["jersey"], 0.0)
    players.sort(key=lambda p: -p["apm"])

    # ── 2/3/4/5-man combos: aggregate every co-occurring subset ──
    combos = {}
    for k in (2, 3, 4, 5):
        acc = {}
        for l in lineups:
            js = sorted(set(l["jerseys"]))
            if len(js) < k:
                continue
            for combo in combinations(js, k):
                a = acc.setdefault(combo, {f: 0.0 for f in _SUM})
                for f in _SUM:
                    a[f] += l.get(f, 0.0)
        rows = []
        floor_k = fl(k)
        for combo, s in acc.items():
            if s["mins"] < floor_k:
                continue
            s["mins"] *= min_scale   # reconcile wall-clock to official minutes
            row = {"players": [pname(j) for j in combo], **_metrics(s)}
            _apply_adj(row, combo, k, adj_maps, lg_avg)
            _apply_measured_def(row, combo, k, mdef_maps)
            rows.append(row)
        rows.sort(key=lambda r: -r["min"])
        combos[str(k)] = rows[:_CAP]

    # ── positional sets: filter/group the same stints by position class ──
    pos = _load_positions(jmap)
    isG = lambda j: pos.get(j) in GUARDS
    isF = lambda j: pos.get(j) in FORWARDS

    def _pos_combos(size, filt, floor):
        acc = {}
        for l in lineups:
            js = sorted(set(l["jerseys"]))
            for combo in combinations(js, size):
                if not filt(combo):
                    continue
                a = acc.setdefault(combo, {f: 0.0 for f in _SUM})
                for f in _SUM:
                    a[f] += l.get(f, 0.0)
        rows = []
        for combo, s in acc.items():
            if s["mins"] < floor:
                continue
            s["mins"] *= min_scale
            row = {"players": [pname(j) for j in combo], **_metrics(s)}
            _apply_adj(row, combo, size, adj_maps, lg_avg)
            _apply_measured_def(row, combo, size, mdef_maps)
            rows.append(row)
        rows.sort(key=lambda r: -r["min"])
        return rows[:_CAP]

    def _pos_group(memberfn, floor):
        acc = {}
        for l in lineups:
            sub = tuple(sorted(j for j in set(l["jerseys"]) if memberfn(j)))
            if not sub:
                continue
            a = acc.setdefault(sub, {f: 0.0 for f in _SUM})
            for f in _SUM:
                a[f] += l.get(f, 0.0)
        rows = []
        for sub, s in acc.items():
            if s["mins"] < floor:
                continue
            s["mins"] *= min_scale
            row = {"players": [pname(j) for j in sub], **_metrics(s)}
            _apply_adj(row, sub, len(sub), adj_maps, lg_avg)
            _apply_measured_def(row, sub, len(sub), mdef_maps)
            rows.append(row)
        rows.sort(key=lambda r: -r["min"])
        return rows[:_CAP]

    pos_sets = {
        "P": _pos_combos(1, lambda c: isG(c[0]), fl(1, 40)),                       # each guard, 1 on floor
        "backcourt": _pos_combos(3, lambda c: all(isG(j) for j in c), fl(3)),
        "guard_fwd": _pos_combos(2, lambda c: sum(isG(j) for j in c) == 1 and sum(isF(j) for j in c) == 1, fl(2)),
        "frontcourt": _pos_combos(2, lambda c: all(isF(j) for j in c), fl(2)),
        "C": _pos_combos(1, lambda c: isF(c[0]), fl(1, 40)),                       # each forward, 1 on floor
    }

    team_poss = tot["off_poss"] or 1.0
    tt = {
        "min": round(off_wallclock),
        "ortg": _r(tot["pf"] / team_poss * 100),
        "drtg": _r(tot["pa"] / team_poss * 100),
        "net100": _r((tot["pf"] - tot["pa"]) / team_poss * 100),
        "lineups_tracked": len(lineups),
        "n_games": n_games,
        "min_reconciled": bool(official_min),
    }
    if adj_maps:
        ta = adj_maps.get(0, {}).get(())
        if ta and ta["poss"] > 0:
            wO, wD = ta["oO"] / ta["poss"], ta["oD"] / ta["poss"]
            tt["adj_ortg"] = _r(tt["ortg"] + (lg_avg - wD))
            tt["adj_drtg"] = _r(tt["drtg"] + (lg_avg - wO))
            tt["adj_net100"] = _r(tt["net100"] + (wO - wD))
            tt["opp_net"] = _r(wO - wD)
    _apply_measured_def(tt, (), 0, mdef_maps)
    return {
        "team": "Moorpark",
        "team_totals": tt,
        "players": players,
        "combos": combos,
        "positions": pos,
        "pos_sets": pos_sets,
        "opp_adjusted": bool(adj_maps),
        "def_logged": bool(mdef_maps),
        "onoff_adj": onoff_adj,
    }


if __name__ == "__main__":
    d = build_moorpark_lineups()
    if not d:
        print("No lineup file.")
    else:
        print("Team:", d["team_totals"])
        print(f"\nPlayers (1-man): {len(d['players'])}")
        for p in d["players"][:5]:
            print(f"  {p['name']:<16}{p['min']:>5}m  net/40 {p['on_net40']:+5.1f}  "
                  f"on/off {p['onoff']:+5.1f}  adj {p['apm']:+5.1f}")
        for k in ("2", "3", "4", "5"):
            c = d["combos"][k]
            print(f"\n{k}-man combos: {len(c)} (>= {_MIN_MINS[int(k)]} min). Top 3 by minutes:")
            for r in c[:3]:
                print(f"  {r['min']:>4}m net {r['net100']:+6.1f} eFG {r['efg']:>4} TS {r['ts']:>4} "
                      f"TOV {r['tov']:>4} OREB% {r['oreb_pct']:>4}  " + " / ".join(r["players"]))
