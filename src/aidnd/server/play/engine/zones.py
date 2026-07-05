"""Зоны живой сцены: выбор зоны НУЖДАМИ — рекурсия society-скоринга внутрь здания
(docs/locations.md, кейс 13: голодный к столу, уставший к лежанке, нелюдим в тень).

Скоринг и выбор — чистые функции (тестируются без сервера и LLM). building_zones —
резолв обстановки здания: мир → пул по имени → пул по типу (мост до материализации шага 2).
"""

from __future__ import annotations

import random

POST_BONUS = 3.0            # рабочий пост держит работника
CROWD_PENALTY = 0.35        # толчея сверх вместимости отталкивает
MOVE_HYSTERESIS = 0.22      # пересаживаемся, только если новая зона ЗАМЕТНО лучше
SERVICE_KINDS = {"private", "storage", "cell"}   # служебные зоны — не для посетителей


def building_zones(bid) -> tuple[dict, list]:
    """Фактшит здания с зонами: мир → пул по имени → пул по типу. ({}, []) если зон нет."""
    from aidnd.server.play.engine.core import _pool, _store, _wid
    if not bid:
        return {}, []
    data = (_store().get_building(_wid(), bid) or {}).get("data") or {}
    if not data.get("zones"):
        t = str(data.get("type") or "").lower()
        cand = [r for r in _pool().pool_buildings("key") if r["data"].get("zones")]
        row = (next((r for r in cand if r["data"].get("name") == data.get("name")), None)
               or next((r for r in cand
                        if t and str(r["data"].get("type") or "").lower() == t), None)
               or next((r for r in cand
                        if t and (t in r["btype"].lower() or r["btype"].lower() in t)), None))
        if row:
            data = {**data, "zones": row["data"]["zones"], "layout": row["data"].get("layout")}
    return data, (data.get("zones") or [])


def zone_score(state, zone: dict, load: int = 0) -> float:
    """Насколько зона закрывает нужды человека: afford её ПРЕДМЕТОВ × давление нужд
    + приватность по нраву (нелюдим тянется в тень, общительный — в гул) − толчея."""
    s = 0.04
    needs = getattr(state, "needs", None) or {}
    for o in zone.get("objects") or []:
        for need, rate in (o.get("afford") or {}).items():
            s += rate * max(0.0, needs.get(need, 0.0) - 0.2) * 2.0
    traits = getattr(getattr(state, "config", None), "traits", None) or {}
    soc = traits.get("sociability", 0.5)
    s += zone.get("privacy", 0.3) * (0.55 - soc) * 0.5
    s -= zone.get("noise", 0.4) * max(0.0, 0.45 - soc) * 0.25
    cap = zone.get("cap", 4)
    if load >= cap:
        s -= CROWD_PENALTY * (1 + load - cap)
    return s


def choose_zone(state, zones: list, load: dict, rng: random.Random,
                role: str = "", works_here: bool = False, current: str | None = None):
    """Зона для человека: рабочий пост держит; иначе лучшая по нуждам; гистерезис
    против дёрганья (пересел — значит, было ЗАЧЕМ). Запертые зоны не предлагаем."""
    if works_here and role:
        rl = role.lower()
        zp = next((z for z in zones
                   if z.get("post") and (z["post"] in rl or rl in z["post"])), None)
        if zp is not None:
            return zp["id"]
    open_z = [z for z in zones if not z.get("lockable")
              and (works_here or z["kind"] not in SERVICE_KINDS)]
    if not open_z:
        open_z = [z for z in zones if not z.get("lockable")]
    if not open_z:
        return None
    best = max(open_z,
               key=lambda z: zone_score(state, z, load.get(z["id"], 0)) + rng.uniform(0, 0.03))
    if current:
        cur = next((z for z in open_z if z["id"] == current), None)
        if cur is not None and (zone_score(state, best, load.get(best["id"], 0))
                                < zone_score(state, cur, load.get(current, 0)) + MOVE_HYSTERESIS):
            return current
    return best["id"]


def assign_zones(states: dict, zones: list, seed: str,
                 roles: dict | None = None, workers: set | None = None) -> dict:
    """Начальная расстановка компании по зонам — детерминированно по сиду, посты первыми."""
    rng = random.Random(seed)
    out: dict = {}
    load: dict = {}
    ordered = sorted(states, key=lambda p: (p not in (workers or set()), p))
    for pid in ordered:
        zid = choose_zone(states[pid], zones, load, rng,
                          role=(roles or {}).get(pid, ""),
                          works_here=pid in (workers or set()))
        out[pid] = zid
        if zid:
            load[zid] = load.get(zid, 0) + 1
    return out
