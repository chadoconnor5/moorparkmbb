/* Tag the shot clock on an attempt that was logged without one.
   ─────────────────────────────────────────────────────────────
   Paste into the browser console on the practice tracker, then:

     tagShotClock({ filmTs: 113*60 + 14.9, player: 'Quian', value: 24 })              // dry run
     tagShotClock({ filmTs: 113*60 + 14.9, player: 'Quian', value: 24, apply: true }) // writes it

   Several at once:

     tagShotClock([{ filmTs: 113*60 + 14.9, player: 'Quian', value: 24 },
                   { filmTs: 114*60 + 2.3,  player: 'Hees',  value: 9  }], { apply: true })

   The Shot Type modal takes a reading while the attempt is being logged; this is the
   after-the-fact route for one that went in untagged, until the ✎ film-event editor
   learns the field. It writes the same integer key everything else reads — absent means
   "not read", which is not zero, so a tag is only ever ADDED here, never blanked.

   Safe to run mid-scrimmage: when the session is the live one it edits the copy the
   tracker itself holds and saves through saveLiveSession(), so the next autosave cannot
   put the old event back. Nothing else moves — not the event's position in the log, not
   its film time, not a single stat. */

window.tagShotClock = function tagShotClock(specs, common) {
  const list = (Array.isArray(specs) ? specs : [specs]).map(x => Object.assign({}, common || {}, x));
  /* One shot is the common case and its options belong in the same object as its filmTs —
     nobody should have to write tagShotClock({...}, { apply: true }). A batch keeps them in
     the second argument, since they apply to every row. */
  const o = Object.assign({
    session:   /#\s*27\b/i,   // title (regex or substring), or an exact session id
    tolerance: 20,            // how far from the given film time a match may sit, in seconds
    apply:     false,
    force:     false,         // overwrite a reading that is already there
  }, common || {}, Array.isArray(specs) ? {} : (specs || {}));

  const fmt = s => {
    if (s == null || !isFinite(s)) return '—';
    const t = Math.round(s), a = Math.abs(t);
    return (t < 0 ? '-' : '') + Math.floor(a / 60) + ':' + String(a % 60).padStart(2, '0');
  };
  const fail = msg => { console.error('%ctagShotClock: ' + msg, 'color:#ef4444;font-weight:700'); return null; };

  /* ── The session, in whichever store holds it ── */
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
    return fail('matched ' + pool.length + ' copies: ' + pool.map(p => `${p.session.title} [${p.where}]`).join(', ') +
                '. Pass session: "<exact id>" for the one you mean.');
  }
  let { where, index, session } = pool[0];

  /* Mid-scrimmage the tracker is holding its own copy in memory and saves it on every
     entry. Edit THAT one, or the next autosave overwrites this.

     `State` is a script-scope const, so it is NOT window.State — testing for it there
     comes back undefined on a page that has it, which is the silent-loss case: the tag
     goes to localStorage, the tracker keeps its stale copy, and the next save undoes it. */
  const APP = (typeof State !== 'undefined' && State) ? State : null;
  const liveInMemory = where === 'live' && APP && APP.liveSession && APP.liveSession.id === session.id;
  if (liveInMemory) session = APP.liveSession;

  const FG = new Set(['2fg_make', '2fg_miss', '3fg_make', '3fg_miss']);
  const label = e => `Q${e.quarter} ${statLabelOf(e.stat)} — ${e.player}, film ${fmt(e.videoTs)}`;
  const statLabelOf = st => (typeof statLabel === 'function' ? statLabel(st) : st);

  const planned = [];
  for (const spec of list) {
    if (spec.filmTs == null) return fail('each spec needs a filmTs.');
    const v = parseInt(spec.value, 10);
    if (!isFinite(v) || v < 0 || v > 35) return fail(`shot clock ${spec.value} is not a reading between 0 and 35.`);

    /* A free throw has no shot clock, so only field-goal attempts are candidates. */
    let cands = (session.eventLog || []).filter(e => FG.has(e.stat) && e.videoTs != null);
    if (spec.player) {
      const needle = String(spec.player).toLowerCase();
      const byName = cands.filter(e => String(e.player || '').toLowerCase().includes(needle));
      if (!byName.length) return fail(`no field-goal attempt by anyone matching "${spec.player}".`);
      cands = byName;
    }
    const near = cands
      .map(e => ({ e, off: Math.abs(e.videoTs - spec.filmTs) }))
      .sort((x, y) => x.off - y.off);
    if (!near.length || near[0].off > o.tolerance) {
      return fail(`nothing within ${o.tolerance}s of film ${fmt(spec.filmTs)}` +
        (spec.player ? ` by "${spec.player}"` : '') +
        (near.length ? `. Nearest: ${label(near[0].e)}, ${fmt(near[0].off)} away.` : '.'));
    }
    /* Two attempts a second apart is a putback, and picking the wrong one is silent. */
    if (near[1] && near[1].off - near[0].off < 2) {
      return fail(`two attempts are equally close to film ${fmt(spec.filmTs)}:\n  ` +
        [near[0], near[1]].map(n => label(n.e) + ` (${n.off.toFixed(1)}s away)`).join('\n  ') +
        '\nNarrow it with player, or a film time nearer the one you mean.');
    }
    const ev = near[0].e;
    if (ev.shotClock != null && !o.force && ev.shotClock !== v) {
      return fail(`${label(ev)} already reads ${ev.shotClock}. Pass force:true to change it to ${v}.`);
    }
    planned.push({ ev, was: ev.shotClock == null ? null : ev.shotClock, value: v, off: near[0].off });
  }

  console.log(`%c${session.title} — ${planned.length} shot clock tag${planned.length === 1 ? '' : 's'}` +
              `  (${where === 'live' ? 'in progress' : 'saved'})`, 'font-weight:700;font-size:13px');
  console.table(planned.map(p => ({
    shot:       label(p.ev),
    'off by':   p.off.toFixed(1) + 's',
    was:        p.was == null ? 'not tagged' : p.was,
    'shot clock': p.value,
  })));

  if (!o.apply) {
    console.log('%cdry run — nothing written. Add apply: true once the shots above are the right ones.',
                'color:#f59e0b;font-weight:700');
    return planned.map(p => ({ shot: label(p.ev), value: p.value, applied: false }));
  }

  planned.forEach(p => { p.ev.shotClock = p.value; });

  if (where === 'live') {
    if (liveInMemory && typeof saveLiveSession === 'function') saveLiveSession(session);
    else localStorage.setItem('pt_live_session', JSON.stringify(session));
  } else {
    saved[index] = session;
    localStorage.setItem('pt_sessions', JSON.stringify(saved));
    if (APP && Array.isArray(APP.sessions)) {
      const i = APP.sessions.findIndex(x => x.id === session.id);
      if (i !== -1) APP.sessions[i] = session;
    }
  }
  console.log('%csaved' + (liveInMemory ? ' — carry on tracking, nothing to reload' : ''),
              'color:#22c55e;font-weight:700');
  return planned.map(p => ({ shot: label(p.ev), value: p.value, applied: true }));
};

console.log('%ctagShotClock({ filmTs, player, value }) ready — dry run first, then apply: true.',
            'color:#6366f1;font-weight:700');
