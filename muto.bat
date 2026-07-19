@echo off
rem muto launcher (Windows)—screen first.
rem Opens the dashboard immediately, then streams BIOS-POST-style check
rem results into dashboard\status.js, which the page polls every second.
rem All communication is file-based (same principle as stop.flag).
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set CHECKS=
set TASK_PRESENT=false

rem ── 1. Screen first: open the dashboard, start in boot phase ──
call :emit boot
start "" "dashboard\index.html"

rem ── 2/3. POST checks, rendered on screen as they complete ──
where claude >nul 2>nul
if errorlevel 1 (
    set CHECKS=%CHECKS%{"name":"CLAUDE CLI","state":"fail","hint":"install it: see https://claude.com/claude-code"},
    call :halt "claude CLI is not installed."
)
set CHECKS=%CHECKS%{"name":"CLAUDE CLI","state":"ok","hint":""},
call :emit boot

where codex >nul 2>nul
if errorlevel 1 (
    set CHECKS=%CHECKS%{"name":"CODEX CLI","state":"fail","hint":"install it: npm install -g @openai/codex"},
    call :halt "codex CLI is not installed."
)
set CHECKS=%CHECKS%{"name":"CODEX CLI","state":"ok","hint":""},
call :emit boot

where python >nul 2>nul
if errorlevel 1 (
    set CHECKS=%CHECKS%{"name":"PYTHON","state":"fail","hint":"install it: https://www.python.org/downloads/"},
    call :halt "python is not installed."
)
set CHECKS=%CHECKS%{"name":"PYTHON","state":"ok","hint":""},
call :emit boot

claude -p "reply with exactly: ok" >nul 2>nul
if errorlevel 1 (
    set CHECKS=%CHECKS%{"name":"CLAUDE AUTH","state":"fail","hint":"run claude once and complete the browser login"},
    call :halt "claude auth failed."
)
set CHECKS=%CHECKS%{"name":"CLAUDE AUTH","state":"ok","hint":""},
call :emit boot

codex exec --sandbox read-only "reply with exactly: ok" >nul 2>nul
if errorlevel 1 (
    set CHECKS=%CHECKS%{"name":"CODEX AUTH","state":"fail","hint":"run codex login"},
    call :halt "codex auth failed. Run codex login."
)
set CHECKS=%CHECKS%{"name":"CODEX AUTH","state":"ok","hint":""},
call :emit boot

if not exist "task\task.md" (
    if not exist "task" mkdir task
    > "task\task.md" (
        echo # Task
        echo.
        echo Describe the task here. This file is injected only into the
        echo user-role agent and cannot be modified once the cycle starts.
    )
    start notepad "task\task.md"
    set CHECKS=%CHECKS%{"name":"TASK FILE","state":"fail","hint":"task.md was missing; a template was opened. Write it, save, and run muto.bat again"},
    call :halt "task\task.md was missing; a template has been opened in Notepad."
)
set TASK_PRESENT=true
set CHECKS=%CHECKS%{"name":"TASK FILE","state":"ok","hint":""},
call :emit boot

rem ── 4. All OK: show [START CYCLE] on screen, wait for the human ──
call :emit ready
echo ALL CHECKS PASSED.
echo Press any key to START CYCLE...
pause >nul

rem ── 5. Launch: orchestrator takes over status.js from here ──
if exist "stop.flag" del "stop.flag"
start "muto-orchestrator" /min python orchestrator.py
echo Cycle started. Use the [STOP] button on the dashboard to halt.
exit /b 0

rem ── subroutines ──────────────────────────────────────────
:emit
rem %1 = phase. Rewrites dashboard\status.js; the page polls it.
> "dashboard\status.js" echo window.MUTO_STATUS = {"phase":"%~1","checks":[%CHECKS%],"round":0,"status":"","task_present":%TASK_PRESENT%};
exit /b 0

:halt
rem The screen stays alive (mascots keep roaming); only the console halts.
call :emit failed
echo [ERROR] %~1
echo         See the dashboard for details, fix it, then run muto.bat again.
pause
exit 1
