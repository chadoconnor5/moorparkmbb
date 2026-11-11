@echo off
rem Python reads and writes UTF-8
set PYTHONUTF8=1
rem Moorpark SYNERGY: after downloading Synergy leaderboards (.xlsx) to Downloads, double-click this.
rem Gets the latest code, loads every Synergy export in Downloads, deletes each one it loaded (a file it
rem couldn't read is left there), then pushes them so the labels use them. The window stays open at the end.
cd /d "%USERPROFILE%\Documents\GitHub\moorparkmbb\Neural Network - Codex Optimized"
if errorlevel 1 (
  echo Could not find the project folder: %USERPROFILE%\Documents\GitHub\moorparkmbb\Neural Network - Codex Optimized
  pause
  exit /b
)
echo ============================================================
echo  MOORPARK SYNERGY  -  loads the Synergy leaderboards in Downloads
echo ============================================================
echo.
if not exist "%USERPROFILE%\Downloads\Leaderboards*.xlsx" (
  echo No Synergy leaderboards in Downloads ^(files named Leaderboards ... .xlsx^). Nothing to do.
  echo.
  pause
  exit /b
)
echo Getting the latest code...
git pull
echo.
echo Loading the Synergy leaderboards...
echo.
python import_synergy_leaderboard.py "%USERPROFILE%\Downloads\Leaderboards*.xlsx" --delete
echo.
echo Pushing them...
git add -A -- internal_data/synergy_leaderboards
git diff --cached --quiet && (
  echo Nothing new: Synergy had the same numbers as last time.
) || (
  git commit -q -m "Synergy leaderboards (Moorpark Synergy.bat)"
  git push && echo Pushed. The labels use them from the next nightly ^(or rebuild^).
)
echo.
echo ============================================================
echo  Done. Look above for any "NOT LOADED (kept)" lines.
echo ============================================================
pause
