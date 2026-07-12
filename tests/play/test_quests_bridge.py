"""Inc 1 honest bridge (docs/superpowers/specs/2026-07-12-emergent-quests-design.md §4):
Milestone.done → contract step (5 real _met kinds), verbatim done_any, giver-relative
done_any evaluation, and the completion writeback that advances the giver's real Agenda."""

from __future__ import annotations

from aidnd.mind.agenda import Milestone
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
