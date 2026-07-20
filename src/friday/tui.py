"""Dependency-free terminal UI inspired by modern coding-agent CLIs."""

import json
import os
import queue
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
    print(f"\n  {DIM}{ORANGE}Claude{DIM} directs, {ICE}Codex{DIM} builds — "
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
    if t == "worker_error":
        print(f"    {RED}⚠ codex stopped: {str(item.get('message', ''))[:120]}{RESET}")
    elif t == "item.completed" and it == "agent_message":
        raw = item.get("text", "").strip()
        if not raw:
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


def _stream_summary(buffer: list) -> str:
    """A compact, faithful digest of Codex's stream for the overseer — every
    command and file it touched (they're short) plus its recent messages, so the
    review is grounded in what actually happened, not a lossy truncation."""
    lines: list = []
    for ev in buffer:
        t, item = ev.get("type"), ev.get("item", {})
        it = item.get("type")
        if t == "worker_error":
            lines.append("!! codex stopped: " + str(item.get("message", ""))[:160])
        elif t == "worker_finished":
            txt = (item.get("text") or "").strip()
            lines.append("— codex finished the brief" + (f": {txt[:200]}" if txt else ""))
        elif t == "item.started" and it == "command_execution":
            lines.append("$ " + _clean_cmd(item.get("command", ""))[:140])
        elif t == "item.completed" and it == "command_execution":
            out = (item.get("aggregated_output", "") or "").strip().splitlines()
            if out:
                lines.append("  → " + out[-1][:140])
        elif t == "item.completed" and it == "agent_message":
            txt = (item.get("text") or "").strip()
            if txt:
                lines.append("codex: " + txt[:300])
        elif t == "item.started" and it and it not in ("agent_message", "reasoning"):
            detail = item.get("path") or item.get("file") or item.get("name") or ""
            lines.append(f"{it.replace('_', ' ')}: {detail}"[:140])
    if not lines:
        return "(nothing yet)"
    if len(lines) <= 40:
        return "\n".join(lines)
    return "\n".join(lines[:8] + ["…"] + lines[-28:])       # keep head + recent tail


def _is_milestone(ev) -> bool:
    """A concrete, observable step — the primary trigger for a review, because
    wrong-turn latency is cut by judging right after each real action, not on a
    clock. The timer is only a fallback for a silent worker."""
    t, item = ev.get("type"), ev.get("item", {})
    it = item.get("type")
    if t == "worker_error":
        return True
    if t == "item.completed" and it == "command_execution":
        return True
    if t == "item.started" and it and it not in ("agent_message", "reasoning", "command_execution"):
        return True                                          # a file write / edit
    return False


def _continuation_brief(prior_summary: str, correction: str) -> str:
    """A respawn / next brief: the overseer, which watched the stream, folds what
    was done into one instruction — a single compression, authored by the mind."""
    return ("Continue in the workspace. Here is what has already been done:\n"
            f"{prior_summary}\n\nNow do exactly this:\n{correction}")


def _prompt_human() -> str:
    try:
        return input(f"  {DIM}› you:{RESET} {WHITE}").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    finally:
        print(RESET, end="", flush=True)


def _pipeline(root: Path, config: dict, goal: str, first_brief: str, stop_fn) -> None:
    """Concurrent build. Codex (a thread) works a brief and streams every step;
    Claude (a thread) watches that stream, verifies against ground truth, and
    returns a verdict — continue / correct(soft|hard) / ask / done. The main thread
    renders live and turns a human keypress into a correction. Only one Codex is
    ever alive; a hard correction kills it and respawns with a folded-in brief."""
    from . import providers

    events: queue.Queue = queue.Queue()
    buffer: list = []
    buf_lock = threading.Lock()
    review_needed = threading.Event()
    finished = threading.Event()

    model = config.get("codex_model")
    verify = str(config.get("verify_command", "") or "")
    review_seconds = float(config.get("review_seconds", 25) or 25)
    timeout = int(config.get("timeout_seconds", 600))
    budget = int(config.get("round_budget", 30))

    worker = {"stop": None, "active": False}
    st = {"pending": None, "brief": first_brief, "start": time.monotonic()}

    def spawn(brief: str) -> None:
        stop = threading.Event()
        worker["stop"], worker["active"] = stop, True
        st["brief"], st["start"] = brief, time.monotonic()

        def run():
            final = providers.codex_run(
                brief, on_event=lambda ev: events.put(("codex", ev)),
                sandbox="workspace-write", cwd=root, model=model,
                stop=stop, timeout=timeout)
            events.put(("worker_done", final))

        threading.Thread(target=run, daemon=True).start()

    def overseer() -> None:
        reviews = 0
        while not finished.is_set():
            review_needed.wait(timeout=review_seconds)
            review_needed.clear()
            if finished.is_set():
                break
            reviews += 1
            with buf_lock:
                summary = _stream_summary(buffer)
            idle = not worker["active"]
            try:
                v = providers.claude_review(root, goal, st["brief"], summary, verify,
                                            model=model, timeout=timeout)
            except Exception as exc:                         # noqa: BLE001
                v = {"verdict": "continue", "hard": False, "note": f"(review failed: {exc})"}
            events.put(("verdict", v, idle))
            if reviews >= budget:
                events.put(("verdict",
                            {"verdict": "done", "hard": False,
                             "note": "review budget reached — stopping"}, True))
                break

    def queue_brief(brief: str, *, kill: bool) -> None:
        if worker["active"]:
            st["pending"] = brief
            if kill and worker["stop"]:
                worker["stop"].set()                         # worker_done will spawn pending
        else:
            print(); _header_line(ICE, "codex")
            spawn(brief)

    def apply_correction(note: str, *, hard: bool) -> None:
        with buf_lock:
            summary = _stream_summary(buffer)
        queue_brief(_continuation_brief(summary, note), kill=hard)

    def _erase_spin() -> None:
        print("\r" + " " * 48 + "\r", end="", flush=True)

    spawn(first_brief)
    threading.Thread(target=overseer, daemon=True).start()
    _header_line(ICE, "codex")

    spin, i = False, 0
    try:
        while not finished.is_set():
            if _key():
                if spin:
                    _erase_spin(); spin = False
                human = _prompt_human()
                if human:
                    _header_line(ORANGE, "claude", "steering")
                    apply_correction(human, hard=True)
            try:
                msg = events.get(timeout=0.12)
            except queue.Empty:
                if worker["active"]:
                    frame = _BRAILLE[i % len(_BRAILLE)]; i += 1
                    print(f"\r    {DIM}{frame} working "
                          f"{_fmt_elapsed(time.monotonic() - st['start'])}{RESET}   ",
                          end="", flush=True)
                    spin = True
                continue
            if spin:
                _erase_spin(); spin = False

            kind = msg[0]
            if kind == "codex":
                ev = msg[1]
                with buf_lock:
                    buffer.append(ev)
                _render_codex_event(ev)
                if _is_milestone(ev):
                    review_needed.set()
            elif kind == "worker_done":
                worker["active"] = False
                with buf_lock:
                    buffer.append({"type": "worker_finished", "item": {"text": msg[1] or ""}})
                if st["pending"]:
                    nb, st["pending"] = st["pending"], None
                    print(); _header_line(ICE, "codex"); spawn(nb)
                else:
                    review_needed.set()                      # overseer: done or next brief?
            elif kind == "verdict":
                v, idle = msg[1], msg[2]
                verdict = v.get("verdict", "continue")
                note = (v.get("note") or "").strip()
                hard = bool(v.get("hard"))
                if verdict == "done":
                    _header_line(ORANGE, "claude")
                    if note:
                        _emit_body(note)
                    print(f"  {ORANGE}✓ done{RESET}")
                    finished.set()
                elif verdict == "ask":
                    _header_line(ORANGE, "claude")
                    if note:
                        _emit_body(note)
                    _rule()
                    ans = _prompt_human()                    # empty = keep going, never drop the goal
                    if ans:
                        apply_correction(ans, hard=True)
                elif verdict == "correct":
                    _header_line(ORANGE, "claude")
                    if note:
                        _emit_body(note)
                    apply_correction(note or "continue toward the goal", hard=hard)
                elif not worker["active"] and not st["pending"]:
                    finished.set()                           # idle + nothing to do → goal met
    except KeyboardInterrupt:
        print(f"\n  {DIM}stopped{RESET}")
    finally:
        finished.set()
        review_needed.set()
        if worker["stop"]:
            worker["stop"].set()


def _run_goal(root: Path, config: dict, goal: str, stop_fn) -> None:
    """Route the input, then build. Claude decides — as structured output — whether
    this is a question to answer or a goal to build; a build hands the first brief
    to the concurrent pipeline. Claude is read-only here; the pipeline's overseer
    verifies, and Codex is the only hand that writes."""
    from . import providers
    history = f"USER: {goal}"
    try:
        while True:
            try:
                d = _spin_call("claude", ORANGE, "thinking",
                               lambda: providers.pm_decide(root, config, goal,
                                                           history, "(nothing built yet)"))
            except Exception as exc:                         # noqa: BLE001
                print(f"    {RED}{exc}{RESET}")
                return
            action = d.get("action", "answer")
            message = (d.get("message") or "").strip()
            _header_line(ORANGE, "claude")
            if message:
                _emit_body(message)
            if action == "answer":
                return
            if action == "done":
                print(f"  {ORANGE}✓ done{RESET}")
                return
            if action == "ask":
                _rule()
                ans = _prompt_human()
                if not ans:
                    return                                   # nothing to build yet — back to prompt
                history += f"\nhuman: {ans}"
                continue
            break                                            # instruct → message is the first brief
        print()
        _pipeline(root, config, goal, message, stop_fn)
    except KeyboardInterrupt:
        print(f"\n  {DIM}stopped{RESET}")


def _pm_session(root: Path, config: dict, stop_fn) -> int:
    """Give a goal or ask a question; watch Claude and Codex work together.
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


