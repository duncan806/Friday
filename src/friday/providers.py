"""Provider adapters — the two CLIs Friday drives.

One rule, enforced by the tools each side is handed:
- **Claude decides, never writes.** `pm_decide` routes the goal (read-only tools);
  `claude_review` oversees a running build with a *verification-only* allowlist —
  it may run `git diff`/tests to check ground truth, but never authors the work.
- **Codex writes, never decides.** `codex_run` / `codex_stream` execute a brief
  and stream every step; Codex has no view of the goal and no authority over scope.
"""

import json
import shutil
import subprocess
import threading
from pathlib import Path

from .errors import AdapterError


def _run_claude_structured(prompt: str, *, allowed_tools: list, schema: dict,
                           root: Path, model: str | None, timeout: int, runner) -> dict:
    """Call Claude headlessly with a JSON-schema-constrained answer and a fixed
    tool allowlist. Returns the validated payload dict (from `structured_output`,
    falling back to a JSON `result` string). Raises AdapterError on any failure."""
    exe = shutil.which("claude")
    if not exe:
        raise AdapterError("claude CLI is not installed or not on PATH")
    cmd = [exe, "-p", prompt, "--permission-mode", "bypassPermissions",
           "--allowedTools", *allowed_tools,
           "--output-format", "json", "--json-schema", json.dumps(schema)]
    if model:
        cmd += ["--model", model]
    try:
        r = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=timeout, cwd=str(root), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("Claude call timed out") from exc
    except OSError as exc:
        raise AdapterError(f"Claude call failed: {exc}") from exc
    if r.returncode != 0:
        raise AdapterError(((r.stderr or r.stdout) or "Claude call failed").strip()[:240])
    try:
        env = json.loads(r.stdout)
        payload = env.get("structured_output")
        if payload is None:
            payload = json.loads(env.get("result", "{}"))
    except (ValueError, TypeError) as exc:
        raise AdapterError("Claude returned unparseable output") from exc
    if not isinstance(payload, dict):
        raise AdapterError("Claude returned unparseable output")
    return payload


# ── entry router: question vs. first brief ───────────────────────────────────

_PM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["action", "message"],
    "properties": {
        "action": {"type": "string", "enum": ["answer", "instruct", "done", "ask"]},
        "message": {"type": "string"},
    },
}

_PM_PROMPT = """You direct Codex, a fast builder with NO decision authority and NO ability to see the goal — Codex only executes the exact text you put in "message", verbatim. You cannot write files yourself (you are read-only); Codex is the only hand that edits. You decide everything.

USER GOAL / MESSAGE:
{{goal}}

WORK SO FAR:
{{history}}

CODEX'S LAST REPORT:
{{last}}

Read the workspace files (Read/Grep/Glob) to check reality. Then choose ONE action and put ALL of the content in "message":
- "answer": the user asked a question, or it's not a build/edit task — "message" is your reply to the user. Codex will NOT run. (Use this for capability questions like "can you review code?" — just answer.)
- "instruct": building or editing is needed — "message" is the COMPLETE, self-contained first brief handed to Codex verbatim: name the files and the exact change/build. It must stand alone (Codex never sees the goal or your reasoning — only this text). Do NOT describe what you instructed; write the instruction itself.
- "done": the goal is already fully and verifiably met — "message" is the summary.
- "ask": you genuinely cannot proceed without the human — "message" is the question.
Reply in the user's language. Return {action, message}."""


def pm_decide(root: Path, config: dict, goal: str, history: str, last: str, *,
              model: str | None = None, timeout: int = 180, runner=subprocess.run) -> dict:
    """Claude routes the goal as structured output — reliable dispatch
    (answer | instruct Codex | done | ask), grounded by reading files (read-only)."""
    prompt = (_PM_PROMPT.replace("{{goal}}", goal).replace("{{history}}", history)
              .replace("{{last}}", last))
    # Claude cannot write — read-only tools only. It reads to ground its decision,
    # but the builder (Codex) is the sole hand that touches files.
    payload = _run_claude_structured(prompt, allowed_tools=["Read", "Grep", "Glob"],
                                     schema=_PM_SCHEMA, root=root, model=model,
                                     timeout=timeout, runner=runner)
    if "action" not in payload:
        raise AdapterError("Claude returned no action")
    return payload


# ── overseer: judge a running build against ground truth ─────────────────────

_REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "hard", "note"],
    "properties": {
        "verdict": {"type": "string", "enum": ["continue", "correct", "ask", "done"]},
        "hard": {"type": "boolean"},
        "note": {"type": "string"},
    },
}

_REVIEW_PROMPT = """You are the overseer of a build. Codex — a builder with no judgment — is working the brief below toward the user's goal. You watch its live stream and decide.

You CANNOT write, and you must not author the work (never open source files to think for Codex). You CAN verify: run `git diff`, `git status`{{verify}} to check what ACTUALLY happened against what Codex claims — because Codex's self-report is least trustworthy exactly when it fails (it may say "done" without ever testing, or half-break a file and only stream "edited X"). Verify before you trust the stream.

USER GOAL:
{{goal}}

BRIEF CODEX IS BUILDING:
{{brief}}

CODEX'S STREAM SO FAR (its self-report — verify it):
{{summary}}

Choose exactly ONE verdict:
- "continue": the direction is right; let Codex keep working. (Only meaningful while Codex is still active.)
- "correct": something must change. "note" is the correction, written as a direct instruction to Codex. Set "hard": true ONLY if the current direction is wrong and finishing it wastes work (Codex is killed and respawned) — otherwise "hard": false so the fix folds into the next step. If Codex has finished but the goal is not met, use "correct" with "note" = the next brief.
- "ask": you are unsure the work matches the user's real intent — "note" is the question for the human. Use this instead of guessing.
- "done": the goal is verifiably met — you RAN the checks (tests pass, the diff matches the goal), not merely because Codex said "done". "note" is a one-line summary.

Reply in the user's language for "note". Return {verdict, hard, note}."""


def claude_review(root: Path, goal: str, brief: str, summary: str, verify: str = "", *,
                  model: str | None = None, timeout: int = 180, runner=subprocess.run) -> dict:
    """The overseer verdict. Claude sees the goal, the current brief, and a digest
    of Codex's stream — and may run a *verification-only* command allowlist to check
    ground truth. It can verify, never author. Returns {verdict, hard, note}."""
    allowed = ["Bash(git diff:*)", "Bash(git status:*)", "Bash(git log:*)"]
    verify_hint = ""
    if verify:
        allowed.append(f"Bash({verify}:*)")
        verify_hint = f", and `{verify}`"
    prompt = (_REVIEW_PROMPT.replace("{{goal}}", goal).replace("{{brief}}", brief)
              .replace("{{summary}}", summary or "(nothing yet)")
              .replace("{{verify}}", verify_hint))
    payload = _run_claude_structured(prompt, allowed_tools=allowed, schema=_REVIEW_SCHEMA,
                                     root=root, model=model, timeout=timeout, runner=runner)
    if "verdict" not in payload:
        raise AdapterError("Claude returned no verdict")
    payload.setdefault("hard", False)
    payload.setdefault("note", "")
    return payload


# ── builder: stream a brief, killable, never silent on failure ───────────────

def codex_stream(prompt: str, *, on_event=None, sandbox: str = "read-only",
                 cwd: Path | None = None, model: str | None = None, timeout: int = 180,
                 stop: "threading.Event | None" = None, popen=subprocess.Popen) -> str:
    """Run Codex and stream its rich activity (reasoning, the commands it runs,
    their output) via on_event(event) — like Claude Code showing tool use. Parses
    `codex exec --json` (line-delimited events). Returns the final agent message.

    If `stop` is provided, setting it kills the subprocess mid-stream (used by the
    pipeline for a hard correction) — that intentional kill is not treated as an
    error."""
    exe = shutil.which("codex")
    if not exe:
        raise AdapterError("codex CLI is not installed or not on PATH")
    cmd = [exe, "exec", "--json", "--ephemeral", "--sandbox", sandbox,
           "--skip-git-repo-check"]
    if model:
        cmd += ["-m", model]
    cmd.append(prompt)
    try:
        proc = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, encoding="utf-8", errors="replace",
                     cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL, bufsize=1)
    except OSError as exc:
        raise AdapterError(f"codex call failed: {exc}") from exc

    if stop is not None:
        def _watch():
            while not stop.wait(0.1):
                if proc.poll() is not None:
                    return
            try:
                proc.kill()
            except Exception:                            # noqa: BLE001
                pass
        threading.Thread(target=_watch, daemon=True).start()

    messages: list[str] = []
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if on_event:
                on_event(ev)
            item = ev.get("item", {})
            if ev.get("type") == "item.completed" and item.get("type") == "agent_message":
                messages.append(item.get("text", ""))
    finally:
        try:
            proc.wait(timeout=timeout)
        except Exception:                                # noqa: BLE001
            proc.kill()

    final = messages[-1] if messages else ""
    killed = stop is not None and stop.is_set()
    if not final and proc.returncode and not killed:
        err = ""
        try:
            err = proc.stderr.read() if proc.stderr else ""
        except Exception:                                # noqa: BLE001
            pass
        raise AdapterError((err or "codex failed").strip()[:240] or "codex failed")
    return final


_CODEX_BRIEF_PREFIX = (
    "Do this now in the workspace. Read and edit files and run commands as needed. "
    "Report each concrete step as you go — the exact files you change and the exact "
    "commands you run and their results — because a reviewer watches only your stream "
    "and cannot see anything you don't surface. You decide nothing about scope; do "
    "exactly this:\n\n"
)


def codex_run(brief: str, *, on_event=None, sandbox: str = "workspace-write",
              cwd: Path | None = None, model: str | None = None,
              stop: "threading.Event | None" = None, timeout: int = 180,
              popen=subprocess.Popen) -> str:
    """The pipeline's worker entry: stream Codex on a brief; `stop` kills it. A
    crash/timeout is surfaced as an explicit `worker_error` event (never silence)
    and returns "" — so the overseer can see the failure and route around it."""
    try:
        return codex_stream(_CODEX_BRIEF_PREFIX + brief, on_event=on_event,
                            sandbox=sandbox, cwd=cwd, model=model, stop=stop,
                            timeout=timeout, popen=popen)
    except AdapterError as exc:
        if on_event:
            on_event({"type": "worker_error",
                      "item": {"type": "worker_error", "message": str(exc)}})
        return ""
