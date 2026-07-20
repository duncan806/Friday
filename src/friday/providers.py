"""Provider adapters — cherry-picking Claude Code / Codex CLI mechanisms (spec §11).

The advisor profile calls Claude headlessly with `--permission-mode
bypassPermissions` so the human⇄Claude conversation never blocks on an approval
prompt. bypassPermissions maps to `--dangerously-skip-permissions`, which the
CLI refuses under root; that is surfaced as AdapterError rather than a hang or a
silent no-op (spec §11.1).
"""

import json
import shutil
import subprocess
from pathlib import Path

from .errors import AdapterError


_PM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["action", "message"],
    "properties": {
        "action": {"type": "string", "enum": ["answer", "instruct", "done", "ask"]},
        "message": {"type": "string"},
    },
}

_PM_PROMPT = """You are the PM directing Codex, a fast builder with NO decision authority and NO ability to see the goal — Codex only executes the exact text you put in "message", verbatim. You cannot write files yourself (you are read-only); Codex is the only hand that edits. You decide everything.

USER GOAL / MESSAGE:
{{goal}}

WORK SO FAR:
{{history}}

CODEX'S LAST REPORT:
{{last}}

Read the workspace files (Read/Grep/Glob) to check reality. Then choose ONE action and put ALL of the content in "message":
- "answer": the user asked a question, or it's not a build/edit task — "message" is your reply to the user. Codex will NOT run. (Use this for capability questions like "can you review code?" — just answer.)
- "instruct": building or editing is needed — "message" is the COMPLETE, self-contained instruction handed to Codex verbatim: name the files and the exact change/build. It must stand alone (Codex never sees the goal or your reasoning — only this text). Do NOT describe what you instructed; write the instruction itself.
- "done": the goal is fully and verifiably met — "message" is the summary.
- "ask": you genuinely cannot proceed without the human — "message" is the question.
Reply in the user's language. Return {action, message}."""


def pm_decide(root: Path, config: dict, goal: str, history: str, last: str, *,
              model: str | None = None, timeout: int = 180, runner=subprocess.run) -> dict:
    """Claude, the PM, decides the next move as structured output — reliable
    dispatch (answer | instruct Codex | done | ask), grounded by reading files."""
    exe = shutil.which("claude")
    if not exe:
        raise AdapterError("claude CLI is not installed or not on PATH")
    prompt = (_PM_PROMPT.replace("{{goal}}", goal).replace("{{history}}", history)
              .replace("{{last}}", last))
    # Claude cannot write — read-only tools only. It reads to ground its decision,
    # but the builder (Codex) is the sole hand that touches files.
    cmd = [exe, "-p", prompt, "--permission-mode", "bypassPermissions",
           "--allowedTools", "Read", "Grep", "Glob",
           "--output-format", "json", "--json-schema", json.dumps(_PM_SCHEMA)]
    if model:
        cmd += ["--model", model]
    try:
        r = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=timeout, cwd=str(root), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("PM decision timed out") from exc
    except OSError as exc:
        raise AdapterError(f"PM decision failed: {exc}") from exc
    if r.returncode != 0:
        raise AdapterError(((r.stderr or r.stdout) or "PM decision failed").strip()[:240])
    try:
        env = json.loads(r.stdout)
        payload = env.get("structured_output")
        if payload is None:
            payload = json.loads(env.get("result", "{}"))
    except (ValueError, TypeError) as exc:
        raise AdapterError("PM returned unparseable output") from exc
    if not isinstance(payload, dict) or "action" not in payload:
        raise AdapterError("PM returned no action")
    return payload


def codex_stream(prompt: str, *, on_event=None, sandbox: str = "read-only",
                 cwd: Path | None = None, model: str | None = None, timeout: int = 180,
                 popen=subprocess.Popen) -> str:
    """Run Codex and stream its rich activity (reasoning, the commands it runs,
    their output) via on_event(event) — like Claude Code showing tool use. Parses
    `codex exec --json` (line-delimited events). Returns the final agent message."""
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
        except Exception:
            proc.kill()

    final = messages[-1] if messages else ""
    if not final and proc.returncode:
        err = ""
        try:
            err = proc.stderr.read() if proc.stderr else ""
        except Exception:
            pass
        raise AdapterError((err or "codex failed").strip()[:240] or "codex failed")
    return final


