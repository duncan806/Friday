"""friday smoke test—first task (§10), 3 rounds. (spec §12-⑥)

Drives the whole loop (asserts -> filter -> report -> build -> dashboard)
with scripted mock agents instead of the real CLIs. Runs in a sandbox
workspace; prompts come from the packaged defaults, exactly as an installed
`friday run` would resolve them.

Script: R1 initial noise -> R2 in progress (blockage+deviation, one intent
sentence attempts to leak) -> R3 awaiting verdict (no blockage+deviation)
-> halt awaiting the human verdict.
"""

import shutil
import subprocess
import sys
import tempfile
import zipapp
from pathlib import Path

from friday.bandwidth_filter import apply_filter
from friday.dashboard_gen import generate as gen_dash
from friday.orchestrator import CLIAgents, Orchestrator

SCRIPT = [
    # (attempt response, build_ok)
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
    for d in ["workspace/src", "workspace/surface", "task", "reports/dropped",
              "predictions", "verdicts", "dashboard"]:
        (sandbox / d).mkdir(parents=True)
    (sandbox / "task" / "task.md").write_text(
        "A CLI tool that takes a CSV file and answers natural-language questions.\n",
        encoding="utf-8")
    (sandbox / "config.yaml").write_text("bandwidth_level: 1\nround_budget: 3\n")

    orch = Orchestrator(root=sandbox, agents=SmokeAgents(),
                        filter_fn=apply_filter, dashboard_fn=gen_dash)
    return orch.run_cycle()


def build_surface_pyz(surface: Path) -> Path:
    """Write a real, runnable .pyz product into surface/ (a tiny CSV-Q CLI)."""
    src = Path(tempfile.mkdtemp())
    (src / "__main__.py").write_text(
        "import sys\n"
        "if '--help' in sys.argv or len(sys.argv) == 1:\n"
        "    print('usage: csvq [--help] FILE QUESTION'); sys.exit(0)\n"
        "print('answer: 42'); sys.exit(0)\n", encoding="utf-8")
    out = surface / "app.pyz"
    zipapp.create_archive(str(src), target=str(out))
    return out


def smoke_surface_executable() -> bool:
    """Item 3: the user role must be able to EXECUTE the product.

    Always verifies `python surface/*.pyz --help` runs (the exact action a
    Claude turn takes). If the real `claude` CLI is present, additionally
    drives one live user turn to confirm the permission shape actually allows
    execution while blocking Read; otherwise that half is SKIPPED (reported,
    not silently dropped).
    """
    root = Path(tempfile.mkdtemp(prefix="friday-exec-"))
    surface = root / "workspace" / "surface"
    surface.mkdir(parents=True)
    pyz = build_surface_pyz(surface)

    pyz_name = pyz.name
    r = subprocess.run([sys.executable, pyz_name, "--help"], cwd=surface,
                       capture_output=True, text=True)
    exec_ok = r.returncode == 0 and "usage" in r.stdout
    print(f"exec   : python surface/{pyz_name} --help -> "
          f"rc={r.returncode} {'OK' if exec_ok else 'FAIL'}")

    if shutil.which("claude"):
        out = CLIAgents(root, timeout=180).claude(
            "You are the user. Run the only program in this directory with "
            "--help and report the usage line you saw.")
        live_ok = "usage" in out.lower()
        print(f"claude : live user turn executed product -> "
              f"{'OK' if live_ok else 'FAIL'}")
        return exec_ok and live_ok
    print("claude : SKIPPED (claude CLI not installed; live turn not run)")
    return exec_ok


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="friday-smoke-"))
    state = run_smoke(sandbox)
    print(f"sandbox: {sandbox}")
    print(f"status : {state.status}")
    for r in state.rounds:
        print(f"  R{r.round}: {r.quadrant} (blocked={r.blocked}, deviation={r.deviation}, "
              f"dropped={r.dropped_count})")
    loop_ok = (state.status == "awaiting_verdict"
               and [r.quadrant for r in state.rounds]
               == ["initial noise", "in progress", "awaiting verdict"]
               and (sandbox / "dashboard" / "index.html").is_file())
    exec_ok = smoke_surface_executable()
    ok = loop_ok and exec_ok
    print("SMOKE " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
