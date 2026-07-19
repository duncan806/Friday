import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchestrator import Orchestrator, parse_claude_attempt  # noqa: E402


class ScriptedAgents:
    """Mock agents that answer from a per-round script: [(stuck_text, deviation, build_ok)]"""

    def __init__(self, script):
        self.script = script
        self.round = 0

    def claude(self, prompt):
        if "mode=predict" in prompt or "예측" in prompt:
            return f"평범한 구현자 예측 (라운드 {self.round + 1})"
        self.round += 1
        stuck, deviation, _ = self.script[self.round - 1]
        return (f"```yaml\nreport:\n  action_taken: 도구 실행\n"
                f"  where_stuck: {stuck!r}\ndeviation: {str(deviation).lower()}\n```")

    def codex(self, prompt):
        return "built", self.script[self.round - 1][2]


def make_root(tmp_path):
    for d in ["workspace/src", "workspace/surface", "task", "reports/dropped",
              "predictions", "verdicts", "dashboard", "prompts"]:
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "task" / "task.md").write_text("CSV 질문 응답 CLI를 사용해 보라.\n")
    (tmp_path / "prompts" / "claude_user.md").write_text("mode={{mode}} round={{round}}\n")
    (tmp_path / "prompts" / "codex_builder.md").write_text("reports:\n{{reports}}\n")
    (tmp_path / "config.yaml").write_text("bandwidth_level: 1\nround_budget: 5\n")
    return tmp_path


def run(tmp_path, script):
    root = make_root(tmp_path)
    orch = Orchestrator(root=root, agents=ScriptedAgents(script))
    return root, orch.run_cycle()


def test_awaiting_verdict_stops_cycle(tmp_path):
    root, state = run(tmp_path, [
        ("import 에러로 실행 불가", False, True),   # initial noise
        ("질문에 오답을 냈다", True, True),          # in progress
        ("", True, True),                            # awaiting verdict -> halt
        ("도달하면 안 됨", False, True),
    ])
    assert state.status == "awaiting_verdict"
    assert [r.quadrant for r in state.rounds] == ["초기 노이즈", "진행 중", "판정 대기"]
    assert (root / "predictions" / "round_001.md").is_file()
    assert (root / "reports" / "round_003.md").is_file()


def test_toxic_convergence_does_not_stop(tmp_path):
    _, state = run(tmp_path, [("", False, True)] * 5)
    assert state.status == "budget_exhausted"
    assert all(r.quadrant == "토스틱 수렴 — 경보" for r in state.rounds)


def test_build_failure_is_blockage(tmp_path):
    root, state = run(tmp_path, [("", True, False)] * 5)
    assert state.status == "budget_exhausted"           # blocked, so never awaiting verdict
    assert state.rounds[0].blocked and state.rounds[0].build_failed
    assert "제품 출시 불가" in (root / "reports" / "round_001.md").read_text()


def test_integrity_breach_voids_round(tmp_path):
    import os
    root = make_root(tmp_path)
    os.symlink(root / "workspace" / "src", root / "workspace" / "surface" / "leak")
    orch = Orchestrator(root=root, agents=ScriptedAgents([("", True, True)] * 5))
    state = orch.run_cycle()
    assert all(r.void for r in state.rounds)
    assert "INTEGRITY_BREACH" in (root / "reports" / "orchestrator.log").read_text()
    assert state.status == "budget_exhausted"


def test_filter_fn_wiring_writes_dropped(tmp_path):
    root = make_root(tmp_path)
    def fake_filter(rep, level):
        return {k: v for k, v in rep.items() if k != "where_stuck"} | \
               {"where_stuck": rep["where_stuck"]}, ["의도 문장 드롭됨"]
    orch = Orchestrator(root=root, agents=ScriptedAgents([("멈춤", False, True)] * 5),
                        filter_fn=fake_filter)
    orch.run_round(1)
    assert (root / "reports" / "dropped" / "round_001.md").read_text().startswith("의도")


def test_parse_fallback_treats_garbage_as_stuck():
    rep = parse_claude_attempt("완전 자유 서술 텍스트")
    assert rep["where_stuck"] == "완전 자유 서술 텍스트"
    assert rep["deviation"] is False
