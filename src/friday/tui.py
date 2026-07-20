"""Dependency-free terminal UI inspired by modern coding-agent CLIs."""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

from .integrations import inspect

ESC = "\x1b["
ORANGE, IVORY = ESC + "38;5;208m", ESC + "38;5;230m"
ICE = ESC + "38;5;117m"          # Codex — icy blue (Claude stays Hermès orange)
WHITE = ESC + "38;5;255m"        # the user's own words
YELLOW, CYAN, DIM, RED, RESET = ORANGE, IVORY, ESC + "38;5;245m", ESC + "38;5;203m", ESC + "0m"
VT_ENABLED = os.name != "nt"


def _enable_terminal():
    """Enable ANSI processing on Windows; retain a non-ANSI clear fallback."""
    global VT_ENABLED
    # UTF-8 stdio so streamed Claude/Codex output (em-dashes, emoji, Hangul)
    # never crashes the UI on a legacy console code page (e.g. Windows cp949).
    for stream in (sys.stdout, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except (AttributeError, OSError):
            pass
    if os.name != "nt":
        VT_ENABLED = True
        return
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            VT_ENABLED = bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        VT_ENABLED = False


def _clear():
    if VT_ENABLED:
        print(ESC + "2J" + ESC + "H", end="", flush=True)
    elif os.name == "nt":
        os.system("cls")


def _status(root: Path) -> dict:
    try:
        return json.loads((root / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "boot", "status": "unknown", "round": 0}


_BANNER = (
    "███████╗ ██████╗  ██╗ ██████╗   █████╗  ██╗   ██╗",
    "██╔════╝ ██╔══██╗ ██║ ██╔══██╗ ██╔══██╗ ╚██╗ ██╔╝",
    "█████╗   ██████╔╝ ██║ ██║  ██║ ███████║  ╚████╔╝ ",
    "██╔══╝   ██╔══██╗ ██║ ██║  ██║ ██╔══██║   ╚██╔╝  ",
    "██║      ██║  ██║ ██║ ██████╔╝ ██║  ██║    ██║   ",
    "╚═╝      ╚═╝  ╚═╝ ╚═╝ ╚═════╝  ╚═╝  ╚═╝    ╚═╝   ",
)


def _short_path(root: Path) -> str:
    try:
        home = Path.home().resolve()
        r = Path(root).resolve()
        if r == home:
            return "~"
        if home in r.parents:
            return "~/" + r.relative_to(home).as_posix()
    except (OSError, ValueError):
        pass
    return str(root)


def _header(root: Path):
    for line in _BANNER:                     # "Fri" in Hermès orange, "Day" in ivory
        print(f"{ORANGE}{line[:21]}{IVORY}{line[21:]}{RESET}")
    print(f"{DIM}   not knowing is the asset{RESET}")


def loading(root: Path, checks_fn) -> bool:
    checks, result, done = [], {"ok": False}, threading.Event()

    def update(items):
        checks[:] = list(items)

    def work():
        _, result["ok"] = checks_fn(root, on_update=update)
        done.set()

    threading.Thread(target=work, daemon=True).start()
    _clear()
    print(f"{ORANGE}friday{RESET}  {DIM}initializing…{RESET}\n")
    printed = 0
    i = 0
    while not done.wait(0.08):
        while printed < len(checks):
            check = checks[printed]
            icon = f"{CYAN}[ok]{RESET}" if check["state"] == "ok" else f"{RED}[!!]{RESET}"
            print(f"\r{' ' * 72}\r  {icon} {check['name'].lower()}")
            if check.get("hint"):
                print(f"       {DIM}{check['hint']}{RESET}")
            printed += 1
        print(f"\r  {ORANGE}{_BRAILLE[i % len(_BRAILLE)]}{RESET} verifying local environment", end="", flush=True)
        i += 1
    while printed < len(checks):
        check = checks[printed]
        icon = f"{CYAN}[ok]{RESET}" if check["state"] == "ok" else f"{RED}[!!]{RESET}"
        print(f"\r{' ' * 72}\r  {icon} {check['name'].lower()}")
        if check.get("hint"): print(f"       {DIM}{check['hint']}{RESET}")
        printed += 1
    print(f"\r{' ' * 72}\r  {IVORY}[ready]{RESET} environment verified")
    time.sleep(0.25)
    return result["ok"]


def _fmt_elapsed(seconds: float) -> str:
    """Compact elapsed time, in the spirit of Claude Code's '3m 40s' status."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


_BRAILLE = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"   # smooth spinner while an agent is thinking


def _spin_call(label: str, color: str, note: str, fn):
    """Run a blocking model call in a thread while animating a live spinner —
    so the real waiting process shows a heartbeat instead of freezing."""
    result: dict = {}
    done = threading.Event()

    def work():
        try:
            result["v"] = fn()
        except Exception as exc:                # noqa: BLE001 — re-raised below
            result["e"] = exc
        done.set()

    threading.Thread(target=work, daemon=True).start()
    i = 0
    start = time.monotonic()
    while not done.wait(0.09):
        frame = _BRAILLE[i % len(_BRAILLE)]
        el = _fmt_elapsed(time.monotonic() - start)
        print(f"\r  {color}●{RESET} {color}{label}{RESET} {DIM}· {note} {frame} {el}{RESET}   ",
              end="", flush=True)
        i += 1
    print("\r" + " " * 64 + "\r", end="", flush=True)
    if "e" in result:
        raise result["e"]
    return result.get("v")


def _integration_line(root: Path) -> str:
    try:
        data = json.loads((root / "integrations.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    hue = {"claude": ORANGE, "codex": ICE, "github": IVORY}
    parts = []
    for name in ("claude", "codex", "github"):
        item = data.get(name, {})
        if item.get("authenticated"):
            parts.append(f"{hue[name]}●{RESET} {IVORY}{name}{RESET}")
        elif item.get("installed"):
            parts.append(f"{DIM}◐ {name}{RESET}")
        else:
            parts.append(f"{DIM}○ {name}{RESET}")
    return "   ".join(parts)


def _home(root: Path, state: dict):
    print()
    print(f"  {_integration_line(root)}     {DIM}{_short_path(root)}{RESET}")
    status = state.get("status") or ""
    if status and status not in ("ready", "boot", "unknown"):
        print(f"  {DIM}· {status.replace('_', ' ')} · round {state.get('round', 0)}{RESET}")
    print(f"\n  {DIM}{ORANGE}Claude{DIM} is PM, {ICE}Codex{DIM} builds — "
          f"they work your goal together while you watch.{RESET}")


def _key():
    if os.name == "nt":
        import msvcrt
        return msvcrt.getwch().lower() if msvcrt.kbhit() else ""
    import select
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    return sys.stdin.read(1).lower() if ready else ""


def _load_cfg(root: Path) -> dict:
    try:
        return yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _md(text: str) -> str:
    """Render a useful subset of Markdown to ANSI for the terminal."""
    import re
    bold, nb = ESC + "1m", ESC + "22m"

    def fence(m):
        return "\n".join(f"{DIM}    {ln}{RESET}" for ln in m.group(1).splitlines())

    t = re.sub(r"```[\w+-]*\n?(.*?)```", fence, text, flags=re.S)
    t = re.sub(r"(?m)^#{1,6}\s*(.+)$", lambda m: f"{bold}{IVORY}{m.group(1)}{RESET}", t)
    t = re.sub(r"\*\*(.+?)\*\*", lambda m: f"{bold}{m.group(1)}{nb}", t)
    t = re.sub(r"`([^`]+)`", lambda m: f"{ICE}{m.group(1)}{RESET}", t)
    t = re.sub(r"(?m)^(\s*)[-*]\s+", lambda m: f"{m.group(1)}• ", t)
    return t


def _clean_cmd(cmd: str) -> str:
    import re
    m = re.search(r"-Command\s+['\"](.*)['\"]\s*$", cmd, re.S)
    return " ".join((m.group(1) if m else cmd).split())


def _rule() -> None:
    """A dim horizontal rule — separates one user turn from the next."""
    width = min(shutil.get_terminal_size((80, 24)).columns, 76)
    print(f"{DIM}{'─' * width}{RESET}")


def _header_line(color: str, label: str, note: str = "") -> None:
    """A speaker header: a colored dot, the name, an optional dim note."""
    tail = f" {DIM}· {note}{RESET}" if note else ""
    print(f"  {color}●{RESET} {color}{label}{RESET}{tail}")


def _emit_body(text: str) -> None:
    """Print a reply body under its header: Markdown-rendered, indented, blanks blank."""
    for ln in _md((text or "").strip() or "(no answer)").split("\n"):
        print(("    " + ln) if ln.strip() else "")


def _render_codex_event(ev) -> None:
    """Codex's live activity indented under its header — commands, output, edits."""
    t, item = ev.get("type"), ev.get("item", {})
    it = item.get("type")
    if t == "item.completed" and it == "agent_message":
        raw = item.get("text", "").strip()
        if not raw or raw.upper().startswith(("ESCALATE", "BUILD")):
            return
        _emit_body(raw)
    elif t == "item.started" and it == "command_execution":
        print(f"    {DIM}$ {_clean_cmd(item.get('command', ''))[:96]}{RESET}")
    elif t == "item.completed" and it == "command_execution":
        out = (item.get("aggregated_output", "") or "").strip().splitlines()
        if out:
            more = f"  …+{len(out) - 1}" if len(out) > 1 else ""
            print(f"      {DIM}{out[0][:86]}{more}{RESET}")
    elif t == "item.started" and it and it not in ("agent_message", "reasoning"):
        detail = (item.get("path") or item.get("file") or item.get("title")
                  or item.get("name") or "")
        print(f"    {DIM}· {it.replace('_', ' ')} {str(detail)[:68]}{RESET}")


def _codex_do(root: Path, config: dict, instruction: str) -> str:
    """Codex executes the PM's instruction — it cannot decide anything, only do
    exactly what it's told. A spinner runs until its first step, then the real
    work (commands, edits, output) streams live beneath it."""
    from .providers import codex_stream
    prompt = ("Execute this instruction now in the workspace — read and edit files as needed, "
              "then report in 1-2 sentences what you did. You have no authority to decide, judge, "
              "or change the scope; do exactly this:\n\n" + instruction)
    _header_line(ICE, "codex")
    first, done, result = threading.Event(), threading.Event(), {}
    lock = threading.Lock()

    def on_event(ev):
        first.set()
        with lock:
            _render_codex_event(ev)

    def work():
        try:
            result["v"] = codex_stream(prompt, on_event=on_event, sandbox="workspace-write",
                                       cwd=root, timeout=int(config.get("timeout_seconds", 600)))
        except Exception as exc:
            result["e"] = exc
        done.set()

    threading.Thread(target=work, daemon=True).start()
    i, start = 0, time.monotonic()
    while not first.is_set() and not done.is_set():
        with lock:
            print(f"\r    {DIM}{_BRAILLE[i % len(_BRAILLE)]} working "
                  f"{_fmt_elapsed(time.monotonic() - start)}{RESET}   ", end="", flush=True)
        i += 1
        time.sleep(0.09)
    with lock:
        print("\r" + " " * 40 + "\r", end="", flush=True)
    done.wait()
    if "e" in result:
        print(f"    {RED}{result['e']}{RESET}")
        return ""
    return result.get("v", "")


def _steer_window(seconds: float = 1.4) -> str:
    """Brief pause between rounds: press any key to steer, otherwise the PM↔Codex
    loop keeps running on its own."""
    print(f"  {DIM}(press a key to steer, or let them keep working…){RESET}", end="", flush=True)
    start = time.monotonic()
    hit = False
    while time.monotonic() - start < seconds:
        if _key():
            hit = True
            break
        time.sleep(0.05)
    print("\r" + " " * 52 + "\r", end="", flush=True)
    if not hit:
        return ""
    try:
        return input(f"  {DIM}› you:{RESET} {WHITE}").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    finally:
        print(RESET, end="", flush=True)


def _run_goal(root: Path, config: dict, goal: str, stop_fn) -> None:
    """The core loop. Each round the PM (Claude) decides — as structured output,
    so the dispatch is reliable — one of: answer the human, instruct Codex,
    finish, or ask. Codex executes instructions and never decides; the human
    steers between rounds. A question just gets answered (no build loop)."""
    from . import providers
    history: list = [f"USER: {goal}"]
    last = "(nothing built yet)"
    budget = int(config.get("round_budget", 30))
    try:
        for n in range(1, budget + 1):
            try:
                d = _spin_call("claude", ORANGE, "PM · thinking",
                               lambda: providers.pm_decide(
                                   root, config, goal, "\n".join(history[-16:]), last))
            except Exception as exc:
                print(f"    {RED}{exc}{RESET}")
                return
            action = d.get("action", "answer")
            message = (d.get("message") or "").strip()

            _header_line(ORANGE, "claude")
            if message:
                _emit_body(message)

            if action == "answer":
                return                       # a question, answered — back to the goal prompt
            if action == "done":
                print(f"  {ORANGE}✓ done{RESET}")
                return
            if action == "ask":
                _rule()
                try:
                    ans = input(f"  {DIM}› you:{RESET} {WHITE}").strip()
                finally:
                    print(RESET, end="", flush=True)
                if not ans:
                    return
                history.append(f"human: {ans}")
                continue
            if not message:
                return
            history.append(f"PM: {message[:400]}")
            print()
            report = _codex_do(root, config, message)
            history.append(f"codex: {(report or '').strip()[:400]}")
            last = report or "(no report)"
            steer = _steer_window()
            if steer:
                history.append(f"human: {steer}")
        print(f"  {DIM}round budget reached — give another goal to continue.{RESET}")
    except KeyboardInterrupt:
        print(f"\n  {DIM}stopped{RESET}")


def _pm_session(root: Path, config: dict, stop_fn) -> int:
    """Give a goal or ask a question; watch Claude (PM) and Codex work together.
    A dim rule separates each of your turns."""
    _clear(); _header(root); _home(root, _status(root))
    while True:
        print()
        _rule()
        try:
            goal = input(f"  {DIM}›{RESET} {WHITE}").strip()
        except (EOFError, KeyboardInterrupt):
            print(RESET, end=""); return 0
        print(RESET, end="", flush=True)
        if not goal or goal.lower() in ("/quit", "/exit", "quit", "exit"):
            return 0
        print()
        _run_goal(root, config, goal, stop_fn)


def run(root: Path, checks_fn, start_fn, stop_fn) -> int:
    _enable_terminal()
    if not loading(root, checks_fn):
        print(f"\n{RED}environment check failed{RESET}")
        return 1
    inspect(root)
    if not sys.stdin.isatty():
        print("friday ready")
        return 0
    return _pm_session(root, _load_cfg(root), stop_fn)


