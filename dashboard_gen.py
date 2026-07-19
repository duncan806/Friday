"""muto dashboard generator—DOS-style static single-file HTML. (spec §8)

No server. JS for animation only. Gradients, rounded corners, and shadows
are banned outright.

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
    return f"막힘 {bars}\n라운드{labels}   █=막힘 ░=없음 ▒=무효"


def _quadrant_rows(rounds) -> str:
    return "\n".join(
        f"║ R{r.round:03d} │ 막힘 {'유' if r.blocked else '무'} │ "
        f"편차 {'유' if r.deviation else '무'} │ {r.quadrant:<14}║"
        for r in rounds) or "║ (아직 라운드 없음)                          ║"


def generate(state, root: Path) -> Path:
    rounds = state.rounds
    toxic = bool(rounds) and rounds[-1].quadrant == "토스틱 수렴 — 경보"
    passed = state.status == "verdict_passed"
    alert = ('<div class="alert blink">⚠ 토스틱 수렴 — 경보 ⚠</div>' if toxic else "")

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
</style></head><body>
<pre class="title">
╔══════════════════════════════════════════════╗
║  muto—validation dashboard                   ║
╚══════════════════════════════════════════════╝
</pre>
{alert}
<pre>
╔══ 수렴 곡선 ═════════════════════════════════╗
{_ascii_curve(rounds)}
╚══════════════════════════════════════════════╝
╔══ 사분면 ════════════════════════════════════╗
{_quadrant_rows(rounds)}
╚══════════════════════════════════════════════╝
status: {state.status}
</pre>
<div class="stage">{mascots}</div>
</body></html>"""
    out = root / "dashboard" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
