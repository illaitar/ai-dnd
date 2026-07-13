"""Player-journal capture helpers — thin, LLM-free wrappers over WorldStore.journal_add.

Each wrapper resolves world-id / store / game-time internally and is a SAFE NO-OP
(returns None, never raises) when no live session/store is available. Called from the
five capture hooks at existing render sites; also hosts journal_feed (Hook 1 pass).

Import the id/store/time resolvers from the SESSION LEAF modules (not core) so a
top-level import from any hook site cannot form a load-time cycle.

Key functions
-------------
j_event(prov, text, refs=None) : kind=event row (overheard line, witnessed deed, item reveal).
j_quest(prov, text, cid)       : kind=quest row, refs=[cid] (pitch/accept=told, outcome=saw).
j_person(prov, text, pid)      : kind=person row, refs=[pid] (first meeting, later facts).
j_place(text, bid)             : kind=place row, prov=saw, refs=[bid] (first visit).
journal_feed(feed)             : Hook 1 pass — one event row per witnessed speech/deed (Task 3).
"""

from __future__ import annotations

from aidnd.server.play.engine.session.persist import _store
from aidnd.server.play.engine.session.state import _wid
from aidnd.server.play.engine.session.time import _gt


def _emit(kind: str, prov: str, refs: list, text: str) -> None:
    """One row via journal_add — silent no-op if there's no live world/store."""
    try:
        wid = _wid()
        store = _store()
    except Exception:  # noqa: BLE001 — no live session: capture is best-effort, never fatal
        return None
    if wid is None or store is None:
        return None
    store.journal_add(wid, kind, prov, list(refs or []), text, _gt())
    return None


def j_event(prov: str, text: str, refs: list | None = None) -> None:
    return _emit("event", prov, refs or [], text)


def j_quest(prov: str, text: str, cid: str) -> None:
    return _emit("quest", prov, [cid], text)


def j_person(prov: str, text: str, pid: str) -> None:
    return _emit("person", prov, [pid], text)


def j_person_once(pid: str, text: str) -> None:
    """First-meeting person entry, gated on a dedicated jmet|<pid> flag — NOT on `_met()`/
    relationships, which the player's sight-appraisal populates for every co-present NPC each
    tick (Hook 3 must fire on the first actual TALK, not on merely having been seen)."""
    try:
        wid = _wid()
        store = _store()
    except Exception:  # noqa: BLE001 — no live session: capture is best-effort, never fatal
        return None
    if wid is None or store is None:
        return None
    if store.flag_get(wid, f"jmet|{pid}"):
        return None
    store.flag_set(wid, f"jmet|{pid}")
    j_person("saw", text, pid)


def j_place(text: str, bid: str, prov: str = "saw") -> None:
    return _emit("place", prov, [bid], text)


def journal_feed(feed: list) -> None:
    """Hook 1 pass over one tick's feed: the feed IS the witnessed scene.
    speech tier 1 → event/heard1 (full) · tier 2 → event/heard2 (cutout fragment) ·
    tier 3 & murmur → skip. deed with a real actor pid → event/saw refs=[pid] ·
    ambient/'зал' deed (no pid) → skip. text is copied exactly, never rewritten."""
    for e in feed or []:
        if e.get("k") == "speech":
            tier = e.get("tier")
            if tier == 1:
                j_event("heard1", e.get("text", ""), refs=[])
            elif tier == 2:
                j_event("heard2", e.get("text", ""), refs=[])
        elif e.get("k") == "deed" and e.get("pid"):
            j_event("saw", e.get("text", ""), refs=[e["pid"]])
