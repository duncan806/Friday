@echo off
rem friday launcher (Windows)—thin wrapper preserving the double-click path.
rem All logic lives in the friday CLI package (friday/cli.py). `friday` opens the
rem dashboard as a standalone Chrome/Edge app window (--app) by default.
rem For a shortcut that opens ONLY the app window (no console), run once:
rem     friday shortcut
rem which creates a Desktop shortcut targeting the no-console `fridayw` entry.
chcp 65001 >nul
cd /d "%~dp0"
where friday >nul 2>nul
if %errorlevel%==0 (
    friday %*
) else (
    python -m friday %*
)
if errorlevel 1 pause
