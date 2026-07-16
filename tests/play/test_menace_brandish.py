"""A drawn weapon aimed at NO ONE must still radiate fear to the room (playtest gap: «сталь со
свистом выходит из ножен» and not a single NPC reacted). Two layers:
  * `core._menace_affect` — fans a TARGETLESS МОЗГ Inc2 Event onto the co-present crowd, leaves a
    witness memory line, and touches NEITHER wanted points NOR karma (no victim, not a crime).
  * `freeform._attempt` — verb=="attack" with npc=None (a weapon drawn at no one) routes to
    `_brandish` instead of falling through to `_say_aloud` (which would narrate pure fiction with
    zero affect), and never opens combat (there's no foe to fight)."""

from __future__ import annotations

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.handlers import freeform


class _P:
    def __init__(self, name, pid, wv=None):
        self.name, self.role, self.work, self.persona = name, "завсегдатай", None, {}
        cfg = NpcConfig(id=pid, name=name, role="завсегдатай", worldview=wv or {})
        self.state = NpcState.from_config(cfg)


def test_menace_affect_scares_peasant_more_than_cutthroat(monkeypatch):
    monkeypatch.setattr(core, "_npc_save", lambda *a, **k: None, raising=False)
    peasant = _P("Селма", "npc:selma", {"morals": {"violence": -0.4}})
    cutthroat = _P("Мерек", "npc:merek", {"morals": {"violence": 0.9}})
    people = {"npc:selma": peasant, "npc:merek": cutthroat}

    n = core._menace_affect(people, ["npc:selma", "npc:merek"], "loc:x")

    assert n == 2
    assert peasant.state.emotion["fear"] > 0.1
    assert cutthroat.state.emotion["fear"] < peasant.state.emotion["fear"]
    assert any("обнажил оружие" in m.text for m in peasant.state.memory.items)


def test_menace_affect_is_not_a_crime(monkeypatch):
    """No victim → no wanted points, no karma stain."""
    monkeypatch.setattr(core, "_npc_save", lambda *a, **k: None, raising=False)
    before = core._wanted()
    peasant = _P("Селма", "npc:selma", {"morals": {"violence": -0.4}})
    people = {"npc:selma": peasant}

    core._menace_affect(people, ["npc:selma"], "loc:x")

    assert core._wanted() == before


@pytest.fixture
def world(tmp_path, monkeypatch):
    from aidnd.server.play.engine.session import persist
    from aidnd.worldgen import WorldStore

    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    for mod in (core, freeform):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(freeform, "_npc_save", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(freeform, "_pc_remember", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(freeform, "_materialize_npc", lambda *a, **k: None, raising=False)

    people = {"npc:dunn": _P("Горм", "npc:dunn", {"morals": {"violence": -0.4}})}
    crof = {"npc:dunn": "loc:x"}
    monkeypatch.setattr(freeform, "_play", lambda: (None, people, crof, {}, "loc:x"))

    d = core._S._d()
    saved = dict(d)
    try:
        d.clear()
        d["wid"] = 1
        d["gt"] = 514
        d["live"] = {}
        yield st, people
    finally:
        d.clear()
        d.update(saved)


def test_attack_with_no_target_brandishes_not_narrates(world, monkeypatch):
    """verb=="attack" with npc=None (weapon drawn at no one) must reach `_brandish`, NOT
    `_say_aloud` — narration must never be the only effect of a drawn blade."""
    st, people = world

    class _Stub:
        def __init__(self):
            self.called = False

        def call(self, *a, **k):
            self.called = True
            return {"content": "не должно вызываться"}

    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)

    res = freeform._attempt(
        {"verb": "attack", "npc": None, "_text": "обнажаю клинок прямо здесь"}, {}
    )

    assert not stub.called                                   # never fell through to narration
    assert res.get("combat") is None                          # no foe named → no duel
    assert core._S.get("combat") is None
    assert any("оружие" in ln or "клинок" in ln or "сталь" in ln.lower()
               for ln in res["narr"])
    assert people["npc:dunn"].state.emotion["fear"] > 0.0      # the room actually flinched
