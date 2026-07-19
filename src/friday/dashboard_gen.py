"""friday dashboard generator—DOS-style static single-file HTML. (spec §8)

The HTML template, mascot sprite frames, and the IBM VGA 8x16 webfont are
package data (friday/data/), loaded via importlib.resources and rendered into
the workspace's dashboard/index.html. See the template for the CRT effect
rationale (phosphor, scanlines, vignette, power-on—all held at "missed when
off, unnoticed when on" intensity) and the boot/status flow.

Status channel: write_status() maintains dashboard/status.js
(`window.FRIDAY_STATUS = {...}`—a script tag is the only thing a file:// page
may poll, so the status file is JS-shaped JSON; same file-based principle
as stop.flag). The CLI writes boot/ready/failed phases; generate() writes
the cycle phase on every round.

Mascot invariant: the Codex sprite and the Claude sprite roam disjoint
regions and never meet—a visualization of information asymmetry.
16x16 sprites at 2x scale, 3-frame walk cycles, image-rendering: pixelated,
no antialiasing anywhere. Only on cycle completion (verdict passed,
status == "verdict_passed") do they meet once at the center.
"""

import base64
import html as html_lib
import json
from dataclasses import asdict
from importlib import resources
from pathlib import Path

# Roaming regions (% of screen width). The two ranges never overlap—invariant.
CODEX_ROAM = (2, 42)    # left: src panel side
CLAUDE_ROAM = (58, 96)  # right: surface panel side
assert CODEX_ROAM[1] < CLAUDE_ROAM[0], "mascot roaming regions overlap"

_BLOCK = {True: "█", False: "░"}

SPRITE_PX = 2  # rendered pixel size → 32px sprites

LOGO = r"""
███████╗ ██████╗  ██╗ ██████╗   █████╗  ██╗   ██╗
██╔════╝ ██╔══██╗ ██║ ██╔══██╗ ██╔══██╗ ╚██╗ ██╔╝
█████╗   ██████╔╝ ██║ ██║  ██║ ███████║  ╚████╔╝
██╔══╝   ██╔══██╗ ██║ ██║  ██║ ██╔══██║   ╚██╔╝
██║      ██║  ██║ ██║ ██████╔╝ ██║  ██║    ██║
╚═╝      ╚═╝  ╚═╝ ╚═╝ ╚═════╝  ╚═╝  ╚═╝    ╚═╝

        NOT KNOWING IS THE ASSET.
"""


def _data(name: str):
    return resources.files("friday").joinpath("data", name)


def _load_frames(sprite: str) -> list:
    """Load 16x16 pixel-map frames from data/sprites/<sprite>.spr
    (frames separated by '---' lines, 'X' = lit pixel)."""
    text = _data(f"sprites/{sprite}.spr").read_text(encoding="utf-8")
    return [f.strip() for f in text.split("---") if f.strip()]


CODEX_FRAMES = _load_frames("codex")
CLAUDE_FRAMES = _load_frames("claude")


def _sprite_shadow(art: str, color: str, px: int = SPRITE_PX) -> str:
    """Compile a pixel map into a box-shadow list (one shadow per pixel)."""
    rows = [r.strip() for r in art.strip().splitlines()]
    shadows = [
        f"{x * px}px {y * px}px 0 {color}"
        for y, row in enumerate(rows)
        for x, c in enumerate(row) if c == "X"
    ]
    return ", ".join(shadows)


def _frame_keyframes(name: str, frames: list, color: str) -> str:
    """3-frame walk cycle as a steps(1) box-shadow animation."""
    f = [_sprite_shadow(a, color) for a in frames]
    return (f"@keyframes {name} {{\n"
            f"    0%   {{ box-shadow: {f[0]}; }}\n"
            f"    33%  {{ box-shadow: {f[1]}; }}\n"
            f"    66%  {{ box-shadow: {f[2]}; }}\n"
            f"    100% {{ box-shadow: {f[0]}; }}\n"
            f"  }}")


def _favicon() -> str:
    """Data URI for the app/taskbar icon (Hermès-orange friday sprite).

    A Chrome/Edge --app window has no tab bar, so this favicon is what shows
    as the window's taskbar icon. Built by scripts/build_icon.py."""
    png = _data("favicon.png")
    if not png.is_file():
        return ""
    return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()


def _font_face() -> str:
    """Embed the real VGA 8x16 bitmap font (built by scripts/build_font.py)."""
    woff2 = _data("vga_8x16.woff2")
    if not woff2.is_file():
        return ""
    b64 = base64.b64encode(woff2.read_bytes()).decode()
    return ("@font-face { font-family:'FridayVGA'; "
            f"src:url(data:font/woff2;base64,{b64}) format('woff2'); }}"
            .replace("}}", "}"))


def _panel(title: str, body: str) -> str:
    """Double-line box sized to its content—every border stays aligned."""
    lines = body.splitlines() or [""]
    w = max(max(len(ln) for ln in lines) + 2, len(title) + 6, 46)
    if title:
        top = "╔══ " + title + " " + "═" * (w - len(title) - 4) + "╗"
    else:
        top = "╔" + "═" * w + "╗"
    mid = "\n".join("║ " + ln.ljust(w - 2) + " ║" for ln in lines)
    return f"{top}\n{mid}\n╚{'═' * w}╝"


def _ascii_curve(rounds) -> str:
    if not rounds:
        return "(no rounds yet)"
    bars = "".join("▒" if r.void else _BLOCK[r.blocked] for r in rounds)
    labels = "".join(str(r.round % 10) for r in rounds)
    return f"stuck {bars}\nround {labels}   █=blocked ░=clear ▒=void"


def _quadrant_rows(rounds) -> str:
    return "\n".join(
        f"R{r.round:03d} │ blocked {'Y' if r.blocked else 'N'} │ "
        f"deviation {'Y' if r.deviation else 'N'} │ {r.quadrant}"
        for r in rounds) or "(no rounds yet)"


def write_status(root: Path, phase: str, *, checks=None, round_no: int = 0,
                 status: str = "", task_present: bool = False, rounds=None,
                 message: str = "", context=None) -> Path:
    """Write dashboard/status.js—the file the page polls."""
    payload = {"phase": phase, "checks": checks or [], "round": round_no,
               "status": status, "task_present": task_present,
               "rounds": rounds or [], "message": message,
               "context": context or {}}
    canonical = root / "status.json"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    tmp = canonical.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(canonical)
    out = root / "dashboard" / "status.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("window.FRIDAY_STATUS = " + json.dumps(payload) + ";\n",
                   encoding="utf-8")
    return out


def generate(state, root: Path) -> Path:
    rounds = state.rounds
    toxic = bool(rounds) and rounds[-1].quadrant == "toxic convergence—alert"
    passed = state.status == "verdict_passed"
    predictions = sorted((root / "predictions").glob("round_*.md"))
    prediction_text = predictions[-1].read_text(encoding="utf-8") if predictions else "(none)"
    surface = root / "workspace" / "surface"
    artifact_text = ("\n".join(str(p.relative_to(surface)) for p in surface.rglob("*")
                               if p.is_file()) if surface.is_dir() else "(none)")
    alert = ('<div class="alert blink">⚠ TOXIC CONVERGENCE—ALERT ⚠</div>' if toxic else "")

    if passed:
        mascots = '<div class="mascot codex meet"></div><div class="mascot claude meet2"></div>'
    else:
        mascots = '<div class="mascot codex roam-codex"></div><div class="mascot claude roam-claude"></div>'

    tokens = {
        "@@FAVICON@@": _favicon(),
        "@@FONT_FACE@@": _font_face(),
        "@@LOGO@@": LOGO,
        "@@ALERT@@": alert,
        "@@MASCOTS@@": mascots,
        "@@TITLE_PANEL@@": _panel("", "friday—validation dashboard"),
        "@@CURVE_PANEL@@": _panel("CONVERGENCE CURVE", _ascii_curve(rounds)),
        "@@QUADRANT_PANEL@@": _panel("QUADRANTS", _quadrant_rows(rounds)),
        "@@STATUS@@": state.status,
        "@@PREDICTION@@": html_lib.escape(prediction_text),
        "@@ARTIFACT@@": html_lib.escape(artifact_text or "(empty)"),
        "@@BAKED_ROUND@@": str(len(rounds)),
        "@@SPRITE_PX@@": str(SPRITE_PX),
        "@@CODEX_MIN@@": str(CODEX_ROAM[0]),
        "@@CODEX_MAX@@": str(CODEX_ROAM[1]),
        "@@CLAUDE_MIN@@": str(CLAUDE_ROAM[0]),
        "@@CLAUDE_MAX@@": str(CLAUDE_ROAM[1]),
        "@@CODEX_KEYFRAMES@@": _frame_keyframes("cframes", CODEX_FRAMES, "var(--hl)"),
        "@@CLAUDE_KEYFRAMES@@": _frame_keyframes("aframes", CLAUDE_FRAMES, "var(--fg)"),
    }
    html = _data("dashboard.html").read_text(encoding="utf-8")
    for k, v in tokens.items():
        html = html.replace(k, v)

    out = root / "dashboard" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    write_status(root, "cycle", round_no=len(rounds), status=state.status,
                 task_present=True, rounds=[asdict(r) for r in rounds],
                 context=getattr(state, "context", {}))
    return out
