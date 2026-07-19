from smoke_test import run_smoke  # noqa: E402


def test_three_round_smoke(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    state = run_smoke(sandbox)

    assert state.status == "awaiting_verdict"
    assert [r.quadrant for r in state.rounds] == ["initial noise", "in progress", "awaiting verdict"]

    # artifacts: 3 predictions, 3 reports, dashboard
    assert len(list((sandbox / "predictions").glob("round_*.md"))) == 3
    assert len(list((sandbox / "reports").glob("round_*.md"))) == 3
    assert (sandbox / "dashboard" / "index.html").is_file()

    # R2's intent sentence ("~보기 위해") is dropped by the filter, preserved in dropped/
    dropped = (sandbox / "reports" / "dropped" / "round_002.md").read_text()
    assert "위해" in dropped
    report2 = (sandbox / "reports" / "round_002.md").read_text()
    assert "위해" not in report2

    # no integrity breach
    log = (sandbox / "reports" / "orchestrator.log").read_text()
    assert "INTEGRITY_BREACH" not in log
