"""Гибридная модель NPC: состояние + способности (9 семейств) + вероятностный utility-арбитр.

LLM насыщает 3 точки и НЕ выбирает действие: озвучка результата (Cap.voice), генерация
контента под способность, субъективное суждение (Context.estimate → балл в utility).
Решение — всегда вероятностный top-k поверх детерминированной полезности (arbiter.choose).
"""

from __future__ import annotations

from .arbiter import choose, distribution, evaluate, shortlist
from .capabilities import BY_KEY, CAPABILITIES, FAMILIES, Cap, Effects
from .context import Context, Stimulus
from .state import NEEDS, TRAITS, NpcState, make_state, tweak_from_description

__all__ = [
    "NpcState", "make_state", "tweak_from_description", "NEEDS", "TRAITS",
    "Stimulus", "Context", "Cap", "Effects", "CAPABILITIES", "BY_KEY", "FAMILIES",
    "choose", "evaluate", "shortlist", "distribution",
]
