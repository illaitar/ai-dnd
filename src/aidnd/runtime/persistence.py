"""Сейв/лоад партии поверх event sourcing (док 08 §5).

Сейв = (seed, roster_size, scenario, pc_spec) + рантайм-хвост лога (события после
baseline пре-гена) + не-событийное состояние (час, журнал, затишье). Загрузка =
детерминированный пре-ген из тех же параметров → регистрация квестов → реплей хвоста.
Это та же golden-replay-инвариантность, что покрыта тестами реплея.

Примечание: память NPC о рантайм-репликах не реплеится (мягкий read-model);
ядро мира (позиции, инвентарь, флаги, квесты, важность) восстанавливается точно.
"""

from __future__ import annotations

import glob
import json
import os
import re
import time

from .. import config
from ..content import build_world, register_quests
from ..content.newgame import (
    CLASSES,
    SCENARIOS,
    default_scenario,
    resolve_pc_spec,
)
from ..gen import QuestSystem
from ..inference import ModelManager
from ..world.events import Event
from .orchestrator import GameSession

SAVE_VERSION = 1


def _dir() -> str:
    os.makedirs(config.SAVE_DIR, exist_ok=True)
    return config.SAVE_DIR


def _slug(name: str) -> str:
    base = re.sub(r"[^0-9A-Za-zА-Яа-яЁё _-]", "", name or "").strip().replace(" ", "_")
    return (base or "save")[:48]


def _path(slug: str) -> str:
    return os.path.join(_dir(), os.path.basename(slug) + ".json")


def save_session(session: GameSession, name: str) -> dict:
    """Сохранить текущую партию в файл. Возвращает карточку сейва для UI."""
    boot = getattr(session, "boot", None)
    if not boot:
        raise ValueError("сессия без boot — сохранять нечего")
    tail = [e.to_dict() for e in session.world.log.after(boot["baseline"] - 1)]
    v = session.view()
    pc = v.get("player", {})
    meta = {
        "place": v.get("place_name"), "time": v.get("time"),
        "hero": pc.get("name"), "level": pc.get("level"),
        "scenario": SCENARIOS.get(boot["scenario"], {}).get("name", boot["scenario"]),
        "klass": CLASSES.get(boot["pc_spec"].get("klass"), {}).get("name", ""),
    }
    data = {
        "version": SAVE_VERSION, "name": name, "created": time.time(),
        "seed": boot["seed"], "roster_size": boot["roster_size"],
        "scenario": boot["scenario"], "pc_spec": boot["pc_spec"],
        "baseline": boot["baseline"], "clock": session.world.clock.tick,
        "journal": session.journal[-60:], "quiet": session.quiet_ticks,
        "events": tail, "meta": meta, "main_quest": boot.get("main_quest"),
    }
    slug = _slug(name)
    with open(_path(slug), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return {"slug": slug, "name": name, "created": data["created"],
            "meta": meta, "events": len(tail)}


def list_saves() -> list[dict]:
    out = []
    for p in glob.glob(os.path.join(_dir(), "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            out.append({"slug": os.path.splitext(os.path.basename(p))[0],
                        "name": d.get("name"), "created": d.get("created"),
                        "meta": d.get("meta", {}), "events": len(d.get("events", []))})
        except Exception:
            continue
    out.sort(key=lambda s: s.get("created") or 0, reverse=True)
    return out


def load_session(slug: str, use_model: bool = True) -> GameSession:
    """Восстановить партию: пре-ген из параметров → квесты → реплей рантайм-хвоста."""
    with open(_path(slug), encoding="utf-8") as f:
        d = json.load(f)
    manager = ModelManager() if use_model else None
    model = manager if (manager and manager.available()) else None
    world = build_world(seed=d["seed"], roster_size=d["roster_size"], model=model,
                        scenario=d.get("scenario"), pc_spec=d.get("pc_spec"))
    quests = QuestSystem(world)
    register_quests(world, quests)                       # порядок как в new_session
    if d.get("main_quest"):                              # сгенерированный сюжет — ДО реплея (его прогресс в хвосте)
        from ..gen.campaign import plan_to_quest
        quests.register(plan_to_quest(d["main_quest"]))
    for ed in d.get("events", []):                       # реплей рантайм-хвоста поверх
        world.apply(Event.from_dict(ed))
    world.clock.tick = int(d.get("clock", 0))
    session = GameSession(world, model=manager if use_model else None, quest_system=quests)
    session.boot = {"seed": d["seed"], "roster_size": d["roster_size"],
                    "scenario": d.get("scenario") or default_scenario(),
                    "pc_spec": resolve_pc_spec(d.get("pc_spec")), "baseline": d["baseline"],
                    "main_quest": d.get("main_quest")}
    session.journal = list(d.get("journal", []))
    session.quiet_ticks = int(d.get("quiet", 0))
    return session


def delete_save(slug: str) -> bool:
    p = os.path.join(_dir(), os.path.basename(slug) + ".json")
    if os.path.exists(p):
        os.remove(p)
        return True
    return False
