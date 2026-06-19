"""Предметы: flyweight шаблон против инстанса (док 03 §2, док 04 §3-4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # избегаем цикла inventory→gen (gen зависит от inventory)
    from ..gen.provenance import Provenance

# Конверсия валюты 5e в медяки (док 04 §4).
COIN = {"cp": 1, "sp": 10, "ep": 50, "gp": 100, "pp": 1000}

# Слоты экипировки (док 04 §3).
EQUIP_SLOTS = ["main_hand", "off_hand", "armor", "helm", "cloak",
               "boots", "gloves", "ring_1", "ring_2", "amulet"]

ATTUNEMENT_CAP = 3
QUEST_ITEM_TAGS = {"undroppable", "unsellable", "quest_bound"}


@dataclass(frozen=True)
class ItemTemplate:
    template_id: str
    name: str
    category: str               # weapon|armor|tool|gear|consumable|gem|art|magic|currency
    base_stats: dict = field(default_factory=dict)   # damage, ac, weapon_key, slot, ...
    weight: float = 0.0
    base_value: int = 0         # в медяках, канонический
    rarity: str = "mundane"     # mundane|common|uncommon|rare|very_rare|legendary
    attunement: bool = False
    stackable: bool = False
    max_stack: int = 1
    tags: tuple = ()            # martial, finesse, holy, two_handed, undroppable ...


@dataclass
class ItemInstance:
    instance_id: str
    template_id: str
    owner_ref: str | None = None        # инвариант именных
    location_ref: str = ""              # container id либо place id
    quantity: int = 1
    charges: int | None = None
    durability: float | None = None
    identified: bool = True
    custom_name: str | None = None
    description: str | None = None      # флейвор от item_smith (косметика, не механика)
    affixes: list[str] = field(default_factory=list)
    equipped_slot: str | None = None
    provenance: Provenance | None = None


def wallet_value_cp(wallet: dict[str, int]) -> int:
    return sum(amount * COIN[c] for c, amount in wallet.items() if c in COIN)


def make_change(total_cp: int) -> dict[str, int]:
    """Раскладывает медяки в крупные монеты (для показа/выдачи наград)."""
    out: dict[str, int] = {}
    for coin in ("pp", "gp", "ep", "sp", "cp"):
        v = COIN[coin]
        if total_cp >= v:
            out[coin] = total_cp // v
            total_cp %= v
    return out
