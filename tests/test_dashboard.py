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
    """불변량: 두 마스코트는 절대 만나지 않는다."""
    assert CODEX_ROAM[1] < CLAUDE_ROAM[0]


def test_generated_keyframes_respect_disjoint_regions(tmp_path):
    state = CycleState(rounds=[rr(1, True, False, "초기 노이즈")])
    html = generate(state, tmp_path).read_text()
    roamc = re.search(r"@keyframes roamc.*?from.*?left:(\d+)%.*?to.*?left:(\d+)%", html)
    roama = re.search(r"@keyframes roama.*?from.*?left:(\d+)%.*?to.*?left:(\d+)%", html)
    assert roamc and roama
    assert max(int(g) for g in roamc.groups()) < min(int(g) for g in roama.groups())


def test_toxic_alert_blinks(tmp_path):
    state = CycleState(rounds=[rr(1, False, False, "토스틱 수렴 — 경보")])
    html = generate(state, tmp_path).read_text()
    assert "blink" in html and "토스틱 수렴" in html and "#FF5555" in html


def test_meet_only_on_verdict_passed(tmp_path):
    normal = CycleState(rounds=[rr(1, True, True, "진행 중")])
    assert 'class="mascot codex roam-codex"' in generate(normal, tmp_path).read_text()

    done = CycleState(rounds=[rr(1, False, True, "판정 대기")], status="verdict_passed")
    html = generate(done, tmp_path).read_text()
    assert 'meet' in html and 'roam-codex' not in html.split("<body>")[1]


def test_dos_aesthetics(tmp_path):
    html = generate(CycleState(), tmp_path).read_text()
    assert "#0000AA" in html and "╔" in html and "monospace" in html
    for banned in ("gradient", "border-radius"):
        assert banned not in html
