from friday.bus import Event, EventLog


def test_append_replay_roundtrip(tmp_path):
    log = EventLog(tmp_path)
    log.append(Event("round_done", "T1", {"round": 1}))
    log.append(Event("cycle_status", "T2", {"status": "running"}))
    evs = list(log.replay())
    assert [e.kind for e in evs] == ["round_done", "cycle_status"]
    assert evs[0].payload["round"] == 1
    assert evs[1].payload["status"] == "running"


def test_tail_incremental(tmp_path):
    log = EventLog(tmp_path)
    log.append(Event("a"))
    evs, cursor = log.tail(0)
    assert [e.kind for e in evs] == ["a"]
    log.append(Event("b"))
    evs2, cursor2 = log.tail(cursor)
    assert [e.kind for e in evs2] == ["b"]
    assert cursor2 == 2


def test_tail_empty(tmp_path):
    log = EventLog(tmp_path)
    evs, cursor = log.tail(0)
    assert evs == [] and cursor == 0


def test_unicode_preserved(tmp_path):
    log = EventLog(tmp_path)
    log.append(Event("notify", "T", {"msg": "라운드 완료"}))
    assert list(log.replay())[0].payload["msg"] == "라운드 완료"
