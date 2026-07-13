"""Playtest bug: /act inside a dungeon fell through to the OUTSIDE-scene arbiter (_play/
_scene_dict/resolve), which knows nothing about being underground — after POST /delve, freeform
/act narrated tavern people inside an empty cellar (context bleed). No freeform-inside-dungeon
path exists yet, so the /act entrypoint must refuse honestly instead, without ever reaching the
narrator/model. A live combat inside the dungeon must still fall through unaffected (existing
combat-in-dungeon handling is untouched by this guard)."""
from __future__ import annotations

import asyncio

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.handlers import freeform


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _Stub:
    """Anything the guard must short-circuit before reaching: _play(), resolve(), the model."""
    def __init__(self):
        self.called = False

    def call(self, *a, **k):
        self.called = True
        return {"content": "не должно быть вызвано"}

    def __call__(self, *a, **k):
        self.called = True
        raise AssertionError("must not be called when a dungeon is active")


@pytest.fixture
def dungeon_active(monkeypatch):
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=100, dungeon={"room": 0, "d": {"name": "Тест-подвал"}})
        yield
    finally:
        d.clear(); d.update(saved)


def test_act_in_dungeon_refuses_without_model_call(dungeon_active, monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    monkeypatch.setattr(freeform, "_play", stub, raising=False)
    res = asyncio.run(freeform.act(_Req({"text": "оглядываюсь по сторонам"})))
    assert res.get("fail") is True
    assert not stub.called
    assert "подземель" in " ".join(res["narr"])


def test_act_in_dungeon_combat_falls_through(monkeypatch):
    """A live encounter inside the dungeon is a normal combat contour — the guard must not
    swallow it; /act still reaches the ordinary combat-already-in-progress narration."""
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=100, dungeon={"room": 0, "d": {"name": "Тест-подвал"}},
                 combat={"enc": None})
        monkeypatch.setattr(freeform, "_play", lambda: (None, {}, {}, {}, "loc:x"))
        monkeypatch.setattr(freeform, "_scene_dict", lambda *a, **k: {})

        def _resolve(text, sc):
            return {"verb": "wait"}

        monkeypatch.setattr(freeform, "resolve", _resolve)
        monkeypatch.setattr(freeform, "_pc_remember", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(freeform, "_world_tick_fast", lambda: {"feed": [], "address": []})
        monkeypatch.setattr(freeform, "_pc_coins", lambda: 0, raising=False)
        monkeypatch.setattr(freeform, "_pc_hp", lambda: 10, raising=False)
        res = asyncio.run(freeform.act(_Req({"text": "бью врага"})))
        assert res.get("combat") is True
        assert "Бой уже идёт" in " ".join(res["narr"])
    finally:
        d.clear(); d.update(saved)


def test_act_without_dungeon_unaffected(monkeypatch):
    """Baseline: with no dungeon active, /act proceeds to the normal outside-world path."""
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=100)
        monkeypatch.setattr(freeform, "_play", lambda: (None, {}, {}, {}, "loc:x"))
        monkeypatch.setattr(freeform, "_scene_dict", lambda *a, **k: {})

        def _resolve(text, sc):
            return None

        monkeypatch.setattr(freeform, "resolve", _resolve)
        res = asyncio.run(freeform.act(_Req({"text": "что-то делаю"})))
        assert "не понял" in " ".join(res["narr"])
    finally:
        d.clear(); d.update(saved)
