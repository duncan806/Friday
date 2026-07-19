"""muto orchestrator—a thin router. It does not judge. (spec §2, §4)

It only manages session state, invokes the CLIs, applies the bandwidth
filter, and generates the dashboard. Code that calls an LLM API directly to
judge content is forbidden—any point that seems to require judgment is
either a human-verdict item or a design error.

Round loop (spec §4):
  a. Claude pre-registered prediction -> predictions/round_N.md (hidden from Codex)
  b. Claude attempts the task on surface -> blockage report
  c. bandwidth filter -> reports/round_N.md (dropped sentences preserved in dropped/)
  d. Codex takes all of reports/ as input, edits src, rebuilds surface
     (build failure auto-converts to the maximum-severity blockage
     "product cannot ship")
  e. regenerate the dashboard

Termination (spec §6): no blockage AND deviation present -> halt, awaiting
human verdict. No blockage AND no deviation -> toxic-convergence alert (do
NOT auto-abort—judging entrapment belongs to the human's stop button).
Otherwise repeat until the round budget runs out.
"""

import subprocess
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from .gitutil import commit_round
from .integrity import (
    IntegrityBreach,
    assert_claude_isolation,
    assert_codex_prompt_clean,
    assert_surface_cwd,
)

QUADRANTS = {
    (True, False): "initial noise",
    (True, True): "in progress",
    (False, False): "toxic convergence—alert",
    (False, True): "awaiting verdict",
}


@dataclass
class RoundResult:
    round: int
    blocked: bool
    deviation: bool
    quadrant: str
    void: bool = False          # voided on INTEGRITY_BREACH
    build_failed: bool = False
    dropped_count: int = 0


@dataclass
class CycleState:
    rounds: list = field(default_factory=list)
    status: str = "running"     # running | awaiting_verdict | budget_exhausted | aborted


class CLIAgents:
    """Non-interactive subprocess invocations per spec §3."""

    def __init__(self, root: Path, timeout: int):
        self.root = root
        self.timeout = timeout

    def claude(self, prompt: str) -> str:
        surface = self.root / "workspace" / "surface"
        r = subprocess.run(
            ["claude", "-p", prompt,
             "--permission-mode", "plan",
             "--disallowedTools", "Edit,Write"],
            cwd=surface, capture_output=True, text=True, timeout=self.timeout)
        return r.stdout

    def codex(self, prompt: str) -> tuple[str, bool]:
        r = subprocess.run(
            ["codex", "exec", "--sandbox", "workspace-write",
             "--cd", "workspace", prompt],
            cwd=self.root, capture_output=True, text=True, timeout=self.timeout)
        return r.stdout, r.returncode == 0


def parse_claude_attempt(output: str) -> dict:
    """Parse the report block out of Claude's user-turn output.

    Expected form: the report schema (spec §5) inside a ```yaml ... ``` fence,
    plus deviation: true/false. On parse failure, treat the full text as
    where_stuck (we do not judge—malformed output is itself a blockage).
    """
    text = output
    if "```yaml" in output:
        text = output.split("```yaml", 1)[1].split("```", 1)[0]
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict):
            rep = data.get("report", data)
            if isinstance(rep, dict):
                rep.setdefault("deviation", bool(data.get("deviation", False)))
                return rep
    except yaml.YAMLError:
        pass
    return {"action_taken": "", "where_stuck": output.strip(), "deviation": False}


class Orchestrator:
    def __init__(self, root: Path, config: dict | None = None,
                 agents=None, filter_fn=None, dashboard_fn=None,
                 prompt_builder=None):
        self.root = Path(root)
        self.config = config or yaml.safe_load((root / "config.yaml").read_text())
        self.agents = agents or CLIAgents(root, int(self.config.get("timeout_seconds", 1800)))
        # filter_fn(report_dict, level) -> (kept_dict, dropped_lines)
        self.filter_fn = filter_fn or (lambda rep, level: (rep, []))
        self.dashboard_fn = dashboard_fn or (lambda state, root: None)
        self.prompt_builder = prompt_builder
        self.state = CycleState()
        self.log_path = root / "reports" / "orchestrator.log"

    # ── path helpers ──
    def _p(self, *parts) -> Path:
        return self.root.joinpath(*parts)

    def _log(self, msg: str) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def _load_prompt(self, name: str, **kw) -> str:
        # A workspace-local prompts/ copy (written by `muto init`) wins so
        # users can tune the templates; otherwise use the packaged default.
        local = self._p("prompts", name)
        if local.is_file():
            tpl = local.read_text(encoding="utf-8")
        else:
            tpl = resources.files("muto").joinpath(
                "data/prompts", name).read_text(encoding="utf-8")
        for k, v in kw.items():
            tpl = tpl.replace("{{" + k + "}}", str(v))
        return tpl

    # ── round ──
    def run_round(self, n: int) -> RoundResult:
        task_text = self._p("task", "task.md").read_text(encoding="utf-8")
        workspace = self._p("workspace")
        level = int(self.config.get("bandwidth_level", 1))

        surface = workspace / "surface"
        try:
            if not surface.exists():
                # surface absent: no build artifact to test. Skip the whole
                # Claude turn (its cwd would be invalid) and substitute the
                # maximum-severity report—same path as a build failure (§4d).
                self._log(f"round={n}: surface absent, skipping Claude turn")
                report = {"action_taken": "",
                          "where_stuck": "no build artifact in surface/ to test"}
                kept, dropped = report, []
                self._p("reports", f"round_{n:03d}.md").write_text(
                    yaml.safe_dump({"report": {**kept, "round": n}},
                                   allow_unicode=True, sort_keys=False) +
                    "build_failure: product cannot ship\n",
                    encoding="utf-8")
            else:
                # Integrity gate (item 1): surface must be a real directory
                # that is exactly Claude's cwd, or the round is void with no
                # report. A wrong report is worse than no report.
                assert_surface_cwd(workspace)

                # a. pre-registered prediction (Claude only, hidden from Codex)
                assert_claude_isolation(workspace)
                pred_prompt = self._load_prompt("claude_user.md", task=task_text,
                                                round=n, mode="predict")
                prediction = self.agents.claude(pred_prompt)
                self._p("predictions", f"round_{n:03d}.md").write_text(
                    prediction, encoding="utf-8")

                # b. task attempt -> blockage report
                assert_claude_isolation(workspace)
                assert_surface_cwd(workspace)
                attempt_prompt = self._load_prompt("claude_user.md", task=task_text,
                                                   round=n, mode="attempt")
                raw = self.agents.claude(attempt_prompt)
                report = parse_claude_attempt(raw)

                # c. bandwidth filter
                kept, dropped = self.filter_fn(report, level)
                self._p("reports", f"round_{n:03d}.md").write_text(
                    yaml.safe_dump({"report": {**kept, "round": n}},
                                   allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
                if dropped:
                    self._p("reports", "dropped", f"round_{n:03d}.md").write_text(
                        "\n".join(dropped) + "\n", encoding="utf-8")

            # d. Codex build (all of reports/ is the only input)
            reports_text = "\n\n".join(
                p.read_text(encoding="utf-8")
                for p in sorted(self._p("reports").glob("round_*.md")))
            codex_prompt = self._load_prompt("codex_builder.md",
                                             reports=reports_text, round=n)
            assert_codex_prompt_clean(codex_prompt, self._p("task", "task.md"),
                                      self._p("predictions"))
            _, build_ok = self.agents.codex(codex_prompt)
            if not build_ok:
                # build failure auto-converts to the maximum-severity blockage
                path = self._p("reports", f"round_{n:03d}.md")
                path.write_text(path.read_text(encoding="utf-8") +
                                "\nbuild_failure: product cannot ship\n", encoding="utf-8")
            # snapshot the workspace so Codex's changes leave per-round
            # history (no-op when workspace/ is not a git repo)
            commit_round(self._p("workspace"), n)

            blocked = bool(str(kept.get("where_stuck", "")).strip()) or not build_ok
            deviation = bool(report.get("deviation", False))
            result = RoundResult(
                round=n, blocked=blocked, deviation=deviation,
                quadrant=QUADRANTS[(blocked, deviation)],
                build_failed=not build_ok, dropped_count=len(dropped))

        except IntegrityBreach as e:
            self._log(f"INTEGRITY_BREACH round={n}: {e}")
            result = RoundResult(round=n, blocked=False, deviation=False,
                                 quadrant="void", void=True)

        self.state.rounds.append(result)
        # e. regenerate the dashboard
        self.dashboard_fn(self.state, self.root)
        self._log(f"round={n} quadrant={result.quadrant} void={result.void}")
        return result

    # ── cycle ──
    def run_cycle(self) -> CycleState:
        # File-based stop signal: the dashboard's [STOP] button drops
        # stop.flag into the root; the loop checks it before every round.
        stop_flag = self.root / "stop.flag"
        stop_flag.unlink(missing_ok=True)  # clear a stale flag from a previous run
        self.dashboard_fn(self.state, self.root)  # initial render for the launcher
        budget = int(self.config.get("round_budget", 10))
        for n in range(1, budget + 1):
            if stop_flag.exists():
                self.state.status = "aborted"
                self._log(f"stop.flag detected before round {n}: aborted")
                break
            result = self.run_round(n)
            if not result.void and result.quadrant == "awaiting verdict":
                self.state.status = "awaiting_verdict"
                break
        else:
            self.state.status = "budget_exhausted"
        self.dashboard_fn(self.state, self.root)
        self._log(f"cycle end: {self.state.status}")
        return self.state
