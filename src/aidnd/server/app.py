"""L9 Presentation: FastAPI + WebSocket (main §11).

Backend держит живое состояние (event log на сервере), шлёт дельты и нарратив,
фронт рендерит. Никакого browser storage — всё состояние на сервере. Броски —
server-authoritative animated (док 07 §8): сервер кидает, клиент анимирует.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import config
from ..bootstrap import new_session
from ..rules.dice import roll_expr
from . import auth as _svc_auth
from . import games as _svc_games
from . import usage as _svc_usage
from .db import SessionLocal
from .routes_auth import router as _auth_router
from .routes_games import router as _games_router
from .routes_usage import router as _usage_router

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
app = FastAPI(title="AI-DnD Engine")
app.include_router(_auth_router)
app.include_router(_games_router)
app.include_router(_usage_router)


@app.on_event("startup")
async def _init_service_db() -> None:
    """Создать таблицы сервиса. БД недоступна → анонимный демо-режим всё равно работает."""
    try:
        from .db import init_db
        await init_db()
    except Exception as exc:                       # noqa: BLE001
        import logging
        logging.getLogger("aidnd").warning("service DB unavailable (%s) — auth disabled", exc)


@app.middleware("http")
async def _no_cache(request, call_next):
    """Не кэшировать статику (dev): preview всегда берёт свежие JS/CSS/карты."""
    resp = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/login")
def login_page() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "login.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


# --------------------------------------------------------------------------- #
#  Интерфейс правки диалоговых кейсов: реплики + ожидаемый результат           #
# --------------------------------------------------------------------------- #
@app.get("/eval")
def eval_page() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "eval.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/eval/cases")
def eval_cases():
    from ..eval.conversations import load_raw_cases
    return {"cases": load_raw_cases()}


@app.post("/eval/save")
async def eval_save(request: Request) -> dict:
    from ..eval.conversations import save_cases
    data = await request.json()
    save_cases(data.get("cases", []))
    return {"saved": len(data.get("cases", []))}


@app.get("/map")
def map_page() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "map.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/city")
def city_page() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "city.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/world")
def world_page() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "world.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/new_game_options")
def new_game_options() -> dict:
    """Списки классов, стартового снаряжения и сценариев для экрана новой игры."""
    from ..content.newgame import options
    return options()


@app.get("/patchnotes")
def patchnotes() -> dict:
    """Версия игры + новостной раздел (патчноут) для верхней панели."""
    from ..content.patchnotes import feed
    return feed()


@app.get("/saves")
def saves_list() -> dict:
    from ..runtime.persistence import list_saves
    return {"saves": list_saves()}


def _town_buildings(session) -> list:
    """Здания города из сессии (с актуальным status — отражает мутации событиями)."""
    ml = session.map_levels()
    town = next((lvl for lvl in ml["levels"] if lvl["id"] == "town"), {"nodes": []})
    sp = session.world.spatial
    buildings = []
    for n in town["nodes"]:
        p = sp.places.get(n["id"])
        buildings.append({"id": n["id"], "name": n["name"], "kind": n["kind"],
                          "dir": n.get("dir_ru", ""), "dx": n["dx"], "dy": n["dy"],
                          "affordances": list(p.affordances) if p else [],
                          "go": n.get("go"), "status": getattr(p, "status", "open") if p else "open"})
    return buildings


@app.get("/town_layout")
def town_layout(seed: int = config.WORLD_SEED) -> dict:
    """Список достопримечательностей города (здания+направления) для процедурной
    карты: реальные узлы графа якорят сгенерированный город (улицы/дома)."""
    session = new_session(seed=seed, roster_size=12, use_model=False)
    return {"seed": int(seed), "settlement": "Фэндалин", "buildings": _town_buildings(session)}


# --------------------------------------------------------------------------- #
#  Процедурный город на Python (SVG) с выбором дома                            #
# --------------------------------------------------------------------------- #
_CITYGEN = None


def _citygen():
    """Ленивая загрузка self-contained модуля web/citygen.py."""
    global _CITYGEN
    if _CITYGEN is None:
        spec = importlib.util.spec_from_file_location("citygen", os.path.join(WEB_DIR, "citygen.py"))
        _CITYGEN = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_CITYGEN)
    return _CITYGEN


@app.get("/city_svg")
def city_svg(seed: int = config.WORLD_SEED, w: int = 980, h: int = 700, page: int = 0):
    """Интерактивный SVG города. Клик по дому → яркое выделение + событие cityHouse(id).
    page=1 → готовая HTML-страница (для iframe), которая шлёт выбор в parent через postMessage."""
    cg = _citygen()
    layout = town_layout(seed)
    blds = [{"kind": "building", "dx": b["dx"], "dy": b["dy"], "name": b["name"],
             "affordances": b.get("affordances", []), "go": b.get("go"), "id": b["id"]}
            for b in layout["buildings"]]
    m = cg.build_city(int(seed), int(w), int(h), buildings=blds, title=layout["settlement"])
    if not m:
        return Response("<svg/>", media_type="image/svg+xml")
    svg = cg.render_svg(m, interactive=True)
    if page:
        return HTMLResponse(
            '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">'
            '<style>body{margin:0;background:#15161a}svg{max-width:100vw;height:auto;display:block}</style>'
            "</head><body>" + svg +
            '<script>window.addEventListener("cityHouse",function(e){'
            'try{parent.postMessage({type:"cityHouse",id:e.detail.id},"*");}catch(_){}'
            '});</script></body></html>')
    return Response(svg, media_type="image/svg+xml")


_CITY_FULL_CACHE: dict = {}


def _city_blds(buildings: list) -> list:
    """Здания → формат citygen.build_city (с status, чтобы карта показывала закрытые/руины/новые)."""
    return [{"kind": "building", "dx": b["dx"], "dy": b["dy"], "name": b["name"],
             "affordances": b.get("affordances", []), "go": b.get("go"), "id": b["id"],
             "status": b.get("status", "open")} for b in buildings]


def _session_with_incidents(seed: int, tick: int):
    """Свежая сессия, в которой СРАБОТАЛИ мутации карты от событий с spawn_tick ≤ tick
    (закрытия/руины/новые локации). Детерминированно по расписанию → город «как на тике»."""
    from ..runtime import incidents as inc
    session = new_session(seed=int(seed), roster_size=12, use_model=False)
    sched = _INCIDENT_SCHED_CACHE.get(int(seed))
    if sched is None:
        _s, factions, sites, digest = _incident_world(seed)
        sched = inc.build_schedule(factions, sites, int(seed), 0, 200, model=_incident_model(), digest=digest)
        _INCIDENT_SCHED_CACHE[int(seed)] = sched
    for sp in sched:
        chg = (sp.effects or {}).get("change")
        if chg and chg.get("action") and sp.spawn_tick <= tick:
            session.world.commit("place_change", "incident", payload=chg)
    return session


@app.get("/city_full")
def city_full(seed: int = config.WORLD_SEED, w: int = 980, h: int = 700, keys: str = "", tick: int = -1):
    """JSON для встраивания в игровую карту: интерактивный SVG + hits/legend/streets.
    tick≥0 → город отражает мутации от событий (закрытые лавки, руины, новые локации) на этом тике."""
    ckey = (int(seed), int(w), int(h), keys, int(tick))
    cached = _CITY_FULL_CACHE.get(ckey)
    if cached is not None:
        return cached
    key_houses = []
    if keys:
        try:
            key_houses = json.loads(keys)
        except Exception:
            key_houses = []
    cg = _citygen()
    if tick >= 0:
        buildings = _town_buildings(_session_with_incidents(seed, tick))
    else:
        buildings = town_layout(seed)["buildings"]
    m = cg.build_city(int(seed), int(w), int(h), buildings=_city_blds(buildings),
                      key_houses=key_houses, title="Фэндалин")
    if not m:
        return {"svg": "<svg/>", "hits": [], "legend": [],
                "streets": {"nodes": [], "adj": [], "start": 0}}
    out = {"svg": cg.render_svg(m, interactive=True, marks=False), "hits": m["hits"],
           "legend": m["legend"], "streets": m["streets"]}
    _CITY_FULL_CACHE[ckey] = out
    return out


_INCIDENT_GEOM_CACHE: dict = {}


def _incident_geometry(seed: int, w: int, h: int) -> dict:
    """Геометрия города для слоя инцидентов: place_id→xy (лендмарки), ворота, центр.
    Кэшируется, чтобы скраббер тиков не пересобирал город на каждый кадр."""
    key = (int(seed), int(w), int(h))
    geom = _INCIDENT_GEOM_CACHE.get(key)
    if geom is None:
        cg = _citygen()
        layout = town_layout(seed)
        blds = [{"kind": "building", "dx": b["dx"], "dy": b["dy"], "name": b["name"],
                 "affordances": b.get("affordances", []), "go": b.get("go"), "id": b["id"]}
                for b in layout["buildings"]]
        m = cg.build_city(int(seed), int(w), int(h), buildings=blds, title=layout["settlement"])
        if not m:
            geom = {"place_xy": {}, "gates": [], "center": [w / 2, h / 2]}
        else:
            geom = {"place_xy": {L["id"]: [L["x"], L["y"]] for L in m["legend"]},
                    "gates": [r[0] for r in m.get("roads_out", [])],
                    "center": [m["CX"], m["CY"]]}
        _INCIDENT_GEOM_CACHE[key] = geom
    return geom


_INCIDENT_SCHED_CACHE: dict = {}
_INCIDENT_MODEL = {"mm": None}


def _incident_model():
    """ModelManager для LLM-режиссёра (сессии слоя инцидентов идут use_model=False ради
    скорости — состояние от модели не зависит, а расписание берёт модель отдельно)."""
    if _INCIDENT_MODEL["mm"] is None:
        from ..inference import ModelManager
        _INCIDENT_MODEL["mm"] = ModelManager()
    return _INCIDENT_MODEL["mm"]


def _incident_world(seed: int):
    """Состояние мира для слоя инцидентов: фракции, сайты, дайджест для LLM-режиссёра."""
    from ..content.region import REGION_SITES
    session = _city_session(seed)
    w = session.world
    factions = [{"id": fid, "name": getattr(f, "name", fid),
                 "goals": list(getattr(f, "goals", []) or []),
                 "controls": list(getattr(f, "controls", []) or []),
                 "members": list(getattr(f, "members", []) or []),
                 "relations": dict(getattr(f, "relations", {}) or {})}
                for fid, f in w.factions.items()]
    sites = [{"key": k, "place": v.get("place"), "danger": v.get("danger"),
              "label": v.get("label", k)} for k, v in REGION_SITES.items()]

    def pn(pid):
        p = w.spatial.places.get(pid)
        return p.name if p else pid
    lines = ["Фракции (id, имя, бойцов, территория place_id, враги):"]
    for f in factions:
        terr = "; ".join(f"{c} ({pn(c)})" for c in f["controls"][:3]) or "—"
        rivals = ", ".join(f"{o}({v:+.1f})" for o, v in f["relations"].items() if v < -0.1) or "нет"
        lines.append(f"  - {f['id']} «{f['name']}»: {len(f['members'])} чел.; терр: {terr}; враги: {rivals}")
    lines.append("Опасные места (ключ для origin 'gate:<ключ>', опасность):")
    for s in sites[:8]:
        lines.append(f"  - {s['key']} «{s['label']}» — {s['danger']}")
    flags = list(getattr(w, "flags", []) or [])[:10]
    if flags:
        lines.append("Флаги мира: " + ", ".join(flags))
    return session, factions, sites, "\n".join(lines)


@app.get("/city_incidents")
def city_incidents(seed: int = config.WORLD_SEED, tick: int = 0, w: int = 980, h: int = 700):
    """Слой инцидентов на тике: активные события (фракции/монстры/политика/катаклизмы) с
    координатами/радиусом/интенсивностью + пересечения. Расписание строит LLM-режиссёр из
    состояния мира (этап 2; фоллбэк — детерминированные правила) и КЭШИРУЕТСЯ по seed, поэтому
    скраббер тиков детерминирован и не дёргает модель на каждый кадр."""
    from ..runtime import incidents as inc
    geom = _incident_geometry(seed, w, h)
    session, factions, sites, digest = _incident_world(seed)
    sched = _INCIDENT_SCHED_CACHE.get(int(seed))
    if sched is None:
        sched = inc.build_schedule(factions, sites, int(seed), 0, 200,
                                   model=_incident_model(), digest=digest)
        _INCIDENT_SCHED_CACHE[int(seed)] = sched
    return inc.simulate(sched, geom["place_xy"], geom["gates"], geom["center"],
                        factions, int(seed), int(tick))


# кэш сессий по сиду: чтобы материализация дома сохранялась в памяти между запросами
_CITY_SESSIONS: dict[int, object] = {}


def _city_session(seed: int):
    s = _CITY_SESSIONS.get(seed)
    if s is None:
        s = new_session(seed=seed, roster_size=12, use_model=False)
        _CITY_SESSIONS[seed] = s
    return s


@app.get("/materialize")
def materialize_house(seed: int = config.WORLD_SEED, place: str = "", kind: str = "") -> dict:
    """Ленивая материализация наполнения конкретного дома + сохранение в память.
    Повтор по тому же дому возвращает то же содержимое (recorded=True)."""
    if not place:
        return {"error": "no place"}
    return _city_session(seed).discovery.materialize_interior(place, kind_hint=kind or None)


@app.get("/city_event")
def city_event(seed: int = config.WORLD_SEED, step: int = 0, quiet: int = 2,
               loc: str = "frontier_town") -> dict:
    """Шаг прогулки по городу → нарративный дизайнер (director) с вероятностью, растущей
    от затишья (quiet), выдаёт случайный бит или ничего. Детерминирован по seed+step."""
    s = _city_session(seed)
    beat = s.director.ambient_beat(int(seed), int(step), f"city:{step}", loc,
                                   s.scene_context(), int(quiet), True)
    return {"beat": beat}


@app.get("/agentsim")
def agent_sim(seed: int = config.WORLD_SEED, rounds: int = 6) -> dict:
    """Наблюдение за агентами: NPC сами выбирают исходящие команды по утилите и взаимодействуют друг с другом
    (общение / сплетни / стычки), мнения диффундируют по сети. Детерминирован по seed (свежая офлайн-сессия)."""
    from ..content import agent
    s = new_session(seed=int(seed), roster_size=12, use_model=False)
    events = agent.step_social(s.world, rounds=int(rounds))
    return {"seed": int(seed), "rounds": int(rounds), "count": len(events), "events": events}


@app.get("/region_map")
def region_map_dump(seed: int = config.WORLD_SEED, do: str = "", gold: int = 0) -> dict:
    """Генератор снимка карты: свежая сессия (seed), опц. список команд `do`
    (через «;») и опц. подкрутка золота `gold` для демонстрации покупок сведений.
    Возвращает region_map() — то, по чему рисует страница /map (любой момент партии)."""
    session = new_session(seed=seed, roster_size=12, use_model=False)
    if gold > 0:
        session.world.wallet("pc:hero").update({"gp": gold})
    for cmd in (c.strip() for c in do.split(";")):
        if cmd:
            session.handle(cmd)
    return session.region_map()


@app.post("/eval/run")
async def eval_run(request: Request) -> dict:
    from ..eval.conversations import run_case_dict, transcript_to_dict
    from ..inference import ModelManager
    case = await request.json()
    use_model = ModelManager().available()
    t = run_case_dict(case, use_model=use_model)
    return {"online": use_model, "transcript": transcript_to_dict(t)}


def _auto_roll(rr: dict, salt: int) -> list[int]:
    from ..gen.seeds import subseed  # стабильный сид (не builtin hash)
    seed = subseed(0, rr["request_id"], salt) & 0x7FFFFFFF
    return roll_expr(rr["request_id"], rr["dice"], seed, source="server_ui").raw


_active = {"n": 0}
_MAX_SESSIONS = int(os.environ.get("AIDND_MAX_SESSIONS", "2"))  # демо на одной GPU: ограничить наплыв
_badge_mgr = None


def _model_online() -> bool:
    """Доступна ли модель — для бейджа на стартовом меню (без сборки сессии). Кешируется."""
    global _badge_mgr
    try:
        from ..inference import ModelManager
        if _badge_mgr is None:
            _badge_mgr = ModelManager()
        return _badge_mgr.available()
    except Exception:
        return False


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    salt = {"n": 1}
    holds = {"slot": False}                               # слот гейтит ГЕНЕРАЦИЮ (GPU), не коннект

    me = {"user": None}                                   # авторизация по cookie сессии (или ?token=)
    _tok = sock.cookies.get("aidnd_session", "") or sock.query_params.get("token", "")
    if _tok:
        try:
            async with SessionLocal() as _db:
                me["user"] = await _svc_auth.user_for_token(_db, _tok)
        except Exception:                                 # БД недоступна → анонимно
            me["user"] = None

    async def send(result: dict) -> None:
        await sock.send_text(json.dumps(result, ensure_ascii=False, default=str))

    async def start_menu() -> None:                       # при заходе — всегда явное меню, без фоновой сборки
        payload = {"kind": "menu", "server_online": _model_online()}
        if me["user"]:                                    # юзер → его игры из БД
            async with SessionLocal() as _db:
                payload["games"] = await _svc_games.list_games(_db, me["user"].id)
            payload["user"] = {"id": me["user"].id, "email": me["user"].email,
                               "name": me["user"].display_name}
            payload["usage"] = _svc_usage.snapshot(me["user"])   # шкала лимитов
        else:                                             # аноним → файловые сейвы (как было)
            from ..runtime.persistence import list_saves
            payload["saves"] = list_saves()
        await send(payload)

    def acquire_slot() -> bool:                           # занять слот под генерацию; False — занято
        if holds["slot"]:
            return True
        if _active["n"] >= _MAX_SESSIONS:
            return False
        _active["n"] += 1
        holds["slot"] = True
        return True

    session = None
    await start_menu()
    try:
        while True:
            msg = json.loads(await sock.receive_text())
            cmd = msg.get("cmd")
            if cmd in ("new_game", "new", "load") and not acquire_slot():   # генерация — под слот GPU
                await send({"kind": "system", "text": "Сервер сейчас занят, зайди чуть позже."})
                continue
            if session is None and cmd not in ("new_game", "new", "load", "delete_save", "redeem"):
                await start_menu()                        # игры ещё нет — возвращаем меню (без неявной сборки)
                continue
            if cmd == "redeem":                           # код разблокировки безлимита (меню настроек)
                if not me["user"]:
                    result = {"kind": "auth_required", "text": "Войдите, чтобы ввести код."}
                else:
                    async with SessionLocal() as _db:
                        _ok, _u = await _svc_usage.redeem(_db, me["user"].id, msg.get("code", ""))
                    me["user"] = _u
                    result = {"kind": "redeem", "ok": _ok, "usage": _svc_usage.snapshot(_u),
                              "text": "Безлимит активирован!" if _ok else "Код неверный или уже использован."}
            elif cmd == "input":
                if not me["user"]:                        # игра требует входа (лимиты на аккаунт)
                    await send({"kind": "auth_required", "text": "Войдите, чтобы играть."})
                    continue
                async with SessionLocal() as _db:         # списать 1 игровой запрос из лимита
                    _ok, _u = await _svc_usage.consume_request(_db, me["user"].id)
                me["user"] = _u
                if not _ok:
                    await send({"kind": "limit", "what": "requests", "usage": _svc_usage.snapshot(_u),
                                "text": "Бесплатные запросы кончились — введите код в настройках."})
                    continue
                loop = asyncio.get_running_loop()         # ход в треде → стримим «мышление» в реальном времени
                chain = []
                def _think(role, model):                  # каждый LLM-вызов хода → кадр прогресса/роутинга
                    chain.append({"role": role, "model": model})
                    asyncio.run_coroutine_threadsafe(
                        send({"kind": "thinking", "step": len(chain), "est": 5, "chain": list(chain)}), loop)
                mgr = session.model
                if mgr is not None:
                    mgr.on_call = _think
                try:
                    result = await asyncio.to_thread(session.handle, msg.get("text", ""))
                finally:
                    if mgr is not None:
                        mgr.on_call = None
            elif cmd == "look":
                result = session.look_around()            # осмотр + видимые вывески вокруг
            elif cmd == "record_signs":                   # «галочка»: записать увиденные вывески на карту
                result = session._record_signs()
            elif cmd == "combat_attack":
                result = session.combat_attack(msg["target"])
            elif cmd == "combat_move":
                result = session.combat_move(msg["cell"])
            elif cmd == "combat_action":
                result = session.combat_action(msg.get("action"), target=msg.get("target"),
                                               cell=msg.get("cell"), spell=msg.get("spell"))
            elif cmd == "combat_end_turn":
                result = session.combat_end_turn()
            elif cmd == "roll":
                # server-animated: один бросок к серверному результату
                rr = session.pending_roll["request"] if session.pending_roll else None
                if not rr:
                    result = {"kind": "error", "text": "Нет ожидающего броска.",
                              "view": session.view()}
                else:
                    faces = _auto_roll({"request_id": rr.request_id, "dice": rr.dice}, salt["n"])
                    salt["n"] += 1
                    result = session.submit_roll(faces)
                    result["rolled_faces"] = faces
            elif cmd == "materialize":
                house = session.discovery.materialize_interior(msg.get("place", ""),
                                                               kind_hint=msg.get("kind"))
                result = {"kind": "house", "house": house, "view": session.view()}
            elif cmd == "travel":                          # переход «через карту» — свободно по дорогам до места
                result = session.travel_to(msg.get("place", ""))
            elif cmd == "walk_node":                       # свободная ходьба к точке дороги/перекрёстку на карте
                result = session.walk_to_xy(msg.get("x", 0), msg.get("y", 0))
            elif cmd == "roll_manual":
                result = session.submit_roll(msg.get("faces", []))
            elif cmd == "new_game":
                if not me["user"]:                        # генерация требует входа (лимит на аккаунт)
                    await send({"kind": "auth_required", "text": "Войдите, чтобы начать игру."})
                    continue
                async with SessionLocal() as _db:         # списать 1 генерацию мира из лимита
                    _ok, _u = await _svc_usage.consume_enrich(_db, me["user"].id)
                me["user"] = _u
                if not _ok:
                    await send({"kind": "limit", "what": "enrich", "usage": _svc_usage.snapshot(_u),
                                "text": "Бесплатная генерация мира исчерпана — введите код в настройках."})
                    continue
                pc_spec = {"klass": msg.get("klass"), "kit": msg.get("kit"),
                           "name": msg.get("name"), "skills": msg.get("skills"),
                           "l1": msg.get("l1")}
                loop = asyncio.get_running_loop()         # стримим прогресс генерации из рабочего треда
                def _progress(done, total, label):
                    asyncio.run_coroutine_threadsafe(
                        send({"kind": "loading", "done": done, "total": total, "label": label}), loop)
                await send({"kind": "loading", "done": 0, "total": 0, "label": "Строю мир…"})
                session = await asyncio.to_thread(       # жадная генерация не блокирует event loop
                    new_session, seed=int(msg.get("seed", config.WORLD_SEED)),
                    roster_size=12, use_model=True, scenario=msg.get("scenario"),
                    pc_spec=pc_spec, progress=_progress)
                result = session.look()
                result["server_online"] = bool(session.model and session.model.available())
            elif cmd == "levelup":
                result = session.apply_levelup(msg.get("selections") or {})
            elif cmd == "journal":                        # подробный журнал квестов (лор/стадии)
                result = {"kind": "journal", "journal": session.quest_journal(),
                          "view": session.view()}
            elif cmd == "faction_join":
                result = session.join_faction(msg.get("faction", ""))
            elif cmd == "faction_leave":
                result = session.leave_faction()
            elif cmd == "faction_inspect":
                result = session.inspect_faction(msg.get("faction", ""))
            elif cmd == "quest_accept":
                result = session.accept_quest(msg.get("quest", ""))
            elif cmd == "quest_turnin":
                result = session.turn_in_quest(msg.get("quest", ""))
            elif cmd == "guild":                          # экран гильдии (ранг/контракты)
                result = {"kind": "guild", "guild": session.guild_view(), "view": session.view()}
            elif cmd == "take_contract":                  # взять контракт гильдии на угрозу
                result = session.take_contract(msg.get("site", ""))
            elif cmd == "equip":
                result = session.equip_item(msg.get("item", ""))
            elif cmd == "unequip":
                result = session.unequip_item(msg.get("item", ""))
            elif cmd == "use_item":
                result = session.use_item(msg.get("item", ""))
            elif cmd == "save":
                if me["user"]:                            # игра пользователя → БД
                    async with SessionLocal() as _db:
                        g = await _svc_games.save_game(_db, me["user"].id, session,
                                                       msg.get("name"), msg.get("game_id"))
                        glist = await _svc_games.list_games(_db, me["user"].id)
                    result = {"kind": "saved", "card": {"id": g.id, "title": g.title},
                              "games": glist, "view": session.view()}
                else:
                    from ..runtime.persistence import list_saves, save_session
                    card = save_session(session, msg.get("name", "Без названия"))
                    result = {"kind": "saved", "card": card, "saves": list_saves(),
                              "view": session.view()}
            elif cmd == "load":
                if me["user"] and msg.get("game_id") is not None:   # игра пользователя из БД
                    async with SessionLocal() as _db:
                        snap = await _svc_games.get_snapshot(_db, me["user"].id, int(msg["game_id"]))
                    if snap is None:
                        result = {"kind": "error", "text": "игра не найдена"}
                    else:
                        from ..runtime.persistence import deserialize_session
                        session = await asyncio.to_thread(deserialize_session, snap, True)
                        result = session.look()
                        result["server_online"] = bool(session.model and session.model.available())
                else:
                    from ..runtime.persistence import load_session
                    session = load_session(msg.get("slug", ""), use_model=True)
                    result = session.look()
                    result["server_online"] = bool(session.model and session.model.available())
            elif cmd == "delete_save":
                if me["user"] and msg.get("game_id") is not None:
                    async with SessionLocal() as _db:
                        await _svc_games.delete_game(_db, me["user"].id, int(msg["game_id"]))
                        glist = await _svc_games.list_games(_db, me["user"].id)
                    result = {"kind": "saves", "games": glist,
                              "view": session.view() if session else None}
                else:
                    from ..runtime.persistence import delete_save, list_saves
                    delete_save(msg.get("slug", ""))
                    result = {"kind": "saves", "saves": list_saves(),
                              "view": session.view() if session else None}
            elif cmd == "new":
                session = new_session(seed=msg.get("seed", config.WORLD_SEED),
                                      roster_size=12, use_model=True)
                result = session.look()
            else:
                result = {"kind": "error", "text": f"неизвестная команда {cmd}",
                          "view": session.view() if session else None}
            if session is not None and isinstance(result, dict):
                result = session.drain_toasts(result)     # тосты-«ачивки» за ход → фронту
            if me["user"] and isinstance(result, dict) and "usage" not in result:
                result["usage"] = _svc_usage.snapshot(me["user"])   # шкала лимитов обновляется каждым ответом
            await send(result)
    except WebSocketDisconnect:
        pass
    finally:
        if holds["slot"]:                                 # вернуть слот только если занимали под генерацию
            _active["n"] -= 1


def run(host: str = "127.0.0.1", port: int | None = None) -> None:
    import uvicorn
    port = port or int(os.environ.get("PORT", "8000"))   # PORT env → удобно для preview/прокси
    print(f"AI-DnD веб-сервер: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
