@echo off
cd /d "%~dp0"

call "scripts\_bootstrap_venv.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

cls
set PYTHONIOENCODING=utf-8
set TGARCHIVE_MENU=1
REM Run the menu with the system Python (it's stdlib-only) so it never holds .venv open - that is
REM what lets Prepare Transfer delete .venv while this menu stays running.
python scripts\menu.py
if errorlevel 1 (
    echo.
    echo The menu exited with an error - see above.
)

REM You opened this window yourself - it never closes on its own, close it when you're done.
echo.
pause
