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

REM The CLI mirrors the bot and uses the same database; it reports clearly if the DB isn't ready
REM (run Setup Database first). Reads need no Telegram login; scraping asks for one when first used.

call "%~dp0_bootstrap_venv.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" CLI\Menu.py
if errorlevel 1 (
    echo.
    echo The CLI exited with an error - see above.
    pause
)
