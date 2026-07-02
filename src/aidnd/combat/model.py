"""Боевая модель (5e-lite, дух Baldur's Gate — упрощённо): единый Combatant из ЛЮБОГО источника —
монстр бестиария (данные SRD), NPC пула (его mech), игрок (pc + оружие из сумки). Никакого
хардкода видов: всё из данных.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

_BESTIARY = None
_BPATH = os.path.join(os.path.dirname(__file__), "..", "content", "bestiary.json")

# качество оружия-предмета → кость урона (данные-маппинг предметной системы на бой)
WEAPON_DICE = {"crude": "1d4", "plain": "1d6", "fine": "1d8", "exquisite": "1d10"}
UNARMED_DICE = "1d4"

# дальнобой: подстрока имени ПРЕДМЕТА игрока/NPC → дальность в клетках (данные, не if-цепочки)
WEAPON_RANGE = {"лук": 12, "арбалет": 15, "самострел": 15, "праща": 8,
                "дротик": 6, "метательн": 6, "сюрикен": 6}
# атаки монстров SRD (по имени attack.name) → дальность в клетках
MONSTER_RANGE = {"longbow": 12, "shortbow": 10, "sling": 8, "javelin": 6, "dart": 6,
                 "light crossbow": 15, "heavy crossbow": 15, "spit": 6, "acid spray": 4,
                 "fire breath": 4, "web": 6}


def _ranged(name: str, table: dict, default: int = 1) -> int:
    """Дальность по имени (первое совпадение подстроки), иначе default (ближний = 1)."""
    n = (name or "").lower()
    for kw, rng in table.items():
        if kw in n:
            return rng
    return default


def bestiary() -> list:
    global _BESTIARY
    if _BESTIARY is None:
        with open(_BPATH, encoding="utf-8") as f:
            _BESTIARY = json.load(f)
    return _BESTIARY


def _mod(score: int) -> int:
    return (int(score) - 10) // 2


def _resist_types(s: str) -> set:
    """Строка резистов SRD → набор простых типов урона (щадяще: берём только явные слова)."""
    out = set()
    for t in ("bludgeoning", "piercing", "slashing", "fire", "cold", "poison", "radiant", "necrotic"):
        if t in (s or "").lower():
            out.add(t)
    return out


@dataclass
class Combatant:
    id: str
    name: str
    side: str                        # party | foes
    x: int = 0
    y: int = 0
    hp: int = 10
    max_hp: int = 10
    ac: int = 10
    speed: int = 6                   # клетки за ход (5 футов = 1 клетка)
    init_mod: int = 0
    to_hit: int = 2
    dmg_dice: str = "1d6"
    dmg_bonus: int = 0
    dmg_type: str = "bludgeoning"
    reach: int = 1                   # ближняя досягаемость (клетки)
    range: int = 1                   # МАКС дальность атаки (клетки): >1 = дальнобой (лук/арбалет)
    resist: set = field(default_factory=set)
    immune: set = field(default_factory=set)
    cr: float = 0.0
    kind: str = "npc"                # pc | npc | monster
    ref: str = ""                    # id источника (srd:goblin / pool:0007 / pc)
    alive: bool = True
    dodging: bool = False
    fled: bool = False

    def down(self) -> bool:
        return not self.alive or self.fled

    def view(self) -> dict:
        return {"id": self.id, "name": self.name, "side": self.side, "x": self.x, "y": self.y,
                "hp": self.hp, "max_hp": self.max_hp, "ac": self.ac, "speed": self.speed,
                "alive": self.alive, "fled": self.fled, "dodging": self.dodging,
                "kind": self.kind, "ref": self.ref, "reach": self.reach, "range": self.range}


def from_monster(row: dict, cid: str) -> Combatant:
    atk = row.get("attack") or {}
    dice = str(atk.get("dice") or "1d4").split("+1d")[0]   # смешанные кости упрощаем до первой
    if not re.fullmatch(r"\d+d\d+", dice):
        dice = "1d6"
    rng = _ranged(atk.get("name", ""), MONSTER_RANGE, 1)   # лучник/пращник бьёт издали
    wtype = "slashing" if "sword" in (row.get("weapon") or "") else "piercing" \
        if (atk.get("name", "").lower() in ("bite", "sting") or rng > 1) else "bludgeoning"
    return Combatant(
        id=cid, name=row.get("name_ru") or row["name"], side="foes",
        hp=int(row["hp"]), max_hp=int(row["hp"]), ac=int(row["ac"]),
        speed=max(2, int(row.get("speed", 30)) // 5), init_mod=_mod(row.get("dex", 10)),
        to_hit=int(atk.get("hit", 2 + _mod(row.get("str", 10)))),
        dmg_dice=dice, dmg_bonus=int(atk.get("bonus", 0)), dmg_type=wtype, range=rng,
        resist=_resist_types(row.get("resist", "")), immune=_resist_types(row.get("immune", "")),
        cr=float(row.get("cr", 0)), kind="monster", ref=row["id"])


def from_npc(pid: str, name: str, mech: dict, hp: int | None = None,
             weapon: dict | None = None) -> Combatant:
    ab = mech.get("abilities") or {}
    smod, dmod = _mod(ab.get("str", 10)), _mod(ab.get("dex", 10))
    brave = (mech.get("traits") or {}).get("bravery", 0.5)
    hp = 10 if hp is None else hp
    rng = _ranged((weapon or {}).get("name", ""), WEAPON_RANGE, 1)
    dice = WEAPON_DICE.get((weapon or {}).get("quality", ""), "1d6") if weapon else "1d6"
    return Combatant(
        id=pid, name=name, side="party",
        hp=hp, max_hp=hp, ac=10 + dmod,
        speed=6, init_mod=dmod, to_hit=2 + (dmod if rng > 1 else max(smod, dmod)),
        dmg_dice=dice, dmg_bonus=(dmod if rng > 1 else smod),
        dmg_type="piercing" if rng > 1 else "slashing", range=rng,
        cr=0.25 + brave * 0.5, kind="npc", ref=pid)


def from_pc(abilities: dict, hp: int, max_hp: int, weapon: dict | None = None) -> Combatant:
    smod, dmod = _mod(abilities.get("str", 10)), _mod(abilities.get("dex", 10))
    dice = WEAPON_DICE.get((weapon or {}).get("quality", ""), UNARMED_DICE)
    rng = _ranged((weapon or {}).get("name", ""), WEAPON_RANGE, 1)
    return Combatant(
        id="pc", name="Странник", side="party",
        hp=hp, max_hp=max_hp, ac=10 + dmod, speed=6, init_mod=dmod,
        to_hit=2 + (dmod if rng > 1 else max(smod, dmod)),   # дальнобой опирается на ловкость
        dmg_dice=dice, dmg_bonus=(dmod if rng > 1 else smod), range=rng,
        dmg_type="piercing" if rng > 1 else ("slashing" if weapon else "bludgeoning"),
        kind="pc", ref="pc")
