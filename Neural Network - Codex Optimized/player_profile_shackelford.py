#!/usr/bin/env python3
"""One-page player scouting profile (report style) — Andrew Shackelford, LA Pierce.
Fuses our pipeline box/advanced metrics + league ranks (589 qualified players)
with the Synergy play-type / shot-type / drive data. reportlab, letter, 1 page."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)
from reportlab.lib.styles import ParagraphStyle

BLUE = colors.HexColor('#003087'); GOLD = colors.HexColor('#C4922A')
DARK = colors.HexColor('#1a1a2e'); MID = colors.HexColor('#555577')
LGRAY = colors.HexColor('#f2f3f7'); MGRAY = colors.HexColor('#dde0ea')
GREEN_BG = colors.HexColor('#d4edda'); RED_BG = colors.HexColor('#f8d7da')
GREEN_TXT = colors.HexColor('#1a5c30'); RED_TXT = colors.HexColor('#7b1b1b')
TH_BG = colors.HexColor('#1a3a6e'); WHITE = colors.white
NEU = colors.HexColor('#5b6472')

OUT = "Andrew_Shackelford_LA_Pierce_profile.pdf"


def S(sz, bold=False, color=DARK, align=TA_LEFT, lead=None, ital=False):
    fn = ('Helvetica-BoldOblique' if bold and ital else 'Helvetica-Bold' if bold
          else 'Helvetica-Oblique' if ital else 'Helvetica')
    return ParagraphStyle('s', fontName=fn, fontSize=sz, textColor=color,
                          alignment=align, leading=lead or sz * 1.25)


def hdr(t):
    return [Spacer(1, 2), Paragraph(t.upper(), S(10.5, True, BLUE)),
            HRFlowable(width='100%', thickness=1.4, color=GOLD,
                       spaceBefore=1, spaceAfter=3)]


def rank_color(pct, inverse=False):
    p = 100 - pct if inverse else pct
    return GREEN_TXT if p >= 75 else RED_TXT if p <= 25 else NEU


def ordn(p):
    suf = 'th' if 10 <= p % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(p % 10, 'th')
    return f"{p}{suf}"


def build():
    doc = SimpleDocTemplate(OUT, pagesize=letter, topMargin=0.34 * inch,
                            bottomMargin=0.3 * inch, leftMargin=0.55 * inch,
                            rightMargin=0.55 * inch)
    E = []
    # ---- Header ----
    E.append(Paragraph("LA PIERCE BRAHMAS&nbsp;&nbsp;·&nbsp;&nbsp;#2", S(9, True, GOLD)))
    E.append(Paragraph("Andrew Shackelford", S(24, True, BLUE)))
    E.append(Paragraph("Freshman&nbsp;·&nbsp;6&#39;1&quot;&nbsp;·&nbsp;2025-26&nbsp;·&nbsp;20 G, 20.6 MPG",
                       S(9.5, False, MID)))
    E.append(Paragraph("<b>Synergy Archetype:</b>&nbsp;Slashing Wing&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
                       "<b>bball-index Archetype:</b>&nbsp;Slasher", S(9.5, True, GOLD)))
    E.append(Paragraph("<b>Identity:</b> An undersized (6&#39;1&quot;) but relentless rim-running, transition-and-cut "
                       "scorer and elite defensive disruptor — efficient as the focal point of a weak team "
                       "(LA Pierce net rating &minus;12.4). At 6&#39;1&quot; he takes 82% of his shots at the rim and "
                       "blocks shots in the 93rd percentile; he does not shoot from outside.",
                       S(9, False, DARK, lead=12.5)))

    # ---- Statline ----
    E += hdr("Statline (per game)")
    sl = [["PTS", "REB", "AST", "STL", "BLK", "FG%", "3P%", "FT%", "TS%"],
          ["14.6", "5.7", "1.6", "2.9", "1.0", "57.2", "25.0 (6-24)", "70.3", "61.9"]]
    t = Table(sl, colWidths=[0.78 * inch] * 9)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), TH_BG), ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'), ('TEXTCOLOR', (0, 1), (-1, 1), DARK),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('TOPPADDING', (0, 0), (-1, -1), 2.2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.2), ('GRID', (0, 0), (-1, -1), 0.4, MGRAY),
        ('ROWBACKGROUNDS', (0, 1), (-1, 1), [LGRAY])]))
    E.append(t)

    # ---- Advanced w/ league ranks ----
    E += hdr("Advanced metrics &amp; league rank (of 589 qualified CCC players, 200+ min)")
    adv = [  # label, value, rank str, pct, inverse(lower=better)
        ("Usage%", "30.9", "81/589", 86, False),
        ("True Shooting%", "61.9", "56/589", 91, False),
        ("eFG%", "58.8", "61/589", 90, False),
        ("FT Rate", "54.0", "75/589", 87, False),
        ("OREB%", "12.9", "87/589", 85, False),
        ("Steal%", "7.0", "15/589", 98, False),
        ("Block%", "5.3", "42/589", 93, False),
        ("Def Rtg", "87.4", "68/589", 89, True),
        ("Fouls Drawn/40", "7.2", "70/589", 88, False),
        ("AST%", "22.1", "144/589", 76, False),
        ("Turnover%", "22.5", "409/589", 31, True),
        ("Off Rtg", "107.6", "199/589", 66, False),
    ]
    rows = [["Metric", "Value", "Rank", "Pctile"] * 1]
    data = [["Metric", "Value", "Rank", "%ile", "", "Metric", "Value", "Rank", "%ile"]]
    half = (len(adv) + 1) // 2
    L, R = adv[:half], adv[half:]
    body = []
    for i in range(half):
        l = L[i]
        r = R[i] if i < len(R) else None
        row = [l[0], l[1], l[2], ordn(l[3])]
        row += ([r[0], r[1], r[2], ordn(r[3])] if r else ["", "", "", ""])
        body.append(row)
    tbl = [["Metric", "Val", "Rank", "%ile", "Metric", "Val", "Rank", "%ile"]] + \
          [r[:4] + r[4:] for r in body]
    at = Table(tbl, colWidths=[1.18 * inch, 0.5 * inch, 0.72 * inch, 0.5 * inch] * 2)
    st = [('BACKGROUND', (0, 0), (-1, 0), TH_BG), ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
          ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 7.4),
          ('ALIGN', (1, 0), (-1, -1), 'CENTER'), ('ALIGN', (0, 0), (0, -1), 'LEFT'),
          ('ALIGN', (4, 0), (4, -1), 'LEFT'),
          ('TOPPADDING', (0, 0), (-1, -1), 1.6), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.6),
          ('GRID', (0, 0), (-1, -1), 0.3, MGRAY), ('LINEAFTER', (3, 0), (3, -1), 1, GOLD),
          ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, LGRAY])]
    # color the %ile cells
    for i in range(half):
        l = L[i]
        st.append(('TEXTCOLOR', (3, i + 1), (3, i + 1), rank_color(l[3], l[4])))
        st.append(('FONTNAME', (3, i + 1), (3, i + 1), 'Helvetica-Bold'))
        if i < len(R):
            r = R[i]
            st.append(('TEXTCOLOR', (7, i + 1), (7, i + 1), rank_color(r[3], r[4])))
            st.append(('FONTNAME', (7, i + 1), (7, i + 1), 'Helvetica-Bold'))
    at.setStyle(TableStyle(st))
    E.append(at)

    # ---- Synergy offense + defense, side by side ----
    E += hdr("Synergy profile — offense (left) &amp; defense (right), 17 logged games")

    def mini(rows, green, red, cw):
        t = Table(rows, colWidths=cw)
        s = [('BACKGROUND', (0, 0), (-1, 0), TH_BG), ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
             ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 7),
             ('ALIGN', (1, 0), (1, -1), 'CENTER'), ('ALIGN', (2, 0), (2, -1), 'LEFT'),
             ('TOPPADDING', (0, 0), (-1, -1), 1.6), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.6),
             ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
             ('GRID', (0, 0), (-1, -1), 0.3, MGRAY),
             ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, LGRAY])]
        for r in green:
            s.append(('TEXTCOLOR', (2, r), (2, r), GREEN_TXT))
        for r in red:
            s.append(('TEXTCOLOR', (2, r), (2, r), RED_TXT))
        t.setStyle(TableStyle(s))
        return t

    off = [["Offense — play / shot", "PPP", "Rating"],
           ["Transition (34%)", "1.15", "Very Good (78)"],
           ["Cut (15%)", "1.39", "Excellent (90)"],
           ["P&R ball handler (5%)", "1.08", "Excellent (92)"],
           ["Putbacks (10%)", "0.96", "Average (34)"],
           ["Spot up (17%)", "0.67", "Below Avg (26)"],
           ["Isolation (2%)", "0.00", "— none"],
           ["At rim — 82% of FGA", "1.22", "Very Good (73)"],
           ["Catch & shoot", "0.46", "Poor (7)"]]
    dfn = [["Defense — allows", "Allow", "Rating"],
           ["Overall", "0.667", "Excellent (85)"],
           ["Spot-ups (62%)", "0.705", "Very Good (78)"],
           ["Catch & shoot", "28.6%", "Very Good (68)"],
           ["Dribble jumpers", "16.7%", "Excellent (95)"],
           ["Long threes", "24.4%", "Very Good (81)"],
           ["At rim", "41.7%", "Very Good (68)"],
           ["Post-ups", "1.333", "Vulnerable"]]
    off_t = mini(off, green=(1, 2, 3, 7), red=(5, 6, 8), cw=[1.75 * inch, 0.5 * inch, 1.35 * inch])
    def_t = mini(dfn, green=(1, 2, 3, 4, 5, 6), red=(7,), cw=[1.55 * inch, 0.62 * inch, 1.43 * inch])
    pair = Table([[off_t, def_t]], colWidths=[3.62 * inch, 3.62 * inch])
    pair.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                              ('LEFTPADDING', (0, 0), (-1, -1), 0),
                              ('RIGHTPADDING', (0, 0), (0, 0), 8),
                              ('RIGHTPADDING', (1, 0), (1, 0), 0)]))
    E.append(pair)

    # ---- Strengths / Weaknesses ----
    E += hdr("Strengths &amp; weaknesses")
    strengths = ("<b>Elite rim finisher &amp; cutter</b> — 61% at the rim (Very Good), "
                 "1.39 PPP on cuts (Excellent, 90th).<br/>"
                 "<b>Transition weapon</b> — 1.146 PPP, a third of his offense.<br/>"
                 "<b>Elite, versatile defender</b> — 0.667 PPP allowed (Excellent, 85th); 98th-pctile "
                 "steals AND 93rd-pctile blocks; smothers shooters (opp 29% FG, 24% on threes).<br/>"
                 "<b>Draws fouls &amp; crashes the glass</b> — 7.2 fouls drawn/40, 85th-pctile OREB%.")
    weaknesses = ("<b>Cannot shoot</b> — catch &amp; shoot Poor (7th pctile, 0.46 PPS); "
                  "6-of-24 from three; spot-up Below Average.<br/>"
                  "<b>No self-creation</b> — isolation 0.000 PPP on 5 poss.<br/>"
                  "<b>Strongly left-hand dominant</b> — 76% of drives go left (0.607 PPP) vs "
                  "right (0.286).<br/>"
                  "<b>Turnover-prone</b> — 22.5% TOV (31st pctile) at high usage.<br/>"
                  "<b>Can be posted up</b> — allows 1.333 PPP defending post-ups; undersized at 6&#39;1&quot;.")
    sw = Table([[Paragraph("STRENGTHS", S(8.5, True, GREEN_TXT)),
                 Paragraph("WEAKNESSES", S(8.5, True, RED_TXT))],
                [Paragraph(strengths, S(8, False, DARK, lead=11.5)),
                 Paragraph(weaknesses, S(8, False, DARK, lead=11.5))]],
               colWidths=[3.7 * inch, 3.7 * inch])
    sw.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), GREEN_BG), ('BACKGROUND', (1, 0), (1, -1), RED_BG),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3), ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8), ('BOX', (0, 0), (-1, -1), 0.5, MGRAY),
        ('LINEBETWEEN', (0, 0), (0, -1), 0.5, WHITE)]))
    E.append(sw)

    E.append(Spacer(1, 6))
    E.append(HRFlowable(width='100%', thickness=0.6, color=MGRAY, spaceAfter=3))
    E.append(Paragraph(
        "Box &amp; advanced metrics from the CCC pipeline (20 games); play-type / shot-type / drive "
        "data from Synergy (17 logged games). League percentiles among 589 players with 200+ minutes.",
        S(6.8, False, MID)))

    doc.build(E)
    print("Wrote", OUT)


if __name__ == "__main__":
    build()
