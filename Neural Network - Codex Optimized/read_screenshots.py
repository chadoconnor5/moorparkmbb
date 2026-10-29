"""Box scores from screenshots, read on this computer (no site requests, nothing sent anywhere).

Folders, one per night: "2026-27 Box Score Screenshots/<Month>/<MMDD>/" (October/1029 ... March/0331, made for the
season; any folder named "1031", "10-31" or "2026-10-31" under it works too). In each, one screenshot per
team box (the box score page's table for one team: its name on top, Player / MIN / FGM-A ... PTS, STARTERS, RESERVES,
TM Team, TOTALS), named for the team and the date: "Citrus 1031.png" ("Citrus 1031 2.png" for a second shot of a box
that didn't fit; short names like "Mt SAC" are fine). The date in the name wins over the folder's.

    python read_screenshots.py              every night with something new
    python read_screenshots.py --date 1031  one night

Each screenshot is read with Tesseract (the possession tracker's copy, run in Chrome) and checked: every player's points
against his FG/3P/FT, REB = OREB + DREB, each column against TOTALS, minutes against 200 (+25 an overtime). Each one
also gets a CSV beside it with what was read: fix a number there and rerun, and the CSV is used instead of the image.
A game whose sides all check out is saved where scrape.py saves box scores, so the nightly counts it as done and never
asks the site for it. CHECK.txt in each night's folder lists what's saved and what needs fixing. Folders are never
renamed: screenshots can come in through the night or days later, and each run reads only what's new (a screenshot
already read is reused from its CSV, a game already saved is skipped), whatever the date.
scrape.py nightly reads that night's folder first on its own."""

import argparse
import base64
import csv
import functools
import http.server
import json
import os
import re
import socketserver
import sys
import threading
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
def root(season):
    return HERE / f"{season} Box Score Screenshots"   # <Month>/<MMDD>/ inside; screenshots stay out of git
COLS = ["MIN", "FGM-A", "3PM-A", "FTM-A", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS"]
PAIRS = ("FGM-A", "3PM-A", "FTM-A")
COUNTS = ["OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS"]
IMAGES = (".png", ".jpg", ".jpeg", ".webp")


# ---------------------------------------------------------------------------
# Reading the image (Tesseract in Chrome, the tracker's vendored copy)
# ---------------------------------------------------------------------------
class Reader:
    def __init__(self):
        self.page = None

    def _start(self):
        from playwright.sync_api import sync_playwright
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE.parent))
        handler.log_message = lambda *a, **k: None
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.pw = sync_playwright().start()
        self.browser = None
        tries = [{"channel": "chrome"}, {"channel": "msedge"}, {}]
        if os.environ.get("CHROME_PATH"):   # a specific Chrome/Chromium binary
            tries.insert(0, {"executable_path": os.environ["CHROME_PATH"]})
        for kw in tries:
            try:
                self.browser = self.pw.chromium.launch(headless=True, **kw)
                break
            except Exception:
                continue
        if self.browser is None:
            sys.exit("Couldn't start Chrome (pip install playwright; it uses the installed Chrome).")
        self.page = self.browser.new_page()
        self.page.goto(f"http://127.0.0.1:{self.httpd.server_address[1]}/poss/vendor/tess/")
        self.page.add_script_tag(url="tesseract.min.js")
        self.page.evaluate("""async () => {
            window.W = await Tesseract.createWorker('eng', 1, { workerPath: 'worker.min.js', corePath: '.',
                                                               langPath: '.', workerBlobURL: false });
            await W.setParameters({ tessedit_pageseg_mode: '6', preserve_interword_spaces: '1' });
        }""")

    def words(self, path: Path):
        """Every word with its box, the image scaled up 2x in grayscale (small screen text reads better)."""
        if self.page is None:
            self._start()
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/webp"
        url = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
        return self.page.evaluate("""async (url) => {
            const img = new Image(); img.src = url; await img.decode();
            const c = document.createElement('canvas'); c.width = img.width * 2; c.height = img.height * 2;
            const x = c.getContext('2d'); x.filter = 'grayscale(1)'; x.drawImage(img, 0, 0, c.width, c.height);
            const { data } = await W.recognize(c, {}, { blocks: true });
            const out = [];
            for (const b of data.blocks || []) for (const p of b.paragraphs) for (const l of p.lines) for (const w of l.words)
                out.push({ t: w.text, c: w.confidence, x0: w.bbox.x0, x1: w.bbox.x1, y0: w.bbox.y0, y1: w.bbox.y1 });
            return out;
        }""", url)

    def close(self):
        if self.page is not None:
            self.browser.close()
            self.pw.stop()
            self.httpd.shutdown()
            self.page = None


# ---------------------------------------------------------------------------
# Words -> table
# ---------------------------------------------------------------------------
_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "|": "1", "i": "1", "!": "1",
                      "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "g": "9", "—": "-", "–": "-", "_": "-", "~": "-"})


def _num(t):
    t = t.replace("n", "11").replace("N", "11")   # the box score font's "11" reads as "n"
    t = t.translate(_FIX).strip(".,:;'\"")
    return t if re.fullmatch(r"\d+(-\d+)?", t) else None


def _rows(words):
    """Words grouped into lines by their vertical middle."""
    ws = sorted(words, key=lambda w: (w["y0"] + w["y1"]) / 2)
    h = sorted(w["y1"] - w["y0"] for w in ws)[len(ws) // 2] if ws else 10
    rows, cur, mid = [], [], None
    for w in ws:
        m = (w["y0"] + w["y1"]) / 2
        if cur and m - mid > 0.6 * h:
            rows.append(sorted(cur, key=lambda w: w["x0"]))
            cur = []
        cur.append(w)
        mid = m if len(cur) == 1 else (mid * (len(cur) - 1) + m) / len(cur)
    if cur:
        rows.append(sorted(cur, key=lambda w: w["x0"]))
    return rows


def parse_words(words):
    """{"team": header name, "rows": [{name, role, MIN..PTS}], "team_row": {...}, "totals": {...}} from OCR words."""
    rows = _rows(words)
    hi = next((i for i, r in enumerate(rows) if {"MIN", "PTS"} <= {w["t"].upper().strip(".") for w in r}), None)
    if hi is None:
        raise ValueError("no header line (MIN ... PTS) found")
    head = rows[hi]
    title = " ".join(w["t"] for r in rows[:hi] for w in r).strip()
    hw = [w for w in head if w["t"].lower() != "player"]
    if len(hw) != len(COLS):
        raise ValueError(f"header has {len(hw)} columns, expected {len(COLS)}: {' '.join(w['t'] for w in hw)}")
    centers = [(w["x0"] + w["x1"]) / 2 for w in hw]
    name_edge = hw[0]["x0"] - 0.6 * (centers[1] - centers[0])
    out = {"title": title, "rows": [], "team_row": None, "totals": None}
    role = None
    for r in rows[hi + 1:]:
        label = " ".join(w["t"] for w in r if (w["x0"] + w["x1"]) / 2 < name_edge).strip()
        vals = {}
        for w in r:
            mx = (w["x0"] + w["x1"]) / 2
            if mx < name_edge:
                continue
            k = COLS[min(range(len(COLS)), key=lambda i: abs(centers[i] - mx))]
            v = _num(w["t"])
            if v is not None:
                vals[k] = v if k not in vals else vals[k]
            elif "%" not in w["t"]:
                vals.setdefault("_bad", []).append(f'{k}:"{w["t"]}"')
        up = label.upper()
        if up.startswith("STARTER"):
            role = "starter"; continue
        if up.startswith("RESERVE") or up.startswith("BENCH"):
            role = "reserve"; continue
        if up.startswith("TOTAL"):
            out["totals"] = vals; continue
        if "TEAM" in up and not re.match(r"^\d", label):
            out["team_row"] = vals; continue
        if not label or not vals or all(k == "_bad" for k in vals):
            continue
        m = re.match(r"^#?(\S+)\s+(.*)$", label)
        num, nm = (m.group(1), m.group(2)) if m and _num(m.group(1)) else ("", label)
        out["rows"].append({"num": (_num(num) or num), "name": nm.strip(), "role": role or "reserve", **vals})
    return out


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def _ma(v):
    m = re.fullmatch(r"(\d+)-(\d+)", str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _i(v):
    return int(v) if re.fullmatch(r"\d+", str(v or "")) else None


def _dropped(read, want):
    """A TOTALS number misread by one dropped digit (31-71 read as 31-7): the players' own sum stands."""
    return len(read) == len(want) - 1 and any(want[:i] + want[i + 1:] == read for i in range(len(want)))


def check(t):
    """Problems (list of strings) in a parsed side; repairs what the other numbers pin down (marked)."""
    probs = []
    for r in t["rows"]:
        who = f'{("#" + r["num"] + " ") if r["num"] else ""}{r["name"]}'
        for k in COLS:
            if k not in r:
                probs.append(f"{who}: {k} missing")
        for k in PAIRS:
            p = _ma(r.get(k))
            if k in r and not p:
                probs.append(f"{who}: {k} '{r[k]}' isn't made-attempts")
            elif p and p[0] > p[1]:
                probs.append(f"{who}: {k} {r[k]} made more than attempted")
        fg, tp, ft = (_ma(r.get(k)) for k in PAIRS)
        o, d, rb, pts = (_i(r.get(k)) for k in ("OREB", "DREB", "REB", "PTS"))
        if rb is None and o is not None and d is not None:   # REB unreadable: OREB + DREB settles it
            rb = o + d; r["REB"] = str(rb); r.setdefault("_fixed", []).append("REB")
            probs[:] = [p for p in probs if p != f"{who}: REB missing"]
        if o is not None and d is not None and rb is not None and o + d != rb:
            probs.append(f"{who}: REB {rb} but OREB {o} + DREB {d} = {o + d}")
        if fg and tp and ft:
            want = 2 * fg[0] + tp[0] + ft[0]
            if pts is None:
                r["PTS"] = str(want); r.setdefault("_fixed", []).append("PTS")
            elif pts != want:
                probs.append(f"{who}: PTS {pts} but FG {fg[0]}, 3P {tp[0]}, FT {ft[0]} make {want}")
            if tp[0] > fg[0] or tp[1] > fg[1]:
                probs.append(f"{who}: more threes than field goals ({r['3PM-A']} of {r['FGM-A']})")
    tot = t.get("totals") or {}
    team = t.get("team_row") or {}
    if not tot:
        probs.append("no TOTALS line read")
    else:
        for k in COLS[1:]:
            if k in PAIRS:
                s = [sum(_ma(r.get(k))[j] for r in t["rows"] if _ma(r.get(k))) for j in (0, 1)]
                tv = _ma(tot.get(k))
                if tv and tuple(s) != tv and not _dropped(str(tot[k]), f"{s[0]}-{s[1]}"):
                    probs.append(f"{k}: players add up to {s[0]}-{s[1]}, TOTALS say {tot[k]}")
            else:
                s = sum(_i(r.get(k)) or 0 for r in t["rows"]) + (_i(team.get(k)) or 0)
                tv = _i(tot.get(k))
                if tv is not None and s != tv and not _dropped(str(tot[k]), str(s)):
                    probs.append(f"{k}: players{' + team' if team.get(k) else ''} add up to {s}, TOTALS say {tv}")
    mins = [_i(r.get("MIN")) for r in t["rows"]]
    total_min = sum(m or 0 for m in mins)
    if total_min > 60 and all(abs(total_min - g) > 2 for g in (200, 225, 250, 275, 300)):
        probs.append(f"minutes add up to {total_min} (a game is 200, +25 an overtime)")
    return probs


# ---------------------------------------------------------------------------
# CSV beside each image (what was read; edit it to correct)
# ---------------------------------------------------------------------------
def write_csv(path: Path, t):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#", "Player", "Role"] + COLS)
        for r in t["rows"]:
            w.writerow([r["num"], r["name"], r["role"]] + [r.get(k, "") for k in COLS])
        w.writerow(["", "TM Team", "team"] + [(t.get("team_row") or {}).get(k, "") for k in COLS])
        w.writerow(["", "TOTALS", "totals"] + [(t.get("totals") or {}).get(k, "") for k in COLS])


def read_csv(path: Path):
    t = {"title": "", "rows": [], "team_row": None, "totals": None}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            vals = {k: (row.get(k) or "").strip() for k in COLS if (row.get(k) or "").strip()}
            role = (row.get("Role") or "").strip().lower()
            if role == "team":
                t["team_row"] = vals
            elif role == "totals":
                t["totals"] = vals
            elif (row.get("Player") or "").strip():
                t["rows"].append({"num": (row.get("#") or "").strip(), "name": row["Player"].strip(),
                                  "role": role if role in ("starter", "reserve") else "reserve", **vals})
    return t


# ---------------------------------------------------------------------------
# Folders, files, games
# ---------------------------------------------------------------------------
def folder_date(name: str, season: str):
    s = re.sub(r"\s*DONE$", "", name.strip(), flags=re.I)
    y0 = int(season[:4])
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s) or re.fullmatch(r"(\d{1,2})[-_/]?(\d{2})", s)
    if not m:
        return None
    if len(m.groups()) == 3:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    mo, d = int(m.group(1)), int(m.group(2))
    return date(y0 if mo >= 7 else y0 + 1, mo, d)


def file_key(stem: str, season: str, fallback):
    """("Citrus", date) from "Citrus 1031" / "Citrus 1031 2" / "Citrus 1031 (2)"; the folder's date if none."""
    m = re.match(r"^(.*?)\s+(\d{3,4})(?:\s*\(?\d\)?)?$", stem.strip())
    if not m:
        return re.sub(r"\s*\(?\d\)?$", "", stem).strip(), fallback
    mmdd = m.group(2).zfill(4)
    return m.group(1).strip(), folder_date(mmdd, season) or fallback


# Short names people use in file names -> the schedule's team names
SHORT = {"mt sac": "Mt. San Antonio", "msjc": "Mt. San Jacinto", "sac city": "Sacramento City", "scc": "Santiago Canyon",
         "la city": "Los Angeles City", "lacc": "Los Angeles City", "east la": "East Los Angeles", "elac": "East Los Angeles",
         "sbcc": "Santa Barbara", "sbvc": "San Bernardino Valley", "sd city": "San Diego City", "sdcc": "San Diego City",
         "mesa": "San Diego Mesa", "miramar": "San Diego Miramar", "pierce": "LA Pierce", "trade tech": "LA Trade Tech",
         "lattc": "LA Trade Tech", "harbor": "LA Harbor", "lasc": "LA Southwest", "coc": "Canyons", "cos": "Sequoias",
         "av": "Antelope Valley", "avc": "Antelope Valley", "ivc": "Irvine Valley", "occ": "Orange Coast",
         "rcc": "Riverside", "pcc": "Pasadena City", "pasadena": "Pasadena City", "lbcc": "Long Beach", "ccsf": "San Francisco",
         "city college of san francisco": "San Francisco", "dvc": "Diablo Valley", "sjcc": "San Jose", "delta": "San Joaquin Delta",
         "sjdc": "San Joaquin Delta", "arc": "American River", "crc": "Cosumnes River", "flc": "Folsom Lake",
         "mpc": "Monterey Peninsula", "monterey": "Monterey Peninsula", "fcc": "Fresno", "fresno city": "Fresno",
         "wlac": "West LA", "west los angeles": "West LA", "smc": "Santa Monica", "gcc": "Glendale", "ecc": "El Camino",
         "mjc": "Modesto", "lamc": "LA Valley", "lavc": "LA Valley", "hancock": "Allan Hancock", "ahc": "Allan Hancock",
         "deanza": "De Anza", "mira costa": "MiraCosta", "cuyamaca": "Cuyamaca", "swc": "Southwestern"}


def _norm(x):
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\b(college|of the|of)\b", " ", x.lower())).split()


def resolve_team(state, label, d):
    """The schedule's team name for a file's label: exact, a short name (Mt SAC, SBCC...), or the one team playing
    that night whose name contains it ("Barbara")."""
    import scrape
    t = scrape.canon_name(state, label)
    if t in state.teams:
        return t
    low = " ".join(_norm(label))
    if low in SHORT:
        return SHORT[low]
    playing = {n for g in state.games.values() if g["date"] == d.isoformat() for n in g["names"]} if d else set()
    for pool in (playing, set(state.teams)):
        hit = [n for n in pool if " ".join(_norm(n)) == low] or \
              [n for n in pool if low and (low in " ".join(_norm(n)) or " ".join(_norm(n)) in low)]
        if len(hit) == 1:
            return hit[0]
    return t


def to_box_rows(t):
    out = []
    for r in t["rows"]:
        name = f'#{r["num"]} {r["name"]}' if r["num"] else r["name"]
        out.append({"name": name, "stats": {k: r.get(k, "0") for k in COLS},
                    "role": r["role"], "is_starter": r["role"] == "starter"})
    return out


def run(state=None, only=None, verbose=True):
    """Read every night folder with something new (or only=date). Returns the keys of the games saved."""
    import scrape
    state = state or scrape.State(scrape.DEFAULT_SEASON)
    base = root(state.season)
    if not base.exists():
        return []
    reader, saved = Reader(), []
    try:
        for folder in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: folder_date(p.name, state.season) or date.min):
            fdate = folder_date(folder.name, state.season)
            if fdate is None or (only and fdate != only):
                continue
            images = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGES)
            if not images:
                continue
            if all(p.with_suffix(".csv").exists() for p in images) and (folder / "CHECK.txt").exists() \
                    and (folder / "CHECK.txt").stat().st_mtime >= max(p.stat().st_mtime for p in folder.iterdir()) - 1:
                continue   # nothing new in this folder since its last read
            if verbose:
                print(f"\nScreenshots: {folder.name} ({len(images)} images)")
            sides, notes = {}, []   # (team, date) -> merged side
            for img in images:
                label, d = file_key(img.stem, state.season, fdate)
                team = resolve_team(state, label, d)
                csv_path = img.with_suffix(".csv")
                try:
                    if csv_path.exists():
                        t = read_csv(csv_path)
                    else:
                        t = parse_words(reader.words(img))
                        write_csv(csv_path, t)
                except Exception as err:
                    notes.append(f"{img.name}: couldn't read it ({err})")
                    continue
                s = sides.setdefault((team, d), {"rows": [], "team_row": None, "totals": None, "files": []})
                s["rows"] += [r for r in t["rows"] if (r["num"], r["name"]) not in {(x["num"], x["name"]) for x in s["rows"]}]
                s["team_row"] = s["team_row"] or t["team_row"]
                s["totals"] = s["totals"] or t["totals"]
                s["files"].append(img.name)
            ok = {}
            for (team, d), s in sides.items():
                probs = check(s)
                if probs:
                    notes.append(f"{team} ({', '.join(s['files'])}) — fix in the CSV beside the image, then rerun:\n    "
                                 + "\n    ".join(probs))
                else:
                    ok[(team, d)] = s
            pending = 0
            for g in [g for g in state.games.values()]:
                d = date.fromisoformat(g["date"])
                here = [t for t in g["names"] if (t, d) in ok]
                if not here:
                    continue
                members = [t for t in scrape.members_in(g) if t in state.teams]
                need = [t for t in g["names"] if t in members]
                if any((t, d) not in ok for t in need):
                    missing = [t for t in need if (t, d) not in ok]
                    if not any((t, d) in sides for t in missing):
                        pending += 1
                        notes.append(f"{' vs '.join(g['names'])} {g['date_label']}: waiting for {', '.join(missing)}'s screenshot")
                    continue
                if scrape.box_from_disk(state, g) is not None:
                    continue   # already saved (an earlier run or the site)
                home = next((t for t in g["names"] if g["sides"].get(t, {}).get("home_away") == "home"), None)
                a, b = g["names"]
                visitor, home = (b, a) if home == a else (a, b)
                bs = {"visitor": visitor, "home": home, "date": f"{d.month}/{d.day}/{d.year}", "source": "screenshots",
                      "score": {t: _i((ok[(t, d)]["totals"] or {}).get("PTS")) for t in (visitor, home) if (t, d) in ok},
                      "teams": {t: to_box_rows(ok[(t, d)]) for t in (visitor, home) if (t, d) in ok}}
                scrape.classify_box(bs, g)
                scrape.save_box(state, g, bs)
                saved.append(g["key"])
                if verbose:
                    print(f"  saved {visitor} at {home} {g['date']} ({', '.join(f'{t} {bs['score'].get(t)}' for t in bs['score'])})")
            unmatched = [f"{t} {d:%m/%d}" for (t, d) in ok
                         if not any(g["date"] == d.isoformat() and t in g["names"] for g in state.games.values())]
            if unmatched:
                notes.append("no game on the schedule for: " + ", ".join(unmatched) + " (check the team name / date in the file name)")
            # the folder stays as it is (screenshots keep coming in through the night); CHECK.txt says where it stands
            done = sorted({" vs ".join(g["names"]) for g in state.games.values()
                           if g["date"] in {d.isoformat() for (_, d) in sides} and scrape.box_from_disk(state, g) is not None
                           and any((t, date.fromisoformat(g["date"])) in sides for t in g["names"])})
            report = (f"Saved ({len(done)}): " + ", ".join(done) if done else "Saved: none yet") + "\n\n" + \
                     ("\n\n".join(notes) if notes else "Nothing to fix.") + "\n"
            (folder / "CHECK.txt").write_text(report, encoding="utf-8")
            if verbose and notes:
                print("  " + "\n  ".join(n.splitlines()[0] for n in notes) + f"\n  -> {folder / 'CHECK.txt'}")
    finally:
        reader.close()
    return saved


def main():
    import scrape
    ap = argparse.ArgumentParser(description="Box scores from screenshots (see the top of this file).")
    ap.add_argument("--date", help="one night: 1031, 10-31 or 2026-10-31")
    ap.add_argument("--season", default=scrape.DEFAULT_SEASON)
    args = ap.parse_args()
    state = scrape.State(args.season)
    only = folder_date(args.date, args.season) if args.date else None
    n = len(run(state, only))
    state.save()
    print(f"\n{n} game(s) saved from screenshots. `python scrape.py nightly --browser` counts them as done.")


if __name__ == "__main__":
    main()
