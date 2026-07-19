import pytest

from friday.control_server import safe_get_target, origin_ok
from friday.integrity import assert_reverse_channel_clean, IntegrityBreach


def _dash(tmp_path):
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "index.html").write_text("x", encoding="utf-8")
    (tmp_path / "task").mkdir()
    (tmp_path / "task" / "task.md").write_text("secret Why", encoding="utf-8")
    return tmp_path


def test_dashboard_index_served(tmp_path):
    _dash(tmp_path)
    assert safe_get_target(tmp_path, "/index.html") is not None
    assert safe_get_target(tmp_path, "/") is not None


def test_traversal_to_task_blocked(tmp_path):
    _dash(tmp_path)
    assert safe_get_target(tmp_path, "/../task/task.md") is None
    assert safe_get_target(tmp_path, "/task/task.md") is None
    assert safe_get_target(tmp_path, "/predictions/round_001.md") is None


def test_status_json_allowed(tmp_path):
    _dash(tmp_path)
    (tmp_path / "status.json").write_text("{}", encoding="utf-8")
    assert safe_get_target(tmp_path, "/status.json") is not None


def test_origin_csrf_guard():
    assert origin_ok(None)                          # curl / no browser
    assert origin_ok("http://127.0.0.1:8765")
    assert origin_ok("http://localhost:8765")
    assert not origin_ok("http://evil.example.com")
    assert not origin_ok("https://attacker.test")


def test_reverse_channel_assert():
    assert_reverse_channel_clean("빌드가 느려서 어디부터 봐야 할지 모르겠습니다")  # clean
    with pytest.raises(IntegrityBreach):
        assert_reverse_channel_clean("여기 보세요:\n```python\nimport os\n```")
    with pytest.raises(IntegrityBreach):
        assert_reverse_channel_clean("src/friday/cli.py 를 고치면 됩니다")
