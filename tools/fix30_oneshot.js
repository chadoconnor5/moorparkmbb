/* Fall Workout #30 — paste into the tracker console. Rebuilds Q1-Q2 with the 1:32 reset, drops the empty Q8, recomputes stats, saves and reloads. Comment-free copy of tools/clock_reset_fix.js; a second paste is a no-op. */
var CLOCK_RESET_FIX = {
  date:          '2026-09-23',
  title:         /#\s*30\b/,
  q1SubFilm:     2 * 3600 + 4 * 60 + 50.2,
  q2StartFilm:   2 * 3600 + 8 * 60 + 11.1,
  subFilmTs:     2 * 3600 + 11 * 60 + 8.4,
  resetFilmTs:   2 * 3600 + 11 * 60 + 20,
  resetFrom:     268,
  resetTo:       360,
  ADD:           92,
  quarterLength: 512,
};
function repairClockReset(original, opts) {
  const o = Object.assign({}, CLOCK_RESET_FIX, opts || {});
  const f = x => {
    if (x == null || !isFinite(x)) return '—';
    const t = Math.round(x), a = Math.abs(t);
    return (t < 0 ? '-' : '') + Math.floor(a / 60) + ':' + String(a % 60).padStart(2, '0');
  };
  const film = x => x == null ? 'no film'
    : `${Math.floor(x / 3600)}:${String(Math.floor((x % 3600) / 60)).padStart(2, '0')}:${(x % 60).toFixed(1).padStart(4, '0')}`;
  const stop = m => { throw new Error(m); };
  const s = JSON.parse(JSON.stringify(original));
  const log = s.eventLog || [], all = s.lineupSegments || [];
  const qs = s.quarters || [];
  const q1 = qs.find(x => x.number === 1), q2 = qs.find(x => x.number === 2);
  if (!q1 || !q2) stop('Q1 and Q2 have to be ended before this can run.');
  if (q2.clockReset && !o.force) {
    const e = new Error(`already repaired — Q2 carries ${JSON.stringify(q2.clockReset)}.`);
    e.alreadyDone = true;
    throw e;
  }
  if (q2.duration !== 420 || q2.timeRemaining !== 0) stop(`Q2 reads ${f(q2.duration)} ending ${f(q2.timeRemaining)}, expected 7:00 ending 0:00.`);
  const subAt = (film_, clock, label) => {
    const hits = log.filter(e => e.type === 'sub' && e.videoTs != null && Math.abs(e.videoTs - film_) < 0.5);
    if (hits.length !== 1) stop(`expected one sub at film ${film(film_)} (${label}), found ${hits.length}.`);
    if (hits[0].timeSecs !== clock) stop(`the ${label} sub at film ${film(film_)} reads ${f(hits[0].timeSecs)}, expected ${f(clock)}.`);
    return hits[0];
  };
  const misfiled = subAt(o.q1SubFilm, 99, 'Johnson → Niles');
  const q2Start  = subAt(o.q2StartFilm, 420, 'start of Q2');
  const target   = subAt(o.subFilmTs, o.resetFrom, 'reset');
  if (misfiled.quarter !== 2) stop(`the 1:39 sub is filed under Q${misfiled.quarter}, expected Q2 — the data is not what this was written for.`);
  if (q2Start.quarter !== 2 || target.quarter !== 2) stop('the start-of-Q2 or reset sub is not in Q2.');
  const mi = log.indexOf(misfiled);
  const near = [log[mi - 1], log[mi + 1]].filter(e => e && e.type !== 'sub');
  if (!near.length || near.some(e => e.quarter !== 1)) stop('the 1:39 sub is not sitting among Q1 plays.');
  const ti = log.indexOf(target);
  const lateSub = log.find((e, i) => e.type === 'sub' && e.quarter === 2 && i > ti && e.videoTs != null && e.videoTs < o.resetFilmTs);
  if (lateSub) stop(`another sub sits between the 4:28 sub and the reset (film ${film(lateSub.videoTs)}).`);
  for (let i = 1; i < all.length; i++) {
    if ((all[i].quarter || 0) < (all[i - 1].quarter || 0)) stop('lineup stints are not stored in quarter order — needs a look by hand.');
  }
  const beforeRows = all.filter(g => g.quarter <= 2).map(g => `Q${g.quarter} ${f(g.startTimeSecs)} → ${f(g.endTimeSecs)}`);
  misfiled.quarter = 1;
  q2.duration = o.quarterLength;
  const clockOf = (e, i) => (e.quarter === 2 && i <= ti) ? e.timeSecs + o.ADD : e.timeSecs;
  let A = [...(s.startersA || [])], B = [...(s.startersB || [])];
  const rebuilt = [];
  for (const q of [q1, q2]) {
    const Q = q.number;
    let open = { quarter: Q, lineupA: [...A], lineupB: [...B], startTimeSecs: q.duration, endTimeSecs: null };
    let played = false;
    log.forEach((e, i) => {
      if (e.quarter !== Q) return;
      if (e.type !== 'sub') { played = true; return; }
      const clock = clockOf(e, i);
      for (const sp of (e.subs && e.subs.length ? e.subs : [{ team: e.team, playerOut: e.playerOut, playerIn: e.playerIn }])) {
        const lu = (sp.team || e.team) === 'a' ? A : B;
        const k = lu.indexOf(sp.playerOut);
        if (k === -1) stop(`Q${Q} sub at film ${film(e.videoTs)}: ${sp.playerOut} is not on the floor for ${sp.team === 'a' ? 'White' : 'Black'}.`);
        if (lu.includes(sp.playerIn)) stop(`Q${Q} sub at film ${film(e.videoTs)}: ${sp.playerIn} is already on the floor.`);
        lu[k] = sp.playerIn;
      }
      e.timeSecs = clock;
      if (clock === open.startTimeSecs && !played) {
        open.lineupA = [...A]; open.lineupB = [...B];      // absorbed: same five's stint, corrected
        e.startOfStint = true;
      } else {
        if (clock > open.startTimeSecs) stop(`Q${Q} sub at film ${film(e.videoTs)} reads ${f(clock)}, after a stint that opened at ${f(open.startTimeSecs)}.`);
        open.endTimeSecs = clock;
        rebuilt.push(open);
        open = { quarter: Q, lineupA: [...A], lineupB: [...B], startTimeSecs: clock, endTimeSecs: null };
        e.startOfStint = false;
        played = false;
      }
    });
    open.endTimeSecs = q.timeRemaining || 0;
    rebuilt.push(open);
  }
  q2.playedDuration = Math.max(0, q2.duration - (q2.timeRemaining || 0));
  q2.clockReset = { added: o.ADD, atClock: o.resetFrom, subFilmTs: target.videoTs, resetFilmTs: o.resetFilmTs,
                    rebuiltQ1Q2: true, movedSubToQ1: misfiled.videoTs, appliedAt: new Date().toISOString() };
  s.lineupSegments = [...rebuilt, ...all.filter(g => g.quarter > 2)];
  const bad = [];
  for (const q of [q1, q2]) {
    const segs = rebuilt.filter(g => g.quarter === q.number);
    if (segs[0].startTimeSecs !== q.duration) bad.push(`Q${q.number} first stint starts ${f(segs[0].startTimeSecs)}, quarter is ${f(q.duration)}`);
    segs.forEach((g, i) => {
      if (g.endTimeSecs > g.startTimeSecs) bad.push(`Q${q.number} stint ${f(g.startTimeSecs)} → ${f(g.endTimeSecs)} runs backwards`);
      if (i && segs[i - 1].endTimeSecs !== g.startTimeSecs) bad.push(`Q${q.number} stints do not meet at ${f(g.startTimeSecs)}`);
      for (const lu of [g.lineupA, g.lineupB]) if (new Set(lu).size !== 5) bad.push(`Q${q.number} stint ${f(g.startTimeSecs)} does not have five different players`);
    });
    const span = segs.reduce((n, g) => n + g.startTimeSecs - g.endTimeSecs, 0);
    const playedQ = q.playedDuration != null ? q.playedDuration : q.duration - (q.timeRemaining || 0);
    if (span !== playedQ) bad.push(`Q${q.number} stints add to ${f(span)} but it played ${f(playedQ)}`);
    log.filter(e => e.type === 'sub' && e.quarter === q.number && !e.startOfStint).forEach(e => {
      if (!segs.some(g => g.startTimeSecs === e.timeSecs)) bad.push(`Q${q.number} sub at film ${film(e.videoTs)} does not open a stint`);
    });
  }
  if (q2.duration !== o.quarterLength || q2.playedDuration !== o.quarterLength) bad.push(`Q2 is ${f(q2.duration)} long with ${f(q2.playedDuration)} played, expected 8:32 and 8:32`);
  const endQ2 = all.filter(g => g.quarter === 2).pop();
  const same = (x, y) => x.length === y.length && x.every(n => y.includes(n));
  if (endQ2 && !(same(A, endQ2.lineupA) && same(B, endQ2.lineupB))) {
    bad.push(`the replay ends Q2 with ${A.join(', ')} / ${B.join(', ')}, but the tracker ended it with ${endQ2.lineupA.join(', ')} / ${endQ2.lineupB.join(', ')}`);
  }
  if (bad.length) stop('NOT SAVED — the result does not hold together:\n  ' + bad.join('\n  '));
  const crossing = rebuilt.find(g => g.quarter === 2 && g.startTimeSecs === o.resetTo);
  return {
    session: s,
    report: {
      title: s.title, quarter: 2, add: o.ADD, beforeRows,
      crossing: crossing ? { lineupA: crossing.lineupA, lineupB: crossing.lineupB } : null,
      stints: rebuilt.map(g => ({
        stint:  `Q${g.quarter} ${f(g.startTimeSecs)} → ${f(g.endTimeSecs)}`,
        length: f(g.startTimeSecs - g.endTimeSecs),
        White:  g.lineupA.join(', '),
        Black:  g.lineupB.join(', '),
      })),
      quarterWas: { duration: 420, played: 420, remaining: 0 },
      quarterNow: { duration: q2.duration, played: q2.playedDuration, remaining: q2.timeRemaining },
      fmt: f,
    },
  };
}
function dropPhantomQuarter(s) {
  const f = x => {
    if (x == null || !isFinite(x)) return '—';
    const t = Math.round(x), a = Math.abs(t);
    return Math.floor(a / 60) + ':' + String(a % 60).padStart(2, '0');
  };
  const qs = s.quarters || [], segs = s.lineupSegments || [], log = s.eventLog || [];
  const recorded = qs.length ? Math.max(...qs.map(x => x.number || 0)) : 0;
  const lastSegQ = segs.length ? Math.max(...segs.map(g => g.quarter || 0)) : 0;
  const Q = Math.max(recorded, lastSegQ);
  if (!Q) return null;
  const evs = log.filter(e => e.quarter === Q);
  if (evs.length) return null;
  if (!s.completed && segs.some(g => g.quarter === Q && g.endTimeSecs == null)) {
    throw new Error(`Q${Q} is still open on the live clock — press End Practice first (any clock), then paste this again.`);
  }
  const at = qs.findIndex(x => x.number === Q);
  if (at !== -1 && at !== qs.length - 1) throw new Error(`Q${Q} is not the last recorded quarter — needs a look by hand.`);
  const mine = segs.filter(g => g.quarter === Q);
  if (mine.length > 1) throw new Error(`Q${Q} has ${mine.length} stints but no subs — does not look like an accidental quarter.`);
  const q = at !== -1 ? qs[at] : null;
  const removed = {
    quarter: Q,
    length:  q ? f(q.duration) : '—',
    played:  q ? f(q.playedDuration != null ? q.playedDuration : (q.duration || 0) - (q.timeRemaining || 0)) : '—',
    stint:   mine.length ? `${f(mine[0].startTimeSecs)} → ${f(mine[0].endTimeSecs)}` : '—',
  };
  if (at !== -1) qs.splice(at, 1);
  s.lineupSegments = segs.filter(g => g.quarter !== Q);
  return removed;
}
function repairTonight(original, opts) {
  let s = original, clock = null, clockDone = false;
  try {
    const out = repairClockReset(original, opts);
    s = out.session; clock = out.report;
  } catch (e) {
    if (!e.alreadyDone) throw e;
    s = JSON.parse(JSON.stringify(original));
    clockDone = true;
  }
  const dropped = dropPhantomQuarter(s);
  if (clockDone && !dropped) {
    const e = new Error('already repaired — the clock is fixed and there is no empty quarter left. Nothing to do.');
    e.alreadyDone = true;
    throw e;
  }
  return { session: s, clock, clockDone, dropped };
}
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
  module.exports = { repairClockReset, dropPhantomQuarter, repairTonight, clockResetMinutes, CLOCK_RESET_FIX };
} else if (typeof window !== 'undefined' && !window.__clockResetNoAutorun) {
  (() => {
    const stop = m => { console.error('%cclock reset fix: ' + m, 'color:#ef4444;font-weight:700'); return null; };
    let saved = [], live = null;
    try { saved = JSON.parse(localStorage.getItem('pt_sessions') || '[]') || []; } catch (e) {}
    try { live  = JSON.parse(localStorage.getItem('pt_live_session') || 'null'); } catch (e) {}
    const hit = x => x && x.date === CLOCK_RESET_FIX.date && CLOCK_RESET_FIX.title.test(x.title || '');
    const idx = saved.findIndex(hit);
    if (idx !== -1 && saved.findIndex((x, i) => i > idx && hit(x)) !== -1) return stop(`more than one saved session is dated ${CLOCK_RESET_FIX.date}.`);
    const where = idx !== -1 ? 'saved' : (hit(live) ? 'live' : null);
    if (!where) return stop(`no session dated ${CLOCK_RESET_FIX.date} in this browser.`);
    if (idx !== -1 && hit(live)) return stop('tonight is in BOTH the saved list and the live slot. Tell Claude before going further.');
    const orig = where === 'saved' ? saved[idx] : live;
    let out;
    try { out = repairTonight(orig); } catch (e) { return stop(e.message); }
    const s = out.session, r = out.clock;
    const f = x => { if (x == null || !isFinite(x)) return '—'; const t = Math.round(x), a = Math.abs(t);
                     return (t < 0 ? '-' : '') + Math.floor(a / 60) + ':' + String(a % 60).padStart(2, '0'); };
    const finalised = !!(s.completed || (s.playerStats && Object.keys(s.playerStats).length));
    if (finalised) {
      if (typeof computeTeamStats !== 'function' || typeof computePlayerStats !== 'function')
        return stop('run this on the tracker page — its stat functions are not here.');
      s.teamStats   = computeTeamStats(s);
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
    if (r) {
      console.log(`%cFIXED — ${r.title}, Q${r.quarter}: +${f(r.add)} to the five on for the clock reset`,
                  'color:#22c55e;font-weight:700;font-size:13px');
      console.table(r.stints);
      console.table(clockResetMinutes(orig, s).map(x => ({ player: x.player, team: x.team, was: f(x.was), now: f(x.now), gained: f(x.now - x.was) })));
      console.table([
        { what: `Q${r.quarter} length`, before: f(r.quarterWas.duration), after: f(r.quarterNow.duration) },
        { what: `Q${r.quarter} played`, before: f(r.quarterWas.played),   after: f(r.quarterNow.played) },
      ]);
    } else {
      console.log('%cclock reset already repaired — left as it is', 'color:#6366f1;font-weight:700');
    }
    if (out.dropped) {
      console.log(`%cDROPPED — Q${out.dropped.quarter}, the quarter opened by accident (nothing was logged in it)`,
                  'color:#22c55e;font-weight:700;font-size:13px');
      console.table([out.dropped]);
    } else {
      console.log('%cno empty quarter at the end — nothing dropped. If one is still showing, tell Claude.',
                  'color:#f59e0b;font-weight:700');
    }
    console.table([{ what: 'quarters', before: (orig.quarters || []).length, after: (s.quarters || []).length },
                   { what: 'lineup stints', before: (orig.lineupSegments || []).length, after: (s.lineupSegments || []).length }]);
    if (finalised) console.log('%cstat lines recomputed — ↑ Publish to push it to the site', 'color:#6366f1;font-weight:700');
    console.log('%creloading…', 'color:#6366f1;font-weight:700');
    setTimeout(() => location.reload(), 800);
  })();
}
