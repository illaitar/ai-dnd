"""Seed item pool for the world (DATA, no LLM): basic goods/finds of the town with a rarity axis.
The world copies this to item_pool on creation; loot/rewards drawn by weight, skipping
already-drawn uniques. New items (crafted/trophies) are added to the world pool at runtime.

Key functions
-------------
seed_templates() -> list : Build item pool templates with weights for world init.
draw(pool, taken_uniques, seed, tier) -> dict | None : Draw weighted loot, respecting tier and skipping taken uniques.
"""

from __future__ import annotations

from random import Random

from .model import RARITY_WEIGHT

# (name, kind, craftsmanship quality, worth, rarity)
SEED_POOL = [
    ("ржавый нож", "weapon", "crude", 3, "common"),
    ("крепкий топор", "weapon", "plain", 8, "common"),
    ("охотничий лук", "weapon", "plain", 12, "common"),
    ("тугой арбалет", "weapon", "fine", 18, "common"),
    ("меч доброй ковки", "weapon", "fine", 20, "rare"),
    ("кинжал с насечкой", "weapon", "fine", 16, "rare"),
    ("кожаный жилет", "armor", "plain", 10, "common"),
    ("клёпаная броня", "armor", "fine", 22, "rare"),
    ("походные сапоги", "armor", "plain", 8, "common"),
    ("тёплый плащ", "armor", "plain", 7, "common"),
    ("целебный отвар", "consumable", "plain", 6, "common"),
    ("склянка крепкого зелья", "consumable", "fine", 14, "rare"),
    ("вяленое мясо", "consumable", "crude", 2, "common"),
    ("моток верёвки", "tool", "plain", 3, "common"),
    ("огниво", "tool", "plain", 2, "common"),
    ("лоза-отмычка", "tool", "fine", 9, "rare"),
    ("точильный камень", "tool", "plain", 3, "common"),
    ("походный котелок", "tool", "plain", 4, "common"),
    ("серебряный медальон", "trinket", "fine", 15, "rare"),
    ("самоцвет в оправе", "valuable", "exquisite", 40, "epic"),
    ("старинная монета", "valuable", "fine", 12, "rare"),
    ("древний талисман", "trinket", "exquisite", 55, "epic"),
    ("клинок Утренней Зари", "weapon", "exquisite", 90, "unique"),
    ("амулет Семи Ветров", "trinket", "exquisite", 80, "unique"),
]


def seed_templates() -> list:
    """Templates for populating the world's item_pool: key/data(factsheet)/weight(by rarity)."""
    out = []
    for name, kind, quality, worth, rarity in SEED_POOL:
        out.append({"key": f"seed:{name}", "weight": RARITY_WEIGHT[rarity],
                    "data": {"name": name, "kind": kind, "quality": quality, "worth": worth,
                             "apparent_worth": worth, "rarity": rarity}})
    return out


def draw(pool: list, taken_uniques: set, seed: str, tier: str | None = None):
    """Weighted draw from the pool (skipping drawn uniques). tier — minimum rarity (for
    'rare+' rewards). Returns template {key,data,weight} or None."""
    order = ("common", "rare", "epic", "unique")
    floor = order.index(tier) if tier in order else 0
    cand = [t for t in pool
            if order.index(t["data"].get("rarity", "common")) >= floor
            and not (t["data"].get("rarity") == "unique" and t["key"] in taken_uniques)]
    if not cand:
        return None
    total = sum(t["weight"] for t in cand)
    r = Random(f"draw|{seed}").random() * total
    acc = 0
    for t in cand:
        acc += t["weight"]
        if r <= acc:
            return t
    return cand[-1]
