import os
import sys
from pathlib import Path

import pytest

from muto.integrity import (  # noqa: E402
    IntegrityBreach,
    assert_claude_isolation,
    assert_codex_prompt_clean,
)


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "workspace" / "src").mkdir(parents=True)
    (tmp_path / "workspace" / "surface").mkdir(parents=True)
    return tmp_path / "workspace"


def test_isolation_ok(ws):
    (ws / "surface" / "app").write_text("binary")
    assert_claude_isolation(ws)


def test_isolation_missing_surface(tmp_path):
    (tmp_path / "workspace" / "src").mkdir(parents=True)
    with pytest.raises(IntegrityBreach):
        assert_claude_isolation(tmp_path / "workspace")


def test_isolation_symlink_escape(ws):
    os.symlink(ws / "src", ws / "surface" / "leak")
    with pytest.raises(IntegrityBreach):
        assert_claude_isolation(ws)


def test_isolation_symlink_internal_ok(ws):
    (ws / "surface" / "real.txt").write_text("x")
    os.symlink(ws / "surface" / "real.txt", ws / "surface" / "alias.txt")
    assert_claude_isolation(ws)


@pytest.fixture
def secrets(tmp_path):
    task = tmp_path / "task.md"
    task.write_text("CSV 파일을 받아 자연어 질문에 답하는 CLI 도구를 만들어라.\n")
    preds = tmp_path / "predictions"
    preds.mkdir()
    (preds / "round_001.md").write_text("평범한 구현자라면 pandas로 만들었을 것이다.\n")
    return task, preds


def test_prompt_clean_ok(secrets):
    task, preds = secrets
    assert_codex_prompt_clean("reports/ 를 읽고 src 를 수정하라.", task, preds)


def test_prompt_leaks_task(secrets):
    task, preds = secrets
    prompt = "다음 과제: CSV 파일을 받아 자연어 질문에 답하는 CLI 도구를 만들어라."
    with pytest.raises(IntegrityBreach):
        assert_codex_prompt_clean(prompt, task, preds)


def test_prompt_leaks_prediction(secrets):
    task, preds = secrets
    prompt = "참고: 평범한 구현자라면 pandas로 만들었을 것이다."
    with pytest.raises(IntegrityBreach):
        assert_codex_prompt_clean(prompt, task, preds)


def test_prompt_clean_when_no_secret_files(tmp_path):
    assert_codex_prompt_clean("anything", tmp_path / "nope.md", tmp_path / "nopreds")


def test_surface_cwd_ok(ws):
    from muto.integrity import assert_surface_cwd
    got = assert_surface_cwd(ws)
    assert got == (ws.resolve() / "surface")


def test_surface_cwd_breach_when_file(tmp_path):
    from muto.integrity import assert_surface_cwd
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "surface").write_text("i am a file, not a dir")
    with pytest.raises(IntegrityBreach):
        assert_surface_cwd(tmp_path / "workspace")


def test_surface_cwd_breach_when_symlink(tmp_path):
    from muto.integrity import assert_surface_cwd
    (tmp_path / "workspace").mkdir()
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", tmp_path / "workspace" / "surface")
    with pytest.raises(IntegrityBreach):
        assert_surface_cwd(tmp_path / "workspace")
