"""Actions (common primitives) + selection. enumerate_actions unfolds primitives from perception;
decide scores each (action, target) pair by common utility and takes the best (softmax, at temp→0 — argmax).

Few primitives and they are common: move/attack/take/give/say(act)/use/wait. No «follow», «flee»,
«ambush» — these are all WINNING primitives under specific targets.

Key functions
-------------
Action : Primitive action datatype: move/attack/take/give/say/use/wait.
enumerate_actions(state, world, percept) -> list : Generate feasible actions.
score(state, world, percept) -> list : Score and rank action-goal pairs.
decide(state, world, percept, temp, rng) -> tuple : Select best action.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .goals import propose_goals
from .value import idle_floor, utility

SAY_ACTS = ("chat", "threat", "flatter", "ask", "counter", "accept")


@dataclass
class Action:
    kind: str                       # move|attack|take|give|say|use|wait
    to: str | None = None           # place (move)
    target: str | None = None       # body id
    say: str | None = None          # threat|flatter|ask|counter|accept
    item: object = None             # Item (give|take|use)

    def label(self) -> str:
        if self.kind == "move":
            return f"move→{self.to}"
        if self.kind == "say":
            return f"say:{self.say}→{self.target}"
        if self.kind in ("attack", "take") and self.target:
            return f"{self.kind}→{self.target}"
        if self.kind == "give":
            return f"give:{getattr(self.item, 'name', '?')}→{self.target}"
        if self.kind == "use":
            return f"use:{getattr(self.item, 'name', '?')}"
        return self.kind


def enumerate_actions(state, world, percept) -> list:
    me = percept.me
    acts = [Action("wait")]
    for n in percept.exits:
        acts.append(Action("move", to=n))
    for b in percept.present:
        acts.append(Action("attack", target=b.id))
        acts.append(Action("take", target=b.id))
        for sa in SAY_ACTS:
            acts.append(Action("say", target=b.id, say=sa))
        for it in me.carrying:
            acts.append(Action("give", target=b.id, item=it))
    for it in me.carrying:
        acts.append(Action("use", item=it))
    for it in world.ground.get(me.place, []):
        acts.append(Action("take", item=it))
        acts.append(Action("use", item=it))
    return acts


def score(state, world, percept) -> list:
    """Ranked list (action, goal, utility) across all pairs — best goal per action."""
    goals = propose_goals(state, world, percept)
    out = []
    for a in enumerate_actions(state, world, percept):
        best_g, best_u = None, idle_floor(a)
        for g in goals:
            u = utility(a, g, state, world, percept)
            if u > best_u:
                best_u, best_g = u, g
        out.append((a, best_g, best_u))
    out.sort(key=lambda x: -x[2])
    return out


def decide(state, world, percept, temp: float = 0.0, rng=None):
    """Best action. temp=0 → argmax (determinism for tests); temp>0 → softmax-selection.
    The softmax pool contains only MEANINGFUL actions (backed by a goal) + harmless
    wait/move — so stochastics don't spawn causeless hits/steals (action without goal ≠ choice)."""
    ranked = score(state, world, percept)
    if temp <= 0 or rng is None:
        return ranked[0], ranked
    pool = [x for x in ranked if x[1] is not None or x[0].kind in ("wait", "move")]
    top = pool[:4] or ranked[:1]
    ws = [math.exp(u / temp) for _, _, u in top]
    s = sum(ws) or 1.0
    r, acc = rng.random() * s, 0.0
    for (item, w) in zip(top, ws):
        acc += w
        if r <= acc:
            return item, ranked
    return top[0], ranked
