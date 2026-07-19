"""muto integrity asserts—spec §3.

These asserts are the entirety of system reliability. On failure, raise
IntegrityBreach; the orchestrator voids the round, writes no report, and
records INTEGRITY_BREACH in the log (a wrong report is worse than none).

1. assert_claude_isolation: before invoking Claude, verify that src/ is
   unreachable from surface (the cwd)—path containment plus symlink-escape
   checks.
2. assert_surface_cwd: before invoking Claude, verify that surface exists as
   a real directory whose resolved absolute path is exactly the cwd we will
   hand the subprocess—so a report can never be produced from the wrong
   working directory. (Absence is not a breach: the caller substitutes a
   product-cannot-ship report instead—spec §4d.)
3. assert_codex_prompt_clean: when assembling the Codex prompt, verify that
   the contents of task.md and predictions/ are not included.
"""

from pathlib import Path


class IntegrityBreach(AssertionError):
    """Information asymmetry has been broken. The round is void."""


def assert_surface_cwd(workspace: Path) -> Path:
    """Verify surface is a real directory that will be Claude's exact cwd.

    Returns the verified absolute surface path. Raises IntegrityBreach if
    surface exists but is not a directory, or is a symlink that would land
    the working directory somewhere other than workspace/surface. Surface
    *absence* is deliberately NOT a breach here—the caller checks existence
    first and substitutes a product-cannot-ship report.
    """
    workspace = Path(workspace).resolve()
    surface = workspace / "surface"
    if not surface.is_dir():
        raise IntegrityBreach(f"surface exists but is not a directory: {surface}")
    # the cwd the subprocess lands in (symlinks resolved) must equal the
    # expected absolute path exactly—no symlink redirection
    landed = surface.resolve()
    if landed != surface:
        raise IntegrityBreach(
            f"surface cwd mismatch: would land in {landed}, expected {surface}")
    return surface


def assert_claude_isolation(workspace: Path) -> None:
    """Verify that surface is Claude's entire world.

    - surface/ must exist.
    - src/ must not live inside surface/.
    - No symlink under surface/ may point outside surface/ (especially src/).
    """
    workspace = workspace.resolve()
    surface = workspace / "surface"
    src = workspace / "src"

    if not surface.is_dir():
        raise IntegrityBreach(f"surface/ missing: {surface}")

    surface_real = surface.resolve()
    src_real = src.resolve()

    if src.exists() and src_real.is_relative_to(surface_real):
        raise IntegrityBreach(f"src/ is inside surface/: {src_real}")

    for p in surface.rglob("*"):
        if p.is_symlink():
            target = p.resolve()
            if not target.is_relative_to(surface_real):
                raise IntegrityBreach(
                    f"symlink escapes surface: {p} -> {target}")


def assert_codex_prompt_clean(
    prompt: str, task_path: Path, predictions_dir: Path
) -> None:
    """Codex must never see the task (the Why).

    If even a single line from task.md or any predictions/ file appears in
    the prompt, raise IntegrityBreach.
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
                    f"Codex prompt leaks {name} content: {line[:60]!r}")
