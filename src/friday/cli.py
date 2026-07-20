"""friday CLI — launcher for the decide-and-build terminal.

  friday            open the terminal (default): Claude decides, Codex builds
  friday init       create a friday workspace in the current directory
  friday shortcut   create a desktop shortcut targeting this workspace
"""

import argparse
import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

MARKER = "config.yaml"

DEFAULT_CONFIG = """\
# friday
round_budget: 30          # max overseer reviews per goal (a runaway backstop)
timeout_seconds: 600      # cut a stalled agent call (seconds)
review_seconds: 25        # timer fallback for how often Claude reviews Codex
codex_model: gpt-5.6-luna # fast model the builder runs on
verify_command: ""        # command Claude may run to verify (e.g. "python -m pytest -q")
"""


def find_root() -> Path | None:
    cwd = Path.cwd()
    return cwd if (cwd / MARKER).is_file() else None


def default_workspace_root() -> Path:
    """A deterministic location removes directory choice from normal startup."""
    return Path.home() / "FRIDAY"


def require_root() -> Path:
    root = find_root()
    if root is None:
        print("No friday workspace here (config.yaml missing). Run: friday init",
              file=sys.stderr)
        raise SystemExit(1)
    return root


# ── environment checks ───────────────────────────────────────────────────────

def _auth_probe(cmd: list) -> bool:
    try:
        exe = shutil.which(cmd[0])
        if not exe:
            return False
        return subprocess.run([exe, *cmd[1:]], capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run_checks(root: Path | None, on_update=None) -> tuple[list, bool]:
    """Check the two CLIs Friday drives are installed and signed in. A failure
    stops the sequence (BIOS-POST style)."""
    plan = [
        ("CLAUDE CLI", lambda: shutil.which("claude") is not None,
         "install it: see https://claude.com/claude-code"),
        ("CODEX CLI", lambda: shutil.which("codex") is not None,
         "install it: npm install -g @openai/codex"),
        ("CLAUDE AUTH", lambda: _auth_probe(["claude", "auth", "status"]),
         "run claude once and complete the login"),
        ("CODEX AUTH", lambda: _auth_probe(["codex", "login", "status"]),
         "run codex login"),
    ]
    checks = []
    for name, probe, hint in plan:
        ok = probe()
        checks.append({"name": name, "state": "ok" if ok else "fail",
                       "hint": "" if ok else hint})
        if on_update:
            on_update(checks)
        if not ok:
            return checks, False
    return checks, True


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_init() -> int:
    root = Path.cwd()
    if not (root / MARKER).is_file():
        (root / MARKER).write_text(DEFAULT_CONFIG, encoding="utf-8")
    print(f"friday ready in {root}")
    print("Run: friday")
    return 0


def cmd_home() -> int:
    root = find_root()
    if root is None:
        target = default_workspace_root()
        target.mkdir(parents=True, exist_ok=True)
        os.chdir(target)
        cmd_init()
        root = require_root()
    from .tui import run as run_tui

    def _noop(*_a, **_k):
        return 0

    return run_tui(root, run_checks, _noop, _noop)


# ── desktop shortcut ─────────────────────────────────────────────────────────

def _install_icon(root: Path) -> Path:
    name, res = ("friday.ico", "data/friday.ico") if os.name == "nt" \
        else ("friday.png", "data/favicon.png")
    dst = root / name
    dst.write_bytes(resources.files("friday").joinpath(res).read_bytes())
    return dst


def _shortcut_windows(root: Path, icon: Path) -> int:
    target = shutil.which("fridayw") or shutil.which("friday")
    if not target:
        print("friday executable not found on PATH; install friday first.", file=sys.stderr)
        return 1
    ps = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$w=New-Object -ComObject WScript.Shell;"
        "$s=$w.CreateShortcut((Join-Path $d 'FRIDAY.lnk'));"
        f"$s.TargetPath='{target}';"
        f"$s.WorkingDirectory='{root}';"
        f"$s.IconLocation='{icon}';"
        "$s.Description='friday';"
        "$s.Save()"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("Failed to create shortcut:\n" + r.stderr, file=sys.stderr)
        return 1
    print("Desktop shortcut created: FRIDAY.lnk")
    return 0


def _shortcut_linux(root: Path, icon: Path) -> int:
    entry = ("[Desktop Entry]\nType=Application\nName=FRIDAY\nComment=friday\n"
             f"Exec=friday\nPath={root}\nIcon={icon}\nTerminal=true\n")
    made = []
    for d in (Path.home() / "Desktop", Path.home() / ".local/share/applications"):
        if d.is_dir() or d == Path.home() / ".local/share/applications":
            d.mkdir(parents=True, exist_ok=True)
            p = d / "friday.desktop"
            p.write_text(entry, encoding="utf-8")
            p.chmod(0o755)
            made.append(p)
    print("Desktop entry created: " + ", ".join(str(p) for p in made))
    return 0


def _shortcut_macos(root: Path, icon: Path) -> int:
    p = Path.home() / "Desktop" / "FRIDAY.command"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'#!/bin/bash\ncd "{root}"\nexec friday\n', encoding="utf-8")
    p.chmod(0o755)
    print(f"Desktop launcher created: {p}")
    return 0


def cmd_shortcut() -> int:
    root = require_root()
    icon = _install_icon(root)
    if os.name == "nt":
        return _shortcut_windows(root, icon)
    if sys.platform == "darwin":
        return _shortcut_macos(root, icon)
    return _shortcut_linux(root, icon)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="friday",
        description="A terminal you hand a goal to: Claude decides, Codex builds.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="create a friday workspace here")
    sub.add_parser("shortcut", help="create a desktop shortcut")
    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init()
    if args.command == "shortcut":
        return cmd_shortcut()
    return cmd_home()
