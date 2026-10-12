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
- **Fouls**: team fouls per half (2nd half carries into OT), with BONUS at 7 and DOUBLE BONUS at
  10. Foul trouble: tap a player to add his foul and a team foul; − takes one off.
- **Timeouts**: 3 full + 4 thirty-second per team for the game, plus one 30 per overtime.
- **Periods**: 1H, + starts 2H, then OT1, OT2… Tap a period to look at or fix its sheet.
- Tap any row of the sheet to change it, delete it or insert a missed one above it. ↶ Undo takes
  back the last thing logged.
- ⋯ menu: game details, roster, print / PDF (every period's sheet + summary), export / import.

Games are saved on the iPad (localStorage `pl_games`) and it works offline once opened.
