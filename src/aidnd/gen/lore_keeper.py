"""Lore-Keeper: проверка мировых законов на генерации (main §12.4, док 01 §6).

Инварианты живут в KG слоя L1. Профессиональный NPC имеет workplace и residence.
Лавка имеет ровно одного владельца. Именной предмет имеет владельца и локацию.
Цикл reject-repair: при нарушении — автоматический фикс, повторная валидация, до
N попыток. Невалидный контент не коммитится. Детерминированное ядро (может
эскалировать к LLM-валидатору, но не обязано).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Violation:
    invariant: str
    detail: str


@dataclass
class Fix:
    op: str                 # add_triple | remove_triple | instantiate_entity | set_field
    subject: str = ""
    relation: str = ""
    object: str = ""
    field: str = ""
    value: object = None


@dataclass
class Verdict:
    valid: bool
    violations: list[Violation] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)


PROFESSIONLESS = {"none", None, "", "adventurer", "child", "vagrant"}


def validate_npc_draft(draft: dict, world) -> Verdict:
    """Проверяет черновик персоны NPC против инвариантов (main §12.4)."""
    violations: list[Violation] = []
    fixes: list[Fix] = []
    prof = draft.get("profession")

    if prof not in PROFESSIONLESS:
        if not draft.get("workplace_ref"):
            violations.append(Violation("profession_has_workplace",
                                        f"{draft.get('name')} без места работы"))
            fixes.append(Fix("set_field", field="workplace_ref",
                             value="__instantiate_workplace__"))
        if not draft.get("residence_ref"):
            violations.append(Violation("profession_has_residence",
                                        f"{draft.get('name')} без жилья"))
            fixes.append(Fix("set_field", field="residence_ref",
                             value="__instantiate_residence__"))

    name = draft.get("name")
    if name and name in world.name_registry and not draft.get("_registered"):
        violations.append(Violation("name_unique", f"имя {name} уже занято"))
        fixes.append(Fix("set_field", field="name", value="__rename__"))

    return Verdict(valid=not violations, violations=violations, fixes=fixes)


def validate_item_draft(draft: dict, world) -> Verdict:
    """Именной предмет обязан иметь владельца/локацию (док 03 §3)."""
    violations: list[Violation] = []
    fixes: list[Fix] = []
    if draft.get("named"):
        if not draft.get("owner_ref") and not draft.get("location_ref"):
            violations.append(Violation("named_item_has_owner_location",
                                        f"{draft.get('instance_id')} без владельца и локации"))
            fixes.append(Fix("set_field", field="location_ref", value="__place_with_owner__"))
    return Verdict(valid=not violations, violations=violations, fixes=fixes)


def check_world_invariants(world) -> list[Violation]:
    """Глобальная проверка KG (для тестов/инспектора): лавка — ровно один владелец и т.п."""
    out: list[Violation] = []
    # каждая лавка имеет владельца
    for sid, shop in world.containers.items():
        if shop.kind == "shop" and not shop.owner_ref:
            out.append(Violation("shop_has_owner", f"{sid} без владельца"))
    # каждый профессиональный NPC имеет works_at и lives_in
    for npc in world.npcs():
        prof = world.kg.object_of(npc, "profession")
        if prof and prof not in PROFESSIONLESS:
            if not world.kg.works_at(npc):
                out.append(Violation("profession_has_workplace", f"{npc} без works_at"))
            if not world.kg.lives_in(npc):
                out.append(Violation("profession_has_residence", f"{npc} без lives_in"))
    return out
