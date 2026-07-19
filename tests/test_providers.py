import pytest

import friday.providers as providers
from friday.errors import AdapterError


def test_advisor_success(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "claude")

    def runner(cmd, **kw):
        assert "--permission-mode" in cmd and "bypassPermissions" in cmd
        assert cmd[1] == "-p"

        class R:
            stdout = "여기 방향입니다"
            stderr = ""
            returncode = 0
        return R()

    assert providers.claude_advisor("안녕", runner=runner) == "여기 방향입니다"


def test_advisor_root_refusal_surfaces(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "claude")

    def runner(cmd, **kw):
        class R:
            stdout = ""
            stderr = "--dangerously-skip-permissions cannot be used with root"
            returncode = 1
        return R()

    with pytest.raises(AdapterError):
        providers.claude_advisor("안녕", runner=runner)


def test_advisor_not_installed(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: None)
    with pytest.raises(AdapterError):
        providers.claude_advisor("안녕")


def test_build_engine_end_to_end(tmp_path):
    eng = providers.build_conversation_engine(
        tmp_path, {"convo_budget_chars": 1000}, claude_fn=lambda prompt: "그냥 대화")
    assert eng.human_says("안녕") is None  # plain reply → no directive


def test_exec_summary(tmp_path):
    (tmp_path / "status.json").write_text(
        '{"status":"running","round":2,"rounds":[{"quadrant":"clear"}]}', encoding="utf-8")
    s = providers.exec_summary(tmp_path)
    assert "running" in s and "round=2" in s


class _FakeProc:
    returncode = 0
    stderr = None

    def __init__(self, lines):
        self.stdout = iter(line + "\n" for line in lines)

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def test_advisor_stream_parses_token_deltas(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "claude")
    lines = [
        '{"type":"system","subtype":"init"}',
        '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"hel"}}}',
        '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}}',
        '{"type":"result","subtype":"success","result":"hello","is_error":false}',
    ]

    def fake_popen(cmd, **kw):
        assert "stream-json" in cmd and "--include-partial-messages" in cmd
        return _FakeProc(lines)

    got = []
    text = providers.claude_advisor_stream("hi", on_text=got.append, popen=fake_popen)
    assert text == "hello"
    assert "".join(got) == "hello"       # streamed token-by-token


def test_gpt_assist_answers_and_strips_footer(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "codex")

    def runner(cmd, **kw):
        assert "read-only" in cmd and "--ephemeral" in cmd
        assert "exec" in cmd

        class R:
            stdout = "Yes, I can review code without changes.\ntokens used\n2,820"
            stderr = ""
            returncode = 0
        return R()

    assert providers.gpt_assist("can you review?", runner=runner) == \
        "Yes, I can review code without changes."


def test_gpt_assist_not_installed(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: None)
    with pytest.raises(AdapterError):
        providers.gpt_assist("q")


def test_advisor_stream_falls_back_to_full_message(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "claude")
    lines = [
        '{"type":"assistant","message":{"content":[{"type":"text","text":"full reply"}]}}',
        '{"type":"result","result":"full reply","is_error":false}',
    ]
    got = []
    text = providers.claude_advisor_stream("hi", on_text=got.append,
                                           popen=lambda cmd, **kw: _FakeProc(lines))
    assert text == "full reply"
    assert "".join(got) == "full reply"   # printed once as fallback
