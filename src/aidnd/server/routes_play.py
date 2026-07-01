"""Бэкенд пилота /play на НОВОМ стеке: citygraph (город+карта) + play.populate (жители с мозгами
mind) + LLM-озвучка (inference, офлайн-стаб). Процессная пилот-сессия (один мир, одна фигура игрока).

Карта РЕАЛЬНАЯ и полная: все улицы+дома+река+стены; ходим по ключевым точкам (перекрёсткам) с
пути-поиском (route). «Кто здесь» зависит от перекрёстка. Карточка NPC — отношение/эмоция ИЗ МОЗГА.
"""

from __future__ import annotations

import hashlib
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
from ..mind import World as MWorld
from ..mind import think
from ..play import populate
from ..play.population import KEY_ROLES, Townsperson
from ..worldgen import WorldStore

router = APIRouter(tags=["play"])
PLAYER = "pc"
PLAY_WORLD = 1                       # id пилотного мира для привязок пула (placements)
_STORE: WorldStore | None = None


def _store() -> WorldStore:
    global _STORE
    if _STORE is None:
        _STORE = WorldStore()
    return _STORE
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


def _person_from_row(row: dict, home: int, work: str | None) -> Townsperson:
    """Готовый NPC из банка → Townsperson с мозгом (mind) + богатой персоной/портретами."""
    mech = row.get("mech") or {}
    cfg = NpcConfig(id=row["id"], name=row["name"], role=row["role"],
                    traits=mech.get("traits") or {}, abilities=mech.get("abilities") or {})
    st = NpcState.from_config(cfg)
    r = random.Random(row["id"])                           # лёгкий фон нужд, детерминированно
    for n in st.needs:
        st.needs[n] = round(r.uniform(0.1, 0.35), 2)
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
        start = next((spot[pid] for pid, p in people.items() if p.role == "трактирщик"),
                     keynode.get(sorted(city.key_buildings)[0]) if city.key_buildings else kps[0])
        _S.update(city=city, people=people, crof=spot, cr2b=n2b, loc=start,
                  geom=_build_geom(city, xy, n2b, vis))
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
        "ambient": {"time": "вечер", "weather": "дождь", "mood": "оживлённо" if len(here) > 2 else "тихо",
                    "event": "Народ занят своими делами." if here else "Пусто; лишь ветер гуляет меж домов."},
        "here": [{"id": pid, "name": people[pid].name, "role": people[pid].role,
                  "init": people[pid].name[0], "color": _COLORS[i % len(_COLORS)],
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
    bits.append(f"Симпатия к собеседнику {rel.get('affinity', 0):.2f} (низкая — суше/настороже, высокая — теплее). "
                "Отвечай В ХАРАКТЕРЕ, живой разговорной речью, 1-2 фразы, без ремарок-описаний.")
    user = ("К тебе подошёл незнакомец и заговорил — брось первую реплику." if kind == "greet"
            else f"Он говорит: «{player_text}». Ответь.")
    resp = mgr.call("narrator", [{"role": "system", "content": " ".join(bits)},
                                 {"role": "user", "content": user}], options={"temperature": 0.85})
    return (resp.get("content") if resp else "").strip() or f"{p.name} молчит."


@router.get("/api/play/scene")
def scene():
    city, people, crof, cr2b, loc = _play()
    return _scene_dict(city, people, crof, cr2b, loc)


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
    sc = _scene_dict(city, people, crof, cr2b, to)
    return {**sc, "path": path, "moved": sc["location"]["name"]}


@router.post("/api/play/talk")
async def talk(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    st = p.state
    st.needs["social"] = max(st.needs.get("social", 0.0), 0.4)
    think(st, _mind_scene(npc, people), None)
    rel = st.relationships.get(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    per = p.persona or {}
    emo = _emo(st)
    ports = {e: "/portraits/" + path for e, path in (p.portraits or {}).items()
             if os.path.exists(os.path.join(_PORT_DIR, path))}
    return {"name": p.name, "role": p.role, "init": p.name[0], "color": "#8a6fae",
            "aff": round(rel.get("affinity", 0), 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": emo,
            "portrait": _portrait_url(p, emo), "portraits": ports,
            "sex": per.get("sex"), "age": per.get("age"), "origin": per.get("origin"),
            "look": (per.get("look") or {}).get("clothing") or None,
            "keys": [k["name"] for k in (p.keys or [])],
            "crafter": p.role in _CRAFT, "recipe": (_CRAFT[p.role].name if p.role in _CRAFT else None),
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
    line = _voice(p, rel, "reply", str(b.get("text", "")))
    emo = _emo(p.state)
    return {"line": line, "aff": round(rel["affinity"], 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": emo, "portrait": _portrait_url(p, emo)}


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
