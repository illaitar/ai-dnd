"""Осмотр: резолвим гейт каждого скрытого свойства о Capability наблюдателя. Разный `via` вскрывает
разное; expert делегирует чужой способности (NPC-знаток). view() — что наблюдатель ЗНАЕТ о предмете
(surface + вскрытое), с истинной ценой только после вскрытия true_worth/forgery.
"""

from __future__ import annotations

from random import Random

from .model import Capability


def _roll(seed: str) -> int:
    return Random(seed).randint(1, 20)                     # стабильный d20 (не перекинуть переосмотром)


def _gate(g: dict, cap: Capability, via: str, tool, context, seed: str) -> str:
    """'pass' | 'near' | 'fail'."""
    if via in ("glance", "handle"):
        return "pass"
    if via == "craft_eye":
        return "pass" if g["req"] and g["req"] in cap.competencies else "fail"
    if via == "tool":
        return "pass" if g["req"] and (g["req"] in cap.tools or (tool and g["req"] in {tool})) else "fail"
    if via == "context":
        return "pass" if g["req"] and context and g["req"] in context else "fail"
    if via == "use":
        return "fail"                                      # вскрывается использованием, не осмотром
    if via == "lore" and g["req"] and g["req"] in cap.competencies:
        return "pass"                                      # знаток видит сразу
    abil = max(cap.mod("int"), cap.mod("wis")) if via == "appraise" else cap.mod("int")
    total = abil + _roll(seed)
    return "pass" if total >= g["dc"] else "near" if total >= g["dc"] - 3 else "fail"


def inspect(item: dict, cap: Capability, via: str, *, tool=None, context=None,
            observer: str = "pc", known=None) -> dict:
    """Осмотреть предмет способом `via`. Возвращает {revealed:[hidden], hints:[fact], via}.
    via='expert' — знаток пробует РОДНЫМ способом каждого свойства своей способностью."""
    known = set(known or [])
    base = f"{item.get('id') or item.get('name')}|{observer}"
    revealed, hints = [], []
    for h in item.get("hidden", []):
        if h["prop"] in known:
            continue
        g = h["gate"]
        used = g["via"] if via == "expert" else via
        if via != "expert" and used != g["via"]:
            continue                                       # таким осмотром эту скрытую не вскрыть
        res = _gate(g, cap, used, tool, context, f"{base}|{h['prop']}|{used}")
        if res == "pass":
            revealed.append(h)
        elif res == "near":
            hints.append("что-то не так с предметом — нужен иной осмотр или знаток")
    return {"revealed": revealed, "hints": hints, "via": via}


def view(item: dict, known=None) -> dict:
    """Что наблюдатель ЗНАЕТ о предмете (для UI/торга)."""
    known = set(known or [])
    worth_known = any((h["prop"] in ("true_worth", "forgery"))
                      or any(m["target"] == "worth" for m in h.get("mods", []))
                      for h in item.get("hidden", []) if h["prop"] in known)
    facts = [h["fact"] for h in item.get("hidden", []) if h["prop"] in known and h.get("fact")]
    rmods = [m for h in item.get("hidden", []) if h["prop"] in known for m in h.get("mods", [])]
    unknown = sum(1 for h in item.get("hidden", []) if h["prop"] not in known)
    return {"name": item["name"], "kind": item["kind"], "slot": item["slot"],
            "material": item["material"], "quality": item["quality"], "weight": item["weight"],
            "worth": item["worth"] if worth_known else item["apparent_worth"], "worth_known": worth_known,
            "tags": item["tags"], "mods": [m for m in item["mods"] if not m.get("hidden")] + rmods,
            "facts": facts, "unknown": unknown, "durability": item.get("durability")}
