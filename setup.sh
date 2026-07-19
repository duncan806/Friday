#!/usr/bin/env bash
# muto setup—spec §9
# Check both CLIs are installed -> validate auth with a trivial prompt ->
# on failure, print guidance and abort.
set -euo pipefail

fail() { echo "✗ $1" >&2; echo "  → $2" >&2; exit 1; }
ok()   { echo "✓ $1"; }

# 1. CLI installation checks
command -v claude >/dev/null 2>&1 \
  || fail "claude CLI not installed" "See https://claude.com/claude-code and install it."
claude --version >/dev/null 2>&1 || fail "claude --version failed" "Check the installation."
ok "claude CLI: $(claude --version 2>/dev/null | head -1)"

command -v codex >/dev/null 2>&1 \
  || fail "codex CLI not installed" "Run: npm install -g @openai/codex, then retry."
codex --version >/dev/null 2>&1 || fail "codex --version failed" "Check the installation."
ok "codex CLI: $(codex --version 2>/dev/null | head -1)"

# 2. Resolve auth_mode (config.yaml, default: subscription)
AUTH_MODE=$(python3 - <<'EOF' 2>/dev/null || echo subscription
import yaml, pathlib
cfg = pathlib.Path("config.yaml")
print(yaml.safe_load(cfg.read_text()).get("auth_mode", "subscription") if cfg.is_file() else "subscription")
EOF
)
echo "auth_mode: ${AUTH_MODE}"

if [ "$AUTH_MODE" = "api_key" ]; then
  [ -n "${ANTHROPIC_API_KEY:-}" ] || fail "ANTHROPIC_API_KEY not set" "export ANTHROPIC_API_KEY=... and retry."
  [ -n "${OPENAI_API_KEY:-}" ]    || fail "OPENAI_API_KEY not set"    "export OPENAI_API_KEY=... and retry."
  ok "API key environment variables present"
fi

# 3. Auth validity: one trivial prompt per CLI
claude -p "reply with exactly: ok" >/dev/null 2>&1 \
  || fail "claude auth failed" "Run claude once, complete the browser login, then retry."
ok "claude auth valid"

codex exec --sandbox read-only "reply with exactly: ok" >/dev/null 2>&1 \
  || fail "codex auth failed" "Run codex login, sign in, then retry."
ok "codex auth valid"

# 4. Directory skeleton
for d in workspace/src workspace/surface task reports/dropped predictions verdicts dashboard prompts; do
  mkdir -p "$d"
done
ok "directory skeleton present"

echo
echo "muto is ready. Write task/task.md, then run orchestrator.py."
