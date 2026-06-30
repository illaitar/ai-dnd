"""Слой насыщения локаций — ОТДЕЛЬНЫЙ от графа. Ссылается на узлы по id, граф НЕ мутирует.

Двухфазно: (1) насыщаем здания батчами — каждое объявляет доп-помещения СТАБАМИ; (2) собираем все
стабы в очередь и генерируем суб-помещения ДРУГИМ промптом с контекстом их здания. У суб-помещений
своих суб-помещений нет. Прогресс — по фазам (здания, затем суб-помещения).
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
class SubRoom:
    name: str
    kind: str = ""          # cellar|backroom|attic|quarters|hidden
    access: str = "public"  # public|staff|locked|hidden
    contents: str = ""
    description: str = ""
    parent: str = ""        # id здания-родителя


@dataclass
class Building:
    id: str
    node: int
    name: str
    type: str = ""
    services: list = field(default_factory=list)
    keeper: dict | None = None
    notable: str = ""
    secret: dict | None = None
    description: str = ""
    sub_rooms: list = field(default_factory=list)   # list[SubRoom]


@dataclass
class Enrichment:
    """Контент поверх графа: id здания → богатое описание + доп-помещения."""
    buildings: dict = field(default_factory=dict)
    progress: dict = field(default_factory=dict)
    scope: str = "keys"

    def add_building(self, bid: str, node: int, res: dict) -> None:
        subs = [SubRoom(name=s.get("name", ""), kind=s.get("kind", ""),
                        access=s.get("access", "public"), parent=bid)
                for s in (res.get("sub_rooms") or [])]
        self.buildings[bid] = Building(
            id=bid, node=node, name=(res.get("name") or bid), type=res.get("type", ""),
            services=list(res.get("services") or []), keeper=res.get("keeper"),
            notable=res.get("notable", ""), secret=res.get("secret"),
            description=res.get("description", ""), sub_rooms=subs)

    def to_dict(self) -> dict:
        return {"scope": self.scope, "progress": self.progress, "buildings": {
            b: {"node": x.node, "name": x.name, "type": x.type, "services": x.services,
                "keeper": x.keeper, "notable": x.notable, "secret": x.secret,
                "description": x.description,
                "sub_rooms": [{"name": s.name, "kind": s.kind, "access": s.access,
                               "contents": s.contents, "description": s.description}
                              for s in x.sub_rooms]}
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


def _run_batch(items, work, prog) -> None:
    with ThreadPoolExecutor(max_workers=prog.max_concurrent) as ex:
        for fut in as_completed([ex.submit(work, it) for it in items]):
            fut.result()
            prog.tick(1)


def enrich_city(city, scope: str, enricher: Enricher, max_concurrent: int = 8,
                on_progress=None) -> Enrichment:
    """Насытить локации города двухфазно. scope: 'keys' | 'all'."""
    targets = _targets(city, scope)
    enr = Enrichment(scope=scope)

    # ── фаза 1: здания (каждое объявляет суб-помещения стабами) ──────────────
    prog1 = Progress(len(targets), max_concurrent, on_progress, label="здания")

    def work_building(item):
        idx, (bid, is_key, node) = item
        landmarks = city._landmarks_at(node) if node in city._xy else []
        ctx = BuildingCtx(id=bid, name_hint=_name_hint(is_key, idx, landmarks),
                          role_hint=("значимое здание небольшого городка" if is_key
                                     else "жилой дом горожанина"),
                          landmarks=landmarks)
        res = enricher.describe_building(ctx)
        if res:
            enr.add_building(bid, node, res)

    _run_batch(list(enumerate(targets)), work_building, prog1)

    # ── фаза 2: суб-помещения в очереди (другой промпт + контекст здания) ────
    queue = [(b, sr) for b in enr.buildings.values() for sr in b.sub_rooms]
    prog2 = Progress(len(queue), max_concurrent, on_progress, label="суб-помещения")

    def work_subroom(item):
        b, sr = item
        parent = {"name": b.name, "type": b.type, "description": b.description}
        res = enricher.describe_subroom(parent, {"name": sr.name, "kind": sr.kind, "access": sr.access})
        if res:
            sr.contents = res.get("contents", "")
            sr.description = res.get("description", "")

    if queue:
        _run_batch(queue, work_subroom, prog2)

    enr.progress = {"buildings": prog1.snapshot(),
                    "subrooms": prog2.snapshot() if queue else None}
    return enr
