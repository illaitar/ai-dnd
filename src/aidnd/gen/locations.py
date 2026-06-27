"""Жадная генерация описаний локаций на старте — богатый контекст для нарратора.

build_world даёт лишь короткий ambiance. Здесь по КРАТКИМ фактам места (тип/функции/состояние/
округа — то, что мир знает) дообученный aidnd-location придумывает облик и ПРЕДЛАГАЕТ комнаты.
Результат кладётся на Place.description (+ Place.rooms) и переживает сейв/лоад (снапшот)."""

from __future__ import annotations

# описываем «обитаемые» места; регион/поселение/район — пропускаем
_DESCRIBE = {"building", "site"}

# тип-архетип из аффордансов (то, что мир знает) — порядок = приоритет
_TYPE_BY_AFF = [
    ("inn", "inn"), ("drink", "tavern"), ("shrine", "temple"), ("townhall", "hall"),
    ("hideout", "lair"), ("combat", "lair"), ("dungeon", "mine"), ("board", "market"),
    ("shop", "shop"), ("work", "smithy"), ("storage", "warehouse"), ("serve", "tower"),
    ("travel", "road"), ("explore", "ruin"),
]
_TYPE_BY_KIND = {"site": "ruin", "dungeon": "mine", "room": "residence", "building": "residence"}
_COND_BY_STATUS = {"open": "обжитое", "closed": "закрытое", "ruined": "руины", "new": "новое"}


def _notable(p) -> bool:
    return p.kind in _DESCRIBE or (p.kind == "room" and bool(p.affordances))


def _type_of(p) -> str:
    affs = set(p.affordances or [])
    return next((t for a, t in _TYPE_BY_AFF if a in affs), _TYPE_BY_KIND.get(p.kind, "site"))


def _region_of(p) -> str:
    if p.kind == "dungeon":
        return "подземелье"
    if p.kind in ("building", "room"):
        return "город"
    return "окраина"


def place_facts(world, p) -> dict:
    """КРАТКИЕ факты места, которые знает мир (вход aidnd-location). Облик/материалы/запахи/
    комнаты модель придумывает сама."""
    return {"type": _type_of(p),
            "affordances": list(p.affordances or []),
            "condition": _COND_BY_STATUS.get(getattr(p, "status", "open"), "обжитое"),
            "region": _region_of(p)}


def enrich_locations(world, model, progress=None) -> None:
    """Сгенерировать Place.description (+ Place.rooms) для значимых мест. Без модели — no-op."""
    if model is None or not getattr(model, "available", lambda: False)():
        return
    from ..inference.agents import forge_location
    from .parallel import pmap
    from .room_loot import classify_room
    places = [p for _pid, p in world.spatial.places.items() if _notable(p) and not p.description]
    if not places:
        return
    conc = model.enrich_concurrency() if hasattr(model, "enrich_concurrency") else 1
    total = len(places)
    outs = pmap(places, lambda p: forge_location(model, p.name, **place_facts(world, p)), conc,
                (lambda done, p: progress(done, total, f"Описываю место: {p.name}")) if progress else None)
    for p, out in zip(places, outs):                     # apply последовательно → детерминизм/replay
        if out and out.get("description"):
            p.description = str(out["description"]).strip()[:600]
            rooms = []
            for r in (out.get("rooms") or []):
                nm = str(r.get("name", ""))[:60]
                if not nm:
                    continue
                ds = str(r.get("desc", ""))[:320]
                rooms.append({"name": nm, "desc": ds, "loot": classify_room(nm, ds)})  # вид лута комнаты
            p.rooms = rooms
