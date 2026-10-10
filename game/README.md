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

Data lives on the device that tracked it (browser storage). Use **Backup** after each game to
keep a copy, and **Publish** to download `gt_data.json` for the read-only site view.

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

The **Opponent** dropdown under the schedule opens that team's page: roster (**+ Add
player** — number, name, position, height, year, and a note that shows on his button in
the game), scouting PDF, notes, results against them and their players' totals against
us. Mid-game, the **Roster** button on their side edits the same roster; edits match by
number, so stats already logged stay with the player.

## Live entry

- Tap a stat, then the player. Makes ask for the assister, misses for the rebounder (tap
  the player — offensive/defensive is read from his team). Steal → who turned it over.
- **Foul** → who fouled → who drew it. **Off Foul** → who committed it → who drew it
  (records the foul, a turnover, and a foul drawn / charge for the defender).
- **Sub**: tap the player on the floor (no stat selected) → tap his replacement → type the
  clock → Enter. The clock is required at every sub.
- **Timeout**: team, 30s or full, clock.
- No running clock: the time entered at each sub, timeout and period end is the clock. **Set time** under the scoreboard clock updates it any time (e.g. to check garbage time during a long stretch with no sub). S flips to the scouting report and back.

## Killshots

Tracked silently (no live alert): every unanswered run. 10-0 is a killshot; 15-0 and 20-0
are counted on top of it, for and against, and runs carry across the half. Analytics lists
each one with when it happened and the Moorpark five on the floor; Season totals them.

## Their lineups and +/-

With their roster entered, pick their five when you start each half (or **Set their five**
in their column). Their subs: tap one of their players with no stat selected, tap who comes
in; the clock is optional for their subs. Their five show big, the bench underneath. Each of
their players carries his +/- on his button and in the box score, both lineups' +/- sit side
by side on the live page, and Analytics has a table of their fives.

## Garbage time and leverage (live)

- **Garbage time** — the defensive possession logger's ladder on game time left: 30+ any
  time, 25+ ≤8:00, 20+ ≤5:00, 15+ ≤3:00, 10+ ≤1:00. Sticky once reached. Those possessions
  are flagged (`gt` on each event) and left out of On/Off and Lineups by default.
- **Leverage** per possession — High ≤3, Medium 4–12 and reachable, Low 13+ or out of reach
  on the trips left. **Clutch**: last 5:00 of the game (all of OT), within 5, not Low.
- **Kills** — three straight stops banks a kill for that defence; the count restarts after
  each one (six straight = two). A trip that ends on a rebound off a missed free throw is
  not a stop and breaks the run. Shown on the scoreboard (pips = current stop run), in
  Analytics by period and by lineup, and tagged in the play-by-play.
- The game clock for each possession is read from the sub/timeout clocks (and the running
  clock when used).

`vendor/` is pdf.js 4.10.38 (Apache-2.0, see `vendor/PDFJS_LICENSE`), bundled so the
scouting report renders on iPad without a network.
