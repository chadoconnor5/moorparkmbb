#!/usr/bin/env python3
"""Add the bonus overtime timeouts to the TIMEOUTS panel on the overtime tracker.

    python tools/ot_timeouts_box.py Moorpark_Overtime_Possession_Tracker.pdf

The sheet's timeout panel carries a regulation allotment — three FULL and four 30 SEC per
team — and on the overtime sheet those are still worth having, because unused ones carry
into the extra periods and the whole point of the panel is knowing what is left. What it
lacks is the ones overtime GRANTS: under NCAA men's rules each team gets one additional
30-second timeout per extra period, granted as that period begins.

So the regulation rows are left exactly as they are and a second block is added beneath
them — MOORPARK and OPPONENT again, three boxes each, numbered 1-2-3 for OT1, OT2 and OT3,
under a caption saying what they are. The panel border is redrawn taller to hold it.

The panel is found by its GEOMETRY, not its text: the relabelled sheet still carries the
original FIRST HALF wording underneath the covers this repo's relabeller paints over it, so
anything keying on words reads an interleaving of both. Two rows of seven ten-point boxes
inside one unfilled rectangle is the timeouts panel and nothing else on the page is.
"""

import argparse, io, pathlib
from collections import defaultdict
import pdfplumber
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

H = letter[1]

# Measured off the sheet, so the new block is set in its own hand.
BORDER  = (0.1333, 0.1333, 0.1333)
TEAM    = (0.2157, 0.2549, 0.3176)   # MOORPARK / OPPONENT
SUB     = (0.2941, 0.3333, 0.3882)   # FULL / 30 SEC
NUMERAL = (0.6039, 0.6392, 0.6863)   # the little digits in the foul grid
TICK    = 10.5                        # a tick box, square
PITCH   = 14.3                        # box to box


def find_panel(path):
    """The timeouts panel: the one unfilled rectangle holding two rows of seven ticks."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        ticks = [r for r in page.rects
                 if abs(r['width'] - TICK) < 1.5 and abs(r['height'] - TICK) < 1.5 and not r.get('fill')]
        panels = [r for r in page.rects if not r.get('fill') and r['width'] > 120 and r['height'] > 30]
        best = None
        for p in panels:
            inside = [t for t in ticks if p['x0'] <= t['x0'] and t['x1'] <= p['x1']
                      and p['top'] <= t['top'] and t['bottom'] <= p['bottom']]
            rows = defaultdict(list)
            for t in inside:
                rows[round(t['top'], 0)].append(t)
            if len(inside) >= 12 and len(rows) == 2 and all(len(v) >= 6 for v in rows.values()):
                if best is None or p['top'] < best[0]['top']:
                    best = (p, rows)
        if not best:
            raise SystemExit('could not find a timeouts panel (two rows of seven tick boxes)')
        panel, rows = best
        ordered = [sorted(v, key=lambda t: t['x0']) for _, v in sorted(rows.items())]
        return {'x0': panel['x0'], 'x1': panel['x1'], 'top': panel['top'], 'bottom': panel['bottom'],
                'rows': ordered,
                'label_x': panel['x0'] + 59.8,      # where FULL / 30 SEC sit
                'team_x': panel['x0'] + 6,
                'first_tick_x': ordered[0][0]['x0'],
                'row_gap': ordered[1][0]['top'] - ordered[0][0]['top']}


def add_bonus(src, out, per_team=3, caption=None):
    g = find_panel(src)
    caption = caption or 'BONUS — ONE 30-SEC TIMEOUT GRANTED PER EXTRA PERIOD'
    last_bottom = g['rows'][1][0]['bottom']

    divider = last_bottom + 4.5
    cap_top = divider + 3.5
    row1 = cap_top + 8.5                       # MOORPARK bonus ticks
    row2 = row1 + g['row_gap']                 # OPPONENT bonus ticks
    new_bottom = row2 + TICK + 5

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)

    # The old bottom rule has to go before a taller border can be drawn over it.
    c.setFillColorRGB(1, 1, 1)
    c.rect(g['x0'] - 1, H - (new_bottom + 2), (g['x1'] - g['x0']) + 2,
           (new_bottom + 2) - (g['bottom'] - 1.2), stroke=0, fill=1)

    c.setStrokeColorRGB(*NUMERAL)
    c.setLineWidth(0.4)
    c.line(g['team_x'], H - divider, g['x1'] - 6, H - divider)

    c.setFillColorRGB(*SUB)
    c.setFont('Helvetica-Bold', 4.8)
    c.drawString(g['team_x'], H - cap_top - 4.4, caption)

    c.setLineWidth(0.7)
    for top, team in ((row1, 'MOORPARK'), (row2, 'OPPONENT')):
        c.setFillColorRGB(*TEAM)
        c.setFont('Helvetica-Bold', 6.2)
        c.drawString(g['team_x'], H - top - TICK + 3.4, team)
        c.setFillColorRGB(*SUB)
        c.setFont('Helvetica-Bold', 5.6)
        c.drawString(g['label_x'], H - top - TICK + 3.4, 'OT')
        for i in range(per_team):
            x = g['first_tick_x'] + i * PITCH
            c.setStrokeColorRGB(*BORDER)
            c.rect(x, H - top - TICK, TICK, TICK, stroke=1, fill=0)
            # Numbered the way the foul grid numbers its boxes, so OT1/2/3 are tickable
            # without a second label row.
            c.setFillColorRGB(*NUMERAL)
            c.setFont('Helvetica', 4.4)
            c.drawString(x + 1.6, H - top - 5.2, str(i + 1))
            c.setFillColorRGB(*SUB)

    c.setStrokeColorRGB(*BORDER)
    c.setLineWidth(0.8)
    c.rect(g['x0'], H - new_bottom, g['x1'] - g['x0'], new_bottom - g['top'], stroke=1, fill=0)
    c.showPage()
    c.save()
    buf.seek(0)

    reader = PdfReader(src)
    page = reader.pages[0]
    page.merge_page(PdfReader(buf).pages[0])
    w = PdfWriter()
    w.add_page(page)
    w.add_metadata({'/Title': 'Moorpark College — Possession Tracking (Overtime)',
                    '/Author': "Moorpark College Men's Basketball"})
    with open(out, 'wb') as fh:
        w.write(fh)
    return {'panel': (round(g['x0'], 1), round(g['top'], 1), round(g['x1'], 1), round(new_bottom, 1)),
            'grew_by': round(new_bottom - g['bottom'], 1), 'per_team': per_team}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('--out')
    ap.add_argument('--per-team', type=int, default=3)
    a = ap.parse_args()
    out = pathlib.Path(a.out or a.src)
    info = add_bonus(a.src, out, a.per_team)
    print(f"  bonus row: {info['per_team']} per team, panel now {info['panel']}, "
          f"taller by {info['grew_by']}pt")
    print('wrote', out)


if __name__ == '__main__':
    main()
