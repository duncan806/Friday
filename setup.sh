#!/usr/bin/env bash
# muto setup — 스펙 §9
# 두 CLI 설치 확인 → 트리비얼 프롬프트로 인증 유효성 확인 → 실패 시 안내 후 중단.
set -euo pipefail

fail() { echo "✗ $1" >&2; echo "  → $2" >&2; exit 1; }
ok()   { echo "✓ $1"; }

# 1. CLI 설치 확인
command -v claude >/dev/null 2>&1 \
  || fail "claude CLI 미설치" "https://claude.com/claude-code 참고 후 설치하세요."
claude --version >/dev/null 2>&1 || fail "claude --version 실패" "설치 상태를 확인하세요."
ok "claude CLI: $(claude --version 2>/dev/null | head -1)"

command -v codex >/dev/null 2>&1 \
  || fail "codex CLI 미설치" "npm install -g @openai/codex 후 다시 실행하세요."
codex --version >/dev/null 2>&1 || fail "codex --version 실패" "설치 상태를 확인하세요."
ok "codex CLI: $(codex --version 2>/dev/null | head -1)"

# 2. auth_mode 결정 (config.yaml, 기본 subscription)
AUTH_MODE=$(python3 - <<'EOF' 2>/dev/null || echo subscription
import yaml, pathlib
cfg = pathlib.Path("config.yaml")
print(yaml.safe_load(cfg.read_text()).get("auth_mode", "subscription") if cfg.is_file() else "subscription")
EOF
)
echo "auth_mode: ${AUTH_MODE}"

if [ "$AUTH_MODE" = "api_key" ]; then
  [ -n "${ANTHROPIC_API_KEY:-}" ] || fail "ANTHROPIC_API_KEY 미설정" "export ANTHROPIC_API_KEY=... 후 재실행."
  [ -n "${OPENAI_API_KEY:-}" ]    || fail "OPENAI_API_KEY 미설정"    "export OPENAI_API_KEY=... 후 재실행."
  ok "API 키 환경변수 확인"
fi

# 3. 인증 유효성: 트리비얼 프롬프트 1회 호출
claude -p "reply with exactly: ok" >/dev/null 2>&1 \
  || fail "claude 인증 실패" "claude 를 한 번 실행해 브라우저 로그인을 완료한 뒤 재실행하세요."
ok "claude 인증 유효"

codex exec --sandbox read-only "reply with exactly: ok" >/dev/null 2>&1 \
  || fail "codex 인증 실패" "codex login 을 실행해 로그인한 뒤 재실행하세요."
ok "codex 인증 유효"

# 4. 디렉토리 골격 확인
for d in workspace/src workspace/surface task reports/dropped predictions verdicts dashboard prompts; do
  mkdir -p "$d"
done
ok "디렉토리 골격 확인"

echo
echo "muto 준비 완료. task/task.md 를 작성한 뒤 orchestrator.py 를 실행하세요."
