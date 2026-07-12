@echo off
cd /d "%~dp0.."

if not defined TGARCHIVE_MENU (
    echo NOTE: meant to be launched from TGArchive.bat for guided setup. Running it directly still works.
    echo.
)

if not exist ".env" (
    echo WARNING: .env file not found.
    if exist ".env.example" (
        echo Creating .env from .env.example - remember to fill in your own values.
        copy /y ".env.example" ".env" >nul
    ) else (
        echo WARNING: .env.example not found either - cannot create .env automatically.
    )
)

findstr /b "DATABASE_URL_BOT=postgresql" .env >nul 2>nul
if errorlevel 1 (
    echo WARNING: DATABASE_URL_BOT is not configured in .env yet.
    echo Run setup_database.bat first - continuing anyway, the bot itself will explain what's missing.
)

call "%~dp0_bootstrap_venv.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

cls
echo Starting the bot... (CTRL+C to stop)
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m bot.main
if errorlevel 1 (
    echo.
    echo The bot exited with an error - see above.
    pause
)
