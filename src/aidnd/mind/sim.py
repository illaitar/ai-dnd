"""Симуляция: восприятие → решение → применение к миру → апрейзал эмоций. Один тик = один
выбор примитива. Это стенд для проверки эмерджентных сценариев (без npcdebug/LLM).

Где был бы LLM (в продовом контуре): apprise неоднозначных событий (Tier-2), формирование НОВОЙ
ситуативной цели в propose_goals, рендер речевого акта say(...) в текст, rerank в recall. Здесь
всё механически — чтобы сценарии были детерминированы и проверяемы.
"""

from __future__ import annotations

from dataclasses import dataclass

from .act import decide
from .tick import appraise


@dataclass
class Percept:
    here: str
    exits: list
    present: list                   # тела ЗДЕСЬ (со-локация) — свидетели, острые угрозы
    nearby: list                    # тела в радиусе видимости (соседние места) — цели/опасности вдали
    me: object                      # моё тело (Body)


def perceive(state, world, radius: int = 1) -> Percept:
    me = world.bodies[state.config.id]
    present = world.present_at(me.place, exclude=(me.id,))
    nearby = [b for b in world.bodies.values()
              if b.id != me.id and 0 < world.dist(me.place, b.place) <= radius]
    return Percept(here=me.place, exits=world.neighbors(me.place),
                   present=present, nearby=nearby, me=me)


def apply(action, state, world) -> dict:
    """Применить выбранный примитив к миру. Возвращает событие (для лога/апрейзала)."""
    me = world.bodies[state.config.id]
    ev = {"action": action.label()}
    me.talking_to = None                                     # любой не-say ход выходит из разговора
    if action.kind == "move" and action.to:
        me.place = action.to
    elif action.kind == "attack" and action.target in world.bodies:
        tb = world.bodies[action.target]
        tb.hp -= 6
        if tb.hp <= 0:
            tb.alive = False
        ev["hit"] = tb.id
        # жертва-НПЦ переживает нападение (фикс. апрейзал) И начинает БОЯТЬСЯ нападавшего адресно
        # → в следующий тик формируется цель «уцелеть» именно от него (бегство/чаще — погоня хищника)
        vs = world.npc_minds.get(tb.id) if hasattr(world, "npc_minds") else None
        if vs is not None:
            appraise(vs, {"goal_impact": -0.8, "intent": "deliberate", "desert": -0.6,
                          "harm": 0.8, "control": 0.1, "norm": -0.5}, source=me.id)
            r = vs.rel(me.id)
            r["fear"] = max(r["fear"], 0.85)
            r["affinity"] = min(r["affinity"], -0.3)
    elif action.kind == "take":
        if action.target in world.bodies:
            tb = world.bodies[action.target]
            if tb.loot:
                got = tb.loot.pop(0)
                me.loot.append(got)
                ev["took"] = got.name
        elif action.item is not None and action.item in world.ground.get(me.place, []):
            world.ground[me.place].remove(action.item)
            me.loot.append(action.item)
            ev["took"] = action.item.name
    elif action.kind == "give" and action.target in world.bodies and action.item in me.carrying:
        me.carrying.remove(action.item)
        world.bodies[action.target].carrying.append(action.item)
        ev["gave"] = action.item.name
    elif action.kind == "use" and action.item is not None:
        nd = getattr(action.item, "satisfies", None)
        if nd and nd in state.needs:
            state.needs[nd] = max(0.0, state.needs[nd] - 0.6)
            ev["satisfied"] = nd
    elif action.kind == "say":
        ev["say"] = action.say
        if action.say in ("chat", "flatter", "ask") and action.target in world.bodies:
            me.talking_to = action.target                    # «я сейчас говорю с ним» (видно всем в зале)
            state.needs["social"] = max(0.0, state.needs.get("social", 0.0) - 0.25)   # общение закрывает нужду
            r = state.rel(action.target)
            r["affinity"] = min(1.0, r["affinity"] + (0.06 if action.say == "flatter" else 0.04))
            vs = world.npc_minds.get(action.target) if hasattr(world, "npc_minds") else None
            if vs is not None:                                    # взаимная симпатия крепнет
                vs.needs["social"] = max(0.0, vs.needs.get("social", 0.0) - 0.12)
                rr = vs.rel(me.id)
                rr["affinity"] = min(1.0, rr["affinity"] + 0.04)
            ev["talked"] = action.target
    return ev


def tick(state, world, temp: float = 0.0, rng=None) -> dict:
    """Один ход: восприятие → решение → применение. Эмоции/нужды двигает внешний advance при желании."""
    p = perceive(state, world)
    (action, goal, u), ranked = decide(state, world, p, temp=temp, rng=rng)
    ev = apply(action, state, world)
    return {"clock": world.__dict__.get("clock", 0), "action": action, "goal": goal,
            "utility": round(u, 3), "event": ev,
            "ranked": [(a.label(), g.label() if g else "idle", round(x, 3)) for a, g, x in ranked[:5]]}
