/* ── Game Tracker lineups (opponent-adjusted; Moorpark-only) ───────────────
   Inserted into the leaderboard by generate_leaderboard.py. The coach loads the file
   adjust_lineups.py writes (from the game tracker's Lineup file) with the button below;
   it is read in this browser only and kept in localStorage - never published. Every
   N-man group is summed from the 5-man units: raw counts add up, and the adjusted
   ratings add up as possession-weighted sums (adjOrtg x adjPossO). */
const TLU_KEY = 'lb_tracker_lineups';
const TLU_CUR_SEASON = activeSeason;   // the build's current season: tracker data belongs to it
let tluSize = '5', tluSort = 'poss', tluDir = -1, tluMin = null;
function tluData() { try { return JSON.parse(localStorage.getItem(TLU_KEY) || 'null'); } catch (e) { return null; } }
function tluPick() { document.getElementById('tlu-file').click(); }
function tluClear() {
  if (!confirm('Remove the loaded tracker lineups from this browser?')) return;
  try { localStorage.removeItem(TLU_KEY); } catch (e) {}
  renderTrackerLineups();
}
function tluLoad(input) {
  const f = input.files && input.files[0]; input.value = '';
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    let d; try { d = JSON.parse(rd.result); } catch (e) { alert('Not a valid JSON file.'); return; }
    if (!d || d.kind !== 'lineups-adjusted' || !Array.isArray(d.units)) { alert('Not an adjusted lineup file. Run adjust_lineups.py on the tracker\'s Lineup file and load its output.'); return; }
    try { localStorage.setItem(TLU_KEY, JSON.stringify(d)); } catch (e) { alert('This browser would not save it (storage full or blocked); showing it until you leave the page.'); window.__tluMem = d; }
    renderTrackerLineups();
  };
  rd.readAsText(f);
}
function tluSet(k, v) { if (k === 'size') { tluSize = v; tluMin = null; } else if (k === 'min') tluMin = Math.max(0, +v || 0); renderTrackerLineups(); }
function tluSortBy(k) { if (tluSort === k) tluDir = -tluDir; else { tluSort = k; tluDir = k === 'name' ? 1 : -1; } renderTrackerLineups(); }
function __tluCombos(arr, k) {
  const out = [];
  const go = (s, cur) => { if (cur.length === k) { out.push(cur.slice()); return; } for (let i = s; i < arr.length; i++) { cur.push(arr[i]); go(i + 1, cur); cur.pop(); } };
  go(0, []); return out;
}
function __tluGroups(D, size) {
  const g = new Map();
  for (const u of D.units) {
    const players = u.players || u.names.map(n => ({ name: n, num: '' }));
    for (const c of __tluCombos(players, size)) {
      const key = c.map(p => p.name).sort().join('|');
      if (!g.has(key)) g.set(key, { key, players: c.slice().sort((a, b) => (+a.num || 99) - (+b.num || 99)), units: 0, gpMax: 0, secs: 0, oT: 0, dT: 0, pf: 0, pa: 0, o: {}, d: {}, aO: 0, aOT: 0, aD: 0, aDT: 0 });
      const x = g.get(key);
      x.units++; x.gpMax = Math.max(x.gpMax, u.gp || 0);
      for (const k of ['secs', 'oT', 'dT', 'pf', 'pa']) x[k] += u[k] || 0;
      for (const s of ['o', 'd']) for (const [k, v] of Object.entries(u[s] || {})) x[s][k] = (x[s][k] || 0) + v;
      if (u.adjOrtg != null && u.adjPossO) { x.aO += u.adjOrtg * u.adjPossO; x.aOT += u.adjPossO; }
      if (u.adjDrtg != null && u.adjPossD) { x.aD += u.adjDrtg * u.adjPossD; x.aDT += u.adjPossD; }
    }
  }
  return [...g.values()].map(x => {
    const o = x.o, d = x.d, ortg = x.oT ? 100 * x.pf / x.oT : null, drtg = x.dT ? 100 * x.pa / x.dT : null;
    const ao = x.aOT ? x.aO / x.aOT : null, ad = x.aDT ? x.aD / x.aDT : null;
    const efg = s => s.fga ? 100 * ((s.fgm || 0) + 0.5 * (s.fg3m || 0)) / s.fga : null;
    return Object.assign(x, {
      poss: x.oT + x.dT, min: x.secs / 60, ortg, drtg, net: ortg != null && drtg != null ? ortg - drtg : null,
      adjO: ao, adjD: ad, adjNet: ao != null && ad != null ? ao - ad : null,
      efg: efg(o), tov: x.oT ? 100 * (o.tov || 0) / x.oT : null, orb: ((o.oreb || 0) + (d.dreb || 0)) ? 100 * (o.oreb || 0) / ((o.oreb || 0) + (d.dreb || 0)) : null, ftr: o.fga ? 100 * (o.fta || 0) / o.fga : null,
      oefg: efg(d), otov: x.dT ? 100 * (d.tov || 0) / x.dT : null, drb: ((d.oreb || 0) + (o.dreb || 0)) ? 100 * (o.dreb || 0) / ((d.oreb || 0) + (o.dreb || 0)) : null, oftr: d.fga ? 100 * (d.fta || 0) / d.fga : null,
      name: x.players.map(p => p.name).join(', '),
    });
  });
}
function renderTrackerLineups() {
  const box = document.getElementById('lu-tracker'); if (!box) return;
  const D = tluData() || window.__tluMem || null;
  const btn = (lab, on, click, title) => `<button onclick="${click}" ${title ? `title="${title}"` : ''} style="background:${on ? '#ffd700' : '#2a2a40'};border:1px solid #ffd700;color:${on ? '#1a1a2e' : '#ffd700'};font-weight:${on ? 700 : 600};padding:5px 14px;border-radius:5px;cursor:pointer;font-size:0.85rem">${lab}</button>`;
  const tools = `<div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin:0 0 8px">
      ${btn('⬆ Load adjusted lineups', false, 'tluPick()', 'The file adjust_lineups.py writes from the game tracker\'s Lineup file')}${D ? btn('Clear', false, 'tluClear()') : ''}
      <input type="file" id="tlu-file" accept=".json,application/json" style="display:none" onchange="tluLoad(this)"></div>`;
  if (!D) {
    box.innerHTML = tools + `<div style="color:#999;text-align:center;padding:14px 0 22px;font-size:0.9rem;max-width:760px;margin:0 auto">
      In the game tracker, Season → <b>⬇ Lineup file</b>; run <code>python3 adjust_lineups.py &lt;file&gt;</code>; load
      <code>internal_data/moorpark_lineups_adj.json</code> here. It stays in this browser only.</div>`;
    return;
  }
  const size = +tluSize, minP = tluMin != null ? tluMin : (size === 5 ? 10 : size === 1 ? 20 : 20);
  let rows = __tluGroups(D, size).filter(x => x.poss >= minP);
  const val = x => tluSort === 'name' ? x.name : x[tluSort];
  rows.sort((a, b) => { const va = val(a), vb = val(b); if (va == null && vb == null) return 0; if (va == null) return 1; if (vb == null) return -1; return (va < vb ? -1 : va > vb ? 1 : 0) * tluDir; });
  const f0 = v => v == null || !isFinite(v) ? '—' : Math.round(v), f1 = v => v == null || !isFinite(v) ? '—' : v.toFixed(1);
  const sg = v => { if (v == null || !isFinite(v)) return '—'; const r = Math.round(v); return (r > 0 ? '+' : '') + r; };
  const pc = v => v == null ? '' : v > 0 ? 'color:#15803d!important;font-weight:700' : v < 0 ? 'color:#b91c1c!important;font-weight:700' : '';
  const nm = p => `${p.num ? '#' + p.num + ' ' : ''}${p.name.split(' ').slice(-1)[0]}`;
  const cols = [['name', size === 1 ? 'Player' : 'Lineup'], ['gpMax', size === 5 ? 'GP' : 'Units'], ['min', 'Min'], ['poss', 'Poss O/D'], ['pf', 'Pts F–A'],
    ['ortg', 'ORtg'], ['drtg', 'DRtg'], ['net', 'Net'], ['adjO', 'Adj ORtg'], ['adjD', 'Adj DRtg'], ['adjNet', 'Adj Net'],
    ['efg', 'eFG%'], ['tov', 'TO%'], ['orb', 'OR%'], ['ftr', 'FTR'], ['oefg', 'Opp eFG%'], ['otov', 'Opp TO%'], ['drb', 'DR%'], ['oftr', 'Opp FTR']];
  const th = cols.map(([k, l], i) => `<th onclick="tluSortBy('${k}')" style="cursor:pointer;padding:6px 8px;background:#1a1a2e;color:#ffd700;font-size:0.72rem;text-transform:uppercase;white-space:nowrap;text-align:${i ? 'right' : 'left'};${k === 'adjO' || k === 'efg' || k === 'oefg' ? 'border-left:2px solid #ffd700;' : ''}">${l}${tluSort === k ? (tluDir < 0 ? ' ▼' : ' ▲') : ''}</th>`).join('');
  // Page-wide table rules (centred cells, zebra rows, bold columns) are overridden per cell.
  let bg = '';
  const td = (v, s) => `<td style="padding:5px 8px!important;text-align:right!important;white-space:nowrap;font-weight:400;color:#1f2937;background:${bg}!important;${s || ''}">${v}</td>`;
  const body = rows.map((x, i) => (bg = i % 2 ? '#dde1e7' : '#eef0f3', `<tr>
      ${td(x.players.map(nm).join(', '), 'text-align:left!important')}
      ${td(size === 5 ? x.gpMax : x.units)}${td(f1(x.min))}${td(x.oT + ' / ' + x.dT)}${td(x.pf + '–' + x.pa)}
      ${td(f0(x.ortg))}${td(f0(x.drtg))}${td(sg(x.net), pc(x.net))}
      ${td(f0(x.adjO), 'border-left:2px solid #ffd700')}${td(f0(x.adjD))}${td(sg(x.adjNet), pc(x.adjNet))}
      ${td(f1(x.efg), 'border-left:2px solid #ffd700')}${td(f1(x.tov))}${td(f1(x.orb))}${td(f1(x.ftr))}
      ${td(f1(x.oefg), 'border-left:2px solid #ffd700')}${td(f1(x.otov))}${td(f1(x.drb))}${td(f1(x.oftr))}</tr>`)).join('');
  const skipped = (D.games || []).filter(g => !g.adjusted);
  box.innerHTML = tools + `
    <div style="color:#ccc;font-size:0.8rem;text-align:center;margin:0 0 8px">
      File ${String(D.generatedAt || '').slice(0, 10)} · ${D.gamesAdjusted} of ${D.gamesTotal} games adjusted against ${D.ratingsSeason} team ratings
      (league avg ORtg ${D.leagueAvg ? D.leagueAvg.ortg : '—'} / DRtg ${D.leagueAvg ? D.leagueAvg.drtg : '—'}, home court ${D.homeAdvantage ?? '—'}/100)
      ${skipped.length ? `<br><span style="color:#999">Not adjusted: ${skipped.map(g => `${g.date} ${g.opponent} (${g.skipped})`).join(' · ')}</span>` : ''}</div>
    <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin:0 0 8px">
      ${['1', '2', '3', '4', '5'].map(k => btn(k === '1' ? 'Players' : k + '-Man', tluSize === k, `tluSet('size','${k}')`)).join('')}
      <span style="color:#ccc;font-size:0.82rem;align-self:center;margin-left:8px">Min poss <input type="number" min="0" value="${minP}" onchange="tluSet('min', this.value)" style="width:56px;background:#2a2a40;border:1px solid #ffd700;color:#ffd700;border-radius:4px;padding:3px 5px"></span></div>
    <div style="background:#fff;border-radius:8px;border:1px solid #ccc;overflow-x:auto">
      <table style="border-collapse:collapse;width:100%;font-size:0.82rem;font-variant-numeric:tabular-nums"><tr>${th}</tr>${body || `<tr><td colspan="${cols.length}" style="padding:14px;text-align:center;color:#666">No ${size === 1 ? 'player' : 'group'} with ${minP}+ possessions.</td></tr>`}</table></div>
    <div style="color:#999;font-size:0.72rem;text-align:center;margin-top:6px">
      Garbage time out. Adj: each game adjusted for the opponent's rating and home court, possession-weighted; out-of-system games and scrimmages count in the raw columns only.
      ${size === 1 ? 'Players: every possession that player was on the floor.' : size < 5 ? 'Units = how many five-man units this group was part of.' : 'GP = games this five played together.'} Click a header to sort.</div>`;
}
