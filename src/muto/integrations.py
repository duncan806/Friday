"""Local CLI integrations for GitHub, Claude Code, and Codex."""

import json
from datetime import datetime, timezone
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
        return subprocess.run(command, cwd=cwd, capture_output=True, text=True,
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


def connect(root: Path, provider: str) -> int:
    """Start the provider's official interactive login only on explicit selection."""
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    spec = PROVIDERS[provider]
    if not shutil.which(spec["exe"]):
        raise RuntimeError(f"{spec['exe']} CLI is not installed")
    return subprocess.run(spec["login"], cwd=root).returncode


def sync_github(root: Path) -> int:
    """Explicitly push committed round history; never called automatically."""
    state = inspect(root).get("github", {})
    if not state.get("authenticated"):
        raise RuntimeError("GitHub CLI is not authenticated")
    if not state.get("remote"):
        raise RuntimeError("workspace has no origin remote")
    return subprocess.run(["git", "push", "origin", "HEAD"], cwd=Path(root) / "workspace").returncode


def pull_requests(root: Path) -> list[dict]:
    """Read open PRs for the connected workspace repository."""
    result = _run(["gh", "pr", "list", "--json", "number,title,url,headRefName,state"],
                  Path(root) / "workspace")
    if not result or result.returncode != 0:
        raise RuntimeError(((result.stderr if result else "") or "unable to read pull requests").strip())
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError("GitHub returned invalid PR data") from exc


def create_pull_request(root: Path, title: str, body: str = "", base: str = "") -> str:
    """Push the current branch and create a PR after an explicit TUI action."""
    root = Path(root)
    state = inspect(root).get("github", {})
    if not state.get("authenticated") or not state.get("remote"):
        raise RuntimeError("connect GitHub and configure workspace/origin first")
    branch = state.get("branch")
    if not branch:
        raise RuntimeError("workspace is not on a named branch")
    pushed = subprocess.run(["git", "push", "-u", "origin", branch], cwd=root / "workspace")
    if pushed.returncode != 0:
        raise RuntimeError("branch push failed")
    command = ["gh", "pr", "create", "--title", title, "--body", body]
    if base:
        command += ["--base", base]
    made = subprocess.run(command, cwd=root / "workspace", capture_output=True, text=True)
    if made.returncode != 0:
        raise RuntimeError((made.stderr or made.stdout or "PR creation failed").strip())
    url = made.stdout.strip().splitlines()[-1]
    record_dir = root / "github"
    record_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (record_dir / f"pr_{stamp}.json").write_text(json.dumps({
        "url": url, "title": title, "body": body, "base": base,
        "branch": branch, "created_at": stamp,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return url


def connect_repository(root: Path, url: str) -> None:
    workspace = Path(root) / "workspace"
    current = _run(["git", "remote", "get-url", "origin"], workspace)
    command = ["git", "remote", "set-url" if current and current.returncode == 0 else "add", "origin", url]
    result = subprocess.run(command, cwd=workspace, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "unable to configure origin").strip())
    inspect(root)


def create_repository(root: Path, name: str, visibility: str = "private") -> str:
    if visibility not in ("private", "public"):
        raise ValueError("visibility must be private or public")
    command = ["gh", "repo", "create", name, f"--{visibility}", "--source", ".",
               "--remote", "origin", "--push"]
    result = subprocess.run(command, cwd=Path(root) / "workspace", capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "repository creation failed").strip())
    inspect(root)
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else name
