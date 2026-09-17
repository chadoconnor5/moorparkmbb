/* Amend a quarter whose game clock was not running for part of it.
   ────────────────────────────────────────────────────────────────
   Paste into the browser console on the practice tracker, then run:

     amendQuarterClock()                 // dry run — prints before/after, changes nothing
     amendQuarterClock({ apply: true })  // writes it and reloads the page

   WHY THIS EXISTS. The tracker measures a stint as a span of the DOWN-counting game
   clock: stintSeconds() is startTimeSecs - endTimeSecs. Time played while the clock was
   stopped is therefore invisible to it, and no screen in the app can add it back — the
   quarter-setup duration is asked once, before the quarter, and the only after-the-fact
   lever (Amend Quarter End Clock) moves the END, which would rob the LAST stint to pay
   an earlier one. Lengthening the quarter is the only honest repair, and it has to be
   done to the stored session.

   THE ARITHMETIC. Let B be the clock reading at the substitution that splits the untimed
   stretch, `before` the seconds the pre-sub five played untimed, `after` the seconds the
   post-sub five played untimed. The quarter grows by before+after, so with the clock
   counting down every boundary EARLIER in the quarter than B (a higher reading) moves up
   by the full total, B itself moves up by `after` only, and everything after B stays put:

     boundary > B   →  + (before + after)     earlier stints keep their length
     boundary = B   →  + after                the pre-sub stint gains `before`
     boundary < B   →  unchanged              the post-sub stint gains `after`

   Sub events carry the same clock reading as the segment boundary they opened, and
   segEventCounts() advances a stint only where sub.timeSecs === nextSeg.startTimeSecs —
   so subs and boundaries are shifted by the same rule, in lockstep. Break that and every
   event after the sub silently files under the wrong five.

   Nothing here touches the event log's order, its film times, or any stat: plus/minus and
   possession counts read event ADJACENCY, not the clock. Only minutes move. */

window.amendQuarterClock = function amendQuarterClock(opts) {
  const o = Object.assign({
    session:     /#\s*27\b/i,           // title (regex or substring), or an exact session id
    quarter:     2,
    pausedFilmTs:  105 * 60 + 53,       // 105:53 — the clock stopped here and stayed stopped
    subFilmTs:     108 * 60 + 17.1,     // 108:17.1 — the sub inside the untimed stretch
    restartFilmTs: 108 * 60 + 38,       // 108:38 — the clock started running again
    subClock:    null,                  // pin the sub by its clock reading instead of film
    before:      null,                  // override the split; otherwise read off the marks
    after:       null,
    apply:       false,
    force:       false,                 // re-run over an amendment already applied
  }, opts || {});

  /* The split is the film's, not a guess: each five is credited with the untimed seconds it
     was actually on the floor for. Rounded to whole seconds, which is what the clock boxes
     and every minutes figure show anyway. */
  if (o.before == null) o.before = Math.round(o.subFilmTs - o.pausedFilmTs);
  if (o.after  == null) o.after  = Math.round(o.restartFilmTs - o.subFilmTs);
  if (!(o.before >= 0) || !(o.after >= 0)) {
    console.error('amendQuarterClock: the film marks are out of order — paused < sub < restart.');
    return null;
  }

  const fmt = s => {
    if (s == null || !isFinite(s)) return '—';
    const t = Math.round(s), a = Math.abs(t);
    return (t < 0 ? '-' : '') + Math.floor(a / 60) + ':' + String(a % 60).padStart(2, '0');
  };
  const film = s => s == null ? 'no film' : fmt(s);
  const fail = msg => { console.error('%camendQuarterClock: ' + msg, 'color:#ef4444;font-weight:700'); return null; };

  /* ── 1. Find the session, in whichever store holds it ── */
  let live = null;
  try { live = JSON.parse(localStorage.getItem('pt_live_session') || 'null'); } catch (e) {}
  let saved = [];
  try { saved = JSON.parse(localStorage.getItem('pt_sessions') || '[]') || []; } catch (e) {}

  const matches = s => {
    if (!s) return false;
    if (o.session instanceof RegExp) return o.session.test(s.title || '');
    return s.id === o.session || String(s.title || '').includes(o.session);
  };
  const pool = [];
  if (matches(live)) pool.push({ where: 'live', session: live });
  saved.forEach((s, i) => { if (matches(s)) pool.push({ where: 'saved', index: i, session: s }); });

  if (!pool.length) {
    const names = [live, ...saved].filter(Boolean).map(s => `${s.title} (${s.date})`);
    return fail('no session matched ' + o.session + '. Sessions in this browser:\n  ' + names.join('\n  '));
  }
  if (pool.length > 1) {
    return fail('matched ' + pool.length + ' sessions: ' + pool.map(p => p.session.title).join(', ') + '. Narrow `session`.');
  }
  const { where, index, session } = pool[0];

  /* ── 2. The quarter, its segments and its subs ── */
  const q = (session.quarters || [])[o.quarter - 1];
  if (!q) return fail(`Q${o.quarter} has not been ended yet — there is nothing stored to amend.`);
  if (q.clockAmend && !o.force) {
    return fail(`Q${o.quarter} already carries an amendment (${JSON.stringify(q.clockAmend)}). Pass force:true to redo it.`);
  }
  const segs = (session.lineupSegments || []).filter(s => s.quarter === o.quarter);
  if (!segs.length) return fail(`Q${o.quarter} has no lineup stints.`);
  const subs = (session.eventLog || []).filter(e => e.type === 'sub' && e.quarter === o.quarter && e.timeSecs != null);

  /* ── 3. The sub that splits the untimed stretch ── */
  let target = null;
  if (o.subClock != null) {
    target = subs.find(e => e.timeSecs === o.subClock);
    if (!target) return fail(`no Q${o.quarter} sub at ${fmt(o.subClock)}. Subs: ${subs.map(e => fmt(e.timeSecs)).join(', ')}`);
  } else {
    const withFilm = subs.filter(e => e.videoTs != null);
    if (!withFilm.length) return fail('no Q' + o.quarter + ' sub carries a film time — pin it with subClock instead.');
    target = withFilm.reduce((best, e) =>
      Math.abs(e.videoTs - o.subFilmTs) < Math.abs(best.videoTs - o.subFilmTs) ? e : best);
    const off = Math.abs(target.videoTs - o.subFilmTs);
    if (off > 30) return fail(`nearest Q${o.quarter} sub to film ${film(o.subFilmTs)} is ${film(target.videoTs)} — ${fmt(off)} away. Wrong session or wrong mark.`);
  }
  const B = target.timeSecs;

  /* The boundary has to exist on BOTH sides or the shift would tear the chain apart. */
  const opened = segs.find(s => s.startTimeSecs === B);
  const closed = segs.find(s => s.endTimeSecs === B);
  if (!opened || !closed) {
    return fail(`the sub at ${fmt(B)} does not line up with a stint boundary` +
      ` (starts: ${segs.map(s => fmt(s.startTimeSecs)).join(', ')} | ends: ${segs.map(s => fmt(s.endTimeSecs)).join(', ')}).`);
  }

  /* One sub inside the stretch is what this splits. A second one means a third five was
     out there and the arithmetic below would hand its seconds to somebody else. */
  const inside = subs.filter(e => e !== target && e.videoTs != null
                              && e.videoTs > o.pausedFilmTs && e.videoTs < o.restartFilmTs);
  if (inside.length) {
    return fail('another sub sits inside the untimed stretch, at film ' +
      inside.map(e => film(e.videoTs)).join(' and ') +
      ' — more than two fives shared that time, so the split has to be worked out by hand.');
  }

  const total = o.before + o.after;
  const shift = v => (v == null ? v : v > B ? v + total : v === B ? v + o.after : v);

  /* ── 4. Report, then (only if asked) write ── */
  const stint = s => ({
    'stint':  `${fmt(s.startTimeSecs)} → ${fmt(s.endTimeSecs)}`,
    'length': fmt(s.startTimeSecs != null && s.endTimeSecs != null ? s.startTimeSecs - s.endTimeSecs : null),
    'White':  (s.lineupA || []).join(', '),
    'Black':  (s.lineupB || []).join(', '),
  });
  console.log(`%c${session.title} — Q${o.quarter}  (${where === 'live' ? 'in progress' : 'saved'})`,
              'font-weight:700;font-size:13px');
  console.log(`sub that splits it: ${fmt(B)} on the clock, film ${film(target.videoTs)}` +
              (target.subs || []).map(p => `  ${p.playerOut} → ${p.playerIn}`).join(''));
  console.log(`clock stopped at film ${film(o.pausedFilmTs)}, running again at ${film(o.restartFilmTs)}` +
              ` — ${fmt(total)} of play the quarter never counted`);
  console.log(`adding ${fmt(o.before)} to the five before the sub and ${fmt(o.after)} to the five after`);
  console.log('BEFORE  duration ' + fmt(q.duration) + ', ended at ' + fmt(q.timeRemaining));
  console.table(segs.map(stint));

  const after = segs.map(s => stint({
    startTimeSecs: shift(s.startTimeSecs), endTimeSecs: shift(s.endTimeSecs),
    lineupA: s.lineupA, lineupB: s.lineupB,
  }));
  console.log('AFTER   duration ' + fmt(q.duration + total) + ', ended at ' + fmt(q.timeRemaining));
  console.table(after);

  if (!o.apply) {
    console.log('%cdry run — nothing written. Run amendQuarterClock({ apply: true }) to commit it.',
                'color:#f59e0b;font-weight:700');
    return { session: session.title, quarter: o.quarter, sub: fmt(B), applied: false };
  }

  segs.forEach(s => { s.startTimeSecs = shift(s.startTimeSecs); s.endTimeSecs = shift(s.endTimeSecs); });
  subs.forEach(e => { e.timeSecs = shift(e.timeSecs); });
  q.duration = q.duration + total;
  q.playedDuration = (q.timeRemaining != null)
    ? Math.max(0, q.duration - q.timeRemaining)
    : (q.playedDuration != null ? q.playedDuration + total : q.playedDuration);
  q.clockAmend = { before: o.before, after: o.after, atClock: B, appliedAt: new Date().toISOString() };

  /* ── 5. Invariants, checked before anything is stored ── */
  const problems = [];
  segs.forEach(s => {
    if (s.endTimeSecs != null && s.endTimeSecs > s.startTimeSecs) problems.push(`stint ${fmt(s.startTimeSecs)} → ${fmt(s.endTimeSecs)} runs backwards`);
  });
  (session.eventLog || []).filter(e => e.type === 'sub' && e.quarter === o.quarter && e.timeSecs != null)
    .forEach(e => {
      if (!segs.some(s => s.startTimeSecs === e.timeSecs)) problems.push(`sub at ${fmt(e.timeSecs)} no longer opens a stint — event attribution would drift`);
    });
  const spans = segs.filter(s => s.endTimeSecs != null).reduce((n, s) => n + (s.startTimeSecs - s.endTimeSecs), 0);
  const played = Math.max(0, q.duration - (q.timeRemaining || 0));
  if (segs.every(s => s.endTimeSecs != null) && Math.abs(spans - played) > 0.5) {
    problems.push(`stints add to ${fmt(spans)} but the quarter played ${fmt(played)}`);
  }
  if (problems.length) {
    return fail('NOT SAVED — the result does not hold together:\n  ' + problems.join('\n  ') +
                '\nReload the page to discard these in-memory changes.');
  }

  if (where === 'live') {
    localStorage.setItem('pt_live_session', JSON.stringify(session));
  } else {
    saved[index] = session;
    localStorage.setItem('pt_sessions', JSON.stringify(saved));
  }
  console.log('%csaved — reloading so every view recomputes from it', 'color:#22c55e;font-weight:700');
  setTimeout(() => location.reload(), 400);
  return { session: session.title, quarter: o.quarter, sub: fmt(B), added: fmt(total), applied: true };
};

console.log('%camendQuarterClock() ready — run it for a dry run, then { apply: true }.',
            'color:#6366f1;font-weight:700');
