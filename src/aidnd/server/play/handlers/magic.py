"""Домен МАГИЯ (хендлеры /cast /glyphs /learn /teachers /grimoire) — распил world.py (LOOP.md).
Круг-рисунок → закон от LLM (кламп по бюджету), каст без броска, гримуар-на-мир, обучение глифам.
"""

from __future__ import annotations

import math
import random

from fastapi import Request

from aidnd.combat import roll_dice
from aidnd.magic import circle_hash, classify, fallback_law, power_budget
from aidnd.magic import describe as magic_describe
from aidnd.magic import load as magic_load
from aidnd.magic import normalize as magic_normalize
from aidnd.server.play.engine.core import (
    _S,
    PB,
    PLAYER,
    TEACHER_ROLES,
    _fat_add,
    _fatigue,
    _glyph_learn,
    _glyphs_known,
    _grimoire_get,
    _grimoire_list,
    _grimoire_put,
    _gt,
    _gt_add,
    _here,
    _inscriber,
    _mana,
    _mana_cap,
    _mana_grow,
    _mana_spend,
    _met,
    _mt,
    _npc_save,
    _pc_cap_eff,
    _pc_hp,
    _pc_remember,
    _pc_save,
    _store,
    _wanted_add,
    _wid,
    router,
)
from aidnd.server.play.engine.world import _look_key, _play, _voice


def _spell_hit(t, dmg: dict, out: dict, tag: str) -> None:
    """Нанести урон-по-типу одному бойцу (резисты/иммунитеты бестиария), разбудить спящего."""
    n = roll_dice(dmg["dice"], random.Random(f"spelldmg|{_mt()}|{tag}"))
    if dmg["type"] in t.immune:
        n = 0
    elif dmg["type"] in t.resist:
        n //= 2
    t.hp -= n
    if n > 0 and t.status.pop("asleep", 0):
        out["narr"].append(f"{t.name} просыпается от удара.")
    if t.hp <= 0:
        t.alive = False
    fell = " — падает!" if not t.alive else f" [{t.hp}/{t.max_hp}]"
    out["narr"].append(f"{dmg['dice']} → {t.name}: {n} урона{fell}")


def _apply_law(law: dict, target, out: dict, people, crof, loc) -> None:
    """Исполнение ЗАКОНА круга. Механика (mech) — по бою/миру как раньше; freeform-суть (полёт,
    иллюзия, туман...) — фраза закона становится СОБЫТИЕМ мира: нарратив, память, свидетели."""
    cb = _S.get("combat")
    mech = law.get("mech") or {}
    if law.get("sensory"):
        out["narr"].append(law["sensory"])
    if mech.get("heal"):
        before = _pc_hp()
        _pc_hp(mech["heal"])
        out["narr"].append(f"Раны затягиваются — +{_pc_hp() - before} hp.")
    if mech.get("reveal"):
        _S.setdefault("looked", {})[_look_key(loc, _S.get("inside"))] = 2
        out["narr"].append("Округа проявляется до мелочей.")
        out["refresh"] = True
    if mech.get("light"):
        out["narr"].append("Ровный свет разгоняет тьму вокруг.")
    if mech.get("unlock"):
        out["narr"].append("Незримый ключ поворачивается — что заперто, поддаётся.")

    enc = cb["enc"] if cb else None
    t = enc.units.get(target) if (enc and target) else None
    area = mech.get("aoe") or {}
    dmg = mech.get("damage")
    if dmg and enc:
        foes = [u for u in enc.units.values() if u.side == "foes" and not u.down()]
        if area.get("shape") in ("burst", "cloud") and t:  # AoE вокруг клетки цели
            r = area.get("radius", 1)
            hit = [u for u in foes if max(abs(u.x - t.x), abs(u.y - t.y)) <= r]
            out["narr"].append(f"«{law['name']}» накрывает {len(hit)} цел(и):")
            for u in hit:
                _spell_hit(u, dmg, out, u.id)
            out["combat_refresh"] = True
        elif area.get("shape") in ("cone", "wall"):  # веер/стена от героя
            pc_u = enc.units.get("pc")
            length = max(2, area.get("radius", 2))
            hit = [u for u in foes if pc_u and enc.dist(pc_u, u) <= length] if pc_u else foes[:3]
            out["narr"].append(f"«{law['name']}» бьёт {len(hit)} цел(и):")
            for u in hit:
                _spell_hit(u, dmg, out, u.id)
            out["combat_refresh"] = True
        elif t and t.side == "foes" and not t.down():  # одиночный снаряд
            _spell_hit(t, dmg, out, target)
            out["combat_refresh"] = True
        else:
            out["narr"].append("Заряд собран, но метать не в кого — цель не указана.")
    elif dmg:
        out["narr"].append("Заряд собран, но метать не в кого — врагов рядом нет.")

    st = mech.get("status")
    if st:
        kind, turns = st.get("kind", "bound"), st.get("turns", 1)
        if enc and t and t.side == "foes" and not t.down():
            t.status[kind] = max(t.status.get(kind, 0), turns)
            word = {"bound": "спутан", "asleep": "усыплён", "afraid": "объят ужасом"}.get(
                kind, kind
            )
            out["narr"].append(f"{t.name} {word} ({turns} р.).")
            out["combat_refresh"] = True
        else:
            out["narr"].append("Путы сплетены, но некого вязать (нужна цель в бою).")

    # freeform-суть закона — событие мира: что круг ДЕЛАЕТ, то и происходит (нарратив + память + сцена)
    known_mech = any(k in mech for k in ("damage", "heal", "status", "reveal", "unlock", "light"))
    if law.get("law") and not known_mech:
        out["narr"].append(law["law"])
        out["refresh"] = True
        for wpid in _here(loc, crof):  # очевидцы freeform-чуда запоминают его
            people[wpid].state.memory.add(
                f"видел(а) волшбу чужака: {law['law'][:90]}", _mt(), 0.55, about=[PLAYER]
            )
            _npc_save(wpid)
    _pc_remember(f"сотворил «{law['name']}»: {law.get('law', '')[:80]}", 0.5)


_ELEM_DMG = {
    "огонь": "fire",
    "лёд": "cold",
    "яд": "poison",
    "свет": "radiant",
    "тьма": "necrotic",
    "камень": "bludgeoning",
}


def _apply_wild(comp, reason: str, out: dict) -> None:
    """Дикий/сорванный круг (М-3): LLM выбирает исход из ОГРАНИЧЕННОГО меню — применяем механически.
    Меню безопасно (нельзя сломать мир): backfire | nothing | scorch | warp | boon."""
    cb = _S.get("combat")
    w = _inscriber().wild(comp, reason, bool(cb)) or {
        "effect": "backfire",
        "magnitude": 2,
        "element": "",
        "text": f"Круг рвётся вразнос — {reason}.",
    }
    mag = max(1, min(3, int(w.get("magnitude") or 1)))
    eff = w.get("effect", "backfire")
    out["cast"]["wild"] = True
    out["cast"]["effect"] = eff
    out["narr"].append(w.get("text") or f"Круг идёт вразнос — {reason}.")
    if eff == "nothing":
        return
    if eff == "boon":
        before = _pc_hp()
        _pc_hp(2 * mag)
        out["narr"].append(f"Нежданная удача — раны затягиваются (+{_pc_hp() - before} hp).")
        return
    if eff == "warp":
        _gt_add(PB["act_min"])  # искажение — странный сдвиг, без жёсткой механики
        out["refresh"] = True
        return
    if eff == "scorch" and cb:
        dt = _ELEM_DMG.get(w.get("element", ""), "fire")
        hit = 0
        for u in cb["enc"].units.values():
            if u.side == "foes" and not u.down():
                n = mag * 3
                if dt in u.immune:
                    n = 0
                elif dt in u.resist:
                    n //= 2
                u.hp -= n
                if u.hp <= 0:
                    u.alive = False
                hit += 1
        if hit:
            out["narr"].append(f"Выброс стихии хлещет по округе — задето {hit}.")
            out["combat_refresh"] = True
            return
    # backfire (и scorch, когда некого жечь) — отдача калечит чертящего
    _pc_hp(-2 * mag)
    out["narr"].append(f"Отдача калечит чертящего — {2 * mag} урона.")


def _inscribe_law(comp, cls: dict):
    """Роль А: рисунок круга → ЗАКОН мира. Первый раз LLM-законописец ПРОЯВЛЯЕТ закон целиком
    (суть свободна, сила клампится бюджетом рисунка), кэш в гримуаре по хэшу РИСУНКА.
    Возвращает (entry, fresh)."""
    h = circle_hash(comp)
    entry = _grimoire_get(h)
    if entry:
        return entry, False
    law = _inscriber().scribe_law(comp, cls) or fallback_law(comp)
    entry = {
        "hash": h,
        "comp": magic_normalize(comp),
        "descr": magic_describe(comp),
        **{
            k: law.get(k)
            for k in (
                "name",
                "flavor",
                "sensory",
                "kind",
                "power",
                "target",
                "range",
                "duration",
                "mech",
                "law",
                "taboo",
            )
        },
        "first_gt": _gt(),
        "casts": 0,
    }
    _grimoire_put(h, entry)
    return entry, True


def _taboo(people, crof, loc, out: dict) -> int:
    """Открытая боевая/дикая магия среди горожан = ведьмовство → розыск (М-4, лёгкая версия;
    отдельный орден/инквизиция — второй срез). В бою (логово вне города) свидетелей нет."""
    if _S.get("combat"):
        return 0
    wit = [w for w in _here(loc, crof) if people[w].role not in ("маг", "писец")]
    if not wit:
        return 0
    for w in wit:
        people[w].state.memory.add(
            "видел(а): чужак колдовал прямо у всех на виду", _mt(), 0.6, about=[PLAYER]
        )
        _npc_save(w)
    _wanted_add(PB["taboo_witness"] + min(2, len(wit)), "колдовал у всех на виду")
    out["narr"].append("Люди вокруг отшатываются и крестятся — ведьмовство не забудут.")
    return len(wit)


def _draw_rate() -> float:
    """Скорость таяния свечи (мана/сек) при черчении: базовая, мягче от Инт+Мдр (усталость учтена)."""
    cap = _pc_cap_eff()
    soft = 1 + PB["draw_intwis_k"] * (cap.mod("int") + cap.mod("wis"))
    return round(PB["draw_drain_per_s"] / max(0.4, soft), 3)


def _cast_cost(comp, draw_ms, known: bool):
    """Сколько маны сожжёт круг. Известный из гримуара — мгновенно за долю бюджета (М1a). Новый —
    утечка·секунды_черчения + Σ(вес×размер×кольцо). Без draw_ms (клик-ввод) — только глифы."""
    budget = power_budget(comp)
    if known:
        return max(1, round(budget * PB["known_cost_k"]))
    secs = max(0.0, float(draw_ms or 0) / 1000.0)
    return max(1, math.ceil(_draw_rate() * secs + budget))


@router.post("/api/play/cast")
async def cast(request: Request):
    """Сотворить круг-РИСУНОК (глифы × размер × положение × кольца). БЕЗ бросков: чистый круг при
    хватившей мане срабатывает ВСЕГДА; срывы — только противоречия в рисунке или выброс (свеча
    погасла посреди черчения). Закон круга проявляет LLM-законописец (кэш в гримуаре); известный
    закон — мгновенно за фикс-долю. Гейт: только выученные глифы; тёмный закон на людях → розыск."""
    city, people, crof, cr2b, loc = _play()
    body = await request.json()
    comp = magic_normalize(body.get("drawing") or body.get("glyphs") or [])
    target = body.get("target")
    known_g = set(_glyphs_known())
    locked = sorted({p["id"] for p in comp if p["id"] not in known_g})
    if locked:
        g = magic_load()
        names = ", ".join(g["all"][c].get("ru", c) for c in locked)
        return {
            "cast": {"kind": "locked"},
            "narr": [f"Ты не владеешь глифом: {names}. Выучи у наставника."],
            "mana": _mana(),
            "gt": _gt(),
        }
    cls = classify(comp)
    out = {"narr": [], "cast": {"kind": cls["kind"]}}
    if cls["kind"] == "empty":
        return {
            **out,
            "narr": [f"Круг не сходится — {cls['reason']}."],
            "mana": _mana(),
            "gt": _gt(),
        }
    is_known = _grimoire_get(circle_hash(comp)) is not None  # рисунок уже вписан → мастерский каст
    mana_before = _mana()
    cost = _cast_cost(comp, body.get("draw_ms"), is_known)
    if is_known and mana_before < cost:  # мастерский круг не запустить без маны
        return {
            **out,
            "narr": [f"Маны мало: нужно {cost:g}, есть {mana_before:g}. Отдохни."],
            "mana": mana_before,
            "mana_cap": _mana_cap(),
            "gt": _gt(),
        }
    guttered = (not is_known) and cost > mana_before  # свеча погасла посреди черчения — выброс
    spend = min(mana_before, cost)
    _mana_spend(spend)
    _mana_grow(spend)  # выжигание растит потолок маны
    _fat_add(spend * (PB["burnout_fat_mult"] if guttered else 1))  # выброс истощает сильнее
    _gt_add(PB["act_min"])
    out["cast"].update(
        {
            "mode": "known" if is_known else "drawn",
            "guttered": guttered,
            "cost": round(spend, 1),
            "budget": power_budget(comp),
        }
    )
    if cls["kind"] == "wild" or guttered:  # противоречие/выброс → непредсказуемый исход
        reason = (
            "свеча погасла — круг сорвался в руках"
            if guttered and cls["kind"] != "wild"
            else cls["reason"]
        )
        _apply_wild(comp, reason, out)
        _taboo(people, crof, loc, out)  # дикий выброс на людях — ведьмовство
        _pc_remember("круг ушёл вразнос", 0.4)
        _pc_save()
        res = {
            **out,
            "mana": _mana(),
            "mana_cap": _mana_cap(),
            "hp": _pc_hp(),
            "fatigue": _fatigue(),
            "gt": _gt(),
        }
        if out.get("combat_refresh") and _S.get("combat"):
            res["combat"] = _S["combat"]["enc"].view()
        return res
    law, fresh = _inscribe_law(comp, cls)  # чистый круг: закон (LLM/кэш гримуара)
    law["casts"] = law.get("casts", 0) + 1
    _grimoire_put(law["hash"], law)
    out["cast"]["name"] = law["name"]
    out["cast"]["fresh"] = fresh
    if fresh:
        head = f"✦ Новый закон вписан в гримуар: «{law['name']}»"
        if law.get("flavor"):
            head += f" — {law['flavor']}"
        out["narr"].append(head)
    _apply_law(law, target, out, people, crof, loc)  # исполнение: механика + freeform-событие
    if (
        law.get("taboo")
        or (law.get("mech") or {}).get("damage")
        or (law.get("mech") or {}).get("status")
    ):
        _taboo(people, crof, loc, out)  # тёмный/боевой закон на людях — ведьмовство
    _pc_save()
    res = {
        **out,
        "mana": _mana(),
        "mana_cap": _mana_cap(),
        "hp": _pc_hp(),
        "fatigue": _fatigue(),
        "gt": _gt(),
    }
    if out.get("combat_refresh") and _S.get("combat"):
        res["combat"] = _S["combat"]["enc"].view()
    return res


@router.get("/api/play/glyphs")
def glyphs_list():
    """Палитра магии: весь базис + пометка known (владеет игрок) vs заперто (учить у мага/писца)."""
    _play()
    g = magic_load()
    known = set(_glyphs_known())
    elems = [{**e, "known": e["id"] in known} for e in g["elements"].values()]
    glyphs = [{**s, "known": s["id"] in known} for s in g["glyphs"].values()]
    return {
        "elements": elems,
        "glyphs": glyphs,
        "known": sorted(known),
        "mana": _mana(),
        "mana_cap": _mana_cap(),
        "fatigue": _fatigue(),
        "draw": {"rate": _draw_rate(), "known_k": PB["known_cost_k"]},
    }  # клиент тает свечу в такт


def _teachable(role: str) -> set:
    """Что учит наставник: маг — стихии/формы/моды; писец — глаголы/моды (не огонь)."""
    g = magic_load()
    axes = {"маг": {"element", "form", "mod"}}.get(role, {"verb", "mod"})
    return {gid for gid, e in g["all"].items() if e.get("axis") in axes}


@router.post("/api/play/learn")
async def learn_glyph(request: Request):
    """Выучить глиф у наставника (маг в башне / писец). Гейт: симпатия ≥ порога; цена монетами по весу,
    при высокой симпатии — даром. Наставник должен быть здесь и уметь это преподать."""
    _city, people, crof, _cr2b, loc = _play()
    b = await request.json()
    gid, teacher = str(b.get("glyph") or ""), b.get("teacher")
    g = magic_load()
    if gid not in g["all"]:
        return {"error": "нет такого глифа"}
    if teacher not in people or teacher not in _here(loc, crof):
        return {"error": "наставника нет рядом"}
    p = people[teacher]
    if p.role not in TEACHER_ROLES:
        return {"error": f"{p.name} не учит магии"}
    if gid not in _teachable(p.role):
        kind = (
            "стихиям и формам — ищи мага в башне"
            if p.role != "маг"
            else "глаголам письма — это к писцу"
        )
        return {"error": f"{p.name} не обучает этому ({kind})"}
    if gid in _glyphs_known():
        return {"error": "ты уже владеешь этим глифом"}
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    aff = rel.get("affinity", 0.0)
    if aff < PB["learn_aff_min"]:
        return {"error": f"{p.name} не станет тебя учить — сперва заслужи доверие"}
    weight = g["all"][gid].get("weight", 1)
    price = 0 if aff >= PB["learn_aff_free"] else PB["learn_base"] + PB["learn_per_weight"] * weight
    if price > _store().purse_get(_wid(), "pc"):
        return {"error": f"нужно {price} зм за урок — не хватает"}
    if price:
        _store().purse_add(_wid(), "pc", -price)
        _store().purse_add(_wid(), teacher, price)
    _glyph_learn(gid)
    _gt_add(PB["talk_min"])
    ru = g["all"][gid].get("ru", gid)
    p.state.memory.add(f"обучил игрока глифу «{ru}»", _mt(), 0.4, about=[PLAYER])
    _pc_remember(f"выучил глиф «{ru}» у {p.name}", 0.5, about=[teacher])
    _npc_save(teacher)
    _pc_save()
    line = _voice(
        p,
        rel,
        "reply",
        f"(Ты обучил игрока чертить глиф «{ru}»{' за ' + str(price) + ' зм' if price else ' безвозмездно, по дружбе'}. "
        f"Скажи что-нибудь наставническое, по своему характеру.)",
    )
    return {
        "learned": gid,
        "ru": ru,
        "price": price,
        "line": line,
        "coins": _store().purse_get(_wid(), "pc"),
        "known": sorted(_glyphs_known()),
        "gt": _gt(),
    }


@router.get("/api/play/teachers")
def teachers_here():
    """Кто на локации способен учить магии (для UI: подсветить наставника)."""
    _city, people, crof, _cr2b, loc = _play()
    out = []
    for pid in _here(loc, crof):
        p = people[pid]
        if p.role in TEACHER_ROLES and (pid in _met() or p.work):
            out.append(
                {
                    "id": pid,
                    "name": p.name,
                    "role": p.role,
                    "teaches": sorted(_teachable(p.role) - set(_glyphs_known())),
                }
            )
    return {"teachers": out}


@router.get("/api/play/grimoire")
def grimoire_list():
    """Вписанные в мир законы (гримуар игрока): имя, состав, флейвор, число сотворений."""
    _play()
    laws = _grimoire_list()
    return {
        "laws": [
            {
                "name": e.get("name"),
                "comp": e.get("comp", []),
                "flavor": e.get("flavor", ""),
                "sensory": e.get("sensory", ""),
                "law": e.get("law", ""),
                "kind": e.get("kind", ""),
                "power": e.get("power"),
                "descr": e.get("descr", ""),
                "casts": e.get("casts", 0),
            }
            for e in laws
        ],
        "count": len(laws),
    }
