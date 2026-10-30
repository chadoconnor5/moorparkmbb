"""Play-by-play from a PrestoSports box score page. The plays are on the same page scrape.py already fetches for the
box score (no extra request), so they're read from that HTML and saved once per game (scrape.save_box) as
"<season> Play by Play/<YYYYMMDD>_<visitor>_at_<home>.json":

    {"visitor": "Mt. San Antonio", "home": "Citrus",
     "linescore": {"Mt. San Antonio": [41, 37], "Citrus": [43, 45]},      # points by half (+ overtimes)
     "cols": ["period", "clock", "team", "player", "action", "v", "h"],
     "plays": [[1, "19:38", 0, "GATES,DAYVON", "missed jump shot", 0, 0], ...]}   # team 0 visitor / 1 home;
                                                                                    # v / h: the score after the play

The same file carries "periods": each half's (and overtime's) box score from the page's period tabs, as
{"1": {team label: [players in parse_boxscore's format]}, "2": {...}} (parse_periods); the leaderboard's box scores
show them under 1st Half / 2nd Half. A page with period boxes but no play-by-play saves just those.

Player names are as the play-by-play writes them ("LAST,FIRST"); action is the text after the name ("made layup",
"enters the game", "goes to the bench") or before it ("Foul by", "Assist by", "Turnover by", "Steal by", "Block by")."""

import html as _html
import re

COLS = ["period", "clock", "team", "player", "action", "v", "h"]   # team: 0 visitor, 1 home; v / h: score after
_ROW = re.compile(r'<tr class="row (visitor|home)[^"]*">\s*<td class="time">([^<]*)</td>(.*?)</tr>', re.S)
_PERIOD = re.compile(r'id="prd(\d+)"')
_TEXT = re.compile(r'<span class="text">(.*?)</span>', re.S)
_SCORE = re.compile(r'<span class="v-score">(\d+)</span>.*?<span class="h-score">(\d+)</span>', re.S)
_BY = re.compile(r"^(Foul|Assist|Turnover|Steal|Block|Timeout)\s+by\s+(.+)$", re.I)


def _clean(s):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


# The plays that follow the player's name (lowercase; names are capitals). The site writes some names out of order
# ("SILVA,CAIO DA" for Caio Da Silva, "JR,KEIAN WILLIAMS" for Keian Williams Jr., "JOHNSON,RODERICK (QUICK)"), so
# the name is everything before the play, not "LAST,FIRST" up to the first space.
_ACT = re.compile(r"^(.+?)\s+((?:made|missed|enters the game|goes to the bench|offensive rebound|defensive rebound"
                  r"|deadball rebound|team rebound|blocked)\b.*)$")


def _split(text):
    """(player, action) from a play's text."""
    m = _BY.match(text)
    if m:
        return m.group(2).strip(), f"{m.group(1)} by"
    m = _ACT.match(text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^([A-Z][A-Z' .\-]*,[A-Z' .\-]+?|TEAM)\s+(\S.*)$", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", text


def fix_plays(pj):
    """Repair a saved file's plays split before _ACT (a name's last word left on the action: "SILVA,CAIO" + "DA missed
    3-pt. jump shot"): the play is re-split from its text. Returns pj (its plays fixed in place)."""
    for p in pj.get("plays") or []:
        player, action = p[3] or "", p[4] or ""
        if not action or _ACT.match("X " + action) or _BY.match(action + " X") or action.endswith(" by"):
            continue
        name, act = _split(f"{player} {action}".strip())
        if name and act != action and _ACT.match("X " + act):
            p[3], p[4] = name, act
    return pj


def _linescore(page, visitor, home):
    i = page.find("linescore")
    if i < 0:
        return {}
    j = page.find("</table>", i)
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page[i:j], re.S):
        cells = [_clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) >= 3 and cells[0] in (visitor, home) and all(c.isdigit() for c in cells[1:]):
            out[cells[0]] = [int(c) for c in cells[1:-1]]   # by period, without the total
    return out


def parse(page, visitor, home):
    """The plays (and points by half) from a box score page; None when the page has no play-by-play."""
    marks = [(m.start(), int(m.group(1))) for m in _PERIOD.finditer(page)]
    if not marks:
        return None
    plays, v, h = [], 0, 0
    for m in _ROW.finditer(page):
        period = max((p for pos, p in marks if pos < m.start()), default=1)
        side, clock, rest = m.group(1), m.group(2).strip(), m.group(3)
        text = " ".join(_clean(t) for t in _TEXT.findall(rest)).strip()
        if not text:
            continue
        sc = _SCORE.search(rest)
        if sc:
            v, h = int(sc.group(1)), int(sc.group(2))
        player, action = _split(text)
        plays.append([period, clock, 0 if side == "visitor" else 1, player, action, v, h])   # COLS
    if not plays:
        return None
    return {"visitor": visitor, "home": home, "linescore": _linescore(page, visitor, home), "cols": COLS, "plays": plays}


BOX_COLS = ["MIN", "FGM-A", "3PM-A", "FTM-A", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS"]


def parse_periods(page):
    """Each period's box score (the page's 1st Half / 2nd Half / OT tabs): {"1": {team label: [players]}, ...}, the
    players in scrape_team.parse_boxscore's format ({"name": "#2 Jeremy Williams", "stats": {...}, "role", "is_starter"}).
    {} when the page has none."""
    out = {}
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'id="period-tabpanel-(\d+)"', page)]
    for i, (pos, per) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else page.find("</section>", pos) if page.find("</section>", pos) > 0 else len(page)
        seg = page[pos:end]
        teams = {}
        for tbl in re.findall(r"<table[^>]*>(.*?)</table>", seg, re.S):
            cap = re.search(r"<caption[^>]*>(.*?)</caption>", tbl, re.S)
            label = _clean(cap.group(1)) if cap else ""
            if not label or "MIN" not in tbl:
                continue
            players, role = [], None
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S):
                head = re.search(r"<th[^>]*>(.*?)</th>", row, re.S)
                cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
                name = _clean(head.group(1)) if head else ""
                up = name.upper()
                if up in ("PLAYER", ""):
                    continue
                if up.startswith("STARTERS"):
                    role = "starter"; continue
                if up.startswith("RESERVES"):
                    role = "reserve"; continue
                if up.startswith("TOTALS") or up.startswith("TM") or up.startswith("TEAM") or len(cells) < len(BOX_COLS):
                    continue
                name = re.sub(r"^[A-Z]{1,2} (\d+ )", r"\1", name)   # position first on some pages: "F 31 Name"
                parts = name.split(" ", 1)
                if parts[0].isdigit() and len(parts) > 1:
                    name = f"#{parts[0]} {parts[1].strip()}"
                p = {"name": name, "stats": dict(zip(BOX_COLS, cells[:len(BOX_COLS)]))}
                if role:
                    p["role"], p["is_starter"] = role, role == "starter"
                players.append(p)
            if players:
                teams[label] = players
        if len(teams) == 2:
            out[per] = teams
    return out
