/* Offline support for the game tracker.
   The page: network first, but only for 3 seconds - a gym with one bar of signal must not
   leave the tracker hanging - then the cached copy. A pushed update shows up the next time
   there is a real connection.
   pdf.js (vendor/) and team logos (logos/): cache first; they never change under the same name.
   The page warms the cache with every logo on the schedule, so they show offline too.
   Bump CACHE when what is cached changes shape. */
const CACHE = 'gt-v1';
const SHELL = ['./', './index.html', './manifest.webmanifest', './icon.svg', './icon-180.png', './logos/moorpark.png',
               './vendor/pdf.min.mjs', './vendor/pdf.worker.min.mjs'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
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

  // pdf.js and team logos never change under the same name: cache first.
  if (url.pathname.includes('/vendor/') || url.pathname.includes('/logos/')) {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
      return res;
    })));
    return;
  }

  const isShell = req.mode === 'navigate' || SHELL.some(p => p !== './' && url.pathname.endsWith(p.slice(1)));
  e.respondWith(
    withTimeout(fetch(req), isShell ? 3000 : 8000).then(res => {
      if (res.ok && isShell) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req, { ignoreSearch: true })
      .then(hit => hit || (req.mode === 'navigate' ? caches.match('./index.html') : Response.error())))
  );
});
