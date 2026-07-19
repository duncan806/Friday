from friday.orchestrator import Orchestrator
from friday.route import Router
from friday.domain import Directive
from friday.bus import EventLog


class CollabAgents:
    """collaborate execution: Claude drafts the work order, Codex builds it."""

    def __init__(self, builds):
        self.builds = builds
        self.i = 0
        self.codex_prompts = []
        self.claude_prompts = []

    def claude(self, prompt):  # the work-order drafter (Tony→JARVIS)
        self.claude_prompts.append(prompt)
        return "Create surface/wc.py and src/wc.py implementing the goal; write the files now."

    def codex(self, prompt):
        self.codex_prompts.append(prompt)
        ok = self.builds[self.i] if self.i < len(self.builds) else True
        self.i += 1
        return "built", ok


def make_collab_root(tmp_path, budget=3, **cfg):
    for d in ["workspace/src", "workspace/surface", "task", "reports/dropped",
              "predictions", "verdicts", "dashboard", "prompts", "directives"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "task" / "task.md").write_text("데모 과제\n", encoding="utf-8")
    (tmp_path / "prompts" / "codex_builder.md").write_text(
        "reports:\n{{reports}}\nround {{round}}\n", encoding="utf-8")
    lines = ["mode: collaborate", f"round_budget: {budget}", "bandwidth_level: 1"]
    lines += [f"{k}: {v}" for k, v in cfg.items()]
    (tmp_path / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def test_collaborate_converges_on_clean_build(tmp_path):
    # A clean build with no pending direction converges (status "done"), instead
    # of burning the full round budget re-building what already works.
    root = make_collab_root(tmp_path, budget=3)
    state = Orchestrator(root=root, agents=CollabAgents([True, True, True])).run_cycle()
    assert state.status == "done"
    assert len(state.rounds) == 1
    assert state.rounds[0].quadrant == "clear"
    kinds = [e.kind for e in EventLog(root).replay()]
    assert "round_done" in kinds and "cycle_status" in kinds


def test_directive_injected_into_codex(tmp_path):
    root = make_collab_root(tmp_path, budget=5)
    router = Router(root)
    router.submit(Directive(id="001", kind="steer", text="인증부터 구현", approved=True))
    agents = CollabAgents([True] * 5)
    orch = Orchestrator(root=root, agents=agents, router=router)
    orch.run_round(1)
    # direction + goal reach Claude, who drafts the Codex work order
    assert "인증부터 구현" in agents.claude_prompts[0]
    assert "데모 과제" in agents.claude_prompts[0]
    assert orch.state.rounds[0].directive_id == "001"
    # Codex receives Claude's drafted imperative
    assert agents.codex_prompts[0].startswith("Create surface/wc.py")
    # applied directive is not re-applied next round
    orch.run_round(2)
    assert orch.state.rounds[1].directive_id is None
    assert "(none)" in agents.claude_prompts[1]       # no fresh direction this round


def test_halt_directive_stops_cycle(tmp_path):
    root = make_collab_root(tmp_path, budget=5)
    router = Router(root)
    router.submit(Directive(id="001", kind="halt", text="접근이 틀렸다", approved=True))
    state = Orchestrator(root=root, agents=CollabAgents([True] * 5),
                         router=router).run_cycle()
    assert state.status == "halted"
    assert len(state.rounds) == 1


def test_pause_flag_stops_cycle(tmp_path):
    root = make_collab_root(tmp_path, budget=5)
    (root / "pause.flag").write_text("p", encoding="utf-8")
    state = Orchestrator(root=root, agents=CollabAgents([True] * 5)).run_cycle()
    assert state.status == "paused"
    assert len(state.rounds) == 1


def test_build_fail_fires_claude_trigger(tmp_path):
    root = make_collab_root(tmp_path, budget=3, claude_on_build_fail=1)
    Orchestrator(root=root, agents=CollabAgents([False, True, True])).run_cycle()
    notes = [e for e in EventLog(root).replay() if e.kind == "notify"]
    assert notes and "build failed" in notes[0].payload.get("reason", "")


def test_validate_mode_unaffected(tmp_path):
    # A collaborate helper with mode flipped back must still not call codex path early.
    root = make_collab_root(tmp_path, budget=2)
    (root / "config.yaml").write_text("mode: validate\nround_budget: 2\n", encoding="utf-8")
    orch = Orchestrator(root=root, agents=CollabAgents([True, True]))
    assert orch.mode.name == "validate"
