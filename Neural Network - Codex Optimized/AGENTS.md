# AGENTS.md

## MANDATORY: Read OPTIMIZATION_NOTES.md First

**Before implementing ANY change in this repository, you (any AI model, agent,
or assistant) MUST read `OPTIMIZATION_NOTES.md` in full and abide by it.**
It records how the leaderboard build pipeline is optimized (columnar data
packing, lazy-loaded season files, derived fields) and the build/caching
workflow. Changes that ignore it can silently regress page size, break the
season lazy-loader, or corrupt the packed data format. If your change alters
the build pipeline, data formats, or workflows, update OPTIMIZATION_NOTES.md
in the same change.

## Project Overview
This repository contains a pipeline for scraping, aggregating, and analyzing California Community College men's basketball statistics. The workflow is:

1. Scrape schedules and box scores from CCCMBCA
2. Aggregate season and player stats
3. Compute advanced analytics

## Setup Instructions
- Requires Python 3.8+
- Recommended: Create a virtual environment
- Install dependencies (if any requirements.txt or pip install needed)

## Main Scripts & Commands
- List all teams:
  python3 scrape_team.py --list-teams
- Scrape a single team:
  python3 scrape_team.py --teams <TeamName>
- Scrape multiple teams:
  python3 scrape_team.py --teams Team1 Team2 ...
- Scrape all WSC North teams:
  python3 scrape_team.py --teams Moorpark Ventura "Allan Hancock" Cuesta Oxnard "Santa Barbara" "LA Pierce"
- Scrape all teams:
  python3 scrape_team.py --all
- Generate stats for all teams:
  python3 generate_team_stats.py --all
- Update advanced analytics for all teams:
  python3 update_advanced_analytics.py --all

## Folder Structure
- 2025-26 Teams Schedules/<Team>/
  - schedule.json
  - YYYYMMDD_opponent/ (box scores)
- 2025-26 Team Statistics/<Team>/
  - season_stats.json
  - player_stats.json
  - team_summary.json
  - game_log.json
  - advanced_analytics.json

## Key Conventions
- Team and player names are case-sensitive and must match CCCMBCA listings.
- All scripts are run from the project root.
- Output files are overwritten on each run.

## Agent/LLM Guidance
- Always run the full pipeline (scrape → stats → analytics) for up-to-date results.
- Validate output files after each step.
- When adding new teams or seasons, update folder structure accordingly.
- If you encounter errors, check for missing or malformed JSON files in the schedules/statistics folders.

## Updating This File
- Update this AGENTS.md whenever you add scripts, change folder structure, or update workflows.
- Keep instructions concise and actionable.

## See Also
- Terminal Commands README.md for more detailed usage examples.
- Add additional rules or skills in `.Codex/rules/` if the project grows.
