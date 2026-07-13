"""j_beat: code-built facts → ONE narrator call → one kind='quest' prov=<beat> refs=[cid] row.
BEST-EFFORT: LLMUnavailable / empty output → NO row and NO exception (quest already committed)."""
import pytest

from aidnd.inference.client import LLMUnavailable
from aidnd.server.play.engine import core
from aidnd.server.play.engine.journal import j_beat
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _StubOK:
    def __init__(self, line="Я взялся за это дело."):
        self.line = line
        self.calls = []

    def call(self, role, messages, **kw):
        self.calls.append((role, messages, kw))
        return {"content": self.line}


class _StubDown:
    def call(self, role, messages, **kw):
        raise LLMUnavailable("no model")


class _StubEmpty:
    def call(self, role, messages, **kw):
        return {"content": "   "}


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=21360)
        yield st
    finally:
        d.clear(); d.update(saved)


def _quest_rows(st):
    return [r for r in st.journal_list(1, kind="quest")]


def test_beat_writes_one_quest_row(store, monkeypatch):
    stub = _StubOK("Я взялся добыть для Розы мешочек с медяками.")
    monkeypatch.setattr(core, "_model", lambda: stub)
    j_beat("ct:sift:p_roza:20880", "accept",
           {"kind": "bring", "want": "мешочек с медяками", "where": "сундук (лавка Розы)",
            "reward": 8, "giver_name": "Роза Медовар"})
    rows = _quest_rows(store)
    assert len(rows) == 1
    assert rows[0]["kind"] == "quest"
    assert rows[0]["prov"] == "accept"                       # beat rides prov column
    assert rows[0]["refs"] == ["ct:sift:p_roza:20880"]
    assert rows[0]["gt"] == 21360
    assert rows[0]["text"] == "Я взялся добыть для Розы мешочек с медяками."


def test_facts_reach_the_narrator_prompt(store, monkeypatch):
    stub = _StubOK()
    monkeypatch.setattr(core, "_model", lambda: stub)
    j_beat("c1", "offer",
           {"giver_name": "Роза Медовар", "giver_role": "лавочник",
            "appearance": "в переднике, руки в муке", "pitch": "Сбегай к сундуку за медяками."})
    role, messages, kw = stub.calls[-1]
    assert role == "narrator"
    assert kw.get("options", {}).get("temperature") == 0.4    # local literal, low for faithful wording
    user = messages[-1]["content"]
    assert "Роза Медовар" in user and "в переднике" in user and "Сбегай к сундуку" in user


def test_llm_down_writes_no_row_and_does_not_raise(store, monkeypatch):
    monkeypatch.setattr(core, "_model", lambda: _StubDown())
    j_beat("c1", "accept", {"giver_name": "Роза Медовар"})    # must NOT raise
    assert _quest_rows(store) == []


def test_empty_output_writes_no_row(store, monkeypatch):
    monkeypatch.setattr(core, "_model", lambda: _StubEmpty())
    j_beat("c1", "done", {"giver_name": "Роза", "what": "мешочек", "kind": "bring"})
    assert _quest_rows(store) == []


def test_multiparagraph_line_is_clamped_to_one_short_phrase(store, monkeypatch):
    no_punct_run = "слово за слово " * 20                     # long single "sentence", no . ! ?
    stub = _StubOK(f"{no_punct_run}\nВторой абзац тут, он вообще не должен попасть в строку.")
    monkeypatch.setattr(core, "_model", lambda: stub)
    j_beat("c1", "accept", {"giver_name": "Роза Медовар"})
    rows = _quest_rows(store)
    assert len(rows) == 1
    text = rows[0]["text"]
    assert "\n" not in text and "Второй абзац" not in text
    assert len(text) <= 200
    assert not text.endswith(" ")                              # clean word boundary, not mid-word cut


class _StubNonDict:
    def call(self, role, messages, **kw):
        return "просто строка, не словарь"


def test_non_dict_response_writes_no_row_and_does_not_raise(store, monkeypatch):
    monkeypatch.setattr(core, "_model", lambda: _StubNonDict())
    j_beat("c1", "accept", {"giver_name": "Роза Медовар"})    # must NOT raise
    assert _quest_rows(store) == []


def test_no_session_is_a_safe_noop(monkeypatch):
    # no wid/store bound → best-effort no-op, never raises
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        j_beat("c1", "accept", {"giver_name": "X"})
    finally:
        d.clear(); d.update(saved)
