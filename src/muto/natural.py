"""Codex-backed natural-language control-plane interpretation."""

from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import subprocess


KINDS = ("task", "start", "stop", "status", "context", "data", "connect",
         "github", "pr", "verdict", "quit", "noop")


@dataclass
class Intent:
    kind: str
    text: str = ""
    args: dict = field(default_factory=dict)


SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "text", "args"],
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "text": {"type": "string"},
        "args": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string"},
                "provider": {"type": "string", "enum": ["github", "claude", "codex", ""]},
                "verdict": {"type": "string", "enum": ["INEVITABLE", "PREDICTABLE", ""]},
                "reason": {"type": "string"},
                "operation": {"type": "string", "enum": ["", "list", "create", "sync"]},
            },
            "required": ["path", "provider", "verdict", "reason", "operation"],
        },
    },
}


def interpret(text: str, status: str = "ready", runtime_dir: Path | None = None,
              timeout: int = 60, providers: tuple[str, ...] = ("codex", "claude")) -> Intent:
    """Ask isolated CLI adapters for a typed intent, with ordered failover."""
    raw = text.strip()
    if not raw:
        return Intent("noop")
    runtime = Path(runtime_dir or Path.cwd() / ".muto" / "control").resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    schema = runtime / "intent.schema.json"
    output = runtime / "intent.output.json"
    schema.write_text(json.dumps(SCHEMA, indent=2), encoding="utf-8")
    prompt = f"""You are the natural-language control plane for muto.
Classify the user's request into exactly one typed action. Do not execute tools.
The current cycle status is {status!r}.

Rules:
- A product request or desired outcome is `task`; preserve it verbatim in text.
- A request to attach a local file is `data` and its path goes in args.path.
- Provider login/linking is `connect` with github, claude, or codex.
- GitHub synchronization is `github` with operation `sync`.
- Creating or viewing a pull request is `pr` with operation `create` or `list`;
  preserve the request in text.
- A final judgment is `verdict` only while awaiting_verdict.
- Use `noop` only when there is no actionable request.
- Fill unused args fields with empty strings.

User input:
{raw}
"""
    errors = []
    for provider in providers:
        try:
            executable = shutil.which(provider)
            if not executable:
                raise OSError(f"{provider} CLI is not installed or not on PATH")
            if provider == "codex":
                command = [executable, "exec", "--ephemeral", "--ignore-rules",
                           "--sandbox", "read-only", "--skip-git-repo-check",
                           "--output-schema", str(schema), "--output-last-message", str(output), prompt]
            elif provider == "claude":
                command = [executable, "-p", prompt, "--tools", "",
                           "--permission-mode", "dontAsk", "--no-session-persistence",
                           "--output-format", "json", "--json-schema", json.dumps(SCHEMA)]
            else:
                raise ValueError(f"unsupported intent provider: {provider}")
            result = subprocess.run(command, cwd=runtime, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=timeout,
                                    stdin=subprocess.DEVNULL)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or
                                    f"{provider} routing failed").strip())
            if provider == "codex":
                payload = json.loads(output.read_text(encoding="utf-8"))
            else:
                envelope = json.loads(result.stdout)
                payload = envelope.get("structured_output")
                if payload is None:
                    payload = json.loads(envelope.get("result", "{}"))
            return Intent(payload["kind"], payload.get("text", ""), payload.get("args", {}))
        except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, KeyError) as exc:
            errors.append(f"{provider}: {exc}")
    raise RuntimeError("Natural-language routing failed (" + "; ".join(errors) + ")")
