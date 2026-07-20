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


def claude_advisor(prompt: str, *, timeout: int = 120, cwd: Path | None = None,
                   runner=subprocess.run) -> str:
    """Call Claude as the conversational advisor and return its text.

    `runner` is injectable for testing (defaults to subprocess.run)."""
    exe = shutil.which("claude")
    if not exe:
        raise AdapterError("claude CLI is not installed or not on PATH")
    try:
        r = runner([exe, "-p", prompt, "--permission-mode", "bypassPermissions"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=timeout, cwd=str(cwd) if cwd else None,
                   stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("claude advisor call timed out") from exc
    except OSError as exc:
        raise AdapterError(f"claude advisor call failed: {exc}") from exc
    if r.returncode != 0:
        # e.g. bypassPermissions refused under root — surface, do not hang.
        raise AdapterError(((r.stderr or r.stdout) or "claude advisor failed").strip()[:240])
    return r.stdout or ""


def claude_advisor_stream(prompt, *, on_text=None, model=None, timeout=180, cwd=None,
                          popen=subprocess.Popen) -> str:
    """Stream Claude's reply, calling on_text(delta) as text arrives, and return
    the full text — for real-time conversation in the terminal. Parses the
    claude CLI's --output-format stream-json events (line-delimited JSON).
    `model` selects a specific model (e.g. haiku for the fast lane)."""
    exe = shutil.which("claude")
    if not exe:
        raise AdapterError("claude CLI is not installed or not on PATH")
    # Claude cannot write — read-only tools only (it grounds by reading, never edits).
    cmd = [exe, "-p", prompt, "--permission-mode", "bypassPermissions",
           "--allowedTools", "Read", "Grep", "Glob",
           "--output-format", "stream-json", "--include-partial-messages", "--verbose"]
    if model:
        cmd += ["--model", model]
    try:
        proc = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, encoding="utf-8", errors="replace",
                     cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL, bufsize=1)
    except OSError as exc:
        raise AdapterError(f"claude advisor call failed: {exc}") from exc

    deltas, assistant_text, result_text, is_error = [], "", "", False
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            typ = ev.get("type")
            if typ == "stream_event":
                se = ev.get("event", {})
                if se.get("type") == "content_block_delta":
                    d = se.get("delta", {})
                    if d.get("type") == "text_delta" and d.get("text"):
                        deltas.append(d["text"])
                        if on_text:
                            on_text(d["text"])
            elif typ == "assistant":
                for block in ev.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        assistant_text += block.get("text", "")
            elif typ == "result":
                result_text = ev.get("result", "") or ""
                is_error = bool(ev.get("is_error"))
    finally:
        try:
            proc.wait(timeout=timeout)
        except Exception:
            proc.kill()

    text = "".join(deltas) or assistant_text or result_text
    if not text and (proc.returncode or is_error):
        err = ""
        try:
            err = proc.stderr.read() if proc.stderr else ""
        except Exception:
            pass
        raise AdapterError((err or "claude advisor failed").strip()[:240] or "claude advisor failed")
    if on_text and not deltas and text:
        on_text(text)  # fell back to a full-text event; show it once
    return text


def _strip_codex_footer(text: str) -> str:
    """codex exec prints the reply, then a 'tokens used\\nN' footer — drop it."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().lower() == "tokens used":
            return "\n".join(lines[:i]).strip()
    return text.strip()


def gpt_assist(prompt: str, *, timeout: int = 60, cwd: Path | None = None,
               runner=subprocess.run) -> str:
    """Fast GPT (Codex) assistant for simple things — read-only, no build.

    GPT is the quick subcontractor: it answers plain questions in seconds
    (`codex exec --sandbox read-only`), leaving slow judgment to Claude and real
    builds to the cycle. `runner` is injectable for testing."""
    exe = shutil.which("codex")
    if not exe:
        raise AdapterError("codex CLI is not installed or not on PATH")
    try:
        r = runner([exe, "exec", "--ephemeral", "--sandbox", "read-only",
                    "--skip-git-repo-check", prompt],
                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=timeout, cwd=str(cwd) if cwd else None,
                   stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("gpt assistant timed out") from exc
    except OSError as exc:
        raise AdapterError(f"gpt assistant failed: {exc}") from exc
    if r.returncode != 0:
        raise AdapterError(((r.stderr or r.stdout) or "gpt assistant failed").strip()[:240])
    return _strip_codex_footer(r.stdout or "")


_ROUTE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["route", "answer", "reason"],
    "properties": {
        "route": {"type": "string", "enum": ["answer", "codex", "claude", "build"]},
        "answer": {"type": "string"},
        "reason": {"type": "string"},
    },
}

_ROUTER_INSTRUCTIONS = """You are Friday's router. Read the user's message and the conversation, then choose ONE route (understand meaning — do not match keywords):
- "answer": trivial chat, greeting, or thanks you can settle in one short line yourself → put that line in "answer".
- "codex": needs reading files, running commands, code/factual lookup, or a concrete technical answer → the fast executor handles it.
- "claude": a judgment call — whether something is right, a decision, a tradeoff, an opinion, or deep reasoning → only the slow judge (Claude) may decide these.
- "build": the user wants software built, created, changed, or fixed → the build cycle.
Return {route, answer, reason}. Leave "answer" empty unless route is "answer"."""


def route_turn(text: str, context: str = "", *, workdir: Path | None = None,
               model: str = "gpt-5.6-terra", timeout: int = 30,
               runner=subprocess.run) -> dict:
    """Fast semantic router: classify a turn into answer | codex | claude | build
    with a small, fast model (default gpt-5.6-luna via codex) using structured
    output. Understands intent, not keywords. `runner` is injectable for testing."""
    exe = shutil.which("codex")
    if not exe:
        raise AdapterError("codex CLI is not installed or not on PATH")
    work = Path(workdir or (Path.cwd() / ".friday" / "route")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    schema = work / "route.schema.json"
    out = work / "route.out.json"
    schema.write_text(json.dumps(_ROUTE_SCHEMA), encoding="utf-8")
    prompt = f"{context}User message: {text}\n\n{_ROUTER_INSTRUCTIONS}"
    cmd = [exe, "exec", "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check",
           "-m", model, "--output-schema", str(schema), "--output-last-message", str(out), prompt]
    try:
        r = runner(cmd, capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, cwd=str(work))
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("router timed out") from exc
    except OSError as exc:
        raise AdapterError(f"router failed: {exc}") from exc
    if r.returncode != 0:
        raise AdapterError(((r.stderr or r.stdout) or "router failed").strip()[:240])
    try:
        payload = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdapterError("router returned unparseable output") from exc
    if not isinstance(payload, dict) or "route" not in payload:
        raise AdapterError("router returned no route")
    return payload


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


def claude_stream(prompt: str, *, on_event=None, model: str | None = None,
                  cwd: Path | None = None, timeout: int = 180,
                  popen=subprocess.Popen) -> str:
    """Run Claude with its tools available (bypassPermissions) so it can read
    files to ground its answer, streaming activity via on_event(event) — tool_use
    calls (Read/Grep/Bash…) like Claude Code shows. Returns the final answer text.
    `cwd` is where it reads; `model` picks haiku (fast) or opus (deep)."""
    exe = shutil.which("claude")
    if not exe:
        raise AdapterError("claude CLI is not installed or not on PATH")
    # Claude cannot write — read-only tools only (it grounds by reading, never edits).
    cmd = [exe, "-p", prompt, "--permission-mode", "bypassPermissions",
           "--allowedTools", "Read", "Grep", "Glob",
           "--output-format", "stream-json", "--include-partial-messages", "--verbose"]
    if model:
        cmd += ["--model", model]
    try:
        proc = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                     encoding="utf-8", errors="replace", cwd=str(cwd) if cwd else None,
                     stdin=subprocess.DEVNULL, bufsize=1)
    except OSError as exc:
        raise AdapterError(f"claude call failed: {exc}") from exc

    seen, result_text, assistant_text = set(), "", ""
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            typ = ev.get("type")
            if typ == "assistant":
                for block in ev.get("message", {}).get("content", []):
                    bt = block.get("type")
                    if bt == "tool_use":
                        key = block.get("id") or f"{block.get('name')}:{block.get('input')}"
                        if key not in seen:
                            seen.add(key)
                            if on_event:
                                on_event({"kind": "tool_use", "name": block.get("name", ""),
                                          "input": block.get("input", {}) or {}})
                    elif bt == "text":
                        assistant_text = block.get("text", "")
            elif typ == "result":
                result_text = ev.get("result", "") or ""
    finally:
        try:
            proc.wait(timeout=timeout)
        except Exception:
            proc.kill()

    text = result_text or assistant_text
    if not text and proc.returncode:
        err = ""
        try:
            err = proc.stderr.read() if proc.stderr else ""
        except Exception:
            pass
        raise AdapterError((err or "claude failed").strip()[:240] or "claude failed")
    return text


def exec_summary(root: Path) -> str:
    """A one-line, read-only summary of what GPT is doing, for the advisor's
    context (spec §5.3 / D4 — conversation sees execution state, read-only)."""
    import json
    try:
        st = json.loads((Path(root) / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    rounds = st.get("rounds", [])
    last = rounds[-1] if rounds else {}
    return (f"status={st.get('status', '?')} round={st.get('round', 0)} "
            f"last_quadrant={last.get('quadrant', '-')}").strip()


def build_conversation_engine(root, config, *, claude_fn=None, exec_summary_fn=None,
                              on_text=None):
    """Wire a ConversationEngine to the real Claude advisor (spec §5). When
    on_text is given, replies stream token-by-token through it (real-time chat)."""
    from .kernel import Authority
    from .route import Router
    from .convo import ConversationEngine

    root = Path(root)
    timeout = int(config.get("timeout_seconds", 120))
    if claude_fn is not None:
        fn = claude_fn
    elif on_text is not None:
        fn = lambda prompt: claude_advisor_stream(prompt, on_text=on_text, timeout=timeout)
    else:
        fn = lambda prompt: claude_advisor(prompt, timeout=timeout)
    summary_fn = exec_summary_fn or (lambda: exec_summary(root))
    return ConversationEngine(
        root, Authority(), Router(root), fn,
        budget_chars=int(config.get("convo_budget_chars", 40000)),
        recent_turns=int(config.get("convo_recent_turns", 12)),
        exec_summary_fn=summary_fn,
    )
