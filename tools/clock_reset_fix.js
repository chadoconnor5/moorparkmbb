/* Repair a quarter whose game clock was RESET partway through a stint.
   ─────────────────────────────────────────────────────────────────────
   Fall Workout, 24 September 2026. At film 1:31:20 the clock was knocked from 4:28 back
   to 6:00 and play carried on. The five on the floor at that moment went in on the sub at
   film 1:31:08.4, and they are owed 1:30 that the clock never showed.

   Two ways to run it:

     • ON THE TRACKER (Chad's browser): paste this whole file into the console. It finds
       the 24 September session, repairs it, recomputes its stat lines, saves and reloads.
       Then ↑ Publish as usual. It refuses, without writing anything, if the session is
       not shaped as expected, and a second paste is a no-op.

     • ON AN EXPORT (pt_data.json already downloaded):
         node tools/apply_clock_reset.mjs tracker/pt_data.json
       which runs the same repair inside the tracker page headlessly, so the stat lines
       are recomputed by the tracker's own code rather than a copy of it.

   WHY THE #27 TOOL CANNOT DO THIS. amend_quarter_clock.js shifts boundaries by VALUE —
   every reading above the sub's moves up. That is right when the clock STOPPED: the
   readings stay in order. After a RESET they do not: everything typed after 1:31:20 was
   read off a clock that jumped back up 1:32, so a sub at 5:10 after the reset is LATER
   than the 4:40 one before it despite the bigger number. A value rule would drag those
   post-reset stints up with the pre-reset ones. This one decides by ORDER instead —
   position in the quarter's stint chain and in the event log, which the reset never
   touched.

   THE ARITHMETIC. The quarter grows by ADD. Every stint that finished before the reset
   moves up by ADD whole, so its length is unchanged. The stint that crosses the reset —
   the one the 1:31:08.4 sub opened — has its START moved up by ADD and its END left where
   it is, so it alone gains ADD. Every stint after it is already on the post-reset clock
   and stays put. Subs up to and including the 1:31:08.4 one move with the stints they
   open, in lockstep, because segEventCounts() advances a stint only where
   sub.timeSecs === nextSeg.startTimeSecs.

   The clock itself says the gap was 6:00 - 4:28 = 1:32; ADD is 1:30 because that is the
   figure asked for. Either value leaves the quarter consistent — change ADD to 92 if the
   full clock gap is wanted.

   Nothing touches the event log's order, film times or shot clocks. Plus/minus and
   possessions read event adjacency, not the clock, so they are unchanged by construction. */

var CLOCK_RESET_FIX = {   // var, not const: a second console paste must not die on a redeclaration
  date:        '2026-09-24',
  subFilmTs:   91 * 60 + 8.4,   // 1:31:08.4 — the sub whose five was on the floor for the reset
  resetFilmTs: 91 * 60 + 20,    // 1:31:20   — the clock went 4:28 → 6:00 here
  ADD:         90,              // 1:30, as asked (the clock gap itself is 1:32)
};

/* Pure: takes a session, returns { session, report } on a deep copy, or throws with the
   reason. Stores nothing and recomputes nothing — the callers do that. */
function repairClockReset(original, opts) {
  const o = Object.assign({}, CLOCK_RESET_FIX, opts || {});
  const f = s => {
    if (s == null || !isFinite(s)) return '—';
    const t = Math.round(s), a = Math.abs(t);
    return (t < 0 ? '-' : '') + Math.floor(a / 60) + ':' + String(a % 60).padStart(2, '0');
  };
  const film = s => {
    if (s == null) return 'no film';
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = (s % 60).toFixed(1);
    return `${h}:${String(m).padStart(2, '0')}:${sec.padStart(4, '0')}`;
  };
  const stop = m => { throw new Error(m); };
  const s = JSON.parse(JSON.stringify(original));
  const log = s.eventLog || [], allSegs = s.lineupSegments || [];

  /* ── The sub, and the quarter it sits in ── */
  const subsWithFilm = log.filter(e => e.type === 'sub' && e.videoTs != null);
  if (!subsWithFilm.length) stop('no sub in this session carries a film time.');
  const target = subsWithFilm.reduce((b, e) =>
    Math.abs(e.videoTs - o.subFilmTs) < Math.abs(b.videoTs - o.subFilmTs) ? e : b);
  if (Math.abs(target.videoTs - o.subFilmTs) > 3) {
    stop(`no sub near film ${film(o.subFilmTs)} — the nearest is ${film(target.videoTs)}. Wrong session or wrong mark.`);
  }
  const Q = target.quarter, B = target.timeSecs;
  if (B == null) stop(`the ${film(target.videoTs)} sub has no clock reading.`);
  const q = (s.quarters || []).find(x => x.number === Q) || (s.quarters || [])[Q - 1];
  if (!q) stop(`Q${Q} has not been ended yet — end the quarter (or the practice) first.`);
  if (q.clockReset && !o.force) stop(`already repaired — Q${Q} carries ${JSON.stringify(q.clockReset)}. Nothing to do.`);

  /* The reset stint must be the one this sub opened: no other sub between it and the reset. */
  const tIdx = log.indexOf(target);
  const between = log.filter((e, i) => e.type === 'sub' && e.quarter === Q && i > tIdx &&
                                       e.videoTs != null && e.videoTs < o.resetFilmTs);
  if (between.length) {
    stop(`another sub sits between ${film(target.videoTs)} and the reset (${between.map(e => film(e.videoTs)).join(', ')}) — ` +
         'a different five was on the floor when the clock reset.');
  }
  if (target.startOfStint) {
    stop('the 1:31:08.4 sub was absorbed into the stint before it (startOfStint) — look at this one by hand.');
  }

  /* ── The stint it opened ── */
  const segs = allSegs.filter(g => g.quarter === Q);
  const k = segs.findIndex(g => g.startTimeSecs === B);
  if (k === -1) stop(`no Q${Q} stint starts at ${f(B)}, the sub's clock. Starts: ${segs.map(g => f(g.startTimeSecs)).join(', ')}`);
  if (segs.filter(g => g.startTimeSecs === B).length > 1) {
    stop(`two Q${Q} stints start at ${f(B)} — the reset made the reading ambiguous; needs a look by hand.`);
  }
  for (let i = 0; i < k; i++) {
    if (segs[i].endTimeSecs !== segs[i + 1].startTimeSecs) {
      stop(`Q${Q}'s stints before the reset do not chain (${f(segs[i].endTimeSecs)} ≠ ${f(segs[i + 1].startTimeSecs)}).`);
    }
  }
  if (segs[k].endTimeSecs == null) stop('the reset stint is still open — end the quarter first.');

  const beforeRows = segs.map(g => ({ start: g.startTimeSecs, end: g.endTimeSecs }));
  const qWas = { duration: q.duration, played: q.playedDuration, remaining: q.timeRemaining };

  /* ── Shift, by order ── */
  for (let i = 0; i < k; i++) { segs[i].startTimeSecs += o.ADD; segs[i].endTimeSecs += o.ADD; }
  segs[k].startTimeSecs += o.ADD;                       // the crossing stint gains ADD
  const shiftedSubs = log.filter((e, i) => e.type === 'sub' && e.quarter === Q && i <= tIdx && e.timeSecs != null);
  shiftedSubs.forEach(e => { e.timeSecs += o.ADD; });
  q.duration += o.ADD;
  q.playedDuration = q.timeRemaining != null
    ? Math.max(0, q.duration - q.timeRemaining)
    : (q.playedDuration != null ? q.playedDuration + o.ADD : q.playedDuration);
  q.clockReset = { added: o.ADD, atClock: B, subFilmTs: target.videoTs, resetFilmTs: o.resetFilmTs,
                   appliedAt: new Date().toISOString() };

  /* ── Invariants before anyone stores it ── */
  const bad = [];
  if (segs[0].startTimeSecs !== q.duration) bad.push(`first stint starts ${f(segs[0].startTimeSecs)}, quarter is ${f(q.duration)}`);
  segs.forEach((g, i) => {
    if (g.endTimeSecs != null && g.endTimeSecs > g.startTimeSecs) bad.push(`stint ${i + 1} ${f(g.startTimeSecs)} → ${f(g.endTimeSecs)} runs backwards`);
    if (i && segs[i - 1].endTimeSecs !== g.startTimeSecs) bad.push(`stints ${i} and ${i + 1} do not meet (${f(segs[i - 1].endTimeSecs)} / ${f(g.startTimeSecs)})`);
  });
  log.filter(e => e.type === 'sub' && e.quarter === Q && e.timeSecs != null && !e.startOfStint).forEach(e => {
    if (!segs.some(g => g.startTimeSecs === e.timeSecs)) bad.push(`sub at ${film(e.videoTs)} (${f(e.timeSecs)}) no longer opens a stint`);
  });
  const span = segs.reduce((n, g) => n + (g.endTimeSecs == null ? 0 : g.startTimeSecs - g.endTimeSecs), 0);
  if (q.playedDuration != null && Math.abs(span - q.playedDuration) > 0.5) {
    bad.push(`stints add to ${f(span)} but Q${Q} played ${f(q.playedDuration)}`);
  }
  if (bad.length) stop('NOT SAVED — the result does not hold together:\n  ' + bad.join('\n  '));

  return {
    session: s,
    report: {
      title: s.title, quarter: Q, subClock: B, add: o.ADD,
      crossing: { lineupA: segs[k].lineupA, lineupB: segs[k].lineupB },
      stints: segs.map((g, i) => ({
        '#': i + 1,
        before: `${f(beforeRows[i].start)} → ${f(beforeRows[i].end)}`,
        after:  `${f(g.startTimeSecs)} → ${f(g.endTimeSecs)}`,
        length: f(g.startTimeSecs - g.endTimeSecs),
        gained: i === k ? '+' + f(o.ADD) : '',
        White: (g.lineupA || []).join(', '),
        Black: (g.lineupB || []).join(', '),
      })),
      quarterWas: qWas,
      quarterNow: { duration: q.duration, played: q.playedDuration, remaining: q.timeRemaining },
      fmt: f,
    },
  };
}

/* Players whose minutes moved, before vs after — for the printout. */
function clockResetMinutes(before, after) {
  const secs = (sess, name, team) => (sess.lineupSegments || []).reduce((n, g) => {
    if (g.endTimeSecs == null || g.endTimeSecs > g.startTimeSecs) return n;
    return ((team === 'a' ? g.lineupA : g.lineupB) || []).includes(name) ? n + g.startTimeSecs - g.endTimeSecs : n;
  }, 0);
  const rows = [];
  for (const team of ['a', 'b']) {
    const names = new Set();
    (after.lineupSegments || []).forEach(g => ((team === 'a' ? g.lineupA : g.lineupB) || []).forEach(n => names.add(n)));
    for (const name of names) {
      const was = secs(before, name, team), now = secs(after, name, team);
      if (Math.abs(now - was) < 0.5) continue;
      rows.push({ player: name, team: team === 'a' ? (after.teamAName || 'White') : (after.teamBName || 'Black'),
                  was: was, now: now });
    }
  }
  return rows;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { repairClockReset, clockResetMinutes, CLOCK_RESET_FIX };
} else if (typeof window !== 'undefined' && !window.__clockResetNoAutorun) {
  /* Console paste: apply on paste, one step, nothing to forget. */
  (() => {
    const stop = m => { console.error('%cclock reset fix: ' + m, 'color:#ef4444;font-weight:700'); return null; };
    let saved = [], live = null;
    try { saved = JSON.parse(localStorage.getItem('pt_sessions') || '[]') || []; } catch (e) {}
    try { live  = JSON.parse(localStorage.getItem('pt_live_session') || 'null'); } catch (e) {}
    const hit = x => x && x.date === CLOCK_RESET_FIX.date;
    const idx = saved.findIndex(hit);
    if (idx !== -1 && saved.findIndex((x, i) => i > idx && hit(x)) !== -1) return stop(`more than one saved session is dated ${CLOCK_RESET_FIX.date}.`);
    const where = idx !== -1 ? 'saved' : (hit(live) ? 'live' : null);
    if (!where) return stop(`no session dated ${CLOCK_RESET_FIX.date} in this browser.`);
    if (idx !== -1 && hit(live)) return stop('tonight is in BOTH the saved list and the live slot. Tell Claude before going further.');
    const orig = where === 'saved' ? saved[idx] : live;

    let out;
    try { out = repairClockReset(orig); } catch (e) { return stop(e.message); }
    const s = out.session, r = out.report, f = r.fmt;

    const finalised = !!(s.completed || (s.playerStats && Object.keys(s.playerStats).length));
    if (finalised) {
      if (typeof computeTeamStats !== 'function' || typeof computePlayerStats !== 'function')
        return stop('run this on the tracker page — its stat functions are not here.');
      s.teamStats   = computeTeamStats(s);        // first: computePlayerStats divides by it
      s.playerStats = computePlayerStats(s);
    }

    const APP = (typeof State !== 'undefined' && State) ? State : null;
    if (where === 'saved') {
      saved[idx] = s;
      localStorage.setItem('pt_sessions', JSON.stringify(saved));
      if (APP && Array.isArray(APP.sessions)) {
        const i = APP.sessions.findIndex(x => x.id === s.id);
        if (i !== -1) APP.sessions[i] = s;
      }
    } else {
      localStorage.setItem('pt_live_session', JSON.stringify(s));
      if (APP && APP.liveSession && APP.liveSession.id === s.id) APP.liveSession = s;
    }

    console.log(`%cFIXED — ${r.title}, Q${r.quarter}: +${f(r.add)} to the five on for the clock reset`,
                'color:#22c55e;font-weight:700;font-size:13px');
    console.table(r.stints);
    console.table(clockResetMinutes(orig, s).map(x => ({ player: x.player, team: x.team, was: f(x.was), now: f(x.now), gained: f(x.now - x.was) })));
    console.table([
      { what: `Q${r.quarter} length`, before: f(r.quarterWas.duration), after: f(r.quarterNow.duration) },
      { what: `Q${r.quarter} played`, before: f(r.quarterWas.played),   after: f(r.quarterNow.played) },
    ]);
    if (finalised) console.log('%cstat lines recomputed — ↑ Publish to push it to the site', 'color:#6366f1;font-weight:700');
    console.log('%creloading…', 'color:#6366f1;font-weight:700');
    setTimeout(() => location.reload(), 800);
  })();
}
