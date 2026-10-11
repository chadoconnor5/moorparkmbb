# Moorpark MBB — Live Game Tracker

Live URL (once on `main`): https://chadoconnor5.github.io/moorparkmbb/game/

Built on the practice tracker's engine (event log, lineup stints, stat lines, ratings) with
no film, no shot locations, no shot types and no shot clock.

## Getting it on the iPad (works with no wifi)

1. On the iPad, open the live URL in **Safari** once while online.
2. Share → **Add to Home Screen**. Open it from that icon from now on.
3. Check the pill at the top right says **offline: ready**. From then on it opens and runs
   with wifi and cellular off.
4. Add the scouting report PDF (Scouting tab → Add PDF… or at game setup) while you have the
   file — it is saved on the iPad and opens offline.

Data lives on the device that tracked it (browser storage). **⬇ Backup** (top bar) saves
everything — every game, the roster, opponents and schedule — to one file, and the app does
it on its own when the 1st half ends and when a game is finished, so a lost iPad never costs
a game. On the home-screen app the iPad's Share sheet opens with the file: tap **Save to
Files** (or AirDrop / Mail it). Games → **Import** reads a backup back in. **Publish**
downloads `gt_data.json` for the read-only site view.

## Format

- Two 20:00 halves; every OT is 5:00.
- Timeouts: 2 × 30-second + 4 full. Each OT adds one 30-second timeout to what is left.
- Team fouls reset at the half and carry into OT; bonus at 7, double bonus at 10.

## Schedule and opponents

Schedule tab: **+ Add game** (date, home/away/neutral, opponent, time, conference) or
**Paste schedule** — one game per line as it reads on the athletics site
(`Fri, Nov 7 vs Ventura 7:00 PM`, `11/12 at Oxnard*`, `Nov 22 Santa Barbara (N)`; `*` =
conference; `scrimmage` marks a scrimmage, which is tracked but kept out of the record and season totals). Save schedule. Each game has **Start game** (fills in the setup screen) and
shows the result once played; on game day today's game fills setup in by itself.

The **Opponents** tab (its own tab, apart from the schedule) has a page per team: roster
(**+ Add player** — number, name, position, height, year, and a note that shows on his
button in the game), scouting PDF, notes, results against them and their players' totals
against us. At game setup, **+ Add players / Edit roster** opens the same roster in a
pop-up without leaving setup, and their five starters can be tapped right there (optional —
they can also be set at tip-off). Mid-game, the **Roster** button on their side edits the
same roster; edits match by number, so stats already logged stay with the player.

## Live entry

- Tap a stat, then the player. Makes ask for the assister, misses for the rebounder (tap
  the player — offensive/defensive is read from his team). Steal → who turned it over.
- **Foul** → who fouled → who drew it. **Off Foul** → who committed it → who drew it
  (records the foul, a turnover, and an offensive foul drawn for the defender). **Charge**
  is the same, flagged as a charge: every charge is an offensive foul drawn, not every
  offensive foul drawn is a charge, and Analytics counts them separately.
- **Tech** → tap the player, or **[team] coach**. A player technical is a personal foul and a
  team foul; a coach technical is a team foul. The other side then shoots two (FT Make /
  FT Miss, any player): no rebound on a miss, and they don't use a possession — the
  shooting side keeps the ball. Offensive fouls (charges included) are personal fouls only
  and don't count toward the bonus.
- **Sub**: one window for both teams. Tap a player on either side (no stat selected), or
  **⇄ Sub** → tap who comes out → who goes in, on either or both sides → type the clock →
  Enter. The clock is required at every sub, theirs included.
- **Free throws across a sub**: free throws (attempts and points) belong to the five on the
  floor when the foul was committed, even with a sub between the foul and the shots or
  between the shots. A rebound off a missed free throw belongs to the five on the floor
  then. Lineups, on/off and +/- all follow this.
- Players on the floor (both teams), the lineup card and the Sub window are in jersey order.
- **Timeout**: team, 30s or full, clock.
- **📋 Huddle** (timeout sheet): opens on every timeout and from under the clock — score,
  timeouts, fouls, up to four talk points, the last 5:00 for both teams, the current run,
  empty-trip streaks, kills this half, and both fives on the floor.
- **End-of-game alerts** (last 2:00 of the 2nd half and each OT): one line in the Leverage
  bar's place — no extra room taken — for the most urgent situation, stated as facts (no
  instructions): up 3 with their ball under 0:10; down 1–3 with their ball under the shot
  clock; down 4–9 with their ball under 1:30 (with their FT shooting and each man on the
  floor's); tied / down 1–3 with our ball under 0:35 (bonus status, timeouts); fouls to
  give; their double bonus. Possession comes from the last play; **Our ball? / Their
  ball?** flips it. **Got it** hides it until the situation changes. The same line tops the
  📋 Huddle talk points.
- **Fouled out / ejected**: a 5th foul or a 2nd technical opens the Sub window with him coming
  off; he's red in the Sub window (FOULED OUT / EJECTED (2 T)) and can't be put back in.
- **± Fouls / TOs** (under the scoreboard clock): fix a missed or doubled foul or timeout —
  each team's fouls this half (the bonus count only; a player's foul still goes in with
  Foul), 30-second and full timeouts left. Each tap shows in the play-by-play and Undo takes
  it back.
- Every school name on every screen shows in that school's main colour (a deeper shade on
  white rows and on paper). The small version label next to the Offline pill shows which
  build the device is running.
- No running clock: the time entered at each sub, timeout and period end is the clock. **Set time** under the scoreboard clock updates it any time (e.g. to check garbage time during a long stretch with no sub). S flips to the scouting report and back.

## Killshots

Tracked silently (no live alert): every unanswered run. 10-0 is a killshot; 15-0 and 20-0
are counted on top of it, for and against, and runs carry across the half. Analytics lists
each one with when it happened and the Moorpark five on the floor; Season totals them.

## Their lineups, minutes and +/-

With their roster entered, pick their five at setup, at the start of each half (the start
window picks both teams' fives), or with **Set their five** in their column. Their column
looks like ours: the five on the floor and a Team button. Their subs go through the same
Sub window with the clock, so they get minutes, and their box score has every column ours
has. Under their column, each team's current five shows its possessions, ORtg, DRtg, Net
and +/- together, then each man's +/-. Analytics has a table of their fives with minutes
and the four factors at both ends.

## Halftime and post-game reports

Ending the 1st half opens the **halftime report** on the Live tab: second-half keys (the
factors that are swinging it, turnovers and second chances with the points they cost, their
hot scorer, runs against, foul trouble on both sides), four factors, fouls and timeouts
left, our box, their top scorers, best and worst lineup, and 10-0 runs. **Start 2nd Half**
sets both starting fives. Finishing the game opens the same report for the whole game on
the **Report** tab (each report has a rotation chart — who was on the floor and when, with
10-0 runs shaded), which has 1st half / 2nd half / Full game reports (the Box Score has the
same three buttons). Its "What decided it" leads with the comeback
(or the lead lost) and explains each side's change in points per 100 possessions between the
halves through the stats that drove it, each with a rough worth in points per 100 (e.g.
their 3PT% 8-14 → 3-14, our DREB% 63 → 93). A 1st half vs 2nd half table tags every factor
Flipped, Grew, Held or Narrowed. 🖨 prints it on white paper.

## Season lineups and opponent adjustment

The **Season** page sums every five over the finished games (scrimmages and garbage time
out), with GP, possessions, ratings, four factors and kills; fives under 10 possessions
are folded away. To opponent-adjust them:

1. **⬇ Lineup file** saves every finished game's fives, game by game, with the opponent.
2. In `Neural Network - Codex Optimized/`, run
   `python3 adjust_lineups.py <that file>`. It adjusts each five's game for the
   opponent's leaderboard rating and home court and writes
   `internal_data/moorpark_lineups_adj.json`.
3. **⬆ Adjusted** loads that file (the leaderboard's Moorpark → Lineups page has the same
   **⬆ Load adjusted lineups** button, with 1- to 5-man groups); the table gains Adj ORtg / Adj DRtg / Adj Net. Repeat
   between games — the page says when newer games aren't in the loaded file.

## Saved files: play order

A game's `eventLog` is append-only: plays are added in the order they are logged and
never re-sorted (delete and Undo keep the order). Each event carries `seq` (1 = first
play), `quarter`, `clk` (game clock, seconds left in the period, read from the clock or
the nearest sub/timeout clocks), `ts` and an increasing `id`, so a backup or export
reads in order without the app.

## Possession (all game)

The pill under the clock shows who has the ball (◀ MOORPARK BALL / THEIRS BALL ▶ in
their colour). It follows the plays logged (makes, rebounds, steals, turnovers) and one
tap sets it:

- **Tip-off and the start of the 2nd half** (or before the first play of a period, or at
  the break): the tap just gives the ball - no questions.
- **Mid-possession** (a tie-up): the tap asks. **Held ball: turnover + steal** logs a
  turnover on the man who lost it (none picked = Team) and, optionally, a steal for the
  man who tied him up. **Just switch** only fixes a wrong read (out of bounds, etc.).

A tap holds through timeouts and subs until the next play. The end-of-game alerts read
the same possession.

## Huddle: last 5:00 vs the game

The Huddle's table is the four factors plus 3PA rate and assist rate - eFG%, TO% (with the points the
turnovers gave up), OREB% (with second-chance points), DREB%, FT rate (FTA / FGA) and 3PA rate
(3PA / FGA) - each side's last 5:00 beside its whole-game number, with the count behind
it. A cell turns amber with ▲/▼ only when the last 5:00 has moved well away from the game
on enough attempts: 15 points of eFG% or 20 of FT / 3PA rate on 5+ FGA, 20 points of
OREB% or DREB% on 4+ chances, 10 points of TO% on 3+ turnovers. A last row, **AST rate** (AST / FGM,
with the assist-to-turnover ratio under it), lights up on 25 points over 4+ makes. Five minutes is 8-10 trips, so this
is the "something changed" flag, not a verdict.

## Flags and editing past subs

- **🚩 Flag** a play to look back at later: on the Live screen, **🚩 Flag last play** (the
  play just logged) or the 🚩 on any recent play; in the Play-by-Play, the 🚩 on any row, with
  an optional note. **Flagged only** filters the Play-by-Play. Flags are saved on the play
  (`flag`, `flagNote`), and every ⬇ Backup / export starts with a `flagged` list per game:
  period, clock, score, play and note.
- **✏️ Edit a sub** (Play-by-Play): change its clock or who went in / out, or delete it,
  without undoing the plays after it - they follow the new lineup, and minutes are rebuilt.
  It's refused if the clock falls outside the entries around it, or if a later sub would no
  longer make sense (the reason is shown). Undo takes an edit back.

## Clock entries

A sub, a timeout (official included) and the end of a period refuse a time that has
already gone by in the period: above the live clock when it runs, the last time entered
when it doesn't, or the last sub. **Set time** is the one place the clock may go back UP
(a correction, or the officials put time back), and it shows that it is a correction; it
still can't go above the last sub.

## Official timeouts

The timeout window has a third choice, **Official** (clock fix, wet spot, injury): the
stoppage and its clock are logged and the Huddle sheet opens, but neither team is
charged a timeout. It shows as OFFICIAL TIMEOUT in the play-by-play and "Official" in
the timeout table.

## Live cards

- **Foul trouble** colours the whole card: 1st half 2 PF amber, 3+ red; 2nd half and OT
  3 PF amber, 4+ red.
- **Stint timer** (bottom right): how long that man has been on since he last checked
  in, counting up with the clock; restarts each period.

## Garbage time and leverage (live)

- **Garbage time** — the defensive possession logger's ladder on game time left: 30+ any
  time, 25+ ≤8:00, 20+ ≤5:00, 15+ ≤3:00, 10+ ≤1:00. Sticky once reached. Those possessions
  are flagged (`gt` on each event) and left out of On/Off and Lineups by default.
- **Leverage** per possession — High ≤3, Medium 4–12 and reachable, Low 13+ or out of reach
  on the trips left. **Clutch**: last 5:00 of the game (all of OT), within 5, not Low.
- **Kills** — three straight stops banks a kill for that defence; the count restarts after
  each one (six straight = two) and at the start of each half (and each OT): the three
  stops have to come in the same half. A trip that ends on a rebound off a missed free
  throw is not a stop and breaks the run, and so does a technical (made or missed) for
  the side that committed it. The scoreboard shows this half's kills (green
  circles = the current stop run); the reports, Analytics and Season keep the game totals,
  and the play-by-play tags each one.
- The game clock for each possession is read from the sub/timeout clocks (and the running
  clock when used).

`vendor/` is pdf.js 4.10.38 (Apache-2.0, see `vendor/PDFJS_LICENSE`), bundled so the
scouting report renders on iPad without a network.
