import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from smoke_test import run_smoke  # noqa: E402


def test_three_round_smoke(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    state = run_smoke(sandbox)

    assert state.status == "awaiting_verdict"
    assert [r.quadrant for r in state.rounds] == ["초기 노이즈", "진행 중", "판정 대기"]

    # 산출물: 예측 3, 보고 3, 대시보드
    assert len(list((sandbox / "predictions").glob("round_*.md"))) == 3
    assert len(list((sandbox / "reports").glob("round_*.md"))) == 3
    assert (sandbox / "dashboard" / "index.html").is_file()

    # R2의 의도 문장("~보기 위해")은 필터에 드롭되어 dropped/ 에 보존
    dropped = (sandbox / "reports" / "dropped" / "round_002.md").read_text()
    assert "위해" in dropped
    report2 = (sandbox / "reports" / "round_002.md").read_text()
    assert "위해" not in report2

    # 무결성 위반 없음
    log = (sandbox / "reports" / "orchestrator.log").read_text()
    assert "INTEGRITY_BREACH" not in log
