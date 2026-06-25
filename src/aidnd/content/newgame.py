"""Опции старта новой игры: класс персонажа, стартовое снаряжение, сценарий.

Класс задаёт характеристики/навыки/HP, снаряжение — пак предметов с экипировкой,
сценарий — стартовую локацию, флаги мира и спутников. Всё детерминировано: одни и
те же (seed, scenario, pc_spec) дают тот же пре-ген (основа сейв/лоада, док 08 §5).
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
#  Классы (старт 1 ур.). stats = (str, dex, con, int, wis, cha). Механика       #
#  (кость хитов, спасброски, навыки, фичи, заклинания) — в rules/progression.   #
# --------------------------------------------------------------------------- #
CLASSES: dict[str, dict] = {
    "fighter": {
        "name": "Воин", "archetype": "fighter",
        "desc": "Стойкий боец ближнего боя: меч, щит, тяжёлая броня.",
        "stats": (16, 14, 14, 10, 12, 10), "kit": "sword_board",
    },
    "rogue": {
        "name": "Плут", "archetype": "rogue",
        "desc": "Ловкий и скрытный: клинки, лук, точные удары из тени.",
        "stats": (10, 16, 14, 12, 13, 12), "kit": "blades",
    },
    "cleric": {
        "name": "Жрец", "archetype": "priest",
        "desc": "Служитель веры: булава, кольчуга, заклинания и лечение.",
        "stats": (13, 10, 14, 10, 16, 12), "kit": "mace_mail",
    },
    "wizard": {
        "name": "Маг", "archetype": "mage",
        "desc": "Хрупкий, но опасный: жезл, тайная магия, дальний урон.",
        "stats": (9, 14, 14, 16, 12, 10), "kit": "arcane",
    },
}

# --------------------------------------------------------------------------- #
#  Снаряжение: equip=(tmpl, slot, instance_id), carry=(tmpl, qty, instance_id) #
#  ВАЖНО: id у «sword_board» оставлены прежними (it:hero_sword/...) — на них    #
#  опираются тесты дефолтного воина.                                           #
# --------------------------------------------------------------------------- #
KITS: dict[str, dict] = {
    "sword_board": {
        "name": "Меч и щит", "blurb": "Длинный меч, кольчужная рубаха, щит, 2 зелья",
        "equip": [("tmpl:longsword", "main_hand", "it:hero_sword"),
                  ("tmpl:chain_shirt", "armor", "it:hero_armor"),
                  ("tmpl:shield", "off_hand", "it:hero_shield")],
        "carry": [("tmpl:potion_healing", 2, "it:hero_potions"),
                  ("tmpl:rations", 3, "it:hero_rations")],
        "wallet": {"gp": 25, "sp": 30},
    },
    "blades": {
        "name": "Клинки и лук", "blurb": "Короткий меч, кинжал, клёпаная кожа, лук",
        "equip": [("tmpl:shortsword", "main_hand", "it:hero_blade"),
                  ("tmpl:dagger", "off_hand", "it:hero_dagger"),
                  ("tmpl:studded_leather", "armor", "it:hero_armor")],
        "carry": [("tmpl:shortbow", 1, "it:hero_bow"),
                  ("tmpl:potion_healing", 1, "it:hero_potions"),
                  ("tmpl:rations", 3, "it:hero_rations")],
        "wallet": {"gp": 35, "sp": 10},
    },
    "mace_mail": {
        "name": "Булава и кольчуга", "blurb": "Булава, чешуйчатый доспех, щит, 2 зелья",
        "equip": [("tmpl:mace", "main_hand", "it:hero_mace"),
                  ("tmpl:scale_mail", "armor", "it:hero_armor"),
                  ("tmpl:shield", "off_hand", "it:hero_shield")],
        "carry": [("tmpl:potion_healing", 2, "it:hero_potions"),
                  ("tmpl:rations", 3, "it:hero_rations")],
        "wallet": {"gp": 20, "sp": 20},
    },
    "arcane": {
        "name": "Тайные искусства", "blurb": "Кинжал, кожаная броня, жезл магических снарядов",
        "equip": [("tmpl:dagger", "main_hand", "it:hero_dagger"),
                  ("tmpl:leather", "armor", "it:hero_armor")],
        "carry": [("tmpl:wand_magic_missiles", 1, "it:hero_wand"),
                  ("tmpl:potion_healing", 2, "it:hero_potions")],
        "wallet": {"gp": 40, "sp": 0},
    },
}

# --------------------------------------------------------------------------- #
#  Сценарии: стартовая конфигурация одного и того же мира                      #
# --------------------------------------------------------------------------- #
SCENARIOS: dict[str, dict] = {
    "arrival": {
        "name": "Прибытие в Фэндалин",
        "desc": "Ты только добрался до фронтирного городка — слухи, зацепки, первое знакомство.",
        "intro": "Дорога позади. Ты входишь в «Каменный Холм» — отогреться и осмотреться.",
        "start": "building:stonehill_inn", "flags": [], "companions": [],
    },
    "escort": {
        "name": "Эскорт к руднику",
        "desc": "Вы вели припасы и Гундрена к Пещере Эха Волн — но на тракте неспокойно.",
        "intro": "Дикие земли вокруг. Сильдар рядом; свежие следы засады уходят на запад.",
        "start": "place:phandalin_wilds", "flags": ["escort_active"],
        "companions": [], "reveals": ["faction:cragmaw"],   # напарник временно отключён (тест соло)
    },
    "redbrands": {
        "name": "Логово Красных плащей",
        "desc": "Красные плащи терроризируют город из поместья Тресендар. Пора в их укрытие.",
        "intro": "Поместье Тресендар. За обвалившейся стеной — лаз в подземелье Красных плащей.",
        "start": "building:tresendar_manor", "flags": ["redbrands_alerted"], "companions": [],
        "reveals": ["faction:redbrands"],
    },
}


def default_scenario() -> str:
    return "arrival"


def default_pc_spec() -> dict:
    return {"klass": "fighter", "kit": "sword_board", "name": "Герой"}


def resolve_pc_spec(spec: dict | None) -> dict:
    """Нормализовать выбор персонажа: класс, снаряжение, имя и набор навыков (по классу)."""
    from ..rules.progression import CLASSES as PROG
    spec = dict(spec or {})
    klass = spec.get("klass") if spec.get("klass") in CLASSES else "fighter"
    kit = spec.get("kit") if spec.get("kit") in KITS else CLASSES[klass]["kit"]
    cls = PROG[klass]
    chosen, out = spec.get("skills") or [], []
    for s in chosen:                                   # валидные выбранные навыки класса
        if s in cls["skills"] and s not in out:
            out.append(s)
    for s in cls.get("default_skills", []) + cls["skills"]:   # добить дефолтами класса
        if len(out) >= cls["skill_count"]:
            break
        if s not in out:
            out.append(s)
    skills = out[:cls["skill_count"]]
    return {"klass": klass, "kit": kit, "name": (spec.get("name") or "Герой")[:24],
            "race": spec.get("race", "human"), "skills": skills,
            "l1": _resolve_l1(klass, spec.get("l1") or {}, skills)}


def _resolve_l1(klass: str, l1: dict, skills: list[str]) -> dict:
    """Выборы 1 уровня (стиль/домен/компетентность). Невалидное → разумный дефолт."""
    from ..rules.progression import FIGHTING_STYLES, SUBCLASSES
    if klass == "fighter":
        fs = l1.get("fighting_style")
        return {"fighting_style": fs if fs in FIGHTING_STYLES else "defense"}
    if klass == "cleric":
        doms = SUBCLASSES.get("cleric", {})
        sub = l1.get("subclass")
        return {"subclass": sub if sub in doms else next(iter(doms), None)}
    if klass == "rogue":
        ex = [s for s in (l1.get("expertise") or []) if s in skills]
        return {"expertise": ex[:2] if len(ex) >= 2 else skills[:2]}
    return {}


def creation_choices(class_id: str) -> list[dict]:
    """Выборы 1 уровня для экрана создания (стиль воина, домен жреца, экспертиза плута)."""
    from ..rules.progression import FIGHTING_STYLES, SUBCLASSES
    if class_id == "fighter":
        return [{"id": "fighting_style", "label": "Боевой стиль", "pick": 1,
                 "options": [{"id": k, "name": v["name"], "desc": v["desc"]}
                             for k, v in FIGHTING_STYLES.items()]}]
    if class_id == "cleric":
        return [{"id": "subclass", "label": "Жреческий домен", "pick": 1,
                 "options": [{"id": k, "name": v["name"], "desc": v["desc"]}
                             for k, v in SUBCLASSES["cleric"].items()]}]
    if class_id == "rogue":
        return [{"id": "expertise", "label": "Компетентность (×2 мастерство): выбери 2 навыка",
                 "pick": 2, "from": "skills"}]
    return []


def options() -> dict:
    """Данные для экрана новой игры (классы с навыками, выборами 1 ур., снаряжение, сценарии)."""
    from ..rules.progression import CLASSES as PROG
    from ..rules.progression import SKILL_RU
    return {
        "classes": [{"id": k, "name": v["name"], "desc": v["desc"], "kit": v["kit"],
                     "caster": bool(PROG[k]["caster"]), "skill_count": PROG[k]["skill_count"],
                     "skills": [{"id": s, "name": SKILL_RU.get(s, s)} for s in PROG[k]["skills"]],
                     "l1": creation_choices(k)}
                    for k, v in CLASSES.items()],
        "kits": [{"id": k, "name": v["name"], "blurb": v["blurb"]} for k, v in KITS.items()],
        "scenarios": [{"id": k, "name": v["name"], "desc": v["desc"]}
                      for k, v in SCENARIOS.items()],
    }
