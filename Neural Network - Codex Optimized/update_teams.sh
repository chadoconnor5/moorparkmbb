#!/bin/bash
# Nightly in-season update: box scores posted today (or yesterday before 6 PM),
# re-checks of games still missing stats, and a few team-page refreshes.
# See "Terminal Commands README.md" -> Daily Scraping.
#
# Cron setup (runs nightly at 11:45 PM):
#   crontab -e
#   45 23 * * * "/Users/chadoconnor/Neural Network - Codex Optimized/update_teams.sh" >> "/Users/chadoconnor/Neural Network - Codex Optimized/scrape_state/nightly.log" 2>&1
#
# Build the master schedule once before the first nightly run:
#   python3 scrape.py master

set -e
cd "$(dirname "$0")"

echo "=== Nightly scrape: $(date) ==="
python3 scrape.py nightly
echo "=== Done ==="
