"""Regression: on a brand-new world, the very first-ever /talk with an NPC greeted the player
as an old acquaintance ("А, это ты... снова на Костяном Мосту") even though the two had NEVER
interacted. Root cause had two parts:

  1. mind/appraisal.py's appraise_present() treated the player's Body like any other NPC and
     silently seeded a ~0.2-0.3 relationship prior the moment an NPC's mind merely SAW the player
     in the scene (before any /talk) — fixed by threading skip_seed_id=player_id through so the
     player never gets an auto-seeded relationship from mere co-presence (tests/mind/test_appraisal.py
     covers this half).
  2. narrator/voice.py's greet prompt UNCONDITIONALLY told the LLM "Помнишь собеседника — покажи
     это естественно" (you remember the interlocutor, show it) regardless of whether any
     relationship/memory of the player actually existed — so even with (1) fixed, the LLM had no
     hard signal and could still invent a shared past. This file covers that half: the prompt must
     say «видишь ВПЕРВЫЕ» when no relationship row exists, and must NOT say that once a real
     relationship row exists (built by a genuine prior interaction).
"""

from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.narrator import voice as voice_mod
from aidnd.server.play.engine.session.config import PLAYER


class _CaptureStub:
    """Stand-in ModelManager.call — captures the messages sent to the narrator LLM."""

    def __init__(self):
        self.calls = []

    def call(self, role, messages, **kw):
        self.calls.append(messages)
        return {"content": '{"say": "...", "player_tone": "neutral"}'}


def _npc(name="Марья Ольхова", role="торговка"):
    st = NpcState.from_config(NpcConfig(id="npc:m", name=name, role=role))
    return SimpleNamespace(id="npc:m", name=name, role=role, state=st, persona={})


@pytest.fixture
def wired(monkeypatch):
    saved = dict(core._S._d())
    d = core._S._d()
    d.clear()
    d["wid"] = 1
    d["gt"] = 600
    d["city_name"] = "Городок"
    d["live"] = {}
    d["loc"] = "loc:square"
    try:
        yield
    finally:
        d.clear()
        d.update(saved)


def _stub_model(monkeypatch):
    monkeypatch.setattr(core, "_binfo", lambda bid: {"name": "площадь"})
    monkeypatch.setattr(core, "_city_name", lambda: "Городок")
    stub = _CaptureStub()
    monkeypatch.setattr(core, "_model", lambda: stub)
    return stub


def test_never_met_gets_first_contact_marker(wired, monkeypatch):
    npc_obj = _npc()
    assert PLAYER not in npc_obj.state.relationships   # fresh NPC — no row toward the player at all
    stub = _stub_model(monkeypatch)

    voice_mod._voice(npc_obj, {"affinity": 0.0}, "greet")

    sys_content = stub.calls[-1][0]["content"]
    assert "ВПЕРВЫЕ" in sys_content
    assert "Помнишь собеседника" not in sys_content


def test_existing_relationship_suppresses_first_contact_marker(wired, monkeypatch):
    npc_obj = _npc()
    # a genuine prior interaction already built a relationship row (e.g. contracts.py's
    # complete_favor(), combat.py, deals.py — NOT mere co-presence)
    npc_obj.state.relationships[PLAYER] = {"trust": 0.4, "affinity": 0.35, "fear": 0.0}
    stub = _stub_model(monkeypatch)

    voice_mod._voice(npc_obj, {"affinity": 0.35}, "greet")

    sys_content = stub.calls[-1][0]["content"]
    assert "ВПЕРВЫЕ" not in sys_content
