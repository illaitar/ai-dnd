"""Dialogue domain (handlers /talk /say) — split from world.py (docs/loop.md). Introductions, lines; tone
of player's words → relationships/trust/fear/emotions. NPC voice — service world._voice.

Key functions
-------------
talk(request)  [POST /api/play/talk] : the player walks up to an NPC — first contact reveals the
    name, marks the NPC as busy in this conversation, seeds a 'social' need bump, writes the
    introduction into both memories, materializes the NPC's visible gear, and returns the portrait
    + relationship + topic snapshot. Advances the world by PB['talk_min']. Greeting only — no
    contract card; if the NPC has a pending errand it's stashed (_S['pending_offer']) and merely
    HINTED at in the greeting (voice._voice has_offer=True).
say(request)   [POST /api/play/say] : one spoken line to the current NPC — tone of the player's
    words shifts affinity/trust/fear/emotion; the NPC answers in its own voice (world._voice) and
    both sides remember it. If the player's words show interest in work (_WORK_INTEREST_RE) AND an
    errand is stashed for this NPC, the «Уговор» contract card is attached here instead.
npc_card(request) [POST /api/play/npc] : view-only NPC card (portrait, acquainted, relationship,
    remembered history) — no world tick, no side effects on the conversation.
"""

from __future__ import annotations

import os
import re

from fastapi import Request

from aidnd.inference import LLMBadOutput, LLMUnavailable
from aidnd.server.play.engine.core import (
    _PORT_DIR,
    _S,
    PB,
    PLAYER,
    _emo,
    _gt,
    _gt_add,
    _here,
    _met,
    _mt,
    _npc_save,
    _pc,
    _pc_remember,
    _portrait_url,
    _topics_for,
    router,
)
from aidnd.server.play.engine.resolve import _voice
from aidnd.server.play.engine.world import _play, _world_tick
from aidnd.server.play.mechanics.contracts import _contract_offer, _contract_on_talk
from aidnd.server.play.mechanics.items import _CRAFT, _materialize_npc, _pc_coins

# Player's words signal interest in work/errands — gates the «Уговор» card reveal in say().
_WORK_INTEREST_RE = re.compile(
    # asking about WORK/business — deliberately NOT bare "дел[оа]" (that matches the greeting "как дела")
    r"работ|заработ|подработ|на[её]м|поручен|задани|дельц"
    r"|(?:по|за|о|какое|что за)\s+дел|помо(?:чь|гу|жешь|щь)|ищу зара",
    re.IGNORECASE,
)


@router.post("/api/play/talk")
async def talk(request: Request):
    _city, people, crof_, _cr2b, loc_ = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    if npc not in _here(loc_, crof_):
        return {"error": "его здесь нет — говорить можно с тем, кто рядом"}
    p = people[npc]
    first = npc not in _met()
    _pc().rel(npc)  # spoke = met (name revealed)
    _S["dlg"] = npc  # world knows: stranger is busy IN THIS conversation
    lv = _S.get("live")
    if lv:  # scene sees the player's action
        lv["last"][PLAYER] = f"подошёл и заговорил с {p.name}"
        lv["pc_spoke"] = True
        from aidnd.server.play.engine.convo import conv_note_say
        zplace = lv["world"].bodies[PLAYER].place if PLAYER in lv["world"].bodies else None
        conv_note_say(lv, PLAYER, npc, "(подходит и заговаривает)", zplace)
    _gt_add(PB["talk_min"])
    st = p.state
    st.needs["social"] = max(st.needs.get("social", 0.0), 0.4)
    if first:  # introduction goes into memory OF BOTH
        st.memory.add("незнакомец (игрок) подошёл и заговорил со мной", _mt(), 0.4, about=[PLAYER])
        _pc_remember(f"я познакомился с {p.name} ({p.role})", 0.45, about=[npc])
        _npc_save(npc)
    _materialize_npc(npc, "visible")  # visible (gear+keys) — real items
    rel = st.relationships.get(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    per = p.persona or {}
    emo = _emo(st)
    ports = {
        e: "/portraits/" + path
        for e, path in (p.portraits or {}).items()
        if os.path.exists(os.path.join(_PORT_DIR, path))
    }
    known = [
        m.text
        for m in _pc().memory.recall(f"{p.name} {p.role}", now=_mt(), k=3)
        if npc in (m.about or [])
    ]  # what the player KNOWS about this person
    try:
        offer = _contract_offer(npc)  # he might have business with you (from agenda) — not shown yet
    except (LLMUnavailable, LLMBadOutput):  # without the model, we don't pretend (principle 1)
        raise
    except Exception:  # noqa: BLE001 — other request failures don't break dialogue
        offer = None
    pending = _S.setdefault("pending_offer", {})
    if offer:
        pending[npc] = offer  # stashed — say() reveals it once the player asks about work
    has_offer = bool(pending.get(npc))
    return {
        "name": p.name,
        "role": p.role,
        "init": p.name[0],
        "color": "#8a6fae",
        "aff": round(rel.get("affinity", 0), 2),
        "trust": round(rel.get("trust", 0), 2),
        "fear": round(rel.get("fear", 0), 2),
        "emotion": emo,
        "portrait": _portrait_url(p, emo),
        "portraits": ports,
        "sex": per.get("sex"),
        "age": per.get("age"),
        "origin": per.get("origin"),
        "look": (per.get("look") or {}).get("clothing") or None,
        "keys": [k["name"] for k in (p.keys or [])],
        "crafter": p.role in _CRAFT,
        "recipe": (_CRAFT[p.role].name if p.role in _CRAFT else None),
        "known": known,
        "gt": _gt(),
        "topics": _topics_for(p),
        "line": _voice(p, rel, "greet", has_offer=has_offer),
    }


@router.post("/api/play/say")
async def say(request: Request):
    _city, people, crof_, _cr2b, loc_ = _play()
    b = await request.json()
    npc = b.get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    if npc not in _here(loc_, crof_):
        return {"error": "он уже не рядом — разговор оборвался"}
    p = people[npc]
    rel = p.state.relationships.setdefault(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    text = str(b.get("text", ""))
    _S["dlg"] = npc  # conversation continues
    lv = _S.get("live")
    if lv:  # scene sees: stranger talks (line — in conversation-object)
        lv["last"][PLAYER] = f"беседует с {p.name}: «{text[:50]}»"
        lv["pc_spoke"] = True
        from aidnd.server.play.engine.convo import conv_note_say
        zplace = lv["world"].bodies[PLAYER].place if PLAYER in lv["world"].bodies else None
        conv_note_say(lv, PLAYER, npc, text[:100], zplace)
    _gt_add(PB["talk_min"])
    line = _voice(p, rel, "reply", text)
    tone = _S.get("last_tone", "neutral")  # tone of player's words — from NPC's own lips
    if tone == "friendly":
        rel["affinity"] = min(1.0, rel["affinity"] + PB["tone_friendly_aff"])
    elif tone == "rude":
        rel["affinity"] = max(-1.0, rel["affinity"] - PB["tone_rude_aff"])
        p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.2)
        p.state.emotion_target["anger"] = PLAYER
    elif tone == "threat":
        rel["affinity"] = max(-1.0, rel["affinity"] - PB["tone_threat_aff"])
        rel["fear"] = min(1.0, rel["fear"] + PB["tone_threat_fear"])
        p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.35)
        p.state.emotion_target["anger"] = PLAYER
        p.state.memory.add(f"игрок УГРОЖАЛ мне: «{text[:80]}»", _mt(), 0.8, about=[PLAYER])
    p.state.memory.add(
        f"игрок сказал мне: «{text[:100]}», я ответил(а): «{line[:100]}»",
        _mt(),
        0.4,
        about=[PLAYER],
    )  # dialogue remains in NPC's memory
    _pc_remember(f"{p.name} на «{text[:60]}» ответил(а): «{line[:90]}»", 0.35, about=[npc])
    _npc_save(npc)
    emo = _emo(p.state)
    ct_done = _contract_on_talk(npc)  # befriend-contract: target bought in
    contract = None
    if _WORK_INTEREST_RE.search(text):  # player asked about work — reveal the stashed errand, if any
        contract = (_S.get("pending_offer") or {}).pop(npc, None)
    t = _world_tick()  # line = world turn (turn-based)
    return {
        **t,
        "line": line,
        "aff": round(rel["affinity"], 2),
        "trust": round(rel.get("trust", 0), 2),
        "fear": round(rel.get("fear", 0), 2),
        "emotion": emo,
        "portrait": _portrait_url(p, emo),
        "gt": _gt(),
        "contract": contract,
        "contract_done": ct_done,
        "coins": _pc_coins(),
    }


@router.post("/api/play/npc")
async def npc_card(request: Request):
    """View-only NPC card (portrait/map click) — portrait, acquainted flag, PLAYER→npc relationship,
    remembered history. No world tick, no dialogue side effects."""
    _city, people, crof_, _cr2b, loc_ = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    acquainted = npc in _met()  # BEFORE rel() — rel() setdefaults the entry and would always flip this true
    rel = _pc().rel(npc)
    history = [m.text for m in _pc().memory.items if npc in (m.about or [])][-6:][::-1]
    return {
        "name": p.name,
        "role": p.role,
        "portrait": _portrait_url(p, _emo(p.state)),
        "acquainted": acquainted,
        "rel": {
            "affinity": round(rel.get("affinity", 0.0), 2),
            "trust": round(rel.get("trust", 0.0), 2),
            "fear": round(rel.get("fear", 0.0), 2),
        },
        "history": history,
    }
