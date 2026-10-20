/* Offline support for the coaches' demo (a copy of the possession tracker's), the same way the game tracker does it: the page
   network first (5 seconds, then the cached copy, so one bar of signal never hangs it), logos
   and the game tracker's pdf.js cache first. Bump CACHE when what is cached changes shape. */
const CACHE = 'pl-v6';
const SHELL = ['./', './index.html', './manifest.webmanifest', '../game/icon.svg', '../game/icon-180.png',
               '../game/vendor/pdf.min.mjs', '../game/vendor/pdf.worker.min.mjs',
               '../game/logos/allan_hancock.png', '../game/logos/bakersfield.png', '../game/logos/chaffey.png', '../game/logos/cuesta.png', '../game/logos/irvine_valley.png', '../game/logos/la_pierce.png', '../game/logos/la_valley.png', '../game/logos/moorpark.png', '../game/logos/oxnard.png', '../game/logos/riverside.png', '../game/logos/santa_barbara.png', '../game/logos/ventura.png', '../game/logos/west_la.png'];
// The stat-sheet photo reader (Tesseract, ~11 MB), saved up front so it works with no signal. Best effort:
// a failed download never blocks the app from installing; it is fetched again on first use.
const TESS = ['vendor/tess/tesseract.min.js', 'vendor/tess/worker.min.js', 'vendor/tess/tesseract-core-simd-lstm.wasm.js',
              'vendor/tess/tesseract-core-lstm.wasm.js', 'vendor/tess/eng.traineddata.gz'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL).then(() => Promise.all(TESS.map(u => c.add('../poss/' + u).catch(() => {})))))
    .then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith('mbbdemo-') && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
function withTimeout(p, ms) {
  return new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('timeout')), ms);
    p.then(v => { clearTimeout(t); res(v); }, err => { clearTimeout(t); rej(err); });
  });
}
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.includes('/logos/') || url.pathname.includes('/vendor/')) {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
      return res;
    })));
    return;
  }
  // The page, and the season baseline (baseline.enc.json): network first, the saved copy offline.
  const isShell = req.mode === 'navigate' || url.pathname.endsWith('/demo/') || url.pathname.endsWith('/demo/index.html') || url.pathname.endsWith('/baseline.enc.json');
  e.respondWith(
    withTimeout(fetch(req, isShell ? { cache: 'no-cache' } : {}), isShell ? 5000 : 8000).then(res => {
      if (res.ok && isShell) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req, { ignoreSearch: true })
      .then(hit => hit || (req.mode === 'navigate' ? caches.match('./index.html') : Response.error())))
  );
});
