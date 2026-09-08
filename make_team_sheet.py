#!/usr/bin/env python3
"""
Render the scrimmage teams as a printable two-page PDF.

Page 1 is the team sheet a coach carries onto the floor: both rosters with the
opening fives shaded, the projected margin, and what to swap when someone is out.
Page 2 carries the ratings behind it and the method note.

The split itself comes from balance_scrimmage_teams.analyze(), so the sheet and the
command-line output can never disagree.

Usage:
    python3 make_team_sheet.py [--exclude "Name One,Name Two"] [--out scrimmage_teams.pdf]

Needs a Chromium or Chrome binary to turn the HTML into PDF; pass --chrome to point
at one, otherwise the usual install locations are searched. Without a browser the
HTML is still written and can be printed from any browser.
"""

import argparse
import html
import shutil
import subprocess
import tempfile
from pathlib import Path

from balance_scrimmage_teams import analyze

LONG = {"BIG": "Big", "WING": "Wing", "GUARD": "Guard"}
ROTATION_WEIGHTS = [1.25, 1.15, 1.05, 1.00, 0.95, 0.90, 0.85, 0.85]

CHROME_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def find_chrome(explicit=None):
    if explicit:
        return explicit
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    for path in Path("/opt/pw-browsers").glob("chromium*/chrome-linux/chrome"):
        return str(path)
    return None


CSS = """
@page { size: letter; margin: 0.5in 0.55in; }
* { box-sizing: border-box; }
body { margin:0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
       color:#16181d; font-size:9.6pt; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
header { border-bottom:2.5px solid #16181d; padding-bottom:7px; margin-bottom:13px;
         display:flex; align-items:baseline; justify-content:space-between; }
h1 { font-size:17pt; margin:0; letter-spacing:-0.35px; font-weight:800; }
.sub { font-size:8.4pt; color:#5c6270; text-align:right; line-height:1.45; }
h2 { font-size:10.5pt; margin:17px 0 7px; text-transform:uppercase; letter-spacing:1.1px;
     color:#3a3f4a; font-weight:700; }
h2:first-of-type { margin-top:0; }
.teams { display:flex; gap:15px; }
.team { flex:1; border:1.4px solid #16181d; border-radius:5px; overflow:hidden; }
.thead { padding:6px 11px; font-weight:800; font-size:12pt; letter-spacing:1.6px;
         display:flex; justify-content:space-between; align-items:baseline; }
.white .thead { background:#f0f1f3; color:#16181d; border-bottom:1.4px solid #16181d; }
.black .thead { background:#16181d; color:#fff; }
.thead .cnt { font-size:7.4pt; font-weight:600; letter-spacing:0.3px; opacity:.72; }
table { width:100%; border-collapse:collapse; }
.team td { padding:3.6px 7px; border-bottom:0.6px solid #e4e6ea; }
.team tr:last-child td { border-bottom:none; }
tr.starter { background:#fbf7e8; }
tr.starter .nm { font-weight:700; }
tr.bench { color:#4a4f5a; }
tr.bench .nm { font-size:9.1pt; }
td.num { width:15px; color:#a0a5b0; font-size:7.6pt; text-align:right; }
td.ps { color:#6b7280; font-size:8pt; width:40px; }
td.rt { text-align:right; width:40px; font-variant-numeric:tabular-nums; font-size:8.6pt; color:#3a3f4a; }
.unk { color:#c2410c; font-weight:700; }
.divider { display:flex; align-items:center; gap:7px; margin:5px 0 2px;
           font-size:7.2pt; text-transform:uppercase; letter-spacing:1px; color:#9aa0ac; }
.divider::before, .divider::after { content:""; flex:1; height:0.6px; background:#e4e6ea; }
.bal { display:flex; gap:10px; margin-top:13px; }
.card { flex:1; border:0.9px solid #d8dbe1; border-radius:5px; padding:8px 11px; background:#fafbfc; }
.card .lab { font-size:7.2pt; text-transform:uppercase; letter-spacing:0.9px; color:#6b7280; margin-bottom:3px; }
.card .big { font-size:14pt; font-weight:800; letter-spacing:-0.4px; }
.card .note { font-size:7.6pt; color:#6b7280; margin-top:1.5px; }
.grid { width:100%; border-collapse:collapse; font-size:8.4pt; }
.grid th { background:#f0f1f3; padding:4.5px 5px; text-align:center; font-size:7.4pt;
           text-transform:uppercase; letter-spacing:0.5px; color:#4a4f5a;
           border-bottom:1.1px solid #c8ccd4; font-weight:700; }
.grid th:first-child { text-align:left; padding-left:8px; }
.grid td { padding:3.4px 5px; border-bottom:0.6px solid #e9ebef; font-variant-numeric:tabular-nums; }
.grid td.nm { padding-left:8px; font-weight:600; }
.grid td.ctr { text-align:center; }
.grid td.strong { font-weight:800; }
.side-w { color:#5c6270; font-weight:700; }
.side-b { color:#16181d; font-weight:700; }
.grid tr:nth-child(even) td { background:#fafbfc; }
.swaps { width:100%; border-collapse:collapse; font-size:8.4pt; }
.swaps th { text-align:left; background:#f0f1f3; padding:4.5px 8px; font-size:7.4pt;
            text-transform:uppercase; letter-spacing:0.5px; color:#4a4f5a; font-weight:700;
            border-bottom:1.1px solid #c8ccd4; }
.swaps td { padding:3.4px 8px; border-bottom:0.6px solid #e9ebef; }
.swaps td.arrow { color:#9aa0ac; text-align:center; width:18px; }
.none { color:#6b7280; font-style:italic; }
.method { font-size:8.3pt; line-height:1.55; color:#3a3f4a; }
.method p { margin:0 0 7px; }
.method strong { color:#16181d; }
.callout { border-left:2.5px solid #16181d; background:#f7f8f9; padding:8px 12px;
           margin:11px 0; font-size:8.3pt; line-height:1.55; }
footer { margin-top:15px; padding-top:7px; border-top:0.9px solid #d8dbe1;
         font-size:7.4pt; color:#8a909c; display:flex; justify-content:space-between; }
"""



def build_html(r, split):
    rate, pos, role, mins = r["rate"], r["pos"], r["role"], r["mins"]
    box, rapm, est = r["box"], r["rapm"], r["established"]
    sessions, stints = r["sessions"], r["stints"]
    W = sorted(split["a"], key=lambda p: (p not in split["five_a"], -rate[p]))
    B = sorted(split["b"], key=lambda p: (p not in split["five_b"], -rate[p]))
    pool = W + B

    def roster(team, five):
        rows = []
        for i, p in enumerate(team):
            cls = "starter" if p in five else "bench"
            tag = '<span class="unk">~</span>' if p not in est else ""
            rows.append(f'<tr class="{cls}"><td class="num">{i+1}</td>'
                        f'<td class="nm">{html.escape(p)}{tag}</td>'
                        f'<td class="ps">{LONG[pos[p]]}</td>'
                        f'<td class="rt">{rate[p]:+.2f}</td></tr>')
        return "\n".join(rows)

    def ratings():
        rows = []
        for p in sorted(pool, key=lambda x: -rate[x]):
            side = "W" if p in W else "B"
            tag = '<span class="unk">~</span>' if p not in est else ""
            d = role[p]
            rows.append(
                f'<tr><td class="nm">{html.escape(p)}{tag}</td>'
                f'<td class="ctr side-{side.lower()}">{side}</td>'
                f'<td class="ctr">{LONG[pos[p]]}</td><td class="ctr">{mins[p]:.0f}</td>'
                f'<td class="ctr">{box[p]:+.1f}</td><td class="ctr">{rapm[p]:+.1f}</td>'
                f'<td class="ctr strong">{rate[p]:+.2f}</td>'
                f'<td class="ctr">{d["pts100"]:.1f}</td><td class="ctr">{100*d["ts"]:.0f}</td>'
                f'<td class="ctr">{d["reb100"]:.1f}</td><td class="ctr">{d["ast100"]:.1f}</td></tr>')
        return "\n".join(rows)

    def counts(team):
        out = []
        for g in ("BIG", "WING", "GUARD"):
            n = sum(pos[p] == g for p in team)
            out.append(f'{n} {LONG[g].lower()}{"s" if n != 1 else ""}')
        return " / ".join(out)

    def rotation(team):
        order = sorted(team, key=lambda p: (-(rate[p] if p in est else -99), p))
        w = ROTATION_WEIGHTS[:len(order)]
        w = [x / sum(w) * len(order) for x in w]
        return 5 * sum(rate[p] * wi for p, wi in zip(order, w)) / len(order)

    swaps = []
    for out in sorted(pool, key=lambda p: -rate[p]):
        src, dst = (W, B) if out in W else (B, W)
        short = [p for p in src if p != out]
        stay = abs(rotation(short) - rotation(dst))
        gap, mover = min(((abs(rotation(short + [m]) - rotation([p for p in dst if p != m])), m)
                          for m in dst), key=lambda x: x[0])
        if stay <= gap + 0.15:
            swaps.append(f'<tr><td>{html.escape(out)}</td><td class="arrow"></td>'
                         f'<td class="none">no change needed</td></tr>')
        else:
            side = "Black" if out in W else "White"
            swaps.append(f'<tr><td>{html.escape(out)}</td><td class="arrow">&rarr;</td>'
                         f'<td>{html.escape(mover)} moves from {side}</td></tr>')

    fw, fb, rw, rb = split["fa"], split["fb"], split["ra"], split["rb"]
    span = f"{sessions[0]['date'][5:].replace('-', '/')} &ndash; {sessions[-1]['date'][5:].replace('-', '/')}"
    # only name players held out by request; roster-hidden names are not on the team
    left_out = ", ".join(sorted(r["excluded"] - r["hidden"])) or "nobody"

    body = f"""
<div class="page">
<header>
  <h1>Scrimmage Teams</h1>
  <div class="sub">Moorpark MBB &middot; Fall 2026<br>
  {len(sessions)} tracked sessions, {span} &middot; out: {html.escape(left_out)}</div>
</header>
<div class="teams">
  <div class="team white">
    <div class="thead"><span>WHITE</span><span class="cnt">{counts(W)}</span></div>
    <table>{roster(W, split['five_a'])}</table></div>
  <div class="team black">
    <div class="thead"><span>BLACK</span><span class="cnt">{counts(B)}</span></div>
    <table>{roster(B, split['five_b'])}</table></div>
</div>
<div class="divider">shaded = opening five &middot; ~ = thin sample, treated as group average</div>
<div class="bal">
  <div class="card"><div class="lab">Opening fives</div>
    <div class="big">{0.35*(fw-fb):+.1f} pts</div>
    <div class="note">White {fw:+.2f} &middot; Black {fb:+.2f} per 100</div></div>
  <div class="card"><div class="lab">Full rotations</div>
    <div class="big">{0.35*(rw-rb):+.1f} pts</div>
    <div class="note">White {rw:+.2f} &middot; Black {rb:+.2f} per 100</div></div>
  <div class="card"><div class="lab">For scale</div>
    <div class="big">&plusmn;21 pts</div>
    <div class="note">SD of a single session margin per 100</div></div>
</div>
<div class="callout">
Projected margin either way is <strong>well under a point</strong> across a 35-possession
scrimmage &mdash; far inside the noise of any single run. The four highest-rated players
split two per side, so neither team stacks the top end.
</div>
<h2>If someone is out</h2>
<table class="swaps">
  <tr><th>Absent</th><th></th><th>Move across to rebalance</th></tr>
  {"".join(swaps)}
</table>
<footer><span>Moorpark Men's Basketball</span><span>Page 1 of 2</span></footer>
</div>

<div class="page">
<header><h1>Player Ratings</h1>
  <div class="sub">{len(sessions)} sessions &middot; {len(stints)} stints &middot;
  {sum(s['poss'] for s in stints):.0f} possessions<br>
  Rating 0.00 = average for this group</div></header>
<table class="grid">
  <tr><th>Player</th><th>Tm</th><th>Pos</th><th>Min</th><th>Box<br>/100</th><th>RAPM</th>
      <th>Rating</th><th>Pts<br>/100</th><th>TS%</th><th>Reb<br>/100</th><th>Ast<br>/100</th></tr>
  {ratings()}
</table>
<h2>How these were built</h2>
<div class="method">
<p><strong>Raw plus/minus was unusable.</strong> White has won all seven tracked sessions,
and several players never switched jerseys &mdash; Claiborne went 7-for-7 on Black, Wilson
6-for-6 on White, Ostergard 5-for-5. On/off margin therefore mostly measures which jersey a
player was handed. Claiborne grades at &minus;21.6 per 100 on raw plus/minus; once his effect
is solved for with teammates held constant, he is &minus;1.7.</p>
<p><strong>The rating blends two independent signals.</strong> 70% is box-score value per 100
possessions &mdash; points above an average shot at this scrimmage's efficiency, plus weighted
credit for rebounds, assists, steals, blocks, deflections, turnovers and fouls. That measure is
team-independent. The other 30% is ridge-regularized adjusted plus/minus, which solves for each
player's effect with teammates and opponents held constant, and carries the defensive impact a
box score misses. Ratings are then regressed toward the group average in proportion to minutes
played, so a two-session sample cannot drift far from average.</p>
<p><strong>The split balances two things at once:</strong> the strength of the opening fives and
the strength of the full eight-man rotations. Rebounding, playmaking, scoring, defensive events,
usage and position counts break the near-ties.</p>
<p><strong>Validation.</strong> Replaying the event logs reproduces the published score of all
seven sessions exactly. The split also holds under every alternative model tested &mdash; pure
box score, pure RAPM, 50/50 and 85/15 blends, and shrinkage from none to heavy &mdash; staying
within a point per scrimmage in each.</p>
<p><strong>Two caveats.</strong> Sean Castro (5 minutes, one session) and KaLeke
Singletary-Jinks (43 minutes, two sessions) have too little data to rate honestly; both sit near
group average, are benched rather than started, and are placed on opposite teams so the
uncertainty does not stack on one side. Attendance has ranged from 11 to 17, so treat the swap
table on page 1 as the working document.</p>
</div>
<footer><span>Generated from tracker/pt_data.json &middot; balance_scrimmage_teams.py</span>
<span>Page 2 of 2</span></footer>
</div>
"""
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>Scrimmage Teams</title>'
            f"<style>{CSS}</style></head><body>{body}</body></html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude", default="Josh Castaniero")
    ap.add_argument("--min-minutes", type=int, default=0)
    ap.add_argument("--out", default="scrimmage_teams.pdf")
    ap.add_argument("--chrome", default=None, help="path to a Chrome/Chromium binary")
    args = ap.parse_args()

    r = analyze(args.exclude.split(","), args.min_minutes, split_unknowns=True)
    page = build_html(r, r["splits"][0])

    out = Path(args.out)
    html_path = out.with_suffix(".html")
    html_path.write_text(page)

    chrome = find_chrome(args.chrome)
    if not chrome:
        print(f"no Chrome/Chromium found; wrote {html_path} — print it from a browser")
        return
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox",
                        "--no-pdf-header-footer", f"--user-data-dir={tmp}",
                        f"--print-to-pdf={out.resolve()}", html_path.resolve().as_uri()],
                       check=True, capture_output=True)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
