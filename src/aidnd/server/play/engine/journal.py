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

from aidnd.inference.client import LLMUnavailable
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


_BEATS = {"offer", "accept", "step", "twist", "reveal", "done", "overtaken", "failed"}

_J_SYS = (
    "Ты — герой этой истории, ведёшь дневник дел. Опиши событие ниже ОДНОЙ короткой "
    "фразой: от ПЕРВОГО лица, в ПРОШЕДШЕМ времени, по-русски, только по фактам — "
    "ничего не домысливай и не добавляй. Верни ТОЛЬКО фразу, без кавычек и пояснений."
)


def _facts_ru(beat: str, f: dict) -> str:
    """Render the code-built facts dict into one RU description for the narrator. Pure string
    assembly — no invention; every value comes from the caller (the contract/giver)."""
    if beat == "offer":
        role = f" ({f['giver_role']})" if f.get("giver_role") else ""
        app = f", {f['appearance']}" if f.get("appearance") else ""
        return (f"ко мне обратился(лась) {f.get('giver_name', 'кто-то')}{role}{app}; "
                f"его(её) просьба: {f.get('pitch', '')}")
    if beat == "accept":
        where = f", место: {f['where']}" if f.get("where") else ""
        what = f.get("want") or f.get("target_name") or "поручение"
        return (f"я согласился взяться за дело для {f.get('giver_name', 'заказчика')}: "
                f"{what}{where}; награда: {f.get('reward', '?')}")
    if beat == "step":
        return (f"я выполнил шаг ({f.get('step_narr', '')}); осталось: {f.get('next', '')} "
                f"— шаг {f.get('n', '?')} из {f.get('total', '?')}")
    if beat in ("twist", "reveal"):
        return f"вскрылось: {f.get('reveal', 'новый поворот в этом деле')}"
    if beat == "done":
        return (f"дело для {f.get('giver_name', 'заказчика')} завершено: {f.get('what', 'исполнено')} "
                f"(тип: {f.get('kind', '')})")
    if beat == "overtaken":
        return (f"дело уладилось без меня, я опоздал — {f.get('giver_name', 'заказчик')} сказал(а): "
                f"«{f.get('giver_line', 'поздно')}»")
    if beat == "failed":
        return f"дело для {f.get('giver_name', 'заказчика')} не удалось: {f.get('reason', '')}"
    return "; ".join(f"{k}: {v}" for k, v in (f or {}).items())


def j_beat(cid: str, beat: str, facts: dict) -> None:
    """One thread line for a quest event. beat ∈ {offer,accept,step,twist,reveal,done,overtaken,failed}.
    Builds an RU facts block, makes ONE narrator call (temp 0.4), appends kind='quest' prov=beat
    refs=[cid]. BEST-EFFORT: LLMUnavailable / empty / any error → returns without writing; NEVER
    raises to the caller (the quest transaction has already committed). No canned fallback line."""
    try:
        wid = _wid()
        store = _store()
    except Exception:  # noqa: BLE001 — no live session: journaling is best-effort, never fatal
        return None
    if wid is None or store is None:
        return None
    try:
        from aidnd.server.play.engine.core import _model  # deferred: avoid load-time cycle
        msgs = [{"role": "system", "content": _J_SYS},
                {"role": "user", "content": f"Событие ({beat}): {_facts_ru(beat, facts)}."}]
        resp = _model().call("narrator", msgs, options={"temperature": 0.4})
    except LLMUnavailable:
        return None                                          # no model → no row, no stub (no-LLM-fallback)
    except Exception:  # noqa: BLE001 — journaling never breaks a committed quest
        return None
    line = ((resp.get("content") if resp else "") or "").strip().strip('"').strip()
    if not line:
        return None                                          # empty/garbled → no row
    store.journal_add(wid, "quest", beat, [cid], line, _gt())
    return None
