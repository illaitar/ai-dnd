"""L9 Presentation: FastAPI + WebSocket (main §11).

Backend держит живое состояние (event log на сервере), шлёт дельты и нарратив,
фронт рендерит. Никакого browser storage — всё состояние на сервере. Броски —
server-authoritative animated (док 07 §8): сервер кидает, клиент анимирует.
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import config
from ..bootstrap import new_session
from ..rules.dice import roll_expr

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
app = FastAPI(title="AI-DnD Engine")


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


@app.get("/saves")
def saves_list() -> dict:
    from ..runtime.persistence import list_saves
    return {"saves": list_saves()}


@app.get("/town_layout")
def town_layout(seed: int = config.WORLD_SEED) -> dict:
    """Список достопримечательностей города (здания+направления) для процедурной
    карты: реальные узлы графа якорят сгенерированный город (улицы/дома)."""
    session = new_session(seed=seed, roster_size=12, use_model=False)
    ml = session.map_levels()
    town = next((lvl for lvl in ml["levels"] if lvl["id"] == "town"), {"nodes": []})
    sp = session.world.spatial
    buildings = []
    for n in town["nodes"]:
        p = sp.places.get(n["id"])
        buildings.append({"id": n["id"], "name": n["name"], "kind": n["kind"],
                          "dir": n.get("dir_ru", ""), "dx": n["dx"], "dy": n["dy"],
                          "affordances": list(p.affordances) if p else [],
                          "go": n.get("go")})
    return {"seed": int(seed), "settlement": "Фэндалин", "buildings": buildings}


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


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    session = new_session(seed=config.WORLD_SEED, roster_size=12, use_model=True)
    salt = {"n": 1}

    async def send(result: dict) -> None:
        await sock.send_text(json.dumps(result, ensure_ascii=False, default=str))

    online = bool(session.model and session.model.available())
    intro = session.look()
    intro["server_online"] = online
    await send(intro)

    try:
        while True:
            msg = json.loads(await sock.receive_text())
            cmd = msg.get("cmd")
            if cmd == "input":
                result = session.handle(msg.get("text", ""))
            elif cmd == "look":
                result = session.look()
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
            elif cmd == "roll_manual":
                result = session.submit_roll(msg.get("faces", []))
            elif cmd == "new_game":
                pc_spec = {"klass": msg.get("klass"), "kit": msg.get("kit"),
                           "name": msg.get("name"), "skills": msg.get("skills")}
                session = new_session(seed=int(msg.get("seed", config.WORLD_SEED)),
                                      roster_size=12, use_model=True,
                                      scenario=msg.get("scenario"), pc_spec=pc_spec)
                result = session.look()
                result["server_online"] = bool(session.model and session.model.available())
            elif cmd == "levelup":
                result = session.apply_levelup(msg.get("selections") or {})
            elif cmd == "save":
                from ..runtime.persistence import list_saves, save_session
                card = save_session(session, msg.get("name", "Без названия"))
                result = {"kind": "saved", "card": card, "saves": list_saves(),
                          "view": session.view()}
            elif cmd == "load":
                from ..runtime.persistence import load_session
                session = load_session(msg.get("slug", ""), use_model=True)
                result = session.look()
                result["server_online"] = bool(session.model and session.model.available())
            elif cmd == "delete_save":
                from ..runtime.persistence import delete_save, list_saves
                delete_save(msg.get("slug", ""))
                result = {"kind": "saves", "saves": list_saves(), "view": session.view()}
            elif cmd == "new":
                session = new_session(seed=msg.get("seed", config.WORLD_SEED),
                                      roster_size=12, use_model=True)
                result = session.look()
            else:
                result = {"kind": "error", "text": f"неизвестная команда {cmd}",
                          "view": session.view()}
            await send(result)
    except WebSocketDisconnect:
        return


def run(host: str = "127.0.0.1", port: int | None = None) -> None:
    import uvicorn
    port = port or int(os.environ.get("PORT", "8000"))   # PORT env → удобно для preview/прокси
    print(f"AI-DnD веб-сервер: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
