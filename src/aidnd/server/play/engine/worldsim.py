"""АДАПТЕР мира ↔ общества: строит из реальных зданий/графа доступные каждому NPC места и гоняет
их рутину (aidnd.society). Тут — только «перевод» мира в кандидатов; логика выбора живёт в society.

routine_step() — дешёвый пересчёт спотов ВСЕХ жителей по нуждам (замена хардкода _routine_spot).
Вызывается на смене фазы суток из тика мира (см. engine.world._world_tick).
"""

from __future__ import annotations

import random

from aidnd import society
from aidnd.server.play.engine.core import _S, _gt, _phase, _store, _wid


def _place_index(people, keynode: dict) -> dict:
    """Узлы города по типам мест (из фактшитов зданий): {kind: [node,...]}. Считается раз за шаг."""
    idx: dict = {}
    for bid, node in keynode.items():
        data = (_store().get_building(_wid(), bid) or {}).get("data") or {}
        for kind in society.kinds_of(data):
            idx.setdefault(kind, []).append(node)
    return idx


def _gate_ok(kind: str, p) -> bool:
    """Кого место вообще касается: work — при наличии работы; patrol — стража; prowl — лихой люд."""
    pk = society.PLACE[kind]
    if pk.gate == "job":
        return bool(p.work)
    if pk.gate == "guard":
        return p.role == "стражник"
    if pk.gate == "rogue":
        return (
            p.role in ("головорез", "бродяга", "наёмник")
            or p.state.config.traits.get("malice", 0.5) > 0.6
        )
    return True


_BCAP: dict = {}
_NOT_SOCIAL = {"private", "storage", "cell", "beds"}   # не «общий зал» — не считаем в толпу


def _building_cap(bid) -> int:
    """Ёмкость здания = Σ cap социальных зон (мест «где можно быть на людях»); кэш по bid."""
    if bid not in _BCAP:
        from aidnd.server.play.engine.zones import building_zones
        _zd, zs = building_zones(bid)
        cap = sum(int(z.get("cap", 0)) for z in zs if z.get("kind") not in _NOT_SOCIAL)
        _BCAP[bid] = max(6, cap) if zs else 14        # разумный дефолт без зон
    return _BCAP[bid]


def _candidates(p, place_idx: dict, keynode: dict, kps: list, rng,
                work_kinds: dict | None = None, load: dict | None = None,
                n2b: dict | None = None) -> list:
    """Доступные этому NPC места как список society.Candidate. Дом/работа персональны;
    трактир/храм/рынок — «свой» из города (сидированный выбор); улица/дозор/промысел — точка графа."""
    out = []
    home = p.home if p.home is not None else (rng.choice(kps) if kps else None)
    if home is not None:
        out.append(society.Candidate("home", home))
    if p.work:
        wk = (work_kinds or {}).get(p.work)          # окно ЗАВЕДЕНИЯ: таверна зовёт вечером
        out.append(society.Candidate("work", keynode.get(p.work, home), window_kind=wk))
    elif home is not None and p.role != "горожанин":  # ремесленник трудится ДОМА (ист. норма)
        out.append(society.Candidate("work", home))
    for kind in ("tavern", "temple", "market"):  # привязанные к зданиям места
        nodes = place_idx.get(kind)
        if nodes and _gate_ok(kind, p):
            node = nodes[hash((p.state.config.id, kind)) % len(nodes)]
            if load is not None and n2b is not None:  # ёмкость: полное здание не зовёт
                bid = n2b.get(node)
                if bid and load.get(node, 0) >= _building_cap(bid):
                    continue
            out.append(society.Candidate(kind, node))
    for kind in ("street", "patrol", "prowl"):  # мобильные места — точка на графе
        if kps and _gate_ok(kind, p):
            out.append(
                society.Candidate(
                    kind, kps[hash((p.state.config.id, kind, _gt() // 1440)) % len(kps)]
                )
            )
    return out


def routine_step(people: dict, crof: dict) -> None:
    """Пересчитать, где каждый житель, по его нуждам/характеру/времени. Дёшево (без LLM/БД в цикле):
    один индекс зданий + O(люди×места) утилити. Мутирует crof (спот) и нужды в people[*].state."""
    keynode, kps = _S.get("keynode") or {}, _S.get("kps") or []
    phase = _phase()
    place_idx = _place_index(people, keynode)
    work_kinds = {}                                  # bid → тип заведения (окно работы)
    for bid in keynode:
        data = (_store().get_building(_wid(), bid) or {}).get("data") or {}
        ks = society.kinds_of(data)
        if ks:
            work_kinds[bid] = ks[0]
    day, gt = _gt() // 1440, _gt()
    node2kind = {}  # где сейчас стоит NPC → тип места (гасит нужды)
    for kind, nodes in place_idx.items():
        for n in nodes:
            node2kind.setdefault(n, kind)
    from aidnd.server.play.engine import deeds as _deeds

    # обязательства: в СРОК рутина тянет обе стороны на место встречи; просрочка = слово нарушено
    appts: dict = {}
    for d in _deeds.promises_active():
        node = d["data"].get("node")
        due = d["data"].get("due")
        if node is None:
            continue
        if due == phase:
            appts.setdefault(d["actor"], node)
            appts.setdefault(d["obj"], node)
        elif gt > d["data"].get("made_gt", gt) + 300 and due != phase:
            both = crof.get(d["actor"]) == node and crof.get(d["obj"]) == node
            _deeds.promise_resolve(d, both)
            actor_p, obj_p = people.get(d["actor"]), people.get(d["obj"])
            if actor_p and obj_p:
                if both:
                    actor_p.state.memory.add(f"я сдержал(а) слово ({obj_p.name})", gt // 10, 0.55,
                                             about=[d["obj"]])
                    obj_p.state.memory.add(f"{actor_p.name} сдержал(а) слово", gt // 10, 0.55,
                                           about=[d["actor"]])
                    obj_p.state.rel(d["actor"])["trust"] = min(
                        1.0, obj_p.state.rel(d["actor"]).get("trust", 0) + 0.15)
                else:
                    obj_p.state.memory.add(f"{actor_p.name} НЕ сдержал(а) слово", gt // 10, 0.6,
                                           about=[d["actor"]])
                    obj_p.state.rel(d["actor"])["trust"] = max(
                        -1.0, obj_p.state.rel(d["actor"]).get("trust", 0) - 0.25)
    n2b = _S.get("cr2b") or {}
    kind_of: dict = _S.setdefault("crof_kind", {})    # pid → вид занятия (для GIF/наблюдаемости)
    load: dict = {}                                   # узел → сколько уже там (для ёмкости)
    last = _S.setdefault("needs_gt", {})
    order = sorted(people.items(), key=lambda kv: (kv[1].work is None, kv[0]))  # работники — первыми
    for pid, p in order:
        st = p.state
        mins = max(0, gt - last.get(pid, gt - 360))  # прошло с прошлого шага (старт: ~фаза)
        here = node2kind.get(crof.get(pid))  # где стоял → что гасил
        if here is None and crof.get(pid) == p.home:
            here = "home"
        rng = random.Random(f"rout|{pid}|{phase}|{gt // 30}")
        cands = _candidates(p, place_idx, keynode, kps, rng, work_kinds=work_kinds,
                            load=load, n2b=n2b)
        if pid in appts:                              # уговор в силе: место встречи зовёт
            cands.append(society.Candidate("appointment", appts[pid]))
        node, akind = society.step(st, cands, phase, mins, here, rng, stay=crof.get(pid))
        if node is not None:
            crof[pid] = node
            kind_of[pid] = akind
        if node is not None and n2b.get(node):        # встал в здание — занял место
            load[node] = load.get(node, 0) + 1
        last[pid] = gt
