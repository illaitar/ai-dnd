"""anchored routing + persistence + scene-entry decay (МОЗГ Inc1 wiring).

- A direct interaction (attack, crime-victim grudge) writes `anchored=True` → the SLOW carrier;
  a co-present bystander / impression keeps the default `anchored=False` → LOOSE (fades fast).
- `_npc_save` round-trips `last_decay_gt`, so the decay clock survives a deploy (git reset + restart).
- `decay_scene_entrants` applies `decay_lazy` exactly ONCE per scene entrant — an NPC already
  in-scene last tick is skipped, so per-tick emotion decay and lazy decay never double-apply.
"""
import os
import tempfile

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.decay import decay_scene_entrants
from aidnd.mind.world import Body, World
from aidnd.server.play.engine import core
from aidnd.server.play.engine.pc.hero import _npc_save
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _state(pid: str, **traits):
    t = {"bravery": 0.5, "vengefulness": 0.0}
    t.update(traits)
    return NpcState.from_config(NpcConfig(id=pid, name=pid.upper(), role="страж", traits=t))


# ── 1. attack anchors the victim; a co-present non-target stays unanchored ──────────────
def test_attack_write_anchors_victim_not_bystander():
    from aidnd.mind.llm_agent import apply_actions

    attacker = _state("npc:att")
    victim = _state("npc:vic")
    bystander = _state("npc:by")
    w = World()
    w.add(Body(id="npc:att", place="площадь"))
    w.add(Body(id="npc:vic", place="площадь", hp=12))
    w.add(Body(id="npc:by", place="площадь"))
    w.npc_minds = {"npc:att": attacker, "npc:vic": victim, "npc:by": bystander}

    apply_actions([{"tool": "attack", "target": "npc:vic"}], attacker, w, clock=1)

    assert victim.rel("npc:att")["anchored"] is True          # прямое насилие → медленный носитель
    # Inc2: the bystander now FEELS the violence via the Event bus — a loose fear-of-attacker, but
    # NOT an anchored grudge (that stays reserved for the direct target). Loose → fades fast (Inc1).
    assert "npc:att" in bystander.relationships               # projected onto him (was a memory-only sight)
    assert bystander.rel("npc:att")["fear"] > 0.0
    assert bystander.rel("npc:att")["anchored"] is False


# ── 1b. attack gives the victim ANGER too, not only fear — feuds between equals ──────────
def test_attack_write_gives_victim_anger_not_only_fear():
    from aidnd.mind.llm_agent import apply_actions

    attacker = _state("npc:att")
    victim = _state("npc:vic")
    w = World()
    w.add(Body(id="npc:att", place="площадь"))
    w.add(Body(id="npc:vic", place="площадь", hp=12))
    w.npc_minds = {"npc:att": attacker, "npc:vic": victim}

    apply_actions([{"tool": "attack", "target": "npc:vic"}], attacker, w, clock=1)

    assert victim.emotion["fear"] >= 0.6
    assert victim.emotion["anger"] >= 0.6                     # retaliation drive, not just flight
    assert victim.emotion_target["anger"] == "npc:att"


# ── 2. crime-victim grudge is anchored; a bystander gets only memory → unanchored ───────
class _Person:
    def __init__(self, st: NpcState, name: str):
        self.state = st
        self.name = name


@pytest.fixture
def session(monkeypatch):
    store = WorldStore(os.path.join(tempfile.mkdtemp(), "live.db"))
    monkeypatch.setattr(persist, "_STORE", store)
    saved = dict(core._S._d())
    d = core._S._d()
    try:
        d.clear()
        d.update(wid=1, gt=8 * 60, transit={})
        yield store
    finally:
        d.clear()
        d.update(saved)


def test_witness_crime_victim_anchored_bystander_loose(session):
    victim = _Person(_state("npc:vic"), "Жертва")
    bystander = _Person(_state("npc:by"), "Зевака")
    people = {"npc:vic": victim, "npc:by": bystander}
    core._S["people"] = people
    crof = {"npc:vic": 1, "npc:by": 1}                        # both settled at node 1

    core._witness_crime(people, crof, 1, "npc:vic", "силой отнял кошель", weight=2)

    from aidnd.server.play.engine.session.config import PLAYER
    assert victim.state.rel(PLAYER)["anchored"] is True       # обида жертвы — медленный носитель
    # Inc2: the bystander now feels the robbery too (Event bus) — a LOOSE fear-of-actor, unanchored,
    # so it fades fast; only the victim carries the slow anchored grudge.
    assert PLAYER in bystander.state.relationships
    assert bystander.state.rel(PLAYER)["fear"] > 0.0
    assert bystander.state.rel(PLAYER)["anchored"] is False


# ── 3. last_decay_gt round-trips through save → store → load ────────────────────────────
def test_npc_save_roundtrips_decay_clock(session):
    st = _state("npc:m")
    st.last_decay_gt = 12345
    st.rel("pc")["affinity"] = -0.4
    core._S["people"] = {"npc:m": _Person(st, "М")}

    _npc_save("npc:m")

    raw = session.get_npc_state(core._wid(), "npc:m")
    assert raw is not None and raw["last_decay_gt"] == 12345   # persisted (deploy-survivable)
    # restore path (mirrors worldbuild/person.py) reads it back onto a fresh state
    fresh = _state("npc:m")
    fresh.last_decay_gt = int(raw.get("last_decay_gt") or 0)
    assert fresh.last_decay_gt == 12345


# ── 4. decay_scene_entrants: once on entry, NOT per-tick (the double-apply guard) ───────
def test_decay_applied_once_on_entry_not_per_tick():
    st = _state("npc:x", vengefulness=0.0)
    st.rel("pc")["fear"] = 0.24
    st.rel("pc")["anchored"] = False                          # loose → hl 2 days
    st.last_decay_gt = 10_000
    minds = {"npc:x": st}

    # tick 1: npc:x ENTERS the scene (absent from prev_who) → decay fires once, over a 3-day gap
    now1 = 10_000 + 3 * 1440
    decay_scene_entrants(minds, {"npc:x"}, prev_who=set(), now_gt=now1)
    after_entry = st.rel("pc")["fear"]
    assert after_entry == pytest.approx(0.085, abs=0.01)      # 0.24 × 0.5^1.5 — decayed ONCE

    # tick 2: npc:x is STILL in scene (in prev_who) → skipped; the loose fear is NOT re-decayed
    entered = decay_scene_entrants(minds, {"npc:x"}, prev_who={"npc:x"}, now_gt=now1 + 1440)
    assert entered == []                                      # nobody entered
    assert st.rel("pc")["fear"] == after_entry                # unchanged — guard held
    assert st.last_decay_gt == now1                           # clock not re-stamped for a stayer


def test_decay_scene_entrants_ignores_unknown_ids():
    """A present id with no live mind (transit/edge) is skipped without error."""
    st = _state("npc:x")
    st.last_decay_gt = 0
    entered = decay_scene_entrants({"npc:x": st}, {"npc:x", "npc:ghost"}, set(), now_gt=1440)
    assert entered == ["npc:x"]
