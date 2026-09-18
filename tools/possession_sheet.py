#!/usr/bin/env python3
"""Printable possession-log sheets for the second half and overtime.

    python tools/possession_sheet.py                      # possession_log_sheets.pdf
    python tools/possession_sheet.py --out foo.pdf        # somewhere else
    python tools/possession_sheet.py --roster-from FILE   # names from a pt_data.json export

The paper counterpart to `Neural Network - Codex Optimized/defensive_logger.html`. Every
option printed on a row is one the logger already has, spelled the same way and in the same
order, so a sheet filled in at the scorer's table types straight in afterwards with nothing
to translate or remember. Change the taxonomy in one place and it has to change in both:

    shot     2PA / 3PA, Made / Missed / Blocked, PiP / SCP / PoT, Assisted
    foul     Shooting / Non-shooting / Technical, Bonus, FT made / attempted
    turnover Steal / Dead-ball / Charge / Off. foul / Shot clock / Other
    ending   Def Reb ends it, Opp OReb continues it, Deflection ends nothing

The `+` box at the left of each row is the logger's "+ same possession": tick it and the
row belongs to the possession above rather than opening a new one, which is how an offensive
rebound, an and-one, or a foul with no free throws gets recorded.

Rows are pre-numbered because a possession count that is written by hand is a possession
count that gets miscounted; the numbers on the page are the numbers in the app.
"""

import argparse, json, pathlib
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

W, H = letter
M = 28.8                      # 0.4in margins — as wide as a laser printer reliably prints
INK, GLYPH, RULE = 0, 0.42, 0.62   # black structure, mid-grey options to circle, light rules
ROW = 20                      # tall enough to write a number in at speed

ROSTER = ['Josh Castaniero', 'Matthew Wilson', 'Alex Bello', 'SoulJah Niles',
          'Mikey Duran-Morales', 'Eric Kubel', 'Quian Khawaja', 'Brenden Banks-Speed',
          'George Hees', 'Emmitt Claiborne', 'Sean Castro', 'CJ Temme', 'Axel Ostergard',
          'Jaylen Smith', 'Finn Ortiz', 'Jack Johnson', 'Ashton Carraway', 'Reese Widerburg']

# label, width. The widths are the taxonomy's, not the page's: the busiest group (a shot)
# gets the room it needs and the rest are packed around it.
COLS = [('#', 20), ('+', 15), ('CLOCK', 34), ('SCORE', 42), ('FIVE ON FLOOR', 58),
        ('SHOT', 130), ('FOUL', 92), ('TURNOVER', 74), ('END', 34), ('NOTES', 0)]
COLS[-1] = ('NOTES', (W - 2 * M) - sum(w for _, w in COLS[:-1]))


def xs():
    x, out = M, []
    for _, w in COLS:
        out.append((x, w))
        x += w
    return out


def _width(c, items, size, gap):
    return sum(c.stringWidth(i, 'Helvetica', size) for i in items) + gap * (len(items) - 1)


def opts(c, x, y, items, maxw=None, size=5.4, gap=3.4):
    """Options to circle, shrunk to fit their column rather than trusted to.

    Every group here is a taxonomy that will grow — a new turnover type, a new context
    flag — and the first thing a hand-tuned font size does when it does is run silently
    into the next column. So the size is measured down until it fits, and the only way to
    lose a group is to make its column too narrow to read, which is visible."""
    if maxw is not None:
        while size > 4.0 and _width(c, items, size, gap) > maxw:
            size -= 0.15
            gap = max(2.2, gap - 0.04)
    c.setFont('Helvetica', size)
    c.setFillGray(GLYPH)
    for it in items:
        c.setFillGray(0.8 if it == '|' else GLYPH)
        c.drawString(x, y, it)
        x += c.stringWidth(it, 'Helvetica', size) + gap
    c.setFillGray(INK)
    return x


def box(c, x, y, w, h, label=None, size=5.2):
    c.setLineWidth(0.4)
    c.setStrokeGray(0.45)
    c.rect(x, y, w, h)
    if label:
        c.setFont('Helvetica', size)
        c.setFillGray(GLYPH)
        c.drawString(x + w + 2, y + 1.5, label)
        c.setFillGray(INK)
    c.setStrokeGray(INK)


def header(c, period, page_note, roster, full=True, ot_select=False):
    """Returns the y the table may start at."""
    y = H - M

    c.setFillGray(INK)
    c.setFont('Helvetica-Bold', 13)
    title = "MOORPARK MEN'S BASKETBALL"
    c.drawString(M, y - 11, title)
    c.setFont('Helvetica', 8.5)
    c.setFillGray(0.35)
    c.drawString(M + c.stringWidth(title, 'Helvetica-Bold', 13) + 10, y - 11, 'POSSESSION LOG')
    c.setFillGray(INK)

    c.setFont('Helvetica-Bold', 12)
    c.drawRightString(W - M, y - 11, period)
    if ot_select:
        # A period that has to be written in is a period that gets left blank, and an
        # overtime sheet with no period on it is unfilable afterwards.
        items = ['OT1', '|', 'OT2', '|', 'OT3']
        w = _width(c, items, 8, 5)
        c.setFont('Helvetica', 6.2)
        c.setFillGray(0.4)
        c.drawRightString(W - M - w - 8, y - 22, 'CIRCLE THE PERIOD — one sheet per overtime')
        c.setFillGray(INK)
        opts(c, W - M - w, y - 24, items, size=8, gap=5)
    elif page_note:
        c.setFont('Helvetica', 7)
        c.setFillGray(0.4)
        c.drawRightString(W - M, y - 21, page_note)
        c.setFillGray(INK)
    y -= 34 if ot_select else 26

    c.setLineWidth(1)
    c.line(M, y, W - M, y)
    y -= 16

    # Game strip: the four things a loose sheet needs to identify itself afterwards.
    c.setFont('Helvetica', 6.2)
    c.setFillGray(GLYPH)
    c.drawString(M, y + 11, 'DATE')
    box(c, M, y, 74, 9)
    c.drawString(M + 84, y + 11, 'OPPONENT')
    box(c, M + 84, y, 150, 9)
    c.drawString(M + 244, y + 11, 'VENUE')
    opts(c, M + 244, y + 2, ['HOME', '|', 'AWAY', '|', 'NEUTRAL'], maxw=78, size=6.2)
    c.drawString(M + 330, y + 11, 'LOGGING')
    opts(c, M + 330, y + 2, ['DEFENSE (opp poss)', '|', 'OFFENSE'], maxw=130, size=6.2)
    c.drawString(W - M - 96, y + 11, 'SCORE AT START')
    c.setFillGray(INK)
    box(c, W - M - 96, y, 30, 9, 'MP')
    box(c, W - M - 46, y, 30, 9, 'OPP')
    y -= 18

    if full:
        c.setFont('Helvetica', 6.2)
        c.setFillGray(GLYPH)
        c.drawString(M, y, 'ROSTER — write the number once, then photocopy')
        c.setFillGray(INK)
        y -= 10
        colw = (W - 2 * M) / 3.0
        for i, name in enumerate(roster):
            cx = M + (i // 6) * colw
            cy = y - (i % 6) * 11
            box(c, cx, cy - 1, 15, 9)
            c.setFont('Helvetica', 6.4)
            c.drawString(cx + 19, cy + 1.5, name)
        y -= 5 * 11 + 30      # the block's own five gaps, then clear air under it

    c.setFont('Helvetica', 6.2)
    c.setFillGray(GLYPH)
    c.drawString(M, y + 11, 'FIVE ON FLOOR AT THE START OF THIS PERIOD')
    c.setFillGray(INK)
    for i in range(5):
        box(c, M + 172 + i * 34, y, 28, 10)
    c.setFont('Helvetica', 6)
    c.setFillGray(GLYPH)
    c.drawString(M + 348, y + 2.5, 'then write the new five in a row only when it CHANGES')
    c.setFillGray(INK)
    return y - 12


def table(c, y_top, first_no, rows):
    col = xs()

    # Head: group name over the options each row repeats.
    c.setFillGray(0.92)
    c.rect(M, y_top - 15, W - 2 * M, 15, stroke=0, fill=1)
    c.setFillGray(INK)
    c.setFont('Helvetica-Bold', 6.4)
    for (x, w), (label, _) in zip(col, COLS):
        c.drawString(x + 3, y_top - 10.5, label)
    c.setLineWidth(0.8)
    c.line(M, y_top - 15, W - M, y_top - 15)

    y = y_top - 15
    for i in range(rows):
        ry = y - ROW
        # Alternating tint: on a page of 28 near-identical rows it is what stops the eye
        # sliding onto the wrong line halfway across.
        if i % 2:
            c.setFillGray(0.965)
            c.rect(M, ry, W - 2 * M, ROW, stroke=0, fill=1)
            c.setFillGray(INK)

        c.setFont('Helvetica-Bold', 7.5)
        c.drawCentredString(col[0][0] + col[0][1] / 2, ry + 6.5, str(first_no + i))
        box(c, col[1][0] + 3.5, ry + 5.5, 8, 8)              # + same possession
        box(c, col[2][0] + 3, ry + 5, 28, 10)                # clock
        box(c, col[3][0] + 3, ry + 5, 16, 10)                # MP
        box(c, col[3][0] + 22, ry + 5, 16, 10)               # OPP
        for k in range(5):                                    # five on floor
            box(c, col[4][0] + 2 + k * 11, ry + 5, 10, 10)

        opts(c, col[5][0] + 3, ry + 7.5,                      # SHOT
             ['2', '3', '|', 'MADE', 'MISS', 'BLK', '|', 'AST', '|', 'PiP', 'SCP', 'PoT'],
             maxw=col[5][1] - 6)
        # The FT boxes are real estate, not text, so they come off the column first and the
        # words are fitted into what is left.
        ft_w = 32
        gx = opts(c, col[6][0] + 3, ry + 7.5, ['Sh', 'NS', 'Tech', '|', 'BNS', '|', 'FT'],
                  maxw=col[6][1] - 6 - ft_w)
        gx = max(gx, col[6][0] + col[6][1] - ft_w - 2)
        box(c, gx, ry + 5.5, 11, 9)
        c.setFont('Helvetica', 6)
        c.setFillGray(GLYPH)
        c.drawString(gx + 12.5, ry + 7.5, '/')
        c.setFillGray(INK)
        box(c, gx + 16, ry + 5.5, 11, 9)

        opts(c, col[7][0] + 3, ry + 7.5,                      # TURNOVER
             ['Stl', 'DB', 'Chg', 'OffF', 'SC', 'Oth'], maxw=col[7][1] - 6)
        opts(c, col[8][0] + 3, ry + 7.5, ['DR', 'OR', 'Defl'], maxw=col[8][1] - 6)  # END

        c.setStrokeGray(RULE)
        c.setLineWidth(0.3)
        c.line(M, ry, W - M, ry)
        c.setStrokeGray(INK)
        y = ry

    # Verticals last, so they sit over the row tints.
    c.setStrokeGray(0.55)
    c.setLineWidth(0.4)
    for x, w in col[1:]:
        c.line(x, y_top - 15, x, y)
    c.setLineWidth(0.8)
    c.setStrokeGray(INK)
    c.rect(M, y, W - 2 * M, y_top - y)
    return y


def legend(c, y):
    """Wrapped to the page, not eyeballed: the taxonomy lines are the ones most likely to
    grow, and an un-wrapped legend loses its last words off the right edge silently."""
    lines = [
        ('CIRCLE WHAT HAPPENED.',
         '+ = same possession as the row above (opp offensive rebound, and-one, foul with no FTs). '
         'DR ends the possession · OR continues it · Defl ends nothing.'),
        ('SHOT',
         '2/3 = 2PA/3PA · PiP points in paint · SCP second-chance · PoT points off turnover.'),
        ('FOUL',
         'Sh shooting · NS non-shooting · Tech technical · BNS bonus · FT made/attempted.'),
        ('TURNOVER',
         'Stl steal · DB dead-ball · Chg charge drawn · OffF off. foul · SC shot clock · Oth other.'),
        ('CLOCK & SCORE',
         'only need writing when they move — every row is stamped with the last one above it. '
         'Fields match the Defensive Possession Logger exactly.'),
    ]
    c.setFillGray(0.3)
    dy = y - 9
    for head, body in lines:
        c.setFont('Helvetica-Bold', 5.8)
        c.drawString(M, dy, head)
        x = M + c.stringWidth(head, 'Helvetica-Bold', 5.8) + 5
        c.setFont('Helvetica', 5.8)
        room = (W - M) - x
        words, line = body.split(' '), ''
        for w in words:
            trial = (line + ' ' + w).strip()
            if c.stringWidth(trial, 'Helvetica', 5.8) > room and line:
                c.drawString(x, dy, line)
                dy -= 7.5
                x, room, line = M + 12, (W - M) - (M + 12), w
            else:
                line = trial
        if line:
            c.drawString(x, dy, line)
        dy -= 8
    c.setFillGray(INK)


def page(c, period, page_note, roster, first_no, full_header=True, ot_select=False):
    y = header(c, period, page_note, roster, full=full_header, ot_select=ot_select)
    room = y - (M + 52)
    rows = int(room // ROW)
    end = table(c, y, first_no, rows)
    legend(c, end)
    c.showPage()
    return rows


def build(out, roster):
    c = canvas.Canvas(str(out), pagesize=letter)
    c.setTitle('Moorpark MBB — Possession Log: Second Half & Overtime')
    c.setAuthor('Moorpark MBB')

    n = page(c, 'SECOND HALF', 'page 1 of 2 — possessions from 1', roster, 1)
    page(c, 'SECOND HALF', f'page 2 of 2 — possessions from {n + 1}', roster, n + 1,
         full_header=False)
    page(c, 'OVERTIME', None, roster, 1, ot_select=True)
    c.save()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='possession_log_sheets.pdf')
    ap.add_argument('--roster-from', help='a pt_data.json export; visible players are used')
    a = ap.parse_args()
    roster = ROSTER
    if a.roster_from:
        d = json.loads(pathlib.Path(a.roster_from).read_text())
        roster = [p['name'] for p in d.get('roster', []) if not p.get('hidden')]
    # Three columns of six; anything past eighteen would need a taller block.
    roster = roster[:18]
    print('wrote', build(pathlib.Path(a.out), roster))


if __name__ == '__main__':
    main()
