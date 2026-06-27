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


def serialize_session(session: GameSession, name: str) -> dict:
    """Сериализовать партию в dict (boot + хвост event-лога + снапшот обогащения). БЕЗ записи в файл —
    общая основа для файловых сейвов И для игр в БД (server/games)."""
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
    from .snapshot import capture
    return {
        "version": SAVE_VERSION, "name": name, "created": time.time(),
        "seed": boot["seed"], "roster_size": boot["roster_size"],
        "scenario": boot["scenario"], "pc_spec": boot["pc_spec"],
        "baseline": boot["baseline"], "clock": session.world.clock.tick,
        "journal": session.journal[-60:], "quiet": session.quiet_ticks,
        "quest_timeline": session.quest_timeline,         # хроника квестов (день/время по участию) — персист
        "merges": [{**m, "state": session.world.quests[m["id"]].state,    # слияния (+живое состояние подряда)
                    "current_stages": session.world.quests[m["id"]].current_stages}
                   for m in session.merges if m.get("id") in session.world.quests],
        "event_leads": [{**ld, "state": session.world.quests[ld["id"]].state,   # зацепки из уличных событий
                         "current_stages": session.world.quests[ld["id"]].current_stages}
                        for ld in session.event_leads if ld.get("id") in session.world.quests],
        "dungeon_status": session.dungeon_status,          # cleared|occupied подземелий (переоккупация)
        "cases": getattr(session.world, "cases", {}) or {},  # дела дознавателей (подозрение к игроку)
        "events": tail, "meta": meta, "main_quest": boot.get("main_quest"),
        "state": capture(session),                       # снапшот обогащения: предметы/персоны/память
    }


def save_session(session: GameSession, name: str) -> dict:
    """Сохранить текущую партию в файл. Возвращает карточку сейва для UI."""
    data = serialize_session(session, name)
    slug = _slug(name)
    with open(_path(slug), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return {"slug": slug, "name": name, "created": data["created"],
            "meta": data["meta"], "events": len(data["events"])}


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
    """Восстановить партию из файла-сейва."""
    with open(_path(slug), encoding="utf-8") as f:
        d = json.load(f)
    return deserialize_session(d, use_model)


def deserialize_session(d: dict, use_model: bool = True) -> GameSession:
    """Восстановить партию из dict: пре-ген из параметров → квесты → реплей рантайм-хвоста.
    Общая основа для файловых сейвов И игр в БД (server/games)."""
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
    for m in d.get("merges", []):                        # объединённые подряды — ПОСЛЕ реплея (источники уже есть:
        a, b = world.quests.get(m.get("a")), world.quests.get(m.get("b"))   # статичные + threat из реплея)
        if a and b and m.get("id") and m["id"] not in world.quests:
            from ..content.board import build_merged_quest
            mq = build_merged_quest(m["id"], a, b, m.get("title", ""), m.get("framing", ""))
            mq.state = m.get("state", "offered")          # прогресс берём из сейва (не из реплея)
            mq.current_stages = list(m.get("current_stages", []))
            quests.register(mq)
            a.state = b.state = "superseded"
    for ld in d.get("event_leads", []):                  # зацепки из уличных событий — пересоздать с состоянием
        if ld.get("id") and ld["id"] not in world.quests:
            from ..content.board import build_lead_quest
            quests.register(build_lead_quest(ld, ld.get("state", "offered"),
                                             ld.get("current_stages", [])))
    for _ in range(20):                                  # догнать стадии квестов: advance НЕ событийный,
        progressed = False                               # реплей флагов сам по себе не двигает current_stages
        for q in list(world.quests.values()):
            if q.state == "active":
                before = list(q.current_stages)
                quests.advance(q)
                if q.current_stages != before:
                    progressed = True
        if not progressed:
            break
    session = GameSession(world, model=manager if use_model else None, quest_system=quests)
    from .snapshot import apply  # снапшот обогащения поверх реконструкции
    apply(session, d.get("state"))                        # предметы/контейнеры/кошельки/персоны/память
    session._quest_log_seen = session._toast_log_seen = len(quests.log)   # не всплывать из-за догоняющего advance
    session._quest_entries_seen = len(quests.entries)     # хронику не пересобираем реплеем — берём из сейва
    session.quest_timeline = {k: list(v) for k, v in (d.get("quest_timeline") or {}).items()}
    session.merges = [dict(m) for m in (d.get("merges") or [])]   # слияния уже пересозданы выше
    session.event_leads = [dict(ld) for ld in (d.get("event_leads") or [])]   # зацепки уже пересозданы выше
    session.dungeon_status = dict(d.get("dungeon_status") or {})
    session._apply_dungeon_status()                       # переоккупация: снять cleared-флаги/переоткрыть контракты
    session.world.cases = {k: dict(v) for k, v in (d.get("cases") or {}).items()}   # дела дознавателей
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
