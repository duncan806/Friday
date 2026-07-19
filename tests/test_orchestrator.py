from muto.orchestrator import Orchestrator, parse_claude_attempt  # noqa: E402


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
    assert [r.quadrant for r in state.rounds] == ["initial noise", "in progress", "awaiting verdict"]
    assert (root / "predictions" / "round_001.md").is_file()
    assert (root / "reports" / "round_003.md").is_file()


def test_toxic_convergence_does_not_stop(tmp_path):
    _, state = run(tmp_path, [("", False, True)] * 5)
    assert state.status == "budget_exhausted"
    assert all(r.quadrant == "toxic convergence—alert" for r in state.rounds)


def test_build_failure_is_blockage(tmp_path):
    root, state = run(tmp_path, [("", True, False)] * 5)
    assert state.status == "budget_exhausted"           # blocked, so never awaiting verdict
    assert state.rounds[0].blocked and state.rounds[0].build_failed
    assert "product cannot ship" in (root / "reports" / "round_001.md").read_text()


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


def test_stop_flag_aborts_before_next_round(tmp_path):
    root = make_root(tmp_path)

    class StopAfterFirst(ScriptedAgents):
        def codex(self, prompt):
            (root / "stop.flag").write_text("stop")
            return super().codex(prompt)

    orch = Orchestrator(root=root, agents=StopAfterFirst([("멈춤", False, True)] * 5))
    state = orch.run_cycle()
    assert state.status == "aborted"
    assert len(state.rounds) == 1
    assert "stop.flag detected" in (root / "reports" / "orchestrator.log").read_text()


def test_stale_stop_flag_cleared_at_cycle_start(tmp_path):
    root = make_root(tmp_path)
    (root / "stop.flag").write_text("stale")
    orch = Orchestrator(root=root, agents=ScriptedAgents([("멈춤", False, True)] * 5))
    state = orch.run_cycle()
    assert state.status == "budget_exhausted"
    assert len(state.rounds) == 5


def test_surface_absent_substitutes_product_cannot_ship(tmp_path):
    root = make_root(tmp_path)
    import shutil
    shutil.rmtree(root / "workspace" / "surface")  # no build artifact

    calls = {"claude": 0}
    class NoSurfaceAgents(ScriptedAgents):
        def claude(self, prompt):
            calls["claude"] += 1
            return super().claude(prompt)

    orch = Orchestrator(root=root, agents=NoSurfaceAgents([("x", True, True)] * 3))
    result = orch.run_round(1)
    # Claude turn skipped entirely; report is the max-severity substitute
    assert calls["claude"] == 0
    assert not result.void and result.blocked
    report = (root / "reports" / "round_001.md").read_text()
    assert "product cannot ship" in report
    assert not (root / "predictions" / "round_001.md").exists()


def test_surface_is_file_voids_round_without_report(tmp_path):
    root = make_root(tmp_path)
    import shutil
    shutil.rmtree(root / "workspace" / "surface")
    (root / "workspace" / "surface").write_text("not a directory")

    orch = Orchestrator(root=root, agents=ScriptedAgents([("x", True, True)] * 3))
    result = orch.run_round(1)
    assert result.void and result.quadrant == "void"
    # a wrong report is worse than no report: none is written
    assert not (root / "reports" / "round_001.md").exists()
    assert "INTEGRITY_BREACH" in (root / "reports" / "orchestrator.log").read_text()


def test_claude_command_allows_exec_and_blocks_read(tmp_path, monkeypatch):
    import muto.orchestrator as om
    from muto.orchestrator import CLIAgents
    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["cwd"] = kw.get("cwd")
        class R:
            stdout = "ok"
            returncode = 0
        return R()
    monkeypatch.setattr(om.subprocess, "run", fake_run)
    (tmp_path / "workspace" / "surface").mkdir(parents=True)

    CLIAgents(tmp_path, timeout=10).claude("hello")
    cmd = captured["cmd"]
    assert "plan" not in cmd                     # execution must not be blocked
    assert cmd[cmd.index("--allowedTools") + 1] == "Bash"   # execution allowed
    disallowed = cmd[cmd.index("--disallowedTools") + 1]
    for tool in ("Edit", "Write", "Read", "Glob", "Grep"):
        assert tool in disallowed               # Read blocked = no source/.pyz unpack
    assert str(captured["cwd"]).endswith("surface")


def test_surface_pyz_executes(tmp_path):
    import subprocess as sp
    import sys
    from smoke_test import build_surface_pyz
    surface = tmp_path / "workspace" / "surface"
    surface.mkdir(parents=True)
    pyz = build_surface_pyz(surface)
    r = sp.run([sys.executable, pyz.name, "--help"], cwd=surface,
               capture_output=True, text=True)
    assert r.returncode == 0 and "usage" in r.stdout
