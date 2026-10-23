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
  estimate from possessions, and late and close leads the Huddle ("Clutch: up 2 with 0:50 left"). 4 full + 2 thirty-second a team, +1 thirty per OT (full = rectangles, 30s = dots). **± Fouls / TOs** fixes the counts: team fouls this half, timeouts, and every player's fouls on both teams (a player's + logs a foul on him, which also counts for the team; − takes off his latest foul; charges, offensive fouls and technicals are fixed in the log).
- **⏱ Set time** (scoreboard, beside ± Fouls / TOs): enter the game clock any time on the same big keypad
  (7, 4, 2 → 7:42). It works like a timeout's clock: time left, leverage, clutch and garbage time run from
  it, the scoreboard shows **Clock 4:30**, and it goes in the feed as "Game clock · 4:30" (tap it to fix or delete).
  Each period starts showing its full clock: **Clock 20:00** at tip-off and the start of the 2nd half, **5:00** each
  overtime, until a clock is entered. That start-of-period clock is display only: leverage keeps its possession
  estimate until you enter one (a 20:00 checkpoint would freeze "time left" for the whole half).
- **Picking a player:** once a stat is tapped, a tap anywhere on a player card picks him — his labels and the +N chip
  too (they only open their pop-up when no stat is waiting).
- **Auto rebounds.** Tap rebounds as always; one you forget is filled in from the next play, so a possession is never
  split: after a miss, the same team playing on (shot, FTs, turnover, the other side's steal) = their offensive
  rebound; the other team playing = its defensive rebound. Not between FTs of one trip, not across periods, not after
  **No rebound**. It shows as "(auto)" in the feed, a toast says so, and Undo takes it with the play. Games saved before
  get the same fill once (a backup is kept first: Games → Backups, "Before auto rebounds").
- **Free throws name the shooter.** The trip's first **FT Make / FT Miss**: tap the shooter's card (the player
  cards light up), or the team logo for team. The rest of the trip logs on the FT Make / FT Miss tap alone, to
  the same shooter (or team), with a note ("FT make · #3 Kubel"). A trip is free throws in a row by one team:
  a sub, timeout or Set time in between doesn't end it; a foul or any other play does, so the next trip asks
  again. Wrong shooter? Tap the line in the feed. The trip counts for the fives on the floor at the foul: subs at
  that stoppage (logged between the foul and the free throws) take over after it (lineups, +/-, on/off).
- **FT Shooter** (gold, two buttons wide, above FT Make / FT Miss): name the shooter before the shots. Tap it, then
  his card (either team); everything else is muted until you do (or Cancel). The button turns into **FTs: #8 ✕**
  and everything is live again: sub, timeout, log the foul. His FT Make / FT Miss taps then log straight to him
  (no card tap). The strip says which shot is next (**1 of 2**) and has **1+1 · 1 · 2 · 3** for how many he's shooting
  (2 to start; **1+1** when the fouling team is in the bonus, 7–9 team fouls: a front-end miss is the whole trip, a make
  earns the second — tap 2 for a shooting foul); after the last one the trip ends on its own (Undo of that shot brings it back). Until then he's **AT THE
  LINE**: greyed in Sub (and the lineup suggestions' Sub this five in), and taking him off asks first. Any other play
  (not a foul) clears him, and so does ✕.
- **No clock.**
- **Possession pill** (under the period; the pill fits its text, and the middle of the scoreboard is sized to this
  game's longest label: wider for a long opponent name like Mack Attack Prep, compact for Cuesta, the same all game,
  so changing the ball never moves the logos): moves only when you tap it — at the tip, at the start of the
  2nd half, after a jump ball. Plays, subs and timeouts never move it. Tapped mid-half it asks: **Held
  ball: steal** (a steal for the team that gets the ball, ending the other team's possession; shown as "steal (held ball)") or **Just switch**.
- **Team stats** (Huddle, Halftime report, Post-game report; with or without a stat sheet): Moorpark on the left, the
  stat in the middle, the opponent on the right, one row each, from the tracked plays: points, FG / 2PT / 3PT / FT
  made-attempted, each with its % on the next row (eFG% right after 3PT%, TS% right after FT%), offensive / defensive /
  total rebounds, assists, steals, blocks, turnovers, turnovers on steals, fouls; then possessions, points per
  possession, TO%, OREB%, DREB%, FT rate,
  3PA rate, 2nd-chance points and points off turnovers. The better number in each row is bold. The Huddle and Post-game show the game so far; Halftime shows the 1st half.
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
    *Closing FTs*) and its worst weakness (red ✕: *1 shooter*, *G can't shoot*, *No handler*, *Thin glass*, *TO risk*,
    *Foul-prone*, *FT #21*). Tap one: a light-grey bubble above it lists who earned it, with their numbers. Nothing
    is logged.
    - **Elite glass / Thin glass** are the five itself, not its players: its own OREB% and DREB% as a group from the lineup data
      (ours: every tracked game; theirs: every game we've tracked against them), 2+ points over (Elite) or under (Thin) the
      team's average over the same games at **both** ends, on 10+ rebound chances at each end. The bubble shows both with the team's.
    - **No handler**: nobody on the floor is listed at PG or is a *Floor general* (his stats label, or typed on his
      card). Pressure that five. Only when 4+ of the five have a position or a stats line; the bubble shows each
      player's position and assist rate.
    - The rest come from each player's season line (quality games: stat sheets / leaderboard; at halftime the 1st-half sheet
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
off, or put it back to automatic. Lineups can be filtered to Clutch, No garbage time or Garbage time only (who made the most of their minutes).

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
  - **The KILL flash:** the play that completes a kill flashes the word over the score bug, then it fades (about 2
    seconds; taps go through it): gold for ours, red for theirs. KILL at 3 straight stops, SKUNK at 6, DEAD SKUNK at 9,
    then DEAD SKUNK +1, +2... for each kill after that. Only on a play just logged, never on undo or a reload.
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
show the current five for each team: possessions, ORtg, DRtg, net and +/-. Each player's +/- rows start
minimized (every time the app opens); the boxed **+** at the card's top right shows them, **−** hides them again
(Moorpark's and the opponent's separately).

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
| Stop the run | they're on a run (6-0, or +8 holding us to 40%) | the stop-the-run score: most possessions, best net, fewest runs allowed = (net − 10 per run allowed per 20 def poss) × poss / (poss + 20); runs charged to the five on when they started; season = every game tracked here |
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
FTs tagged to a shooter in the last 5:00 of the 2nd half or OT within 5, in every game (scrimmages only until the first regular-season game is final),
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
rate start lowest-first). Filter All / Clutch / No garbage time / Garbage time only. **Season** adds up Moorpark's lineups and combos from every game tracked on the iPad.

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

**Halftime: lineups for what's hurting us, today and season.** A **What's hurting us** box on top (also in 💡 Try
and the situations) lists all four factors this half: us / them, our edge, and about how many points the gap is
worth, most points lost first, the ones we're losing in red. The points: eFG% gap × 2 × FGA; TO% gap ×
possessions × points per possession; OREB% gap × missed shots × points per possession; FT rate gap × FGA × FT%
(the two teams' averages this half). So a 2% TO% gap and a 15% rebounding gap can be weighed at a glance, and the
problem sections below come in the same order. Each four factor we're losing in the 1st
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

## Sub for a player (⏳ Pending)

Under the bench on the Pending screen, **On the floor** lists our five, each with a bar for how well he fits what we
need right now (same scoring as below, against the other four); the lowest is tagged **WEAKEST FIT**: who to take
out. Tap any of them (1-5, gold NEEDS A SUB) and the **top 3 subs** show right under it, on actual numbers only (no
projections), with nothing to choose:

**The pressing needs, automatic.** The four factor battles of this game so far (garbage time out), shown us vs them,
green = safe, gold = close, red = losing: eFG% · TO% · OREB% · FT rate. A battle's urgency = how far it is from a
5-point cushion (losing by 5 = 10, winning by 2 = 3, winning by 5+ = 0) × Dean Oliver's weight (shooting 40,
turnovers 25, rebounding 20, FTs 15). Each is split between our end and theirs by which side is worse than our
season norm: eFG → Shooting / Defense, TO → Ball security / Pressure, rebounding → Off / Def rebounding, FTs → Get
to the line / Fewer fouls. The needs show as gold chips with their share. Safely ahead everywhere: the closest
battle.

**Two versions**, labeled at the top: **STAT SHEET** once tonight's 1st-half (or final) sheet is read, which adds
each player's own line from it; **NO STAT SHEET**, where tonight is the tracker's numbers.

**Each player, four parts**, each a bar for where he ranks on our bench:
- **Fit (50%)**: for each need, the numbers that answer it, ranked and averaged: his **season analytics** (DR%,
  OR%, STL%, BLK%, TO%, ARate, TS%, eFG%, FT rate, fouls and fouls drawn per 40), his **season per 40 / %** (quality
  games), **how we do on that factor with him on the floor tonight and this season** (our DREB%, their eFG%, our
  TO%...), and in the stat sheet version **his line on the sheet**. Blended by the needs' shares; every number shows.
- **With the others (20%)**: our net per 100 with him on alongside each player staying in, this season + tonight.
- **Tonight (15%)**: our net per 100 with him on tonight and his +/-; plus how long he's sat, fouls (4 flagged), FTs.
- **Season (15%)**: his individual ORtg and our net per 100 with him on this season.
A number he doesn't have is left out; a part with none is left out and the others count for it.

**What you see** is kept short for the bench: one line on top, **Need Defense + Def rebounding** (the top one or
two), with why in plain words ("they're shooting 50.0% eFG · they're grabbing 32.3% of their misses"); then the
**top 3** (one coming out = 3 players; more = the 3 best groups), each with a few words on why ("best defender on
the bench · good with this group", "+11 tonight", "4 fouls") and its own **⏳ Pending** (at the table *for* the ones
coming out; the Live strip says "Checking in: X for Y" and ⇄ Sub opens with the swap made) and **⇄ Sub now**. A
footnote says whether tonight's stat sheet is in. ✕ clears. The opponent's bench stays on the right throughout.

## Fixing a sub (tap it in the feed)

Tap a sub (⇄ line) in the Live feed: both teams' rosters with the fives that were on the floor after it lit. Tap to swap
until the right fives are lit (GOING IN / COMING OFF show the change), Save. Every possession from that sub to the
next one is then counted with the fixed five: lineups, +/-, possessions in a row, on/off, the five on now, all worked
out from the plays. Later subs are whole fives, so a mistake usually rode along: **Fix the later subs too** (on by
default) makes the same swap in each later sub of that team that still has the wrong player, stopping once he's been
subbed out. Plays tagged to a player (fouls, free throws) stay his. The starting five can be fixed the same way (it
can't be deleted); any other sub can also be deleted from there. The other team's sub at the same moment (next to it
in the log) is fixed in the same window; if that team had none logged, changing its five adds one right after this
sub (a sub missed at the time).

## Box scores (📋 Box score CSV on the Report)

Upload the stats app's box score CSVs ("MC vs … — All Athletes — Averages", one per team; pick both at once). Which
file is which team is worked out from our roster. The Report's **Players** box then shows them in the game tracker's
box score (the same table a stat sheet photo fills): starters (the tracker's starting fives), BENCH, MIN, MIN%, ORTG,
USG, SHOT%, EFG, TS%, FTR, OR%, DR%, AST%, TO%, STL%, BLK%, 2PT, 3PT, FT, the counting stats and the box score's
+/-, with the TEAM line; players under 25% of the minutes (MIN%) greyed. **PF is always the tracker's** foul count for each player (as on
the player cards), never the file's, and our players' names are our roster's (by number). The **coaches' PDF** uses them too
(both teams' box and the top performers) when the game has no final stat sheet; its team stats stay the tracker's. Points are worked out
from the makes (the file heads its points column "PF"; fouls are its FOUL column). **Players only:** saved on the game
as its own box score, nothing else reads it, so team stats, the four factors, possessions and lineups stay the
tracker's. It travels with the game in exports and the baseline. The Mack Attack Prep box scores are built in (put on
that game once on each device).

## Free throws & fouls by player

From the shooter and fouler you tap, so it's there live with no stat sheet photo:
- **Live player cards:** `+/- +6 · 7 poss · FT 2-2`. *7 poss* = his current stint: possessions in a row on the
  floor, counted back from the latest finished one (a sub out or halftime resets it; overtime doesn't), both ends
  halved and rounded like the lineup tables' POSS, so you can see who on the five has been out there longest. FT
  made-attempted shows once a player has shot one.
- **Report** (halftime and post-game), under Team stats: a *Free throws & fouls* card, both teams side by
  side, one row per player with an FT attempt or a foul (FT, FT%, PF), Team for ones put on the team logo,
  and a gold Total row. Fouls include charges, offensive fouls and technicals, as on the cards.

## Lineup Builder and WOWY (as in the practice tracker)

**Lineup Builder**, above the Moorpark lineup table: one dropdown per player of the size you're on (5-, 4-,
3- or 2-man). Pick a player and the other slots only offer players who actually shared the floor with him
under the current scope (game / half / season) and leverage filter; the table narrows to the units with every
pick, so a full pick is one row. A pick that stops fitting after a filter change is kept and the panel says
so. Clear empties it.

**Min. possessions**, the slider under the Lineup Builder (as on the practice tracker): units with fewer
possessions together are hidden in both lineup tables on the Lineups tab, live as you slide, with "N of M
fives" beside it. Starts at 1; remembered on this iPad. Report tables always show every unit.

**WOWY** (With Or Without You), the button after 2-man: five slots, pick 2-5 of our players and every on/off
combination of them gets a row (2 picks = 4 rows, 3 = 8 ...): GP, possessions, +/-, ORtg, DRtg, net and the
four factors at both ends, over the possessions with exactly that pattern on the floor (green chip = on, red =
off). Off means he sat: a game only counts if every pick played in it; the others are counted under the table.
Moorpark only (the opponent lineups are hidden in WOWY). Combinations that never happened stay, dimmed and last. Always the whole season (every game tracked, scrimmages in), whatever the Lineups scope; the leverage filter applies.

**Lineups opens on Full season.** The controls sit in one panel: **Games** (This game or a season split), **Half**, **View** (5- to 2-man, WOWY), then **Possessions** and **Situation**. **Scope** on Lineups: a dropdown of **This game** or a **season split** (as CBB Analytics has them), then **All · 1H ·
2H · OT** and the Possessions filter on top. Splits (game counts shown): Full season, Last 5, Last 10, Conference,
Non-conference, Conference wins / losses, Postseason, Home, Away, Neutral, Away + neutral, Games won / lost,
**Q1A, Q1, Q2, Q1 + Q2, Q3, Q4**, vs top 25 / outside the top 25, and Select your own games (a
chip per game). Quads are the leaderboard's (its Quads tab), exactly: opponents ranked by net among every rated team,
NCAA cutoffs of 353 scaled to the league (Q1A home 15 / neutral 25 / away 40, Q1 30/50/75, Q2 75/100/135, Q3
160/200/240, Q4 the rest); Q1 includes Q1A and Q1 + 2 includes Q1A, Q1 and Q2. They use the nightly ratings. Scrimmages count in every split only until the first regular-season game is Final
(Nov 2, Antelope Valley): until then every game adds to who's played together and the sample; after it they drop
out of every season number (lineups, WOWY, the Season report, the situation lineups like Stop the run, clutch FTs)
on their own. The scrimmage games stay on the iPad and
open one at a time. **No scrimmages** leaves them out sooner. Season 2H =
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
On / Off / Diff (green = team better with him on), in alternating light grey / darker grey rows. The Defense panel ends with **PF Efficiency, Steals / PF and
Blocks / PF** (the version before paint / transition / off-turnover points). Differences from practice: minutes
are his share of each half's possessions (a half = 20 min), possessions are the real count, and assists, blocks
and deflections aren't logged in games (—), so PF Efficiency is steals per foul. Ratings and four factors are
opponent-adjusted (Data → Show raw numbers for raw).
**Shooting** checkbox (top of the on / off view, remembered): adds a Shooting panel to every card, 3rd in the left column
(under Core Stats and Offense & Activity),
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
| Stop the run | both ends, from when their run counts (6-0, or +8 holding us to 40%) until our first score after its peak ends it | stops on their trips; its line adds our points on our trips and **runs ended** (the five on when that score went in) |
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
- **Kill** = 3 straight stops (6 = skunk, 9 = dead skunk), the tracker's kill rules. A stop counts only once the possession is
  over: a defensive rebound, turnover, steal, charge or offensive foul, the other team having the ball next, or the end of
  the half. A miss still waiting for its rebound is no stop yet, so an offensive rebound and a basket never make (or
  flash) a kill.
- **Kill shot** = 10-0 unanswered (technical FTs count; it carries across the half), as on the Report.
- **Run** = 6-0 unanswered, or outscoring the other side by 8+ while holding it to 40% of your points or less
  (10-2, 12-4, 15-6, 22-5; never 8-7 or 14-7). It runs inside a half from your first points to your peak margin,
  however long that is, and stops at the other side's own 6-0. The score bug shows the run going on now
  ("MPK 22-5 run"), and so do the Huddle and the Stop the run lineup call.

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
  - Edit rows, Paste schedule, + Add game. Edits save as you make them (date, time, site, opponent, Conf, Scrim), so
    switching tabs never loses one; a new row saves once it has a date and an opponent. Save schedule sorts and checks.
  - **TBD games** (a tournament) pick their opponent from a dropdown: that tournament's own field in **Teams to have
    ready** (full names: RCC → Riverside), plus **Other…** to type any team. The pick saves right away and keeps its
    dropdown so it can change; the tournament's name stays under the game. A tournament with no field yet keeps a text box.
  - **Teams to have ready** has a section per tournament on the schedule (its name and dates, from the TBD games'
    event), each with its own Add box, plus **Other teams**. Every team in every section downloads its stats
    (pt2_fields / pt2_ready). An old single list moved, once, into the next tournament with TBD games.
    The known fields come filled in once on each iPad (San Bernardino: West LA, East LA, RCC, CCSF, Chaffey, Compton,
    SBVC; Grossmont: San Diego City), and a saved schedule gets its known first-round opponents (West LA Nov 13, San
    Diego City Dec 4, flexed from LA Trade Tech: a saved LA Trade Tech game and field entry switch over once), and its tournament games move to their dates (San Bernardino Nov 13–15, Grossmont Dec 4–6). Each later tournament game is a dropdown of that field (Other… types anyone): pick the
    opponent once the bracket says who's next.
  - **Start game** opens the New game screen filled in for that row.
  - A tracked game shows its score, Open and Sheet.
- **This season only.** Ratings, team stats (Moorpark's too), stat labels and scouting reports are 2026-27 only
  (`TRACKER_SEASON`); until the season has stats they're empty, and the iPad drops any older season's saved copies
  the next time it opens with signal. Labels you typed yourself stay.
- **Scouting reports on the iPad.** Every scrape that brings in new box scores also remakes the scouting report of each
  team that played and is on our schedule or in a tournament field (`poss/reports/`, one current PDF each, listed in
  `reports/index.json`). When the tracker opens with signal it saves each new one on the iPad, and **📄 Scout** opens
  the opponent's latest report (a PDF you added for that game or opponent still comes first; every report is in the
  picker). Works offline once saved.
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
- **Rosters:** Moorpark and every opponent: #, name, position, height, year and **labels**. A dropdown at the top picks the team: Moorpark,
  our schedule (date order), each tournament field, other teams to have ready, and any other saved roster (✓ = one is
  saved). Any team on it can be edited; Save creates its roster.
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
  - **Labels guide:** the **Labels** button in the Moorpark header on the Live screen (and **Labels guide** on
    Rosters) opens a glossary of every label and what earns it.
  - **Labels from stats** (the same solid gold, square chip as yours, filled everywhere; yours come first, except *Star*, which is always first): every player, ours and every opponent with a
    leaderboard file, gets labels that say who he is, how he scores and what else he does, from his season numbers
    qualified against the state (the leaderboard's State Ranks; top 20% = a strength, bottom 20% = a weakness unless
    noted). Roles are **composites**: each blends the related stats as state percentiles (e.g. Interior scorer = 2P%,
    share of shots inside, FT rate, 2PA a game, OR%), and when the team has a Synergy export its shot-type percentiles
    (at the rim, 3PT, catch-and-shoot, pull-up) join the blend. Each composite's cut is calibrated on the state's scores (`export_ratings.py` COMPOSITES; team files carry
    `comp` / `compCut` / `syn`); older files fall back to the single-stat rules. A player can have several; the card
    shows them in this order:
    - **Role:** *Star* (the state's top 20, North and South together: PORPAGATU! on analytics teams, and on
      teams without reliable minutes Game Score per game placed on the same list) · *Scorer* (top 10% on points
      produced a game, points a game and usage; not with Star) · *Go-to* (over 28% of
      possessions; not with Star or Scorer) · *Sixth man* (his team's best bench player: starts 35% or
      fewer of his games and 3 or fewer of the last 10, 15+ minutes, tops their bench on minutes, usage and points produced) · *Glue guy* (usage under 17%, low scoring,
      but top 30% in three or more of OR%, DR%, Stl%, Blk%, assist rate) · *Help off* (a starter who doesn't score: starts 60%+ of his
      games, under 5 points a game, usage under 16%; shown even below the who-plays bar) · *2nd option* (his team's second-leading scorer:
      10+ ppg and 1.5+ ahead of the #3; none on a balanced team; not with Star or Scorer) · *Efficient role player* (top 10% of his %Poss band on ORtg, under 20% usage) · *Inefficient
      volume* (24%+ usage, TS% bottom 30%).
    - **How he scores:** *Interior scorer* (2P% top 20% on 4+ two-point tries a game, threes under 25% of his shots) ·
      *Finisher* (threes under 20% of his shots, TS 58%+, not
      already an Interior scorer or Slasher) · *All-Around* (TS% top 35%, 25-55% of his shots threes, FT rate top half; plain *Shooter* is implied and left off, *Elite shooter* still shows) · *Balanced* (All-Around's mix without its efficiency bar: 30-55% of his shots threes, FT
      rate top half, 20%+ of possessions) · *Slasher* (a non-shooter who gets to the line) ·
      *Draws fouls* (FD/40 top 20% or FT rate top 15%) · *Struggles inside* (2P% bottom 20%) · *3PT heavy* (55%+
      of his shots threes, 2.0+ a game).
    - **The shooting call:** every player who plays gets exactly one, from his own threes, never a state rank. It's
      what a three from him is worth against an average trip (the state's rotation players shoot 32.4% = 0.97 points
      a shot). *Est.* = his 3P% as if he'd also taken 25 threes at 32.4%, so one hot or cold night doesn't flip it:
      *Shooter* (close out: est. 35%+ = 1.05+ points a three; *Elite shooter* = the top 10% of those; plain Shooter
      is left off when he's *All-Around*) · *Avg 3PT* (guard him straight: 30-35%) · *Poor 3PT* (let him shoot:
      under 30% = under 0.90 points a three) · *Non-shooter* (sag off: under 15 threes, or under 10% of his shots).
      The bubble shows his 3P%, the est. and the points a three.
    - **Glass:** *Glass cleaner* (OR% and DR% both top 20%) · *Rebounder* (DR%) · *Off. rebounder* (OR%).
    - **Ball:** *Floor general* (assist rate top 10%, not turnover-prone) · *Passer*
      · *Non-passer* (assist rate bottom 10%) · *TO-prone*.
    - **Defense:** *Ball hawk* (Stl%) · *Rim protector* (Blk% top 15%) ·
      *Foul-prone*. **FT:** *FT shooter* (75%+: don't foul him late) · *Bad FT* (under
      65%: foul him), both only for players who get to the line: 2+ FTA a game in half the team's games,
      on 2 attempts per team game played (up to 40). (No Ball secure or Disciplined: only who *isn't* those things matters: TO-prone, Foul-prone.)
    Teams with analytics get ranked labels only (a player there with too few minutes to be ranked just doesn't get
    that label). Low-info teams (no reliable minutes) are judged against the same state cuts on what needs no minutes:
    the scoring labels from TS%, 2P%, FT rate, shot diet and 3P% (their percentile among the state's qualified players),
    and Rebounder / Off. rebounder / Glass cleaner, Ball hawk, Rim protector, Passer / Floor general, Non-passer and
    TO-prone from per-game numbers and per-possession ratios (export_ratings.py box_pct); the per-40 estimate is the
    last fallback. Only players who play get these (30%+ of the minutes on teams with analytics; on teams without reliable minutes,
    4+ points or 3+ rebounds a game over half the games), so end-of-bench samples don't.
    (The ★ team-leader labels, Top scorer and the rest, are gone: low-info players get the state labels.) The +N bubble shows label names only (each label's numbers are kept for a future player page). In the roster editor they
    sit under **From stats**: ✕ turns one off for that player (it stays off), + brings it back. A label you typed
    already isn't repeated.
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
- **Report:** opens by itself: **End 1H** brings up the Halftime report (its **Start 2nd half** button puts the
  2nd-half starting fives on the Live screen: a panel, not a pop-up, that stays until each team's five is confirmed with
  its own **Confirm** button; logging is paused until both are in, and the other tabs work meanwhile), and **Final** brings up the Post-game report.
  Under the score: each team's **largest lead** (and the score then), **lead changes** and **ties** (0-0 aside), from
  the logged points in order: the 1st half on the Halftime report, the game on the Post-game report and under the
  score on the coaches' PDF.
  After Final, Live stops taking plays and shows the final score with **Start next game →** (the new-game setup),
  **Post-game report** and **Reopen game**. The report has a **game list** at the top (every game played, newest
  first); it stays on the last game played, even after Live moves on to the next one, and opens each game on its
  latest report: Post-game once it's final, Halftime until then (the buttons still switch).
- **Game list** at the top of Report, Play-by-Play, Sheet and Four factors: pick any game played (newest first); the
  pick carries across them and is Lineups' and Runs' **This game**. Report also has **Season** (the **Season report**:
  record, each game's score and PPP, tap one to open it, and the team stats summed over every game, scrimmages
  included and marked). Lineups and Runs keep their own Game / Season controls and open on Season. By default the game
  is the one in progress once it has a play, else the last game played, so between games (Live on the new-game setup)
  nothing goes blank. Halftime, Final and starting a game move the pick to that game. Both start with
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
- **Scouting:** two tabs. The **scouting PDF** (📄 Scout and the Scouting tab open on it) and **Last time vs
  <opponent>** (when we've tracked them before; 📁 Last time on Schedule / Rosters opens straight to it).
  - The **opponent file** is built from every game on this iPad against that team, plus their stat sheets — nothing
    to enter: what decided it (the full report's hurting / helping lines when a sheet was read, else the four
    factors), their biggest run and our best five, their lineups (most used, best against us — ranked by net weighted for sample size, as if each five had also played 50 possessions at even, so 18 possessions at +40 outranks 5 at +100; under each five its ORtg, DRtg and net, and the four factors at both ends: Off = their offense, Def = ours against that five), their players (sheet
    numbers and your notes) and their tendencies (pace, PPP, TO% / non-steal, eFG% / FT rate, kills, biggest run,
    timeouts after our runs). Two or more games → a chip per game plus All games.
  - Opened from: the Scouting tab (a LAST TIME badge shows when there's a file), 📄 Scout on the live screen,
    **📁 Last time** on the Schedule row, the New game screen (a line under the opponent with Open file) and the
    opponent's page on the Rosters tab.
- **Scouting PDF:** the scouting PDF. It shares the game tracker's stored PDFs, and the opponent's
  opens first.
- **Games:** new game, open, export / import, delete, the Moorpark roster.
- **Your data and updates.** Updating the tracker replaces its code, never your games: they live in the iPad's
  website storage, apart from the app's offline files. What *can* wipe them: deleting the home-screen icon, or Safari →
  Clear History and Website Data. The home-screen app and a Safari tab keep separate data: always open it the same way.
- **Post-game report PDF** (for the staff, ready to text): at **Final** it downloads next to the game file as
  `Moorpark_vs_<Opponent>_<date>_postgame.pdf` (Files → Downloads). Dark, Letter size. Page 1: the score, by half,
  key numbers (PPP, eFG%, 3P%, TO%, OREB%, FT rate), what decided it (written out from the numbers), runs, lineups
  (most used, best, worst). Page 2: team stats. With the final stat sheet read in, the counts come from the box score,
  the top performers join what decided it, and both teams' box scores follow (+/- from the tracker, game score).
  **📄 Coaches' PDF** on the Post-game report makes it again (say, once the stat sheet is in). Made on the iPad with no
  signal needed (html2canvas + jsPDF in `vendor/pdf`, MIT, saved for offline).
- **Rosters from the stats.** Every opponent with a stats file on the iPad (our schedule and tournament fields, once
  the season's games are scraped) gets its roster filled automatically: number and name of everyone who has played
  (zero-padded numbers like 01 read as 1). A roster you've never saved keeps getting new players as they appear; one
  you've saved stays as you made it (removed players stay removed) and only gets blank names filled. Height and year
  aren't in the stats.
- **Opponent rosters travel with the files.** A game file carries its opponent's roster (names, position, height,
  year, labels) and the baseline / a season file carries every roster, so a roster you type is in the next baseline you
  make and every iPad gets it. Each **Save** stamps the roster; importing keeps, team by team, the most recently saved
  one: a newer save replaces this iPad's roster for that team (players added *or taken away*), an older one is ignored,
  an empty roster always takes it. (The home-screen app and a Safari tab keep separate storage, so this is also how a
  roster typed in one reaches the other.)
- **Confirmed rosters** (SEED_ROSTERS in app.js, e.g. Mack Attack Prep's 13 numbers) are set once on each device:
  the roster becomes exactly those numbers, keeping anything already typed on them, stamped so it wins over an older
  baseline / game-file copy. A roster saved after that stamp is left alone.
- **A roster that only lives in a game shows on Rosters too.** When the tracker opens (and after importing a game,
  a season file or the baseline), each game's opponent roster is copied into the Rosters store if that team is
  missing there or has missing players / blank fields. Fill-only: a roster saved by hand on Rosters is never touched.
- **Game file downloads automatically** at the end of the 1st half (`poss_<date>_<opponent>_half.json`), at the end of
  regulation when the game goes to OT (`..._reg.json`), at the end of each OT that goes to another (`..._ot1.json`,
  `..._ot2.json`…) and at Final (`..._final.json`): a copy off the iPad, in Files → Downloads. Games → Import game reads it back.
- **Backups** (Games tab): a full copy of each game, kept on the iPad apart from the live data, at the end of the 1st half, at
  the end of regulation and each OT, at Final, before a delete or an import replaces it, and every 5 minutes while tracking (the last 3 of those per game).
  **Restore** puts one back (the game as it is now is backed up first); a deleted game comes back too.
- **Season backup file** (Games tab): **Export season** saves every game, the rosters, the schedule and the label /
  tournament settings in one file (iPad: Save to Files / Drive); the card shows when it was last saved and turns red
  after 7 days. **Import season** adds the file's games (one already here is replaced only if the file's copy has more
  plays, after a backup) and fills rosters / schedule / settings this iPad doesn't have. After Final a reminder says so.
- **The season baseline** (encrypted, on the site): Games → **Make baseline file** saves the season (as Export
  season) locked with a passcode you choose (PBKDF2-SHA256 250k → AES-GCM; the passcode never leaves the iPad). Put that
  file on the site as `poss/baseline.enc.json`. When the tracker opens and the site's baseline is newer than the last
  one merged on that iPad, it asks for the passcode once (remembered after), unlocks it and merges it like Import
  season: adds what's missing, replaces a game only with a longer copy, never deletes. A new or wiped iPad is never
  blank. The site is public; without the passcode the file is unreadable. The baseline is saved for offline use.
- **Old data always comes forward** (backup.js upgradeGame): every game, from the iPad, a game file, a season file or a
  backup, is upgraded to the current format before it's used; everything else is worked out fresh from the plays.
- **Saved reports** (Games tab): a copy of each halftime and post-game report as it was, kept on the iPad apart
  from the game, so it stays even if the game is edited or deleted. They save themselves at **Start 2nd half**,
  at **Final** and whenever a stat sheet is saved; **💾 Save report** on the report saves one any time. One halftime
  and one post-game copy per game (the newest kept). **Open** shows it as saved with Print / PDF; **Delete**
  removes it.

Games are saved on the iPad (localStorage `pt2_games`), and the app works offline once opened. **Updates:** the home-screen app can stay
open in the background for days, so each time it opens or comes back to the front it checks the site for a newer
version and shows a **New version · Update** bar (it never reloads on its own, so a game is never interrupted). Every team logo
(`game/logos/`, ~1.8 MB) is saved for offline as soon as the app opens with signal, so an opponent's logo shows in a gym
with none even if it was never opened before.
The page is built from the game tracker's stylesheet, copied into `poss/index.html`. If the game
tracker's look changes, copy its `<style>` block across again.
