"""Крафт: мастер + станок + рецепт + материалы → предмет. Мастерство СДВИГАЕТ распределение исхода
(качество / +mods / клеймо / прочность), брак рождает СКРЫТЫЙ flaw (тот же hidden-гейт) + хрупкость.
Починка/перековка — тот же трансформ, гейт по мастерству. Детерминированно (score + бросок по seed).

Крафтит и NPC-мастер (Capability из NpcState), и игрок (pc-Capability). LLM тут НЕ нужен — механика
табличная; флейвор-имя навешивает item_smith на слое игры (по желанию).
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from .model import Capability, normalize

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
    mod_target: str = ""             # что усиливает masterwork (attack | social:appearance | …)


def mastery(cap: Capability, station: str, reputation: int = 0, station_tier: int = 1) -> int:
    """Мастерство: профильная способность + намётанный глаз (компетенция) + станок + репутация."""
    ab = max((cap.mod(a) for a in _ABIL.get(station, ("dex",))), default=0)
    comp = 3 if _COMP.get(station) in cap.competencies else 0
    return ab + comp + station_tier + reputation


def _material_bonus(inputs) -> int:
    """Средний сдвиг от качества материалов-предметов (kind:material)."""
    qs = [{"crude": -1, "plain": 0, "fine": 1, "exquisite": 2}.get(i.get("quality"), 0)
          for i in (inputs or []) if isinstance(i, dict)]
    return round(sum(qs) / len(qs)) if qs else 0


def craft(cap: Capability, recipe: Recipe, *, seed: str, inputs=None,
          maker: dict | None = None, reputation: int = 0, station_tier: int = 1) -> dict:
    """Скрафтить предмет. maker={id,name} — для клейма. Возвращает фактшит."""
    roll = Random(f"craft|{seed}").randint(1, 20)
    m = mastery(cap, recipe.station, reputation, station_tier)
    margin = m + roll + _material_bonus(inputs) - recipe.dc
    quality = ("exquisite" if margin >= 10 else "fine" if margin >= 5
               else "plain" if margin >= 0 else "crude")
    mods, hidden, weak_at = [], [], 0.0
    if recipe.mod_target and quality in ("fine", "exquisite"):
        mods.append({"target": recipe.mod_target, "op": "add", "amount": 1 if quality == "fine" else 2,
                     "when": "equipped" if recipe.slot != "none" else "on_use"})
    if margin < 0:                                          # БРАК → скрытый порок + хрупкость
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
        "kind": recipe.out_kind, "name": recipe.name, "slot": recipe.slot,  # качество — отдельным полем (без грам. рода)
        "quality": quality, "worth": worth, "apparent_worth": worth, "mods": mods, "hidden": hidden,
        "durability": {"max": dur_max, "current": dur_max, "break_behavior": _BREAK.get(recipe.out_kind, "snap"),
                       "repair_dc": recipe.dc, "weak_at": weak_at},
        "make": {"maker_id": (maker or {}).get("id"), "maker_name": (maker or {}).get("name"),
                 "mastery": m, "margin": margin, "mark": mark},
    })


def repair(item: dict, cap: Capability, *, seed: str, station: str = "anvil") -> dict:
    """Починка/перековка — гейт по мастерству. Слабая рука чинит грубо (потолок просядет)."""
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
