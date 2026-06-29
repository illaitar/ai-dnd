"""NPC-агент: командная шина + behaviour-выбор исходящих команд + взаимодействие NPC↔NPC.

Команда = (gate/applicable, utility, execute). Машина каждый раунд выбирает для NPC ИСХОДЯЩУЮ команду по
утилитарности против со-локализованного соседа или мира — это П6 (проактивность). Сплетни двигают граф
мнений (world.opinions) и расползаются по сети — П5 (диффузия/репутация). LLM — голос поверх событий
(здесь только механика/детерминизм, чтобы симуляция была реплей-безопасной и дешёвой)."""

from __future__ import annotations

import random

from ..gen.seeds import subseed
from ..world.components import Persona


# --------------------------------------------------------------------------- #
#  Граф мнений NPC ↔ NPC (П4): world.opinions[a][b] = affinity [-1..1]         #
# --------------------------------------------------------------------------- #
def _opinions(world) -> dict:
    if not hasattr(world, "opinions") or world.opinions is None:
        world.opinions = {}
    return world.opinions


def _seed_opinion(world, a: str, b: str) -> float:
    """База мнения a о b: фракционное отношение + детерминированный шум характера."""
    base = 0.0
    try:
        from ..rules.factions import social_reaction
        base = social_reaction(world, a, b)
    except Exception:
        base = 0.0
    rng = random.Random(subseed(world.seed, "opinion", a, b))
    return max(-1.0, min(1.0, base + rng.uniform(-0.5, 0.5)))  # разброс характеров: кто-то невзлюбит крепко


def opinion(world, a: str, b: str) -> float:
    op = _opinions(world)
    if a in op and b in op[a]:
        return op[a][b]
    v = _seed_opinion(world, a, b)
    op.setdefault(a, {})[b] = v
    return v


def set_opinion(world, a: str, b: str, v: float) -> None:
    _opinions(world).setdefault(a, {})[b] = max(-1.0, min(1.0, v))


def _name(world, npc: str) -> str:
    p = world.ecs.get(npc, Persona)
    return p.name if p else npc


def _strongest_opinion(world, a: str, exclude: str | None):
    """О ком у a самое яркое мнение (для сплетни) — кроме самого a и собеседника, и ТОЛЬКО о ЗНАКОМЫХ."""
    from . import acquaintance
    best, bv = None, 0.0
    for c in world.npcs():
        if c == a or c == exclude or not world.is_alive(c):
            continue
        if not acquaintance.acquainted(world, a, c):       # сплетничают лишь о тех, кого знают
            continue
        v = opinion(world, a, c)
        if abs(v) > abs(bv):
            best, bv = c, v
    return best, bv


# --------------------------------------------------------------------------- #
#  Команды агента: applicable / utility / execute(world,a,b) -> текст-событие  #
# --------------------------------------------------------------------------- #
def _socialize_u(world, a, b):
    return 0.45 + 0.25 * max(0.0, opinion(world, a, b))


def _socialize_x(world, a, b):
    set_opinion(world, a, b, opinion(world, a, b) + 0.05)         # общение чуть теплит
    return f"{_name(world, a)} перекинулся словом с {_name(world, b)}."


def _gossip_ap(world, a, b):
    c, v = _strongest_opinion(world, a, b)
    return c is not None and abs(v) >= 0.35 and opinion(world, a, b) >= -0.1


def _gossip_u(world, a, b):
    _c, v = _strongest_opinion(world, a, b)
    return 0.40 + abs(v) * 0.45                                   # ярче мнение → охотнее сплетничает


def _gossip_x(world, a, b):
    c, v = _strongest_opinion(world, a, b)
    if c is None:
        return f"{_name(world, a)} поболтал с {_name(world, b)}."
    nb = opinion(world, b, c) + 0.3 * (v - opinion(world, b, c))  # ДИФФУЗИЯ: мнение b о c тянется к мнению a
    set_opinion(world, b, c, nb)
    tone = "нахваливает" if v > 0 else "чернит"
    return f"{_name(world, a)} шепчет {_name(world, b)} про {_name(world, c)} — {tone}."


def _confront_ap(world, a, b):
    return opinion(world, a, b) <= -0.5              # только крепкая неприязнь (фракц./резкий характер)


def _confront_u(world, a, b):
    return 0.6 + 0.5 * (abs(opinion(world, a, b)) - 0.5)  # вспыхивает у недругов, ярче при сильной злости


def _confront_x(world, a, b):
    set_opinion(world, b, a, opinion(world, b, a) - 0.1)
    return f"{_name(world, a)} сцепился с {_name(world, b)}."


def _agenda_ap(world, a, _b):
    from .agency import is_active
    return is_active(world, a)


def _agenda_u(world, _a, _b):
    return 0.60


def _agenda_x(world, a, _b):
    ag = (getattr(world, "agendas", None) or {}).get(a) or {}
    goal = ag.get("goal") or "свои дела"
    return f"{_name(world, a)} продвигает замысел: {goal}."


# (key, target_kind, applicable, utility, execute)
PEER_COMMANDS = [
    ("socialize", lambda w, a, b: True, _socialize_u, _socialize_x),
    ("gossip", _gossip_ap, _gossip_u, _gossip_x),
    ("confront", _confront_ap, _confront_u, _confront_x),
]
SELF_COMMANDS = [
    ("pursue_agenda", _agenda_ap, _agenda_u, _agenda_x),
]


# self-care: NPC утоляет накопленную нужду (виден как обрывок жизни города)
def _eat_x(world, a, _b):
    from ..npc.integration import relax_need
    relax_need(world, a, "hunger")
    return f"{_name(world, a)} подкрепляется."


def _rest_x(world, a, _b):
    from ..npc.integration import relax_need
    relax_need(world, a, "fatigue")
    return f"{_name(world, a)} отдыхает, клюёт носом."


def _carouse_x(world, a, _b):
    from ..npc.integration import relax_need
    relax_need(world, a, "social")
    return f"{_name(world, a)} балагурит за кружкой."


def _work_x(world, a, _b):
    from ..npc.integration import relax_need
    relax_need(world, a, "purpose")
    return f"{_name(world, a)} занят делом."


def _commission_x(world, a, _b):
    """NPC заказывает ковку у со-локализованного мастера b: платит, ставит мастера в работу."""
    from ..world.components import Persona
    from . import commerce
    b = _b
    if not b or commerce.busy(world, b):                   # мастер занят — только приценился
        return f"{_name(world, a)} заглядывает к {_name(world, b)}, да тот занят работой."
    pa = world.ecs.get(a, Persona)
    prof = (pa.profession or "") if pa else ""
    tmpl, hours = (("tmpl:shortsword", 8) if any(w in prof for w in ("страж", "guard", "солдат", "наёмник", "рыцар"))
                   else ("tmpl:dagger", 5))                # воин — меч, прочие — кинжал/нож
    price = commerce.craft_price(world, tmpl)
    if not commerce.charge(world, a, b, price):
        return f"{_name(world, a)} приценивается у {_name(world, b)}, да не по карману."
    from .. import config
    until = world.clock.tick + max(1, hours * 60 // config.SIM_MINUTES_PER_TICK)
    item = world.templates[tmpl].name if tmpl in world.templates else "изделие"
    commerce.commission(world, b, tmpl, until, f"куёт {item} для {_name(world, a)}")
    return f"{_name(world, a)} заказывает у {_name(world, b)} ковку: {item} ({price} мон.)."


# способность модели → её эффект (диффузия/потепление/ссора/утоление нужды/сделка), по КЛЮЧУ способности
_EX = {"gossip": _gossip_x, "threaten": _confront_x, "greet": _socialize_x, "seek_out": _socialize_x,
       "solicit_alms": _socialize_x, "advance_agenda": _agenda_x, "commission": _commission_x,
       "eat": _eat_x, "routine_sleep": _rest_x, "carouse": _carouse_x, "routine_work": _work_x}
_DIRECTED = {"gossip", "threaten", "greet", "seek_out", "solicit_alms", "commission"}   # обращено к собеседнику


def _now_hhmm(world) -> int:
    from .. import config
    m = (world.clock.tick * config.SIM_MINUTES_PER_TICK) % (24 * 60)
    return (m // 60) * 100 + (m % 60)


def _affinity(world, a, b, player=None) -> float:
    """Отношение a к b: к ИГРОКУ — из Relationships (канон), к NPC — из графа мнений."""
    if player is not None and b == player:
        from ..world.components import Relationships
        rels = world.ecs.get(a, Relationships)
        edge = rels.edges.get(player) if rels else None
        return getattr(edge, "affinity", 0.0) if edge else 0.0
    return opinion(world, a, b)


def choose(world, a: str, peers: list[str], player: str | None = None):
    """ЕДИНЫЙ behaviour-выбор: NPC взвешивает self-care (по нуждам), агенду и СОЦКОНТАКТ с самым заметным
    из присутствующих — где ИГРОК участвует как равный «сосед». Выбран собеседником игрок → это проактивный
    подход к нему (тем же арбитром, без спецпути). → (cap_key, target|None, ex) или None."""
    from ..npc import Context, Stimulus, choose_multi
    from ..npc.integration import npc_state
    rng = random.Random(subseed(world.seed, "choose", a, world.clock.tick))
    active = False
    try:
        from .agency import is_active
        active = is_active(world, a)
    except Exception:
        active = False
    st = npc_state(world, a)
    if active:
        st.agenda = st.agenda or ["замысел"]
    hhmm = _now_hhmm(world)
    ctxs = [Context(Stimulus("tick", data={"important": active}), time_hhmm=hhmm, world=world)]
    target = None
    if peers:
        def _salience(b):                                  # к кому потянет: сила отношения ИЛИ новизна чужака-новичка
            s = 0.25 + abs(_affinity(world, a, b, player))
            if player is not None and b == player:         # чужак-искатель заметен сам по себе — тянет общительных/любопытных
                s += 0.45 + st.t("sociability") * 0.45 + st.t("curiosity") * 0.3
            return s + rng.uniform(0, 0.3)
        target = max(peers, key=_salience)
        st.relations[target] = {"affinity": _affinity(world, a, target, player),
                                "trust": 0.0, "fear": 0.0, "debt": 0}
        _c, v = _strongest_opinion(world, a, target)       # о ком сплетничать (не о собеседнике)
        juicy = min(1.0, abs(v)) if _c is not None else 0.15
        from . import commerce
        peer_craft = commerce.is_crafter(world, target) and not commerce.is_crafter(world, a)  # собеседник — мастер
        ctxs.append(Context(Stimulus("meet_npc", source=target, target=target,
                                     data={"juicy": juicy, "important": active, "peer_craft": peer_craft}),
                            time_hhmm=hhmm, world=world))
        if player is not None and target == player:        # собеседник — игрок: дельцу/нищему дать предложить/поклянчить
            if st.t("ambition") > 0.6 or st.t("greed") > 0.6:
                ctxs.append(Context(Stimulus("opportunity", source=player), time_hhmm=hhmm, world=world))
            if (world.ecs.get(a, Persona).profession or "") == "нищий":
                ctxs.append(Context(Stimulus("see_rich", source=player), time_hhmm=hhmm, world=world))
    cap, _top = choose_multi(st, ctxs, rng)
    if not cap:
        return None
    tgt = target if cap.key in _DIRECTED else None
    return cap.key, tgt, _EX.get(cap.key, _socialize_x)


def step_social(world, rounds: int = 6) -> list[dict]:
    """Прогнать N раундов взаимодействия NPC↔NPC на текущих позициях. Возвращает события (для наблюдения)."""
    events = []
    for r in range(rounds):
        byplace: dict[str, list[str]] = {}
        for n in world.npcs():
            pos = world.position(n)
            if world.is_alive(n) and pos:
                byplace.setdefault(pos.place_id, []).append(n)
        for place, npcs in byplace.items():
            for a in npcs:
                peers = [n for n in npcs if n != a]
                pick = choose(world, a, peers)
                if not pick:
                    continue
                key, b, ex = pick
                events.append({"round": r, "place": place, "actor": _name(world, a),
                               "target": _name(world, b) if b else None, "cmd": key,
                               "text": ex(world, a, b)})
    return events
