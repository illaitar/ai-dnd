"""Game loop — ITEMS: inventory, forging, pool, rarity, crafting along materials graph.

Mechanics layer (see docs/loop.md).

Key functions
-------------
_pool_draw(seed, tier, holder) -> dict | None : Draw item from loot pool, forge, mark unique.
_do_craft(detail, out) -> dict : Perform crafting along materials graph with skill checks.
_materialize_zones(bid) -> None : Lazily manifest building zone objects as real items.
_put_item(seed, name, kind, ...) -> str : Mechanically forge and place item idempotently.
_materialize_npc(pid, layer) -> None : Manifest NPC inventory from persona (visible/pockets).
_forge(seed, kind, name_hint, source, band) -> dict : Lazy item forging via LLM with cache.
_zone_stock(bid, zid) -> list[tuple] : Get current items in zone after theft/pickup.
"""

from __future__ import annotations

import hashlib
import random

from aidnd.items import Capability, ItemCtx, LLMSmith, craft_path, loot_pool
from aidnd.items import condition as item_condition
from aidnd.items import inspect as item_inspect
from aidnd.items import normalize as item_normalize
from aidnd.items import view as item_view
from aidnd.items.craft import ROLE_RECIPES, materials_graph
from aidnd.server.play.engine.core import (
    _PC_CAP,
    _S,
    PB,
    _binfo,
    _gt_add,
    _model,
    _mt,
    _store,
    _tokens_ru,
    _wid,
)


def _seed_item_pool() -> None:
    """Populate world item pool with seed templates (data, no LLM). Once per world."""
    if _store().item_pool_count(_wid()) > 0:
        return
    for t in loot_pool.seed_templates():
        _store().pool_add_item(_wid(), t["key"], t["data"], t["weight"])


def _pool_draw(seed: str, tier: str | None = None, holder: str = "pc") -> dict | None:
    """Draw item from world pool (by rarity weight, skipping used uniques), forge it as real item
    for holder, and—if unique—mark so it won't drop again."""
    pool = _store().pool_items(_wid())
    if not pool:
        _seed_item_pool()
        pool = _store().pool_items(_wid())
    taken = {r["key"] for r in pool if _store().unique_taken(_wid(), r["key"])}
    tpl = loot_pool.draw(pool, taken, seed, tier=tier)
    if not tpl:
        return None
    d = tpl["data"]
    if d.get("rarity") == "unique":
        _store().unique_mark(_wid(), tpl["key"])
    iid = "it:" + hashlib.md5(f"{seed}|{tpl['key']}|{holder}".encode()).hexdigest()[:10]
    if not _store().get_item(iid):
        it = item_normalize({**d, "apparent_worth": d.get("worth", 1)})
        it["id"] = iid
        _store().save_item(it)
    _store().inv_add(_wid(), iid, holder=holder)
    return _store().get_item(iid)


def _pool_add_new(it: dict) -> None:
    """New item (crafted/loot) added to world POOL—as per spec §5."""
    rar = it.get("rarity", "common")
    _store().pool_add_item(
        _wid(),
        f"made:{it['name']}",
        {
            "name": it["name"],
            "kind": it["kind"],
            "quality": it.get("quality", "plain"),
            "worth": it.get("worth", 1),
            "rarity": rar,
        },
        loot_pool.RARITY_WEIGHT.get(rar, 100),
    )


_RAR_RU = {"common": "", "rare": " (редкое)", "epic": " (эпическое!)", "unique": " (УНИКАЛЬНОЕ!)"}


def _rar_tag(it: dict) -> str:
    return _RAR_RU.get(it.get("rarity", "common"), "")


def _merchant_restock(seed: str) -> str | None:
    """Spawn event: restock merchant from item pool (lair clear / caravan)."""
    people = _S.get("people") or {}
    sellers = [pid for pid, p in sorted(people.items()) if p.work]
    if not sellers:
        return None
    pid = random.Random(f"restock|{seed}|{_wid()}").choice(sellers)
    it = _pool_draw(f"{seed}|{pid}", tier=None, holder=pid)
    return f"{people[pid].name} выставил на продажу «{it['name']}»{_rar_tag(it)}" if it else None


# Lathe from edge of materials graph → in which buildings it exists (keywords for type/name)
STATION_HINTS = {
    "anvil": ("кузн", "оружейн"),
    "forge": ("кузн", "оружейн"),
    "bench": ("мастерск", "лавк", "оружейн", "сапожн", "столярн", "гильди"),
    "cauldron": ("целебн", "знахар", "таверн", "трактир", "травн", "пекарн"),
    "tannery": ("кожевн", "дубильн"),
}
STATION_RU = {
    "anvil": "наковальня",
    "forge": "горн",
    "bench": "верстак",
    "cauldron": "котёл",
    "tannery": "дубильня",
}


def _do_craft(detail: str, out: dict) -> dict:
    """Craft along MATERIALS GRAPH: inventory items → goal via path with gates (place=workshop,
    time from edges). Consumes leaf materials, forges result, adds to world pool."""
    graph = materials_graph()
    nodes = {n["id"]: n for n in graph["nodes"]}
    dtok = _tokens_ru(detail)
    scored = [
        (nid, len(_tokens_ru(nid) & dtok) + (2 if nid.lower() in detail.lower() else 0))
        for nid in nodes
    ]
    best = max(scored, key=lambda s: s[1])
    want = best[0] if best[1] > 0 else None  # most matched words
    if not want:
        out["narr"].append(
            "Не пойму, что сковать — назови вещь ремесла (клинок, лук, доспех, отвар…)."
        )
        return out
    inv = [
        (r["item_id"], _store().get_item(r["item_id"])) for r in _store().inventory(_wid(), "pc")
    ]
    have = {itm["name"] for _i, itm in inv if itm}
    path = craft_path(have, want)
    if path is None:
        out["narr"].append(f"«{want}» так просто не сделать — не хватает материалов.")
        return out
    if not path:
        out["narr"].append(f"«{want}» у тебя уже есть.")
        return out
    inside = _S.get("inside")
    if not inside:  # gate-place: need workshop
        out["narr"].append("Тут не смастеришь — зайди в мастерскую/кузницу.")
        return out
    binfo = _binfo(inside)
    btok = (binfo["name"] + " " + binfo["kind"]).lower()
    for e in path:  # gate-machine: BUILDING must have required
        hints = STATION_HINTS.get(e.get("place", "bench"), ())
        if hints and not any(h in btok for h in hints):
            need = STATION_RU.get(e.get("place"), e.get("place", ""))
            out["narr"].append(f"Для «{e['to']}» нужен {need} — тут такого нет.")
            return out
    produced = {e["to"] for e in path}
    leaves = {src for e in path for src in e["from"] if src not in produced}
    missing = [s for s in leaves if s not in have]
    if missing:
        out["narr"].append("Не хватает: " + ", ".join(missing) + ".")
        return out
    skills = {e["skill"] for e in path if e.get("skill")}
    if skills - set(_PC_CAP.competencies):  # gate-skill: unfamiliar craft—roll
        roll = random.Random(f"craftskill|{want}|{_mt()}").randint(1, 20)
        total_r = roll + _PC_CAP.mod("int")
        out["dice"] = {
            "die": 20,
            "roll": roll,
            "mod": _PC_CAP.mod("int"),
            "total": total_r,
            "dc": PB["craft_skill_dc"],
            "ok": total_r >= PB["craft_skill_dc"],
            "label": "Ремесло (Int) — незнакомая работа",
        }
        if total_r < PB["craft_skill_dc"]:
            _gt_add(PB["craft_fail_min"])
            out["narr"].append(
                "Работа не задалась — заготовка цела, но время ушло. Попробуй позже."
            )
            return out
    for name in leaves:  # consume base materials from bag
        iid = next((i for i, itm in inv if itm and itm["name"] == name), None)
        if iid:
            _store().inv_drop(_wid(), iid)
    total = sum(int(e.get("time", 10)) for e in path)
    _gt_add(total)
    made_id = _put_item(
        f"craft|{want}|{_mt()}",
        want,
        nodes[want].get("kind", "misc"),
        tier="fine",
        note="своей ковки",
        holder="pc",
    )
    _pool_add_new(_store().get_item(made_id))
    out["narr"].append(
        f"Ты мастеришь: {' → '.join(e['to'] for e in path)}. "
        f"Готово — «{want}» (потрачено {total} мин)."
    )
    out["refresh"] = True
    return out


# --------------------------------------------------- ITEMS (slice 1) ---- #
_ROLE_COMP = {
    "кузнец": {"metalwork"},
    "знахарка": {"herbs", "poison", "medicine"},
    "лавочник": {"trade", "gems"},
    "жрец": {"letters", "faith"},
    "бард": {"lore", "letters"},
    "стражник": {"law"},
    "трактирщик": {"trade"},
}


def _smith():
    if _S.get("smith") is None:
        _S["smith"] = LLMSmith(_model())  # LLM only—no fallbacks
    return _S["smith"]


def _npc_cap(p) -> Capability:
    ab = getattr(getattr(p.state, "config", None), "abilities", None) or {}
    return Capability(abilities=ab, competencies=_ROLE_COMP.get(p.role, set()))


# ---------------------------------- UNIFIED INVENTORY (holders: pc | npc | cont:) ----
_TIER_Q = {"poor": "crude", "modest": "plain", "fine": "fine", "rich": "exquisite"}
_TIER_W = {"poor": 1, "modest": 4, "fine": 15, "rich": 40}


def _cont_holder(bid: str, name: str) -> str:
    return f"cont:{bid}:{name}"


def _zone_holder(bid: str, zid: str) -> str:
    return f"zone:{bid}/{zid}"


def _materialize_zones(bid: str) -> None:
    """Building décor → REAL items in live.db (holder=zone:<bid>/<zid>), lazily on first entry.
    Idempotent: id from seed, inv_add OR IGNORE—taken NOT returned (PK world+item tracks new holder).
    Final layer 'all real'."""
    from aidnd.server.play.engine.zones import building_zones

    _zd, zones = building_zones(bid)
    for z in zones:
        holder = _zone_holder(bid, z["id"])
        for i, o in enumerate(z.get("objects") or []):
            if not isinstance(o, dict) or not o.get("name"):
                continue
            iid = "it:" + hashlib.md5(
                f"zone|{_wid()}|{bid}|{z['id']}|{i}|{o['name']}".encode()).hexdigest()[:10]
            if not _store().get_item(iid):
                it = item_normalize(o)
                it["id"] = iid
                it["fixed"] = bool(o.get("fixed"))    # zone roles travel with item
                it["afford"] = dict(o.get("afford") or {})
                _store().save_item(it)
            _store().inv_add(_wid(), iid, holder=holder)


def _zone_stock(bid: str, zid: str) -> list[tuple[str, dict]]:
    """What currently sits in zone (after all thefts/pickups)—[(item_id, factsheet)]."""
    out = []
    for r in _store().inventory(_wid(), _zone_holder(bid, zid)):
        it = _store().get_item(r["item_id"])
        if it:
            out.append((r["item_id"], it))
    return out


def _put_item(
    seed: str,
    name: str,
    kind: str,
    *,
    tier: str = "modest",
    note: str = "",
    mods=None,
    holder: str = "pc",
) -> str:
    """Mechanical forging of item from persona/factsheet tag (no LLM—flavor already authored)
    + place for holder. Idempotent by seed."""
    iid = "it:" + hashlib.md5(seed.encode()).hexdigest()[:10]
    if not _store().get_item(iid):
        w = _TIER_W.get(tier, 3)
        it = item_normalize(
            {
                "kind": kind,
                "name": name,
                "quality": _TIER_Q.get(tier, "plain"),
                "worth": w,
                "apparent_worth": w,
                "tags": [note] if note else [],
                "mods": mods or [],
            }
        )
        it["id"] = iid
        _store().save_item(it)
    _store().inv_add(_wid(), iid, holder=holder)
    return iid


def _materialize_npc(pid: str, layer: str = "visible") -> None:
    """NPC inventory from persona → real items, BY LAYER: visible (gear+keys—visible to eye)
    on first touch; pockets (pockets/valuables/coins)—on theft/search."""
    p = (_S.get("people") or {}).get(pid)
    if not p or _store().flag_get(_wid(), f"mat|{pid}|{layer}"):
        return
    per = p.persona or {}
    if layer == "visible":
        g = per.get("gear") or {}
        for slot, kind in (
            ("weapon", "weapon"),
            ("offhand", "misc"),
            ("armor", "armor"),
            ("garb", "armor"),
        ):
            it = g.get(slot)
            if it:
                _put_item(
                    f"npcinv|{pid}|{slot}",
                    it["name"],
                    kind,
                    tier=it.get("tier", "modest"),
                    note=it.get("note", ""),
                    holder=pid,
                )
        for i, t in enumerate((g.get("trinkets") or [])[:3]):
            _put_item(
                f"npcinv|{pid}|tr{i}",
                t["name"],
                "trinket",
                tier=t.get("tier", "modest"),
                note=t.get("note", ""),
                holder=pid,
            )
        for k in p.keys or []:  # owner keys—REAL items
            _put_item(
                f"npcinv|{pid}|key|{k['opens']}",
                k["name"],
                "key",
                tier="plain",
                note=f"открывает: {k['opens']}",
                mods=[
                    {
                        "target": "special:opens",
                        "op": "grant",
                        "amount": 1,
                        "when": "passive",
                        "cond": k["opens"],
                    }
                ],
                holder=pid,
            )
    else:  # pockets
        c = per.get("carry") or {}
        for i, s in enumerate((c.get("goods") or [])[:3]):
            _put_item(f"npcinv|{pid}|g{i}", s, "misc", tier="modest", holder=pid)
        for i, s in enumerate((c.get("personal") or [])[:3]):
            _put_item(f"npcinv|{pid}|p{i}", s, "misc", tier="poor", holder=pid)
        for i, s in enumerate((per.get("valuables") or [])[:3]):
            _put_item(f"npcinv|{pid}|v{i}", s, "valuable", tier="fine", holder=pid)
        _store().purse_add(
            _wid(), pid, int(c.get("coins") or 0) + (PB["merchant_float"] if p.work else 0)
        )
    _store().flag_set(_wid(), f"mat|{pid}|{layer}")  # worker—trade float


def _pc_coins() -> int:
    """Player purse (real). First access—12 coins starting (as in UI header)."""
    if not _store().flag_get(_wid(), "purse_init|pc"):
        _store().purse_add(_wid(), "pc", PB["start_coins"])
        _store().flag_set(_wid(), "purse_init|pc")
    return _store().purse_get(_wid(), "pc")


def _npc_sees(it: dict, cap: Capability, observer: str) -> dict:
    """What MERCHANT sees in item: their eye (competencies/rolls) reveals its gates.
    Knowledge asymmetry: they may see sapphire you don't—and vice versa."""
    res = item_inspect(it, cap, "expert", observer=observer)
    return item_view(it, {h["prop"] for h in res["revealed"]})


def _pc_key_for(cont_name: str) -> dict | None:
    """Key in player bag that opens this container (mod special:opens with cond=name)."""
    for r in _store().inventory(_wid(), "pc"):
        it = _store().get_item(r["item_id"])
        if (
            it
            and it["kind"] == "key"
            and any(
                m["target"] == "special:opens" and m.get("cond") == cont_name
                for m in it.get("mods", [])
            )
        ):
            return it
    return None


def _forge(seed: str, kind: str, name_hint: str, source: str, band: str = "plain") -> dict:
    """Lazy item forging (cache by id per seed)—string → factsheet with surface/hidden."""
    iid = "it:" + hashlib.md5(seed.encode()).hexdigest()[:10]
    ex = _store().get_item(iid)
    if ex:
        return ex
    ctx = ItemCtx(kind=kind, name_hint=name_hint, source=source, quality_band=band)
    it = _smith().forge(ctx)  # LLM errors surface honestly
    it["id"] = iid
    _store().save_item(it)
    return it


def _item_card(it: dict, known) -> dict:
    v = item_view(it, known)
    v["id"] = it["id"]
    v["condition"] = item_condition(it)
    v["make"] = it.get("make")
    v["rarity"] = it.get("rarity", "common")  # rarity axis for UI/price
    return v


_CRAFT = ROLE_RECIPES  # recipes—item system data


def _known(iid: str) -> set:
    return next((set(r["known"]) for r in _store().inventory(_wid()) if r["item_id"] == iid), set())
