# Coaches' demo

A standalone copy of the possession tracker for showing the staff, at
**https://chadoconnor5.github.io/moorparkmbb/demo/**. It is separate from the real tracker (`poss/`):

- **Its own data.** Everything it saves is stored under `mbbdemo:` keys, so its fake games never mix with the real
  tracker's games, rosters or schedule on the same iPad. **Reset demo** (the orange bar) puts it back to the start.
- **Works offline.** All the data is inside the page. Open it once with signal (Safari → Share → Add to Home Screen
  makes it an app called *MBB Demo*); after that it opens with no signal, logos included.
- **Frozen on last season (2025-26).** Real rosters, jersey numbers, labels and leaderboard ratings for Moorpark and
  every opponent in it; it never refreshes from the leaderboard.

## What's loaded

- **13 simulated games** last season (Ventura twice, Oxnard, Santa Barbara, Irvine Valley, Allan Hancock, Cuesta,
  LA Valley, LA Pierce, West LA, Bakersfield, Chaffey, Riverside). Each player shoots, rebounds, passes, turns it
  over and fouls at his real season rates, and each team rotates through the same handful of fives, so the season
  lineups and situations have real samples.
- **The live game: Irvine Valley at home**, 2nd half, **3:12 left, down 76–79, our ball**, right after our full
  timeout. Team fouls: ours 6 (one from their bonus), theirs 8 (we're in the 1-and-1). Timeouts left: ours 1 full
  + 1 thirty, theirs 2 full + 1 thirty. Foul trouble: Finney 4, Kubel 3; Mowers 4, Alhammouri 3. A halftime stat
  sheet is loaded, so the halftime report is the full version.
- **The Irvine Valley scouting report** (📄 Scout → Scouting PDF, also on the Scouting tab): the real 2025-26 report
  (the Ventura report's layout, 11 pages: identity, analytics, four factors, every player's profile, splits, keys
  to victory) in Irvine Valley's blue. Its head-to-head is the real February game, not the demo's simulated one.
  It's stored on the iPad the first time the demo opens and opens offline.

## A walk-through for the staff

1. **Live:** CLUTCH and HIGH leverage, the clock, bonus and fouls on the scoreboard. Finney's and Mowers' cards are
   red (4 fouls). Labels on every player (tap **+N** for the rest; **Labels** explains each one). THIS FIVE says
   what the five on the floor does well and badly. The gold **Lineup suggestion** banner: the five on is losing late.
2. **Huddle:** down 3 with 3:12, fouls to give, timeouts, FT tonight, the last 10 possessions vs the game.
3. **💡 Try / Lineups:** better fives for this moment from the season; the **Situation** filter (late and close,
   after a timeout...).
4. **Report → Halftime:** key takeaways, who's behind the four factors, the box score with advanced numbers,
   on/off, best fives and combos.
5. **Rosters → Irvine Valley:** their roster with labels, their Basic / Advanced stats with state ranks.
6. **📄 Scout:** Last time vs Irvine Valley (the November meeting), then the Scouting PDF tab.
7. **Schedule:** last season's results; the Irvine Valley game has **📁 Last time** (the November meeting).
8. **Runs, Play-by-Play, Four factors:** kills, kill shots and runs; every possession; the factors by half.
9. **Log a few plays** (2PT Make, a foul, a sub): everything updates. **Reset demo** when done.

## Rebuilding

`demo/src/`: `gen.js` simulates the season inside the real tracker (served from the repo root on port 8765) and
writes `seed.json`; `recolor_ivc.py` turns the real Irvine Valley report into `ivc_scout.pdf` (Irvine Valley's
colors); `build_demo.py` copies `poss/index.html`, adds the storage prefix, the seed, the PDF and the banner, and
writes `demo/index.html`, `demo/sw.js` and `demo/manifest.webmanifest`. Rebuild after a tracker change you want in
the demo.
