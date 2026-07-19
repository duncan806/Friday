"""muto integrity asserts — 스펙 §3.

이 두 assert가 시스템 신뢰성의 전부다.
실패 시 IntegrityBreach를 던지고, 오케스트레이터는 해당 라운드를 무효 처리하며
로그에 INTEGRITY_BREACH로 기록한다.

1. assert_claude_isolation: Claude 호출 전, surface(cwd) 기준으로 src/가
   도달 불가능한지 검증한다. (경로 포함 관계 + symlink 탈출 검사)
2. assert_codex_prompt_clean: Codex 프롬프트 조립 시 task.md 및 predictions/
   내용이 포함되지 않았는지 검증한다.
"""

from pathlib import Path


class IntegrityBreach(AssertionError):
    """정보 비대칭이 깨졌다. 해당 라운드는 무효다."""


def assert_claude_isolation(workspace: Path) -> None:
    """surface가 Claude의 유일한 세계인지 검증한다.

    - surface/ 가 존재해야 한다.
    - src/ 가 surface/ 안에 있으면 안 된다.
    - surface/ 아래의 어떤 symlink도 surface 밖(특히 src/)을 가리키면 안 된다.
    """
    workspace = workspace.resolve()
    surface = workspace / "surface"
    src = workspace / "src"

    if not surface.is_dir():
        raise IntegrityBreach(f"surface/ 부재: {surface}")

    surface_real = surface.resolve()
    src_real = src.resolve()

    if src.exists() and src_real.is_relative_to(surface_real):
        raise IntegrityBreach(f"src/ 가 surface/ 내부에 있다: {src_real}")

    for p in surface.rglob("*"):
        if p.is_symlink():
            target = p.resolve()
            if not target.is_relative_to(surface_real):
                raise IntegrityBreach(
                    f"surface 탈출 symlink: {p} -> {target}")


def assert_codex_prompt_clean(
    prompt: str, task_path: Path, predictions_dir: Path
) -> None:
    """Codex는 과제(Why)를 볼 수 없다.

    프롬프트에 task.md 본문 또는 predictions/ 파일 본문의 한 줄이라도
    포함되면 IntegrityBreach.
    """
    forbidden_sources = []
    if task_path.is_file():
        forbidden_sources.append(("task.md", task_path.read_text(encoding="utf-8")))
    if predictions_dir.is_dir():
        for f in sorted(predictions_dir.glob("*.md")):
            forbidden_sources.append((f.name, f.read_text(encoding="utf-8")))

    for name, text in forbidden_sources:
        for line in text.splitlines():
            line = line.strip()
            if len(line) >= 8 and line in prompt:
                raise IntegrityBreach(
                    f"Codex 프롬프트에 {name} 내용 누출: {line[:60]!r}")
