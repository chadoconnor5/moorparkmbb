# The demo's scouting PDF: the real 2025-26 Irvine Valley report (Neural Network - Codex Optimized/
# irvine_valley_scouting_report_2025_26.pdf, made with the Ventura report's layout) recolored from the generator's Ventura orange to Irvine Valley blue (#004789, the
# game tracker's TEAM_COLORS), with the light and dark orange tints moved to matching blues.
import sys, pypdf
from pypdf.generic import ContentStream
src, out = sys.argv[1], sys.argv[2]
def rl(h):   # ReportLab's own number format: 1, .4, 0, .188235
    out = []
    for i in (1, 3, 5):
        v = int(h[i:i + 2], 16) / 255; s = ('%.6f' % v).rstrip('0').rstrip('.')
        out.append('0' if s in ('', '0') else s[1:] if s.startswith('0.') else s)
    return ' '.join(out)
SWAP = {'#FF6600': '#004789', '#FF9900': '#2E6DB4', '#FFF1E6': '#E6EEF7', '#7A3000': '#00264D'}
w = pypdf.PdfWriter(clone_from=src); n = 0
for pg in w.pages:
    d = pg.get_contents().get_data().decode('latin1')
    for a, b in SWAP.items():
        for op in ('rg', 'RG'):
            k = f'{rl(a)} {op}'; n += d.count(k); d = d.replace(k, f'{rl(b)} {op}')
    cs = ContentStream(None, w); cs.set_data(d.encode('latin1'))
    pg.replace_contents(cs); pg.compress_content_streams()
w.write(out); print('swapped', n)
