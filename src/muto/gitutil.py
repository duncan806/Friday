"""Workspace git helpers—shared by `muto init` and the round loop.

Codex requires a git repo: the orchestrator invokes `codex exec` with
`--cd workspace` (spec §3), and codex refuses to run outside a repo. Rather
than pass `--skip-git-repo-check`, `muto init` makes workspace/ its own repo
and the round loop commits after every Codex turn—so Codex's changes leave
per-round history and the human can observe diff stats (spec §7).

All operations are best-effort and guarded: if git is absent or workspace/
is not a repo, the round loop simply skips committing.
"""

import shutil
import subprocess
from pathlib import Path

# Inline identity so commits succeed regardless of global git config.
_IDENT = ["-c", "user.email=muto@localhost", "-c", "user.name=muto"]


def git_available() -> bool:
    return shutil.which("git") is not None


def is_repo(workspace: Path) -> bool:
    """True only when workspace/ is its own git repo (not a parent's)."""
    return (Path(workspace) / ".git").is_dir()


def _run(args, cwd) -> bool:
    try:
        return subprocess.run(args, cwd=str(cwd), capture_output=True,
                              text=True).returncode == 0
    except OSError:
        return False


def init_repo(workspace: Path) -> bool:
    """git init workspace/ + an empty baseline commit. Idempotent.

    Returns True if workspace/ is a repo afterward, False if git is missing.
    """
    workspace = Path(workspace)
    if is_repo(workspace):
        return True
    if not git_available():
        return False
    workspace.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q"], workspace)
    _run(["git", *_IDENT, "commit", "--allow-empty", "-q", "-m",
          "muto: round 0 (workspace initialized)"], workspace)
    return is_repo(workspace)


def commit_round(workspace: Path, n: int) -> bool:
    """Snapshot the workspace after a Codex turn. No-op if not a repo."""
    workspace = Path(workspace)
    if not is_repo(workspace) or not git_available():
        return False
    _run(["git", "add", "-A"], workspace)
    return _run(["git", *_IDENT, "commit", "--allow-empty", "-q", "-m",
                 f"muto: round {n}"], workspace)
