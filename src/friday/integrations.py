"""Local CLI integrations for GitHub, Claude Code, and Codex."""

import json
import shutil
import subprocess
from pathlib import Path


PROVIDERS = {
    "github": {"exe": "gh", "auth": ["gh", "auth", "status"], "login": ["gh", "auth", "login"]},
    "claude": {"exe": "claude", "auth": ["claude", "auth", "status"], "login": ["claude"]},
    "codex": {"exe": "codex", "auth": ["codex", "login", "status"], "login": ["codex", "login"]},
}


def _run(command: list[str], cwd: Path, timeout: int = 20) -> subprocess.CompletedProcess | None:
    try:
        executable = shutil.which(command[0])
        if not executable:
            return None
        return subprocess.run([executable, *command[1:]], cwd=cwd,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


def inspect(root: Path) -> dict:
    root = Path(root)
    result = {}
    for name, spec in PROVIDERS.items():
        executable = shutil.which(spec["exe"])
        probe = _run(spec["auth"], root) if executable else None
        item = {"installed": bool(executable), "authenticated": bool(probe and probe.returncode == 0)}
        if probe and probe.returncode != 0:
            item["detail"] = ((probe.stderr or probe.stdout) or "not authenticated").strip()[:240]
        result[name] = item

    workspace = root / "workspace"
    remote = _run(["git", "remote", "get-url", "origin"], workspace)
    branch = _run(["git", "branch", "--show-current"], workspace)
    result["github"]["remote"] = remote.stdout.strip() if remote and remote.returncode == 0 else ""
    result["github"]["branch"] = branch.stdout.strip() if branch and branch.returncode == 0 else ""
    path = root / "integrations.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return result


