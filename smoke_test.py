"""muto 스모크 테스트 — 최초 과제(§10) 3라운드. (스펙 §12-⑥)

실제 CLI 대신 각본 목 에이전트로 루프 전체(assert → 필터 → 보고 →
빌드 → 대시보드)를 관통한다. 리포지토리를 더럽히지 않도록 샌드박스에서 실행.

각본: R1 초기 노이즈 → R2 진행 중(막힘+편차, 의도 문장 1개 누출 시도)
→ R3 판정 대기(막힘 없음+편차 있음) → 인간 판정 대기 정지.
"""

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bandwidth_filter import apply_filter        # noqa: E402
from dashboard_gen import generate as gen_dash   # noqa: E402
from orchestrator import Orchestrator            # noqa: E402

SCRIPT = [
    # (attempt 응답, build_ok)
    ("""```yaml
report:
  action_taken: surface의 사용법대로 python csvq.py sales.csv 를 실행했다.
  where_stuck: '질문을 입력할 방법이 없다. 인자도 프롬프트도 없이 즉시 종료된다.'
deviation: false
```""", True),
    ("""```yaml
report:
  action_taken: csvq.py sales.csv "3월 총매출은?" 을 실행했다. 매출 추이를 보기 위해 월별 질문도 했다.
  where_stuck: '두 번째 질문에서 KeyError로 정지했다.'
deviation: true
```""", True),
    ("""```yaml
report:
  action_taken: 세 종류의 CSV로 열 개 질문을 던졌고 모두 답을 받았다.
  where_stuck: ''
deviation: true
```""", True),
]


class SmokeAgents:
    def __init__(self):
        self.n = 0

    def claude(self, prompt):
        if "mode: predict" in prompt:
            return f"사전등록 예측: 평범한 구현자라면 argparse+pandas 단발 질의 CLI를 만들었을 것이다. (R{self.n + 1})"
        self.n += 1
        return SCRIPT[self.n - 1][0]

    def codex(self, prompt):
        return "built surface", SCRIPT[self.n - 1][1]


def run_smoke(sandbox: Path) -> "object":
    for d in ["workspace/src", "workspace/surface", "reports/dropped",
              "predictions", "verdicts", "dashboard"]:
        (sandbox / d).mkdir(parents=True)
    shutil.copytree(ROOT / "prompts", sandbox / "prompts")
    shutil.copytree(ROOT / "task", sandbox / "task")
    (sandbox / "config.yaml").write_text("bandwidth_level: 1\nround_budget: 3\n")

    orch = Orchestrator(root=sandbox, agents=SmokeAgents(),
                        filter_fn=apply_filter, dashboard_fn=gen_dash)
    return orch.run_cycle()


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="muto-smoke-"))
    state = run_smoke(sandbox)
    print(f"sandbox: {sandbox}")
    print(f"status : {state.status}")
    for r in state.rounds:
        print(f"  R{r.round}: {r.quadrant} (막힘={r.blocked}, 편차={r.deviation}, "
              f"드롭={r.dropped_count})")
    ok = (state.status == "awaiting_verdict"
          and [r.quadrant for r in state.rounds]
          == ["초기 노이즈", "진행 중", "판정 대기"]
          and (sandbox / "dashboard" / "index.html").is_file())
    print("SMOKE " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
