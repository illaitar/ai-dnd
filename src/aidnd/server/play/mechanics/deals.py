"""СДЕЛКА игрока — deal-гейт цепочки: want × ставка × DC-из-разума × бросок → ОБЯЗАТЕЛЬСТВО.

Речь со ставкой = состояние мира: успех создаёт контракт giver=pc + эскроу золота + цель в
агенду исполнителя + слово-deed со сроком; грязное предложение честному — розыск, память и
deed «предлагал кровь» (пища дознавателям). DC собирается из mind-черт (honesty/malice),
отношений и АДЕКВАТНОСТИ ставки против цены дела; формулы в PB (принцип 4).
Исполнение заказов крови — утренний шаг _deal_jobs: авторезолв ТЕМ ЖЕ движком, что
NPC-зачистки; исход настоящий (flag dead, deed murder, выплата эскроу / возврат задатка).
"""

from __future__ import annotations

import random

from aidnd.mind.agenda import Agenda
from aidnd.server.play.engine.core import (
    _PC_CAP,
    _S,
    PB,
    PLAYER,
    _gt,
    _gt_add,
    _mt,
    _npc_save,
    _pc_remember,
    _store,
    _wid,
    _witness_crime,
)

DEAL_KINDS = ("dead", "bring", "visit", "befriend")


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("id", "status")}


def _scene_witnesses(npc: str, manner: str) -> list:
    """Кто слышал уговор: люди ТВОЕЙ зоны (слышимость сцены); шёпот — никто, кроме двоих."""
    if manner == "stealthily":
        return []
    lv = _S.get("live") or {}
    zmap = lv.get("zonemap") or {}
    mine = zmap.get(PLAYER)
    return [pid for pid, z in zmap.items()
            if pid not in (PLAYER, npc) and z is not None and z == mine]


def deal_attempt(npc: str, deal: dict, manner: str, out: dict,
                 people, crof, loc) -> dict | None:
    """Гейт сделки. None — «это не сделка» (пустая ставка/вид): пусть фраза идёт диалогом."""
    from aidnd.server.play.engine import deeds as _deeds

    p = people[npc]
    kind = str(deal.get("kind") or "").strip()
    try:
        stake = max(0, int(deal.get("stake_gold") or 0))
    except (TypeError, ValueError):
        stake = 0
    if kind not in DEAL_KINDS or stake <= 0:
        return None                                   # без ставки — обычные уговоры (диалог)
    raw_t = str(deal.get("target") or "").strip()
    target = raw_t if raw_t in people else None
    want_txt = str(deal.get("want") or "")[:60]
    if kind == "dead" and (not target or target == npc):
        out["narr"].append(f"{p.name} щурится: «Кого? Говори прямо — или не говори вовсе».")
        out["fail"] = True
        return out
    coins = _store().purse_get(_wid(), "pc")
    if coins < stake:
        out["narr"].append(f"Сулишь {stake} зм, а в кошеле {coins}. {p.name} не дурак.")
        out["fail"] = True
        return out

    tr = p.state.config.traits
    rel = p.state.rel(PLAYER)
    wit = _scene_witnesses(npc, manner)
    tname = people[target].name if target else want_txt
    if kind == "dead":
        # свой человек — отказ без броска: родня по фамилии или тёплые отношения с целью
        t_aff = p.state.relationships.get(target, {}).get("affinity", 0)
        kin = p.name.split()[-1] == people[target].name.split()[-1]
        if kin or t_aff > PB["deal_kin_aff"]:
            p.state.memory.add(f"чужак предлагал мне убить {tname} — СВОЕГО", _mt(), 0.9,
                               about=[PLAYER, target])
            rel["affinity"] = min(rel["affinity"], -0.4)
            _deeds.record(PLAYER, "solicit", obj=npc, place=str(loc), witnesses=wit,
                          data={"kind": kind, "target": target, "stake": stake})
            _npc_save(npc)
            out["narr"].append(f"{p.name} каменеет: «{tname} мне не чужой. Уйди с глаз».")
            out["fail"] = True
            return out
        if tr.get("honesty", 0.5) >= PB["deal_flat_honesty"] and \
                tr.get("malice", 0.5) <= PB["deal_flat_malice"]:
            wn = _witness_crime(people, crof, loc, npc,
                                f"предлагал мне золото за убийство ({tname}!)",
                                weight=PB["crime_solicit"])
            _deeds.record(PLAYER, "solicit", obj=npc, place=str(loc), witnesses=wit,
                          data={"kind": kind, "target": target, "stake": stake})
            _npc_save(npc)
            out["narr"].append(f"{p.name} отшатывается: «Да ты душегуб!» — и не понижает "
                               f"голоса. Свидетелей: {wn}. Город такое помнит.")
            out["fail"] = True
            return out

    # DC: цена дела против ставки, нрав, отношения — всё из PB и mind-состояния
    price = PB[f"deal_price_{kind}"]
    dc = PB[f"deal_dc_{kind}"]
    dc += tr.get("honesty", 0.5) * (PB["deal_honesty_dead_k"] if kind == "dead"
                                    else PB["deal_honesty_k"])
    if kind == "dead":
        dc -= tr.get("malice", 0.5) * PB["deal_malice_dead_k"]
    adq = (stake / price - 1.0) * PB["deal_adq_k"]
    dc -= max(-PB["deal_adq_clamp"], min(PB["deal_adq_clamp"], adq))
    dc -= rel["affinity"] * PB["deal_aff_k"] + rel.get("fear", 0) * PB["deal_fear_k"]
    dc = round(dc)
    n = int(_store().flag_get(_wid(), f"deal|{npc}") or 0) + 1
    _store().flag_set(_wid(), f"deal|{npc}", str(n))
    roll = random.Random(f"deal|{npc}|{n}").randint(1, 20)
    mod = _PC_CAP.mod("cha")
    _gt_add(PB["talk_min"])
    verdict = f"Убеждение: {roll}+{mod} против {dc}"
    if roll + mod < dc:
        p.state.memory.add(
            (f"чужак сговаривался со мной о тёмном деле ({tname}) — не сошлись в цене"
             if kind == "dead" else f"чужак предлагал уговор ({stake} зм) — я отказался"),
            _mt(), 0.7, about=[PLAYER])
        if kind == "dead":
            _deeds.record(PLAYER, "solicit", obj=npc, place=str(loc), witnesses=wit,
                          data={"kind": kind, "target": target, "stake": stake})
        _npc_save(npc)
        out["narr"].append(f"{verdict} — {p.name} долго смотрит и качает головой: «Не пойдёт».")
        out["fail"] = True
        return out

    # СГОВОРИЛИСЬ: эскроу, контракт, агенда, слово со сроком — всё настоящее
    _store().purse_add(_wid(), "pc", -stake)
    summary = {"dead": f"убрать {tname}", "bring": f"добыть {want_txt or 'обещанное'}",
               "visit": f"прийти: {want_txt or 'куда уговорились'}",
               "befriend": f"сойтись с {tname}"}[kind]
    cid = f"deal|{npc}|{_gt()}"
    _store().save_contract(_wid(), cid, "active", {
        "giver": "pc", "executor": npc, "kind": kind, "target": target,
        "want": want_txt, "stake": stake, "made_gt": _gt(),
        "due_gt": _gt() + PB["deal_due_min"], "title": summary,
    })
    p.state.agendas.insert(0, Agenda(
        f"исполнить уговор с чужаком: {summary} (задаток взят, {stake} зм)", "hired", 0.9))
    _deeds.promise_make(npc, PLAYER, what=summary, when_ru="утром", where="",
                        node=None, place_label=str(loc), witnesses=wit)
    p.state.memory.add(f"взял у чужака задаток {stake} зм: {summary}", _mt(), 0.9,
                       about=[PLAYER] + ([target] if target else []))
    _pc_remember(f"нанял {p.name}: {summary} за {stake} зм", 0.8, about=[npc])
    _npc_save(npc)
    out["narr"].append(f"{verdict} — сговорились. {stake} зм уходят задатком. "
                       f"{p.name}, не глядя: «Сделаю. Не ищи меня до срока».")
    out["refresh"] = True
    return out


def _deal_jobs() -> list:
    """Утро: наёмные дела исполняются НАСТОЯЩИМ миром — заказ крови = авторезолв
    исполнитель против цели (тот же движок, что зачистки); просрочка = возврат задатка."""
    from aidnd.combat.auto import resolve as combat_resolve
    from aidnd.server.play.engine import deeds as _deeds
    from aidnd.server.play.mechanics.combat import _combatant_from_npc

    people = _S.get("people") or {}
    dead = {k.split("|", 1)[1] for k in _store().flags_prefix(_wid(), "dead|")}
    news = []
    for d in _store().contracts(_wid(), "active"):
        if d.get("giver") != "pc" or not d.get("executor"):
            continue
        ex, cid = d["executor"], d["id"]
        if ex not in people or ex in dead:             # исполнитель выбыл — задаток назад
            _store().purse_add(_wid(), "pc", d["stake"])
            _store().save_contract(_wid(), cid, "failed", _clean(d))
            continue
        if d["kind"] != "dead":                        # прочие виды: срок вышел — слово пало
            if _gt() > d["due_gt"]:
                _store().purse_add(_wid(), "pc", d["stake"])
                _store().save_contract(_wid(), cid, "failed", _clean(d))
                _pc_remember(f"{people[ex].name} не исполнил уговор — задаток вернулся", 0.5,
                             about=[ex])
            continue
        if _gt() < d["made_gt"] + PB["deal_night_min"]:
            continue                                   # на дело идут ночью — не сразу
        tgt = d.get("target")
        if not tgt or tgt in dead or tgt not in people:
            _store().purse_add(_wid(), ex, d["stake"])  # цель уже мертва — считает исполненным
            _store().save_contract(_wid(), cid, "done", _clean(d))
            continue
        hunter = _combatant_from_npc(ex, people[ex])
        prey = _combatant_from_npc(tgt, people[tgt])
        prey.side = "foes"
        r = combat_resolve([hunter], [prey], seed=f"dealkill|{cid}")
        tname = people[tgt].name
        if r["status"] == "won":
            _store().flag_set(_wid(), f"dead|{tgt}")
            _deeds.record(ex, "murder", obj=tgt, place="глухой час", witnesses=[],
                          data={"hired_by": "pc", "stake": d["stake"]})
            _store().purse_add(_wid(), ex, d["stake"])
            _store().save_contract(_wid(), cid, "done", _clean(d))
            people[ex].state.memory.add(
                f"сделал грязную работу ({tname}) — задаток отработан", _mt(), 0.9,
                about=[PLAYER, tgt])
            _npc_save(ex)
            news.append(f"{tname} — найден(а) мёртвым(ой). Город гудит, стража рыщет.")
        else:
            _store().purse_add(_wid(), "pc", d["stake"])
            _store().save_contract(_wid(), cid, "failed", _clean(d))
            people[ex].state.memory.add(
                f"не смог: {tname} отбился(лась) — я едва ушёл", _mt(), 0.9, about=[tgt])
            _npc_save(ex)
            _pc_remember(f"{people[ex].name} не сдюжил — задаток вернулся", 0.6, about=[ex])
            news.append(f"ночью у {tname} была драка — отбился(лась) от ночного гостя")
    return news
