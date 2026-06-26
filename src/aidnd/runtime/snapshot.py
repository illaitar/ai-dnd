"""Снапшот изменчивого/обогащённого состояния мира — «БД поверх детерминированного бейзлайна».

build_world(seed,…) даёт детерминированный костяк; снапшот хранит то, что им НЕ воспроизводится:
сгенерированные на старте шаблоны предметов, предметы/контейнеры/кошельки (авторитетно), обогащение
персон (имя/голос/черты/секреты…) и эпизодическую память NPC. На загрузке накладывается поверх
реконструкции (build_world + реплей хвоста), делая сейв самодостаточным снимком мира."""

from __future__ import annotations

import dataclasses

from ..cognition.memory import MemoryNode, NPCMemory
from ..gen.provenance import Provenance
from ..inventory.container import Container
from ..inventory.items import ItemInstance, ItemTemplate
from ..world.components import Persona

# поля персоны, которые наполняет обогащение (остальное — детерминированный бейзлайн build_world)
_PERSONA_FIELDS = ("name", "traits", "voice", "appearance", "ideal", "bond", "flaw",
                   "epithet", "aliases", "knowledge", "secrets", "marks", "enriched")


def _d(obj):
    return dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj


def capture(session) -> dict:
    """Снять полный снимок обогащённого/изменчивого состояния (для сейва)."""
    w = session.world
    return {
        "templates": {tid: _d(t) for tid, t in w.templates.items() if str(tid).startswith("tmpl:gen_")},
        "items": {iid: _d(i) for iid, i in w.items.items()},
        "containers": {cid: _d(c) for cid, c in w.containers.items()},
        "wallets": {k: dict(v) for k, v in w.wallets.items()},
        "item_seq": getattr(w, "_item_seq", 0),
        "personas": {nid: {f: getattr(p, f) for f in _PERSONA_FIELDS}
                     for nid in w.npcs() if (p := w.ecs.get(nid, Persona))},
        "memory": _capture_memory(session),
        "incidents": _capture_incidents(session),
        "quest_briefs": dict(getattr(session, "_quest_briefs", {}) or {}),
    }


def _capture_incidents(session) -> dict | None:
    """Расписание инцидентов + уже сработавшие id — чтобы на лоаде не пересоздать окно и
    не выстрелить повторно (без этого _inc_fired сбрасывается → дабл-фаер)."""
    sched = getattr(session, "_inc_sched", None)
    if sched is None:
        return None
    return {"sched": [dataclasses.asdict(s) for s in sched],
            "horizon": getattr(session, "_inc_horizon", -1),
            "fired": list(getattr(session, "_inc_fired", set()) or [])}


def _capture_memory(session) -> dict:
    store = getattr(session, "cog_store", None)
    if store is None:
        return {}
    out = {}
    for nid, mem in store._mem.items():
        nodes = [{k: v for k, v in _d(n).items() if k != "_embed"} for n in mem.nodes.values()]
        out[nid] = {"nodes": nodes, "semantic": dict(mem.semantic), "counter": mem._counter}
    return out


# --------------------------------------------------- реконструкция датаклассов --
def _prov(d):
    if not d:
        return None
    return Provenance(source=d.get("source", "pregen"), generator=d.get("generator", "manual@1.0"),
                      seed=d.get("seed", 0), tick=d.get("tick", 0),
                      satisfied=list(d.get("satisfied") or []), parent_ctx=d.get("parent_ctx"))


def _template(d) -> ItemTemplate:
    return ItemTemplate(template_id=d["template_id"], name=d["name"], category=d["category"],
                        base_stats=dict(d.get("base_stats") or {}), weight=d.get("weight", 0.0),
                        base_value=d.get("base_value", 0), rarity=d.get("rarity", "mundane"),
                        attunement=d.get("attunement", False), stackable=d.get("stackable", False),
                        max_stack=d.get("max_stack", 1), tags=tuple(d.get("tags") or ()))


def _instance(d) -> ItemInstance:
    return ItemInstance(instance_id=d["instance_id"], template_id=d["template_id"],
                        owner_ref=d.get("owner_ref"), location_ref=d.get("location_ref", ""),
                        quantity=d.get("quantity", 1), charges=d.get("charges"),
                        durability=d.get("durability"), identified=d.get("identified", True),
                        custom_name=d.get("custom_name"), description=d.get("description"),
                        mods=dict(d.get("mods") or {}), affixes=list(d.get("affixes") or []),
                        equipped_slot=d.get("equipped_slot"), provenance=_prov(d.get("provenance")))


def _container(d) -> Container:
    return Container(container_id=d["container_id"], owner_ref=d.get("owner_ref"),
                     kind=d.get("kind", "carry"), capacity_slots=d.get("capacity_slots"),
                     capacity_weight=d.get("capacity_weight"), items=list(d.get("items") or []),
                     locked=d.get("locked", False), trapped=d.get("trapped"),
                     buy_rate=d.get("buy_rate", 0.5), deals_in=tuple(d.get("deals_in") or ()))


def apply(session, snap: dict | None) -> None:
    """Наложить снапшот на собранный мир: шаблоны/предметы/контейнеры/кошельки — авторитетно
    заменяем; персоны — оверлей обогащения; память — восстанавливаем."""
    if not snap:
        return
    w = session.world
    for tid, d in (snap.get("templates") or {}).items():
        w.templates[tid] = _template(d)
    if snap.get("items") is not None:
        w.items = {iid: _instance(d) for iid, d in snap["items"].items()}
    if snap.get("containers") is not None:
        w.containers = {cid: _container(d) for cid, d in snap["containers"].items()}
    if snap.get("wallets") is not None:
        w.wallets = {k: dict(v) for k, v in snap["wallets"].items()}
    if "item_seq" in snap:
        w._item_seq = max(getattr(w, "_item_seq", 0), int(snap["item_seq"]))
    for nid, fields in (snap.get("personas") or {}).items():
        p = w.ecs.get(nid, Persona)
        if p:
            for f, v in (fields or {}).items():
                setattr(p, f, v)
    _restore_memory(session, snap.get("memory"))
    inc = snap.get("incidents")
    if inc is not None:                                  # восстановить расписание инцидентов (анти-redouble)
        from .incidents import Spawn
        session._inc_sched = [Spawn(**s) for s in (inc.get("sched") or [])]
        session._inc_horizon = inc.get("horizon", -1)
        session._inc_fired = set(inc.get("fired") or [])
    session._quest_briefs = dict(snap.get("quest_briefs") or {})   # сген. лор-брифы квестов


def _restore_memory(session, mem_snap) -> None:
    store = getattr(session, "cog_store", None)
    if store is None or not mem_snap:
        return
    for nid, m in mem_snap.items():
        npc_mem = NPCMemory(nid)
        for nd in m.get("nodes") or []:
            node = MemoryNode(node_id=nd["node_id"], text=nd["text"], t=nd.get("t", 0),
                              importance=nd.get("importance", 5), kind=nd.get("kind", "observation"),
                              access_count=nd.get("access_count", 0),
                              evidence_ids=list(nd.get("evidence_ids") or []))
            npc_mem.nodes[node.node_id] = node
        npc_mem.semantic = dict(m.get("semantic") or {})
        npc_mem._counter = m.get("counter", len(npc_mem.nodes))
        store._mem[nid] = npc_mem
