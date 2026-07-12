@echo off
REM Shared by TGArchive.bat, start_bot.bat, start_menu.bat, clean_logs.bat - not meant to run directly.
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/ - tick "Add Python to PATH".
    exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python 3.10 or newer is required.
    python --version
    echo Install a newer Python from https://www.python.org/downloads/, then try again.
    exit /b 1
)

if not exist ".venv" (
    echo Creating Python virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: cannot create the virtual environment.
        exit /b 1
    )
)

REM A .venv copied from another PC keeps that PC's hardcoded paths and won't run here. If its
REM Python can't even start, rebuild it so a transferred folder works with no manual cleanup.
".venv\Scripts\python.exe" --version >nul 2>nul
if errorlevel 1 (
    echo Rebuilding the virtual environment - the existing .venv doesn't work on this PC...
    rmdir /s /q ".venv"
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: cannot create the virtual environment.
        exit /b 1
    )
)

REM Only install dependencies when they're actually missing, so normal launches stay fast.
".venv\Scripts\python.exe" -c "import aiogram, asyncpg, telethon, dotenv, watchfiles" 2>nul
if errorlevel 1 (
    echo Installing/updating dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: dependency installation failed, see the reason above.
        exit /b 1
    )
)

exit /b 0
