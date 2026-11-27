"""One team's season stats page from an old season (before 2017-18), as a test before deciding on older seasons.

    python3 scrape_old_team.py --season 2015-16 --team citrus

One page, one request, read through the installed Chrome like scrape.py's browser mode (the site refuses scripts).
Saves the page as served and every table on it (header + rows) to internal_data/old_seasons/<season>/<team>.html /
.json, then prints what it found. Nothing on the site uses it yet.
"""
import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from scrape import Fetcher

SITE = "https://cccmbca.prestosports.com/sports/mbkb"


class Tables(HTMLParser):
    """Every <table>: its caption (or the nearest heading before it), header cells and body rows, as text."""

    def __init__(self):
        super().__init__()
        self.tables, self.cur, self.row, self.cell, self.heading, self.in_h = [], None, None, None, "", False

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "caption"):
            self.in_h, self.heading = True, ""
        elif tag == "table":
            self.cur = {"title": self.heading.strip(), "header": [], "rows": []}
        elif tag == "tr" and self.cur is not None:
            self.row, self.all_th = [], True
        elif tag in ("td", "th") and self.row is not None:
            self.cell = ""
            self.all_th = self.all_th and tag == "th"

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "caption"):
            self.in_h = False
            if self.cur is not None and tag == "caption":
                self.cur["title"] = self.heading.strip()
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join(self.cell.split()))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.cur is not None:
            if self.row and not self.cur["header"] and self.all_th:
                self.cur["header"] = self.row          # the first all-<th> row is the header
            elif self.row:
                self.cur["rows"].append(self.row)
            self.row = None
        elif tag == "table" and self.cur is not None:
            self.tables.append(self.cur)
            self.cur = None

    def handle_data(self, data):
        if self.in_h:
            self.heading += data
        if self.cell is not None:
            self.cell += data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2015-16")
    ap.add_argument("--team", default="citrus", help="the team's slug in the site's address (teams/<slug>)")
    a = ap.parse_args()
    url = f"{SITE}/{a.season}/teams/{a.team}?jsRendering=true"
    out = Path("internal_data/old_seasons") / a.season
    out.mkdir(parents=True, exist_ok=True)
    f = Fetcher(max_requests=1, browser=True)
    print(f"Reading {url} (one page, through Chrome)")
    html = f.get(url)
    if re.search(r"rate limited|bot traffic|too many requests", html[:20000], re.I):   # stop: never push through it
        f.close()
        raise SystemExit("The site says it's rate limiting (heavy bot traffic). Nothing saved; wait a day before trying again.")
    (out / f"{a.team}.html").write_text(html, encoding="utf-8")
    p = Tables()
    p.feed(html)
    (out / f"{a.team}.json").write_text(json.dumps({"url": url, "tables": p.tables}, indent=1), encoding="utf-8")
    print(f"Saved {out / (a.team + '.html')} ({len(html) // 1024} KB) and {len(p.tables)} tables:")
    for t in p.tables:
        print(f"  {t['title'][:50]!r}: {len(t['rows'])} rows | {' '.join(t['header'][:14])}")
    f.close()


if __name__ == "__main__":
    main()
