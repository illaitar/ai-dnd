"""Жадная генерация полных описаний локаций на старте — богатый контекст для нарратора.

build_world даёт лишь короткий ambiance (и тот у пары мест). Здесь LLM пишет устойчивое
описание значимых мест (облик/планировка/сенсорика), кладёт на Place.description; оно идёт
нарратору в _narrator_context и переживает сейв/лоад (снапшот state.place_descriptions)."""

from __future__ import annotations

# описываем «обитаемые» места; регион/поселение/район — пропускаем
_DESCRIBE = {"building", "site"}


def _notable(p) -> bool:
    return p.kind in _DESCRIBE or (p.kind == "room" and bool(p.affordances))


def enrich_locations(world, model, progress=None) -> None:
    """Сгенерировать Place.description для значимых мест (если ещё нет). Без модели — no-op."""
    if model is None or not getattr(model, "available", lambda: False)():
        return
    from ..inference.agents import forge_location
    for _pid, p in list(world.spatial.places.items()):
        if not _notable(p) or p.description:
            continue
        if progress:
            progress(0, 0, f"Описываю место: {p.name}")
        try:
            out = forge_location(model, p.name, p.kind, ", ".join(p.affordances or []), p.ambiance or "", "")
        except Exception:
            out = None
        if out and out.get("description"):
            p.description = str(out["description"]).strip()[:600]
