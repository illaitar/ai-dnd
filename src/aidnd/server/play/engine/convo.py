"""Conversation object of a live scene (docs/locations.md): {zone, participants, recent lines,
answer debt}. Replaces "nudge to memory": participants see conversation STRUCTURALLY in the prompt,
answer debt — the top impulse of the conductor, "I already greeted" — fact of conversation, not cooldown.

Pure logic over lv-dict (tested without LLM/server). Conversation lives in a zone:
left the zone — left the conversation; silence of N ticks — conversation broke apart.

Key functions
-------------
conv_of(lv, pid) -> dict | None : Find conversation containing a participant.
conv_note_say(lv, frm, to, text, zone) -> dict : Record speech act; merge and set debt.
conv_debt_to(lv, pid) -> dict | None : Check if participant has unanswered question.
conv_tick(lv, place_of) : Age conversations; remove stale or empty ones.
conv_block(lv, pid, names) -> str | None : Build current conversation prompt block.
"""

from __future__ import annotations

QUIET_DIE = 3          # ticks of silence → conversation broke apart
LOG_KEEP = 6           # how many recent lines we keep
DEBT_STALE = 3         # ticks without answer → debt "burned out" (addressee clearly avoided answer)


def _convs(lv: dict) -> list:
    return lv.setdefault("convs", [])


def conv_of(lv: dict, pid: str):
    """Conversation in which pid participates (participant can only be in one)."""
    return next((c for c in _convs(lv) if pid in c["members"]), None)


def conv_note_say(lv: dict, frm: str, to: str, text: str, zone: str | None) -> dict:
    """Line from frm→to: goes into their conversation (create/join/merge).
    Question or direct address sets ANSWER DEBT on the addressee."""
    ca, cb = conv_of(lv, frm), conv_of(lv, to)
    if ca and cb and ca is not cb:                      # two circles merged by a line
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
    if c.get("debt") and c["debt"].get("to") == frm:    # answered — debt extinguished
        c["debt"] = None
    c["debt"] = {"to": to, "frm": frm, "text": text[:100], "ticks": 0}
    return c


def conv_debt_to(lv: dict, pid: str):
    """Does pid have an outstanding answer debt (they were asked a question/addressed)."""
    c = conv_of(lv, pid)
    if c and c.get("debt") and c["debt"]["to"] == pid and c["debt"]["ticks"] <= DEBT_STALE:
        return c["debt"]
    return None


def conv_tick(lv: dict, place_of) -> None:
    """Aging conversations: silence accumulates, those who left the zone exit, empty ones break apart.
    place_of(pid) → current body location (zone) or None."""
    for c in list(_convs(lv)):
        c["quiet"] += 1
        if c.get("debt"):
            c["debt"]["ticks"] += 1
            if c["debt"]["ticks"] > DEBT_STALE:
                c["debt"] = None                        # question lingered and burned out — fact of conversation
        if c.get("zone"):
            c["members"] = [m for m in c["members"]
                            if place_of(m) in (c["zone"], None)]
        if len(c["members"]) < 2 or c["quiet"] >= QUIET_DIE:
            _convs(lv).remove(c)


def conv_block(lv: dict, pid: str, names: dict) -> str | None:
    """Structural block "CURRENT CONVERSATION" for participant's prompt."""
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
