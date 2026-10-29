# WSC North Basketball Stats Pipeline

## Scripts

| Script | Purpose |
|---|---|
| `scrape_team.py` | Scrape schedules and box scores from CCCMBCA |
| `generate_team_stats.py` | Aggregate season stats from box score JSONs |
| `update_advanced_analytics.py` | Compute advanced analytics (eFG%, TOV%) |
| `build_preseason.py` | New season: last season's ratings as every team's start, SOS/NCSOS from this season's schedule |
| `generate_leaderboard.py` | Build the published leaderboard: `../index.html` + `../season_data/` (repo root, GitHub Pages) |

## Daily Scraping (`scrape.py`) — use this during the season

Low-traffic scraper. Each night it reads ONE page — the league composite
(daily scoreboard, `cccmbca.prestosports.com/composite`) — to find every box
score posted that day, fetches each box score once (both teams' folders get a
copy). It touches only that night's games: older games still missing stats are
re-checked only when you ask (`scrape.py missing`), never automatically.
Requests are one at a time, 5–8 s apart, capped at 150 per run, and the run
stops (progress saved) if the site rate-limits twice.

State lives in `scrape_state/<season>/`:
- `master_schedule.json` — every game once, both teams
- `ledger.json` — per-game status, box score URL, check history
- `missing_boxscores.md` — games still missing stats, why, and the URL
- `minutes_report.md` — per team, how many box scores have real minutes, and every game that
  doesn't: `PLACEHOLDER` (every player listed at 1 minute), `WRONG_TOTAL` (real-looking minutes that
  don't add up to 190–275), `NONE`. Each box score file also carries `minutes_quality` per team.

Statuses: `COMPLETE` · `PARTIAL` (one team's stats missing) · `NO_BOX` (no box
score / no stats yet) · `STALE` (given up on in older ledgers;
`missing --include-stale` re-checks them) · `POSTPONED` · `FORFEIT` · `NOT_TRACKED` (TBA / exhibition) ·
`SCHEDULED`. Missing games are never re-checked automatically: run
`scrape.py status` to see them and `scrape.py missing` (optionally `--team`,
`--conference`, `--date 2026-11-14 [--to 2026-11-20]`) to re-check them.

```bash
# --- Master schedule (once, when schedules are posted; ~100 requests, ~11 min) ---
python3 scrape.py master --from-typed   # 2026-27: build the game list from the typed-in schedules (no requests)
python3 scrape.py master
python3 scrape.py master --resync              # refresh pages older than 24h (rerun resumes)

# --- Box scores from screenshots (no site): 2026-27 Box Score Screenshots/<Month>/<MMDD>/<Team MMDD>.png ---
python3 read_screenshots.py                # every night folder not DONE; --date 1031 for one (the nightly runs it first)

# --- Nightly (the scheduled job: today after 6 PM, otherwise yesterday) ---
# Any scrape that saves new box scores then rebuilds, in the same run: those teams' stats, every team's analytics
# (each past game re-graded against the opponent's current rating), the saved daily ranks (daily_ranks/<season>.json),
# the leaderboard (+ the tracker's ratings.json / team files), and the tracker's scouting reports for the
# teams that played and are on our schedule or in tracker_teams.txt (../poss/reports/). Then it commits and
# pushes the run's changes itself (the site and the iPad pick them up); --no-push skips that, --no-rebuild the rebuild.
python3 scrape.py nightly
python3 scrape.py nightly --date 2026-11-14

# --- Day ---
python3 scrape.py day 2026-11-14
python3 scrape.py day 2026-11-14 --to 2026-11-16

# --- Single game ---
python3 scrape.py game 20261114_ab12
python3 scrape.py game /sports/mbkb/2026-27/boxscores/20261114_ab12.xml
python3 scrape.py game --team Moorpark --date 2026-11-14

# --- Team ---
python3 scrape.py team Moorpark
python3 scrape.py team Moorpark Ventura "Allan Hancock"
python3 scrape.py team Moorpark --date 2026-11-14

# --- Conference ---
python3 scrape.py conference "WSC North"
python3 scrape.py conference "WSC North" --date 2026-11-14
python3 scrape.py conference "WSC North" "WSC South"

# --- Missing / incomplete box scores ---
python3 scrape.py missing
python3 scrape.py missing --team Moorpark
python3 scrape.py missing --conference "WSC North"
python3 scrape.py missing --include-stale      # also STALE and POSTPONED games

# --- Status (no network) ---
python3 scrape.py status
python3 scrape.py status --team Moorpark
python3 scrape.py status --conference "WSC North"
python3 scrape.py status --date 2026-11-14

# --- Flags (any command) ---
--dry-run              # show what would be fetched, fetch nothing
--force                # re-fetch even complete games
--max-requests 50      # request cap for this run (default 150)
--no-rebuild           # skip rebuilding team stats afterwards
--season 2026-27       # choose season (default from ccc_config.py)
```

After a run, team stats and advanced analytics are rebuilt for the teams that
got new box scores. Rebuild the leaderboard separately
(`python3 generate_leaderboard.py`).

If the composite page ever stops honouring its `?d=` date parameter, the run
notices (the box score IDs carry the game date) and falls back to team
schedule pages. The URL format is `COMPOSITE_URL` at the top of `scrape.py`.

## Opponent-adjusted lineups (`adjust_lineups.py`)

Takes a tracker's **⬇ Lineup file** (game tracker: Season page; possession tracker:
Lineups → Season) and adjusts each five's games for the opponent's leaderboard rating
and home court, and each five's four factors against the opponent's opponent-adjusted
four factors (so out-rebounding a team that rebounds well against good opponents counts
for more). Run `update_advanced_analytics.py --all` first in-season so those are current.
From the possession tracker's file, each five is also adjusted within High / Medium / Low
leverage, High+Med and clutch, and leverage-weighted (High ×1, Medium ×0.6, Low ×0.25).
Load the output in the tracker with **⬆ Adjusted** (the possession tracker's halftime
report then suggests season fives for the factors we're losing), and in the leaderboard
(Moorpark → Lineups → **⬆ Load adjusted lineups**). All read it in the browser only.
Moorpark-internal: don't publish the output.

```bash
python3 adjust_lineups.py ~/Downloads/moorpark_lineups_2026-11-20.json
python3 adjust_lineups.py lineups.json --ratings-season 2026-27   # default: newest ratings
python3 adjust_lineups.py lineups.json --out internal_data/moorpark_lineups_adj.json
```

Out-of-system opponents (exhibitions) and scrimmages stay in the raw numbers and are
left out of the adjusted ones; the run lists every game it skipped.

## Scrape Schedules (`scrape_team.py`, whole-season pulls)

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
