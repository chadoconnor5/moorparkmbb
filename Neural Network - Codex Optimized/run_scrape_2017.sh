#!/bin/bash
cd "/Users/chadoconnor/Neural Network"

# Find python3 - try common locations
PYTHON=$(which python3 2>/dev/null || echo /opt/homebrew/bin/python3)

while true; do
  $PYTHON scrape_team_2017.py --all --skip-existing >> scrape_2017_log.txt 2>&1
  DONE=$(grep -c "^Saved:" scrape_2017_log.txt 2>/dev/null || echo 0)
  echo "[restart] $(date): $DONE/96 done, exit $?" >> scrape_2017_log.txt
  if [ "$DONE" -ge 96 ]; then
    echo "[done] $(date): All 96 teams scraped." >> scrape_2017_log.txt
    break
  fi
  sleep 5
done
