"""Жадное наполнение экономики на старте: генерация новых шаблонов предметов (с механикой,
под rarity-гейт), пополнение лавок категорийным стоком и пулы лута ВСЕМ базовым NPC.

Заметным NPC (лидеры/торговцы/квестовые/лендмарк) — богатый пул + LLM-флейвор; безликим
горожанам — лёгкий табличный лут. NPC получают owner_ref-предметы → на смерть _spawn_corpse
авто-собирает их в труп. Всё это переживает сейв/лоад через снапшот состояния (runtime.snapshot)."""

from __future__ import annotations

import random

from ..world.components import Persona
from .item_gen import (
    _smith_for,
    generate_item_template,
    npc_loot_pool,
    spawn_item,
)
from .seeds import subseed

_GENERIC_ROLE = {"", "none", "miner", "farmhand", "commoner", "townsfolk", "labourer", "hunter"}

# что генерим на старте (категория, редкость) — потолок rare для тира 1 (LMoP)
_GEN_PLAN = [("weapon", "uncommon"), ("armor", "uncommon"), ("consumable", "common"),
             ("magic", "uncommon"), ("weapon", "rare"), ("magic", "rare")]


def enrich_economy(world, model, progress=None) -> None:
    """Сгенерировать пул новых предметов, пополнить лавки и раздать пулы лута всем NPC."""
    rng = random.Random(subseed(world.seed, "economy"))

    gen_tmpls: list[str] = []                            # 1) новые шаблоны (имя/описание LLM, механика — валидатор)
    for i, (cat, rar) in enumerate(_GEN_PLAN):
        tid, _ = generate_item_template(world, cat, rar, model, rng, i, context="фронтир Фэндалина")
        gen_tmpls.append(tid)
        if progress:
            progress(-1, -1, f"Куётся предмет: {world.templates[tid].name}")

    for sid, shop in list(world.containers.items()):     # 2) лавки добирают категорийный сток
        if getattr(shop, "kind", "") != "shop":
            continue
        cats = tuple(shop.deals_in or ())
        base_pool = [tid for tid, t in world.templates.items()
                     if t.category in cats and not tid.startswith("tmpl:gen_")]
        new_for_cat = [tid for tid in gen_tmpls if world.templates[tid].category in cats]
        picks = (rng.sample(base_pool, min(4, len(base_pool))) if base_pool else []) + new_for_cat
        for tid in picks:
            spawn_item(world, tid, sid, qty=rng.randint(1, 3), source="pregen",
                       smith=_smith_for(model, "товар лавки"))
        if progress:
            progress(-1, -1, f"Лавка пополнена: {sid.split(':')[-1]}")

    for nid in world.npcs():                              # 3) пулы лута ВСЕМ NPC
        per = world.ecs.get(nid, Persona)
        if not per:
            continue
        role = (getattr(per, "archetype", "") or getattr(per, "profession", "") or "").lower()
        rich = role not in _GENERIC_ROLE                 # заметный → богатый пул + сген-предмет
        npc_loot_pool(world, nid, role, rng, gen_tmpls if rich else [], rich)
        if progress:
            progress(-1, -1, f"Пожитки: {getattr(per, 'name', nid)}")
