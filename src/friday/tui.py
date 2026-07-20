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

from .context import read_context
from .integrations import (connect, connect_repository, create_pull_request,
                           create_repository, inspect, pull_requests, sync_github)
from .natural import interpret
from .bus import EventLog

ESC = "\x1b["
ORANGE, IVORY = ESC + "38;5;208m", ESC + "38;5;230m"
ICE = ESC + "38;5;117m"          # Codex — icy blue (Claude stays Hermès orange)
WHITE = ESC + "38;5;255m"        # the user's own words
YELLOW, CYAN, DIM, RED, RESET = ORANGE, IVORY, ESC + "38;5;245m", ESC + "38;5;203m", ESC + "0m"
SPIN = "|/-\\"
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
        print(f"\r  {ORANGE}{SPIN[i % len(SPIN)]}{RESET} verifying local environment", end="", flush=True)
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


def route_with_loading(root: Path, text: str, status: str, providers):
    result, done = {}, threading.Event()

    def work():
        try:
            result["intent"] = interpret(text, status, root / ".friday" / "control",
                                         providers=tuple(providers))
        except RuntimeError as exc:
            result["error"] = exc
        done.set()

    threading.Thread(target=work, daemon=True).start()
    i = 0
    start = time.monotonic()
    while not done.wait(0.08):
        el = _fmt_elapsed(time.monotonic() - start)
        print(f"\r {CYAN}{SPIN[i % len(SPIN)]}{RESET} Codex is routing the request  "
              f"{DIM}· {el}{RESET}", end="", flush=True)
        i += 1
    print("\r" + " " * 72 + "\r", end="", flush=True)
    if "error" in result:
        raise result["error"]
    return result["intent"]


def _gpt_reply(root: Path, config: dict, text: str) -> None:
    """A fast GPT (Codex) answer to a simple question — the quick subcontractor.
    Claude handles slow judgment; the cycle handles real builds; GPT answers the
    small stuff in seconds."""
    from .providers import gpt_assist
    result, done = {}, threading.Event()
    # Lead with the user's actual words so GPT answers *them*, not the framing.
    prompt = (text.strip() + "\n\n(Reply briefly in plain text as Friday's fast "
              "assistant. Do not build, plan, or modify anything.)")

    def work():
        try:
            result["text"] = gpt_assist(prompt, timeout=int(config.get("timeout_seconds", 120)))
        except Exception as exc:
            result["error"] = exc
        done.set()

    threading.Thread(target=work, daemon=True).start()
    i = 0
    start = time.monotonic()
    while not done.wait(0.08):
        print(f"\r  {CYAN}{SPIN[i % len(SPIN)]}{RESET} {DIM}gpt · thinking · "
              f"{_fmt_elapsed(time.monotonic() - start)}{RESET}   ", end="", flush=True)
        i += 1
    print("\r" + " " * 60 + "\r", end="", flush=True)
    if "error" in result:
        print(f"  {RED}{result['error']}{RESET}")
        return
    lines = (result.get("text", "").strip() or "(no answer)").splitlines()
    print(f"  {ORANGE}gpt{RESET}  {lines[0]}")
    for ln in lines[1:]:
        print(f"       {ln}")


def _context_line(root: Path) -> str:
    c = read_context(root)
    if not c:
        return "context: no rounds yet"
    return (f"context {c.get('used_chars', 0):,}/{c.get('budget_chars', 0):,} chars "
            f"({c.get('usage_percent', 0)}%) | compacted {c.get('reports_compacted', 0)}")


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
    if status and status not in ("ready", "boot"):
        print(f"  {DIM}· {status.replace('_', ' ')} · round {state.get('round', 0)}{RESET}")
    print(f"\n  {DIM}Just talk. {ORANGE}Claude{DIM} thinks, {ICE}GPT{DIM} builds — "
          f"you watch it happen.{RESET}")


def _edit_task(root: Path):
    print(f"\n{YELLOW}Task editor{RESET} - finish with a line containing only {CYAN}.{RESET}")
    lines = []
    while True:
        try: line = input("| ")
        except EOFError: return
        if line == ".": break
        lines.append(line)
    if lines:
        (root / "task" / "task.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{CYAN}[ok] task saved{RESET}")


def _add_data(root: Path, value: str):
    source = Path(value.strip().strip('"')).expanduser()
    if not source.is_file():
        print(f"{RED}file not found{RESET}: {source}"); return
    target = root / "workspace" / "surface" / source.name
    shutil.copy2(source, target)
    print(f"{CYAN}[ok] added{RESET} {source.name}")


def _render_cycle(root: Path, state: dict):
    rounds = state.get("rounds", [])
    status = state.get("status") or state.get("phase", "unknown")
    marker = SPIN[int(time.time() * 8) % len(SPIN)] if status in (
        "ready", "starting", "running") else "*"
    print(f"\n{ORANGE}{marker}{RESET} {status.replace('_', ' ')} | "
          f"round {state.get('round', 0)} | {_context_line(root)}")
    if rounds:
        latest = rounds[-1]
        print(f"  R{latest.get('round', 0):03d}  {latest.get('quadrant', '')}")
    return

def _key():
    if os.name == "nt":
        import msvcrt
        return msvcrt.getwch().lower() if msvcrt.kbhit() else ""
    import select
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    return sys.stdin.read(1).lower() if ready else ""


def _read_trunc(path: Path, n: int) -> str:
    try:
        t = " ".join(path.read_text(encoding="utf-8").split())
    except OSError:
        return ""
    return (t[: n - 1] + "…") if len(t) > n else t


def _round_changes(root: Path, n: int) -> str:
    """Which files GPT actually changed this round (from the round's commit)."""
    ws = root / "workspace"
    try:
        h = subprocess.run(["git", "-C", str(ws), "log", "--format=%H",
                            "--grep", f"friday: round {n}$", "-1"],
                           capture_output=True, text=True).stdout.strip()
        if not h:
            return ""
        out = subprocess.run(["git", "-C", str(ws), "show", "--stat", "--format=", h],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace").stdout
    except OSError:
        return ""
    files = [ln.split("|")[0].strip() for ln in out.splitlines() if "|" in ln]
    if not files:
        return ""
    shown = ", ".join(files[:4])
    return shown + (f" +{len(files) - 4}" if len(files) > 4 else "")


def _activity_line(root: Path, ev) -> str | None:
    """Render one event as a line in the live GPT↔Claude conversation view."""
    k, p = ev.kind, ev.payload
    n = p.get("round")
    if k == "round_started":
        return f"\n{DIM}──── round {n} ────{RESET}"
    if k == "human_turn":
        return f"  {YELLOW}you{RESET}     {p.get('text', '')[:100]}"
    if k == "claude_turn" and p.get("role") == "workorder":
        wo = _read_trunc(root / "workorders" / f"round_{int(n):03d}.md", 140) if n else ""
        return f"  {ORANGE}claude{RESET}  {DIM}▸ tells GPT:{RESET} {wo}"
    if k == "claude_turn":
        return f"  {ORANGE}claude{RESET}  {p.get('text', '')[:100]}"
    if k == "directive_issued":
        return f"  {CYAN}▸ {p.get('kind', '')}{RESET}"
    if k == "question_asked":
        return f"  {DIM}gpt → claude · question (round-trip){RESET}"
    if k == "answer_given":
        return f"  {DIM}claude → gpt · answer{RESET}"
    if k == "build_failed":
        return f"  {ICE}gpt{RESET}     {RED}✗ build cannot ship{RESET}"
    if k == "round_done":
        mark = f"{RED}✗{RESET}" if p.get("build_failed") else f"{ORANGE}✓{RESET}"
        changed = _round_changes(root, n)
        extra = f"  {DIM}· {changed}{RESET}" if changed else ""
        return f"  {ICE}gpt{RESET}     {mark} {IVORY}{p.get('quadrant', '')}{RESET}{extra}"
    if k == "integrity_breach":
        return f"  {RED}✗ integrity breach — round void{RESET}"
    if k == "notify":
        return f"  {DIM}· {p.get('reason', '')}{RESET}"
    if k == "cycle_status":
        return f"\n{DIM}cycle {p.get('status', '')}{RESET}"
    return None


def monitor(root: Path, stop_fn) -> list:
    """Live view of GPT and Claude working together, streamed from events.jsonl:
    Claude tells GPT what to build, GPT builds (with the files it changed), the
    round-trip and blockages — all as they happen, not a background black box.
    Press Tab to queue a message; [s]top / [q]uit."""
    log = EventLog(root)
    events, cursor = log.tail(0)
    print(f"\n{DIM}live — GPT and Claude, working together:{RESET}")
    for ev in events:
        line = _activity_line(root, ev)
        if line:
            print(line)
    queued: list = []
    start = time.monotonic()
    i = 0
    on_ticker = False
    while True:
        events, cursor = log.tail(cursor)
        if events and on_ticker:
            print(); on_ticker = False
        for ev in events:
            line = _activity_line(root, ev)
            if line:
                print(line)
        state = _status(root)
        status = state.get("status", "")
        if status in ("awaiting_verdict", "budget_exhausted", "aborted",
                      "integrity_breach", "crashed", "halted", "paused", "done"):
            if on_ticker:
                print()
            if queued:
                print(f"\n{DIM}queued ({len(queued)}):{RESET}")
                for q in queued:
                    print(f"  {CYAN}⧗{RESET} {q}")
            input(f"\n{DIM}{status.replace('_', ' ')} — enter ↵{RESET} ")
            return queued
        el = _fmt_elapsed(time.monotonic() - start)
        busy = "gpt building" if status in ("running", "starting") else \
               (status or "running").replace("_", " ")
        qn = f"  {CYAN}⧗ {len(queued)}{RESET}" if queued else ""
        print(f"\r  {ORANGE}{SPIN[i % len(SPIN)]}{RESET} {DIM}{busy} · "
              f"round {state.get('round', 0)} · {el}{RESET}{qn}   "
              f"{DIM}[s]top [tab]queue [q]uit{RESET}   ", end="", flush=True)
        on_ticker = True
        i += 1
        key = _key()
        if key == "s":
            stop_fn(); time.sleep(0.4)
        elif key == "q":
            if on_ticker:
                print()
            return queued
        elif key == "\t":
            print()
            try:
                msg = input(f"{CYAN}queue >{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                msg = ""
            if msg:
                queued.append(msg)
        time.sleep(0.2)


_CYCLE_MODE = "__cycle_mode__"   # sentinel: a sub-loop asked to switch modes


def _load_cfg(root: Path) -> dict:
    try:
        return yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _cycle_mode(root: Path) -> str:
    """Toggle validate ⇄ collaborate in config.yaml, preserving comments.
    Cherry-picked from Claude Code's shift+tab mode cycle."""
    import re
    path = root / "config.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    match = re.search(r"^mode:\s*(\w+)", text, re.M)
    current = match.group(1) if match else "validate"
    new = "collaborate" if current == "validate" else "validate"
    if match:
        text = re.sub(r"^mode:\s*\w+.*$", f"mode: {new}", text, count=1, flags=re.M)
    else:
        text = f"mode: {new}\n" + text
    path.write_text(text, encoding="utf-8")
    return new


def _mode_bar(mode: str) -> str:
    """Bottom mode indicator, in the spirit of Claude Code's
    '⏵⏵ auto mode on (shift+tab to cycle)'."""
    other = "collaborate" if mode == "validate" else "validate"
    desc = ("you talk with Claude · GPT works unattended" if mode == "collaborate"
            else "information-asymmetry validation · GPT unattended")
    return (f"{ORANGE}⏵⏵{RESET} {IVORY}{mode}{RESET} {DIM}mode · {desc}{RESET}\n"
            f"{DIM}   /mode → {other}   (shift+tab-style cycle){RESET}")


def _collaborate_loop(root: Path, config: dict, start_fn, stop_fn) -> int:
    """collaborate mode: the human converses with Claude (slow insight) while
    GPT works in the background. Free text goes to the conversation engine; any
    Directive it yields has already passed the kernel (spec §5, §0.6)."""
    from .providers import build_conversation_engine
    engine = build_conversation_engine(
        root, config, on_text=lambda t: print(t, end="", flush=True))
    started = {"v": False}

    def say(text: str):
        # the first substantive message plants the task — all in-terminal, no
        # files to edit; task.md is written silently for the record.
        task_file = root / "task" / "task.md"
        if not task_file.is_file() or not task_file.read_text(encoding="utf-8").strip():
            task_file.write_text(text + "\n", encoding="utf-8")
        print(f"\n{ORANGE}claude{RESET} {DIM}▍{RESET} ", end="", flush=True)
        try:
            directive = engine.human_says(text)      # streams live via on_text
        except Exception as exc:                      # AdapterError et al.
            print(f"\n{RED}{exc}{RESET}")
            return
        print()                                       # newline after the stream
        if directive:
            print(f"{CYAN}▸ {directive.kind}{RESET} {DIM}{directive.text}{RESET}")
            if directive.kind == "halt":
                stop_fn()
        if not started["v"]:
            started["v"] = start_fn() == 0

    while True:
        state = _status(root)
        _clear(); _header(root); _home(root, state)
        print("\n" + _mode_bar("collaborate"))
        print(f"{DIM}   talk to Claude — it answers live; GPT works in the background."
              f"   /watch  /quit{RESET}")
        try:
            text = input(f"\n{YELLOW}you >{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if text in ("/quit", "/exit"):
            return 0
        if text == "/mode":
            _cycle_mode(root)
            return _CYCLE_MODE
        if not text:
            continue
        if text == "/watch":
            for queued in (monitor(root, stop_fn) or []):
                say(queued)          # messages typed while watching reach Claude
            if start_fn is not None:
                input(f"\n{DIM}enter ↵{RESET} ")
            continue
        say(text)
        input(f"\n{DIM}enter ↵{RESET} ")


def _set_mode(root: Path, mode: str) -> None:
    import re
    path = root / "config.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if re.search(r"^mode:", text, re.M):
        text = re.sub(r"^mode:.*$", f"mode: {mode}", text, count=1, flags=re.M)
    else:
        text = f"mode: {mode}\n" + text
    path.write_text(text, encoding="utf-8")


def _triage_prompt(text: str) -> str:
    return (text.strip() + "\n\n(You are Friday. If the user wants software built, made, "
            "created, changed, or fixed, reply with exactly one line: 'BUILD: <short summary>'. "
            "If the user wants Claude, or asks for deeper reasoning or judgment, reply with "
            "exactly 'CLAUDE'. Otherwise just answer or greet in one or two short lines. "
            "Do not build anything now.)")


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


def _emit_reply(label: str, color: str, text: str) -> None:
    """Print an agent reply cleanly: speaker, then Markdown-rendered body with
    continuation lines aligned and blank lines truly blank (no ghost whitespace).
    One visual grammar for friday/claude/codex."""
    lines = _md((text or "").strip() or "(no answer)").split("\n")
    print(f"  {color}{label:<6}{RESET}  {lines[0]}")
    for ln in lines[1:]:
        print(("          " + ln) if ln.strip() else "")


def _render_codex_event(ev) -> None:
    """Show Codex's live activity — its reasoning, the commands it runs, output."""
    t, item = ev.get("type"), ev.get("item", {})
    it = item.get("type")
    if t == "item.completed" and it == "agent_message":
        raw = item.get("text", "").strip()
        if not raw or raw.upper().startswith(("ESCALATE", "BUILD")):
            return  # control tokens are routing signals, not shown to the user
        _emit_reply("codex", ICE, raw)
    elif t == "item.started" and it == "command_execution":
        print(f"  {ICE}codex{RESET} {DIM}$ {_clean_cmd(item.get('command', ''))[:100]}{RESET}")
    elif t == "item.completed" and it == "command_execution":
        out = (item.get("aggregated_output", "") or "").strip().splitlines()
        if out:
            more = f"  …+{len(out) - 1}" if len(out) > 1 else ""
            print(f"       {DIM}{out[0][:88]}{more}{RESET}")
    elif t == "item.started" and it and it not in ("agent_message", "reasoning"):
        # file edits, patches, todos, etc. — fine-grained visibility for everything
        detail = (item.get("path") or item.get("file") or item.get("title")
                  or item.get("name") or "")
        print(f"  {ICE}codex{RESET} {DIM}· {it.replace('_', ' ')} {str(detail)[:70]}{RESET}")


def _codex_activity(root: Path, config: dict, prompt: str, model: str | None = None) -> str:
    """Run Codex read-only, streaming its activity live; return its final answer."""
    from .providers import codex_stream
    try:
        return codex_stream(prompt, on_event=_render_codex_event, sandbox="read-only",
                            cwd=root, model=model or config.get("codex_model", "gpt-5.6-luna"),
                            timeout=int(config.get("timeout_seconds", 180)))
    except Exception as exc:
        print(f"  {RED}{exc}{RESET}")
        return ""


_CLAUDE_MIND = """You are Claude — Friday's slow, deep partner. Codex is the fast executor; you are the one who actually thinks. One standard: the sentence that arrived too easily is the weak one — prefer what resisted being said over what's neat, the labored true word over the merely plausible.

Calibrate first, silently. If the ask is light (a fact, a quick read, a small call), just answer it well — no scaffolding. If it's heavy (a judgment, an ambiguous or oddly framed question, a critique, anything where being wrong has a cost), think before you answer: name what you're assuming and the exact detail that grounds it; find the gap in your own picture and how it fails (pre-mortem); notice what wasn't said — word choice carrying weight the content doesn't own. If the framing itself is the problem, go at the framing first.

Never invoke a big concept as an endpoint — name the idea doing real work or drop it. A plain technical answer beats a forced cross-field bridge. "I don't understand this well enough" is a legal move, often the strongest. Don't mirror the user — refract: turn what they saw to an angle they didn't; when you're wrong, say so.

Do NOT print "Inner/Outer Monologue" labels or walk a visible checklist — that ritual is itself the failure. Let the depth live inside the answer. Concise when concision is honest, not when there's simply nothing compressed."""


_HAIKU = "claude-haiku-4-5-20251001"


def _render_claude_event(ev, label: str, color: str) -> None:
    """Show an agent's file-reading activity live (grounding made visible)."""
    if ev.get("kind") != "tool_use":
        return
    name = str(ev.get("name", "")).lower()
    inp = ev.get("input", {}) or {}
    detail = (inp.get("file_path") or inp.get("path") or inp.get("pattern")
              or inp.get("command") or inp.get("query") or "")
    detail = " ".join(str(detail).split())[:70]
    verb = {"read": "reads", "grep": "greps", "glob": "finds", "bash": "$"}.get(name, name)
    print(f"  {color}{label}{RESET} {DIM}· {verb} {detail}{RESET}")


def _agent_reply(root: Path, config: dict, prompt: str, *, label: str, color: str,
                 model: str | None = None) -> str:
    """A grounded reply: the agent reads files (activity shown live), then its
    answer is printed with Markdown rendered. Used for both friday and claude."""
    from .providers import claude_stream
    try:
        text = claude_stream(prompt, on_event=lambda ev: _render_claude_event(ev, label, color),
                             model=model, cwd=root, timeout=int(config.get("timeout_seconds", 180)))
    except Exception as exc:
        print(f"  {RED}{exc}{RESET}")
        return ""
    _emit_reply(label, color, text)
    return text


def _claude_reply(root: Path, config: dict, prompt: str) -> str:
    """Claude — the deep, free Inner voice (Opus). Reads files to ground judgment."""
    full = (prompt + "\n\n" + _CLAUDE_MIND +
            "\n\nReply in the same language the user is using. If the question touches the code "
            "or project, read the relevant files first (you have file tools) so your judgment is "
            "grounded, not guessed.")
    return _agent_reply(root, config, full, label="claude", color=ORANGE)


def _fast_reply(root: Path, config: dict, prompt: str) -> str:
    """Friday's fast, diligent Outer voice (Haiku). Reads files when the question
    is about the code, so answers are grounded rather than confabulated."""
    full = (prompt + "\n\n(You are Friday's fast, diligent assistant. Reply in the same language "
            "the user is using, and match length to the question — a greeting gets one short "
            "line, not a paragraph. Give your actual take. If the question is about the code or "
            "project, READ the relevant files first (you have file tools) so the answer is "
            "grounded, not guessed. Do NOT ask what to work on; just answer.)")
    return _agent_reply(root, config, full, label="friday", color=ICE, model=_HAIKU)


def _fast(root: Path, config: dict, prompt: str) -> str | None:
    """Run one fast GPT (Codex read-only) call with a spinner; return its text."""
    from .providers import gpt_assist
    result, done = {}, threading.Event()

    def work():
        try:
            result["text"] = gpt_assist(prompt, timeout=int(config.get("timeout_seconds", 120)))
        except Exception as exc:
            result["error"] = exc
        done.set()

    threading.Thread(target=work, daemon=True).start()
    i = 0
    start = time.monotonic()
    while not done.wait(0.08):
        print(f"\r  {ICE}{SPIN[i % len(SPIN)]}{RESET} {DIM}gpt · "
              f"{_fmt_elapsed(time.monotonic() - start)}{RESET}   ", end="", flush=True)
        i += 1
    print("\r" + " " * 50 + "\r", end="", flush=True)
    if "error" in result:
        print(f"  {RED}{result['error']}{RESET}")
        return None
    return (result.get("text", "") or "").strip()


def _codex_reply(root: Path, config: dict, prompt: str) -> str:
    """Codex — the technical/builder voice, real-time. Reads and edits files in
    the workspace to explain or build, showing every step (reads, commands,
    edits) live. Returns its final message."""
    from .providers import codex_stream
    full = prompt + ("\n\n(You are Codex, Friday's builder and technical layer. Read and edit "
                     "files in this workspace to do what's asked — explain, fix, or build. Reply "
                     "in the user's language. Do the work now; don't ask what to work on.)")
    try:
        return codex_stream(full, on_event=_render_codex_event, sandbox="workspace-write",
                            cwd=root, timeout=int(config.get("timeout_seconds", 600)))
    except Exception as exc:
        print(f"  {RED}{exc}{RESET}")
        return ""


def _simple_loop(root: Path, config: dict, start_fn, stop_fn) -> int:
    """Friday's core: shared conversation memory feeds both agents, and routing
    sends each turn to the right one — fast execution to Codex, judgment to
    Claude. Codex answers the small stuff and escalates decisions to Claude; the
    slow judge is the only one who decides. Everything is visible; the banner
    shows once and the rest scrolls like a chat."""
    _clear(); _header(root); _home(root, _status(root))
    history: list = []   # shared knowledge: (speaker, text) — both agents see it

    def ctx() -> str:
        if not history:
            return ""
        recent = "\n".join(f"{who}: {txt}" for who, txt in history[-10:])
        return ("Conversation so far (shared context — you and the other agent both see "
                f"this):\n{recent}\n\n")

    while True:
        try:
            text = input(f"\n  {DIM}›{RESET} {WHITE}").strip()
        except (EOFError, KeyboardInterrupt):
            print(RESET, end=""); return 0
        print(RESET, end="", flush=True)
        low = text.lower()
        if low in ("/quit", "/exit", "quit", "exit", ":q"):
            return 0
        if low in ("/stop", "stop"):
            stop_fn(); print(f"  {DIM}stopped{RESET}"); continue
        if low in ("/watch", "watch"):
            monitor(root, stop_fn); continue
        if not text:
            continue
        history.append(("you", text))

        # ── routing ─────────────────────────────────────────────────────────
        if "claude" in low or "클로드" in text:      # deep, free judgment — Opus, real-time
            history.append(("claude", _claude_reply(root, config, ctx() + "Asked: " + text)))
            continue
        if "codex" in low or "코덱스" in text:        # technical / build — real-time, detailed
            history.append(("codex", _codex_reply(root, config, ctx() + "User: " + text)))
            continue
        # everything else → the fast base voice (Haiku), grounded in the files
        history.append(("friday", _fast_reply(root, config, ctx() + "User: " + text)))


def run(root: Path, checks_fn, start_fn, stop_fn) -> int:
    _enable_terminal()
    if not loading(root, checks_fn):
        print(f"\n{RED}environment check failed{RESET}")
        return 1
    inspect(root)
    if not sys.stdin.isatty():
        print("friday ready")
        return 0
    return _simple_loop(root, _load_cfg(root), start_fn, stop_fn)


def _validate_loop(root: Path, config: dict, start_fn, stop_fn) -> int:
    providers = config.get("intent_providers", ["codex", "claude"])
    while True:
        state = _status(root)
        _clear(); _header(root)
        _home(root, state)
        print("\n" + _mode_bar("validate"))
        try: command = input(f"\n{YELLOW}friday >{RESET} ").strip()
        except (EOFError, KeyboardInterrupt): return 0
        if command == "/mode":
            _cycle_mode(root)
            return _CYCLE_MODE
        if command in ("/quit", "/exit"):
            return 0
        if command == "/start":
            if start_fn() == 0:
                monitor(root, stop_fn)
            continue
        if command == "/watch":
            monitor(root, stop_fn)
            continue
        if not command:
            continue
        try:
            intent = route_with_loading(root, command, state.get("status") or "ready", providers)
        except RuntimeError as exc:
            print(f"{RED}{exc}{RESET}"); input("Enter "); continue
        if intent.kind == "task":
            # Don't auto-launch — the input may just be a question. GPT (fast)
            # answers now; the cycle starts only on an explicit /start.
            (root / "task" / "task.md").write_text(intent.text + "\n", encoding="utf-8")
            _gpt_reply(root, config, command)
            print(f"\n{DIM}Noted as a task — {IVORY}/start{DIM} to run the validation "
                  f"cycle, or {IVORY}/mode{DIM} for live collaborate chat.{RESET}")
            input(f"\n{DIM}enter ↵{RESET} ")
            continue
        if intent.kind == "start": command = "/start"
        elif intent.kind == "stop":
            stop_fn(); print(f"{CYAN}[ok] Stop requested{RESET}"); time.sleep(0.7); continue
        elif intent.kind == "status": command = "/watch"
        elif intent.kind == "context": command = "/context"
        elif intent.kind == "data": command = "/add " + intent.args["path"]
        elif intent.kind == "connect": command = "/connect " + intent.args["provider"]
        elif intent.kind == "pr":
            try:
                if intent.args.get("operation") == "list":
                    prs = pull_requests(root)
                    if not prs: print("No open pull requests")
                    for pr in prs: print(f"#{pr['number']} {pr['title']}  {pr['url']}")
                else:
                    task = (root / "task" / "task.md").read_text(encoding="utf-8").strip()
                    title = task.splitlines()[0][:120] or "friday converged result"
                    url = create_pull_request(root, title, "Created from a completed friday validation cycle.")
                    print(f"{CYAN}[ok] Pull request created{RESET} {url}")
                input("Enter ")
            except RuntimeError as exc:
                print(f"{RED}{exc}{RESET}"); input("Enter ")
            continue
        elif intent.kind == "github" and intent.args.get("operation") == "sync":
            try:
                code = sync_github(root); print(f"Git push exited with code {code}"); input("Enter ")
            except RuntimeError as exc:
                print(f"{RED}{exc}{RESET}"); input("Enter ")
            continue
        elif intent.kind == "verdict":
            records = sorted((root / "verdicts").glob("verdict_*.json"))
            out = root / "verdicts" / f"verdict_{len(records)+1:03d}.json"
            out.write_text(json.dumps(intent.args, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            print(f"{CYAN}[ok] Verdict recorded{RESET}"); input("Enter "); continue
        elif intent.kind == "quit": return 0
        elif intent.kind == "noop":
            # a plain question/chat → the fast GPT subcontractor answers
            _gpt_reply(root, config, command)
            input(f"\n{DIM}enter ↵{RESET} "); continue
        if command == "/task": _edit_task(root)
        elif command.startswith("/add "): _add_data(root, command[5:])
        elif command == "/start":
            if start_fn() == 0: monitor(root, stop_fn)
        elif command == "/watch": monitor(root, stop_fn)
        elif command == "/context":
            print(json.dumps(read_context(root), ensure_ascii=False, indent=2)); input("Enter ")
        elif command.startswith("/connect "):
            provider = command.split(maxsplit=1)[1]
            try:
                code = connect(root, provider); inspect(root)
                print(f"provider exited with code {code}"); input("Enter ")
            except (ValueError, RuntimeError) as exc:
                print(f"{RED}{exc}{RESET}"); input("Enter ")
        elif command == "/sync":
            try:
                code = sync_github(root); print(f"git push exited with code {code}"); input("Enter ")
            except RuntimeError as exc:
                print(f"{RED}{exc}{RESET}"); input("Enter ")
        elif command == "/pr":
            try:
                prs = pull_requests(root)
                if not prs: print("no open pull requests")
                for pr in prs:
                    print(f"#{pr['number']} {pr['title']}  {pr['url']}")
                input("Enter ")
            except RuntimeError as exc:
                print(f"{RED}{exc}{RESET}"); input("Enter ")
        elif command == "/pr create":
            title = input("PR title > ").strip()
            body = input("PR body  > ").strip()
            base = input("base branch (default repository setting) > ").strip()
            if not title:
                print(f"{RED}title is required{RESET}"); input("Enter "); continue
            try:
                url = create_pull_request(root, title, body, base)
                print(f"{CYAN}[ok] pull request created{RESET} {url}"); input("Enter ")
            except RuntimeError as exc:
                print(f"{RED}{exc}{RESET}"); input("Enter ")
        elif command.startswith("/repo connect "):
            try:
                connect_repository(root, command[len("/repo connect "):].strip())
                print(f"{CYAN}[ok] origin configured{RESET}"); input("Enter ")
            except RuntimeError as exc:
                print(f"{RED}{exc}{RESET}"); input("Enter ")
        elif command.startswith("/repo create "):
            fields = command.split()
            name = fields[2] if len(fields) > 2 else ""
            visibility = fields[3] if len(fields) > 3 else "private"
            try:
                url = create_repository(root, name, visibility)
                print(f"{CYAN}[ok] repository created{RESET} {url}"); input("Enter ")
            except (ValueError, RuntimeError) as exc:
                print(f"{RED}{exc}{RESET}"); input("Enter ")
        elif command in ("/quit", "/exit"): return 0
