"""
Standalone mockup of the enhanced Player Profile page (v2 feature preview).

Generates player_page_mockup.html for one player with REAL data from the
leaderboard caches: percentile bars + state ranks, expanded splits (home/away,
wins/losses, monthly, L5/L10), season highs, consistency profile, Line of the
Night badges, role context, rolling-form sparkline, usage-vs-efficiency mini
scatter, similar players, and a filterable game log.

Usage: python3 mockup_player_page.py  (defaults to Noah Cotton, Moorpark)
"""

import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generate_leaderboard import (
    _cached_json, _box_game_key, STAT_DEFINITIONS,
    attach_porpagatu, attach_player_jerseys,
)
from update_advanced_analytics import _compute_ind_ortg

PLAYER = "Noah Cotton"
SCHOOL = "Moorpark"

players = _cached_json("2526_players", lambda: None)
conf_players = _cached_json("2526_conf_players", lambda: None)
teams = _cached_json("2526_teams", lambda: None)
rosters = _cached_json("2526_rosters", lambda: None)
boxes = _cached_json("2526_boxes", lambda: None)
storylines = _cached_json("2526_storylines", lambda: None)

attach_porpagatu(players, teams)
attach_player_jerseys(players)
me = next(p for p in players if p["name"] == PLAYER and p["school"] == SCHOOL)
conf_me = next((p for p in conf_players if p["name"] == PLAYER and p["school"] == SCHOOL), None)
team = next(t for t in teams if t["team"] == SCHOOL)
roster_me = next(p for p in rosters[SCHOOL]["players"] if p["name"] == PLAYER)

try:
    bpm_meta = next(r for r in json.load(open("internal_data/ccc_bpm_2025_26.json"))["players"]
                    if r["team"] == SCHOOL and r["player"] == PLAYER)
except StopIteration:
    bpm_meta = {}

# ── collect games (mirror of the page's __ppGames) ──────────────────────────
net_ranks = {t["team"]: i + 1 for i, t in
             enumerate(sorted([t for t in teams if t.get("ortg", 0) > 0],
                              key=lambda x: -x["net_rtg"]))}

games = []
for gr in team.get("game_ratings", []):
    if gr.get("result") not in ("W", "L"):
        continue
    opp = gr.get("canonical_opponent") or gr.get("opponent")
    g = boxes.get(_box_game_key(gr["date"], SCHOOL, opp))
    if not g:
        continue
    tkey = next((k for k in g["t"] if k == SCHOOL), None)
    okey = next((k for k in g["t"] if k != SCHOOL), None)
    rows = g["t"].get(tkey, [])
    mine = next((r for r in rows if r["n"] == PLAYER), None)
    if not mine:
        continue
    rk = net_ranks.get(opp)
    tier = ""
    if rk:
        adj = rk * 50 / 90 if gr.get("location") == "Away" else rk * 50 / 20 if gr.get("location") == "Home" else rk
        tier = "A" if adj <= 15 else "B" if adj <= 30 else ""
    games.append({"gr": gr, "opp": opp, "rk": rk or "", "tier": tier,
                  "me": mine, "team_rows": rows, "opp_rows": g["t"].get(okey, [])})

# ── aggregation engine (same formulas as the pipeline) ──────────────────────
KEYS = ["MIN", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "OREB", "DREB",
        "AST", "STL", "BLK", "TO", "PF", "PTS"]
RK = {"MIN": "min", "FGM": "fgm", "FGA": "fga", "3PM": "tpm", "3PA": "tpa",
      "FTM": "ftm", "FTA": "fta", "OREB": "or", "DREB": "dr", "AST": "ast",
      "STL": "stl", "BLK": "blk", "TO": "to", "PF": "pf", "PTS": "pts"}

def summed(rows):
    return {k: sum(r.get(RK[k], 0) or 0 for r in rows) for k in KEYS}

def line(label, subset):
    if not subset:
        return None
    P = summed([g["me"] for g in subset])
    T = summed([r for g in subset for r in g["team_rows"]])
    O = summed([r for g in subset for r in g["opp_rows"]])
    P["REB"] = P["OREB"] + P["DREB"]
    ctx = {
        "team_min": T["MIN"] / 5.0, "team_fgm": T["FGM"], "team_fga": T["FGA"],
        "team_fta": T["FTA"], "team_ftm": T["FTM"], "team_to": T["TO"],
        "team_oreb": T["OREB"], "team_dreb": T["DREB"], "team_ast": T["AST"],
        "team_pts": T["PTS"], "team_3pm": T["3PM"], "team_blk": T["BLK"],
        "team_stl": T["STL"], "team_pf": T["PF"],
        "team_poss": T["FGA"] + 0.475 * T["FTA"] - T["OREB"] + T["TO"],
        "opp_dreb": O["DREB"], "opp_fga": O["FGA"], "opp_fgm": O["FGM"],
        "opp_fta": O["FTA"], "opp_ftm": O["FTM"], "opp_oreb": O["OREB"],
        "opp_to": O["TO"], "opp_pts": O["PTS"], "opp_3pa": O["3PA"],
        "opp_pf": O["PF"],
    }
    out = {"label": label, "g": len(subset),
           "gp": sum(1 for g in subset if (g["me"].get("min") or 0) > 0 or g["me"].get("pts") or g["me"].get("fga"))}
    out["min_pct"] = round(P["MIN"] / (40 * len(subset)) * 100, 1)
    out["ortg"] = _compute_ind_ortg(P, ctx) or None
    for short, stat in [("usg", "usage_pct"), ("shots", "shot_pct"), ("efg", "efg_pct"),
                        ("ts", "ts_pct"), ("orp", "oreb_pct"), ("drp", "dreb_pct"),
                        ("ar", "ast_rate"), ("tor", "tov_pct"), ("blk", "blk_pct"),
                        ("stl", "stl_pct"), ("fc", "fc_per_40"), ("fd", "fd_per_40"),
                        ("ftr", "ft_rate")]:
        try:
            out[short] = STAT_DEFINITIONS[stat]["compute"](P, ctx)
        except Exception:
            out[short] = None
    out["ftm"], out["fta"] = P["FTM"], P["FTA"]
    out["ftp"] = round(100 * P["FTM"] / P["FTA"], 1) if P["FTA"] else None
    out["twom"], out["twoa"] = P["FGM"] - P["3PM"], P["FGA"] - P["3PA"]
    out["twop"] = round(100 * out["twom"] / out["twoa"], 1) if out["twoa"] else None
    out["tpm"], out["tpa"] = P["3PM"], P["3PA"]
    out["tpp"] = round(100 * P["3PM"] / P["3PA"], 1) if P["3PA"] else None
    out["P"] = P
    return out

MONTHS = {"11": "November", "12": "December", "1": "January", "2": "February", "3": "March"}
def month_of(g):
    return g["gr"]["date"].split("/")[0]

splits = [
    line("Season", games),
    line("Conference", [g for g in games if g["gr"].get("is_conference")]),
    line("vs Tier A", [g for g in games if g["tier"] == "A"]),
    line("vs Tier B", [g for g in games if g["tier"] == "B"]),
    line("vs Tier A+B", [g for g in games if g["tier"]]),
    line("Untiered", [g for g in games if not g["tier"]]),
    None,
    line("Home", [g for g in games if g["gr"].get("location") == "Home"]),
    line("Away", [g for g in games if g["gr"].get("location") == "Away"]),
    line("Neutral", [g for g in games if g["gr"].get("location") not in ("Home", "Away")]),
    line("In Wins", [g for g in games if g["gr"]["result"] == "W"]),
    line("In Losses", [g for g in games if g["gr"]["result"] == "L"]),
    None,
] + [line(MONTHS[m], [g for g in games if month_of(g) == m])
     for m in ["11", "12", "1", "2", "3"] if any(month_of(g) == m for g in games)] + [
    None,
    line("Last 5", games[-5:]),
    line("Last 10", games[-10:]),
]

# ── percentiles & state ranks (min30 pool) ──────────────────────────────────
pool = [p for p in players if (p.get("min_pct") or 0) >= 30]
PCT_STATS = [("ind_ortg", "ORtg", False), ("usage_pct", "%Poss", False),
             ("efg_pct", "eFG%", False), ("ts_pct", "TS%", False),
             ("ast_rate", "ARate", False), ("tov_pct", "TORate", True),
             ("stl_pct", "Stl%", False), ("porp", "PRPG!", False)]
pct_bars = []
for key, label, asc in PCT_STATS:
    vals = sorted((p[key] for p in pool if p.get(key) is not None), reverse=not asc)
    v = me.get(key)
    if v is None or not vals:
        continue
    rank = next((i + 1 for i, x in enumerate(vals) if (x <= v if not asc else x >= v)), len(vals))
    pctl = round(100 * (1 - (rank - 1) / max(len(vals) - 1, 1)))
    pct_bars.append({"label": label, "value": v, "rank": rank, "n": len(vals), "pctl": pctl})

# ── season highs / consistency / LOTN ───────────────────────────────────────
played = [g for g in games if (g["me"].get("min") or 0) > 0 or g["me"].get("pts")]
def best(keyfn, fmt):
    g = max(played, key=keyfn)
    return {"v": fmt(g), "date": g["gr"]["date"], "opp": g["opp"], "res": g["gr"]["result"]}
highs = {
    "Points": best(lambda g: g["me"]["pts"], lambda g: g["me"]["pts"]),
    "Rebounds": best(lambda g: g["me"]["or"] + g["me"]["dr"], lambda g: g["me"]["or"] + g["me"]["dr"]),
    "Assists": best(lambda g: g["me"]["ast"], lambda g: g["me"]["ast"]),
    "Steals": best(lambda g: g["me"]["stl"], lambda g: g["me"]["stl"]),
    "Blocks": best(lambda g: g["me"]["blk"], lambda g: g["me"]["blk"]),
    "Best ORtg": best(lambda g: (g["me"].get("ortg") or 0) if (g["me"].get("min") or 0) >= 10 else 0,
                      lambda g: g["me"].get("ortg")),
    "Best BPM": best(lambda g: g["me"].get("bpm") if g["me"].get("bpm") is not None else -99,
                     lambda g: g["me"].get("bpm")),
}
buckets = {"0-9": 0, "10-19": 0, "20+": 0}
dds = 0
for g in played:
    pts = g["me"]["pts"]
    buckets["0-9" if pts < 10 else "10-19" if pts < 20 else "20+"] += 1
    cats = sum(1 for v in [pts, g["me"]["or"] + g["me"]["dr"], g["me"]["ast"]] if v >= 10)
    dds += cats >= 2
bpms = [g["me"]["bpm"] for g in played if g["me"].get("bpm") is not None]
volatility = round(statistics.pstdev(bpms), 1) if len(bpms) > 2 else None

lotn = [(d, l) for d, l in (storylines.get("lines_of_night") or {}).items()
        if l.get("name") == PLAYER and l.get("team") == SCHOOL]

# ── similar players (z-score nearest neighbors) ─────────────────────────────
SIM_KEYS = ["usage_pct", "ind_ortg", "ast_rate", "oreb_pct", "dreb_pct",
            "stl_pct", "blk_pct", "tov_pct", "min_pct"]
SEASON_LABELS = {"2526": "2025-26", "2425": "2024-25", "2324": "2023-24",
                 "2223": "2022-23", "2122": "2021-22", "1920": "2019-20",
                 "1819": "2018-19", "1718": "2017-18"}
sim_pool = []
for skey, slabel in SEASON_LABELS.items():
    sp = _cached_json(f"{skey}_players", lambda: None) or []
    st = _cached_json(f"{skey}_teams", lambda: None) or []
    attach_porpagatu(sp, st)
    for q in sp:
        if (q.get("min_pct") or 0) >= 30 and all(q.get(k) is not None for k in SIM_KEYS):
            q["_season"] = slabel
            sim_pool.append(q)
sd = {k: statistics.pstdev(q[k] for q in sim_pool) or 1 for k in SIM_KEYS}
def dist(q):
    return math.sqrt(sum(((q[k] - me[k]) / sd[k]) ** 2 for k in SIM_KEYS))
similar = sorted((q for q in sim_pool
                  if not (q["name"] == PLAYER and q["school"] == SCHOOL and q["_season"] == "2025-26")),
                 key=dist)[:6]

# ── sparkline: rolling-5 ORtg ───────────────────────────────────────────────
spark_pts = []
ortgs = [(i, g["me"].get("ortg")) for i, g in enumerate(played)]
for i in range(len(played)):
    window = [v for j, v in ortgs[max(0, i - 4):i + 1] if v is not None]
    spark_pts.append(sum(window) / len(window) if window else None)

# ═════════ HTML ══════════════════════════════════════════════════════════════
def f(v, d=1):
    return "—" if v is None else f"{v:.{d}f}"

def split_row(s):
    if s is None:
        return '<tr class="sep"><td colspan="24"></td></tr>'
    cls = ' class="season-row"' if s["label"] == "Season" else ""
    return (f'<tr{cls}><td class="l">{s["label"]}</td><td>{s["gp"]}</td><td>{f(s["min_pct"])}</td>'
            f'<td><b>{f(s["ortg"])}</b></td><td>{f(s["usg"])}</td><td>{f(s["shots"])}</td>'
            f'<td>{f(s["efg"])}</td><td>{f(s["ts"])}</td><td>{f(s["orp"])}</td><td>{f(s["drp"])}</td>'
            f'<td>{f(s["ar"])}</td><td>{f(s["tor"])}</td><td>{f(s["blk"])}</td><td>{f(s["stl"])}</td>'
            f'<td>{f(s["fc"])}</td><td>{f(s["fd"])}</td><td>{f(s["ftr"])}</td>'
            f'<td>{s["ftm"]}-{s["fta"]}</td><td>{f(s["ftp"])}</td>'
            f'<td>{s["twom"]}-{s["twoa"]}</td><td>{f(s["twop"])}</td>'
            f'<td>{s["tpm"]}-{s["tpa"]}</td><td>{f(s["tpp"])}</td></tr>')

season = splits[0]
rank_cells = "".join(
    f'<td class="rk">{b["rank"]}</td>' if i < 0 else "" for i, b in enumerate(pct_bars))

bar_html = ""
for b in pct_bars:
    color = "#2e7d32" if b["pctl"] >= 75 else "#f9a825" if b["pctl"] >= 40 else "#c62828"
    bar_html += (f'<div class="pbar"><div class="pbar-label">{b["label"]}</div>'
                 f'<div class="pbar-track"><div class="pbar-fill" style="width:{b["pctl"]}%;background:{color}"></div></div>'
                 f'<div class="pbar-val">{b["value"]}</div>'
                 f'<div class="pbar-rk">#{b["rank"]}<small>/{b["n"]}</small> · {b["pctl"]}th</div></div>')

highs_html = "".join(
    f'<div class="high"><div class="high-v">{h["v"]}</div><div class="high-k">{k}</div>'
    f'<div class="high-d">{h["date"]} {"vs" if True else ""} {h["opp"]} ({h["res"]})</div></div>'
    for k, h in highs.items())

lotn_html = ""
if lotn:
    lotn_html = ('<div class="card"><div class="sub">🏆 Lines of the Night</div><div class="lotn">'
                 + "".join(f'<span class="lotn-badge">{d} — {l["pts"]} pts vs {next((g["opp"] for g in games if g["gr"]["date"] == d), "?")}</span>'
                           for d, l in lotn) + "</div></div>")

sim_html = "".join(
    f'<tr><td class="l">{p["name"]}</td><td class="l">{p["school"]}</td><td>{p.get("_season", "")}</td><td>{p.get("pos", "")}</td>'
    f'<td>{f(p["ind_ortg"])}</td><td>{f(p["usage_pct"])}</td><td>{f(p["min_pct"])}</td>'
    f'<td>{f(p.get("porp"), 2)}</td></tr>'
    for p in similar)

# Torvik-style rolling chart data: per-game series for every stat
def g3p(r):
    return round(100 * r["tpm"] / r["tpa"], 1) if r.get("tpa") else None
CHART_STATS = [
    ("ortg", "Offensive Rating"), ("usg", "Usage"), ("efg", "Effective FG %"),
    ("top", "Turnover Rate"), ("orp", "Offensive Rebounding %"), ("drp", "Defensive Rebounding %"),
    ("p3", "3-Pt %"), ("pts", "Points"), ("ast", "Assists"), ("or", "Off. Rebounds"),
    ("dr", "Def. Rebounds"), ("stl", "Steals"), ("blk", "Blocks"), ("to", "Turnovers"),
    ("min", "Minutes"), ("bpm", "Game BPM"),
]
chart_series = [{
    "d": g["gr"]["date"], "opp": g["opp"], "res": g["gr"]["result"],
    "ortg": g["me"].get("ortg"), "usg": g["me"].get("usg"), "efg": g["me"].get("efg"),
    "top": g["me"].get("top"), "orp": g["me"].get("orp"), "drp": g["me"].get("drp"),
    "p3": g3p(g["me"]), "pts": g["me"]["pts"], "ast": g["me"]["ast"], "or": g["me"]["or"],
    "dr": g["me"]["dr"], "stl": g["me"]["stl"], "blk": g["me"]["blk"], "to": g["me"]["to"],
    "min": g["me"]["min"], "bpm": g["me"].get("bpm"),
} for g in played]
chart_json = json.dumps(chart_series)
chart_opts = "".join(f'<option value="{k}">{lbl}</option>' for k, lbl in CHART_STATS)

# mini scatter
mw, mh = 560, 300
xs = [p["usage_pct"] for p in pool if p.get("usage_pct") and p.get("ind_ortg")]
ys = [p["ind_ortg"] for p in pool if p.get("usage_pct") and p.get("ind_ortg")]
x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
def sx(v): return 35 + (v - x0) * (mw - 50) / (x1 - x0)
def sy(v): return mh - 25 - (v - y0) * (mh - 40) / (y1 - y0)
scatter_dots = "".join(
    f'<circle cx="{sx(p["usage_pct"]):.1f}" cy="{sy(p["ind_ortg"]):.1f}" r="2.4" fill="#bbb" opacity="0.55"><title>{p["name"]} ({p["school"]})</title></circle>'
    for p in pool if p.get("usage_pct") and p.get("ind_ortg")
    and not (p["name"] == PLAYER and p["school"] == SCHOOL))
me_dot = (f'<circle cx="{sx(me["usage_pct"]):.1f}" cy="{sy(me["ind_ortg"]):.1f}" r="8" fill="#c8960c" stroke="#1a1a2e" stroke-width="2"/>'
          f'<text x="{sx(me["usage_pct"])+12:.1f}" y="{sy(me["ind_ortg"])+4:.1f}" font-size="11" font-weight="700" fill="#1a1a2e">{PLAYER}</text>')
scatter_svg = (f'<svg viewBox="0 0 {mw} {mh}" style="width:100%;max-width:{mw}px">'
               f'<text x="{mw/2}" y="{mh-4}" font-size="10" fill="#666" text-anchor="middle">%Poss (usage)</text>'
               f'<text x="10" y="{mh/2}" font-size="10" fill="#666" transform="rotate(-90 10 {mh/2})" text-anchor="middle">ORtg</text>'
               + scatter_dots + me_dot + "</svg>")

# game log
def log_row(g):
    r = g["me"]
    cls = "gw" if g["gr"]["result"] == "W" else "gl"
    badge = {"A": '<span class="tA">A</span>', "B": '<span class="tB">B</span>'}.get(g["tier"], "")
    mn = f'<span class="st">{r["min"]}</span>' if r.get("st") else r["min"]
    return (f'<tr class="{cls}" data-f="{g["flags"]}"><td class="l">{g["gr"]["date"]}</td><td>{g["rk"]}</td>'
            f'<td class="l">{g["opp"]}{" *" if g["gr"].get("is_conference") else ""}</td><td>{badge}</td>'
            f'<td class="l res">{g["gr"]["result"]}, {g["gr"]["team_score"]}-{g["gr"]["opponent_score"]}</td>'
            f'<td>{mn}</td><td><b>{r["pts"]}</b></td>'
            f'<td>{r["fgm"]-r["tpm"]}-{r["fga"]-r["tpa"]}</td><td>{r["tpm"]}-{r["tpa"]}</td>'
            f'<td>{r["ftm"]}-{r["fta"]}</td><td>{r["or"]}-{r["dr"]}</td><td>{r["ast"]}</td>'
            f'<td>{r["to"]}</td><td>{r["stl"]}</td><td>{r["blk"]}</td><td>{r["pf"]}</td>'
            f'<td>{f(r.get("ortg"))}</td><td>{f(r.get("usg"))}</td><td>{f(r.get("bpm"))}</td></tr>')

last_conf = max((i for i, g in enumerate(games) if g["gr"].get("is_conference")), default=-1)
for i, g in enumerate(games):
    fl = []
    if g["gr"].get("is_conference"): fl.append("conf")
    if g["tier"] == "A": fl.append("ta")
    if g["tier"] == "B": fl.append("tb")
    if last_conf >= 0 and i > last_conf: fl.append("po")
    g["flags"] = " ".join(fl)
opp_opts = ('<option value="">Full Season</option><option value="conf">Conference</option>'
            '<option value="ta">vs Tier A</option><option value="tb">vs Tier B</option>'
            '<option value="ta tb">vs Tier A+B</option><option value="po">Playoffs</option>')

role_bits = []
if bpm_meta:
    role_bits.append(f'position scale <b>{bpm_meta["position_scale"]}</b>')
    role_bits.append(f'creation role <b>{bpm_meta["creation_role"]}</b> '
                     f'({"creator" if bpm_meta["creation_role"] >= 3 else "play finisher"})')
starts = sum(1 for g in games if g["me"].get("st"))
recent_starts = sum(1 for g in games[-15:] if g["me"].get("st"))
role_bits.append(f'started <b>{recent_starts}</b> of last 15')
role_line = " · ".join(role_bits)

adv_header = ('<tr><th class="l">Split</th><th>G</th><th>%Min</th><th>ORtg</th><th>%Poss</th><th>%Shots</th>'
              '<th>eFG%</th><th>TS%</th><th>OR%</th><th>DR%</th><th>ARate</th><th>TORate</th>'
              '<th>Blk%</th><th>Stl%</th><th>FC/40</th><th>FD/40</th><th>FTRate</th>'
              '<th>FTM-A</th><th>Pct</th><th>2PM-A</th><th>Pct</th><th>3PM-A</th><th>Pct</th></tr>')

html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>MOCKUP — {PLAYER} Player Page v2</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0a0a0a; padding:24px; color:#000; }}
  .mock-banner {{ text-align:center; background:#c8960c; color:#000; font-weight:800; padding:6px; border-radius:6px; margin-bottom:14px; }}
  .hdr {{ background:#1a1a2e; border-radius:8px; padding:18px 20px; text-align:center; margin-bottom:16px; }}
  .hdr .meta {{ color:#4fc3f7; font-size:0.95rem; font-weight:700; }}
  .hdr h1 {{ color:#B9D9EB; font-size:1.8rem; margin:4px 0; }}
  .hdr .sub2 {{ color:#ccc; font-size:0.9rem; }}
  .hdr .hl {{ color:#fff; font-size:1rem; font-weight:600; margin-top:6px; }}
  .hdr .role {{ color:#9fb6d4; font-size:0.8rem; margin-top:6px; }}
  .card {{ background:#fff; border:1px solid #ccc; border-radius:8px; padding:16px; margin:0 auto 16px; max-width:fit-content; overflow-x:auto; }}
  .sub {{ font-size:0.95rem; font-weight:700; text-align:center; border-bottom:2px solid #333; padding-bottom:5px; margin-bottom:12px; }}
  .grid2 {{ display:flex; gap:16px; flex-wrap:wrap; justify-content:center; align-items:stretch; }}
  table {{ border-collapse:collapse; font-size:0.78rem; white-space:nowrap; margin:0 auto; }}
  th {{ background:#1a1a2e; color:#fff; padding:5px 8px; text-align:right; font-size:0.7rem; }}
  th.l, td.l {{ text-align:left; }}
  td {{ padding:4px 8px; border-bottom:1px solid #ddd; text-align:right; background:#fff; }}
  td.l {{ font-weight:600; }}
  tr.season-row td {{ background:#eef3fb; border-bottom:2px solid #1a3a6e; }}
  tr.sep td {{ background:#1a1a2e; padding:2px; border:none; }}
  tr:hover td {{ background:#eef4ff; }}
  tr.gw td {{ background:rgb(0,255,0); }} tr.gl td {{ background:rgb(255,0,0); }}
  tr.gw:hover td {{ background:rgb(0,230,0); }} tr.gl:hover td {{ background:rgb(230,0,0); }}
  .tA {{ background:#c8960c; color:#fff; padding:1px 6px; border-radius:3px; font-size:0.7rem; font-weight:700; }}
  .tB {{ background:#546e7a; color:#fff; padding:1px 6px; border-radius:3px; font-size:0.7rem; font-weight:700; }}
  .st {{ display:inline-block; min-width:18px; border:1.6px solid #1a3e8f; border-radius:2px; padding:0 2px; font-weight:700; }}
  .pbar {{ display:grid; grid-template-columns:64px 240px 52px 110px; gap:10px; align-items:center; margin-bottom:7px; font-size:0.82rem; }}
  .pbar-label {{ font-weight:700; text-align:right; }}
  .pbar-track {{ background:#e8e8e8; border-radius:4px; height:14px; }}
  .pbar-fill {{ height:14px; border-radius:4px; }}
  .pbar-val {{ font-weight:800; text-align:right; }}
  .pbar-rk {{ color:#c62828; font-weight:700; font-size:0.74rem; }}
  .high {{ background:#f4f6fb; border:1px solid #d8e0ee; border-radius:8px; padding:10px 14px; text-align:center; min-width:108px; }}
  .high-v {{ font-size:1.5rem; font-weight:800; color:#1a3e8f; }}
  .high-k {{ font-size:0.72rem; font-weight:700; color:#555; text-transform:uppercase; }}
  .high-d {{ font-size:0.68rem; color:#888; margin-top:3px; }}
  .buckets {{ display:flex; gap:10px; justify-content:center; }}
  .bucket {{ text-align:center; padding:8px 16px; border-radius:8px; background:#f4f6fb; border:1px solid #d8e0ee; }}
  .bucket b {{ font-size:1.3rem; color:#1a3e8f; }}
  .lotn-badge {{ display:inline-block; background:#fff7df; border:1px solid #c8960c; color:#7a5b00; font-weight:700; border-radius:6px; padding:4px 10px; margin:3px; font-size:0.8rem; }}
  select {{ font-size:0.85rem; padding:4px 8px; margin-bottom:10px; }}
  .res {{ color:#0d47a1; font-weight:700; }}
  .note {{ font-size:0.7rem; color:#888; margin-top:6px; }}
</style></head><body>
<div class="mock-banner">MOCKUP — Player Page v2 preview (real 2025-26 data)</div>
<div class="hdr">
  <div class="meta">#{me.get('jersey','')} · {me.get('pos','')} · {roster_me.get('ht','')}</div>
  <h1>{PLAYER}</h1>
  <div class="sub2">{SCHOOL} · {team['conference']} · 2025-26</div>
  <div class="hl">{me['gp']} GP · {starts} starts &nbsp;|&nbsp; <b>{me['ppg']}</b> PPG · <b>{me['ind_ortg']}</b> ORtg · <b>{me.get('porp')}</b> PRPG! · <b>{me.get('bpm')}</b> BPM</div>
  <div class="role">{role_line}</div>
</div>

<div class="card" style="min-width:540px">
  <div class="sub">State Percentiles <small>(vs {len(pool)} qualified players · red = state rank)</small></div>
  {bar_html}
</div>

<div class="grid2">
  <div class="card"><div class="sub">Season Highs</div><div class="grid2">{highs_html}</div></div>
  <div class="card"><div class="sub">Consistency</div>
    <div class="buckets">
      <div class="bucket"><b>{buckets['0-9']}</b><div>0-9 pts</div></div>
      <div class="bucket"><b>{buckets['10-19']}</b><div>10-19 pts</div></div>
      <div class="bucket"><b>{buckets['20+']}</b><div>20+ pts</div></div>
      <div class="bucket"><b>{dds}</b><div>dbl-dbls</div></div>
      <div class="bucket"><b>{f(volatility)}</b><div>BPM volatility</div></div>
    </div>
  </div>
</div>
{lotn_html}

<div class="grid2">
  <div class="card" style="min-width:660px"><div class="sub">Game-by-Game <small>(dots = games · solid = season moving avg · dashed = 5-game avg)</small></div>
    <div style="text-align:center;margin-bottom:8px"><select id="cstat" onchange="drawChart()">{chart_opts}</select></div>
    <div id="chartbox"></div>
  </div>
  <div class="card"><div class="sub">Usage vs Efficiency <small>(every qualified player in the state)</small></div>{scatter_svg}</div>
</div>

<div class="card">
  <div class="sub">Season &amp; Split Stats</div>
  <table><thead>{adv_header}</thead><tbody>
    {"".join(split_row(s) for s in splits)}
  </tbody></table>
  <div class="note">Splits aggregated from box scores with the same formulas as season stats · Tier A/B per the schedule rule</div>
</div>

<div class="card"><div class="sub">Similar Players <small>(statistical nearest neighbors, qualified pool)</small></div>
  <table><thead><tr><th class="l">Player</th><th class="l">School</th><th>Season</th><th>Pos</th><th>ORtg</th><th>%Poss</th><th>%Min</th><th>PRPG!</th></tr></thead>
  <tbody>{sim_html}</tbody></table>
</div>

<div class="card">
  <div class="sub">Game Log</div>
  <div style="text-align:center"><select onchange="const want=this.value.split(' ').filter(Boolean);document.querySelectorAll('tbody#log tr').forEach(r => {{const fl=(r.dataset.f||'').split(' ');r.style.display = !want.length || want.some(w => fl.includes(w)) ? '' : 'none'}})">{opp_opts}</select></div>
  <table><thead><tr><th class="l">Date</th><th>Rk</th><th class="l">Opponent</th><th>Tier</th><th class="l">Result</th>
  <th>Min</th><th>Pts</th><th>2P</th><th>3P</th><th>FT</th><th>OR-DR</th><th>A</th><th>TO</th><th>S</th><th>B</th><th>PF</th><th>ORtg</th><th>%Poss</th><th>BPM</th></tr></thead>
  <tbody id="log">{"".join(log_row(g) for g in games)}</tbody></table>
  <div class="note">Boxed minutes = started · * = conference game</div>
</div>
<script>
const SERIES = {chart_json};
function drawChart() {{
  const key = document.getElementById('cstat').value;
  const pts = SERIES.map((g, i) => ({{ i: i, v: g[key], res: g.res, d: g.d, opp: g.opp }}));
  const valid = pts.filter(p => p.v != null);
  if (!valid.length) {{ document.getElementById('chartbox').innerHTML = '<i>no data</i>'; return; }}
  const W = 640, H = 260, L = 38, R = 12, T = 12, B = 26;
  let mov = [], five = [], run = [];
  pts.forEach(p => {{
    if (p.v != null) run.push(p.v);
    mov.push(run.length ? run.reduce((a, b) => a + b, 0) / run.length : null);
    const tail = run.slice(-5);
    five.push(tail.length ? tail.reduce((a, b) => a + b, 0) / tail.length : null);
  }});
  const all = valid.map(p => p.v).concat(mov.filter(v => v != null), five.filter(v => v != null));
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 2) {{ hi += 1; lo -= 1; }}
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const X = i => L + i * (W - L - R) / Math.max(SERIES.length - 1, 1);
  const Y = v => T + (hi - v) * (H - T - B) / (hi - lo);
  let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;max-width:' + W + 'px">';
  for (let k = 0; k <= 4; k++) {{
    const v = lo + k * (hi - lo) / 4;
    svg += '<line x1="' + L + '" y1="' + Y(v) + '" x2="' + (W - R) + '" y2="' + Y(v) + '" stroke="#eee"/>'
        + '<text x="' + (L - 4) + '" y="' + (Y(v) + 3) + '" font-size="9" fill="#888" text-anchor="end">' + v.toFixed(1) + '</text>';
  }}
  const line = (arr, color, dash) => {{
    const seg = arr.map((v, i) => v == null ? null : X(i).toFixed(1) + ',' + Y(v).toFixed(1)).filter(Boolean).join(' ');
    return '<polyline points="' + seg + '" fill="none" stroke="' + color + '" stroke-width="2"' + (dash ? ' stroke-dasharray="6 4"' : '') + '/>';
  }};
  svg += line(mov, '#1a3e8f', false) + line(five, '#c8960c', true);
  pts.forEach(p => {{
    if (p.v == null) return;
    svg += '<circle cx="' + X(p.i).toFixed(1) + '" cy="' + Y(p.v).toFixed(1) + '" r="3.6" fill="' + (p.res === 'W' ? '#2e7d32' : '#c62828') + '" opacity="0.85"><title>' + p.d + ' vs ' + p.opp + ': ' + p.v + '</title></circle>';
  }});
  svg += '</svg>';
  document.getElementById('chartbox').innerHTML = svg;
}}
window.addEventListener('DOMContentLoaded', drawChart);
</script>
</body></html>"""

out = Path("player_page_mockup_noah_cotton.html")
out.write_text(html)
print(f"Saved: {out} ({out.stat().st_size // 1024} KB)")
