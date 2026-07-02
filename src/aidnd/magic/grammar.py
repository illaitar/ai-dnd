"""Грамматика магии: композиция глифов → классификация (empty|clean|wild) + механический спек
эффекта. Всё детерминированно из данных glyphs.json — БЕЗ LLM (LLM только даёт имя/дикий хаос,
слой inscribe). Чистый круг исполняется по спеку; противоречивый идёт «вразнос» (wild → LLM).
"""

from __future__ import annotations

import json
import os

_G = None
_GPATH = os.path.join(os.path.dirname(__file__), "glyphs.json")


def load() -> dict:
    """{elements: {id:..}, glyphs: {id:..}, all: {id:..}} — словарь символов из данных."""
    global _G
    if _G is None:
        with open(_GPATH, encoding="utf-8") as f:
            raw = json.load(f)
        elems = {e["id"]: {**e, "axis": "element"} for e in raw["elements"]}
        glyphs = {g["id"]: g for g in raw["glyphs"]}
        _G = {"elements": elems, "glyphs": glyphs, "all": {**elems, **glyphs}}
    return _G


def known_ids() -> set:
    g = load()
    return set(g["all"])


def _split(comp):
    """Композиция (список id) → (элементы, формы, глаголы, модификаторы), неизвестное отброшено."""
    g = load()
    buckets = {"element": [], "form": [], "verb": [], "mod": []}
    for cid in comp:
        e = g["all"].get(cid)
        if e and e["axis"] in buckets:
            buckets[e["axis"]].append(e)
    return buckets["element"], buckets["form"], buckets["verb"], buckets["mod"]


def classify(comp) -> dict:
    """Классификация круга: empty (не сходится) | clean (чистый закон) | wild (вразнос).
    Возвращает {kind, reason, elements, forms, verbs, mods}."""
    elems, forms, verbs, mods = _split(comp)
    base = {"elements": [e["id"] for e in elems], "forms": [f["id"] for f in forms],
            "verbs": [v["id"] for v in verbs], "mods": [m["id"] for m in mods]}
    if not elems and not verbs:                            # ни субстанции, ни действия — пустой круг
        return {"kind": "empty", "reason": "нет ни стихии, ни глагола — круг не сходится", **base}
    # ---- противоречия → дикая магия (не отбраковка) ----
    if len(forms) >= 2:
        return {"kind": "wild", "reason": "две формы в одном круге — рвётся", **base}
    eids = {e["id"] for e in elems}
    for e in elems:
        if e.get("opposes") and e["opposes"] in eids:
            return {"kind": "wild", "reason": f"{e['id']}↔{e['opposes']} — стихии рвут круг", **base}
    verb_ids = {v["id"] for v in verbs}
    harmful = eids - {"свет"}                               # исцеление мирится только со светом
    if "исцелить" in verb_ids and harmful:
        return {"kind": "wild", "reason": "исцеление с губящей стихией — вразнос", **base}
    return {"kind": "clean", "reason": "", **base}


def build_spec(comp) -> dict:
    """Механический спек чистого круга (детерминированно из глифов). Для wild — не вызывать
    (там LLM). difficulty/mana_cost растут с числом и весом глифов + размером круга."""
    g = load()
    elems, forms, verbs, mods = _split(comp)
    size = sum(1 for m in mods if m.get("mod") == "size")
    rng = sum(1 for m in mods if m.get("mod") == "range")
    dur = sum(1 for m in mods if m.get("mod") == "duration")
    verb_ids = {v["id"] for v in verbs}
    form = forms[0]["shape"] if forms else ("bolt" if elems else None)

    spec: dict = {"elements": [e["id"] for e in elems], "form": form,
                  "verbs": sorted(verb_ids), "mods": [m["id"] for m in mods]}

    if elems:                                              # урон по типу стихии
        n = min(4, 1 + size + (len(elems) - 1))            # смешение стихий и «больше» усиливают
        spec["damage"] = {"dice": f"{n}d6", "type": elems[0]["dmg"],
                          "types": sorted({e["dmg"] for e in elems})}
    if form == "burst":
        spec["area"] = {"shape": "burst", "radius": 1 + size}
    elif form == "cloud":
        spec["area"] = {"shape": "cloud", "radius": 1 + size, "duration": 1 + dur}
    elif form == "wall":
        spec["area"] = {"shape": "wall", "length": 2 + size, "duration": 1 + dur}
    elif form == "cone":
        spec["area"] = {"shape": "cone", "length": 2 + size}
    elif form == "bolt":
        spec["area"] = {"shape": "bolt", "radius": 0}
    # дальность: конус/стена бьют из-под ног, прочее — метается
    spec["range"] = (1 + 5 * rng) if form in ("cone", "wall") else (6 + 5 * rng)

    if "связать" in verb_ids:
        spec["status"] = {"kind": "bound", "turns": 1 + dur}
    if "исцелить" in verb_ids:
        spec["heal"] = 4 + 3 * size + 2 * dur
    if "явить" in verb_ids:
        spec["reveal"] = True
    if "отпереть" in verb_ids:
        spec["unlock"] = True

    diff = sum(g["all"][c].get("weight", 1) for c in comp if c in g["all"]) + len(comp) // 2
    spec["difficulty"] = diff
    spec["mana_cost"] = max(1, diff)                       # 1:1 к сложности (потюним на балансе)
    return spec
