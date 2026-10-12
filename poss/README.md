# Possession Tracker

`chadoconnor5.github.io/moorparkmbb/poss/`: possession-by-possession tracking for both teams,
built in the game tracker's design (`/game/`) and for the iPad in portrait. It is a separate app.
It reads the game tracker's Moorpark roster, opponent rosters, schedule and scouting PDFs on the
same iPad, but never writes to them.

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
- **Timeout:** pick the team, full or 30. **± Fouls / TOs** fixes the counts.
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

The **Poss** number on the scoreboard is the two teams' counts averaged: (Moorpark + opponent) ÷ 2.
Each team's own count shows under it.

**Kills:** 3 defensive stops in a row, for each team. The count restarts after a kill, a score, or
a new period.

## Lineups
⇄ Sub sets both teams' fives on one screen. The starting fives are asked for when a game starts
and at each new period. The opponent's roster comes from the game tracker; edit it with Roster on
the live screen (numbers are enough).

The player cards show each player's fouls and his on-floor **+/-**. The live screen's lineup cards
show the current five for each team: possessions on offense / defense, ORtg, DRtg, net and +/-.

**Lineups tab**, for the game or the current period, for both teams. For every five:
- possessions on offense / defense, points for–against, +/-, ORtg, DRtg, net;
- tap a five to see how its possessions ended at each end.

## Other tabs
- **Sheet:** every possession in order for both teams, with how it ended, offensive rebounds,
  points, kills and the running score. Subs and technicals are shown where they happened.
  - Tap a row to change the stat or team, delete the play, or insert a missed play before it.
  - Summary by period. Print / PDF.
- **Four factors:** type the printed box score totals on the number pad.
  - 1st half at halftime, Full game at the end. 2nd half is the difference.
  - Gives eFG%, TO%, OREB%, DREB%, FT rate, 3PA / AST rate, shooting, possessions and PPP, with
    the game tracker's formulas.
- **Scouting:** the scouting PDF. It shares the game tracker's stored PDFs, and the opponent's
  opens first.
- **Games:** new game, open, export / import, delete, the Moorpark roster.

Games are saved on the iPad (localStorage `pt2_games`), and the app works offline once opened.
The page is built from the game tracker's stylesheet, copied into `poss/index.html`. If the game
tracker's look changes, copy its `<style>` block across again.
