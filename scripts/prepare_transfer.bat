@echo off
if not defined TGARCHIVE_MENU (
    echo NOTE: meant to be launched from TGArchive.bat for guided setup. Running it directly still works.
    echo.
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_transfer.ps1"

REM When run from the menu, the menu itself waits ("Press ENTER to continue") after this finishes.
REM Only pause here when launched standalone, to avoid a double "press a key" in the normal flow.
if not defined TGARCHIVE_MENU (
    echo.
    pause
)
