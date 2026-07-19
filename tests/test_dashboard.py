import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dashboard_gen  # noqa: E402
from dashboard_gen import CLAUDE_ROAM, CODEX_ROAM, generate  # noqa: E402
from orchestrator import CycleState, RoundResult  # noqa: E402


def rr(n, blocked, deviation, quadrant, void=False):
    return RoundResult(round=n, blocked=blocked, deviation=deviation,
                       quadrant=quadrant, void=void)


def test_roam_regions_never_overlap():
    """Invariant: the two mascots never meet."""
    assert CODEX_ROAM[1] < CLAUDE_ROAM[0]


def test_generated_keyframes_respect_disjoint_regions(tmp_path):
    state = CycleState(rounds=[rr(1, True, False, "initial noise")])
    html = generate(state, tmp_path).read_text()
    roamc = re.search(r"@keyframes roamc.*?from.*?left:(\d+)%.*?to.*?left:(\d+)%", html)
    roama = re.search(r"@keyframes roama.*?from.*?left:(\d+)%.*?to.*?left:(\d+)%", html)
    assert roamc and roama
    assert max(int(g) for g in roamc.groups()) < min(int(g) for g in roama.groups())


def test_toxic_alert_blinks(tmp_path):
    state = CycleState(rounds=[rr(1, False, False, "toxic convergence—alert")])
    html = generate(state, tmp_path).read_text()
    assert "blink" in html and "TOXIC CONVERGENCE" in html and "#FF5555" in html


def test_meet_only_on_verdict_passed(tmp_path):
    normal = CycleState(rounds=[rr(1, True, True, "in progress")])
    assert 'class="mascot codex roam-codex"' in generate(normal, tmp_path).read_text()

    done = CycleState(rounds=[rr(1, False, True, "awaiting verdict")], status="verdict_passed")
    html = generate(done, tmp_path).read_text()
    assert 'meet' in html and 'roam-codex' not in html.split("<body>")[1]


def test_dos_aesthetics(tmp_path):
    html = generate(CycleState(), tmp_path).read_text()
    assert "#0000AA" in html and "╔" in html and "monospace" in html
    for banned in ("gradient", "border-radius"):
        assert banned not in html


def test_stop_button_present_with_flag_wiring(tmp_path):
    html = generate(CycleState(), tmp_path).read_text()
    assert 'id="stop"' in html and "[ STOP ]" in html
    assert "stop.flag" in html and "showSaveFilePicker" in html


def test_boot_screen_and_poller(tmp_path):
    html = generate(CycleState(), tmp_path).read_text()
    assert 'id="boot"' in html and "NOT KNOWING IS THE ASSET." in html
    assert "status.js?t=" in html and "setInterval(poll, 1000)" in html
    assert "[START CYCLE]" in html and "BAKED_ROUND = 0" in html


def test_generate_writes_cycle_status(tmp_path):
    generate(CycleState(rounds=[rr(1, True, False, "initial noise")]), tmp_path)
    status = (tmp_path / "dashboard" / "status.js").read_text()
    assert status.startswith("window.MUTO_STATUS = ")
    assert '"phase": "cycle"' in status and '"round": 1' in status


def test_write_status_boot_phase(tmp_path):
    dashboard_gen.write_status(tmp_path, "ready",
                               checks=[{"name": "CLAUDE CLI", "state": "ok", "hint": ""}],
                               task_present=True)
    status = (tmp_path / "dashboard" / "status.js").read_text()
    assert '"phase": "ready"' in status and '"CLAUDE CLI"' in status
