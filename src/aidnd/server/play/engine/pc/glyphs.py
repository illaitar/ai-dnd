"""Player glyphs / grimoire — magic circle vocabulary owned or inscribed by the player.

Key functions
-------------
_glyphs_known() -> list : Glyphs OWNED by the player (persists in pc_state).
_glyph_learn(gid) -> bool : Add a glyph to the player's arsenal.
_grimoire_get(h) -> dict | None : Inscribed circle law (by composition hash), or None.
_grimoire_put(h, entry) -> None : Store an inscribed circle law.
_grimoire_list() -> list : All circles inscribed in the world, oldest first.
"""

from __future__ import annotations

import json

from ..session.persist import _store
from ..session.state import _S, _wid

# player starter glyph set (§M1e): enough for fire arrow and healing; rest must be learned
_STARTER_GLYPHS = ("огонь", "свет", "стрела", "исцелить", "больше")


def _glyphs_known() -> list:
    """Glyphs OWNED by player (persists in pc_state); others must be learned from mage."""
    if _S.get("glyphs") is None:
        row = _store().get_pc(_wid()) or {}
        g = row.get("glyphs")
        _S["glyphs"] = list(dict.fromkeys(g if g is not None else _STARTER_GLYPHS))
    return list(_S["glyphs"])


def _glyph_learn(gid: str) -> bool:
    """Add glyph to player arsenal. True — learned for first time, False — already knew."""
    known = _glyphs_known()
    if gid in known:
        return False
    _S["glyphs"] = known + [gid]
    return True


def _grimoire_get(h: str) -> dict | None:
    """Inscribed circle law (by composition hash) for current world — or None."""
    raw = _store().flag_get(_wid(), f"grim|{h}")
    return json.loads(raw) if raw else None


def _grimoire_put(h: str, entry: dict) -> None:
    _store().flag_set(_wid(), f"grim|{h}", json.dumps(entry, ensure_ascii=False))


def _grimoire_list() -> list:
    """All circles inscribed in world (player grimoire), in order of first creation."""
    out = []
    for v in _store().flags_prefix(_wid(), "grim|").values():
        try:
            out.append(json.loads(v))
        except (ValueError, TypeError):
            pass
    return sorted(out, key=lambda e: e.get("first_gt", 0))
