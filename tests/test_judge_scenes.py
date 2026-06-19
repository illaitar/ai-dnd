"""E2E сцены: объективная часть рубрики LLM-as-judge (main §13).

Эти инварианты обязаны держать ОБА пути — модель и детерминированный фоллбэк.
Тесты гоняются офлайн (use_model=False), поэтому зелёные без сервера; при живой
модели тот же харнесс захватывает её выходы для субъективного судейства.
"""

import pytest

from aidnd.eval import SCENES, run_scene


@pytest.mark.parametrize("name", list(SCENES))
def test_scene_auto_checks_pass(name):
    t = run_scene(name, use_model=False)
    failed = [str(c) for c in t.checks if not c.passed]
    assert not failed, f"сцена {name}: провалены автопроверки:\n" + "\n".join(failed)


def test_narrator_never_invents_numbers():
    # ключевой инвариант main §12.3: нарратор не меняет цифры исхода
    t = run_scene("combat_round", use_model=False)
    narr_checks = [c for c in t.checks if "narrator" in c.name]
    assert narr_checks and all(c.passed for c in narr_checks)


def test_npc_respects_relationship_gates():
    t = run_scene("tavern_dialogue", use_model=False)
    gate = [c for c in t.checks if c.name.startswith("gate")]
    assert gate and all(c.passed for c in gate)


def test_lazy_npc_satisfies_invariants():
    t = run_scene("lazy_npc_generation", use_model=False)
    inv = [c for c in t.checks if c.name == "world_invariants"]
    assert inv and inv[0].passed
