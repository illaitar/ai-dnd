"""Прокачка 5e (уровни 1–5): опыт, таблицы классов, фичи и выборы при апе.

Данные-таблицы + чистые функции. Применение выборов — событийно (level_up), поэтому
лоад/реплей восстанавливают тот же лист. Заклинатели (жрец/маг) получают ячейки,
заговоры и список заклинаний; выбор заклинаний — часть выборов уровня.
"""

from __future__ import annotations

# --------------------------------------------------------------- опыт ------- #
XP_THRESHOLDS = {1: 0, 2: 300, 3: 900, 4: 2700, 5: 6500}
PROF_BY_LEVEL = {1: 2, 2: 2, 3: 2, 4: 2, 5: 3}
MAX_LEVEL = 5

# опыт за побеждённого монстра по его стат-блоку (PHB/MM)
MONSTER_XP = {
    "srd:commoner": 10, "srd:guard": 25, "srd:acolyte": 25, "srd:bandit": 25,
    "srd:goblin": 50, "srd:wolf": 50, "srd:scout": 100, "srd:thug": 100,
    "srd:drow": 100, "srd:bugbear": 200, "srd:veteran": 700, "srd:mage": 700,
}


def level_for_xp(xp: int) -> int:
    lvl = 1
    for level, thr in sorted(XP_THRESHOLDS.items()):
        if xp >= thr:
            lvl = level
    return min(MAX_LEVEL, lvl)


def next_threshold(level: int) -> int | None:
    return XP_THRESHOLDS.get(level + 1)


def hp_gain(hit_die: int, con_mod: int) -> int:
    """Среднее по правилу 5e: hit_die/2 + 1 + мод. Телосложения (минимум 1)."""
    return max(1, hit_die // 2 + 1 + con_mod)


# ----------------------------------------------- заклинательство ----------- #
# ячейки полного заклинателя (жрец/маг) по уровню персонажа
FULL_SLOTS = {
    1: {"1": 2}, 2: {"1": 3}, 3: {"1": 4, "2": 2},
    4: {"1": 4, "2": 3}, 5: {"1": 4, "2": 3, "3": 2},
}
CANTRIPS_KNOWN = {1: 3, 2: 3, 3: 3, 4: 4, 5: 4}
# максимальный круг заклинаний, доступный на уровне персонажа
MAX_SPELL_CIRCLE = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3}

# заклинания по классу и кругу (ключи — из combat/spells.py)
CLASS_SPELLS = {
    "cleric": {
        0: ["sacred_flame", "toll_the_dead", "light", "resistance"],
        1: ["cure_wounds", "healing_word", "guiding_bolt", "bless"],
        2: ["spiritual_weapon", "aid"],
        3: ["spirit_guardians", "mass_healing_word"],
    },
    "wizard": {
        0: ["firebolt", "ray_of_frost", "shocking_grasp", "mage_hand"],
        1: ["magic_missile", "burning_hands", "grease", "thunderwave"],
        2: ["scorching_ray", "shatter"],
        3: ["fireball"],
    },
}

# ----------------------------------------------- варианты выборов ---------- #
FIGHTING_STYLES = {
    "defense": {"name": "Оборона", "desc": "+1 к КД, пока носишь броню."},
    "dueling": {"name": "Дуэлянт", "desc": "+2 к урону одноручным оружием без второго."},
    "great_weapon": {"name": "Большое оружие", "desc": "перебрасывать 1–2 на кубах урона."},
    "archery": {"name": "Стрельба", "desc": "+2 к попаданию дальнобойным оружием."},
}
FEATS = {
    "tough": {"name": "Крепкий", "desc": "+2 к максимуму HP за уровень."},
    "alert": {"name": "Бдительный", "desc": "+5 к инициативе, нельзя застать врасплох."},
    "lucky": {"name": "Везунчик", "desc": "3 жетона удачи на переброс."},
    "war_caster": {"name": "Боевой маг", "desc": "преимущество на спасбросок концентрации."},
    "athlete": {"name": "Атлет", "desc": "+1 к Силе или Ловкости, быстрый подъём."},
}
SUBCLASSES = {
    "fighter": {"champion": {"name": "Чемпион", "desc": "улучшенный крит (19–20)."},
                "battle_master": {"name": "Мастер боя", "desc": "боевые приёмы и кубики превосходства."}},
    "rogue": {"thief": {"name": "Вор", "desc": "быстрые руки, верхолаз."},
              "assassin": {"name": "Убийца", "desc": "преимущество и крит по застигнутым врасплох."}},
    "cleric": {"life": {"name": "Домен Жизни", "desc": "усиленное лечение, тяжёлая броня."},
               "light": {"name": "Домен Света", "desc": "огненные заклинания, оберегающая вспышка."}},
    "wizard": {"evocation": {"name": "Воплощение", "desc": "точные мощные área-заклинания."},
               "abjuration": {"name": "Ограждение", "desc": "защитный барьер из магии."}},
}

# имена фич для листа персонажа
FEATURE_NAMES = {
    "second_wind": "Второе дыхание", "action_surge": "Всплеск действий",
    "extra_attack": "Дополнительная атака", "sneak_attack": "Скрытая атака",
    "cunning_action": "Хитрое действие", "uncanny_dodge": "Невероятное уклонение",
    "spellcasting": "Заклинательство", "channel_divinity": "Божественный канал",
    "destroy_undead": "Изгнание нежити",
}

# --------------------------------------------------------------- классы ---- #
# features[level] = [(feature_id, choice_kind|None)]. choice_kind != None → выбор игрока.
CLASSES = {
    "fighter": {
        "name": "Воин", "archetype": "fighter", "hit_die": 10, "saves": ["str", "con"],
        "skills": ["acrobatics", "animal_handling", "athletics", "history", "insight",
                   "intimidation", "perception", "survival"], "skill_count": 2, "caster": None,
        "default_skills": ["athletics", "perception"],
        "features": {1: [("second_wind", None), ("fighting_style", "fighting_style")],
                     2: [("action_surge", None)], 3: [("subclass", "subclass")],
                     4: [("asi", "asi")], 5: [("extra_attack", None)]},
    },
    "rogue": {
        "name": "Плут", "archetype": "rogue", "hit_die": 8, "saves": ["dex", "int"],
        "skills": ["acrobatics", "athletics", "deception", "insight", "intimidation",
                   "investigation", "perception", "performance", "persuasion",
                   "sleight_of_hand", "stealth"], "skill_count": 4, "caster": None,
        "default_skills": ["stealth", "perception", "acrobatics", "deception"],
        "features": {1: [("sneak_attack", None), ("expertise", "expertise")],
                     2: [("cunning_action", None)], 3: [("subclass", "subclass")],
                     4: [("asi", "asi")], 5: [("uncanny_dodge", None)]},
    },
    "cleric": {
        "name": "Жрец", "archetype": "priest", "hit_die": 8, "saves": ["wis", "cha"],
        "caster": "wis",
        "skills": ["history", "insight", "medicine", "persuasion", "religion"], "skill_count": 2,
        "default_skills": ["insight", "religion"],
        "features": {1: [("spellcasting", None), ("subclass", "subclass"), ("spells", "spells")],
                     2: [("channel_divinity", None), ("spells", "spells")],
                     3: [("spells", "spells")], 4: [("asi", "asi"), ("spells", "spells")],
                     5: [("destroy_undead", None), ("spells", "spells")]},
    },
    "wizard": {
        "name": "Маг", "archetype": "mage", "hit_die": 6, "saves": ["int", "wis"],
        "caster": "int",
        "skills": ["arcana", "history", "insight", "investigation", "medicine", "religion"],
        "skill_count": 2, "default_skills": ["arcana", "investigation"],
        "features": {1: [("spellcasting", None), ("spells", "spells")],
                     2: [("subclass", "subclass"), ("spells", "spells")],
                     3: [("spells", "spells")], 4: [("asi", "asi"), ("spells", "spells")],
                     5: [("spells", "spells")]},
    },
}


def slots_for(class_id: str, level: int) -> dict:
    return dict(FULL_SLOTS.get(level, {})) if CLASSES.get(class_id, {}).get("caster") else {}


def spells_to_learn(class_id: str, level: int) -> int:
    """Сколько заклинаний выбрать на этом уровне (маг учит 2/ур.; жрец +1 «подготовлено»)."""
    if class_id == "wizard":
        return 2 if level > 1 else 4          # стартовая книга — 4 заклинания 1 круга
    if class_id == "cleric":
        return 1                              # +1 подготовленное за уровень (упрощённо)
    return 0


def available_spells(class_id: str, level: int) -> list[str]:
    circ = MAX_SPELL_CIRCLE.get(level, 1)
    pool = CLASS_SPELLS.get(class_id, {})
    out = []
    for c in range(1, circ + 1):
        out += pool.get(c, [])
    return out


SKILL_RU = {
    "acrobatics": "Акробатика", "animal_handling": "Уход за животными", "arcana": "Магия",
    "athletics": "Атлетика", "deception": "Обман", "history": "История", "insight": "Проницательность",
    "intimidation": "Запугивание", "investigation": "Анализ", "medicine": "Медицина",
    "nature": "Природа", "perception": "Внимательность", "performance": "Выступление",
    "persuasion": "Убеждение", "religion": "Религия", "sleight_of_hand": "Ловкость рук",
    "stealth": "Скрытность", "survival": "Выживание",
}
ABIL_RU = {"str": "Силе", "dex": "Ловкости", "con": "Телосложению",
           "int": "Интеллекту", "wis": "Мудрости", "cha": "Харизме"}


def feature_label(fid: str, payload: str | None = None) -> str:
    if fid == "fighting_style":
        return "Боевой стиль: " + FIGHTING_STYLES.get(payload, {}).get("name", payload or "")
    if fid == "asi":
        return "Рост характеристик / черта"
    if fid == "expertise":
        return "Компетентность"
    if fid == "subclass":
        return payload or "Архетип"
    return FEATURE_NAMES.get(fid, fid)
