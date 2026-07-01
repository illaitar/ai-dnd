"""Граф-мозг MODULARBRAIN — проход по узлам за один тик с ТРАССИРОВКОЙ пути.

Сейчас реализованы фазы 1-2 + минимальная сквозная модуляция (Фаза 4 «мягко»): существующее
реактивное ядро (perceive→propose_goals→score→decide) обёрнуто как узлы графа; вектор урджей и шина
модуляторов вычисляются и (при modulate=True) домножают полезности — НЕЙТРАЛЬНО в норме, кусается под
давлением. Каждый узел пишет в trace {id,label,active,llm,content}, чтобы дебаг подсветил ПУТЬ.

Модуляция общая (по КЛАССУ действия/цели, не по ситуации): нетерпёж (arousal) дисконтирует
ожидание/подход и тянет к немедленному (и рушит «держать цену» в торге → голодный соглашается);
пессимизм (valence↓) добавляет риск-аверсию к атаке. Argmax остаётся у ядра — меняется РАНЖИРОВАНИЕ.
"""

from __future__ import annotations

from .act import score
from .goals import propose_goals
from .modulators import modulators, urges
from .sim import perceive


def _mfactor(a, gkind, m) -> float:
    """Множитель полезности от модуляторов — по классу действия (общо, без ситуаций)."""
    da = m["arousal"] - 0.5
    dv = 0.5 - m["valence"]
    dd = m["dominance"] - 0.5
    say = getattr(a, "say", None)
    f = 1.0
    if a.kind == "wait" or (a.kind == "move" and gkind in ("acquire", "harm", "need", "affiliate", "inform")):
        f *= 1 - 0.55 * da                     # нетерпёж дисконтирует ожидание/подход
    if a.kind in ("attack", "take", "use") or (a.kind == "say" and say == "accept"):
        f *= 1 + 0.35 * da                     # нетерпёж тянет к немедленному
    if a.kind == "say" and say == "counter":
        f *= 1 - 0.7 * da                      # импульсивный не держит цену (голодный уступает)
    if a.kind in ("attack", "take") or (a.kind == "say" and say == "threat"):
        f *= 1 - 0.6 * dv                      # пессимизм → осторожность на ЛЮБОМ рисковом акте
    if a.kind == "attack":
        f *= 1 + 0.4 * dd                      # власть/кураж → готовность бить
    if a.kind == "move" and gkind == "safe":
        f *= 1 - 0.4 * dd                      # низкая власть (страх) → бегство привлекательнее
    return max(0.2, f)


def modulate_ranked(ranked, m):
    out = [(a, g, (u * _mfactor(a, (g.kind if g else "idle"), m) if u > 0 else u)) for a, g, u in ranked]
    out.sort(key=lambda x: -x[2])
    return out


def _r(x):
    return round(x, 2)


def think(state, world, percept=None, modulate: bool = True) -> dict:
    """Полный проход графа с трассировкой. Возвращает урджи/модуляторы/цели/ранжирование/выбор/trace."""
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
    llm = nid in ("n3_decompose", "n4_appraise", "n10_motives", "n21_execute")   # только смысловые узлы
    return {"id": nid, "label": label, "active": bool(active), "llm": llm, "content": content}
