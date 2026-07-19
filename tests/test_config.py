import pytest

from friday import config
from friday.errors import ConfigError


def test_defaults_are_validate_baseline():
    m = config.merged({})
    assert m["mode"] == "validate"
    assert m["dialogue_turns"] == 0
    assert m["claude_checkin_every"] == 0
    assert m["claude_on_build_fail"] == 0


def test_user_overlay_wins():
    m = config.merged({"mode": "collaborate", "claude_checkin_every": 5})
    assert m["mode"] == "collaborate"
    assert m["claude_checkin_every"] == 5
    assert m["round_budget"] == 30  # untouched default retained


def test_rejects_unknown_mode():
    with pytest.raises(ConfigError):
        config.merged({"mode": "chatty"})


def test_rejects_negative_int():
    with pytest.raises(ConfigError):
        config.merged({"dialogue_turns": -1})


def test_rejects_bool_for_int_key():
    with pytest.raises(ConfigError):
        config.merged({"round_budget": True})


def test_load_missing_file_uses_defaults(tmp_path):
    assert config.load(tmp_path)["mode"] == "validate"


def test_load_reads_yaml(tmp_path):
    (tmp_path / "config.yaml").write_text("mode: collaborate\ndialogue_turns: 2\n", encoding="utf-8")
    loaded = config.load(tmp_path)
    assert loaded["mode"] == "collaborate" and loaded["dialogue_turns"] == 2
