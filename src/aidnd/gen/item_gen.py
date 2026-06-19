"""Генерация предметов: сокровища по логике 5e (док 03 §4).

Табличный режим, без LLM. Rarity-гейт держит экономику и кривую силы здравыми;
для LMoP (уровни 1-5) потолок rare, вес смещён к uncommon и расходникам.
"""

from __future__ import annotations

import random

from ..gen.provenance import Provenance
from ..gen.seeds import subseed
from ..inventory.items import ItemInstance

# Rarity-гейт по тиру игры (док 03 §4.1).
RARITY_GATE = {
    "tier1": {"common": 0.45, "uncommon": 0.40, "rare": 0.15, "very_rare": 0.0, "legendary": 0.0},
    "tier2": {"common": 0.25, "uncommon": 0.40, "rare": 0.30, "very_rare": 0.05, "legendary": 0.0},
    "tier3": {"common": 0.10, "uncommon": 0.30, "rare": 0.40, "very_rare": 0.18, "legendary": 0.02},
}

def spawn_item(
    world, template_id: str, container_id: str | None, qty: int = 1,
    owner: str | None = None, source: str = "lazy", seed: int = 0,
    instance_id: str | None = None, smith=None,
) -> str:
    """Инстанцирует предмет в контейнер и регистрирует в мире.

    smith — опц. callable(template) -> {name, description, ...} (роль item_smith):
    задаёт ИМЯ/ОПИСАНИЕ экземпляра по контексту, НЕ трогая механику. None → шаблон
    как есть (детерминированный офлайн-путь)."""
    iid = instance_id or world.next_item_id(template_id)
    inst = ItemInstance(
        instance_id=iid, template_id=template_id, owner_ref=owner,
        location_ref=container_id or "", quantity=qty,
        provenance=Provenance(source=source, generator="item_gen@1.0",
                              seed=seed, tick=world.clock.tick),
    )
    if smith is not None:
        tmpl = world.templates.get(template_id)
        forged = smith(tmpl) if tmpl is not None else None
        if forged:
            inst.custom_name = forged.get("name") or inst.custom_name
            inst.description = forged.get("description") or inst.description
    world.items[iid] = inst
    if container_id and container_id in world.containers:
        if iid not in world.containers[container_id].items:
            world.containers[container_id].items.append(iid)
    return iid


def party_tier(level: int) -> str:
    if level <= 4:
        return "tier1"
    if level <= 10:
        return "tier2"
    return "tier3"


def _weighted_pick(weights: dict, rng: random.Random):
    items = [(k, v) for k, v in weights.items() if v > 0]
    total = sum(v for _, v in items)
    if total <= 0:
        return None
    r = rng.random() * total
    acc = 0.0
    for k, v in items:
        acc += v
        if r <= acc:
            return k
    return items[-1][0]


def roll_coins(cr_tier: int, rng: random.Random) -> dict[str, int]:
    """Грубая аппроксимация individual treasure (док 03 §4)."""
    if cr_tier <= 0:
        return {"cp": rng.randint(3, 18) * 5, "sp": rng.randint(1, 6) * 3}
    if cr_tier == 1:
        return {"cp": rng.randint(2, 12) * 30, "sp": rng.randint(2, 12) * 10,
                "gp": rng.randint(1, 6) * 2}
    return {"gp": rng.randint(2, 20) * 10, "pp": rng.randint(1, 6)}


def generate_individual_treasure(
    world, cr: float, level: int, seed: int, container_id: str, model=None,
) -> dict:
    """Лут одного монстра: монеты + изредка предмет (док 03 §4, док 04 §8).
    model (опц.) включает роль item_smith — флейвор имени/описания добытого предмета."""
    rng = random.Random(subseed(seed, "loot", container_id))
    cr_tier = 0 if cr < 5 else 1
    coins = roll_coins(cr_tier, rng)
    items: list[str] = []
    # ~20% шанс расходника на CR<1, выше — чаще
    if rng.random() < min(0.5, 0.15 + cr * 0.3):
        rarity = _weighted_pick(RARITY_GATE[party_tier(level)], rng)
        tmpl_id = _pick_magic_template(world, rarity, rng)
        if tmpl_id:
            iid = spawn_item(world, tmpl_id, container_id, source="lazy", seed=seed,
                             smith=_smith_for(model, f"найдено в тайнике, CR≈{cr}"))
            inst = world.items[iid]
            inst.identified = world.templates[tmpl_id].rarity in ("mundane", "common")
            items.append(iid)
    return {"coins": coins, "items": items}


def _smith_for(model, context: str):
    """Строит smith-callable для spawn_item из менеджера модели (роль item_smith).
    None, если модели нет — тогда предмет берётся прямо из шаблона."""
    if model is None or not getattr(model, "available", lambda: False)():
        return None
    from ..inference.agents import forge_item

    def smith(tmpl):
        return forge_item(model, tmpl.name, tmpl.category, tmpl.rarity, context)
    return smith


def _pick_magic_template(world, rarity: str, rng: random.Random) -> str | None:
    cands = [tid for tid, t in world.templates.items()
             if t.category in ("magic", "consumable") and t.rarity == rarity]
    if not cands:
        # фоллбэк на расходник
        cands = [tid for tid, t in world.templates.items() if t.category == "consumable"]
    return rng.choice(sorted(cands)) if cands else None
