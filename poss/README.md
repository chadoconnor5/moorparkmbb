# Possession Tracking (digital jamboree sheet)

`chadoconnor5.github.io/moorparkmbb/poss/` — the paper possession sheet on the iPad, portrait.
Separate from the game tracker (`/game/`); it reads the game tracker's roster and opponent
names on the same iPad but never writes to them.

- **One tap per opponent possession**, at the end of it: 2, 3, FT (then how many made), ✗2, ✗3,
  ✗FT, TO (dead ball), STL (steal), CHG (charge, also a foul on them). Player # is optional:
  type it on the pad or tap a recent number first. **And-one +1** and **Their off. reb** apply
  to the next possession you log.
- Stops, **kills** (3 stops in a row; the count restarts after each kill, any score, and each
  period), points per possession and the sheet's subtotals are worked out for you.
- **Moorpark score**: +1 / +2 / +3 (−1 to fix) under the score — it gives Moorpark's PPP. Our
  possessions are the same count as theirs, as on the paper sheet.
- **Fouls**: team fouls per half (2nd half carries into OT), + / − for each team, with BONUS at 7
  and DOUBLE BONUS at 10. A charge adds one to theirs. **Moorpark fouls**: tap a player for his foul
  and a team foul (− takes one off); blue edge = on the floor, red at 5 fouls or 2 technicals.
- **T — Technical**: team, player or coach, free throws made (0–2). On a player it is always his
  foul and a team foul; on a coach, neither (a second on the same coach flags the ejection). The
  free throws count in the score and PPP but are not a possession; the sheet shows a red T line.
  No game clock anywhere — nothing in this tracker asks for a time.
- **Timeouts**: 3 full + 4 thirty-second per team for the game, plus one 30 per overtime.
- **Subs / lineups**: ⇄ Sub, tap players on and off until five are lit, Confirm (at the top).
  A new game and each new period open it for the starting five. "Counts from possession" steps
  back to credit a sub you entered late. Every possession and Moorpark basket carries the five on
  the floor; the sheet shows a blue line where the five changes, and **Lineups** counts how each
  five's possessions ended (2, 3, FT, ✗2, ✗3, ✗FT, TO, STL, CHG) with their points, PPP and kills —
  for the game or the current period.
- **📊 Four factors**: type each team's totals from the printed box score (FGM, FGA, 3PM, 3PA, FTM,
  FTA, OREB, DREB, AST, TO) on the number pad — **1st half** at halftime, **Full game** at the end;
  **2nd half** is the difference. Out come eFG%, TO%, OREB%, DREB%, FT rate, 3PA rate, AST rate,
  FG/3P/FT%, points, possessions (FGA − OREB + TO + 0.475 × FTA, as in the game tracker) and PPP.
- **📄 Scout**: the scouting report PDF. Uses the same PDFs as the game tracker on this iPad (the
  opponent's opens first); Add PDF… stores a new one for offline use.
- **Periods**: 1H, + starts 2H, then OT1, OT2… Tap a period to look at or fix its sheet.
- Tap any row of the sheet to change it, delete it or insert a missed one above it. ↶ Undo takes
  back the last thing logged.
- ⋯ menu: game details, roster, print / PDF (every period's sheet, lineups, four factors, summary), export / import.

Games are saved on the iPad (localStorage `pl_games`) and it works offline once opened.
