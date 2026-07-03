"""
CCCMBCA Team Page Scraper - 2024-25 Season
Scrapes schedule, results, records, and box scores for any team.
Adapted from scrape_team.py for historical 2024-25 data.

Usage:
    python scrape_team_2024.py --team-id rxghxmdxqgb3vor5 --name Moorpark
    python scrape_team_2024.py --all          # scrape all teams
    python scrape_team_2024.py --list-teams   # list available team IDs
"""

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

BASE_URL = "https://cccmbca.org/sports/mbkb/2024-25"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATA_DIR = Path("2024-25 Teams Schedules")

# 2024-25 conference alignments (may differ from 2025-26)
# Note: De Anza was active in 2024-25, Golden West may have been different
CONFERENCES = {
    "WSC North": ["Allan Hancock", "Cuesta", "LA Pierce", "Moorpark", "Oxnard", "Santa Barbara", "Ventura"],
    "WSC South": ["Antelope Valley", "Bakersfield", "Canyons", "Citrus", "Glendale", "LA Valley", "Santa Monica", "West LA"],
    "Orange Empire Athletic": ["Cypress", "Fullerton", "Golden West", "Irvine Valley", "Orange Coast", "Riverside", "Saddleback", "Santa Ana", "Santiago Canyon"],
    "Pacific Coast Athletic": ["Cuyamaca", "Grossmont", "Imperial Valley", "MiraCosta", "Palomar", "San Diego City", "San Diego Mesa", "San Diego Miramar", "Southwestern"],
    "South Coast-South": ["Cerritos", "Compton", "El Camino", "LA Harbor", "LA Southwest", "Long Beach"],
    "South Coast-North": ["East Los Angeles", "LA Trade Tech", "Los Angeles City", "Mt. San Antonio", "Pasadena City", "Rio Hondo"],
    "Inland Empire Athletic": ["San Bernardino Valley", "Mt. San Jacinto", "Chaffey", "Copper Mountain", "Barstow", "Cerro Coso", "Victor Valley", "Desert", "Palo Verde"],
    "Coast-North": ["San Francisco", "Las Positas", "Chabot", "Canada", "San Mateo", "Ohlone", "De Anza", "Skyline"],
    "Big Eight": ["Santa Rosa", "Cosumnes River", "Sierra", "Modesto", "San Joaquin Delta", "Diablo Valley", "Sacramento City", "Folsom Lake", "American River"],
    "Coast-South": ["San Jose", "West Valley", "Cabrillo", "Foothill", "Monterey Peninsula", "Gavilan", "Hartnell"],
    "Bay Valley": ["Yuba", "Marin", "Contra Costa", "Merritt", "Los Medanos", "Napa Valley", "Alameda", "Mendocino", "Solano"],
    "Central Valley": ["Columbia", "Sequoias", "Merced", "Lemoore", "Reedley", "Fresno", "Porterville", "Coalinga"],
    "Golden Valley": ["Feather River", "Redwoods", "Butte", "Shasta", "Siskiyous", "Lassen"],
}

def normalize_team_name(team_name):
    """Normalize team names (e.g., 'Coalinga College' -> 'Coalinga')."""
    t = team_name.strip()
    # Remove ' College' suffix for standardization
    if t.endswith(" College"):
        t = t[:-8].strip()
    return t

def get_conference(team_name):
    """Return conference name for a team, or 'Other'."""
    t = normalize_team_name(team_name)
    for conf, teams in CONFERENCES.items():
        for ct in teams:
            if ct.lower() == t.lower():
                return conf
    return "Other"


def fetch(url: str) -> str:
    """Fetch a URL and return the HTML content."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for attempt in range(4):
        time.sleep(3 if attempt == 0 else 60)  # Back off on retries
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                if resp.status == 202 and not data:
                    if attempt < 3:
                        print(f"    Rate limited (202), waiting 60s...")
                        continue
                return data
        except urllib.error.HTTPError as e:
            if e.code == 459 and attempt < 3:
                print(f"    Rate limited (459), waiting 60s...")
                continue
            raise
    return ""


# ---------------------------------------------------------------------------
# Schedule page parser
# ---------------------------------------------------------------------------
class ScheduleParser(HTMLParser):
    """Parse team schedule page for records and game results."""

    def __init__(self):
        super().__init__()
        self.teams = {}  # team_name -> team_id (from dropdown)
        self.records = {}
        self.games = []
        # state
        self._in_option = False
        self._option_val = ""
        self._option_text = ""
        self._in_team_stats = False
        self._in_stat_label = False
        self._in_stat_value = False
        self._stat_label = ""
        self._stat_value = ""
        self._in_event_row = False
        self._current_game = {}
        self._in_date = False
        self._in_team_name = False
        self._in_result = False
        self._in_status = False
        self._in_notes = False
        self._in_links = False
        self._in_location_badge = False
        self._buf = ""
        self._in_a = False
        self._a_href = ""
        self._last_select_id = ""

    def handle_endtag(self, tag):
        if tag == "option" and self._in_option:
            self._in_option = False
            # Extract teamId from value
            m = re.search(r"teamId=([a-z0-9]+)", self._option_val)
            if m:
                self.teams[self._option_text.strip()] = m.group(1)

        if tag == "ul" and self._in_team_stats:
            self._in_team_stats = False

        if self._in_team_stats:
            if tag == "div" and self._in_stat_label:
                self._in_stat_label = False
                self._stat_label = self._stat_label.strip()
            if tag == "div" and self._in_stat_value:
                self._in_stat_value = False
                val = self._stat_value.strip()
                if self._stat_label and val:
                    self.records[self._stat_label] = val

        if self._in_event_row:
            if tag == "td" and self._in_date:
                self._in_date = False
                self._current_game["date"] = self._buf.strip()
            if tag == "span" and self._in_team_name:
                self._in_team_name = False
                self._current_game["opponent"] = self._buf.strip()
            if tag == "span" and self._in_location_badge:
                self._in_location_badge = False
                self._current_game["location_tag"] = self._buf.strip()
            if tag == "td" and self._in_result:
                self._in_result = False
                self._current_game["result"] = re.sub(r"\s+", " ", self._buf).strip()
            if tag == "td" and self._in_status:
                self._in_status = False
                self._current_game["status"] = re.sub(r"\s+", " ", self._buf).strip()
            if tag == "td" and self._in_notes:
                self._in_notes = False
                self._current_game["notes"] = self._buf.strip()
            if tag == "a" and self._in_a:
                self._in_a = False
                text = self._buf.strip()
                if "Box Score" in text and self._a_href:
                    self._current_game["boxscore_url"] = self._a_href
                elif "Video" in text and self._a_href:
                    self._current_game["video_url"] = self._a_href
                self._buf = ""
            if tag == "td" and self._in_links:
                self._in_links = False
            if tag == "tr":
                self._in_event_row = False
                if self._current_game.get("date"):
                    self.games.append(self._current_game)

    def handle_data(self, data):
        if self._in_option:
            self._option_text += data
        if self._in_stat_label:
            self._stat_label += data
        if self._in_stat_value:
            self._stat_value += data
        if self._in_date or self._in_team_name or self._in_result or self._in_status or self._in_notes or self._in_location_badge:
            self._buf += data
        if self._in_a:
            self._buf += data

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")

        if tag == "select":
            self._last_select_id = a.get("id", "")
        if tag == "option" and self._last_select_id == "filter-by-team":
            self._in_option = True
            self._option_val = a.get("value", "")
            self._option_text = ""

        # Team stats bar
        if tag == "ul" and "team-stats" in cls:
            self._in_team_stats = True
        if self._in_team_stats:
            if tag == "div" and "text-muted" in cls:
                self._in_stat_label = True
                self._stat_label = ""
            if tag == "span" and "fw-bold" in cls:
                self._in_stat_value = True
                self._stat_value = ""

        # Game rows
        if tag == "tr" and "event-row" in cls:
            self._in_event_row = True
            self._current_game = {
                "home_away": "home" if "home" in cls else ("away" if "away" in cls else "neutral"),
                "is_conference": "conf" in cls,
            }
        if self._in_event_row:
            if tag == "td" and "date" in cls:
                self._in_date = True
                self._buf = ""
            if tag == "span" and "team-name" in cls:
                self._in_team_name = True
                self._buf = ""
            if tag == "span" and "event-location-badge" in cls:
                self._in_location_badge = True
                self._buf = ""
            if tag == "td" and "result" in cls:
                self._in_result = True
                self._buf = ""
            if tag == "td" and "status" in cls:
                self._in_status = True
                self._buf = ""
            if tag == "td" and "notes" in cls:
                self._in_notes = True
                self._buf = ""
            if tag == "td" and "links" in cls:
                self._in_links = True
            if tag == "a" and self._in_links:
                self._in_a = True
                self._a_href = a.get("href", "")
                self._buf = ""


# ---------------------------------------------------------------------------
# Box score parser (reused from scrape_boxscore.py)
# ---------------------------------------------------------------------------
class BoxScoreParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_td = False
        self.in_th = False
        self.current_text = ""
        self.rows = []
        self.current_row = []
        self.in_stats_box = False
        self.current_team = None
        self.in_row_head = False
        self.teams = {}
        self.depth = 0
        self.stats_box_depth = 0
        self.visitor_name = ""
        self.home_name = ""
        self.score_line = []
        self.visitor_captured = False
        self.home_captured = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "div":
            self.depth += 1
            if "stats-box" in cls and "lineup" in cls and "full" in cls:
                team = None
                if "visitor" in cls:
                    team = "visitor"
                elif "home" in cls:
                    team = "home"
                # Only capture the FIRST occurrence (full-game stats);
                # subsequent matches are per-period breakdowns.
                if team == "visitor" and self.visitor_captured:
                    pass
                elif team == "home" and self.home_captured:
                    pass
                else:
                    self.in_stats_box = True
                    self.stats_box_depth = self.depth
                    self.current_team = team
                    self.rows = []
        if tag == "td":
            self.in_td = True
            self.current_text = ""
        if tag == "th":
            self.in_th = True
            self.current_text = ""
            if "row-head" in cls:
                self.in_row_head = True
        if tag == "tr":
            self.current_row = []

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_td = False
            self.current_row.append(self.current_text.strip())
        if tag == "th":
            self.in_th = False
            txt = self.current_text.strip()
            if txt:
                self.current_row.append(txt)
            self.in_row_head = False
        if tag == "tr" and self.current_row:
            self.rows.append(self.current_row)
        if tag == "div":
            if self.in_stats_box and self.depth == self.stats_box_depth:
                if self.current_team:
                    self.teams[self.current_team] = self.rows[:]
                    if self.current_team == "visitor":
                        self.visitor_captured = True
                    elif self.current_team == "home":
                        self.home_captured = True
                self.in_stats_box = False
                self.current_team = None
            self.depth -= 1

    def handle_data(self, data):
        if self.in_td or self.in_th:
            self.current_text += data


def parse_boxscore(html: str) -> dict:
    """Parse a box score page and return structured data."""
    parser = BoxScoreParser()
    parser.feed(html)

    # Extract team names from og:title
    title_m = re.search(r'og:title" content="(.+?) vs\. (.+?) - Box Score - (.+?)"', html)
    visitor_name = title_m.group(1) if title_m else "Visitor"
    home_name = title_m.group(2) if title_m else "Home"
    game_date = title_m.group(3) if title_m else ""

    total_match = re.findall(r'<td class="score total">(\d+)</td>', html)
    period_scores = re.findall(r'<td class="score">(\d+)</td>', html)

    headers = ["MIN", "FGM-A", "3PM-A", "FTM-A", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS"]

    result = {
        "visitor": visitor_name,
        "home": home_name,
        "date": game_date,
        "score": {},
        "teams": {},
    }

    if total_match:
        result["score"] = {visitor_name: int(total_match[0]), home_name: int(total_match[1])}

    name_map = {"visitor": visitor_name, "home": home_name}
    for key in ["visitor", "home"]:
        if key not in parser.teams:
            continue
        players = []
        current_role = None
        for row in parser.teams[key]:
            cleaned = [c.strip() for c in row if c.strip()]
            if not cleaned or cleaned[0] == "Player":
                continue
            if cleaned[0] == "STARTERS":
                current_role = "starter"
                continue
            if cleaned[0] == "RESERVES":
                current_role = "reserve"
                continue
            if cleaned[0] == "TEAM":
                current_role = "team"
                continue
            if len(cleaned) < 10:
                continue
            if cleaned[0] in ("TOTALS", "Totals"):
                continue
            name = re.sub(r"\s+", " ", cleaned[0]).strip()
            parts = name.split(" ", 1)
            if parts[0].isdigit() and len(parts) > 1:
                name = f"#{parts[0]} {parts[1]}"
            stats = dict(zip(headers, cleaned[1:]))
            player = {"name": name, "stats": stats}
            if current_role in ("starter", "reserve"):
                player["role"] = current_role
                player["is_starter"] = current_role == "starter"
            players.append(player)
        result["teams"][name_map[key]] = players

    return result


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------
def scrape_team(team_id: str, team_name: str, scrape_boxscores: bool = True) -> dict:
    """Scrape a team's full schedule page and optionally all box scores."""
    url = f"{BASE_URL}/schedule?teamId={team_id}"
    print(f"Fetching schedule: {team_name} ({team_id})...")
    html = fetch(url)

    parser = ScheduleParser()
    parser.feed(html)

    team_data = {
        "team_name": team_name,
        "team_id": team_id,
        "url": url,
        "last_updated": datetime.now().isoformat(),
        "records": parser.records,
        "all_teams": parser.teams,
        "games": [],
    }

    for g in parser.games:
        game = {
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

        # Parse W/L and score from result
        result_text = game["result"]
        wl_match = re.match(r"([WL]),?\s*(\d+)-(\d+)", result_text)
        if wl_match:
            game["win_loss"] = wl_match.group(1)
            game["team_score"] = int(wl_match.group(2))
            game["opponent_score"] = int(wl_match.group(3))

        # Scrape box score if available
        if scrape_boxscores and game.get("boxscore_url"):
            # Check if we already have this box score saved
            date_str = game.get("date", "").strip()
            opponent = game.get("opponent", "unknown")
            try:
                # 2024-25 season: dates from Aug 2024 to Jun 2025
                dt = datetime.strptime(date_str + " 2024", "%b %d %Y")
                if dt.month <= 6:
                    dt = dt.replace(year=2025)
                safe_opp = re.sub(r"[^a-zA-Z0-9]", "_", opponent).lower().strip("_")
                game_name = f"{dt.strftime('%Y%m%d')}_{safe_opp}"
                conf = get_conference(team_name)
                existing = DATA_DIR / conf / team_name / game_name / f"{game_name}.json"
                if existing.exists():
                    print(f"  Box score: {game['date']} vs {game['opponent']}... (cached)")
                    with open(existing) as ef:
                        game["boxscore"] = json.load(ef)
                    team_data["games"].append(game)
                    continue
            except ValueError:
                pass

            bs_url = game["boxscore_url"]
            if not bs_url.startswith("http"):
                bs_url = f"https://cccmbca.org{bs_url}"
            try:
                print(f"  Box score: {game['date']} vs {game['opponent']}...")
                bs_html = fetch(bs_url)
                game["boxscore"] = parse_boxscore(bs_html)
            except Exception as e:
                print(f"    Error: {e}")
                game["boxscore"] = None

        team_data["games"].append(game)

    return team_data


def list_teams():
    """Fetch the schedule page and list all available teams."""
    html = fetch(f"{BASE_URL}/schedule")
    parser = ScheduleParser()
    parser.feed(html)
    return parser.teams


def save_team(data: dict):
    """Save team data: <DATA_DIR>/<Conference>/<Name>/schedule.json + subfolder per game."""
    raw_name = normalize_team_name(data["team_name"].strip())
    conf = get_conference(raw_name)
    # Use canonical name from CONFERENCES if found
    name = raw_name
    if conf != "Other":
        for ct in CONFERENCES[conf]:
            if ct.lower() == raw_name.lower():
                name = ct
                break
    team_dir = DATA_DIR / conf / name
    team_dir.mkdir(parents=True, exist_ok=True)

    # Each box score gets its own subfolder: <date>_<opponent>/<date>_<opponent>.json
    bs_count = 0
    for g in data["games"]:
        bs = g.get("boxscore")
        if not bs:
            continue
        date_str = g.get("date", "").strip()
        opponent = g.get("opponent", "unknown")
        try:
            # 2024-25 season date handling
            dt = datetime.strptime(date_str + " 2024", "%b %d %Y")
            if dt.month <= 6:
                dt = dt.replace(year=2025)
        except ValueError:
            continue
        safe_opp = re.sub(r"[^a-zA-Z0-9]", "_", opponent).lower().strip("_")
        game_name = f"{dt.strftime('%Y%m%d')}_{safe_opp}"
        game_dir = team_dir / game_name
        game_dir.mkdir(exist_ok=True)
        bs_path = game_dir / f"{game_name}.json"
        with open(bs_path, "w") as f:
            json.dump(bs, f, indent=2)
        bs_count += 1

    # Save schedule (without inline boxscore data to keep it lean)
    schedule_data = dict(data)
    schedule_data["games"] = []
    for g in data["games"]:
        game_copy = {k: v for k, v in g.items() if k != "boxscore"}
        game_copy["has_boxscore"] = g.get("boxscore") is not None
        schedule_data["games"].append(game_copy)

    schedule_path = team_dir / "schedule.json"
    with open(schedule_path, "w") as f:
        json.dump(schedule_data, f, indent=2)

    total_size = sum(f.stat().st_size for f in team_dir.rglob("*.json")) / 1024
    print(f"Saved: {team_dir}/ — schedule + {bs_count} box scores ({total_size:.1f} KB total)")
    return team_dir


def main():
    parser = argparse.ArgumentParser(description="CCCMBCA Team Scraper - 2024-25 Season")
    parser.add_argument("--team-id", help="Team ID from the URL")
    parser.add_argument("--name", help="Team name")
    parser.add_argument("--list-teams", action="store_true", help="List all available teams")
    parser.add_argument("--all", action="store_true", help="Scrape all teams")
    parser.add_argument("--no-boxscores", action="store_true", help="Skip scraping individual box scores")
    parser.add_argument("--teams", nargs="+", help="Scrape specific teams by name")
    args = parser.parse_args()

    if args.list_teams:
        teams = list_teams()
        print(f"\n{'Team Name':<35} {'Team ID'}")
        print("-" * 60)
        for name, tid in sorted(teams.items()):
            print(f"{name:<35} {tid}")
        print(f"\nTotal: {len(teams)} teams")
        return

    if args.all:
        teams = list_teams()
        print(f"Scraping {len(teams)} teams for 2024-25 season...")
        for name, tid in sorted(teams.items()):
            try:
                data = scrape_team(tid, name, scrape_boxscores=not args.no_boxscores)
                save_team(data)
            except Exception as e:
                print(f"  ERROR scraping {name}: {e}")
        return

    if args.teams:
        all_teams = list_teams()
        for team_query in args.teams:
            # Fuzzy match
            matches = [(n, t) for n, t in all_teams.items() if team_query.lower() in n.lower()]
            if not matches:
                print(f"No team found matching '{team_query}'")
                continue
            for name, tid in matches:
                data = scrape_team(tid, name, scrape_boxscores=not args.no_boxscores)
                save_team(data)
        return

    if args.team_id:
        name = args.name or args.team_id
        data = scrape_team(args.team_id, name, scrape_boxscores=not args.no_boxscores)
        save_team(data)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
