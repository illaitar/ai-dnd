"""World — источник истины (main §3, док 08 §4 CQRS).

Модель записи — event log. Модель чтения — проекции: ECS (компоненты), KG
(триплеты), пространственный индекс, реестры предметов/контейнеров/квестов.

Путь записи: world.commit(verb, ...) → append события в лог → apply() мутирует
проекции. Replay: восстановить пре-ген из сида, затем apply() каждый рантайм-
event. Пре-ген детерминирован от WORLD_SEED, поэтому в лог не пишется (док 01 §4).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from .. import config
from .components import LODState, Position, Relationships, RelEdge, Stats5e
from .ecs import ECS
from .events import Event, EventLog, RollRecord
from .kg import KnowledgeGraph
from .spatial import SpatialIndex

if TYPE_CHECKING:  # избегаем циклических импортов
    from ..inventory.container import Container
    from ..inventory.items import ItemInstance, ItemTemplate


class Clock:
    """Модель симуляционного времени (док 08 §8). 1 тик = SIM_MINUTES_PER_TICK мин."""

    def __init__(self, tick: int = 0) -> None:
        self.tick = tick

    def advance(self, dt_ticks: int = 1) -> int:
        self.tick += dt_ticks
        return self.tick

    def time_of_day(self) -> str:
        minutes = (self.tick * config.SIM_MINUTES_PER_TICK) % (24 * 60)
        h = minutes // 60
        if 5 <= h < 12:
            return "morning"
        if 12 <= h < 18:
            return "day"
        if 18 <= h < 22:
            return "evening"
        return "night"

    def hhmm(self) -> str:
        minutes = (self.tick * config.SIM_MINUTES_PER_TICK) % (24 * 60)
        return f"{minutes // 60:02d}:{minutes % 60:02d}"


class World:
    def __init__(self, seed: int = config.WORLD_SEED) -> None:
        self.seed = seed
        self.ecs = ECS()
        self.kg = KnowledgeGraph()
        self.log = EventLog()
        self.spatial = SpatialIndex()
        self.clock = Clock()

        # реестры предметного слоя (док 03/04)
        self.templates: dict[str, ItemTemplate] = {}
        self.items: dict[str, ItemInstance] = {}
        self.containers: dict[str, Container] = {}
        self.wallets: dict[str, dict[str, int]] = {}     # entity_id -> {cp,sp,..}

        # прочее состояние мира
        self.quests: dict[str, object] = {}
        self.factions: dict[str, object] = {}
        self.flags: set[str] = set()
        self.resolutions: dict[str, dict] = {}           # зафиксированные факты доразрешения сцены
        self.player_maps: dict[str, dict] = {}           # карта в голове игрока (может врать)
        self.name_registry: set[str] = set()
        self.conditions: dict[str, list] = {}            # entity_id -> [Condition]
        self.player_id: str | None = None
        self._item_seq = 0                               # per-world счётчик id предметов

        self._subscribers: list = []                     # коллбэки on_event (квесты)

    def next_item_id(self, template_id: str) -> str:
        """Детерминированный per-world id инстанса (не зависит от других миров)."""
        self._item_seq += 1
        base = template_id.split(":", 1)[-1]
        return f"it:{base}_{self._item_seq}"

    # ----------------------------------------------------------------- API --
    def subscribe(self, cb) -> None:
        self._subscribers.append(cb)

    def commit(
        self, verb: str, actor: str, target: str | None = None,
        payload: dict | None = None, roll: RollRecord | None = None,
    ) -> Event:
        """Записать событие и применить его к проекциям (единственный писатель)."""
        ev = Event(self.clock.tick, actor, verb, target, payload or {}, roll)
        self.log.append(ev)
        self.apply(ev)
        for cb in self._subscribers:
            cb(ev, self)
        return ev

    def apply(self, ev: Event) -> None:
        """Мутировать проекции по событию (CQRS write path, реиспользуется в replay)."""
        handler = getattr(self, f"_h_{ev.verb}", None)
        if handler:
            handler(ev)

    # ----------------------------------------------- обработчики мутаций ----
    def _h_kg_add(self, ev: Event) -> None:
        p = ev.payload
        self.kg.add(p["s"], p["r"], p["o"])

    def _h_kg_remove(self, ev: Event) -> None:
        p = ev.payload
        self.kg.remove(p["s"], p["r"], p["o"])

    def _h_kg_set(self, ev: Event) -> None:
        """Функциональная связь: снять все subject-relation-* и поставить одну."""
        p = ev.payload
        self.kg.remove_where(p["s"], p["r"])
        self.kg.add(p["s"], p["r"], p["o"])

    def _h_set_hp(self, ev: Event) -> None:
        st = self.ecs.get(ev.target, Stats5e)
        if st:
            if "hp" in ev.payload:
                st.hp = ev.payload["hp"]
            if "temp_hp" in ev.payload:
                st.temp_hp = ev.payload["temp_hp"]

    def _h_damage(self, ev: Event) -> None:
        st = self.ecs.get(ev.target, Stats5e)
        if not st:
            return
        dmg = ev.payload.get("amount", 0)
        if st.temp_hp > 0:
            absorbed = min(st.temp_hp, dmg)
            st.temp_hp -= absorbed
            dmg -= absorbed
        st.hp = max(0, st.hp - dmg)

    def _h_heal(self, ev: Event) -> None:
        st = self.ecs.get(ev.target, Stats5e)
        if st:
            st.hp = min(st.max_hp, st.hp + ev.payload.get("amount", 0))

    def _h_set_position(self, ev: Event) -> None:
        p = ev.payload
        pos = self.ecs.get(ev.target, Position)
        if not pos:
            pos = Position(region_id=p.get("region", "region:phandalin"))
            self.ecs.add(ev.target, pos)
        if "region" in p:
            pos.region_id = p["region"]
        if "place" in p:
            pos.place_id = p["place"]
        if pos.place_id:
            self.spatial.update_position(ev.target, pos.place_id)

    def _h_set_lod(self, ev: Event) -> None:
        lod = self.ecs.get(ev.target, LODState)
        if lod:
            lod.tier = ev.payload["tier"]
            if ev.payload["tier"] >= 3:
                lod.last_promoted_tick = self.clock.tick
            lod.last_active_tick = self.clock.tick

    def _h_rel_update(self, ev: Event) -> None:
        p = ev.payload
        npc, tgt = p["npc"], p["target"]
        rels = self.ecs.get(npc, Relationships)
        if rels is None:
            rels = Relationships()
            self.ecs.add(npc, rels)
        edge = rels.edges.setdefault(tgt, RelEdge())
        for k in ("affinity", "trust", "fear", "respect"):
            if k in p:
                setattr(edge, k, getattr(edge, k) + p[k])
        for tag in p.get("tags", []):
            if tag not in edge.tags:
                edge.tags.append(tag)
        edge.clamp()

    def _h_item_move(self, ev: Event) -> None:
        p = ev.payload
        src = self.containers.get(p["from"])
        dst = self.containers.get(p["to"])
        inst_id = p["instance"]
        if src and inst_id in src.items:
            src.items.remove(inst_id)
        if dst and inst_id not in dst.items:
            dst.items.append(inst_id)
        inst = self.items.get(inst_id)
        if inst and dst:
            inst.location_ref = dst.container_id

    def _h_item_remove(self, ev: Event) -> None:
        c = self.containers.get(ev.payload["container"])
        iid = ev.payload["instance"]
        if c and iid in c.items:
            c.items.remove(iid)
        if ev.payload.get("destroy"):
            self.items.pop(iid, None)

    def _h_currency_transfer(self, ev: Event) -> None:
        p = ev.payload
        frm, to = p.get("from"), p.get("to")
        for coin, amt in p.get("coins", {}).items():
            if frm:
                w = self.wallets.setdefault(frm, {})
                w[coin] = w.get(coin, 0) - amt
            if to:
                w = self.wallets.setdefault(to, {})
                w[coin] = w.get(coin, 0) + amt

    def _h_equip(self, ev: Event) -> None:
        p = ev.payload
        inst = self.items.get(p["instance"])
        if inst:
            # снять чужой предмет с того же слота
            for other in self.items.values():
                if other.owner_ref == p["character"] and other.equipped_slot == p["slot"]:
                    other.equipped_slot = None
            inst.equipped_slot = p["slot"]
            inst.owner_ref = p["character"]

    def _h_unequip(self, ev: Event) -> None:
        inst = self.items.get(ev.payload["instance"])
        if inst:
            inst.equipped_slot = None

    def _h_set_flag(self, ev: Event) -> None:
        self.flags.add(ev.payload["flag"])

    def _h_resolve(self, ev: Event) -> None:
        """Фиксирует факт доразрешения сцены (eager persistence): повторный запрос
        по тому же ключу вернёт тот же ответ навсегда (main §2, док 06 §6)."""
        self.resolutions[ev.payload["key"]] = dict(ev.payload)

    def _h_map_update(self, ev: Event) -> None:
        """Добавляет/обновляет запись в карте игрока (может быть ложной/неполной)."""
        p = ev.payload
        belief = dict(p["belief"])
        self.player_maps.setdefault(p["player"], {})[belief["id"]] = belief

    def _h_map_verify(self, ev: Event) -> None:
        """Игрок проверил сведение на месте: подтверждение либо разоблачение лжи."""
        p = ev.payload
        beliefs = self.player_maps.get(p["player"], {})
        b = beliefs.get(p["belief_id"])
        if b:
            b["verified"] = True
            b["reliability"] = "true_revealed" if b.get("true") else "false_revealed"

    def _h_quest_state(self, ev: Event) -> None:
        q = self.quests.get(ev.target)
        if q is not None:
            q.state = ev.payload["state"]               # type: ignore[attr-defined]
            if "current_stages" in ev.payload:
                q.current_stages = ev.payload["current_stages"]  # type: ignore[attr-defined]

    # ----------------------------------------------------- запросы чтения ---
    def get_stats(self, eid: str) -> Stats5e | None:
        return self.ecs.get(eid, Stats5e)

    def position(self, eid: str) -> Position | None:
        return self.ecs.get(eid, Position)

    def wallet(self, eid: str) -> dict[str, int]:
        return self.wallets.setdefault(eid, {})

    def is_alive(self, eid: str) -> bool:
        st = self.ecs.get(eid, Stats5e)
        return st is None or st.hp > 0

    def npcs(self) -> list[str]:
        return [e for e in self.ecs.entities() if e.startswith("npc:")]

    # --------------------------------------------------- снапшоты/реплей ----
    def state_hash(self) -> str:
        """Детерминированный хеш состояния для golden-реплея (док 08 §12)."""
        h = hashlib.blake2b(digest_size=16)
        # KG
        for t in sorted(self.kg.all()):
            h.update(("|".join(t)).encode())
        # HP всех существ
        for eid in sorted(self.ecs.entities()):
            st = self.ecs.get(eid, Stats5e)
            if st:
                h.update(f"{eid}:{st.hp}:{st.temp_hp}".encode())
        # содержимое контейнеров
        for cid in sorted(self.containers):
            items = ",".join(sorted(self.containers[cid].items))
            h.update(f"{cid}:[{items}]".encode())
        # кошельки
        for wid in sorted(self.wallets):
            h.update(f"{wid}:{json.dumps(self.wallets[wid], sort_keys=True)}".encode())
        # флаги
        h.update(("flags:" + ",".join(sorted(self.flags))).encode())
        return h.hexdigest()
