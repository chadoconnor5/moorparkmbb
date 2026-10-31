"""Shared configuration helpers for the CCC men's basketball pipeline."""

import re
from pathlib import Path

DEFAULT_SEASON = "2026-27"
# The possession tracker (../poss) only ever carries this season's data: ratings, team files (Moorpark too) and the
# scouting reports. Until the season has stats, export_ratings publishes them empty. (The leaderboard page has its
# own season wiring; this doesn't touch it.)
TRACKER_SEASON = "2026-27"


CONFERENCES = {
    "WSC North": ["Allan Hancock", "Cuesta", "LA Pierce", "Moorpark", "Oxnard", "Santa Barbara", "Ventura"],
    "WSC South": ["Antelope Valley", "Bakersfield", "Canyons", "Citrus", "Glendale", "LA Valley", "Santa Monica", "West LA"],
    "Orange Empire Athletic": ["Cypress", "Fullerton", "Irvine Valley", "Orange Coast", "Riverside", "Saddleback", "Santa Ana", "Santiago Canyon"],
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

# Members with no team that season: no preseason rating, so they stay off that season's leaderboard.
NO_TEAM = {
    "2026-27": {"Alameda"},
}


# Forfeits: (date, winner, loser). The game's stats stay (players, team totals, ORtg / DRtg / net from the score on the
# court), but its result is a 2-0 forfeit: record, game log, schedules, WAB, quads. generate_team_stats.py applies it
# (team_score / opponent_score 2-0, court_score keeps the real one).
FORFEITS = [
    ("2026-10-29", "Desert", "LA Southwest"),   # LA Southwest won 85-82 on the court
]


def forfeit_of(date: str, team: str, opponent: str):
    """'W' / 'L' when this game (box score date M/D/YYYY or YYYY-MM-DD) is a forfeit for team, else None."""
    m = re.match(r"(\d+)/(\d+)/(\d{4})", date or "")
    iso = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else (date or "")[:10]
    low = lambda s: (s or "").strip().lower()
    for d, w, l in FORFEITS:
        if d == iso and {low(w), low(l)} == {low(team), low(opponent)}:
            return "W" if low(w) == low(team) else "L"
    return None


def fields_team(team_name: str, season: str) -> bool:
    return team_name not in NO_TEAM.get(season, set())


def season_base_url(season: str) -> str:
    return f"https://cccmbca.org/sports/mbkb/{season}"


def schedule_dir(season: str) -> Path:
    return Path(f"{season} Teams Schedules")


def stats_dir(season: str) -> Path:
    return Path(f"{season} Team Statistics")


def get_conference(team_name: str) -> str:
    """Return conference name for a team, or 'Other'."""
    normalized = team_name.strip().lower()
    for conference, teams in CONFERENCES.items():
        if any(team.lower() == normalized for team in teams):
            return conference
    return "Other"
