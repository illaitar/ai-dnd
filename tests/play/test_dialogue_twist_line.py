"""The giver's next conversation line must voice the stashed twist reveal (quests/twist.py
giver_next_line) — grounded via _voice(twist_line=...), spoken once then popped from the contract."""

import asyncio
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import dialogue as dlg_mod
from aidnd.worldgen import WorldStore

REVEAL = "Ральф сам должен гильдии — его можно прижать."


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _CaptureStub:
    def __init__(self):
        self.calls = []

    def call(self, role, messages, **kw):
        self.calls.append(messages)
        return {"content": '{"say": "Постой, есть новость.", "player_tone": "neutral"}'}


def _npc(name="Дунн", role="торговец"):
    st = NpcState.from_config(NpcConfig(id="npc:dunn", name=name, role=role))
    return SimpleNamespace(
        id="npc:dunn", name=name, role=role, state=st, persona={}, portraits={}, work=None,
        keys=[],
    )


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    saved = dict(core._S._d())
    d = core._S._d()
    try:
        d.clear()
        d["wid"] = 1
        d["gt"] = 600
        d["city_name"] = "Городок"
        yield st
    finally:
        d.clear()
        d.update(saved)


def _wire_dialogue(monkeypatch, npc_obj):
    people = {"npc:dunn": npc_obj}
    crof = {"npc:dunn": "loc:square"}
    monkeypatch.setattr(dlg_mod, "_play", lambda: (None, people, crof, None, "loc:square"))
    core._S["people"] = people


def _twisted_ct(st):
    st.save_contract(
        1, "ct:sift:npc:dunn:1", "active",
        {"giver": "npc:dunn", "giver_name": "Дунн", "src": "sift",
         "arc": {"beat": "twisted"}, "done_any": [{"type": "have", "item": "гроссбух"},
                                                   {"type": "dead", "id": "npc:ralf"}],
         "giver_next_line": REVEAL},
    )


def test_talk_grounds_voice_in_the_twist_reveal_and_pops_it_once(wired, monkeypatch):
    st = wired
    _twisted_ct(st)
    npc_obj = _npc()
    _wire_dialogue(monkeypatch, npc_obj)
    stub = _CaptureStub()
    monkeypatch.setattr(core, "_model", lambda: stub)

    res = asyncio.run(dlg_mod.talk(_Req({"npc": "npc:dunn"})))

    assert res["twist_line"] == REVEAL
    assert stub.calls, "narrator LLM was never invoked"
    sys_content = stub.calls[-1][0]["content"]
    assert REVEAL in sys_content

    ct = st.contracts(1, "active")[0]
    assert "giver_next_line" not in ct                 # spoken once — popped

    # second talk() — nothing left to voice, no crash, no repeat
    stub.calls.clear()
    res2 = asyncio.run(dlg_mod.talk(_Req({"npc": "npc:dunn"})))
    assert res2["twist_line"] is None
