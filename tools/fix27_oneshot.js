/* Fall Workout #27 — both repairs, applied on paste. No second command.
   Q2's clock sat stopped from film 105:53 to 108:38; Q8 was opened by ending Q7
   instead of ending the practice. Refuses, loudly and without writing, if the session
   is not exactly as expected — including if it has already been fixed. */
(() => {
  const B = 150, ADD_BEFORE = 144, ADD_AFTER = 21, TOTAL = 165, DROP_Q = 8, SUB_FILM = 6497.1;
  const f = s => s == null ? '—' : Math.floor(s / 60) + ':' + String(Math.round(s % 60)).padStart(2, '0');
  const stop = m => { console.error('%cfix27: ' + m, 'color:#ef4444;font-weight:700'); return null; };

  let saved = [], live = null;
  try { saved = JSON.parse(localStorage.getItem('pt_sessions') || '[]') || []; } catch (e) {}
  try { live  = JSON.parse(localStorage.getItem('pt_live_session') || 'null'); } catch (e) {}
  const hit = x => x && (x.id === 'session_1789611548918' || /#\s*27\b/.test(x.title || ''));
  const idx = saved.findIndex(hit);
  const where = idx !== -1 ? 'saved' : (hit(live) ? 'live' : null);
  if (!where) return stop('no Fall Workout #27 in this browser.');
  if (idx !== -1 && hit(live)) return stop('#27 is in BOTH the saved list and the live slot. Tell Claude before going further.');
  const s = JSON.parse(JSON.stringify(where === 'saved' ? saved[idx] : live));

  const q2 = (s.quarters || [])[1];
  if (!q2 || q2.number !== 2) return stop('Q2 is not the second recorded quarter.');
  if (q2.duration === 585) return stop('already fixed — Q2 is 9:45. Nothing to do.');
  if (q2.duration !== 420 || q2.timeRemaining !== 7) return stop(`Q2 reads ${f(q2.duration)} ending ${f(q2.timeRemaining)}, expected 7:00 ending 0:07.`);

  const segs2 = (s.lineupSegments || []).filter(g => g.quarter === 2);
  const subs2 = (s.eventLog || []).filter(e => e.type === 'sub' && e.quarter === 2 && e.timeSecs != null);
  const target = subs2.find(e => e.timeSecs === B);
  if (!target) return stop(`no Q2 sub at ${f(B)}. Subs: ${subs2.map(e => f(e.timeSecs)).join(', ')}`);
  if (Math.abs((target.videoTs || 0) - SUB_FILM) > 5) return stop(`the ${f(B)} sub sits at film ${f(target.videoTs)}, not ${f(SUB_FILM)}.`);
  if (!segs2.some(g => g.startTimeSecs === B) || !segs2.some(g => g.endTimeSecs === B)) return stop(`the ${f(B)} sub is not a stint boundary.`);
  if (subs2.some(e => e !== target && e.videoTs > 6353 && e.videoTs < 6518)) return stop('another sub sits inside the untimed stretch.');

  const q8at = (s.quarters || []).findIndex(q => q.number === DROP_Q);
  if (q8at !== -1) {
    if (q8at !== s.quarters.length - 1) return stop('Q8 is not the last quarter.');
    if ((s.eventLog || []).some(e => e.quarter === DROP_Q)) return stop('Q8 holds events — it was played.');
    if ((s.quarters[q8at].playedDuration || 0) > 0) return stop('Q8 has time played.');
    if ((s.lineupSegments || []).some(g => g.quarter === DROP_Q && g.endTimeSecs != null && g.endTimeSecs !== g.startTimeSecs))
      return stop('a Q8 stint holds elapsed time.');
  }

  const was = { q2: q2.duration, qs: s.quarters.length, segs: (s.lineupSegments || []).length,
                total: s.quarters.reduce((n, q) => n + (q.playedDuration || 0), 0) };
  const shift = v => v == null ? v : v > B ? v + TOTAL : v === B ? v + ADD_AFTER : v;
  segs2.forEach(g => { g.startTimeSecs = shift(g.startTimeSecs); g.endTimeSecs = shift(g.endTimeSecs); });
  subs2.forEach(e => { e.timeSecs = shift(e.timeSecs); });
  q2.duration += TOTAL;
  q2.playedDuration = q2.duration - q2.timeRemaining;
  q2.clockAmend = { before: ADD_BEFORE, after: ADD_AFTER, atClock: B, appliedAt: new Date().toISOString() };
  if (q8at !== -1) {
    s.quarters.splice(q8at, 1);
    s.lineupSegments = s.lineupSegments.filter(g => g.quarter !== DROP_Q);
  }

  const bad = [];
  segs2.forEach(g => { if (g.endTimeSecs > g.startTimeSecs) bad.push(`stint ${f(g.startTimeSecs)}→${f(g.endTimeSecs)} backwards`); });
  subs2.forEach(e => { if (!segs2.some(g => g.startTimeSecs === e.timeSecs)) bad.push(`sub ${f(e.timeSecs)} orphaned`); });
  const span = segs2.reduce((n, g) => n + (g.startTimeSecs - g.endTimeSecs), 0);
  if (span !== q2.playedDuration) bad.push(`stints total ${f(span)}, quarter played ${f(q2.playedDuration)}`);
  if (bad.length) return stop('NOT SAVED — ' + bad.join('; '));

  if (typeof computeTeamStats !== 'function' || typeof computePlayerStats !== 'function')
    return stop('run this on the tracker page — its stat functions are not here.');
  s.teamStats = computeTeamStats(s);
  s.playerStats = computePlayerStats(s);

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

  const now = { qs: s.quarters.length, segs: s.lineupSegments.length,
                total: s.quarters.reduce((n, q) => n + (q.playedDuration || 0), 0) };
  console.log('%cFIXED — ' + s.title, 'color:#22c55e;font-weight:700;font-size:13px');
  console.table([
    { what: 'Q2 length',   before: f(was.q2),    after: f(q2.duration) },
    { what: 'quarters',    before: was.qs,       after: now.qs },
    { what: 'stints',      before: was.segs,     after: now.segs },
    { what: 'scrimmage',   before: f(was.total), after: f(now.total) },
  ]);
  console.table(segs2.map(g => ({ stint: `${f(g.startTimeSecs)} → ${f(g.endTimeSecs)}`,
                                  length: f(g.startTimeSecs - g.endTimeSecs),
                                  White: (g.lineupA || []).join(', '), Black: (g.lineupB || []).join(', ') })));
  console.log('%creloading…', 'color:#6366f1;font-weight:700');
  setTimeout(() => location.reload(), 800);
})()
