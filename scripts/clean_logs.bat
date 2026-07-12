@echo off
cd /d "%~dp0.."

if not defined TGARCHIVE_MENU (
    echo NOTE: meant to be launched from TGArchive.bat for guided setup. Running it directly still works.
    echo.
)

REM Deletes the local log files under log\ and the reachability-check cache (each after a y/n). Filesystem only - no database.
call "%~dp0_bootstrap_venv.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m db.clean_logs
if errorlevel 1 (
    echo.
    echo Clean Logs exited with an error - see above.
    pause
)
