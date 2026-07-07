"""РАЗГОВОР-ОБЪЕКТ живой сцены (docs/locations.md): {зона, участники, последние реплики,
долг ответа}. Заменяет «нуджи в память»: участники видят беседу СТРУКТУРНО в промпте,
долг ответа — верхний импульс дирижёра, «я уже здоровался» — факт разговора, не кулдаун.

Чистая логика над lv-словарём (тестируется без LLM/сервера). Разговор живёт в зоне:
ушёл из зоны — вышел из беседы; тишина N тиков — беседа распалась.

Key functions
-------------
conv_of(lv, pid) -> dict | None : Find conversation containing a participant.
conv_note_say(lv, frm, to, text, zone) -> dict : Record speech act; merge and set debt.
conv_debt_to(lv, pid) -> dict | None : Check if participant has unanswered question.
conv_tick(lv, place_of) : Age conversations; remove stale or empty ones.
conv_block(lv, pid, names) -> str | None : Build current conversation prompt block.
"""

from __future__ import annotations

QUIET_DIE = 3          # тиков тишины → разговор распался
LOG_KEEP = 6           # сколько последних реплик держим
DEBT_STALE = 3         # тиков без ответа → долг «прогорел» (адресат явно ушёл от ответа)


def _convs(lv: dict) -> list:
    return lv.setdefault("convs", [])


def conv_of(lv: dict, pid: str):
    """Разговор, в котором состоит pid (участник может быть только в одном)."""
    return next((c for c in _convs(lv) if pid in c["members"]), None)


def conv_note_say(lv: dict, frm: str, to: str, text: str, zone: str | None) -> dict:
    """Реплика frm→to: попадает в их разговор (создаём/присоединяем/сливаем).
    Вопрос или прямое обращение вешает ДОЛГ ОТВЕТА на адресата."""
    ca, cb = conv_of(lv, frm), conv_of(lv, to)
    if ca and cb and ca is not cb:                      # два кружка слились репликой
        ca["members"] = list(dict.fromkeys(ca["members"] + cb["members"]))
        ca["log"] = (cb["log"] + ca["log"])[-LOG_KEEP:]
        _convs(lv).remove(cb)
        c = ca
    else:
        c = ca or cb
    if c is None:
        c = {"id": f"c{len(_convs(lv)) + 1}|{lv.get('clock', 0)}", "zone": zone,
             "members": [frm, to], "log": [], "debt": None, "quiet": 0}
        _convs(lv).append(c)
    for m in (frm, to):
        if m not in c["members"]:
            c["members"].append(m)
    c["zone"] = zone or c.get("zone")
    c["log"] = (c["log"] + [(frm, text[:120])])[-LOG_KEEP:]
    c["quiet"] = 0
    if c.get("debt") and c["debt"].get("to") == frm:    # ответил — долг гасится
        c["debt"] = None
    c["debt"] = {"to": to, "frm": frm, "text": text[:100], "ticks": 0}
    return c


def conv_debt_to(lv: dict, pid: str):
    """Висит ли на pid долг ответа (ему задали вопрос/обратились)."""
    c = conv_of(lv, pid)
    if c and c.get("debt") and c["debt"]["to"] == pid and c["debt"]["ticks"] <= DEBT_STALE:
        return c["debt"]
    return None


def conv_tick(lv: dict, place_of) -> None:
    """Старение разговоров: тишина копится, ушедшие из зоны выходят, пустые распадаются.
    place_of(pid) → текущее место тела (зона) или None."""
    for c in list(_convs(lv)):
        c["quiet"] += 1
        if c.get("debt"):
            c["debt"]["ticks"] += 1
            if c["debt"]["ticks"] > DEBT_STALE:
                c["debt"] = None                        # вопрос повис и прогорел — факт беседы
        if c.get("zone"):
            c["members"] = [m for m in c["members"]
                            if place_of(m) in (c["zone"], None)]
        if len(c["members"]) < 2 or c["quiet"] >= QUIET_DIE:
            _convs(lv).remove(c)


def conv_block(lv: dict, pid: str, names: dict) -> str | None:
    """Структурный блок «ТЕКУЩИЙ РАЗГОВОР» для промпта участника."""
    c = conv_of(lv, pid)
    if not c or not c["log"]:
        return None
    nm = lambda i: "ты" if i == pid else names.get(i, i)          # noqa: E731
    others = ", ".join(names.get(m, m) for m in c["members"] if m != pid)
    lines = [f"ТЕКУЩИЙ РАЗГОВОР (с {others}" + (f", {c['zone']}" if c.get("zone") else "") + "):"]
    for who, txt in c["log"]:
        lines.append(f"  {nm(who)}: «{txt}»")
    d = c.get("debt")
    if d and d["to"] == pid:
        lines.append(f"  ⚑ ТЕБЕ обращена последняя реплика ({nm(d['frm'])}) — ответь по существу "
                     "или честно уйди от ответа; НЕ переспрашивай то, что уже прозвучало выше.")
    elif d:
        lines.append(f"  (ждут ответа от {nm(d['to'])} — не отвечай за него)")
    return "\n".join(lines)
