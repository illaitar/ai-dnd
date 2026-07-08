# bench.trace composes the three already-built bench/ pieces (harness/snapshot/llmtap) into one
# per-turn record and a streaming JSONL writer. `look` is one of harness._GET_ROUTES and the play
# observe handler — it never touches the LLM, so this test drives a real bench_world() turn
# without needing a live model (docs no-LLM-fallback: unit tests must not require one).
import json

from bench.trace import TraceWriter, record_turn

from bench.harness import bench_world


def test_record_turn_captures_all_four_faces():
    with bench_world(seed=7) as h:
        rec = record_turn(h, "look")

    assert rec["input"] == {"endpoint": "look", "params": {}}
    assert rec["frontend"] == rec["frontend"]  # sanity: JSON-decoded response body present
    assert isinstance(rec["frontend"], dict)
    assert rec["backend"]["economy"]["money_supply"] > 0
    assert rec["llm"] == []  # look never calls the model
    assert "turn" in rec


def test_trace_writer_round_trips_one_line(tmp_path):
    path = tmp_path / "trace.jsonl"
    writer = TraceWriter(path)
    try:
        writer.append({"turn": 0, "input": {"endpoint": "look", "params": {}},
                        "frontend": {"ok": True}, "backend": {"economy": {"money_supply": 1}},
                        "llm": []})
    finally:
        writer.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    decoded = json.loads(lines[0])
    assert decoded["turn"] == 0
    assert decoded["frontend"] == {"ok": True}


def test_trace_writer_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "trace.jsonl"
    writer = TraceWriter(path)
    writer.append({"turn": 0})
    writer.close()

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0]) == {"turn": 0}
