"""Graph-brain MODULARBRAIN — traverse nodes in a single tick with PATH TRACING.

Currently phases 1-2 implemented + minimal cross-cutting modulation (Phase 4 "soft"):
existing reactive core (perceive→propose_goals→score→decide) wrapped as graph nodes;
urges vector and modulators bus computed and (when modulate=True) multiply utilities —
NEUTRAL normally, bites under pressure. Each node writes to trace {id,label,active,llm,content}
so debug highlights the PATH.

Common modulation (by ACTION/GOAL CLASS, not by situation): impatience (arousal) discounts
waiting/approach and pulls toward immediate (breaks "hold price" in negotiation → hungry agrees);
pessimism (valence↓) adds risk-aversion to attack. Argmax stays with core — only RANKING changes.

Key functions
--------------
think(state, world, percept=None, modulate=True) -> dict : Execute full decision cycle.
modulate_ranked(ranked, m) -> list : Weight actions by emotional modulators.
node(nid, label, active, content) -> dict : Build trace node for debugging.
"""

from __future__ import annotations

from .act import score
from .goals import propose_goals
from .modulators import modulators, urges
from .sim import perceive


def _mfactor(a, gkind, m) -> float:
    """Utility multiplier from modulators — by action class (general, no situation-specifics)."""
    da = m["arousal"] - 0.5
    dv = 0.5 - m["valence"]
    dd = m["dominance"] - 0.5
    say = getattr(a, "say", None)
    f = 1.0
    if a.kind == "wait" or (a.kind == "move" and gkind in ("acquire", "harm", "need", "affiliate", "inform")):
        f *= 1 - 0.55 * da                     # impatience discounts waiting/approach
    if a.kind in ("attack", "take", "use") or (a.kind == "say" and say == "accept"):
        f *= 1 + 0.35 * da                     # impatience pulls toward immediate
    if a.kind == "say" and say == "counter":
        f *= 1 - 0.7 * da                      # impulsive doesn't hold price (hungry gives in)
    if a.kind in ("attack", "take") or (a.kind == "say" and say == "threat"):
        f *= 1 - 0.6 * dv                      # pessimism → caution on ANY risky act
    if a.kind == "attack":
        f *= 1 + 0.4 * dd                      # power/courage → willingness to strike
    if a.kind == "move" and gkind == "safe":
        f *= 1 - 0.4 * dd                      # low power (fear) → flight more attractive
    return max(0.2, f)


def modulate_ranked(ranked, m):
    out = [(a, g, (u * _mfactor(a, (g.kind if g else "idle"), m) if u > 0 else u)) for a, g, u in ranked]
    out.sort(key=lambda x: -x[2])
    return out


def _r(x):
    return round(x, 2)


def think(state, world, percept=None, modulate: bool = True) -> dict:
    """Full graph traversal with tracing. Returns urges/modulators/goals/ranking/choice/trace."""
    p = percept or perceive(state, world)
    urg = urges(state)
    mods = modulators(state)
    goals = propose_goals(state, world, p)
    base = score(state, world, p)
    ranked = modulate_ranked(base, mods) if modulate else base
    top = ranked[0]
    gap = round(top[2] - (ranked[1][2] if len(ranked) > 1 else 0.0), 3)
    impasse = gap < 0.08 or (top[2] > 0 and gap / max(top[2], 1e-6) < 0.15)

    present = [b.id for b in p.present]
    lead = mods["_lead"]
    lead_need = max(urg, key=lambda n: urg[n]["priority"]) if urg else "—"
    hot = [f"{k} {_r(v['urge'])}" for k, v in urg.items() if v["urge"] >= .35]
    emo = [f"{k} {_r(v)}" for k, v in state.emotion.items() if v >= .15]
    gtxt = ", ".join(f"{g.kind}→{g.target}" for g in goals[:5]) or "нет"
    mtxt = " ".join(f"{k}={_r(mods[k])}" for k in ("arousal", "valence", "dominance", "resolution", "selection_threshold", "securing"))

    trace = [
        node("n0_serialize", "Сериализация", False, f"здесь: {', '.join(present) or 'никого'}; выходы: {', '.join(p.exits) or 'нет'}"),
        node("n3_decompose", "Разложение", True, f"раздражители из восприятия: {', '.join(present) or '—'}" + (f"; предметы: {', '.join(i.name for i in world.ground.get(p.here, []))}" if world.ground.get(p.here) else "")),
        node("n4_appraise", "Апрейзал", True, f"нужды: {', '.join(hot) or 'в норме'}; эмоции: {', '.join(emo) or 'спокоен'}"),
        node("n5_urges", "Урджи", False, f"ведущий: {lead_need} (приоритет {_r(lead['priority'])}, срочность {_r(mods['_max_urgency'])})"),
        node("n6_affect", "Аффект", False, ", ".join(emo) or "спокоен"),
        node("n7_modulators", "ШИНА МОДУЛЯТОРОВ", True, mtxt),
        node("n9_workspace", "Раб. простр-во (фокус)", False, f"режим/фокус: {state.mode}"),
        node("n10_motives", "Мотивы", True, gtxt),
        node("n11_options", "Опции", False, f"{len(ranked)} кандидатов над примитивами"),
        node("n14_score", "Скоринг ×модуляторы", True, f"топ: {top[0].label()} = {_r(top[2])}" + ("  (модуляция ON)" if modulate else "")),
        node("n16_arbiter", "Арбитр", False, f"выбор {top[0].label()}, разрыв top1−top2 = {gap}"),
        node("n17_impasse", "Импасс?", impasse, "ДА → нужен S2 (LLM lookahead)" if impasse else "нет → магистраль S1"),
        node("n21_execute", "Действие", True, f"{top[0].label()} ({top[1].kind if top[1] else '—'})"),
    ]
    return {
        "urges": {k: {"urge": _r(v["urge"]), "urgency": _r(v["urgency"])} for k, v in urg.items()},
        "modulators": {k: _r(mods[k]) for k in ("arousal", "valence", "dominance", "resolution", "selection_threshold", "securing")},
        "lead_need": lead_need,
        "goals": [{"kind": g.kind, "target": g.target, "value": _r(g.value), "agenda": g.meta.get("agenda")} for g in goals],
        "ranked": [{"action": a.label(), "kind": a.kind, "goal": (g.kind if g else "idle"), "u": _r(u)} for a, g, u in ranked[:16]],
        "chosen": {"action": top[0].label(), "goal": (top[1].kind if top[1] else "idle"), "u": _r(top[2])},
        "impasse": bool(impasse), "trace": trace, "modulate": modulate,
    }


def node(nid, label, active, content):
    llm = nid in ("n3_decompose", "n4_appraise", "n10_motives", "n21_execute")   # only semantic nodes
    return {"id": nid, "label": label, "active": bool(active), "llm": llm, "content": content}
