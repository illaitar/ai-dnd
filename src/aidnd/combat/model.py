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
    reach: int = 1                   # дальность атаки в клетках
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
                "kind": self.kind, "ref": self.ref, "reach": self.reach}


def from_monster(row: dict, cid: str) -> Combatant:
    atk = row.get("attack") or {}
    dice = str(atk.get("dice") or "1d4").split("+1d")[0]   # смешанные кости упрощаем до первой
    if not re.fullmatch(r"\d+d\d+", dice):
        dice = "1d6"
    wtype = "slashing" if "sword" in (row.get("weapon") or "") else "piercing" \
        if atk.get("name", "").lower() in ("bite", "sting") else "bludgeoning"
    return Combatant(
        id=cid, name=row.get("name_ru") or row["name"], side="foes",
        hp=int(row["hp"]), max_hp=int(row["hp"]), ac=int(row["ac"]),
        speed=max(2, int(row.get("speed", 30)) // 5), init_mod=_mod(row.get("dex", 10)),
        to_hit=int(atk.get("hit", 2 + _mod(row.get("str", 10)))),
        dmg_dice=dice, dmg_bonus=int(atk.get("bonus", 0)), dmg_type=wtype,
        resist=_resist_types(row.get("resist", "")), immune=_resist_types(row.get("immune", "")),
        cr=float(row.get("cr", 0)), kind="monster", ref=row["id"])


def from_npc(pid: str, name: str, mech: dict, hp: int | None = None) -> Combatant:
    ab = mech.get("abilities") or {}
    smod, dmod = _mod(ab.get("str", 10)), _mod(ab.get("dex", 10))
    brave = (mech.get("traits") or {}).get("bravery", 0.5)
    hp = 10 if hp is None else hp
    return Combatant(
        id=pid, name=name, side="party",
        hp=hp, max_hp=hp, ac=10 + dmod,
        speed=6, init_mod=dmod, to_hit=2 + max(smod, dmod),
        dmg_dice="1d6", dmg_bonus=smod, dmg_type="slashing",
        cr=0.25 + brave * 0.5, kind="npc", ref=pid)


def from_pc(abilities: dict, hp: int, max_hp: int, weapon: dict | None = None) -> Combatant:
    smod, dmod = _mod(abilities.get("str", 10)), _mod(abilities.get("dex", 10))
    dice = WEAPON_DICE.get((weapon or {}).get("quality", ""), UNARMED_DICE)
    return Combatant(
        id="pc", name="Странник", side="party",
        hp=hp, max_hp=max_hp, ac=10 + dmod, speed=6, init_mod=dmod,
        to_hit=2 + max(smod, dmod), dmg_dice=dice, dmg_bonus=smod,
        dmg_type="slashing" if weapon else "bludgeoning", kind="pc", ref="pc")
