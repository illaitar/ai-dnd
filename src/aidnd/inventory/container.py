"""Единая модель контейнера и операций (док 04).

Инвентарь, экипировка, сундук, труп, лавка, земля — всё это контейнеры, делящие
модель и операции. Каждая мутация идёт через event log; move — атомарная пара
remove+add. Экипированные предметы кормят движок правил через AC и атаку (L5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..rules.srd import WEAPONS, ability_modifier
from ..world.components import Stats5e
from .items import ATTUNEMENT_CAP, ItemInstance, wallet_value_cp


@dataclass
class Container:
    container_id: str
    owner_ref: str | None = None
    kind: str = "carry"             # carry|equip|chest|corpse|shop|ground
    capacity_slots: int | None = None
    capacity_weight: float | None = None
    items: list[str] = field(default_factory=list)
    locked: bool = False
    trapped: str | None = None
    buy_rate: float = 0.5           # доля стоимости, по которой лавка выкупает
    deals_in: tuple = ()            # категории, которыми торгует лавка


class InventoryError(Exception):
    pass


# --------------------------------------------------------------------------- #
#  Вес и нагрузка (док 04 §2)                                                  #
# --------------------------------------------------------------------------- #
def total_weight(world, container: Container) -> float:
    w = 0.0
    for iid in container.items:
        inst = world.items.get(iid)
        if not inst:
            continue
        tmpl = world.templates.get(inst.template_id)
        if tmpl:
            w += tmpl.weight * inst.quantity
    return w


def carry_capacity(world, eid: str) -> float:
    st = world.ecs.get(eid, Stats5e)
    return (st.str_ if st else 10) * 15.0


def encumbrance_state(world, eid: str, container: Container) -> str:
    tw = total_weight(world, container)
    return "ok" if tw <= carry_capacity(world, eid) else "over"


# --------------------------------------------------------------------------- #
#  Операции (через event log)                                                 #
# --------------------------------------------------------------------------- #
def can_accept(world, container: Container, inst: ItemInstance) -> bool:
    if container.capacity_slots is not None and len(container.items) >= container.capacity_slots:
        return False
    if container.capacity_weight is not None:
        tmpl = world.templates.get(inst.template_id)
        if tmpl and total_weight(world, container) + tmpl.weight * inst.quantity > container.capacity_weight:
            return False
    return True


def move(world, src_id: str, dst_id: str, instance_id: str, actor: str | None = None) -> None:
    """Атомарный перенос инстанса между контейнерами (док 04 §6)."""
    src = world.containers.get(src_id)
    dst = world.containers.get(dst_id)
    inst = world.items.get(instance_id)
    if not (src and dst and inst):
        raise InventoryError("контейнер или предмет не найден")
    if instance_id not in src.items:
        raise InventoryError("предмета нет в источнике")
    if not can_accept(world, dst, inst):
        raise InventoryError("назначение переполнено")
    world.commit("item_move", actor or (inst.owner_ref or "world"),
                 payload={"from": src_id, "to": dst_id, "instance": instance_id})


def loot(world, character: str, container: Container) -> list[str]:
    """Открыть труп/сундук — вернуть содержимое (док 04 §8)."""
    if container.locked:
        raise InventoryError("заперто")
    if container.trapped:
        raise InventoryError("ловушка не обезврежена")
    return list(container.items)


def transfer_currency(world, src: str | None, dst: str | None, coins: dict[str, int],
                      actor: str = "world") -> None:
    world.commit("currency_transfer", actor,
                 payload={"from": src, "to": dst, "coins": coins})


# --------------------------------------------------------------------------- #
#  Торговля (док 04 §7, цены из док 03 §7)                                     #
# --------------------------------------------------------------------------- #
def _faction_reaction(world, shop: Container, buyer: str) -> float:
    """Отношение фракции торговца к покупателю [-1..1] (скидка своим, наценка врагам)."""
    if not shop.owner_ref:
        return 0.0
    try:
        from ..rules.factions import social_reaction
        return social_reaction(world, buyer, shop.owner_ref)
    except Exception:
        return 0.0


def price_of(world, inst: ItemInstance, shop: Container, buyer: str) -> int:
    """Цена покупки в медяках: base × фракционный множитель (свои дешевле, враги дороже)."""
    tmpl = world.templates.get(inst.template_id)
    base = (tmpl.base_value if tmpl else 0) * inst.quantity
    mult = max(0.8, min(1.25, 1.0 - _faction_reaction(world, shop, buyer) * 0.15))
    return max(1, int(base * mult))


def buy(world, player: str, shop_id: str, instance_id: str) -> None:
    shop = world.containers[shop_id]
    inst = world.items[instance_id]
    price_cp = price_of(world, inst, shop, player)
    wallet = world.wallet(player)
    if wallet_value_cp(wallet) < price_cp:
        raise InventoryError("недостаточно средств")
    player_carry = f"carry:{player.split(':',1)[1]}"
    move(world, shop_id, player_carry, instance_id, actor=player)
    _pay(world, player, shop.owner_ref or shop_id, price_cp)


def sell(world, player: str, shop_id: str, instance_id: str) -> None:
    shop = world.containers[shop_id]
    inst = world.items[instance_id]
    tmpl = world.templates.get(inst.template_id)
    if shop.deals_in and tmpl and tmpl.category not in shop.deals_in:
        raise InventoryError("торговец этим не торгует")
    mult = max(0.8, min(1.25, 1.0 + _faction_reaction(world, shop, player) * 0.15))
    payout = int((tmpl.base_value if tmpl else 0) * inst.quantity * shop.buy_rate * mult)
    player_carry = f"carry:{player.split(':',1)[1]}"
    move(world, player_carry, shop_id, instance_id, actor=player)
    _pay(world, shop.owner_ref or shop_id, player, max(1, payout))


def _pay(world, payer: str, payee: str, amount_cp: int) -> None:
    """Перевод в медяках с округлением кошельков к каноничной форме."""
    pw = world.wallet(payer)
    have_cp = wallet_value_cp(pw)
    new_payer = have_cp - amount_cp
    # обнулим и переразложим (медяки как каноника)
    transfer_currency(world, payer, None, dict(pw), actor=payer)
    from .items import make_change
    transfer_currency(world, None, payer, make_change(max(0, new_payer)), actor=payer)
    transfer_currency(world, None, payee, make_change(amount_cp), actor=payer)


# --------------------------------------------------------------------------- #
#  Экипировка и производные статы (док 04 §3, кормят L5)                       #
# --------------------------------------------------------------------------- #
def equip(world, character: str, instance_id: str, slot: str) -> None:
    inst = world.items.get(instance_id)
    if not inst:
        raise InventoryError("предмет не найден")
    tmpl = world.templates.get(inst.template_id)
    if tmpl and tmpl.attunement and count_attuned(world, character) >= ATTUNEMENT_CAP:
        raise InventoryError("исчерпан лимит настройки (3)")
    world.commit("equip", character,
                 payload={"instance": instance_id, "slot": slot, "character": character})


def unequip(world, character: str, instance_id: str) -> None:
    world.commit("unequip", character, payload={"instance": instance_id})


def count_attuned(world, character: str) -> int:
    n = 0
    for _iid, inst in world.items.items():
        if inst.owner_ref == character and inst.equipped_slot:
            tmpl = world.templates.get(inst.template_id)
            if tmpl and tmpl.attunement:
                n += 1
    return n


def _equipped(world, eid: str) -> dict[str, ItemInstance]:
    out: dict[str, ItemInstance] = {}
    for inst in world.items.values():
        if inst.equipped_slot and inst.owner_ref == eid:
            out[inst.equipped_slot] = inst
    return out


def equipped_weapon_key(world, eid: str) -> str:
    eq = _equipped(world, eid)
    main = eq.get("main_hand")
    if main:
        tmpl = world.templates.get(main.template_id)
        if tmpl and tmpl.base_stats.get("weapon_key"):
            return tmpl.base_stats["weapon_key"]
    st = world.ecs.get(eid, Stats5e)
    return getattr(st, "default_weapon", None) or "unarmed"


def attack_bonus_from_equipment(world, eid: str, kind: str) -> int:
    """Бонус к попаданию/урону от экипированного оружия: магия шаблона + instance-моды
    (заточка/затупление, док 07 §6)."""
    eq = _equipped(world, eid)
    main = eq.get("main_hand")
    if not main:
        return 0
    tmpl = world.templates.get(main.template_id)
    bonus = tmpl.base_stats.get("attack_bonus", 0) if tmpl else 0
    return bonus + (main.mods or {}).get("attack_bonus", 0)


def armor_class(world, eid: str) -> int:
    """AC из экипированной брони + DEX + щит (док 04 §3, док 09 §5)."""
    st = world.ecs.get(eid, Stats5e)
    dex_mod = ability_modifier(st.dex) if st else 0
    eq = _equipped(world, eid)
    armor = eq.get("armor")
    ac = st.ac_base if st else 10
    if armor:
        tmpl = world.templates.get(armor.template_id)
        if tmpl:
            base = tmpl.base_stats.get("ac", 10)
            max_dex = tmpl.base_stats.get("max_dex", 99)
            ac = base + min(dex_mod, max_dex) + tmpl.base_stats.get("ac_bonus", 0)
    else:
        ac = 10 + dex_mod
    if eq.get("off_hand"):
        ot = world.templates.get(eq["off_hand"].template_id)
        if ot and "shield" in ot.tags:
            ac += ot.base_stats.get("ac_bonus", 2)
    return ac


_DIE_LADDER = ["1d4", "1d6", "1d8", "1d10", "1d12"]


def _step_die(expr: str, steps: int) -> str:
    """Сдвиг кости урона по лестнице (затупление = вниз, заточка = вверх). Нестандартные
    выражения (2d6 и т.п.) не трогаем."""
    if steps and expr in _DIE_LADDER:
        i = _DIE_LADDER.index(expr)
        return _DIE_LADDER[max(0, min(len(_DIE_LADDER) - 1, i + steps))]
    return expr


def weapon_damage_expr(world, eid: str) -> tuple[str, str, int]:
    """(выражение_кости, ability, magic_bonus) для урона оружия (док 09 §5).
    Учитывает instance-моды экипированного оружия (затупление/заточка)."""
    wkey = equipped_weapon_key(world, eid)
    weapon = WEAPONS.get(wkey, WEAPONS["unarmed"])
    expr = weapon.damage
    magic = attack_bonus_from_equipment(world, eid, "damage")
    main = _equipped(world, eid).get("main_hand")
    if main and main.mods:
        expr = _step_die(expr, main.mods.get("damage_die_step", 0))
        magic += main.mods.get("damage_bonus", 0)
    return expr, weapon.ability, magic


# --------------------------------------------------------------------------- #
#  Модификация экземпляров + «вытягивание» из БД шаблонов 5e (док 03)          #
# --------------------------------------------------------------------------- #
def modify_item(world, instance_id: str, *, name=None, description=None, **mods):
    """Изменить экземпляр предмета (instance-моды + имя/описание), событийно (реплей)."""
    inst = world.items.get(instance_id)
    if not inst:
        raise InventoryError("предмет не найден")
    merged = {**(inst.mods or {}), **mods}
    world.commit("item_modify", "smith", target=instance_id, payload={
        "mods": merged,
        "name": name if name is not None else inst.custom_name,
        "description": description if description is not None else inst.description})
    return world.items[instance_id]


def blunt_weapon(world, instance_id: str):
    """Притупить клинок: кость урона на ступень ниже и −1 к урону, переименовать."""
    inst = world.items.get(instance_id)
    if not inst:
        raise InventoryError("предмет не найден")
    tmpl = world.templates.get(inst.template_id)
    base = inst.custom_name or (tmpl.name if tmpl else "оружие")
    name = base if base.startswith("затупл") else f"затупленный {base}"
    cur = inst.mods or {}
    return modify_item(world, instance_id, name=name,
                       description="Кромка смята, лезвие село — рубит заметно слабее.",
                       damage_die_step=cur.get("damage_die_step", 0) - 1,
                       damage_bonus=cur.get("damage_bonus", 0) - 1, dulled=True)


def find_template(world, query: str) -> str | None:
    """Найти шаблон 5e по id или имени (точно, затем по подстроке)."""
    q = query.strip().lower()
    if q in world.templates:
        return q
    for tid, t in world.templates.items():
        if q == tid.lower() or q == t.name.lower():
            return tid
    for tid, t in world.templates.items():
        if q in t.name.lower() or q in tid.lower():
            return tid
    return None


def pull_item(world, query: str, container_id: str, owner=None, qty: int = 1, model=None) -> str:
    """Материализовать существующий предмет из БД шаблонов 5e (по имени/id) в контейнер.
    Опц. item_smith (model) даёт экземпляру имя/описание под контекст."""
    tid = find_template(world, query)
    if not tid:
        raise InventoryError(f"в базе нет предмета «{query}»")
    from ..gen.item_gen import _smith_for, spawn_item
    smith = _smith_for(model, f"товар лавки: {world.templates[tid].name}")
    return spawn_item(world, tid, container_id, qty=qty, owner=owner, source="pulled", smith=smith)
