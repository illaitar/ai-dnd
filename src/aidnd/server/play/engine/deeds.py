"""ДЕЛА (deeds) — append-only журнал мира (docs/entities.md): единый субстрат сплетен,
хроники, обязательств и (дальше) стражи/сюжета. Состояние остаётся авторитетным — журнал
не пересобирает мир, он ПОМНИТ, что случилось.

Обязательство (promise) — дело со статусом: active → done|broken. Мир напоминает о слове
в промпте и ведёт на встречу рутиной (worldsim: кандидат «appointment» в срок).
"""

from __future__ import annotations

from aidnd.server.play.engine.core import _gt, _phase, _store, _wid

# публичные глаголы — годятся в сплетни/новости сцены
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
    """Свежие ПУБЛИЧНЫЕ дела (за сутки) — материал «о чём судачит город»."""
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
    """Зафиксировать СЛОВО: дело со статусом active. Срок — фаза суток (кламп по словарю)."""
    due = RU2PHASE.get((when_ru or "").strip().lower(), "morning")
    return record(actor, "promise", obj=to, place=place_label, witnesses=witnesses,
                  status="active",
                  data={"what": (what or "")[:120], "due": due, "where": (where or "")[:60],
                        "node": node, "made_gt": _gt()})


def promises_active(actor: str | None = None) -> list:
    return _store().deeds(_wid(), verb="promise", actor=actor, status="active", limit=20)


def promise_line(d: dict, names: dict | None = None) -> str:
    """Строка-напоминание для промпта должника."""
    to = (names or {}).get(d["obj"], d["obj"])
    where = d["data"].get("where") or d["place"] or ""
    return (f"ТЫ ДАЛ СЛОВО ({to}): {d['data'].get('what', '')} — "
            f"{PHASE_RU.get(d['data'].get('due', ''), 'в срок')}"
            + (f", место: {where}" if where else "") + ". Слово держат.")


def promise_resolve(d: dict, done: bool) -> None:
    _store().deed_status(_wid(), d["id"], "done" if done else "broken")
