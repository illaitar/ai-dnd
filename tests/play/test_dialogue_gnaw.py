"""FIX 3: the giver's live sift errand must show up on the CARD (talk()/npc() response), not just
folded silently into the mind-prompt (foreshadow.open_lines, Fix D). Severe playtest bug: the card
showed nothing but 'спокойное' — zero visible signal the NPC is a live quest giver."""

import asyncio
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import dialogue as dlg_mod
from aidnd.worldgen import WorldStore

FORESHADOW = "Тебя гложет долг — гроссбух у Ральфа."
PITCH = "Верни мне гроссбух, чужак, и получишь награду."


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _CaptureStub:
    def call(self, role, messages, **kw):
        return {"content": '{"say": "Здравствуй, чужак.", "player_tone": "neutral"}'}


def _npc(pid="npc:dunn", name="Дунн", role="торговец"):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(
        id=pid, name=name, role=role, state=st, persona={}, portraits={}, work=None, keys=[],
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
        monkeypatch.setattr(core, "_model", lambda: _CaptureStub())
        yield st
    finally:
        d.clear()
        d.update(saved)


def _wire_dialogue(monkeypatch, *npc_objs):
    people = {n.id: n for n in npc_objs}
    crof = {n.id: "loc:square" for n in npc_objs}
    monkeypatch.setattr(dlg_mod, "_play", lambda: (None, people, crof, None, "loc:square"))
    core._S["people"] = people


def _sift_ct(st, status, beat, giver="npc:dunn", **extra):
    data = {"giver": giver, "giver_name": "Дунн", "src": "sift",
            "arc": {"beat": beat}, "framer": {"foreshadow": FORESHADOW}, "pitch": PITCH,
            "done_any": [{"type": "have", "item": "гроссбух"}]}
    data.update(extra)
    st.save_contract(1, f"ct:sift:{giver}:1", status, data)


@pytest.mark.parametrize("status,beat", [("queued", "foreshadow"), ("offered", "offered"),
                                          ("active", "active")])
def test_talk_shows_gnaw_for_live_giver(wired, monkeypatch, status, beat):
    st = wired
    _sift_ct(st, status, beat)
    npc_obj = _npc()
    _wire_dialogue(monkeypatch, npc_obj)

    res = asyncio.run(dlg_mod.talk(_Req({"npc": "npc:dunn"})))

    assert res["gnaw"] == "Тебя гложет долг — гроссбух у Ральфа"   # foreshadow line, first clause


def test_talk_gnaw_falls_back_to_pitch_first_clause_when_no_foreshadow(wired, monkeypatch):
    st = wired
    _sift_ct(st, "active", "active", **{"framer": {}})
    npc_obj = _npc()
    _wire_dialogue(monkeypatch, npc_obj)

    res = asyncio.run(dlg_mod.talk(_Req({"npc": "npc:dunn"})))

    assert res["gnaw"] == "Верни мне гроссбух"                     # pitch's first clause (comma-split)


def test_talk_no_gnaw_for_non_giver_npc(wired, monkeypatch):
    st = wired
    _sift_ct(st, "active", "active", giver="npc:dunn")
    other = _npc(pid="npc:other", name="Марта", role="швея")
    _wire_dialogue(monkeypatch, other)

    res = asyncio.run(dlg_mod.talk(_Req({"npc": "npc:other"})))

    assert res.get("gnaw") is None


def test_talk_no_gnaw_when_arc_closed(wired, monkeypatch):
    st = wired
    _sift_ct(st, "active", "closed")
    npc_obj = _npc()
    _wire_dialogue(monkeypatch, npc_obj)

    res = asyncio.run(dlg_mod.talk(_Req({"npc": "npc:dunn"})))

    assert res.get("gnaw") is None


def test_npc_card_shows_gnaw_too(wired, monkeypatch):
    st = wired
    _sift_ct(st, "offered", "offered")
    npc_obj = _npc()
    _wire_dialogue(monkeypatch, npc_obj)

    res = asyncio.run(dlg_mod.npc_card(_Req({"npc": "npc:dunn"})))

    assert res["gnaw"] == "Тебя гложет долг — гроссбух у Ральфа"
