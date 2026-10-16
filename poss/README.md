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
- **Timeout:** pick the team, full or 30, and tap the **game clock** (time left in the half) on the big keypad: digits fill
  from the right (7, 4, 2 → 7:42; 5, 0 → 0:50), no iPad keyboard. Then **Log timeout → Huddle**; **Skip clock** if you don't have it. The clock shows in the Huddle header, the feed and
  Play-by-Play (tap the timeout line to fix it on the same keypad). Each clock is a checkpoint: from then on leverage, clutch and garbage
  time use exactly that clock (no running estimate; it holds until the next clock you enter) instead of the
  estimate from possessions, and late and close leads the Huddle ("Clutch: up 2 with 0:50 left"). 4 full + 2 thirty-second a team, +1 thirty per OT (full = rectangles, 30s = dots). **± Fouls / TOs** fixes the counts.
- **⏱ Set time** (scoreboard, beside ± Fouls / TOs): enter the game clock any time on the same big keypad
  (7, 4, 2 → 7:42). It works like a timeout's clock: time left, leverage, clutch and garbage time run from
  it, the scoreboard shows **Clock 4:30**, and it goes in the feed as "Game clock · 4:30" (tap it to fix or delete).
- **Free throws name the shooter.** The trip's first **FT Make / FT Miss**: tap the shooter's card (the player
  cards light up), or the team logo for team. The rest of the trip logs on the FT Make / FT Miss tap alone, to
  the same shooter (or team), with a note ("FT make · #3 Kubel"). A trip is free throws in a row by one team:
  a sub, timeout or Set time in between doesn't end it; a foul or any other play does, so the next trip asks
  again. Wrong shooter? Tap the line in the feed.
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
  - **End of half** (4:00 or less, once a clock has been entered at a timeout; any half or OT): the clock, the margin
    and possessions needed, rough possessions left each, fouls to give for both teams (bonus on the 7th, double at
    10), timeouts left and each team's FT tonight. Only in the Huddle: the live screen already shows fouls and
    timeouts beside the score;
  - momentum: current run, stops in a row, kills this half;
  - both fives on the floor: fouls (foul-trouble colours), +/-, notes, and the five's ratings.
  - **THIS FIVE** (where the Team / bench foul row was, once a five is set): two labels on one line for each five
    on the floor: its best strength (green: *3 shooters*, *Attack the rim*, *Ball hawks*, *Rim protector*, *Elite glass*, *Passers*,
    *Closing FTs*) and its worst weakness (red ✕: *1 shooter*, *G can't shoot*, *Thin glass*, *TO risk*,
    *Foul-prone*, *FT #21*). Tap one: a light-grey bubble above it lists who earned it, with their numbers. Nothing
    is logged.
    - From each player's season line (quality games: stat sheets / leaderboard; at halftime the 1st-half sheet
      joins it when the game is close against a good team, so the 2nd half adapts) and, where a player has no line
      yet (every opponent for now), from his position and his card labels (Shooter, Big, Ball hawk, Can't shoot...).
    - **Shooter / non-shooter** combines 3PA rate (share of his shots that are threes), threes a game and 3P%:
      - *Estimated 3P%* = his quality-game makes / attempts pulled toward **his own all-games 3P%** (the
        leaderboard's box scores, downloaded with the ratings) until they add up (the starting point counts as 50
        attempts). Only a player with under 10 threes anywhere starts from the team's 3P%, moved by his card
        label (Shooter +3, Can't shoot −4). FT% is not used.
      - *Volume* = 3PA rate (40% of his shots, 10+ FGA) or 2.0 threes a game, whichever says more.
      - Shooter: full volume and est. 32%+, or 75% of the volume and est. 36%+. Non-shooter: est. under 28%, or
        under 15% of his shots on 20+ FGA, or under 0.5 a game over 3+ games. In between: neither.
      - So week one runs on volume and labels, and February on his own threes. The bubble shows
        "est 36% · 4/10 · 2.5/g · 33% of FGA".
    - **FT rate** (FTA / FGA, 15+ FGA) = how often he attacks the basket: 45%+ is an attacker; two on the floor =
      *Attack the rim*. A **slasher** is a non-shooter who attacks: he counts toward Attack the rim, and a
      slasher guard is not *G can't shoot* (that is a guard who neither shoots nor attacks).
    - Other lines (per 40, 60+ minutes): ball hawk 2.5+ steals, rim protector 2.5+ blocks, TO risk 4+ (two
      players), foul-prone 6+ PF (two players); glass = the five's rebounds per 40 (40+ elite, 26 or less thin);
      passers = assists per 40 of 18+; Closing FTs = all five 75%+; FT #N = the worst shooter under 62% (6+ FTA).
    - Foul trouble stays on the player cards (yellow / red), not here. A foul on nobody (bench / team) is set from
      the play's edit screen; before a five is set, the Team / bench foul button is still there.
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
below. Tap a player on the floor to take him out, tap a bench player to put him in (in any order: with more
than five on, it says how many to tap off). The starting fives are asked for when a game starts
and at each new period. The opponent's roster comes from the game tracker; edit it with Roster on
the live screen (numbers are enough).

**⏳ Pending** (its own button, beside ⇄ Sub): mark players waiting at the table before you know who
they're replacing. It lists each team's bench only (no one on the floor, no one fouled out); tap to
mark **⏳ CHECKING IN**, tap again to unmark, **Clear all** to reset. A **Checking in** strip shows under
each team's on-floor list with a **Sub now** button, ⇄ Sub reads **⇄ Sub (3)** and ⏳ Pending turns gold. When the sub
happens, ⇄ Sub opens with them already on the floor list (gold, first) and says **tap 2 coming off**:
tap who's coming off and Confirm. **Sub now** on the strip opens the same screen. You can still add more
from the bench there (the count goes up: **tap 3 coming off**); Confirm unlocks when each team is back to five. Players who went in leave the pending list; anyone left out stays
pending. On a fouled-out player's forced sub, a pending player fills the spot.

**Holding a pending sub (free throws):** the sub screen lists pending players in their own **Checking in**
group, each **⏳ GOING IN** (the default) or **✋ HOLD**: one tap switches. Use it when the man a pending
player would replace is shooting free throws and has to stay in: hold that sub, tap off only the others
("tap 1 coming off"), Confirm. The held player stays pending, so after the free throws **Sub now** brings
him straight back.

The player cards show each player's fouls and his on-floor **+/-**. The live screen's lineup cards
show the current five for each team: possessions, ORtg, DRtg, net and +/-.

**Their best five (2nd half and OT only):** the opponent five with the best net rating so far, among
fives with 8+ possessions. When it is on the floor a ★ **Their best five is on** tag (net, possessions)
shows at the top of their column and on their lineup card, and a sub that puts it back on pops a note.

**Lineups (situational lineups):** a button in the live controls (and 💡 Try opens it on Best overall).
The situation buttons sit in four fixed rows, so each is always in the same place: **Close it out**
(Closing FTs · Ball security · Last stop), **Come back** (Need a 3 · Need steals), **Defense** (Stop the
run · Stop the 2s · Off the 3-pt line · Close out the glass · Stop fouling) and **Overall** (Best overall ·
What's hurting us · Move the ball · vs their best five). A gold **Right now** bar on top lists the ones whose trigger is
met, most urgent first, with the reason ("Up 5 with 3:11 left: they have to foul"); they're also
underlined gold in their rows. Blue is the one open.

| Situation | Lights up when | Fives ranked by |
|---|---|---|
| Last stop | up 1-3, their ball, last 1:00 | best stop % |
| Closing FTs | up 1-8 with 4:00 or less on a clock you set (never an estimate) | closing FT% of each player (below) |
| Ball security | up 1-10, last 4:00 | lowest TO% |
| Need steals | down 4+, last 4:00 | most steals per defensive possession |
| Need a 3 | down 4-9, last 4:00 | players' season 3P% |
| Stop the run | they're on a 6-0 run or more | best stop % |
| Stop fouling | 7+ team fouls with 5:00+ left in the half, or their FT rate 10+ over our norm | fewest fouls per 100 defensive possessions |
| Stop the 2s | their 2P% 8+ over our norm (10+ twos) | best **rim D**: low opponent 2P%, blocks, without fouling (below) |
| Off the 3-pt line | their 3PA rate 8+ over our norm | fewest opponent 3-point attempts |
| Close out the glass | our DREB% 5+ under our norm | best DREB% |
| Move the ball | our AST% tonight 12+ under our norm (8+ made shots, logged game) | best AST%, with AST/TO shown |
| What's hurting us | we're losing a four factor this half | the halftime card's logic |
| vs their best five | their best five is on | our fives' net against that exact five, tonight |
| Best overall | the five on is at a net of 0 or worse late | four-factor edge |

**Assists and blocks in the situations.** Only games logged with the Assist / Block buttons count, so older
games never read as zero; a five's AST% and BLK% are pulled toward our norm until the sample supports them
(15 made shots / 20 of their 2-pt tries count half). **Rim D** (Stop the 2s) = opponent 2P%, minus half of how
far the five's BLK% (blocks per opponent 2-pt try) is above our norm, plus a quarter of how far its fouls / 100
defensive possessions are above our norm; lower is better. So two fives that hold teams to the same 2P% are
split by who blocks shots without sending them to the line. Each five shows its raw line: "opp 2P 41% ·
BLK 9/48 · 1.3 blk/PF · 22 fouls/100" on Stop the 2s, "AST 14/20 made, AST/TO 2.3" on Move the ball and Ball
security. Until a logged game is in, Stop the 2s ranks on opponent 2P% and fouls. Plug in (fouled out) on
Move the ball ranks by assists / 40.

**Closing FTs** is one list: the **best five FT shooters available**, ranked by **closing FT%**, each
with season FTs and clutch FTs, IN / ON tags against the five on the floor, then who comes out (OUT) and the
next three on the bench, a red line naming the weakest shooter on the floor ("That's who they'll foul"),
and **Sub these five in**. Closing FT% = the player's season FT% (quality games, pulled toward the team
rate when attempts are few; 10+ FTA to be picked) moved toward their **clutch FTs** as those add up: clutch
attempts weigh against 20 attempts at the season rate, so one 0/2 night can't sink anyone. Clutch FTs =
FTs tagged to a shooter in the last 5:00 of the 2nd half or OT within 5, in every game (no scrimmages),
only where a clock you set stands behind the possession. Fewer than five qualified players → it says so
and leaves the rest to you. No leverage row here (FT% is the players' own numbers). Plug in uses the same
closing FT%.

Every other situation opens to Today | Season (opponent-adjusted for the four factors; the season's raw counts for the
rest), the leverage filter (every situation opens on High+Med), IN/OUT and **Sub
this five in** on every five. The FT and 3-point situations also list the **best 5 available** shooters,
whether or not they've played together, with **Sub these five in**. Never a five with a player who fouled
out or isn't dressed; **Protect fouls** also leaves out anyone with 3+ fouls in the 1st half or 4+ after.
Our norm is our earlier finished games (league average until 2 are in). The players' season lines (FT%,
3P%, fouls, steals) come in the ⬆ Adjusted file.

**Fouled out → Plug in.** The forced-sub screen suggests the three best single players to replace him, for
the moment: the most urgent situation lit right now picks the stat (last stop → steals + blocks per 40;
closing FTs → FT%; ball security → fewest turnovers per 40; need steals → steals per 40; need a 3 → 3P%;
stop fouling → fewest fouls per 40; stop the 2s → blocks + defensive rebounds per 40; glass → defensive
rebounds per 40). With nothing lit: how the five with him in has done (season, opponent-adjusted and
leverage-weighted, then tonight), then his +/- tonight. The same position breaks ties (SAME POS).
**Plug in** puts him in; Confirm.

**Players' season stats so far** (for Plug in and the FT / 3-point situations) count **quality games only**:
against an opponent with a positive adjusted net rating, decided by 15 or fewer, so nobody is suggested
off blowouts or weak opponents. Box scores can't see leverage inside a game; that's the closest they get.
They come from the final stat sheets photographed in this tracker (plus tonight's latest sheet while tonight
is close against a good team; scrimmages out) and the leaderboard's box scores in the ⬆ Adjusted file,
whichever has more of a player's quality games. Small samples are pulled toward the team's number (FT%: 20
attempts at the team rate; 3P%: 40; per-40 rates: 60 minutes), and a player needs 10+ FTA, 20+ 3PA or 60+
minutes in quality games to be suggested on that stat at all. Every suggestion shows its sample
("24/28 FT, 11 quality g").

**Season lineup numbers for the situations:** the four factors are opponent-adjusted; the rest (stop %,
steals, fouls, opponent 2P% and 3-point attempt rate) count only games against quality opponents. Leverage
(garbage time always out) applies to both.

**💡 Try (lineups to try, last 10:00 of regulation and OT):** when our five on the floor is at a net of 0
or worse (garbage time out), the **💡 Try** button at the top right of our lineup card (there only in the last 10:00 of the 2nd half and OT, on
the MOORPARK — THIS FIVE line; plain otherwise) lights up gold, and a gold **Lineup suggestion** banner
shows above the scoreboard ("the five on is at a net of −200.0 with 6:08 left. Better fives are ready.")
with **See lineups** and **✕**. ✕ closes it for the five on the floor; it comes back only if a different
five gets into the same spot. Both open
**Lineups to try**, the same card as the halftime report, built for now, with today's fives beside the
season's (opponent-adjusted), at a **Leverage** setting that opens on **High+Med**:
- **Best overall:** the four-factor edge (ours minus theirs, weighted eFG% 40, TO% 25, OReb% 20, FT
  rate 15), better than the five on now and winning the factors;
- **What's hurting us** in the 2nd half so far, one stat at a time, as at halftime.

Each five shows who comes **IN** and goes **OUT**, and **Sub this five in** opens the sub screen with it
filled in, ready to confirm. Nobody fouled out or not dressed. No five qualifies, no button.

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

**Season lineups, opponent-adjusted** (Lineups → Season):
1. **⬇ Lineup file** saves every finished game's Moorpark fives, game by game with the opponent and
   site (garbage time out), in the game tracker's format.
2. On the PC, in `Neural Network - Codex Optimized/`, run `python3 adjust_lineups.py <that file>`.
   Each five's ratings are adjusted for the opponent's leaderboard rating and home court, and its four
   factors against the opponent's opponent-adjusted four factors: holding a team that has rebounded well
   against good opponents counts for more than holding a weak one. Scrimmages and teams outside the CCC
   system are left out of the adjusted numbers.
3. **⬆ Adjusted** loads `internal_data/moorpark_lineups_adj.json`. A table lists each five: adjusted
   ORtg, DRtg, net and four factors at both ends, and **H · M · L**, how its possessions split by
   leverage (red when mostly low). It says when newer games aren't in the file.

**Leverage.** The file carries each five's possessions split by leverage (High / Medium / Low, and clutch;
garbage time is out of everything), and each split is opponent-adjusted. A **Leverage** filter, on the
season table and the halftime card, picks **High+Med** (the default), **High**, **Clutch** or **All**.
Season **All** is leverage-weighted: a possession counts High ×1, Medium ×0.6, Low ×0.25, so a five that
built its numbers in low-leverage minutes ranks lower. Smaller scopes need fewer possessions (season
All 25 / High+Med 15 / High 10 / Clutch 6 at that end; today 6 / 5 / 4 / 3), and when no five qualifies
the next wider scope is shown, saying so. The Lineups tab filters add High+Med and High.

**Halftime: lineups for what's hurting us, today and season.** Each four factor we're losing in the 1st
half is split into its two ends, and only the end that's off our norm tonight is worked on (our season
norm once 2 games are in, league average before). Each problem is one stat with one direction, and the
fives are ranked on that stat alone:
- they're getting their misses back → **Defensive rebounding**: the best DREB% fives;
- they're shooting well → **Their shooting**: the lowest opponent eFG% fives;
- likewise our shooting (eFG%), our turnovers (TO%), forcing turnovers (opp TO%), offensive rebounding
  (OREB%), getting to the line (FT rate) and fouling (opp FT rate).

Worst problem first. Two columns side by side:
- **Today:** this half's fives, as played;
- **Season:** the opponent-adjusted season fives (from ⬆ Adjusted), with their H · M · L leverage mix;

both at the chosen leverage (High+Med by default; see Leverage above).

Each lists its top two, only fives better than the norm with everyone dressed and not fouled out.
★ BOTH marks a five in the top two of both columns; ON NOW marks the five on the floor. No five
qualifies, none is listed.

## Lineup Builder and WOWY (as in the practice tracker)

**Lineup Builder**, above the Moorpark lineup table: one dropdown per player of the size you're on (5-, 4-,
3- or 2-man). Pick a player and the other slots only offer players who actually shared the floor with him
under the current scope (game / half / season) and leverage filter; the table narrows to the units with every
pick, so a full pick is one row. A pick that stops fitting after a filter change is kept and the panel says
so. Clear empties it.

**WOWY** (With Or Without You), the button after 2-man: five slots, pick 2-5 of our players and every on/off
combination of them gets a row (2 picks = 4 rows, 3 = 8 ...): GP, possessions, +/-, ORtg, DRtg, net and the
four factors at both ends, over the possessions with exactly that pattern on the floor (green chip = on, red =
off). Off means he sat: a game only counts if every pick played in it; the others are counted under the table.
Moorpark only (the opponent lineups are hidden in WOWY). Combinations that never happened stay, dimmed and last. Always the whole season (every game tracked, scrimmages out), whatever the Lineups scope; the leverage filter applies.

**Lineups opens on Full season.** The controls sit in one panel: **Games** (This game or a season split), **Half**, **View** (5- to 2-man, WOWY), then **Possessions** and **Situation**. **Scope** on Lineups: a dropdown of **This game** or a **season split** (as CBB Analytics has them), then **All · 1H ·
2H · OT** and the Possessions filter on top. Splits (game counts shown): Full season, Last 5, Last 10, Conference,
Non-conference, Conference wins / losses, Postseason, Home, Away, Neutral, Away + neutral, Games won / lost,
**Q1A, Q1, Q2, Q1 + Q2, Q3, Q4**, vs top 25 / outside the top 25, and Select your own games (a
chip per game). Quads are the leaderboard's (its Quads tab), exactly: opponents ranked by net among every rated team,
NCAA cutoffs of 353 scaled to the league (Q1A home 15 / neutral 25 / away 40, Q1 30/50/75, Q2 75/100/135, Q3
160/200/240, Q4 the rest); Q1 includes Q1A and Q1 + 2 includes Q1A, Q1 and Q2. They use the nightly ratings. Scrimmages never count. Season 2H =
every game in the split's 2nd half. The Lineup Builder and WOWY follow the split (WOWY uses Full season when
This game is picked).

**Situation** dropdown on Lineups (Any, Closing FTs, Ball security, Last stop, Need steals, Need a 3, Stop the run,
Stop fouling): only the possessions each game's situation log tagged with it, so a split, a half, a leverage and a
situation stack (e.g. Q1A · High · Last stop). A **Moorpark line** above the lineups gives the team's possessions,
score, ORtg / DRtg / net and four factors for exactly that view.

**Possessions** dropdown on Lineups (opens on **High + Med**): All, High, High + Med, Medium, Low, Clutch, No
garbage time. It drives the lineup table, the Lineup Builder and WOWY.

## Assist and Block buttons

Two stat buttons ride on a shot, right above FT Make / FT Miss (red outline when it can be added, gold when toggled on):
- Tap **2PT Make** or **3PT Make**: every other stat button mutes except **Assist** (and the team logos). Tap Assist
  if it was assisted, then the team logo logs the make, assisted. No Assist tap = unassisted.
- Tap **2PT Miss** or **3PT Miss**: everything mutes except **Block**. Tap Block if it was blocked, then the logo
  logs the miss, blocked (and the logos wait for the rebound as before). No Block tap = not blocked.
Tap the make / miss again (or Cancel) to back out. The feed shows "(assisted)" / "(blocked)", and the leaderboard
export's assisted column fills in.

Games started from now on log them (old games don't, so on / off counts assists and blocks only from games that do):
the on / off cards' Assists / 40, Assist %, Ast/Tov, Blocks / 40, Block %, Hakeem %, Blocks / PF and PF Efficiency
((steals + blocks) / fouls, as in the practice tracker) fill in.

## Player on / off and projected fives (Lineups → View)

**View** is one dropdown: 5-man lineups, 4-man, 3-man, 2-man pairs, Player on / off, Projected fives & synergy,
WOWY, Rotation map. Everything follows the Games split, Half, Possessions and Situation.

**Player on / off** mirrors the practice tracker's Player On-Court Impact cards: a card per player ranked by share
of floor time, four panels of eight rows (Core Stats, Box Stats, Offense & Activity, Defense), each a team stat
On / Off / Diff (green = team better with him on). The Defense panel ends with **PF Efficiency, Steals / PF and
Blocks / PF** (the version before paint / transition / off-turnover points). Differences from practice: minutes
are his share of each half's possessions (a half = 20 min), possessions are the real count, and assists, blocks
and deflections aren't logged in games (—), so PF Efficiency is steals per foul. Ratings and four factors are
opponent-adjusted (Data → Show raw numbers for raw).
**Shooting** checkbox (top of the on / off view, remembered): adds a full-width Shooting panel first on every card,
the team's raw shooting with him on / off: Effective FG%, True Shooting %, FGAs / 40, Field Goal Pct, 2PAs / 40,
2-Point Pct, 3PAs / 40, 3-Point Pct, FTAs / 40, Free Throw Pct (On / Off / Diff).

**Projected fives & synergy**: an adjusted plus-minus model (ridge regression over every possession in the view,
opponent-adjusted, each player starting at 60 possessions of average): each player's Off / Def / Net impact per
100. **Pair synergy** = how the team did with both on beyond what the model expected from who was on the floor,
shrunk toward 0 (40 possessions to count half). **Best projected fives** = team baseline + five players + half of
each pair's synergy, from the 13 most-used players: the best untested fives (with a Try button) and the best
overall.

## Rotation map (Lineups → View → Rotation)

CBB Analytics' "Lineup Tendencies" heat maps, by possession instead of by minute: each half is cut into 20 equal
slices of its own possessions (both teams, in order). Every slice is a whole number of possessions (a 38-possession half:
18 slices of 2 and 2 of 1, spread evenly; tap a box for "Possessions 37–38 · 2 possessions"), so a slice stands in
for a minute. Each game is sliced on its own count, then the games in the Games split are added. One row per player,
sorted by possessions on the floor; darker = higher.
- **On court**: % of the slice's possessions he was on the floor (scale to 80%).
- **On court for shots**: % of our shot attempts in the slice taken with him on the floor (to 80%).
- **Shots taken**: % of our shot attempts in the slice he took (shots tagged to a shooter; to 25%).
Tap a box for the numbers behind it; **Slices per box** 1 / 2 / 4 / 5 widens the boxes. Overtime isn't drawn.

## Lineup shooting and scoring (tap a five on Lineups)

Under how its possessions ended, every five shows both ends (ours = OFF, theirs = DEF):
2P, 3P and FT (made/attempts and %), **TS%** (points / (2 × (FGA + 0.44 FTA))), **PTS/FGA** (field-goal points per
shot), **SCORE%** (trips with a point), **2ND CH** (points after an offensive rebound, and per OREB), **OFF TO**
(points on the trip right after the other side's turnover), **AND-1s**, **STL'D** (turnovers that were
steals) and **CHG/OFF** (charges / other offensive fouls committed). Game, half and season scopes all have it.
FTs made now go in the ⬇ Lineup file too.

## Opponent ratings, live (every game re-graded nightly)

The leaderboard build writes **`poss/ratings.json`** every night (`export_ratings.py`): every in-system team's
current opponent-adjusted ORtg / DRtg and four factors, games played, the name aliases, Moorpark's player
season lines (all / quality games), and the time-of-season baseline. The tracker downloads it whenever it
opens online and keeps the last copy for offline gyms. It then **re-adjusts every finished game on the
iPad** with the same math as `adjust_lineups.py` (a test checks they agree to the decimal), so:
- Every past game is graded against **what that opponent turned out to be**, not what they were that
  night: holding a team in November that became a great shooting team counts as exactly that.
- **No recency decay**: game 1 counts as much as game 20.
- **Time of season** (measured on 8 seasons): league scoring runs ~1.8 points per 100 below its season
  average in November and ~1.7 above in February, every year. Each game is put on the season-average scale
  for its month, so scoring well early counts for more and holding a team down early for a little less.
  Both ends move together, so a five's net is unchanged.
- Everything uses it: season lineups, situational lineups, the halftime card, the quality-opponent filter,
  players' quality-game lines, our norm (four factors opponent-adjusted), and the Runs tab (kills weighted
  by the opponent's rating: a kill on a good offense counts more).
- **One lineup table, opponent-adjusted.** The Moorpark lineups (and the Moorpark line above them) show
  adjusted ORtg / DRtg / net and four factors for exactly the view picked: games split, half, possessions,
  situation and group size. Each game's units in that view are adjusted against that opponent, then summed.
  +/- and possessions stay actual counts (no PTS, STOPS or NS TO% columns: points and stops are in the row details). A five with no rated opponent in the view shows
  its raw line in italics.
- **Raw is the backup**, in the **Data** corner under the table: **Show raw numbers** (and back), the ratings
  date (warns when more than a week old), ⬇ Lineup file and ⬆ Adjusted file (only used if the iPad has never
  been online). The old second "Season lineups, opponent-adjusted" card and its Whole season / Last 8 toggle
  are gone: Last 5 / Last 10 are in the Games dropdown.

## Situation log (automatic, saved in each game)

Nobody tags anything. Every time the game saves, each possession is checked against the Lineups situations
and the result is written into the game (`g.sitLog`): which situations it was in, both fives, the margin,
the clock you set, and what happened (points, stop, turnover, steal, FTs, whether they went to the line).
It travels with the game (backups, exports), is rewritten when a play is fixed, and games tracked before it
existed are filled in when the tracker opens.

| Situation | Tagged when (from the five's side) | Record |
|---|---|---|
| Closing FTs | our ball, up 1-8, late | pts / trip, FTs |
| Ball security | our ball, up 1-10, late | turnovers |
| Last stop | their ball, up 1-3, last minute | stops |
| Need steals | their ball, down 4+, late | steals, TOs forced |
| Need a 3 | our ball, down 4-9, late | pts / trip |
| Stop the run | their ball while they're on a 6-0 or more | stops |
| Stop fouling | their ball with our 7+ team fouls | trips without sending them to the line |

**Late is never estimated:** during a game, the clock you entered (4:00 or less in the 2nd half, any OT;
the last minute for Last stop); once the game is final, also the exact count of possessions left (the last
16 of the 2nd half; the last 4 for Last stop). The situations show as chips on the play-by-play sheet.

On Lineups every five shows **In this spot**: its record in that exact situation this season (quality
opponents once ratings are on the iPad), e.g. "6/6 stops · 2 games · counts 33%". The record moves the
five's ranking as the trips add up (weight trips / (trips + 12): 3 trips → 20%, 12 → 50%), so one lucky
night can't decide it. **PROVEN** = 6+ trips and better than our norm. Closing FTs also lists the fives'
record up 1-8 late (these five, the five on now, the best there).

## Runs tab

**Tabs** run in game order: Live · Report · Lineups · Scouting · Runs · Play-by-Play · Four factors · Sheet ·
Schedule · Rosters · Games. On the iPad the title shrinks to "Moorpark" so all the in-game tabs fit without
scrolling.

**Runs** tracks three things, ours and theirs (green = ours / red = theirs):
- **Kill** = 3 straight stops (6 = skunk, 9 = dead skunk), the tracker's kill rules.
- **Kill shot** = 10-0 unanswered (technical FTs count; it carries across the half), as on the Report.
- **Run** = 6-0 unanswered, or a spurt of +8 within 6 possessions each (10-2, 12-4); overlapping ones merge.

**This game / Season / Season · quality opp** (quality = positive adjusted net, needs the ⬆ Adjusted file).
It opens on This game during a game, Season otherwise. Garbage time is always out, and so are scrimmages.
- **Per game:** kills, kill shots, runs, and kill → skunk (how often a kill goes on to 6 straight stops).
- **Fives:** kills per 100 defensive possessions, kills allowed per 100 offensive, kills / kill shots / runs
  for and against. **KILLER** / **LEAKS KILLS** = 1.4x the team rate on 25+ possessions with 2+ kills.
  Kills are credited to the five on the floor at the 3rd stop; kill shots and runs to the five on when they
  started. **Tap a five** for every kill, kill shot and run it was on for: date, opponent, half and trip,
  score before → after, what started and ended it.
- **Kill shots:** every 10-0, with when, the score, our five, what started it and what ended it.
- **When kills start:** trips (possessions each) into each half, ours vs theirs: the possession count,
  never a clock estimate.
- **What starts and ends them**, for kills and for kill shots & runs. Started by: start of a half, out of
  their own timeout, after the other side's timeout, a fresh five (2+ subs), the other side just subbed 2+,
  after forcing a live-ball / dead-ball TO, after missed FTs, after a stop on a missed shot. Ended by: made
  3, made 2, foul → FTs, timeout then they scored, end of the half, technical FTs.
- **What stops their runs:** once they hit 6-0, did we call timeout, sub, or do nothing, and their points
  in their next 3 possessions (and the same for ours).
- **Players:** kills, kill shots and runs for / against while each player is on, and kill margin.

**Live:** under KILLS on the scoreboard, "1 more stop → kill" when we have 2 straight (or 5, 8). When they
have 2 straight stops on us: "2 stops on us · this five allows X kills / 100" (the season rate, once the
five has 25+ offensive possessions).

## Other tabs
- **Play-by-Play:** everything in order by period: each possession with its plays and the score,
  plus fouls, subs, technicals and timeouts. Filter by team. Tap any line to fix it.
- **Schedule:** the game tracker's Schedule tab, same look, same shared schedule.
  - Edit rows, Paste schedule, + Add game, Save schedule.
  - **Start game** opens the New game screen filled in for that row.
  - A tracked game shows its score, Open and Sheet.
- **Leaderboard stats on the iPad.** Every leaderboard build also publishes a stats file (record, averages for and
  against, advanced numbers, and every player's jersey number, season lines and advanced numbers) for each team on
  Moorpark's schedule and each potential opponent in the leaderboard's `tracker_teams.txt` (a tournament field: one
  team per line, short names ok). The tracker downloads the ones for teams we play, keeps them for offline gyms,
  and refreshes them after each build:
  - every team on the **schedule** (a team added to the schedule downloads as soon as you Save),
  - every team under **Teams to have ready** on the Schedule tab: type a tournament field once (short names work:
    RCC, CCSF, SBVC, East LA) and each team shows *✓ stats ready* with its logo, before you know who you play (a team
    the leaderboard doesn't publish says *not published: add to tracker_teams.txt*),
  - every opponent you keep a roster for.
  An opponent's THIS FIVE labels then come from his players' real numbers, matched by jersey number.
- **Rosters:** Moorpark and every opponent: #, name, position, height, year and **labels**.
  - **Roster · Basic · Advanced** (every team with leaderboard stats, Moorpark too): the leaderboard's Team Stats
    table. *Basic*: per-game lines (G, MPG, PPG, rebounds, AST, STL, BLK, TO, FG / 2P / 3P / FT, eFG%, TS%), sorted
    by PPG; tap a header to sort (the table stays scrolled where it was). The %Poss band labels stay pinned at the left when the table is scrolled right. *Advanced*: %Min, ORtg, %Poss, %Shots, eFG%, TS%, OR%, DR%, ARate, TORate, Blk%,
    Stl%, FC/40, FD/40, FTRate and the shooting splits, grouped like the leaderboard (Go-to Guys >28% of
    possessions, Major Contributors 24-28, Significant 20-24, Role Players 16-20, Limited Roles 12-16, Nearly
    Invisible <12, Benchwarmers <10% of minutes last), with a red **State Rank** line under each qualified player
    (the leaderboard's own ranks and rules; ORtg is ranked within the player's %Poss band, so a role player's
    efficiency is compared with other role players). The leaderboard's own table format (navy header, bold names, blue
    %Poss band rows, italic State Rank label with small red ranks), with light grey / darker grey alternating rows (a
    player's rank line shares his row) and centred numbers. Scrolls sideways with the player column pinned. Roster edits in
    progress are kept while you look.
  - An opponent shows its leaderboard line (record, ORtg / DRtg, net and rank, points per game) and
    **⬇ Fill from leaderboard**: adds everyone who played for them this season (by minutes, jersey numbers from
    the latest box score), keeping the numbers already on the roster. Check them, then Save.
  - Labels are short tags (Shooter, Lefty, Foul): type one and tap **Add** (or Enter); tap **✕** on a chip to remove
    it. While you edit a row, labels already used on any roster show as **+ quick picks** under it.
  - Opponent rosters are shared with the game tracker. Labels are saved as one comma-separated note
    ("Shooter, Lefty"), so the game tracker shows the same thing; an old one-line note splits on commas.
  - On the Live screen the position and labels sit on **one line** under the player's name, in the order you added
    them. What doesn't fit collapses into a grey **+N** chip; tapping it opens a small light-grey bubble above the
    card with every label, in yellow (the red ✕ with a black outline, any other tap — a game action button included — or 8 seconds closes it). It never logs anything; tapping the rest of
    the card works as before.
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
- **Scouting:** two tabs. **Last time vs <opponent>** (when we've tracked them before; it opens first) and the
  scouting PDF.
  - The **opponent file** is built from every game on this iPad against that team, plus their stat sheets — nothing
    to enter: what decided it (the full report's hurting / helping lines when a sheet was read, else the four
    factors), their biggest run and our best five, their lineups (most used, best against us), their players (sheet
    numbers and your notes) and their tendencies (pace, PPP, TO% / non-steal, eFG% / FT rate, kills, biggest run,
    timeouts after our runs). Two or more games → a chip per game plus All games.
  - Opened from: the Scouting tab (a LAST TIME badge shows when there's a file), 📄 Scout on the live screen,
    **📁 Last time** on the Schedule row, the New game screen (a line under the opponent with Open file) and the
    opponent's page on the Rosters tab.
- **Scouting PDF:** the scouting PDF. It shares the game tracker's stored PDFs, and the opponent's
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
