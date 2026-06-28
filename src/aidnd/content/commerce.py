"""Унифицированная коммерция NPC-агента: сделки (предмет / услуга / наводка) единым контуром.

Делёж ответственности (см. дизайн торговой системы):
  behaviour-гейт (доверие/фракция/часы) → price_cp (МЕХАНИКА, не плывёт) → haggle (бросок Убеждения,
  в оркестраторе) → settle (списать деньги + ВЫДАТЬ ОБЪЕКТ) → narrate (LLM поверх готовой сделки).

Здесь — данные и чистая механика: цены услуг, торг→скидка, выдача объектов (ключ+гостевая комната, паёк).
Бросок-торг и флейвор живут в оркестраторе; оплата — поверх inventory.container (_pay/wallet)."""

from __future__ import annotations

from ..inventory.container import _pay, wallet_value_cp
from ..inventory.items import COIN, ItemTemplate
from ..world.spatial import Place

ROOM_RATE_CP = 5 * COIN["sp"]    # ночлег: 5 ср за ночь (канон LMoP; COIN[sp]=10cp)
MEAL_PRICE_CP = 3 * COIN["sp"]   # горячая еда (паёк): 3 ср
DRINK_PRICE_CP = 2 * COIN["sp"]  # кружка эля: 2 ср
HAGGLE_DC = 13                   # базовая стойкость продавца к торгу
HAGGLE_CAP = 0.25                # максимум скидки торгом (вниз, никогда вверх)

_ROOM_KEY = "tmpl:room_key"


def _ensure_key_template(world) -> None:
    if _ROOM_KEY not in world.templates:
        world.templates[_ROOM_KEY] = ItemTemplate(
            template_id=_ROOM_KEY, name="ключ от гостевой комнаты", category="gear",
            weight=0.0, base_value=0, tags=("undroppable",))


def room_rate(world, inn: str) -> int:
    return ROOM_RATE_CP


def haggle_discount(success: bool, margin: int) -> float:
    """Скидка от торга: провал — 0; успех — тем больше, чем выше маржа броска (кап HAGGLE_CAP)."""
    if not success:
        return 0.0
    return min(HAGGLE_CAP, 0.10 + 0.02 * max(0, margin))


def can_afford(world, player: str, price_cp: int) -> bool:
    return wallet_value_cp(world.wallet(player)) >= max(1, int(price_cp))


def charge(world, player: str, payee: str, price_cp: int) -> bool:
    """Списать price_cp с игрока в пользу payee (NPC/двор). False — не хватило средств."""
    price_cp = max(1, int(price_cp))
    if wallet_value_cp(world.wallet(player)) < price_cp:
        return False
    _pay(world, player, payee, price_cp)
    return True


def guest_room_id(inn: str) -> str:
    return f"room:{inn.split(':', 1)[-1]}_guest"


def ensure_guest_room(world, inn: str) -> str:
    """Лениво создать гостевую комнату как дочернюю к двору (вход гейчен ключом в _entry_blocked)."""
    rid = guest_room_id(inn)
    sp = world.spatial
    if rid not in sp.places:
        sp.add_place(Place(rid, "room", "Гостевая комната", parent=inn,
                           affordances=["rest"], ambiance="тесная чистая каморка с лежанкой и тазом для умывания",
                           portals=[inn]))
        host = sp.places.get(inn)
        if host:
            if rid not in host.children:
                host.children.append(rid)
            host.portals = list(dict.fromkeys((host.portals or []) + [rid]))
    return rid


def grant_lodging(world, player: str, inn: str) -> tuple[str, str]:
    """Снять комнату: создать гостевую, выдать КЛЮЧ-предмет, открыть доступ. → (room_id, key_iid)."""
    from ..gen.item_gen import spawn_item
    _ensure_key_template(world)
    rid = ensure_guest_room(world, inn)
    carry = f"carry:{player.split(':', 1)[1]}"
    key_iid = spawn_item(world, _ROOM_KEY, carry, owner=player, source="service")
    world.flags.add(f"lodging:{rid}")                # доступ открыт — ключ на руках
    return rid, key_iid


def holds_lodging(world, room_id: str) -> bool:
    return f"lodging:{room_id}" in world.flags


def is_guest_room(place_id: str) -> bool:
    return isinstance(place_id, str) and place_id.endswith("_guest") and place_id.startswith("room:")


def serve_food(world, player: str) -> str:
    """Выдать предмет-еду (паёк) в инвентарь игрока. Возвращает iid."""
    from ..gen.item_gen import spawn_item
    carry = f"carry:{player.split(':', 1)[1]}"
    return spawn_item(world, "tmpl:rations", carry, owner=player, source="service")
