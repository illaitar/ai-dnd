"""MAGIC domain (handlers /cast /glyphs /learn /teachers /grimoire) — split from world.py (docs/loop.md).
Circle-drawing → law from LLM (budget-clamped), casting without roll, world-grimoire, glyph learning.

Key functions
-------------
cast(request) -> dict : Execute a drawn spell circle—validate glyphs, cost, and handle backlash.
glyphs_list() -> dict : List all available glyphs and mark which ones the player knows.
learn_glyph(request) -> dict : Learn a glyph from a teacher—requires affinity and coins.
teachers_here() -> dict : List nearby NPCs who teach magic for UI highlighting.
grimoire_list() -> dict : List spells inscribed in the grimoire with composition and cast count.
"""

from __future__ import annotations

import math
import random

from fastapi import Request

from aidnd.combat import roll_dice
from aidnd.magic import circle_hash, classify, power_budget
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
from aidnd.server.play.engine.resolve import _voice
from aidnd.server.play.engine.world import _look_key, _play


def _spell_hit(t, dmg: dict, out: dict, tag: str) -> None:
    """Deal typed damage to one combatant (bestiary resists/immunities), wake sleeping one."""
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
    """Execute circle LAW. Mechanics (mech) — combat/world as before; freeform essence (flight,
    illusion, fog...) — law phrase becomes world EVENT: narration, memory, witnesses."""
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
        if area.get("shape") in ("burst", "cloud") and t:  # AoE around target cell
            r = area.get("radius", 1)
            hit = [u for u in foes if max(abs(u.x - t.x), abs(u.y - t.y)) <= r]
            out["narr"].append(f"«{law['name']}» накрывает {len(hit)} цел(и):")
            for u in hit:
                _spell_hit(u, dmg, out, u.id)
            out["combat_refresh"] = True
        elif area.get("shape") in ("cone", "wall"):  # cone/wall from hero
            pc_u = enc.units.get("pc")
            length = max(2, area.get("radius", 2))
            hit = [u for u in foes if pc_u and enc.dist(pc_u, u) <= length] if pc_u else foes[:3]
            out["narr"].append(f"«{law['name']}» бьёт {len(hit)} цел(и):")
            for u in hit:
                _spell_hit(u, dmg, out, u.id)
            out["combat_refresh"] = True
        elif t and t.side == "foes" and not t.down():  # single projectile
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

    # freeform essence of law — world event: what circle DOES happens (narration + memory + scene)
    known_mech = any(k in mech for k in ("damage", "heal", "status", "reveal", "unlock", "light"))
    if law.get("law") and not known_mech:
        out["narr"].append(law["law"])
        out["refresh"] = True
        for wpid in _here(loc, crof):  # witnesses of freeform miracle remember it
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
    """Wild/ruptured circle (M-3): LLM chooses outcome from LIMITED menu — apply mechanically.
    Menu is safe (can't break world): backfire | nothing | scorch | warp | boon."""
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
        _gt_add(PB["act_min"])  # distortion — strange shift, no hard mechanics
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
    # backfire (and scorch when no one to burn) — recoil cripples drawer
    _pc_hp(-2 * mag)
    out["narr"].append(f"Отдача калечит чертящего — {2 * mag} урона.")


def _inscribe_law(comp, cls: dict):
    """Role A: circle drawing → world LAW. First time LLM lawscribe MANIFESTS the whole law
    (essence free, power clamped by drawing budget), cache in grimoire by drawing HASH.
    Returns (entry, fresh)."""
    h = circle_hash(comp)
    entry = _grimoire_get(h)
    if entry:
        return entry, False
    law = _inscriber().scribe_law(comp, cls)  # LLM required; errors go honestly to player
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
    """Open combat/wild magic among townsfolk = witchcraft → manhunt (M-4, light version;
    separate order/inquisition — second tier). In combat (lair outside city) no witnesses."""
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
    """Candle melting speed (mana/sec) while drawing: base, softened by Int+Wis (fatigue accounted for)."""
    cap = _pc_cap_eff()
    soft = 1 + PB["draw_intwis_k"] * (cap.mod("int") + cap.mod("wis"))
    return round(PB["draw_drain_per_s"] / max(0.4, soft), 3)


def _cast_cost(comp, draw_ms, known: bool):
    """How much mana circle burns. Known from grimoire — instantly for fraction of budget (M1a). New —
    leak·drawing_seconds + Σ(weight×size×ring). Without draw_ms (click-input) — glyphs only."""
    budget = power_budget(comp)
    if known:
        return max(1, round(budget * PB["known_cost_k"]))
    secs = max(0.0, float(draw_ms or 0) / 1000.0)
    return max(1, math.ceil(_draw_rate() * secs + budget))


@router.post("/api/play/cast")
async def cast(request: Request):
    """Execute a circle-DRAWING (glyphs × size × position × rings). WITHOUT rolls: clean circle with
    enough mana fires ALWAYS; ruptures — only contradictions in drawing or guttering (candle went out
    mid-draw). Circle law manifested by LLM-lawscribe (grimoire cached); known law — instantly for fixed
    fraction. Gate: learned glyphs only; dark law among people → manhunt."""
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
    is_known = _grimoire_get(circle_hash(comp)) is not None  # drawing already inscribed → master cast
    mana_before = _mana()
    cost = _cast_cost(comp, body.get("draw_ms"), is_known)
    if is_known and mana_before < cost:  # master circle won't cast without mana
        return {
            **out,
            "narr": [f"Маны мало: нужно {cost:g}, есть {mana_before:g}. Отдохни."],
            "mana": mana_before,
            "mana_cap": _mana_cap(),
            "gt": _gt(),
        }
    guttered = (not is_known) and cost > mana_before  # candle went out mid-draw — rupture
    spend = min(mana_before, cost)
    _mana_spend(spend)
    _mana_grow(spend)  # burning grows mana cap
    _fat_add(spend * (PB["burnout_fat_mult"] if guttered else 1))  # rupture exhausts harder
    _gt_add(PB["act_min"])
    out["cast"].update(
        {
            "mode": "known" if is_known else "drawn",
            "guttered": guttered,
            "cost": round(spend, 1),
            "budget": power_budget(comp),
        }
    )
    if cls["kind"] == "wild" or guttered:  # contradiction/rupture → unpredictable outcome
        reason = (
            "свеча погасла — круг сорвался в руках"
            if guttered and cls["kind"] != "wild"
            else cls["reason"]
        )
        _apply_wild(comp, reason, out)
        _taboo(people, crof, loc, out)  # wild rupture among people — witchcraft
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
    law, fresh = _inscribe_law(comp, cls)  # clean circle: law (LLM/grimoire cache)
    law["casts"] = law.get("casts", 0) + 1
    _grimoire_put(law["hash"], law)
    out["cast"]["name"] = law["name"]
    out["cast"]["fresh"] = fresh
    if fresh:
        head = f"✦ Новый закон вписан в гримуар: «{law['name']}»"
        if law.get("flavor"):
            head += f" — {law['flavor']}"
        out["narr"].append(head)
    _apply_law(law, target, out, people, crof, loc)  # execution: mechanics + freeform-event
    if (
        law.get("taboo")
        or (law.get("mech") or {}).get("damage")
        or (law.get("mech") or {}).get("status")
    ):
        _taboo(people, crof, loc, out)  # dark/combat law among people — witchcraft
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


# ---------------------------------------------------------- ENCHANT (bound law) --- #
_LAW_KEYS = ("name", "flavor", "sensory", "kind", "power", "target", "range", "duration",
             "mech", "law", "taboo", "hash")


def _enchant_cap(it: dict) -> float:
    """Max law budget an item can hold — from its чара (arcane capacity). No чара → not enchantable."""
    chara = ((it.get("attrs") or {}).get("чара") or {}).get("true", 0)
    return chara / PB["enchant_chara_k"]


def _activate_enchant(it: dict) -> dict:
    """Fire an item's bound law via the spell runner (_apply_law) — deterministic, no LLM. Decrements
    charges; the enchant is spent (removed) at 0, the item remains. In combat, targets a standing foe."""
    _city, people, crof, _cr2b, loc = _play()
    en = it["enchant"]
    out: dict = {"narr": []}
    cb = _S.get("combat")
    target = None
    if cb and cb.get("enc"):
        target = next((u.id for u in cb["enc"].units.values() if u.side == "foes" and not u.down()), None)
    _apply_law(en, target, out, people, crof, loc)
    en["charges"] = int(en.get("charges", 1)) - 1
    if en["charges"] <= 0:
        it.pop("enchant", None)
        out["narr"].append("Чары иссякли — вещь снова проста.")
    _store().save_item(it)
    _pc_save()
    res = {"activated": True, "name": it["name"], "narr": out["narr"], "refresh": out.get("refresh"),
           "hp": _pc_hp(), "mana": _mana(), "mana_cap": _mana_cap(),
           "charges": (it.get("enchant") or {}).get("charges", 0), "gt": _gt()}
    if out.get("combat_refresh") and cb:
        res["combat"] = cb["enc"].view()
    return res


@router.post("/api/play/enchant")
async def enchant_item(request: Request):
    """Bind a drawn circle's LAW into an item instead of casting it (reuses the cast pipeline). The
    item's чара caps the law's budget; binding costs mana like a cast; the law fires later on «применить»."""
    _city, people, crof, _cr2b, loc = _play()
    body = await request.json()
    iid = body.get("item")
    it = _store().get_item(iid)
    if not it or not any(r["item_id"] == iid for r in _store().inventory(_wid(), "pc")):
        return {"error": "нет такой вещи"}
    cap = _enchant_cap(it)
    if cap <= 0:
        return {"error": f"«{it['name']}» не держит чар — в ней нет чары."}
    comp = magic_normalize(body.get("drawing") or body.get("glyphs") or [])
    locked = sorted({p["id"] for p in comp if p["id"] not in set(_glyphs_known())})
    if locked:
        g = magic_load()
        return {"error": "Ты не владеешь глифом: " + ", ".join(g["all"][c].get("ru", c) for c in locked)}
    cls = classify(comp)
    if cls["kind"] == "empty":
        return {"error": f"Круг не сходится — {cls['reason']}."}
    if cls["kind"] == "wild":
        return {"error": "Круг противоречив — такой закон не вплести в вещь."}
    budget = power_budget(comp)
    if budget > cap:
        return {"error": f"«{it['name']}» не удержит столь мощный закон — нужна чара покрепче."}
    is_known = _grimoire_get(circle_hash(comp)) is not None
    cost = _cast_cost(comp, body.get("draw_ms"), is_known)
    if _mana() < cost:
        return {"error": f"Маны мало: нужно {cost:g}, есть {_mana():g}. Отдохни."}
    _mana_spend(cost)
    _mana_grow(cost)
    _gt_add(PB["act_min"])
    law, _fresh = _inscribe_law(comp, cls)                  # LLM on a novel circle; grimoire-cached is DET
    it["enchant"] = {**{k: law.get(k) for k in _LAW_KEYS}, "charges": PB["enchant_charges"]}
    _store().save_item(it)
    _pc_save()
    return {"enchanted": True, "name": it["name"], "law": law["name"], "charges": PB["enchant_charges"],
            "narr": [f"✦ «{law['name']}» вплетён в «{it['name']}» — {PB['enchant_charges']} закл."],
            "mana": _mana(), "mana_cap": _mana_cap(), "gt": _gt()}


@router.get("/api/play/glyphs")
def glyphs_list():
    """Magic palette: all basis + mark known (player owns) vs locked (learn from mage/scribe)."""
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
    }  # client melts candle in sync


def _teachable(role: str) -> set:
    """What teacher teaches: mage — elements/forms/modes; scribe — verbs/modes (not fire)."""
    g = magic_load()
    axes = {"маг": {"element", "form", "mod"}}.get(role, {"verb", "mod"})
    return {gid for gid, e in g["all"].items() if e.get("axis") in axes}


@router.post("/api/play/learn")
async def learn_glyph(request: Request):
    """Learn a glyph from a teacher (mage in tower / scribe). Gate: affinity ≥ threshold; price in coins
    by weight, high affinity — free. Teacher must be here and able to teach it."""
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
    """Who on location can teach magic (for UI: highlight teacher)."""
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
    """Laws inscribed in world (player grimoire): name, composition, flavor, cast count."""
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
