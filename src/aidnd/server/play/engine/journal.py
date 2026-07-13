"""Player-journal — quest chronicle only. One writer (`j_beat`) and one one-shot migration
(`purge_legacy_once`); the old ambient capture hooks (person/place/event) are gone (Task 3):
the journal now records deeds only, not everything the player saw or heard.

Import the id/store/time resolvers from the SESSION LEAF modules (not core) so a
top-level import from any hook site cannot form a load-time cycle.

Key functions
-------------
j_beat(cid, beat, facts)   : kind=quest row, prov=beat, refs=[cid] — the single journal writer.
purge_legacy_once(wid)     : one-shot compost of pre-existing non-quest rows for a world.
"""

from __future__ import annotations

from aidnd.inference.client import LLMUnavailable
from aidnd.server.play.engine.session.persist import _store
from aidnd.server.play.engine.session.state import _wid
from aidnd.server.play.engine.session.time import _gt


def purge_legacy_once(wid) -> None:
    """One-shot legacy compost: drop all non-quest rows for this world, guarded by a journal_purged
    flag so it runs exactly once after deploy. Best-effort no-op with no live store."""
    try:
        store = _store()
    except Exception:  # noqa: BLE001
        return None
    if wid is None or store is None:
        return None
    if store.flag_get(wid, "journal_purged"):
        return None
    store.journal_purge_nonquest(wid)
    store.flag_set(wid, "journal_purged")
    return None


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
        line = ((resp.get("content") if resp else "") or "").strip().strip('"').strip()
    except LLMUnavailable:
        return None                                          # no model → no row, no stub (no-LLM-fallback)
    except Exception:  # noqa: BLE001 — journaling never breaks a committed quest (defensive:
        return None   # covers a non-dict resp too — .get() raising must not escape j_beat)
    if not line:
        return None                                          # empty/garbled → no row
    line = _clamp_line(line)                                  # журнальная строка — одна фраза, дисплейный бюджет
    if not line:
        return None
    store.journal_add(wid, "quest", beat, [cid], line, _gt())
    return None


def _clamp_line(line: str) -> str:
    """Cut to the first sentence or 200 chars, whichever is shorter — the journal shows one
    short phrase, not a narrator ramble. Never cuts mid-word past the 200-char budget."""
    line = line.split("\n")[0]
    ends = [i for i in (line.find("."), line.find("!"), line.find("?")) if i != -1]
    if ends:
        line = line[: min(ends) + 1]
    if len(line) > 200:
        cut = line.rfind(" ", 0, 200)
        line = line[:cut] if cut > 0 else line[:200]
    return line.strip()
