"""Граф состояний NPC: routine | leisure | converse | threat.

Переход — приоритетный, с ПРЕРЫВАНИЕМ: каждый тик считаем urgency каждого режима из стимулов+эмоций+нужд;
если лучший бид превышает hold(текущего)+гистерезис — переключаемся, иначе держим режим (в routine —
следующий шаг плана). hold(routine)=важность плана → важная рутина устойчива к мелочам, пустяковая рвётся.

Решения внутри режима (выбор инструмента) — отдельный слой; здесь только КАКОЙ режим.
"""

from __future__ import annotations

from .model import NEEDS, NpcState, Plan

HYST = 0.1                                  # гистерезис против дребезга
_NEED_WEIGHT = {"social": "sociability", "purpose": "ambition",
                "wealth": "greed", "novelty": "curiosity"}
# шаблоны планов по доминирующей нужде (LLM-построение рутины — позже)
_PLAN_BY_NEED = {
    "hunger":  ("утолить голод", ["идти к еде", "поесть"], 0.6),
    "fatigue": ("выспаться", ["идти домой", "спать"], 0.7),
    "purpose": ("отработать смену", ["идти на работу", "работать"], 0.55),
    "wealth":  ("заработать", ["идти на работу", "торговать"], 0.45),
    "comfort": ("укрыться", ["идти под кров", "переждать"], 0.5),
    "novelty": ("разузнать новости", ["идти в людное место", "слушать слухи"], 0.35),
}


def dominant_need(state: NpcState) -> tuple:
    """(нужда, значение, взвешенный_приоритет) — самая давящая с учётом черт."""
    best = ("", 0.0, 0.0)
    for nd in NEEDS:
        val = state.needs.get(nd, 0.0)
        w = state.config.traits.get(_NEED_WEIGHT[nd], 0.5) + 0.5 if nd in _NEED_WEIGHT else 1.0
        if val * w > best[2]:
            best = (nd, val, val * w)
    return best


def _build_plan(state: NpcState) -> Plan:
    nd = dominant_need(state)
    goal, steps, imp = _PLAN_BY_NEED.get(nd[0], ("обход", ["осмотреться", "пройтись"], 0.3))
    return Plan(goal=goal, steps=list(steps), importance=imp)


def urgency(state: NpcState, stim: dict | None = None) -> dict:
    """Бид каждого режима [0..1]."""
    stim = stim or {}
    e, n, t = state.emotion, state.needs, state.config.traits
    threat = max(e.get("fear", 0.0), 0.7 * e.get("anger", 0.0), float(stim.get("danger", 0.0)))
    if stim.get("addressed"):
        converse = 0.4 + 0.4 * float(stim.get("addresser_importance", 0.5)) + 0.3 * n.get("social", 0.0)
    else:
        converse = 0.25 * n.get("social", 0.0) * (0.5 + t.get("sociability", 0.5))
    if state.plan and not state.plan.done():
        routine = state.plan.importance
    else:
        nd = dominant_need(state)
        routine = nd[2] if nd[1] > 0.6 else 0.0          # рутину строит только давящая нужда
    routine = min(0.85, routine)                         # ниже угрозы (≤1.0) — threat надёжно прерывает
    leisure = 0.15 + 0.25 * max(n.values(), default=0.0)
    return {"threat": threat, "converse": converse, "routine": routine, "leisure": leisure}


def hold(state: NpcState) -> float:
    """Стойкость текущего режима к прерыванию. threat держится, ПОКА есть страх/гнев — иначе спадает."""
    threat_h = 0.2 + max(state.emotion.get("fear", 0.0), 0.7 * state.emotion.get("anger", 0.0))
    return {"threat": threat_h,
            "converse": max(0.4, state.engagement),
            "routine": state.plan.importance if state.plan else 0.2,
            "leisure": 0.15}.get(state.mode, 0.15)


def step(state: NpcState, scene, stim: dict | None = None) -> dict:
    """Один шаг графа: пересчёт режима. Возвращает трассу перехода (для маршрута на стенде)."""
    if stim and stim.get("danger"):                      # опасность оставляет след страха (угасает в тике)
        state.emotion["fear"] = max(state.emotion.get("fear", 0.0), float(stim["danger"]))
    bids = urgency(state, stim)
    best = max(bids, key=bids.get)
    cur = state.mode
    switched, reason = False, "держим режим"

    if best != cur and bids[best] > hold(state) + HYST:
        switched, reason = True, f"{cur}→{best} (бид {bids[best]:.2f} > hold {hold(state):.2f})"
        state.mode = best
        if best == "routine" and (not state.plan or state.plan.done()):
            state.plan = _build_plan(state)
        if best == "converse":
            state.engagement = 0.4
        if best != "converse":
            state.engagement = 0.0
    else:
        if cur == "routine" and state.plan and not state.plan.done():
            state.plan.cursor += 1                       # выполнили шаг рутины
            if state.plan.done():
                reason = f"план «{state.plan.goal}» выполнен"
        elif cur == "routine":
            state.plan = None
            reason = "рутины нет — к решению"
        elif cur == "converse":
            state.engagement = min(0.8, state.engagement + 0.1)   # глубже в разговоре
        elif cur == "threat" and bids["threat"] < 0.3:
            reason = "угроза спала"

    trace = {"tick": scene.clock, "mode": state.mode, "prev": cur, "switched": switched,
             "reason": reason, "bids": {k: round(v, 2) for k, v in bids.items()},
             "hold": round(hold(state), 2)}
    state.mode_history.append([scene.clock, state.mode, switched, reason])
    return trace
