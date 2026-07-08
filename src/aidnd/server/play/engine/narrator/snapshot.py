"""DM narrator scene snapshot and ambient-sound note for non-mechanical player actions.

Key functions
-------------
_dm_snapshot(sc: dict) -> str : narrator snapshot of the live scene (place/time, who is where,
    audible lines, nearby items) so the DM describes THIS world, not an invented one.
_ambient_note(lv: dict, listener_zone: dict, occupancy: dict) -> str : Russian one-liner of audible
    ambient sound for the DM snapshot; '' if silent.
"""

from __future__ import annotations

from ..core import _display
from ..session.config import PLAYER
from ..session.state import _S
from ..session.time import _PHASE_RU, _gt, _phase
from ..sound import audible_ambient


def _dm_snapshot(sc: dict) -> str:
    """Snapshot of live scene for narrator: place/time/weather, who is where and what they do, last
    lines, items around player. Narrator DESCRIBES this world, not inventing their own."""
    lv = _S.get("live") or {}
    amb = (sc or {}).get("ambient") or {}
    parts = [f"МЕСТО: {(sc.get('location') or {}).get('name', lv.get('place', 'улица'))}. "
             f"{lv.get('pdesc', '')}",
             f"ВРЕМЯ: {amb.get('time', _PHASE_RU[_phase()])}, {_gt() // 60 % 24:02d}:{_gt() % 60:02d}; "
             f"погода: {amb.get('weather', '—')}; в зале {amb.get('mood', '—')}."]
    w = lv.get("world")
    people = _S.get("people") or {}
    if w is not None:
        pb = w.bodies.get(PLAYER)
        if pb is not None:
            parts.append(f"ИГРОК сейчас: {pb.place}.")
            objs = [i.name for i in (w.ground.get(pb.place) or [])][:8]
            if objs:
                parts.append("Рядом с игроком: " + ", ".join(objs) + ".")
        folks = []
        for pid in list(w.npc_minds)[:8]:
            if pid == PLAYER or w.bodies[pid].down():
                continue
            folks.append(f"{_display(pid, people)} ({w.bodies[pid].place}) — "
                         f"{(lv.get('last') or {}).get(pid, 'занят собой')}")
        if folks:
            parts.append("ЛЮДИ: " + "; ".join(folks) + ".")
        zonemap = lv.get("zonemap") or {}
        occ: dict = {}
        for zid in zonemap.values():
            occ[zid] = occ.get(zid, 0) + 1
        listener_zone_id = zonemap.get(PLAYER)
        lz = next((z for z in (lv.get("zones") or []) if z.get("id") == listener_zone_id), None)
        if lz is not None:
            note = _ambient_note(lv, lz, occ)
            if note:
                parts.append(note)
        lines = []
        my = (lv.get("zonemap") or {}).get(PLAYER)
        ev = _S.get("eaves") or {}
        for c in (lv.get("convs") or [])[-3:]:
            znm = (lv.get("zone_names") or {}).get(c.get("zone"))
            audible = (PLAYER in (c.get("members") or []) or c.get("zone") == my
                       or (znm and znm == ev.get("place")))
            if not audible:                          # foreign table — don't feed to narrator
                continue
            for who, txt in c.get("log", [])[-2:]:
                lines.append(f"{lv.get('names', {}).get(who, who)}: «{txt[:70]}»")
        if lines:
            parts.append("ПОСЛЕДНИЕ РЕПЛИКИ (что игроку слышно): " + " | ".join(lines[-5:]))
    return "\n".join(parts)


def _ambient_note(lv: dict, listener_zone: dict, occupancy: dict) -> str:
    """Russian one-liner of audible ambient sound for the DM snapshot; '' if silent."""
    phrases = audible_ambient(lv.get("zones") or [], listener_zone, occupancy)
    return f"слышно: {', '.join(phrases)}" if phrases else ""
