#!/bin/bash
# Wait for 2018-19 scrape to finish (100 schedule.json files), then launch 2017-18
SCHEDULES_DIR="/Users/chadoconnor/Neural Network/2018-19 Teams Schedules"
TARGET=100
echo "[$(date)] Watching 2018-19 scrape... waiting for $TARGET teams"
while true; do
  DONE=$(find "$SCHEDULES_DIR" -name "schedule.json" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$DONE" -ge "$TARGET" ]; then
    echo "[$(date)] 2018-19 complete ($DONE teams). Launching 2017-18 scrape..."
    launchctl load ~/Library/LaunchAgents/com.chadoconnor.scrape2017.plist
    echo "[$(date)] 2017-18 scrape launched."
    break
  fi
  sleep 30
done
