"""muto orchestrator — 얇은 라우터. 판단하지 않는다. (스펙 §2, §4)

세션 상태 관리, CLI 호출, 대역폭 필터 적용, 대시보드 생성만 한다.
LLM API를 직접 호출해 내용을 판단하는 코드는 금지 —
판단이 필요해 보이는 지점은 인간 판정 항목이거나 설계 오류다.

라운드 루프 (스펙 §4):
  a. Claude 사전등록 예측 → predictions/round_N.md (Codex 비공개)
  b. Claude surface에서 과제 수행 시도 → 막힘 보고
  c. 대역폭 필터 → reports/round_N.md (드롭 문장은 dropped/ 보존)
  d. Codex reports/ 전체 입력으로 src 수정, surface 재빌드
     (빌드 실패 = 최강도 막힘 보고 "제품 출시 불가" 자동 변환)
  e. 대시보드 재생성

종료 (스펙 §6): 막힘 없음 ∧ 편차 있음 → 인간 판정 대기 정지.
막힘 없음 ∧ 편차 없음 → 토스틱 수렴 경보(자동 중단하지 않는다 —
갇힘 판단은 인간의 중단 버튼 몫이다). 그 외 라운드 예산까지 반복.
"""

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from integrity import (
    IntegrityBreach,
    assert_claude_isolation,
    assert_codex_prompt_clean,
)

ROOT = Path(__file__).resolve().parent

QUADRANTS = {
    (True, False): "초기 노이즈",
    (True, True): "진행 중",
    (False, False): "토스틱 수렴 — 경보",
    (False, True): "판정 대기",
}


@dataclass
class RoundResult:
    round: int
    blocked: bool
    deviation: bool
    quadrant: str
    void: bool = False          # INTEGRITY_BREACH 시 무효
    build_failed: bool = False
    dropped_count: int = 0


@dataclass
class CycleState:
    rounds: list = field(default_factory=list)
    status: str = "running"     # running | awaiting_verdict | budget_exhausted | aborted


class CLIAgents:
    """스펙 §3의 비대화형 서브프로세스 호출."""

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
    """Claude 사용자 턴 출력에서 보고 블록을 파싱한다.

    기대 형식: ```yaml ... ``` 펜스 안의 report 스키마(스펙 §5) +
    deviation: true/false. 파싱 실패 시 전문을 where_stuck으로 취급
    (판단하지 않는다 — 형식 불량도 하나의 막힘이다).
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
    def __init__(self, root: Path = ROOT, config: dict | None = None,
                 agents=None, filter_fn=None, dashboard_fn=None,
                 prompt_builder=None):
        self.root = root
        self.config = config or yaml.safe_load((root / "config.yaml").read_text())
        self.agents = agents or CLIAgents(root, int(self.config.get("timeout_seconds", 1800)))
        # filter_fn(report_dict, level) -> (kept_dict, dropped_lines)
        self.filter_fn = filter_fn or (lambda rep, level: (rep, []))
        self.dashboard_fn = dashboard_fn or (lambda state, root: None)
        self.prompt_builder = prompt_builder
        self.state = CycleState()
        self.log_path = root / "reports" / "orchestrator.log"

    # ── 경로 헬퍼 ──
    def _p(self, *parts) -> Path:
        return self.root.joinpath(*parts)

    def _log(self, msg: str) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def _load_prompt(self, name: str, **kw) -> str:
        tpl = self._p("prompts", name).read_text(encoding="utf-8")
        for k, v in kw.items():
            tpl = tpl.replace("{{" + k + "}}", str(v))
        return tpl

    # ── 라운드 ──
    def run_round(self, n: int) -> RoundResult:
        task_text = self._p("task", "task.md").read_text(encoding="utf-8")
        workspace = self._p("workspace")
        level = int(self.config.get("bandwidth_level", 1))

        try:
            # a. 사전등록 예측 (Claude만, Codex 비공개)
            assert_claude_isolation(workspace)
            pred_prompt = self._load_prompt("claude_user.md", task=task_text,
                                            round=n, mode="predict")
            prediction = self.agents.claude(pred_prompt)
            self._p("predictions", f"round_{n:03d}.md").write_text(
                prediction, encoding="utf-8")

            # b. 과제 수행 시도 → 막힘 보고
            assert_claude_isolation(workspace)
            attempt_prompt = self._load_prompt("claude_user.md", task=task_text,
                                               round=n, mode="attempt")
            raw = self.agents.claude(attempt_prompt)
            report = parse_claude_attempt(raw)

            # c. 대역폭 필터
            kept, dropped = self.filter_fn(report, level)
            self._p("reports", f"round_{n:03d}.md").write_text(
                yaml.safe_dump({"report": {**kept, "round": n}},
                               allow_unicode=True, sort_keys=False),
                encoding="utf-8")
            if dropped:
                self._p("reports", "dropped", f"round_{n:03d}.md").write_text(
                    "\n".join(dropped) + "\n", encoding="utf-8")

            # d. Codex 빌드 (reports/ 전체가 유일한 입력)
            reports_text = "\n\n".join(
                p.read_text(encoding="utf-8")
                for p in sorted(self._p("reports").glob("round_*.md")))
            codex_prompt = self._load_prompt("codex_builder.md",
                                             reports=reports_text, round=n)
            assert_codex_prompt_clean(codex_prompt, self._p("task", "task.md"),
                                      self._p("predictions"))
            _, build_ok = self.agents.codex(codex_prompt)
            if not build_ok:
                # 빌드 실패 = 최강도 막힘 보고로 자동 변환
                path = self._p("reports", f"round_{n:03d}.md")
                path.write_text(path.read_text(encoding="utf-8") +
                                "\nbuild_failure: 제품 출시 불가\n", encoding="utf-8")

            blocked = bool(str(kept.get("where_stuck", "")).strip()) or not build_ok
            deviation = bool(report.get("deviation", False))
            result = RoundResult(
                round=n, blocked=blocked, deviation=deviation,
                quadrant=QUADRANTS[(blocked, deviation)],
                build_failed=not build_ok, dropped_count=len(dropped))

        except IntegrityBreach as e:
            self._log(f"INTEGRITY_BREACH round={n}: {e}")
            result = RoundResult(round=n, blocked=False, deviation=False,
                                 quadrant="무효", void=True)

        self.state.rounds.append(result)
        # e. 대시보드 재생성
        self.dashboard_fn(self.state, self.root)
        self._log(f"round={n} quadrant={result.quadrant} void={result.void}")
        return result

    # ── 사이클 ──
    def run_cycle(self) -> CycleState:
        budget = int(self.config.get("round_budget", 10))
        for n in range(1, budget + 1):
            result = self.run_round(n)
            if not result.void and result.quadrant == "판정 대기":
                self.state.status = "awaiting_verdict"
                break
        else:
            self.state.status = "budget_exhausted"
        self.dashboard_fn(self.state, self.root)
        self._log(f"cycle end: {self.state.status}")
        return self.state


def main() -> int:
    task = ROOT / "task" / "task.md"
    if not task.is_file():
        print("task/task.md 가 없다. 과제를 먼저 심어라.", file=sys.stderr)
        return 1
    try:
        from bandwidth_filter import apply_filter
    except ImportError:
        apply_filter = None
    try:
        from dashboard_gen import generate as gen_dash
    except ImportError:
        gen_dash = None
    orch = Orchestrator(filter_fn=apply_filter, dashboard_fn=gen_dash)
    state = orch.run_cycle()
    print(json.dumps({"status": state.status,
                      "rounds": [r.quadrant for r in state.rounds]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
