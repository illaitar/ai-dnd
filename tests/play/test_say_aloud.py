"""Playtester bug: POST /api/play/say with no `npc` used to bounce with {"error": "нет такого"} —
but the game has a designed speak-aloud path (freeform's non-verb fallback: pc_said/pc_spoke feed
the world tick so the room hears the player). say() now routes the no-addressee case through that
same _say_aloud() helper (shared with handlers/freeform.py's /act fallback) instead of erroring.
When an npc IS given but unknown, the error stays but gets a clearer message."""

import asyncio

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.pc import hero as hero_mod
from aidnd.server.play.handlers import dialogue as dlg_mod
from aidnd.server.play.handlers import freeform as ff_mod
from aidnd.worldgen import WorldStore


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _Stub:
    """Fake narrator manager — mirrors tests/play/test_quest_judge.py's `_Stub`."""

    def __init__(self, content):
        self.content = content
        self.seen = None

    def call(self, role, messages, **kw):
        self.seen = messages
        return {"content": self.content}


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    for mod in (core, dlg_mod, hero_mod):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(dlg_mod, "_play", lambda: (None, {}, None, None, None), raising=False)
    monkeypatch.setattr(dlg_mod, "_scene_dict", lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(dlg_mod, "_world_tick", lambda: {"feed": [], "address": []}, raising=False)
    monkeypatch.setattr(core, "_gt", lambda: 514, raising=False)
    d = core._S._d()
    saved = dict(d)                    # snapshot the shared world-1 session blob...
    try:
        d.clear()
        d["wid"] = 1
        d["gt"] = 514
        d["live"] = {}                 # scene present — the aloud path writes pc_said/pc_spoke here
        yield st
    finally:
        d.clear()
        d.update(saved)                # ...and restore it so later tests keep their 'seed' etc.


def test_say_without_npc_speaks_aloud_to_the_room(wired, monkeypatch):
    monkeypatch.setattr(ff_mod, "_model", lambda: _Stub("Зал на миг притих."), raising=False)
    r = asyncio.run(dlg_mod.say(_Req({"text": "Есть тут кто живой?"})))
    assert "error" not in r
    lv = core._S.get("live")
    assert lv["pc_said"] == "Есть тут кто живой?"
    assert lv["pc_spoke"] is True
    assert r["narr"] == ["Зал на миг притих."]


def test_say_unknown_npc_returns_clearer_error(wired):
    r = asyncio.run(dlg_mod.say(_Req({"npc": "npc:nobody", "text": "эй!"})))
    assert r == {"error": "нет такого — рядом никого с таким именем"}
