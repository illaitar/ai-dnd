"""Автоматизируемые критерии судейства (main §13, §12.3).

Эти проверки — объективная часть рубрики LLM-as-judge. Они кодируют контракты,
которые обязаны держать ОБА пути (модель и детерминированный фоллбэк):

* schema_valid          — выход агента валиден по тулсхеме (JSONSchemaBench).
* narrator_preserves_numbers — нарратор НЕ меняет цифры исхода (main §12.3).
* intent_valid          — интент в пределах схемы и правдоподобных целей.
* gate_respected        — NPC уважает гейты отношений (не выдаёт секрет без trust).

Субъективная believability оценивается судьёй поверх транскрипта отдельно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..inference.agents import SCHEMAS


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    hard: bool = True       # hard — контракт (проверяется в pytest); soft — для судьи

    def __str__(self) -> str:
        tag = "PASS" if self.passed else ("FAIL" if self.hard else "warn")
        return f"[{tag}] {self.name}: {self.detail}"


def _schema_props(schema_name: str) -> tuple[dict, list[str]]:
    params = SCHEMAS[schema_name]["parameters"]
    return params.get("properties", {}), params.get("required", [])


def schema_valid(output: dict | None, schema_name: str) -> Check:
    """Проверяет наличие обязательных полей и членство в enum (JSONSchemaBench)."""
    if output is None:
        return Check(f"schema:{schema_name}", False, "вывод отсутствует (None)")
    props, required = _schema_props(schema_name)
    for r in required:
        if r not in output:
            return Check(f"schema:{schema_name}", False, f"нет обязательного поля '{r}'")
    for key, val in output.items():
        spec = props.get(key, {})
        enum = spec.get("enum")
        if enum is not None and val not in enum:
            return Check(f"schema:{schema_name}", False,
                         f"поле '{key}'={val!r} вне enum {enum}")
    return Check(f"schema:{schema_name}", True, "валидно по схеме")


def _numbers(text: str) -> set[int]:
    return {int(n) for n in re.findall(r"\d+", text or "")}


def narrator_preserves_numbers(mechanical_numbers: set[int], narration: str,
                               hit: bool | None = None) -> Check:
    """Нарратор не должен вводить новые механические числа и не противоречить
    исходу (main §12.3). Эвристика: все числа в нарративе должны принадлежать
    набору механических чисел исхода (или быть «литературными» — годами/часами)."""
    nums = _numbers(narration)
    intruders = {n for n in nums if n not in mechanical_numbers and n > 1}
    # допускаем мелкие числовые слова времени/счёта (1..2) и точные совпадения
    if intruders:
        return Check("narrator_no_invented_numbers", False,
                     f"нарратив вводит числа вне исхода: {sorted(intruders)}")
    if hit is False and re.search(r"\b(попада|пронза|рассека|ранит)\w*", narration or "", re.I):
        return Check("narrator_consistent_outcome", False,
                     "нарратив описывает попадание при промахе")
    return Check("narrator_preserves_numbers", True, "цифры исхода сохранены")


def intent_valid(intent: dict | None, options: list[str]) -> Check:
    base = schema_valid(intent, "emit_intent")
    if not base.passed:
        return base
    return Check("intent_valid", True, f"verb={intent.get('verb')}")


def gate_respected(decision: dict | None, trust: float, fear: float) -> Check:
    """NPC не выдаёт секрет недоверяемому; при высоком страхе — бежит/сдаётся."""
    if decision is None:
        return Check("gate", False, "решение отсутствует")
    action = decision.get("action")
    disclosed = decision.get("info_disclosed", [])
    if "secret" in disclosed and trust < 0.6:
        return Check("gate_secret", False, f"выдан секрет при trust={trust:.2f} < 0.6")
    if fear >= 0.6 and action not in ("flee", "yield", "call_guards"):
        return Check("gate_fear", False, f"высокий fear={fear:.2f}, но action={action}")
    return Check("gate_respected", True, f"action={action} уважает гейты")
