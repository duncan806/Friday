"""muto CLI—the launcher, cross-platform. (spec §9 + the screen-first flow)

Commands:
  muto          home (default): open the dashboard as a standalone app window,
                stream POST checks into status.js, then start the cycle
  muto init     create a cycle workspace in the current directory
                (workspace/, task/, reports/...—code and data separated)
  muto doctor   POST checks only (claude/codex/auth), terminal output
  muto run      start the cycle
  muto stop     drop stop.flag (the loop halts before the next round)
  muto shortcut create a desktop shortcut targeting this workspace

The package (code) lives in site-packages; cycle data lives wherever the
user ran `muto init`. Every command except doctor operates on the workspace
in the current directory.
"""

import argparse
import os
import shutil
import subprocess
import sys
import webbrowser
from importlib import resources
from pathlib import Path

import yaml

from . import gitutil
from .dashboard_gen import generate, write_status
from .orchestrator import CycleState, Orchestrator

MARKER = "config.yaml"

DEFAULT_CONFIG = """\
# muto config—spec §2, §9
bandwidth_level: 1        # bandwidth dial: 1 (action/where only) | 2 (expected allowed). Change per cycle only.
round_budget: 10          # round budget. Cycle ends when exhausted.
auth_mode: subscription   # subscription | api_key (ANTHROPIC_API_KEY / OPENAI_API_KEY)
timeout_seconds: 1800     # agent subprocess timeout
window: true              # open the dashboard as a standalone app window (Chrome/Edge --app); false = default browser tab
"""

WINDOW_SIZE = (1024, 768)

WORKSPACE_DIRS = [
    "workspace/src", "workspace/surface", "task", "reports/dropped",
    "predictions", "verdicts", "dashboard", "prompts",
]


def find_root() -> Path | None:
    cwd = Path.cwd()
    return cwd if (cwd / MARKER).is_file() else None


def require_root() -> Path:
    root = find_root()
    if root is None:
        print("No muto workspace here (config.yaml missing). Run: muto init",
              file=sys.stderr)
        raise SystemExit(1)
    return root


def load_config(root: Path) -> dict:
    try:
        return yaml.safe_load((root / MARKER).read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


# ── standalone app window (Chrome/Edge --app) ───────────────────────────────

def find_browser() -> Path | None:
    """Locate a Chromium-family browser that supports --app windows."""
    candidates = []
    if os.name == "nt":
        bases = [os.environ.get("PROGRAMFILES", ""),
                 os.environ.get("PROGRAMFILES(X86)", ""),
                 os.environ.get("LOCALAPPDATA", "")]
        rel = [r"Google\Chrome\Application\chrome.exe",
               r"Microsoft\Edge\Application\msedge.exe",
               r"Chromium\Application\chrome.exe",
               r"BraveSoftware\Brave-Browser\Application\brave.exe"]
        for base in bases:
            for r in rel:
                if base:
                    candidates.append(Path(base) / r)
        exes = ("chrome", "msedge", "chromium", "brave")
    else:
        exes = ("google-chrome", "google-chrome-stable", "chromium",
                "chromium-browser", "microsoft-edge", "brave-browser")
        candidates += [Path(p) for p in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium")]
    for exe in exes:
        found = shutil.which(exe)
        if found:
            candidates.append(Path(found))
    for c in candidates:
        if c.is_file():
            return c
    return None


def open_app_window(browser: Path, url: str, size=WINDOW_SIZE) -> bool:
    """Launch a chrome-tabless app window; detached, non-blocking."""
    try:
        subprocess.Popen(
            [str(browser), f"--app={url}",
             f"--window-size={size[0]},{size[1]}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def launch_dashboard(root: Path, window: bool) -> str:
    """Open the dashboard. Standalone app window if possible, else a tab."""
    url = (root / "dashboard" / "index.html").resolve().as_uri()
    if window:
        browser = find_browser()
        if browser and open_app_window(browser, url):
            return "app"
        print("  (no Chrome/Edge found—opening in the default browser)")
    webbrowser.open(url)
    return "tab"


# ── POST checks ────────────────────────────────────────────────────────────

def _auth_probe(cmd: list) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=180).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run_checks(root: Path | None, on_update=None) -> tuple[list, bool]:
    """Run the POST checks in order, calling on_update(checks) after each.

    Returns (checks, all_ok). A check failure stops the sequence—later
    checks stay unreported, matching BIOS POST behavior.
    """
    plan = [
        ("CLAUDE CLI", lambda: shutil.which("claude") is not None,
         "install it: see https://claude.com/claude-code"),
        ("CODEX CLI", lambda: shutil.which("codex") is not None,
         "install it: npm install -g @openai/codex"),
        ("CLAUDE AUTH",
         lambda: _auth_probe(["claude", "-p", "reply with exactly: ok"]),
         "run claude once and complete the browser login"),
        # --skip-git-repo-check so a missing repo can't masquerade as an auth
        # failure; this probe measures auth validity only (matches CLAUDE AUTH).
        ("CODEX AUTH",
         lambda: _auth_probe(["codex", "exec", "--sandbox", "read-only",
                              "--skip-git-repo-check", "reply with exactly: ok"]),
         "run codex login"),
    ]
    if root is not None:
        plan.append(("WORKSPACE GIT",
                     lambda: gitutil.is_repo(root / "workspace"),
                     "run: muto init  (workspace/ must be a git repo so Codex can commit per-round diffs)"))
        plan.append(("TASK FILE",
                     lambda: (root / "task" / "task.md").is_file(),
                     "write task/task.md first (a template was created by muto init)"))

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


def _print_post(checks) -> None:
    line = checks[-1]
    label = f"CHECKING {line['name']} ".ljust(34, ".")
    state = " OK " if line["state"] == "ok" else "FAIL"
    print(f"{label} [{state}]")
    if line["hint"]:
        print(f"  -> {line['hint']}")


# ── commands ───────────────────────────────────────────────────────────────

def cmd_init() -> int:
    root = Path.cwd()
    for d in WORKSPACE_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    if not (root / MARKER).is_file():
        (root / MARKER).write_text(DEFAULT_CONFIG, encoding="utf-8")
    for name in ("claude_user.md", "codex_builder.md"):
        target = root / "prompts" / name
        if not target.is_file():
            target.write_text(
                resources.files("muto").joinpath("data/prompts", name)
                .read_text(encoding="utf-8"), encoding="utf-8")
    task = root / "task" / "task.md"
    if not task.is_file():
        task.write_text(
            resources.files("muto").joinpath("data/task_template.md")
            .read_text(encoding="utf-8"), encoding="utf-8")
    # workspace/ becomes its own git repo so Codex can run and leave
    # per-round diff history (spec §7).
    if not gitutil.init_repo(root / "workspace"):
        print("  warning: git not found—workspace/ is not a repo; "
              "Codex will refuse to build until git is installed and "
              "you re-run muto init.")
    generate(CycleState(), root)
    write_status(root, "boot")
    print(f"muto workspace initialized in {root}")
    print("Next: write task/task.md, then run: muto")
    return 0


def cmd_doctor() -> int:
    root = find_root()
    checks, ok = run_checks(root, on_update=_print_post)
    print("ALL CHECKS PASSED." if ok else "BOOT HALTED.")
    return 0 if ok else 1


def cmd_home(window: bool | None = None) -> int:
    root = find_root()
    if root is None:
        cmd_init()
        root = require_root()

    if window is None:
        window = bool(load_config(root).get("window", True))

    # Screen first: open the dashboard, then stream the checks into status.js.
    write_status(root, "boot")
    launch_dashboard(root, window)

    def stream(checks):
        write_status(root, "boot", checks=checks,
                     task_present=(root / "task" / "task.md").is_file())
        _print_post(checks)

    checks, ok = run_checks(root, on_update=stream)
    if not ok:
        write_status(root, "failed", checks=checks)
        print("BOOT HALTED. See the dashboard, fix the item, run muto again.")
        return 1

    write_status(root, "ready", checks=checks, task_present=True)
    print("ALL CHECKS PASSED.")
    # The Enter gate needs an interactive console. When launched without one
    # (e.g. via the no-console `mutow` entry / a desktop shortcut), start the
    # cycle automatically—the app window is the only surface the user sees.
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("Press Enter to START CYCLE... ")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 1
    else:
        print("No interactive console; starting cycle automatically.")
    return cmd_run()


def cmd_run() -> int:
    root = require_root()
    if not (root / "task" / "task.md").is_file():
        print("task/task.md missing. Plant the task first.", file=sys.stderr)
        return 1
    from .bandwidth_filter import apply_filter
    orch = Orchestrator(root=root, filter_fn=apply_filter, dashboard_fn=generate)
    state = orch.run_cycle()
    print(f"cycle finished: {state.status}")
    for r in state.rounds:
        print(f"  R{r.round}: {r.quadrant}")
    return 0


def cmd_stop() -> int:
    root = require_root()
    (root / "stop.flag").write_text("stop", encoding="utf-8")
    print("stop.flag written—the cycle halts before the next round.")
    return 0


# ── desktop shortcut ────────────────────────────────────────────────────────

def _install_icon(root: Path) -> Path:
    """Copy the packaged app icon into the workspace for the shortcut."""
    name, res = ("muto.ico", "data/muto.ico") if os.name == "nt" \
        else ("muto.png", "data/favicon.png")
    dst = root / name
    dst.write_bytes(resources.files("muto").joinpath(res).read_bytes())
    return dst


def _shortcut_windows(root: Path, icon: Path) -> int:
    # Prefer the no-console entry so the shortcut opens just the app window.
    target = shutil.which("mutow") or shutil.which("muto")
    if not target:
        print("muto executable not found on PATH; install muto first.",
              file=sys.stderr)
        return 1
    ps = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$w=New-Object -ComObject WScript.Shell;"
        "$s=$w.CreateShortcut((Join-Path $d 'MUTO.lnk'));"
        f"$s.TargetPath='{target}';"
        f"$s.WorkingDirectory='{root}';"
        f"$s.IconLocation='{icon}';"
        "$s.Description='muto validation cycle';"
        "$s.Save()"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("Failed to create shortcut:\n" + r.stderr, file=sys.stderr)
        return 1
    print("Desktop shortcut created: MUTO.lnk")
    return 0


def _shortcut_linux(root: Path, icon: Path) -> int:
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=MUTO\n"
        "Comment=muto validation cycle\n"
        "Exec=muto\n"
        f"Path={root}\n"
        f"Icon={icon}\n"
        "Terminal=true\n"
    )
    made = []
    for d in (Path.home() / "Desktop", Path.home() / ".local/share/applications"):
        if d.is_dir() or d == Path.home() / ".local/share/applications":
            d.mkdir(parents=True, exist_ok=True)
            p = d / "muto.desktop"
            p.write_text(entry, encoding="utf-8")
            p.chmod(0o755)
            made.append(p)
    print("Desktop entry created: " + ", ".join(str(p) for p in made))
    return 0


def _shortcut_macos(root: Path, icon: Path) -> int:
    p = Path.home() / "Desktop" / "MUTO.command"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'#!/bin/bash\ncd "{root}"\nexec muto\n', encoding="utf-8")
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
        prog="muto",
        description="Validation through enforced information asymmetry.")
    win = parser.add_mutually_exclusive_group()
    win.add_argument("--window", dest="window", action="store_true", default=None,
                     help="open the dashboard as a standalone app window (default)")
    win.add_argument("--no-window", dest="window", action="store_false",
                     help="open the dashboard in the default browser tab")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="create a cycle workspace in the current directory")
    sub.add_parser("doctor", help="run POST checks (claude/codex/auth) in the terminal")
    sub.add_parser("run", help="start the cycle")
    sub.add_parser("stop", help="signal the running cycle to halt")
    sub.add_parser("shortcut", help="create a desktop shortcut for this workspace")
    args = parser.parse_args(argv)

    if args.command is None:
        return cmd_home(window=args.window)
    return {
        "init": cmd_init,
        "doctor": cmd_doctor,
        "run": cmd_run,
        "stop": cmd_stop,
        "shortcut": cmd_shortcut,
    }[args.command]()
