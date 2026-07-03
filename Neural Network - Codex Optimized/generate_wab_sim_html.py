#!/usr/bin/env python3
"""Generate a standalone HTML file visualizing the WAB simulation (North/South split, bubble @24)."""
import json

data = json.load(open('wab_sim_split24.json'))
north = data['north']
south = data['south']

max_abs = max(abs(r['wab']) for r in north + south)

def row_html(i, r):
    wab = r['wab']
    bar_pct = round(abs(wab) / max_abs * 100)
    bar_color = '#2563eb' if wab >= 0 else '#dc2626'
    wab_cls = 'pos' if wab >= 0 else 'neg'
    gold = ' class="gold"' if r['team'] == 'Moorpark' else ''
    return (
        f'<tr{gold}>'
        f'<td class="rk">{i}</td>'
        f'<td class="team">{r["team"]}</td>'
        f'<td class="conf">{r["conference"]}</td>'
        f'<td class="val">{r["net"]:+.1f}</td>'
        f'<td class="val">{r["games"]}</td>'
        f'<td class="val"><span class="{wab_cls}">{wab:+.2f}</span>'
        f'<span class="bar-wrap"><span class="bar" style="width:{bar_pct}%;background:{bar_color}"></span></span></td>'
        f'</tr>'
    )

def bubble_row():
    return '<tr class="bubble-line"><td colspan="6">— Bubble Line (#24) —</td></tr>'

def table_html(rows, region):
    bubble_rank = 24
    body = ''
    for i, r in enumerate(rows, 1):
        body += row_html(i, r)
        if i == bubble_rank:
            body += bubble_row()
    return (
        '<div class="panel">'
        f'<div class="panel-title">{region} Region <span class="subtitle">Bubble @ #24</span></div>'
        '<div class="table-wrap">'
        '<table>'
        '<thead><tr>'
        '<th class="rk">#</th><th>Team</th><th>Conference</th>'
        '<th class="val">NET</th><th class="val">G</th><th class="val">WAB</th>'
        '</tr></thead>'
        f'<tbody>{body}</tbody>'
        '</table></div></div>'
    )

css = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f0f2f5; color: #111; padding: 20px; }
h1 { text-align: center; font-size: 1.4rem; margin-bottom: 4px; color: #1a1a2e; }
.subtitle-top { text-align: center; color: #666; font-size: 0.85rem; margin-bottom: 16px; }
.note { background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; padding: 10px 16px; font-size: 0.82rem; color: #555; margin-bottom: 20px; text-align: center; }
.panels { display: flex; gap: 20px; flex-wrap: wrap; }
.panel { flex: 1; min-width: 460px; background: #fff; border-radius: 10px; border: 1px solid #ddd; overflow: hidden; }
.panel-title { background: #1a1a2e; color: #fff; padding: 12px 16px; font-size: 1rem; font-weight: 700; }
.panel-title .subtitle { font-size: 0.78rem; font-weight: 400; color: #aac4e0; margin-left: 8px; }
.table-wrap { overflow-y: auto; max-height: 900px; }
table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
thead th { background: #2a2a4a; color: #fff; padding: 6px 8px; position: sticky; top: 0; z-index: 1; }
th.rk, td.rk { width: 32px; text-align: right; padding-right: 6px; color: #888; }
th.val, td.val { width: 60px; text-align: right; padding-right: 10px; }
td { padding: 4px 8px; border-bottom: 1px solid #eee; vertical-align: middle; }
tr:hover td { background: #f5f7fa; }
td.team { font-weight: 600; white-space: nowrap; }
td.conf { color: #555; font-size: 0.74rem; white-space: nowrap; }
span.pos { color: #1565c0; font-weight: 700; }
span.neg { color: #c62828; font-weight: 700; }
.bar-wrap { display: inline-block; width: 60px; height: 8px; background: #eee; border-radius: 4px; vertical-align: middle; margin-left: 6px; }
.bar { display: inline-block; height: 8px; border-radius: 4px; }
tr.bubble-line td { background: #ffd700; color: #333; font-weight: 700; text-align: center; font-size: 0.75rem; border-top: 2px solid #b8860b; border-bottom: 2px solid #b8860b; padding: 3px; }
tr.gold td { background: #fff9e0 !important; }
"""

html = (
    '<!DOCTYPE html><html><head><meta charset="UTF-8">'
    '<title>WAB Simulation — North/South Split, Bubble @24</title>'
    f'<style>{css}</style></head><body>'
    '<h1>WAB Simulation — North/South Fully Separated, Bubble @24</h1>'
    '<p class="subtitle-top">2025-26 Season &nbsp;|&nbsp; '
    'Current system: combined pool of ~100 teams, bubble @48 &nbsp;|&nbsp; '
    'This simulation: two separate pools (~47 North / ~53 South), bubble @24 each</p>'
    '<div class="note">Simulation only &mdash; not yet integrated into the leaderboard. '
    'North bubble: NET -1.33 &nbsp;|&nbsp; South bubble: NET +3.10 &nbsp;|&nbsp; '
    'WAB values are not comparable across regions (different bubble baselines).</div>'
    '<div class="panels">'
    + table_html(north, 'North')
    + table_html(south, 'South')
    + '</div></body></html>'
)

with open('wab_simulation.html', 'w') as f:
    f.write(html)
print("Saved wab_simulation.html")
