import json

from muto.context import ContextManager


def test_context_compacts_old_reports_without_changing_files(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    paths = []
    for n in range(8):
        path = reports / f"round_{n:03d}.md"
        path.write_text("report:\n  action_taken: tried\n  where_stuck: " + "x" * 900,
                        encoding="utf-8")
        paths.append(path)
    originals = [p.read_text(encoding="utf-8") for p in paths]

    text, state = ContextManager(tmp_path, budget_chars=4000, recent_reports=2).build(paths)

    assert len(text) <= 4000
    assert state["reports_compacted"] > 0
    assert "COMPACTED EARLIER REPORTS" in text
    assert [p.read_text(encoding="utf-8") for p in paths] == originals
    assert json.loads((tmp_path / "context.json").read_text())["used_chars"] == len(text)


def test_context_keeps_small_history_verbatim(tmp_path):
    report = tmp_path / "round_001.md"
    report.write_text("small report", encoding="utf-8")
    text, state = ContextManager(tmp_path).build([report])
    assert text == "small report"
    assert state["reports_compacted"] == 0
