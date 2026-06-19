"""Покупка картографических сведений у NPC — может оказаться ложью либо неполнотой.

Карта в голове игрока (world.player_maps) пополняется покупкой «наводок» у NPC.
Честность продавца зависит от архетипа/фракции/доверия: жулик (Жентарим, громила,
низкое доверие) продаёт ложь, честный — правду, но иногда неполную. Истинность
зафиксирована при покупке (детерминированно по сиду) и вскрывается при посещении
места (verify_on_visit): тогда ложь разоблачается и доверие к продавцу падает.
"""

from __future__ import annotations

import random

from ..content.region import REGION_SITES, TOPIC_TO_SITE, reachable_place_to_site
from ..world.components import Persona
from .seeds import subseed

HONEST_ARCH = {"priest", "townmaster", "guard", "retired_adventurer", "scout",
               "hunter", "innkeeper", "knight", "prospector"}
SHADY_ARCH = {"thug", "bandit", "mage", "guildmaster", "bugbear_boss", "goblin"}
SHADY_FACTION = {"faction:zhentarim", "faction:redbrands", "faction:cragmaw"}
KNOW_ALL = {"innkeeper", "scout", "prospector", "guildmaster"}   # держат слухи обо всём
DANGER_PRICE_GP = {"средняя": 15, "высокая": 30, "смертельная": 50, "?": 10}

FALSE_CONTENTS = ["брошенный клад, охраны нет", "лёгкая добыча, путь свободен",
                  "там давно пусто и тихо", "богатый тайник без ловушек"]


def honesty(world, npc: str, player: str) -> tuple[float, float]:
    """(вероятность ЛЖИ, вероятность НЕПОЛНОТЫ) для продавца.

    Зависит ТОЛЬКО от устойчивых черт (архетип/фракция) — не от текущего доверия.
    Это и есть инвариант «истина о территории зафиксирована»: вместе с замороженным
    броском (subseed по npc+site) исход не плавает при изменении отношений, поэтому
    «спросить 1000 раз = тот же ответ» выполняется буквально, а не лишь потому,
    что повторная покупка заблокирована."""
    p = world.ecs.get(npc, Persona)
    arch = (p.archetype or p.profession or "") if p else ""
    fac = p.faction if p else None
    p_false = 0.12
    if fac in SHADY_FACTION or arch in SHADY_ARCH:
        p_false = 0.55
    elif arch in HONEST_ARCH:
        p_false = 0.05
    return p_false, 0.3


def sellable_sites(world, npc: str) -> list[str]:
    p = world.ecs.get(npc, Persona)
    if not p:
        return []
    sites = [TOPIC_TO_SITE[k.get("topic")] for k in p.knowledge
             if k.get("topic") in TOPIC_TO_SITE]
    if (p.archetype or p.profession) in KNOW_ALL:
        sites += list(REGION_SITES)
    return list(dict.fromkeys(sites))


def price_gp(site_key: str) -> int:
    return DANGER_PRICE_GP.get(REGION_SITES.get(site_key, {}).get("danger", "?"), 10)


def buy_info(world, player: str, npc: str, site_key: str) -> dict:
    """Покупка наводки. Возвращает то, что игрок УСЛЫШАЛ (ложь неотличима от правды
    до проверки), либо {'error': ...}."""
    truth = REGION_SITES.get(site_key)
    if not truth:
        return {"error": "unknown_site"}
    bid = f"belief:{npc}:{site_key}"
    if bid in world.player_maps.get(player, {}):
        return {"error": "already_known", "belief": world.player_maps[player][bid]}

    from ..inventory.container import _pay
    from ..inventory.items import wallet_value_cp
    cost_cp = price_gp(site_key) * 100
    if wallet_value_cp(world.wallet(player)) < cost_cp:
        return {"error": "insufficient_funds", "price_gp": price_gp(site_key)}

    p_false, p_incomplete = honesty(world, npc, player)
    rng = random.Random(subseed(world.seed, "mapinfo", npc, site_key))
    r = rng.random()
    belief = {"id": bid, "site": site_key, "place": truth.get("place"), "source": npc,
              "label": truth["label"], "terrain": truth["terrain"],
              "direction": truth["direction"], "verified": False}
    if r < p_false:                                   # ЛОЖЬ (выглядит заманчиво)
        belief.update(contents=rng.choice(FALSE_CONTENTS), danger="безопасно",
                      direction=rng.choice(["север", "юг", "восток", "запад", truth["direction"]]),
                      reliability="false", true=False)
    elif r < p_false + p_incomplete:                  # НЕПОЛНО (правда, но скудно)
        belief.update(contents="", danger="?", reliability="hearsay", true=True)
    else:                                             # НАДЁЖНО (правда)
        belief.update(contents=truth["contents"], danger=truth["danger"],
                      reliability="reliable", true=True)

    _pay(world, player, npc, cost_cp)
    world.commit("map_update", player, target=npc, payload={"player": player, "belief": belief})
    return dict(belief)


def verify_on_visit(world, player: str, place_id: str) -> list[tuple[str, bool]]:
    """Игрок дошёл до места → сверяет наводки о нём с реальностью. Ложь разоблачается
    (доверие к продавцу падает). Возвращает [(belief_id, оказалось_правдой)]."""
    site_key = reachable_place_to_site(place_id)
    out = []
    for bid, b in list(world.player_maps.get(player, {}).items()):
        if b.get("verified"):
            continue
        if b["site"] == site_key or b.get("place") == place_id:
            world.commit("map_verify", player, payload={"player": player, "belief_id": bid})
            if not b.get("true") and b.get("source"):    # разоблачение лжи — минус доверие
                world.commit("rel_update", player, payload={
                    "npc": b["source"], "target": player, "trust": -0.3, "affinity": -0.2,
                    "tags": ["sold_me_lies"]})
            out.append((bid, bool(b.get("true"))))
    return out


# приоритет достоверности для свёртки дублей об одном физическом месте
_DISPLAY_PRIO = {"explored": 4, "true_revealed": 3, "false_revealed": 2}


def map_view(world: object, player: str) -> list[dict]:
    """Карта глазами игрока: ложь до проверки неотличима (поле true не раскрывается).

    Дубли об одном месте (личный визит + купленный слух) сворачиваются в один пин:
    остаётся самый достоверный (разведано > подтверждено > опровергнуто > со слов),
    чтобы карта не двоила метки."""
    chosen: dict[str, dict] = {}
    liars: dict[str, str] = {}                           # место -> кто солгал про него
    for b in world.player_maps.get(player, {}).values():
        key = b.get("place") or f"site:{b.get('site')}"
        if b.get("reliability") == "false_revealed" and b.get("source"):
            liars.setdefault(key, b["source"])           # разоблачённая ложь — соц. факт
        prio = _DISPLAY_PRIO.get(b.get("reliability"), 1)
        cur = chosen.get(key)
        if cur is None or prio > _DISPLAY_PRIO.get(cur.get("reliability"), 1):
            chosen[key] = b
    out = []
    for key, b in chosen.items():
        rel = b.get("reliability")
        display = ("explored" if rel == "explored" else
                   "confirmed" if rel == "true_revealed" else
                   "debunked" if rel == "false_revealed" else
                   "hearsay")                            # купленное непроверенное = «со слов»
        out.append({"label": b["label"], "site": b["site"], "place": b.get("place"),
                    "terrain": b.get("terrain"), "direction": b.get("direction"),
                    "contents": b.get("contents"), "danger": b.get("danger"),
                    "source": b.get("source"), "verified": bool(b.get("verified")),
                    "display": display, "lied_by": liars.get(key)})
    return out
