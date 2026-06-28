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
    theme: str = "", min_items: int = 0,
) -> dict:
    """Лут одного монстра/тайника: монеты + предмет(ы) (док 03 §4, док 04 §8).
    model (опц.) — роль item_smith (флейвор имени/описания). theme — характер находки
    (для смита). min_items — гарантированный минимум предметов (тайник комнаты: ≥1)."""
    rng = random.Random(subseed(seed, "loot", container_id))
    cr_tier = 0 if cr < 5 else 1
    coins = roll_coins(cr_tier, rng)
    items: list[str] = []
    ctx = theme or f"найдено в тайнике, CR≈{cr}"

    def _spawn_one() -> None:
        rarity = _weighted_pick(RARITY_GATE[party_tier(level)], rng)
        tmpl_id = _pick_magic_template(world, rarity, rng)
        if not tmpl_id:
            return
        iid = spawn_item(world, tmpl_id, container_id, source="lazy", seed=seed,
                         smith=_smith_for(model, ctx))
        world.items[iid].identified = world.templates[tmpl_id].rarity in ("mundane", "common")
        items.append(iid)

    # ~20% шанс расходника на CR<1, выше — чаще
    if rng.random() < min(0.5, 0.15 + cr * 0.3):
        _spawn_one()
    while len(items) < min_items:                    # гарантия осязаемой находки в тайнике
        n = len(items)
        _spawn_one()
        if len(items) == n:                          # подходящий шаблон не нашёлся — не зацикливаемся
            break
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


# ----------------------------------------------------------------------------- #
#  Генерация НОВЫХ шаблонов: имя/описание от модели, механика — honored-поля     #
#  (weapon_key/ac/ac_bonus/heal/slot) с клемпом по rarity → баланс безопасен.    #
# ----------------------------------------------------------------------------- #
_WEAPON_KEYS = ("dagger", "shortsword", "longsword", "scimitar", "mace", "morningstar", "greataxe", "shortbow")
_MAGIC_SLOTS = ("cloak", "boots", "ring", "amulet", "head")
_VALUE_BY_RARITY = {"common": (2000, 9000), "uncommon": (15000, 90000), "rare": (90000, 350000)}
_AC_BONUS_CAP = {"common": 0, "uncommon": 1, "rare": 2}
_HEAL_BY_RARITY = {"common": "2d4+2", "uncommon": "4d4+4", "rare": "8d4+8"}
_ARMOR_AC = {"common": 11, "uncommon": 13, "rare": 15}
_WEIGHT = {"weapon": 3.0, "armor": 12.0, "consumable": 0.5, "magic": 1.0, "gear": 1.0}
_FALLBACK_NAMES = {
    "weapon": ["Клинок странника", "Зазубренный тесак", "Старый палаш", "Гнутая алебарда"],
    "armor": ["Латаный нагрудник", "Дорожный доспех", "Кожанка наёмника", "Помятый щит"],
    "consumable": ["Мутное зелье", "Травяной отвар", "Фляга знахаря", "Склянка с осадком"],
    "magic": ["Тусклый амулет", "Потёртое кольцо", "Странный талисман", "Холодная подвеска"],
}


def _validate_mechanic(category: str, rarity: str, raw: dict, rng: random.Random):
    """Honored-механика по category+rarity (числа клемпит движок, не модель). → (base_stats, tags)."""
    if category == "weapon":
        wk = raw.get("weapon_key") if raw.get("weapon_key") in _WEAPON_KEYS else rng.choice(_WEAPON_KEYS)
        return {"weapon_key": wk, "slot": "main_hand"}, ("martial",)
    if category == "armor":
        if rng.random() < 0.3:                            # щит
            return {"ac_bonus": max(1, _AC_BONUS_CAP.get(rarity, 1) or 1), "slot": "off_hand"}, ("shield",)
        return {"ac": _ARMOR_AC.get(rarity, 11), "max_dex": 99, "slot": "armor"}, ()
    if category == "consumable":
        return {"heal": _HEAL_BY_RARITY.get(rarity, "2d4+2")}, ()
    slot = raw.get("slot") if raw.get("slot") in _MAGIC_SLOTS else rng.choice(_MAGIC_SLOTS)  # магия: +AC-тринкет
    bs = {"slot": slot}
    if _AC_BONUS_CAP.get(rarity, 0):
        bs["ac_bonus"] = _AC_BONUS_CAP[rarity]
    return bs, ()


def generate_item_template(world, category: str, rarity: str, model, rng: random.Random,
                           idx: int, context: str = "") -> tuple[str, str]:
    """Зарегистрировать НОВЫЙ шаблон в world.templates. Возвращает (template_id, описание)."""
    from ..inventory.items import ItemTemplate
    raw, name, desc = {}, None, ""
    if model is not None and getattr(model, "available", lambda: False)():
        try:
            from ..inference.agents import forge_item_template
            out = forge_item_template(model, category, rarity, context) or {}
            name, desc, raw = out.get("name"), out.get("description") or "", out
        except Exception:
            pass
    bs, tags = _validate_mechanic(category, rarity, raw, rng)
    if not name:
        name = rng.choice(_FALLBACK_NAMES.get(category, ["Безымянная вещица"]))
    lo, hi = _VALUE_BY_RARITY.get(rarity, (2000, 9000))
    tid = f"tmpl:gen_{category}_{idx}"
    world.templates[tid] = ItemTemplate(
        template_id=tid, name=str(name)[:48], category=category, base_stats=bs,
        weight=_WEIGHT.get(category, 1.0), base_value=rng.randint(lo, hi), rarity=rarity,
        attunement=(rarity == "rare" and category == "magic"), tags=tags)
    return tid, str(desc)[:160]


_ARCH_ITEMS = {
    "guard": ["tmpl:shortsword", "tmpl:leather"], "knight": ["tmpl:longsword", "tmpl:chain_shirt"],
    "mage": ["tmpl:dagger"], "merchant": ["tmpl:rations", "tmpl:torch"],
    "priest": ["tmpl:potion_healing"], "innkeeper": ["tmpl:rations", "tmpl:torch"],
    "thug": ["tmpl:dagger", "tmpl:leather"], "guildmaster": ["tmpl:dagger"],
}


# профессия/архетип → база личных вещей (механика табличная; ИМЯ/ОПИСАНИЕ переименует LLM-смит под роль)
_NPC_INV = {
    "guard": ["tmpl:shortsword", "tmpl:leather"], "guardsman": ["tmpl:shortsword", "tmpl:leather"],
    "captain": ["tmpl:longsword", "tmpl:chain_shirt"], "knight": ["tmpl:longsword", "tmpl:chain_shirt"],
    "soldier": ["tmpl:shortsword", "tmpl:leather"], "thug": ["tmpl:mace", "tmpl:leather"],
    "громила": ["tmpl:mace", "tmpl:leather"], "merchant": ["tmpl:rations", "tmpl:torch"],
    "лавочник": ["tmpl:rations", "tmpl:torch"], "innkeeper": ["tmpl:rations", "tmpl:torch"],
    "трактирщик": ["tmpl:rations", "tmpl:torch"], "слуга": ["tmpl:rations"], "разносчик": ["tmpl:rations"],
    "priest": ["tmpl:potion_healing"], "cleric": ["tmpl:potion_healing"], "служка": ["tmpl:potion_healing"],
    "blacksmith": ["tmpl:mace", "tmpl:dagger"], "кузнец": ["tmpl:mace", "tmpl:dagger"],
    "ремесленник": ["tmpl:dagger", "tmpl:torch"], "farmhand": ["tmpl:dagger"], "фермер": ["tmpl:dagger"],
    "батрак": ["tmpl:dagger"], "miner": ["tmpl:mace"], "рудокоп": ["tmpl:mace"],
    "mage": ["tmpl:dagger"], "wizard": ["tmpl:dagger"], "scribe": ["tmpl:torch"], "писарь": ["tmpl:torch"],
    "чиновник": ["tmpl:torch"], "noble": ["tmpl:dagger"], "дворянин": ["tmpl:dagger"],
    "guildmaster": ["tmpl:dagger"], "adventurer": ["tmpl:shortsword", "tmpl:leather"],
}
_RICH_ROLE = {"noble", "дворянин", "merchant", "лавочник", "guildmaster", "captain", "knight",
              "priest", "cleric", "townmaster", "градоправитель"}
_POOR_ROLE = {"farmhand", "фермер", "батрак", "слуга", "servant", "commoner", "горожанин",
              "beggar", "miner", "рудокоп", "разносчик"}


def enrich_npc_inventory(world, npc: str, model=None) -> list[str]:
    """ЛЕНИВО (раз) насытить инвентарь NPC осмысленными вещами под профессию/статус, с LLM-флейвором имён.
    Срабатывает при ПЕРВОМ доступе (труп/кража). Идемпотентно (флаг). Без модели — голые шаблоны."""
    flag = f"inv:{npc}"
    if flag in world.flags:
        return [iid for iid, i in world.items.items() if i.owner_ref == npc]
    from ..world.components import Persona
    per = world.ecs.get(npc, Persona)
    prof = (((per.profession or "") or (per.archetype or "")).lower() if per else "") or "townsfolk"
    if prof not in _NPC_INV and prof not in ("townsfolk", "горожанин", "commoner", ""):
        return []                                      # боевой моб (гоблин/разбойник) → не личный инвентарь, а клад по CR
    world.flags.add(flag)
    rng = random.Random(subseed(world.seed, "npcinv", npc))
    smith = _smith_for(model, f"личные вещи человека профессии «{prof}»")
    out = []
    base = 8 if prof in _RICH_ROLE else 1 if prof in _POOR_ROLE else 3   # достаток по роли
    out.append(spawn_item(world, "tmpl:gp", None, qty=rng.randint(1, 6) * base, owner=npc, source="lazy"))
    items = list(_NPC_INV.get(prof, ["tmpl:dagger"]))
    if rng.random() < 0.5:
        items.append("tmpl:rations")
    for tid in items:                                  # каждая вещь — табличная механика + LLM-имя под роль
        if tid in world.templates:
            out.append(spawn_item(world, tid, None, owner=npc, source="lazy", smith=smith))
    return out


def npc_loot_pool(world, npc: str, archetype: str, rng: random.Random,
                  bonus_pool: list[str], rich: bool) -> list[str]:
    """Дать NPC owner_ref-предметы (на смерть авто-собираются в труп _spawn_corpse). rich → +предмет
    из сгенерированного пула. Монеты — как предметы (tmpl:gp), чтобы тоже падали в труп."""
    out = []
    gp = rng.randint(1, 6) * (5 if rich else 1)
    out.append(spawn_item(world, "tmpl:gp", None, qty=gp, owner=npc, source="pregen"))
    cands = _ARCH_ITEMS.get(archetype) or ["tmpl:rations", "tmpl:torch", "tmpl:dagger"]
    out.append(spawn_item(world, rng.choice(cands), None, qty=1, owner=npc, source="pregen"))
    if rich and bonus_pool and rng.random() < 0.5:
        out.append(spawn_item(world, rng.choice(bonus_pool), None, qty=1, owner=npc, source="pregen"))
    return out
