"""
Scouting Report v2 — extends the generic generator with a
"What Drives Them" efficiency-correlation cascade and a Synergy play-type
layer.

Design: this file does NOT fork the generator. It imports
generate_scouting_report, fixes its data path to THIS repo, and appends the
new section. If v2 is promoted to the main generator, fold the section in and
retire the per-team forks.

Usage:
    python3 generate_scouting_report_v2.py --team "Palomar"
    python3 generate_scouting_report_v2.py --team "Ventura" --out my.pdf

Section layout:
  Level 1  Four-factor correlations vs game efficiency (offense + defense),
           with significance gating (|r| >= 2/sqrt(n) to be non-noise).
  Level 2  Drill-down for the dominant offensive and defensive lever:
           above/below-median W-L splits plus lever-specific micro stats
           (shot profile for eFG%, glass personnel for OR%, etc.).
  Level 3  Synergy play-type tables when
           internal_data/synergy_team_<slug>_<season>.json exists for the
           scouted team; degrades to a one-line note when not scraped yet.
"""

import argparse
import json
import math
import os
import re
import statistics
from pathlib import Path

import generate_scouting_report as base
from generate_scouting_report import (
    S, HR, section, ScoutingData, ReportBuilder,
    BLUE, GOLD, DARK, MID, LGRAY, MGRAY, GREEN_BG, RED_BG, YELLOW_BG,
    GREEN_TXT, RED_TXT, TH_BG, ALT, WHITE, BLACK,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)

# v2 reads from THIS repo, not the original copy.
REPO = str(Path(__file__).resolve().parent)
base.BASE = REPO

SEASON_TAG = "2025_26"

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


def synergy_path(team):
    slug = re.sub(r"[^a-z0-9]+", "_", team.lower()).strip("_")
    return Path(REPO) / "internal_data" / f"synergy_team_{slug}_{SEASON_TAG}.json"


def enriched_game_ratings(team):
    """Per-game ratings WITH four factors.

    advanced_analytics.json only stores basic per-game fields; the four
    factors are enriched inside the leaderboard's load_teams(). Reading the
    leaderboard cache guarantees the report's correlations match the Game
    Plan view exactly.
    """
    from generate_leaderboard import _cached_json, load_teams
    try:
        teams = _cached_json("2526_teams", load_teams)
    except Exception:
        teams = load_teams()
    t = next((x for x in teams if x.get("team") == team), None)
    return (t or {}).get("game_ratings", [])


class CorrelationCascade:
    """Computes Levels 1-2 from a team's per-game four factors."""

    def __init__(self, d: ScoutingData):
        self.d = d
        self.games = [g for g in enriched_game_ratings(d.team)
                      if g.get("o_efg") is not None]
        self.n = len(self.games)
        # |r| below this is statistically indistinguishable from noise
        self.r_crit = 2.0 / math.sqrt(self.n) if self.n >= 3 else 1.0

        self.off = self._correlate("ortg", ["o_efg", "o_tov", "o_or", "o_ftr"])
        self.dfn = self._correlate("drtg", ["d_efg", "d_tov", "d_or", "d_ftr"])
        self.off_sub = self._correlate("ortg", ["o_2p", "o_3p"])
        self.dfn_sub = self._correlate("drtg", ["d_2p", "d_3p"])

    def _correlate(self, eff_key, keys):
        out = []
        for k in keys:
            pairs = [(g[k], g[eff_key]) for g in self.games
                     if g.get(k) is not None and g.get(eff_key) is not None]
            r = pearson([p[0] for p in pairs], [p[1] for p in pairs])
            out.append((k, r))
        out.sort(key=lambda kv: -(abs(kv[1]) if kv[1] is not None else 0))
        return out

    def strength(self, r):
        if r is None:
            return "—"
        a = abs(r)
        if a < self.r_crit:
            return "Noise"
        if a >= 0.60:
            return "Strong"
        if a >= 0.45:
            return "Moderate"
        return "Mild"

    def top_lever(self, side):
        ranked = self.off if side == "off" else self.dfn
        for k, r in ranked:
            if r is not None and abs(r) >= self.r_crit:
                return k, r
        return ranked[0] if ranked else (None, None)

    def median_split(self, key, eff_key):
        """W-L record and avg net rating above/below the factor's median."""
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


class ReportBuilderV2(ReportBuilder):

    # ── Level 1: correlation tables ──────────────────────────────────────
    def _corr_table(self, title, ranked, subs, casc, eff_label):
        rows = [[title, "r", "Read"]]
        spans = []
        for k, r in ranked:
            lab = FACTOR_LABELS[k]
            rv = "—" if r is None else f"{r * 100:+.0f}"
            rows.append([lab, rv, casc.strength(r)])
        rows.append([f"{eff_label} sub-stats", "", ""])
        spans.append(len(rows) - 1)
        for k, r in subs:
            rv = "—" if r is None else f"{r * 100:+.0f}"
            rows.append([SUB_LABELS[k], rv, casc.strength(r)])

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
        ]
        for sr in spans:
            style += [("BACKGROUND", (0, sr), (-1, sr), LGRAY),
                      ("FONTNAME", (0, sr), (-1, sr), "Helvetica-Oblique"),
                      ("SPAN", (0, sr), (-1, sr))]
        # color by strength
        for i, row in enumerate(rows):
            if i == 0 or i in spans:
                continue
            tag = row[2]
            if tag == "Strong":
                style.append(("BACKGROUND", (1, i), (2, i), GREEN_BG))
            elif tag == "Moderate":
                style.append(("BACKGROUND", (1, i), (2, i), YELLOW_BG))
            elif tag == "Noise":
                style.append(("TEXTCOLOR", (0, i), (2, i), MGRAY))
        t.setStyle(TableStyle(style))
        return t

    # ── Level 2: lever drill-down ────────────────────────────────────────
    def _lever_block(self, side, key, r, casc):
        d = self.d
        lab = FACTOR_LABELS.get(key, key)
        eff_key = "ortg" if side == "off" else "drtg"
        prefix = "Offensive" if side == "off" else "Defensive"
        flow = [Paragraph(f"<b>{prefix} lever: {lab}</b> "
                          f"(r = {r * 100:+.0f} vs {'ORtg' if side == 'off' else 'DRtg'})", S(9.5, bold=True, color=BLUE))]

        sp = casc.median_split(key, eff_key)
        if sp:
            flow.append(Paragraph(
                f"{lab} ≥ {sp['median']:.1f} (median): <b>{sp['hi_rec']}</b>, "
                f"net {sp['hi_net']:+.1f} &nbsp;·&nbsp; below: <b>{sp['lo_rec']}</b>, "
                f"net {sp['lo_net']:+.1f}", S(8.5)))

        tot = d.team_sum.get("totals", {})
        if side == "off" and key == "o_efg" and tot.get("FGA"):
            fga, tpa, fta = tot["FGA"], tot.get("3PA", 0), tot.get("FTA", 0)
            fgm, tpm = tot.get("FGM", 0), tot.get("3PM", 0)
            att = fga + fta
            twop = 100 * (fgm - tpm) / (fga - tpa) if fga > tpa else 0
            threep = 100 * tpm / tpa if tpa else 0
            flow.append(Paragraph(
                f"Shot profile: {100 * (fga - tpa) / att:.0f}% 2PA · {100 * tpa / att:.0f}% 3PA · "
                f"{100 * fta / att:.0f}% FTA — shooting {twop:.1f}% on 2s, {threep:.1f}% on 3s"
                f"{self._sub_corr_text(casc.off_sub)}", S(8.5)))
        elif key in ("o_or", "d_or"):
            flow.append(Paragraph(self._glass_personnel(side), S(8.5)))
        elif key in ("o_ftr", "d_ftr"):
            flow.append(Paragraph(self._foul_personnel(side), S(8.5)))
        elif side == "def" and key == "d_efg":
            flow.append(Paragraph(
                f"Opponent shot-making splits{self._sub_corr_text(casc.dfn_sub)}", S(8.5)))
        return flow

    def _sub_corr_text(self, subs):
        bits = []
        for k, r in subs:
            if r is not None:
                bits.append(f"{SUB_LABELS[k]} r {r * 100:+.0f}")
        return (" — sub-correlations: " + ", ".join(bits)) if bits else ""

    def _glass_personnel(self, side):
        key = "oreb_pct" if side == "off" else "dreb_pct"
        players = self.d.adv_json.get("players", [])
        ranked = sorted((p for p in players if isinstance(p.get(key), (int, float))),
                        key=lambda p: -p[key])[:3]
        names = ", ".join(f"{p['name']} ({p[key]:.1f}%)" for p in ranked)
        return f"Glass personnel ({'OR%' if side == 'off' else 'DR%'}): {names}" if names else ""

    def _foul_personnel(self, side):
        players = self.d.adv_json.get("players", [])
        key = "fd_per_40" if side == "off" else "fc_per_40"
        ranked = sorted((p for p in players if isinstance(p.get(key), (int, float))),
                        key=lambda p: -p[key])[:3]
        what = "draws fouls" if side == "off" else "commits fouls"
        names = ", ".join(f"{p['name']} ({p[key]:.1f}/40)" for p in ranked)
        return f"Who {what}: {names}" if names else ""

    # ── Level 3: Synergy play types ──────────────────────────────────────
    def _synergy_tables(self):
        path = synergy_path(self.d.team)
        if not path.exists():
            return [Paragraph(
                f"<i>Synergy play-type data not scraped for {self.d.team} yet — "
                f"run scrape_synergy_team_overall.py to enable shot-location / "
                f"play-type granularity here.</i>", S(8, color=MID))]
        try:
            syn = json.load(open(path))
        except Exception:
            return [Paragraph("<i>Synergy file unreadable.</i>", S(8, color=MID))]

        flows = []
        for side_key, side_label in (("offense", "Offense"), ("defense", "Defense")):
            plays = (syn.get(side_key) or {}).get("play_types") or []
            plays = sorted(plays, key=lambda p: -(p.get("poss") or 0))[:6]
            if not plays:
                continue
            rows = [[f"Synergy — {side_label}", "%Time", "PPP", "Rating", "eFG%", "TO%"]]
            for p in plays:
                rows.append([
                    p.get("play_type", ""), f"{p.get('pct_time', 0):.1f}",
                    f"{p.get('ppp', 0):.3f}", p.get("ppp_rating", ""),
                    f"{p.get('efg_pct', 0):.1f}", f"{p.get('to_pct', 0):.1f}",
                ])
            t = Table(rows, colWidths=[1.5 * inch, 0.6 * inch, 0.6 * inch, 0.95 * inch, 0.6 * inch, 0.6 * inch])
            style = [
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.4, MGRAY),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
            for i, p in enumerate(plays, start=1):
                rating = (p.get("ppp_rating") or "").lower()
                if "excellent" in rating or "very good" in rating:
                    style.append(("BACKGROUND", (3, i), (3, i), GREEN_BG))
                elif "poor" in rating or "below" in rating:
                    style.append(("BACKGROUND", (3, i), (3, i), RED_BG))
            t.setStyle(TableStyle(style))
            flows += [t, Spacer(1, 6)]
        return flows

    # ── The page ─────────────────────────────────────────────────────────
    def page_what_drives_them(self):
        d = self.d
        casc = CorrelationCascade(d)
        flow = section("WHAT DRIVES THEM",
                       f"Per-game four factors vs. game efficiency · {casc.n} games · "
                       f"|r| < {casc.r_crit * 100:.0f} reads as noise at this sample size")

        ok, orr = casc.top_lever("off")
        dk, drr = casc.top_lever("def")
        verdict = []
        if ok and orr is not None and abs(orr) >= casc.r_crit:
            verdict.append(f"Their offense swings on <b>{FACTOR_LABELS[ok]}</b> (r {orr * 100:+.0f}).")
        else:
            verdict.append("No single offensive factor clears the noise floor — efficiency is multi-causal.")
        if dk and drr is not None and abs(drr) >= casc.r_crit:
            verdict.append(f"Defensively, games turn on <b>{FACTOR_LABELS[dk]}</b> (r {drr * 100:+.0f}).")
        flow.append(Paragraph(" ".join(verdict), S(9.5)))
        flow.append(Spacer(1, 8))

        corr_tables = Table(
            [[self._corr_table("Offense vs ORtg", casc.off, casc.off_sub, casc, "Shooting"),
              self._corr_table("Defense vs DRtg", casc.dfn, casc.dfn_sub, casc, "Shooting")]],
            colWidths=[3.0 * inch, 3.0 * inch])
        corr_tables.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        flow += [corr_tables, Spacer(1, 10)]

        if ok and orr is not None:
            flow += self._lever_block("off", ok, orr, casc)
            flow.append(Spacer(1, 6))
        if dk and drr is not None:
            flow += self._lever_block("def", dk, drr, casc)
            flow.append(Spacer(1, 10))

        flow.append(HR())
        flow += self._synergy_tables()
        return [KeepTogether(flow[:3])] + flow[3:]


def main():
    parser = argparse.ArgumentParser(description="Scouting report v2 (correlation cascade + Synergy)")
    parser.add_argument("--team", required=True)
    parser.add_argument("--conference")
    parser.add_argument("--out")
    args = parser.parse_args()

    conference = args.conference
    if not conference:
        for conf, team in base.list_teams():
            if team.lower() == args.team.lower():
                conference, args.team = conf, team
                break
        if not conference:
            print(f'Team "{args.team}" not found.')
            return

    print(f"Generating v2 scouting report: {args.team} ({conference})...")
    d = ScoutingData(args.team, conference)
    rb = ReportBuilderV2(d)

    safe = re.sub(r"[^a-z0-9]+", "_", args.team.lower()).strip("_")
    out_path = args.out or f"{REPO}/{safe}_scouting_report_v2_{SEASON_TAG}.pdf"
    doc = SimpleDocTemplate(out_path, pagesize=letter,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.72 * inch, bottomMargin=0.55 * inch)
    story = (rb.page_cover()
             + rb.page_analytics()
             + rb.page_what_drives_them()
             + rb.page_players()
             + rb.page_situations()
             + rb.page_scouting_guide())
    doc.build(story, onFirstPage=rb.on_page, onLaterPages=rb.on_page)
    print(f"Saved: {out_path} ({os.path.getsize(out_path) // 1024} KB)")


if __name__ == "__main__":
    main()
