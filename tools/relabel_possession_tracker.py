#!/usr/bin/env python3
"""Re-label the possession tracker for another period.

    python tools/relabel_possession_tracker.py FIRST_HALF.pdf \
        --period "SECOND HALF" --out Moorpark_Second_Half_Possession_Tracker.pdf

The sheet says FIRST HALF in five places — the header rule, and the FOULS, SUMMARY,
TIMEOUTS and KILLS bars — and nothing else about it is period-specific. Its text is
subsetted CID glyphs under Identity-H encoding, so there is no "FIRST HALF" string in the
file to search for and no guarantee the subset even carries a glyph the new wording needs
(no capital V anywhere on this sheet, and OVERTIME wants one). So each label is covered and
redrawn instead of edited.

Three things make the patch invisible rather than merely correct:

  · The cover is filled with the colour sampled from the page beside the label, not white.
    Four of the five sit on a yellow bar, and a white box on a yellow bar is worse than a
    wrong word.
  · The labels are letter-spaced. The tracking is measured from the original — drawn width
    against natural width, divided by the gaps — and reapplied, so the new wording breathes
    the way the rest of the sheet does.
  · Liberation Sans Bold and Helvetica-Bold are metric-compatible, so the substitute font
    sets to the same widths the original was laid out with.

Everything else on the page is the original, untouched: same grid, same colours, same
Satisfy script in the masthead, same footer.
"""

import argparse, io, pathlib
import pdfplumber
import pypdfium2
from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

FONT = 'Helvetica-Bold'
ANCHOR = 'FIRST'          # every period label on this sheet starts here
GAP = 14                  # a word further right than this starts a different label


def labels(path):
    """The five period labels, with the geometry and colour needed to redraw them."""
    out = []
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(extra_attrs=['size', 'non_stroking_color'])
        words.sort(key=lambda w: (round(w['top'], 1), w['x0']))
        for i, w in enumerate(words):
            if w['text'].upper() != ANCHOR:
                continue
            run = [w]
            for nxt in words[i + 1:]:
                if abs(nxt['top'] - w['top']) > 2 or nxt['x0'] - run[-1]['x1'] > GAP:
                    break
                run.append(nxt)
            text = ' '.join(r['text'] for r in run)
            chars = [c for c in page.chars
                     if abs(c['top'] - w['top']) < 2 and run[0]['x0'] - 1 <= c['x0'] <= run[-1]['x1']]
            out.append({
                'text':  text,
                'x0':    run[0]['x0'], 'x1': run[-1]['x1'],
                'top':   min(c['top'] for c in chars),
                'bottom': max(c['bottom'] for c in chars),
                # y0/y1 are PDF coordinates (up from the page foot), which is what the
                # overlay canvas draws in. All caps, so y0 IS the baseline.
                'y0':    min(c['y0'] for c in chars),
                'y1':    max(c['y1'] for c in chars),
                'size':  w['size'],
                'color': w['non_stroking_color'],
                'page_height': page.height,
            })
    return out


def backdrop(path, lab, scale=6.0):
    """The colour the label is printed ON, read off the page a few points to its left."""
    page = pypdfium2.PdfDocument(path)[0]
    img = page.render(scale=scale).to_pil().convert('RGB')
    y = int(((lab['top'] + lab['bottom']) / 2) * scale)
    samples = []
    for dx in (-9, -7, -5, 5, 7, 9):
        x = int((lab['x0'] + dx if dx < 0 else lab['x1'] + dx) * scale)
        if 0 <= x < img.width and 0 <= y < img.height:
            samples.append(img.getpixel((x, y)))
    if not samples:
        return (1, 1, 1)
    # The mode, not the mean: averaging a sample that clipped a letter gives a muddy colour.
    top = max(set(samples), key=samples.count)
    return tuple(v / 255 for v in top)


def tracking(text, width, size):
    """Letter-spacing the original was drawn with."""
    natural = pdfmetrics.stringWidth(text, FONT, size)
    return (width - natural) / max(1, len(text) - 1)


def relabel(src, period, out):
    found = labels(src)
    if not found:
        raise SystemExit(f'no "{ANCHOR} ..." labels found in {src}')

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for lab in found:
        new = lab['text'].upper().replace('FIRST HALF', period.upper())
        track = tracking(lab['text'], lab['x1'] - lab['x0'], lab['size'])
        bg = backdrop(src, lab)

        # Cover: the label's own box plus a whisker, in the colour beside it.
        c.setFillColorRGB(*bg)
        c.rect(lab['x0'] - 3, lab['y0'] - 2.5,
               (lab['x1'] - lab['x0']) + 6, (lab['y1'] - lab['y0']) + 5,
               stroke=0, fill=1)

        # Redraw centred on the old centre, at the old size, colour and tracking.
        col = lab['color']
        rgb = tuple(col) if isinstance(col, (list, tuple)) and len(col) == 3 else (0, 0, 0)
        c.setFillColorRGB(*rgb)
        width = pdfmetrics.stringWidth(new, FONT, lab['size']) + track * (len(new) - 1)
        # A text object, because letter-spacing lives there rather than on the canvas.
        t = c.beginText((lab['x0'] + lab['x1']) / 2 - width / 2, lab['y0'])
        t.setFont(FONT, lab['size'])
        t.setCharSpace(track)
        t.setFillColorRGB(*rgb)
        t.textOut(new)
        c.drawText(t)
    c.showPage()
    c.save()
    buf.seek(0)

    reader = PdfReader(src)
    page = reader.pages[0]
    page.merge_page(PdfReader(buf).pages[0])
    writer = PdfWriter()
    writer.add_page(page)
    writer.add_metadata({'/Title': f'Moorpark College — Possession Tracking ({period.title()})',
                         '/Author': 'Moorpark College Men\'s Basketball'})
    with open(out, 'wb') as fh:
        writer.write(fh)
    return [(l['text'], l['text'].upper().replace('FIRST HALF', period.upper())) for l in found]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('--period', required=True, help='e.g. "SECOND HALF" or "OVERTIME"')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    for old, new in relabel(a.src, a.period, pathlib.Path(a.out)):
        print(f'  {old}  ->  {new}')
    print('wrote', a.out)


if __name__ == '__main__':
    main()
