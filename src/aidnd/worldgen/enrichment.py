"""Слой насыщения локаций — ОТДЕЛЬНЫЙ от графа. Ссылается на узлы графа по id, граф НЕ мутирует
(под-помещения от LLM живут как данные с родителем-зданием; материализация в граф-узлы — шаг
склейки контуров позже). Оркестратор гонит описания батчами (макс. одновременных промптов).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .enrich_llm import BuildingCtx, Enricher
from .progress import Progress

# стартовые подсказки типов значимых зданий (LLM сочиняет дальше); и по ориентиру для домов
_SIGNIFICANT = ["Таверна", "Лавка", "Кузница", "Храм удачи", "Усадьба", "Склад",
                "Мастерская", "Дом старосты", "Гильдия", "Конюшня", "Пекарня", "Целебница"]
_BY_LANDMARK = {"river": "Дом у реки", "wall": "Дом у стены",
                "gate": "Сторожка у ворот", "bridge": "Дом у моста"}


@dataclass
class Building:
    id: str
    node: int
    name: str
    description: str
    sub_rooms: list = field(default_factory=list)


@dataclass
class Enrichment:
    """Контент поверх графа: id здания → описание + доп-помещения."""
    buildings: dict = field(default_factory=dict)
    progress: dict = field(default_factory=dict)
    scope: str = "keys"

    def add(self, bid: str, node: int, res: dict) -> None:
        self.buildings[bid] = Building(id=bid, node=node, name=(res.get("name") or bid),
                                       description=res.get("description", ""),
                                       sub_rooms=res.get("sub_rooms", []))

    def to_dict(self) -> dict:
        return {"scope": self.scope, "progress": self.progress,
                "buildings": {b: {"node": x.node, "name": x.name, "description": x.description,
                                  "sub_rooms": x.sub_rooms} for b, x in self.buildings.items()}}


def _name_hint(is_key: bool, idx: int, landmarks: list[str]) -> str:
    if is_key:
        return _SIGNIFICANT[idx % len(_SIGNIFICANT)]
    for lm in landmarks:
        if lm in _BY_LANDMARK:
            return _BY_LANDMARK[lm]
    return "Дом горожанина"


def _targets(city, scope: str) -> list[tuple]:
    """[(id, is_key, node)] зданий для насыщения. keys — только ключевые; all — + все дома."""
    out = [(bid, True, kb.interior) for bid, kb in city.key_buildings.items()]
    if scope == "all":
        out += [(hid, False, ho.node) for hid, ho in city.houses.items() if not ho.building]
    return out


def enrich_city(city, scope: str, enricher: Enricher, max_concurrent: int = 8,
                on_progress=None) -> Enrichment:
    """Насытить локации города. scope: 'keys' (только ключевые) | 'all' (каждое здание).
    Гонит до max_concurrent описаний одновременно; прогресс — здания/батчи."""
    targets = _targets(city, scope)
    prog = Progress(len(targets), max_concurrent, on_update=on_progress)
    enr = Enrichment(scope=scope)

    def work(item):
        idx, (bid, is_key, node) = item
        landmarks = city._landmarks_at(node) if node in city._xy else []   # геом-факты карты
        ctx = BuildingCtx(id=bid, name_hint=_name_hint(is_key, idx, landmarks),
                          role_hint=("значимое здание небольшого городка" if is_key
                                     else "жилой дом горожанина"),
                          landmarks=landmarks)
        return bid, node, enricher.describe(ctx)

    with ThreadPoolExecutor(max_workers=max(1, max_concurrent)) as ex:
        futs = [ex.submit(work, it) for it in enumerate(targets)]
        for fut in as_completed(futs):
            bid, node, res = fut.result()
            if res:
                enr.add(bid, node, res)
            prog.tick(1)
    enr.progress = prog.snapshot()
    return enr
