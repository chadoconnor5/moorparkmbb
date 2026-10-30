@echo off
rem Moorpark NIGHTLY: run this once a night, after the games are final.
rem Goes to the project folder, gets the latest code, then runs the nightly scrape
rem (screenshots first, then the site, then rebuild and push). The window stays open at the end.
cd /d "%USERPROFILE%\Documents\GitHub\moorparkmbb\Neural Network - Codex Optimized"
if errorlevel 1 (
  echo Could not find the project folder: %USERPROFILE%\Documents\GitHub\moorparkmbb\Neural Network - Codex Optimized
  pause
  exit /b
)
echo ============================================================
echo  MOORPARK NIGHTLY  -  run ONCE a night, after games are final
echo ============================================================
echo.
echo Getting the latest code...
git pull
echo.
echo Running the nightly scrape (about 10-15 minutes). A Chrome window opens minimized - leave it alone.
echo.
python scrape.py nightly --browser
echo.
echo ============================================================
echo  Done. Look above for:  Pushed: scrape.py nightly ...
echo  If it says STOPPED: do NOT run it again tonight.
echo ============================================================
pause
