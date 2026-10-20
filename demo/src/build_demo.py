#!/usr/bin/env python3
"""The coaches' demo: a standalone copy of the possession tracker at /demo/, frozen on last season (2025-26) with a
season of simulated games and a live game vs Irvine Valley late in the 2nd half. Separate from the real tracker:
its own folder, offline cache (sw.js) and home-screen icon, and every key it stores is prefixed 'mbbdemo:' so its
fake games never mix with real ones on the same iPad. All data is inside the page (works offline).
Rebuild: build the tracker (poss/index.html), serve the repo root on :8765 (python3 -m http.server 8765),
then node demo/src/gen.js (writes demo/src/seed.json) and python3 demo/src/build_demo.py."""
import json, re, os, hashlib, base64
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = f'{REPO}/demo'
html = open(f'{REPO}/poss/index.html').read()
seed = json.load(open(f'{HERE}/seed.json'))
# The scouting PDF on Irvine Valley: the standard report from generate_opponent_report.py (copied here as ivc_scout.pdf),
# attached to them and to the live game, and stored in the page's offline file store on first open, after Reset demo, and
# whenever the PDF changes (PDF_V).
SCOUT_KEY = 'scout_demo_ivc'
pdf_bytes = open(f'{HERE}/ivc_scout.pdf', 'rb').read()
pdf_b64, PDF_V = base64.b64encode(pdf_bytes).decode(), hashlib.md5(pdf_bytes).hexdigest()[:8]
opp = json.loads(seed['gt_opp_rosters'])
for o in opp:
    if o['name'] == 'Irvine Valley': o['scoutKey'] = SCOUT_KEY
seed['gt_opp_rosters'] = json.dumps(opp)
gms = json.loads(seed['pt2_games'])
for gm in gms:
    if gm.get('opp') == 'Irvine Valley' and not gm.get('final'): gm['scoutKey'] = SCOUT_KEY
seed['pt2_games'] = json.dumps(gms)
SEED_V = 'v1-' + hashlib.md5((json.dumps(seed, sort_keys=True) + pdf_b64).encode()).hexdigest()[:8]

shim = '''<script>
/* DEMO: every key this page stores is prefixed, so the demo never touches the real tracker's data on this iPad. The
   seed (last season's teams, a season of games, the live game) loads on first open and on Reset demo. */
(() => {
  const P = 'mbbdemo:', S = Storage.prototype, g = S.getItem, s = S.setItem, r = S.removeItem;
  S.getItem = function (k) { return g.call(this, P + k); };
  S.setItem = function (k, v) { return s.call(this, P + k, v); };
  S.removeItem = function (k) { return r.call(this, P + k); };
  if (window.indexedDB) { const o = indexedDB.open.bind(indexedDB); indexedDB.open = (n, v) => o(P + n, v); }
  window.demoReset = () => { const ks = []; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith(P)) ks.push(k); }
    ks.forEach(k => r.call(localStorage, k)); location.reload(); };
  if (g.call(localStorage, P + '__seed') !== %s) {
    const keep = []; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith(P)) keep.push(k); }
    keep.forEach(k => r.call(localStorage, k));
    const SEED = %s;
    Object.entries(SEED).forEach(([k, v]) => s.call(localStorage, P + k, v));
    s.call(localStorage, P + '__seed', %s);
  }
  // The Irvine Valley scouting PDF, in the same offline file store the Scouting screen reads (raw bytes, as Add PDF stores them).
  if (window.indexedDB) try { const r = indexedDB.open('gt_files', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('files');
    r.onsuccess = () => { const db = r.result, q = db.transaction('files').objectStore('files').get(%s);
      q.onsuccess = () => { if (q.result && q.result.v === %s) return; const b = atob(%s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
        db.transaction('files', 'readwrite').objectStore('files').put({ name: 'Irvine Valley scouting report 2025-26.pdf', data: u.buffer, v: %s, added: new Date().toISOString() }, %s); }; };
  } catch (e) {}
})();
</script>
''' % (json.dumps(SEED_V), json.dumps(seed, separators=(',', ':')).replace('</', '<\\/'), json.dumps(SEED_V), json.dumps(SCOUT_KEY), json.dumps(PDF_V), json.dumps(pdf_b64), json.dumps(PDF_V), json.dumps(SCOUT_KEY))

banner = '''<div class="demo-bar"><b>DEMO</b> · last season's Moorpark vs Irvine Valley · simulated games<button class="btn btn-sm" onclick="if(confirm('Reset the demo to the start (3:12 left, down 3)?'))demoReset()">Reset demo</button></div>'''
css = '''.demo-bar{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:10px;justify-content:center;padding:5px 12px;background:#7c2d12;color:#fde68a;font-size:12.5px}
.demo-bar b{letter-spacing:.12em}.demo-bar .btn{margin-left:8px;padding:3px 10px;font-size:12px}
'''

def sub(a, b, count=1):
    global html
    assert html.count(a) >= 1, a[:60]
    html = html.replace(a, b, count)

sub('<title>Moorpark Possession Tracker</title>', '<title>MBB Demo</title>')
sub('<meta name="apple-mobile-web-app-title" content="MBB Poss">', '<meta name="apple-mobile-web-app-title" content="MBB Demo">')
sub('</style>', css + '</style>')
sub('<nav class="nav">', banner + '\n<nav class="nav">')
i = html.index('<script>')
html = html[:i] + shim + html[i:]
sub('\nfetchRatings();\ncheckBaseline();\n', '\n/* DEMO: frozen on the seeded 2025-26 ratings and team files; no refresh, no season baseline. */\n')
html = html.replace("'vendor/tess/", "'../poss/vendor/tess/").replace("corePath: 'vendor/tess'", "corePath: '../poss/vendor/tess'").replace("langPath: 'vendor/tess'", "langPath: '../poss/vendor/tess'")
os.makedirs(OUT, exist_ok=True)
open(f'{OUT}/index.html', 'w').write(html)

logos = sorted({re.sub(r'[^a-z0-9]+', '_', t.lower()).strip('_') for t in json.loads(seed['pt2_team_files'])})
sw = open(f'{REPO}/poss/sw.js').read()
# Its own cache, renamed on every new seed / PDF (so an installed demo picks the update up), whatever the tracker's is called.
sw = re.sub(r"const CACHE = '[^']*';", f"const CACHE = 'mbbdemo-{SEED_V}';", sw)
sw = re.sub(r"const SHELL = \[[^\]]*\];", "const SHELL = ['./', './index.html', './manifest.webmanifest', '../game/icon.svg', '../game/icon-180.png',\n               '../game/vendor/pdf.min.mjs', '../game/vendor/pdf.worker.min.mjs',\n               "
            + ', '.join(f"'../game/logos/{l}.png'" for l in logos) + "];", sw, flags=re.S)
sw = sw.replace("TESS.map(u => c.add(u)", "TESS.map(u => c.add('../poss/' + u)")
sw = sw.replace("k.startsWith('pl-') && k !== CACHE", "k.startsWith('mbbdemo-') && k !== CACHE")
sw = sw.replace("url.pathname.endsWith('/poss/') || url.pathname.endsWith('/poss/index.html')", "url.pathname.endsWith('/demo/') || url.pathname.endsWith('/demo/index.html')")
sw = sw.replace('/* Offline support for the possession tracker,', '/* Offline support for the coaches\' demo (a copy of the possession tracker\'s),')
assert f"const CACHE = 'mbbdemo-{SEED_V}';" in sw and '/demo/' in sw
open(f'{OUT}/sw.js', 'w').write(sw)
man = json.load(open(f'{REPO}/poss/manifest.webmanifest'))
man.update(name='Moorpark MBB Demo', short_name='MBB Demo')
json.dump(man, open(f'{OUT}/manifest.webmanifest', 'w'), indent=2)
print(len(html), SEED_V, len(logos), 'logos')
