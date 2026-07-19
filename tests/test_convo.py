from friday.convo import ConversationEngine, extract_directive
from friday.kernel import Authority
from friday.route import Router
from friday.bus import EventLog
from friday.domain import ConversationState, Turn
from friday.convo.memory import ConversationMemory


def test_extract_directive_parses_block():
    d = extract_directive(
        "좋아요, 방향을 이렇게 잡죠.\n```directive\nkind: steer\ntext: CSV 스키마부터\n```",
        "001")
    assert d and d.kind == "steer" and "CSV" in d.text
    assert d.origin == "human+claude"


def test_extract_directive_absent_or_noop():
    assert extract_directive("그냥 대화입니다", "001") is None
    assert extract_directive("```directive\nkind: noop\n```", "001") is None


def _engine(tmp_path, claude_fn):
    return ConversationEngine(tmp_path, Authority(), Router(tmp_path), claude_fn,
                              clock=lambda: "T")


def test_human_says_records_turns_and_submits_directive(tmp_path):
    reply = "이해했어요.\n```directive\nkind: steer\ntext: 인증부터 구현\n```"
    eng = _engine(tmp_path, lambda prompt: reply)
    d = eng.human_says("먼저 로그인이 되게 해줘")
    assert d and d.kind == "steer"
    # two turns recorded
    turns = eng.session.load().turns
    assert [t.role for t in turns] == ["human", "claude"]
    # directive materialized and pending for execution
    assert Router(tmp_path).pending(1).text == "인증부터 구현"
    # events emitted
    kinds = [e.kind for e in EventLog(tmp_path).replay()]
    assert kinds == ["human_turn", "claude_turn", "directive_issued"]


def test_human_can_halt(tmp_path):
    reply = "멈춥시다.\n```directive\nkind: halt\ntext: 접근이 틀렸다\n```"
    eng = _engine(tmp_path, lambda prompt: reply)
    d = eng.human_says("이건 아닌 것 같아, 멈춰")
    assert d and d.kind == "halt" and d.approved


def test_plain_conversation_yields_no_directive(tmp_path):
    eng = _engine(tmp_path, lambda prompt: "좋은 질문이네요. 조금 더 설명하면...")
    assert eng.human_says("이거 왜 이렇게 됐어?") is None
    assert Router(tmp_path).pending(1) is None


def test_memory_folds_exec_summary_and_clips():
    state = ConversationState(session_id="1",
                              turns=[Turn("human", "a"), Turn("claude", "b")])
    mem = ConversationMemory(budget_chars=2000, recent_turns=12)
    out = mem.build(state, exec_summary="round 3, blocked")
    assert "EXECUTION STATE" in out and "round 3" in out
    assert "[human] a" in out and "[claude] b" in out
