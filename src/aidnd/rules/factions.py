"""Фракции: архетипы для пер-мирной генерации, тиры стояния, реакции.

Архетипы детерминированно инстанцируются в пре-гене (сейв/лоад-сейф), а имена/
описания/цели лениво обогащаются LLM (событие faction_enrich). Стояние игрока с
фракцией — число [-1..1]; тиры дают ярлык и влияют на цены, диалоги, слежку.
"""

from __future__ import annotations

# архетипы гражданских фракций — пул, из которого мир набирает свои гильдии
FACTION_ARCHETYPES = {
    "thieves_guild": {
        "name": "Гильдия теней", "emblem": "🗡", "kind": "thieves_guild",
        "blurb": "Скрытная сеть воров и контрабандистов, живёт в тени закона.",
        "goals": ["прибрать к рукам теневую экономику", "держать стражу на расстоянии"],
        "values": ["скрытность", "добыча", "верность своим"],
        "ranks": ["Шестёрка", "Вор", "Домушник", "Мастер клинка", "Глава теней"],
        "join_min_rep": 0.2,
    },
    "merchant_guild": {
        "name": "Торговая гильдия", "emblem": "⚖", "kind": "merchant_guild",
        "blurb": "Союз купцов и ремесленников, держит рынки и караваны.",
        "goals": ["расширять торговлю", "поддерживать порядок на трактах"],
        "values": ["торговля", "достаток", "порядок"],
        "ranks": ["Подмастерье", "Купец", "Старший купец", "Старшина гильдии"],
        "join_min_rep": 0.25,
    },
    "aristocracy": {
        "name": "Знать", "emblem": "👑", "kind": "aristocracy",
        "blurb": "Родовитые семьи, землевладельцы и покровители города.",
        "goals": ["сохранять влияние и титулы", "оберегать традиции"],
        "values": ["честь", "статус", "традиции"],
        "ranks": ["Дворянин", "Лорд", "Высокий лорд"],
        "join_min_rep": 0.45,
    },
    "temple": {
        "name": "Орден Света", "emblem": "☀", "kind": "temple",
        "blurb": "Храмовый орден: вера, милосердие и борьба со злом.",
        "goals": ["нести веру и помощь", "изгонять нежить и порчу"],
        "values": ["вера", "милосердие", "справедливость"],
        "ranks": ["Послушник", "Жрец", "Иерофант"],
        "join_min_rep": 0.3,
    },
    "watch": {
        "name": "Городская стража", "emblem": "🛡", "kind": "watch",
        "blurb": "Ополчение и стражи порядка фронтирного города.",
        "goals": ["держать порядок", "защищать жителей от разбоя"],
        "values": ["долг", "порядок", "стойкость"],
        "ranks": ["Новобранец", "Стражник", "Сержант", "Капитан стражи"],
        "join_min_rep": 0.3,
    },
    "arcane": {
        "name": "Круг тайн", "emblem": "✦", "kind": "arcane",
        "blurb": "Кружок чародеев и собирателей запретных знаний.",
        "goals": ["копить магические знания", "находить артефакты"],
        "values": ["знание", "тайна", "сила"],
        "ranks": ["Ученик", "Адепт", "Архимаг"],
        "join_min_rep": 0.35,
    },
    "info_guild": {
        "name": "Информационная гильдия", "emblem": "👁", "kind": "info_guild",
        "blurb": "Сеть осведомителей и скупщиков тайн: знает всё, торгует всем.",
        "goals": ["собирать и продавать сведения", "держать руку на пульсе города"],
        "values": ["знание", "сдержанность", "рычаги влияния"],
        "ranks": ["Слушок", "Осведомитель", "Скупщик тайн", "Хозяин слухов"],
        "join_min_rep": 0.3,
    },
}

# взаимная неприязнь/союзничество по виду (faction kind -> {kind: value})
ARCHETYPE_RELATIONS = {
    "thieves_guild": {"watch": -0.7, "merchant_guild": -0.4, "aristocracy": -0.3},
    "watch": {"thieves_guild": -0.7, "criminal": -0.6, "merchant_guild": 0.3},
    "merchant_guild": {"thieves_guild": -0.4, "aristocracy": 0.4, "watch": 0.3},
    "aristocracy": {"merchant_guild": 0.4, "thieves_guild": -0.3, "temple": 0.2},
    "temple": {"arcane": -0.2, "aristocracy": 0.2},
    "arcane": {"temple": -0.2},
    "info_guild": {"thieves_guild": 0.3, "watch": -0.3, "merchant_guild": 0.2},
}

# тиры стояния игрока с фракцией
STANDING_TIERS = [
    (-1.01, "Враг", "#c0492f"),
    (-0.5, "Недоверие", "#b5763a"),
    (-0.1, "Нейтрально", "#9a8f78"),
    (0.3, "Дружба", "#7fa650"),
    (0.6, "Почёт", "#d8b15a"),
]


def standing_tier(value: float) -> tuple[str, str]:
    label, color = "Нейтрально", "#9a8f78"
    for threshold, lbl, col in STANDING_TIERS:
        if value >= threshold:
            label, color = lbl, col
    return label, color


def social_reaction(world, actor_id: str, npc_id: str) -> float:
    """Отношение NPC к актору через фракции: своя +, вражеская −, плюс репутация [-1..1]."""
    from ..world.components import Affiliation, Faction, Persona
    persona = world.ecs.get(npc_id, Persona)
    nf = persona.faction if persona else None
    if not nf:
        return 0.0
    aff = world.ecs.get(actor_id, Affiliation)
    score = world.reputation.get(nf, 0.0) * 0.5
    if aff and aff.membership == nf:
        score += 0.4
    elif aff and aff.membership:
        fac = world.ecs.get(nf, Faction)
        if fac:
            score += fac.relations.get(aff.membership, 0.0) * 0.4
    return max(-1.0, min(1.0, score))


def rank_for_rep(faction, value: float) -> int:
    """Индекс ранга внутри фракции по стоянию (0..len(ranks)-1)."""
    ranks = faction.ranks or ["Член"]
    if value <= faction.join_min_rep:
        return 0
    span = max(0.01, 1.0 - faction.join_min_rep)
    step = (value - faction.join_min_rep) / span
    return max(0, min(len(ranks) - 1, int(step * len(ranks))))
