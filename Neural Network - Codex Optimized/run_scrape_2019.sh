#!/bin/bash
cd "/Users/chadoconnor/Neural Network"
while true; do
  echo "[$(date)] Starting scrape..." >> scrape_2019_log.txt
  python3 -u scrape_team_2019.py --all --skip-existing >> scrape_2019_log.txt 2>&1
  code=$?
  if [ $code -eq 0 ]; then
    echo "[$(date)] Scrape completed successfully." >> scrape_2019_log.txt
    break
  fi
  echo "[$(date)] Process exited with code $code, restarting in 120s..." >> scrape_2019_log.txt
  sleep 120
done
