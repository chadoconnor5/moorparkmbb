# CLAUDE.md

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
- In-season daily scraping: `scrape.py` (master schedule, nightly composite
  scrape, missing-box-score ledger in `scrape_state/<season>/`). Full command
  list in "Terminal Commands README.md". Keep it low-traffic: one request at a
  time, never fetch a box score that's already COMPLETE.
  python3 scrape.py master      # once, when schedules post
  python3 scrape.py master --from-typed   # instead: from the typed-in schedules (no requests; the site blocks team pages)
  python3 scrape.py nightly     # every night, that night's games only; then rebuilds stats, the leaderboard (ratings + team files)
                                # and the tracker's scouting reports for the teams that played (--no-rebuild skips),
                                # then commits and pushes it all (--no-push skips; a pull conflict stops before the push)
  python3 scrape.py status      # what's missing (no network)
  python3 scrape.py missing     # re-check older games missing stats (only when asked; --team/--conference/--date/--to)
- Opponent-adjust the trackers' lineups (game tracker Season page, or possession tracker
  Lineups -> Season -> Lineup file); ratings AND four factors, the four factors against
  each opponent's opponent-adjusted factors (adj_ff, from update_advanced_analytics.py):
  python3 adjust_lineups.py <lineup file>   # -> internal_data/moorpark_lineups_adj.json
- Publish the team ratings the possession tracker re-adjusts every game against (runs automatically at the
  end of generate_leaderboard.py and in run_pipeline.py). The tracker only carries ccc_config.TRACKER_SEASON (2026-27):
  until that season has ratings, everything it publishes is empty (no last-season numbers, Moorpark included):
  python3 export_ratings.py                 # -> ../poss/ratings.json + ../poss/teams/<team>.json (season and player
                                            #    stats for Moorpark's schedule + tracker_teams.txt, potential opponents
                                            #    like a tournament field: one team per line, short names ok)
                                            #    Team files also carry composite role-label scores (COMPOSITES),
                                            #    blending Synergy shot data from internal_data/synergy_players_*.json
- Opponent scouting report, the standard (the Ventura report's layout and detail) for any team; never overwrites a
  report (an existing name gets _v2, _v3...). Built from a team's first game: what there isn't data for yet shows "—"
  (the game / key / rotation counts are printed as notes, never a reason to skip); it refuses only a missing section or
  coaching / film / hedge language:
  python3 generate_opponent_report.py "Irvine Valley"   # -> scouting_reports/irvine_valley_scouting_report_2025_26_pre_synergy.pdf
                                                        #    (_synergy.pdf once internal_data/synergy_team_irvine_valley_2025_26.json
                                                        #    and synergy_players_irvine_valley_2025_26.json are added)
  python3 generate_opponent_report.py --all --out-dir <dir>   # every team (a check that the standard holds statewide)
  python3 generate_opponent_report.py --latest                # the tracker's copies: every team it has files for, one
                                                              #    current PDF each in ../poss/reports/ (replaced each time)
                                                              #    + index.json; scrape.py runs it with --only <teams that played>
- Schedules typed in from CCCMBCA screenshots (while cccmbca.org can't be scraped): one folder per team,
  `2026-27 Schedule Screenshots/<Conference>/<Team>/` (month PNGs + schedule.json in scrape_team.py's game format).
  Partial schedules for every other team from those (mirrored games), plus cross-checks between typed-in teams:
  python3 assemble_schedules.py            # -> <Team>/schedule_from_opponents.json + assembled_schedules_report.txt
  python3 build_preseason.py               # new season: every team starts at last season's ORtg/DRtg/net (+ tempo);
                                           #   SOS/NCSOS = this season's schedule rated by last season's net. Teams
                                           #   with games are left to update_advanced_analytics.py (prior fades in)
- Rosters typed in from the teams' roster pages: `2026-27 Rosters/<Conference>/<Team>/roster.json` (+ screenshot;
  height_adjustments.json for teams that list heights high). season_rosters.py loads them for the leaderboard (Team
  Stats shows a team's roster until its first game) and export_ratings.py (-> ../poss/rosters.json; the tracker fills
  opponent rosters from it, never replacing what was typed on the iPad). ccc_config.NO_TEAM lists members with no
  team in a season (Alameda 2026-27): no preseason rating, off that season's leaderboard.
- Team pages list each team's whole season schedule from the typed-in schedule.json files (load_season_schedules,
  embedded as SEASON_SCHEDULES); played games take their results from game_ratings.
- FanMatch shows a neutral-site game's location as "Host (N)" (neutral_host() reads the host from the schedule
  note's "@ ..."); team schedules keep Home / Away / Neutral.
- Bracket tournaments: `2026-27 Schedule Screenshots/brackets.json` (brackets.py). Opening-round games name the teams;
  later games reference them (W:G1 / L:G1). FanMatch lists each later game once ("Winner A/B vs Winner C/D",
  filled in as results come in). TBA games of tournaments
  without a bracket entered show once per game (the TBA teams at a site paired up), not once per team.
- The site refuses Python/curl requests (403) but not a browser: after a 403 scrape.py reads pages through the
  installed Chrome (Playwright, `pip install playwright`, no browser download; `--browser` from the start). A Chrome
  window opens minimized during the run. Gentle by design: 25-45s between pages, 40 pages a run at most, text only
  (no images/fonts/video), and the run stops at the first refusal, rate limit or bot check (never retries).
- Box score screenshots read on the PC (no site, no AI): `2026-27 Box Score Screenshots/<Month>/<MMDD>/<Team MMDD>.png`,
  one per team box (images stay out of git; the folders are kept). python3 read_screenshots.py [--date 1031] reads them
  with the tracker's Tesseract in Chrome, checks points/rebounds/TOTALS/minutes, writes a CSV beside each (edit it to
  correct; it is used over the image), saves a game once its member sides pass, CHECK.txt lists saved / to fix. Folders
  are never renamed: screenshots come in through the night or days later; each run reads only what's new (any date). scrape.py nightly/day/missing runs it first. SCRAPE COMMANDS.txt: the copy-paste list.
- Play-by-play: on the box score page scrape.py already fetches (no extra request). play_by_play.py reads it and
  scrape.save_box writes it once per game to `2026-27 Play by Play/<YYYYMMDD>_<visitor>_at_<home>.json` (each play:
  period, clock, team, player LAST,FIRST, action, score after; points by half). Kept out of the team folders (the box
  score readers take every .json there). Games from screenshots have no play-by-play.
- Every team's lineups from the play-by-play: python3 compute_pbp_lineups.py [--season S] (the nightly runs it) ->
  internal_data/pbp_lineups/<season>/<team>.json: five-man units per game from the substitutions (each later period's
  five from who shows up first; half-logged subs repaired from what players do next), possessions FGA-OREB+TO+.475FTA,
  leverage High/Med/Low/Clutch and garbage time as the possession tracker grades them, then adjust_lineups.adjust (the
  tracker lineups' opponent adjustment). A game is used only if five-on-the-floor holds, every player's minutes are
  within 2.5 of the box score, each half's within 2.0 of that half's box score (the page's period tabs) and the names match; the rest are listed with the reason. The leaderboard puts each
  team's in season_data/lineups_2627_<team>.js (lazy) with PBP_LU in the page; the team page shows Lineups -> for every
  team that has them (leaderboard_tracker_lineups.js: renderPbpLineups, shared table __luTable, leverage buttons).
- Game attributes (Misc tabs, build_storylines): 2026-27 only, from the play-by-play (KenPom's, the teams assumed
  equal; _sl_wp): Excitement (win probability's total movement), Tension (how close it stayed to 50%), Dominance
  (the winner's time-weighted lead), Min WP, Max Deficit, Window (largest lead + deficit); games without
  play-by-play aren't in those lists. Upsets count from game one (both teams rated from last season). Past seasons
  keep their tabs and formulas as they were (no new tabs).
- Box score win-probability chart (2026-27 games with play-by-play, Final view), Torvik-style: the winner's chance
  from the lead, time left and the pregame expected margin (the game's FanMatch row: pregame nets + 3 home court),
  the score margin dotted on the right axis, green/red dots for each team's scores, a ring where it reached 99% for
  good. build_game_boxes stores the scoring as "wp" [visitor, periods, string] (_wp_events); the page rebuilds the
  curve (__bxWpChart). The Min WP / Excitement / Tension tabs stay KenPom's (teams equal). Past seasons: no chart.
- Stints (internal, for a possible BPR later): compute_pbp_lineups.py also writes internal_data/pbp_stints/<season>.json,
  every usable game's stretches with the same ten on the floor (both fives, seconds, each side's possessions and
  points, garbage-time flag, leverage). Not used on the site; BPR only if play-by-play coverage per team turns out
  high enough to mean something.
- Box scores typed in from screenshots: saved where scrape.py saves them (`2026-27 Teams Schedules/<Conf>/<Team>/
  YYYYMMDD_<opponent slug>/<same>.json`, scrape_team.parse_boxscore's format, one copy per member team). The nightly
  takes a box score on disk first: the game is COMPLETE with no request, its teams rebuild, and a night with every game
  in (and no TBA games) never touches the site. A refused composite page (403) marks that night's games missing; the
  run still rebuilds and pushes.
- TBA games (tournaments) aren't in the master schedule: the nightly reads its night's composite page every time, so
  their box scores turn up there and are added; the TBA row takes the opponent's name. A tournament game against
  the host is the host's Home game and the visitor's Away game (generate_team_stats.py, neutral_host() in
  assemble_schedules.py); other tournament games stay Neutral. A played TBA game replaces its TBA row (team pages,
  FanMatch).
- Playoff dates (after the regular season, late Feb on) stay off the typed-in schedules during the regular season.
- No conference games before mid-December, and never at a neutral site / tournament: typed-in schedules must not
  flag them (is_conference).
- Daily ranks (2026-27) are saved, not rebuilt: every leaderboard build writes each team's rank and the date to
  daily_ranks/<season>.json (rank_history.py; the nightly commits and pushes it). A played game shows the rank saved before
  its date (locked at tip-off); of the games to come only a team's next one shows a rank (today's). A saved day is
  recomputed only when a game dated on/before it arrives late. Past seasons keep their reconstructed daily ranks.
- WAB from 2026-27 on (calculate_wab.py / compute_wab_sim.py, ADJUSTED_FROM): every game is graded against the
  opponent's current leaderboard rating (update_advanced_analytics: opponent-adjusted, last season fading out), the
  bubble is the 48th (split: 24th) team on those ratings, and a team is listed from its first game - sensible from
  night one. Earlier seasons keep the raw per-game method (published WAB unchanged). Scouting reports read the
  season's own wab_results_<season>.json.
- Nightly opponent adjustment: scrape.py runs update_advanced_analytics.py --all, so every team's past games are
  re-graded against each opponent's current rating (ORtg/DRtg/net, adjusted four factors, SOS, Opp/Pace Adjust);
  the current season regresses to last season's rating with prior_weight(games) (fades out), past seasons unchanged.
- Keys tab (KEYS_TEAMS in generate_leaderboard.py): a team with a head coach analyzes the last 5 seasons (2022-23 to
  2026-27) or the coach's tenure if shorter ("seasons"); "cur" is 2026-27 from its 5th game (last season until then).
  A team without a coach (windows ["cur"]) gets 2026-27 only, from its first game. Rebuilt every run.
- Charts: player bubbles show one letter per name and hyphen piece (John Paul Ozumba JPO, Jaxon Rous-Smith JRS),
  suffixes dropped, at most 3.
- Last 5 / Last 10 (leaderboard scopes, charts, player pages, Moorpark lineups, the possession tracker's splits) are
  empty until a team has played 5 / 10 games that season: never fewer games, never last season's.
- FanMatch lists every scheduled game; it projects one only when both teams have played MIN_PROJ_GAMES (5) games
  that season (generate_leaderboard.py).
  python3 build_master_schedule.py         # -> master_schedule.csv/.xlsx/.html (every game once; rows colored:
                                           #    Moorpark gold, Moorpark opponents vs each other blue, other opponent games red)
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
- ../index.html: the published leaderboard (generate_leaderboard.py writes it to the repo root, which GitHub Pages
  serves; ../wsc_north_leaderboard.html only redirects there). The page is the redesign (light theme, left sidebar).
- ../season_data/*.js (lazy-loaded per-season data) and ../team_logos/: written next to it; must stay beside it
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

## Practice Tracker (two copies, kept identical)

The practice tracker ships as two byte-identical files:

- `tracker/index.html` — what GitHub Pages serves, with `tracker/pt_data.json` beside it
- `Neural Network - Codex Optimized/practice_tracker.html` — the local editor copy

They are the same app. The only difference is that `pt_data.json` sits next to the
published one, and `loadPublishedData()` treats that file's presence as "this is the
published site": it sets `_publishedMode` and hides Live Tracker, Publish and Backup.
**Never put a `pt_data.json` next to the editor copy** — it would turn it view-only.
The editor copy's data comes from `localStorage`.

Edit either file; a `pre-commit` hook runs `tools/sync_tracker.py` and copies your
change to the other one automatically. It infers the direction from which side you
changed, and refuses the commit only if both were edited to different content. Run
`python tools/sync_tracker.py --check` to test for drift without writing anything.
(The hook lives in `.git/hooks/` and is not cloned — reinstall it after a fresh clone.)

Publishing data is separate: the ↑ Publish button downloads `pt_data.json`, which you
commit next to `tracker/index.html`. GitHub Pages serves it with `max-age=600` behind
a CDN, so the fetch carries a `?v=` timestamp to force a fresh copy; `index.html`
itself cannot bust its own cache and will trail a push by a few minutes.

## Agent/LLM Guidance
- Always run the full pipeline (scrape → stats → analytics) for up-to-date results.
- Validate output files after each step.
- When adding new teams or seasons, update folder structure accordingly.
- If you encounter errors, check for missing or malformed JSON files in the schedules/statistics folders.

## Updating This File
- Update this CLAUDE.md whenever you add scripts, change folder structure, or update workflows.
- Keep instructions concise and actionable.

## See Also
- Terminal Commands README.md for more detailed usage examples.
- Add additional rules or skills in `.claude/rules/` if the project grows.
