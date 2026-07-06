"""Кейс: промпт арбитра ГЕНЕРИТСЯ из реестра примитивов (принцип 3 — одна истина в коде)."""

from aidnd.server.play.engine.resolve import PRIMITIVES, _sys_prompt


def test_prompt_is_derived_from_registry():
    sp = _sys_prompt()
    for p in PRIMITIVES:
        assert p["verb"] in sp
        assert p["when"] in sp
    assert '"verdict":"do|narrate"' in sp


def test_registry_targets_have_field_hints():
    from aidnd.server.play.engine.resolve import _FIELD_HINT

    for p in PRIMITIVES:
        for t in p["targets"]:
            assert t in _FIELD_HINT, f"цель {t} без подсказки поля"


def test_normalize_plan_shapes():
    from aidnd.server.play.engine.resolve import normalize_plan

    one = normalize_plan({"verb": "take", "item": "it:1"})     # старая форма → план из 1
    assert one["plan"] == [{"verb": "take", "item": "it:1"}]
    long = normalize_plan({"plan": [{"verb": "move"}, {"verb": "take"}, {"verb": "use"},
                                    {"verb": "give"}]})
    assert len(long["plan"]) == 3                              # кап длины
    mixed = normalize_plan({"plan": [{"verb": "move"}, {"verb": "wait"}, {"verb": "take"}]})
    assert [s["verb"] for s in mixed["plan"]] == ["move", "take"]  # wait-балласт вон
    narr = normalize_plan({"verdict": "narrate",
                           "plan": [{"verb": "move"}, {"verb": "wait", "detail": "смотрит"}]})
    assert narr["plan"] == [{"verb": "wait", "detail": "смотрит"}]  # narrate → одно wait
