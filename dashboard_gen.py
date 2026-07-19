"""muto dashboard generator—DOS-style static single-file HTML. (spec §8)

No server. JS for animation, the single [STOP] control (spec §7), and the
file-based status poller. Gradients as decoration, rounded corners, and drop
shadows remain banned; the only gradient functions used are the CRT overlays
(scanlines, vignette), which imitate glass, not modern chrome.

CRT materiality (restraint rule: each effect should be missed when turned
off, never noticed when on):
- Real IBM VGA 8x16 bitmap font, embedded as woff2 (built by
  scripts/build_font.py from assets/vga8x16.json; see assets/LICENSE-pcface.md)
- Phosphor glow: text-shadow 0 0 4px currentColor, nothing stronger
- Scanlines: 2px-period horizontal lines at 0.06 opacity
- Curvature hint: edge vignette via radial-gradient—implied glass only
- Power-on: one-shot 0.4s horizontal-line bloom on load
- Palette: DOS 16-color values held in CSS variables; the "sunk" look comes
  from a whole-screen brightness filter, never from new colors

Screen-first boot flow: the launcher opens this page before doing anything
else, then streams BIOS-POST-style check results into dashboard/status.js
(`window.MUTO_STATUS = {...}`—a script tag is the only thing a file:// page
may poll, so the status file is JS-shaped JSON; same file-based principle as
stop.flag). The page polls it every second: boot/ready/failed phases show
the boot screen with the MUTO logo and POST lines; the cycle phase shows the
panels and auto-reloads when the round count changes. A failed check never
kills the screen—the mascots keep roaming.

Mascot invariant: the Codex sprite and the Claude sprite roam disjoint
regions and never meet—a visualization of information asymmetry.
16x16 sprites at 2x scale, 3-frame walk cycles, image-rendering: pixelated,
no antialiasing anywhere. Only on cycle completion (verdict passed,
status == "verdict_passed") do they meet once at the center.
"""

import base64
import json
from pathlib import Path

# Roaming regions (% of screen width). The two ranges never overlap—invariant.
CODEX_ROAM = (2, 42)    # left: src panel side
CLAUDE_ROAM = (58, 96)  # right: surface panel side
assert CODEX_ROAM[1] < CLAUDE_ROAM[0], "mascot roaming regions overlap"

_BLOCK = {True: "█", False: "░"}

ASSETS = Path(__file__).resolve().parent / "assets"

LOGO = r"""
███╗   ███╗ ██╗   ██╗ ████████╗  ██████╗
████╗ ████║ ██║   ██║ ╚══██╔══╝ ██╔═══██╗
██╔████╔██║ ██║   ██║    ██║    ██║   ██║
██║╚██╔╝██║ ██║   ██║    ██║    ██║   ██║
██║ ╚═╝ ██║ ╚██████╔╝    ██║    ╚██████╔╝
╚═╝     ╚═╝  ╚═════╝     ╚═╝     ╚═════╝

        NOT KNOWING IS THE ASSET.
"""

# ── mascot sprites ─────────────────────────────────────────────────────────
# 16x16 pixel maps, 'X' = lit pixel, 3 walk frames each. Rendered as
# box-shadow pixel lists on a 2x2px element (2x scale → 32px sprite).
# Single DOS color per mascot; detail comes from gaps, not extra colors.

CODEX_FRAMES = [  # yellow builder: antenna, square head, hammer arm
    """
    .......X........
    ......XXX.......
    .....XXXXX..XXX.
    ....XX.X.XX.XXX.
    ....XXXXXXX.XXX.
    .....XXXXX...X..
    .....XXXXX...X..
    ....XXXXXXXXXX..
    .....XXXXX......
    .....XXXXX......
    ....XX...XX.....
    ....XX...XX.....
    ...XX.....XX....
    ...XX.....XX....
    ...XX.....XX....
    ................
    """,
    """
    .......X........
    ......XXX.......
    .....XXXXX......
    ....XX.X.XX.....
    ....XXXXXXX.....
    .....XXXXX.XXX..
    .....XXXXX.XXX..
    ....XXXXXXXXXX..
    .....XXXXX..X...
    .....XXXXX......
    .....XX.XX......
    .....XX.XX......
    ....XX...XX.....
    ....XX...XX.....
    ....XX...XX.....
    ................
    """,
    """
    .......X........
    ......XXX.......
    .....XXXXX......
    ....XX.X.XX.....
    ....XXXXXXX.....
    .....XXXXX......
    .....XXXXX......
    ....XXXXXXXX....
    .....XXXXX.XXX..
    .....XXXXX.XXX..
    ....XX...XX.X...
    ....XX...XX.....
    ...XX.....XX....
    ...XX.....XX....
    ...XX.....XX....
    ................
    """,
]

CLAUDE_FRAMES = [  # gray wanderer: round body, eye gaps, three feet
    """
    .....XXXXXX.....
    ...XXXXXXXXXX...
    ..XXXXXXXXXXXX..
    ..XX.XXXXXX.XX..
    ..XX.XXXXXX.XX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ...XX..XX..XX...
    ...XX..XX..XX...
    ................
    ................
    ................
    """,
    """
    ................
    .....XXXXXX.....
    ...XXXXXXXXXX...
    ..XXXXXXXXXXXX..
    ..XX.XXXXXX.XX..
    ..XX.XXXXXX.XX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XX..XXXX..XX..
    ................
    ................
    ................
    """,
    """
    .....XXXXXX.....
    ...XXXXXXXXXX...
    ..XXXXXXXXXXXX..
    ..XX.XXXXXX.XX..
    ..XX.XXXXXX.XX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XXXXXXXXXXXX..
    ..XX..XX..XX....
    ..XX..XX..XX....
    ................
    ................
    ................
    """,
]

SPRITE_PX = 2  # rendered pixel size → 32px sprites


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


def _font_face() -> str:
    """Embed the real VGA 8x16 bitmap font if the built asset exists."""
    woff2 = ASSETS / "vga_8x16.woff2"
    if not woff2.is_file():
        return ""
    b64 = base64.b64encode(woff2.read_bytes()).decode()
    return ("@font-face { font-family:'MutoVGA'; "
            f"src:url(data:font/woff2;base64,{b64}) format('woff2'); }}"
            .replace("}}", "}"))


# Static page script (single braces—kept out of the f-string on purpose).
SCRIPT = """
document.getElementById('stop').onclick = async () => {
  const blob = new Blob(["stop"], {type: "text/plain"});
  const hint = document.getElementById('stophint');
  if (window.showSaveFilePicker) {
    try {
      const h = await showSaveFilePicker({suggestedName: "stop.flag"});
      const w = await h.createWritable(); await w.write(blob); await w.close();
    } catch (e) { return; }
  } else {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = "stop.flag"; a.click();
  }
  hint.textContent = "place stop.flag in the muto folder to halt before the next round";
};

function poll() {
  const old = document.getElementById('statusjs');
  if (old) old.remove();
  const s = document.createElement('script');
  s.id = 'statusjs';
  s.src = 'status.js?t=' + Date.now();
  s.onload = render;
  s.onerror = () => {};
  document.body.appendChild(s);
}

function render() {
  const st = window.MUTO_STATUS;
  if (!st) return;
  const boot = document.getElementById('boot');
  const main = document.getElementById('main');
  if (st.phase === 'cycle') {
    boot.hidden = true; main.hidden = false;
    if (st.round !== BAKED_ROUND) location.reload();
    return;
  }
  boot.hidden = false; main.hidden = true;
  const pad = n => ('CHECKING ' + n + ' ').padEnd(34, '.');
  document.getElementById('post').textContent = (st.checks || []).map(c =>
    pad(c.name) + ' [' +
    (c.state === 'ok' ? ' OK ' : c.state === 'fail' ? 'FAIL' : '....') + ']' +
    (c.hint ? '\\n  -> ' + c.hint : '')).join('\\n');
  const msg = document.getElementById('bootmsg');
  if (st.phase === 'ready') {
    msg.innerHTML = '<span class="go blink">[START CYCLE]</span> press any key in the muto console window';
  } else if (st.phase === 'failed') {
    msg.innerHTML = '<span class="alert">boot halted—fix the item above, then run muto.bat again</span>';
  } else {
    msg.textContent = '';
  }
}

setInterval(poll, 1000);
poll();
"""


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
                 status: str = "", task_present: bool = False) -> Path:
    """Write dashboard/status.js—the file the page polls.

    The launcher writes boot/ready/failed phases from muto.bat; the
    orchestrator writes the cycle phase on every round via generate().
    """
    payload = {"phase": phase, "checks": checks or [], "round": round_no,
               "status": status, "task_present": task_present}
    out = root / "dashboard" / "status.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("window.MUTO_STATUS = " + json.dumps(payload) + ";\n",
                   encoding="utf-8")
    return out


def generate(state, root: Path) -> Path:
    rounds = state.rounds
    toxic = bool(rounds) and rounds[-1].quadrant == "toxic convergence—alert"
    passed = state.status == "verdict_passed"
    alert = ('<div class="alert blink">⚠ TOXIC CONVERGENCE—ALERT ⚠</div>' if toxic else "")

    if passed:
        mascots = '<div class="mascot codex meet"></div><div class="mascot claude meet2"></div>'
    else:
        mascots = '<div class="mascot codex roam-codex"></div><div class="mascot claude roam-claude"></div>'

    codex_frames = _frame_keyframes("cframes", CODEX_FRAMES, "var(--hl)")
    claude_frames = _frame_keyframes("aframes", CLAUDE_FRAMES, "var(--fg)")

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>muto</title>
<style>
  {_font_face()}
  /* DOS 16-color palette only; the sunk look comes from the #crt filter. */
  :root {{ --bg:#0000AA; --fg:#AAAAAA; --hl:#FFFF55; --alarm:#FF5555; }}
  html {{ height:100%; }}
  body {{ background:var(--bg); color:var(--fg); min-height:100%;
         font-family:'MutoVGA','Px437 IBM VGA 8x16',monospace;
         font-size:16px; margin:0;
         text-shadow: 0 0 4px currentColor; /* phosphor—no stronger */ }}
  /* CRT glass: scanlines (2px period, barely there) + edge vignette */
  body::after {{ content:''; position:fixed; inset:0; pointer-events:none; z-index:8;
    background:repeating-linear-gradient(to bottom,
      rgba(0,0,0,0.06) 0 1px, transparent 1px 2px); }}
  /* vignette doubles as the "sunk" tint: a flat 4% black at center keeps
     the DOS palette values untouched while lowering the whole screen.
     No filter here—a filtered/transformed ancestor would capture the
     fixed-position mascots and overlays. */
  body::before {{ content:''; position:fixed; inset:0; pointer-events:none; z-index:9;
    background:radial-gradient(ellipse 130% 105% at 50% 48%,
      rgba(0,0,0,0.04) 0%, rgba(0,0,0,0.04) 64%,
      rgba(0,0,0,0.12) 88%, rgba(0,0,0,0.24) 100%); }}
  #crt {{ padding:16px; animation: poweron 0.4s ease-out 1; }}
  @keyframes poweron {{
    0%   {{ transform: scale(1, 0.004); filter: brightness(3); }}
    70%  {{ transform: scale(1, 1); filter: brightness(1.4); }}
    100% {{ transform: scale(1, 1); filter: none; }}
  }}
  pre {{ margin:0; line-height:1; }}
  .title {{ color:var(--hl); }}
  .alert {{ color:var(--alarm); }}
  .go {{ color:var(--hl); }}
  .blink {{ animation: blink 1s steps(1) infinite; }}
  @keyframes blink {{ 50% {{ opacity:0; }} }}
  #boot {{ text-align:center; padding-top:8vh; }}
  #boot .logo {{ color:var(--hl); display:block; width:max-content;
                 margin:0 auto; text-align:left; }}
  #boot #post {{ display:block; width:max-content; margin:24px auto 0;
                 text-align:left; }}
  #boot #bootmsg {{ margin-top:24px; }}
  .stage {{ position:fixed; bottom:0; left:0; right:0; height:44px; }}
  /* 16x16 sprites at 2x, 3-frame walk, hard pixels only—no antialiasing */
  .mascot {{ position:absolute; bottom:36px; width:{SPRITE_PX}px; height:{SPRITE_PX}px;
             background:transparent; image-rendering: pixelated; }}
  .codex  {{ animation-name: roamc, cframes; }}
  .claude {{ animation-name: roama, aframes; }}
  /* roaming regions—never overlap (visualization of information asymmetry) */
  .roam-codex  {{ animation: roamc 9s linear infinite alternate,
                             cframes 0.6s steps(1) infinite; }}
  .roam-claude {{ animation: roama 11s linear infinite alternate,
                             aframes 0.7s steps(1) infinite; }}
  @keyframes roamc {{ from {{ left:{CODEX_ROAM[0]}%; }} to {{ left:{CODEX_ROAM[1]}%; }} }}
  @keyframes roama {{ from {{ left:{CLAUDE_ROAM[0]}%; }} to {{ left:{CLAUDE_ROAM[1]}%; }} }}
  {codex_frames}
  {claude_frames}
  /* only when the verdict passes: a one-time meeting at the center */
  .meet  {{ left:{CODEX_ROAM[0]}%; animation: meetc 4s linear forwards,
                                              cframes 0.6s steps(1) infinite; }}
  .meet2 {{ left:{CLAUDE_ROAM[1]}%; animation: meeta 4s linear forwards,
                                               aframes 0.7s steps(1) infinite; }}
  @keyframes meetc {{ to {{ left:47%; }} }}
  @keyframes meeta {{ to {{ left:53%; }} }}
  #stop {{ background:var(--fg); color:var(--bg); border:2px solid var(--hl);
           font-family:inherit; font-size:inherit; padding:2px 10px; cursor:pointer;
           text-shadow:none; }}
  #stophint {{ color:var(--hl); }}
</style></head><body>
<div id="crt">
<div id="boot" hidden>
<pre class="logo">{LOGO}</pre>
<pre id="post"></pre>
<div id="bootmsg"></div>
</div>
<div id="main">
<pre class="title">
{_panel("", "muto—validation dashboard")}
</pre>
{alert}
<pre>
{_panel("CONVERGENCE CURVE", _ascii_curve(rounds))}
{_panel("QUADRANTS", _quadrant_rows(rounds))}
status: {state.status}
</pre>
<p><button id="stop">[ STOP ]</button> <span id="stophint"></span></p>
</div>
<div class="stage">{mascots}</div>
</div>
<script>const BAKED_ROUND = {len(rounds)};</script>
<script>{SCRIPT}</script>
</body></html>"""
    out = root / "dashboard" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    write_status(root, "cycle", round_no=len(rounds), status=state.status,
                 task_present=True)
    return out
