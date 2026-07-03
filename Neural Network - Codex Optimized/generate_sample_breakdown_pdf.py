from pathlib import Path
from matplotlib import pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle, Circle, Arc, FancyBboxPatch

OUT = Path('/Users/chadoconnor/Neural Network/sample_player_breakdown.pdf')

COLORS = {
    'bg': '#f4f1ea',
    'ink': '#101828',
    'muted': '#5f6b7a',
    'line': '#d7dce2',
    'panel': '#ffffff',
    'panel_soft': '#faf7f2',
    'accent': '#c2410c',
    'blue': '#2563eb',
    'green': '#16a34a',
    'red': '#dc2626',
    'gold': '#d97706',
}

PLAYER = {
    'name': 'J. Lee',
    'team': 'White',
    'minutes': 28.5,
    'points': 21,
    'reb': 4,
    'ast': 3,
    'stl': 2,
    'blk': 0,
    'tov': 1,
    'fgm': 8,
    'fga': 15,
    'fg3m': 4,
    'fg3a': 8,
    'ftm': 1,
    'fta': 2,
    'efg': 66.7,
    'ts': 68.4,
    'usg': 24.9,
    'ortg': 124,
    'shot_types': [
        ('Catch & Shoot', 4, 5),
        ('Pull-Up', 2, 4),
        ('Layup', 2, 3),
        ('Drive', 1, 2),
        ('Floater', 1, 1),
    ],
    'contests': [
        ('Uncontested', 6, 8),
        ('Contested', 2, 7),
    ],
}

TEAM = {
    'name': 'White',
    'score': 78,
    'opp_score': 71,
    'fgm': 31,
    'fga': 68,
    'fg3m': 8,
    'fg3a': 24,
    'ftm': 8,
    'fta': 11,
    'reb': 38,
    'ast': 19,
    'tov': 11,
    'efg': 50.0,
    'ts': 54.1,
    'ortg': 112.4,
    'drtg': 102.3,
    'net': 10.1,
    'poss': 69.4,
}

LINEUPS = [
    ('Q1', '12:00', '08:42', '3:18', 'A. Smith / J. Lee / M. Torres / D. Brown / R. Young', '+6', '8.4', '119', '96'),
    ('Q1', '08:42', '04:10', '4:32', 'A. Smith / J. Lee / M. Torres / D. Brown / K. Davis', '+1', '9.1', '111', '109'),
    ('Q2', '07:30', '02:05', '5:25', 'J. Lee / M. Torres / K. Davis / R. Young / T. Carter', '+4', '7.8', '118', '101'),
]

ACTIONS = [
    ('1:14', '2P Make', 'Catch & Shoot', 'Uncontested'),
    ('1:42', 'Sub', 'K. Davis in for D. Brown', ''),
    ('2:08', 'Assist', 'Kickout to J. Lee', ''),
    ('3:22', '2P Miss', 'Layup', 'Contested'),
    ('5:05', '3P Make', 'Pull-Up', 'Contested'),
    ('7:41', 'Sub', 'R. Young in for T. Carter', ''),
]

SHOT_POINTS = [
    (0.10, 0.18, COLORS['green']),
    (0.18, 0.36, COLORS['green']),
    (0.33, 0.52, COLORS['green']),
    (0.28, 0.68, COLORS['red']),
    (0.46, 0.40, COLORS['green']),
    (0.50, 0.24, COLORS['green']),
    (0.62, 0.74, COLORS['red']),
    (0.74, 0.53, COLORS['green']),
    (0.84, 0.21, COLORS['green']),
    (0.67, 0.34, COLORS['red']),
]


def add_panel(ax, x, y, w, h, title, subtitle=None):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        transform=ax.transAxes,
        boxstyle='round,pad=0.005,rounding_size=0.010',
        facecolor=COLORS['panel'],
        edgecolor=COLORS['line'],
        linewidth=1.0,
    ))
    ax.text(x + 0.014, y + h - 0.022, title, transform=ax.transAxes,
            color=COLORS['ink'], fontsize=12, fontweight='bold', va='top')
    if subtitle:
        ax.text(x + 0.014, y + h - 0.043, subtitle, transform=ax.transAxes,
                color=COLORS['muted'], fontsize=8.5, va='top')


def add_table_grid(ax, x, y, w, h, rows, cols, row_h=0.055, col_ws=None, header=True, font=8):
    def fit_cell_text(value, cell_w, font_size):
        text = str(value)
        # Conservative width heuristic for readable truncation in PDF tables.
        max_chars = max(4, int(cell_w * 150 / max(font_size, 6)))
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        return text[:max_chars - 1] + '…'

    col_ws = col_ws or [w / len(cols)] * len(cols)
    # outer box and header
    ax.add_patch(Rectangle((x, y), w, h, transform=ax.transAxes, facecolor=COLORS['panel'], edgecolor=COLORS['line'], linewidth=1.0))
    header_h = row_h if header else 0
    if header:
        ax.add_patch(Rectangle((x, y + h - header_h), w, header_h, transform=ax.transAxes, facecolor=COLORS['panel_soft'], edgecolor=COLORS['line'], linewidth=1.0))
        cx = x
        for c, cw in zip(cols, col_ws):
            header_cell = Rectangle((cx, y + h - header_h), cw, header_h, transform=ax.transAxes, facecolor='none', edgecolor=COLORS['line'], linewidth=0.8)
            ax.add_patch(header_cell)
            txt = ax.text(cx + 0.008, y + h - header_h / 2, fit_cell_text(c, cw, 8), transform=ax.transAxes, color=COLORS['muted'], fontsize=8, fontweight='bold', va='center', ha='left', clip_on=True)
            txt.set_clip_path(header_cell)
            cx += cw
    yy = y + h - header_h - row_h
    for ridx, row in enumerate(rows):
        row_fill = '#fcfcfd' if ridx % 2 == 1 else COLORS['panel']
        ax.add_patch(Rectangle((x, yy), w, row_h, transform=ax.transAxes, facecolor=row_fill, edgecolor='none'))
        cx = x
        for value, cw in zip(row, col_ws):
            cell = Rectangle((cx, yy), cw, row_h, transform=ax.transAxes, facecolor='none', edgecolor=COLORS['line'], linewidth=0.6)
            ax.add_patch(cell)
            txt = ax.text(cx + 0.008, yy + row_h / 2, fit_cell_text(value, cw, font), transform=ax.transAxes, color=COLORS['ink'], fontsize=font, va='center', ha='left', clip_on=True)
            txt.set_clip_path(cell)
            cx += cw
        ax.plot([x, x + w], [yy, yy], transform=ax.transAxes, color=COLORS['line'], linewidth=0.8)
        yy -= row_h


def draw_shot_map(ax):
    # Exact court orientation follows the live tracker shot chart.
    ax.add_patch(Rectangle((0.04, 0.10), 0.92, 0.76, fill=False, edgecolor=COLORS['line'], linewidth=1.3))
    ax.add_patch(Rectangle((0.41, 0.10), 0.18, 0.34, fill=False, edgecolor=COLORS['line'], linewidth=1.2))
    ax.add_patch(Arc((0.50, 0.44), 0.16, 0.16, theta1=0, theta2=180, edgecolor=COLORS['line'], linewidth=1.1))
    ax.add_patch(Circle((0.50, 0.44), 0.012, color='#9aa3af'))
    ax.add_patch(Arc((0.50, 0.44), 0.88, 0.88, theta1=22, theta2=158, edgecolor=COLORS['line'], linewidth=1.1))
    ax.add_patch(Rectangle((0.04, 0.10), 0.92, 0.00, fill=False, edgecolor='none'))
    for x, y, color in SHOT_POINTS:
        ax.add_patch(Circle((x, y), 0.015, facecolor=color, edgecolor='white', linewidth=0.5))


def page_one(pdf):
    fig = plt.figure(figsize=(8.5, 11), facecolor=COLORS['bg'])
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')

    ax.add_patch(Rectangle((0.04, 0.92), 0.92, 0.055, transform=ax.transAxes, facecolor=COLORS['accent'], edgecolor='none'))
    ax.text(0.06, 0.946, 'PLAYER HANDOUT', transform=ax.transAxes, color='white', fontsize=18, fontweight='bold', va='center')
    ax.text(0.94, 0.946, 'May 26, 2026', transform=ax.transAxes, color='white', fontsize=9, va='center', ha='right')

    add_panel(ax, 0.04, 0.76, 0.92, 0.13, PLAYER['name'], f"{PLAYER['team']} team  •  {PLAYER['minutes']} minutes  •  {PLAYER['points']} points")
    ax.text(0.06, 0.81, f"FG {PLAYER['fgm']}-{PLAYER['fga']}   3PT {PLAYER['fg3m']}-{PLAYER['fg3a']}   FT {PLAYER['ftm']}-{PLAYER['fta']}", transform=ax.transAxes, color=COLORS['ink'], fontsize=11, fontweight='bold')
    ax.text(0.06, 0.785, f"REB {PLAYER['reb']}   AST {PLAYER['ast']}   STL {PLAYER['stl']}   TOV {PLAYER['tov']}", transform=ax.transAxes, color=COLORS['muted'], fontsize=10)
    ax.text(0.62, 0.812, f"eFG {PLAYER['efg']}%", transform=ax.transAxes, color=COLORS['green'], fontsize=16, fontweight='bold')
    ax.text(0.62, 0.787, f"TS {PLAYER['ts']}%   ORTG {PLAYER['ortg']}", transform=ax.transAxes, color=COLORS['blue'], fontsize=13, fontweight='bold')
    ax.text(0.62, 0.763, f"USG {PLAYER['usg']}%", transform=ax.transAxes, color=COLORS['gold'], fontsize=13, fontweight='bold')

    # Summary boxes with fixed positions
    summary_positions = [
        (0.04, 0.63, 0.13, 0.095),
        (0.19, 0.63, 0.13, 0.095),
        (0.34, 0.63, 0.13, 0.095),
        (0.49, 0.63, 0.13, 0.095),
        (0.64, 0.63, 0.13, 0.095),
        (0.79, 0.63, 0.17, 0.095),
    ]
    summary_data = [
        ('Points', PLAYER['points'], COLORS['accent']),
        ('Minutes', PLAYER['minutes'], COLORS['blue']),
        ('FG', f"{PLAYER['fgm']}-{PLAYER['fga']}", COLORS['green']),
        ('3PT', f"{PLAYER['fg3m']}-{PLAYER['fg3a']}", COLORS['green']),
        ('FT', f"{PLAYER['ftm']}-{PLAYER['fta']}", COLORS['red']),
        ('REB', PLAYER['reb'], COLORS['gold']),
    ]
    for (x, y, w, h), (label, value, color) in zip(summary_positions, summary_data):
        ax.add_patch(FancyBboxPatch((x, y), w, h, transform=ax.transAxes, boxstyle='round,pad=0.004,rounding_size=0.010', facecolor=COLORS['panel'], edgecolor=COLORS['line'], linewidth=1.0))
        ax.text(x + 0.010, y + h - 0.018, label, transform=ax.transAxes, color=COLORS['muted'], fontsize=8, fontweight='bold', va='top')
        ax.text(x + 0.010, y + 0.020, str(value), transform=ax.transAxes, color=color, fontsize=18, fontweight='bold', va='bottom')

    add_panel(ax, 0.04, 0.30, 0.92, 0.28, 'SHOT MIX', 'Shot type and contest breakdown for the player')
    shot_rows = [(lbl, f'{m}-{a}', f"{round(100*m/a) if a else 0}%") for lbl, m, a in PLAYER['shot_types']]
    add_table_grid(ax, 0.06, 0.335, 0.40, 0.205, shot_rows, ['Type', 'FGM-A', 'FG%'], row_h=0.038, col_ws=[0.20, 0.11, 0.09])

    contest_rows = [(lbl, f'{m}-{a}', f"{round(100*m/a) if a else 0}%") for lbl, m, a in PLAYER['contests']]
    add_table_grid(ax, 0.50, 0.335, 0.18, 0.205, contest_rows, ['Contest', 'FGM-A', 'FG%'], row_h=0.052, col_ws=[0.08, 0.05, 0.05])

    notes_x, notes_y, notes_w, notes_h = 0.70, 0.335, 0.22, 0.205
    ax.add_patch(FancyBboxPatch((notes_x, notes_y), notes_w, notes_h, transform=ax.transAxes, boxstyle='round,pad=0.004,rounding_size=0.010', facecolor=COLORS['panel_soft'], edgecolor=COLORS['line'], linewidth=1.0))
    ax.text(notes_x + 0.012, notes_y + notes_h - 0.020, 'PLAYER NOTES', transform=ax.transAxes, color=COLORS['ink'], fontsize=11, fontweight='bold', va='top')
    bullets = [
        '21 points on 8-for-15 shooting',
        '4-for-8 from three',
        'Strong catch-and-shoot volume',
        'Only 1 turnover',
    ]
    for i, txt in enumerate(bullets):
        ax.text(notes_x + 0.015, notes_y + notes_h - 0.055 - i * 0.034, f'• {txt}', transform=ax.transAxes, color=COLORS['ink'], fontsize=9, va='top')

    ax.text(0.04, 0.06, 'Page 1 is intentionally separated from the court and timeline so the player summary stays clean.', transform=ax.transAxes, color=COLORS['muted'], fontsize=8)
    pdf.savefig(fig, facecolor=fig.get_facecolor(), bbox_inches='tight')
    plt.close(fig)


def page_two(pdf):
    fig = plt.figure(figsize=(8.5, 11), facecolor=COLORS['bg'])
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')

    ax.add_patch(Rectangle((0.04, 0.92), 0.92, 0.055, transform=ax.transAxes, facecolor=COLORS['blue'], edgecolor='none'))
    ax.text(0.06, 0.946, 'SHOT MAP', transform=ax.transAxes, color='white', fontsize=18, fontweight='bold', va='center')
    ax.text(0.94, 0.946, 'Page 2', transform=ax.transAxes, color='white', fontsize=9, va='center', ha='right')

    add_panel(ax, 0.04, 0.09, 0.92, 0.80, 'SHOT CHART', 'Dedicated page for the court and shot locations')
    chart_ax = fig.add_axes([0.08, 0.16, 0.84, 0.66], facecolor='#0f172a')
    chart_ax.set_xlim(0, 1)
    chart_ax.set_ylim(0, 1)
    chart_ax.axis('off')

    draw_shot_map(chart_ax)
    chart_ax.text(0.05, 0.90, 'Made shots are green', color=COLORS['green'], fontsize=10, fontweight='bold', ha='left')
    chart_ax.text(0.05, 0.86, 'Missed shots are red', color=COLORS['red'], fontsize=10, fontweight='bold', ha='left')
    chart_ax.text(0.05, 0.82, 'Court orientation matches the live tracker shot chart', color=COLORS['muted'], fontsize=9, ha='left')

    # Tiny legend box in a specific position
    ax.add_patch(FancyBboxPatch((0.66, 0.13), 0.26, 0.12, transform=ax.transAxes, boxstyle='round,pad=0.004,rounding_size=0.010', facecolor=COLORS['panel'], edgecolor=COLORS['line'], linewidth=1.0))
    ax.text(0.675, 0.225, 'SHOT LEGEND', transform=ax.transAxes, color=COLORS['ink'], fontsize=10, fontweight='bold')
    ax.text(0.675, 0.198, 'Green dot = make', transform=ax.transAxes, color=COLORS['green'], fontsize=9)
    ax.text(0.675, 0.173, 'Red dot = miss', transform=ax.transAxes, color=COLORS['red'], fontsize=9)
    ax.text(0.675, 0.148, 'Court placed alone on this page', transform=ax.transAxes, color=COLORS['muted'], fontsize=8)

    pdf.savefig(fig, facecolor=fig.get_facecolor(), bbox_inches='tight')
    plt.close(fig)


def page_three(pdf):
    fig = plt.figure(figsize=(8.5, 11), facecolor=COLORS['bg'])
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')

    ax.add_patch(Rectangle((0.04, 0.92), 0.92, 0.055, transform=ax.transAxes, facecolor=COLORS['accent'], edgecolor='none'))
    ax.text(0.06, 0.946, 'LINEUP + ACTION TIMELINE', transform=ax.transAxes, color='white', fontsize=17, fontweight='bold', va='center')
    ax.text(0.94, 0.946, 'Page 3', transform=ax.transAxes, color='white', fontsize=9, va='center', ha='right')

    add_panel(ax, 0.04, 0.09, 0.92, 0.80, 'TIMELINE', 'Lineup stints and action timestamps shown in a fixed layout')

    lineup_rows = [
        [q, start, end, dur, lineup, score, poss, ortg, drtg]
        for q, start, end, dur, lineup, score, poss, ortg, drtg in LINEUPS
    ]
    add_table_grid(
        ax, 0.06, 0.47, 0.86, 0.30, lineup_rows,
        ['Q', 'Start', 'End', 'Dur', 'Lineup', 'Score', 'Poss', 'ORTG', 'DRTG'],
        row_h=0.070,
        col_ws=[0.05, 0.08, 0.08, 0.08, 0.32, 0.08, 0.08, 0.10, 0.09],
        font=7.6,
    )

    action_rows = [
        [q, video, typ, det]
        for q, video, typ, det in ACTIONS
    ]
    add_table_grid(
        ax, 0.06, 0.14, 0.86, 0.26, action_rows,
        ['Q', 'Video', 'Type', 'Details'],
        row_h=0.048,
        col_ws=[0.06, 0.10, 0.16, 0.54],
        font=8,
    )

    ax.text(0.06, 0.41, 'Top table: player stints with exact on/off windows.', transform=ax.transAxes, color=COLORS['muted'], fontsize=8)
    ax.text(0.06, 0.37, 'Bottom table: action log with timestamps for film review.', transform=ax.transAxes, color=COLORS['muted'], fontsize=8)

    pdf.savefig(fig, facecolor=fig.get_facecolor(), bbox_inches='tight')
    plt.close(fig)


def build_pdf():
    with PdfPages(OUT) as pdf:
        page_one(pdf)
        page_two(pdf)
        page_three(pdf)
    return OUT


if __name__ == '__main__':
    print(build_pdf())
