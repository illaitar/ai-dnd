"""Каталог SRD 5.1 (CC-BY-4.0): монстры → STAT_BLOCKS, предметы → шаблоны мира.

Аддитивно и НЕдеструктивно: курируемые LMoP-id не перезаписываются, а item_gen/
character_gen по-прежнему выдумывают новые предметы/персон. Полный каталог тянется
`scripts/fetch_srd.py` из open5e в content/srd/{monsters,items}.json; в репозитории
лежит стартовый набор, так что движок работает и без запуска скрипта.
"""

from __future__ import annotations

import json
import os
import re

from ..inventory.items import ItemTemplate
from ..rules.progression import MONSTER_XP
from ..rules.srd import STAT_BLOCKS, StatBlock

SRD_DIR = os.path.join(os.path.dirname(__file__), "srd")

# опыт за победу по CR (DMG) и бонус мастерства по CR
_XP_BY_CR = {0: 10, 0.125: 25, 0.25: 50, 0.5: 100, 1: 200, 2: 450, 3: 700, 4: 1100,
             5: 1800, 6: 2300, 7: 2900, 8: 3900, 9: 5000, 10: 5900, 11: 7200, 12: 8400,
             13: 10000, 14: 11500, 15: 13000, 16: 15000, 17: 18000, 20: 25000, 24: 62000}


def _prof_by_cr(cr: float) -> int:
    return 2 + max(0, (int(cr) - 1)) // 4 if cr >= 1 else 2


def _xp_by_cr(cr: float) -> int:
    keys = sorted(_XP_BY_CR)
    best = min(keys, key=lambda k: abs(k - cr))
    return _XP_BY_CR[best]


def _slug(name: str, prefix: str) -> str:
    return f"{prefix}:" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "x")


def _load(fn: str) -> list:
    path = os.path.join(SRD_DIR, fn)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# полные записи бестиария (механика + ЛОР: тип/размер/среда/чувства/языки/иммунитеты/атака/описание) —
# справочная база мира: NPC «подтягивают» её при разговоре, генераторы — при наполнении сцены
BESTIARY: dict[str, dict] = {}
SPELLS: dict[str, dict] = {}                              # справочный каталог заклинаний (имя/уровень/школа/описание)
MAGICITEMS: dict[str, dict] = {}                          # магпредметы (редкость/тип/настройка/эффект)
EQUIPMENT: dict[str, dict] = {}                           # снаряжение: оружие+броня (урон/AC/свойства/цена)
MATERIALS: dict[str, dict] = {}                           # материалы/ресурсы (тип/источник/ценность/применение)
FLORA: dict[str, dict] = {}                               # растения (тип/среда/применение/опасность)
CONDITIONS: dict[str, dict] = {}                          # состояния (имя/описание)
CLASSES: dict[str, dict] = {}                             # классы персонажей (имя/описание)
PLANES: dict[str, dict] = {}                              # планы бытия (имя/описание)

# ВАРИАЦИИ существ — набор атрибутов поверх базового стат-блока (имя/флейвор уточняет LLM при появлении)
MONSTER_VARIANTS = {
    "young":    {"ru": "молодой",    "cr": -1, "hp": 0.6, "ac": -1, "prof": -1},
    "seasoned": {"ru": "бывалый",    "cr": 1,  "hp": 1.3, "ac": 1,  "prof": 1},
    "elite":    {"ru": "матёрый",    "cr": 2,  "hp": 1.6, "ac": 2,  "prof": 2},
    "leader":   {"ru": "вожак",      "cr": 2,  "hp": 1.5, "ac": 1,  "prof": 2},
    "weakened": {"ru": "истощённый", "cr": -1, "hp": 0.5, "ac": -1, "prof": -1},
    "frenzied": {"ru": "бешеный",    "cr": 1,  "hp": 1.1, "ac": -2, "prof": 2},
    "ancient":  {"ru": "древний",    "cr": 3,  "hp": 2.0, "ac": 2,  "prof": 3},
    "scarred":  {"ru": "израненный", "cr": 0,  "hp": 0.7, "ac": 0,  "prof": 1},
}


def make_variant(base_ref: str, variant: str) -> StatBlock | None:
    """Производный стат-блок: базовое существо × модификатор вариации (бывалый/матёрый/…). Регистрирует и возвращает."""
    import dataclasses
    base = STAT_BLOCKS.get(base_ref)
    v = MONSTER_VARIANTS.get(variant)
    if not base or not v:
        return None
    ref = f"{base_ref}#{variant}"
    if ref in STAT_BLOCKS:
        return STAT_BLOCKS[ref]
    sb = dataclasses.replace(
        base, ref=ref, name=f"{v['ru'].capitalize()} {base.name.lower()}",
        hp=max(1, int(base.hp * v["hp"])), ac=max(1, base.ac + v["ac"]),
        proficiency=max(2, base.proficiency + v["prof"]), cr=max(0.0, base.cr + v["cr"]))
    STAT_BLOCKS[ref] = sb
    MONSTER_XP.setdefault(ref, _xp_by_cr(sb.cr))
    return sb


def load_srd(world) -> tuple[int, int]:
    """Регистрирует монстров и предметы SRD: курируемый seed + полный дамп от fetch_srd.
    Возвращает (добавлено монстров, предметов). Дубликаты по id игнорируются."""
    nm = ni = 0
    monsters = _load("seed_monsters.json") + _load("monsters.json")
    items = _load("seed_items.json") + _load("items.json")
    for m in monsters:
        ref = m.get("id") or _slug(m["name"], "srd")
        BESTIARY[ref] = m                                 # полная запись (механика+лор) для справки NPC/генераторов
        if ref in STAT_BLOCKS:                            # курируемые стат-блоки не трогаем
            continue
        cr = float(m.get("cr", 0))
        STAT_BLOCKS[ref] = StatBlock(
            ref=ref, name=m.get("name_ru") or m["name"], str_=m.get("str", 10), dex=m.get("dex", 10),
            con=m.get("con", 10), int_=m.get("int", 10), wis=m.get("wis", 10),
            cha=m.get("cha", 10), ac=m.get("ac", 10), hp=m.get("hp", 4),
            speed=m.get("speed", 30), proficiency=_prof_by_cr(cr), cr=cr,
            intelligence_score=m.get("int", 10), weapon=m.get("weapon", "unarmed"),
            traits=tuple(m.get("traits", [])))
        MONSTER_XP.setdefault(ref, _xp_by_cr(cr))
        nm += 1
    for it in items:
        tid = it.get("id") or _slug(it["name"], "tmpl")
        if tid in world.templates:                        # курируемые шаблоны приоритетны
            continue
        world.templates[tid] = ItemTemplate(
            template_id=tid, name=it["name"], category=it.get("category", "gear"),
            base_stats=it.get("base_stats", {}), weight=it.get("weight", 0.0),
            base_value=it.get("value", 0), rarity=it.get("rarity", "mundane"),
            stackable=it.get("stackable", False), max_stack=it.get("max_stack", 1),
            tags=tuple(it.get("tags", [])))
        ni += 1
    for s in _load("spells.json"):                        # справочные категории реестра
        SPELLS[s.get("id") or _slug(s["name"], "spell")] = s
    for it in _load("magicitems.json"):
        MAGICITEMS[it.get("id") or _slug(it["name"], "mitem")] = it
    for g in _load("equipment.json"):
        EQUIPMENT[g.get("id") or _slug(g["name"], "gear")] = g
    for mt in _load("materials.json"):
        MATERIALS[mt.get("id") or _slug(mt["name"], "mat")] = mt
    for fl in _load("flora.json"):
        FLORA[fl.get("id") or _slug(fl["name"], "flora")] = fl
    for c in _load("conditions.json"):
        CONDITIONS[c.get("id") or _slug(c["name"], "cond")] = c
    for cl in _load("classes.json"):
        CLASSES[cl.get("id") or _slug(cl["name"], "class")] = cl
    for pl in _load("planes.json"):
        PLANES[pl.get("id") or _slug(pl["name"], "plane")] = pl
    from . import lore_ref  # справочные базы → реестр lore_ref
    for _cat, _db in (("bestiary", BESTIARY), ("spells", SPELLS), ("magicitems", MAGICITEMS),
                      ("equipment", EQUIPMENT), ("materials", MATERIALS), ("flora", FLORA),
                      ("conditions", CONDITIONS), ("classes", CLASSES), ("planes", PLANES)):
        lore_ref.register(_cat, _db)
    return nm, ni
