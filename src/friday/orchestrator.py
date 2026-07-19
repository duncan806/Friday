"""friday orchestrator—a thin router. It does not judge. (spec §2, §4)

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

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from .gitutil import commit_round
from .context import ContextManager
from .config import merged as _merge_config
from .kernel import Mode
from .bus import Event, EventLog
from .route import TriggerConfig, should_call_claude
from .reverse_filter import reverse_filter
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
    directive_id: str | None = None   # collaborate: the direction applied this round


@dataclass
class CycleState:
    rounds: list = field(default_factory=list)
    status: str = "running"
    context: dict = field(default_factory=dict)
    mode: str = "validate"


APPROVAL_MARKERS = (
    "approval required", "waiting for approval", "permission required",
    "approve this", "do you want to allow", "requires approval",
)


def _approval_requested(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in APPROVAL_MARKERS)


class CLIAgents:
    """Non-interactive subprocess invocations per spec §3."""

    def __init__(self, root: Path, timeout: int):
        self.root = root
        self.timeout = timeout

    def claude(self, prompt: str) -> str:
        surface = self.root / "workspace" / "surface"
        executable = shutil.which("claude") or "claude"
        # The user role must be able to EXECUTE the product, but never edit
        # files (Edit,Write) or read source (Read,Glob,Grep). Blocking Read is
        # the crux: it shuts down .pyz unpacking and source browsing via the
        # file tools. Empirically:
        #   - `--permission-mode plan` blocks execution itself → the user
        #     could not use the product at all. Wrong.
        #   - `bypassPermissions` maps to --dangerously-skip-permissions,
        #     which is refused under root. Fragile.
        # The robust shape is an allowlist: allow just Bash (runs
        # non-interactively in headless -p mode), and hard-block the file
        # tools. Bash stays powerful, so assert_claude_isolation is re-run
        # after the turn as post-hoc verification that surface/ stayed the
        # boundary (raw `cat ../src` reads remain a documented residual, U4).
        try:
            r = subprocess.run(
            [executable, "-p", prompt,
             "--allowedTools", "Bash",
             "--disallowedTools", "Edit,Write,Read,Glob,Grep"],
            cwd=surface, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return "agent call timed out; no user input was requested"
        output = (r.stdout or "") + (r.stderr or "")
        if _approval_requested(output):
            raise IntegrityBreach("Claude entered an approval-wait state")
        return r.stdout

    def codex(self, prompt: str) -> tuple[str, bool]:
        executable = shutil.which("codex") or "codex"
        try:
            # --ephemeral: a fresh session each turn. Without it, codex exec
            # resumes the directory's prior rollout and confabulates from stale
            # context (observed: rebuilding an unrelated app every round).
            r = subprocess.run(
            [executable, "exec", "--ephemeral", "--sandbox", "workspace-write",
             "--cd", "workspace", prompt],
            cwd=self.root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return "agent call timed out", False
        output = (r.stdout or "") + (r.stderr or "")
        if _approval_requested(output):
            raise IntegrityBreach("Codex entered an approval-wait state")
        return r.stdout, r.returncode == 0

    def claude_draft(self, prompt: str) -> str:
        """Draft text with Claude using the advisor profile (bypassPermissions,
        no isolation) — used in collaborate mode to author Codex's work order.
        Falls back to the isolated profile if bypass is refused (e.g. root)."""
        from .providers import claude_advisor
        from .errors import AdapterError
        try:
            return claude_advisor(prompt, timeout=self.timeout, cwd=self.root)
        except AdapterError:
            return self.claude(prompt)


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
                 prompt_builder=None, notify_fn=None, router=None, event_log=None):
        self.root = Path(root)
        if config is None:
            cfg_path = self.root / "config.yaml"
            raw = (yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                   if cfg_path.is_file() else {})
        else:
            raw = config
        self.config = _merge_config(raw)
        self.mode = Mode(self.config["mode"])
        self.agents = agents or CLIAgents(root, int(self.config.get("timeout_seconds", 1800)))
        # filter_fn(report_dict, level) -> (kept_dict, dropped_lines)
        self.filter_fn = filter_fn or (lambda rep, level: (rep, []))
        self.dashboard_fn = dashboard_fn or (lambda state, root: None)
        self.prompt_builder = prompt_builder
        self.notify_fn = notify_fn or (lambda title, message: None)
        self.context_manager = ContextManager(
            root,
            int(self.config.get("context_budget_chars", 60000)),
            int(self.config.get("context_recent_reports", 6)),
        )
        self.state = CycleState()
        self.state.mode = self.mode.name
        self.log_path = root / "reports" / "orchestrator.log"
        # collaborate-mode wiring (inert in validate mode)
        self.router = router
        self.bus = event_log or EventLog(root)
        self.trigger_cfg = TriggerConfig(
            claude_checkin_every=int(self.config.get("claude_checkin_every", 0)),
            claude_on_build_fail=int(self.config.get("claude_on_build_fail", 0)),
            dialogue_turns=int(self.config.get("dialogue_turns", 0)),
        )

    def _emit(self, event_kind: str, **payload) -> None:
        try:
            self.bus.append(Event(event_kind, "", payload))
        except OSError:
            pass

    def _paused(self) -> bool:
        return (self.root / "flags" / "pause.flag").exists() or \
               (self.root / "pause.flag").exists()

    def _restore_state(self) -> int:
        """Restore completed rounds from status.json; reports remain canonical."""
        path = self.root / "status.json"
        if not path.is_file():
            return 1
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            restored = []
            for item in raw.get("rounds", []):
                n = int(item["round"])
                if not self._p("reports", f"round_{n:03d}.md").is_file() and not item.get("void"):
                    break
                restored.append(RoundResult(**{
                    k: item[k] for k in RoundResult.__dataclass_fields__ if k in item
                }))
            prior_status = str(raw.get("status", "running"))
            self.state = CycleState(rounds=restored, status=prior_status)
            return (restored[-1].round + 1) if restored else 1
        except (OSError, ValueError, TypeError, KeyError):
            self._log("status.json unreadable; resuming from round 1")
            return 1

    # ── path helpers ──
    def _p(self, *parts) -> Path:
        return self.root.joinpath(*parts)

    def _log(self, msg: str) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def _load_prompt(self, name: str, **kw) -> str:
        # A workspace-local prompts/ copy (written by `friday init`) wins so
        # users can tune the templates; otherwise use the packaged default.
        local = self._p("prompts", name)
        if local.is_file():
            tpl = local.read_text(encoding="utf-8")
        else:
            tpl = resources.files("friday").joinpath(
                "data/prompts", name).read_text(encoding="utf-8")
        for k, v in kw.items():
            tpl = tpl.replace("{{" + k + "}}", str(v))
        return tpl

    # ── round ──
    def run_round(self, n: int) -> RoundResult:
        """Dispatch by mode. validate = the blockage-report validation loop;
        collaborate = GPT builds continuously, steered by human⇄Claude directives."""
        if self.mode.collaborate:
            return self._run_round_collaborate(n)
        return self._run_round_validate(n)

    def _run_round_collaborate(self, n: int) -> RoundResult:
        """Role-asymmetry round (implementation-spec §6, D6): the fast executor
        (GPT/Codex) builds from reports/ plus the current human-via-Claude
        direction. No blockage-report ritual, no information-hiding asserts;
        the kernel still governs which directives may exist."""
        workspace = self._p("workspace")
        directive_id = None
        halted = False
        try:
            direction = ""
            if self.router is not None:
                pend = self.router.pending(n)
                if pend is not None:
                    direction, directive_id = pend.text, pend.id
                    self.router.mark_applied(pend, n)
                    self._emit("directive_applied", id=pend.id, kind=pend.kind, round=n)
                    halted = pend.kind == "halt"

            reports_text, context_state = self.context_manager.build(
                list(self._p("reports").glob("round_*.md")))
            self.state.context = context_state
            task_path = self._p("task", "task.md")
            task_text = task_path.read_text(encoding="utf-8") if task_path.is_file() else ""
            # Claude (insight) drafts the build command for Codex (execution) —
            # the Tony→JARVIS step. Claude knows Codex acts only on a direct
            # imperative, so it phrases the order effectively (see
            # claude_workorder.md). Falls back to the template if no drafting
            # agent is available.
            work_order = ""
            draft_fn = (getattr(self.agents, "claude_draft", None)
                        or getattr(self.agents, "claude", None))
            if draft_fn is not None:
                try:
                    wo_prompt = self._load_prompt(
                        "claude_workorder.md", task=task_text,
                        direction=(direction or "(none)"), reports=reports_text, round=n)
                    drafted = draft_fn(wo_prompt)
                    if drafted and drafted.strip():
                        work_order = drafted.strip()
                        self._p("workorders").mkdir(parents=True, exist_ok=True)
                        self._p("workorders", f"round_{n:03d}.md").write_text(
                            work_order + "\n", encoding="utf-8")
                        self._emit("claude_turn", round=n, role="workorder")
                except Exception as exc:
                    self._log(f"work-order draft failed round={n}: {exc}")
            if not work_order:
                work_order = self._load_prompt(
                    "codex_collaborate.md", task=task_text,
                    direction=(direction or "(none)"), reports=reports_text, round=n)
            _, build_ok = self.agents.codex(work_order)

            body = yaml.safe_dump(
                {"report": {"round": n, "direction": direction, "build_ok": build_ok}},
                allow_unicode=True, sort_keys=False)
            if not build_ok:
                body += "build_failure: product cannot ship\n"
            self._p("reports", f"round_{n:03d}.md").write_text(body, encoding="utf-8")
            commit_round(workspace, n)

            blocked = not build_ok
            quadrant = "halted" if halted else ("blocked" if blocked else "clear")
            result = RoundResult(round=n, blocked=blocked, deviation=False,
                                 quadrant=quadrant, build_failed=not build_ok,
                                 directive_id=directive_id)
        except IntegrityBreach as e:
            self._log(f"INTEGRITY_BREACH round={n}: {e}")
            result = RoundResult(round=n, blocked=False, deviation=False,
                                 quadrant="void", void=True)

        self.state.rounds.append(result)
        self.dashboard_fn(self.state, self.root)
        self._log(f"round={n} quadrant={result.quadrant} void={result.void}")
        self.notify_fn("FRIDAY round complete", f"Round {n}: {result.quadrant}")
        return result

    def _round_trip(self, n: int, turns: int, task_text: str, level: int) -> None:
        """A안 bounded Codex↔Claude round-trip (spec §6.1 / M5). Codex asks a
        clarifying question; reverse_filter strips any code/How leak (audited in
        questions/*.dropped); Claude answers; the forward filter strips intent
        before the answer reaches Codex. Q/A is appended to the round report."""
        self._p("questions").mkdir(parents=True, exist_ok=True)
        self._p("answers").mkdir(parents=True, exist_ok=True)
        supplement: list[str] = []
        for t in range(turns):
            reports_text, _ = self.context_manager.build(
                list(self._p("reports").glob("round_*.md")))
            q_raw, _ = self.agents.codex(
                self._load_prompt("codex_question.md", reports=reports_text, round=n))
            q_clean, q_dropped = reverse_filter(q_raw)
            self._p("questions", f"round_{n:03d}_t{t}.md").write_text(
                q_clean + "\n", encoding="utf-8")
            if q_dropped:
                self._p("questions", f"round_{n:03d}_t{t}.dropped.md").write_text(
                    "\n".join(q_dropped) + "\n", encoding="utf-8")
            a_raw = self.agents.claude(
                self._load_prompt("claude_answer.md", question=q_clean,
                                  task=task_text, round=n))
            a_kept, a_dropped = self.filter_fn({"where_stuck": a_raw}, level)
            answer = str(a_kept.get("where_stuck", "")).strip()
            self._p("answers", f"round_{n:03d}_t{t}.md").write_text(
                answer + "\n", encoding="utf-8")
            if a_dropped:
                self._p("answers", f"round_{n:03d}_t{t}.dropped.md").write_text(
                    "\n".join(a_dropped) + "\n", encoding="utf-8")
            self._emit("question_asked", round=n, turn=t)
            self._emit("answer_given", round=n, turn=t)
            supplement.append(f"Q{t}: {q_clean}\nA{t}: {answer}")
        if supplement:
            path = self._p("reports", f"round_{n:03d}.md")
            path.write_text(path.read_text(encoding="utf-8") +
                            "\n# ROUND-TRIP\n" + "\n".join(supplement) + "\n",
                            encoding="utf-8")

    def _run_round_validate(self, n: int) -> RoundResult:
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
                self._emit("claude_turn", round=n, text="pre-registered a prediction")

                # b. task attempt -> blockage report
                assert_claude_isolation(workspace)
                assert_surface_cwd(workspace)
                attempt_prompt = self._load_prompt("claude_user.md", task=task_text,
                                                   round=n, mode="attempt")
                raw = self.agents.claude(attempt_prompt)
                # post-hoc verification: the Bash-enabled turn must not have
                # bridged surface/ to anything outside it (e.g. a new escaping
                # symlink or src/ relocated inside surface). Structural only—
                # it cannot audit a direct `cat ../src` Bash read (README U4).
                assert_claude_isolation(workspace)
                report = parse_claude_attempt(raw)

                # c. bandwidth filter
                kept, dropped = self.filter_fn(report, level)
                self._p("reports", f"round_{n:03d}.md").write_text(
                    yaml.safe_dump({"report": {**kept, "round": n}},
                                   allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
                _stuck = str(kept.get("where_stuck", "")).strip()
                self._emit("claude_turn", round=n,
                           text=f"tested surface — {_stuck[:90]}" if _stuck else "tested surface — no blockage")
                if dropped:
                    self._p("reports", "dropped", f"round_{n:03d}.md").write_text(
                        "\n".join(dropped) + "\n", encoding="utf-8")

                # c2. optional bounded Codex↔Claude round-trip (A안; off by default)
                if self.trigger_cfg.dialogue_turns > 0:
                    self._round_trip(n, self.trigger_cfg.dialogue_turns, task_text, level)

            # d. Codex build (all of reports/ is the only input)
            reports_text, context_state = self.context_manager.build(
                list(self._p("reports").glob("round_*.md")))
            self.state.context = context_state
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
        self.notify_fn("FRIDAY round complete", f"Round {n}: {result.quadrant}")
        return result

    # ── cycle ──
    def run_cycle(self) -> CycleState:
        # File-based stop signal: the dashboard's [STOP] button drops
        # stop.flag into the root; the loop checks it before every round.
        stop_flag = self.root / "stop.flag"
        stop_flag.unlink(missing_ok=True)  # a new run explicitly resumes an old stop
        start_round = self._restore_state()
        if self.state.status in ("awaiting_verdict", "budget_exhausted"):
            self.dashboard_fn(self.state, self.root)
            return self.state
        self.state.status = "running"
        self.dashboard_fn(self.state, self.root)  # initial render for the launcher
        budget = int(self.config.get("round_budget", 30))
        for n in range(start_round, budget + 1):
            if stop_flag.exists():
                self.state.status = "aborted"
                self._log(f"stop.flag detected before round {n}: aborted")
                break
            self._emit("round_started", round=n)
            result = self.run_round(n)
            self._emit("round_done", round=result.round, quadrant=result.quadrant,
                       blocked=result.blocked, void=result.void,
                       build_failed=result.build_failed)
            if result.build_failed:
                self._emit("build_failed", round=result.round)
            if result.void:
                self.state.status = "integrity_breach"
                self._emit("integrity_breach", round=result.round)
                self._log(f"cycle halted after INTEGRITY_BREACH in round {n}")
                break
            if self.mode.collaborate:
                # spend the slow, expensive insight only on a trigger (spec §4.5)
                reason = should_call_claude(self.state.rounds, self.trigger_cfg)
                if reason:
                    self._emit("notify", reason=reason, round=result.round)
                if result.quadrant == "halted":
                    self.state.status = "halted"
                    self._log(f"halt directive applied in round {n}")
                    break
                if self._paused():
                    self.state.status = "paused"
                    self._log(f"pause.flag detected after round {n}")
                    break
                if result.quadrant == "clear" and (
                        self.router is None or self.router.pending(n + 1) is None):
                    # built cleanly and no pending human direction → converged
                    self.state.status = "done"
                    self._log(f"collaborate converged at round {n}")
                    break
                continue  # collaborate: GPT keeps working; no verdict gate
            if not result.void and result.quadrant == "awaiting verdict":
                self.state.status = "awaiting_verdict"
                break
        else:
            self.state.status = "budget_exhausted"
        self._emit("cycle_status", status=self.state.status)
        self.dashboard_fn(self.state, self.root)
        self._log(f"cycle end: {self.state.status}")
        title = "FRIDAY awaiting verdict" if self.state.status == "awaiting_verdict" else "FRIDAY cycle ended"
        self.notify_fn(title, self.state.status.replace("_", " "))
        return self.state
