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
  python3 scrape.py rebuild     # stats, ratings, lineups, WAB/BPM, leaderboard, reports from disk, then push (no site requests)
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
                                           #   SOS/NCSOS/Opp ORtg/DRtg 0.0 until it plays. Teams
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
- Positions (compute_positions_from_boxscore.py, the hoop-explorer LDA trained on 2025-26 heights): every season
  in SEASONS, or --season S. The rebuild (scrape.py) runs it for the current season every night before the
  leaderboard, so a player gets his position once he has MIN_GAMES (5) games and MIN_FGA (5) shots; 2026-27 heights
  for the touch-up come from the typed-in rosters (generate_leaderboard._load_player_heights). Needs scikit-learn
  (the rebuild carries on without it).
- Every team's lineups from the play-by-play: python3 compute_pbp_lineups.py [--season S] (the nightly runs it) ->
  internal_data/pbp_lineups/<season>/<team>.json: five-man units per game from the substitutions (each later period's
  five from who shows up first; half-logged subs repaired from what players do next), possessions FGA-OREB+TO+.475FTA,
  leverage High/Med/Low/Clutch and garbage time as the possession tracker grades them, then adjust_lineups.adjust (the
  tracker lineups' opponent adjustment). Scorekeepers log subs loosely, so the five is repaired from what players do;
  only stretches that needed no repair count (a stretch between two of a team's logged subs with a repair in it is
  left out of that team's units; each game records its "clean" share). A game is dropped only if names don't match
  the box score or over 25% of plays lack five on the floor. Box-score minutes (whole game, each half) are notes, not
  a reason to drop: box scores are sometimes wrong (10/29 Marin: two players' minutes swapped). The site writes some
  names out of order ("SILVA,CAIO DA", "JR,KEIAN WILLIAMS"): play_by_play splits at the play, fix_plays repairs saved
  files as they are read, and names match the box score by all their words. The leaderboard puts each
  team's in season_data/lineups_2627_<team>.js (lazy) with PBP_LU in the page; the team page shows Lineups -> for every
  team that has them (leaderboard_tracker_lineups.js: renderPbpLineups, shared table __luTable, leverage buttons).
- Game attributes (Misc tabs, build_storylines): 2026-27 only, from the play-by-play (KenPom's, the teams assumed
  equal; _sl_wp): Excitement (win probability's total movement), Tension (how close it stayed to 50%), Dominance
  (the winner's time-weighted lead), Min WP, Max Deficit, Window (largest lead + deficit); games without
  play-by-play aren't in those lists. Upsets count from game one (both teams rated from last season). Past seasons
  keep their tabs and formulas as they were (no new tabs).
- Player labels (export_ratings.auto_labels, a port of the tracker's autoLabels, checked label-for-label and why-line
  for-line against it on every 2026-27 player): written into each team file's Team Stats rows (row["labels"]); the
  tracker shows them (its own JS rules stay for older files and players known only from our tracked games), and the
  scouting report's player profiles list them ("Labels: Scorer, Elite shooter; weak spots: Foul-prone"). Change a
  label rule in both places.
  The report's player card header shows a label line under the name (generate_opponent_report.header_labels): up to 3
  strengths in green (Lockdown always among them) and up to 2 weak spots in red (Attackable first; WEAK_LABELS).
- Synergy leaderboard exports (any situation: At Rim, Long 3, Catch and Shoot, All Poss + Assists, Overall Player
  Defensive, Transition Team Defensive...): Synergy needs a login, so they come in by hand when we scout.
  python3 import_synergy_leaderboard.py <file.xlsx> [...] [--as-of YYYY-MM-DD] -> internal_data/synergy_leaderboards/
  <season>/<situation>.json (internal only; counts as season totals, rates as they are; team names mapped to ours,
  Synergy's name kept as "Synergy Team"; player names through fix_player_name; the newest export of a situation
  replaces the last). Labels lean on Synergy (very accurate) over the play-by-play, whatever its age.
  Moorpark Synergy.bat (double-click on the PC): loads every Downloads\Leaderboards*.xlsx (--delete removes each one
  once loaded; one it can't read stays and is listed), then commits and pushes internal_data/synergy_leaderboards.
  SYNERGY CHECKLIST.txt: what to grab each scout.
- Scouting report player profiles end with one sentence on what he does most by the Synergy leaderboards
  (generate_opponent_report.syn_board_sentence): his two offensive boards with the most possessions (At Rim, Around
  Basket, Post Ups, Short, Mid, Long 3, Catch & Shoot, Off-Dribble Jumpers; Around Basket dropped when At Rim is one),
  each with possessions, PPP and rank on the board, as of the exports' date. Every edition; a board lists only the
  players it qualified, so a player on none gets no sentence.
- Synergy edition's key numbers (generate_opponent_report.syn_key_numbers, its own page right before the player profiles): highlighted boxes
  for the team's offense (most-used play type, best / worst rated, little P&R, three-point %, share of jumpers that are
  threes, at-rim / catch-and-shoot / off-dribble PPS, turnovers, after timeouts), defense (half court, transition and
  press-to-transition, after timeouts, at-rim allowed, best / worst defended) and each player with a Synergy page
  (archetype, top play type, overall PPP, threes, spot-up drives, at-rim, defense PPP and his weakest defensive play
  type: the most points per possession allowed, 2+ possessions). Numbers only; ratings marked
  green (Excellent / Very Good) or red (Below Average / Poor). Needs the team export's overall situations and shot types.
- Matchup Suggestions (generate_opponent_report.page_matchups): ON HOLD (11/12) until more games and Moorpark's Synergy
  defense pages; not in the report. Rebuild with hard size / position eligibility and box-score archetypes before using.
  Design so far:
  Moorpark's rotation defenders against their top 9 by minutes. What each player runs: his Synergy play types (spot-up /
  off screen / handoff = spot; P&R handler / iso = pnr; post-up = post; cut / roll / putback = rim), else his labels.
  Each defender's PPP allowed on those actions from the Synergy player-defense boards (Spot Up, P&R Ball Handler, Post-Up,
  else Overall), blended toward the board's average by MATCH_K = 10 possessions; size: +0.06 per inch beyond 2 he gives up,
  weighted by post / rim share (small guards off post scorers), small penalty for a much bigger defender on a perimeter
  player. One assignment per player, each defender used at most twice (_assign: exact lowest total, a second use costs
  0.05); three options each (the assigned one, then the next two), each with + why / − why not in numbers: PPP
  allowed on his actions vs the state, sample size, missing data, size gap, fouls per 40, steal rate. Suggestions by design (Keys-like); defenders without Synergy defense get
  the state average (listed under the table). Send Moorpark players' Synergy defense pages to sharpen it.
- Finisher (both label copies): Synergy decides when it has 10+ of his shots at the rim (At Rim leaderboard, else a
  player page's shot types): half his shots at the rim, made at the state's at-rim FG% or better (the leaderboard's
  pool; 58.0% on 11/11). Otherwise the play-by-play (export_ratings.rim_shots: layups, dunks, tip-ins of his FGA, 40%+:
  scorekeepers log some layups as jump shots, 11/11: Elijah Wade 88% at the rim by Synergy, 42% by the play-by-play)
  with threes under 20% and TS 58%+; with neither, the box score (threes under 20%, TS 58%+). Shots: 10+, 40 by game
  28 (scaled like Non-shooter's threes). Rows carry rim {src syn/pbp, m, a, share, lg, asof}.
- More Synergy in the labels (both copies; export_ratings.syn_boards loads every leaderboard once, each player's
  percentile among the board's qualified players, SYN_MIN):
  Attackable / Lockdown: Overall Player Defensive (else his Defense tab's ppp_rank), 15+ possessions, points allowed
  per possession bottom / top 25% (row sd). Drives left / Drives right: player pages' drive direction, 10+ drives left
  or right (straight ones not counted), 65%+ one way (row drv). The composites' Synergy factors (syn_rim / syn_three /
  syn_cs / syn_pull) come from the At Rim / Long 3 / Catch and Shoot / Dribble Jumpers leaderboards' PPP percentiles
  when a player page has none, and the why lines' "Synergy:" shooting from them (row syn). All Poss + Assists (row
  sa, 20+): its Ast/TO is Floor general's ball security (not bottom 30%) and its numbers go in the why line; the assist
  rate still decides Passer / Floor general (Synergy's assist share of his own possessions + assists rewards
  low-usage players: 11/11 a 3.3 ARate player topped it).
- A box score side whose players all have 0 in every stat (minutes aside) didn't post: the game stays PARTIAL / NO_BOX
  and on the missing list (scrape.classify_box). A game with one side posted still shows its box score on the
  leaderboard: that side's table, "hasn't posted" for the other, and the rates that need the other side (DRtg, OR%,
  DR%, Stl%, Blk%) blank (build_game_boxes "miss").
- Conference table (Misc -> Conferences, slRenderConf): besides the scope's combined Net, Top 3 (the average current
  net rating of the conference's three best teams, whichever they are) and Avg Net (every member's current net),
  each with its rank among the conferences.
- Opponent schedules in the possession tracker (Rosters -> Schedule): export_ratings.team_schedule puts each team file's
  "schedule": every game on the typed-in schedule (date, opponent, H/A/N, time, event, conference), played ones with the
  result, plus played TBA games. Each played game carries the leaderboard's own box score record (build_game_boxes:
  rows packed in BX_COLS order, halves, win-probability data) and its FanMatch line; ratings.json "box" has the color
  scales (box_ctx: the page's __bxScales, set by generate_leaderboard before export) and school colors. The tracker lists
  the games (schedTable; the next one highlighted) and a tap opens the leaderboard's box score itself: its CSS, popup and
  JS (__bxTeamTable, __bxWpChart, renderBoxScore...) copied from the built page, only the data hooks pointed at the
  tracker (BX_CTX). Change the box score's design in generate_leaderboard.py, then copy the block again.
- Team Stats (leaderboard and tracker) for teams without reliable minutes: eFG%, TS%, TO rate and FT rate need no
  minutes, so they show exact (no "est"); FT rate from FTA / FGA when the analytics have none.
- FT rate leaderboard: 4+ shots a game (FTR_FGA_PG_MIN) and the season's games minimum, on both qualifying paths (1
  FGA and 7 FTA made a 700 leader).
- Moorpark roster changes that reach every device: game tracker REMOVED / JERSEY (lockRoster adds a locked player a
  device lacks); possession tracker OFF_ROSTER / ADD_ROSTER (rosterFix). 11/11/2026: Jack Johnson off (redshirt),
  Jeremiah White on (6'0" G, number to come: set it in JERSEY and ADD_ROSTER).
- Possession tracker saved opponent rosters are found under any of a team's names (oppFind: exact name first, else
  the same leaderboard team): the Rosters picker shows the leaderboard's name ("East Los Angeles") while a tournament
  field saves the roster under its short one ("East LA"); 11/11 ELAC showed an empty roster on the iPad.
  A team picked with no saved players gets its published roster then (pubRosters also re-applies to an empty one).
  Fill from leaderboard takes the published roster (number, name, position, height, year) plus anyone in the box scores
  it lacks, fills blanks only (typed labels kept) and saves at once, so the labels from stats show.
- Who gets stat labels (both label copies): a player who plays 30%+ of the minutes (reliable minutes) or scores 4+ /
  rebounds 3+ a game over half the team's games, on any team (11/11: Saddleback's Dylan Gomez, 6.4 pts/g, 50% from three
  at 29.0% of the minutes, had none). Go-to (usage over 28%) still needs 30%+ of the minutes where minutes are reliable: a
  bench stint's usage isn't go-to.
- Three-point calls (both label copies, SH3): Shooter / Avg 3PT / Poor 3PT read his 3P% pulled toward the state's 32.4% by
  25 attempts, and need 10+ threes (MIN_CALL): on fewer the estimate is mostly the state's average (11/11: Jaison Joyce,
  1 of 5, read Avg 3PT; 83 calls on under 10 attempts dropped). Non-shooter is unchanged.
- Star label (export_ratings.tiers, both label copies): the top 20 by PORPAGATU!; a fake-minutes player is placed by
  his PORPAGATU! (est) (porp_est, rank pest / eqr; Game Score a game only without an estimate).
- A team with no opponent box score yet (only its own side posted) has no opponent defensive rebounds: its offensive
  rebound rate read 100%, so no missed shot ended a possession (11/11 De Anza ORtg (est) 179-373, four De Anza Stars).
  update_advanced_analytics assumes ASSUMED_ORB = 30% for the players' possessions then (De Anza, Hartnell on 11/11).
- Synergy Archetype (scouting reports' player cards, synergy edition; synergy_roles.role, used by generate_opponent_report,
  generate_moorpark_scouting_report and generate_scouting_report): one role per player from his player page's play-type
  mix, modeled on a published NBA role framework: guards / wings Primary Ball Handler, Secondary Ball Handler, Shot
  Creator, Slasher, Athletic Finisher, Off Screen Shooter, Movement Shooter, Stationary Shooter; bigs Versatile Big, Post
  Scorer, Stretch Big, Roll & Cut Big. Each role is a typical mix (PROFILES) plus hard gates (Primary: P&R 22%+ and assist
  rate 18+, and it beats Secondary; Shot Creator: isolation over P&R; Post Scorer: post-ups his top half-court play;
  Versatile Big needs some spot-ups...); the closest allowed mix wins. Big or not: box-score position, else the roster's
  listed one, else the mix. It replaced the old Synergy Archetype rules (11/11: guards called Secondary Ball Handler for
  being combo guards). The bball-index Archetype line stays as it was (bball_index_archetype, its own rules) under it.
  Shoot or drive (Slasher vs shooters, synergy_roles.page_inputs): 3PA rate (box score, 10+ FGA), drive rate (player
  page drives / its total possessions; 2026-27 pages) and the spot-up split (player page "spot_up": {"drive_pct": share
  of his spot-ups that are drives}; record it when a player page comes in). 3PA rate 25% or less with 45%+ of shots at
  the rim or 30%+ drives, or spot-ups 50%+ drives, make him a Slasher candidate and rule out the three shooter roles;
  the shooter roles also need a 3PA rate of 30%+ when known.
  Who creates the shot (pbp_creation.py, 2026-27 play-by-play: each made shot assisted or not, by zone; putbacks 3 s
  after an offensive rebound; transition 8 s after a defensive rebound / steal / turnover): Primary Ball Handler and
  Shot Creator need 55%+ of his makes unassisted (10+ makes), the shooter roles and Stretch Big 70%+ of his made threes
  assisted (5+); the state: 48.5% of makes assisted, 83% of threes, 39% at the rim. Not used for finishers (their
  putbacks are unassisted rim makes and the play-by-play misses most putbacks: 4% of shots). A role a check rules out
  stays out even when no gate passes (_vetoed). The report's Synergy box shows the counts (creation_line).
- Possession tracker VERSION (poss/index.html): raise it with every tracker change. The iPad offers Update only when
  the site's VERSION is newer than its own (checkUpdate).
- Possession tracker Sub screen (subSide): on the floor, the five who were on when it opened stay green; players just
  put on from the bench are yellow with "↑ COMING IN" (.sub-p.in.new), so after adding two (seven on) it's clear who
  is new and which of the original five are still on.
- Possession tracker technicals (techModal): on a player (his foul + team foul), the team / bench (team foul only,
  e.bench) or the coach (no foul); 2, 1 (Class B) or no free throws; Double technical logs one on each team, linked
  by e.dbl, no free throws (the Moorpark player required, the opponent's optional).
- Possession tracker stat sheet photo (readSheetPhoto / parseSheet, Tesseract on the iPad): the photo is scaled to
  2600px wide, its light evened out (shFlatten, not-paper blanked), deskewed, the paper's bend straightened
  (shDewarp: text rows traced and fitted), the table rules erased (shUnrule); a first pass reads the page, then
  (shGrid) each number column is cut out and read on its own, digits and dashes only, and each table's name column is
  levelled and read on its own (a photo at an angle tilts it most). Rows are traced across the columns; names are
  chained left to right and matched to rows with a per-table shift; confident first-pass numbers fill gaps. The three
  made-attempted columns are the most-dashed (two numbers in one = a pair that lost its dash); a column under two
  header names is split (PF / PTS run together at a bent corner). A header read in full is the layout; columns are
  placed by position (shAssignX) when a row's count is off; 3PA never above FGA; a nameless row of numbers after the
  players is the totals line; minutes add up within 2 (the printout rounds). Tested on the 11/2 Antelope Valley
  photos: halftime (curved) 7 of 323 cells wrong, final (at an angle) 19 of 336, every miss caught by an add-up
  check (old reader: 278 of 323); a flat printout 0. ~12 s in desktop Chrome.
  Check screen: ✎ on each row (and the totals; also "Retype the whole row" in Clarify) retypes a row as one line in the
  sheet's order, REB optional ("4 0-4 0-2 0-0 0 1 1 0 0 0 0 1 0"): for numbers put in the wrong boxes (a dash added
  or lost shifts the whole row). Checked as typed (count, dashes only in made-attempted, REB = OREB + DREB, points).
  Screenshots of the box score page (with Wi-Fi) work too: pick several at once (both teams, scrolled, overlaps fine);
  they're read in order and put together (sheetRead: a screenshot starting mid-box carries on the box before it; a
  team's box shown again is merged, a row shown twice counts once; Clarify crops each row from its own screenshot).
  Tested on a 11/2 iPad screenshot: Moorpark's 12 players and TOTALS all right, also split in two overlapping shots.
  The website's live stats view works too (# PLAYER MIN FG FG% 3PT 3PT% FT FT% R OR DR A TO BLK STL F PTS, "2 - 6"
  spaced, header in light text on a dark bar, team name in big type above each table, no TOTALS): a screenshot (a
  quarter pure white and its other colours mostly flat: a photo under bright lights is pure white too, but grainy) skips deskew / straightening / evening out, gets its dark header bars flipped (shUnbar; never on a
  photo: shadowed paper is dark too), and keeps the whole-page read or the column pass, whichever has more rows that add
  up; the % columns are skipped; a big-type heading after a table's players starts the next team; jersey numbers come
  from the game's rosters by name ("11" read "1"). A row on the other team's roster and not its own table's team's moves there
  (sheetTeams; two teams read as one table: 11/3 San Bernardino Valley's players all landed in Moorpark's). Names
  match by last name (5+ letters may be one letter off) and first initial.
  Buttons: "📷 Printout photo (both teams)", "📱 Moorpark screenshots", "📱 <opponent> screenshots" (pick screen), and
  "📱 Add / Replace with screenshots" on each team on the check screen: a team's button makes every table read that
  team's (sheetRead(files, team) / sheetTeams(g, secs, only)), keeping the other team's numbers; Clarify crops each
  team's rows from its own screenshots (T.canvases). The site's menu / cookie banner aren't team names. Tested on the
  11/2 Antelope Valley-San Diego Miramar halftime screenshots: 0 of 286 cells wrong.
  A sheet photographed on a wood floor (11/4 Palomar halftime: 246 of 271 cells wrong -> 3): the grain beside the sheet
  reads as junk before the jersey number ("pe 3 3 Eric Kubel"), so a line that doesn't start "number Name" starts at the
  number before its first capitalised name word (parseSheet and shGrid); a rebuilt row takes one name chain plus any
  scraps; a title may start with a stray mark ("~ Moorpark 43 + 0-2").
- Conference awards and All-Conference (attach_badges, conference-only stats: conf_players / conf_teams; none for a
  conference until it plays conference games): per conference a Player of the Year (conference PRPG! z + team
  conference net z, half each), Offensive POY (conference points a game), Defensive POY (steals, blocks, half
  defensive rebounds a game, minus individual DRtg, minus 1.5 x team DRtg z) and Sixth Man (35% or fewer of his games
  started, by the POY rating), the POY left out of the other three; named with CONF_ABBR (WSC North, PCAC, OEC, ...),
  badge [code, 3, est, abbr]. All-Conference first team (Gold) / second team (Silver, honorable mention rolled in) by
  conference place: 4/3/3/2/2/1 and 3/2/2/1/1/1/0 (five real 2025-26 conferences: 136 picks for 132, 49 of 67
  first-teamers right). Tested on the real 2025-26 awards: POY right in 3 of 4, OPOY 1 of
  2, DPOY 0 of 3 (the real winners rank 4th-8th).
- Player badges (every season, each ranked within its own season; generate_leaderboard.attach_badges / _badge_values / _hof_bars, page: BADGES /
  __bdgIcons / __ppBadges / ppBadgeGuide): what a player does best this season, statewide. Four levels: Bronze, Silver
  and Gold rank this season (skills: top 15% / 7% / 3% of qualified players; rank badges: top 50 / 25 / 10); Hall of
  Fame is the all-time top HOF_SHARE = 3% for that badge, every season since 2017-18 pooled as one pool
  (real-minutes, qualified, HOF_MIN_GP = 20+ games); any season that clears that pooled bar earns it, whatever its rank
  within its own season. Indispensable needs 4+ players on the team with positive
  win shares. Skills: Volume
  Scorer (PPG), Sniper (3P%, 2+ 3PA/g, pulled toward the state 3P% by 25 attempts), Finisher (2P%, 3+ 2PA/g, 25), Ice
  Water (FT%, 2+ FTA/g, 20), Floor General (z ARate - half z TO%), Glass Cleaner (OR% and DR%), Pickpocket (Stl%), Rim
  Protector (Blk%), Green Light (%Shots: his share of the team's shots while on the floor; fake-minutes
  stand-in FGA a game). Ratings (the PRPG! + BPM blend: z-scores among the season's real-minutes qualified players, half each; PRPG!
  alone without a BPM; a fake-minutes player's Game Score placed on PRPG!): All-State in the CCCMBCA's shape (2025-26:
  24 first team, 14 honorable mention) = Gold 24 (each conference's best, then the best of the rest), Silver the next
  14, no Bronze; Player of the Year North / South (the best in each region); All-Conference by the conference
  standings (_conf_places: overall win % then net until every team has 3 conference games, then conference win %),
  first team Gold 4 / 3 / 3 / 2 / 2 / 1 by place, second team Silver 2 / 2 / 1 / 1 / 1 / 1 / 0, honorable mention Bronze
  2 / 1 / 1 / 1 / 1 / 0 (fitted on the real 2025-26 WSC North, PCAC, Orange Empire and Inland Empire teams: 111 picks
  for their 109, 78 real honorees, 36 of 50 first-teamers right; a Gold All-State fills the spot but shows All-State); Offensive Engine / Defensive Anchor by OBPM / DBPM (not a Gold All-State). The All-State / All-Conference rating also
  counts the team's net rating (ALL_STATE_TEAM_W = 0.4), and a fake-minutes player gets the PRPG! at his Game Score
  percentile among fake-minutes players: tested on the real 2025-26 team, 20 of our 38 were real selections (11 of our
  24 Gold on the real first team), 13 of ours from fake-minutes teams against the real 12. Roles: Indispensable (share of the team's win shares), Glue Guy (the Glue guy label: three of the five
  Bronze, four Silver, five Gold; HoF the all-time top 3% of glue seasons: average pooled
  percentile of the five rates, among under-17%-usage seasons). Fake-minutes teams: box-score stand-ins placed
  on the real scales by percentile, marked est., no Hall of Fame; their players qualify with half the team's games
  and 4+ ppg or 3+ rpg. Tables show Gold and HoF emoji after the name (playerLink); player pages every level as
  hexagons, with the guide. The badge block sits before the first table render (var, not const).
- Box score colors: the rate and analytics columns (ORtg, eFG, TS%, OR%, DR%, A%, TO%, Stl%, Blk%, BPM, OBPM,
  DBPM) color their text only (not the cell) against the season's qualified players: average in the normal text
  color, 2 standard deviations better full green, worse full red (TO% reversed); the totals row against the teams.
  Usage and the counting stats stay plain, and so do short stints (9 minutes or fewer when minutes are tracked).
- Player nicknames in parentheses ("#2 Roderick (Quick) Johnson", "JOHNSON,RODERICK (QUICK)") are dropped when a
  box score is saved (scrape.drop_nicknames: the box, its period boxes and its plays).
- Names the stats site spells wrong are fixed at the same step: ccc_config.PLAYER_NAME_FIXES (Matthew Wilson ->
  Mathew Wilson, WILSON,MATTHEW -> WILSON,MATHEW). Add a pair there for any other; the possession tracker has its own
  NAME_FIX (poss/index.html) that renames its stored games, roster and incoming files. The practice tracker and game
  tracker keep their own spelling (their data on the iPad is keyed by name).
- Starters-at-40 / bench-at-0 box scores (the minutes add up to 200 but bench players with stats show 0: 11/6 Santa Ana
  at Los Angeles City): box_minutes.py rebuilds the minutes from the game's play-by-play (compute_pbp_lineups.game_units'
  stints, each player's share of the 40 minutes, whole minutes adding up to 200 / +25 an OT). scrape.save_box runs it
  as each box score is saved; the box keeps the scorekeeper's number as "min_box" and minutes_quality says PBP
  (counted as real). Only when the play-by-play places 75%+ of the game and every player with a stat was on the floor;
  otherwise the side stays BENCH_ZERO (minutes_report: wrong total). Saved box scores: python3 box_minutes.py
  [--dry-run], then python3 scrape.py rebuild (no site requests). 2026-27 through 11/7: 6 such sides, 5 fixed (10/31
  Bakersfield has no play-by-play).
- ORtg (est) for teams without reliable minutes (placeholder / no minutes in their box scores): minutes enter Dean
  Oliver's individual ORtg only through qAST, so update_advanced_analytics writes ind_ortg_est / pprod_est / scposs_est
  for every player with his minutes estimated as his share of the team's activity (FGA, .44 FTA, TO, AST, OREB, DREB,
  PF, STL, BLK) of the team's player-minutes. 2025-26 real-minutes teams (254 players, 100+ FGA): 0.1 ORtg points off
  on average, 0.3 for 90%, 1.1 at most. Shown marked "est" where the real ORtg isn't (adv 0 teams): the leaderboard's
  Team Stats (ortg_est on roster rows, a note above the table) and player pages, the tracker's Team Stats table,
  the scouting report's player cards (BOX_ONLY). Usage, rebound / assist / steal / block % and per-40 stay blank
  (they really are per-minute). Not in the individual ORtg leaderboard's KenPom view (it ranks within %Poss bands);
  its "3 tiers (all teams)" toggle (ortgView) ranks everyone in Primary / Rotation / Limited (over 24 / 16-24 / under
  16% usage): real-minutes players by ORtg and usage, the others by ORtg (est) and role (est), marked est, qualifying
  with half their team's games and 4+ ppg or 3+ rpg.
  Box scores too (build_game_boxes, _box_ortg_est): a side with placeholder minutes and its turnovers recorded gets
  ORtg (est) per game (row ortg_e, shown marked "est", a note under the box): the same activity share of the game's
  player-minutes (the other side's real minutes, so an overtime counts, else 40); halves as well. TO% needs no minutes
  and always shows. A side whose box has no turnovers (0 for everyone) shows no ORtg / usage / TO%, real or est.
- Box score fixes typed in by hand keep where they came from in the box ("to_source"): 11/9 Redwoods at Cuesta,
  Cuesta's turnovers (the site posted 0) from Synergy's player box. Rebuild the two teams after such a fix:
  python3 generate_team_stats.py --season 2026-27 --teams A B, then update_advanced_analytics.py --teams A B.
  Alongside it for the same players: TORate (est) (the TO% itself, needs no minutes: tov_est), a 3-tier role (est)
  in place of %Poss (role_est: Primary over 24% usage, Rotation 16-24, Limited under 16; KenPom's 6 bands are not
  shown for estimates) and PRPG! (est) (porp_est). The role and PRPG! use a minutes estimate inside the sums only,
  never shown: update_advanced_analytics.MIN_EST_W, a regression of %Min on starts a game (generate_team_stats now
  counts GS), possession share (TotPoss / team possessions in his games, exactly minute-free), per-game box stats
  and activity share, fitted on 2022-23 to 2025-26 real-minutes players (%Min 4.6 off; the right tier 79-83%). usage_est
  = season possession share / %Min est (%Min is of the whole season: the share in his games alone inflated anyone who
  missed games). attach_porpagatu runs the real formula on ORtg (est), usage_est and min_pct_est for players
  without a real PRPG!: 0.07 off on 2022-23 to 2025-26, 23-24 of the top 24 the same each season. All-State / All-Conference use porp_est for
  fake-minutes players (the Game Score stand-in stays for seasons without it). Shown on the leaderboard's Team Stats
  and player pages, the tracker's Team Stats table and the scouting report's player cards (role and TO% est).
- Box score win-probability chart (2026-27 games with play-by-play, Final view), Torvik-style: the winner's chance
  from the lead, time left and the pregame expected margin (the game's FanMatch row: pregame nets + 3 home court),
  the score margin dotted on the right axis, a dot per play (shots, free throws, turnovers) in the team's color
  (filled made, open missed / turnover) with time, player and play on hover, a ring where it reached 99% for good.
  build_game_boxes stores "wp" [visitor, periods, plays string, visitor players, home players] (_wp_events); the
  page rebuilds the curve (__bxWpChart). The Min WP / Excitement / Tension tabs stay KenPom's (teams equal). The box
  score's tables are unchanged. Past seasons: no chart.
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
- One team's box score only (the other side posted nothing, or fake minutes): update_advanced_analytics takes the
  posted side's possessions for both teams and the final score for each, so both get that game's ORtg / DRtg / net
  (four factors need both sides: those skip it). Fake (placeholder) minutes don't affect possessions; the game
  counts as 40 minutes.
- Box-score rate stats (Databallr's glossary; boxRate in the page, from each player's season totals, every season):
  rTS% (TS% minus the league's), TSAdd/100 (points above a league-average shooter on the same shots per 100
  possessions on the floor), 3P rTS% (1.5 x 3P% minus the league's), 3PR (3PA/FGA), SHOTS/100, STL/100, BLK/100.
  Possessions on the floor = team possessions a game x his minutes / 40 x games (needs real minutes). Shown as
  Individual Stats -> Advanced buttons (qualifying like their base stat: TS%, 3P%, Stl%/Blk%), chart axes, and a
  Shooting & Defense Rates card on player pages (value + statewide rank).
- Forfeits: ccc_config.FORFEITS lists (date, winner, loser). The game's stats stay (players, team totals, PPG, and
  ORtg / DRtg / net from the score on the court); its result is a 2-0 forfeit everywhere a result shows (record, game
  log, team schedules, FanMatch, WAB, quads). generate_team_stats.py writes team_score / opponent_score 2-0 and
  court_score (the real one) into the game log; the ratings and points read court_score. A forfeit is left out of the
  ranked game lists (Upsets, Busts, Dominance, Tension, the play-by-play tabs). 10/29: LA Southwest (won 85-82) forfeited
  to Desert.
- Early-season minimums (2026-27; past seasons keep the full-season numbers): a full season's bar is pro-rated to
  the games so far (of a 28-game season). Charts and the individual leaderboard's rate stats: 20 GP -> 20/28 of
  the player's team's games (seasonGpMin). Players' minutes-based stats (ORtg, usage, rebound %, PER, WS...): a
  team needs 18 clean games -> 18/28 of its games (_adv_clean_needed). BPM (compute_ccc_bpm.py): 18 team / 5
  player games -> 18/28 and 5/28 of the most games any team has played. Records always show a Conference line
  (0-0 before conference play).
- Records (2026-27): typed-in schedules have none (or a preseason 0-0), so generate_team_stats.py counts them from
  the games played ("Overall (.500)": "1-1", "Conference ..."); past seasons keep the site's.
- A box score page with no teams / players (stats not up yet, or the site sent something else) is not filed as a
  game; its link is read again next run, and the page is kept as served in scrape_state/<season>/unreadable/ (local,
  gitignored) to diagnose. 10/29: Riverside-West LA and Canyons-Cuyamaca came back empty at 10:02 / 10:07 PM and were
  filed as one "Visitor vs Home" game, which hid both links (fixed: State drops such games when it loads).
- Night log: every scrape run writes scrape_state/<season>/logs/<date>_<time>_<command>.md (pushed with the run):
  the composite pages read, every game it looked at and its outcome, and for each failure why: when and how the page
  was read (browser / script, HTTP status) and what it held (bytes, title, teams, final score, stats-box tables,
  player rows, any "live stats" / "not available" text), plus where the page was kept on the PC (unreadable/). A box
  score page with no stats is read again on the same browser page after 4s and 8s more (no new request), then fetched
  once more at the end of the run (a minute or more later); both show in the log. 10/30 El Camino-Santa Barbara and
  10/29 Riverside-West LA / Canyons-Cuyamaca came back without stats though they were posted.
- The nightly also re-reads the night before's composite page when that night left games without a box score (late
  games post after the run): one more page, only then.
- Python on the PC runs in UTF-8 (PYTHONUTF8 in the .bat files and for every script scrape.py starts); the site has
  a .nojekyll (GitHub Pages serves the files as they are, no Jekyll build to break on a file's encoding).
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
  night one. Home court in a game's odds matches the ratings (3.0 per 100 in all, a quarter on each side's ORtg
  and DRtg; calculate_wab.wab_hca); earlier seasons keep the old 2.2 on each of the four (8.8 in all) so their published
  WAB holds. WAB is recomputed from scratch every night, so every game is re-graded as the ratings move off last season. Earlier seasons keep the raw per-game method (published WAB unchanged). Scouting reports read the
  season's own wab_results_<season>.json.
- SOS / NCSOS (2026-27 on): KenPom's - the plain average of the opponents' current net ratings over the games played
  (NCSOS: non-conference games). Last season enters only through the opponents' own ratings (their prior); a team
  with no games is 0.0 (SOS, NCSOS, Opp ORtg / DRtg build up as games are played). Earlier seasons keep WIN50 (compute_sos kenpom=False).
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
- FanMatch's played games (2026-27 on): the pregame nets, expected margin and win probability come from
  opponent-adjusted ratings as of each game's date (_sl_adjusted_pregame: KenPom-style, last season's final ratings
  regressed 30% as 3 games), not the running ratings the older seasons keep. Backtest (2024-25, 2025-26): 78-79% of
  winners, 9.7-9.8 pts off the margin vs 76-78% / 10.8-11.3; Torvik-style recency / blowout weighting didn't help.
  Feeds Upsets, Busts and the box score chart's pregame odds.
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
  iPhone / iPad portrait (up to 1024 px wide): the sidebar is a slide-out drawer behind a top bar (☰, toggleNav; the bar
  names the section showing), the main tables pin the name column while the stats scroll, and wide tables / panels
  scroll inside the page (no sideways page scroll on any section at 320-1280 px). iPad landscape and PC keep the
  fixed sidebar. The mobile CSS is the last block of the page's first <style>.
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
