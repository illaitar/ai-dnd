"""NPC voice and small narrator-layer helpers (persona → LLM in-character speech).

Key functions
-------------
_voice(p, rel, kind, player_text=None, has_offer=False, offer_pitch=None, twist_line=None) -> str :
    NPC speaks in-character (LLM narrator) — folds in persona, memory of the player, grudges and
    world-lookup facts; records the player's tone. has_offer hints (greet only) that the NPC has
    a pending errand to mention. offer_pitch — the NPC's REAL pending errand (emergent sift
    offer or stashed improvised one) so her spoken words, when she does talk about it, line up
    with the actual contract instead of improvising a different task (reveal-gate unchanged:
    this only grounds WHAT she says, it does not force her to say it). twist_line — a one-time
    emergent-quest reveal (quests/twist.py) stashed for THIS conversation; unlike offer_pitch it
    is FORCED into the opening words (spoken once, then popped by the caller). active_pitch — the
    pitch of a sift quest the giver has ALREADY accepted (status 'active'): unlike offer_pitch (a
    request not yet taken) this is framed as a deal in progress, so the giver keeps his own quest in
    mind instead of forgetting it and improvising unrelated tasks.
_topics_for(p) -> list : Conversation topics — from PERSONA (rumors/wants), not from role table.
_spurns(p) -> bool : Doesn't want to deal with you: enmity or fresh targeted anger.
_DM_SYS : System prompt for the DM-narrator fallback (non-mechanical player actions).
"""

from __future__ import annotations

import json

from ..session.config import PB, PLAYER
from ..session.state import _S
from ..session.time import _mt
from .lookup import _world_lookup

# ─── Narrator/arbiter services moved from world.py (docs/structure.md, Phase B) ────────
# NPC voice, world lookup and DM snapshot — these are arbiter/narrator-layer, not scene; home is here.
_VOICE = {
    "gruff": "грубовато",
    "warm": "тепло",
    "clipped": "сухо и коротко",
    "florid": "витиевато",
    "meek": "робко",
    "booming": "громко, зычно",
}
_STANCE = {
    "warm": "дружелюбно",
    "neutral": "нейтрально",
    "wary": "настороженно",
    "dour": "хмуро",
    "greedy": "с расчётом на выгоду",
    "hostile": "враждебно",
}


def _voice(
    p, rel, kind, player_text=None, has_offer: bool = False, offer_pitch: str | None = None,
    twist_line: str | None = None, active_pitch: str | None = None,
) -> str:
    from ..core import (  # lazy: core.py imports narrator.voice at module top
        _binfo,
        _city_name,
        _model,
    )

    mgr = _model()
    per = getattr(p, "persona", None) or {}
    bits = [f"Ты — {p.name}, {p.role} на фронтире (тёмное фэнтези)."]
    if per:  # rich persona from pool
        if per.get("origin"):
            bits.append(f"Родом: {per['origin']}.")
        if per.get("voice"):
            bits.append(f"Говоришь {_VOICE.get(per['voice'], 'обычно')}.")
        if per.get("speech"):
            bits.append("Речевые привычки: " + "; ".join(per["speech"][:2]) + ".")
        if per.get("quirk"):
            bits.append(f"Причуда: {per['quirk']}.")
        if per.get("wants"):
            bits.append("Стремишься: " + "; ".join(per["wants"][:2]) + ".")
        bits.append(f"К чужаку держишься {_STANCE.get(per.get('stance'), 'нейтрально')}.")
        if per.get("secret"):
            bits.append(
                f"У тебя есть тайна (НЕ выдавай без веской причины): {per['secret'].get('what', '')}."
            )
    if _spurns(p):  # grievance/anger OUTWEIGH persona's warmth
        bits.append(
            "Ты ЗОЛ на этого человека (вспомни, почему) — никакого радушия: "
            "холод, резкость или презрение, по твоему характеру."
        )
    here_name = _binfo(_S.get("inside"))["name"] if _S.get("inside") else "улица города"
    bits.append(
        f"МЕСТО: город называется «{_city_name()}», вы сейчас — {here_name}. "
        "КАНОН: о людях и местах ЭТОГО города говори только то, что есть в памяти и справке — "
        "здешних имён и заведений не выдумывай (и город зови ТОЛЬКО его настоящим именем). "
        "Вымысел допустим лишь о дальних краях и былом, и подавай его как слух."
    )
    bits.append(
        "СОБЕСЕДНИК — чужак-путник. Его внешности, одежды и имени ты НЕ ЗНАЕШЬ, пока он сам "
        "не показал/назвал — НЕ приписывай ему одежд, черт и званий (не путай его с другими "
        "посетителями из памяти)."
    )
    lv = _S.get("live") or {}
    just = (lv.get("last") or {}).get(p.id)
    if just and just != "—":
        bits.append(f"Только что ты: {just}.")
    mems = p.state.memory.recall(player_text or "разговор с чужаком-игроком", now=_mt(), k=5)
    mine = [m for m in mems if PLAYER in (m.about or [])]
    other = [m for m in mems if PLAYER not in (m.about or [])]
    if mine:  # continuity: NPC remembers YOU exactly
        bits.append("ТЫ ПОМНИШЬ О СОБЕСЕДНИКЕ: " + "; ".join(m.text for m in mine) + ".")
    if other:  # other — background, NOT about the interlocutor
        bits.append(
            "ПРОЧЕЕ ИЗ ПАМЯТИ (про ДРУГИХ людей, НЕ про собеседника — не смешивай): "
            + "; ".join(m.text for m in other)
            + "."
        )
    if player_text:  # question about world → lookup immediately (no invention)
        info = _world_lookup(player_text, _S.get("loc"))
        if "не скажу" not in info:
            bits.append(
                f"СПРАВКА МИРА (это истина — придерживайся её, имена и места не выдумывай): {info}."
            )
    bits.append(
        f"Симпатия к собеседнику {rel.get('affinity', 0):.2f} (низкая — суше/настороже, высокая — теплее). "
        "Отвечай В ХАРАКТЕРЕ, живой разговорной речью, 1-2 фразы, без ремарок-описаний. "
        "Помнишь собеседника — покажи это естественно, не пересказывай память дословно. "
        'ФОРМАТ — строго JSON: {"say": "<реплика>", "player_tone": '
        '"friendly|neutral|rude|threat"} (player_tone — как звучали слова СОБЕСЕДНИКА к тебе). '
        "Если для ответа НУЖЕН факт о городе или людях (где что находится, кто есть кто) — "
        'верни СТРОГО JSON {"ask": "<короткий вопрос>"} вместо реплики: получишь справку и ответишь.'
    )
    acquainted = any(PLAYER in (m.about or []) for m in p.state.memory.items)
    user = (
        (
            "К тебе снова подошёл тот самый человек, которого ты помнишь, — поприветствуй его "
            "КАК ЗНАКОМОГО, опираясь на то, что помнишь."
            if acquainted
            else "К тебе подошёл незнакомец и заговорил — брось первую реплику."
        )
        if kind == "greet"
        else f"Он говорит: «{player_text}». Ответь."
    )
    if offer_pitch:  # ground what she says in the REAL pending errand (don't improvise another one)
        bits.append(
            f"У ТЕБЯ ЕСТЬ НАСТОЯЩЕЕ ДЕЛО/ПРОСЬБА К НЕМУ: {offer_pitch}. Если разговор коснётся "
            "твоих забот или дела — держись именно ЭТОЙ просьбы (не выдумывай другую, не путай "
            "суть). Раскрывай её только когда уместно по ходу разговора."
        )
    if active_pitch:  # already agreed — this is the deal in progress, not a fresh request
        bits.append(
            f"ОН УЖЕ ВЗЯЛСЯ ПОМОЧЬ ТЕБЕ С ЭТИМ ДЕЛОМ: {active_pitch}. Вы УЖЕ уговорились — это твоя "
            "живая забота, о которой вы условились; помни о ней, не выдумывай других поручений и не "
            "забывай, о чём просил(а). Спроси, как продвигается, или подскажи — по ходу разговора."
        )
    if twist_line:  # a one-time emergent reveal — FORCE it into her opening words (spoken once)
        bits.append(
            f"У ТЕБЯ ЕСТЬ СВЕЖАЯ ВЕСТЬ ПО ВАШЕМУ ДЕЛУ, И ТЫ ОБЯЗАН(А) ЕЁ СКАЗАТЬ ПРЯМО СЕЙЧАС: "
            f"{twist_line}"
        )
    if kind == "greet" and has_offer:  # a pending errand — hint it, don't dump it (player must ask)
        user += (
            " У тебя есть к нему дело/просьба — дай это понять между делом, полунамёком, "
            "не выкладывая суть и не называя награду: подробности только если сам спросит о работе."
        )
    msgs = [{"role": "system", "content": " ".join(bits)}, {"role": "user", "content": user}]
    resp = mgr.call("narrator", msgs, options={"temperature": 0.85})
    content = (resp.get("content") if resp else "").strip()

    def _parse(c):
        i, j = c.find("{"), c.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(c[i : j + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        return None

    d = _parse(content)
    if d and d.get("ask"):  # tool call ask: world lookup → second pass
        info = _world_lookup(str(d["ask"]), _S.get("loc"))
        msgs += [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": f"СПРАВКА МИРА: {info}. Теперь ответь собеседнику (тот же JSON-формат).",
            },
        ]
        resp = mgr.call("narrator", msgs, options={"temperature": 0.85})
        content = (resp.get("content") if resp else "").strip()
        d = _parse(content)
    if d and d.get("say"):
        _S["last_tone"] = d.get("player_tone") or "neutral"
        return str(d["say"]).strip() or f"{p.name} молчит."
    _S["last_tone"] = "neutral"
    return content or f"{p.name} молчит."


def _topics_for(p) -> list:
    """Conversation topics — from PERSONA (rumors/wants), not from role table."""
    per = p.persona or {}
    out = [t[:40] for t in (per.get("rumors") or [])[:2]] + [
        t[:40] for t in (per.get("wants") or [])[:1]
    ]
    return out or ["что нового?", "о городе", "о жизни здесь"]


def _spurns(p) -> bool:
    """Doesn't want to deal with you: enmity or fresh targeted anger."""
    rel = p.state.relationships.get(PLAYER) or {}
    ang = p.state.emotion.get("anger", 0)
    return rel.get("affinity", 0) < PB["hostile_aff"] or (
        ang > 0.5 and p.state.emotion_target.get("anger") == PLAYER
    )


_DM_SYS = (
    "Ты — мастер настольной игры. Игрок заявил свободное действие. Тебе дан СНИМОК живой сцены "
    "(место, время, люди и их занятия, последние реплики, предметы рядом) — это ЕДИНСТВЕННАЯ "
    "правда: опирайся на неё и вплетай её детали (кто рядом чем занят, что слышно), НИЧЕГО не "
    "выдумывай сверх снимка и не противоречь ему (если люди греются у очага — очаг горит). "
    "Опиши ТОЛЬКО само действие игрока — как оно СВЕРШАЕТСЯ: игрок кричит, выхватывает нож, "
    "швыряет кружку, бьёт кулаком по столу — это ПРОИСХОДИТ. НЕ мешай ему и не выдумывай, почему "
    "оно «не выходит» или на чём «застревает» — свободу действий игрока не ограничивай. НЕ "
    "описывай, как реагируют окружающие — их ответ придёт следующим ходом. Не решай за мир чужую "
    "участь (попал ли удар, погиб ли кто-то) — только то, что делает сам игрок. Ответь 1-2 "
    "фразами: 2-е лицо, настоящее время, сухо."
)
