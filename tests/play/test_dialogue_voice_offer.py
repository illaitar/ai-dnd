"""The giver's spoken voice must reference her own emergent offer (live-playtest bug: her
/talk /say lines improvised a DIFFERENT task because the dialogue voice LLM never saw the
pending emergent contract's pitch). say() must ground _voice()'s prompt in the REAL pitch."""

import asyncio
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import dialogue as dlg_mod
from aidnd.worldgen import WorldStore

PITCH = "накопить на долг кузнецу за починку кадила"


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _CaptureStub:
    """Stand-in ModelManager.call — captures the messages sent to the narrator LLM."""

    def __init__(self):
        self.calls = []

    def call(self, role, messages, **kw):
        self.calls.append(messages)
        return {"content": '{"say": "Здравствуй, путник.", "player_tone": "neutral"}'}


def _npc(name="Юна Вересковый", role="жрица"):
    st = NpcState.from_config(NpcConfig(id="npc:yuna", name=name, role=role))
    return SimpleNamespace(
        id="npc:yuna", name=name, role=role, state=st, persona={}, portraits={}, work=None,
        keys=[],
    )


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)             # root-patch store used by offer.py etc
    saved = dict(core._S._d())
    d = core._S._d()
    try:
        d.clear()
        d["wid"] = 1
        d["gt"] = 600
        d["city_name"] = "Городок"                         # skip _city_name() store round-trip
        yield st
    finally:
        d.clear()
        d.update(saved)


def _wire_dialogue(monkeypatch, npc_obj):
    """Stub the heavy plumbing around say()/talk() so only the voice-prompt wiring is exercised."""
    people = {"npc:yuna": npc_obj}
    crof = {"npc:yuna": "loc:square"}
    monkeypatch.setattr(dlg_mod, "_play", lambda: (None, people, crof, None, "loc:square"))
    monkeypatch.setattr(dlg_mod, "_contract_on_talk", lambda npc: None)
    monkeypatch.setattr(dlg_mod, "_world_tick_fast", lambda: {})
    monkeypatch.setattr(dlg_mod, "_pc_coins", lambda: 0)
    core._S["people"] = people


def _sift_contract(st):
    st.save_contract(
        1, "ct:sift:npc:yuna:1", "offered",
        {"giver": "npc:yuna", "giver_name": "Юна Вересковый", "kind": "wealth", "src": "sift",
         "pitch": PITCH, "reward": 12, "arc": {"beat": "offered"}},
    )


def test_say_grounds_voice_in_the_real_emergent_pitch(wired, monkeypatch):
    # regression: say() used to call _voice() with NO offer context at all, so the LLM
    # improvised an unrelated task instead of speaking to Юна's actual sift pitch.
    st = wired
    _sift_contract(st)
    npc_obj = _npc()
    _wire_dialogue(monkeypatch, npc_obj)
    stub = _CaptureStub()
    monkeypatch.setattr(core, "_model", lambda: stub)

    res = asyncio.run(dlg_mod.say(_Req({"npc": "npc:yuna", "text": "Как дела?"})))

    assert res["line"] == "Здравствуй, путник."
    assert stub.calls, "narrator LLM was never invoked"
    sys_content = stub.calls[-1][0]["content"]
    assert PITCH in sys_content


def test_talk_greeting_hint_also_grounded_in_the_real_pitch(wired, monkeypatch):
    st = wired
    _sift_contract(st)
    npc_obj = _npc()
    _wire_dialogue(monkeypatch, npc_obj)
    stub = _CaptureStub()
    monkeypatch.setattr(core, "_model", lambda: stub)

    asyncio.run(dlg_mod.talk(_Req({"npc": "npc:yuna"})))

    assert stub.calls, "narrator LLM was never invoked"
    sys_content = stub.calls[-1][0]["content"]
    assert PITCH in sys_content


def _active_sift_contract(st):
    """A sift quest the giver has ALREADY accepted (status 'active') — emergent_offer() returns None
    for it, so before FIX C the giver's voice forgot his own quest and improvised unrelated tasks."""
    st.save_contract(
        1, "ct:sift:npc:yuna:2", "active",
        {"giver": "npc:yuna", "giver_name": "Юна Вересковый", "kind": "wealth", "src": "sift",
         "pitch": PITCH, "reward": 12, "arc": {"beat": "active"}},
    )


def test_say_grounds_voice_in_the_accepted_active_pitch(wired, monkeypatch):
    # FIX C: once a sift quest is ACTIVE the giver still keeps it in mind, framed as a deal in
    # progress ("он уже взялся помочь тебе с …") rather than a fresh request.
    st = wired
    _active_sift_contract(st)
    npc_obj = _npc()
    _wire_dialogue(monkeypatch, npc_obj)
    stub = _CaptureStub()
    monkeypatch.setattr(core, "_model", lambda: stub)

    asyncio.run(dlg_mod.say(_Req({"npc": "npc:yuna", "text": "Как дела?"})))

    assert stub.calls, "narrator LLM was never invoked"
    sys_content = stub.calls[-1][0]["content"]
    assert PITCH in sys_content
    assert "УЖЕ ВЗЯЛСЯ" in sys_content                     # framed as the accepted deal, not an offer


def test_talk_grounds_voice_in_the_accepted_active_pitch(wired, monkeypatch):
    st = wired
    _active_sift_contract(st)
    npc_obj = _npc()
    _wire_dialogue(monkeypatch, npc_obj)
    stub = _CaptureStub()
    monkeypatch.setattr(core, "_model", lambda: stub)

    asyncio.run(dlg_mod.talk(_Req({"npc": "npc:yuna"})))

    assert stub.calls, "narrator LLM was never invoked"
    sys_content = stub.calls[-1][0]["content"]
    assert PITCH in sys_content
    assert "УЖЕ ВЗЯЛСЯ" in sys_content
