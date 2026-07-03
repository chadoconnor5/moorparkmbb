"""
Moorpark Scouting Report v2 — the detailed Moorpark report
(generate_moorpark_scouting_report.py) plus a "What Drives Them"
efficiency-correlation page.

Design: no code fork. The detailed script loads its data at import time with
a hardcoded BASE pointing at the original repo, so this file loads its source
with BASE rewritten to THIS repo and executes it as a module. Every page of
the original report is reused as-is; one new page is inserted after
Analytics, and the Synergy tie-in references the report's existing Synergy
page instead of duplicating it.

Usage:
    python3 generate_moorpark_scouting_report_v2.py
"""

import math
import os
import statistics
import types
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

REPO = str(Path(__file__).resolve().parent)
SEASON_TAG = "2025_26"

# ── Load the detailed report module with BASE repointed to this repo ────────
_src_path = Path(REPO) / "generate_moorpark_scouting_report.py"
_src = _src_path.read_text()
_old_base = "BASE = '/Users/chadoconnor/Neural Network'"
assert _old_base in _src, "BASE line moved in generate_moorpark_scouting_report.py — update v2 loader"
_src = _src.replace(_old_base, f"BASE = {REPO!r}", 1)
mp = types.ModuleType("mp_report_base")
mp.__file__ = str(_src_path)
exec(compile(_src, str(_src_path), "exec"), mp.__dict__)

S, HR, section = mp.S, mp.HR, mp.section
BLUE, MID, WHITE, MGRAY = mp.BLUE, mp.MID, mp.WHITE, mp.MGRAY
TH_BG, LGRAY, GREEN_BG, YELLOW_BG = mp.TH_BG, mp.LGRAY, mp.GREEN_BG, mp.YELLOW_BG

FACTOR_LABELS = {
    "o_efg": "eFG%", "o_tov": "TO%", "o_or": "OR%", "o_ftr": "FT Rate",
    "d_efg": "eFG%", "d_tov": "TO%", "d_or": "OR%", "d_ftr": "FT Rate",
}
SUB_LABELS = {"o_2p": "2P%", "o_3p": "3P%", "d_2p": "2P%", "d_3p": "3P%"}


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def enriched_game_ratings(team="Moorpark"):
    """Game ratings WITH per-game four factors, from the leaderboard cache —
    the same enriched data the site's Game Plan view correlates."""
    from generate_leaderboard import _cached_json, load_teams
    try:
        teams = _cached_json("2526_teams", load_teams)
    except Exception:
        teams = load_teams()
    t = next((x for x in teams if x.get("team") == team), None)
    return (t or {}).get("game_ratings", [])


class Cascade:
    def __init__(self, games):
        self.games = [g for g in games if g.get("o_efg") is not None]
        self.n = len(self.games)
        self.r_crit = 2.0 / math.sqrt(self.n) if self.n >= 3 else 1.0
        self.off = self._corr("ortg", ["o_efg", "o_tov", "o_or", "o_ftr"])
        self.dfn = self._corr("drtg", ["d_efg", "d_tov", "d_or", "d_ftr"])
        self.off_sub = self._corr("ortg", ["o_2p", "o_3p"])
        self.dfn_sub = self._corr("drtg", ["d_2p", "d_3p"])

    def _corr(self, eff, keys):
        out = []
        for k in keys:
            pairs = [(g[k], g[eff]) for g in self.games
                     if g.get(k) is not None and g.get(eff) is not None]
            out.append((k, pearson([p[0] for p in pairs], [p[1] for p in pairs])))
        out.sort(key=lambda kv: -(abs(kv[1]) if kv[1] is not None else 0))
        return out

    def strength(self, r):
        if r is None:
            return "—"
        a = abs(r)
        if a < self.r_crit:
            return "Noise"
        return "Strong" if a >= 0.60 else ("Moderate" if a >= 0.45 else "Mild")

    def top_lever(self, side):
        for k, r in (self.off if side == "off" else self.dfn):
            if r is not None and abs(r) >= self.r_crit:
                return k, r
        ranked = self.off if side == "off" else self.dfn
        return ranked[0] if ranked else (None, None)

    def median_split(self, key):
        vals = [g[key] for g in self.games if g.get(key) is not None]
        if len(vals) < 4:
            return None
        med = statistics.median(vals)
        hi = [g for g in self.games if g.get(key) is not None and g[key] >= med]
        lo = [g for g in self.games if g.get(key) is not None and g[key] < med]

        def fmt(pool):
            w = sum(1 for g in pool if g.get("result") == "W")
            l = sum(1 for g in pool if g.get("result") == "L")
            net = (sum(g["ortg"] - g["drtg"] for g in pool) / len(pool)) if pool else 0.0
            return f"{w}-{l}", net

        (hr, hn), (lr, ln) = fmt(hi), fmt(lo)
        return {"median": med, "hi_rec": hr, "hi_net": hn, "lo_rec": lr, "lo_net": ln}


def _corr_table(title, ranked, subs, casc):
    rows = [[title, "r", "Read"]]
    for k, r in ranked:
        rows.append([FACTOR_LABELS[k], "—" if r is None else f"{r * 100:+.0f}", casc.strength(r)])
    sub_hdr = len(rows)
    rows.append(["Shooting sub-stats", "", ""])
    for k, r in subs:
        rows.append([SUB_LABELS[k], "—" if r is None else f"{r * 100:+.0f}", casc.strength(r)])
    t = Table(rows, colWidths=[1.25 * inch, 0.55 * inch, 0.85 * inch])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), TH_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, MGRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, sub_hdr), (-1, sub_hdr), LGRAY),
        ("FONTNAME", (0, sub_hdr), (-1, sub_hdr), "Helvetica-Oblique"),
        ("SPAN", (0, sub_hdr), (-1, sub_hdr)),
    ]
    for i, row in enumerate(rows):
        if i in (0, sub_hdr):
            continue
        if row[2] == "Strong":
            style.append(("BACKGROUND", (1, i), (2, i), GREEN_BG))
        elif row[2] == "Moderate":
            style.append(("BACKGROUND", (1, i), (2, i), YELLOW_BG))
        elif row[2] == "Noise":
            style.append(("TEXTCOLOR", (0, i), (2, i), MGRAY))
    t.setStyle(TableStyle(style))
    return t


def _sub_corr_text(subs):
    bits = [f"{SUB_LABELS[k]} r {r * 100:+.0f}" for k, r in subs if r is not None]
    return (" — sub-correlations: " + ", ".join(bits)) if bits else ""


def _lever_flow(side, key, r, casc):
    lab = FACTOR_LABELS.get(key, key)
    prefix = "Offensive" if side == "off" else "Defensive"
    eff_lab = "ORtg" if side == "off" else "DRtg"
    flow = [Paragraph(f"<b>{prefix} lever: {lab}</b> (r = {r * 100:+.0f} vs {eff_lab})",
                      S(9.5, True, BLUE))]
    sp = casc.median_split(key)
    if sp:
        flow.append(Paragraph(
            f"{lab} ≥ {sp['median']:.1f} (median): <b>{sp['hi_rec']}</b>, net {sp['hi_net']:+.1f}"
            f" &nbsp;·&nbsp; below: <b>{sp['lo_rec']}</b>, net {sp['lo_net']:+.1f}", S(8.5)))

    tot = mp.team_sum.get("totals", {})
    if side == "off" and key == "o_efg" and tot.get("FGA"):
        fga, tpa, fta = tot["FGA"], tot.get("3PA", 0), tot.get("FTA", 0)
        fgm, tpm = tot.get("FGM", 0), tot.get("3PM", 0)
        att = fga + fta
        twop = 100 * (fgm - tpm) / (fga - tpa) if fga > tpa else 0
        threep = 100 * tpm / tpa if tpa else 0
        flow.append(Paragraph(
            f"Shot profile: {100 * (fga - tpa) / att:.0f}% 2PA · {100 * tpa / att:.0f}% 3PA · "
            f"{100 * fta / att:.0f}% FTA — shooting {twop:.1f}% on 2s, {threep:.1f}% on 3s"
            f"{_sub_corr_text(casc.off_sub)}", S(8.5)))
        # Synergy tie-in: which play types carry the shot-making
        plays = (mp.synergy_team.get("offense") or {}).get("play_types") or []
        top = sorted(plays, key=lambda p: -(p.get("poss") or 0))[:3]
        if top:
            bits = ", ".join(f"{p['play_type']} ({p['pct_time']:.0f}% of poss, {p['ppp']:.2f} PPP, {p.get('ppp_rating', '')})"
                             for p in top)
            flow.append(Paragraph(
                f"Where the shot-making lives: {bits} — full play-type breakdown on the Synergy page.",
                S(8.5, color=MID)))
    elif key in ("o_or", "d_or"):
        akey = "oreb_pct" if key == "o_or" else "dreb_pct"
        players = mp.adv_json.get("players", [])
        ranked = sorted((p for p in players if isinstance(p.get(akey), (int, float))),
                        key=lambda p: -p[akey])[:3]
        if ranked:
            names = ", ".join(f"{p['name']} ({p[akey]:.1f}%)" for p in ranked)
            flow.append(Paragraph(f"Glass personnel: {names}", S(8.5)))
    elif key in ("o_ftr", "d_ftr"):
        akey = "fd_per_40" if key == "o_ftr" else "fc_per_40"
        players = mp.adv_json.get("players", [])
        ranked = sorted((p for p in players if isinstance(p.get(akey), (int, float))),
                        key=lambda p: -p[akey])[:3]
        if ranked:
            what = "draws fouls" if key == "o_ftr" else "commits fouls"
            names = ", ".join(f"{p['name']} ({p[akey]:.1f}/40)" for p in ranked)
            flow.append(Paragraph(f"Who {what}: {names}", S(8.5)))
    elif side == "def" and key == "d_efg":
        flow.append(Paragraph(
            f"Opponent shot-making splits{_sub_corr_text(casc.dfn_sub)} — pair with the "
            f"defensive play-type table on the Synergy page.", S(8.5)))
    return flow


def page_what_drives_them():
    casc = Cascade(enriched_game_ratings("Moorpark"))
    flow = section("WHAT DRIVES THE RAIDERS",
                   f"Per-game four factors vs. game efficiency · {casc.n} games · "
                   f"|r| < {casc.r_crit * 100:.0f} reads as noise at this sample size")

    ok, orr = casc.top_lever("off")
    dk, drr = casc.top_lever("def")
    verdict = []
    if ok and orr is not None and abs(orr) >= casc.r_crit:
        verdict.append(f"The offense swings on <b>{FACTOR_LABELS[ok]}</b> (r {orr * 100:+.0f}).")
    else:
        verdict.append("No single offensive factor clears the noise floor — efficiency is multi-causal.")
    if dk and drr is not None and abs(drr) >= casc.r_crit:
        verdict.append(f"Defensively, games turn on <b>{FACTOR_LABELS[dk]}</b> (r {drr * 100:+.0f}).")
    flow.append(Paragraph(" ".join(verdict), S(9.5)))
    flow.append(Spacer(1, 8))

    pair = Table([[_corr_table("Offense vs ORtg", casc.off, casc.off_sub, casc),
                   _corr_table("Defense vs DRtg", casc.dfn, casc.dfn_sub, casc)]],
                 colWidths=[3.0 * inch, 3.0 * inch])
    pair.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flow += [pair, Spacer(1, 10)]

    if ok and orr is not None:
        flow += _lever_flow("off", ok, orr, casc)
        flow.append(Spacer(1, 6))
    if dk and drr is not None:
        flow += _lever_flow("def", dk, drr, casc)
    flow.append(HR())
    return flow


def main():
    out = f"{REPO}/moorpark_scouting_report_v2_{SEASON_TAG}.pdf"
    doc = SimpleDocTemplate(out, pagesize=letter,
                            topMargin=0.65 * inch, bottomMargin=0.5 * inch,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    story = []
    story += mp.page_cover()
    story += mp.page_analytics()
    story += page_what_drives_them()
    story += mp.page_synergy_team()
    story += mp.page_big_games()
    story += mp.page_game_log()
    story += mp.page_rotation()
    story += mp.page_player_profiles()
    story += mp.page_position_dependence()
    story += mp.page_scouting_guide()
    doc.build(story, onFirstPage=mp.on_page, onLaterPages=mp.on_page)
    print(f"Saved: {out} ({os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    main()
