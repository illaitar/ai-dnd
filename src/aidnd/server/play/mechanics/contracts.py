"""Игровой контур — КОНТРАКТЫ: квесты из агенд (шаги-предикаты) + доска объявлений.

Слой mechanics/ (см. docs/loop.md).
"""

from __future__ import annotations

import json
import random
import re

from aidnd.mind import World as MWorld
from aidnd.mind.llm_agent import plan_agenda
from aidnd.server.play.engine.core import (
    _S,
    PB,
    PLAYER,
    _binfo,
    _gt,
    _model,
    _mt,
    _npc_save,
    _pc_remember,
    _store,
    _tokens_ru,
    _wid,
)
from aidnd.server.play.mechanics.items import _cont_holder, _materialize_npc

# ------------------------------------------- КОНТРАКТЫ (квесты из агенд) --- #
# Квест = делегированная нужда NPC: want-ПРЕДИКАТ над миром (всё равно КАК добудешь) + реальная
# награда. Цель выбирается из НАСТОЯЩИХ вещей мира (ёмкости зданий, ценное других людей).

_CONTRACT_SYS = (
    "Ты — житель фронтирного городка, которому нужна помощь чужака. По твоей натуре и долгой цели выбери "
    "ОДНО поручение из доступных ВИДОВ (используй только перечисленные кандидаты, дословно):\n"
    "bring — добыть тебе вещь из мира; deliver — отнести ТВОЮ вещь названному человеку; "
    "visit — сходить в место и глянуть, что там; befriend — расположить к себе названного человека; "
    "dead — покончить с твоим ВРАГОМ (только из списка врагов; тёмное дело — лишь если твоя натура "
    "такое стерпит).\n"
    "Можно ОДНО поручение или ЦЕПОЧКУ из 2-3 связанных шагов (steps), если так честнее "
    "(например: bring траву → deliver зелье жене мельника).\n"
    'Верни СТРОГО JSON: {"steps": [{"kind": "bring|deliver|visit|befriend|dead", '
    '"want": "<вещь дословно или null>", "target": "<имя человека/место дословно или null>"}, ...], '
    '"reward": <целое, не больше наличности>, "pitch": "<просьба В ХАРАКТЕРЕ, 1-2 фразы, с сутью и наградой>"}. '
    "Для простого поручения — steps из одного элемента."
)


def _build_step(spec, npc, p, cands, own, others) -> dict | None:
    """Проверить и собрать ОДИН шаг уговора из спеки LLM (цель — из реального мира). None — невалиден."""
    kind = (
        spec.get("kind")
        if spec.get("kind") in ("bring", "deliver", "visit", "befriend", "dead")
        else "bring"
    )
    want, tgt = str(spec.get("want") or "").strip(), str(spec.get("target") or "").strip()
    step = {
        "kind": kind,
        "want": None,
        "target": None,
        "target_name": None,
        "where": "",
        "deliver_item": None,
    }
    if kind == "bring":
        cand = next((c for c in cands if c["name"] == want), None)
        if not cand:
            return None
        step.update(want=want, where=cand["where"])
    elif kind == "deliver":
        oit = next(((i, it) for i, it in own if it["name"] == want), None)
        who = next(((pid, o) for pid, o in others if o.name == tgt), None)
        if not oit or not who:
            return None
        step.update(
            want=want,
            deliver_item=oit[0],
            target=who[0],
            target_name=who[1].name,
            where=f"вручить: {who[1].name}",
        )
    elif kind == "visit":
        pl = next((k for k in _S["geom"]["keys"] if k["label"] == tgt), None)
        if not pl:
            return None
        step.update(target=pl["node"], target_name=pl["label"], where=f"место: {pl['label']}")
    elif kind == "befriend":
        who = next(((pid, o) for pid, o in others if o.name == tgt), None)
        if not who:
            return None
        step.update(target=who[0], target_name=who[1].name, where=f"человек: {who[1].name}")
    else:  # dead — только настоящий враг гивера
        who = next(
            (
                (oid, o)
                for oid, o in others
                if o.name == tgt
                and (p.state.relationships.get(oid) or {}).get("affinity", 0) < -0.15
            ),
            None,
        )
        if not who:
            return None
        step.update(
            target=who[0],
            target_name=who[1].name,
            where=f"человек: {who[1].name} — найти и покончить",
        )
    return step


def _contract_candidates(giver: str) -> list:
    """Реальные цели для контракта: содержимое ёмкостей зданий + ценное ДРУГИХ людей."""
    out = []
    giver_work = (_S.get("people") or {}).get(giver)
    giver_work = giver_work.work if giver_work else None
    for bid in list(_S.get("cr2b", {}).values()):
        if bid == giver_work:
            continue  # из СВОЕГО здания не просят — абсурд
        bd = _store().get_building(_wid(), bid)
        if not bd:
            continue
        nm_b = _binfo(bid)["name"]
        for cnt in bd["data"].get("containers") or []:
            for it_s in (cnt.get("contents") or [])[:2]:
                out.append({"name": it_s, "where": f"{cnt['name']} ({nm_b})"})
    for pid, p in sorted((_S.get("people") or {}).items()):
        if pid == giver:
            continue
        for v in ((p.persona or {}).get("valuables") or [])[:1]:
            out.append({"name": v, "where": f"при {p.name} ({p.role})"})
    return out[:24]


def _contract_offer(npc: str) -> dict | None:
    """Личная просьба в разговоре: раз на человека (флаг coffer). Механика решает ЧТО можно,
    LLM просит В ХАРАКТЕРЕ."""
    p = _S["people"][npc]
    last = _store().flag_get(_wid(), f"coffer|{npc}")
    if last:
        try:
            if _gt() - int(last) < 2880:             # просил недавно — не канючит; 2 суток и можно снова
                return None
        except ValueError:                           # старый формат флага (без gt) — протух
            pass
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    if rel.get("affinity", 0) < PB["contract_enemy_aff"]:  # с явным недругом дел не ведут
        return None
    r = _make_contract(npc, "offered")
    if r:
        _store().flag_set(_wid(), f"coffer|{npc}", str(_gt()))
    return r


def _make_contract(npc: str, status: str) -> dict | None:
    """Ядро генерации уговора для NPC (просьба/объявление): агенда → кандидаты → LLM → шаги.
    Сохраняет контракт с заданным статусом. None — только «нечего предложить/невалидно»;
    недоступность LLM летит исключением."""
    p = _S["people"][npc]
    mgr = _model()
    if not (p.state.agendas or []):  # долгая цель — лениво, при первой нужде
        ag0 = plan_agenda(p.state, MWorld(), {"roles": {npc: p.role}}, mgr)
        if ag0:
            p.state.agendas.append(ag0)
    if not (p.state.agendas or []):
        return None
    _materialize_npc(npc, "pockets")
    purse = _store().purse_get(_wid(), npc)
    reward_item = None
    if purse < PB["contract_poor_purse"]:  # бедняк платит вещью, не монетой
        rows = [
            (r["item_id"], _store().get_item(r["item_id"])) for r in _store().inventory(_wid(), npc)
        ]
        rows = [(i, it) for i, it in rows if it and it["kind"] != "key"]
        if not rows:
            return None
        reward_item = max(rows, key=lambda x: x[1]["worth"])
    cands = _contract_candidates(npc)
    random.Random(f"cands|{npc}").shuffle(cands)  # разный порядок разным гиверам — против эха
    others = [(pid, o) for pid, o in sorted((_S.get("people") or {}).items()) if pid != npc]
    own = [(r["item_id"], _store().get_item(r["item_id"])) for r in _store().inventory(_wid(), npc)]
    own = [(i, it) for i, it in own if it and it["kind"] != "key"]
    places = [k["label"] for k in _S["geom"]["keys"]]
    ag = p.state.agendas[0]
    pay_line = (
        f"Наличность: {purse} зм."
        if not reward_item
        else f"Монет у тебя нет — в награду отдашь свою вещь «{reward_item[1]['name']}» (reward=0)."
    )
    user = (
        f"ТЫ: {p.name}, {p.role}. Натура: {trait_hints_str(p)}. "
        f"ТВОЯ ДОЛГАЯ ЦЕЛЬ: {getattr(ag, 'summary', '')}. {pay_line}\n"
        f"bring-КАНДИДАТЫ (вещь → где): "
        + ("; ".join(f"«{c['name']}» → {c['where']}" for c in cands) or "нет")
        + "\n"
        "deliver-ТВОИ ВЕЩИ: " + ("; ".join(f"«{it['name']}»" for _i, it in own[:4]) or "нет") + "\n"
        "ЛЮДИ (для deliver/befriend): "
        + ("; ".join(o.name for _pid, o in others[:10]) or "нет")
        + "\n"
        "МЕСТА (для visit): " + ", ".join(places) + "\n"
        "ВРАГИ (для dead): "
        + (
            "; ".join(
                o.name
                for oid, o in others
                if (p.state.relationships.get(oid) or {}).get("affinity", 0) < -0.15
            )
            or "нет"
        )
    )
    resp = mgr.call(
        "narrator",
        [{"role": "system", "content": _CONTRACT_SYS}, {"role": "user", "content": user}],
        options={"temperature": 0.7},
    )
    t = (resp.get("content") if resp else "").strip()
    try:
        d = json.loads(t[t.find("{") : t.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    specs = d.get("steps") if isinstance(d.get("steps"), list) and d["steps"] else [d]
    steps = []
    for spec in specs[:3]:  # цепочка до 3 шагов; любой невалидный → отказ
        st = _build_step(spec if isinstance(spec, dict) else {}, npc, p, cands, own, others)
        if not st:
            return None
        steps.append(st)
    if not steps:
        return None
    first = steps[0]  # top-level = ПЕРВЫЙ шаг (совместимость)
    data = {
        "giver": npc,
        "giver_name": p.name,
        "step": 0,
        "steps": steps,
        **first,
        "reward": (
            0
            if reward_item
            else max(PB["contract_reward_min"], min(int(d.get("reward") or 5), purse))
        ),
        "reward_item": (reward_item[0] if reward_item else None),
        "reward_name": (reward_item[1]["name"] if reward_item else None),
        "pitch": str(d.get("pitch") or "")[:220],
        "why": getattr(ag, "summary", ""),
    }
    cid = f"ct:{npc}:{_mt()}"
    _store().save_contract(_wid(), cid, status, data)
    return {"id": cid, **data}


_KIND_VERB = {
    "bring": "добыть",
    "deliver": "отнести",
    "visit": "наведаться",
    "befriend": "расположить к себе",
    "dead": "покончить с",
}


def _ct_steps(ct: dict) -> list:
    """Шаги уговора. Старый одношаговый контракт (без steps) — оборачиваем в один шаг."""
    if ct.get("steps"):
        return ct["steps"]
    return [
        {
            "kind": ct.get("kind", "bring"),
            "want": ct.get("want"),
            "target": ct.get("target"),
            "target_name": ct.get("target_name"),
            "where": ct.get("where", ""),
            "deliver_item": ct.get("deliver_item"),
        }
    ]


def _ct_cur(ct: dict) -> dict:
    steps = _ct_steps(ct)
    return steps[min(ct.get("step", 0), len(steps) - 1)]


def _step_desc(step: dict) -> str:
    v = _KIND_VERB.get(step.get("kind"), "сделать")
    tgt = step.get("want") or step.get("target_name") or ""
    return f"{v} «{tgt}»" + (f" ({step['where']})" if step.get("where") else "")


def _ct_advance(ct: dict, step_narr: str) -> str:
    """Текущий шаг закрыт: если он последний — выплата; иначе шаг++ и подсказка следующего."""
    steps = _ct_steps(ct)
    nstep = ct.get("step", 0) + 1
    if nstep >= len(steps):
        return _contract_complete(ct)
    data = {k: v for k, v in ct.items() if k not in ("id", "status")}
    data["step"] = nstep
    _store().save_contract(_wid(), ct["id"], "active", data)
    return f"{step_narr} Шаг {nstep} из {len(steps)}. Дальше: {_step_desc(steps[nstep])}."


def _contract_complete(ct: dict) -> str:
    """Общая выплата ЛЮБОГО исполненного уговора: награда, доверие, память, журнал."""
    giver = ct["giver"]
    p = _S["people"][giver]
    _materialize_npc(giver, "pockets")  # чтоб было чем платить
    if ct.get("reward_item"):  # награда вещью (бедняк)
        _store().inv_move(_wid(), ct["reward_item"], "pc")
        paid = f"{p.name} отдаёт обещанное — «{ct.get('reward_name')}»"
    else:
        reward = min(ct["reward"], _store().purse_get(_wid(), giver))
        _store().purse_add(_wid(), giver, -reward)
        coins = _store().purse_add(_wid(), "pc", reward)
        paid = f"{p.name} отсыпает тебе {reward} зм (кошель: {coins})"
    _store().save_contract(
        _wid(), ct["id"], "done", {k: v for k, v in ct.items() if k not in ("id", "status")}
    )
    p.state.rel(PLAYER)["trust"] = min(1.0, p.state.rel(PLAYER)["trust"] + PB["complete_trust"])
    p.state.rel(PLAYER)["affinity"] = min(1.0, p.state.rel(PLAYER)["affinity"] + PB["complete_aff"])
    p.state.memory.add("чужак исполнил мою просьбу. Надёжный человек", _mt(), 0.85, about=[PLAYER])
    from aidnd.server.play.engine import deeds as _deeds

    _deeds.record(PLAYER, "favor", obj=giver, place=ct.get("where") or "",
                  data={"kind": ct.get("kind"), "what": ct.get("want") or ct.get("target_name")})
    _pc_remember(
        f"исполнил просьбу {p.name} ({ct['kind']}: {ct.get('want') or ct.get('target_name')})",
        0.6,
        about=[giver],
    )
    _npc_save(giver)
    return f"Уговор исполнен! {paid}."


def _contract_on_give(npc: str, it: dict) -> str | None:
    """give закрывает ТЕКУЩИЙ шаг: bring (принёс гиверу) и deliver (вручил адресату)."""
    for ct in _store().contracts(_wid(), "active"):
        cur = _ct_cur(ct)
        kind = cur.get("kind", "bring")
        if (
            kind == "bring"
            and ct["giver"] == npc
            and (_tokens_ru(cur["want"]) & _tokens_ru(it["name"]))
        ):
            return _ct_advance(ct, "Есть, добыто.")
        if (
            kind == "deliver"
            and cur.get("target") == npc
            and (_tokens_ru(cur["want"]) & _tokens_ru(it["name"]))
        ):
            tgt = _S["people"][npc]
            tgt.state.memory.add(
                f"чужак передал мне «{it['name']}» от {ct['giver_name']}",
                _mt(),
                0.5,
                about=[PLAYER, ct["giver"]],
            )
            _npc_save(npc)
            return _ct_advance(ct, "Передал из рук в руки.")
    return None


def _contract_on_move(loc: int) -> str | None:
    """visit: дошёл до места — текущий шаг закрыт."""
    for ct in _store().contracts(_wid(), "active"):
        cur = _ct_cur(ct)
        if cur.get("kind") == "visit" and cur.get("target") == loc:
            return _ct_advance(ct, "Место осмотрено.")
    return None


def _contract_on_talk(npc: str) -> str | None:
    """befriend: цель прониклась к тебе — текущий шаг закрыт."""
    for ct in _store().contracts(_wid(), "active"):
        cur = _ct_cur(ct)
        if cur.get("kind") == "befriend" and cur.get("target") == npc:
            rel = _S["people"][npc].state.relationships.get(PLAYER, {})
            if rel.get("affinity", 0) >= PB["befriend_aff"]:
                return _ct_advance(ct, "Он проникся к тебе.")
    return None


def _board_ads() -> list:
    """Объявления на столбе — контракты со статусом board (повесили NPC по своим агендам)."""
    out = []
    for ct in _store().contracts(_wid(), "board"):
        cur = _ct_cur(ct)
        out.append(
            {
                "id": ct["id"],
                "giver_name": ct["giver_name"],
                "kind": cur.get("kind"),
                "want": cur.get("want"),
                "target_name": cur.get("target_name"),
                "where": cur.get("where", ""),
                "reward": ct.get("reward", 0),
                "reward_name": ct.get("reward_name"),
                "steps": len(_ct_steps(ct)),
            }
        )
    return out


def _board_publish() -> list:
    """Утро: занятый горожанин вешает объявление на столб (тот же генератор уговоров)."""
    people = _S.get("people") or {}
    ads = _store().contracts(_wid(), "board")
    if len(ads) >= PB["board_max_ads"]:
        return []
    taken = {a["giver"] for a in ads}
    cands = [pid for pid, p in sorted(people.items()) if p.work and pid not in taken]
    if not cands:
        return []
    npc = random.Random(f"boardpub|{_gt() // 1440}").choice(cands)
    try:
        r = _make_contract(npc, "board")
    except Exception:  # noqa: BLE001 — публикация не роняет утро
        return []
    return [f"{people[npc].name} повесил объявление на городскую доску"] if r else []


def _consume_world_item(want: str, where: str) -> None:
    """Вещь по объявлению закрыл NPC → она РЕАЛЬНО уходит из мира: из строк ёмкости здания
    (не материализована) или из cont-держателя (материализована). «при человеке» не трогаем."""
    m = re.search(r"\(([^)]+)\)\s*$", where or "")
    if not m:
        return
    bname = m.group(1)
    for bid in set((_S.get("cr2b") or {}).values()):
        bd = _store().get_building(_wid(), bid)
        if not bd or _binfo(bid)["name"] != bname:
            continue
        data = bd["data"]
        for cnt in data.get("containers") or []:
            holder = _cont_holder(bid, cnt["name"])
            if _store().flag_get(_wid(), f"seeded|{holder}"):
                for r in _store().inventory(_wid(), holder):  # ёмкость уже живая
                    it = _store().get_item(r["item_id"])
                    if it and (_tokens_ru(it["name"]) & _tokens_ru(want)):
                        _store().inv_drop(_wid(), r["item_id"])
                        return
            else:
                cts = cnt.get("contents") or []
                hit = next((x for x in cts if _tokens_ru(x) & _tokens_ru(want)), None)
                if hit:
                    cnt["contents"] = [x for x in cts if x != hit]
                    node = bd.get("node") or 0
                    _store().save_building(
                        _wid(), bid, bool(bd.get("is_key")), node, bd.get("sign"), data
                    )
                    return
        return


def _board_npc_fulfill() -> list:
    """Утро: кто-то из горожан снимает объявление и выполняет его (мир живёт без игрока).
    bring-вещь при этом РЕАЛЬНО исчезает из ёмкости — мир не врёт."""
    rng = random.Random(f"boardful|{_gt() // 1440}")
    news = []
    for ct in _store().contracts(_wid(), "board"):
        if rng.random() > PB["board_npc_fulfill"]:
            continue
        cur = _ct_cur(ct)
        if cur.get("kind") == "bring" and cur.get("want"):
            try:
                _consume_world_item(cur["want"], cur.get("where", ""))
            except Exception:  # noqa: BLE001 — уборка не роняет утро
                pass
        _store().save_contract(
            _wid(), ct["id"], "done", {k: v for k, v in ct.items() if k not in ("id", "status")}
        )
        news.append(f"с доски сняли: «{_step_desc(_ct_cur(ct))}» — выполнено горожанином")
    return news


def trait_hints_str(p) -> str:
    from aidnd.worldgen.persona_llm import trait_hints

    return trait_hints(p.state.config.traits, p.charisma, p.appearance)
