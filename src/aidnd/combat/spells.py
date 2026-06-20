"""Подмножество боевых заклинаний SRD (док 09 §8).

Каждое заклинание — данные + резолвер. Атакующие используют бросок атаки заклинания,
спасброски считают DC = 8 + proficiency + модификатор характеристики каста. AoE
кладёт шаблон на сетку и может создавать поверхности.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Spell:
    key: str
    name: str
    level: int                  # 0 — заговор
    kind: str                   # attack | save | auto | heal | utility
    range_sq: int               # дальность в клетках
    damage: str = ""
    dtype: str = ""
    save_ability: str = ""
    shape: str = ""             # "" | cone3 | square2 | line
    creates: str = ""           # поверхность (fire/grease/...)


SPELLS = {
    # --- заговоры (0 круг) ---
    "firebolt": Spell("firebolt", "Огненный снаряд", 0, "attack", 24, "1d10", "fire"),
    "ray_of_frost": Spell("ray_of_frost", "Луч холода", 0, "attack", 12, "1d8", "cold"),
    "shocking_grasp": Spell("shocking_grasp", "Шокирующее прикосновение", 0, "attack", 1, "1d8", "lightning"),
    "mage_hand": Spell("mage_hand", "Рука мага", 0, "utility", 6),
    "sacred_flame": Spell("sacred_flame", "Священное пламя", 0, "save", 12, "1d8", "radiant",
                          save_ability="dex"),
    "toll_the_dead": Spell("toll_the_dead", "Похоронный звон", 0, "save", 12, "1d8", "necrotic",
                           save_ability="wis"),
    "light": Spell("light", "Свет", 0, "utility", 6),
    "resistance": Spell("resistance", "Сопротивление", 0, "utility", 1),
    # --- 1 круг ---
    "magic_missile": Spell("magic_missile", "Волшебная стрела", 1, "auto", 24, "1d4+1", "force"),
    "burning_hands": Spell("burning_hands", "Огненные ладони", 1, "save", 3, "3d6", "fire",
                           save_ability="dex", shape="cone3", creates="fire"),
    "thunderwave": Spell("thunderwave", "Волна грома", 1, "save", 3, "2d8", "thunder",
                         save_ability="con", shape="cone3"),
    "grease": Spell("grease", "Жир", 1, "utility", 12, shape="square2", creates="grease"),
    "cure_wounds": Spell("cure_wounds", "Лечение ран", 1, "heal", 1, "1d8"),
    "healing_word": Spell("healing_word", "Слово исцеления", 1, "heal", 12, "1d4"),
    "guiding_bolt": Spell("guiding_bolt", "Направляющий снаряд", 1, "attack", 24, "4d6", "radiant"),
    "bless": Spell("bless", "Благословение", 1, "utility", 6),
    "shield_of_faith": Spell("shield_of_faith", "Щит веры", 1, "utility", 12),
    # --- 2 круг ---
    "spiritual_weapon": Spell("spiritual_weapon", "Духовное оружие", 2, "auto", 12, "1d8", "force"),
    "aid": Spell("aid", "Помощь", 2, "heal", 6, "2d4"),
    "scorching_ray": Spell("scorching_ray", "Опаляющий луч", 2, "attack", 24, "2d6", "fire"),
    "shatter": Spell("shatter", "Раскол", 2, "save", 12, "3d8", "thunder", save_ability="con",
                     shape="cone3"),
    # --- 3 круг ---
    "fireball": Spell("fireball", "Огненный шар", 3, "save", 24, "8d6", "fire", save_ability="dex",
                      shape="cone3", creates="fire"),
    "spirit_guardians": Spell("spirit_guardians", "Стражи веры", 3, "save", 3, "3d8", "radiant",
                              save_ability="wis"),
    "mass_healing_word": Spell("mass_healing_word", "Массовое слово исцеления", 3, "heal", 12, "1d4"),
}


def cone_cells(grid, origin: tuple, toward: tuple, length: int) -> list:
    """Грубый конус: клетки в пределах length в сторону цели (квадрант)."""
    ox, oy = origin
    tx, ty = toward
    dx = (tx > ox) - (tx < ox)
    dy = (ty > oy) - (ty < oy)
    out = []
    for r in range(1, length + 1):
        for s in range(-r, r + 1):
            if dx and not dy:
                c = (ox + dx * r, oy + s)
            elif dy and not dx:
                c = (ox + s, oy + dy * r)
            else:                       # диагональ
                c = (ox + dx * r, oy + dy * max(0, r + min(0, s)))
            if grid.in_bounds(*c):
                out.append(c)
    return list(dict.fromkeys(out))


def square_cells(grid, center: tuple, half: int) -> list:
    cx, cy = center
    return [(x, y) for x in range(cx - half, cx + half + 1)
            for y in range(cy - half, cy + half + 1) if grid.in_bounds(x, y)]
