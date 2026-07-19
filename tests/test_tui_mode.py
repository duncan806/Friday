from friday.tui import _cycle_mode, _mode_bar, _load_cfg


def test_cycle_mode_toggles_and_preserves(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "# friday config\nmode: validate\nround_budget: 5\n", encoding="utf-8")
    assert _cycle_mode(tmp_path) == "collaborate"
    assert _load_cfg(tmp_path)["mode"] == "collaborate"
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "round_budget: 5" in text and "# friday config" in text  # comments/keys kept
    assert _cycle_mode(tmp_path) == "validate"


def test_cycle_mode_adds_when_missing(tmp_path):
    (tmp_path / "config.yaml").write_text("round_budget: 5\n", encoding="utf-8")
    assert _cycle_mode(tmp_path) == "collaborate"
    assert _load_cfg(tmp_path)["mode"] == "collaborate"


def test_mode_bar_names_current_and_other():
    assert "collaborate" in _mode_bar("collaborate")
    assert "validate" in _mode_bar("validate") and "collaborate" in _mode_bar("validate")
    assert "⏵⏵" in _mode_bar("validate")
