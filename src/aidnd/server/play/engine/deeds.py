"""Deeds — append-only world journal (docs/entities.md): single substrate for intrigues,
chronicles, obligations and (later) watchers/plot. State remains authoritative — journal
does not rebuild the world, it REMEMBERS what happened.

Promise — a deed with status: active → done|broken. World reminds of the word
in the prompt and leads to meeting by routine (worldsim: candidate "appointment" on time).

Key functions
-------------
record(...) -> int : Append deed event to the world journal.
town_talk(names, limit) -> list[str] : Extract fresh PUBLIC deeds for gossip.
promise_make(...) -> int : Create a promise deed with active status.
promises_active(actor) -> list : Get active promises for NPC or globally.
promise_resolve(d, done) -> None : Mark promise as done or broken.
"""

from __future__ import annotations

from aidnd.server.play.engine.core import _gt, _phase, _store, _wid

# public verbs - fit for gossip/scene news
PUBLIC_VERBS = ("theft", "murder", "clear", "arrest", "brawl")
PHASES = ("morning", "day", "evening", "night")
PHASE_RU = {"morning": "утром", "day": "днём", "evening": "вечером", "night": "ночью"}
RU2PHASE = {"утро": "morning", "утром": "morning", "день": "day", "днём": "day",
            "вечер": "evening", "вечером": "evening", "ночь": "night", "ночью": "night",
            "завтра": "morning", "на рассвете": "morning", "рассвет": "morning"}


def record(actor: str, verb: str, obj: str = "", place: str = "",
           witnesses: list | None = None, status: str = "", data: dict | None = None) -> int:
    return _store().deed_add(_wid(), _gt(), actor, verb, obj, place,
                             witnesses=witnesses, status=status, data=data)


def town_talk(names: dict | None = None, limit: int = 2) -> list[str]:
    """Fresh PUBLIC deeds (per day) - material for "what the city gossips about"."""
    out = []
    since = _gt() - 1440
    for d in _store().deeds(_wid(), since_gt=since, limit=30):
        if d["verb"] not in PUBLIC_VERBS:
            continue
        who = (names or {}).get(d["actor"], "кто-то")
        if d["verb"] == "theft":
            out.append(f"{PHASE_RU.get(_phase(d['gt']), 'на днях')} обокрали "
                       f"({d['data'].get('what', 'добро')}, {d['place'] or 'в городе'})")
        elif d["verb"] == "murder":
            out.append(f"смертоубийство: {d['place'] or 'в городе'}")
        elif d["verb"] == "clear":
            out.append(f"смельчаки зачистили {d['obj'] or 'логово'}")
        elif d["verb"] == "brawl":
            out.append(f"драка ({d['place'] or 'в городе'})")
        else:
            out.append(f"{who}: {d['verb']}")
        if len(out) >= limit:
            break
    return out


def promise_make(actor: str, to: str, what: str, when_ru: str, where: str,
                 node: int | None, place_label: str, witnesses: list | None) -> int:
    """Record a WORD: a deed with status active. Deadline - phase of day (clamped by dictionary)."""
    due = RU2PHASE.get((when_ru or "").strip().lower(), "morning")
    return record(actor, "promise", obj=to, place=place_label, witnesses=witnesses,
                  status="active",
                  data={"what": (what or "")[:120], "due": due, "where": (where or "")[:60],
                        "node": node, "made_gt": _gt()})


def promises_active(actor: str | None = None) -> list:
    return _store().deeds(_wid(), verb="promise", actor=actor, status="active", limit=20)


def promise_line(d: dict, names: dict | None = None) -> str:
    """Reminder line for the debtor's prompt."""
    to = (names or {}).get(d["obj"], d["obj"])
    where = d["data"].get("where") or d["place"] or ""
    return (f"ТЫ ДАЛ СЛОВО ({to}): {d['data'].get('what', '')} — "
            f"{PHASE_RU.get(d['data'].get('due', ''), 'в срок')}"
            + (f", место: {where}" if where else "") + ". Слово держат.")


def promise_resolve(d: dict, done: bool) -> None:
    _store().deed_status(_wid(), d["id"], "done" if done else "broken")
