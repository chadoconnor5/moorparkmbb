# Internal 2025-26 Player Role Classification

This is an internal-only workflow and is not wired into leaderboard generation.

## Files
- `internal_build_player_roles_2025.py`: Builds role probabilities + labels from `2025-26 Team Statistics` player box score aggregates.
- `internal_scrape_roster_heights_2025.py`: Attempts to scrape roster links from the CCCMBCA roster index and output heights CSV.
- `internal_data/roster_heights_2025_26.csv`: Height input file (`team,player,height,source_url`).

## Run
1. Build no-height baseline:
   `python3 internal_build_player_roles_2025.py`
2. Scrape heights (if site allows):
   `python3 internal_scrape_roster_heights_2025.py`
   If the index page blocks scripted access, add URLs to `internal_data/roster_links_2025_26.txt` and run:
   `python3 internal_scrape_roster_heights_2025.py --links-file internal_data/roster_links_2025_26.txt --insecure`
3. Rebuild with heights:
   `python3 internal_build_player_roles_2025.py --height-csv internal_data/roster_heights_2025_26.csv`

## Outputs
- `internal_analysis/player_role_classification_2025_26.json`
- `internal_analysis/player_role_classification_2025_26.csv`
- `internal_analysis/player_role_classification_2025_26_summary.json`

## Notes
- If CCCMBCA blocks scripted requests, `internal_scrape_roster_heights_2025.py` will log failures to:
  `internal_data/roster_height_failed_urls_2025_26.json`
- In that case, you can still manually populate `internal_data/roster_heights_2025_26.csv` and rerun classification.
