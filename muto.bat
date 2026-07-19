@echo off
rem muto launcher (Windows)—thin wrapper preserving the double-click path.
rem All logic lives in the muto CLI package (muto/cli.py).
chcp 65001 >nul
cd /d "%~dp0"
where muto >nul 2>nul
if %errorlevel%==0 (
    muto %*
) else (
    python -m muto %*
)
if errorlevel 1 pause
