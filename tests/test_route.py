from dataclasses import dataclass

import pytest

from friday.domain import Directive
from friday.route import TriggerConfig, should_call_claude, Router
from friday.errors import AuthorityBreach


@dataclass
class _R:
    build_failed: bool = False


def test_checkin_every():
    cfg = TriggerConfig(claude_checkin_every=3)
    assert should_call_claude([_R(), _R(), _R()], cfg)
    assert should_call_claude([_R(), _R()], cfg) is None


def test_build_fail_streak():
    cfg = TriggerConfig(claude_on_build_fail=2)
    assert should_call_claude([_R(False), _R(True), _R(True)], cfg)
    assert should_call_claude([_R(True), _R(False)], cfg) is None


def test_no_trigger_when_empty():
    assert should_call_claude([], TriggerConfig(claude_checkin_every=1)) is None


def test_router_submit_requires_approval(tmp_path):
    r = Router(tmp_path)
    with pytest.raises(AuthorityBreach):
        r.submit(Directive(id="1", kind="steer", approved=False))


def test_router_pending_and_apply(tmp_path):
    r = Router(tmp_path)
    d = Directive(id="1", kind="steer", text="go left", approved=True)
    r.submit(d)
    got = r.pending(1)
    assert got and got.text == "go left"
    r.mark_applied(got, 1)
    assert r.pending(2) is None
