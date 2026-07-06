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


def _candidates(p, place_idx: dict, keynode: dict, kps: list, rng,
                work_kinds: dict | None = None) -> list:
    """Доступные этому NPC места как список society.Candidate. Дом/работа персональны;
    трактир/храм/рынок — «свой» из города (сидированный выбор); улица/дозор/промысел — точка графа."""
    out = []
    home = p.home if p.home is not None else (rng.choice(kps) if kps else None)
    if home is not None:
        out.append(society.Candidate("home", home))
    if p.work:
        wk = (work_kinds or {}).get(p.work)          # окно ЗАВЕДЕНИЯ: таверна зовёт вечером
        out.append(society.Candidate("work", keynode.get(p.work, home), window_kind=wk))
    for kind in ("tavern", "temple", "market"):  # привязанные к зданиям места
        nodes = place_idx.get(kind)
        if nodes and _gate_ok(kind, p):
            out.append(society.Candidate(kind, nodes[hash((p.state.config.id, kind)) % len(nodes)]))
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
    last = _S.setdefault("needs_gt", {})
    for pid, p in people.items():
        st = p.state
        mins = max(0, gt - last.get(pid, gt - 360))  # прошло с прошлого шага (старт: ~фаза)
        here = node2kind.get(crof.get(pid))  # где стоял → что гасил
        if here is None and crof.get(pid) == p.home:
            here = "home"
        rng = random.Random(f"rout|{pid}|{phase}|{gt // 30}")
        cands = _candidates(p, place_idx, keynode, kps, rng, work_kinds=work_kinds)
        node = society.step(st, cands, phase, mins, here, rng)
        if node is not None:
            crof[pid] = node
        last[pid] = gt
