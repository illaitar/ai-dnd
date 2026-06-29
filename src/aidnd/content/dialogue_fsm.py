"""Стейт-машина диалога: разговор пары агентов проходит ФАЗЫ, переходы — по СОСТОЯНИЮ (utility, не пороги).

Одна машина для игрок↔NPC и NPC↔NPC. Два трека:
  дружелюбный: opening → small_talk → substance → confidence → closing
  агрессивный: menace → pressure → resolve         (когда отношение враждебно / разговор сорвался)
Внутри фазы КОНКРЕТНУЮ речевую способность выбирает utility-арбитр; фаза лишь задаёт допустимый набор и цель.
Длина фаз ЭМЕРДЖЕНТНА: пока ready(текущей) ≥ ready(следующей) — остаёмся (болтун тянет, бирюк проскакивает).
Никаких новых сущностей — кормится тем, что уже построено (знакомство/отношения/черты/нужды/агенда/терпение).
"""

from __future__ import annotations

from dataclasses import dataclass, field

FRIENDLY = ["opening", "small_talk", "substance", "confidence", "closing"]
HOSTILE = ["menace", "pressure", "resolve"]

# фаза → допустимые речевые способности (арбитр выбирает из них по состоянию)
PHASE_CAPS = {
    "opening":    {"introduce", "greet"},
    "small_talk": {"smalltalk", "opine", "inquire", "greet"},
    "substance":  {"inform", "gossip", "opine", "deceive", "inquire"},
    "confidence": {"confide", "offer", "request", "inform", "deceive"},
    "closing":    {"farewell", "excuse"},
    "menace":     {"menace", "rebuff"},
    "pressure":   {"threaten", "demand", "extort", "intimidate"},
    "resolve":    {"attack", "yield", "break_off"},
}


@dataclass
class Conversation:
    a: str                                    # инициатор (часто игрок)
    b: str                                    # собеседник
    track: str = "friendly"                   # friendly | hostile
    phase: str = "opening"
    turn: int = 0                             # реплик в разговоре
    phase_turn: int = 0                       # реплик в текущей фазе
    rapport: float = 0.0                      # теплота, накопленная за разговор (поверх базового отношения)
    covered: set = field(default_factory=set)  # затронутые темы — не повторяться
    goal: str = ""                            # топик/намерение (у NPC с агендой)
    known: bool | None = None                 # знали ли друг друга ДО этого разговора (снапшот; None → считать по графу)
    log: list = field(default_factory=list)   # транскрипт пары [{who,line}] — обе стороны, последние реплики (для контекста)


def _affinity(world, a, b, player):
    """Отношение a к b: к игроку — Relationships, к NPC — граф мнений."""
    from .agent import opinion
    if b == player:
        from ..world.components import Relationships
        rels = world.ecs.get(a, Relationships)
        e = rels.edges.get(player) if rels else None
        return getattr(e, "affinity", 0.0) if e else 0.0
    return opinion(world, a, b)


def _trust(world, a, b, player):
    if b == player:
        from ..world.components import Relationships
        rels = world.ecs.get(a, Relationships)
        e = rels.edges.get(player) if rels else None
        return getattr(e, "trust", 0.0) if e else 0.0
    return 0.0                                 # NPC↔NPC доверие отдельно не моделируем — берём симпатию


def is_hostile_pair(world, a, b, player) -> bool:
    """Враждебны ли: крепкая неприязнь ИЛИ боевой флаг (для переключения на агр-трек)."""
    if _affinity(world, a, b, player) <= -0.4:
        return True
    try:
        from ..world.components import Relationships
        rels = world.ecs.get(a, Relationships)
        e = rels.edges.get(b) if rels else None
        return bool(e and (getattr(e, "fear", 0) > 0.6 or "hostile" in (getattr(e, "tags", []) or [])))
    except Exception:
        return False


def _readiness(world, conv: Conversation, speaker: str, listener: str, player: str) -> dict:
    """Готовность каждой фазы текущего трека из состояния агента-говорящего."""
    from ..npc.integration import npc_state
    from . import acquaintance
    st = npc_state(world, speaker, player)
    if conv.known is not None:                             # снапшот «знакомы ДО разговора» (запись встречи не путает)
        acq = 1.0 if conv.known else 0.0
    else:
        acq = 1.0 if acquaintance.acquainted(world, speaker, listener) else 0.0
    trust = _trust(world, speaker, listener, player)
    rap = conv.rapport
    patience = max(0.0, 1.0 - conv.turn * 0.18)            # терпение тает с числом реплик (П2)
    busy = st.n("purpose")                                  # занят делом → проскакивает светское
    has_goal = 1.0 if (st.agenda or conv.goal) else 0.0
    if conv.track == "hostile":
        return {
            "menace":   1.2 - conv.phase_turn * 0.5,        # коротко осадить
            "pressure": 0.5 + st.t("bravery") * 0.6 + has_goal * 0.4,
            "resolve":  0.2 + conv.phase_turn * 0.4 + (1 - patience) * 0.6,  # дожали/надоело → развязка
        }
    return {
        "opening":    (1.0 - acq) * 1.4 - conv.phase_turn * 0.6,           # чужие держатся; знакомые мимо
        "small_talk": st.t("sociability") * 0.8 + st.n("social") * 0.5 - busy * 0.6 + acq * 0.2,
        "substance":  acq * 0.4 + rap * 0.8 + st.t("curiosity") * 0.4 + has_goal * 0.5 + 0.2,
        "confidence": trust * 1.1 + rap * 0.35 - st.t("pride") * 0.3,   # секреты/сделки — В ОСНОВНОМ по доверию, рапорт лишь помогает
        "closing":    (1.0 - patience) + st.n("fatigue") * 0.4 + st.n("hunger") * 0.3 - rap * 0.4,
    }


def advance(world, conv: Conversation, speaker: str, listener: str, player: str,
            trigger: str | None = None) -> Conversation:
    """Один шаг машины: выбрать трек, продвинуть фазу (монотонно вперёд по readiness). Мутирует conv."""
    hostile = trigger == "hostile" or is_hostile_pair(world, speaker, listener, player)
    new_track = "hostile" if hostile else ("friendly" if trigger == "calm" or conv.track == "friendly" else conv.track)
    if hostile and conv.track != "hostile":
        conv.track, conv.phase, conv.phase_turn = "hostile", "menace", 0
    elif not hostile and conv.track == "hostile" and trigger == "calm":
        conv.track, conv.phase, conv.phase_turn = "friendly", "closing", 0   # деэскалация → к завершению по-доброму
    conv.track = new_track if new_track in ("friendly", "hostile") else conv.track

    order = HOSTILE if conv.track == "hostile" else FRIENDLY
    ready = _readiness(world, conv, speaker, listener, player)
    cur = conv.phase if conv.phase in order else order[0]
    i = order.index(cur)
    # монотонно вперёд, не больше ОДНОЙ фазы за реплику: следующая, если её готовность ≥ текущей
    nxt = i + 1 if (i + 1 < len(order) and ready.get(order[i + 1], 0) >= ready.get(order[i], 0)) else i
    new_phase = order[nxt]
    conv.phase_turn = conv.phase_turn + 1 if new_phase == conv.phase else 0
    conv.phase = new_phase
    conv.turn += 1
    if conv.track == "friendly":                          # разговор сам теплеет → после знакомства/светской открывается «по делу»
        conv.rapport = min(1.0, conv.rapport + 0.12)
    return conv


def phase_intent(phase: str) -> str:
    """Цель фазы для LLM-нарратора (situation/intent в render_dialogue)."""
    return {
        "opening":    "introduce yourself by name and find out who this is" ,
        "small_talk": "make light small talk, build a bit of rapport",
        "substance":  "share news, rumours or your honest opinion, as far as you trust them",
        "confidence": "confide something deeper, propose a deal or ask a favour — you trust them",
        "closing":    "wind the conversation down and take your leave",
        "menace":     "size them up coldly and warn them off",
        "pressure":   "press them hard — threaten or demand",
        "resolve":    "force the issue: attack, back down or break it off",
    }.get(phase, "respond in character")
