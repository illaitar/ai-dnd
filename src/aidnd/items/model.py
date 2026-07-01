"""Модель предмета: фактшит в ДВА слоя знания — surface (видно, может врать) + hidden[] (истина под
гейтами осмотра). Модификаторы системно-нейтральны (соц-ось mind/функции/цена/улики работают сейчас,
боевые спят до боёвки). Предмет — dict-фактшит (как здания/персоны), логика — функции рядом.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("weapon", "armor", "tool", "trinket", "consumable", "key", "document", "valuable", "material", "misc")
SLOTS = ("main_hand", "off_hand", "body", "head", "worn", "none")
QUALITY = ("crude", "plain", "fine", "exquisite")
GATE_VIA = ("glance", "handle", "appraise", "lore", "craft_eye", "tool", "context", "use", "expert")
MOD_OP = ("add", "mul", "set", "grant", "advantage", "disadvantage")
MOD_WHEN = ("passive", "equipped", "worn", "on_use", "conditional")
HIDDEN_PROP = ("true_material", "true_worth", "forgery", "provenance", "poison", "enchant",
               "curse", "flaw", "compartment", "function")
BREAK = ("shatter", "dull", "fray", "snap", "spoil")
# компетенции для craft_eye/lore-гейтов (у кого «глаз намётан»)
COMPETENCIES = ("metalwork", "gems", "herbs", "poison", "medicine", "letters", "lore", "trade", "faith", "law")


@dataclass
class Capability:
    """Кто осматривает/крафтит: способности + намётанный глаз (компетенции) + инструменты."""
    abilities: dict = field(default_factory=dict)          # {int, wis, dex, …} ~8..16
    competencies: set = field(default_factory=set)         # {metalwork, gems, poison, …}
    tools: set = field(default_factory=set)                # {лупа, детект-магии, пробирный набор}

    def mod(self, ability: str) -> int:
        return (int(self.abilities.get(ability, 10)) - 10) // 2


def _enum(v, allowed, default):
    return v if v in allowed else default


def _list(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _num(v, default=0):
    try:
        return type(default)(v)
    except (TypeError, ValueError):
        return default


def norm_mod(m) -> dict | None:
    if not isinstance(m, dict) or not str(m.get("target") or "").strip():
        return None
    return {"target": str(m["target"]).strip(), "op": _enum(m.get("op"), MOD_OP, "add"),
            "amount": m.get("amount", 0), "when": _enum(m.get("when"), MOD_WHEN, "passive"),
            "cond": str(m.get("cond") or "").strip(), "hidden": bool(m.get("hidden"))}


def norm_gate(g) -> dict:
    g = g if isinstance(g, dict) else {}
    return {"via": _enum(g.get("via"), GATE_VIA, "appraise"),
            "dc": max(0, _num(g.get("dc", 12), 12)), "req": str(g.get("req") or "").strip()}


def norm_hidden(h) -> dict | None:
    if not isinstance(h, dict) or not h.get("prop"):
        return None
    return {"prop": _enum(h.get("prop"), HIDDEN_PROP, "flaw"),
            "value": str(h.get("value") or "").strip(),
            "fact": str(h.get("fact") or "").strip(),
            "gate": norm_gate(h.get("gate")),
            "mods": [x for x in (norm_mod(m) for m in (h.get("mods") or [])) if x]}


def norm_durability(d) -> dict | None:
    if not isinstance(d, dict) or not d.get("max"):
        return None
    mx = max(1, _num(d.get("max", 10), 10))
    return {"max": mx, "current": min(mx, max(0, _num(d.get("current", mx), mx))),
            "break_behavior": _enum(d.get("break_behavior"), BREAK, "snap"),
            "repair_dc": max(0, _num(d.get("repair_dc", 10), 10))}


def normalize(d: dict) -> dict:
    """LLM/скелет-dict → чистый фактшит предмета."""
    d = d or {}
    app = _num(d.get("apparent_worth", 0), 0)
    worth = _num(d.get("worth", app), app)                 # истинная цена ≥ видимой (если ценность скрыта)
    return {
        "kind": _enum(d.get("kind"), KINDS, "misc"),
        "name": str(d.get("name") or "предмет").strip(),
        "slot": _enum(d.get("slot"), SLOTS, "none"),
        "material": str(d.get("material") or "").strip(),
        "quality": _enum(d.get("quality"), QUALITY, "plain"),
        "weight": round(_num(d.get("weight", 0.5), 0.5), 2),
        "apparent_worth": app, "worth": max(worth, app if not d.get("hidden") else 0) if worth else app,
        "tags": _list(d.get("tags")),
        "mods": [x for x in (norm_mod(m) for m in (d.get("mods") or [])) if x],
        "hidden": [x for x in (norm_hidden(h) for h in (d.get("hidden") or [])) if x],
        "durability": norm_durability(d.get("durability")),
        "make": (d.get("make") if isinstance(d.get("make"), dict) else None),
    }
