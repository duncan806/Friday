"""muto CLI—the launcher, cross-platform. (spec §9 + the screen-first flow)

Commands:
  muto          home (default): open the dashboard, stream POST checks into
                status.js, then wait for the human to start the cycle
  muto init     create a cycle workspace in the current directory
                (workspace/, task/, reports/...—code and data separated)
  muto doctor   POST checks only (claude/codex/auth), terminal output
  muto run      start the cycle
  muto stop     drop stop.flag (the loop halts before the next round)

The package (code) lives in site-packages; cycle data lives wherever the
user ran `muto init`. Every command except doctor operates on the workspace
in the current directory.
"""

import argparse
import shutil
import subprocess
import sys
import webbrowser
from importlib import resources
from pathlib import Path

import yaml

from .dashboard_gen import generate, write_status
from .orchestrator import CycleState, Orchestrator

MARKER = "config.yaml"

DEFAULT_CONFIG = """\
# muto config—spec §2, §9
bandwidth_level: 1        # bandwidth dial: 1 (action/where only) | 2 (expected allowed). Change per cycle only.
round_budget: 10          # round budget. Cycle ends when exhausted.
auth_mode: subscription   # subscription | api_key (ANTHROPIC_API_KEY / OPENAI_API_KEY)
timeout_seconds: 1800     # agent subprocess timeout
"""

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
        ("CODEX AUTH",
         lambda: _auth_probe(["codex", "exec", "--sandbox", "read-only",
                              "reply with exactly: ok"]),
         "run codex login"),
    ]
    if root is not None:
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


def cmd_home() -> int:
    root = find_root()
    if root is None:
        cmd_init()
        root = require_root()

    # Screen first: open the dashboard, then stream the checks into status.js.
    write_status(root, "boot")
    webbrowser.open((root / "dashboard" / "index.html").resolve().as_uri())

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
    try:
        input("Press Enter to START CYCLE... ")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 1
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="muto",
        description="Validation through enforced information asymmetry.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="create a cycle workspace in the current directory")
    sub.add_parser("doctor", help="run POST checks (claude/codex/auth) in the terminal")
    sub.add_parser("run", help="start the cycle")
    sub.add_parser("stop", help="signal the running cycle to halt")
    args = parser.parse_args(argv)

    return {
        None: cmd_home,
        "init": cmd_init,
        "doctor": cmd_doctor,
        "run": cmd_run,
        "stop": cmd_stop,
    }[args.command]()
