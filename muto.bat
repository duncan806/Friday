@echo off
rem muto launcher (Windows)
rem 1) check claude/codex/python  2) check auth  3) check task/task.md
rem 4) start orchestrator in background + open dashboard
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem ── 1. CLI/runtime presence checks ───────────────────────
where claude >nul 2>nul
if errorlevel 1 (
    echo [ERROR] claude CLI is not installed.
    echo         See https://claude.com/claude-code and install it.
    pause
    exit /b 1
)
where codex >nul 2>nul
if errorlevel 1 (
    echo [ERROR] codex CLI is not installed.
    echo         Install it with: npm install -g @openai/codex
    pause
    exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python is not installed.
    echo         Install it from https://www.python.org/downloads/
    pause
    exit /b 1
)

rem ── 2. Auth checks (trivial call) ────────────────────────
echo Checking auth... (claude)
claude -p "reply with exactly: ok" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] claude auth failed.
    echo         Run claude once and complete the browser login.
    pause
    exit /b 1
)
echo Checking auth... (codex)
codex exec --sandbox read-only "reply with exactly: ok" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] codex auth failed.
    echo         Run codex login.
    pause
    exit /b 1
)

rem ── 3. task/task.md presence check ───────────────────────
if not exist "task\task.md" (
    if not exist "task" mkdir task
    > "task\task.md" (
        echo # Task
        echo.
        echo Describe the task here. This file is injected only into the
        echo user-role agent and cannot be modified once the cycle starts.
        echo.
        echo Tasks with a clear surface, observable blockages, and a short
        echo build cycle are a good fit.
    )
    start notepad "task\task.md"
    echo [INFO] task\task.md was missing; a template has been opened.
    echo        Write it, save, and run this launcher again.
    pause
    exit /b 0
)

rem ── 4. Run: orchestrator in background + open dashboard ──
if exist "stop.flag" del "stop.flag"
start "muto-orchestrator" /min python orchestrator.py
rem wait briefly for the initial dashboard render
timeout /t 2 /nobreak >nul
start "" "dashboard\index.html"
echo muto cycle started. Use the [STOP] button on the dashboard to halt.
echo (saving a stop.flag file into this folder halts before the next round)
exit /b 0
