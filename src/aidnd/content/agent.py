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
    """О ком у a самое яркое мнение (для сплетни) — кроме самого a и собеседника."""
    best, bv = None, 0.0
    for c in world.npcs():
        if c == a or c == exclude or not world.is_alive(c):
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


def choose(world, a: str, peers: list[str]):
    """Behaviour-выбор: лучшая по утилите исходящая команда (с лёгким шумом). → (key, target|None, execute)."""
    rng = random.Random(subseed(world.seed, "choose", a, len(peers)))
    cands = []
    for key, ap, ut, ex in SELF_COMMANDS:
        if ap(world, a, None):
            cands.append((ut(world, a, None), key, None, ex))
    for b in peers:
        for key, ap, ut, ex in PEER_COMMANDS:
            if ap(world, a, b):
                cands.append((ut(world, a, b), key, b, ex))
    if not cands:
        return None
    cands.sort(key=lambda c: c[0] + rng.uniform(0.0, 0.15), reverse=True)
    _u, key, b, ex = cands[0]
    return key, b, ex


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
