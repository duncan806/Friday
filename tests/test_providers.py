import pytest

from friday import providers
from friday.errors import AdapterError


# ── pm_decide (Claude, read-only, structured) ────────────────────────────────

def test_pm_decide_is_read_only_and_parses(monkeypatch, tmp_path):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "claude")

    def runner(cmd, **kw):
        assert "--json-schema" in cmd
        # Claude cannot write — read-only tools only
        assert "--allowedTools" in cmd and "Read" in cmd and "Grep" in cmd
        assert "Edit" not in cmd and "Write" not in cmd

        class R:
            stdout = '{"structured_output":{"action":"instruct","message":"create x.py"}}'
            stderr = ""
            returncode = 0
        return R()

    d = providers.pm_decide(tmp_path, {}, "goal", "history", "last", runner=runner)
    assert d["action"] == "instruct" and d["message"] == "create x.py"


def test_pm_decide_result_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "claude")

    def runner(cmd, **kw):
        class R:
            stdout = '{"result":"{\\"action\\":\\"answer\\",\\"message\\":\\"hi\\"}"}'
            stderr = ""
            returncode = 0
        return R()

    d = providers.pm_decide(tmp_path, {}, "g", "h", "l", runner=runner)
    assert d["action"] == "answer" and d["message"] == "hi"


def test_pm_decide_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(providers.shutil, "which", lambda _: None)
    with pytest.raises(AdapterError):
        providers.pm_decide(tmp_path, {}, "g", "h", "l")


# ── claude_review (overseer, verify-only, structured) ────────────────────────

def test_claude_review_verifies_never_writes_and_parses(monkeypatch, tmp_path):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "claude")

    def runner(cmd, **kw):
        assert "--json-schema" in cmd
        # verify-only allowlist: git tools + the project's test command, never write
        assert any(a.startswith("Bash(git diff") for a in cmd)
        assert any("pytest" in a for a in cmd)
        assert "Write" not in cmd and "Edit" not in cmd and "Read" not in cmd

        class R:
            stdout = '{"structured_output":{"verdict":"correct","hard":true,"note":"add tests"}}'
            stderr = ""
            returncode = 0
        return R()

    v = providers.claude_review(tmp_path, "goal", "brief", "summary",
                                "python -m pytest -q", runner=runner)
    assert v["verdict"] == "correct" and v["hard"] is True and v["note"] == "add tests"


def test_claude_review_defaults_hard_and_note(monkeypatch, tmp_path):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "claude")

    def runner(cmd, **kw):
        class R:
            stdout = '{"structured_output":{"verdict":"continue"}}'
            stderr = ""
            returncode = 0
        return R()

    v = providers.claude_review(tmp_path, "g", "b", "s", runner=runner)
    assert v["verdict"] == "continue" and v["hard"] is False and v["note"] == ""


# ── codex_stream (Codex, sole writer, streamed activity) ─────────────────────

class _FakeCodex:
    returncode = 0
    stderr = None

    def __init__(self, lines):
        self.stdout = iter(line + "\n" for line in lines)

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def test_codex_stream_parses_events_and_final(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "codex")
    lines = [
        '{"type":"item.completed","item":{"type":"agent_message","text":"looking"}}',
        '{"type":"item.started","item":{"type":"command_execution","command":"ls"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"done, created x"}}',
    ]
    events = []
    text = providers.codex_stream("do it", on_event=events.append,
                                  popen=lambda cmd, **kw: _FakeCodex(lines))
    assert text == "done, created x"
    assert any(e.get("type") == "item.started" for e in events)


def test_codex_stream_not_installed(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: None)
    with pytest.raises(AdapterError):
        providers.codex_stream("x")


# ── codex_run (pipeline worker: killable, never silent on failure) ───────────

def test_codex_run_surfaces_worker_error_never_silence(monkeypatch):
    # codex not installed → codex_stream raises → codex_run must emit worker_error, not ""
    monkeypatch.setattr(providers.shutil, "which", lambda _: None)
    events = []
    out = providers.codex_run("brief", on_event=events.append)
    assert out == ""
    assert events and events[0]["type"] == "worker_error"
    assert events[0]["item"]["message"]


def test_codex_run_returns_final_on_success(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "codex")
    lines = ['{"type":"item.completed","item":{"type":"agent_message","text":"built it"}}']
    out = providers.codex_run("brief", popen=lambda cmd, **kw: _FakeCodex(lines))
    assert out == "built it"
