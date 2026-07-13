"""_voice injects geo_line into the system prompt as fixed facts the voice may wrap but not alter."""
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.narrator import voice as V
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Capture:
    def __init__(self):
        self.calls = []

    def call(self, role, messages, **kw):
        self.calls.append(messages)
        return {"content": '{"say": "Ступай к кузнице.", "player_tone": "neutral"}'}


def _npc():
    st = NpcState.from_config(NpcConfig(id="npc:oda", name="Ода Вент", role="лавочница"))
    return SimpleNamespace(id="npc:oda", name="Ода Вент", role="лавочница", state=st,
                           persona={}, portraits={}, work=None, keys=[])


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=600, city_name="Городок")
        yield
    finally:
        d.clear(); d.update(saved)


def test_geo_line_injected(wired, monkeypatch):
    stub = _Capture()
    monkeypatch.setattr(core, "_model", lambda: stub)
    dline = "минут пять ходу к северу, за рыночной площадью"
    line = V._voice(_npc(), {"affinity": 0.2}, "reply", "где кузница?",
                    geo_line=f"ты знаешь место кузница: {dline} — посоветуй дорогу")
    assert line == "Ступай к кузнице."
    sys = stub.calls[-1][0]["content"]
    assert dline in sys


def test_no_geo_line_leaves_prompt_clean(wired, monkeypatch):
    stub = _Capture()
    monkeypatch.setattr(core, "_model", lambda: stub)
    V._voice(_npc(), {"affinity": 0.2}, "reply", "как дела?")
    sys = stub.calls[-1][0]["content"]
    assert "посоветуй дорогу" not in sys


def test_price_line_injected(wired, monkeypatch):
    stub = _Capture()
    monkeypatch.setattr(core, "_model", lambda: stub)
    pline = "ночлег: 2 зм за ночь"
    line = V._voice(_npc(), {"affinity": 0.2}, "reply", "сколько стоит ночлег?",
                    price_line=pline)
    assert line == "Ступай к кузнице."
    sys = stub.calls[-1][0]["content"]
    assert "ЦЕНЫ (это ИСТИНА от кода" in sys
    assert pline in sys


def test_no_price_line_leaves_prompt_clean(wired, monkeypatch):
    stub = _Capture()
    monkeypatch.setattr(core, "_model", lambda: stub)
    V._voice(_npc(), {"affinity": 0.2}, "reply", "как дела?")
    sys = stub.calls[-1][0]["content"]
    assert "ЦЕНЫ (это ИСТИНА от кода" not in sys
