/* Apply clock_reset_fix.js to a pt_data.json export, in place.

     node tools/apply_clock_reset.mjs tracker/pt_data.json            # dry run: prints, writes nothing
     node tools/apply_clock_reset.mjs tracker/pt_data.json --apply    # writes the repaired file

   The repair runs INSIDE the tracker page (headless Chromium), so teamStats and playerStats
   are recomputed by the tracker's own computeTeamStats/computePlayerStats — not a copy of
   them that could drift. Only the one session dated in CLOCK_RESET_FIX is touched; every
   other key in the file is written back exactly as it was read. */
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require('playwright')); }
catch (e) { ({ chromium } = require(path.join(process.execPath, '../../lib/node_modules/playwright'))); }

const here = path.dirname(fileURLToPath(import.meta.url));
const file = process.argv[2];
const apply = process.argv.includes('--apply');
if (!file) { console.error('usage: node tools/apply_clock_reset.mjs <pt_data.json> [--apply]'); process.exit(2); }

const raw = readFileSync(file, 'utf8');
const data = JSON.parse(raw);
const tool = readFileSync(path.join(here, 'clock_reset_fix.js'), 'utf8');
const { CLOCK_RESET_FIX } = require(path.join(here, 'clock_reset_fix.js'));

const hits = (data.sessions || []).map((s, i) => [s, i]).filter(([s]) => s.date === CLOCK_RESET_FIX.date);
if (hits.length !== 1) {
  console.error(`expected exactly one session dated ${CLOCK_RESET_FIX.date}, found ${hits.length}.`);
  console.error('sessions:\n  ' + (data.sessions || []).map(s => `${s.title} (${s.date})`).join('\n  '));
  process.exit(1);
}
const [orig, at] = hits[0];

const browser = await chromium.launch(process.env.PLAYWRIGHT_BROWSERS_PATH ? {} : { executablePath: '/opt/pw-browsers/chromium' });
let result;
try {
  const page = await browser.newPage();
  await page.addInitScript(() => { window.__clockResetNoAutorun = true; });
  await page.goto(pathToFileURL(path.join(here, '..', 'tracker', 'index.html')).href);
  await page.waitForFunction(() => typeof computePlayerStats === 'function');
  await page.addScriptTag({ content: tool });
  result = await page.evaluate((sess) => {
    try {
      const out = repairClockReset(sess);
      const s = out.session, f = out.report.fmt;
      s.teamStats   = computeTeamStats(s);
      s.playerStats = computePlayerStats(s);
      const minutes = clockResetMinutes(sess, s).map(x => ({ player: x.player, team: x.team,
                                                              was: f(x.was), now: f(x.now), gained: f(x.now - x.was) }));
      const r = out.report;
      return { ok: true, session: s, minutes, stints: r.stints, title: r.title, quarter: r.quarter, add: f(r.add),
               q: { was: [f(r.quarterWas.duration), f(r.quarterWas.played)], now: [f(r.quarterNow.duration), f(r.quarterNow.played)] } };
    } catch (e) { return { ok: false, error: e.message }; }
  }, orig);
} finally {
  await browser.close();
}

if (!result.ok) { console.error('NOT APPLIED — ' + result.error); process.exit(1); }

console.log(`${result.title} — Q${result.quarter}: +${result.add} to the five on the floor across the reset`);
console.table(result.stints);
console.log('player minutes that moved:');
console.table(result.minutes);
console.log(`Q${result.quarter} length ${result.q.was[0]} → ${result.q.now[0]}, played ${result.q.was[1]} → ${result.q.now[1]}`);

if (!apply) { console.log('\ndry run — nothing written. Add --apply to write it.'); process.exit(0); }
data.sessions[at] = result.session;
writeFileSync(file, JSON.stringify(data));
console.log(`\nwritten: ${file}`);
