"""Playtest bug: a tester «killed» a full-HP NPC purely through free narration — the DM described
crunching bones and a pulse-check, no combat ever rolled — then was confused the NPC's contract
stayed active. Fix: the /act free-narration fallback (handlers/freeform.py's _say_aloud path) must
never resolve violence outside combat.
    - unrecognized violent phrasing ("бью Горма ножом") toward a REAL present NPC is caught by a
      lethal-verb regex + present-NPC name match and routed into the same duel branch as
      verb=="attack" (_start_duel), instead of falling through to DM narration.
    - if a combat is already active, the free-narration fallback (_say_aloud, shared by /act and
      /api/play/say) short-circuits with a redirect line instead of narrating over the fight.
    - ordinary non-violent text is unaffected — it still narrates via the DM snapshot prompt."""

from __future__ import annotations

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.handlers import freeform


class _P:
    def __init__(self, name="Горм", pid="npc:dunn"):
        self.name, self.role, self.work, self.persona = name, "лавочник", None, {}
        cfg = NpcConfig(id=pid, name=name, role="лавочник")
        self.state = NpcState.from_config(cfg)


class _Stub:
    """Fake narrator manager — must NOT be called when the lethal/combat-active guards fire."""

    def __init__(self, content="Зал на миг притих."):
        self.content = content
        self.called = False

    def call(self, role, messages, **kw):
        self.called = True
        return {"content": self.content}


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

    people = {"npc:dunn": _P()}
    crof = {"npc:dunn": "loc:x"}          # NPC is present at the player's location
    monkeypatch.setattr(freeform, "_play", lambda: (None, people, crof, {}, "loc:x"))

    class _FakeCombatant:
        def __init__(self, name="?"):
            self.name = name
            self.side = None

    monkeypatch.setattr(freeform, "_combatant_from_npc",
                        lambda pid, p: _FakeCombatant(p.name), raising=False)
    monkeypatch.setattr(freeform, "_pc_combatant", lambda: _FakeCombatant("pc"), raising=False)

    class _FakeEncounter:
        def __init__(self, pcs, foes, **kw):
            self.pcs, self.foes, self.kw = pcs, foes, kw

        def view(self):
            return {}

    monkeypatch.setattr(freeform, "Encounter", _FakeEncounter, raising=False)

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


def test_violent_phrase_toward_present_npc_starts_duel_not_narration(world, monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)

    res = freeform._attempt({"verb": "wait", "_text": "я бью Горма ножом в живот"}, {})

    assert res.get("combat") is True
    assert core._S.get("combat") is not None
    assert core._S["combat"]["npc"] == "npc:dunn"
    assert not stub.called                                  # never reached the narrator LLM
    assert "Горм" in " ".join(res["narr"])


def test_violent_phrase_with_combat_already_active_redirects(world, monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    core._S["combat"] = {"enc": object(), "npc": "npc:dunn", "loc": "loc:x", "head": {}}

    res = freeform._attempt({"verb": "wait", "_text": "добиваю Горма"}, {})

    assert res.get("combat") is True
    assert res["narr"] == ["Бой уже идёт — действуй в бою."]
    assert not stub.called


def test_nonviolent_text_still_narrates_normally(world, monkeypatch):
    stub = _Stub("Ты оглядываешь лавку.")
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)

    res = freeform._attempt({"verb": "wait", "_text": "оглядываю лавку"}, {})

    assert res.get("combat") is None
    assert core._S.get("combat") is None
    assert stub.called
    assert res["narr"] == ["Ты оглядываешь лавку."]
