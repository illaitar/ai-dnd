"""Entity-Component store (main §3.1).

Сущность — голый id. Компоненты хранятся в таблицах по типу. Системы итерируют
по компонентам. Это материализованная проекция (CQRS, док 08 §4), перестраиваемая
из event log.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TypeVar

T = TypeVar("T")


class ECS:
    def __init__(self) -> None:
        # component_type_name -> {entity_id -> component}
        self._tables: dict[str, dict[str, object]] = {}
        # dict, а не set: порядок вставки стабилен и не зависит от PYTHONHASHSEED —
        # детерминированная итерация сущностей (важно для LOD-капа, «наблюдателя» и т.п.)
        self._entities: dict[str, None] = {}

    def spawn(self, eid: str) -> str:
        self._entities.setdefault(eid, None)
        return eid

    def exists(self, eid: str) -> bool:
        return eid in self._entities

    def add(self, eid: str, component: object) -> None:
        self._entities.setdefault(eid, None)
        self._tables.setdefault(type(component).__name__, {})[eid] = component

    def get(self, eid: str, ctype: type[T]) -> T | None:
        return self._tables.get(ctype.__name__, {}).get(eid)  # type: ignore[return-value]

    def has(self, eid: str, ctype: type[T]) -> bool:
        return eid in self._tables.get(ctype.__name__, {})

    def remove(self, eid: str, ctype: type[T]) -> None:
        self._tables.get(ctype.__name__, {}).pop(eid, None)

    def remove_entity(self, eid: str) -> None:
        self._entities.pop(eid, None)
        for table in self._tables.values():
            table.pop(eid, None)

    def with_component(self, ctype: type[T]) -> Iterator[tuple[str, T]]:
        yield from list(self._tables.get(ctype.__name__, {}).items())  # type: ignore[misc]

    def entities(self) -> list[str]:
        return list(self._entities)

    def components_of(self, eid: str) -> dict[str, object]:
        return {
            name: table[eid]
            for name, table in self._tables.items()
            if eid in table
        }
