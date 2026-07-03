# WSC North Basketball Stats Pipeline

## Scripts

| Script | Purpose |
|---|---|
| `scrape_team.py` | Scrape schedules and box scores from CCCMBCA |
| `generate_team_stats.py` | Aggregate season stats from box score JSONs |
| `update_advanced_analytics.py` | Compute advanced analytics (eFG%, TOV%) |

## Scrape Schedules

### List all available teams
```bash
python3 scrape_team.py --list-teams
```

### Scrape a single team (schedule + box scores)
```bash
python3 scrape_team.py --teams Moorpark
```

### Scrape multiple teams
```bash
python3 scrape_team.py --teams Moorpark Ventura "Allan Hancock"
```

### Scrape all WSC North teams
```bash
python3 scrape_team.py --teams Moorpark Ventura "Allan Hancock" Cuesta Oxnard "Santa Barbara" "LA Pierce"
```

### Scrape schedule only (no box scores)
```bash
python3 scrape_team.py --teams Moorpark --no-boxscores
```

### Scrape every team in the CCCMBCA
```bash
python3 scrape_team.py --all
```

## Calculate Statistics

### Generate season stats for all teams
```bash
python3 generate_team_stats.py --all
```

### Generate stats for specific teams
```bash
python3 generate_team_stats.py --teams Moorpark Ventura
```

This reads box scores from `2025-26 Teams Schedules/<Team>/` and writes to `2025-26 Team Statistics/<Team>/`:
- `season_stats.json` — per-player totals and averages
- `player_stats.json` — individual player stat lines
- `team_summary.json` — team totals, averages, and record
- `game_log.json` — game-by-game results

### Update advanced analytics for all teams
```bash
python3 update_advanced_analytics.py --all
```

### Update advanced analytics for specific teams
```bash
python3 update_advanced_analytics.py --teams Moorpark Ventura
```

### Look up a specific player's analytics
```bash
python3 update_advanced_analytics.py --player Noah Cotton
```

Reads `player_stats.json` and writes `advanced_analytics.json` with team-level and per-player metrics.

## Full Pipeline (scrape → stats → analytics)

```bash
python3 scrape_team.py --teams Moorpark Ventura "Allan Hancock" Cuesta Oxnard "Santa Barbara" "LA Pierce"
python3 generate_team_stats.py --all
python3 update_advanced_analytics.py --all
```

## Folder Structure

```
2025-26 Teams Schedules/
  <Team>/
    schedule.json
    YYYYMMDD_opponent/
      YYYYMMDD_opponent.json    # box score

2025-26 Team Statistics/
  <Team>/
    season_stats.json
    player_stats.json
    team_summary.json
    game_log.json
    advanced_analytics.json
```
