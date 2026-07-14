"""Inc1 — scene churn as feed events. Pure-function unit tests over _salient / _churn_items:
salient joiners are NAMED (capped by churn_named_max), the rest collapse into one summary line per
direction; an empty diff yields no items. No LLM, no session mutation beyond a snapshot restore.

Also: churn-as-QUEUE regression (_live_build must extend, never overwrite, the undrained buffer —
review finding on 84b45c7) and singular grammar for a rest of exactly 1."""
import os
import tempfile
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine.core import PLAYER
from aidnd.server.play.engine.world import _churn_items, _ru_count, _salient


def _npc(pid, name, role="горожанин", knows_player=False, hp=None):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    if knows_player:
        st.relationships[PLAYER] = {"trust": 0.2, "affinity": 0.3, "fear": 0.0}
    if hp is not None:
        st.hp = hp
    return SimpleNamespace(id=pid, name=name, role=role, state=st, work=None, home=None, persona={})


def _people(*npcs):
    return {n.id: n for n in npcs}


def test_salient_by_each_signal():
    ppl = _people(
        _npc("p_ac", "Мара", knows_player=True),          # acquaintance
        _npc("p_gv", "Роза", role="лавочник"),            # giver (via set)
        _npc("p_tg", "Тор", role="кузнец"),               # contract target (via set)
        _npc("p_guard", "Гром", role="стражник"),         # guard
        _npc("p_hurt", "Пал", hp=3),                      # wounded (hp<max, default max 10)
        _npc("p_bg", "Йорг"),                             # plain civilian
    )
    givers, targets = {"p_gv"}, {"p_tg"}
    assert _salient("p_ac", ppl, givers, targets)
    assert _salient("p_gv", ppl, givers, targets)
    assert _salient("p_tg", ppl, givers, targets)
    assert _salient("p_guard", ppl, givers, targets)
    assert _salient("p_hurt", ppl, givers, targets)
    assert not _salient("p_bg", ppl, givers, targets)


def test_empty_diff_no_items():
    who = frozenset({"a", "b"})
    assert _churn_items(who, who, _people(_npc("a", "A"), _npc("b", "B")), set(), set()) == []


def test_five_joins_two_salient_two_named_plus_summary():
    # 5 join, 2 salient (acquaintance + giver), 3 background → 2 named + 1 summary «вошли трое»
    ppl = _people(
        _npc("host", "Гром", role="трактирщик"),          # already present
        _npc("p_mara", "Мара", knows_player=True),
        _npc("p_roza", "Роза Медовар", role="лавочник"),
        _npc("p_yorg", "Йорг"), _npc("p_pal", "Пал"), _npc("p_tim", "Тим"),
    )
    prev = frozenset({"host"})
    here = frozenset({"host", "p_mara", "p_roza", "p_yorg", "p_pal", "p_tim"})
    items = _churn_items(prev, here, ppl, {"p_roza"}, set())
    named = [i for i in items if i.get("pid")]
    summary = [i for i in items if not i.get("pid")]
    assert {i["who"] for i in named} == {"Мара", "Роза Медовар"}   # 2 named (== churn_named_max)
    assert len(summary) == 1                                        # one arrival summary
    assert _ru_count(3) in summary[0]["text"]                       # «трое»
    assert all(i["k"] == "deed" for i in items)                    # feed-shape compat (scene_digest)


def test_leavers_symmetric_summary():
    ppl = _people(_npc("host", "Гром"), _npc("p_vit", "Витольд"), _npc("p_x", "Икс"))
    prev = frozenset({"host", "p_vit", "p_x"})
    here = frozenset({"host"})                                     # two left, neither salient
    items = _churn_items(prev, here, ppl, set(), set())
    assert len(items) == 1 and items[0].get("pid") is None
    assert _ru_count(2) in items[0]["text"]                        # «зал редеет — вышли двое»


def test_named_cap_folds_extra_salient_into_summary():
    # 3 salient joiners, churn_named_max=2 → 2 named + summary counting the 3rd
    ppl = _people(
        _npc("host", "Гром"),
        _npc("g1", "Роза", role="лавочник"), _npc("g2", "Тор", role="кузнец"),
        _npc("g3", "Влас", role="писарь"),
    )
    prev = frozenset({"host"})
    here = frozenset({"host", "g1", "g2", "g3"})
    items = _churn_items(prev, here, ppl, {"g1", "g2", "g3"}, set())
    named = [i for i in items if i.get("pid")]
    summary = [i for i in items if not i.get("pid")]
    assert len(named) == 2 and len(summary) == 1


def test_rest_of_one_is_grammatically_singular():
    # rest==1 (one non-salient joiner/leaver) → «вошёл один» / «вышел один», NOT «вошли один»
    # (matches the spec's own worked example — plural is only for rest>=2, kept via _ru_count).
    ppl = _people(_npc("host", "Гром"), _npc("p_a", "Аня"))
    prev = frozenset({"host"})
    here = frozenset({"host", "p_a"})
    items = _churn_items(prev, here, ppl, set(), set())
    assert len(items) == 1
    assert items[0]["text"] == "народ прибывает — вошёл один"

    items = _churn_items(here, prev, ppl, set(), set())            # symmetric: one leaves
    assert len(items) == 1
    assert items[0]["text"] == "зал редеет — вышел один"


# ─────────────────────── Inc1 review fix: churn is a QUEUE, not a slot ───────────────────────
# _live_build needs a real assembled world (city/people/crof/cr2b/loc) to diff against, so these
# integration tests drive it directly (same fixture shape as tests/play/test_surface.py) — no HTTP,
# no LLM (plan_agenda stubbed out).


@pytest.fixture
def live_world(monkeypatch):
    from aidnd.server.play.engine import core
    from aidnd.server.play.engine import world as world_m
    from aidnd.server.play.engine.session import persist
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(persist, "_STORE", WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None                              # force a fresh build in the fresh store
    monkeypatch.setattr(world_m, "plan_agenda", lambda *a, **k: None)  # LLM-backed — irrelevant here
    saved = dict(core._S._d())
    try:
        city, people, crof, cr2b, loc = world_m._play()
        core._S["live"] = None                           # clean slate — build from scratch below
        yield world_m, core, city, people, crof, cr2b, loc
    finally:
        d = core._S._d()
        d.clear()
        d.update(saved)


def _mark_salient(people, pid):
    """Make `pid` a NAMED churn line unconditionally (acquaintance signal), so assertions can key
    off their name rather than depend on the pool's random role/hp draw."""
    people[pid].state.relationships[PLAYER] = {"trust": 0.2, "affinity": 0.3, "fear": 0.0}


def test_two_diffs_before_one_drain_both_batches_present(live_world):
    # Two successive _live_build rebuilds (e.g. act/say never draining live_pending, per the
    # review finding) must NOT lose the first batch: the queue accumulates, drain empties it once.
    world_m, core, city, people, crof, cr2b, loc = live_world
    base_here = [pid for pid, node in crof.items() if node == loc]
    assert len(base_here) >= 2, "нужно ≥2 душ в стартовой сцене для этого теста"
    p_a, p_b = base_here[0], base_here[1]
    _mark_salient(people, p_a)
    _mark_salient(people, p_b)
    away = next(n for n in crof.values() if n != loc)    # any other real node — "outside" this scene
    crof[p_a] = away
    crof[p_b] = away                                     # both start OUTSIDE the scene

    world_m._live_build(city, people, crof, cr2b, loc)   # build #1 — no prior scene, churn == []
    assert core._S["live"]["churn"] == []

    crof[p_a] = loc                                       # p_a joins
    world_m._live_build(city, people, crof, cr2b, loc)    # build #2 — NOT drained after this
    churn_after_2 = core._S["live"]["churn"]
    assert any(i.get("pid") == p_a for i in churn_after_2), "первая партия (p_a) должна попасть в очередь"

    crof[p_b] = loc                                       # p_b joins too, p_a still present
    world_m._live_build(city, people, crof, cr2b, loc)    # build #3 — still not drained
    churn_after_3 = core._S["live"]["churn"]
    names_in_queue = {i.get("pid") for i in churn_after_3}
    assert p_a in names_in_queue, "overwrite regression: вторая сборка не должна стереть первую партию"
    assert p_b in names_in_queue
    assert len(churn_after_3) >= len(churn_after_2), "очередь растёт, а не перезаписывается"

    drained = core._S["live"].pop("churn", [])            # atomic drain — as _live_tick does
    assert {i.get("pid") for i in drained} == {p_a, p_b}

    world_m._live_build(city, people, crof, cr2b, loc)    # build #4 — no new arrivals, drained buffer
    assert core._S["live"]["churn"] == []                 # nothing resurfaces from the drained batch
