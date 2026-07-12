@echo off
cd /d "%~dp0.."

if not defined TGARCHIVE_MENU (
    echo NOTE: meant to be launched from TGArchive.bat. Running it directly still works.
    echo.
)

if not exist ".env" (
    echo WARNING: .env not found - run TGArchive.bat and complete setup first.
    pause
    exit /b 1
)

REM Logs in (or switches) the Telegram scraping account without opening the CLI. Needs only the
REM TG_API_ID / TG_API_HASH / TG_SESSION_NAME values in .env - no database required.

call "%~dp0_bootstrap_venv.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m collectors.login
if errorlevel 1 (
    echo.
    echo Telegram login exited with an error - see above.
    pause
)
