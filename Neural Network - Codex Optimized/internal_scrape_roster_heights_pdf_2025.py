#!/usr/bin/env python3
"""
Parse CCCMBCA roster PDFs and the Merritt .doc file for player heights.

Downloads PDFs from CloudFront CDN (via cccmbca.org HTML wrappers) and parses
each one. Merritt .doc is parsed using macOS textutil.

Usage:
    python3 internal_scrape_roster_heights_pdf_2025.py
"""

import csv
import json
import re
import subprocess
import tempfile
from pathlib import Path

import pdfplumber
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OUT_CSV = Path("internal_data/roster_heights_2025_26.csv")
OUT_FAILED = Path("internal_data/roster_height_failed_urls_2025_26.json")
CACHE_DIR = Path("internal_data/pdf_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# These are the cccmbca.org "PDF" URL wrappers + the Merritt .doc
SOURCE_FILES = [
    ("Alameda",      "https://www.cccmbca.org/sports/mbkb/2025-26/Rosters_2025-26/Alameda_roster.pdf"),
    ("Contra Costa", "https://www.cccmbca.org/sports/mbkb/2025-26/Rosters_2025-26/Contra_Costa.pdf"),
    ("Mendocino",    "https://www.cccmbca.org/sports/mbkb/2025-26/Rosters_2025-26/Mendocino_roster.pdf"),
    ("Yuba",         "https://www.cccmbca.org/sports/mbkb/2025-26/Rosters_2025-26/Yuba.pdf"),
    ("Columbia",     "https://www.cccmbca.org/sports/mbkb/2025-26/Rosters_2025-26/Columbia.pdf"),
    ("LA Harbor",    "https://www.cccmbca.org/sports/mbkb/2025-26/Rosters_2025-26/LA_Harbor_roster.pdf"),
    ("LA Southwest", "https://www.cccmbca.org/sports/mbkb/2025-26/Rosters_2025-26/LASC_Roster_2025-2026.pdf"),
    ("Merritt",      "https://www.cccmbca.org/sports/mbkb/2025-26/Rosters_2025-26/Merritt_roster_2025-2026.doc"),
]

# ---------------------------------------------------------------------------
# Height parsing (shared with playwright scraper)
# ---------------------------------------------------------------------------

def parse_height_to_inches(raw: str) -> int | None:
    s = raw.strip()
    # Normalize various quote characters to standard ' and "
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    # 6'0" or 6'0 or 6'10"
    m = re.match(r"^(\d)'(\d{1,2})\"?$", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    # 6-0 or 6-10
    m = re.match(r"^(\d)-(\d{1,2})$", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    # 6 0  (space separated)
    m = re.match(r"^(\d)\s(\d{1,2})$", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    # Bare inches (60-90) or centimeters (150-230)
    m = re.match(r"^(\d{2,3})$", s)
    if m:
        v = int(m.group(1))
        if 60 <= v <= 90:
            return v
        if 150 <= v <= 230:
            return round(v / 2.54)
    # 6ft 0
    m = re.search(r"(\d)\s*ft\s*(\d{1,2})", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    return None


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def download_all_files(context) -> dict[str, Path]:
    """Download all source files, return {team: local_path}."""
    result: dict[str, Path] = {}

    for team, url in SOURCE_FILES:
        safe_name = team.replace(" ", "_")
        is_doc = url.endswith(".doc") or url.endswith(".docx")
        cache_path = CACHE_DIR / f"{safe_name}.{'doc' if is_doc else 'pdf'}"

        if cache_path.exists() and cache_path.stat().st_size > 10_000:
            result[team] = cache_path
            continue

        resp = context.request.get(url)
        ct = resp.headers.get("content-type", "")
        body_bytes = resp.body()

        if "html" in ct:
            # cccmbca.org wrapper — find the CloudFront object tag
            html = body_bytes.decode("utf-8", errors="ignore")
            obj = re.search(r'<object[^>]+data="([^"]+)"', html, re.I)
            if obj:
                cdn_url = obj.group(1)
                r2 = context.request.get(cdn_url)
                data = r2.body()
                cache_path.write_bytes(data)
                result[team] = cache_path
            else:
                print(f"  WARNING: no <object> tag found for {team}")
        else:
            # Direct binary (.doc)
            cache_path.write_bytes(body_bytes)
            result[team] = cache_path

    return result


# ---------------------------------------------------------------------------
# PDF parsing strategies
# ---------------------------------------------------------------------------

def _find_ht_col(header_row: list[str | None]) -> int:
    """Return index of the height column in a table header row, or -1."""
    for i, cell in enumerate(header_row):
        if cell and re.search(r'\bh[te]', cell, re.I):
            return i
    return -1


def _find_name_col(header_row: list[str | None]) -> int:
    """Return index of the name column, or -1."""
    for i, cell in enumerate(header_row):
        if cell and re.search(r'\bname\b', cell, re.I):
            return i
    return -1


def parse_pdf_table(path: Path) -> list[tuple[str, str]]:
    """Parse a PDF using pdfplumber table extraction."""
    results: list[tuple[str, str]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                header = table[0]
                ht_col = _find_ht_col(header)
                name_col = _find_name_col(header)
                if ht_col < 0:
                    continue
                if name_col < 0:
                    # fallback: Name is typically col 1 or 2
                    name_col = 1 if len(header) > 1 else 0
                for row in table[1:]:
                    if not row or len(row) <= max(ht_col, name_col):
                        continue
                    name = (row[name_col] or "").strip().replace("\n", " ")
                    ht_raw = (row[ht_col] or "").strip()
                    if name and parse_height_to_inches(ht_raw) is not None:
                        results.append((name, ht_raw))
    return results


# Normalize smart/curly quotes to ASCII equivalents
def _normalize_quotes(s: str) -> str:
    return (
        s.replace("\u2018", "'")
         .replace("\u2019", "'")
         .replace("\u201c", '"')
         .replace("\u201d", '"')
         .replace("\u2032", "'")
         .replace("\u2033", '"')
    )


# Height pattern used in text-based extraction
_HT_RE = re.compile(
    r"\b([56]'[\d]{1,2}\"?|[56]-\d{1,2}|[56]\s\d{1,2}|[56]')\b"
)

# Name pattern: 2+ words, each starting with capital, no digits
_NAME_RE = re.compile(r"^[A-Z][a-z'\-]+(?:\s+[A-Z][a-z'\-]+)+$")


def parse_pdf_text(path: Path) -> list[tuple[str, str]]:
    """
    Parse a text-layout PDF (no table detected) by reading each line and
    finding lines that start with a number (jersey #) and contain a height.
    """
    results: list[tuple[str, str]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = _normalize_quotes(line.strip())
                # Must start with a digit (jersey number)
                if not line or not line[0].isdigit():
                    continue
                # Find height in the line
                m = _HT_RE.search(line)
                if not m:
                    continue
                ht_raw = m.group(1)
                if parse_height_to_inches(ht_raw) is None:
                    continue
                # Extract name: remove the jersey number at the start,
                # then grab everything up to the first height token.
                before_ht = line[:m.start()]
                # Strip leading jersey number
                name_part = re.sub(r"^\d+\s*", "", before_ht).strip()
                # Clean: keep only name-like token (letters, spaces, hyphens, apostrophes)
                name = re.sub(r"[^A-Za-z '\-]", "", name_part).strip()
                name = re.sub(r"\s+", " ", name)
                if len(name) >= 4:
                    results.append((name, ht_raw))
    return results


def parse_pdf(path: Path) -> list[tuple[str, str]]:
    """Try table extraction first, fall back to text."""
    results = parse_pdf_table(path)
    if results:
        return results
    return parse_pdf_text(path)


# ---------------------------------------------------------------------------
# DOC parsing (Merritt — binary OLE2 .doc, use macOS textutil)
# ---------------------------------------------------------------------------

def parse_doc(path: Path) -> list[tuple[str, str]]:
    """Extract (name, height) pairs from a binary .doc file via textutil."""
    try:
        proc = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True, text=True, timeout=30
        )
        text = proc.stdout
    except Exception as e:
        print(f"  textutil error: {e}")
        return []

    results: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = _normalize_quotes(line.strip())
        if not line or not line[0].isdigit():
            continue
        m = _HT_RE.search(line)
        if not m:
            continue
        ht_raw = m.group(1)
        if parse_height_to_inches(ht_raw) is None:
            continue
        before_ht = line[:m.start()]
        name_part = re.sub(r"^\d+\s*", "", before_ht).strip()
        name = re.sub(r"[^A-Za-z '\-\.]", "", name_part).strip()
        name = re.sub(r"\s+", " ", name)
        if len(name) >= 4:
            results.append((name, ht_raw))
    return results


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def load_existing_csv() -> tuple[list[dict], set[tuple[str, str]]]:
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    if OUT_CSV.exists():
        with OUT_CSV.open(newline="") as f:
            for row in csv.DictReader(f):
                rows.append(row)
                seen.add((row["team"].lower(), row["player"].lower()))
    return rows, seen


def write_csv(rows: list[dict]) -> None:
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["team", "player", "height", "source_url"])
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    existing_rows, seen = load_existing_csv()
    new_rows: list[dict] = []

    print("Downloading files...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        local_files = download_all_files(context)
        browser.close()

    print(f"\nParsing {len(local_files)} files:")
    success_urls: set[str] = set()

    for team, url in SOURCE_FILES:
        path = local_files.get(team)
        if path is None:
            print(f"  [{team}] SKIP: download failed")
            continue

        is_doc = path.suffix.lower() in (".doc", ".docx")
        pairs = parse_doc(path) if is_doc else parse_pdf(path)

        added = 0
        for name, ht_raw in pairs:
            key = (team.lower(), name.lower())
            if key not in seen:
                seen.add(key)
                new_rows.append({
                    "team": team,
                    "player": name,
                    "height": str(parse_height_to_inches(ht_raw)),
                    "source_url": url,
                })
                added += 1

        status = f"OK: {len(pairs)} players, {added} new" if pairs else "FAIL: no heights extracted"
        print(f"  [{team}] {status}")
        if pairs:
            success_urls.add(url)

    if new_rows:
        all_rows = existing_rows + new_rows
        write_csv(all_rows)
        print(f"\nAdded {len(new_rows)} new rows -> {OUT_CSV}")
    else:
        print("\nNo new rows to add.")

    # Remove resolved entries from failed JSON
    if OUT_FAILED.exists() and success_urls:
        failed_data = json.loads(OUT_FAILED.read_text())
        remaining = [e for e in failed_data if e.get("url") not in success_urls]
        removed = len(failed_data) - len(remaining)
        if removed:
            OUT_FAILED.write_text(json.dumps(remaining, indent=2))
            print(f"Removed {removed} resolved entries from failed list ({len(remaining)} remain)")


if __name__ == "__main__":
    main()
