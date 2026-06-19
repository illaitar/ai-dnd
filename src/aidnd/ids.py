"""Конвенция идентификаторов (00_Index §4).

Единое правило неймспейсинга: <тип>:<имя>. id уникален и стабилен на всё время
жизни мира — сущность рождается с id и сохраняет его навсегда (нужно для event
log, KG и провенанса).
"""

from __future__ import annotations

import re

# Префиксы типов из 00_Index §4.
PREFIXES = {
    "entity",     # родовая сущность
    "npc",        # неигровой персонаж
    "pc",         # игровой персонаж
    "it",         # инстанс предмета
    "tmpl",       # шаблон предмета (flyweight)
    "srd",        # ссылка на SRD-контент (стат-блок, заклинание)
    "place",      # локация, регион, сцена
    "building",   # здание
    "room",       # комната
    "container",  # контейнер (сундук, труп, лавка, земля)
    "faction",    # фракция
    "quest",      # квест
    "household",  # домохозяйство
    "item",       # именной авторский предмет
    "shop",       # лавка (контейнер с ценовой политикой)
    "district",   # район поселения
    "corpse",     # труп как контейнер
    "carry",      # инвентарь переноски персонажа
    "wallet",     # кошелёк
}

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def slug(text: str) -> str:
    """Нормализует произвольную строку в стабильный slug для id."""
    return _SLUG_RE.sub("_", text.strip().lower()).strip("_")


def make(prefix: str, name: str) -> str:
    """Собирает id вида prefix:name."""
    if prefix not in PREFIXES:
        raise ValueError(f"неизвестный префикс id: {prefix!r}")
    return f"{prefix}:{slug(name)}"


def kind_of(eid: str) -> str:
    """Возвращает префикс типа из id (часть до двоеточия)."""
    return eid.split(":", 1)[0] if ":" in eid else "entity"


def name_of(eid: str) -> str:
    """Возвращает имя из id (часть после двоеточия)."""
    return eid.split(":", 1)[1] if ":" in eid else eid


def is_pc(eid: str) -> bool:
    return kind_of(eid) == "pc"


def is_npc(eid: str) -> bool:
    return kind_of(eid) == "npc"
