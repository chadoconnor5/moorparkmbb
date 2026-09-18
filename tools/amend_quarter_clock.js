/* Amend a quarter whose game clock was not running for part of it.
   ────────────────────────────────────────────────────────────────
   Paste into the browser console on the practice tracker, then run:

     amendQuarterClock()                 // dry run — full before/after, changes nothing
     amendQuarterClock({ apply: true })  // writes it and reloads the page

   Works before or after End Practice. Run it after, and it refreshes the frozen stat
   lines too (see 6) — run it before, and End Practice computes them from amended data.

   WHY THIS EXISTS. The tracker measures a stint as a span of the DOWN-counting game
   clock: stintSeconds() is startTimeSecs - endTimeSecs. Time played while the clock was
   stopped is therefore invisible to it, and no screen in the app can add it back — the
   quarter-setup duration is asked once, before the quarter, and the only after-the-fact
   lever (Amend Quarter End Clock) moves the END, which would rob the LAST stint to pay
   an earlier one. Lengthening the quarter is the only honest repair.

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

   WHAT MOVES. Lineup minutes and player minutes are read off lineupSegments every render,
   so they follow on their own. The quarter's played time and the scrimmage total come
   from duration/playedDuration, which this updates. Stat LINES are different: computed
   once at End Practice and stored, so a completed session gets teamStats and playerStats
   recomputed here, the same pair and the same order repairInvertedStints() uses.

   Nothing touches the event log's order or its film times. Plus/minus and the possession
   counts read event ADJACENCY, not the clock, so they are unchanged by construction. */

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
    reload:      true,                  // false to keep the page up and chain another repair
  }, opts || {});

  /* The split is the film's, not a guess: each five is credited with the untimed seconds it
     was actually on the floor for. Rounded to whole seconds, which is what the clock boxes
     and every minutes figure show anyway. */
  if (o.before == null) o.before = Math.round(o.subFilmTs - o.pausedFilmTs);
  if (o.after  == null) o.after  = Math.round(o.restartFilmTs - o.subFilmTs);

  const fmt = s => {
    if (s == null || !isFinite(s)) return '—';
    const t = Math.round(s), a = Math.abs(t);
    return (t < 0 ? '-' : '') + Math.floor(a / 60) + ':' + String(a % 60).padStart(2, '0');
  };
  const film = s => s == null ? 'no film' : fmt(s);
  const fail = msg => { console.error('%camendQuarterClock: ' + msg, 'color:#ef4444;font-weight:700'); return null; };
  if (!(o.before >= 0) || !(o.after >= 0)) return fail('the film marks are out of order — paused < sub < restart.');

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
    /* Ending the practice moves it from the live slot into the saved list. Seeing it in
       both means End Practice left the live copy behind — say which is which rather than
       guessing, because amending the abandoned one would look like it worked. */
    return fail('matched ' + pool.length + ' copies: ' +
      pool.map(p => `${p.session.title} [${p.where}]`).join(', ') +
      '. Pass session: "<exact id>" for the one you mean.');
  }
  const { where, index } = pool[0];
  const before = pool[0].session;
  const s = JSON.parse(JSON.stringify(before));   // everything happens on a copy until it is proven

  /* ── 2. The quarter, its segments and its subs ── */
  const q = (s.quarters || [])[o.quarter - 1];
  if (!q) return fail(`Q${o.quarter} has not been ended yet — end it first, then amend it.`);
  if (q.clockAmend && !o.force) {
    return fail(`Q${o.quarter} already carries an amendment (${JSON.stringify(q.clockAmend)}). Pass force:true to redo it.`);
  }
  const segs = (s.lineupSegments || []).filter(g => g.quarter === o.quarter);
  if (!segs.length) return fail(`Q${o.quarter} has no lineup stints.`);
  const subs = (s.eventLog || []).filter(e => e.type === 'sub' && e.quarter === o.quarter && e.timeSecs != null);

  /* ── 3. The sub that splits the untimed stretch ── */
  let target = null;
  if (o.subClock != null) {
    target = subs.find(e => e.timeSecs === o.subClock);
    if (!target) return fail(`no Q${o.quarter} sub at ${fmt(o.subClock)}. Subs: ${subs.map(e => fmt(e.timeSecs)).join(', ')}`);
  } else {
    const withFilm = subs.filter(e => e.videoTs != null);
    if (!withFilm.length) return fail(`no Q${o.quarter} sub carries a film time — pin it with subClock instead.`);
    target = withFilm.reduce((best, e) =>
      Math.abs(e.videoTs - o.subFilmTs) < Math.abs(best.videoTs - o.subFilmTs) ? e : best);
    const off = Math.abs(target.videoTs - o.subFilmTs);
    if (off > 30) return fail(`nearest Q${o.quarter} sub to film ${film(o.subFilmTs)} is ${film(target.videoTs)} — ${fmt(off)} away. Wrong session or wrong mark.`);
  }
  const B = target.timeSecs;

  /* The boundary has to exist on BOTH sides or the shift would tear the chain apart. */
  if (!segs.some(g => g.startTimeSecs === B) || !segs.some(g => g.endTimeSecs === B)) {
    return fail(`the sub at ${fmt(B)} does not line up with a stint boundary` +
      ` (starts: ${segs.map(g => fmt(g.startTimeSecs)).join(', ')} | ends: ${segs.map(g => fmt(g.endTimeSecs)).join(', ')}).`);
  }
  /* One sub inside the stretch is what this splits. A second one means a third five was
     out there and the arithmetic would hand its seconds to somebody else. */
  const inside = subs.filter(e => e !== target && e.videoTs != null
                              && e.videoTs > o.pausedFilmTs && e.videoTs < o.restartFilmTs);
  if (inside.length) {
    return fail('another sub sits inside the untimed stretch, at film ' +
      inside.map(e => film(e.videoTs)).join(' and ') +
      ' — more than two fives shared that time, so the split has to be worked out by hand.');
  }

  /* ── 4. Shift the clock ── */
  const total = o.before + o.after;
  const shift = v => (v == null ? v : v > B ? v + total : v === B ? v + o.after : v);
  segs.forEach(g => { g.startTimeSecs = shift(g.startTimeSecs); g.endTimeSecs = shift(g.endTimeSecs); });
  subs.forEach(e => { e.timeSecs = shift(e.timeSecs); });
  q.duration = q.duration + total;
  q.playedDuration = (q.timeRemaining != null)
    ? Math.max(0, q.duration - q.timeRemaining)
    : (q.playedDuration != null ? q.playedDuration + total : q.playedDuration);
  q.clockAmend = { before: o.before, after: o.after, atClock: B, appliedAt: new Date().toISOString() };

  /* ── 5. Invariants, before anything is stored ── */
  const problems = [];
  segs.forEach(g => {
    if (g.endTimeSecs != null && g.endTimeSecs > g.startTimeSecs) problems.push(`stint ${fmt(g.startTimeSecs)} → ${fmt(g.endTimeSecs)} runs backwards`);
  });
  subs.forEach(e => {
    if (!segs.some(g => g.startTimeSecs === e.timeSecs)) problems.push(`sub at ${fmt(e.timeSecs)} no longer opens a stint — event attribution would drift`);
  });
  const spans = segs.filter(g => g.endTimeSecs != null).reduce((n, g) => n + (g.startTimeSecs - g.endTimeSecs), 0);
  const played = Math.max(0, q.duration - (q.timeRemaining || 0));
  if (segs.every(g => g.endTimeSecs != null) && Math.abs(spans - played) > 0.5) {
    problems.push(`stints add to ${fmt(spans)} but the quarter played ${fmt(played)}`);
  }
  if (problems.length) return fail('NOT SAVED — the result does not hold together:\n  ' + problems.join('\n  '));

  /* ── 6. Stat lines are frozen at End Practice, so a completed session needs them redone.
         teamStats first: computePlayerStats() divides by it. ── */
  let recomputed = false;
  const isCompleted = !!(s.completed || (s.playerStats && Object.keys(s.playerStats).length));
  if (isCompleted) {
    if (typeof computeTeamStats === 'function' && typeof computePlayerStats === 'function') {
      s.teamStats   = computeTeamStats(s);
      s.playerStats = computePlayerStats(s);
      recomputed = true;
    } else {
      return fail('this session is finalised and its stored stat lines need recomputing, but ' +
                  'computeTeamStats/computePlayerStats are not on this page. Run this in the console ' +
                  'ON THE TRACKER, not anywhere else.');
    }
  }

  /* ── 7. Report: stints, the players whose minutes moved, and the totals ── */
  const secsFor = (sess, name, team) => (typeof calcPlayerSeconds === 'function')
    ? calcPlayerSeconds(sess, name, team)
    : (sess.lineupSegments || []).reduce((n, g) => {
        if (g.endTimeSecs == null || g.endTimeSecs > g.startTimeSecs) return n;
        const lu = team === 'a' ? g.lineupA : g.lineupB;
        return (lu || []).includes(name) ? n + (g.startTimeSecs - g.endTimeSecs) : n;
      }, 0);
  const sessionSecs = sess => (sess.quarters || []).reduce((n, x) => {
    const d = Math.max(0, Number(x.duration) || 0);
    const p = x.playedDuration != null ? Math.min(Math.max(0, Number(x.playedDuration) || 0), d || Infinity)
                                       : Math.max(0, d - Math.max(0, Math.min(Number(x.timeRemaining) || 0, d)));
    return n + p;
  }, 0);

  const stintRow = g => ({
    'stint':  `${fmt(g.startTimeSecs)} → ${fmt(g.endTimeSecs)}`,
    'length': fmt(g.startTimeSecs != null && g.endTimeSecs != null ? g.startTimeSecs - g.endTimeSecs : null),
    [s.teamAName || 'White']: (g.lineupA || []).join(', '),
    [s.teamBName || 'Black']: (g.lineupB || []).join(', '),
  });

  console.log(`%c${s.title} — Q${o.quarter}  (${where === 'live' ? 'in progress' : 'saved'}${isCompleted ? ', finalised' : ''})`,
              'font-weight:700;font-size:13px');
  console.log(`sub that splits it: ${fmt(B)} on the clock, film ${film(target.videoTs)}` +
              (target.subs || []).map(p => `  ${p.playerOut} → ${p.playerIn}`).join(''));
  console.log(`clock stopped at film ${film(o.pausedFilmTs)}, running again at ${film(o.restartFilmTs)}` +
              ` — ${fmt(total)} of play the quarter never counted`);
  console.log(`adding ${fmt(o.before)} to the five before the sub, ${fmt(o.after)} to the five after`);

  console.log('%cLINEUP STINTS — before', 'font-weight:700');
  console.table((before.lineupSegments || []).filter(g => g.quarter === o.quarter).map(stintRow));
  console.log('%cLINEUP STINTS — after', 'font-weight:700');
  console.table(segs.map(stintRow));

  const rows = [];
  for (const team of ['a', 'b']) {
    const names = new Set();
    (before.lineupSegments || []).forEach(g => ((team === 'a' ? g.lineupA : g.lineupB) || []).forEach(n => names.add(n)));
    (s.lineupSegments || []).forEach(g => ((team === 'a' ? g.lineupA : g.lineupB) || []).forEach(n => names.add(n)));
    for (const name of names) {
      const was = secsFor(before, name, team), now = secsFor(s, name, team);
      if (Math.abs(now - was) < 0.5) continue;
      rows.push({ player: name, team: (team === 'a' ? s.teamAName : s.teamBName) || team.toUpperCase(),
                  before: fmt(was), after: fmt(now), gained: fmt(now - was) });
    }
  }
  console.log('%cPLAYER MINUTES — only those that moved', 'font-weight:700');
  console.table(rows.sort((x, y) => x.team.localeCompare(y.team) || x.player.localeCompare(y.player)));

  const qWas = (before.quarters || [])[o.quarter - 1] || {};
  console.log('%cTOTALS', 'font-weight:700');
  console.table([
    { what: `Q${o.quarter} length`, before: fmt(qWas.duration), after: fmt(q.duration) },
    { what: `Q${o.quarter} played`, before: fmt(Math.max(0, (qWas.duration || 0) - (qWas.timeRemaining || 0))), after: fmt(played) },
    { what: 'scrimmage total',      before: fmt(sessionSecs(before)), after: fmt(sessionSecs(s)) },
  ]);
  if (recomputed) console.log('stat lines (MIN, MIN%, and every rate that divides by minutes) recomputed for this session');

  if (!o.apply) {
    console.log('%cdry run — nothing written. Run amendQuarterClock({ apply: true }) to commit it.',
                'color:#f59e0b;font-weight:700');
    return { session: s.title, quarter: o.quarter, sub: fmt(B), added: fmt(total), applied: false };
  }

  /* ── 8. Store it, and keep the in-memory copy in step so a later save cannot undo this ── */
  /* `State` is a script-scope const, so it is NOT window.State — reaching for it there
     finds nothing on a page that has it, and the tracker's stale in-memory copy would be
     written back over this by its next save. */
  const APP = (typeof State !== 'undefined' && State) ? State : null;
  if (where === 'live') {
    localStorage.setItem('pt_live_session', JSON.stringify(s));
    if (APP && APP.liveSession && APP.liveSession.id === s.id) APP.liveSession = s;
  } else {
    saved[index] = s;
    localStorage.setItem('pt_sessions', JSON.stringify(saved));
    if (APP && Array.isArray(APP.sessions)) {
      const i = APP.sessions.findIndex(x => x.id === s.id);
      if (i !== -1) APP.sessions[i] = s;
    }
  }
  console.log('%csaved', 'color:#22c55e;font-weight:700');
  if (isCompleted) console.log('%cre-publish (↑ Publish) to push this to the live site', 'color:#6366f1;font-weight:700');
  if (o.reload) setTimeout(() => location.reload(), 400);
  else console.log('page left up — run the next repair, then reload when you are done');
  return { session: s.title, quarter: o.quarter, sub: fmt(B), added: fmt(total), applied: true, statsRecomputed: recomputed };
};

/* ── Drop a quarter that was started by accident ───────────────────────────────
   Ending the last quarter instead of ending the practice opens the next one, and it is
   recorded the moment it opens: a quarters[] entry with nothing played and a lineup stint
   that starts and ends on the same tick. Nobody was on the floor, so no minutes are wrong
   — but the session reads as one quarter longer than it was, and the phantom five turns up
   wherever stints are counted.

     dropEmptyQuarter({ quarter: 8 })                 // dry run
     dropEmptyQuarter({ quarter: 8, apply: true })    // writes it

   Only ever the LAST quarter, and only when it is provably empty: renumbering a middle one
   would move every event and stint after it. */
window.dropEmptyQuarter = function dropEmptyQuarter(opts) {
  const o = Object.assign({
    session: /#\s*27\b/i,
    quarter: null,          // defaults to the last recorded quarter
    apply:   false,
    reload:  true,
  }, opts || {});

  const fmt = s => {
    if (s == null || !isFinite(s)) return '—';
    const t = Math.round(s), a = Math.abs(t);
    return (t < 0 ? '-' : '') + Math.floor(a / 60) + ':' + String(a % 60).padStart(2, '0');
  };
  const fail = msg => { console.error('%cdropEmptyQuarter: ' + msg, 'color:#ef4444;font-weight:700'); return null; };

  let live = null;
  try { live = JSON.parse(localStorage.getItem('pt_live_session') || 'null'); } catch (e) {}
  let saved = [];
  try { saved = JSON.parse(localStorage.getItem('pt_sessions') || '[]') || []; } catch (e) {}
  const matches = x => {
    if (!x) return false;
    if (o.session instanceof RegExp) return o.session.test(x.title || '');
    return x.id === o.session || String(x.title || '').includes(o.session);
  };
  const pool = [];
  if (matches(live)) pool.push({ where: 'live', session: live });
  saved.forEach((x, i) => { if (matches(x)) pool.push({ where: 'saved', index: i, session: x }); });
  if (!pool.length) {
    const names = [live, ...saved].filter(Boolean).map(x => `${x.title} (${x.date})`);
    return fail('no session matched ' + o.session + '. Sessions in this browser:\n  ' + names.join('\n  '));
  }
  if (pool.length > 1) {
    return fail('matched ' + pool.length + ' copies: ' + pool.map(x => `${x.session.title} [${x.where}]`).join(', ') +
                '. Pass session: "<exact id>" for the one you mean.');
  }
  const { where, index } = pool[0];
  const before = pool[0].session;
  const s = JSON.parse(JSON.stringify(before));

  const qs = s.quarters || [];
  if (!qs.length) return fail('this session has no recorded quarters.');
  const qNum = o.quarter == null ? (qs[qs.length - 1].number || qs.length) : o.quarter;
  const at = qs.findIndex(x => (x.number || 0) === qNum);
  if (at === -1) return fail(`Q${qNum} is not recorded. Quarters: ${qs.map(x => x.number).join(', ')}`);
  if (at !== qs.length - 1) {
    return fail(`Q${qNum} is not the last quarter — dropping it would renumber everything after it. ` +
                'A quarter in the middle has to be dealt with by hand.');
  }

  /* Three separate proofs that nothing happened in it. Any one of them failing means real
     basketball is in there, and this is not the tool for it. */
  const evs  = (s.eventLog || []).filter(e => e.quarter === qNum);
  const segs = (s.lineupSegments || []).filter(g => g.quarter === qNum);
  const q    = qs[at];
  const played = q.playedDuration != null ? q.playedDuration
               : Math.max(0, (q.duration || 0) - (q.timeRemaining != null ? q.timeRemaining : q.duration || 0));
  const alive = segs.filter(g => g.endTimeSecs != null && g.endTimeSecs !== g.startTimeSecs);
  if (evs.length) return fail(`Q${qNum} holds ${evs.length} event${evs.length === 1 ? '' : 's'} — it was played, not opened by mistake.`);
  if (played > 0) return fail(`Q${qNum} has ${fmt(played)} played on the clock — not an empty quarter.`);
  if (alive.length) return fail(`Q${qNum} has a stint with elapsed time (${alive.map(g => `${fmt(g.startTimeSecs)} → ${fmt(g.endTimeSecs)}`).join(', ')}).`);

  console.log(`%c${s.title} — dropping Q${qNum}  (${where === 'live' ? 'in progress' : 'saved'})`,
              'font-weight:700;font-size:13px');
  console.table([{
    'quarter':  `Q${qNum}`,
    'length':   fmt(q.duration),
    'played':   fmt(played),
    'events':   evs.length,
    'stints':   segs.length,
    'the five': segs.length ? (segs[0].lineupA || []).join(', ') + ' / ' + (segs[0].lineupB || []).join(', ') : '—',
  }]);

  s.quarters = qs.filter((_, i) => i !== at);
  s.lineupSegments = (s.lineupSegments || []).filter(g => g.quarter !== qNum);

  let recomputed = false;
  const isCompleted = !!(s.completed || (s.playerStats && s.playerStats.length));
  if (isCompleted) {
    if (typeof computeTeamStats === 'function' && typeof computePlayerStats === 'function') {
      s.teamStats   = computeTeamStats(s);      // must precede playerStats — it divides by it
      s.playerStats = computePlayerStats(s);
      recomputed = true;
    } else {
      return fail('this session is finalised and needs its stat lines recomputed, but ' +
                  'computeTeamStats/computePlayerStats are not on this page. Run this ON THE TRACKER.');
    }
  }

  const totalOf = sess => (sess.quarters || []).reduce((n, x) => n + (x.playedDuration != null
    ? x.playedDuration : Math.max(0, (x.duration || 0) - (x.timeRemaining || 0))), 0);
  console.table([
    { what: 'quarters', before: (before.quarters || []).length, after: s.quarters.length },
    { what: 'lineup stints', before: (before.lineupSegments || []).length, after: s.lineupSegments.length },
    { what: 'scrimmage total', before: fmt(totalOf(before)), after: fmt(totalOf(s)) },
  ]);

  if (!o.apply) {
    console.log('%cdry run — nothing written. Add apply: true to commit it.', 'color:#f59e0b;font-weight:700');
    return { session: s.title, dropped: `Q${qNum}`, applied: false };
  }

  const APP = (typeof State !== 'undefined' && State) ? State : null;
  if (where === 'live') {
    localStorage.setItem('pt_live_session', JSON.stringify(s));
    if (APP && APP.liveSession && APP.liveSession.id === s.id) APP.liveSession = s;
  } else {
    saved[index] = s;
    localStorage.setItem('pt_sessions', JSON.stringify(saved));
    if (APP && Array.isArray(APP.sessions)) {
      const i = APP.sessions.findIndex(x => x.id === s.id);
      if (i !== -1) APP.sessions[i] = s;
    }
  }
  console.log('%csaved', 'color:#22c55e;font-weight:700');
  if (isCompleted) console.log('%cre-publish (↑ Publish) to push this to the live site', 'color:#6366f1;font-weight:700');
  if (o.reload) setTimeout(() => location.reload(), 400);
  return { session: s.title, dropped: `Q${qNum}`, applied: true, statsRecomputed: recomputed };
};

/* ── Both repairs for Fall Workout #27, in one command ────────────────────────
     fixWorkout27()                 // dry run — every table from both repairs
     fixWorkout27({ apply: true })  // writes both, reloads once

   Q2's clock was stopped from film 105:53 to 108:38 and the sub at 108:17.1 divides
   that stretch; Q8 was opened by ending Q7 instead of ending the practice. Both are
   dry-run first and NEITHER is written unless both come back clean, so a session
   cannot end up half-repaired by a guard that only trips on the second one. */
window.fixWorkout27 = function fixWorkout27(opts) {
  const o = Object.assign({ session: /#\s*27\b/i, dropQuarter: 8, apply: false }, opts || {});
  const pins = { session: o.session, quarter: 2,
                 pausedFilmTs: 105 * 60 + 53, subFilmTs: 108 * 60 + 17.1, restartFilmTs: 108 * 60 + 38 };

  console.log('%c1 of 2 — Q2, the stretch the clock sat out', 'font-weight:700;font-size:13px;color:#6366f1');
  if (!amendQuarterClock(Object.assign({}, pins, { apply: false }))) return null;
  console.log('%c2 of 2 — the quarter that opened itself', 'font-weight:700;font-size:13px;color:#6366f1');
  if (!dropEmptyQuarter({ session: o.session, quarter: o.dropQuarter, apply: false })) return null;

  if (!o.apply) {
    console.log('%cdry run — nothing written. Run fixWorkout27({ apply: true }) to commit both.',
                'color:#f59e0b;font-weight:700');
    return { applied: false };
  }

  const a = amendQuarterClock(Object.assign({}, pins, { apply: true, reload: false }));
  if (!a) { console.error('%cthe Q2 amendment did not go through — nothing was written, Q8 left alone.',
                          'color:#ef4444;font-weight:700'); return null; }
  const d = dropEmptyQuarter({ session: o.session, quarter: o.dropQuarter, apply: true, reload: false });
  if (!d) { console.error('%cQ2 IS AMENDED AND SAVED, but Q8 was not dropped — read the reason above, ' +
                          'then run dropEmptyQuarter({ quarter: ' + o.dropQuarter + ', apply: true }) on its own.',
                          'color:#ef4444;font-weight:700'); return null; }

  console.log('%cboth done — reloading, then re-publish (↑ Publish) to update the site',
              'color:#22c55e;font-weight:700;font-size:13px');
  setTimeout(() => location.reload(), 600);
  return { applied: true, amended: a, dropped: d };
};

console.log('%cfixWorkout27() ready — dry run first, then { apply: true }. ' +
            'amendQuarterClock() and dropEmptyQuarter() are here too, for anything else.',
            'color:#6366f1;font-weight:700');
