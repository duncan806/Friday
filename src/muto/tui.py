"""Dependency-free terminal UI inspired by modern coding-agent CLIs."""

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import yaml

from .context import read_context
from .integrations import (connect, connect_repository, create_pull_request,
                           create_repository, inspect, pull_requests, sync_github)
from .natural import interpret

ESC = "\x1b["
YELLOW, CYAN, DIM, RED, RESET = ESC + "93m", ESC + "96m", ESC + "2m", ESC + "91m", ESC + "0m"
SPIN = "|/-\\"


def _clear():
    print(ESC + "2J" + ESC + "H", end="", flush=True)


def _status(root: Path) -> dict:
    try:
        return json.loads((root / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "boot", "status": "unknown", "round": 0}


def _header(root: Path):
    width = shutil.get_terminal_size((90, 24)).columns
    print(f"{YELLOW} __  __ _   _ _____ ___ {RESET}")
    print(f"{YELLOW}|  \\/  | | | |_   _/ _ \\{RESET}   {DIM}not knowing is the asset{RESET}")
    print(f"{YELLOW}|_|  |_|\\___/  |_| \\___/{RESET}")
    print(DIM + "-" * min(width, 100) + RESET)
    print(f"{DIM}workspace:{RESET} {root}")


def loading(root: Path, checks_fn) -> bool:
    checks, result, done = [], {"ok": False}, threading.Event()

    def update(items):
        checks[:] = list(items)

    def work():
        _, result["ok"] = checks_fn(root, on_update=update)
        done.set()

    threading.Thread(target=work, daemon=True).start()
    i = 0
    while not done.wait(0.08):
        _clear(); _header(root)
        print(f"\n {CYAN}{SPIN[i % len(SPIN)]}{RESET} loading environment and credentials\n")
        for check in checks:
            icon = f"{CYAN}[ok]{RESET}" if check["state"] == "ok" else f"{RED}[!!]{RESET}"
            print(f"   {icon} {check['name'].lower()}")
        i += 1
    _clear(); _header(root)
    for check in checks:
        icon = f"{CYAN}[ok]{RESET}" if check["state"] == "ok" else f"{RED}[!!]{RESET}"
        print(f"   {icon} {check['name'].lower()}")
        if check.get("hint"): print(f"     {DIM}{check['hint']}{RESET}")
    return result["ok"]


def route_with_loading(root: Path, text: str, status: str, providers):
    result, done = {}, threading.Event()

    def work():
        try:
            result["intent"] = interpret(text, status, root / ".muto" / "control",
                                         providers=tuple(providers))
        except RuntimeError as exc:
            result["error"] = exc
        done.set()

    threading.Thread(target=work, daemon=True).start()
    i = 0
    while not done.wait(0.08):
        print(f"\r {CYAN}{SPIN[i % len(SPIN)]}{RESET} Codex is routing the request", end="", flush=True)
        i += 1
    print("\r" + " " * 60 + "\r", end="", flush=True)
    if "error" in result:
        raise result["error"]
    return result["intent"]


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
        return "integrations: not checked"
    parts = []
    for name in ("github", "claude", "codex"):
        item = data.get(name, {})
        mark = "+" if item.get("authenticated") else "!" if item.get("installed") else "x"
        parts.append(f"{mark} {name}")
    return "  ".join(parts)


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
    _clear(); _header(root)
    rounds = state.get("rounds", [])
    status = state.get("status") or state.get("phase", "unknown")
    curve = "".join("x" if r.get("void") else "#" if r.get("blocked") else "." for r in rounds)
    print(f"\n+-- CYCLE -----------------------------------------------------------+")
    print(f"| {CYAN}{SPIN[int(time.time()*8) % len(SPIN)]}{RESET} {status.replace('_', ' '):<62}|")
    print(f"| round {state.get('round', 0):<4}  {_context_line(root):<54}|")
    print(f"+-- CONVERGENCE -----------------------------------------------------+")
    print(f"| {curve[-64:]:<65}|")
    latest = rounds[-1] if rounds else {}
    blocked, deviation = latest.get("blocked"), latest.get("deviation")
    cells = {
        "noise": "<" if blocked and not deviation else " ",
        "progress": "<" if blocked and deviation else " ",
        "toxic": "<" if blocked is False and deviation is False else " ",
        "verdict": "<" if blocked is False and deviation else " ",
    }
    print(f"+-- QUADRANT ----------------------+-- ISOLATED ROLES ----------------+")
    print(f"| blocked / no deviation {cells['noise']}         | CODEX  [builder]  src/        |")
    print(f"| blocked / deviation    {cells['progress']}         |          x no direct channel x   |")
    print(f"| clear   / no deviation {cells['toxic']}         | CLAUDE [user]     surface/    |")
    print(f"| clear   / deviation    {cells['verdict']}         | reports/ is the only bridge   |")
    print(f"+-- RECENT ROUNDS ---------------------------------------------------+")
    for item in rounds[-8:]:
        mark = "x" if item.get("void") else "*"
        row = f" {mark} R{item.get('round', 0):03d}  {item.get('quadrant', '')}"
        print(f"| {row:<65}|")
    print(f"+-------------------------------------------------------------------+")
    print(f"\n{DIM}[s] stop   [c] context   [q] detach{RESET}")


def _key():
    if os.name == "nt":
        import msvcrt
        return msvcrt.getwch().lower() if msvcrt.kbhit() else ""
    import select
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    return sys.stdin.read(1).lower() if ready else ""


def monitor(root: Path, stop_fn):
    while True:
        state = _status(root); _render_cycle(root, state)
        status = state.get("status", "")
        if status in ("awaiting_verdict", "budget_exhausted", "aborted", "integrity_breach", "crashed"):
            input("\npress Enter to return "); return
        key = _key()
        if key == "s": stop_fn(); time.sleep(0.5)
        elif key == "c":
            print("\n" + json.dumps(read_context(root), ensure_ascii=False, indent=2)); input("Enter ")
        elif key == "q": return
        time.sleep(0.25)


def run(root: Path, checks_fn, start_fn, stop_fn) -> int:
    if not loading(root, checks_fn):
        print(f"\n{RED}environment check failed{RESET}")
        return 1
    inspect(root)
    try:
        config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        config = {}
    providers = config.get("intent_providers", ["codex", "claude"])
    if not sys.stdin.isatty():
        print("muto ready")
        return 0
    while True:
        state = _status(root)
        _clear(); _header(root)
        print(f"\n{_context_line(root)}")
        print(_integration_line(root))
        print(f"status: {state.get('status') or 'ready'} | round: {state.get('round', 0)}")
        print(f"\n{DIM}Describe an outcome to start a cycle. Ask naturally to add data,"
              f" stop, inspect status, connect providers, or create a PR.{RESET}")
        try: command = input(f"\n{YELLOW}muto >{RESET} ").strip()
        except (EOFError, KeyboardInterrupt): return 0
        try:
            intent = route_with_loading(root, command, state.get("status") or "ready", providers)
        except RuntimeError as exc:
            print(f"{RED}{exc}{RESET}"); input("Enter "); continue
        if intent.kind == "task":
            (root / "task" / "task.md").write_text(intent.text + "\n", encoding="utf-8")
            print(f"{CYAN}[ok] Task planted. Starting the unattended cycle.{RESET}")
            time.sleep(0.5)
            if start_fn() == 0: monitor(root, stop_fn)
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
                    title = task.splitlines()[0][:120] or "muto converged result"
                    url = create_pull_request(root, title, "Created from a completed muto validation cycle.")
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
        elif intent.kind == "noop": continue
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
