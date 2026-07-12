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


def j_place(text: str, bid: str) -> None:
    return _emit("place", "saw", [bid], text)
