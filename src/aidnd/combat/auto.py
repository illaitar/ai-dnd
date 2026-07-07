"""Авторезолв боя целиком (обе стороны на ИИ): NPC-партии зачищают подземелья ОФСКРИН тем же
движком, что и игрок, — один набор правил на весь мир.

Key functions
-------------
resolve(party, foes, seed, obstacles, waves) -> dict : Complete auto-combat simulation for NPC parties.
"""

from __future__ import annotations

from .engine import Encounter


def resolve(party: list, foes: list, seed: str, obstacles=None, waves=None) -> dict:
    enc = Encounter(party, foes, seed, obstacles=obstacles, waves=waves)
    guard = 0
    while enc.status() == "active" and guard < 600:
        if enc.foes_cleared() and enc.next_wave():         # текущий накат зачищен — следующий
            continue
        c = enc.current()
        if c is None:
            break
        enc.ai_turn(c)
        guard += 1
    survivors = [u for u in enc.units.values() if u.side == "party" and not u.down()]
    return {"status": enc.status(), "rounds": enc.round,
            "survivors": [u.view() for u in survivors],
            "fallen": [u.view() for u in enc.units.values() if u.side == "party" and not u.alive],
            "foes_left": sum(1 for u in enc.units.values() if u.side == "foes" and not u.down()),
            "log": enc.log[-8:]}
