@echo off
REM ============================================================
REM Build script for Microfinance Manager
REM Run this from the project root (the folder containing main.py)
REM Requires: the project .venv with requirements installed
REM ============================================================

REM --icon and --add-data "assets;assets" point at the assets\app_icon.ico /
REM app_icon.png files that app_root.py loads at runtime - remove both if
REM you haven't added those files yet.
REM
REM --collect-data / --collect-all flags below bundle each library's own
REM internal data files (themes, fonts, locale strings) that PyInstaller
REM can't see just by tracing imports:
REM   - customtkinter: always used, needs its theme JSON files
REM   - tkcalendar: only if installed (optional import in widgets.py)
REM   - reportlab: only if installed (optional import, used for PDF export)
REM If a package isn't installed, its --collect-* flag below will error -
REM just delete that line.
REM
REM NOTE: using --onedir instead of --onefile on purpose. --onefile
REM re-extracts the whole bundle to a temp folder on every single launch,
REM which is what causes the multi-second startup delay. --onedir extracts
REM once at build time, so the exe just runs directly - startup is close
REM to instant. To share the app, zip the entire dist\MicrofinanceManager
REM folder (not just the .exe) - recipients unzip it and run the exe from
REM inside that folder.

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo ERROR: Project virtual environment not found at .venv\Scripts\python.exe
    echo Create it and install requirements.txt before building.
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" -m PyInstaller ^
    --name "MicrofinanceManager" ^
    --onedir ^
    --windowed ^
    --icon "assets\app_icon.ico" ^
    --add-data "app\schema.sql;app" ^
    --add-data "assets;assets" ^
    --collect-data customtkinter ^
    --collect-data tkcalendar ^
    --collect-all reportlab ^
    main.py

if errorlevel 1 goto build_failed

echo.
echo ============================================================
echo Build complete. Find the app in dist\MicrofinanceManager\
echo Run MicrofinanceManager.exe from inside that folder.
echo To share: zip the whole "MicrofinanceManager" folder, not
echo just the .exe - it needs the files alongside it to run.
echo ============================================================
pause
exit /b 0

:build_failed
echo.
echo Build failed. The executable may still be running or a dependency may be missing.
exit /b 1
