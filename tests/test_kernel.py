import pytest

from friday.domain import Directive
from friday.kernel import Authority, Mode
from friday.errors import AuthorityBreach, ConfigError


def test_gpt_cannot_halt():
    # The differentiator, enforced in code: the executor may not decide to stop.
    auth = Authority()
    d = Directive(id="1", kind="halt", origin="exec")
    with pytest.raises(AuthorityBreach):
        auth.gate(d, actor="exec")
    assert not d.approved


def test_human_can_halt():
    auth = Authority()
    d = Directive(id="1", kind="halt", origin="human+claude")
    out = auth.gate(d, actor="human")
    assert out.approved


@pytest.mark.parametrize("kind", ["redesign", "verdict"])
def test_authority_kinds_need_human(kind):
    auth = Authority()
    with pytest.raises(AuthorityBreach):
        auth.gate(Directive(id="x", kind=kind, origin="trigger"), actor="exec")


def test_steer_allowed_without_human():
    auth = Authority()
    d = Directive(id="1", kind="steer", origin="trigger")
    assert auth.gate(d, actor="trigger").approved


def test_mode_policy():
    assert Mode("validate").policy()["information_asymmetry"] is True
    assert Mode("validate").policy()["forward_filter"] is True
    assert Mode("collaborate").policy()["dialogue_allowed"] is True
    assert Mode("collaborate").policy()["claude_profile"] == "advisor"
    with pytest.raises(ConfigError):
        Mode("bogus")
