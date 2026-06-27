"""Живая экономика: доступность ресурсов → ассортимент и цены лавок (этап A).

Ресурсы привязаны к источникам-подземельям (канон LMoP): металл идёт из рудника (wave_echo_cave),
товары — с трактов, перекрытых разбойниками (cragmaw). Статус ресурса (течёт/нарушен/перекрыт)
выводится из зачисток подземелий (cleared-флаги) и активных инцидентов. Лавка торгует категориями
(deals_in) → её снабжение зависит от статуса соответствующих ресурсов: меньше товара и выше цены при
перекрытии. Скидка гильдии по рангу — тоже здесь. Зачистил источник → ресурс потёк → лавка ожила.
"""

from __future__ import annotations

# категория товара → ресурс
CATEGORY_RESOURCE = {
    "weapon": "metal", "armor": "metal", "tool": "metal",
    "gear": "goods", "consumable": "goods",
}

RESOURCES = {
    "metal": {
        "label": "металл и руда", "source": "place:wave_echo_cave",
        "severed": "Рудник в руках чудовищ — металл в дефиците: кузнечные товары дороги и редки.",
        "flowing": "Рудник снова работает — металла вдоволь, цены у кузнеца упали."},
    "goods": {
        "label": "товары с трактов", "source": "place:cragmaw_klarg_cave",
        "severed": "На трактах разбойники — караваны почти не доходят, припасы дорожают.",
        "flowing": "Дороги спокойны — караваны идут исправно, товары в достатке."},
}

# статус → (множитель цены, множитель снабжения 0..1)
_STATUS = {"flowing": (1.0, 1.0), "disrupted": (1.3, 0.6), "severed": (1.7, 0.35)}


def resource_status(world, res: str) -> str:
    """Состояние ресурса: течёт, если источник зачищен; иначе перекрыт. + нарушение активным инцидентом."""
    meta = RESOURCES.get(res)
    if not meta:
        return "flowing"
    src = meta.get("source")
    if src and f"cleared:{src}" in world.flags:
        return "flowing"
    return "severed"                                   # источник под угрозой — ресурс перекрыт


def price_markup(world, category: str) -> float:
    res = CATEGORY_RESOURCE.get(category)
    return _STATUS.get(resource_status(world, res), (1.0, 1.0))[0] if res else 1.0


def stock_factor(world, categories) -> float:
    """Доля снабжения лавки = по самому дефицитному её ресурсу (0..1)."""
    f = 1.0
    for c in categories or ():
        res = CATEGORY_RESOURCE.get(c)
        if res:
            f = min(f, _STATUS.get(resource_status(world, res), (1.0, 1.0))[1])
    return f


def guild_discount(world, buyer: str) -> float:
    """Скидка гильдии по рангу игрока (перк членства)."""
    if buyer != world.player_id:
        return 0.0
    from .guild import GUILD, rank_of, shop_discount
    return shop_discount(rank_of(world.reputation.get(GUILD, 0.0))[0])


def price_factor(world, category: str, buyer: str) -> float:
    """Итоговый множитель цены покупки: наценка дефицита × (1 − скидка гильдии)."""
    return price_markup(world, category) * (1.0 - guild_discount(world, buyer))


def shop_supply_note(world, categories) -> str:
    """Заметка о снабжении лавки (почему дорого/дёшево) — по её перекрытым/потёкшим ресурсам."""
    seen, parts = set(), []
    for c in categories or ():
        res = CATEGORY_RESOURCE.get(c)
        if not res or res in seen:
            continue
        seen.add(res)
        st = resource_status(world, res)
        if st == "severed":
            parts.append("🔺 " + RESOURCES[res]["severed"])
        elif st == "flowing" and f"cleared:{RESOURCES[res]['source']}" in world.flags:
            parts.append("🟢 " + RESOURCES[res]["flowing"])
    return " ".join(parts)
