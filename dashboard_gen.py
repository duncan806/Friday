"""muto dashboard generator—DOS-style static single-file HTML. (spec §8)

No server. JS for animation only, plus the single [STOP] control (spec §7:
the stop button is one of the four permitted human controls). Gradients,
rounded corners, and shadows are banned outright.

Stop signal is file-based: the button saves a stop.flag file (File System
Access API save dialog, download fallback) which the human places in the
muto root; the orchestrator checks for it before every round.

Mascot invariant: the Codex sprite and the Claude sprite roam disjoint
regions and never meet—a visualization of information asymmetry.
Only on cycle completion (verdict passed, status == "verdict_passed") do
they meet once at the center.
"""

from pathlib import Path

# Roaming regions (% of screen width). The two ranges never overlap—invariant.
CODEX_ROAM = (2, 42)    # left: src panel side
CLAUDE_ROAM = (58, 96)  # right: surface panel side
assert CODEX_ROAM[1] < CLAUDE_ROAM[0], "mascot roaming regions overlap"

_BLOCK = {True: "█", False: "░"}


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
<html lang="ko"><head><meta charset="utf-8"><title>muto</title>
<style>
  body {{ background:#0000AA; color:#AAAAAA; font-family:'Px437 IBM VGA8',monospace;
         margin:0; padding:16px; }}
  pre {{ margin:0; line-height:1.1; }}
  .title {{ color:#FFFF55; }}
  .alert {{ color:#FF5555; }}
  .blink {{ animation: blink 1s steps(1) infinite; }}
  @keyframes blink {{ 50% {{ opacity:0; }} }}
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
<div class="stage">{mascots}</div>
<script>
document.getElementById('stop').onclick = async () => {{
  const blob = new Blob(["stop"], {{type: "text/plain"}});
  const hint = document.getElementById('stophint');
  if (window.showSaveFilePicker) {{
    try {{
      const h = await showSaveFilePicker({{suggestedName: "stop.flag"}});
      const w = await h.createWritable(); await w.write(blob); await w.close();
    }} catch (e) {{ return; }}
  }} else {{
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = "stop.flag"; a.click();
  }}
  hint.textContent = "place stop.flag in the muto folder to halt before the next round";
}};
</script>
</body></html>"""
    out = root / "dashboard" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
