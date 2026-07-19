from friday.bandwidth_filter import apply_filter  # noqa: E402


def test_intent_field_always_blocked():
    kept, dropped = apply_filter(
        {"action_taken": "명령 실행", "where_stuck": "에러 발생",
         "intent": "매출 데이터를 분석하려는 것"}, level=2)
    assert "intent" not in kept
    assert any("매출 데이터" in d for d in dropped)


def test_expected_only_level2():
    rep = {"action_taken": "실행", "where_stuck": "", "expected": "합계가 나올 줄 알았다"}
    kept1, dropped1 = apply_filter(rep, level=1)
    assert "expected" not in kept1 and any("합계" in d for d in dropped1)
    kept2, dropped2 = apply_filter(rep, level=2)
    assert "합계" in kept2["expected"] and not dropped2


def test_intent_sentence_dropped_from_allowed_field():
    kept, dropped = apply_filter(
        {"action_taken": "csv 파일을 넣고 질문했다. 매출 추이를 보기 위해 월별 질문을 했다.",
         "where_stuck": "두 번째 질문에서 멈췄다."}, level=1)
    assert "위해" not in kept["action_taken"]
    assert "질문했다" in kept["action_taken"]
    assert any("위해" in d for d in dropped)


def test_english_intent_dropped():
    kept, dropped = apply_filter(
        {"action_taken": "Ran the tool. I did this in order to analyze sales.",
         "where_stuck": ""}, level=1)
    assert "in order to" not in kept["action_taken"]
    assert len(dropped) == 1


def test_metadata_passthrough():
    kept, _ = apply_filter({"where_stuck": "x", "deviation": True, "round": 3}, level=1)
    assert kept["deviation"] is True and kept["round"] == 3


def test_clean_report_passes_untouched():
    rep = {"action_taken": "python tool.py data.csv 실행", "where_stuck": "인코딩 에러로 정지"}
    kept, dropped = apply_filter(rep, level=1)
    assert kept["action_taken"] == rep["action_taken"]
    assert kept["where_stuck"] == rep["where_stuck"]
    assert dropped == []
