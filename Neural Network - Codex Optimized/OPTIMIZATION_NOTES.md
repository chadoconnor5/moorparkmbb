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

- In-season scraping moved to `scrape.py` (Oct 2026). The nightly job reads
  one composite (daily scoreboard) page, fetches each box score once and
  writes it into both teams' folders, and patches both teams' schedule.json
  rows — so the stats scripts' inputs are unchanged. A box score is only
  "complete" when both teams have players; one-sided ones are re-fetched on a
  backoff (scrape_team.py cached them forever). Small player-points vs score
  mismatches (~4% of last season's boxes) are kept as a ledger note, not
  re-checked. Box labels are matched to schedule names with
  `name_strength()` (exact / TEAM_ALIASES / safe variants); validated on all
  1,443 2025-26 box scores with zero mismatches. State in
  scrape_state/<season>/ — outside the schedules folder, which the stats
  scripts treat as conference folders.

- Opponent-adjusted lineups (Oct 2026): `adjust_lineups.py` reads the game tracker's
  game-by-game lineup file and adjusts each five's game with the same formula
  `compute_iterative_adjusted_ratings()` applies to a team's game (opponent's team
  ortg/drtg from advanced_analytics.json, league averages, HOME_ADVANTAGE split by
  venue), possession-weighted across games. It imports update_advanced_analytics for
  `resolve_opponent()` and `HOME_ADVANTAGE`, so name matching and home court stay in
  one place. Read-only against the stats folders; writes only its output file.
  The leaderboard's Lineups panel loads that output in the browser ("Game Tracker —
  Opponent-Adjusted" section, `leaderboard_tracker_lineups.js`, inserted into the page
  by generate_leaderboard.py as `_TRACKER_LU_JS`). Nothing is embedded at build time:
  the file is read client-side and kept in localStorage (`lb_tracker_lineups`). 1- to
  4-man groups are summed from the 5-man units (adjusted ratings as possession-weighted
  sums). Moorpark's "Lineups →" link shows in the build's current season even without
  a Synergy export; the Synergy panel itself stays 2025-26 only.

- Opponent-adjusted four factors (Oct 2026): `update_advanced_analytics.py` pass 4,
  `compute_iterative_adjusted_factors()`, adjusts eFG%, TO%, OReb% and FT rate at both
  ends the way pass 2 adjusts ORtg/DRtg (game value - opponent's adjusted counterpart +
  league average; iterated, regressed with REGRESSION_GAMES, damped, re-centred; no
  home-court term). Per-game inputs are stored as `team.game_ff` (in-system games only)
  and the result as `team.adj_ff`, keyed like the raw season factors; the raw factors are
  untouched. `game_ff` is NOT shipped: team rows are built from explicit keys, and only
  the eight `adj_*` fields are added to them. The T-Rank table has an Opp-adjusted / Raw
  four-factors toggle (default adjusted; seasons without `adj_ff` fall back to raw).
  `adjust_lineups.py` reads `adj_ff` to adjust each five's four factors (per game,
  weighted by that factor's own attempts, clamped to 0-100) into `adjFF` / `adjFFw`;
  the leaderboard's tracker-lineups panel combines them for 1- to 4-man groups.
  Leverage: the possession tracker's lineup file gives each unit a `lev` block per leverage
  bucket (high / med / low / clutch; garbage time already out). adjust_lineups.py adjusts each
  bucket the same way, plus `hm` (High+Med) and `w` (leverage-weighted, LEV_W: High 1, Medium
  0.6, Low 0.25), into each unit's `lev`, with `levMix` (% of possessions High/Med/Low). Files
  without `lev` (the game tracker's) give the same top-level numbers as before.
  Situational lineups: each bucket also carries raw counts (`o`/`d` incl. 3PA and steals, `stops`,
  `fouls`) for the stats with no opponent adjustment, and the output has `playerSeason` (Moorpark's
  player season lines). playerSeason is built from the season's box scores in the schedules folder:
  {name: {all, quality}}, quality = games against an in-system opponent with a positive adjusted net,
  decided by QUALITY_MARGIN (15) or fewer. Each bucket's `q` holds the same raw counts from games against
  positive-net opponents only.

- Possession tracker ratings (Oct 2026): `export_ratings.py` writes `../poss/ratings.json` (compact JSON,
  ~30 KB): every in-system team's ortg/drtg, `adj_ff` subset, games, OPPONENT_ALIASES, HOME_ADVANTAGE,
  QUALITY_MARGIN, Moorpark `playerSeason` (adjust_lineups.load_players) and `phase`. generate_leaderboard.py
  calls it at the end of every build (wrapped in try/except: it never fails the build) and run_pipeline.py
  runs it after update_advanced_analytics.py. The tracker re-adjusts every game client-side with a JS port of
  `adjust()` (poss: adjust.js); keep the two in sync (scratchpad e2e adjparity.js compares them).
  Time of season: `adjust_lineups.season_phase()` = league in-system game ORtg by month minus the season
  average, averaged over every season folder (Nov ~ -1.8, Dec -0.8, Jan +1.0, Feb +1.7, Mar +0.4; October
  folds into November). `adjust()` takes `phase` and shifts both ends of each game by -phase[month], so a
  five's net is unchanged and its O/D split is put on the season-average scale.

- Team files for the tracker (Oct 2026): `export_ratings.py` also writes `../poss/teams/<team>.json` (~10-20 KB
  each) for Moorpark, every team on Moorpark's schedule.json (`scheduled`) and every team in `tracker_teams.txt`
  (potential opponents, e.g. a tournament field: one per line, short names like RCC / CCSF / SBVC map through
  `SHORT`; unmatched lines are printed). Not all 100 teams: ~27 files / ~400 KB. Files for teams that drop off both
  lists are deleted. Indexed in ratings.json as `teamFiles`.
  Each file also carries `table`: the leaderboard's Team Stats table for that team (rows straight from
  `load_full_rosters()`, `adv` flag) with each player's State Rank on the 15 ranked stats. Ranks are computed in
  `export_ratings.state_ranks()` from `load_players()` (the page's DATA pool) with a Python port of the page's
  TS_RANK_STATS / __tsQualifies / advSchoolNeedsRelaxedCat rules: change those JS rules and the port together.
  Checked against the page (Citrus, 2025-26: identical). Adds ~3 s to the export.
  ORtg State Rank is statewide WITHIN the player's %Poss band (TS_USAGE_BANDS: >28 / 24-28 / 20-24 / 16-20 / 12-16 /
  <12): `__tsUsageBand()` in the page, `usage_band()` in export_ratings.py. Every other ranked stat is overall.
  Rows also carry `porp` (PORPAGATU!, via `attach_porpagatu(load_players(), load_teams())`) with `rank.porp` =
  statewide rank among players with 30%+ of minutes; the tracker's *Star* label is the top 5%.
  Composite role labels (COMPOSITES / composites() in export_ratings.py): per player, factors = State Rank turned into
  a 0-100 "how good" percentile (ORtg within band) plus raw-share percentiles (usage, 3PA rate, 3PA/g, 2PA/g, inside =
  100 - 3PA rate, balance = 100 - 4*|3PA rate - 40|) among min% >= 30, plus Synergy shot-type pps ranks (national
  percentiles) from internal_data/synergy_players_<slug>_<season>.json / synergy_archetypes.json (2025-26 Moorpark).
  Each composite = gate + weighted mean (renormalized over present factors, null under 60% of the weight); the cut
  is the quantile of the gated pool's BOX-ONLY scores (Synergy scores compared against the same cut). Rows carry
  rank.comp {name: score} (sit.js reads it as rk.comp), totals["compCut"], and row["syn"] (shares / FG% only, for the why text). Scorer = pprod/g 60 · ppg 20 · usage 20 (top 10%).
  Sixth man (sixth_men()): per team, bench = gs/gp <= .35 and <= 3 starts in the last 10 box scores (recent_starts(),
  the box's starter flags), gp >= 60% of the team's games, 15+ mpg; best by mpg 40 · usage 30 · pprod/g 30 (state
  percentiles, min% >= 30 pool), score >= 30; rank["roles"] = ["Sixth man"]. 2025-26: 28 teams have one.
  Glue guy (glue_guys()): usage < 17 and >= 2 of OR%, DR%, Stl%, Blk%, ARate at the 70th percentile+ (min% >= 30
  pool); appended to rank["roles"]. 2025-26: 19 players.
  Help off (help_off()): gs >= 60% of gp, gp >= half the team's games, ppg < 5, usage < 16 (or unknown on low-info
  teams). sit.js
  autoLabels uses them when present; keep its why lines and LABEL_GUIDE in step with COMPOSITES. Each holds `team` (team_summary.json's record / totals /
  averages for and against, plus advanced_analytics.json's team block without `game_ratings` / `game_ff`) and
  `players` (`adjust_lineups.load_players(team=...)`: {name: {num, all, quality, adv}}; `adv` = the player's
  advanced_analytics.json row). `load_players` now finds a team's side of a box with `resolve_opponent()` (box labels
  vary: "LA Valley") and records `num`, the jersey number from the latest box score. The tracker downloads only the
  files for teams it plays (its schedule, a "Teams to have ready" tournament list, rosters it keeps), keeps them for
  offline gyms, and refetches when ratings.json's `generatedAt` changes. Same compact JSON as ratings.json; written in
  ~1 s; nothing is added to the leaderboard HTML.

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
