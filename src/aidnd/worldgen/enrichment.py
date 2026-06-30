"""Слой насыщения локаций — ОТДЕЛЬНЫЙ от графа. Один вызов на здание → фактшит характеристик
(суб-помещения инлайн). Граф не мутирует. Результат можно сложить в БД миров (store) для дешёвого
переиспользования.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .enrich_llm import BuildingCtx, Enricher
from .progress import Progress

_SIGNIFICANT = ["Таверна", "Лавка", "Кузница", "Храм удачи", "Усадьба", "Склад",
                "Мастерская", "Дом старосты", "Гильдия", "Конюшня", "Пекарня", "Целебница"]
_BY_LANDMARK = {"river": "Дом у реки", "wall": "Дом у стены",
                "gate": "Сторожка у ворот", "bridge": "Дом у моста"}


@dataclass
class Building:
    id: str
    node: int
    is_key: bool
    sign: str | None
    data: dict = field(default_factory=dict)     # фактшит характеристик


@dataclass
class Enrichment:
    buildings: dict = field(default_factory=dict)
    progress: dict = field(default_factory=dict)
    scope: str = "keys"

    def add(self, bid: str, node: int, is_key: bool, sign: str | None, data: dict) -> None:
        self.buildings[bid] = Building(id=bid, node=node, is_key=is_key, sign=sign, data=data)

    def to_dict(self) -> dict:
        return {"scope": self.scope, "progress": self.progress, "buildings": {
            b: {"node": x.node, "is_key": x.is_key, "sign": x.sign, "data": x.data}
            for b, x in self.buildings.items()}}


def _name_hint(is_key: bool, idx: int, landmarks: list[str]) -> str:
    if is_key:
        return _SIGNIFICANT[idx % len(_SIGNIFICANT)]
    for lm in landmarks:
        if lm in _BY_LANDMARK:
            return _BY_LANDMARK[lm]
    return "Дом горожанина"


def _targets(city, scope: str) -> list[tuple]:
    out = [(bid, True, kb.interior) for bid, kb in city.key_buildings.items()]
    if scope == "all":
        out += [(hid, False, ho.node) for hid, ho in city.houses.items() if not ho.building]
    return out


def building_ctx(city, bid: str, is_key: bool, idx: int):
    """Контекст здания для енричера (имя-подсказка по типу/ориентиру + роль + ориентиры карты)."""
    node = city.key_buildings[bid].interior if is_key else city.houses[bid].node
    landmarks = city._landmarks_at(node) if node in city._xy else []   # noqa: SLF001
    return BuildingCtx(id=bid, name_hint=_name_hint(is_key, idx, landmarks),
                       role_hint=("значимое здание небольшого городка" if is_key else "жилой дом горожанина"),
                       landmarks=landmarks)


def enrich_city(city, scope: str, enricher: Enricher, max_concurrent: int = 8,
                on_progress=None) -> Enrichment:
    """Насытить локации фактшитами (одна фаза, в память). scope: 'keys' | 'all'."""
    targets = _targets(city, scope)
    prog = Progress(len(targets), max_concurrent, on_progress, label="здания")
    enr = Enrichment(scope=scope)

    def work(item):
        idx, (bid, is_key, node_) = item
        data = enricher.describe_building(building_ctx(city, bid, is_key, idx))
        if data:
            sign = city.key_buildings[bid].name if is_key else None
            enr.add(bid, node_, is_key, sign, data)

    with ThreadPoolExecutor(max_workers=max(1, max_concurrent)) as ex:
        for fut in as_completed([ex.submit(work, it) for it in enumerate(targets)]):
            fut.result()
            prog.tick(1)
    enr.progress = prog.snapshot()
    return enr


def store_world(store, world_id: int, city, enr: Enrichment) -> None:
    """Сложить насыщенный мир в БД (последовательно — без гонок SQLite)."""
    p = city.params
    store.upsert_world(world_id, p.seed, p.key_buildings, p.river, p.walls, p.segment)
    for x in enr.buildings.values():
        store.save_building(world_id, x.id, x.is_key, x.node, x.sign, x.data)
