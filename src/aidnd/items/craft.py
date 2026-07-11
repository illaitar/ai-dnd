"""NPC-artisan crafting (commission / repair): master + station + recipe → item. Mastery SHIFTS the
outcome distribution (quality / +mods / mark / durability); defects spawn a HIDDEN flaw + fragility.
Repair/reforge — same transform, gated by mastery. Deterministic (score + roll by seed).

(Player crafting no longer lives here — it walks the derivation graph, see aidnd.items.graph +
server.play.mechanics.items._do_craft. The old materials.json craft-path graph is retired.)

Key functions
-------------
Recipe : Dataclass defining a crafting recipe with DC, duration, station, mod target.
mastery(cap, station, reputation, station_tier) -> int : Calculate crafter's skill modifier.
craft(cap, recipe, *, seed, inputs, maker, reputation, station_tier) -> dict : Craft item with quality/mods/flaws based on roll.
repair(item, cap, *, seed, station) -> dict : Repair item durability, may degrade max durability if failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from .model import Capability, normalize

# NOTE: the old materials.json craft-path graph is retired — player crafting now walks the
# derivation graph (aidnd.items.graph + server.play.mechanics.items._do_craft). What remains here is
# the NPC-artisan engine (commission / repair): mastery + Recipe + craft() + repair().

STATIONS = ("anvil", "bench", "cauldron", "loom", "tannery")
_ABIL = {"anvil": ("str", "dex"), "bench": ("dex",), "cauldron": ("int", "wis"),
         "loom": ("dex",), "tannery": ("con", "str")}
_COMP = {"anvil": "metalwork", "bench": "leather", "cauldron": "herbs", "loom": "cloth", "tannery": "leather"}
_QFACT = {"crude": 0.6, "plain": 1.0, "fine": 1.4, "exquisite": 1.8}
_QRU = {"crude": "грубый", "plain": "простой", "fine": "добротный", "exquisite": "искусный"}
_BREAK = {"weapon": "snap", "tool": "snap", "armor": "fray", "trinket": "shatter",
          "consumable": "spoil", "key": "snap"}


@dataclass
class Recipe:
    out_kind: str
    name: str
    station: str
    base_worth: int = 8
    dur: int = 30
    dc: int = 10
    slot: str = "none"
    mod_target: str = ""             # what masterwork amplifies (attack | social:appearance | …)


# what a craftsman of each role takes on — SYSTEM DATA (not game layer code)
ROLE_RECIPES = {
    "кузнец": Recipe("weapon", "нож", "anvil", 8, 40, 10, "main_hand", "attack"),
    "знахарка": Recipe("consumable", "целебный отвар", "cauldron", 12, 6, 11, "none", "special:heal"),
    "сапожник": Recipe("armor", "сапоги", "bench", 14, 50, 11, "body", "social:appearance"),
    "дубильщик": Recipe("armor", "кожаный жилет", "tannery", 10, 45, 11, "body", "defense"),
    "лавочник": Recipe("trinket", "затейливая безделица", "bench", 6, 20, 12, "worn", ""),
    "трактирщик": Recipe("consumable", "кружка крепкого", "cauldron", 2, 4, 8, "none", ""),
    "мельник": Recipe("material", "мешок доброй муки", "bench", 3, 10, 9, "none", ""),
    "охотник": Recipe("weapon", "охотничий лук", "bench", 12, 45, 11, "main_hand", "attack"),
    "оружейник": Recipe("weapon", "тугой арбалет", "anvil", 18, 50, 12, "main_hand", "attack"),
}


def mastery(cap: Capability, station: str, reputation: int = 0, station_tier: int = 1) -> int:
    """Mastery: on-profile ability + trained eye (competency) + station + reputation."""
    ab = max((cap.mod(a) for a in _ABIL.get(station, ("dex",))), default=0)
    comp = 3 if _COMP.get(station) in cap.competencies else 0
    return ab + comp + station_tier + reputation


def _material_bonus(inputs) -> int:
    """Average shift from material-item quality (kind:material)."""
    qs = [{"crude": -1, "plain": 0, "fine": 1, "exquisite": 2}.get(i.get("quality"), 0)
          for i in (inputs or []) if isinstance(i, dict)]
    return round(sum(qs) / len(qs)) if qs else 0


def craft(cap: Capability, recipe: Recipe, *, seed: str, inputs=None,
          maker: dict | None = None, reputation: int = 0, station_tier: int = 1) -> dict:
    """Craft an item. maker={id,name} — for mark. Returns fact sheet."""
    roll = Random(f"craft|{seed}").randint(1, 20)
    m = mastery(cap, recipe.station, reputation, station_tier)
    margin = m + roll + _material_bonus(inputs) - recipe.dc
    quality = ("exquisite" if margin >= 10 else "fine" if margin >= 5
               else "plain" if margin >= 0 else "crude")
    mods, hidden, weak_at = [], [], 0.0
    if recipe.mod_target and quality in ("fine", "exquisite"):
        mods.append({"target": recipe.mod_target, "op": "add", "amount": 1 if quality == "fine" else 2,
                     "when": "equipped" if recipe.slot != "none" else "on_use"})
    if margin < 0:                                          # DEFECT → hidden flaw + fragility
        weak_at = 0.3
        hidden.append({"prop": "flaw", "value": "скрытая трещина в работе",
                       "fact": "в изделии изъян — переломится раньше срока",
                       "gate": {"via": "craft_eye", "dc": 12, "req": _COMP.get(recipe.station, "metalwork")},
                       "mods": [{"target": "durability", "op": "mul", "amount": 0.6,
                                 "when": "passive", "hidden": True}]})
    dur_max = max(1, round(recipe.dur * _QFACT[quality] * (1 + _material_bonus(inputs) * 0.1)))
    mark = (maker or {}).get("name", "") if (maker and quality in ("fine", "exquisite")) else ""
    worth = round(recipe.base_worth * _QFACT[quality]) + (5 if mark else 0)
    return normalize({
        "kind": recipe.out_kind, "name": recipe.name, "slot": recipe.slot,  # quality — separate field (no grammatical gender)
        "quality": quality, "worth": worth, "apparent_worth": worth, "mods": mods, "hidden": hidden,
        "durability": {"max": dur_max, "current": dur_max, "break_behavior": _BREAK.get(recipe.out_kind, "snap"),
                       "repair_dc": recipe.dc, "weak_at": weak_at},
        "make": {"maker_id": (maker or {}).get("id"), "maker_name": (maker or {}).get("name"),
                 "mastery": m, "margin": margin, "mark": mark},
    })


def repair(item: dict, cap: Capability, *, seed: str, station: str = "anvil") -> dict:
    """Repair/reforge — gate by mastery. Weak hand repairs coarsely (durability ceiling drops)."""
    if item.get("kind") == "consumable":
        return {"ok": False, "reason": "снадобья и съестное не чинятся — только заново"}
    d = item.get("durability")
    if not d:
        return {"ok": False, "reason": "чинить нечего"}
    roll = Random(f"repair|{seed}").randint(1, 20)
    if mastery(cap, station) + roll >= d["repair_dc"]:
        d["current"] = d["max"]
        return {"ok": True, "restored": True, "note": "как новое"}
    d["max"] = max(1, round(d["max"] * 0.8))
    d["current"] = d["max"]
    d["weak_at"] = max(d.get("weak_at", 0.0), 0.15)
    return {"ok": True, "restored": False, "note": "починка грубая — потолок прочности просел"}
