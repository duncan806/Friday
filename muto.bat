@echo off
rem muto launcher (Windows)
rem 1) check claude/codex/python  2) check auth  3) check task/task.md
rem 4) start orchestrator in background + open dashboard
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem ── 1. CLI/런타임 존재 검사 ──────────────────────────────
where claude >nul 2>nul
if errorlevel 1 (
    echo [오류] claude CLI가 설치되어 있지 않습니다.
    echo        https://claude.com/claude-code 를 참고해 설치하세요.
    pause
    exit /b 1
)
where codex >nul 2>nul
if errorlevel 1 (
    echo [오류] codex CLI가 설치되어 있지 않습니다.
    echo        npm install -g @openai/codex 로 설치하세요.
    pause
    exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
    echo [오류] python이 설치되어 있지 않습니다.
    echo        https://www.python.org/downloads/ 에서 설치하세요.
    pause
    exit /b 1
)

rem ── 2. 인증 검사 (트리비얼 호출) ─────────────────────────
echo 인증 확인 중... (claude)
claude -p "reply with exactly: ok" >nul 2>nul
if errorlevel 1 (
    echo [오류] claude 인증에 실패했습니다.
    echo        claude 를 한 번 실행해 브라우저 로그인을 완료하세요.
    pause
    exit /b 1
)
echo 인증 확인 중... (codex)
codex exec --sandbox read-only "reply with exactly: ok" >nul 2>nul
if errorlevel 1 (
    echo [오류] codex 인증에 실패했습니다.
    echo        codex login을 실행하세요.
    pause
    exit /b 1
)

rem ── 3. task/task.md 존재 검사 ────────────────────────────
if not exist "task\task.md" (
    if not exist "task" mkdir task
    > "task\task.md" (
        echo # 과제
        echo.
        echo 여기에 과제를 서술하세요. 이 파일은 사용자 역 에이전트에게만 주입되며,
        echo 사이클 시작 후에는 수정할 수 없습니다.
        echo.
        echo 표면이 명확하고, 막힘이 관찰 가능하며, 빌드 사이클이 짧은 과제가 적합합니다.
    )
    start notepad "task\task.md"
    echo [안내] task\task.md 가 없어 템플릿을 열었습니다.
    echo        작성 후 저장하고 다시 실행하세요.
    pause
    exit /b 0
)

rem ── 4. 실행: 오케스트레이터 백그라운드 + 대시보드 열기 ──
if exist "stop.flag" del "stop.flag"
start "muto-orchestrator" /min python orchestrator.py
rem 초기 대시보드가 생성될 때까지 잠시 대기
timeout /t 2 /nobreak >nul
start "" "dashboard\index.html"
echo muto 사이클을 시작했습니다. 대시보드의 [중단] 버튼으로 정지할 수 있습니다.
echo (stop.flag 파일을 이 폴더에 저장하면 다음 라운드 전에 정지합니다)
exit /b 0
