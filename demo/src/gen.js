// Builds the coaches' demo data: last season's Moorpark and opponents (real rosters, numbers, labels from the
// leaderboard's 2025-26 team files), a season of simulated games (repeatable rotations, so lineups and situations
// have real samples), and a live game vs Irvine Valley frozen late in the 2nd half. Runs inside the real tracker
// (poss/index.html on a local server) so every event is the tracker's own format; writes seed.json (localStorage).
const { chromium } = require('/opt/node-tools/node_modules/playwright');
const fs = require('fs');
const POS = JSON.parse(fs.readFileSync(__dirname + '/pos.json'));
(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  const errs = []; p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await p.goto('http://localhost:8765/poss/'); await p.waitForTimeout(500);
  const out = await p.evaluate(async POS => {
    localStorage.clear();
    let seed = 20260214; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const pickW = (arr, w) => { const t = w.reduce((a, x) => a + x, 0); let r = rnd() * t; for (let i = 0; i < arr.length; i++) { r -= w[i]; if (r <= 0) return arr[i]; } return arr[arr.length - 1]; };
    const R = await (await fetch('ratings.json')).json(); lsSet(LS_RATINGS, R);
    const OPPS = ['Ventura', 'Oxnard', 'Santa Barbara', 'Allan Hancock', 'Cuesta', 'LA Valley', 'LA Pierce', 'West LA', 'Bakersfield', 'Chaffey', 'Riverside', 'Irvine Valley'];
    const tf = {};
    for (const t of ['Moorpark', ...OPPS]) tf[t] = await (await fetch(R.teamFiles[t])).json();
    lsSet(LS_TEAM_FILES, tf);
    // ---- players: per-minute rates from the season totals ----
    const model = team => { const F = tf[team], rows = Object.fromEntries(F.table.rows.map(r => [r.name, r])), seen = new Set(), out = [];
      Object.entries(F.players).forEach(([name, pl]) => { const r = rows[name], a = pl.all; if (!r || !pl.num || !a || !a.MIN || seen.has(String(pl.num))) return;
        if ((r.gp || 0) < 6) return; seen.add(String(pl.num));
        out.push({ name, num: String(pl.num).replace(/^0(?=\d)/, ''), pos: (POS[team] || {})[name] || '', ht: r.ht || '', mpg: r.mpg || 0, gp: r.gp,
          use: (a.FGA + 0.44 * a.FTA + a.TO) / a.MIN, tpar: a.FGA ? a['3PA'] / a.FGA : 0.3, p2: (r.twop || 45) / 100, p3: (r.tpp || 30) / 100,
          ftp: Math.max(0.45, (r.ftp || 65) / 100), ftr: a.FGA ? a.FTA / a.FGA : 0.25, tov: (a.TO + 1) / (a.FGA + 0.44 * a.FTA + a.TO + 3),
          or: (a.OREB + 1) / a.MIN, dr: (a.DREB + 1) / a.MIN, ast: (a.AST + 1) / a.MIN, stl: (a.STL + 0.5) / a.MIN, blk: (a.BLK + 0.3) / a.MIN, pf: (a.PF + 1) / a.MIN }); });
      return out.sort((x, y) => y.mpg - x.mpg); };
    const M = model('Moorpark');
    // ---- rosters (Moorpark's own list; opponents in the game tracker's store), a few typed labels for flavor ----
    const note = {};   // no typed labels: every label in the demo comes from real stats
    lsSet(LS_ROSTER, M.map(x => ({ num: x.num, name: x.name, pos: x.pos, note: note[x.name] || '' })));
    lsSet('gt_opp_rosters', OPPS.map(t => ({ name: t, players: model(t).map(x => ({ num: x.num, name: x.name, pos: x.pos, ht: x.ht, yr: '', note: note[x.name] || '' })) })));
    // ---- rotations: a fixed set of fives per team, so the same lineups come back game after game ----
    const fives = P => { const st = P.slice(0, 5), bench = P.slice(5, 9), L = [{ f: st, w: 6 }];
      bench.forEach((bp, i) => st.slice().sort((x, y) => x.mpg - y.mpg).slice(0, 3).forEach((out, j) => L.push({ f: st.filter(x => x !== out).concat(bp), w: (4 - i) * (3 - j) * 0.45 })));
      for (let i = 0; i < 3; i++) for (let k = i + 1; k < 4; k++) { const two = st.slice().sort((x, y) => x.mpg - y.mpg).slice(0, 2); if (bench[i] && bench[k]) L.push({ f: st.filter(x => !two.includes(x)).concat(bench[i], bench[k]), w: 0.9 / (i + k) }); }
      return L; };
    const ID = (t, x) => t === 'a' ? x.name : 'o:' + x.num;
    // ---- one game ----
    function sim(opp, date, loc, opts) {
      opts = opts || {};
      const B = model(opp), FV = { a: fives(M), b: fives(B) }, P = { a: M, b: B };
      const g = { id: 'demo_' + date + '_' + slug(opp), v: 2, created: Date.parse(date + 'T19:00:00'), per: '1H', periods: ['1H'], ev: [], box: {}, opp, date, loc,
        conf: !!opts.conf, schedId: 'demo_sch_' + date, dressed: M.map(x => x.name), oppRoster: gtOppRoster(opp), scoutKey: null, astBlk: true };
      let n = 0; const E = e => { e.id = 'e' + (++n).toString(36) + date.replace(/-/g, ''); g.ev.push(e); return e; };
      const st = { a: { five: [], tf: 0 }, b: { five: [], tf: 0 } }, pf = {}, edge = opts.edge || 0;
      const setFive = (t, f, lock) => { st[t].five = f.slice(); E(Object.assign({ t: 'sub', per: g.per, team: t, five: f.map(x => ID(t, x)) }, lock ? { lock: true } : {})); };
      const choose = t => { let L = FV[t].filter(o => o.f.every(x => (pf[t + x.name] || 0) < (g.per === '1H' ? 3 : 5))); if (!L.length) L = FV[t]; return pickW(L, L.map(o => o.w)).f; };
      const w = (arr, k) => arr.map(x => x[k]);
      const foul = (t, x) => { pf[t + x.name] = (pf[t + x.name] || 0) + 1; st[t].tf++; E({ t: 'foul', per: g.per, team: t, player: ID(t, x) }); };
      const fts = (t, x, nShots, oneAndOne) => { let last = true; for (let i = 0; i < nShots; i++) { const m = rnd() < x.ftp; E({ t: 'play', per: g.per, team: t, player: ID(t, x), k: m ? 'ftm' : 'ftx' }); last = m; if (oneAndOne && !m) break; }
        return last; };
      const reb = (off, def) => { if (rnd() < 0.29) { E({ t: 'play', per: g.per, team: off, player: ID(off, pickW(st[off].five, w(st[off].five, 'or'))), k: 'oreb' }); return true; }
        E({ t: 'play', per: g.per, team: def, player: ID(def, pickW(st[def].five, w(st[def].five, 'dr'))), k: 'dreb' }); return false; };
      function poss(t) {
        const d = other(t), O = st[t].five, Dd = st[d].five, boost = (t === 'a' ? edge : -edge);
        for (let tries = 0; tries < 4; tries++) {
          const x = pickW(O, w(O, 'use'));
          if (rnd() < x.tov * 0.9) { if (rnd() < 0.5) E({ t: 'play', per: g.per, team: d, player: ID(d, pickW(Dd, w(Dd, 'stl'))), k: 'stl' });
            else if (rnd() < 0.08) { E({ t: 'play', per: g.per, team: t, player: ID(t, x), k: 'offf' }); pf[t + x.name] = (pf[t + x.name] || 0) + 1; }
            else E({ t: 'play', per: g.per, team: t, player: ID(t, x), k: 'to' }); return; }
          if (rnd() < 0.07) {   // off-ball / reach-in foul
            foul(d, pickW(Dd, w(Dd, 'pf')));
            const tf2 = st[d].tf; if (tf2 >= 7) { const s = pickW(O, w(O, 'use')); if (!fts(t, s, 2, tf2 < 10)) { if (reb(t, d)) continue; } return; }
            continue; }
          if (rnd() < x.ftr * 0.33) { foul(d, pickW(Dd, w(Dd, 'pf'))); const three = rnd() < x.tpar * 0.2; if (!fts(t, x, three ? 3 : 2)) { if (reb(t, d)) continue; } return; }
          const three = rnd() < x.tpar, pct = (three ? x.p3 : x.p2) + boost;
          if (rnd() < pct) { const e = E({ t: 'play', per: g.per, team: t, player: ID(t, x), k: three ? '3m' : '2m' }); if (rnd() < 0.55) e.ast = 1;
            if (!three && rnd() < 0.07) { foul(d, pickW(Dd, w(Dd, 'pf'))); fts(t, x, 1); } return; }
          const e = E({ t: 'play', per: g.per, team: t, player: ID(t, x), k: three ? '3x' : '2x' }); if (!three && rnd() < 0.08) e.blk = 1;
          if (!reb(t, d)) return;
        }
      }
      let secs, ball = 'a';
      const half = (per, stopAt) => {
        g.per = per; if (per !== '1H') g.periods.push(per); st.a.tf = st.b.tf = 0; secs = 1200;
        setFive('a', M.slice(0, 5), per === '1H'); setFive('b', B.slice(0, 5), per === '1H');
        let stint = 0, tos = { a: 0, b: 0 }, nextClock = 1200 - 240;
        while (secs > (stopAt || 0)) {
          poss(ball); ball = other(ball); secs -= 12 + Math.round(rnd() * 12);
          if (++stint >= 9 + Math.round(rnd() * 5) && secs > 150) { stint = 0; ['a', 'b'].forEach(t => { const f = secs < 300 && !stopAt ? P[t].slice(0, 5) : choose(t); if (fiveKey(f.map(x => ID(t, x))) !== fiveKey(st[t].five.map(x => ID(t, x)))) setFive(t, f); }); }
          if (secs <= nextClock && secs > 0) { nextClock -= 240; const tt = rnd() < 0.4 ? (rnd() < 0.5 ? 'a' : 'b') : null;
            if (tt && tos[tt] < 2) { tos[tt]++; E({ t: 'to', per, team: tt, kind: rnd() < 0.7 ? 'full' : 's30', clock: Math.max(1, secs) }); }
            else E({ t: 'clock', per, clock: Math.max(1, secs) }); }
        }
      };
      return { g, half, st, pf, E, P, setFive, poss, get ball() { return ball; }, get secs() { return secs; } };
    }
    // ---- the season: games before the Irvine Valley one (one of them vs Irvine Valley, for "Last time") ----
    const SEASON = [['2025-11-07', 'Ventura', 'A', 0.02], ['2025-11-14', 'Oxnard', 'H', 0.06], ['2025-11-21', 'Santa Barbara', 'H', 0.03], ['2025-11-28', 'Irvine Valley', 'N', -0.02],
      ['2025-12-05', 'Allan Hancock', 'A', 0.0], ['2025-12-12', 'Cuesta', 'H', 0.05], ['2025-12-19', 'LA Valley', 'A', 0.01], ['2026-01-09', 'LA Pierce', 'H', 0.04],
      ['2026-01-16', 'West LA', 'A', 0.0], ['2026-01-23', 'Bakersfield', 'H', 0.02], ['2026-01-30', 'Chaffey', 'A', -0.01], ['2026-02-06', 'Riverside', 'H', 0.03], ['2026-02-11', 'Ventura', 'H', 0.01]];
    const all = [];
    SEASON.forEach(([date, opp, loc, edge]) => { const S = sim(opp, date, loc, { edge, conf: ['Ventura', 'Oxnard', 'Santa Barbara', 'Allan Hancock', 'Cuesta', 'LA Valley', 'LA Pierce', 'West LA'].includes(opp) });
      S.half('1H'); S.half('2H');
      const sc = derive(S.g).score; if (sc.a === sc.b) S.E({ t: 'play', per: '2H', team: 'a', player: M[1].name, k: 'ftm' });   // no ties
      S.g.final = true; all.push(S.g); });
    // ---- the live game: Irvine Valley at home, frozen at 3:12 of the 2nd half ----
    let L, D;
    for (let tryN = 0; tryN < 60; tryN++) { L = sim('Irvine Valley', '2026-02-14', 'H', { edge: 0.01, conf: false }); L.half('1H'); L.half('2H', 200);
      D = derive(L.g); const m = D.score.a - D.score.b; if (m >= -3 && m <= -1 && D.score.a >= 55) break; }
    const g = L.g, IV = L.P.b;
    // The fives on the floor now: ours with Finney (foul trouble) in; theirs with Mowers (4 fouls) in.
    const want = { a: [M.find(x => x.name === 'Josh Castaniero'), M.find(x => x.name === 'Eric Kubel'), M.find(x => x.name === 'Roman Finney'), M.find(x => x.name === 'Noah Cotton'), M.find(x => x.name === 'Jake Field')],
      b: IV.slice(0, 5) };
    // Foul trouble and team fouls in the 2nd half: Finney 4, Kubel 3; Mowers 4, Alhammouri 3. Our team fouls 6 (one from
    // their bonus), theirs 8 (we're in the bonus). Added as fouls spread through the 2nd half.
    const pfOf = (t, id) => g.ev.filter(e => e.t === 'foul' && e.team === t && e.player === id).length + g.ev.filter(e => e.t === 'play' && (e.k === 'offf' || e.k === 'chg') && e.team === t && e.player === id).length;
    const h2 = () => g.ev.map((e, i) => ({ e, i })).filter(x => x.e.per === '2H');
    const insertFoul = (t, id) => { const H = h2().filter(x => x.e.t === 'play'); const at = H[Math.floor(rnd() * Math.max(1, H.length - 4))].i;
      g.ev.splice(at, 0, { id: 'ef' + Math.random().toString(36).slice(2, 8), t: 'foul', per: '2H', team: t, player: id }); };
    const removeFoul = (t, id) => { const i = g.ev.findIndex(e => e.t === 'foul' && e.team === t && e.player === id); if (i >= 0) g.ev.splice(i, 1); };
    const fixPF = (t, id, n) => { while (pfOf(t, id) < n) insertFoul(t, id); while (pfOf(t, id) > n) removeFoul(t, id); };
    fixPF('a', 'Roman Finney', 4); fixPF('a', 'Eric Kubel', 3); fixPF('b', 'o:' + IV.find(x => x.name === 'Matt Mowers').num, 4); fixPF('b', 'o:' + IV.find(x => x.name === 'Ahmad Alhammouri').num, 3);
    const tf2 = t => g.ev.filter(e => e.t === 'foul' && e.team === t && e.per === '2H').length;
    const onNow = new Set([...want.a, ...want.b].map(x => x.name));
    const spare = t => (t === 'a' ? M : IV).filter(x => !onNow.has(x.name) && pfOf(t, ID(t, x)) <= 2).slice(0, 8).map(x => ID(t, x));
    const fixTF = (t, n) => { let k = 0; while (tf2(t) < n) insertFoul(t, spare(t)[k++ % 8]);
      const keepIds = ['Roman Finney', 'Eric Kubel', 'Matt Mowers', 'Ahmad Alhammouri'].map(nm => { const x = (t === 'a' ? M : IV).find(y => y.name === nm); return x ? ID(t, x) : null; });
      while (tf2(t) > n) { const i = g.ev.findIndex(e => e.t === 'foul' && e.team === t && e.per === '2H' && !keepIds.includes(e.player)); if (i < 0) break; g.ev.splice(i, 1); } };
    fixTF('a', 6); fixTF('b', 8);
    // Nobody else in foul trouble beyond what the demo wants: anyone at 5 who isn't meant to be comes back to 3.
    ['a', 'b'].forEach(t => (t === 'a' ? M : IV).forEach(x => { const id = ID(t, x); if (!['Roman Finney', 'Eric Kubel', 'Matt Mowers', 'Ahmad Alhammouri'].includes(x.name) && pfOf(t, id) >= 4) {
      while (pfOf(t, id) > 3) { const i = g.ev.findIndex(e => e.t === 'foul' && e.team === t && e.player === id && e.per === '1H') ; const j = i >= 0 ? i : g.ev.findIndex(e => e.t === 'foul' && e.team === t && e.player === id); if (j < 0) break; g.ev[j].player = null; } } }));
    // Timeouts used: ours 2 full + 1 thirty before this one; theirs 2 full + 1 thirty.
    g.ev = g.ev.filter(e => e.t !== 'to');
    const putTO = (t, kind, per, clock) => { const C = g.ev.map((e, i) => ({ e, i })).filter(x => x.e.t === 'clock' && x.e.per === per)
        .sort((x, y) => Math.abs(x.e.clock - clock) - Math.abs(y.e.clock - clock));
      const c = C[0], at = c ? c.i + 1 : g.ev.length; g.ev.splice(at, 0, { id: 'et' + Math.random().toString(36).slice(2, 8), t: 'to', per, team: t, kind, clock: c ? c.e.clock : clock }); };
    [['a', 'full', '1H', 610], ['b', 'full', '1H', 260], ['a', 's30', '2H', 980], ['b', 'full', '2H', 700], ['a', 'full', '2H', 455], ['b', 's30', '2H', 330]].forEach(x => putTO(...x));
    // Now: the floor, then our full timeout at 3:12 (the huddle opens on it).
    ['a', 'b'].forEach(t => { const f = want[t].map(x => ID(t, x)); if (fiveKey(f) !== fiveKey(derive(g).five[t])) g.ev.push({ id: 'es' + t, t: 'sub', per: '2H', team: t, five: f }); });
    g.ev.push({ id: 'etnow', t: 'to', per: '2H', team: 'a', kind: 'full', clock: 192 });
    g.ball = 'a';
    all.push(g);
    games = all; curId = g.id; save();
    // The halftime stat sheet, as if its photo had been read: every player's 1st-half box from the plays (assists and
    // blocks go to a teammate / defender on the floor, by his rates; minutes from his share of the possessions).
    { const DD = derive(g), H = DD.poss.filter(x => x.per === '1H'), rows = { a: {}, b: {} }, rate = { a: Object.fromEntries(M.map(x => [x.name, x])), b: Object.fromEntries(IV.map(x => ['o:' + x.num, x])) };
      const R = (t, id) => rows[t][id] = rows[t][id] || { min: 0, fgm: 0, fga: 0, fg3m: 0, fg3a: 0, ftm: 0, fta: 0, oreb: 0, dreb: 0, ast: 0, stl: 0, blk: 0, tov: 0, pf: 0, pts: 0, on: 0 };
      const pick = (t, ids, k) => pickW(ids, ids.map(id => (rate[t][id] || {})[k] || 0.01));
      H.forEach(x => ['a', 'b'].forEach(t => x.five[t].forEach(id => R(t, id).on++)));
      const fv = { a: [], b: [] };
      g.ev.filter(e => e.per === '1H').forEach(e => { if (e.t === 'sub') { fv[e.team] = e.five.slice(); return; } if (e.t !== 'play') return;
          const t = e.team, r = e.player && e.player !== 'TEAM' ? R(t, e.player) : null; if (!r) return;
          if (e.k === '2m' || e.k === '3m') { r.fgm++; r.fga++; r.pts += e.k === '3m' ? 3 : 2; if (e.k === '3m') { r.fg3m++; r.fg3a++; }
            if (e.ast) { const mates = fv[t].filter(id => id !== e.player); if (mates.length) R(t, pick(t, mates, 'ast')).ast++; } }
          if (e.k === '2x' || e.k === '3x') { r.fga++; if (e.k === '3x') r.fg3a++; if (e.blk && fv[other(t)].length) R(other(t), pick(other(t), fv[other(t)], 'blk')).blk++; }
          if (e.k === 'ftm') { r.ftm++; r.fta++; r.pts++; } if (e.k === 'ftx') r.fta++;
          if (e.k === 'oreb') r.oreb++; if (e.k === 'dreb') r.dreb++; if (e.k === 'stl') r.stl++; if (e.k === 'to') r.tov++; if (e.k === 'offf') { r.tov++; r.pf++; } });
      g.ev.filter(e => e.per === '1H' && e.t === 'foul' && e.player).forEach(e => R(e.team, e.player).pf++);
      const st1 = { a: g.ev.find(e => e.t === 'sub' && e.team === 'a').five, b: g.ev.find(e => e.t === 'sub' && e.team === 'b').five };
      const team = t => { const tot = H.filter(x => x.team === t).length || 1, ids = Object.keys(rows[t]);
        const raw = ids.map(id => Math.max(1, Math.round(20 * 5 * rows[t][id].on / ids.reduce((a, k) => a + rows[t][k].on, 0))));
        let diff = 100 - raw.reduce((a, v) => a + v, 0); for (let i = 0; diff !== 0 && i < 400; i++) { const j = i % raw.length; if (diff > 0 || raw[j] > 1) { raw[j] += diff > 0 ? 1 : -1; diff += diff > 0 ? -1 : 1; } }
        return { title: teamName(g, t), teamReb: null, totals: null, rows: ids.map((id, i) => { const pl = rate[t][id] || {}, r = rows[t][id]; delete r.on;
          return Object.assign({ num: pl.num || '', name: pl.name || id, starter: st1[t].includes(id) }, r, { min: raw[i] }); }) }; };
      SHEET = { sc: '1H', a: team('a'), b: team('b') }; sheetSave(); UI.tab = 'live'; }
    save();
    try { backfillSits(); } catch (e) {}
    save();
    // Schedule: last season's games, the Irvine Valley one today's game.
    lsSet('gt_schedule', all.map(x => ({ id: x.schedId, date: x.date, time: '7:00 PM', opp: x.opp, site: { H: 'home', A: 'away', N: 'neutral' }[x.loc], conf: !!x.conf, scrim: false })));
    const keep = {}; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); keep[k] = localStorage.getItem(k); }
    D = derive(g);
    return { keep, score: D.score, five: D.five, finals: all.filter(x => x.final).map(x => { const s = derive(x).score; return x.opp + ' ' + s.a + '-' + s.b; }) };
  }, POS);
  fs.writeFileSync(__dirname + '/seed.json', JSON.stringify(out.keep));
  console.log(JSON.stringify({ score: out.score, five: out.five, finals: out.finals, keys: Object.keys(out.keep), bytes: JSON.stringify(out.keep).length }, null, 0));
  if (errs.length) console.log('ERRS', errs);
  await b.close();
})();
