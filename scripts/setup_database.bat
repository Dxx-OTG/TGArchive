@echo off
setlocal

if "%~1"=="--elevated-retry" goto :check

if not defined TGARCHIVE_MENU (
    echo NOTE: meant to be launched from TGArchive.bat for guided setup. Running it directly still works.
    echo.
)

fsutil dirty query %systemdrive% >nul 2>&1
if not errorlevel 1 goto :run

echo Requesting administrator privileges...
echo (a new elevated window will open - this one waits for it to finish, do not close it)
powershell -NoProfile -Command "$p = Start-Process -FilePath '%~f0' -ArgumentList '--elevated-retry' -Verb RunAs -Wait -PassThru; exit $p.ExitCode"
exit /b %errorLevel%

:check
REM Already tried to elevate once: if we're still not admin, stop here instead of trying again,
REM so a flaky admin-check can never cause repeated/endless elevation windows.
fsutil dirty query %systemdrive% >nul 2>&1
if errorlevel 1 (
    echo ERROR: still not running as administrator after requesting elevation.
    echo This can happen if UAC was cancelled, or admin rights are restricted by policy.
    echo Run this file again and accept the UAC prompt, or ask an administrator to run it.
    pause
    exit /b 1
)

:run
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_database.ps1"
if errorlevel 1 (
    echo.
    echo Setup Database exited with an error - see above.
    pause
)
