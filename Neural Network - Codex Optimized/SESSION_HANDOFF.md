# SESSION HANDOFF — 2026-06-16

## SETUP (read first)
- **Active code:** `/Users/chadoconnor/Neural Network - Codex Optimized/` (NOT the cwd `Neural Network`).
- **Run with `/usr/local/bin/python3`** (3.14 + numpy/sklearn; default python3 is 3.9 and crashes).
- **Build:** `python3 generate_leaderboard.py` → `wsc_north_leaderboard.html` (+ `season_data/*.js`). Builds ~2 min. If `/private/tmp` ENOSPC, `export CLAUDE_CODE_TMPDIR=/tmp`.
- **Deploy BOTH:** `cp wsc_north_leaderboard.html outputs/` (local preview :8742) AND `cp wsc_north_leaderboard.html "/Users/chadoconnor/Documents/Codex/2026-06-06/when-can-i-get-access-to/outputs/wsc_north_leaderboard_optimized.html"`.
- **Preview:** preview_start "leaderboard-preview" → http://localhost:8742/wsc_north_leaderboard.html . NOTE: scrolled screenshots often come back black on this big page — verify via preview_eval DOM reads instead.
- Caching off by default (no stale data). Memory files in the project memory dir hold durable specifics — see [[keys-project]], [[moorpark-lineup-onoff]], [[defensive-logger]], [[moorpark-lineup-game-order]], [[leaderboard-build-and-preview-paths]].

## ⏭ IMMEDIATE NEXT TASK
*(none — garbage-time calculator built this session; see DONE below. Lineup CSVs are **Hudl** exports, NOT Synergy.)*

**QA/next idea still open:** cross-reference logged competitive possessions vs the **Hudl** game-by-game lineup CSV — lineups that only appear in Hudl (never logged) = pure garbage → drop. (Mixed lineups can't be split from Hudl totals alone — hence the re-export path.)

## DONE THIS SESSION
**Logger PARED to lineup-wide only (v9, final state)** — user decided per-player tagging slowed entry too much. Rewrote `defensive_logger.html` clean: removed ALL individual-player pickers (MP defenders/blocker/fouler/rebounder/deflection-credit + every opponent-player picker + OPP_ROSTERS + zone/contest + assister identity). KEPT: 5-on-court w/ per-event lineup stamping (mid-poss subs still attribute right), shot type+result, optional Assisted boolean, foul type+bonus+FTM/FTA, turnover type, OReb/DReb/Deflection bare events, garbage time, tally, log, CSV(23 cols)/JSON, autosave. Old games still load (same localStorage keys). See [[defensive-logger]] "CURRENT STATE (v9)". *(Earlier this session before the pare-down: block-credit field, non-shooting-foul-doesn't-end-possession fix, clearer incomplete-event messages, per-event lineup stamping for sub attribution — the lineup-stamping survived the pare-down, the rest was superseded.)*

**Garbage-time calculator** in `defensive_logger.html` — Score & clock card (Half / mm:ss / MP / Opp), live "% to garbage time" bar via the standard ladder (30+ anytime · 25+ ≤8m · 20+ ≤5m · 15+ ≤3m · 10+ ≤1m, college 2×20m → gameMinRem adds 20 in 1st half). Each possession is **stamped** with a clock snapshot at log time (`p.clk`). **Garbage is a label, NOT a drop** — possessions keep logging with full defensive stats. **Sticky cutoff**: first possession with a garbage snapshot = the cutoff; every possession from there is flagged even if the clock lapses below threshold (`garbageMap` uses `poss>=cutPoss`; `nextPossGarbage()` true once cutoff reached). UI: readout shows "GARBAGE TIME — still logging, flagged" + cutoff line ("re-export Hudl lineups only up to here"), a live "🗑 next poss = GARBAGE" badge by the Log button, garbage rows dimmed w/ 🗑 GT column, tally shows competitive-vs-garbage poss split. CSV gained `half,clock,mp_score,opp_score,lead,garbage` columns. Lineup CSVs are **Hudl**. Ladder math verified in Python + sticky-lock verified live.


**Keys to Victory** (`compute_team_keys.py` + UI, see [[keys-project]]) — EvanMiya replica, light-theme report, Team + Seasons(5yr/cur) + N-targets dropdowns, narrative + targets-hit (w/ Global cols) + Style Metrics. **49 teams** (KEYS_TEAMS list in generate_leaderboard, per-team windows + custom `seasons`; first-year coaches get both dropdown options). **Margin metrics excluded** from keys (KEY_EXCLUDE) — they were tautological win-proxies. Bench% global columns + perf fix (single-pass `load_all_bench_pct`). Nav: Keys toggle is right after Charts.

**Team Charts** — expanded to ~99 box-derived metrics (per-game / opponent / differential / per-100 for every counting stat + FG%/ratios/SOS), generated block after `TEAM_CHART_METRIC_ORDER`.

**Lineups page** (Moorpark-only, [[moorpark-lineup-onoff]]):
- 6 **themed tables** (Overview/Shooting/Offense/Playmaking/Rebounding/Defense) instead of one 30-col scroll; shared context cols (Min/Poss/Net/100/Adj Net/100/ORtg/DRtg); shared sort.
- **Top Lineups** ranked table at top.
- **Opponent adjustment DONE** — 29 per-game CSVs in `internal_data/per_game_lineups/` (+ manifest), KenPom additive (Adj Net = raw + opp Net), `build_moorpark_lineups(opp_ratings=...)`, Adj cols + Opp Net everywhere, `opp_adjusted`=true.
- **5 positional toggles** (next to 2/3/4/5-Man): **PG** (each guard, 1/row) · **Backcourt** (guard trios) · **PG+C** (guard+fwd pairs) · **Frontcourt** (fwd pairs, empty for MP) · **C** (each forward, 1/row). Positions from `internal_data/player_positions_2025_26.csv` (`pos_class`, 8-archetype). Jersey zero-pad fix in `_load_positions`.

**Defensive logger** (`defensive_logger.html`, standalone, [[defensive-logger]]) — multi-event possessions, matchups, pre-loaded MP + opponent rosters (269 players from box scores, injected at `__OPP_ROSTERS__` marker — RE-INJECT from `internal_data/opp_rosters.json` after any HTML rewrite). Shot types Dunk/Close2/Far2/Three; charges; No Defender; Deflection; non-shooting fouls hide opp; **assist = shooter + assister + on-ball defender + assist-allowed defender (4 fields)**; shooting fouls capture **fouler + primary defender**; **Team** option on Def Reb / Opp OReb / TO. Possession endings auto-derived (made_fg/made_ft/dreb/turnover/steal). CSV = 1 row/event. **NEXT = garbage-time calculator (above).**

## STILL NOT BUILT
- Defense tables / defensive opp-adjustment from logged data (logger is data-entry only; CSV schema designed to feed it).
- Garbage-time calculator (the immediate next task).
- Keys/positional rollout beyond current teams.

## KEY FILES
`generate_leaderboard.py` (main build; JS in f-string, `{{ }}` escaping) · `compute_team_keys.py` · `compute_moorpark_lineups.py` · `compute_positions_from_boxscore.py` → `internal_data/player_positions_2025_26.csv` · `defensive_logger.html` · `internal_data/per_game_lineups/` + `opp_rosters.json`.
