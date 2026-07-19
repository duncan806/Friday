"""muto dashboard generator—DOS-style static single-file HTML. (spec §8)

No server. JS for animation, the single [STOP] control (spec §7), and the
file-based status poller. Gradients, rounded corners, and shadows are banned
outright.

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
Only on cycle completion (verdict passed, status == "verdict_passed") do
they meet once at the center.
"""

import json
from pathlib import Path

# Roaming regions (% of screen width). The two ranges never overlap—invariant.
CODEX_ROAM = (2, 42)    # left: src panel side
CLAUDE_ROAM = (58, 96)  # right: surface panel side
assert CODEX_ROAM[1] < CLAUDE_ROAM[0], "mascot roaming regions overlap"

_BLOCK = {True: "█", False: "░"}

LOGO = r"""
███╗   ███╗ ██╗   ██╗ ████████╗  ██████╗
████╗ ████║ ██║   ██║ ╚══██╔══╝ ██╔═══██╗
██╔████╔██║ ██║   ██║    ██║    ██║   ██║
██║╚██╔╝██║ ██║   ██║    ██║    ██║   ██║
██║ ╚═╝ ██║ ╚██████╔╝    ██║    ╚██████╔╝
╚═╝     ╚═╝  ╚═════╝     ╚═╝     ╚═════╝

        NOT KNOWING IS THE ASSET.
"""

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


def _ascii_curve(rounds) -> str:
    if not rounds:
        return "(no rounds yet)"
    bars = "".join("▒" if r.void else _BLOCK[r.blocked] for r in rounds)
    labels = "".join(str(r.round % 10) for r in rounds)
    return f"stuck {bars}\nround {labels}   █=blocked ░=clear ▒=void"


def _quadrant_rows(rounds) -> str:
    return "\n".join(
        f"║ R{r.round:03d} │ blocked {'Y' if r.blocked else 'N'} │ "
        f"deviation {'Y' if r.deviation else 'N'} │ {r.quadrant:<24}║"
        for r in rounds) or "║ (no rounds yet)                                              ║"


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

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>muto</title>
<style>
  body {{ background:#0000AA; color:#AAAAAA; font-family:'Px437 IBM VGA8',monospace;
         margin:0; padding:16px; }}
  pre {{ margin:0; line-height:1.1; }}
  .title {{ color:#FFFF55; }}
  .alert {{ color:#FF5555; }}
  .go {{ color:#FFFF55; }}
  .blink {{ animation: blink 1s steps(1) infinite; }}
  @keyframes blink {{ 50% {{ opacity:0; }} }}
  #boot {{ text-align:center; padding-top:8vh; }}
  #boot .logo {{ color:#FFFF55; display:inline-block; text-align:left; }}
  #boot #post {{ display:inline-block; text-align:left; margin-top:24px; }}
  #boot #bootmsg {{ margin-top:24px; }}
  .stage {{ position:fixed; bottom:0; left:0; right:0; height:40px; }}
  .mascot {{ position:absolute; bottom:4px; width:16px; height:16px;
             image-rendering: pixelated; }}
  .codex  {{ background:#FFFF55; box-shadow: 4px -16px 0 #FFFF55; }}
  .claude {{ background:#AAAAAA; box-shadow: -4px -16px 0 #AAAAAA; }}
  /* roaming regions—never overlap (visualization of information asymmetry) */
  .roam-codex  {{ animation: roamc 9s linear infinite alternate; }}
  .roam-claude {{ animation: roama 11s linear infinite alternate; }}
  @keyframes roamc {{ from {{ left:{CODEX_ROAM[0]}%; }} to {{ left:{CODEX_ROAM[1]}%; }} }}
  @keyframes roama {{ from {{ left:{CLAUDE_ROAM[0]}%; }} to {{ left:{CLAUDE_ROAM[1]}%; }} }}
  /* only when the verdict passes: a one-time meeting at the center */
  .meet  {{ left:{CODEX_ROAM[0]}%; animation: meetc 4s linear forwards; }}
  .meet2 {{ left:{CLAUDE_ROAM[1]}%; animation: meeta 4s linear forwards; }}
  @keyframes meetc {{ to {{ left:47%; }} }}
  @keyframes meeta {{ to {{ left:53%; }} }}
  #stop {{ background:#AAAAAA; color:#0000AA; border:2px solid #FFFF55;
           font-family:inherit; font-size:inherit; padding:2px 10px; cursor:pointer; }}
  #stophint {{ color:#FFFF55; }}
</style></head><body>
<div id="boot" hidden>
<pre class="logo">{LOGO}</pre>
<pre id="post"></pre>
<div id="bootmsg"></div>
</div>
<div id="main">
<pre class="title">
╔══════════════════════════════════════════════╗
║  muto—validation dashboard                   ║
╚══════════════════════════════════════════════╝
</pre>
{alert}
<pre>
╔══ CONVERGENCE CURVE ═════════════════════════╗
{_ascii_curve(rounds)}
╚══════════════════════════════════════════════╝
╔══ QUADRANTS ═════════════════════════════════╗
{_quadrant_rows(rounds)}
╚══════════════════════════════════════════════╝
status: {state.status}
</pre>
<p><button id="stop">[ STOP ]</button> <span id="stophint"></span></p>
</div>
<div class="stage">{mascots}</div>
<script>const BAKED_ROUND = {len(rounds)};</script>
<script>{SCRIPT}</script>
</body></html>"""
    out = root / "dashboard" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    write_status(root, "cycle", round_no=len(rounds), status=state.status,
                 task_present=True)
    return out
