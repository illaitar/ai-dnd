"""Magic grammar: circle = DRAWING (glyph × size × position × ring) → classification + power
budget + canonical hash. Rules are STRICT and deterministic (see RULES_RU — they also go into the
lawscribe prompt); the circle's LAW is manifested by LLM (inscribe), strictly within budget.
base_law — deterministic LAW SKELETON (table-driven logic): clamp_law fills gaps left by LLM.

Drawing: [{id, size 0..1, angle 0..360 (0 = top, clockwise), ring 0|1}]. Bare string "огонь"
is accepted as {id, size .5, angle auto, ring 0} — backward compat with old input.

Key functions
-------------
load() -> dict : loads glyph/element data dictionary for grammar.
normalize(comp) -> list : normalizes input to [{id, size, angle, ring}].
circle_hash(comp) -> str : canonical 12-char hash of circle drawing.
power_budget(comp) -> float : sums (weight × size × ring_mult) budget.
classify(comp) -> dict : validates circle (empty/clean/wild status).
describe(comp) -> str : human-readable circle description for prompts.
base_law(comp) -> dict : derives deterministic game mechanics skeleton.
"""

from __future__ import annotations

import hashlib
import json
import math
import os

_G = None
_GPATH = os.path.join(os.path.dirname(__file__), "glyphs.json")

# ---- geometry rules (single source of truth: both code and LLM prompt) ----
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

SIZE_MULT = ((0.34, 0.5), (0.67, 1.0), (1.01, 1.5))        # size buckets: small/medium/large
RING_MULT = {0: 1.0, 1: 0.7}


def load() -> dict:
    """{elements: {id:..}, glyphs: {id:..}, all: {id:..}} — symbol dictionary from data."""
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
    """Any input → list of placements [{id,size,angle,ring}]. Unknown glyphs discarded.
    Strings (old input) are laid out on outer ring with medium size."""
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
    """Canonical key of DRAWING: size → 3 buckets, angle → 8 sectors, ring as-is.
    Slightly shifted same drawing = same law."""
    parts = sorted(f"{p['id']}|{_size_mult(p['size'])}|{int(((p['angle'] + 22.5) % 360) // 45)}|{p['ring']}"
                   for p in normalize(comp))
    return hashlib.sha1(("//".join(parts)).encode("utf-8")).hexdigest()[:12]


def power_budget(comp) -> float:
    """Circle power budget: Σ weight × size × ring. Law must fit within budget."""
    g = load()
    return round(sum(g["all"][p["id"]].get("weight", 1) * _size_mult(p["size"]) * RING_MULT[p["ring"]]
                     for p in normalize(comp)), 2)


def glyph_cost(gid: str, size: float, ring: int) -> float:
    """Mana for INSCRIBING one glyph (same formula as contribution to budget)."""
    g = load()
    return round(g["all"].get(gid, {}).get("weight", 1) * _size_mult(size) * RING_MULT[1 if ring else 0], 2)


def anchor(comp) -> str:
    """Circle orientation: outward/at target | at self | around (by placement vector of outer ring)."""
    pts = [p for p in normalize(comp) if p["ring"] == 0]
    if not pts:
        return "вокруг"
    x = sum(math.sin(math.radians(p["angle"])) for p in pts) / len(pts)
    y = sum(math.cos(math.radians(p["angle"])) for p in pts) / len(pts)
    r = math.hypot(x, y)
    if r < 0.35:
        return "вокруг"                                    # spread across circle — as an area
    return "вовне/на цель" if y > 0 else "на себя" if y < -0.3 else "вбок/в сторону"


def classify(comp) -> dict:
    """empty (won't cohere) | clean | wild. Contradictions break circle ONLY within one ring —
    across different rings contrast is tamed (§4 of rules)."""
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
    """Human-readable drawing description — for lawscribe prompt and grimoire."""
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
    """Deterministic LAW SKELETON (table-driven grammar logic) — base that clamp_law fills
    for LLM response. NOT offline fallback: runtime without LLM fails."""
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
