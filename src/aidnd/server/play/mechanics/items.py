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

from aidnd.items import Capability, ItemCtx, LLMSmith, loot_pool
from aidnd.items import condition as item_condition
from aidnd.items import inspect as item_inspect
from aidnd.items import normalize as item_normalize
from aidnd.items import view as item_view
from aidnd.items.craft import ROLE_RECIPES
from aidnd.server.play.engine.core import (
    _PC_CAP,
    _S,
    PB,
    _binfo,
    _gt_add,
    _model,
    _mt,
    _store,
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
# itemgraph process → the station it needs (processes not listed can be done anywhere)
_PROC_STATION = {
    "ковка": "anvil", "заточка": "anvil", "правка": "anvil",
    "плавка": "forge", "легирование": "forge", "закалка": "forge",
    "дубление": "tannery", "отвар": "cauldron", "выпечка": "cauldron",
    "крой": "bench", "резьба": "bench", "сборка": "bench", "распил": "bench",
    "прядение": "bench", "ткачество": "bench", "оправа": "bench",
}


def _craft_band(spark: float) -> str:
    """spark → outcome band (pure). waste | crude(flaw) | plain | fine | exquisite(masterwork)."""
    if spark < PB["craft_waste"]:
        return "waste"
    if spark < PB["craft_flaw"]:
        return "crude"
    if spark < PB["craft_clean"]:
        return "plain"
    if spark < PB["craft_fine"]:
        return "fine"
    return "exquisite"


def _flaw_attrs(attrs: dict) -> dict:
    """Bake a HIDDEN crack: surface прочность intact, true prochnost dropped (revealed by craft_eye)."""
    pr = attrs.get("прочность")
    if pr:
        pr["true"] = max(1, int(round(pr["true"] * PB["craft_flaw_mul"])))
    else:
        attrs["прочность"] = {"surface": 35, "true": 10}
    return attrs


def _mw_attrs(attrs: dict) -> dict:
    """Masterwork: bump the strongest attribute (surface+true)."""
    if attrs:
        best = max(attrs, key=lambda a: attrs[a]["true"])
        for k in ("surface", "true"):
            attrs[best][k] = min(100, attrs[best][k] + PB["craft_masterwork_bonus"])
    return attrs


def _put_graph_item(node_id: str, quality: str = "plain", *, flaw: bool = False,
                    masterwork: bool = False, holder: str = "pc", seed: str | None = None) -> str:
    """Materialize an itemgraph node into a REAL attribute-bearing item in a holder's inventory."""
    from aidnd.items import derive_effects
    from aidnd.items.graph import node_item

    it = item_normalize(node_item(node_id, quality))
    if flaw:
        _flaw_attrs(it["attrs"])
    if masterwork:
        _mw_attrs(it["attrs"])
    worth = derive_effects(it)["worth"]                    # store a real worth (combat/trade read it)
    it["worth"] = worth
    it["apparent_worth"] = worth
    it["tags"] = (it.get("tags") or []) + (["искусной работы"] if masterwork else ["своей работы"])
    it["id"] = "it:" + hashlib.md5((seed or f"craft|{node_id}|{_mt()}").encode()).hexdigest()[:10]
    _store().save_item(it)
    _store().inv_add(_wid(), it["id"], holder=holder)
    return it["id"]


def _do_craft(detail: str, out: dict) -> dict:
    """Craft on the DERIVATION GRAPH via the SPARK LADDER. Resolve the target node, gather its direct
    inputs from the bag, roll spark = base + mastery + material + luck + inspiration + d20, and band it:
    waste (inputs lost) / crude+hidden-crack / plain / fine / exquisite masterwork. Forges a real
    attribute-bearing item — so it lands with combat/trade stats immediately."""
    from aidnd.items.graph import item_graph, node_attrs, node_lookup
    from aidnd.server.play.engine.pc.luck import _pc_inspiration, _pc_luck

    g = item_graph()
    want = node_lookup(detail)
    if not want or want not in g["nodes"]:
        out["narr"].append("Не пойму, что смастерить — назови вещь (клинок, лук, доспех, отвар…).")
        return out
    node = g["nodes"][want]
    need = node.get("from", [])
    inv = [(r["item_id"], _store().get_item(r["item_id"])) for r in _store().inventory(_wid(), "pc")]
    matched, used = {}, set()
    for inp in need:                                       # each input → a distinct held item
        iid = next((i for i, itm in inv
                    if itm and i not in used and node_lookup(itm["name"]) == inp), None)
        if iid:
            matched[inp] = iid
            used.add(iid)
    miss = [inp for inp in need if inp not in matched]
    if miss:
        out["narr"].append("Не хватает для работы: " + ", ".join(miss) + ".")
        return out
    inside = _S.get("inside")
    if not inside:
        out["narr"].append("Тут не смастеришь — зайди в мастерскую/кузницу.")
        return out
    place = _PROC_STATION.get(node.get("process", ""))     # gate: right station for this process
    if place:
        btok = (lambda b: (b["name"] + " " + b["kind"]).lower())(_binfo(inside))
        if not any(h in btok for h in STATION_HINTS.get(place, ())):
            out["narr"].append(f"Для такой работы нужен {STATION_RU.get(place, place)} — тут его нет.")
            return out
    scores = [max(node_attrs(inp).values(), default=0) for inp in need]
    material = (sum(scores) / len(scores)) * PB["craft_material_k"] if scores else 0.0
    mastery = max(_PC_CAP.mod("dex"), _PC_CAP.mod("int"))
    roll = random.Random(f"craft|{want}|{_mt()}").randint(1, 20)
    spark = PB["craft_base"] + mastery + material + _pc_luck() + _pc_inspiration() + roll
    band = _craft_band(spark)
    _gt_add(PB["craft_time"])
    for i in matched.values():                             # inputs are always consumed
        _store().inv_drop(_wid(), i)
    if band == "waste":
        out["narr"].append("Работа загублена — материал испорчен, впустую.")
        out["refresh"] = True
        return out
    made = _put_graph_item(want, band, flaw=(band == "crude"), masterwork=(band == "exquisite"))
    _pool_add_new(_store().get_item(made))
    qru = {"crude": "грубо", "plain": "просто", "fine": "добротно", "exquisite": "искусно"}[band]
    tail = " — истинный шедевр!" if band == "exquisite" else "."
    out["narr"].append(f"Ты мастеришь «{node.get('name', want)}» — вышло {qru}{tail}")
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
