@echo off
rem muto launcher (Windows)—thin wrapper preserving the double-click path.
rem All logic lives in the muto CLI package (muto/cli.py). `muto` opens the
rem dashboard as a standalone Chrome/Edge app window (--app) by default.
rem For a shortcut that opens ONLY the app window (no console), run once:
rem     muto shortcut
rem which creates a Desktop shortcut targeting the no-console `mutow` entry.
chcp 65001 >nul
cd /d "%~dp0"
where muto >nul 2>nul
if %errorlevel%==0 (
    muto %*
) else (
    python -m muto %*
)
if errorlevel 1 pause
