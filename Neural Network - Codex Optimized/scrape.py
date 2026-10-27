"""
Low-traffic CCCMBCA scraper: master schedule + nightly box scores + missing-stats ledger.

Each night it reads ONE page, the league composite (daily scoreboard), to find
every box score posted for that day, then fetches each box score once (both teams'
folders get a copy). Nightly touches only that night's games. Team schedule pages
are only read to build / refresh the master schedule (`master`, `master --resync`).
Games whose box score is missing, or has only one team's stats, are re-checked only
when asked (`missing`), never automatically.

State lives in scrape_state/<season>/ (outside the schedules folder so the stats
scripts never mistake it for a conference):
    master_schedule.json   every game once, both teams, from the team pages
    ledger.json            per-game scrape status, URL, check history
    missing_boxscores.md   human-readable list of games still missing stats

Usage (see "Terminal Commands README.md" for the full list):
    python3 scrape.py master                     build the master schedule (one-time, ~100 requests)
    python3 scrape.py master --resync            refresh it (resumable)
    python3 scrape.py nightly                    the scheduled nightly job: that night's games only
    python3 scrape.py missing                    re-check older games still missing stats (on demand, never automatic)
    python3 scrape.py day 2026-11-14 [--to 2026-11-16]
    python3 scrape.py game 20261114_ab12 | <box score URL> | --team Moorpark --date 2026-11-14
    python3 scrape.py team Moorpark Ventura [--date 2026-11-14]
    python3 scrape.py conference "WSC North" [--date 2026-11-14]
    python3 scrape.py missing [--team ...] [--conference ...] [--include-stale]
    python3 scrape.py status [--team ...] [--conference ...] [--date ...]

Flags for every command: --dry-run --force --max-requests N --no-rebuild --season S
"""

import argparse
import json
import os
import random
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)  # all pipeline scripts run from the project root

from ccc_config import CONFERENCES, DEFAULT_SEASON, get_conference, schedule_dir, season_base_url  # noqa: E402
from generate_team_stats import TEAM_ALIASES  # noqa: E402
from scrape_team import ScheduleParser, parse_boxscore  # noqa: E402

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
SITE = "https://cccmbca.org"
# The daily scoreboard. Box score links are pulled from it by URL pattern, so the
# page layout doesn't matter; if the date parameter is ever not honoured the
# links' dates won't match and the run falls back to team schedule pages.
COMPOSITE_URL = "https://cccmbca.prestosports.com/composite?d={d:%Y-%m-%d}"
BOX_LINK_RE = re.compile(r"(/sports/mbkb/\d{4}-\d{2}/boxscores/(\d{8})_[A-Za-z0-9]+\.xml)")
DELAY_RANGE = (5.0, 8.0)      # seconds between requests, randomised
THROTTLE_WAIT = 90            # seconds to wait after the first rate-limit response
DEFAULT_MAX_REQUESTS = 150

MEMBERS = {t for teams in CONFERENCES.values() for t in teams}

# Ledger statuses
SCHEDULED = "SCHEDULED"      # not played yet / not processed yet
NO_BOX = "NO_BOX"            # played, but no box score link or no stats on it
PARTIAL = "PARTIAL"          # one team's stats missing
COMPLETE = "COMPLETE"        # both teams' stats present
FORFEIT = "FORFEIT"          # forfeit, no stats expected
POSTPONED = "POSTPONED"      # postponed / cancelled
NOT_TRACKED = "NOT_TRACKED"  # TBA opponent or exhibition with no result
STALE = "STALE"              # older ledgers only (games given up on); `missing --include-stale` re-checks them
DONE = {COMPLETE, FORFEIT, NOT_TRACKED}
MISSING = {NO_BOX, PARTIAL}


class Throttled(Exception):
    pass


class BudgetExhausted(Exception):
    pass


# ---------------------------------------------------------------------------
# Polite fetching
# ---------------------------------------------------------------------------
class Fetcher:
    """One request at a time, 5-8s apart, hard request cap, stops on repeated throttling."""

    def __init__(self, max_requests: int):
        self.max_requests = max_requests
        self.count = 0
        self.throttle_hits = 0
        self._last = 0.0
        # Mirrors scrape_team.fetch: some local Pythons lack a CA bundle.
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def _wait(self):
        if self._last:
            gap = random.uniform(*DELAY_RANGE) - (time.time() - self._last)
            if gap > 0:
                time.sleep(gap)

    def _throttled(self, why: str):
        self.throttle_hits += 1
        if self.throttle_hits >= 2:
            raise Throttled(why)
        print(f"    Rate limited ({why}), waiting {THROTTLE_WAIT}s...")
        time.sleep(THROTTLE_WAIT)

    def get(self, url: str) -> str:
        if not url.startswith("http"):
            url = SITE + url
        while True:
            if self.count >= self.max_requests:
                raise BudgetExhausted(f"{self.max_requests} requests")
            self._wait()
            self.count += 1
            self._last = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=30, context=self._ctx) as resp:
                    data = resp.read().decode("utf-8", errors="replace")
                    if resp.status == 202 and not data:
                        self._throttled("202")
                        continue
                    return data
            except urllib.error.HTTPError as e:
                if e.code in (429, 459, 503):
                    self._throttled(str(e.code))
                    continue
                raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", text).lower().strip("_")


def label_to_date(season: str, label: str):
    """'Nov 14' -> date in the right year for the season (Jul-Dec fall, Jan-Jun spring)."""
    fall = int(season.split("-")[0])
    try:
        dt = datetime.strptime(f"{label.strip()} {fall}", "%b %d %Y")
    except ValueError:
        return None
    if dt.month <= 6:
        dt = dt.replace(year=fall + 1)
    return dt.date()


def parse_iso(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def game_row(g: dict) -> dict:
    """Schedule-row dict in the same shape scrape_team.py writes to schedule.json."""
    row = {
        "date": g.get("date", ""),
        "opponent": g.get("opponent", ""),
        "home_away": g.get("home_away", ""),
        "location_tag": g.get("location_tag", ""),
        "result": g.get("result", ""),
        "status": g.get("status", ""),
        "notes": g.get("notes", ""),
        "is_conference": g.get("is_conference", False),
        "boxscore_url": g.get("boxscore_url", ""),
        "video_url": g.get("video_url", ""),
    }
    set_score_fields(row)
    return row


def set_score_fields(row: dict):
    for k in ("win_loss", "team_score", "opponent_score"):
        row.pop(k, None)
    m = re.match(r"([WL]),?\s*(\d+)-(\d+)", row.get("result", ""))
    if m:
        row["win_loss"] = m.group(1)
        row["team_score"] = int(m.group(2))
        row["opponent_score"] = int(m.group(3))


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class State:
    def __init__(self, season: str):
        self.season = season
        self.dir = Path("scrape_state") / season
        self.master_path = self.dir / "master_schedule.json"
        self.ledger_path = self.dir / "ledger.json"
        self.missing_path = self.dir / "missing_boxscores.md"
        self.master = self._load(self.master_path, {"season": season, "teams": {}, "games": {}})
        self.ledger = self._load(self.ledger_path, {})

    @staticmethod
    def _load(path, default):
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return default

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.master["updated"] = now_iso()
        for path, data in ((self.master_path, self.master), (self.ledger_path, self.ledger)):
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=1, sort_keys=True)
            tmp.replace(path)
        write_missing_report(self)

    @property
    def teams(self) -> dict:
        return self.master["teams"]

    @property
    def games(self) -> dict:
        return self.master["games"]

    def entry(self, key: str) -> dict:
        e = self.ledger.get(key)
        if e is None:
            e = self.ledger[key] = {"status": SCHEDULED, "first_seen": now_iso(), "checks": 0}
        return e


def team_url(state: State, team: str) -> str:
    return f"{season_base_url(state.season)}/schedule?teamId={state.teams[team]['id']}"


def game_date(g: dict) -> date:
    return parse_iso(g["date"])


def members_in(g: dict) -> list:
    """Member teams in a game (whether or not their own page has been read yet)."""
    return [n for n in g["names"] if n in MEMBERS]


def name_strength(label: str, name: str) -> int:
    """How well a box-score team label matches a schedule name.
    3 exact or known alias ('MESA-M'), 2 safe variant ('Pasadena' / 'Pasadena City',
    'Palo Verde College', 'College of the Sequoias'), 1 loose substring ('MIRAMAR'),
    0 no match. 'Southwestern Oregon' is NOT a variant of 'Southwestern'."""
    if not label or not name:
        return 0
    if TEAM_ALIASES.get(label) == name:
        return 3
    a, b = slug(label), slug(name)
    if a == b:
        return 3
    if b.startswith(a + "_") or a in (b + "_college", b + "_cc", b + "_community_college") \
            or a == "college_of_the_" + b or a == "college_of_" + b:
        return 2
    if a in b or b in a:
        return 1
    return 0


def assign(labels: list, names: list):
    """Best one-to-one pairing of a box score's two labels with a game's two names.
    Returns (total strength, {label: name})."""
    labels = [x for x in labels if x]
    if len(labels) != 2 or len(names) != 2:
        return 0, {}
    (l0, l1), (n0, n1) = labels, names
    straight = name_strength(l0, n0) + name_strength(l1, n1)
    crossed = name_strength(l0, n1) + name_strength(l1, n0)
    if straight >= crossed:
        return straight, {l0: n0, l1: n1}
    return crossed, {l0: n1, l1: n0}


def canon_name(state: State, label: str) -> str:
    """Box-score label -> site team name, only when the match is safe."""
    best = max(state.teams, key=lambda t: (name_strength(label, t), -len(t)), default=None)
    return best if best and name_strength(label, best) >= 2 else label


# ---------------------------------------------------------------------------
# Master schedule
# ---------------------------------------------------------------------------
def ensure_team_index(state: State, fetcher: Fetcher):
    """Team name -> id, from the dropdown on the league schedule page (1 request)."""
    if state.teams:
        return
    print("Fetching league schedule page for the team list...")
    parser = ScheduleParser()
    parser.feed(fetcher.get(f"{season_base_url(state.season)}/schedule"))
    if not parser.teams:
        sys.exit("Could not read the team list from the league schedule page.")
    for name, tid in parser.teams.items():
        name = name.strip()
        state.teams[name] = {"id": tid, "conference": get_conference(name), "synced": None}
    print(f"  {len(state.teams)} teams")


def sync_team(state: State, fetcher: Fetcher, team: str) -> list:
    """Fetch one team's schedule page, merge it into the master schedule, and
    rewrite that team's schedule.json. Returns the keys of the games on the page."""
    url = team_url(state, team)
    print(f"Schedule page: {team}")
    parser = ScheduleParser()
    parser.feed(fetcher.get(url))

    seen = {}
    keys = []
    rows = []
    for raw in parser.games:
        row = game_row(raw)
        rows.append(row)
        d = label_to_date(state.season, row["date"])
        if d is None:
            continue
        opp = row["opponent"].strip() or "TBA"
        pair = "|".join(sorted([slug(team), slug(opp)]))
        n = seen[(d, pair)] = seen.get((d, pair), 0) + 1
        key = f"{d:%Y%m%d}|{pair}|{n}"
        keys.append(key)

        g = state.games.setdefault(key, {"key": key, "date": d.isoformat(), "date_label": row["date"],
                                         "names": [team, opp], "sides": {}})
        g["sides"][team] = {k: row[k] for k in ("opponent", "home_away", "location_tag", "result",
                                                 "status", "notes", "is_conference")}
        if row["boxscore_url"]:
            g["boxscore_url"] = row["boxscore_url"]
        state.entry(key)

    # Games this team no longer lists (moved / cancelled): drop its side.
    for key, g in list(state.games.items()):
        if team in g["sides"] and key not in keys:
            del g["sides"][team]
            if not g["sides"]:
                del state.games[key]
                if state.ledger.get(key, {}).get("status") not in DONE:
                    state.ledger.pop(key, None)

    state.teams[team]["synced"] = now_iso()
    write_schedule_json(state, team, url, parser, rows)
    return keys


def team_dir(state: State, team: str) -> Path:
    conf = state.teams.get(team, {}).get("conference") or get_conference(team)
    return schedule_dir(state.season) / conf / team


def write_schedule_json(state: State, team: str, url: str, parser: ScheduleParser, rows: list):
    """Same layout scrape_team.save_team writes, so the stats scripts are unaffected."""
    d = team_dir(state, team)
    d.mkdir(parents=True, exist_ok=True)
    for row in rows:
        row["has_boxscore"] = bool(row["boxscore_url"]) and box_folder(state, team, row["date"], row["opponent"]).exists()
    data = {
        "team_name": team,
        "team_id": state.teams[team]["id"],
        "url": url,
        "last_updated": now_iso(),
        "records": parser.records,
        "all_teams": parser.teams,
        "games": rows,
    }
    with open(d / "schedule.json", "w") as f:
        json.dump(data, f, indent=2)


def box_folder(state: State, team: str, date_label: str, opponent: str) -> Path:
    d = label_to_date(state.season, date_label)
    name = f"{d:%Y%m%d}_{slug(opponent)}" if d else "unknown"
    return team_dir(state, team) / name


def box_path(state: State, team: str, g: dict) -> Path:
    opp = next((n for n in g["names"] if n != team), g["names"][-1])
    if team in g["sides"]:
        opp = g["sides"][team]["opponent"] or opp
    folder = box_folder(state, team, g["date_label"], opp)
    return folder / f"{folder.name}.json"


def patch_schedules(state: State, g: dict, bs: dict, have_box: bool):
    """Write a game's result and box link into each member team's schedule.json
    without fetching its schedule page (the nightly resync refreshes them fully)."""
    _, pairing = assign([bs.get("visitor"), bs.get("home")], g["names"])
    canon = {name: label for label, name in pairing.items()}
    score = bs.get("score", {})
    for team in members_in(g):
        path = team_dir(state, team) / "schedule.json"
        if not path.exists():
            continue
        opp = next((n for n in g["names"] if n != team), "")
        if team in g["sides"]:
            opp = g["sides"][team]["opponent"] or opp
        with open(path) as f:
            data = json.load(f)
        for row in data.get("games", []):
            if row.get("date") != g["date_label"] or row.get("opponent") != opp:
                continue
            mine, theirs = score.get(canon.get(team, "")), score.get(canon.get(opp, ""))
            if mine is not None and theirs is not None and not row.get("result"):
                # the site lists the winner's score first: "L, 73-67"
                row["result"] = f"{'W' if mine > theirs else 'L'}, {max(mine, theirs)}-{min(mine, theirs)}"
            status = row.get("status", "")
            if not status.startswith("Final"):
                flags = re.search(r"[*~#%].*", status)
                row["status"] = "Final" + (" " + flags.group(0) if flags else "")
            row["boxscore_url"] = g.get("boxscore_url", "")
            row["has_boxscore"] = have_box
            set_score_fields(row)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            break


# ---------------------------------------------------------------------------
# Box scores
# ---------------------------------------------------------------------------
def classify_box(bs: dict, g: dict):
    """(status, reason, note) for a parsed box score."""
    teams = bs.get("teams", {})
    score = bs.get("score", {})
    present, missing, notes = [], [], []
    for name in (bs.get("visitor"), bs.get("home")):
        players = teams.get(name) or []
        pts = 0
        for p in players:
            try:
                pts += int(p["stats"].get("PTS") or 0)
            except (ValueError, TypeError):
                pass
        if not players or (pts == 0 and (score.get(name) or 0) > 0):
            missing.append(name)
        else:
            present.append(name)
            if score.get(name) is not None and pts != score[name]:
                notes.append(f"{name} player points {pts} vs score {score[name]}")
    note = "; ".join(notes)
    if not present:
        return NO_BOX, "box score page has no stats yet", note
    if not missing:
        return COMPLETE, "", note
    # A non-member opponent's missing stats are unlikely ever to be posted.
    if all(not is_member_label(m, bs, g) for m in missing):
        return COMPLETE, "", "; ".join(filter(None, [note, f"non-member side missing: {', '.join(missing)}"]))
    return PARTIAL, f"only {', '.join(present)} posted stats; missing {', '.join(missing)}", note


def is_member_label(box_name: str, bs: dict, g: dict) -> bool:
    """Is this box-score team one of the game's member teams?"""
    _, pairing = assign([bs.get("visitor"), bs.get("home")], g["names"])
    return pairing.get(box_name, box_name) in MEMBERS or box_name not in pairing


def box_from_disk(state: State, g: dict):
    """A box score already saved by an earlier run or scrape_team.py, if any."""
    for team in members_in(g):
        p = box_path(state, team, g)
        if p.exists():
            try:
                with open(p) as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
    return None


def save_box(state: State, g: dict, bs: dict) -> list:
    saved = []
    for team in members_in(g):
        if team not in state.teams:
            continue
        p = box_path(state, team, g)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(bs, f, indent=2)
        saved.append(team)
    return saved


def offline_status(g: dict):
    """Status for a past game with no box score link, from its schedule rows."""
    sides = list(g["sides"].values())
    text = " ".join(f"{s['status']} {s['result']} {s['notes']}" for s in sides).lower()
    result = any(s["result"] for s in sides)
    final = any(s["status"].lower().startswith("final") for s in sides)
    if "forfeit" in text:
        return FORFEIT, "forfeit"
    if re.search(r"postpon|cancel|\bppd\b", text):
        return POSTPONED, "postponed or cancelled"
    if not result and (any(n.upper() in ("TBA", "TBD") for n in g["names"])
                       or "do not count" in text):
        return NOT_TRACKED, "TBA opponent / exhibition with no result"
    if result or final:
        return NO_BOX, "result posted but no box score link"
    return NO_BOX, "no result or box score posted"


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------
class Run:
    def __init__(self, state: State, fetcher: Fetcher, args):
        self.state = state
        self.fetcher = fetcher
        self.force = args.force
        self.dry = args.dry_run
        self.touched = set()     # teams whose box scores changed -> rebuild stats
        self.synced = set()      # team pages fetched this run
        self.box_cache = {}      # box url -> parsed box (fetched while matching composite links)
        self.composites = {}     # date -> list of box urls, or None if unusable
        self.processed = set()   # game keys already handled this run
        self.log = []

    def composite(self, d: date):
        """Box score links posted for one day, from the composite page (1 request).
        None when the page can't be trusted for that date (fall back to team pages)."""
        if d in self.composites:
            return self.composites[d]
        url = COMPOSITE_URL.format(d=d)
        if self.dry:
            print(f"  would fetch composite: {url}")
            self.composites[d] = []
            return []
        print(f"Composite: {d}")
        html = self.fetcher.get(url)
        links = sorted({m.group(1) for m in BOX_LINK_RE.finditer(html)
                        if f"/{self.state.season}/" in m.group(1)})
        # Box IDs start with the game date (a few are a day early), so a page
        # mostly made of other dates means the date parameter wasn't honoured.
        dated = [u for u in links if BOX_LINK_RE.search(u).group(2) == f"{d:%Y%m%d}"]
        if links and len(dated) * 2 < len(links):
            print(f"    composite didn't show {d} (links are for other dates) — using team pages")
            self.composites[d] = None
        else:
            self.composites[d] = links
        return self.composites[d]

    def attach_links(self, d: date, links: list):
        """Match each new box score link to its game in the master schedule."""
        known = {g.get("boxscore_url") for g in self.state.games.values()}
        added = []
        for url in links:
            if url in known:
                continue
            print(f"  Box score: {url}")
            try:
                bs = parse_boxscore(self.fetcher.get(url))
            except urllib.error.HTTPError as e:
                print(f"    {e.code} — skipped")
                continue
            self.box_cache[url] = bs
            g = match_game(self.state, d, bs)
            if g is None:
                if BOX_LINK_RE.search(url).group(2) != f"{d:%Y%m%d}":
                    print(f"    no {d} game matches {bs.get('visitor')} vs {bs.get('home')} — skipped")
                    continue
                g = new_game(self.state, d, bs)
                print(f"    not in master schedule — added {' vs '.join(g['names'])}")
            g["boxscore_url"] = url
            added.append(g["key"])
            self.process_game(g["key"])   # save now, so a stop mid-run loses nothing
        return added

    def sync(self, team: str):
        if team in self.synced:
            return
        if self.dry:
            print(f"  would fetch schedule page: {team}")
            self.synced.add(team)
            return
        sync_team(self.state, self.fetcher, team)
        self.synced.add(team)

    def pages_for(self, keys: list) -> list:
        """Fewest team pages that cover the games still needing a box score link."""
        need = {}
        for k in keys:
            g = self.state.games.get(k)
            if not g or (g.get("boxscore_url") and not self.force):
                continue
            cands = [t for t in members_in(g) if t in self.state.teams]
            if cands and not any(t in self.synced for t in cands):
                need[k] = set(cands)
        pages = []
        while need:
            counts = {}
            for cands in need.values():
                for t in cands:
                    counts[t] = counts.get(t, 0) + 1
            best = max(sorted(counts), key=lambda t: counts[t])
            pages.append(best)
            need = {k: c for k, c in need.items() if best not in c}
        return pages

    def process(self, keys: list, discover: bool = True):
        """Bring each game up to date: find its box link (fewest team pages), then
        fetch the box once and save it for both teams."""
        today = date.today()
        keys = [k for k in keys if k in self.state.games and game_date(self.state.games[k]) <= today]
        if not self.force:
            keys = [k for k in keys if self.state.entry(k)["status"] not in DONE]
        if discover:
            fallback = []
            for d in sorted({game_date(self.state.games[k]) for k in keys}):
                day = [k for k in keys if self.state.games[k]["date"] == d.isoformat()]
                if not any(not self.state.games[k].get("boxscore_url") for k in day):
                    continue   # every game that day already has its link
                links = self.composite(d)
                if links is None:
                    fallback += day
                elif not self.dry:
                    keys += [k for k in self.attach_links(d, links) if k not in keys]
            for team in self.pages_for(fallback):
                self.sync(team)
        for k in keys:
            if k in self.state.games:
                self.process_game(k)

    def process_game(self, key: str):
        if key in self.processed:
            return
        self.processed.add(key)
        g = self.state.games[key]
        e = self.state.entry(key)
        url = g.get("boxscore_url", "")
        label = f"{g['date']} {' vs '.join(g['names'])}"
        if not url:
            status, reason = offline_status(g)
            if self.dry:
                print(f"  {label}: no box score link known ({reason})")
                return
            self.record(e, g, status, reason, "")
            return

        bs = None if self.force else box_from_disk(self.state, g)
        if bs is not None and classify_box(bs, g)[0] == COMPLETE:
            if not self.dry:
                status, reason, note = classify_box(bs, g)
                saved = [t for t in members_in(g) if t in self.state.teams and not box_path(self.state, t, g).exists()]
                if saved:   # copy to a team folder that doesn't have it yet
                    save_box(self.state, g, bs)
                    self.touched.update(saved)
                self.record(e, g, status, reason, note, checked=False)
            return
        if self.dry:
            print(f"  would fetch box score: {label}  {url}")
            return
        bs = self.box_cache.pop(url, None)
        if bs is None:
            print(f"  Box score: {label}")
            try:
                bs = parse_boxscore(self.fetcher.get(url))
            except urllib.error.HTTPError as err:
                self.record(e, g, NO_BOX, f"box score link returned {err.code}", "")
                return
        status, reason, note = classify_box(bs, g)
        if status != NO_BOX:
            self.touched.update(save_box(self.state, g, bs))
        self.record(e, g, status, reason, note)
        patch_schedules(self.state, g, bs, status != NO_BOX)

    def record(self, e, g, status, reason, note, checked=True):
        old = e["status"]
        e["status"] = status
        e["reason"] = reason
        e["note"] = note
        e["boxscore_url"] = SITE + g["boxscore_url"] if g.get("boxscore_url") else ""
        e["source_url"] = [team_url(self.state, t) for t in members_in(g) if t in self.state.teams]
        if checked:
            e["checks"] = e.get("checks", 0) + 1
            e["last_checked"] = now_iso()
        if status == COMPLETE and old in MISSING | {STALE}:
            e["resolved"] = now_iso()
        if old != status:
            self.log.append(f"{g['date']} {' vs '.join(g['names'])}: {old} -> {status}")


def match_game(state: State, d: date, bs: dict):
    """The master-schedule game on date d between the box score's two teams:
    best match on BOTH names, preferring a game still without a link (the second
    game of a doubleheader)."""
    labels = [bs.get("visitor"), bs.get("home")]
    best, best_score = None, (2, 0)   # need more than one loose match
    for k in sorted(state.games):
        g = state.games[k]
        if g["date"] != d.isoformat():
            continue
        total, _ = assign(labels, g["names"])
        score = (total, 0 if g.get("boxscore_url") else 1)
        if score > best_score:
            best, best_score = g, score
    return best


def new_game(state: State, d: date, bs: dict) -> dict:
    names = [canon_name(state, n) for n in (bs.get("visitor"), bs.get("home"))]
    pair = "|".join(sorted(slug(n) for n in names))
    n = 1
    while f"{d:%Y%m%d}|{pair}|{n}" in state.games:
        n += 1
    key = f"{d:%Y%m%d}|{pair}|{n}"
    g = state.games[key] = {"key": key, "date": d.isoformat(), "date_label": f"{d:%b} {d.day:02d}",
                            "names": names, "sides": {}}
    state.entry(key)
    return g


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def resolve_teams(state: State, names: list) -> list:
    pool = sorted(state.teams) or sorted(MEMBERS)
    out = []
    for q in names:
        exact = [t for t in pool if t.lower() == q.lower()]
        hits = exact or [t for t in pool if q.lower() in t.lower()]
        if not hits:
            sys.exit(f"No team matches '{q}'. Try: python3 scrape.py status")
        if len(hits) > 1:
            sys.exit(f"'{q}' matches several teams: {', '.join(hits)} — be more specific.")
        out.append(hits[0])
    return out


def resolve_conferences(names: list) -> list:
    teams = []
    for q in names:
        hits = [c for c in CONFERENCES if c.lower() == q.lower()] or \
               [c for c in CONFERENCES if q.lower() in c.lower()]
        if len(hits) != 1:
            sys.exit(f"Conference '{q}' not found. Options: {', '.join(CONFERENCES)}")
        teams += CONFERENCES[hits[0]]
    return teams


def date_range(args):
    if not getattr(args, "date", None):
        return None, None
    start = parse_iso(args.date)
    end = parse_iso(args.to) if getattr(args, "to", None) else start
    return start, end


def select_games(state: State, teams=None, start=None, end=None) -> list:
    out = []
    for k, g in state.games.items():
        if teams is not None and not set(g["names"]) & set(teams):
            continue
        d = game_date(g)
        if start and d < start or end and d > end:
            continue
        out.append(k)
    return sorted(out)


def require_master(state: State):
    if not state.games:
        sys.exit("No master schedule yet. Run:  python3 scrape.py master")


def default_night() -> date:
    """The 'end of day' being scraped: today after 6 PM, otherwise yesterday."""
    now = datetime.now()
    return now.date() if now.hour >= 18 else now.date() - timedelta(days=1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_master(run: Run, args):
    state = run.state
    ensure_team_index(state, run.fetcher)
    teams = sorted(state.teams)
    if args.team or args.conference:
        teams = sorted(set(resolve_teams(state, args.team or [])) | set(resolve_conferences(args.conference or [])))
    if args.resync:
        cutoff = datetime.now() - timedelta(hours=24)   # rerun after a stop resumes where it left off
        teams = [t for t in teams if not state.teams[t]["synced"]
                 or datetime.fromisoformat(state.teams[t]["synced"]) < cutoff]
    else:
        teams = [t for t in teams if not state.teams[t]["synced"]]
    print(f"{len(teams)} team schedule pages to fetch (~{len(teams) * 6.5 / 60:.0f} min)")
    for t in teams:
        run.sync(t)
    # Games already on disk from scrape_team.py count as complete without a request.
    if not run.dry:
        for k, g in state.games.items():
            e = state.entry(k)
            if e["status"] == SCHEDULED and g.get("boxscore_url"):
                bs = box_from_disk(state, g)
                if bs is not None:
                    status, reason, note = classify_box(bs, g)
                    run.record(e, g, status, reason, note, checked=False)


def cmd_nightly(run: Run, args):
    state = run.state
    require_master(state)
    night = parse_iso(args.date) if args.date else default_night()
    print(f"Nightly scrape for {night}")
    # Only that night's games: no automatic re-checks of older missing box scores and no team-page refreshes.
    # Older games missing stats are re-checked on demand with `scrape.py missing` (see `scrape.py status`).
    tonight = [k for k in select_games(state, start=night, end=night)]
    print(f"  {len(tonight)} games on {night} (older missing box scores: `scrape.py missing`)")
    run.process(sorted(tonight))


def cmd_day(run: Run, args):
    require_master(run.state)
    start, end = date_range(args)
    keys = select_games(run.state, start=start, end=end)
    print(f"{len(keys)} games {start}" + (f" to {end}" if end != start else ""))
    run.process(keys)


def cmd_game(run: Run, args):
    state = run.state
    if args.id:
        gid = args.id.rstrip("/").split("/")[-1].replace(".xml", "")
        keys = [k for k, g in state.games.items() if gid in g.get("boxscore_url", "")]
        if not keys:
            return game_from_url(run, args.id, gid)
    else:
        if not (args.team and args.date):
            sys.exit("Give a game ID / box score URL, or --team and --date.")
        team = resolve_teams(state, args.team)[0]
        d = parse_iso(args.date)
        keys = select_games(state, teams=[team], start=d, end=d)
        if not keys:
            ensure_team_index(state, run.fetcher)
            run.sync(team)
            keys = select_games(state, teams=[team], start=d, end=d)
        if not keys:
            sys.exit(f"No {team} game on {d} in the schedule.")
    run.force = True if args.force else run.force
    run.process(keys)


def game_from_url(run: Run, raw: str, gid: str):
    """A box score not yet linked in the master schedule: fetch it, match it to
    its game (or add one), and save it."""
    state = run.state
    m = re.match(r"(\d{8})_", gid)
    if not m:
        sys.exit(f"Not a box score ID or URL: {raw}")
    url = f"/sports/mbkb/{state.season}/boxscores/{gid}.xml"
    try:
        d = datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        sys.exit(f"Not a box score ID or URL: {raw}")
    if run.dry:
        print(f"  would fetch box score {url}")
        return
    ensure_team_index(state, run.fetcher)
    try:
        bs = run.box_cache[url] = parse_boxscore(run.fetcher.get(url))
    except urllib.error.HTTPError as err:
        sys.exit(f"Box score {url} returned {err.code}.")
    g = match_game(state, d, bs) or new_game(state, d, bs)
    g["boxscore_url"] = url
    run.force = True
    run.process([g["key"]], discover=False)


def cmd_teams(run: Run, teams: list, args):
    state = run.state
    ensure_team_index(state, run.fetcher)
    teams = [t for t in teams if t in state.teams] or sys.exit("None of those teams are on the site's team list.")
    for t in teams:
        run.sync(t)
    start, end = date_range(args)
    run.process(select_games(state, teams=teams, start=start, end=end), discover=False)


def cmd_missing(run: Run, args):
    state = run.state
    require_master(state)
    teams = None
    if args.team or args.conference:
        teams = resolve_teams(state, args.team or []) + resolve_conferences(args.conference or [])
    want = MISSING | ({STALE, POSTPONED} if args.include_stale else set())
    start, end = date_range(args)
    keys = [k for k in select_games(state, teams=teams, start=start, end=end) if state.entry(k)["status"] in want]
    print(f"Re-checking {len(keys)} games missing stats")
    run.process(keys)


def cmd_status(state: State, args):
    require_master(state)
    teams = None
    if args.team or args.conference:
        teams = resolve_teams(state, args.team or []) + resolve_conferences(args.conference or [])
    start, end = date_range(args)
    keys = select_games(state, teams=teams, start=start, end=end)
    counts = {}
    for k in keys:
        s = state.entry(k)["status"]
        counts[s] = counts.get(s, 0) + 1
    synced = [i["synced"] for i in state.teams.values() if i["synced"]]
    print(f"Season {state.season}: {len(keys)} games, {len(synced)}/{len(state.teams)} team pages synced"
          + (f" (oldest {min(synced)[:10]})" if synced else ""))
    for s in (COMPLETE, PARTIAL, NO_BOX, STALE, POSTPONED, FORFEIT, NOT_TRACKED, SCHEDULED):
        if counts.get(s):
            print(f"  {s:<12}{counts[s]:>5}")
    rows = missing_rows(state, keys)
    if rows:
        print(f"\nMissing stats ({len(rows)}):")
        for r in rows:
            print(f"  {r['date']}  {r['game']:<40} {r['status']:<9} {r['reason']}")
            print(f"      {r['url']}  (checked {r['checks']}x, last {r['last']})")
    if teams:
        print("\nGames:")
        for k in keys:
            g, e = state.games[k], state.entry(k)
            print(f"  {g['date']}  {' vs '.join(g['names']):<40} {e['status']:<9} {e.get('note', '')}")


def missing_rows(state: State, keys: list) -> list:
    rows = []
    for k in keys:
        e = state.ledger.get(k, {})
        if e.get("status") not in MISSING | {STALE, POSTPONED}:
            continue
        g = state.games[k]
        rows.append({
            "date": g["date"], "game": " vs ".join(g["names"]), "status": e["status"],
            "reason": e.get("reason", ""),
            "url": e.get("boxscore_url") or ", ".join(e.get("source_url", [])),
            "checks": e.get("checks", 0), "last": (e.get("last_checked") or "never")[:16],
        })
    return rows


def write_missing_report(state: State):
    rows = missing_rows(state, sorted(state.games))
    lines = [f"# Missing box scores — {state.season}", "", f"Updated {now_iso()}", ""]
    if not rows:
        lines.append("Nothing missing.")
    else:
        lines += ["| Date | Game | Status | Why | URL | Checks | Last checked |",
                  "|---|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['date']} | {r['game']} | {r['status']} | {r['reason']} | {r['url']} "
                         f"| {r['checks']} | {r['last']} |")
    state.missing_path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def rebuild(season: str, teams: set):
    """After new box scores: those teams' stats and analytics, then the leaderboard (which also publishes the
    tracker's ratings.json and team files), then the tracker's scouting reports for the teams that played and are
    on Moorpark's schedule or in tracker_teams.txt (../poss/reports/, one current copy each). --no-rebuild skips it."""
    teams = sorted(t for t in teams)
    if not teams:
        return
    print(f"\nRebuilding stats for {len(teams)} teams: {', '.join(teams)}")
    for script in ("generate_team_stats.py", "update_advanced_analytics.py"):
        subprocess.run([sys.executable, script, "--season", season, "--teams", *teams], check=False)
    print("\nRebuilding the leaderboard (and the tracker's ratings / team files)")
    subprocess.run([sys.executable, "generate_leaderboard.py", "--cache"], check=False)
    print("\nUpdating scouting reports for the tracker")
    subprocess.run([sys.executable, "generate_opponent_report.py", "--season", season, "--latest", "--only", *teams], check=False)


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--season", default=DEFAULT_SEASON, help="Season, e.g. 2026-27")
    common.add_argument("--dry-run", action="store_true", help="Show what would be fetched; fetch nothing")
    common.add_argument("--force", action="store_true", help="Re-fetch even games already complete")
    common.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS, help="Request cap for this run")
    common.add_argument("--no-rebuild", action="store_true", help="Skip rebuilding team stats")

    p = argparse.ArgumentParser(description="Low-traffic CCCMBCA scraper", formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="Usage" + __doc__.split("Usage", 1)[1])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("master", parents=[common], help="Build or refresh the master schedule")
    s.add_argument("--resync", action="store_true", help="Refresh team pages not fetched in the last 24h")
    s.add_argument("--team", nargs="+")
    s.add_argument("--conference", nargs="+")

    s = sub.add_parser("nightly", parents=[common], help="The scheduled nightly job")
    s.add_argument("--date", help="Night to scrape (default: today after 6 PM, else yesterday)")

    s = sub.add_parser("day", parents=[common], help="Every game on a date or range")
    s.add_argument("date", help="YYYY-MM-DD")
    s.add_argument("--to", help="End date YYYY-MM-DD")

    s = sub.add_parser("game", parents=[common], help="One game")
    s.add_argument("id", nargs="?", help="Box score ID (20261114_ab12) or URL")
    s.add_argument("--team", nargs=1)
    s.add_argument("--date")

    for name in ("team", "conference"):
        s = sub.add_parser(name, parents=[common], help=f"Games for one or more {name}s")
        s.add_argument("names", nargs="+")
        s.add_argument("--date", help="YYYY-MM-DD")
        s.add_argument("--to", help="End date YYYY-MM-DD")

    s = sub.add_parser("missing", parents=[common], help="Re-check games missing stats now")
    s.add_argument("--team", nargs="+")
    s.add_argument("--conference", nargs="+")
    s.add_argument("--include-stale", action="store_true", help="Also re-check STALE and POSTPONED games")
    s.add_argument("--date", help="Only games on this date (YYYY-MM-DD), or from it with --to")
    s.add_argument("--to", help="End of the date range")

    s = sub.add_parser("status", parents=[common], help="Show the ledger (no network)")
    s.add_argument("--team", nargs="+")
    s.add_argument("--conference", nargs="+")
    s.add_argument("--date")
    s.add_argument("--to")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    state = State(args.season)
    if args.cmd == "status":
        return cmd_status(state, args)

    fetcher = Fetcher(args.max_requests)
    run = Run(state, fetcher, args)
    started = time.time()
    code = 0
    try:
        if args.cmd == "master":
            cmd_master(run, args)
        elif args.cmd == "nightly":
            cmd_nightly(run, args)
        elif args.cmd == "day":
            cmd_day(run, args)
        elif args.cmd == "game":
            cmd_game(run, args)
        elif args.cmd == "team":
            cmd_teams(run, resolve_teams(state, args.names), args)
        elif args.cmd == "conference":
            cmd_teams(run, resolve_conferences(args.names), args)
        elif args.cmd == "missing":
            cmd_missing(run, args)
    except Throttled as e:
        print(f"\nSTOPPED: the site is rate limiting us ({e}). Progress is saved; run again later.")
        code = 2
    except BudgetExhausted as e:
        print(f"\nSTOPPED: hit the request cap ({e}). Progress is saved; run again to continue.")
        code = 2

    if args.dry_run:
        print("\nDry run: nothing fetched or saved.")
        return code
    state.save()
    for line in run.log:
        print(f"  {line}")
    missing = len(missing_rows(state, sorted(state.games)))
    print(f"\n{fetcher.count} requests in {time.time() - started:.0f}s. "
          f"{missing} games missing stats -> {state.missing_path}")
    if not args.no_rebuild:
        rebuild(args.season, run.touched)
    return code


if __name__ == "__main__":
    sys.exit(main() or 0)
