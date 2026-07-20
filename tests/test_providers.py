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
