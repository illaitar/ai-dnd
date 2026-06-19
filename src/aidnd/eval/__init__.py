"""Eval-харнесс: end-to-end сцены + LLM-as-judge (main §13).

Сцены прогоняются через полный движок. Часть критериев судейства
автоматизирована (схемная валидность по JSONSchemaBench, невмешательство
нарратора в механику, гейты отношений) — эти инварианты обязаны держать и модель,
и детерминированный фоллбэк. Субъективную believability (методология ablation
Generative Agents) выставляет внешний судья (человек или LLM) поверх транскрипта.
"""

from .rubric import (
    Check,
    gate_respected,
    intent_valid,
    narrator_preserves_numbers,
    schema_valid,
)
from .scenes import SCENES, run_all, run_scene

__all__ = ["schema_valid", "narrator_preserves_numbers", "intent_valid",
           "gate_respected", "Check", "SCENES", "run_scene", "run_all"]
