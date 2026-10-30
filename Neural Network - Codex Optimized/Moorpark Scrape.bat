@echo off
rem Python reads and writes UTF-8 (the leaderboard page has characters Windows' default can't save)
set PYTHONUTF8=1
rem Moorpark scraping: opens Command Prompt in the project folder and gets the latest code.
rem Copy this file to the Desktop and double-click it (it works from anywhere).
cd /d "%USERPROFILE%\Documents\GitHub\moorparkmbb\Neural Network - Codex Optimized"
if errorlevel 1 (
  echo Could not find the project folder: %USERPROFILE%\Documents\GitHub\moorparkmbb\Neural Network - Codex Optimized
  pause
  exit /b
)
echo Project folder: %CD%
echo Getting the latest code...
git pull
echo.
echo Ready. Paste a command from SCRAPE COMMANDS.txt, for example:
echo     python scrape.py nightly --browser
echo.
cmd /k
