import os

from friday import cli


def _in(tmp, fn):
    old = os.getcwd()
    os.chdir(tmp)
    try:
        return fn()
    finally:
        os.chdir(old)


def test_init_writes_config(tmp_path):
    assert _in(tmp_path, cli.cmd_init) == 0
    cfg = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "round_budget" in cfg and "codex_model" in cfg


def test_find_root(tmp_path):
    (tmp_path / "config.yaml").write_text("x", encoding="utf-8")
    assert _in(tmp_path, cli.find_root) is not None


def test_run_checks_stops_on_missing_cli(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    checks, ok = cli.run_checks(None)
    assert not ok
    assert checks[0]["name"] == "CLAUDE CLI" and checks[0]["state"] == "fail"
    assert checks[0]["hint"]


def test_run_checks_all_ok(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(cli, "_auth_probe", lambda cmd: True)
    checks, ok = cli.run_checks(None)
    assert ok and len(checks) == 4
    assert [c["name"] for c in checks] == ["CLAUDE CLI", "CODEX CLI", "CLAUDE AUTH", "CODEX AUTH"]
