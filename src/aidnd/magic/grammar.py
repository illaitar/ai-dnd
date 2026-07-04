"""Грамматика магии: круг = РИСУНОК (глиф × размер × положение × кольцо) → классификация + бюджет
силы + канонический хэш. Правила ЧЁТКИЕ и детерминированные (см. RULES_RU — они же уходят в промпт
законописца); сам ЗАКОН круга проявляет LLM (inscribe), строго в пределах бюджета. base_law —
детерминированный СКЕЛЕТ закона (табличная логика): clamp_law достраивает им пропуски LLM.

Рисунок: [{id, size 0..1, angle 0..360 (0 = верх, по часовой), ring 0|1}]. Голая строка "огонь"
принимается как {id, size .5, angle авто, ring 0} — обратная совместимость со старым вводом.
"""

from __future__ import annotations

import hashlib
import json
import math
import os

_G = None
_GPATH = os.path.join(os.path.dirname(__file__), "glyphs.json")

# ---- правила геометрии (единственный источник истины: и код, и промпт LLM) ----
RULES_RU = (
    "ПРАВИЛА КРУГА: 1) РАЗМЕР глифа = сила компонента: мелкий ×0.5, средний ×1, крупный ×1.5 от веса. "
    "2) ПОЛОЖЕНИЕ на внешнем кольце — куда обращено заклинание: верх круга = вовне/на цель, "
    "низ = на себя, глифы раскиданы по кругу без перекоса = вокруг/областью. "
    "3) КОЛЬЦА: внешнее — суть заклинания; внутреннее — условие/оттенок, ОКРАШИВАЕТ внешнее "
    "(огонь снаружи + связать внутри = пламенные путы); вклад внутренних ×0.7. "
    "4) ПРОТИВОРЕЧИЯ: противоположные стихии или две формы НА ОДНОМ кольце рвут круг (дикая магия); "
    "на РАЗНЫХ кольцах контраст обуздан и допустим (огонь снаружи, лёд внутри — пар, туман). "
    "5) БЮДЖЕТ СИЛЫ круга = сумма (вес × размер × кольцо) — закон не может быть мощнее бюджета."
)

SIZE_MULT = ((0.34, 0.5), (0.67, 1.0), (1.01, 1.5))        # корзины размера: мелкий/средний/крупный
RING_MULT = {0: 1.0, 1: 0.7}


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
    return set(load()["all"])


def _size_mult(size: float) -> float:
    for top, m in SIZE_MULT:
        if size <= top:
            return m
    return 1.5


def normalize(comp) -> list:
    """Любой ввод → список размещений [{id,size,angle,ring}]. Неизвестные глифы отброшены.
    Строки (старый ввод) раскладываются по внешнему кольцу средним размером."""
    g, out = load(), []
    raw = list(comp or [])
    for i, c in enumerate(raw):
        if isinstance(c, str):
            c = {"id": c, "size": 0.5, "angle": (360.0 * i / max(1, len(raw))) % 360, "ring": 0}
        cid = str(c.get("id") or "")
        if cid not in g["all"]:
            continue
        out.append({"id": cid,
                    "size": min(1.0, max(0.05, float(c.get("size", 0.5)))),
                    "angle": float(c.get("angle", 0.0)) % 360.0,
                    "ring": 1 if int(c.get("ring", 0)) else 0})
    return out


def circle_hash(comp) -> str:
    """Канонический ключ РИСУНКА: размер → 3 корзины, угол → 8 секторов, кольцо как есть.
    Слегка сдвинутый тот же рисунок = тот же закон."""
    parts = sorted(f"{p['id']}|{_size_mult(p['size'])}|{int(((p['angle'] + 22.5) % 360) // 45)}|{p['ring']}"
                   for p in normalize(comp))
    return hashlib.sha1(("//".join(parts)).encode("utf-8")).hexdigest()[:12]


def power_budget(comp) -> float:
    """Бюджет силы круга: Σ вес × размер × кольцо. Закон обязан уложиться."""
    g = load()
    return round(sum(g["all"][p["id"]].get("weight", 1) * _size_mult(p["size"]) * RING_MULT[p["ring"]]
                     for p in normalize(comp)), 2)


def glyph_cost(gid: str, size: float, ring: int) -> float:
    """Мана за НАНЕСЕНИЕ одного глифа (та же формула, что и вклад в бюджет)."""
    g = load()
    return round(g["all"].get(gid, {}).get("weight", 1) * _size_mult(size) * RING_MULT[1 if ring else 0], 2)


def anchor(comp) -> str:
    """Куда обращён круг: вовне/на цель | на себя | вокруг (по вектору размещений внешнего кольца)."""
    pts = [p for p in normalize(comp) if p["ring"] == 0]
    if not pts:
        return "вокруг"
    x = sum(math.sin(math.radians(p["angle"])) for p in pts) / len(pts)
    y = sum(math.cos(math.radians(p["angle"])) for p in pts) / len(pts)
    r = math.hypot(x, y)
    if r < 0.35:
        return "вокруг"                                    # раскидано по кругу — областью
    return "вовне/на цель" if y > 0 else "на себя" if y < -0.3 else "вбок/в сторону"


def classify(comp) -> dict:
    """empty (не сходится) | clean | wild. Противоречия рвут круг ТОЛЬКО внутри одного кольца —
    на разных кольцах контраст обуздан (§4 правил)."""
    pts = normalize(comp)
    g = load()
    base = {"placements": pts}
    kinds = [(p, g["all"][p["id"]]) for p in pts]
    elems = [(p, e) for p, e in kinds if e["axis"] == "element"]
    verbs = [(p, e) for p, e in kinds if e.get("axis") == "verb"]
    if not elems and not verbs:
        return {"kind": "empty", "reason": "нет ни стихии, ни глагола — круг не сходится", **base}
    for ring in (0, 1):
        ring_e = [e for p, e in elems if p["ring"] == ring]
        ids = {e["id"] for e in ring_e}
        for e in ring_e:
            if e.get("opposes") and e["opposes"] in ids:
                return {"kind": "wild",
                        "reason": f"{e['id']}↔{e['opposes']} на одном кольце — стихии рвут круг", **base}
        forms = [e for p, e in kinds if e.get("axis") == "form" and p["ring"] == ring]
        if len(forms) >= 2:
            return {"kind": "wild", "reason": "две формы на одном кольце — рвётся", **base}
        vids = {e["id"] for p, e in verbs if p["ring"] == ring}
        if "исцелить" in vids and (ids - {"свет"}):
            return {"kind": "wild", "reason": "исцеление с губящей стихией на одном кольце — вразнос", **base}
    return {"kind": "clean", "reason": "", **base}


def describe(comp) -> str:
    """Человекочитаемое описание рисунка — для промпта законописца и гримуара."""
    g = load()
    pts = normalize(comp)
    size_ru = lambda s: "мелко" if _size_mult(s) == 0.5 else "крупно" if _size_mult(s) == 1.5 else "средне"  # noqa: E731
    sect_ru = lambda a: ("вверху" if a < 45 or a >= 315 else "справа" if a < 135                             # noqa: E731
                         else "внизу" if a < 225 else "слева")
    rows = []
    for ring, tag in ((0, "Внешнее кольцо"), (1, "Внутреннее кольцо")):
        items = [p for p in pts if p["ring"] == ring]
        if items:
            rows.append(f"{tag}: " + ", ".join(
                f"{g['all'][p['id']].get('ru', p['id'])} ({size_ru(p['size'])}, {sect_ru(p['angle'])})"
                for p in items))
    rows.append(f"Обращение круга: {anchor(comp)}. Бюджет силы: {power_budget(comp):g}.")
    return "; ".join(rows)


def base_law(comp) -> dict:
    """Детерминированный СКЕЛЕТ закона (табличная логика грамматики) — основа, которую
    clamp_law достраивает под ответ LLM. НЕ офлайн-фоллбэк: рантайм без LLM не работает."""
    g = load()
    pts = normalize(comp)
    kinds = [(p, g["all"][p["id"]]) for p in pts]
    elems = [(p, e) for p, e in kinds if e["axis"] == "element"]
    verbs = {e["id"] for p, e in kinds if e.get("axis") == "verb"}
    forms = [e for p, e in kinds if e.get("axis") == "form"]
    budget = power_budget(comp)
    n = max(1, min(6, round(budget / 3)))
    mech: dict = {}
    if elems:
        mech["damage"] = {"dice": f"{n}d6", "type": elems[0][1]["dmg"]}
    shape = forms[0]["shape"] if forms else ("bolt" if elems else None)
    if shape in ("burst", "cloud", "cone", "wall"):
        mech["aoe"] = {"shape": shape, "radius": max(1, round(budget / 4))}
    if "исцелить" in verbs:
        mech["heal"] = max(2, round(2 * budget / 3))
    if "связать" in verbs:
        mech["status"] = {"kind": "bound", "turns": max(1, round(budget / 4))}
    if "явить" in verbs:
        mech["reveal"] = True
    if "отпереть" in verbs:
        mech["unlock"] = True
    kind = ("heal" if "исцелить" in verbs else "damage" if elems else "utility")
    return {"name": ", ".join(dict.fromkeys(p["id"] for p in pts)) or "круг",
            "flavor": "закон, проявленный без законописца — по самой геометрии",
            "sensory": "линии вспыхивают и складываются в фигуру",
            "kind": kind, "power": max(1, round(budget)),
            "target": {"вовне/на цель": "single", "на себя": "self"}.get(anchor(comp), "area"),
            "range": 6, "duration": max(1, round(budget / 3)),
            "mech": mech, "law": "круг делает ровно то, что начертано", "taboo": bool(elems)}
