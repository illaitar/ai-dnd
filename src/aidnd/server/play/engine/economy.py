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

Key functions
-------------
ensure() -> None : Idempotent init of coin seed and supply chains on world entry.
instantiate() -> list : Assemble named chains from real producers and venues.
economy_step(day) -> list : Daily simulation: production, sales, price updates, wealth.
economy_catchup(cap) -> list : Lazy catch-up for skipped days (time jumps/sleeps).
venue_buyouts() -> list : Daily: aspirants buy out venues and revive broken chains.
market_here(bid) -> list : Get live market state (goods, prices, stocks) at venue.
player_buy(bid, key, qty) -> dict : Player purchase: inflates prices, creates wealth gap.
player_sell(bid, key, qty) -> dict : Player sale: deflates prices, draws from NPC purses.
chains_view() -> list : Diagnostic view: all chains with live prices, stocks, producers.
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


def economy_step(day: int | None = None) -> list:
    """Суточный шаг (в _world_events): производство → продажа (СОХРАНЕНИЕ монеты, только
    перевод) → цены (спрос/запас, кламп) → wealth-нужда от кошелька. Возвращает новости.
    `day` — конкретные сутки для сида (ленивый catch-up гоняет пропущенные дни по-разному)."""
    ensure()
    people = _people()
    dead = _dead()
    if day is None:
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
        # ПОКУПКА: масса платит производителям — монета ПЕРЕМЕЩАЕТСЯ (сохранение M); спрос за
        # шаг = demand. Что не покрыто запасом — неудовлетворённый спрос (дефицит).
        price = max(1, round(ch["price"]))
        want = ch["demand"]
        buyers = [pid for pid in rng.sample(sorted(people),
                                            min(len(people), max(1, want * 2)))
                  if pid not in dead and pid not in ch["producers"]
                  and _store().purse_get(_wid(), pid) >= price]
        sold = 0
        for pid in buyers[:min(ch["stock"], want)]:
            seller = alive[sold % len(alive)]
            _store().purse_add(_wid(), pid, -price)       # покупатель платит…
            _store().purse_add(_wid(), seller, price)     # …производитель получает (сохранение)
            sold += 1
        ch["stock"] = min(ch["stock"] - sold, ch["demand"] * 8)  # потолок склада (порча/место)
        # ЦЕНА: спрос не покрыт запасом → ДЕФИЦИТ → вверх; залежался избыток → вниз
        unmet = want - sold
        if unmet > 0:
            ch["price"] = min(ch["base"] * 4, ch["price"] * 1.08)
        elif ch["stock"] > ch["demand"]:
            ch["price"] = max(1.0, ch["price"] * 0.94)
    _store().flag_set(_wid(), "econ_chains", json.dumps(chains, ensure_ascii=False))
    news += venue_buyouts()                           # B3: аспиранты выкупают ремесло
    _wealth_from_purse()
    return news


def economy_catchup(cap: int = 7) -> list:
    """E1 (ленивый catch-up): прогнать суточный оборот за КАЖДЫЙ пропущенный день (прыжок во
    времени/сон/дорога), не привязываясь к фазе «утро». Идемпотентно через flag econ_day; кап
    cap дней (LOD — глубокие пропуски не молотим впустую). Возвращает новости ПОСЛЕДНЕГО дня."""
    from aidnd.server.play.engine.core import _GT0, _S
    ensure()
    today = _gt() // 1440
    last = _store().flag_get(_wid(), "econ_day")
    last = int(last) if last is not None else _GT0 // 1440  # базлайн — день СТАРТА мира
    if today <= last:
        return _S.get("econ_news") or []
    news: list = []
    for d in range(max(last + 1, today - cap + 1), today + 1):  # максимум cap дней
        news = economy_step(day=d)
    _store().flag_set(_wid(), "econ_day", str(today))
    return news


def _wealth_from_purse() -> None:
    """wealth-нужда = f(кошелёк): пусто → высокая (давление к заработку), богат → низкая.
    Заземляет `wealth` в реальных деньгах (было — косметика)."""
    for pid, p in _people().items():
        purse = _store().purse_get(_wid(), pid)
        p.state.needs["wealth"] = round(max(0.05, min(0.95, 1.0 - purse / 30.0)), 2)


# ── B3: агенды-выкуп venue (аспирант-подёнщик копит и покупает своё ремесло обратно) ──
_VENUE_PRICE = {"таверн": 90, "трактир": 90, "гильд": 120, "игорн": 70, "лавк": 60,
                "оружейн": 70, "кузн": 60, "храм": 0, "молельн": 0, "часовн": 0,
                "лечебн": 55, "мастерск": 55, "башн": 0, "магич": 0}


def venue_buyouts() -> list:
    """Суточно: если у venue вакансия (владелец умер/мест меньше ёмкости), аспирант-подёнщик
    со СВОИМ бывшим ремеслом и деньгами ВЫКУПАЕТ место → work=venue, роль восстановлена, deed
    'acquire'. Убитый производитель цепочки → аспирант оживляет её (экономическое исцеление).
    Деньги уходят из города (M−), если прежний владелец мёртв, иначе — ему (сохранение)."""
    from aidnd.server.play.engine import deeds as _deeds
    from aidnd.server.play.engine.core import _S, _binfo, _mt
    from aidnd.server.play.engine.world import _WORKCAP

    people = _people()
    dead = _dead()
    news = []
    aspirants = [pid for pid, p in sorted(people.items())
                 if p.role == "подёнщик" and getattr(p, "former_role", None)
                 and pid not in dead]
    for bid in sorted(_S.get("keynode") or {}):
        info = (_binfo(bid)["kind"] + " " + _binfo(bid)["name"]).lower()
        price = next((c for w, c in _VENUE_PRICE.items() if w in info), 0)
        if price <= 0:
            continue
        from aidnd.server.play.engine.core import _role_for_building
        role = _role_for_building(bid)
        cap = next((c for w, c in _WORKCAP.items() if w in info), 3)
        workers = [pid for pid, p in people.items()
                   if p.work == bid and pid not in dead]
        if len(workers) >= cap:
            continue                                  # мест нет — не выкупить
        cand = next((pid for pid in aspirants
                     if getattr(people[pid], "former_role", None) == role
                     and _store().purse_get(_wid(), pid) >= price), None)
        if cand is None:
            continue
        p = people[cand]
        _store().purse_add(_wid(), cand, -price)      # платит цену…
        owner = next((w for w in workers), None)
        if owner:
            _store().purse_add(_wid(), owner, price)  # …прежнему совладельцу (сохранение M)
        # иначе venue пустой → деньги ушли из города (M−, честно: выкуп у наследников/города)
        p.work = bid
        p.role = role                                 # ремесло восстановлено!
        aspirants.remove(cand)
        p.state.memory.add(f"выкупил долю в «{_binfo(bid)['name']}» — снова {role}!",
                           _mt(), 0.8)
        _deeds.record(cand, "acquire", obj=bid, place=_binfo(bid)["name"], witnesses=[])
        news.append(f"{p.name} выкупил(а) место в «{_binfo(bid)['name']}» — снова {role}")
    return news


# ── B2: товарный рынок для игрока (покупка/продажа chain-goods двигают запас/цену/M) ──
def market_here(bid: str | None) -> list:
    """Что продаётся в ЭТОМ venue: цепочки, чей узел-заведение == bid (живые цена/запас)."""
    if not bid:
        return []
    dead = _dead()
    people = _people()
    out = []
    for ch in _chains():
        if ch.get("venue") != bid:
            continue
        alive = [p for p in ch["producers"] if p in people and p not in dead]
        out.append({"key": ch["key"], "good": ch["good"], "price": max(1, round(ch["price"])),
                    "stock": ch["stock"], "broken": not alive,
                    "have": _larder_get(ch["key"])})
    return out


def _larder_get(key: str) -> int:
    return int(_store().flag_get(_wid(), f"pc_larder|{key}") or 0)


def _larder_add(key: str, d: int) -> int:
    n = max(0, _larder_get(key) + d)
    _store().flag_set(_wid(), f"pc_larder|{key}", str(n))
    return n


def player_buy(bid: str | None, key: str, qty: int = 1) -> dict:
    """Игрок покупает товар цепочки по ЖИВОЙ цене: запас−, цена↑ (спрос), монета pc→
    производителям (приток извне = ИНФЛЯЦИЯ, M+). Товар кладётся в котомку (pc_larder)."""
    qty = max(1, int(qty))
    chains = _chains()
    ch = next((c for c in chains if c["key"] == key and c.get("venue") == bid), None)
    if ch is None:
        return {"error": "здесь этим не торгуют"}
    people, dead = _people(), _dead()
    alive = [p for p in ch["producers"] if p in people and p not in dead]
    if not alive:
        return {"error": f"{ch['good']}: производить некому — товара нет"}
    if ch["stock"] < qty:
        return {"error": f"в запасе только {ch['stock']} — столько не купить"}
    price = max(1, round(ch["price"]))
    cost = price * qty
    if _store().purse_get(_wid(), "pc") < cost:
        return {"error": f"не хватает монет (нужно {cost} зм)"}
    _store().purse_add(_wid(), "pc", -cost)                # монета pc уходит в город (M+)
    for i in range(qty):                                  # выручка — производителям (round-robin)
        _store().purse_add(_wid(), alive[i % len(alive)], price)
    ch["stock"] -= qty
    ch["price"] = min(ch["base"] * 4, ch["price"] * (1.03 ** qty))  # раскупают → дорожает
    _store().flag_set(_wid(), "econ_chains", json.dumps(chains, ensure_ascii=False))
    _wealth_from_purse()
    return {"good": ch["good"], "qty": qty, "cost": cost,
            "price": max(1, round(ch["price"])), "stock": ch["stock"],
            "have": _larder_add(key, qty), "coins": _store().purse_get(_wid(), "pc")}


def player_sell(bid: str | None, key: str, qty: int = 1) -> dict:
    """Игрок сбывает товар из котомки в цепочку: запас+, цена↓ (переизбыток), монета из
    кошельков производителей→pc (отток = ДЕФЛЯЦИЯ, M−). Наценка-спред 0.7; неликвид → сколько
    есть у производителей (клампится по их деньгам)."""
    qty = max(1, int(qty))
    chains = _chains()
    ch = next((c for c in chains if c["key"] == key and c.get("venue") == bid), None)
    if ch is None:
        return {"error": "здесь это не примут"}
    if _larder_get(key) < qty:
        return {"error": "нечего продавать"}
    people, dead = _people(), _dead()
    alive = [p for p in ch["producers"] if p in people and p not in dead]
    if not alive:
        return {"error": "скупщика нет — цепочка встала"}
    price = max(1, round(ch["price"]))
    want = int(price * 0.7) * qty                         # спред: сбыт дешевле покупки
    paid = 0                                              # тянем из кошельков скупщиков (неликвид)
    i = 0
    while paid < want and any(_store().purse_get(_wid(), s) > 0 for s in alive):
        s = alive[i % len(alive)]
        if _store().purse_get(_wid(), s) > 0:
            _store().purse_add(_wid(), s, -1)
            paid += 1
        i += 1
    _store().purse_add(_wid(), "pc", paid)                # монета уходит из города к игроку (M−)
    ch["stock"] += qty
    ch["price"] = max(1.0, ch["price"] * (0.97 ** qty))   # переизбыток → дешевеет
    _store().flag_set(_wid(), "econ_chains", json.dumps(chains, ensure_ascii=False))
    _wealth_from_purse()
    return {"good": ch["good"], "qty": qty, "paid": paid, "partial": paid < want,
            "price": max(1, round(ch["price"])), "stock": ch["stock"],
            "have": _larder_add(key, -qty), "coins": _store().purse_get(_wid(), "pc")}


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
