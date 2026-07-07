"""ЭКОНОМИКА города — слой B (docs/citysim.md §B): именованные supply-chain + монета M.

Ощущаемая экономика = ИМЕНОВАННЫЕ цепочки `сырьё → производитель@venue → товар → продажа →
потребители` (content/chains.json), которые игрок видит и РВЁТ (убил мельника → хлеб
дорожает). СОХРАНЕНИЕ ДЕНЕГ: монета города M только ПЕРЕМЕЩАЕТСЯ (покупка = перевод из
кошелька покупателя в кошелёк производителя), нигде не создаётся/не исчезает — кроме притока/
оттока игрока (лут → инфляция, скупил и увёз → дефляция). Никакого безусловного «+coin за
работу»: доход ТОЛЬКО из чужой траты. Цены дышат спросом/запасом (кламп+эластичность).
`wealth`-нужда — от РЕАЛЬНОГО кошелька (пусто → давление к работе/промыслу/долгу).

Рантайм — 0 LLM, суточный шаг (economy_step в _world_events). LOD: цепочки — именованные
производители (реальные кошельки); безымянная масса — покупатели/дрейф в общем пуле M.
"""

from __future__ import annotations

import json
import os
import random

from aidnd.server.play.engine.core import _gt, _store, _wid

_CHAINS: list | None = None


def _catalog() -> list:
    global _CHAINS
    if _CHAINS is None:
        p = os.path.join(os.path.dirname(__file__), "..", "..", "..", "content", "chains.json")
        with open(p, encoding="utf-8") as f:
            _CHAINS = json.load(f)["chains"]
    return _CHAINS


def _people():
    from aidnd.server.play.engine.core import _S
    return _S.get("people") or {}


def _dead() -> set:
    return {k.split("|", 1)[1] for k in _store().flags_prefix(_wid(), "dead|")}


def _seed_coin() -> None:
    """Раздать стартовую монету M по достатку (appearance = видимое богатство); идемпотентно."""
    if _store().flag_get(_wid(), "econ_seeded"):
        return
    rng = random.Random(f"coin|{_wid()}")
    for pid, p in sorted(_people().items()):
        base = 4 + int(getattr(p, "appearance", 0.3) * 24) + rng.randint(0, 6)
        if _store().purse_get(_wid(), pid) == 0:
            _store().purse_add(_wid(), pid, base)
    _store().flag_set(_wid(), "econ_seeded")


def _venue_of(sell_kind: str) -> str | None:
    """Узел-заведение продажи цепочки: первый venue нужного place-kind (по detect зданий)."""
    from aidnd import society
    from aidnd.server.play.engine.core import _S, _binfo
    for bid in sorted(_S.get("keynode") or {}):
        data = (_store().get_building(_wid(), bid) or {}).get("data") or {}
        if sell_kind in society.kinds_of(data):
            return bid
    if sell_kind == "market":                             # рынок = любая лавка/склад/мастерская
        for bid in sorted(_S.get("keynode") or {}):
            if any(k in _binfo(bid)["kind"] for k in ("лавк", "склад", "мастерск", "рынок")):
                return bid
    return None


def instantiate() -> list:
    """Собрать именованные цепочки из реальных производителей+venue (детерминир.). ~3 названных
    производителя на цепочку; остальная масса роли — фон. Сохраняется в flag econ_chains."""
    people = _people()
    by_role: dict = {}
    for pid, p in sorted(people.items()):
        by_role.setdefault(p.role, []).append(pid)
    chains = []
    for t in _catalog():
        producers = by_role.get(t["role"], [])[:3]
        venue = _venue_of(t["sell"])
        if not producers:
            continue
        chains.append({"key": t["key"], "good": t["good"], "role": t["role"],
                       "producers": producers, "venue": venue, "base": t["base"],
                       "output": t["output"], "demand": t["demand"],
                       "price": float(t["base"]), "stock": 0})
    _store().flag_set(_wid(), "econ_chains", json.dumps(chains, ensure_ascii=False))
    return chains


def _chains() -> list:
    raw = _store().flag_get(_wid(), "econ_chains")
    return json.loads(raw) if raw else instantiate()


def ensure() -> None:
    """Идемпотентно: сид монеты + инстанцирование цепочек (первый заход в мир)."""
    _seed_coin()
    if not _store().flag_get(_wid(), "econ_chains"):
        instantiate()


def economy_step() -> list:
    """Суточный шаг (в _world_events): производство → продажа (СОХРАНЕНИЕ монеты, только
    перевод) → цены (спрос/запас, кламп) → wealth-нужда от кошелька. Возвращает новости."""
    ensure()
    people = _people()
    dead = _dead()
    day = _gt() // 1440
    rng = random.Random(f"econ|{_wid()}|{day}")
    chains = _chains()
    news = []
    for ch in chains:
        alive = [p for p in ch["producers"] if p in people and p not in dead]
        if not alive:                                     # производитель мёртв — цепочка встала
            ch["stock"] = max(0, ch["stock"] - 1)
            ch["price"] = min(ch["base"] * 4, ch["price"] * 1.25)  # дефицит → цена вверх
            if rng.random() < 0.5:
                news.append(f"{ch['key']}: производить некому — цена растёт ({int(ch['price'])} зм)")
            continue
        ch["stock"] += ch["output"] * len(alive)          # производство → товар (не монета!)
        # ПОКУПКА: масса платит производителям — монета ПЕРЕМЕЩАЕТСЯ (сохранение M)
        price = max(1, round(ch["price"]))
        want = ch["demand"] * 3
        buyers = [pid for pid in rng.sample(sorted(people),
                                            min(len(people), want * 2))
                  if pid not in dead and pid not in ch["producers"]
                  and _store().purse_get(_wid(), pid) >= price]
        sold = 0
        for pid in buyers[:min(ch["stock"], want)]:
            seller = alive[sold % len(alive)]
            _store().purse_add(_wid(), pid, -price)       # покупатель платит…
            _store().purse_add(_wid(), seller, price)     # …производитель получает (сохранение)
            sold += 1
        ch["stock"] -= sold
        # ЦЕНА: не распродано → вниз (эластичность); распродали весь спрос → вверх
        if sold < ch["demand"]:
            ch["price"] = max(1.0, ch["price"] * 0.94)
        elif ch["stock"] <= 0:
            ch["price"] = min(ch["base"] * 4, ch["price"] * 1.08)
    _store().flag_set(_wid(), "econ_chains", json.dumps(chains, ensure_ascii=False))
    _wealth_from_purse()
    return news


def _wealth_from_purse() -> None:
    """wealth-нужда = f(кошелёк): пусто → высокая (давление к заработку), богат → низкая.
    Заземляет `wealth` в реальных деньгах (было — косметика)."""
    for pid, p in _people().items():
        purse = _store().purse_get(_wid(), pid)
        p.state.needs["wealth"] = round(max(0.05, min(0.95, 1.0 - purse / 30.0)), 2)


def money_supply() -> int:
    """M = Σ кошельков (инвариант, кроме притока/оттока игрока) — для теста сохранения/стенда."""
    return sum(_store().purse_get(_wid(), pid) for pid in _people())


def chains_view() -> list:
    """Приборка экономики (стенд/наблюдаемость): цепочка → цена/запас/производители/дефицит."""
    people = _people()
    dead = _dead()
    out = []
    for ch in _chains():
        alive = [people[p].name for p in ch["producers"] if p in people and p not in dead]
        out.append({"key": ch["key"], "good": ch["good"], "price": round(ch["price"], 1),
                    "stock": ch["stock"], "producers": alive,
                    "broken": not alive})
    return out
