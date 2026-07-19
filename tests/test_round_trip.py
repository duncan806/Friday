from friday.orchestrator import Orchestrator
from friday.bandwidth_filter import apply_filter


class RTAgents:
    """Validate-mode agents that also serve the A안 round-trip (question/answer)."""

    def claude(self, prompt):
        if "mode=predict" in prompt:
            return "예측"
        if "ANSWER MODE" in prompt:
            # answer carries intent phrasing ("위해") that the forward filter drops
            return "빈 입력이면 사용법을 보여주기 위해 도움말을 냅니다"
        return ("```yaml\nreport:\n  action_taken: 실행\n"
                "  where_stuck: 빈 입력에서 멈춤\ndeviation: false\n```")

    def codex(self, prompt):
        if "QUESTION MODE" in prompt:
            # question leaks code — must be stripped by reverse_filter and audited
            return "빈 입력이면 ```python\nprint()\n``` 처럼 되나요?", True
        return "built", True


def make_root(tmp_path, **cfg):
    for d in ["workspace/src", "workspace/surface", "task", "reports/dropped",
              "predictions", "verdicts", "dashboard", "prompts", "questions", "answers"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "task" / "task.md").write_text("CSV 질의응답 CLI\n", encoding="utf-8")
    (tmp_path / "prompts" / "claude_user.md").write_text("mode={{mode}} round={{round}}\n", encoding="utf-8")
    (tmp_path / "prompts" / "codex_builder.md").write_text("reports:\n{{reports}}\n", encoding="utf-8")
    lines = ["mode: validate", "round_budget: 1", "bandwidth_level: 1"]
    lines += [f"{k}: {v}" for k, v in cfg.items()]
    (tmp_path / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def test_round_trip_disabled_by_default(tmp_path):
    root = make_root(tmp_path)  # dialogue_turns defaults to 0
    Orchestrator(root=root, agents=RTAgents(), filter_fn=apply_filter).run_round(1)
    assert not (root / "questions" / "round_001_t0.md").exists()


def test_round_trip_writes_qa_and_strips_code(tmp_path):
    root = make_root(tmp_path, dialogue_turns=1)
    Orchestrator(root=root, agents=RTAgents(), filter_fn=apply_filter).run_round(1)

    question = (root / "questions" / "round_001_t0.md").read_text(encoding="utf-8")
    assert "print()" not in question                       # code stripped
    dropped = (root / "questions" / "round_001_t0.dropped.md").read_text(encoding="utf-8")
    assert "print()" in dropped                             # leak audited

    answer = (root / "answers" / "round_001_t0.md").read_text(encoding="utf-8")
    assert "위해" not in answer                             # intent stripped by forward filter

    report = (root / "reports" / "round_001.md").read_text(encoding="utf-8")
    assert "# ROUND-TRIP" in report
