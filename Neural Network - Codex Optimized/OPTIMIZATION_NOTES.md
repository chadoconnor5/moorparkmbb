# Optimization Notes

This copy keeps the original project intact and starts consolidating the working pipeline.

## Changes in this copy

- Added `ccc_config.py` for shared season paths, base URLs, and conference lookup.
- Added `run_pipeline.py` so the standard scrape -> stats -> analytics workflow can run as one command.
- Added `requirements.txt` for the dependencies currently implied by imports.
- Added `.gitignore` for Python caches, logs, virtual environments, and Playwright output.
- Made `scrape_team.py` and `generate_team_stats.py` accept `--season`.
- Added a `Height` Miscellaneous sub-tab to the leaderboard from `internal_data/roster_heights_2025_26.csv`.
- Added `generate_leaderboard.py --fast`, `--cache`, `--refresh-cache`, and `--output` build options.
- Shrunk the leaderboard HTML from ~38 MB to ~2.9 MB:
  - All embedded JSON is compact-serialized and columnar-packed (uniform lists of
    objects ship as one key list + value rows; `__unpack()` in the page restores them).
  - Redundant per-game fields (`pace`/`tempo` equal to `possessions`,
    `canonical_opponent` equal to `opponent`, derivable `result`) are nulled at
    build time and restored by `__fixGames()` in the page.
  - Conference team `game_ratings` are no longer shipped; they are an exact
    `is_conference` projection of the full team data and are rebuilt by
    `__deriveConfGames()` in the page (verified lossless across all seasons).
  - Past seasons (player/team/conference/storylines/daily-rank data) now live in
    `season_data/season_<key>.js` next to the output HTML and are lazy-loaded by
    `ensureSeason()` the first time the season toggle or the Trends tab needs
    them. Initial page load only carries the current season (~3 MB); each past
    season is ~1.7 MB fetched on demand. Works over both `file://` (script-tag
    injection, no fetch) and HTTP. Keep `season_data/` next to the HTML when
    moving or publishing it.
  - `--fast` builds do not rewrite `season_data/`, so existing season files from a
    previous full build keep serving past seasons.
- Shooting qualification rules (June 2026):
  - 2P% / 3P% / FT% leaderboards and charts: 20+ GP and 2.5 attempts per game
    (replaces the old 85-3PA chart rule and the 2.0/game leaderboard rule).
  - eFG% / TS%: teams with clean minutes keep the 50% Min% standard; teams with
    false/unreliable minutes (player flag `fm: 1`) use 20+ GP plus the
    attempt-rate floors anchored to the typical 50% min% player: 6.9 FGA/G
    (eFG%) and 9.1 FGA+FTA/G (TS%) — the median attempts of players in the
    45-55% min% band on clean-minutes teams across all seasons. Constants
    `EFG_FGA_PER_GAME_MIN` / `TS_ATT_PER_GAME_MIN` in generate_leaderboard.py
    — recompute when a season is added.
  - eFG%, TS%, and FT rate are now always populated for every player (computed
    from box totals when a team fails the 18-clean-game minutes checks).
- Chart Suggestions dropdown defaults to a blank option (individual and team
  modes). Manually changing an axis metric clears the suggestion so preset
  minimums no longer stick; qualification minimums follow the selected metrics.
- Player caches store the new fields, so run `--cache --refresh-cache` after
  changing load_players/load_conf_players.
- Per-game box scores (Torvik-style "Advanced Stats Box Score" modal): built by
  `build_game_boxes()` from the season schedules folders, advanced stats reuse
  STAT_DEFINITIONS from update_advanced_analytics.py (single source of truth).
  Shipped as lazy `season_data/boxes_<key>.js` files (~3.5 MB/season, loaded on
  first use; never in the initial HTML). Entry points: blue "Box" links in the
  team-detail schedule (left of Result) and FanMatch (left of Location). Game
  lookup keys come from `_box_game_key()` — its JS twin `__boxKey()` must stay
  in sync. False-minutes games show "—" for minutes-dependent rate columns.
  Single-game BPM/OBPM/DBPM implement Daniel Myers' BPM 2.0 single-game
  calculator (the user's reference workbook): per-100 adjusted-point stats,
  position/role-interpolated coefficients shared with compute_ccc_bpm.py, and
  a team adjustment blending lead-adjusted game ratings with the lineups'
  season OBPM/DBPM priors (from internal_data/ccc_bpm_2025_26.json; other
  seasons use neutral priors until their season BPM is computed). BPM columns
  require tracked minutes, turnovers, and fouls on both sides.
  Starters: boxes with scraped `is_starter`/`role` flags (2024-25 and 2025-26
  fully; 2023-24 partially backfilled) use them; all other boxes treat the
  first five listed players as starters. After backfilling roles for more
  seasons, refresh the box files: delete
  `internal_data/cache/leaderboard/*_boxes.json` and rebuild with `--cache`.
- practice_tracker.html (hand-maintained, not generated): roster lives in
  localStorage (`pt_roster`, edited in-app via the Roster button); the embedded
  `#roster-data` block is only the first-run seed. The Backup nav button
  exports sessions + roster + settings in one JSON; Import accepts that backup
  or legacy session files. All session/roster saves go through `persistKey()`,
  which surfaces quota/blocked-storage failures as a visible warning instead
  of silently losing data.

- PORPAGATU! (player offensive value): attach_porpagatu() in
  generate_leaderboard.py implements Torvik's final 2019 formula verbatim
  (z-score usage regression, asymmetric 1.25/1.5 usage slopes, SOS multiplier
  from opponents' season defensive efficiency, 104.9/88/69.4/500 constants)
  with CCC league averages, so values land on the T-Rank scale. Field `porp`
  on player rows (full + conference, all seasons), surfaced as the PRPG!
  advanced leaderboard category and a chart metric. Null without reliable
  minutes/usage (false-minutes teams).

- Player Profile pages: click any player name (leaderboards, Team Stats,
  box scores). Header + last-5/10 form bar + KenPom-style split table
  (Season / Conference / Tier A / Tier B / A+B / Untiered) + game log.
  Splits aggregate per-game box totals and run the same formulas as the
  season pipeline (Oliver ORtg/DRtg, usage, rates) via JS ports in the page
  (__ppOrtg etc. — keep in sync with update_advanced_analytics.py; note
  team_min semantics = total player minutes / 5). Advanced splits for
  18-clean-game teams, basic splits otherwise. Single-season only: no
  reliable cross-season player identity.
- 2018-19 was rescraped (old data was mislabeled 2019-20 content) and stats
  regenerated. Conference-only data for 2018-19 is sparse (~7 teams): most
  rescraped schedules lack is_conference flags — backfill needed if
  conference splits matter for that season.
- generate_scouting_report_v2.py: candidate replacement for the report forks.
  Imports generate_scouting_report (no code fork), repoints its BASE to THIS
  repo (the original scripts read the old copy's data), and adds a "What
  Drives Them" page: four-factor Pearson correlations vs game efficiency
  (noise-gated at |r| < 2/sqrt(n)), median W-L splits and micro-stats for the
  dominant offensive/defensive lever, and Synergy play-type tables when
  internal_data/synergy_team_<slug>_<season>.json exists (graceful note when
  not). Correlations read the leaderboard's cached enriched game_ratings
  (2526_teams) so they match the Game Plan view exactly. If promoted, fold
  into generate_scouting_report.py and retire the per-team forks.

## Example commands

```bash
python3 run_pipeline.py --season 2025-26 --teams Moorpark Ventura
python3 run_pipeline.py --season 2025-26 --all --prior-season 2024-25
python3 scrape_team.py --season 2024-25 --teams Moorpark --no-boxscores
python3 generate_team_stats.py --season 2024-25 --all
python3 generate_leaderboard.py --fast --cache --output wsc_north_leaderboard_fast.html
python3 generate_leaderboard.py --cache --refresh-cache
```

## Leaderboard build modes

- Full fresh build: `python3 generate_leaderboard.py`
- Full cached build: `python3 generate_leaderboard.py --cache`
- Refresh all caches: `python3 generate_leaderboard.py --cache --refresh-cache`
- Current-season-only build: `python3 generate_leaderboard.py --fast`
- Current-season cached build: `python3 generate_leaderboard.py --fast --cache`

Observed on this copy: fast cached builds run in about 3 seconds; full cached builds run in about 22 seconds after a cache refresh.

## Recommended next optimizations

- Replace the year-specific script copies with one parameterized implementation.
- Move report generation into reusable templates by report type.
- Add golden-file tests for one known box score and one known team summary.
- Decide which generated JSON/PDF/HTML artifacts should be versioned and which should live outside git.
