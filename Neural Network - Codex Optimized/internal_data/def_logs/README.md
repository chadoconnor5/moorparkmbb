# Defensive logger exports → measured lineup defense

Drop **CSV exports from `defensive_logger.html`** here (the "Export CSV" button →
`def_<date>__<opp>__<venue>.csv`). `compute_moorpark_lineups._load_logged_defense()`
scans `*.csv` in this folder on every build.

For each logged game it counts the **actual opponent possessions** each Moorpark
lineup faced and attaches a `measured_def` block to every combo (1–5 man + team)
the logger covers:

- `def_poss` — counted defensive possessions (the real DRtg **denominator**, vs the
  season CSV's `pf/ppp` offensive estimate)
- `drtg` — opp points / counted def poss × 100
- `opp_efg`, `opp_tov`, `opp_ftr`, `opp_3par`, `opp_2pp`, `opp_3pp`, `dreb_pct` —
  the opponent four-factors-allowed Hudl never breaks out per lineup
- `pip100`, `scp100`, `pot100` — opponent points in paint / second-chance / off
  turnovers allowed, per 100

**Scope / conventions:**
- **Competitive only** — possessions flagged garbage-time are excluded.
- **Possession-grain** — each possession (its opp points + event detail) is
  attributed to its **finishing** 5-man lineup, keeping the DRtg numerator and
  denominator at the same scope.
- `measured_def` is kept **separate** from the season opponent-adjusted ratings on
  purpose: it measures D over the logged sample (a subset of games) and would mix
  scopes if it clobbered the season `drtg`. As more games are logged it converges
  to the full season.
- Empty folder → pipeline is unchanged (`def_logged: false`).

Join key is the sorted set of 5 jersey numbers — identical on both sides.
