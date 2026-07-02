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
from ..items import Capability, ItemCtx, LLMSmith, Recipe, StubSmith
from ..items import condition as item_condition
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
from ..play.population import KEY_ROLES, Townsperson
from ..worldgen import WorldStore

router = APIRouter(tags=["play"])
PLAYER = "pc"
PLAY_WORLD = 1                       # id пилотного мира для привязок пула (placements)
_STORE: WorldStore | None = None
_GT0 = 19 * 60 + 40                  # старт: вечер 19:40


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
_PLACE = {
    "трактирщик": ("Трактир «Пьяный вепрь»", "таверна · тепло, тесно, дымно", "трактир"),
    "кузнец": ("Кузница", "жар горна, звон молота", "кузница"),
    "лавочник": ("Лавка", "полки со всякой всячиной", "лавка"),
    "стражник": ("Караулка", "пост городской стражи", "стража"),
    "жрец": ("Святилище", "тихо, пахнет ладаном", "храм"),
    "знахарка": ("Дом знахарки", "пучки трав, склянки", "знахарка"),
    "бард": ("Помост", "здесь поют и судачат", "помост"),
    "мельник": ("Мельница", "мерный скрип у воды", "мельница"),
}
_TOPICS = {
    "трактирщик": ["слухи", "что налить", "заказ комнаты", "о дорогах"],
    "бард": ["спой что-нибудь", "новости с трактов", "кто тут кто"],
    "лавочник": ["что на продажу", "цена", "редкости"],
    "кузнец": ["почини снаряжение", "есть работа", "о железе"],
    "жрец": ["благословение", "о богах", "исцеление"],
    "знахарка": ["зелья", "травы", "о хворях"],
    "стражник": ["что тут за место", "есть розыск", "о законе"],
    "бродяга": ["чего пялишься", "есть работа?"],
    "головорез": ["чего надо", "проваливай"],
    "горожанин": ["как дела", "что нового", "о городе"],
}


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
        if phase in ("evening", "night") and tavern is not None and rng.random() < 0.4:
            return tavern
        return rng.choice(kps) if kps else p.home
    if p.work:                                              # работник: пост днём, вечером трактир/дом
        wn = keynode.get(p.work, p.home)
        if phase in ("morning", "day"):
            return wn
        if phase == "evening":
            if p.role == "трактирщик":
                return wn                                   # трактирщик вечером на посту
            return tavern if (tavern is not None and rng.random() < 0.5) else p.home
        return p.home
    if phase == "morning":                                  # горожанин
        return p.home if rng.random() < 0.5 else (rng.choice(kps) if kps else p.home)
    if phase == "day":
        return rng.choice(kps) if kps else p.home
    if phase == "evening":
        return tavern if (tavern is not None and rng.random() < 0.45) else p.home
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

    def place(row, node, work):
        people[row["id"]] = _person_from_row(row, node, work)
        spot[row["id"]] = node
        store.place_person(PLAY_WORLD, row["id"], node, node, work)

    for i, (bid, kb) in enumerate(sorted(city.key_buildings.items())):
        row = draw(KEY_ROLES[i % len(KEY_ROLES)])
        if row:
            place(row, kb.node, bid)
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
    for i, (bid, kb) in enumerate(sorted(city.key_buildings.items())):
        role = KEY_ROLES[i % len(KEY_ROLES)]
        keys.append({"node": kb.node, "x": round(kb.x, 1), "y": round(kb.y, 1),
                     "label": _PLACE.get(role, (None, None, "здание"))[2]})
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
    if role:
        name, kind, _ = _PLACE[role]
    elif city.node_kind(loc) == NodeKind.CROSSROAD:
        name, kind = "Перекрёсток", "городская развилка"
    else:
        name, kind = "Улица", "мостовая меж домов"
    here = sorted(_here(loc, crof), key=lambda i: (people[i].work is None, i))
    bid = cr2b.get(loc)
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
    return {**_scene_dict(city, people, crof, cr2b, loc), "gt": _gt()}


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
    _gt_add(max(1, len(path) - 1))                         # шаг пути = 1 игровая минута (граф густой)
    _apply_routine()                                       # за дорогу мир мог перейти в другую фазу
    sc = _scene_dict(city, people, crof, cr2b, to)
    return {**sc, "path": path, "moved": sc["location"]["name"], "gt": _gt()}


@router.post("/api/play/talk")
async def talk(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    first = npc not in _met()
    _pc().rel(npc)                                     # заговорил = познакомился (имя открыто)
    _gt_add(2)
    st = p.state
    st.needs["social"] = max(st.needs.get("social", 0.0), 0.4)
    think(st, _mind_scene(npc, people), None)
    if first:                                          # знакомство ложится в память ОБОИМ
        st.memory.add("незнакомец (игрок) подошёл и заговорил со мной", _mt(), 0.4, about=[PLAYER])
        _pc_remember(f"я познакомился с {p.name} ({p.role})", 0.45, about=[npc])
        _npc_save(npc)
    rel = st.relationships.get(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    per = p.persona or {}
    emo = _emo(st)
    ports = {e: "/portraits/" + path for e, path in (p.portraits or {}).items()
             if os.path.exists(os.path.join(_PORT_DIR, path))}
    known = [m.text for m in _pc().memory.recall(f"{p.name} {p.role}", now=_mt(), k=3)
             if npc in (m.about or [])]                    # что игрок ЗНАЕТ об этом человеке
    return {"name": p.name, "role": p.role, "init": p.name[0], "color": "#8a6fae",
            "aff": round(rel.get("affinity", 0), 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": emo,
            "portrait": _portrait_url(p, emo), "portraits": ports,
            "sex": per.get("sex"), "age": per.get("age"), "origin": per.get("origin"),
            "look": (per.get("look") or {}).get("clothing") or None,
            "keys": [k["name"] for k in (p.keys or [])],
            "crafter": p.role in _CRAFT, "recipe": (_CRAFT[p.role].name if p.role in _CRAFT else None),
            "known": known, "gt": _gt(),
            "topics": _TOPICS.get(p.role, _TOPICS["горожанин"]), "line": _voice(p, rel, "greet")}


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
    _gt_add(2)
    line = _voice(p, rel, "reply", text)
    p.state.memory.add(f"игрок сказал мне: «{text[:100]}», я ответил(а): «{line[:100]}»",
                       _mt(), 0.4, about=[PLAYER])         # диалог остаётся в памяти NPC
    _pc_remember(f"{p.name} на «{text[:60]}» ответил(а): «{line[:90]}»", 0.35, about=[npc])
    _npc_save(npc)
    emo = _emo(p.state)
    return {"line": line, "aff": round(rel["affinity"], 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": emo, "portrait": _portrait_url(p, emo),
            "gt": _gt()}


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


# рецепт по ремеслу NPC — что он берётся сковать/сварить
_CRAFT = {
    "кузнец": Recipe("weapon", "нож", "anvil", 8, 40, 10, "main_hand", "attack"),
    "знахарка": Recipe("consumable", "целебный отвар", "cauldron", 12, 6, 11, "none", "special:heal"),
    "сапожник": Recipe("armor", "сапоги", "bench", 14, 50, 11, "body", "social:appearance"),
    "дубильщик": Recipe("armor", "кожаный жилет", "tannery", 10, 45, 11, "body", "defense"),
    "лавочник": Recipe("trinket", "затейливая безделица", "bench", 6, 20, 12, "worn", ""),
    "трактирщик": Recipe("consumable", "кружка крепкого", "cauldron", 2, 4, 8, "none", ""),
    "мельник": Recipe("material", "мешок доброй муки", "bench", 3, 10, 9, "none", ""),
}


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
    if full.get("access") == "locked":
        return {"error": "заперто — нужен ключ"}
    inv = {r["item_id"]: set(r["known"]) for r in _store().inventory(PLAY_WORLD)}
    out = []
    for i, s in enumerate(full.get("contents") or []):
        it = _forge(f"{PLAY_WORLD}|{bid}|{name}|{i}", "misc", s, f"{name} ({full['kind']})")
        _store().inv_add(PLAY_WORLD, it["id"])
        out.append(_item_card(it, inv.get(it["id"], set())))
    return {"container": name, "items": out}


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


# ------------------------------------------- ЖИВАЯ ЛОКАЦИЯ (mind + LLM) --- #
# NPC текущей локации живут по-настоящему: каждый тик КАЖДЫЙ решает ходом гибридного мозга
# (механика даёт побуждения → LLM выбирает В ХАРАКТЕРЕ, пишет реплику и описание). Действия
# реальны (apply_actions мутирует мир и память), фид — то, что игрок видит/слышит; незнакомцы
# обезличены дескриптором, имя открывается знакомством (talk).
_LIVE_GAP = 6.0                                    # мин. сек между тиками (защита от бури поллов)


def _world_lookup(query: str, from_node: int | None = None) -> str:
    """Справка мира для тулкола know/ask: здания (с дорогой от точки), люди (местные знают местных).
    Отвечает ТОЛЬКО реальными фактами графа/пула — не даёт LLM галлюцинировать о городе."""
    city, people = _S.get("city"), _S.get("people") or {}
    if city is None:
        return "не припомню"
    q, outs = query.lower(), []
    for i, (bid, kb) in enumerate(sorted(city.key_buildings.items())):
        role = KEY_ROLES[i % len(KEY_ROLES)]
        nm = _PLACE.get(role, ("здание", "", ""))[0]
        if role in q or any(w in q for w in nm.lower().replace("«", " ").replace("»", " ").split() if len(w) > 3):
            if from_node is not None:
                r = city.route(from_node, kb.node)
                if r.found:
                    outs.append(f"{nm}: {r.bearing or 'недалеко'}, ~{max(1, len(r.nodes) - 1)} мин ходу")
                    continue
            outs.append(nm)
    for pid, p in sorted(people.items()):
        first = p.name.split()[0].lower()
        if p.role in q or first in q or p.name.lower() in q:
            place = next((_PLACE.get(KEY_ROLES[i % len(KEY_ROLES)], ("", "", ""))[0]
                          for i, (bid, _kb) in enumerate(sorted(city.key_buildings.items()))
                          if bid == p.work), None)
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
    role = _role_at(loc, people, crof, cr2b)
    place = _PLACE[role][0] if role else "улица"
    bid = cr2b.get(loc)
    data = ((_store().get_building(PLAY_WORLD, bid) or {}).get("data")) if bid else {}
    w = MWorld()
    w.link(place, "улица")
    w.ground[place] = _live_affordances(bid)
    names, roles = {PLAYER: "чужак"}, {PLAYER: "недавно вошедший незнакомец"}
    rng = random.Random(f"live|{loc}")
    for pid in _here(loc, crof):
        p = people[pid]
        w.add(Body(id=pid, place=place, charisma=p.charisma, appearance=p.appearance,
                   attention=round(rng.uniform(0.45, 0.85), 2),
                   loot=[MItem("кошель", round(0.2 + p.appearance * 0.6, 2), kind="coin",
                               amount=round(3 + p.appearance * 30))] if p.appearance >= 0.3 else []))
        names[pid], roles[pid] = p.name, p.role
    w.add(Body(id=PLAYER, place=place, charisma=0.45, appearance=0.35, attention=0.85,
               loot=[MItem("кошель", 0.4, kind="coin", amount=12)]))
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
                  "who": frozenset(here),
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
           "personas": lv.get("personas", {})}

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
        evs = apply_actions(d.get("actions") or [], st, w, lv["clock"])
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
    _gt_add(3)                                              # тик мира = 3 игровые минуты
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
