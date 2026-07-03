#!/bin/bash
# Daily update script for CCCMBCA team data.
# Run manually or schedule via cron/launchd.
#
# Cron setup (runs daily at 6 AM):
#   crontab -e
#   0 6 * * * /Users/chadoconnor/Neural\ Network/update_teams.sh >> /Users/chadoconnor/Neural\ Network/2025-26\ Teams\ Schedules/update.log 2>&1
#
# To add/remove teams, edit the TEAMS array below.

set -e
cd "$(dirname "$0")"

TEAMS=(
    "Moorpark"
)

echo "=== Team Update: $(date) ==="

for team in "${TEAMS[@]}"; do
    echo "Updating $team..."
    python3 scrape_team.py --teams "$team"
done

echo "=== Done ==="
