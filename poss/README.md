# Possession Tracker

`chadoconnor5.github.io/moorparkmbb/poss/`: possession-by-possession tracking for both teams,
built in the game tracker's design (`/game/`) and for the iPad in portrait. It is a separate app.
It reads the game tracker's Moorpark roster, opponent rosters, schedule and scouting PDFs on the
same iPad, but never writes to them.

## Starting a game
With no game going, the **Live** tab shows the game tracker's New game screen:
- pick the game from the schedule (today's game fills itself in), or type the opponent;
- set the date, site and conference;
- tap Moorpark players to set who is dressed and who starts;
- pick the opponent's roster and, if you like, their starting five;
- pick the scouting report;
- then tap **Create game →**.

Games → **+ New game** brings the screen back. Every tab opens without a game too; the ones that need one say so.

## Logging
- **Team stats:** tap the stat, then a team logo at the top.
  - Shots: 2PT Make / Miss, 3PT Make / Miss, FT Make / Miss.
  - Turnovers: Turnover, Steal. For a steal, tap the team that stole it.
- **Rebounds** have no buttons. After any miss, both logos light up for the rebound: the shooting
  team's logo = offensive rebound, the other logo = defensive rebound. If there was no rebound
  (out of bounds, the first of two FTs), just tap the next stat.
- **Fouls go to the player:** tap Foul, Charge or Off Foul, then his card. "Team / bench foul" is
  for a foul with no player.
- **Tech:** pick team, player or coach, and how many of the two free throws went in.
  - On a player it is his foul and a team foul.
  - On a coach it is neither. A second on the same coach flags the ejection.
  - The free throws count in the score, PPP and +/-, but are not a possession.
- **Timeout:** pick the team, full or 30. 4 full + 2 thirty-second a team, +1 thirty per OT (full = rectangles, 30s = dots). **± Fouls / TOs** fixes the counts.
- **No clock.**

## How possessions are counted
A possession ends three ways:

- **Points:** a made 2 or 3, or the last free throw of a trip.
  - A make followed by free throws from the same team is the and-one; free throws in a row are
    one trip.
  - A trip counts as FT if any went in, ✗FT if none did.
- **Turnover:** Turnover, Steal, Charge, Off Foul.
- **Rebound:** a defensive rebound.

An **offensive rebound** keeps the possession going, after a missed shot or a missed free throw.
A 1-of-2 trip, an offensive rebound and a second shot is all one possession.

The **Poss** number on the scoreboard is the two teams' counts averaged, (Moorpark + opponent) ÷ 2, rounded down to a whole number.
Each team's own count shows under it.

## Leverage, clutch, garbage time (no clock)
The game tracker's rules, with **possessions left** standing in for the clock (possessions left x this
game's seconds per possession; 40:00 / regulation possessions):
- **Leverage:** HIGH within 3 · MEDIUM 4–12 and catchable · LOW 13+, or more than the trailing team
  can close at 3 points a trip on the trips it has left.
- **Clutch:** the last 5:00 of regulation or any overtime, within 5, never LOW.
- **Garbage time:** 30+ any time · 25+ at 8:00 or less · 20+ at 5:00 · 15+ at 3:00 · 10+ at 1:00.
  Sticky from the first possession that meets it, regulation only.

Live, the 2nd half is assumed to run as long as the 1st (a half is ~69 possessions until there is
one), so the band under **Poss** is an estimate. Once the game is **Final** (End 2H → Final, or
start OT) every possession is graded exactly. The Sheet shows the band per row (H / M / L, C =
clutch, GT = garbage) and where garbage time starts. Tap a row to start garbage time there, turn it
off, or put it back to automatic. Lineups can be filtered to Clutch or No garbage time.

## Leaderboard export
Sheet → **⬇ Leaderboard: defense** and **⬇ Leaderboard: offense** download the same CSVs
`defensive_logger.html` wrote (`def_<date>__<opp>__<venue>.csv`, `off_…__OFF.csv`). Drop them in
`Neural Network - Codex Optimized/internal_data/def_logs/`; `compute_moorpark_lineups.py` reads them
unchanged: counted defensive possessions per five, opponent 2P/3P/FT, turnovers, rebounds,
second-chance and points-off-turnover points, and the garbage flag. Points in the paint aren't tracked.
Hudl's per-game lineup export still supplies offense and minutes.

**Kills, skunks, killshots** (the game tracker's rules):
- A **stop** is a finished possession with no points, except one that ended on missed free throws.
  A technical breaks the fouling team's run. The count starts over each half / OT.
- **Kill** = every 3 straight stops (6 = two kills). **Skunk** = the run reaches 6. **Dead skunk** = it
  reaches 9. Counted on top of the kills. The scoreboard shows kills this half, pips toward the next
  kill, and a SKUNK / DEAD SKUNK tag while the run is alive.
- **Killshots:** a run is every point one side scores before the other scores again (technical FTs
  included), across halves. 10-0, 15-0 and 20-0 are counted, nested (a 22-0 is one of each). The
  current run (6+) shows under Poss.
- **Stops in a row** are kept like runs: every run of stops for both teams (same stop rules, restarts
  each half), with the game's longest.
- Sheet → **Stops, kills & killshots**: each team's biggest run, most stops in a row, runs of 3+ stops, kills,
  skunks, dead skunks and 10/15/20-0 runs. Lists every run of 3+ stops (longest first) and every
  10+ scoring run, with the half, the score and Moorpark's five when it started.

## Lineups
⇄ Sub sets both teams' fives on one screen. The starting fives are asked for when a game starts
and at each new period. The opponent's roster comes from the game tracker; edit it with Roster on
the live screen (numbers are enough).

The player cards show each player's fouls and his on-floor **+/-**. The live screen's lineup cards
show the current five for each team: possessions, ORtg, DRtg, net and +/-.

**Lineups tab**, for the game or the current period, for both teams. For every five:
- possessions, points for–against, +/-, ORtg, DRtg, net;
- tap a five to see how its possessions ended at each end.

## Other tabs
- **Play-by-Play:** everything in order by period: each possession with its plays and the score,
  plus fouls, subs, technicals and timeouts. Filter by team. Tap any line to fix it.
- **Schedule:** the game tracker's Schedule tab, same look, same shared schedule.
  - Edit rows, Paste schedule, + Add game, Save schedule.
  - **Start game** opens the New game screen filled in for that row.
  - A tracked game shows its score, Open and Sheet.
- **Rosters:** Moorpark and every opponent: #, name, position, height, year and a **note**.
  - Opponent rosters are shared with the game tracker.
  - Position and the note show on the player's card on the Live screen.
- **Report:** opens by itself: **End 1H** brings up the Halftime report (its **Start 2nd half** button goes
  to the 2nd-half starting fives), and **Final** brings up the Post-game report. Both start with
  **Best lineups**: each team's top 3 fives by net rating, among those with 5+ possessions at the
  half or 8+ for the game. **Halftime** and **Post-game** show:
  - the score with each team's possessions, PPP and kills;
  - the period-by-period summary (post-game);
  - four factors;
  - the stops, kills & killshots card (biggest run, most stops in a row, skunks, 10/15/20-0, every
    run of 3+ stops and 10+ points);
  - both teams' lineups;
  - clutch and garbage-time scoring (post-game);
  - Print / PDF.
- **Sheet:** every possession in order for both teams, with how it ended, offensive rebounds,
  points, kills and the running score. Subs and technicals are shown where they happened.
  - Tap a row to change the stat or team, delete the play, or insert a missed play before it.
  - Summary by period. Print / PDF.
- **Four factors:** worked out from the tracked plays, so nothing needs typing at halftime.
  - Sources: makes and misses, FTs (technical FTs included), the rebound taps, turnovers, steals,
    charges and offensive fouls.
  - Views: 1st half, 2nd half (with OT) and full game.
  - Gives eFG%, TO%, OREB%, DREB%, FT rate, 3PA rate, shooting, possessions and PPP, with the game
    tracker's formulas. No assists.
  - Tap a box to type the official printout's number over a tracked one; **Back to tracked**
    undoes the typed numbers.
- **Scouting:** the scouting PDF. It shares the game tracker's stored PDFs, and the opponent's
  opens first.
- **Games:** new game, open, export / import, delete, the Moorpark roster.

Games are saved on the iPad (localStorage `pt2_games`), and the app works offline once opened.
The page is built from the game tracker's stylesheet, copied into `poss/index.html`. If the game
tracker's look changes, copy its `<style>` block across again.
