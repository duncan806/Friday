import os

from muto import cli
from muto.cli import cmd_init, cmd_shortcut, cmd_stop


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


def test_auth_probes_use_status_without_model_calls(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
    def fake_probe(cmd):
        if cmd[0] == "codex":
            seen["cmd"] = cmd
        return True
    monkeypatch.setattr(cli, "_auth_probe", fake_probe)
    cli.run_checks(None)
    assert seen["cmd"] == ["codex", "login", "status"]


def test_window_config_default_and_flag(tmp_path):
    in_dir(tmp_path, cmd_init)
    assert cli.load_config(tmp_path).get("window") is True  # DEFAULT_CONFIG


def test_favicon_and_title_in_dashboard(tmp_path):
    from muto.dashboard_gen import generate
    from muto.orchestrator import CycleState
    html = generate(CycleState(), tmp_path).read_text()
    assert "<title>MUTO</title>" in html
    assert 'rel="icon"' in html and "data:image/png;base64," in html


def test_launch_dashboard_falls_back_to_tab(tmp_path, monkeypatch):
    in_dir(tmp_path, cmd_init)
    monkeypatch.setattr(cli, "find_browser", lambda: None)
    opened = {}
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.setdefault("url", url))
    mode = cli.launch_dashboard(tmp_path, window=True)
    assert mode == "tab" and opened["url"].startswith("file://")


def test_launch_dashboard_app_window(tmp_path, monkeypatch):
    in_dir(tmp_path, cmd_init)
    calls = {}
    monkeypatch.setattr(cli, "find_browser", lambda: cli.Path("/usr/bin/chrome"))
    def fake_open(browser, url, size=cli.WINDOW_SIZE):
        calls["browser"], calls["url"], calls["size"] = browser, url, size
        return True
    monkeypatch.setattr(cli, "open_app_window", fake_open)
    assert cli.launch_dashboard(tmp_path, window=True) == "app"
    assert calls["size"] == (1024, 768) and calls["url"].startswith("file://")


def test_no_window_flag_skips_browser_search(tmp_path, monkeypatch):
    in_dir(tmp_path, cmd_init)
    monkeypatch.setattr(cli, "find_browser",
                        lambda: (_ for _ in ()).throw(AssertionError("searched")))
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    assert cli.launch_dashboard(tmp_path, window=False) == "tab"


def test_shortcut_linux_writes_desktop_entry(tmp_path, monkeypatch):
    # we run on linux, so os.name/platform already match; only redirect HOME
    in_dir(tmp_path, cmd_init)
    monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: tmp_path))
    assert in_dir(tmp_path, cmd_shortcut) == 0
    entry = (tmp_path / ".local/share/applications/muto.desktop").read_text()
    assert "Name=MUTO" in entry and f"Path={tmp_path}" in entry
    assert (tmp_path / "muto.png").is_file()


def test_shortcut_installs_ico_on_windows(tmp_path, monkeypatch):
    import types
    in_dir(tmp_path, cmd_init)
    # fake the os module reference so name=="nt" without mutating global os
    monkeypatch.setattr(cli, "os", types.SimpleNamespace(name="nt"))
    icon = cli._install_icon(tmp_path)
    assert icon.name == "muto.ico" and icon.read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_find_browser_returns_path_or_none(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli.Path, "is_file", lambda self: False)
    assert cli.find_browser() is None


def test_shortcut_and_stop_need_workspace(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        in_dir(tmp_path, cmd_shortcut)


def test_init_creates_gitkeep_and_tracks_skeleton(tmp_path):
    import subprocess
    in_dir(tmp_path, cmd_init)
    assert (tmp_path / "workspace" / "src" / ".gitkeep").is_file()
    assert (tmp_path / "workspace" / "surface" / ".gitkeep").is_file()
    # the round-0 baseline commit records the skeleton
    tracked = subprocess.run(["git", "-C", str(tmp_path / "workspace"),
                              "ls-files"], capture_output=True, text=True).stdout
    assert "src/.gitkeep" in tracked and "surface/.gitkeep" in tracked
