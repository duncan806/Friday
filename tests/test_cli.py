import os

from muto import cli
from muto.cli import cmd_init, cmd_stop


def in_dir(tmp_path, fn):
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        return fn()
    finally:
        os.chdir(old)


def test_init_creates_workspace(tmp_path):
    assert in_dir(tmp_path, cmd_init) == 0
    for d in cli.WORKSPACE_DIRS:
        assert (tmp_path / d).is_dir()
    assert (tmp_path / "config.yaml").is_file()
    assert (tmp_path / "task" / "task.md").is_file()
    assert (tmp_path / "prompts" / "claude_user.md").is_file()
    assert (tmp_path / "dashboard" / "index.html").is_file()
    assert (tmp_path / "dashboard" / "status.js").is_file()


def test_init_is_idempotent(tmp_path):
    in_dir(tmp_path, cmd_init)
    (tmp_path / "task" / "task.md").write_text("my task")
    in_dir(tmp_path, cmd_init)
    assert (tmp_path / "task" / "task.md").read_text() == "my task"


def test_stop_writes_flag(tmp_path):
    in_dir(tmp_path, cmd_init)
    assert in_dir(tmp_path, cmd_stop) == 0
    assert (tmp_path / "stop.flag").is_file()


def test_stop_requires_workspace(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        in_dir(tmp_path, cmd_stop)


def test_run_checks_stop_at_first_failure(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    checks, ok = cli.run_checks(None)
    assert not ok
    assert checks[-1]["name"] == "CLAUDE CLI" and checks[-1]["state"] == "fail"
    assert len(checks) == 1


def test_init_makes_workspace_a_git_repo(tmp_path):
    from muto import gitutil
    in_dir(tmp_path, cmd_init)
    assert gitutil.is_repo(tmp_path / "workspace")


def test_workspace_git_check_reported_separately(tmp_path, monkeypatch):
    # all CLI/auth probes pass; only the workspace-git state varies
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(cli, "_auth_probe", lambda cmd: True)

    in_dir(tmp_path, cmd_init)  # creates workspace/.git
    checks, ok = cli.run_checks(tmp_path)
    assert ok
    names = [c["name"] for c in checks]
    assert "WORKSPACE GIT" in names
    assert next(c for c in checks if c["name"] == "WORKSPACE GIT")["state"] == "ok"

    import shutil as _sh
    _sh.rmtree(tmp_path / "workspace" / ".git")
    checks, ok = cli.run_checks(tmp_path)
    assert not ok
    wg = next(c for c in checks if c["name"] == "WORKSPACE GIT")
    assert wg["state"] == "fail" and "muto init" in wg["hint"]
    # a failed git repo is NOT reported as a CODEX AUTH failure
    assert next(c for c in checks if c["name"] == "CODEX AUTH")["state"] == "ok"


def test_codex_auth_probe_skips_git_repo_check(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
    def fake_probe(cmd):
        if cmd[0] == "codex":
            seen["cmd"] = cmd
        return True
    monkeypatch.setattr(cli, "_auth_probe", fake_probe)
    cli.run_checks(None)
    assert "--skip-git-repo-check" in seen["cmd"]
