#!/usr/bin/env python3
"""Generate a standalone 'Single Lineup' stint-timeline prototype for Moorpark,
modeled on CBB Analytics. Embeds moorpark_stints_2025_26.json inline so it opens
as a plain file. Pick players -> per-game on-court stint bars colored by +/-."""
import json

DATA = json.load(open("internal_data/moorpark_stints_2025_26.json"))

HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Moorpark — Single Lineup</title>
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1f2e;margin:0;background:#fff}
 .wrap{max-width:1080px;margin:0 auto;padding:24px 28px}
 h1{font-size:1.5rem;margin:0 0 4px}
 .sub{color:#667;font-size:.9rem;margin-bottom:18px}
 .chips{display:flex;flex-wrap:wrap;gap:7px;margin:10px 0 6px}
 .chip{border:1px solid #cdd2da;border-radius:16px;padding:5px 12px;font-size:.82rem;cursor:pointer;background:#fff;user-select:none}
 .chip.on{background:#1a1f2e;color:#fff;border-color:#1a1f2e}
 .tools{display:flex;gap:10px;align-items:center;margin:6px 0 4px}
 .btn{border:1px solid #cdd2da;background:#f7f8fa;border-radius:6px;padding:5px 12px;font-size:.8rem;cursor:pointer}
 .cap{font-style:italic;color:#555;font-size:.88rem;text-align:center;margin:14px 0 6px;line-height:1.5}
 .legend{display:flex;gap:18px;justify-content:center;font-size:.8rem;color:#444;margin-bottom:10px}
 .sw{display:inline-block;width:24px;height:11px;border-radius:2px;vertical-align:middle;margin-right:5px}
 table{width:100%;border-collapse:collapse}
 th{font-size:.74rem;color:#667;text-transform:uppercase;letter-spacing:.03em;padding:4px 6px;text-align:center}
 td{padding:3px 6px;font-size:.82rem;border-bottom:1px solid #f0f1f3}
 .date{white-space:nowrap;color:#333;font-weight:600;font-size:.8rem}
 .bar{position:relative;height:22px;background:#f1f2f4;border-radius:3px;overflow:hidden}
 .half-sep{position:absolute;top:0;bottom:0;left:50%;width:2px;background:#fff}
 .seg{position:absolute;top:0;bottom:0;display:flex;align-items:center;justify-content:center;font-size:.68rem;font-weight:700;color:#1a1f2e;overflow:hidden}
 .mins,.pm{text-align:center;font-variant-numeric:tabular-nums;font-weight:700}
 .pm.pos{color:#1f8a4c}.pm.neg{color:#c0392b}
 .none{color:#999;font-style:italic;font-size:.78rem}
</style></head><body><div class="wrap">
 <h1>Moorpark — Single Lineup</h1>
 <div class="sub">Game-by-game on-court stints from the logged defensive possessions (8 games, 2025-26). Pick up to 5 players to see only stints where they share the floor. Prototype.</div>
 <div id="chips" class="chips"></div>
 <div class="tools"><button class="btn" onclick="clearSel()">Clear</button>
   <span id="selnote" style="font-size:.82rem;color:#667"></span></div>
 <div id="cap" class="cap"></div>
 <div class="legend">
   <span><span class="sw" style="background:linear-gradient(90deg,#c0392b,#e8a9a0)"></span>negative +/- (on court)</span>
   <span><span class="sw" style="background:linear-gradient(90deg,#a9d8bb,#1f8a4c)"></span>positive +/- (on court)</span>
   <span><span class="sw" style="background:#e2e4e8"></span>at least one selected player off</span>
 </div>
 <table><thead><tr><th style="text-align:left">Game</th><th>First Half</th><th>Second Half</th><th>Mins</th><th>+/-</th></tr></thead>
 <tbody id="rows"></tbody></table>
</div>
<script>
const ROSTER=__ROSTER__, GAMES=__GAMES__;
const ORDER=Object.keys(ROSTER).sort((a,b)=>+a-+b);
let SEL=new Set();
function color(pm){ if(pm==null) return '#e2e4e8';
  const i=Math.min(1,Math.abs(pm)/12), a=0.30+0.65*i;
  return pm>=0?`rgba(31,138,76,${a})`:`rgba(192,57,43,${a})`; }
function qualifies(st){ for(const p of SEL) if(st.lineup.indexOf(p)<0) return false; return true; }
function seg(st){ const hoff=(st.half-1)*1200;
  let f0=(st.start-hoff)/1200, f1=(st.end-hoff)/1200;
  f0=Math.max(0,Math.min(1,f0)); f1=Math.max(0,Math.min(1,f1));
  const left=(st.half===1?0:50)+f0*50, w=(f1-f0)*50;
  return {left,w}; }
function renderChips(){ const c=document.getElementById('chips');
  c.innerHTML=ORDER.map(n=>`<div class="chip ${SEL.has(n)?'on':''}" onclick="tog('${n}')">#${n} ${ROSTER[n]}</div>`).join('');
  const names=[...SEL].map(n=>ROSTER[n]);
  document.getElementById('selnote').textContent=SEL.size?`${SEL.size} selected`:'no filter — showing every stint';
  document.getElementById('cap').textContent=SEL.size?
    `Stints with ${names.length>1?'all of ':''}${names.join(', ')} on the court together. Bars show Moorpark's +/- per stint; gray = a selected player was off.`:
    `Showing all stints. Select players to filter to lineups featuring them together.`;
}
function tog(n){ if(SEL.has(n)) SEL.delete(n); else { if(SEL.size>=5) return; SEL.add(n);} render(); }
function clearSel(){ SEL.clear(); render(); }
function render(){ renderChips();
  const keys=Object.keys(GAMES).sort();
  let html='';
  for(const k of keys){ const g=GAMES[k];
    const onAll=g.stints.filter(s=>qualifies(s)&&s.mins>0);  // ignore 0-duration double-sub artifacts
    const mins=onAll.reduce((a,s)=>a+s.mins,0);
    const pm=onAll.reduce((a,s)=>a+(s.pm||0),0);
    const present=SEL.size===0||onAll.length>0;
    // two separate half-bars for a clean 1st/2nd-half split
    const h1=g.stints.filter(s=>s.half===1), h2=g.stints.filter(s=>s.half===2);
    const mkbar=(arr)=>arr.map(st=>{ const hoff=(st.half-1)*1200;
        let f0=Math.max(0,Math.min(1,(st.start-hoff)/1200)), f1=Math.max(0,Math.min(1,(st.end-hoff)/1200));
        const w=(f1-f0)*100; if(w<=0) return '';
        const q=qualifies(st), bg=q?color(st.pm):'#e9eaee';
        const lbl=(q&&st.pm!=null&&w>7)?(st.pm>0?'+'+st.pm:st.pm):'';
        const tip=`H${st.half} ${fmt(st.start)}–${fmt(st.end)} | ${st.mins}m | ${st.pm>0?'+':''}${st.pm} | ${st.lineup.map(x=>'#'+x).join(' ')}`;
        return `<div class="seg" style="left:${f0*100}%;width:${w}%;background:${bg}" title="${tip}">${lbl}</div>`;
      }).join('');
    const pmcls=pm>0?'pos':(pm<0?'neg':'');
    const minsTxt=present?mins.toFixed(1):'0.0';
    const pmTxt=present?(pm>0?'+'+pm:pm):'—';
    html+=`<tr><td class="date">${g.date.slice(5)} ${g.opp}</td>`+
      `<td><div class="bar">${mkbar(h1)}</div></td>`+
      `<td><div class="bar">${mkbar(h2)}</div></td>`+
      `<td class="mins">${present?minsTxt:'<span class=none>—</span>'}</td>`+
      `<td class="pm ${pmcls}">${SEL.size&&!present?'<span class=none>not together</span>':pmTxt}</td></tr>`;
  }
  document.getElementById('rows').innerHTML=html;
}
function fmt(el){ const h=el<1200?el:el-1200; const r=1200-h; return Math.floor(r/60)+':'+String(r%60).padStart(2,'0'); }
render();
</script></body></html>"""

out = (HTML.replace("__ROSTER__", json.dumps(DATA["_roster"]))
           .replace("__GAMES__", json.dumps(DATA["_games"])))
open("moorpark_single_lineup.html", "w").write(out)
print("Wrote moorpark_single_lineup.html")
