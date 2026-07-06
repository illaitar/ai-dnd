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
