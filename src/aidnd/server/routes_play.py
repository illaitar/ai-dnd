"""Бэкенд пилота /play на НОВОМ стеке: citygraph (город+карта) + play.populate (жители с мозгами
mind) + LLM-озвучка (inference, офлайн-стаб). Процессная пилот-сессия (один мир, одна фигура игрока).

Карта РЕАЛЬНАЯ и полная: все улицы+дома+река+стены; ходим по ключевым точкам (перекрёсткам) с
пути-поиском (route). «Кто здесь» зависит от перекрёстка. Карточка NPC — отношение/эмоция ИЗ МОЗГА.
"""

from __future__ import annotations

import hashlib
import json
import os
import random

from fastapi import APIRouter, Request

from ..citygraph import CityParams, generate, visual
from ..citygraph.model import NodeKind
from ..items import Capability, ItemCtx, LLMSmith, StubSmith
from ..items.craft import ROLE_RECIPES
from ..items import condition as item_condition
from ..items import normalize as item_normalize
from ..items import craft as item_craft
from ..items import inspect as item_inspect
from ..items import repair as item_repair
from ..items import use as item_use
from ..items import view as item_view
from ..mind import Body, NpcConfig, NpcState
from ..mind import Item as MItem
from ..mind import World as MWorld
from ..mind import perceive as mind_perceive
from ..mind import think
from ..mind import StubPlanner, advance_agendas
from ..mind.llm_agent import apply_actions, decide_hybrid, plan_agenda
from ..mind.tick import _decay_emotion, _decay_needs
from ..play import populate
from ..play.population import Townsperson
from ..worldgen import WorldStore

router = APIRouter(tags=["play"])
PLAYER = "pc"
PLAY_WORLD = 1                       # id пилотного мира для привязок пула (placements)
_STORE: WorldStore | None = None

# ЕДИНАЯ таблица баланса play-слоя (по образцу mind.value.BAL): все пороги/коэффициенты/времена
# ИМЕНОВАНЫ и живут здесь — не россыпью по коду.
PB = {
    "start_gt": 19 * 60 + 40, "start_coins": 12,
    "step_min": 1, "talk_min": 2, "loot_min": 2, "trade_min": 3, "act_min": 2, "live_tick_min": 3,
    "live_gap_s": 6.0, "give_min": 1,
    # цены: продать торговцу / купить у него (от ЕГО видения worth)
    "sell_base": 0.55, "sell_aff": 0.15, "sell_greed": -0.2,
    "buy_base": 1.35, "buy_greed": 0.25, "buy_aff": -0.15,
    # гейты преступлений
    "steal_dc_base": 9, "steal_dc_att": 8, "rob_dc_base": 10, "rob_dc_brav": 8,
    "purse_cut": 2,                                        # кража уносит 1/N кошеля
    "rob_cut_num": 2, "rob_cut_den": 3,                    # грабёж уносит num/den
    # просьба ключа: bar = base + greed·k + honesty·k
    "askkey_base": 0.5, "askkey_greed": 0.4, "askkey_honesty": -0.2,
    # контракты
    "contract_enemy_aff": -0.1, "contract_poor_purse": 5, "contract_reward_min": 2,
    "complete_trust": 0.3, "complete_aff": 0.2, "befriend_aff": 0.25,
    "merchant_float": 30, "hostile_aff": -0.2,
    # распорядок: вероятность вечерней тяги в трактир
    "eve_worker": 0.5, "eve_commoner": 0.45, "eve_rogue": 0.4,
    # подарок: прирост симпатии = min(cap, base + worth/div)
    "gift_aff_base": 0.05, "gift_aff_div": 100, "gift_aff_cap": 0.25,
}
_GT0 = PB["start_gt"]


def _gt() -> int:
    v = _S.get("gt")
    if v is None:
        v = _S["gt"] = _GT0
    return v


def _gt_add(minutes: int) -> int:
    _S["gt"] = _gt() + max(0, int(minutes))
    return _S["gt"]


def _mt() -> int:
    return _gt() // 10               # такт памяти (halflife ретривы 144 такта ≈ сутки)


def _phase(gt: int | None = None) -> str:
    h = ((gt if gt is not None else _gt()) // 60) % 24
    return "night" if h < 6 else "morning" if h < 11 else "day" if h < 17 else \
        "evening" if h < 22 else "night"


_PHASE_RU = {"morning": "утро", "day": "день", "evening": "вечер", "night": "ночь"}


def _store() -> WorldStore:
    global _STORE
    if _STORE is None:
        _STORE = WorldStore()
    return _STORE


# ------------------------------------------------ ИГРОК-АГЕНТ (pc_state) -- #
def _pc() -> NpcState:
    """Игрок — такой же агент: NpcState с памятью и отношениями. Персист в store."""
    if _S.get("pc") is None:
        st = NpcState.from_config(NpcConfig(id=PLAYER, name="ты", role="странник"))
        row = _store().get_pc(PLAY_WORLD)
        if row:
            st.relationships = row.get("relationships") or {}
            for m in row.get("memory") or []:
                mm = st.memory.add(m["text"], m["t"], m.get("importance", 0.3),
                                   kind=m.get("kind", "observation"), about=m.get("about") or [])
                mm.last_access = m.get("last_access", m["t"])
            _S["gt"] = row.get("gt", _GT0)
        _S["pc"] = st
    return _S["pc"]


def _pc_save() -> None:
    st = _pc()
    _store().save_pc(PLAY_WORLD, {
        "gt": _gt(), "relationships": st.relationships,
        "memory": [{"text": m.text, "t": m.t, "importance": m.importance,
                    "last_access": m.last_access, "kind": m.kind, "about": m.about}
                   for m in st.memory.items[-400:]]})      # хвост — журнал не разрастается бесконечно


def _met() -> set:
    return set(_pc().relationships)


def _pc_remember(text: str, importance: float = 0.3, about=None, kind: str = "observation") -> None:
    _pc().memory.add(text, _mt(), importance, kind=kind, about=list(about or []))
    _pc_save()


def _npc_save(pid: str) -> None:
    """Прожитое NPC (память/отношения/нужды) → БД: переживает рестарт сервера."""
    p = (_S.get("people") or {}).get(pid)
    if not p:
        return
    st = p.state
    _store().save_npc_state(PLAY_WORLD, pid, {
        "relationships": st.relationships, "needs": st.needs,
        "memory": [{"text": m.text, "t": m.t, "importance": m.importance,
                    "last_access": m.last_access, "kind": m.kind, "about": m.about}
                   for m in st.memory.items[-200:]]})
_S: dict = {"city": None, "people": None, "crof": None, "cr2b": None, "loc": None,
            "geom": None, "model": None}

_COLORS = ["#c98a52", "#6f8f6a", "#8a6fae", "#a86a6a", "#5f8296", "#b0894a"]
def _binfo(bid: str | None) -> dict:
    """Имя/вид/метка места — из ФАКТШИТА здания (enrichment генерит name/atmosphere/type),
    не из кода. Фоллбэк — вывеска графа."""
    bd = _store().get_building(PLAY_WORLD, bid) if bid else None
    data = (bd or {}).get("data") or {}
    name = data.get("name") or (bd or {}).get("sign") or "Здание"
    kind = data.get("atmosphere") or data.get("type") or "постройка"
    label = (data.get("type") or "дом").split(",")[0].split()[0][:12]
    return {"name": name, "kind": kind, "label": label}


# тип здания (из фактшита) → роль работника; таблица данных, порядок = приоритет совпадения
_TYPE_ROLE = (("таверн", "трактирщик"), ("трактир", "трактирщик"), ("постоял", "трактирщик"),
              ("лавк", "лавочник"), ("склад", "лавочник"), ("кузн", "кузнец"),
              ("храм", "жрец"), ("свят", "жрец"), ("часовн", "жрец"),
              ("целебн", "знахарка"), ("знахар", "знахарка"), ("травн", "знахарка"),
              ("мельниц", "мельник"), ("пекарн", "трактирщик"), ("мастерск", "сапожник"),
              ("кожевн", "дубильщик"), ("дубильн", "дубильщик"), ("конюшн", "горожанин"),
              ("усадьб", "горожанин"), ("гильди", "лавочник"))


def _role_for_building(bid: str) -> str:
    """Роль работника — ИЗ ДАННЫХ здания (тип/имя из фактшита), не по порядковому кругу."""
    info = _binfo(bid)
    t = (info["kind"] + " " + info["name"]).lower()
    return next((r for w, r in _TYPE_ROLE if w in t), "горожанин")


def _topics_for(p) -> list:
    """Темы разговора — из ПЕРСОНЫ (слухи/стремления), не из таблицы ролей."""
    per = p.persona or {}
    out = [t[:40] for t in (per.get("rumors") or [])[:2]] + \
          [t[:40] for t in (per.get("wants") or [])[:1]]
    return out or ["что нового?", "о городе", "о жизни здесь"]


def _spurns(p) -> bool:
    """Не желает иметь с тобой дела: вражда или свежий адресный гнев."""
    rel = p.state.relationships.get(PLAYER) or {}
    ang = p.state.emotion.get("anger", 0)
    return (rel.get("affinity", 0) < PB["hostile_aff"]
            or (ang > 0.5 and p.state.emotion_target.get("anger") == PLAYER))


_DM_SYS = ("Ты — мастер настольной игры. Игрок заявил действие, которое НЕ ИСПОЛНЯЕТСЯ механикой — "
           "мир от него НЕ изменится. Ответь СУХО: 1-2 короткие фразы, 2-е лицо, настоящее время, без "
           "цветистости. НИКОГДА не подтверждай свершение заявленного (особенно разрушительного): опиши, "
           "почему оно не происходит или на чём останавливается (обстановка, взгляды людей, нет средств, "
           "здравый смысл) — либо, для созерцательного, что игрок видит. Новых фактов мира не выдумывай.")


def _model():
    if _S["model"] is None:
        from ..inference import ModelManager
        _S["model"] = ModelManager()
    return _S["model"]


def _routine_spot(pid: str, p, phase: str, day: int, keynode: dict, kps: list, tavern) -> int:
    """Где человек в эту фазу суток. Детерминировано на (человек, фаза, день) — мир меняется,
    пока игрока нет, но воспроизводимо."""
    rng = random.Random(f"rout|{pid}|{phase}|{day}")
    if p.role in ("бродяга", "головорез"):                  # лихой люд: днём по углам, вечером к людям
        if phase in ("evening", "night") and tavern is not None and rng.random() < PB["eve_rogue"]:
            return tavern
        return rng.choice(kps) if kps else p.home
    if p.work:                                              # работник: пост днём, вечером трактир/дом
        wn = keynode.get(p.work, p.home)
        if phase in ("morning", "day"):
            return wn
        if phase == "evening":
            if p.role == "трактирщик":
                return wn                                   # трактирщик вечером на посту
            return tavern if (tavern is not None and rng.random() < PB["eve_worker"]) else p.home
        return p.home
    if phase == "morning":                                  # горожанин
        return p.home if rng.random() < 0.5 else (rng.choice(kps) if kps else p.home)
    if phase == "day":
        return rng.choice(kps) if kps else p.home
    if phase == "evening":
        return tavern if (tavern is not None and rng.random() < PB["eve_commoner"]) else p.home
    return p.home


def _apply_routine() -> None:
    """Пересчитать споты всех жителей при смене фазы суток (дёшево — ключ по фазе+дню)."""
    key = (_phase(), _gt() // 1440)
    if _S.get("routine_key") == key or not _S.get("people"):
        return
    _S["routine_key"] = key
    people, crof = _S["people"], _S["crof"]
    keynode, kps = _S.get("keynode") or {}, _S.get("kps") or []
    tavern = next((keynode.get(p.work) for p in people.values()
                   if p.role == "трактирщик" and p.work), None)
    for pid, p in people.items():
        crof[pid] = _routine_spot(pid, p, key[0], key[1], keynode, kps, tavern)


_TIE_ROLES = {"головорез": "головорез", "шайк": "головорез", "стражн": "стражник",
              "лавочн": "лавочник", "куп": "лавочник", "трактир": "трактирщик", "жрец": "жрец",
              "знахар": "знахарка", "кузнец": "кузнец", "мельник": "мельник", "бард": "бард",
              "бродя": "бродяга", "сапожн": "сапожник", "дубильщ": "дубильщик", "стар": "жрец"}


def _weave_ties(people) -> None:
    """Связи персон («должен головорезам», «враждует со старостой») ПРИВЯЗЫВАЮТСЯ к реальным
    людям пула: обоюдные отношения в mind + память с настоящим именем. Граф «кто кого знает»
    становится настоящим; детерминировано, идемпотентно (по метке в памяти)."""
    rng = random.Random("ties|1")
    byrole: dict = {}
    for oid, o in sorted(people.items()):
        byrole.setdefault(o.role, []).append(oid)
    for pid, p in sorted(people.items()):
        st = p.state
        if any("— это про" in m.text for m in st.memory.items):
            continue                                       # уже вязан (в т.ч. восстановлен из npc_state)
        for tie in ((p.persona or {}).get("ties") or [])[:2]:
            tl = tie.lower()
            role = next((r for w, r in _TIE_ROLES.items() if w in tl), None)
            cands = [x for x in byrole.get(role, []) if x != pid]
            if not cands:
                continue
            oid = rng.choice(cands)
            o = people[oid]
            neg = any(w in tl for w in ("должен", "долг", "вражд", "боит", "подозр", "ненавид", "угрож"))
            ar, br = st.rel(oid), o.state.rel(pid)
            if neg:
                ar["fear"] = max(ar["fear"], 0.3)
                ar["affinity"] = min(ar["affinity"], -0.2)
                br["affinity"] = min(br["affinity"], -0.1)
            else:
                ar["affinity"] = max(ar["affinity"], 0.4)
                ar["trust"] = max(ar["trust"], 0.3)
                br["affinity"] = max(br["affinity"], 0.3)
            st.memory.add(f"{tie} — это про {o.name}", _mt(), 0.5, kind="fact", about=[oid])
            o.state.memory.add(f"{p.name}: {tie[:90]} — нас связывает", _mt(), 0.4, kind="fact", about=[pid])


def _person_from_row(row: dict, home: int, work: str | None) -> Townsperson:
    """Готовый NPC из банка → Townsperson с мозгом (mind) + богатой персоной/портретами."""
    mech = row.get("mech") or {}
    cfg = NpcConfig(id=row["id"], name=row["name"], role=row["role"],
                    traits=mech.get("traits") or {}, abilities=mech.get("abilities") or {})
    st = NpcState.from_config(cfg)
    r = random.Random(row["id"])                           # лёгкий фон нужд, детерминированно
    for n in st.needs:
        st.needs[n] = round(r.uniform(0.1, 0.35), 2)
    saved = _store().get_npc_state(PLAY_WORLD, row["id"])  # прожитое переживает рестарт
    if saved:
        st.relationships = saved.get("relationships") or {}
        st.needs.update(saved.get("needs") or {})
        for m in saved.get("memory") or []:
            mm = st.memory.add(m["text"], m["t"], m.get("importance", 0.3),
                               kind=m.get("kind", "observation"), about=m.get("about") or [])
            mm.last_access = m.get("last_access", m["t"])
    tp = Townsperson(id=row["id"], name=row["name"], role=row["role"], home=home, work=work,
                     charisma=row["charisma"], appearance=row["appearance"], state=st,
                     persona=row.get("persona"), portraits=row.get("portraits") or {})
    if work:                                               # владелец здания → ключи от его закрытых ёмкостей
        tp.keys = _building_keys(work)
    return tp


def _building_keys(bid: str) -> list:
    """Ключи-открывашки от LOCKED-ёмкостей здания (для владельца)."""
    bd = _store().get_building(PLAY_WORLD, bid)
    if not bd:
        return []
    return [{"name": c["key"]["name"], "opens": c["name"], "where": c.get("where", "")}
            for c in (bd["data"].get("containers") or [])
            if c.get("access") == "locked" and c.get("key")]


def _building_containers(bid: str) -> list:
    """Ёмкости здания для сцены (без содержимого — вскрывается взаимодействием)."""
    bd = _store().get_building(PLAY_WORLD, bid)
    if not bd:
        return []
    return [{"name": c["name"], "kind": c["kind"], "where": c.get("where", ""),
             "locked": c.get("access") == "locked"} for c in (bd["data"].get("containers") or [])]


def _fill_from_pool(city, keynode, kps):
    """Наполнить толпу из БАНКА (worldgen.people): ключевые здания по роли + горожане по домам +
    пара лихих. Привязки пишем в placements (персист) и восстанавливаем при повторном заходе.
    Пул пуст → вернём None (падаем на голое populate)."""
    store = _store()
    if store.people_count() == 0:
        return None
    people, spot = {}, {}
    placed = {pl["npc_id"]: pl for pl in store.placements_for(PLAY_WORLD)}
    if placed and not all(pl["node"] in city._xy and pl["home"] in city._xy   # noqa: SLF001
                          for pl in placed.values()):
        store.clear_placements(PLAY_WORLD)                 # граф города изменился — узлы протухли
        placed = {}                                        # пере-размещаем заново (память NPC цела)
    if placed:                                             # уже наполнен — восстановить тех же людей
        for pid, pl in placed.items():
            row = store.get_person(pid)
            if row:
                people[pid] = _person_from_row(row, pl["home"], pl["work"])
                spot[pid] = pl["node"]
        if people:
            return people, spot
    used, rng = set(), random.Random("poolfill|1")
    houses = [h.node for h in city.houses.values()]
    rng.shuffle(houses)
    hi = iter(houses)

    def draw(role):
        for want in (role, None):                          # сперва по роли, потом любой свободный
            for row in store.free_people(PLAY_WORLD, role=want, limit=128):
                if row["id"] not in used:
                    used.add(row["id"])
                    return row
        return None

    def place(row, node, work, home=None):
        home = node if home is None else home
        people[row["id"]] = _person_from_row(row, home, work)
        spot[row["id"]] = node
        store.place_person(PLAY_WORLD, row["id"], node, home, work)

    for bid, kb in sorted(city.key_buildings.items()):
        row = draw(_role_for_building(bid))               # роль работника — из типа здания
        if row:
            place(row, kb.node, bid, home=next(hi, kb.node))   # дом — настоящий, не лавка
    for _ in range(16):
        row = draw("горожанин")
        if row:
            place(row, next(hi, kps[0]), None)
    for i in range(2):
        row = draw("бродяга" if i % 2 == 0 else "головорез")
        if row:
            place(row, next(hi, kps[0]), None)
    return people, spot


def _play():
    if _S["city"] is None:
        params = CityParams(seed=1, key_buildings=8, river=True, walls=True, segment=16)
        city = generate(params)
        vis = visual(params, interactive=True)             # богатый визуал + кликабельные дома
        xy = {n.id: (n.x, n.y) for n in city.nodes()}
        keynode = {bid: kb.node for bid, kb in city.key_buildings.items()}   # здание → БЛИЖАЙШАЯ точка (дверь)
        kps = city.key_points()
        drawn = _fill_from_pool(city, keynode, kps)
        if drawn:                                          # наполнение из банка
            people, spot = drawn
        else:                                              # фоллбэк: голое население (без персон/портретов)
            people = populate(city, seed=1, commoners=16, deviants=2)
            rng = random.Random("spot|1")
            spot = {pid: (keynode.get(p.work) or p.home or rng.choice(kps)) for pid, p in people.items()}
        n2b = {}                                           # узел-точка → ключевое здание (название/сцена)
        for bid, kb in city.key_buildings.items():
            n2b.setdefault(kb.node, bid)
        start = next((keynode.get(p.work) for p in people.values()
                      if p.role == "трактирщик" and p.work), None) or kps[0]
        _weave_ties(people)                                # связи персон → реальные люди пула
        _S.update(city=city, people=people, crof=spot, cr2b=n2b, loc=start,
                  geom=_build_geom(city, xy, n2b, vis), keynode=keynode, kps=kps)
    _apply_routine()                                       # споты = f(время): распорядок дня
    return _S["city"], _S["people"], _S["crof"], _S["cr2b"], _S["loc"]


def _build_geom(city, xy, n2b, vis) -> dict:
    """Лёгкий интерактивный слой поверх богатого визуала: система координат — холст рендера 0 0 W H.
    Дома/улицы/река/стены рисует сам SVG (vis['inner']); клик по дому → его БЛИЖАЙШАЯ точка дороги
    (h2n = h.node, НЕ перекрёсток). Метки зданий подписываем поверх; _xy — узел→xy для маршрута."""
    h2n = {h.id: h.node for h in city.houses.values()}
    road = (NodeKind.CROSSROAD, NodeKind.POINT, NodeKind.BRIDGE, NodeKind.GATE)
    points = [{"id": n, "x": round(xy[n][0], 1), "y": round(xy[n][1], 1)}  # ВСЕ узлы дорог (не только перекрёстки)
              for n in xy if city.node_kind(n) in road]
    keys = []
    for bid, kb in sorted(city.key_buildings.items()):
        keys.append({"node": kb.node, "x": round(kb.x, 1), "y": round(kb.y, 1),
                     "label": _binfo(bid)["label"]})
    return {"viewBox": [0, 0, vis["W"], vis["H"]], "svg": vis["inner"],
            "h2n": h2n, "points": points, "keys": keys,
            "_xy": {n: [round(xy[n][0], 1), round(xy[n][1], 1)] for n in xy}}


def _role_at(node, people, spot, n2b):
    bid = n2b.get(node)
    if not bid:
        return None
    return next((people[pid].role for pid, s in spot.items()
                 if s == node and people[pid].work == bid), None)


def _here(node, spot):
    return [pid for pid, s in spot.items() if s == node]


def _emo(st) -> str:
    e = st.emotion
    dom = max(e, key=e.get)
    if e[dom] < 0.15:
        return "спокойное"
    return {"joy": "тёплое", "anger": "раздражённое", "fear": "настороженное",
            "distress": "подавленное"}.get(dom, "ровное")


_PORT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "portraits")


def _portrait_url(p, emo: str | None = None) -> str | None:
    """URL портрета NPC под эмоцию (статика /portraits). None, если файла нет на диске —
    так прод без ещё не залитых картинок отдаёт инициалы, а не битые ссылки (персона живёт в БД)."""
    ports = getattr(p, "portraits", None) or {}
    if not ports:
        return None
    key = emo if emo in ports else "спокойное" if "спокойное" in ports else next(iter(ports))
    rel = ports[key]
    return "/portraits/" + rel if os.path.exists(os.path.join(_PORT_DIR, rel)) else None


def _scene_dict(city, people, crof, cr2b, loc):
    role = _role_at(loc, people, crof, cr2b)
    bid = cr2b.get(loc)
    if bid:
        info = _binfo(bid)
        name, kind = info["name"], info["kind"]
    elif city.node_kind(loc) == NodeKind.CROSSROAD:
        name, kind = "Перекрёсток", "городская развилка"
    else:
        name, kind = "Улица", "мостовая меж домов"
    here = sorted(_here(loc, crof), key=lambda i: (people[i].work is None, i))
    return {
        "loc": loc,
        "location": {"name": name, "kind": kind,
                     "desc": ("Обычное место фронтирного городка — идёт своя жизнь." if role
                              else "Мимо спешат редкие прохожие; в лужах дрожит свет окон."),
                     "containers": _building_containers(bid) if bid else []},
        "ambient": {"time": _PHASE_RU[_phase()], "weather": "дождь",
                    "mood": "оживлённо" if len(here) > 2 else "тихо",
                    "event": "Народ занят своими делами." if here else "Пусто; лишь ветер гуляет меж домов."},
        "here": [{"id": pid,
                  "name": _display(pid, people),        # незнакомец — дескриптором, имя после знакомства
                  "role": (people[pid].role if (pid in _met() or people[pid].work)
                           else "кто-то из горожан"),   # роль очевидна лишь у занятого делом (работник места)
                  "init": _display(pid, people)[0].upper(), "color": _COLORS[i % len(_COLORS)],
                  "portrait": _portrait_url(people[pid], _emo(people[pid].state))}
                 for i, pid in enumerate(here)],
    }


def _mind_scene(npc_id, people) -> MWorld:
    p = people[npc_id]
    w = MWorld()
    w.link("зал", "улица")
    w.add(Body(id=npc_id, place="зал", charisma=p.charisma, appearance=p.appearance))
    w.add(Body(id=PLAYER, place="зал", charisma=0.4, appearance=0.3))
    return w


_VOICE = {"gruff": "грубовато", "warm": "тепло", "clipped": "сухо и коротко",
          "florid": "витиевато", "meek": "робко", "booming": "громко, зычно"}
_STANCE = {"warm": "дружелюбно", "neutral": "нейтрально", "wary": "настороженно",
           "dour": "хмуро", "greedy": "с расчётом на выгоду", "hostile": "враждебно"}


def _voice(p, rel, kind, player_text=None) -> str:
    mgr = _model()
    if not mgr.available():
        return (f"{p.name} окидывает тебя оценивающим взглядом." if kind == "greet"
                else f"{p.name} неопределённо пожимает плечами.")
    per = getattr(p, "persona", None) or {}
    bits = [f"Ты — {p.name}, {p.role} на фронтире (тёмное фэнтези)."]
    if per:                                                # богатая персона из пула
        if per.get("origin"):
            bits.append(f"Родом: {per['origin']}.")
        if per.get("voice"):
            bits.append(f"Говоришь {_VOICE.get(per['voice'], 'обычно')}.")
        if per.get("speech"):
            bits.append("Речевые привычки: " + "; ".join(per["speech"][:2]) + ".")
        if per.get("quirk"):
            bits.append(f"Причуда: {per['quirk']}.")
        if per.get("wants"):
            bits.append("Стремишься: " + "; ".join(per["wants"][:2]) + ".")
        bits.append(f"К чужаку держишься {_STANCE.get(per.get('stance'), 'нейтрально')}.")
        if per.get("secret"):
            bits.append(f"У тебя есть тайна (НЕ выдавай без веской причины): {per['secret'].get('what', '')}.")
    if _spurns(p):                                         # обида/гнев ПЕРЕВЕШИВАЮТ радушие персоны
        bits.append("Ты ЗОЛ на этого человека (вспомни, почему) — никакого радушия: "
                    "холод, резкость или презрение, по твоему характеру.")
    bits.append("КАНОН: о людях и местах ЭТОГО города говори только то, что есть в памяти и справке — "
                "здешних имён и заведений не выдумывай. Вымысел допустим лишь о дальних краях и былом, "
                "и подавай его как слух.")
    lv = _S.get("live") or {}
    just = (lv.get("last") or {}).get(p.id)
    if just and just != "—":
        bits.append(f"Ты в «{lv.get('place', 'этом месте')}»; только что ты: {just}.")
    mems = p.state.memory.recall(player_text or "разговор с чужаком-игроком", now=_mt(), k=5)
    if mems:                                               # непрерывность: NPC помнит вас и прошлое
        bits.append("ТЫ ПОМНИШЬ: " + "; ".join(m.text for m in mems) + ".")
    if player_text:                                        # вопрос о мире → справка сразу (не выдумывать)
        info = _world_lookup(player_text, _S.get("loc"))
        if "не скажу" not in info:
            bits.append(f"СПРАВКА МИРА (это истина — придерживайся её, имена и места не выдумывай): {info}.")
    bits.append(f"Симпатия к собеседнику {rel.get('affinity', 0):.2f} (низкая — суше/настороже, высокая — теплее). "
                "Отвечай В ХАРАКТЕРЕ, живой разговорной речью, 1-2 фразы, без ремарок-описаний. "
                "Помнишь собеседника — покажи это естественно, не пересказывай память дословно. "
                'Если для ответа НУЖЕН факт о городе или людях (где что находится, кто есть кто) — '
                'верни СТРОГО JSON {"ask": "<короткий вопрос>"} вместо реплики: получишь справку и ответишь.')
    acquainted = any(PLAYER in (m.about or []) for m in p.state.memory.items)
    user = (("К тебе снова подошёл тот самый человек, которого ты помнишь, — поприветствуй его "
             "КАК ЗНАКОМОГО, опираясь на то, что помнишь." if acquainted else
             "К тебе подошёл незнакомец и заговорил — брось первую реплику.") if kind == "greet"
            else f"Он говорит: «{player_text}». Ответь.")
    msgs = [{"role": "system", "content": " ".join(bits)}, {"role": "user", "content": user}]
    resp = mgr.call("narrator", msgs, options={"temperature": 0.85})
    content = (resp.get("content") if resp else "").strip()
    if content.startswith("{"):                            # тулкол ask: справка мира → второй заход
        try:
            ask = (json.loads(content) or {}).get("ask")
        except (json.JSONDecodeError, ValueError):
            ask = None
        if ask:
            info = _world_lookup(str(ask), _S.get("loc"))
            msgs += [{"role": "assistant", "content": content},
                     {"role": "user", "content": f"СПРАВКА МИРА: {info}. Теперь ответь собеседнику "
                                                 f"В ХАРАКТЕРЕ (без JSON)."}]
            resp = mgr.call("narrator", msgs, options={"temperature": 0.85})
            content = (resp.get("content") if resp else "").strip()
    return content or f"{p.name} молчит."


@router.get("/api/play/scene")
def scene():
    city, people, crof, cr2b, loc = _play()
    return {**_scene_dict(city, people, crof, cr2b, loc), "gt": _gt(), "coins": _pc_coins()}


@router.get("/api/play/map")
def game_map():
    city, people, crof, cr2b, loc = _play()
    g = _S["geom"]
    pxy = g["_xy"].get(loc, [0, 0])
    return {"viewBox": g["viewBox"], "svg": g["svg"], "h2n": g["h2n"],
            "points": g["points"], "keys": g["keys"],
            "loc": loc, "player": {"x": pxy[0], "y": pxy[1]}}


@router.post("/api/play/move")
async def move(request: Request):
    city, people, crof, cr2b, loc = _play()
    to = (await request.json()).get("to")
    try:
        to = int(to)
    except (TypeError, ValueError):
        return {"error": "туда нельзя"}
    if to not in _S["geom"]["_xy"] or city.node_kind(to) not in (
            NodeKind.CROSSROAD, NodeKind.POINT, NodeKind.GATE, NodeKind.BRIDGE):
        return {"error": "туда нельзя"}
    r = city.route(loc, to)
    path = [_S["geom"]["_xy"][n] for n in r.nodes if n in _S["geom"]["_xy"]] if r.found else [_S["geom"]["_xy"][to]]
    _S["loc"] = to
    _gt_add(PB["step_min"] * max(1, len(path) - 1))       # время дороги: минут за шаг
    _apply_routine()                                       # за дорогу мир мог перейти в другую фазу
    ct_done = _contract_on_move(to)                        # visit-уговор: дошёл — исполнил
    sc = _scene_dict(city, people, crof, cr2b, to)
    return {**sc, "path": path, "moved": sc["location"]["name"], "gt": _gt(),
            "contract_done": ct_done, "coins": _pc_coins()}


@router.post("/api/play/talk")
async def talk(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    first = npc not in _met()
    _pc().rel(npc)                                     # заговорил = познакомился (имя открыто)
    _gt_add(PB["talk_min"])
    st = p.state
    st.needs["social"] = max(st.needs.get("social", 0.0), 0.4)
    think(st, _mind_scene(npc, people), None)
    if first:                                          # знакомство ложится в память ОБОИМ
        st.memory.add("незнакомец (игрок) подошёл и заговорил со мной", _mt(), 0.4, about=[PLAYER])
        _pc_remember(f"я познакомился с {p.name} ({p.role})", 0.45, about=[npc])
        _npc_save(npc)
    _materialize_npc(npc, "visible")                   # видимое (экипировка+ключи) — настоящие предметы
    rel = st.relationships.get(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    per = p.persona or {}
    emo = _emo(st)
    ports = {e: "/portraits/" + path for e, path in (p.portraits or {}).items()
             if os.path.exists(os.path.join(_PORT_DIR, path))}
    known = [m.text for m in _pc().memory.recall(f"{p.name} {p.role}", now=_mt(), k=3)
             if npc in (m.about or [])]                    # что игрок ЗНАЕТ об этом человеке
    try:
        contract = _contract_offer(npc)                    # у него может быть к тебе дело (из агенды)
    except Exception:                                      # noqa: BLE001 — просьба не должна ломать диалог
        contract = None
    return {"name": p.name, "role": p.role, "init": p.name[0], "color": "#8a6fae",
            "contract": contract,
            "aff": round(rel.get("affinity", 0), 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": emo,
            "portrait": _portrait_url(p, emo), "portraits": ports,
            "sex": per.get("sex"), "age": per.get("age"), "origin": per.get("origin"),
            "look": (per.get("look") or {}).get("clothing") or None,
            "keys": [k["name"] for k in (p.keys or [])],
            "crafter": p.role in _CRAFT, "recipe": (_CRAFT[p.role].name if p.role in _CRAFT else None),
            "known": known, "gt": _gt(),
            "topics": _topics_for(p), "line": _voice(p, rel, "greet")}


@router.post("/api/play/say")
async def say(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc = b.get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    rel = p.state.relationships.setdefault(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    rel["affinity"] = min(1.0, rel["affinity"] + 0.04)
    text = str(b.get("text", ""))
    _gt_add(PB["talk_min"])
    line = _voice(p, rel, "reply", text)
    p.state.memory.add(f"игрок сказал мне: «{text[:100]}», я ответил(а): «{line[:100]}»",
                       _mt(), 0.4, about=[PLAYER])         # диалог остаётся в памяти NPC
    _pc_remember(f"{p.name} на «{text[:60]}» ответил(а): «{line[:90]}»", 0.35, about=[npc])
    _npc_save(npc)
    emo = _emo(p.state)
    ct_done = _contract_on_talk(npc)                       # befriend-уговор: цель прониклась
    return {"line": line, "aff": round(rel["affinity"], 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": emo, "portrait": _portrait_url(p, emo),
            "gt": _gt(), "contract_done": ct_done, "coins": _pc_coins()}


# --------------------------------------------------- ПРЕДМЕТЫ (срез 1) ---- #
_PC_CAP = Capability(abilities={"str": 10, "dex": 11, "con": 10, "int": 11, "wis": 11, "cha": 12})
_ROLE_COMP = {"кузнец": {"metalwork"}, "знахарка": {"herbs", "poison", "medicine"},
              "лавочник": {"trade", "gems"}, "жрец": {"letters", "faith"},
              "бард": {"lore", "letters"}, "стражник": {"law"}, "трактирщик": {"trade"}}


def _smith():
    if _S.get("smith") is None:
        mgr = _model()
        _S["smith"] = LLMSmith(mgr) if mgr.available() else StubSmith()
    return _S["smith"]


def _npc_cap(p) -> Capability:
    ab = getattr(getattr(p.state, "config", None), "abilities", None) or {}
    return Capability(abilities=ab, competencies=_ROLE_COMP.get(p.role, set()))


# ---------------------------------- ЕДИНЫЙ ИНВЕНТАРЬ (держатели: pc | npc | cont:) ----
_TIER_Q = {"poor": "crude", "modest": "plain", "fine": "fine", "rich": "exquisite"}
_TIER_W = {"poor": 1, "modest": 4, "fine": 15, "rich": 40}


def _cont_holder(bid: str, name: str) -> str:
    return f"cont:{bid}:{name}"


def _put_item(seed: str, name: str, kind: str, *, tier: str = "modest", note: str = "",
              mods=None, holder: str = "pc") -> str:
    """Механическая ковка предмета из тега персоны/фактшита (без LLM — флейвор уже придуман)
    + положить держателю. Идемпотентно по seed."""
    iid = "it:" + hashlib.md5(seed.encode()).hexdigest()[:10]
    if not _store().get_item(iid):
        w = _TIER_W.get(tier, 3)
        it = item_normalize({"kind": kind, "name": name, "quality": _TIER_Q.get(tier, "plain"),
                             "worth": w, "apparent_worth": w, "tags": [note] if note else [],
                             "mods": mods or []})
        it["id"] = iid
        _store().save_item(it)
    _store().inv_add(PLAY_WORLD, iid, holder=holder)
    return iid


def _materialize_npc(pid: str, layer: str = "visible") -> None:
    """Инвентарь NPC из персоны → настоящие предметы, ПО СЛОЯМ: visible (экипировка+ключи —
    видно глазами) при первом касании; pockets (карманы/ценное/монеты) — при краже/обыске."""
    p = (_S.get("people") or {}).get(pid)
    if not p or _store().flag_get(PLAY_WORLD, f"mat|{pid}|{layer}"):
        return
    per = p.persona or {}
    if layer == "visible":
        g = per.get("gear") or {}
        for slot, kind in (("weapon", "weapon"), ("offhand", "misc"),
                           ("armor", "armor"), ("garb", "armor")):
            it = g.get(slot)
            if it:
                _put_item(f"npcinv|{pid}|{slot}", it["name"], kind,
                          tier=it.get("tier", "modest"), note=it.get("note", ""), holder=pid)
        for i, t in enumerate((g.get("trinkets") or [])[:3]):
            _put_item(f"npcinv|{pid}|tr{i}", t["name"], "trinket",
                      tier=t.get("tier", "modest"), note=t.get("note", ""), holder=pid)
        for k in (p.keys or []):                           # ключи владельца — НАСТОЯЩИЕ предметы
            _put_item(f"npcinv|{pid}|key|{k['opens']}", k["name"], "key", tier="plain",
                      note=f"открывает: {k['opens']}",
                      mods=[{"target": "special:opens", "op": "grant", "amount": 1,
                             "when": "passive", "cond": k["opens"]}], holder=pid)
    else:                                                  # pockets
        c = per.get("carry") or {}
        for i, s in enumerate((c.get("goods") or [])[:3]):
            _put_item(f"npcinv|{pid}|g{i}", s, "misc", tier="modest", holder=pid)
        for i, s in enumerate((c.get("personal") or [])[:3]):
            _put_item(f"npcinv|{pid}|p{i}", s, "misc", tier="poor", holder=pid)
        for i, s in enumerate((per.get("valuables") or [])[:3]):
            _put_item(f"npcinv|{pid}|v{i}", s, "valuable", tier="fine", holder=pid)
        _store().purse_add(PLAY_WORLD, pid, int(c.get("coins") or 0) + (PB["merchant_float"] if p.work else 0))
    _store().flag_set(PLAY_WORLD, f"mat|{pid}|{layer}")     # работнику — торговая наличность


def _pc_coins() -> int:
    """Кошель игрока (настоящий). Первый доступ — стартовые 12 зм (как в шапке UI)."""
    if not _store().flag_get(PLAY_WORLD, "purse_init|pc"):
        _store().purse_add(PLAY_WORLD, "pc", PB["start_coins"])
        _store().flag_set(PLAY_WORLD, "purse_init|pc")
    return _store().purse_get(PLAY_WORLD, "pc")


def _npc_sees(it: dict, cap: Capability, observer: str) -> dict:
    """Что ТОРГОВЕЦ видит в предмете: его глаз (компетенции/броски) вскрывает свои гейты.
    Асимметрия знания: он может видеть сапфир, которого не видишь ты — и наоборот."""
    res = item_inspect(it, cap, "expert", observer=observer)
    return item_view(it, {h["prop"] for h in res["revealed"]})


def _pc_key_for(cont_name: str) -> dict | None:
    """Ключ в сумке игрока, открывающий эту ёмкость (mod special:opens с cond=имя)."""
    for r in _store().inventory(PLAY_WORLD, "pc"):
        it = _store().get_item(r["item_id"])
        if it and it["kind"] == "key" and any(
                m["target"] == "special:opens" and m.get("cond") == cont_name
                for m in it.get("mods", [])):
            return it
    return None


def _forge(seed: str, kind: str, name_hint: str, source: str, band: str = "plain") -> dict:
    """Ленивая выковка предмета (кэш на id по seed) — строка → фактшит с surface/hidden."""
    iid = "it:" + hashlib.md5(seed.encode()).hexdigest()[:10]
    ex = _store().get_item(iid)
    if ex:
        return ex
    ctx = ItemCtx(kind=kind, name_hint=name_hint, source=source, quality_band=band)
    it = _smith().forge(ctx) or StubSmith().forge(ctx)
    it["id"] = iid
    _store().save_item(it)
    return it


def _item_card(it: dict, known) -> dict:
    v = item_view(it, known)
    v["id"] = it["id"]
    v["condition"] = item_condition(it)
    v["make"] = it.get("make")
    return v


_CRAFT = ROLE_RECIPES                                  # рецепты — данные предметной системы


def _known(iid: str) -> set:
    return next((set(r["known"]) for r in _store().inventory(PLAY_WORLD) if r["item_id"] == iid), set())


@router.post("/api/play/loot")
async def loot(request: Request):
    _city, _people, _crof, cr2b, loc = _play()
    name = (await request.json()).get("container")
    bid = cr2b.get(loc)
    if not bid:
        return {"error": "тут нечего обшарить"}
    bd = _store().get_building(PLAY_WORLD, bid)
    full = next((x for x in ((bd or {}).get("data", {}).get("containers") or []) if x["name"] == name), None)
    if not full:
        return {"error": "нет такой ёмкости"}
    unlocked = None
    if full.get("access") == "locked":
        key = _pc_key_for(name)
        if not key:
            return {"error": "заперто — нужен ключ"}
        unlocked = key["name"]
    holder = _cont_holder(bid, name)
    if not _store().flag_get(PLAY_WORLD, f"seeded|{holder}"):
        for i, s in enumerate(full.get("contents") or []):   # первое касание: содержимое → ёмкость
            it = _forge(f"{PLAY_WORLD}|{bid}|{name}|{i}", "misc", s, f"{name} ({full['kind']})")
            _store().inv_add(PLAY_WORLD, it["id"], holder=holder)
        _store().flag_set(PLAY_WORLD, f"seeded|{holder}")
    rows = _store().inventory(PLAY_WORLD, holder)
    _gt_add(PB["loot_min"])
    if not rows:
        return {"container": name, "items": [], "empty": True, "unlocked": unlocked, "gt": _gt()}
    out = []
    for r in rows:                                          # обшарить = забрать всё (перенос, не копия)
        it = _store().get_item(r["item_id"])
        if it:
            _store().inv_move(PLAY_WORLD, it["id"], "pc")
            out.append(_item_card(it, set(r["known"])))
    _pc_remember(f"обшарил «{name}» в «{(bd or {}).get('sign') or 'здании'}»: "
                 + ", ".join(i["name"] for i in out), 0.3)
    return {"container": name, "items": out, "unlocked": unlocked, "gt": _gt()}


@router.post("/api/play/inspect")
async def inspect_item(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    iid, via, npc = b.get("item"), b.get("via", "appraise"), b.get("npc")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    known = next((set(r["known"]) for r in _store().inventory(PLAY_WORLD) if r["item_id"] == iid), set())
    if npc and via == "expert" and npc in people:
        cap, observer, by = _npc_cap(people[npc]), npc, people[npc].name
    else:
        cap, observer, by = _PC_CAP, "pc", "ты"
    res = item_inspect(it, cap, via, observer=observer, known=known)
    known |= {h["prop"] for h in res["revealed"]}
    _store().inv_set_known(PLAY_WORLD, iid, known)
    return {"item": _item_card(it, known), "via": via, "by": by,
            "revealed": [h["fact"] for h in res["revealed"] if h.get("fact")], "hints": res["hints"]}


@router.get("/api/play/inventory")
def inventory():
    _play()
    out = []
    for r in _store().inventory(PLAY_WORLD):
        it = _store().get_item(r["item_id"])
        if it:
            out.append(_item_card(it, set(r["known"])))
    return {"items": out}


# --------------------------------------------- КРАФТ / ПРОЧНОСТЬ (срез 2) - #
@router.post("/api/play/commission")
async def commission(request: Request):
    """Заказать вещь у NPC-ремесленника: его МАСТЕРСТВО решает исход (качество/клеймо/брак/прочность)."""
    _city, people, _crof, _cr2b, _loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    rec = _CRAFT.get(p.role)
    if not rec:
        return {"error": f"{p.name} не берётся за ремесло"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}

    n = len(_store().inventory(PLAY_WORLD))
    rep = random.Random(f"skill|{npc}").randint(-1, 3)     # у каждого мастера своя рука (мир разнороден)
    it = item_craft(_npc_cap(p), rec, seed=f"{npc}|{rec.name}|{n}",
                    maker={"id": npc, "name": p.name}, reputation=rep)
    it["id"] = "it:" + hashlib.md5(f"comm|{npc}|{n}".encode()).hexdigest()[:10]
    _store().save_item(it)
    _store().inv_add(PLAY_WORLD, it["id"])
    return {"item": _item_card(it, set()), "maker": p.name, "recipe": rec.name}


@router.post("/api/play/repair")
async def repair_item(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    iid, npc = b.get("item"), b.get("npc")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    p = people.get(npc)
    if not p or p.role not in _CRAFT:
        return {"error": "он не мастер"}
    if not it.get("durability"):
        return {"error": "чинить нечего"}
    res = item_repair(it, _npc_cap(p), seed=f"rep|{iid}|{npc}", station=_CRAFT[p.role].station)
    if not res.get("ok"):
        return {"error": res.get("reason", "не чинится")}
    _store().save_item(it)
    return {"item": _item_card(it, _known(iid)), "note": res.get("note"), "by": p.name}


@router.post("/api/play/use")
async def use_item(request: Request):
    _play()
    iid = (await request.json()).get("item")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    if not it.get("durability"):
        return {"error": "нечего испытывать"}
    ev = item_use(it, 1)
    _store().save_item(it)
    return {"item": _item_card(it, _known(iid)), "event": ev}


@router.post("/api/play/askkey")
async def askkey(request: Request):
    """Попросить у NPC его ключ. Гейт механикой: симпатия+доверие против жадности/осторожности —
    хозяйка кассы чужаку ключ не отдаст (честно; путь добычи — кража/торг, срез 2)."""
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc = b.get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}
    _materialize_npc(npc, "visible")
    want = str(b.get("key") or "").strip()                 # какой именно ключ просим (имя с чипа)
    keys = [(_store().get_item(r["item_id"]), r["item_id"])
            for r in _store().inventory(PLAY_WORLD, npc)]
    keys = [(it, iid) for it, iid in keys if it and it["kind"] == "key"
            and (not want or it["name"] == want)]
    if not keys:
        return {"error": f"у {p.name} нет такого ключа при себе"}
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    tr = p.state.config.traits
    bar = PB["askkey_base"] + PB["askkey_greed"] * tr.get("greed", 0.5) + PB["askkey_honesty"] * tr.get("honesty", 0.5)
    if rel.get("affinity", 0) + rel.get("trust", 0) < bar:
        line = _voice(p, rel, "reply", "Одолжи мне свой ключ.")
        p.state.memory.add("незнакомец просил у меня ключ — я не дал(а)", _mt(), 0.5, about=[PLAYER])
        _npc_save(npc)
        return {"given": False, "line": line}
    it, iid = keys[0]
    _store().inv_move(PLAY_WORLD, iid, "pc")
    p.state.memory.add(f"я доверил(а) игроку свой ключ «{it['name']}»", _mt(), 0.6, about=[PLAYER])
    _pc_remember(f"{p.name} доверил(а) мне ключ «{it['name']}»", 0.5, about=[npc])
    _npc_save(npc)
    return {"given": True, "item": _item_card(it, set()),
            "line": _voice(p, rel, "reply", "Спасибо, что доверяешь мне ключ.")}


# ----------------------------------------------- ТОРГОВЛЯ И КРАЖА (срез 2) - #
def _merchant(people, npc):
    p = people.get(npc)
    return p if (p and (p.role in _CRAFT or p.role == "лавочник")) else None


@router.post("/api/play/offer")
async def offer(request: Request):
    """Предложить предмет торговцу: он оценивает СВОИМ глазом (асимметрия знания) и называет цену."""
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc, iid = b.get("npc"), b.get("item")
    p = _merchant(people, npc)
    if not p:
        return {"error": "он не торгует"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}
    it = _store().get_item(iid)
    if not it or not any(r["item_id"] == iid for r in _store().inventory(PLAY_WORLD, "pc")):
        return {"error": "у тебя нет этого"}
    _materialize_npc(npc, "pockets")
    seen = _npc_sees(it, _npc_cap(p), npc)
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    greed = p.state.config.traits.get("greed", 0.5)
    price = max(0, round(seen["worth"] * (PB["sell_base"] + PB["sell_aff"] * rel.get("affinity", 0) + PB["sell_greed"] * greed)))
    price = min(price, _store().purse_get(PLAY_WORLD, npc))
    line = _voice(p, rel, "reply",
                  f"(Я предлагаю тебе купить у меня «{it['name']}». Ты осмотрел вещь и даёшь {price} зм — "
                  f"назови эту цену вслух по-своему.)")
    return {"price": price, "line": line, "sees_worth": seen["worth"], "gt": _gt()}


@router.post("/api/play/sell")
async def sell(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc, iid = b.get("npc"), b.get("item")
    p = _merchant(people, npc)
    it = _store().get_item(iid)
    if not p or not it or not any(r["item_id"] == iid for r in _store().inventory(PLAY_WORLD, "pc")):
        return {"error": "сделки не будет"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}

    _materialize_npc(npc, "pockets")
    seen = _npc_sees(it, _npc_cap(p), npc)
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    greed = p.state.config.traits.get("greed", 0.5)
    price = max(0, round(seen["worth"] * (PB["sell_base"] + PB["sell_aff"] * rel.get("affinity", 0) + PB["sell_greed"] * greed)))
    price = min(price, _store().purse_get(PLAY_WORLD, npc))
    _store().inv_move(PLAY_WORLD, iid, npc)
    _store().purse_add(PLAY_WORLD, npc, -price)
    coins = _store().purse_add(PLAY_WORLD, "pc", price)
    _gt_add(PB["trade_min"])
    p.state.memory.add(f"купил(а) у игрока «{it['name']}» за {price} зм", _mt(), 0.4, about=[PLAYER])
    _pc_remember(f"продал {p.name} «{it['name']}» за {price} зм", 0.4, about=[npc])
    _npc_save(npc)
    return {"sold": True, "price": price, "coins": coins, "gt": _gt()}


@router.get("/api/play/wares")
def wares(npc: str):
    """Что торговец продаст (его материализованный инвентарь, кроме ключей) + цены ЕГО глазом."""
    _city, people, _crof, _cr2b, _loc = _play()
    p = _merchant(people, npc)
    if not p:
        return {"error": "он не торгует"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}
    _materialize_npc(npc, "visible")
    _materialize_npc(npc, "pockets")
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    greed = p.state.config.traits.get("greed", 0.5)
    out = []
    for r in _store().inventory(PLAY_WORLD, npc):
        it = _store().get_item(r["item_id"])
        if not it or it["kind"] in ("key", "valuable"):
            continue                                       # ключи и ЛИЧНОЕ ценное не продаются (то — красть)
        seen = _npc_sees(it, _npc_cap(p), npc)
        price = max(1, round(seen["worth"] * (PB["buy_base"] + PB["buy_greed"] * greed + PB["buy_aff"] * rel.get("affinity", 0))))
        out.append({**_item_card(it, set()), "price": price})
    return {"items": out, "coins": _pc_coins()}


@router.post("/api/play/buy")
async def buy(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc, iid = b.get("npc"), b.get("item")
    p = _merchant(people, npc)
    it = _store().get_item(iid)
    if not p or not it or not any(r["item_id"] == iid for r in _store().inventory(PLAY_WORLD, npc)):
        return {"error": "у него этого нет"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}

    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    greed = p.state.config.traits.get("greed", 0.5)
    seen = _npc_sees(it, _npc_cap(p), npc)
    price = max(1, round(seen["worth"] * (PB["buy_base"] + PB["buy_greed"] * greed + PB["buy_aff"] * rel.get("affinity", 0))))
    if _pc_coins() < price:
        return {"error": f"не хватает монет (нужно {price})"}
    _store().inv_move(PLAY_WORLD, iid, "pc")
    coins = _store().purse_add(PLAY_WORLD, "pc", -price)
    _store().purse_add(PLAY_WORLD, npc, price)
    _gt_add(PB["trade_min"])
    p.state.memory.add(f"продал(а) игроку «{it['name']}» за {price} зм", _mt(), 0.4, about=[PLAYER])
    _pc_remember(f"купил у {p.name} «{it['name']}» за {price} зм", 0.4, about=[npc])
    _npc_save(npc)
    return {"bought": True, "item": _item_card(it, set()), "price": price, "coins": coins, "gt": _gt()}


@router.post("/api/play/steal")
async def steal(request: Request):
    """Обчистить карманы: dex игрока против бдительности жертвы. Провал = поймал + свидетели видели
    (память+сплетни разнесут). Успех тих — но это преступление, и оно записано в мире."""
    _city, people, crof, _cr2b, loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    _materialize_npc(npc, "pockets")
    n = int(_store().flag_get(PLAY_WORLD, f"steal|{npc}") or 0) + 1
    _store().flag_set(PLAY_WORLD, f"steal|{npc}", str(n))
    lv = _S.get("live") or {}
    att = next((w.attention for w in [(lv.get("world") or MWorld()).bodies.get(npc)] if w), 0.65)
    roll = random.Random(f"steal|{npc}|{n}").randint(1, 20)
    dc = PB["steal_dc_base"] + round(att * PB["steal_dc_att"])
    _gt_add(PB["act_min"])
    if roll + _PC_CAP.mod("dex") < dc:                     # ПОЙМАН
        rel = p.state.rel(PLAYER)
        rel["affinity"] = min(rel["affinity"], -0.5)
        p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.7)
        p.state.emotion_target["anger"] = PLAYER
        p.state.memory.add("поймал(а) игрока, когда тот лез мне в карман!", _mt(), 0.9, about=[PLAYER])
        wit = [w for w in _here(loc, crof) if w != npc]
        for w in wit:
            people[w].state.memory.add(f"видел(а), как чужак лез в карман к {p.name}",
                                       _mt(), 0.6, about=[PLAYER, npc])
            _npc_save(w)
        _pc_remember(f"попался на краже у {p.name} — при {len(wit)} свидетелях", 0.7, about=[npc])
        _npc_save(npc)
        return {"caught": True, "witnesses": len(wit),
                "line": _voice(p, rel, "reply", "(Ты поймал этого человека за руку в своём кармане!)"),
                "gt": _gt()}
    loot_rows = [(r["item_id"], _store().get_item(r["item_id"]))
                 for r in _store().inventory(PLAY_WORLD, npc)]
    loot_rows = [(iid, it) for iid, it in loot_rows if it and it["kind"] != "key"]
    coins_np = _store().purse_get(PLAY_WORLD, npc)
    if coins_np > 0 and (not loot_rows or roll % 2 == 0):  # тянем кошель или вещь
        take = max(1, coins_np // PB["purse_cut"])
        _store().purse_add(PLAY_WORLD, npc, -take)
        coins = _store().purse_add(PLAY_WORLD, "pc", take)
        _pc_remember(f"вытащил у {p.name} {take} зм", 0.6, about=[npc])
        return {"caught": False, "coins_taken": take, "coins": coins, "gt": _gt()}
    if not loot_rows:
        return {"caught": False, "nothing": True, "gt": _gt()}
    iid, it = max(loot_rows, key=lambda x: x[1]["worth"])
    _store().inv_move(PLAY_WORLD, iid, "pc")
    _pc_remember(f"вытащил у {p.name} «{it['name']}»", 0.6, about=[npc])
    return {"caught": False, "item": _item_card(it, set()), "coins": _pc_coins(), "gt": _gt()}


# ------------------------------------------- КОНТРАКТЫ (квесты из агенд) --- #
# Квест = делегированная нужда NPC: want-ПРЕДИКАТ над миром (всё равно КАК добудешь) + реальная
# награда. Цель выбирается из НАСТОЯЩИХ вещей мира (ёмкости зданий, ценное других людей).

_CONTRACT_SYS = (
    "Ты — житель фронтирного городка, которому нужна помощь чужака. По твоей натуре и долгой цели выбери "
    "ОДНО поручение из доступных ВИДОВ (используй только перечисленные кандидаты, дословно):\n"
    "bring — добыть тебе вещь из мира; deliver — отнести ТВОЮ вещь названному человеку; "
    "visit — сходить в место и глянуть, что там; befriend — расположить к себе названного человека "
    "(втереться в доверие, разговорить).\n"
    "Верни СТРОГО JSON: {\"kind\": \"bring|deliver|visit|befriend\", \"want\": \"<вещь дословно или null>\", "
    "\"target\": \"<имя человека или место дословно, или null>\", \"reward\": <целое, не больше наличности>, "
    "\"pitch\": \"<просьба В ХАРАКТЕРЕ, 1-2 фразы, с сутью и наградой>\"}"
)


def _contract_candidates(giver: str) -> list:
    """Реальные цели для контракта: содержимое ёмкостей зданий + ценное ДРУГИХ людей."""
    out = []
    giver_work = (_S.get("people") or {}).get(giver)
    giver_work = giver_work.work if giver_work else None
    for bid in list(_S.get("cr2b", {}).values()):
        if bid == giver_work:
            continue                                       # из СВОЕГО здания не просят — абсурд
        bd = _store().get_building(PLAY_WORLD, bid)
        if not bd:
            continue
        nm_b = _binfo(bid)["name"]
        for cnt in (bd["data"].get("containers") or []):
            for it_s in (cnt.get("contents") or [])[:2]:
                out.append({"name": it_s, "where": f"{cnt['name']} ({nm_b})"})
    for pid, p in sorted((_S.get("people") or {}).items()):
        if pid == giver:
            continue
        for v in ((p.persona or {}).get("valuables") or [])[:1]:
            out.append({"name": v, "where": f"при {p.name} ({p.role})"})
    return out[:24]


def _contract_offer(npc: str) -> dict | None:
    """Механика решает, ЧТО просить можно; LLM просит В ХАРАКТЕРЕ. Раз на человека."""
    p = _S["people"][npc]
    if _store().flag_get(PLAY_WORLD, f"coffer|{npc}"):
        return None
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    if rel.get("affinity", 0) < PB["contract_enemy_aff"]:                      # с явным недругом дел не ведут
        return None
    mgr = _model()
    if not mgr.available():
        return None
    if not (p.state.agendas or []):                        # долгая цель — лениво, при первой нужде
        ag0 = plan_agenda(p.state, MWorld(), {"roles": {npc: p.role}}, mgr) or StubPlanner().plan(p.state, MWorld())
        if ag0:
            p.state.agendas.append(ag0)
    if not (p.state.agendas or []):
        return None
    _materialize_npc(npc, "pockets")
    purse = _store().purse_get(PLAY_WORLD, npc)
    reward_item = None
    if purse < PB["contract_poor_purse"]:                                          # бедняк платит вещью, не монетой
        rows = [(r["item_id"], _store().get_item(r["item_id"]))
                for r in _store().inventory(PLAY_WORLD, npc)]
        rows = [(i, it) for i, it in rows if it and it["kind"] != "key"]
        if not rows:
            return None
        reward_item = max(rows, key=lambda x: x[1]["worth"])
    cands = _contract_candidates(npc)
    others = [(pid, o) for pid, o in sorted((_S.get("people") or {}).items()) if pid != npc]
    own = [(r["item_id"], _store().get_item(r["item_id"]))
           for r in _store().inventory(PLAY_WORLD, npc)]
    own = [(i, it) for i, it in own if it and it["kind"] != "key"]
    places = [k["label"] for k in _S["geom"]["keys"]]
    ag = p.state.agendas[0]
    pay_line = (f"Наличность: {purse} зм." if not reward_item
                else f"Монет у тебя нет — в награду отдашь свою вещь «{reward_item[1]['name']}» (reward=0).")
    user = (f"ТЫ: {p.name}, {p.role}. Натура: {trait_hints_str(p)}. "
            f"ТВОЯ ДОЛГАЯ ЦЕЛЬ: {getattr(ag, 'summary', '')}. {pay_line}\n"
            f"bring-КАНДИДАТЫ (вещь → где): " + ("; ".join(f"«{c['name']}» → {c['where']}" for c in cands) or "нет") + "\n"
            f"deliver-ТВОИ ВЕЩИ: " + ("; ".join(f"«{it['name']}»" for _i, it in own[:4]) or "нет") + "\n"
            f"ЛЮДИ (для deliver/befriend): " + ("; ".join(o.name for _pid, o in others[:10]) or "нет") + "\n"
            f"МЕСТА (для visit): " + ", ".join(places))
    resp = mgr.call("narrator", [{"role": "system", "content": _CONTRACT_SYS},
                                 {"role": "user", "content": user}], options={"temperature": 0.7})
    t = (resp.get("content") if resp else "").strip()
    try:
        d = json.loads(t[t.find("{"):t.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    kind = d.get("kind") if d.get("kind") in ("bring", "deliver", "visit", "befriend") else "bring"
    want, tgt = str(d.get("want") or "").strip(), str(d.get("target") or "").strip()
    data = {"giver": npc, "giver_name": p.name, "kind": kind, "want": None, "where": "",
            "target": None, "target_name": None,
            "reward": (0 if reward_item else max(PB["contract_reward_min"], min(int(d.get("reward") or 5), purse))),
            "reward_item": (reward_item[0] if reward_item else None),
            "reward_name": (reward_item[1]["name"] if reward_item else None),
            "pitch": str(d.get("pitch") or "")[:220], "why": getattr(ag, "summary", "")}
    if kind == "bring":
        cand = next((c for c in cands if c["name"] == want), None)
        if not cand:
            return None
        data.update(want=want, where=cand["where"])
    elif kind == "deliver":
        oit = next(((i, it) for i, it in own if it["name"] == want), None)
        who = next(((pid, o) for pid, o in others if o.name == tgt), None)
        if not oit or not who:
            return None
        data.update(want=want, deliver_item=oit[0], target=who[0], target_name=who[1].name,
                    where=f"вручить: {who[1].name}")
    elif kind == "visit":
        pl = next((k for k in _S["geom"]["keys"] if k["label"] == tgt), None)
        if not pl:
            return None
        data.update(target=pl["node"], target_name=pl["label"], where=f"место: {pl['label']}")
    else:                                                   # befriend
        who = next(((pid, o) for pid, o in others if o.name == tgt), None)
        if not who:
            return None
        data.update(target=who[0], target_name=who[1].name, where=f"человек: {who[1].name}")
    cid = f"ct:{npc}:{_mt()}"
    _store().save_contract(PLAY_WORLD, cid, "offered", data)
    _store().flag_set(PLAY_WORLD, f"coffer|{npc}")
    return {"id": cid, **data}


def _tokens_ru(s: str) -> set:
    """Грубый стем: префикс-5 (падежи не мешают «медяки»↔«медяков»)."""
    return {w[:5] for w in str(s).lower().replace("«", " ").replace("»", " ").split() if len(w) >= 4}


def _contract_complete(ct: dict) -> str:
    """Общая выплата ЛЮБОГО исполненного уговора: награда, доверие, память, журнал."""
    giver = ct["giver"]
    p = _S["people"][giver]
    _materialize_npc(giver, "pockets")                     # чтоб было чем платить
    if ct.get("reward_item"):                              # награда вещью (бедняк)
        _store().inv_move(PLAY_WORLD, ct["reward_item"], "pc")
        paid = f"{p.name} отдаёт обещанное — «{ct.get('reward_name')}»"
    else:
        reward = min(ct["reward"], _store().purse_get(PLAY_WORLD, giver))
        _store().purse_add(PLAY_WORLD, giver, -reward)
        coins = _store().purse_add(PLAY_WORLD, "pc", reward)
        paid = f"{p.name} отсыпает тебе {reward} зм (кошель: {coins})"
    _store().save_contract(PLAY_WORLD, ct["id"], "done", {k: v for k, v in ct.items()
                                                          if k not in ("id", "status")})
    p.state.rel(PLAYER)["trust"] = min(1.0, p.state.rel(PLAYER)["trust"] + PB["complete_trust"])
    p.state.rel(PLAYER)["affinity"] = min(1.0, p.state.rel(PLAYER)["affinity"] + PB["complete_aff"])
    p.state.memory.add("чужак исполнил мою просьбу. Надёжный человек", _mt(), 0.85, about=[PLAYER])
    _pc_remember(f"исполнил просьбу {p.name} ({ct['kind']}: {ct.get('want') or ct.get('target_name')})",
                 0.6, about=[giver])
    _npc_save(giver)
    return f"Уговор исполнен! {paid}."


def _contract_on_give(npc: str, it: dict) -> str | None:
    """give закрывает: bring (принёс гиверу) и deliver (вручил адресату). КАК добыл — неважно."""
    for ct in _store().contracts(PLAY_WORLD, "active"):
        kind = ct.get("kind", "bring")
        if kind == "bring" and ct["giver"] == npc and (_tokens_ru(ct["want"]) & _tokens_ru(it["name"])):
            return _contract_complete(ct)
        if kind == "deliver" and ct.get("target") == npc and (_tokens_ru(ct["want"]) & _tokens_ru(it["name"])):
            tgt = _S["people"][npc]
            tgt.state.memory.add(f"чужак передал мне «{it['name']}» от {ct['giver_name']}",
                                 _mt(), 0.5, about=[PLAYER, ct["giver"]])
            _npc_save(npc)
            return _contract_complete(ct)
    return None


def _contract_on_move(loc: int) -> str | None:
    """visit: дошёл до места — уговор исполнен (гивер узнает — слово чужака здесь вес имеет)."""
    for ct in _store().contracts(PLAY_WORLD, "active"):
        if ct.get("kind") == "visit" and ct.get("target") == loc:
            return _contract_complete(ct)
    return None


def _contract_on_talk(npc: str) -> str | None:
    """befriend: цель прониклась к тебе — уговор исполнен."""
    for ct in _store().contracts(PLAY_WORLD, "active"):
        if ct.get("kind") == "befriend" and ct.get("target") == npc:
            rel = _S["people"][npc].state.relationships.get(PLAYER, {})
            if rel.get("affinity", 0) >= PB["befriend_aff"]:
                return _contract_complete(ct)
    return None


def trait_hints_str(p) -> str:
    from ..worldgen.persona_llm import trait_hints
    return trait_hints(p.state.config.traits, p.charisma, p.appearance)


@router.post("/api/play/contract_accept")
async def contract_accept(request: Request):
    cid = (await request.json()).get("id")
    ct = next((c for c in _store().contracts(PLAY_WORLD, "offered") if c["id"] == cid), None)
    if not ct:
        return {"error": "уговора нет"}
    _store().save_contract(PLAY_WORLD, cid, "active", {k: v for k, v in ct.items()
                                                       if k not in ("id", "status")})
    note = None
    if ct.get("kind") == "deliver" and ct.get("deliver_item"):   # посылку вручают сразу
        _store().inv_move(PLAY_WORLD, ct["deliver_item"], "pc")
        note = f"«{ct['want']}» ложится в твою сумку — доставь по адресу."
    _pc_remember(f"взялся за дело для {ct['giver_name']}: {ct.get('kind')} — "
                 f"{ct.get('want') or ct.get('target_name')} ({ct['where']})", 0.6, about=[ct["giver"]])
    return {"accepted": True, "note": note}


@router.get("/api/play/contracts")
def contracts_list():
    _play()
    return {"active": _store().contracts(PLAY_WORLD, "active"),
            "done": _store().contracts(PLAY_WORLD, "done")[-3:]}


@router.post("/api/play/give")
async def give_item(request: Request):
    """Отдать вещь собеседнику (дар или исполнение уговора) — через единый резолвер."""
    _play()
    b = await request.json()
    res = _attempt({"verb": "give", "npc": b.get("npc"), "item": b.get("item")}, {})
    return {**res, "gt": _gt(), "coins": _pc_coins()}


# --------------------------------- ЕДИНЫЙ КОНТУР ДЕЙСТВИЯ (примитив×манера) - #
# Никаких кнопок-глаголов: свободный текст → LLM-интент → attempt() → события мира.
# Гейты по манере: openly (просто), stealthily (dex vs бдительность, свидетели),
# forcefully (сила vs храбрость, страх+гнев+свидетели), persuasively (симпатия vs натура).

_INTENT_SYS = (
    "Ты — парсер намерения игрока в тёмно-фэнтезийной игре. По его фразе и обстановке верни СТРОГО JSON "
    "с ОДНИМ действием:\n"
    '{"verb":"take|give|use|say|inspect|move|talk|attack|wait", '
    '"manner":"openly|stealthily|forcefully|persuasively", '
    '"npc":"<id из списка или null>", "container":"<имя ёмкости или null>", '
    '"item":"<id предмета из сумки или null>", "place":"<название места или null>", '
    '"detail":"<суть: что именно/о чём, коротко>"}\n'
    "Правила: взять из ёмкости=take+container; обчистить карманы=take+npc+stealthily; отнять силой="
    "take+npc+forcefully; выпросить/попросить вещь=say+npc+persuasively; отдать/подарить=give+npc+item; "
    "заговорить/спросить=talk+npc; пойти к месту=move+place; осмотреть свою вещь=inspect+item; "
    "напасть/ударить=attack+npc. Если фраза — не действие, а мысль/отыгрыш: "
    '{"verb":"wait","detail":"<что делает>"}. Только перечисленные id/имена, ничего не выдумывай.'
)


def _intent(text: str, sc: dict) -> dict | None:
    mgr = _model()
    if not mgr.available():
        return None
    here = "; ".join(f"{h['id']}={h['name']} ({h['role']})" for h in sc["here"]) or "никого"
    conts = "; ".join(c["name"] + (" [заперто]" if c["locked"] else "")
                      for c in sc["location"]["containers"]) or "нет"
    bag = "; ".join(f"{r['item_id']}={(_store().get_item(r['item_id']) or {}).get('name', '?')}"
                    for r in _store().inventory(PLAY_WORLD, "pc")) or "пусто"
    keys_pl = ", ".join(k["label"] for k in _S["geom"]["keys"])
    user = (f"МЕСТО: {sc['location']['name']}. ЛЮДИ ЗДЕСЬ: {here}. ЁМКОСТИ: {conts}. "
            f"СУМКА ИГРОКА: {bag}. МЕСТА ГОРОДА: {keys_pl}.\nФРАЗА ИГРОКА: «{text}»")
    resp = mgr.call("narrator", [{"role": "system", "content": _INTENT_SYS},
                                 {"role": "user", "content": user}], options={"temperature": 0.2})
    t = (resp.get("content") if resp else "").strip()
    try:
        return json.loads(t[t.find("{"):t.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def _witness_crime(people, crof, loc, npc, what: str) -> int:
    """Преступление на глазах: жертва в гневе, свидетели пишут память (сплетни разнесут)."""
    p = people[npc]
    rel = p.state.rel(PLAYER)
    rel["affinity"] = min(rel["affinity"], -0.5)
    p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.7)
    p.state.emotion_target["anger"] = PLAYER
    p.state.memory.add(f"чужак {what} — я этого не забуду!", _mt(), 0.9, about=[PLAYER])
    wit = [w for w in _here(loc, crof) if w != npc]
    for w in wit:
        people[w].state.memory.add(f"видел(а): чужак {what} ({p.name})", _mt(), 0.6, about=[PLAYER, npc])
        _npc_save(w)
    _npc_save(npc)
    return len(wit)


def _attempt(intent: dict, sc: dict) -> dict:
    """ОДИН резолвер на все действия игрока: гейты, броски, перенос, память, последствия.
    Возвращает {narr:[строки], open_talk?, refresh?}."""
    city, people, crof, cr2b, loc = _play()
    verb = intent.get("verb") or "wait"
    manner = intent.get("manner") or "openly"
    npc = intent.get("npc") if intent.get("npc") in people else None
    detail = str(intent.get("detail") or "")
    out: dict = {"narr": [], "refresh": False}

    if verb == "talk" and npc:
        out["open_talk"] = npc
        return out

    if verb == "move" and intent.get("place"):
        want = str(intent["place"]).lower()
        tgt = next((k for k in _S["geom"]["keys"] if k["label"].lower() in want or want in k["label"].lower()), None)
        if tgt:
            out["goto"] = tgt["node"]                       # фронт выполнит обычный move (с ходьбой)
        else:
            out["narr"].append("Ты не знаешь, где это. Спроси у людей.")
        return out

    if verb == "take" and intent.get("container"):
        return {"loot": intent["container"], "narr": [], "refresh": True}

    if verb == "take" and npc:
        p = people[npc]
        _materialize_npc(npc, "pockets")
        if manner == "forcefully":                          # отнять силой: сила против храбрости
            n = int(_store().flag_get(PLAY_WORLD, f"rob|{npc}") or 0) + 1
            _store().flag_set(PLAY_WORLD, f"rob|{npc}", str(n))
            roll = random.Random(f"rob|{npc}|{n}").randint(1, 20)
            brav = p.state.config.traits.get("bravery", 0.5)
            _gt_add(PB["act_min"])
            if roll + _PC_CAP.mod("str") >= PB["rob_dc_base"] + round(brav * PB["rob_dc_brav"]):
                take = max(1, _store().purse_get(PLAY_WORLD, npc) * PB["rob_cut_num"] // PB["rob_cut_den"])
                _store().purse_add(PLAY_WORLD, npc, -take)
                _store().purse_add(PLAY_WORLD, "pc", take)
                p.state.rel(PLAYER)["fear"] = max(p.state.rel(PLAYER)["fear"], 0.8)
                w = _witness_crime(people, crof, loc, npc, "силой отнял у меня кошель")
                out["narr"].append(f"Ты вытрясаешь из {p.name} {take} зм. Свидетелей: {w}. Город такое помнит.")
            else:
                w = _witness_crime(people, crof, loc, npc, "пытался отнять моё силой")
                out["narr"].append(f"{p.name} вырывается и поднимает крик! Свидетелей: {w}.")
            out["refresh"] = True
            return out
        # stealthily (по умолчанию для take+npc): карманная кража — тот же гейт, что был кнопкой
        n = int(_store().flag_get(PLAY_WORLD, f"steal|{npc}") or 0) + 1
        _store().flag_set(PLAY_WORLD, f"steal|{npc}", str(n))
        lv = _S.get("live") or {}
        body = (lv.get("world").bodies.get(npc) if lv.get("world") else None)
        att = body.attention if body else 0.65
        roll = random.Random(f"steal|{npc}|{n}").randint(1, 20)
        _gt_add(PB["act_min"])
        if roll + _PC_CAP.mod("dex") < PB["steal_dc_base"] + round(att * PB["steal_dc_att"]):
            w = _witness_crime(people, crof, loc, npc, "лез мне в карман")
            rel = p.state.relationships.get(PLAYER, {})
            out["narr"].append(f"Тебя ловят за руку! Свидетелей: {w}.")
            out["line"] = {"who": p.name, "npc": npc,
                           "text": _voice(p, rel, "reply", "(Ты поймал этого человека за руку в своём кармане!)")}
        else:
            rows = [(r["item_id"], _store().get_item(r["item_id"]))
                    for r in _store().inventory(PLAY_WORLD, npc)]
            rows = [(i, it) for i, it in rows if it and it["kind"] != "key"]
            coins_np = _store().purse_get(PLAY_WORLD, npc)
            if coins_np > 0 and (not rows or roll % 2 == 0):
                take = max(1, coins_np // PB["purse_cut"])
                _store().purse_add(PLAY_WORLD, npc, -take)
                _store().purse_add(PLAY_WORLD, "pc", take)
                _pc_remember(f"вытащил у {p.name} {take} зм", 0.6, about=[npc])
                out["narr"].append(f"Пальцы делают своё: +{take} зм тихо перетекают к тебе.")
            elif rows:
                iid, it = max(rows, key=lambda x: x[1]["worth"])
                _store().inv_move(PLAY_WORLD, iid, "pc")
                _pc_remember(f"вытащил у {p.name} «{it['name']}»", 0.6, about=[npc])
                out["narr"].append(f"Ты незаметно вытягиваешь «{it['name']}».")
            else:
                out["narr"].append("В карманах пусто.")
        out["refresh"] = True
        return out

    if verb == "say" and npc and manner == "persuasively":
        out["open_talk"] = npc                              # уговоры — это диалог; ключ просится там
        out["say_first"] = detail or None
        return out

    if verb == "give" and npc and intent.get("item"):
        iid = intent["item"]
        it = _store().get_item(iid)
        if not it or not any(r["item_id"] == iid for r in _store().inventory(PLAY_WORLD, "pc")):
            out["narr"].append("У тебя нет этой вещи.")
            return out
        p = people[npc]
        _store().inv_move(PLAY_WORLD, iid, npc)
        rel = p.state.rel(PLAYER)
        rel["affinity"] = min(1.0, rel["affinity"] + min(PB["gift_aff_cap"], PB["gift_aff_base"] + it["worth"] / PB["gift_aff_div"]))
        p.state.memory.add(f"игрок подарил мне «{it['name']}»", _mt(), 0.55, about=[PLAYER])
        _pc_remember(f"подарил {p.name} «{it['name']}»", 0.4, about=[npc])
        _npc_save(npc)
        _gt_add(PB["give_min"])
        done = _contract_on_give(npc, it)
        out["narr"].append(f"«{it['name']}» переходит к {p.name}." + (f" {done}" if done else ""))
        out["refresh"] = True
        return out

    if verb == "use" and intent.get("item"):
        iid = intent["item"]
        it = _store().get_item(iid)
        if not it or not any(r["item_id"] == iid for r in _store().inventory(PLAY_WORLD, "pc")):
            out["narr"].append("У тебя нет этой вещи.")
            return out
        _gt_add(PB["give_min"])
        if it["kind"] == "consumable" or not it.get("durability"):
            _store().inv_move(PLAY_WORLD, iid, "used")     # выпито/израсходовано — вещь уходит
            out["narr"].append(f"«{it['name']}» — израсходовано.")
        else:
            ev = item_use(it, 1)
            _store().save_item(it)
            out["narr"].append(f"«{it['name']}» ломается." if ev["broke"]
                               else f"«{it['name']}»: {ev['label']}.")
        out["refresh"] = True
        return out

    if verb == "inspect" and intent.get("item"):
        return {"inspect": intent["item"], "narr": [], "refresh": True}

    if verb == "attack" and npc:
        p = people[npc]
        p.state.rel(PLAYER)["fear"] = max(p.state.rel(PLAYER)["fear"], 0.6)
        w = _witness_crime(people, crof, loc, npc, "замахнулся на меня")
        out["narr"].append(f"Ты подаёшься вперёд с угрозой — {p.name} отшатывается. Свидетелей: {w}. "
                           "(Сталь подождёт: боёвка ещё не выкована.)")
        return out

    mgr = _model()                                         # не-действие: сухой отклик мастера, мир не меняется
    text = str(intent.get("_text") or detail or "")
    if mgr.available() and text:
        resp = mgr.call("narrator", [{"role": "system", "content": _DM_SYS},
                                     {"role": "user", "content": f"Сцена: {sc.get('location', {}).get('name', 'улица')}. "
                                                                 f"Игрок: «{text}»"}],
                        options={"temperature": 0.5})
        line = (resp.get("content") if resp else "").strip()
        out["narr"].append(line or "Ничего не происходит.")
    else:
        out["narr"].append("Ничего не происходит.")
    return out


@router.post("/api/play/act")
async def act(request: Request):
    """Свободное действие: текст → LLM-интент → единый резолвер. Никаких кнопок-глаголов."""
    city, people, crof, cr2b, loc = _play()
    text = str((await request.json()).get("text") or "").strip()
    if not text:
        return {"narr": []}
    sc = _scene_dict(city, people, crof, cr2b, loc)
    it = _intent(text, sc)
    if it is None:
        return {"narr": ["(мир задумался и не понял — попробуй иначе)"], "gt": _gt()}
    it["_text"] = text
    res = _attempt(it, sc)
    _pc_remember(f"я: {text[:80]}", 0.2)
    return {**res, "gt": _gt(), "coins": _pc_coins()}


# ------------------------------------------- ЖИВАЯ ЛОКАЦИЯ (mind + LLM) --- #
# NPC текущей локации живут по-настоящему: каждый тик КАЖДЫЙ решает ходом гибридного мозга
# (механика даёт побуждения → LLM выбирает В ХАРАКТЕРЕ, пишет реплику и описание). Действия
# реальны (apply_actions мутирует мир и память), фид — то, что игрок видит/слышит; незнакомцы
# обезличены дескриптором, имя открывается знакомством (talk).
_LIVE_GAP = PB["live_gap_s"]                                    # мин. сек между тиками (защита от бури поллов)


def _world_lookup(query: str, from_node: int | None = None) -> str:
    """Справка мира для тулкола know/ask: здания (с дорогой от точки), люди (местные знают местных).
    Отвечает ТОЛЬКО реальными фактами графа/пула — не даёт LLM галлюцинировать о городе."""
    city, people = _S.get("city"), _S.get("people") or {}
    if city is None:
        return "не припомню"
    q, outs = query.lower(), []
    for bid, kb in sorted(city.key_buildings.items()):
        info = _binfo(bid)
        nm = info["name"]
        words = (nm + " " + info["kind"]).lower().replace("«", " ").replace("»", " ").split()
        if any(w[:5] in q for w in words if len(w) > 3):
            if from_node is not None:
                r = city.route(from_node, kb.node)
                if r.found:
                    outs.append(f"{nm}: {r.bearing or 'недалеко'}, ~{max(1, len(r.nodes) - 1)} мин ходу")
                    continue
            outs.append(nm)
    for pid, p in sorted(people.items()):
        first = p.name.split()[0].lower()
        if p.role in q or first in q or p.name.lower() in q:
            place = _binfo(p.work)["name"] if p.work else None
            outs.append(f"{p.name} — {p.role}" + (f", обычно в «{place}»" if place else ""))
        if len(outs) >= 3:
            break
    return "; ".join(outs[:3]) if outs else "точно не скажу — не знаю такого"


def _descriptor(p) -> str:
    per = p.persona or {}
    sex = "женщина" if per.get("sex") == "f" else "мужчина"
    cloth = ((per.get("look") or {}).get("clothing") or "").split(",")[0].strip()
    return f"{sex} ({cloth})" if cloth else sex


def _display(pid: str, people) -> str:
    if pid == PLAYER:
        return "ты"
    p = people.get(pid)
    if not p:
        return pid
    return p.name if pid in _met() else _descriptor(p)


def _live_affordances(bid) -> list:
    """Чем локация закрывает нужды — из фактшита здания (services/features). Улица — суета."""
    if not bid:
        return [MItem("уличная суета", 0.15, satisfies="novelty")]
    data = ((_store().get_building(PLAY_WORLD, bid) or {}).get("data")) or {}
    sv, out = data.get("services") or [], []
    for s, (nm, val, need) in {"eat": ("похлёбка", 0.3, "hunger"), "drink": ("кружка эля", 0.25, "comfort"),
                               "lodging": ("тюфяк наверху", 0.25, "fatigue"), "pray": ("алтарь", 0.25, "purpose"),
                               "heal": ("травяной отвар", 0.2, "comfort")}.items():
        if s in sv:
            out.append(MItem(nm, val, satisfies=need))
    if any("очаг" in f for f in (data.get("features") or [])):
        out.append(MItem("место у очага", 0.2, satisfies="fatigue"))
    if sv:
        out.append(MItem("работа по хозяйству", 0.2, satisfies="purpose"))
    return out or [MItem("уличная суета", 0.15, satisfies="novelty")]


def _live_build(city, people, crof, cr2b, loc) -> None:
    bid = cr2b.get(loc)
    place = _binfo(bid)["name"] if bid else "улица"
    data = ((_store().get_building(PLAY_WORLD, bid) or {}).get("data")) if bid else {}
    w = MWorld()
    w.link(place, "улица")
    w.ground[place] = _live_affordances(bid)
    names, roles = {PLAYER: "чужак"}, {PLAYER: "недавно вошедший незнакомец"}
    rng = random.Random(f"live|{loc}")
    npc_map: dict = {}                                     # pid → {имя вещи: item_id} (кражи реальны)
    for pid in _here(loc, crof):
        p = people[pid]
        _materialize_npc(pid, "visible")                   # у присутствующих настоящие вещи при себе
        loot, imap = [], {}
        coins_np = _store().purse_get(PLAY_WORLD, pid)
        if coins_np > 0:
            loot.append(MItem("кошель", min(1.0, 0.15 + coins_np / 40), kind="coin", amount=coins_np))
        rows = [(r["item_id"], _store().get_item(r["item_id"]))
                for r in _store().inventory(PLAY_WORLD, pid)]
        rows = [(i, it) for i, it in rows if it and it["kind"] != "key"]
        if rows:
            iid, it = max(rows, key=lambda x: x[1]["worth"])
            loot.append(MItem(it["name"], min(1.0, it["worth"] / 40)))
            imap[it["name"]] = iid
        npc_map[pid] = imap
        w.add(Body(id=pid, place=place, charisma=p.charisma, appearance=p.appearance,
                   attention=round(rng.uniform(0.45, 0.85), 2), loot=loot))
        names[pid], roles[pid] = p.name, p.role
    pc_loot, pc_map = [], {}
    coins = _pc_coins()
    if coins > 0:
        pc_loot.append(MItem("кошель", min(1.0, 0.15 + coins / 40), kind="coin", amount=coins))
    best = max(((r["item_id"], _store().get_item(r["item_id"]))
                for r in _store().inventory(PLAY_WORLD, "pc")),
               key=lambda x: (x[1] or {}).get("worth", 0), default=(None, None))
    if best[1]:
        pc_loot.append(MItem(best[1]["name"], min(1.0, best[1]["worth"] / 40)))
        pc_map[best[1]["name"]] = best[0]
    w.add(Body(id=PLAYER, place=place, charisma=0.45, appearance=min(0.8, 0.25 + coins / 60),
               attention=0.85, loot=pc_loot))              # добыча игрока НАСТОЯЩАЯ (кража реальна)
    w.npc_minds = {pid: people[pid].state for pid in _here(loc, crof)}
    w.aliases = {v.lower(): k for k, v in names.items()}
    w.lookup = lambda q: _world_lookup(q, loc)             # тулкол know: знание мира по запросу
    personas = {}
    for pid in _here(loc, crof):                            # глубина: манера/причуда/стремления из банка
        per = people[pid].persona or {}
        bits = []
        if per.get("origin"):
            bits.append(per["origin"])
        if per.get("voice"):
            bits.append("говоришь " + _VOICE.get(per["voice"], "обычно"))
        if per.get("speech"):
            bits.append("манера: " + "; ".join(per["speech"][:2]))
        if per.get("quirk"):
            bits.append("причуда: " + per["quirk"])
        if per.get("wants"):
            bits.append("хочешь: " + "; ".join(per["wants"][:2]))
        if per.get("stance"):
            bits.append("к чужакам — " + _STANCE.get(per["stance"], "нейтрально"))
        if people[pid].work:
            bits.append("ты здесь НА РАБОТЕ — твой пост тут")
        if bits:
            personas[pid] = ". ".join(bits)
    here = _here(loc, crof)
    mgr = _model()
    todo = [pid for pid in here if not (people[pid].state.agendas or [])][:4]
    if todo:                                                # долгая цель для placed NPC (редкий вызов)
        def plan_one(pid):
            st = people[pid].state
            ag = (plan_agenda(st, w, {"roles": roles}, mgr) if mgr.available()
                  else StubPlanner().plan(st, w))
            if ag:
                st.agendas.append(ag)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(plan_one, todo))
    _S["live"] = {"world": w, "loc": loc, "place": place, "clock": 0, "ts": 0.0,
                  "who": frozenset(here), "pc_map": pc_map, "npc_map": npc_map,
                  "last": {}, "hist": {}, "names": names, "roles": roles, "personas": personas,
                  "pdesc": ((data or {}).get("notable") or "")}


def _gossip(actor_st, actor_name: str, target_st) -> None:
    """Разговор NPC↔NPC переносит яркое воспоминание — сплетни ходят, репутация возникает сама."""
    juicy = [m for m in actor_st.memory.items
             if m.importance >= 0.4 and (PLAYER in (m.about or []) or m.importance >= 0.6)]
    if not juicy:
        return
    m = juicy[-1]
    tale = f"{actor_name} рассказал(а) мне: {m.text}"
    if any(x.text == tale for x in target_st.memory.items[-30:]):
        return                                              # эту сплетню уже слышал
    target_st.memory.add(tale, _mt(), max(0.25, m.importance - 0.15), kind="gossip", about=m.about)


def _live_tick(people) -> tuple:
    lv, mgr = _S["live"], _model()
    w = lv["world"]
    order = [pid for pid in w.npc_minds
             if not w.bodies[pid].down() and w.bodies[pid].place == lv["place"]]
    random.Random(f"tick|{lv['clock']}").shuffle(order)
    ctx = {"roles": lv["roles"], "names": lv["names"], "last_actions": lv["last"],
           "history": lv["hist"], "clock": lv["clock"], "place_desc": {lv["place"]: lv["pdesc"]},
           "personas": lv.get("personas", {}),
           "time": f"{_PHASE_RU[_phase()]}, {_gt() // 60 % 24:02d}:{_gt() % 60:02d}"}

    def think_one(pid):                                     # решения параллельно, снимок мира один
        st = w.npc_minds[pid]
        _decay_needs(st)
        _decay_emotion(st)
        advance_agendas(st, w)                              # долгие цели двигаются
        return pid, decide_hybrid(st, w, mind_perceive(st, w), mgr, ctx)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        decisions = dict(ex.map(think_one, order))

    feed, address = [], []
    pc = _pc()
    for pid in order:                                       # применяем последовательно (честный порядок)
        d = decisions[pid]
        st = w.npc_minds[pid]
        before = {vid: {i.name for i in b.loot} for vid, b in w.bodies.items() if vid != pid}
        evs = apply_actions(d.get("actions") or [], st, w, lv["clock"])
        for vid, names_before in before.items():            # кражи РЕАЛЬНЫ (у игрока и NPC↔NPC)
            b = w.bodies.get(vid)
            stolen = names_before - ({i.name for i in b.loot} if b else set())
            for nm in stolen:
                if vid == PLAYER:
                    if nm == "кошель":
                        take = max(1, _pc_coins() // PB["purse_cut"])
                        _store().purse_add(PLAY_WORLD, "pc", -take)
                        _store().purse_add(PLAY_WORLD, pid, take)
                        feed.append({"k": "deed", "who": _display(pid, people),
                                     "text": f"ловко срезает твой кошель — минус {take} зм!"})
                        _pc_remember(f"у меня срезали кошель ({take} зм) — это был {_display(pid, people)}",
                                     0.8, about=[pid])
                    elif nm in (lv.get("pc_map") or {}):
                        _store().inv_move(PLAY_WORLD, lv["pc_map"][nm], pid)
                        feed.append({"k": "deed", "who": _display(pid, people),
                                     "text": f"вытягивает у тебя «{nm}»!"})
                        _pc_remember(f"у меня украли «{nm}»", 0.8, about=[pid])
                    st.memory.add(f"я обчистил(а) чужака: взял(а) {nm}", lv["clock"], 0.7, about=[PLAYER])
                else:
                    if nm == "кошель":
                        take = max(1, _store().purse_get(PLAY_WORLD, vid) // PB["purse_cut"])
                        _store().purse_add(PLAY_WORLD, vid, -take)
                        _store().purse_add(PLAY_WORLD, pid, take)
                    elif nm in (lv.get("npc_map", {}).get(vid) or {}):
                        _store().inv_move(PLAY_WORLD, lv["npc_map"][vid][nm], pid)
                    feed.append({"k": "deed", "who": _display(pid, people),
                                 "text": f"тянет что-то из добра ({_display(vid, people)}) — ты это ВИДИШЬ"})
                    st.memory.add(f"я взял(а) чужое ({nm}) у {lv['names'].get(vid, vid)}",
                                  lv["clock"], 0.6, about=[vid])
                    if vid in w.npc_minds:
                        w.npc_minds[vid].memory.add(f"меня обокрали — пропало {nm}", lv["clock"],
                                                    0.7, about=[pid])
                    _pc_remember(f"видел, как {_display(pid, people)} обокрал {_display(vid, people)}",
                                 0.5, about=[pid, vid])
        lv["last"][pid] = "; ".join(evs)[:80] or "—"
        lv["hist"].setdefault(pid, []).append("; ".join(evs)[:60])
        who = _display(pid, people)
        said = False
        for a in d.get("actions") or []:
            if isinstance(a, dict) and a.get("tool") == "say" and str(a.get("text") or "").strip():
                tgt = str(a.get("to") or "")
                tid = (w.aliases or {}).get(tgt.strip().lower(), tgt)
                txt = str(a["text"])[:180]
                said = True
                if tid == PLAYER:
                    address.append({"npc": pid, "who": who, "text": txt})
                    pc.memory.add(f"{who} обратился ко мне: «{txt[:100]}»", _mt(), 0.4, about=[pid])
                else:
                    feed.append({"k": "speech", "who": who,
                                 "to": _display(tid, people) if tid in people else tgt, "text": txt})
                    pc.memory.add(f"слышал в «{lv['place']}»: {who} — {txt[:90]}",
                                  _mt(), 0.18, kind="heard", about=[pid])
                    if tid in w.npc_minds:                  # сплетня перетекает собеседнику
                        _gossip(st, lv["names"].get(pid, pid), w.npc_minds[tid])
        does = (d.get("does") or "").strip()
        if does and not said:                               # реплика сама несёт момент — не дублируем
            feed.append({"k": "deed", "who": who, "text": does[:150]})
    lv["clock"] += 1
    _gt_add(PB["live_tick_min"])                            # тик мира (игровые минуты)
    _pc_save()
    for pid in order:                                       # прожитое переживает рестарт
        _npc_save(pid)
    return feed, address


@router.post("/api/play/live")
async def live(request: Request):
    """Пульс живой локации: один тик мира (все NPC ходят гибридным мозгом). Клиент поллит."""
    import time as _time
    city, people, crof, cr2b, loc = _play()
    lv = _S.get("live")
    if not lv or lv["loc"] != loc or lv.get("who") != frozenset(_here(loc, crof)):
        _live_build(city, people, crof, cr2b, loc)         # локация сменилась ИЛИ распорядок сменил людей
        lv = _S["live"]
    now = _time.monotonic()
    if now - lv["ts"] < _LIVE_GAP:
        return {"feed": [], "address": [], "clock": lv["clock"], "gt": _gt()}
    lv["ts"] = now
    try:
        feed, address = _live_tick(people)
    except Exception as exc:                               # noqa: BLE001 — пульс не должен ронять клиент
        return {"feed": [], "address": [], "clock": lv["clock"], "gt": _gt(), "error": str(exc)[:160]}
    return {"feed": feed, "address": address, "clock": lv["clock"], "gt": _gt()}
