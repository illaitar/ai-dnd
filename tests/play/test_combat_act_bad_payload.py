"""Playtest bug: POST /api/play/combat_act with a payload that doesn't match any known action
(bad "type", or missing/typo'd fields) used to be silently ignored — the AI turn loop would just
spin and hand the turn back with no feedback. Now an unrecognized action returns {"error": <hint
naming the accepted actions>, "combat": <current view>} instead of silently doing nothing."""

from __future__ import annotations

import asyncio

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.mechanics import combat as combat_mod


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _Combatant:
    def __init__(self, cid):
        self.id = cid

    def incapacitated(self):
        return False


class _FakeEncounter:
    """Only the surface combat_act touches: current()/status()/view(); no foes, no AI turns."""

    def __init__(self):
        self._cur = _Combatant("pc")

    def current(self):
        return self._cur

    def status(self):
        return "active"

    def foes_cleared(self):
        return False

    def view(self):
        return {"status": "active"}

    def end_turn(self):
        pass


@pytest.fixture
def in_combat(monkeypatch):
    d = core._S._d()
    saved = dict(d)
    enc = _FakeEncounter()
    d.clear()
    d["combat"] = {"enc": enc, "npc": "npc:dunn", "loc": "loc:x", "head": {}}
    monkeypatch.setattr(combat_mod, "_gt", lambda: 514, raising=False)
    monkeypatch.setattr(combat_mod, "_pc_hp", lambda **k: 10, raising=False)
    try:
        yield enc
    finally:
        d.clear()
        d.update(saved)


def test_unknown_action_type_returns_error_naming_accepted_actions(in_combat):
    res = asyncio.run(combat_mod.combat_act(_Req({"type": "juggle"})))
    assert "error" in res
    for kw in ("move", "attack", "dodge", "flee", "end"):
        assert kw in res["error"]
    assert "combat" in res


def test_missing_type_field_returns_error(in_combat):
    res = asyncio.run(combat_mod.combat_act(_Req({})))
    assert "error" in res
    assert "combat" in res
