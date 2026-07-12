"""Game loop — CONTRACTS: quests from agendas (steps-predicates) + bulletin board.

Layer mechanics/ (see docs/loop.md).

Key functions
-------------
_contract_offer(npc: str) -> dict | None : Generate personal quest offer for NPC.
_make_contract(npc: str, status: str) -> dict | None : Core contract generation from agendas.
_contract_on_give(npc: str, it: dict) -> str | None : Complete quest step when item given.
_contract_on_move(loc: int) -> str | None : Complete quest step when reaching location.
_contract_on_talk(npc: str) -> str | None : Complete quest step when talking to NPC.
_board_ads() -> list : Return active board advertisements.
_board_publish() -> list : Publish new contract to board.
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

# ------------------------------------------- CONTRACTS (quests from agendas) --- #
# Quest = delegated NPC need: want-PREDICATE over world (regardless of HOW you obtain) + real
# reward. Goal chosen from REAL things in world (building containers, valuables of others).

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
    """Check and assemble ONE contract step from LLM spec (goal — from real world). None — invalid."""
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
    else:  # dead — only true enemy of giver
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
    """Real goals for contract: contents of building containers + valuables OF OTHER people."""
    out = []
    giver_work = (_S.get("people") or {}).get(giver)
    giver_work = giver_work.work if giver_work else None
    for bid in list(_S.get("cr2b", {}).values()):
        if bid == giver_work:
            continue  # don't ask from OWN building — absurd
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
    """Personal request in conversation: once per person (flag coffer). Mechanics decides WHAT is possible,
    LLM requests IN CHARACTER."""
    p = _S["people"][npc]
    last = _store().flag_get(_wid(), f"coffer|{npc}")
    if last:
        try:
            if _gt() - int(last) < 2880:             # asked recently — doesn't whine; 2 days and can ask again
                return None
        except ValueError:                           # old flag format (no gt) — expired
            pass
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    if rel.get("affinity", 0) < PB["contract_enemy_aff"]:  # don't do business with obvious enemy
        return None
    r = _make_contract(npc, "offered")
    if r:
        _store().flag_set(_wid(), f"coffer|{npc}", str(_gt()))
    return r


def _make_contract(npc: str, status: str) -> dict | None:
    """Core contract generation for NPC (request/announcement): agenda → candidates → LLM → steps.
    Saves contract with given status. None — only 'nothing to offer/invalid';
    LLM unavailability raised as exception."""
    p = _S["people"][npc]
    mgr = _model()
    if not (p.state.agendas or []):  # long goal — lazy, on first need
        ag0 = plan_agenda(p.state, MWorld(), {"roles": {npc: p.role}}, mgr)
        if ag0:
            p.state.agendas.append(ag0)
    if not (p.state.agendas or []):
        return None
    _materialize_npc(npc, "pockets")
    purse = _store().purse_get(_wid(), npc)
    reward_item = None
    if purse < PB["contract_poor_purse"]:  # poor pays with thing, not coin
        rows = [
            (r["item_id"], _store().get_item(r["item_id"])) for r in _store().inventory(_wid(), npc)
        ]
        rows = [(i, it) for i, it in rows if it and it["kind"] != "key"]
        if not rows:
            return None
        reward_item = max(rows, key=lambda x: x[1]["worth"])
    cands = _contract_candidates(npc)
    random.Random(f"cands|{npc}").shuffle(cands)  # different order to different givers — against echo
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
    for spec in specs[:3]:  # chain up to 3 steps; any invalid → reject
        st = _build_step(spec if isinstance(spec, dict) else {}, npc, p, cands, own, others)
        if not st:
            return None
        steps.append(st)
    if not steps:
        return None
    first = steps[0]  # top-level = FIRST step (compatibility)
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
    """Contract steps. Old single-step contract (no steps) — wrap in one step."""
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
    """Current step complete: if last — payout; else step++ and hint for next."""
    steps = _ct_steps(ct)
    nstep = ct.get("step", 0) + 1
    if nstep >= len(steps):
        return _contract_complete(ct)
    data = {k: v for k, v in ct.items() if k not in ("id", "status")}
    data["step"] = nstep
    _store().save_contract(_wid(), ct["id"], "active", data)
    return f"{step_narr} Шаг {nstep} из {len(steps)}. Дальше: {_step_desc(steps[nstep])}."


def _contract_complete(ct: dict) -> str:
    """Full payout of ANY completed contract: reward, trust, memory, log."""
    giver = ct["giver"]
    p = _S["people"][giver]
    _materialize_npc(giver, "pockets")  # so there's something to pay with
    if ct.get("reward_item"):  # reward with thing (poor)
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
    from aidnd.server.play.engine.journal import j_quest

    _suf = " доставлен" if ct.get("kind") in ("bring", "deliver") else ""
    j_quest("saw", f"выполнено для {p.name}: "
                   f"{ct.get('want') or ct.get('target_name')}{_suf}", ct["id"])
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
    if ct.get("src") == "sift":  # honest bridge (Inc 1): advance the giver's REAL agenda + re-plan
        from aidnd.server.play.engine.quests import bridge as _qb

        try:
            _qb.quest_writeback(ct, _giver_world(ct), _S.get("model"))
        except Exception:  # noqa: BLE001 — writeback must NEVER break the payout it follows
            pass
    return f"Уговор исполнен! {paid}."


def _giver_world(ct: dict) -> tuple:
    """Build the giver-relative (state, world) the bridge consumes: the giver's Body carries their
    REAL store loot (purse + inventory) so have/wealth predicates read true; each dead-disjunct target
    gets a Body reflecting its dead-flag; affinity reads state.relationships. Dormant in Inc 1 — only
    src:"sift" contracts (Inc 2+) ever reach it."""
    from aidnd.mind import Body as _MBody
    from aidnd.mind import Item as _MItem
    from aidnd.mind import World as _MWorld

    giver = ct["giver"]
    p = _S["people"][giver]
    _materialize_npc(giver, "pockets")
    loot = []
    coins = _store().purse_get(_wid(), giver)
    if coins > 0:
        loot.append(_MItem("кошель", min(1.0, coins / 40), kind="coin", amount=coins))
    for r in _store().inventory(_wid(), giver):
        it = _store().get_item(r["item_id"])
        if it:
            loot.append(_MItem(it["name"], min(1.0, (it.get("worth") or 0) / 40)))
    w = _MWorld()
    w.add(_MBody(id=giver, place="", loot=loot))
    for cond in ct.get("done_any") or []:
        if cond.get("type") == "dead":
            vid = cond.get("id")
            if vid and vid not in w.bodies:
                dead = bool(_store().flag_get(_wid(), f"dead|{vid}"))
                w.add(_MBody(id=vid, place="", hp=0 if dead else 10, alive=not dead))
    return p.state, w


def _sift_maybe_close() -> str | None:
    """Predicate-driven close for emergent (src:"sift") contracts (spec §3a 'however obtained'):
    any active sift contract whose done_any holds for the giver completes now, whatever route made it
    true. Improvised contracts are skipped — their step engine stays authoritative."""
    from aidnd.server.play.engine.quests import bridge as _qb

    for ct in _store().contracts(_wid(), "active"):
        if ct.get("src") != "sift":
            continue
        if _qb.done_any_met(ct, _giver_world(ct)):
            return _contract_complete(ct)
    return None


def _contract_on_give(npc: str, it: dict) -> str | None:
    """give closes CURRENT step: bring (brought to giver) and deliver (handed to recipient)."""
    hit = _sift_maybe_close()  # sift closes predicate-driven, whatever route was taken
    if hit:
        return hit
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
    """visit: reached location — current step complete."""
    hit = _sift_maybe_close()  # sift closes predicate-driven, whatever route was taken
    if hit:
        return hit
    for ct in _store().contracts(_wid(), "active"):
        cur = _ct_cur(ct)
        if cur.get("kind") == "visit" and cur.get("target") == loc:
            return _ct_advance(ct, "Место осмотрено.")
    return None


def _contract_on_talk(npc: str) -> str | None:
    """befriend: target took to you — current step complete."""
    hit = _sift_maybe_close()  # sift closes predicate-driven, whatever route was taken
    if hit:
        return hit
    for ct in _store().contracts(_wid(), "active"):
        cur = _ct_cur(ct)
        if cur.get("kind") == "befriend" and cur.get("target") == npc:
            rel = _S["people"][npc].state.relationships.get(PLAYER, {})
            if rel.get("affinity", 0) >= PB["befriend_aff"]:
                return _ct_advance(ct, "Он проникся к тебе.")
    return None


def _board_ads() -> list:
    """Announcements on pole — contracts with board status (NPCs posted by their agendas)."""
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
    """Morning: busy townsperson posts announcement on pole (same contract generator)."""
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
    except Exception:  # noqa: BLE001 — posting doesn't break morning
        return []
    return [f"{people[npc].name} повесил объявление на городскую доску"] if r else []


def _consume_world_item(want: str, where: str) -> None:
    """Thing from announcement completed by NPC → it REALLY leaves the world: from building container rows
    (not materialized) or from cont-holder (materialized). Do not touch 'person-carried'."""
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
                for r in _store().inventory(_wid(), holder):  # container already live
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
    """Morning: someone from townspeople removes announcement and fulfills it (world lives without player).
    bring-thing REALLY disappears from container — world doesn't lie."""
    rng = random.Random(f"boardful|{_gt() // 1440}")
    news = []
    for ct in _store().contracts(_wid(), "board"):
        if rng.random() > PB["board_npc_fulfill"]:
            continue
        cur = _ct_cur(ct)
        if cur.get("kind") == "bring" and cur.get("want"):
            try:
                _consume_world_item(cur["want"], cur.get("where", ""))
            except Exception:  # noqa: BLE001 — cleanup doesn't break morning
                pass
        _store().save_contract(
            _wid(), ct["id"], "done", {k: v for k, v in ct.items() if k not in ("id", "status")}
        )
        news.append(f"с доски сняли: «{_step_desc(_ct_cur(ct))}» — выполнено горожанином")
    return news


def trait_hints_str(p) -> str:
    from aidnd.worldgen.persona_llm import trait_hints

    return trait_hints(p.state.config.traits, p.charisma, p.appearance)
