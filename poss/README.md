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
  (the first of two FTs, out of bounds, end of the half), tap **No rebound** (it reads "No rebound (1st of 2)"
  after a missed FT), or just tap the next stat.
- **Fouls go to the player:** tap Foul, Charge or Off Foul, then his card. "Team / bench foul" is
  for a foul with no player.
- **Foul trouble** lights the cards: 1st half, 2 fouls yellow, 3–4 red; 2nd half / OT, 3 yellow, 4 red; 5
  fouls (or 2 technicals) = OUT (red, name struck through).
- **Fouled out:** the 5th foul (or 2nd technical) opens the sub screen straight away, with no Cancel; it
  stays up (even after a reload) until a replacement is picked. He can't be put back in. **Edit his
  fouls** on that screen lists each one (period, score): **Wrong player** moves it to the right player,
  **Delete** removes it. Back to 4 and he stays in.
- **🚩 Flag last play** (under the buttons), or the 🚩 on any feed / Play-by-Play line, marks a play to look
  at later. Flagged plays are highlighted, marked on the Sheet, and listed under Play-by-Play → Flagged.
- **Tech:** pick team, player or coach, and how many of the two free throws went in.
  - On a player it is his foul and a team foul.
  - On a coach it is neither. A second on the same coach flags the ejection.
  - The free throws count in the score, PPP and +/-, but are not a possession.
- **Timeout:** pick the team, full or 30, and type the **game clock** (time left in the half: 742 or 7:42), then
  **Log timeout → Huddle**; **Skip clock** if you don't have it. The clock shows in the Huddle header, the feed and
  Play-by-Play (tap the timeout line to fix it). Each clock is a checkpoint: from then on leverage, clutch and garbage
  time use the real time left (that clock, less the possessions since at this half's pace) instead of the estimate
  from possessions, and late and close leads the Huddle ("Clutch: up 2 with 0:50 left"). 4 full + 2 thirty-second a team, +1 thirty per OT (full = rectangles, 30s = dots). **± Fouls / TOs** fixes the counts.
- **No clock.**
- **Possession pill** (under the period; the pill fits its text, and the middle of the scoreboard is sized to this
  game's longest label: wider for a long opponent name like Mack Attack Prep, compact for Cuesta, the same all game,
  so changing the ball never moves the logos): moves only when you tap it — at the tip, at the start of the
  2nd half, after a jump ball. Plays, subs and timeouts never move it. Tapped mid-half it asks: **Held
  ball: steal** (a steal for the team that gets the ball, ending the other team's possession; shown as "steal (held ball)") or **Just switch**.
- **Huddle** opens after every timeout (and from **📋 Huddle** on the scoreboard), the game tracker's
  timeout sheet by possessions:
  - the score, fouls and timeouts left; up to four talk points (turnovers and the points off them,
    offensive boards, their scoring rate, runs, empty trips, stops in a row, bonus, foul trouble);
  - the **last 20 possessions** (both teams; Moorpark's tempo the last 5 seasons averages 78.7 a team per 40:00, so 5:00 is ~10 a team) against the whole game: PPP, eFG%, TO%,
    OREB%, DREB%, FT rate, 3PA rate, highlighted ▲▼ when one has moved well away on enough tries;
  - momentum: current run, stops in a row, kills this half;
  - both fives on the floor: fouls (foul-trouble colours), +/-, notes, and the five's ratings.
  - Tap a row to mark it yellow.

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
⇄ Sub sets both teams' fives on one screen: each team's **On the floor** five on top, one per line in number order, the **Bench** (two across)
below. Tap a player on the floor to take him out, tap a bench player to put him in. The starting fives are asked for when a game starts
and at each new period. The opponent's roster comes from the game tracker; edit it with Roster on
the live screen (numbers are enough).

The player cards show each player's fouls and his on-floor **+/-**. The live screen's lineup cards
show the current five for each team: possessions, ORtg, DRtg, net and +/-.

**Their best five (2nd half and OT only):** the opponent five with the best net rating so far, among
fives with 8+ possessions. When it is on the floor a ★ **Their best five is on** tag (net, possessions)
shows at the top of their column and on their lineup card, and a sub that puts it back on pops a note.

**Lineups tab**, for the game or the current period, for both teams, as **5-man, 4-man, 3-man or 2-man**
combos (a combo is on the floor for every possession of every five that contains it). For each:
- possessions, points for–against, +/-, ORtg, DRtg, net;
- offense: eFG%, TO% (per actual possession), OREB%, FT rate;
- defense: the opponent's eFG%, TO% and FT rate, DREB%, and **STOPS**: the opponent's possessions that
  ended with no points while that unit was on (missed free throws don't count, as with kills), with the
  stop % (stops per defensive possession) under it. Kills can run across lineups; stops belong to the
  unit that got them. Sort by STOPS to see who gets the most;
- tap a row to see how its possessions ended at each end.

Tap any column header to sort by it (tap again to reverse; DRtg, TO% and the opponent's eFG% / FT
rate start lowest-first). Filter All / Clutch / No garbage time. **Season** adds up Moorpark's lineups and combos from every game tracked on the iPad.

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
- **Halftime stat sheet:** **End 1H** brings up the stat-sheet screen over the halftime report: add a photo of the
  printout if you have it (check / Clarify, then Save), or **Skip → halftime report**.
- **Two reports.** With a stat sheet for that half / the game, the report is the **full report**:
  - **Key takeaways:** our edge and theirs in the four factors, each side's best player, most-used, the
    biggest on/off, the best five, foul trouble, points off turnovers / second-chance points, kills and bench.
  - **Turnovers, forced vs unforced:** steal TO% (the other team's steals per possession) and non-steal TO%
    (travels, bad passes out, charges, offensive fouls, violations: the ones we do to ourselves). The two add up
    to TO%. In the full report's team analytics, its own card in the report without a sheet, under each five's
    TO% on the Lineups tab (NS), and in the Huddle. Not in the Four factors table. When we're losing the turnover
    battle and half or more of ours (3+) weren't steals, that leads Hurting us (theirs lead Helping us when we're winning it).
  - **Who's behind the four factors:** a factor we're losing to them (worse eFG%, TO%, OREB% or FT rate) lists
    its players under **Hurting us**; one we're winning, under **Helping us** — for each stat behind it, the
    player with the biggest share of his team's total (e.g. "#33 Mowers — 25% of their defensive boards
    (4 of 16) · our OREB% 20.0%", "#10 Alhammouri — 67% of their steals"). Shooting names the fewest players
    who make up half of the team's missed shots (or field-goal points), most first, e.g. "Kubel 0-5, Castaniero
    2-6, Finney 1-4 — 60% of our missed shots between them (12 of 20)". Rebounds the same way (half of the team's
    offensive / defensive boards, once there are at least 4 offensive / 6 defensive boards). Named only at 25%+ of the total and at least 2 (3 for
    defensive boards).
  - **Team:** four factors; team analytics (points, tracked possessions and PPP, sheet ORtg, points off
    turnovers, second-chance points, bench points, eFG%, TS%, 3P%, 3PA rate, FT% and rate, TO%, OREB%,
    assisted %, AST/TO, STL%, BLK%, kills, fouls); by half (post-game, when the halftime sheet was read too);
    stops, kills & killshots.
  - **Players:** the game tracker's box score for both teams, filled from the sheet: starters, then BENCH;
    MIN, MIN%, ORTG, USG, SHOT%, EFG, TS%, FTR, OR%, DR%, AST%, TO%, STL%, BLK%, 2PT, 3PT, FT, OR, DR, REB, AST,
    TO, STL, BLK, PF, PTS and Moorpark's on-floor +/- from the tracker; the same green / red marks; under 25% of
    the minutes greyed; the TM Team row and a TEAM line. **All players / 25%+ of minutes** hides the greyed
    players (5:00 at the half, 10:00 for the game, plus 25% of each OT). Takeaways always use everyone.
  - **On the floor** (tracker), each team: minutes, possessions on, ORTG / DRTG / net with him on, on/off, +/-,
    defensive stops with him on — best on/off first.
  - **Lineups:** best fives, best combos (post-game), every five for both teams.
  Without a sheet the report is the one below, with an **Add stat sheet** button.
- **Report:** opens by itself: **End 1H** brings up the Halftime report (its **Start 2nd half** button goes
  to the 2nd-half starting fives), and **Final** brings up the Post-game report. Both start with
  **Best lineups**: each team's top 3 fives by net rating, among those with 5+ possessions at the
  half or 8+ for the game. The Post-game report adds **Best combos**: each team's top 2-, 3- and 4-man combos (top 3 of each) and
  by net rating, among those on the floor together for 20+ possessions. Combos that were
  always on together (identical numbers) share one row. **Halftime** and **Post-game** show:
  - the score with each team's possessions, PPP and kills;
  - the period-by-period summary (post-game);
  - four factors;
  - the stops, kills & killshots card (biggest run, most stops in a row, skunks, 10/15/20-0, every
    run of 3+ stops and 10+ points);
  - both teams' lineups;
  - clutch and garbage-time scoring (post-game);
  - Print / PDF.
- **📷 Read stat sheet** (Report and Four factors tabs): take a photo of the halftime or final box score
  printout, both teams in view, flat and straight on. It is read on the iPad, **no internet needed**
  (Tesseract, saved with the app), in a few seconds.
  - Built for the PrestoSports box (Player · MIN · FGM-A · 3PM-A · FTM-A · OREB · DREB · REB · AST · STL · BLK
    · TO · PF · PTS, Starters / Reserves, TM Team, TOTALS). The column order is read off the header line.
  - A tilted photo is straightened first. Common slips (a lost dash in 3-5, a 4 read as "a") are fixed
    from where the number sits in the row.
  - **Check screen**, before anything is saved: every box can be edited.
    - A row turns red when its points don't match FG / 3P / FT.
    - A PTS box turns amber when it was misread and filled in from FG / 3P / FT.
    - The players' sums are checked against the sheet's TOTALS, and minutes against 100 (half) or
      200 (+25 per OT).
    - ⇅ Swap teams if Moorpark landed on the wrong side.
    - **🔎 Clarify iffy numbers (N)** walks you through only the numbers the reader wasn't sure of (under 85%
      confidence, or repaired), one at a time: the strip of the photo with that box circled, under its column
      header, beside the player's name, and a big box to confirm or type over. Numbers the sheet vouches for are
      never asked: a column whose players add up to TOTALS, minutes that add up to 100 / 200, and made shots
      that add up to a row's points. Iffy boxes have a dashed outline on the check screen.
  - **Save → report** adds an **Individual & team advanced** section to the Halftime / Post-game report:
    - talk points (best game score each side, most-used Moorpark player and his TS%, bench points);
    - team: points, possessions, ORtg, eFG%, TS%, assisted %, AST/TO, STL%, BLK%, bench points, fouls;
    - each player: the box, then game score, eFG%, TS%, USG%, AST%, TOV%, OREB%, DREB%, STL%, BLK%,
      plus Moorpark's on-floor +/- from the tracker.
  - The sheet's totals also become the Four factors numbers for that half / the game. **Edit sheet** reopens it.
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
- **Saved reports** (Games tab): a copy of each halftime and post-game report as it was, kept on the iPad apart
  from the game, so it stays even if the game is edited or deleted. They save themselves at **Start 2nd half**,
  at **Final** and whenever a stat sheet is saved; **💾 Save report** on the report saves one any time. One halftime
  and one post-game copy per game (the newest kept). **Open** shows it as saved with Print / PDF; **Delete**
  removes it.

Games are saved on the iPad (localStorage `pt2_games`), and the app works offline once opened.
The page is built from the game tracker's stylesheet, copied into `poss/index.html`. If the game
tracker's look changes, copy its `<style>` block across again.
