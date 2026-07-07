"""Домен ДИАЛОГ (хендлеры /talk /say) — распил world.py (docs/loop.md). Знакомство, реплики; тон
слов игрока → отношения/доверие/страх/эмоции. Голос NPC — сервис world._voice.

Key functions
-------------
talk(request)  [POST /api/play/talk] : the player walks up to an NPC — first contact reveals the
    name, marks the NPC as busy in this conversation, seeds a 'social' need bump, writes the
    introduction into both memories, materializes the NPC's visible gear, and returns the portrait
    + relationship + topic snapshot. Advances the world by PB['talk_min'].
say(request)   [POST /api/play/say] : one spoken line to the current NPC — tone of the player's
    words shifts affinity/trust/fear/emotion; the NPC answers in its own voice (world._voice) and
    both sides remember it. Contract offers/acceptance ride on the same line (mechanics.contracts).
"""

from __future__ import annotations

import os

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
from aidnd.server.play.engine.world import _play, _voice, _world_tick
from aidnd.server.play.mechanics.contracts import _contract_offer, _contract_on_talk
from aidnd.server.play.mechanics.items import _CRAFT, _materialize_npc, _pc_coins


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
    _pc().rel(npc)  # заговорил = познакомился (имя открыто)
    _S["dlg"] = npc  # мир знает: чужак занят ЭТИМ разговором
    lv = _S.get("live")
    if lv:  # сцена видит действие игрока
        lv["last"][PLAYER] = f"подошёл и заговорил с {p.name}"
        lv["pc_spoke"] = True
        from aidnd.server.play.engine.convo import conv_note_say
        zplace = lv["world"].bodies[PLAYER].place if PLAYER in lv["world"].bodies else None
        conv_note_say(lv, PLAYER, npc, "(подходит и заговаривает)", zplace)
    _gt_add(PB["talk_min"])
    st = p.state
    st.needs["social"] = max(st.needs.get("social", 0.0), 0.4)
    if first:  # знакомство ложится в память ОБОИМ
        st.memory.add("незнакомец (игрок) подошёл и заговорил со мной", _mt(), 0.4, about=[PLAYER])
        _pc_remember(f"я познакомился с {p.name} ({p.role})", 0.45, about=[npc])
        _npc_save(npc)
    _materialize_npc(npc, "visible")  # видимое (экипировка+ключи) — настоящие предметы
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
    ]  # что игрок ЗНАЕТ об этом человеке
    try:
        contract = _contract_offer(npc)  # у него может быть к тебе дело (из агенды)
    except (LLMUnavailable, LLMBadOutput):  # без модели не притворяемся (принцип 1)
        raise
    except Exception:  # noqa: BLE001 — прочие сбои просьбы не ломают диалог
        contract = None
    return {
        "name": p.name,
        "role": p.role,
        "init": p.name[0],
        "color": "#8a6fae",
        "contract": contract,
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
        "line": _voice(p, rel, "greet"),
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
    _S["dlg"] = npc  # разговор продолжается
    lv = _S.get("live")
    if lv:  # сцена видит: чужак беседует (реплика — в разговор-объект)
        lv["last"][PLAYER] = f"беседует с {p.name}: «{text[:50]}»"
        lv["pc_spoke"] = True
        from aidnd.server.play.engine.convo import conv_note_say
        zplace = lv["world"].bodies[PLAYER].place if PLAYER in lv["world"].bodies else None
        conv_note_say(lv, PLAYER, npc, text[:100], zplace)
    _gt_add(PB["talk_min"])
    line = _voice(p, rel, "reply", text)
    tone = _S.get("last_tone", "neutral")  # тон слов игрока — из уст самого NPC
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
    )  # диалог остаётся в памяти NPC
    _pc_remember(f"{p.name} на «{text[:60]}» ответил(а): «{line[:90]}»", 0.35, about=[npc])
    _npc_save(npc)
    emo = _emo(p.state)
    ct_done = _contract_on_talk(npc)  # befriend-уговор: цель прониклась
    t = _world_tick()  # реплика = ход мира (пошаговость)
    return {
        **t,
        "line": line,
        "aff": round(rel["affinity"], 2),
        "trust": round(rel.get("trust", 0), 2),
        "fear": round(rel.get("fear", 0), 2),
        "emotion": emo,
        "portrait": _portrait_url(p, emo),
        "gt": _gt(),
        "contract_done": ct_done,
        "coins": _pc_coins(),
    }
