#!/usr/bin/env python3
"""
Playwright-based roster height scraper for CCCMBCA 2025-26.

Handles JS-rendered Sidearm Sports pages (and other dynamic pages) that
returned 'no_name_height_detected' from the urllib-based scraper. Also
optionally retries HTTP 403 URLs since a real browser UA may bypass them.

Reads:   internal_data/roster_height_failed_urls_2025_26.json
Appends: internal_data/roster_heights_2025_26.csv
Writes:  internal_data/roster_height_failed_urls_2025_26.json  (updated failures)

Usage:
  python3 internal_scrape_roster_heights_playwright_2025.py
  python3 internal_scrape_roster_heights_playwright_2025.py --also-403
  python3 internal_scrape_roster_heights_playwright_2025.py --headless false
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

OUT_DIR = Path("internal_data")
OUT_CSV = OUT_DIR / "roster_heights_2025_26.csv"
OUT_FAILED = OUT_DIR / "roster_height_failed_urls_2025_26.json"

# ---------------------------------------------------------------------------
# Height parser (same as original script)
# ---------------------------------------------------------------------------

def parse_height_to_inches(raw: str) -> int | None:
    s = (raw or "").strip().lower()
    s = s.replace("\u2019", "'").replace("\u2032", "'").replace('"', "")
    if not s:
        return None
    m = re.match(r"^(\d)\s*[-']\s*(\d{1,2})$", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    m = re.search(r"\b([5-7])\s*[-' ]\s*(\d{1,2})\b", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    m = re.match(r"^(\d{2,3})$", s)
    if m:
        v = int(m.group(1))
        if 60 <= v <= 90:
            return v
        # Centimeter height (e.g. 185 → ~73 inches)
        if 150 <= v <= 230:
            return round(v / 2.54)
    m = re.search(r"(\d)\s*ft\s*(\d{1,2})", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    return None


# ---------------------------------------------------------------------------
# In-browser extraction helpers (run inside page.evaluate)
# ---------------------------------------------------------------------------

_JS_EXTRACT = """
() => {
  const results = [];

  // ---- Strategy 1: Sidearm table layout ----
  // Each player row: th = name, td[data-label="Ht."] = height
  const tableRows = Array.from(document.querySelectorAll('table tbody tr'));
  if (tableRows.length > 0) {
    for (const tr of tableRows) {
      const nameTh = tr.querySelector('th');
      const htTd =
        tr.querySelector('td[data-label="Ht."]') ||
        tr.querySelector('td[data-label="Ht"]') ||
        tr.querySelector('td[data-label="Height"]') ||
        tr.querySelector('td[data-label="height"]');
      if (!nameTh || !htTd) continue;
      const name = (nameTh.innerText || '').trim().replace(/\\s+/g, ' ');
      let ht = (htTd.innerText || '').trim().replace(/\\s+/g, ' ');
      // Strip label prefix like "Ht.: " that some sites include
      ht = ht.replace(/^(ht\\.?|height):?\\s*/i, '');
      if (name && ht) results.push([name, ht]);
    }
    if (results.length > 0) return results;
  }

  // ---- Strategy 2: Any [data-label] containing "ht" ----
  const htCells = Array.from(document.querySelectorAll('[data-label]')).filter(el => {
    const lbl = (el.getAttribute('data-label') || '').toLowerCase().trim();
    return lbl === 'ht.' || lbl === 'ht' || lbl === 'height';
  });
  if (htCells.length > 0) {
    for (const htCell of htCells) {
      const tr = htCell.closest('tr');
      if (!tr) continue;
      let nameEl =
        tr.querySelector('th') ||
        tr.querySelector('[data-label*="Name"]') ||
        tr.querySelector('[data-label*="name"]');
      if (!nameEl) continue;
      const name = (nameEl.innerText || '').trim().replace(/\\s+/g, ' ');
      let ht = (htCell.innerText || '').trim().replace(/\\s+/g, ' ');
      ht = ht.replace(/^(ht\\.?|height):?\\s*/i, '');
      if (name && ht) results.push([name, ht]);
    }
    if (results.length > 0) return results;
  }

  // ---- Strategy 3: Sidearm card layout ----
  const cards = Array.from(document.querySelectorAll(
    '.s-person-card, .roster-player, .roster-bio-item, [class*="person-card"]'
  ));
  if (cards.length > 0) {
    for (const card of cards) {
      const nameEl =
        card.querySelector('.s-person-card__name') ||
        card.querySelector('.full-name') ||
        card.querySelector('[class*="player-name"]') ||
        card.querySelector('h3') ||
        card.querySelector('h2');
      const htEl =
        card.querySelector('[class*="height"]') ||
        card.querySelector('[data-stat="height"]') ||
        card.querySelector('[class*="ht"]');
      if (!nameEl || !htEl) continue;
      const name = (nameEl.innerText || '').trim().replace(/\\s+/g, ' ');
      const ht = (htEl.innerText || '').trim().replace(/\\s+/g, ' ');
      if (name && ht) results.push([name, ht]);
    }
    if (results.length > 0) return results;
  }

  // ---- Strategy 4: Generic table header scan ----
  // Finds the "Ht." column by header index and the player name from th[scope=row].
  // IMPORTANT: When the Name column is rendered as th[scope=row] (not a td),
  // the actual td index of any column AFTER Name is (headerIndex - 1).
  for (const table of Array.from(document.querySelectorAll('table'))) {
    const theadRow = table.querySelector('thead tr') || table.querySelector('tr');
    if (!theadRow) continue;
    const colHeaders = Array.from(theadRow.querySelectorAll('th[scope="col"], th:not([scope])')).map(th =>
      (th.innerText || '').trim().toLowerCase().replace(/[.]+$/, '')
    );
    const nameIdx = colHeaders.findIndex(h => h === 'name' || h === 'player');
    const htIdxHeader = colHeaders.findIndex(h => h === 'ht' || h === 'height' || h.startsWith('ht'));
    if (htIdxHeader < 0) continue;
    // If Name column (rendered as th) comes before Ht in the header, subtract 1 to get the td index.
    const htIdxTd = htIdxHeader - (nameIdx >= 0 && nameIdx < htIdxHeader ? 1 : 0);
    for (const tr of Array.from(table.querySelectorAll('tbody tr'))) {
      const nameTh = tr.querySelector('th[scope="row"]') || tr.querySelector('th');
      const tds = Array.from(tr.querySelectorAll('td'));
      if (!nameTh || tds.length <= htIdxTd) continue;
      const name = (nameTh.innerText || '').trim().replace(/\\s+/g, ' ');
      const ht = (tds[htIdxTd].innerText || '').trim().replace(/\\s+/g, ' ');
      if (name && ht) results.push([name, ht]);
    }
    if (results.length > 0) return results;
  }

  return results;
}
"""


# ---------------------------------------------------------------------------
# Team name extraction
# ---------------------------------------------------------------------------

def get_team_name(page, url: str) -> str:
    title = page.title()
    # Sidearm titles often look like:
    #   "2025-26 XYZ Men's Basketball Roster - School Name Athletics"
    #   "2025-2026 Men's Basketball Roster - Imperial Valley College"
    # Try extracting the part AFTER the last " - " separator first.
    if " - " in title:
        after_dash = title.rsplit(" - ", 1)[-1]
        candidate = re.sub(r"\s+Athletics.*$", "", after_dash, flags=re.I).strip()
        if candidate and len(candidate) > 3:
            return candidate
    # Fallback: strip common prefixes
    t = re.sub(r"^\d{4}-\d{2,4}\s+", "", title)
    t = re.sub(r"\s+Men'?s Basketball.*$", "", t, flags=re.I)
    t = re.sub(r"\s+Roster.*$", "", t, flags=re.I)
    t = re.sub(r"\s+Athletics.*$", "", t, flags=re.I)
    t = re.sub(r"\s*[-|].*$", "", t).strip()
    if t:
        return t
    host = urlparse(url).netloc.lstrip("www.")
    token = host.split(".")[0]
    return " ".join(p.capitalize() for p in re.sub(r"[^a-z0-9]+", " ", token.lower()).split())


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def add_view_list(url: str) -> str:
    """Append ?view=list if no query string already present."""
    if "?" in url:
        return url
    return url + "?view=list"


def is_binary_url(url: str) -> bool:
    low = url.lower()
    return any(low.endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx"])


def is_redirect_url(url: str) -> bool:
    return "cccmbca.org/x/" in url


# ---------------------------------------------------------------------------
# Single-URL scraper
# ---------------------------------------------------------------------------

def scrape_url(page, url: str) -> tuple[str, list[tuple[str, str]], str | None]:
    """
    Returns (team_name, [(player_name, height_raw), ...], error_or_None).
    error_or_None is None on success, otherwise a short reason string.
    """
    target = add_view_list(url)
    try:
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=30_000)
        except Exception as nav_err:
            err_str = str(nav_err)
            # If navigation was interrupted by another navigation (e.g. Cloudflare
            # bounce from a previous URL), wait for load state and continue.
            if "interrupted by another navigation" in err_str:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15_000)
                except Exception:
                    pass
            else:
                raise
        # Wait for the main content — table rows or player cards
        try:
            page.wait_for_selector(
                "table tbody tr, .s-person-card, .roster-player, .roster-bio-item",
                timeout=10_000,
            )
        except PWTimeout:
            pass  # May still have content; try extraction anyway

        team = get_team_name(page, url)
        pairs: list[list[str]] = page.evaluate(_JS_EXTRACT)

        if not pairs:
            return team, [], "no_name_height_detected"

        # Filter to rows with parseable heights
        valid = [(n, h) for n, h in pairs if parse_height_to_inches(h) is not None]
        if not valid:
            return team, [], "heights_found_but_unparseable"

        return team, valid, None

    except PWTimeout:
        return "", [], "page_load_timeout"
    except Exception as e:
        return "", [], str(e)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def load_existing_csv() -> tuple[list[dict], set[tuple[str, str]]]:
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    if OUT_CSV.exists():
        with OUT_CSV.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
                seen.add((row["team"].lower(), row["player"].lower()))
    return rows, seen


def save_csv(rows: list[dict]) -> None:
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["team", "player", "height", "source_url"])
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Playwright roster height scraper for 2025-26")
    ap.add_argument(
        "--also-403",
        action="store_true",
        help="Also retry URLs that failed with HTTP 403 (browser UA may bypass them).",
    )
    ap.add_argument(
        "--headless",
        default="true",
        choices=["true", "false"],
        help="Run browser headlessly (default: true).",
    )
    ap.add_argument(
        "--url",
        help="Scrape a single URL instead of the full failed list (for testing).",
    )
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load failed list
    if not OUT_FAILED.exists():
        print(f"Failed URL file not found: {OUT_FAILED}", file=sys.stderr)
        sys.exit(1)

    failed_data: list[dict] = json.loads(OUT_FAILED.read_text())

    # Decide which URLs to process
    if args.url:
        to_process = [{"url": args.url, "reason": "manual"}]
    else:
        to_process = []
        for entry in failed_data:
            url = entry.get("url", "")
            reason = entry.get("reason", "")
            if is_binary_url(url) or is_redirect_url(url):
                continue
            if "no_name_height" in reason or "unparseable" in reason:
                to_process.append(entry)
            elif args.also_403 and ("403" in reason or "Forbidden" in reason):
                to_process.append(entry)

    print(f"URLs to attempt with Playwright: {len(to_process)}")
    if not to_process:
        print("Nothing to do.")
        return

    # Load existing CSV rows
    existing_rows, existing_keys = load_existing_csv()
    new_rows: list[dict] = []
    new_failures: list[dict] = []
    still_failed_urls = {e["url"] for e in failed_data if e.get("url") not in {t["url"] for t in to_process}}

    headless = args.headless != "false"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        # Block images/fonts for speed
        page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf}",
            lambda route: route.abort(),
        )

        for i, entry in enumerate(to_process, 1):
            url = entry["url"]
            print(f"[{i}/{len(to_process)}] {url}", end="  ", flush=True)
            team, pairs, error = scrape_url(page, url)

            if error:
                print(f"FAIL: {error}")
                new_failures.append({"url": url, "reason": error})
            else:
                added = 0
                for name, height in pairs:
                    key = (team.lower(), name.lower())
                    if key in existing_keys:
                        continue
                    existing_keys.add(key)
                    new_rows.append(
                        {"team": team, "player": name, "height": height, "source_url": url}
                    )
                    added += 1
                print(f"OK: {len(pairs)} players, {added} new ({team})")

        page.close()
        context.close()
        browser.close()

    # Persist results
    if new_rows:
        all_rows = existing_rows + new_rows
        save_csv(all_rows)
        print(f"\nAdded {len(new_rows)} new player rows -> {OUT_CSV}")
    else:
        print("\nNo new player rows to add.")

    # Update failed JSON: keep non-web entries + new_failures
    if not args.url:
        attempted_urls = {e["url"] for e in to_process}
        # Keep non-web (PDFs, docs, redirects) and any web entries that weren't attempted
        kept_non_web = [
            e for e in failed_data
            if is_binary_url(e.get("url", "")) or is_redirect_url(e.get("url", ""))
        ]
        kept_skipped = [
            e for e in failed_data
            if e.get("url") not in attempted_urls
            and not is_binary_url(e.get("url", ""))
            and not is_redirect_url(e.get("url", ""))
        ]
        # When --also-403 was NOT used, preserve 403 entries (they're already in kept_skipped)
        updated_failed = kept_non_web + kept_skipped + new_failures
    else:
        # Single-URL mode: don't touch the failed list
        updated_failed = failed_data

    if not args.url:
        OUT_FAILED.write_text(json.dumps(updated_failed, indent=2))
        print(f"Updated failed list: {len(updated_failed)} remaining -> {OUT_FAILED}")


if __name__ == "__main__":
    main()
