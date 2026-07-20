from friday import tui


# ── milestone detection (primary review trigger) ─────────────────────────────

def test_command_completion_is_a_milestone():
    assert tui._is_milestone(
        {"type": "item.completed", "item": {"type": "command_execution"}})


def test_file_write_is_a_milestone():
    assert tui._is_milestone(
        {"type": "item.started", "item": {"type": "file_change", "path": "x.py"}})


def test_worker_error_is_a_milestone():
    assert tui._is_milestone({"type": "worker_error", "item": {"message": "boom"}})


def test_agent_message_is_not_a_milestone():
    assert not tui._is_milestone(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}})


# ── stream summary (faithful digest for the overseer, not lossy truncation) ──

def test_summary_includes_commands_files_and_errors():
    buf = [
        {"type": "item.started", "item": {"type": "command_execution", "command": "ls -a"}},
        {"type": "item.started", "item": {"type": "file_change", "path": "src/x.py"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "created x.py"}},
        {"type": "worker_error", "item": {"message": "codex crashed"}},
    ]
    s = tui._stream_summary(buf)
    assert "ls -a" in s
    assert "src/x.py" in s
    assert "created x.py" in s
    assert "codex crashed" in s


def test_summary_empty_buffer():
    assert tui._stream_summary([]) == "(nothing yet)"


# ── continuation brief (single compression, authored by the overseer) ────────

def test_continuation_brief_folds_history_and_correction():
    b = tui._continuation_brief("$ ls\ncodex: made x", "now add tests")
    assert "already been done" in b
    assert "made x" in b
    assert "now add tests" in b
