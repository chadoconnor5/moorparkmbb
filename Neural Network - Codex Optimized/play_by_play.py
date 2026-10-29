"""Play-by-play from a PrestoSports box score page. The plays are on the same page scrape.py already fetches for the
box score (no extra request), so they're read from that HTML and saved once per game (scrape.save_box) as
"<season> Play by Play/<YYYYMMDD>_<visitor>_at_<home>.json":

    {"visitor": "Mt. San Antonio", "home": "Citrus",
     "linescore": {"Mt. San Antonio": [41, 37], "Citrus": [43, 45]},      # points by half (+ overtimes)
     "plays": [{"period": 1, "clock": "19:38", "team": "Mt. San Antonio", "player": "GATES,DAYVON",
                "action": "missed jump shot", "v": 0, "h": 0}, ...]}       # v / h: the score after the play

Player names are as the play-by-play writes them ("LAST,FIRST"); action is the text after the name ("made layup",
"enters the game", "goes to the bench") or before it ("Foul by", "Assist by", "Turnover by", "Steal by", "Block by")."""

import html as _html
import re

_ROW = re.compile(r'<tr class="row (visitor|home)[^"]*">\s*<td class="time">([^<]*)</td>(.*?)</tr>', re.S)
_PERIOD = re.compile(r'id="prd(\d+)"')
_TEXT = re.compile(r'<span class="text">(.*?)</span>', re.S)
_SCORE = re.compile(r'<span class="v-score">(\d+)</span>.*?<span class="h-score">(\d+)</span>', re.S)
_BY = re.compile(r"^(Foul|Assist|Turnover|Steal|Block|Timeout)\s+by\s+(.+)$", re.I)


def _clean(s):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _split(text):
    """(player, action) from a play's text."""
    m = _BY.match(text)
    if m:
        return m.group(2).strip(), f"{m.group(1)} by"
    m = re.match(r"^([A-Z][A-Z' .\-]*,[A-Z' .\-]+?|TEAM)\s+(\S.*)$", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", text


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
        plays.append({"period": period, "clock": clock, "team": visitor if side == "visitor" else home,
                      "player": player, "action": action, "v": v, "h": h})   # the text is player + action
    if not plays:
        return None
    return {"visitor": visitor, "home": home, "linescore": _linescore(page, visitor, home), "plays": plays}
