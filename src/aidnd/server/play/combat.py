"""Игровой контур — БОЙ И ГИЛЬДИЯ: логова, ранги/жетон, дуэли, авторезолв.

Авто-разбит из routes_play.py (ТД3). Слои: core<items<contracts<combat<main.
"""


from __future__ import annotations

import random

from fastapi import Request

from ...combat import (
    dungeon,
    from_npc,
    from_pc,
    lair_name,
    pick_encounter,
    resolve,
)
from .contracts import _ct_advance, _ct_cur
from .core import (
    _GT0,
    _PC_CAP,
    _S,
    _SESS,
    PB,
    PLAYER,
    _binfo,
    _gt,
    _gt_add,
    _here,
    _mt,
    _npc_save,
    _pc_hp,
    _pc_name,
    _pc_remember,
    _pc_save,
    _store,
    _wanted_add,
    _wid,
    router,
)
from .items import _merchant_restock, _pc_coins, _pool_add_new, _pool_draw, _put_item, _rar_tag


# ---------------------------------------- ЛОГОВА, ГИЛЬДИЯ, БОЙ (BG-lite) --- #
def _lairs() -> list:
    """Логова вокруг города: детерминированно из данных бестиария (вид/CR/среда), cleared — в store."""
    if _S.get("lairs") is None:
        import math
        rng = random.Random("lairs|1")
        out = []
        envs = ["Forest", "Hill", "Grassland", "Swamp", "Ruin", "Caverns"]
        for i in range(PB["lairs"]):
            ang = (i / PB["lairs"]) * 6.2832 + rng.uniform(-0.3, 0.3)
            rr = 300 * (1.25 + rng.uniform(0, 0.45))
            cr = PB["lair_cr_near"] + (PB["lair_cr_far"] - PB["lair_cr_near"]) * (i / max(1, PB["lairs"] - 1))
            env = rng.choice(envs)
            units = pick_encounter(cr, env, seed=f"lair|{i}")
            out.append({"id": f"lair:{i}", "name": lair_name(units, random.Random(f"ln|{i}")),
                        "env": env, "cr": round(sum(u.cr for u in units), 2),
                        "n": len(units), "foe": (units[0].name if units else "?"),
                        "x": round(490 + math.cos(ang) * rr, 1), "y": round(350 + math.sin(ang) * rr * 0.72, 1)})
        _S["lairs"] = out
    return [{**l, "cleared": bool(_store().flag_get(_wid(), f"cleared|{l['id']}"))}
            for l in _S["lairs"]]


# ---- РАНГИ ГИЛЬДИИ (данные): имя · потолок CR заказа · сколько закрытых заказов нужно ---- #
GUILD_RANKS = (
    {"name": "Медь", "cr_max": 1.0, "need": 0},
    {"name": "Бронза", "cr_max": 2.0, "need": 2},
    {"name": "Железо", "cr_max": 4.0, "need": 5},
    {"name": "Серебро", "cr_max": 8.0, "need": 9},
    {"name": "Золото", "cr_max": 99.0, "need": 14},
)


def _rank_by_name(nm: str) -> int:
    return next((i for i, r in enumerate(GUILD_RANKS) if r["name"] == nm), 0)


def _mint_badge(rank_idx: int, holder: str = "pc") -> str:
    """Выковать жетон гильдии (предмет-удостоверение) данного ранга и вручить держателю.
    Ранг/владелец живут во флагах, привязанных к id жетона (переживают кражу/передачу)."""
    nm = GUILD_RANKS[rank_idx]["name"]
    iid = _put_item(f"badge|{_wid()}|{holder}|{rank_idx}", f"Жетон гильдии ({nm})", "document",
                    tier="fine", note="удостоверение приключенца", holder=holder)
    _store().flag_set(_wid(), f"badge_rank|{iid}", str(rank_idx))
    _store().flag_set(_wid(), f"badge_owner|{iid}", holder)
    return iid


def _pc_badge() -> tuple | None:
    """(iid, rank_idx, owner) жетона в сумке игрока, либо None. Ранг — из флага (или из имени)."""
    for r in _store().inventory(_wid(), "pc"):
        it = _store().get_item(r["item_id"])
        if it and it["kind"] == "document" and "Жетон гильдии" in it["name"]:
            iid = r["item_id"]
            rf = _store().flag_get(_wid(), f"badge_rank|{iid}")
            if rf is None:
                nm = it["name"].split("(")[-1].rstrip(")")
                rf = _rank_by_name(nm)
            owner = _store().flag_get(_wid(), f"badge_owner|{iid}") or "pc"
            return iid, int(rf), owner
    return None


def _guild_steward():
    """Распорядитель гильдии — работник её здания (для проверки лжи по чужому жетону)."""
    gb = _guild_bid()
    people = _S.get("people") or {}
    return next((p for pid, p in people.items() if p.work == gb), None)


def _guild_closed() -> int:
    return int(_store().flag_get(_wid(), "guild_closed|pc") or 0)


def _guild_promote() -> str | None:
    """Повышение по числу закрытых заказов: если дорос — заменить жетон на старший ранг."""
    b = _pc_badge()
    if not b or b[2] != "pc":                              # без своего жетона не повышают
        return None
    iid, rank, _own = b
    closed = _guild_closed()
    nxt = rank + 1
    if nxt < len(GUILD_RANKS) and closed >= GUILD_RANKS[nxt]["need"]:
        _store().inv_drop(_wid(), iid)                     # старый жетон изымают
        _mint_badge(nxt)
        return f"Распорядитель вручает тебе жетон ({GUILD_RANKS[nxt]['name']}) — ранг повышен."
    return None


def _guild_gate(job_cr: float) -> dict | None:
    """Гейт доски/вылазки: жетон в сумке, ранг по чину, проверка лжи для чужого жетона.
    Возвращает {error, dice?} при отказе, иначе None (и, для чужого жетона, {dice, stolen})."""
    if _store().flag_get(_wid(), "guild_mark|pc"):
        return {"error": f"на тебе чёрная метка гильдии — искупи вину ({PB['guild_mark_fine']} зм)"}
    b = _pc_badge()
    if not b:
        return {"error": "нужен жетон гильдии — вступи у доски"}
    iid, rank, owner = b
    if job_cr > GUILD_RANKS[rank]["cr_max"]:
        return {"error": f"не по чину: жетон «{GUILD_RANKS[rank]['name']}» "
                         f"берёт заказы до CR {GUILD_RANKS[rank]['cr_max']:g}"}
    if owner != "pc":                                      # чужой жетон — распорядитель проверяет
        stew = _guild_steward()
        wis = stew.state.config.abilities.get("wis", 10) if stew else 10
        pr, pw = random.Random(f"lie|{iid}|{_gt()}").randint(1, 20), \
            random.Random(f"insight|{iid}|{_gt()}").randint(1, 20)
        me = pr + _PC_CAP.mod("cha")
        them = pw + (wis - 10) // 2
        dice = {"die": 20, "roll": pr, "mod": _PC_CAP.mod("cha"), "total": me, "dc": them,
                "ok": me >= them, "label": "Обман (Cha) против чутья распорядителя"}
        if me < them:                                      # раскусили — жетон изъят, метка
            _store().inv_drop(_wid(), iid)
            _store().flag_set(_wid(), "guild_mark|pc", "1")
            return {"error": "Распорядитель прищуривается: «Это не твой жетон». Его изымают, "
                             "а тебе — чёрную метку.", "dice": dice}
        return {"ok_stolen": True, "dice": dice}           # прошло, но заслуги не твои
    return None


def _guild_bid() -> str | None:
    """Здание гильдии: лучший матч по данным (тип весомее имени — «склад гильдии» не гильдия)."""
    best, score = None, 0
    for bid in sorted(set((_S.get("cr2b") or {}).values())):
        info = _binfo(bid)
        sc = (2 if "гильд" in info["kind"].lower() else 0) + \
             (1 if "гильд" in info["name"].lower() else 0) - \
             (1 if "склад" in (info["name"] + info["kind"]).lower() else 0)
        if sc > score:
            best, score = bid, sc
    return best


def _guild_board() -> list:
    """Доска гильдии: контракт на каждое незачищенное логово. Награда по CR из кассы гильдии."""
    if not _store().flag_get(_wid(), "guild_purse"):
        _store().purse_add(_wid(), "guild", PB["guild_float"])
        _store().flag_set(_wid(), "guild_purse")
    taken = {c.get("target") for c in _store().contracts(_wid(), "active")}
    done = {c.get("target") for c in _store().contracts(_wid(), "done")}
    out = []
    for l in _lairs():
        if l["cleared"] or l["id"] in taken or l["id"] in done:
            continue
        out.append({"id": f"ct:guild:{l['id']}", "lair": l["id"], "name": l["name"],
                    "foe": l["foe"], "n": l["n"], "cr": l["cr"],
                    "reward": max(3, round(l["cr"] * PB["guild_reward_per_cr"]))})
    return out


def _guild_status() -> dict:
    """Ранг игрока (по жетону в сумке), прогресс до следующего, метка."""
    b = _pc_badge()
    closed = _guild_closed()
    if not b:
        return {"member": False, "closed": closed,
                "marked": bool(_store().flag_get(_wid(), "guild_mark|pc"))}
    _iid, rank, owner = b
    nxt = GUILD_RANKS[rank + 1] if rank + 1 < len(GUILD_RANKS) else None
    return {"member": True, "rank": GUILD_RANKS[rank]["name"], "rank_idx": rank,
            "cr_max": GUILD_RANKS[rank]["cr_max"], "own": owner == "pc", "closed": closed,
            "next": (nxt["name"] if nxt else None), "next_need": (nxt["need"] if nxt else None),
            "marked": bool(_store().flag_get(_wid(), "guild_mark|pc"))}


def _pc_combatant():
    rows = [(r["item_id"], _store().get_item(r["item_id"]))
            for r in _store().inventory(_wid(), "pc")]
    weapons = [it for _i, it in rows if it and it["kind"] == "weapon"]
    weapon = max(weapons, key=lambda w: w["worth"], default=None)
    combatant = from_pc(_PC_CAP.abilities, _pc_hp(), PB["pc_max_hp"], weapon=weapon)
    combatant.name = _pc_name()                            # имя героя (с лендинга), не «Странник»
    return combatant


_TIER_QUALITY = {"poor": "crude", "modest": "plain", "comfortable": "fine", "wealthy": "exquisite"}


def _npc_weapon(p) -> dict | None:
    """Оружие NPC для боя — из его персоны (имя даёт дальнобой, ярус → качество кости)."""
    w = ((p.persona or {}).get("gear") or {}).get("weapon")
    if not w:
        return None
    return {"name": w.get("name", ""), "quality": _TIER_QUALITY.get(w.get("tier", "modest"), "plain")}


def _combatant_from_npc(pid, p):
    """Боец из NPC: живучесть от выносливости/куража, оружие из персоны (from_npc сам считает hp)."""
    return from_npc(pid, p.name, {"abilities": p.state.config.abilities,
                                  "traits": p.state.config.traits}, weapon=_npc_weapon(p))


def _contract_on_death(pid: str) -> str | None:
    """dead-предикат: заказанный враг мёртв — текущий шаг закрыт."""
    for ct in _store().contracts(_wid(), "active"):
        cur = _ct_cur(ct)
        if cur.get("kind") == "dead" and cur.get("target") == pid:
            return _ct_advance(ct, "Дело сделано — его больше нет.")
    return None


_EPITAPHS = (
    "Здесь и оборвалась дорога.",
    "Ни имени на камне, ни венка — только тишина.",
    "Так закончился этот путь, без песен и без могилы.",
    "Город переживёт и это. Тебя — нет.",
    "Дорога забрала своё.",
)


def _death(cause: str) -> dict:
    """ПЕРМАСМЕРТЬ: мир юзера стирается целиком, сессия выбрасывается. Следующий заход в
    /play создаст новый город с нуля (новый seed из монотонного счётчика)."""
    days = max(0, (_gt() - _GT0) // 1440)
    epitaph = _EPITAPHS[(_gt() // 137) % len(_EPITAPHS)]    # варьируем без Random-состояния
    wid = _wid()
    if wid == 1:                                            # дев-мир: следующий — с новым сидом
        _store().flag_set(0, "dev_seed", str(int(_store().flag_get(0, "dev_seed") or 1) + 1))
    _store().destroy_world(wid)
    _SESS.pop(wid, None)                                    # выкинуть мир из памяти (дев переиздаст с нуля)
    return {"status": "lost", "narr": [cause],
            "death": {"text": epitaph, "days": int(days), "cause": cause}}


def _duel_wrapup(enc, cb) -> dict:
    """Итог стычки с человеком: смерть реальна, мир видел, добро — победителю."""
    st = enc.status()
    pid = cb["npc"]
    p = _S["people"].get(pid)
    if st == "lost":                                       # герой пал в дуэли — мир кончился
        return _death(f"{p.name if p else 'Противник'} валит тебя наземь. Ты не встаёшь.")
    _gt_add(max(1, enc.round * PB["combat_round_s"] // 60))  # бой в секундах: раунд = 5с
    pc_u = enc.units.get("pc")
    out = {"status": st, "narr": []}
    if pc_u:
        _pc_hp(set_to=max(1, pc_u.hp))
    if st == "won" and p:
        _store().flag_set(_wid(), f"dead|{pid}")
        for r in _store().inventory(_wid(), pid):       # труп обобран
            _store().inv_move(_wid(), r["item_id"], "pc")
        cnp = _store().purse_get(_wid(), pid)
        if cnp:
            _store().purse_add(_wid(), pid, -cnp)
            _store().purse_add(_wid(), "pc", cnp)
        wit = [w for w in _here(cb.get("loc"), _S["crof"]) if w != pid and w in _S["people"]]
        for w in wit:
            _S["people"][w].state.memory.add(f"чужак УБИЛ {p.name} у меня на глазах",
                                             _mt(), 0.95, about=[PLAYER, pid])
            _npc_save(w)
        done = _contract_on_death(pid)
        _S["crof"].pop(pid, None)
        _S["people"].pop(pid, None)
        _pc_remember(f"убил {p.name}", 0.95, about=[pid])
        if wit:                                            # УБИЙСТВО при свидетелях — тяжкий розыск
            _wanted_add(PB["crime_murder"] + min(4, len(wit)), f"убил {p.name}")
        out["narr"].append(f"{p.name} мёртв. Его добро — твоё. Свидетелей: {len(wit)}."
                           + (f" {done}" if done else ""))
    elif st == "lost" and p:
        take = _pc_coins() // PB["defeat_coin_cut"]
        if take:
            _store().purse_add(_wid(), "pc", -take)
            _store().purse_add(_wid(), pid, take)
        rel = p.state.rel(PLAYER)
        rel["affinity"] = min(rel["affinity"], -0.6)
        p.state.memory.add("чужак напал на меня — я его избил(а) и обобрал(а)", _mt(), 0.9, about=[PLAYER])
        _npc_save(pid)
        out["narr"].append(f"Ты повержен. Очнулся в грязи — кошель легче на {take} зм." if take
                           else "Ты повержен и валяешься в грязи.")
        _pc_remember(f"проиграл драку {p.name}", 0.8, about=[pid])
    elif p:
        p.state.memory.add("чужак напал на меня и сбежал", _mt(), 0.8, about=[PLAYER])
        _npc_save(pid)
        out["narr"].append("Ты уходишь из драки. Позор переживёшь.")
    _pc_save()
    _S["combat"] = None
    out["hp"] = _pc_hp()
    out["coins"] = _pc_coins()
    return out


def _combat_wrapup(enc, cb) -> dict:
    """Итог боя: лут/награды/hp/последствия. Один путь для победы/бегства/поражения."""
    if isinstance(cb, dict) and cb.get("npc"):
        return _duel_wrapup(enc, cb)
    l = cb["lair"] if isinstance(cb, dict) and "lair" in cb else cb
    st = enc.status()
    if st == "lost":                                       # герой пал в логове — мир кончился
        return _death(f"Тьма смыкается в {l['name']}. Отсюда ты уже не выйдешь.")
    _gt_add(max(1, enc.round * PB["combat_round_s"] // 60))  # бой в секундах: раунд = 5с
    pc_u = enc.units.get("pc")
    out = {"status": st, "narr": []}
    if pc_u:
        _pc_hp(set_to=max(1, pc_u.hp))
    if st == "won":
        _store().flag_set(_wid(), f"cleared|{l['id']}")
        coins = max(1, round(l["cr"] * PB["loot_coin_per_cr"]))
        total = _store().purse_add(_wid(), "pc", coins)
        out["narr"].append(f"Логово зачищено. В остатках — {coins} зм (кошель: {total}).")
        if random.Random(f"loot|{l['id']}").random() < PB["loot_item_chance"]:
            it = _pool_draw(f"trophy|{l['id']}", tier="rare", holder="pc")   # трофей rare+ из пула
            if it:
                out["narr"].append(f"Среди костей — «{it['name']}»{_rar_tag(it)}.")
                _pool_add_new(it)                          # добавить в пул мира (спека §5)
        _merchant_restock(f"clearstock|{l['id']}")         # зачистка оживила рынок — новый товар
        ct = next((c for c in _store().contracts(_wid(), "active")
                   if c.get("kind") == "clear" and c.get("target") == l["id"]), None)
        if ct:
            reward = min(ct["reward"], _store().purse_get(_wid(), "guild"))
            _store().purse_add(_wid(), "guild", -reward)
            total = _store().purse_add(_wid(), "pc", reward)
            _store().save_contract(_wid(), ct["id"], "done",
                                   {k: v for k, v in ct.items() if k not in ("id", "status")})
            out["narr"].append(f"Заказ гильдии закрыт: +{reward} зм (кошель: {total}).")
            b = _pc_badge()
            if b and b[2] == "pc":                          # заслуга идёт лишь под СВОИМ жетоном
                _store().flag_set(_wid(), "guild_closed|pc", str(_guild_closed() + 1))
                up = _guild_promote()
                if up:
                    out["narr"].append(up)
        _pc_remember(f"зачистил {l['name']}", 0.7)
    elif st == "lost":
        cut = _pc_coins() // PB["defeat_coin_cut"]
        if cut:
            _store().purse_add(_wid(), "pc", -cut)
        out["narr"].append("Тьма. Ты очнулся у городских ворот — жив, но растрёпан"
                           + (f" и легче на {cut} зм." if cut else "."))
        _pc_remember(f"был бит в {l['name']} — едва унёс ноги", 0.8)
    else:
        out["narr"].append("Ты уходишь из боя. Логово осталось за ними.")
        _pc_remember(f"отступил из {l['name']}", 0.5)
    _pc_save()
    _S["combat"] = None
    out["hp"] = _pc_hp()
    out["coins"] = _pc_coins()
    return out


@router.get("/api/play/combat")
def combat_state():
    cb = _S.get("combat")
    if not cb:
        return {"active": False}
    return {"active": True, "combat": cb["enc"].view(), "head": cb.get("head") or {},
            "lair": cb.get("lair"), "hp": _pc_hp()}


@router.post("/api/play/combat_act")
async def combat_act(request: Request):
    cb = _S.get("combat")
    if not cb:
        return {"error": "боя нет"}
    enc = cb["enc"]
    b = await request.json()
    cur = enc.current()
    err = None
    if cur and cur.id == "pc" and cur.incapacitated():      # связан/спит — ход героя потерян
        enc._log(f"{cur.name} {'связан' if cur.status.get('bound') else 'спит'} — ход потерян.")
        enc.end_turn()
    elif cur and cur.id == "pc":
        a = b.get("type")
        if a == "move":
            err = enc.act_move(cur, int(b.get("x", cur.x)), int(b.get("y", cur.y)))
        elif a == "attack":
            err = enc.act_attack(cur, str(b.get("target")))
        elif a == "dodge":
            err = enc.act_dodge(cur)
        elif a == "flee":
            err = enc.act_flee(cur)
        elif a == "end":
            enc.end_turn()
        if err:
            return {"combat": enc.view(), "error": err}
        if a in ("attack", "dodge", "flee"):
            enc.end_turn()
    guard = 0
    while guard < 80:                                       # крутим ИИ до хода игрока; накаты по пути
        if enc.foes_cleared() and enc.next_wave():          # текущий накат зачищен — следующий
            continue
        if enc.status() != "active":
            break
        c = enc.current()
        if c is None or c.id == "pc":
            break
        enc.ai_turn(c)
        guard += 1
    if enc.status() != "active":
        return {"combat": enc.view(), "over": _combat_wrapup(enc, cb), "gt": _gt()}
    pc_u = enc.units.get("pc")
    if pc_u:
        _pc_hp(set_to=max(0, pc_u.hp))
    return {"combat": enc.view(), "hp": _pc_hp(), "gt": _gt()}


def _npc_delves() -> list:
    """Утренние вылазки: пара смелых незанятых NPC берёт верхний заказ доски и идёт в бой
    (авторезолв ТЕМ ЖЕ движком). Мир живёт: доска пустеет без игрока."""
    people = _S.get("people") or {}
    jobs = _guild_board()
    if not jobs or random.Random(f"delve|{_gt() // 1440}").random() > PB["npc_delve_chance"]:
        return []
    day = _gt() // 1440
    rng = random.Random(f"delveparty|{day}")
    brave = [(pid, p) for pid, p in sorted(people.items())
             if not p.work and p.state.config.traits.get("bravery", 0) >= PB["npc_brave_min"]]
    if not brave:
        return []
    # приоритет — бойцовым ролям (данные), внутри группы порядок случайный; отряд 2-3
    brave.sort(key=lambda pp: (0 if pp[1].role in PB["fighter_roles"] else 1, rng.random()))
    duo = brave[:rng.randint(2, 3)]
    job = jobs[0]
    l = next(x for x in _lairs() if x["id"] == job["lair"])
    party = [_combatant_from_npc(pid, p) for pid, p in duo]
    lseed = l["id"].split(":")[1]
    wv = dungeon.waves(l["cr"] + 0.01, l["env"], seed=lseed, n=PB["dungeon_waves"])
    obs = dungeon.obstacles(12, 9, l["env"], seed=lseed)
    r = resolve(party, wv[0], seed=f"npcdelve|{day}", obstacles=obs, waves=wv[1:])
    names = " и ".join(p.name for _pid, p in duo)
    if r["status"] == "won":
        _store().flag_set(_wid(), f"cleared|{l['id']}")
        for pid, p in duo:
            _store().purse_add(_wid(), pid, max(1, job["reward"] // 2))
            p.state.memory.add(f"мы с напарником зачистили {l['name']} по заказу гильдии",
                               _mt(), 0.8, about=[d0 for d0, _ in duo])
            _npc_save(pid)
        return [f"{names} зачистили {l['name']} (заказ доски закрыт)"]
    for pid, p in duo:
        p.state.memory.add(f"нас потрепали в {l['name']} — еле ушли", _mt(), 0.7)
        _npc_save(pid)
    return [f"{names} вернулись из {l['name']} потрёпанными — логово стоит"]
