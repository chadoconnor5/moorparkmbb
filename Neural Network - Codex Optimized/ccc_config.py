"""Shared configuration helpers for the CCC men's basketball pipeline."""

from pathlib import Path

DEFAULT_SEASON = "2025-26"


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
