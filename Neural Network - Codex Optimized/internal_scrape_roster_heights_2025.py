#!/usr/bin/env python3
"""
Internal roster-height scraper for CCCMBCA 2025-26.

Goal:
- Start from the roster index page.
- Follow team roster links.
- Extract player names + heights.
- Save to CSV that feeds internal_build_player_roles_2025.py.

Notes:
- Uses a browser-like User-Agent to reduce 403 risk.
- If pages still block, script saves failed URLs so you can retry manually.

Usage:
  python3 internal_scrape_roster_heights_2025.py
  python3 internal_scrape_roster_heights_2025.py --index-url https://www.cccmbca.org/sports/mbkb/2025-26/Roster_Page
    python3 internal_scrape_roster_heights_2025.py --links-file internal_data/roster_links_2025_26.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

INDEX_URL_DEFAULT = "https://www.cccmbca.org/sports/mbkb/2025-26/Roster_Page"
OUT_DIR = Path("internal_data")
OUT_CSV = OUT_DIR / "roster_heights_2025_26.csv"
OUT_CLASS_CSV = OUT_DIR / "player_class_2025_26.csv"
OUT_FAILED = OUT_DIR / "roster_height_failed_urls_2025_26.json"
DEFAULT_LINKS_FILE = OUT_DIR / "roster_links_2025_26.txt"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._in_a = False
        self._href = ""
        self._txt = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href", "")
            self._in_a = True
            self._href = href
            self._txt = []

    def handle_data(self, data):
        if self._in_a:
            self._txt.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._in_a:
            text = " ".join("".join(self._txt).split())
            self.links.append((self._href, text))
            self._in_a = False
            self._href = ""
            self._txt = []


class SimpleTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_data: list[str] = []
        self._row: list[str] = []
        self._table: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "table":
            self._in_table = True
            self._table = []
        elif t == "tr" and self._in_table:
            self._in_row = True
            self._row = []
        elif t in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell_data = []

    def handle_data(self, data):
        if self._in_cell:
            self._cell_data.append(data)

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td", "th") and self._in_cell:
            val = " ".join("".join(self._cell_data).split())
            self._row.append(val)
            self._in_cell = False
            self._cell_data = []
        elif t == "tr" and self._in_row:
            if any(cell.strip() for cell in self._row):
                self._table.append(self._row)
            self._in_row = False
            self._row = []
        elif t == "table" and self._in_table:
            if self._table:
                self.tables.append(self._table)
            self._in_table = False
            self._table = []


def fetch_html(url: str, insecure: bool = False) -> str:
    ctx = ssl._create_unverified_context() if insecure else ssl.create_default_context()

    parsed = urlparse(url)
    host = parsed.netloc
    bare_host = host[4:] if host.startswith("www.") else host
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path

    variants = [url]
    if host.startswith("www."):
        variants.append(f"{parsed.scheme}://{bare_host}{path}")
    elif bare_host:
        variants.append(f"{parsed.scheme}://www.{bare_host}{path}")
    if parsed.scheme == "https":
        variants.append(f"http://{host}{path}")
    elif parsed.scheme == "http":
        variants.append(f"https://{host}{path}")

    # Keep order and remove duplicates.
    deduped_variants: list[str] = []
    seen = set()
    for u in variants:
        if u in seen:
            continue
        seen.add(u)
        deduped_variants.append(u)

    last_error = "unknown fetch failure"
    for _attempt in range(3):
        for candidate in deduped_variants:
            try:
                req = Request(
                    candidate,
                    headers={
                        "User-Agent": UA,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Referer": "https://www.cccmbca.org/",
                    },
                )
                with urlopen(req, timeout=30, context=ctx) as resp:
                    content_type = resp.headers.get_content_charset() or "utf-8"
                    body = resp.read()
                    html = body.decode(content_type, errors="replace")

                if html.strip():
                    return html
                last_error = f"empty_html_response from {candidate}"
            except Exception as e:
                last_error = f"{e} [{candidate}]"

    raise RuntimeError(last_error)


def parse_height_to_inches(raw: str) -> int | None:
    s = (raw or "").strip().lower()
    s = s.replace("\u2019", "'").replace("\u2032", "'").replace('"', "")
    if not s:
        return None

    m = re.match(r"^(\d)\s*[-']\s*(\d{1,2})$", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))

    # Compact feet/inches style such as 6-11, 6'11, 6 11.
    m = re.search(r"\b([5-7])\s*[-' ]\s*(\d{1,2})\b", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))

    m = re.match(r"^(\d{2,3})$", s)
    if m:
        v = int(m.group(1))
        if 60 <= v <= 90:
            return v

    m = re.search(r"(\d)\s*ft\s*(\d{1,2})", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))

    return None


def parse_team_name(html: str, fallback: str) -> str:
    for meta_pat in [
        r"<meta[^>]+property=['\"]og:site_name['\"][^>]+content=['\"](.*?)['\"]",
        r"<meta[^>]+name=['\"]application-name['\"][^>]+content=['\"](.*?)['\"]",
    ]:
        m = re.search(meta_pat, html, flags=re.I | re.S)
        if m:
            t = " ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split())
            if t:
                return t

    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S)
    if m:
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = " ".join(t.split())
        if t:
            return t

    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if m:
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = " ".join(t.split())
        if t:
            return t

    return fallback


def infer_team_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    token = host.split(".")[0]
    token = re.sub(r"[^a-z0-9]+", " ", token).strip()
    if token:
        return " ".join(part.capitalize() for part in token.split())
    return url


def roster_links_from_index(index_url: str, html: str) -> list[str]:
    parser = LinkCollector()
    parser.feed(html)
    out = []
    seen = set()

    for href, txt in parser.links:
        if not href:
            continue
        if href.startswith("mailto:"):
            continue
        abs_url = urljoin(index_url, href)
        abs_url = abs_url.split("#", 1)[0]
        low = (abs_url + " " + txt).lower()

        if abs_url.lower() == index_url.lower().split("#", 1)[0]:
            continue

        # Generic filters for team roster pages
        if "roster" not in low:
            continue
        if any(low.endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx"]):
            continue
        if any(x in low for x in ["coach", "staff", "schedule", "news", "facebook", "instagram", "twitter"]):
            continue
        if abs_url not in seen:
            seen.add(abs_url)
            out.append(abs_url)

    return out


def normalize_class(raw: str) -> str:
    """Normalize a roster class/year cell to 'Fr' or 'So' (the only JUCO classes).

    Cell values arrive label-prefixed (e.g. 'Yr.: Freshman', 'Yr.: FR', 'Yr.: SO').
    Returns '' when the value is missing or unrecognized."""
    v = (raw or "").strip()
    if ":" in v:  # strip the 'Yr.:' style label prefix
        v = v.split(":", 1)[1].strip()
    vl = v.lower()
    if not vl:
        return ""
    if vl.startswith("so") or "soph" in vl:
        return "So"
    if vl.startswith("fr") or "fresh" in vl:
        return "Fr"
    if vl.startswith("jr") or "jun" in vl:
        return "Jr"
    if vl.startswith("sr") or "sen" in vl:
        return "Sr"
    return ""


def extract_name_height_rows(html: str) -> list[tuple[str, str, str]]:
    parser = SimpleTableParser()
    parser.feed(html)

    pairs: list[tuple[str, str, str]] = []

    for table in parser.tables:
        if not table:
            continue

        # Find likely header row.
        header_idx = None
        for i, row in enumerate(table[:3]):
            low = [c.lower() for c in row]
            if any("name" in c or "player" in c for c in low) and any("ht" in c or "height" in c for c in low):
                header_idx = i
                break

        if header_idx is None:
            continue

        header = [c.lower() for c in table[header_idx]]
        name_idx = None
        ht_idx = None
        yr_idx = None
        for i, c in enumerate(header):
            cs = c.strip().rstrip(".")
            if name_idx is None and ("name" in c or "player" in c):
                name_idx = i
            if ht_idx is None and ("ht" == c.strip() or "height" in c or c.strip().startswith("ht")):
                ht_idx = i
            if yr_idx is None and (cs in ("yr", "year", "class", "cl") or "year" in c):
                yr_idx = i

        if name_idx is None or ht_idx is None:
            continue

        for row in table[header_idx + 1 :]:
            if len(row) <= max(name_idx, ht_idx):
                continue
            # Sidearm pages self-label each cell ("Ht.: 6'1", "Yr.: FR",
            # "Cl.: Freshman"). Some render the jersey number twice, adding an
            # extra leading cell that shifts every column out of alignment with
            # the header. Prefer label-driven extraction (immune to the shift);
            # fall back to header position for plain, unlabeled tables.
            ht = ""
            yr = ""
            for c in row:
                cs = c.strip()
                if not ht:
                    m = re.match(r"(?i)^(?:ht|height)\s*\.?\s*:\s*(.+)$", cs)
                    if m:
                        ht = m.group(1).strip()
                if not yr:
                    m = re.match(r"(?i)^(?:yr|year|cl|class)\s*\.?\s*:\s*(.+)$", cs)
                    if m:
                        yr = normalize_class(m.group(1))
            # Column shift = extra leading cells beyond the header width.
            offset = max(0, len(row) - len(header))
            name = ""
            ni = name_idx + offset
            if 0 <= ni < len(row):
                name = row[ni].strip()
            # If the positional name landed on a labeled/numeric cell, scan for the
            # first plain (unlabeled, alphabetic) cell instead.
            if (not name) or (":" in name) or name.replace(".", "").isdigit():
                for c in row:
                    cs = c.strip()
                    if cs and ":" not in cs and not cs.replace(".", "").isdigit() and any(ch.isalpha() for ch in cs):
                        name = cs
                        break
            if not ht:
                hi = ht_idx + offset
                if 0 <= hi < len(row):
                    ht = row[hi].strip()
            if not yr and yr_idx is not None:
                yi = yr_idx + offset
                if 0 <= yi < len(row):
                    yr = normalize_class(row[yi])
            if not name or not ht:
                continue
            if parse_height_to_inches(ht) is None:
                continue
            pairs.append((name, ht, yr))

    if pairs:
        return pairs

    # Card-style roster pages: player name in heading and details text includes height.
    card_pat = re.compile(
        r"<h[23][^>]*>\s*(?:<span[^>]*>)?\s*([^<]+?)\s*(?:</span>)?\s*</h[23]>"
        r".*?"
        r"<p[^>]*class=['\"][^'\"]*title[^'\"]*['\"][^>]*>(.*?)</p>",
        flags=re.I | re.S,
    )
    for m in card_pat.finditer(html):
        name = " ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split())
        title_text = " ".join(re.sub(r"<[^>]+>", " ", m.group(2)).split())
        if not name:
            continue
        hm = re.search(r"\b([5-7][\u2019\u2032'\- ]\d{1,2}|[5-7]-\d{1,2})\b", title_text)
        if not hm:
            continue
        ht = hm.group(1).replace("\u2019", "'").replace("\u2032", "'")
        if parse_height_to_inches(ht) is None:
            continue
        # Card-style pages don't expose a structured class column; try a Fr/So
        # keyword in the title text, else leave blank.
        yr = ""
        ym = re.search(r"\b(freshman|sophomore|fr|so)\b", title_text, re.I)
        if ym:
            yr = normalize_class(ym.group(1))
        pairs.append((name, ht, yr))

    return pairs


def normalize_team_name(raw_team: str) -> str:
    t = re.sub(r"\s+Men'?s Basketball.*$", "", raw_team, flags=re.I)
    t = re.sub(r"\s+Roster.*$", "", t, flags=re.I)
    t = re.sub(r"\s+Athletics.*$", "", t, flags=re.I)
    t = re.sub(r"\s*[-|].*$", "", t).strip()
    return t


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape CCCMBCA roster heights for 2025-26")
    parser.add_argument("--index-url", default=INDEX_URL_DEFAULT)
    parser.add_argument(
        "--links-file",
        default=str(DEFAULT_LINKS_FILE),
        help="Optional text file of roster URLs (one per line). Used when index crawling is blocked.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS cert verification (internal use only; helpful for local Python cert issues).",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    links_file = Path(args.links_file)
    links = []
    if links_file.exists():
        for line in links_file.read_text().splitlines():
            u = line.strip()
            if not u or u.startswith("#"):
                continue
            links.append(u)

    if not links:
        index_html = fetch_html(args.index_url, insecure=args.insecure)
        if index_html.strip():
            links = roster_links_from_index(args.index_url, index_html)

    if not links and OUT_FAILED.exists():
        try:
            prev = json.loads(OUT_FAILED.read_text())
            links = [r.get("url", "") for r in prev if r.get("url")]
        except Exception:
            links = []

    if not links:
        raise SystemExit(
            "No roster links found. Provide roster links via --links-file "
            "(one URL per line)."
        )

    rows = []
    failed = []

    for url in links:
        try:
            html = fetch_html(url, insecure=args.insecure)
            team_fallback = infer_team_from_url(url)
            team_raw = parse_team_name(html, fallback=team_fallback)
            team = normalize_team_name(team_raw)
            pairs = extract_name_height_rows(html)
            if not pairs:
                failed.append({"url": url, "reason": "no_name_height_detected"})
                continue
            for name, height, klass in pairs:
                rows.append({"team": team, "player": name, "height": height,
                             "class": klass, "source_url": url})
        except Exception as e:
            failed.append({"url": url, "reason": str(e)})

    # Deduplicate this run by team+player; keep first seen.
    seen = set()
    deduped = []
    for r in rows:
        key = (r["team"].lower(), r["player"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    # MERGE with the existing CSV rather than overwrite. Many CCC roster pages sit
    # behind AWS WAF and fail on any given run; a blind overwrite would wipe good
    # data for teams that happened to be blocked this time. Teams successfully
    # re-scraped this run are fully replaced; all other teams keep their prior rows.
    rescraped_teams = {r["team"].lower() for r in deduped}
    existing = []
    if OUT_CSV.exists():
        with OUT_CSV.open(newline="") as f:
            for r in csv.DictReader(f):
                if r.get("team", "").lower() in rescraped_teams:
                    continue  # superseded by this run
                r.setdefault("class", "")  # older CSVs predate the class column
                existing.append(r)
    merged = existing + deduped
    merged.sort(key=lambda r: (r.get("team", "").lower(), r.get("player", "").lower()))

    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["team", "player", "height", "class", "source_url"])
        w.writeheader()
        for r in merged:
            w.writerow({k: r.get(k, "") for k in ["team", "player", "height", "class", "source_url"]})

    # Dedicated class CSV for the stats pipeline (team, player, class) — only rows
    # where a Fr/So class was actually detected. Merge across runs the same way so
    # class coverage accumulates as more teams become reachable.
    class_by_key = {}
    if OUT_CLASS_CSV.exists():
        with OUT_CLASS_CSV.open(newline="") as f:
            for r in csv.DictReader(f):
                if r.get("team", "").lower() in rescraped_teams:
                    continue
                if r.get("class"):
                    class_by_key[(r["team"], r["player"])] = r["class"]
    for r in deduped:
        if r.get("class"):
            class_by_key[(r["team"], r["player"])] = r["class"]
    with OUT_CLASS_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["team", "player", "class"])
        w.writeheader()
        for (team, player), klass in sorted(class_by_key.items()):
            w.writerow({"team": team, "player": player, "class": klass})

    OUT_FAILED.write_text(json.dumps(failed, indent=2))

    print(f"Index links discovered: {len(links)}")
    print(f"Rows this run: {len(deduped)} ({len(rescraped_teams)} teams); merged total: {len(merged)} -> {OUT_CSV}")
    print(f"Class rows (merged): {len(class_by_key)} -> {OUT_CLASS_CSV}")
    print(f"Failed links: {len(failed)} -> {OUT_FAILED}")


if __name__ == "__main__":
    main()
