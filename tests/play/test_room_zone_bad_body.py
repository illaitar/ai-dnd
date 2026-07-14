"""Playtest bug (2026-07-14-grand2.md): POST /api/play/room and /api/play/zone raised an
unhandled exception (→ 500) when the request body was empty or malformed — instead of an
honest {"error": ...} reply like their sibling endpoints. Now a body that fails to parse as
JSON is caught and answered the same way other handlers refuse bad input."""
from __future__ import annotations

import asyncio

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.handlers import travel


class _RaisingReq:
    """Stand-in for a Request whose .json() blows up (empty body / bad content-type / not JSON)."""

    async def json(self):
        raise ValueError("empty or malformed body")


@pytest.fixture
def inside_building(monkeypatch):
    """Minimal state so go_room()/play_zone() get past their early guards and reach body parsing."""
    from aidnd.server.play.engine.session import persist
    from aidnd.worldgen import WorldStore

    st = WorldStore(":memory:")
    monkeypatch.setattr(persist, "_STORE", st)
    city, people, crof, cr2b, loc = object(), {}, {}, {}, 50
    monkeypatch.setattr(travel, "_play", lambda: (city, people, crof, cr2b, loc))
    monkeypatch.setattr(travel, "_building_rooms", lambda bid: [])
    d = core._S._d()
    saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=514, loc=loc, inside="key:1")
        yield
    finally:
        d.clear()
        d.update(saved)


def test_go_room_bad_body_returns_honest_error_not_500(inside_building):
    res = asyncio.run(travel.go_room(_RaisingReq()))
    assert res == {"error": "нужно тело запроса"}


def test_play_zone_bad_body_returns_honest_error_not_500(inside_building):
    res = asyncio.run(travel.play_zone(_RaisingReq()))
    assert res == {"error": "нужно тело запроса"}
