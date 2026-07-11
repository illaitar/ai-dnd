"""Combat model (5e-lite, Baldur's Gate spirit — simplified): unified Combatant from ANY source —
monster from bestiary (SRD data), NPC from pool (his mech), player (pc + weapon from bag). No hardcoded
types: everything from data.

Key functions
-------------
Combatant : unified combat model (HP/AC/damage for any combatant type).
from_monster(row, cid) -> Combatant : create combatant from SRD data.
from_npc(pid, name, mech, ...) -> Combatant : create NPC combatant.
from_pc(abilities, hp, max_hp, ...) -> Combatant : create PC combatant.
bestiary() -> list : load cached SRD monster database.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

_BESTIARY = None
_BPATH = os.path.join(os.path.dirname(__file__), "..", "content", "bestiary.json")

# weapon item quality → damage dice (data mapping from items system to combat)
WEAPON_DICE = {"crude": "1d4", "plain": "1d6", "fine": "1d8", "exquisite": "1d10"}
UNARMED_DICE = "1d4"

# ranged: weapon name substring (player/NPC) → range in cells (data, not if-chains)
WEAPON_RANGE = {"лук": 12, "арбалет": 15, "самострел": 15, "праща": 8,
                "дротик": 6, "метательн": 6, "сюрикен": 6}
# SRD monster attacks (by attack.name) → range in cells
MONSTER_RANGE = {"longbow": 12, "shortbow": 10, "sling": 8, "javelin": 6, "dart": 6,
                 "light crossbow": 15, "heavy crossbow": 15, "spit": 6, "acid spray": 4,
                 "fire breath": 4, "web": 6}


def _ranged(name: str, table: dict, default: int = 1) -> int:
    """Range by name (first substring match), else default (melee = 1)."""
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
    """SRD resist string → set of simple damage types (conservative: take only explicit words)."""
    out = set()
    for t in ("bludgeoning", "piercing", "slashing", "fire", "cold", "poison", "radiant", "necrotic",
              "acid", "lightning", "thunder"):                # +elemental types weapons can carry
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
    speed: int = 6                   # cells per turn (5 feet = 1 cell)
    init_mod: int = 0
    to_hit: int = 2
    dmg_dice: str = "1d6"
    dmg_bonus: int = 0
    dmg_type: str = "bludgeoning"
    reach: int = 1                   # melee reach (cells)
    range: int = 1                   # MAX attack range (cells): >1 = ranged (bow/crossbow)
    resist: set = field(default_factory=set)
    immune: set = field(default_factory=set)
    cr: float = 0.0
    kind: str = "npc"                # pc | npc | monster
    ref: str = ""                    # source id (srd:goblin / pool:0007 / pc)
    alive: bool = True
    dodging: bool = False
    fled: bool = False
    status: dict = field(default_factory=dict)   # {bound|asleep|afraid: rounds_left}
    on_hit: list = field(default_factory=list)   # weapon elemental payloads [{type,amount,ru}]

    def down(self) -> bool:
        return not self.alive or self.fled

    def incapacitated(self) -> bool:
        """Bound or asleep — no turn (afraid acts but avoids combat)."""
        return self.status.get("bound", 0) > 0 or self.status.get("asleep", 0) > 0

    def view(self) -> dict:
        return {"id": self.id, "name": self.name, "side": self.side, "x": self.x, "y": self.y,
                "hp": self.hp, "max_hp": self.max_hp, "ac": self.ac, "speed": self.speed,
                "alive": self.alive, "fled": self.fled, "dodging": self.dodging,
                "status": {k: v for k, v in self.status.items() if v > 0},
                "kind": self.kind, "ref": self.ref, "reach": self.reach, "range": self.range}


def from_monster(row: dict, cid: str) -> Combatant:
    atk = row.get("attack") or {}
    dice = str(atk.get("dice") or "1d4").split("+1d")[0]   # mixed dice simplified to first
    if not re.fullmatch(r"\d+d\d+", dice):
        dice = "1d6"
    rng = _ranged(atk.get("name", ""), MONSTER_RANGE, 1)   # archer/slinger strikes from range
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


NPC_HP_BASE = 10                     # NPC fighter toughness base (data, not magic code)


def from_npc(pid: str, name: str, mech: dict, hp: int | None = None,
             weapon: dict | None = None) -> Combatant:
    ab = mech.get("abilities") or {}
    smod, dmod, cmod = _mod(ab.get("str", 10)), _mod(ab.get("dex", 10)), _mod(ab.get("con", 10))
    brave = (mech.get("traits") or {}).get("bravery", 0.5)
    prof = round(brave * 3)                               # bravery = combat training proficiency
    hp = NPC_HP_BASE + cmod * 2 + round(brave * 6) if hp is None else hp   # endurance + bravery
    rng = _ranged((weapon or {}).get("name", ""), WEAPON_RANGE, 1)
    dice = WEAPON_DICE.get((weapon or {}).get("quality", ""), "1d6") if weapon else "1d6"
    atk = dmod if rng > 1 else max(smod, dmod)
    return Combatant(
        id=pid, name=name, side="party",
        hp=hp, max_hp=hp, ac=11 + dmod + (1 if brave > 0.7 else 0),   # equipped fighter is tougher
        speed=6, init_mod=dmod, to_hit=2 + atk + prof,
        dmg_dice=dice, dmg_bonus=atk + (1 if brave > 0.6 else 0) + int((weapon or {}).get("bonus", 0)),
        dmg_type="piercing" if rng > 1 else "slashing", range=rng,
        cr=0.25 + brave * 0.5, kind="npc", ref=pid)


def from_pc(abilities: dict, hp: int, max_hp: int, weapon: dict | None = None) -> Combatant:
    smod, dmod = _mod(abilities.get("str", 10)), _mod(abilities.get("dex", 10))
    dice = WEAPON_DICE.get((weapon or {}).get("quality", ""), UNARMED_DICE)
    rng = _ranged((weapon or {}).get("name", ""), WEAPON_RANGE, 1)
    return Combatant(
        id="pc", name="Странник", side="party",
        hp=hp, max_hp=max_hp, ac=10 + dmod, speed=6, init_mod=dmod,
        to_hit=2 + (dmod if rng > 1 else max(smod, dmod)),   # ranged relies on dexterity
        dmg_dice=dice, dmg_bonus=(dmod if rng > 1 else smod) + int((weapon or {}).get("bonus", 0)),
        range=rng,
        dmg_type="piercing" if rng > 1 else ("slashing" if weapon else "bludgeoning"),
        kind="pc", ref="pc")
