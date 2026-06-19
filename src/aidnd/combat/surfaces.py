"""Поверхности на клетках (фирменная механика Baldur's Gate 3).

Огонь, жир, вода, лёд, яд. Эффекты при входе/начале хода и взаимодействия:
огонь поджигает жир, вода тушит огонь, лёд делает клетку скользкой. Урон и
спасброски идут через детерминированный движок и кости.
"""

from __future__ import annotations

from .state import Surface

# kind -> параметры
DEFS = {
    "fire":   {"color": "#d9622b", "enter_dmg": "1d6", "type": "fire", "rounds": 3},
    "grease": {"color": "#6b5a36", "save": ("dex", 10), "rounds": 4},      # упасть ничком
    "water":  {"color": "#3a78b0", "rounds": 5},                            # тушит огонь
    "ice":    {"color": "#9fd0e0", "save": ("dex", 10), "difficult": True, "rounds": 4},
    "poison": {"color": "#5aa05a", "start_dmg": "1d4", "type": "poison", "rounds": 3},
}

SURFACE_COLORS = {k: v["color"] for k, v in DEFS.items()}


def create(engine, cells, kind: str, rounds: int | None = None) -> None:
    """Создаёт поверхность на клетках с учётом взаимодействий."""
    st = engine.state
    d = DEFS.get(kind, {})
    for cell in cells:
        if not st.grid.is_passable(*cell):
            continue
        existing = st.surfaces.get(cell)
        if kind == "fire" and existing and existing.kind == "water":
            st.surfaces.pop(cell, None)            # вода тушит огонь — пар
            continue
        if kind == "fire" and existing and existing.kind == "grease":
            pass                                   # огонь по жиру — горит ярче (остаётся fire)
        if kind == "water" and existing and existing.kind == "fire":
            st.surfaces.pop(cell, None)            # вода гасит
            continue
        st.surfaces[cell] = Surface(kind=kind, rounds=rounds or d.get("rounds", 3))


def on_enter(engine, eid: str, cell: tuple) -> None:
    """Эффект при входе бойца на клетку с поверхностью."""
    surf = engine.state.surfaces.get(cell)
    if not surf:
        return
    _apply(engine, eid, surf, trigger="enter")


def on_turn_start(engine, eid: str) -> None:
    c = engine.state.combatants.get(eid)
    if not c:
        return
    surf = engine.state.surfaces.get(c.pos)
    if surf:
        _apply(engine, eid, surf, trigger="start")


def _apply(engine, eid: str, surf: Surface, trigger: str) -> None:
    d = DEFS.get(surf.kind, {})
    name = engine._name(eid)
    if surf.kind == "fire" and "enter_dmg" in d:
        dmg = engine.dice.roll_seeded("damage", d["enter_dmg"], roller="surface")
        engine._apply_damage("surface:fire", eid, dmg.total)
        engine.state.log.append(f"🔥 {name} обжигается в огне ({dmg.total}).")
    elif surf.kind == "poison" and trigger == "start" and "start_dmg" in d:
        dmg = engine.dice.roll_seeded("damage", d["start_dmg"], roller="surface")
        engine._apply_damage("surface:poison", eid, dmg.total)
        engine.state.log.append(f"☠ {name} травится ядом ({dmg.total}).")
    elif "save" in d and trigger == "enter":
        ability, dc = d["save"]
        if not engine._save(eid, ability, dc):
            engine._set_condition(eid, "prone")
            engine.state.log.append(f"🧊 {name} поскальзывается и падает ({surf.kind}).")


def tick(state) -> None:
    """Убавляет длительность поверхностей в конце раунда."""
    for cell in list(state.surfaces):
        state.surfaces[cell].rounds -= 1
        if state.surfaces[cell].rounds <= 0:
            del state.surfaces[cell]


def is_difficult(state, cell: tuple) -> bool:
    s = state.surfaces.get(cell)
    return bool(s and DEFS.get(s.kind, {}).get("difficult"))
