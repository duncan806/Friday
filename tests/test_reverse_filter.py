from friday.reverse_filter import reverse_filter


def test_strips_code_fence():
    kept, dropped = reverse_filter("설명입니다\n```python\nimport os\nx = 1\n```\n계속 진행")
    assert "import os" not in kept
    assert any("import os" in d for d in dropped)
    assert "설명입니다" in kept and "계속 진행" in kept


def test_strips_src_path():
    kept, dropped = reverse_filter("문제는 src/friday/cli.py 근처에서 난다")
    assert "src/friday/cli.py" not in kept
    assert dropped


def test_strips_file_path_token():
    kept, dropped = reverse_filter("orchestrator.py 를 보면 된다")
    assert "orchestrator.py" not in kept
    assert dropped


def test_strips_diff_lines():
    kept, dropped = reverse_filter("변경:\n+ added line\n- removed line\n끝")
    assert "added line" not in kept
    assert "끝" in kept


def test_empty():
    assert reverse_filter("") == ("", [])
