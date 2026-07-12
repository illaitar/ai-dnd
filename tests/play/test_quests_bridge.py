"""Inc 1 honest bridge (docs/superpowers/specs/2026-07-12-emergent-quests-design.md §4):
Milestone.done → contract step (5 real _met kinds), verbatim done_any, giver-relative
done_any evaluation, and the completion writeback that advances the giver's real Agenda."""

from __future__ import annotations

from aidnd.mind import Body, Item, NpcConfig, NpcState, World
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.server.play.engine.quests import bridge


def _m(done: dict) -> Milestone:
    return Milestone("веха", "acquire", "цель", {}, done)


# ── §4 table: all 5 real _met kinds → step (or None) ──
def test_translate_have_to_bring():
    assert bridge.milestone_to_step(_m({"type": "have", "item": "гроссбух"})) == {
        "kind": "bring", "want": "гроссбух"}


def test_translate_dead_to_dead():
    assert bridge.milestone_to_step(_m({"type": "dead", "id": "npc:ralf"})) == {
        "kind": "dead", "target": "npc:ralf"}


def test_translate_wealth_to_bring_want_filled_by_casting():
    step = bridge.milestone_to_step(_m({"type": "wealth", "value": 100}))
    assert step == {"kind": "bring"}          # `want` (a real valuable) is casting's job
    assert "want" not in step


def test_translate_affinity_to_deliver_gift():
    step = bridge.milestone_to_step(_m({"type": "affinity", "id": "npc:x", "value": 0.5}))
    assert step == {"kind": "deliver", "target": "npc:x"}   # `want` (the gift) is casting's job


def test_translate_at_is_not_delegatable():
    assert bridge.milestone_to_step(_m({"type": "at", "place": "дом"})) is None


def test_translate_never_and_unknown_are_not_delegatable():
    assert bridge.milestone_to_step(_m({"type": "never"})) is None
    assert bridge.milestone_to_step(_m({})) is None


# ── done_any[0] is a VERBATIM copy of Milestone.done ──
def test_make_done_any_is_verbatim_copy():
    m = _m({"type": "have", "item": "гроссбух"})
    res = bridge.make_done_any(m)
    assert res == [{"type": "have", "item": "гроссбух"}]
    res[0]["item"] = "подделка"                # mutating the copy must NOT touch the milestone
    assert m.done == {"type": "have", "item": "гроссбух"}


# ── helpers: a giver State + a mind World holding their loot (mirrors test_agenda.py) ──
def _giver(pid: str, done: dict, loot=(), rels=None, cursor=0):
    cfg = NpcConfig(id=pid, name=pid)
    st = NpcState.from_config(cfg)
    st.relationships = dict(rels or {})
    st.agendas = [Agenda("цель", "ambition", 0.7, [Milestone("веха", "acquire", "цель", {}, done)])]
    st.agendas[0].cursor = cursor
    w = World()
    w.add(Body(id=pid, place="дом", loot=[Item(n, 0.5) for n in loot]))
    return st, w


def _ct(**over) -> dict:
    base = {"src": "sift", "giver": "npc:dunn", "done_any": [{"type": "have", "item": "гроссбух"}]}
    base.update(over)
    return base


# ── done_any_met: ANY disjunct true for the giver ──
def test_done_any_met_true_when_have():
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["гроссбух Марты"])
    assert bridge.done_any_met(_ct(), (st, w)) is True


def test_done_any_met_false_when_none_hold():
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["хлеб"])
    assert bridge.done_any_met(_ct(), (st, w)) is False


def test_done_any_met_true_via_second_disjunct():
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["хлеб"])
    w.add(Body(id="npc:ralf", place="дом", hp=0, alive=False))
    ct = _ct(done_any=[{"type": "have", "item": "гроссбух"}, {"type": "dead", "id": "npc:ralf"}])
    assert bridge.done_any_met(ct, (st, w)) is True


# ── writeback: advances the giver's real cursor AND re-plans the next ambition ──
def test_writeback_advances_cursor_and_replans(monkeypatch):
    calls = []
    monkeypatch.setattr(bridge, "plan_agenda", lambda *a, **k: calls.append(a) or None)
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["гроссбух Марты"])
    ok = bridge.quest_writeback(_ct(), (st, w), manager=object())
    assert ok is True
    assert st.agendas[0].cursor == 1                 # honest bridge: the giver's real goal moved
    assert st.agendas[0].status == "done"            # single-milestone agenda exhausted
    assert len(calls) == 1                           # plan_agenda re-planned the next ambition


def test_writeback_skips_non_sift():
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["гроссбух Марты"])
    assert bridge.quest_writeback(_ct(src="improvised"), (st, w)) is False
    assert st.agendas[0].cursor == 0
    assert bridge.quest_writeback({"giver": "npc:dunn", "done_any": [{"type": "have", "item": "г"}]},
                                  (st, w)) is False   # no src key at all → improvised


def test_writeback_guards_moot(monkeypatch):
    spy = []
    monkeypatch.setattr(bridge, "plan_agenda", lambda *a, **k: spy.append(1))
    # (a) predicate no longer holds → no advance
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["хлеб"])
    assert bridge.quest_writeback(_ct(), (st, w), manager=object()) is False
    assert st.agendas[0].cursor == 0
    # (b) milestone already advanced (cursor moved on) → no double advance
    st2, w2 = _giver("npc:dunn", {"type": "have", "item": "гроссбух"},
                     loot=["гроссбух Марты"], cursor=1)
    assert bridge.quest_writeback(_ct(), (st2, w2), manager=object()) is False
    assert st2.agendas[0].cursor == 1
    assert spy == []                                  # never re-planned on a mooted writeback
