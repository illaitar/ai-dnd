"""Review fix (f719d99 findings, Inc3 transit walkers) — interaction/render surfaces must use
_here_settled, not the transit-aware _here: a street walker mid-transit is pass-through feed only
(see world.py's "проходит мимо" line, and test_transit.py's docstring), never a scene card or a
talk target. Witness-type consumers (crime/combat/magic witnesses) keep transit-aware _here on
purpose and are not touched here — a passer-by can still SEE a crime."""

import asyncio
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.scene import view as view_mod
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import dialogue as dlg_mod
from aidnd.worldgen import WorldStore

LOC = "loc:47"           # scene node the player stands on
ORIGIN = "loc:12"        # walker's transit origin (not the scene node)


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


def _npc(pid, name, role="горожанин"):
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
        d["gt"] = 21361                 # mid-hop: derived transit node == LOC (see path below)
        d["city_name"] = "Городок"
        d["geom"] = {"plaza": LOC}       # short-circuits _scene_locinfo without a real City object
        d["inside"] = None
        d["room"] = None
        d["looked"] = {}
        yield st
    finally:
        d.clear()
        d.update(saved)


def _scene_and_transit_fixture():
    """A settled NPC actually AT the scene node, plus a transit walker whose derived position
    (at gt=21361, path from ORIGIN through LOC) passes through the scene node without being
    settled there — the walker's crof entry stays at ORIGIN until arrival."""
    settled = _npc("npc:anna", "Анна")
    walker = _npc("npc:mara", "Мара")
    people = {"npc:anna": settled, "npc:mara": walker}
    crof = {"npc:anna": LOC, "npc:mara": ORIGIN}
    core._S["people"] = people
    core._S["crof"] = crof
    core._S["transit"] = {
        "npc:mara": {
            "from": ORIGIN, "to": "loc:99", "depart_gt": 21360, "arrive_gt": 21400,
            "path": [ORIGIN, LOC, "loc:99"],
        },
    }
    return people, crof


def test_transit_walker_still_derives_through_the_scene_node():
    """Sanity check on the fixture itself (not the fix): _here (transit-aware) DOES see the walker
    passing through — confirms the fixture reproduces the pre-fix condition faithfully."""
    saved, d = dict(core._S._d()), core._S._d()
    try:
        d.clear()
        d["gt"] = 21361
        people, crof = _scene_and_transit_fixture()
        assert "npc:mara" in core._here(LOC, crof)             # transit-aware sees the walker
        assert "npc:mara" not in core._here_settled(LOC, crof)  # settled-view does not
    finally:
        d.clear(); d.update(saved)


def test_scene_dict_excludes_transit_walker_but_keeps_settled_npc(wired):
    people, crof = _scene_and_transit_fixture()
    d = view_mod._scene_dict(None, people, crof, {}, LOC)
    ids = {c["id"] for c in d["here"]}
    assert "npc:anna" in ids     # settled occupant — a real scene card
    assert "npc:mara" not in ids  # transit walker — pass-through only, not a card


def test_talk_to_transit_walker_is_absent(wired, monkeypatch):
    people, crof = _scene_and_transit_fixture()
    monkeypatch.setattr(dlg_mod, "_play", lambda: (None, people, crof, None, LOC))

    res = asyncio.run(dlg_mod.talk(_Req({"npc": "npc:mara"})))

    assert res == {"error": "его здесь нет — говорить можно с тем, кто рядом"}


def test_talk_to_settled_npc_at_same_node_is_not_rejected_for_absence(wired, monkeypatch):
    people, crof = _scene_and_transit_fixture()
    monkeypatch.setattr(dlg_mod, "_play", lambda: (None, people, crof, None, LOC))
    monkeypatch.setattr(core, "_model", lambda: SimpleNamespace(
        call=lambda role, messages, **kw: {"content": '{"say": "Здравствуй.", "player_tone": "neutral"}'}
    ))

    res = asyncio.run(dlg_mod.talk(_Req({"npc": "npc:anna"})))

    assert res.get("error") != "его здесь нет — говорить можно с тем, кто рядом"
