"""Слой инцидентов: живые события города — фракции, монстры, политика, катаклизмы.

Инцидент возникает в точке (origin place_id), распространяется волной и пересекается
с другими. Распространение ГИБРИДНОЕ: для механики — хопы по графу локаций (этап 2,
эффекты), для визуализации — расходящиеся круги по координатам карты (этот модуль).

Симуляция на тик — ЧИСТАЯ функция от (геометрия, состояние мира, seed, tick): тот же
вход даёт тот же выход, поэтому скраббер тиков и реплей безопасны. Генератор инцидентов
(proposer) на этапе 1 детерминированный (по seed); на этапе 2 его заменит LLM-режиссёр
с тем же форматом расписания (Spawn).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..gen.seeds import subseed

# параметры волны по типу: цвет (для виза), скорость в px/тик, срок жизни (тиков), порог
KIND_META = {
    "faction":   {"color": "#7F77DD", "speed_px": 9.0,  "life": 36},
    "monster":   {"color": "#D85A30", "speed_px": 13.0, "life": 24},
    "politics":  {"color": "#378ADD", "speed_px": 6.5,  "life": 60},
    "cataclysm": {"color": "#854F0B", "speed_px": 20.0, "life": 30},
}
_DANGER_W = {"низкая": 0.25, "средняя": 0.45, "высокая": 0.7, "смертельная": 1.0}
# локации города, которые событие может закрыть/разрушить (правило-генератор; LLM выбирает сам)
_TOWN_SHOPS = ["building:barthens_provisions", "building:lionshield_coster",
               "building:shrine_of_luck", "building:sleeping_giant", "building:edermath_orchard"]
MAX_LIFE = max(m["life"] for m in KIND_META.values())


@dataclass
class Spawn:
    """Запланированное возникновение инцидента (выход proposer'а — правил или LLM)."""
    id: str
    kind: str
    source: str        # faction_id / site_key / "town" / "world"
    origin: str        # place_id (или спец-ключ "gate:<key>" / "center")
    label: str
    spawn_tick: int
    intensity0: float  # 0..1 — начальная сила
    desc: str = ""     # одно предложение-флейвор (от LLM)
    effects: dict = field(default_factory=dict)   # {rumor, alteration} — эффекты в мир


def _rng(seed: int, *parts) -> random.Random:
    return random.Random(subseed(seed, *[str(p) for p in parts]) & 0x7FFFFFFF)


# гражданская жизнь карты: детерминированный каданс — лавки закрываются/открываются,
# появляются новые. Гарантирует ВИДИМУЮ эволюцию города и в правило-, и в LLM-расписании.
_CIVIC = [("close", "Ратуша: торговый запрет — лавка закрыта"),
          ("open", "В городе открылось новое заведение"),
          ("reopen", "Лавка снова открыта"),
          ("ruin", "Пожар — здание выгорело дотла")]


def _civic_stream(seed: int, t0: int, t1: int, period: int = 50) -> list:
    out = []
    t = t0 - (t0 % period)
    while t <= t1:
        if t >= 0:
            i = t // period
            action, label = _CIVIC[i % len(_CIVIC)]
            if action == "open":
                eff = {"change": {"action": "open", "id": f"building:civic:{t}", "name": "Новая лавка",
                                  "dir": "out", "affordances": ["buy", "sell"]}}
            elif _TOWN_SHOPS:
                eff = {"change": {"action": action, "target": _TOWN_SHOPS[i % len(_TOWN_SHOPS)]}}
            else:
                eff = {}
            out.append(Spawn(f"inc:civic:{t}", "politics", "town", "building:townmaster_hall",
                             label, t, 0.5, effects=eff))
        t += period
    return out


def propose_incidents(factions: list, sites: list, seed: int,
                      t0: int, t1: int) -> list[Spawn]:
    """Детерминированное расписание инцидентов на окне [t0, t1] (этап 1).

    factions: [{id, name, controls:[place_id], members:[..], relations:{..}}]
    sites:    [{key, place, danger, label}]
    Этап 2 заменит эту функцию на LLM-режиссёр (тот же возврат list[Spawn]).
    """
    out: list[Spawn] = []

    def schedule(period: int, fire, kind_for_window: str):
        t = t0 - (t0 % period) if period else t0
        while t <= t1:
            if t >= 0:
                fire(t)
            t += period

    # фракции: ходы из своих территорий (реже — живой город, не шланг); сила ∝ числу членов
    for f in factions:
        ctrl = f.get("controls") or []
        if not ctrl:
            continue
        strength = min(1.0, 0.35 + 0.09 * len(f.get("members") or []))

        def fire(t, f=f, ctrl=ctrl, strength=strength):
            r = _rng(seed, "fac", f["id"], t)
            if r.random() >= 0.4:
                return
            origin = ctrl[r.randrange(len(ctrl))]
            verb = r.choice(["облава", "вербовка", "экспансия", "разборка", "поборы"])
            eff = {}
            if verb == "экспансия" and r.random() < 0.4:   # фракция открывает аванпост → новая локация
                eff["change"] = {"action": "open", "id": f"building:outpost:{f['id']}",
                                 "name": f"Аванпост: {f.get('name', 'фракция')}", "dir": "out",
                                 "affordances": ["talk"]}
            out.append(Spawn(f"inc:fac:{f['id']}:{t}", "faction", f["id"], origin,
                             f"{f.get('name', 'Фракция')}: {verb}", t, strength, effects=eff))
        schedule(60, fire, "faction")

    # монстры: вылазки из сайтов, частота/сила ∝ danger; входят в город через ворота
    for s in sites:
        w = _DANGER_W.get(s.get("danger"), 0.0)
        if w <= 0:
            continue
        period = max(40, int(90 - 45 * w))

        def fire(t, s=s, w=w):
            r = _rng(seed, "mon", s["key"], t)
            if r.random() >= 0.3 + 0.3 * w:
                return
            out.append(Spawn(f"inc:mon:{s['key']}:{t}", "monster", s["key"],
                             f"gate:{s['key']}", f"{s.get('label', s['key'])}: вылазка", t, w))
        schedule(period, fire, "monster")

    out += _civic_stream(seed, t0, t1)                 # гражданская жизнь карты (лавки/руины/новое)

    # катаклизм: очень редкий, город-wide (пожар/буря → руины ключевой локации)
    def fire_cat(t):
        r = _rng(seed, "cat", t)
        if r.random() >= 0.18:
            return
        kind = r.choice(["пожар", "поветрие", "буря", "магический выброс"])
        eff = {}
        if kind in ("пожар", "буря") and _TOWN_SHOPS:
            eff["change"] = {"action": "ruin", "target": _TOWN_SHOPS[r.randrange(len(_TOWN_SHOPS))]}
        out.append(Spawn(f"inc:cat:{t}", "cataclysm", "world", "center",
                         f"Катаклизм: {kind}", t, 0.95, effects=eff))
    schedule(200, fire_cat, "cataclysm")

    out.sort(key=lambda s: (s.spawn_tick, s.id))
    return out


def _resolve_xy(sp: Spawn, place_xy: dict, gates: list, center: list, seed: int) -> list | None:
    """Точка инцидента на карте (модель 980×700)."""
    if sp.origin == "center":
        return list(center)
    if sp.origin.startswith("gate:"):                 # монстр входит через ворота
        if not gates:
            return None
        r = _rng(seed, "gate", sp.origin)
        return list(gates[r.randrange(len(gates))])
    return place_xy.get(sp.origin)                     # лендмарк фракции/ратуши


def _norm_kind(k: str) -> str | None:
    """Нормализация kind от LLM к каноническому enum (модель возвращает monster_raids,
    faction_action, political и т.п. — guided-JSON не всегда жмёт вложенный enum)."""
    k = (k or "").lower()
    if "monster" in k or "raid" in k or "creature" in k or "beast" in k:
        return "monster"
    if "fac" in k or "guild" in k or "gang" in k:
        return "faction"
    if "polit" in k or "decree" in k or "council" in k or "ратуш" in k:
        return "politics"
    if "catacl" in k or "disast" in k or "catastro" in k:
        return "cataclysm"
    return k if k in KIND_META else None


def build_schedule(factions: list, sites: list, seed: int, t0: int, t1: int,
                   model=None, digest: str | None = None) -> list[Spawn]:
    """Расписание инцидентов на [t0, t1]. Этап 2: LLM-режиссёр (если модель доступна и
    дан digest) — он предлагает события из состояния мира; иначе детерминированные правила
    (этап 1, фоллбэк). Возврат один — list[Spawn], дальше симуляция детерминирована."""
    if model is not None and digest and getattr(model, "available", lambda: False)():
        try:
            from ..inference.agents import propose_incidents as _llm
            raw = _llm(model, digest)
        except Exception:
            raw = None
        if raw:
            out: list[Spawn] = []
            for i, it in enumerate(raw):
                kind = _norm_kind(it.get("kind"))
                if kind is None:
                    continue
                when = max(0, min(t1 - t0, int(it.get("when", 0))))
                inten = max(0.0, min(1.0, float(it.get("intensity", 0.5))))
                out.append(Spawn(
                    id=f"inc:llm:{t0}:{i}", kind=kind, source=str(it.get("source", "")),
                    origin=str(it.get("origin") or "center"), label=str(it.get("label", ""))[:64],
                    spawn_tick=t0 + when, intensity0=inten, desc=str(it.get("desc", "")),
                    effects={"rumor": it.get("rumor"), "alteration": it.get("alteration"),
                             "change": it.get("change")}))
            if out:
                out += _civic_stream(seed, t0, t1)     # карта эволюционирует и при LLM-режиссёре
                out.sort(key=lambda s: (s.spawn_tick, s.id))
                return out
    return propose_incidents(factions, sites, seed, t0, t1)


def simulate(schedule: list, place_xy: dict, gates: list, center: list,
             factions: list, seed: int, at_tick: int) -> dict:
    """Активные инциденты из расписания и их пересечения на тике at_tick (оверлей/скраббер).

    schedule: list[Spawn] из build_schedule. place_xy: {place_id:[x,y]} в модели 980×700.
    gates: [[x,y],...] ворота (вход монстров). center: [x,y].
    Возвращает {tick, incidents:[...], intersections:[...]} — чистая функция, реплей-safe.
    """
    incidents = []
    for sp in schedule:
        meta = KIND_META[sp.kind]
        age = at_tick - sp.spawn_tick
        if age < 0 or age >= meta["life"]:
            continue
        xy = _resolve_xy(sp, place_xy, gates, center, seed)
        if not xy:
            continue
        intensity = round(sp.intensity0 * max(0.0, 1.0 - age / meta["life"]), 3)
        if intensity <= 0.02:
            continue
        incidents.append({
            "id": sp.id, "kind": sp.kind, "source": sp.source, "origin": sp.origin,
            "label": sp.label, "desc": sp.desc, "effects": sp.effects,
            "x": round(xy[0], 1), "y": round(xy[1], 1),
            "age": age, "intensity": intensity, "color": meta["color"],
            "radius": round(age * meta["speed_px"], 1),
        })

    intersections = []
    rel = {f["id"]: (f.get("relations") or {}) for f in factions}
    for i in range(len(incidents)):
        for j in range(i + 1, len(incidents)):
            a, b = incidents[i], incidents[j]
            d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
            overlap = a["radius"] + b["radius"] - d
            if overlap <= 0:
                continue
            combo = a["intensity"] * b["intensity"]
            if combo < 0.06:
                continue
            # реакция по типам/отношениям фракций
            kinds = {a["kind"], b["kind"]}
            if "cataclysm" in kinds:
                reaction = "усиление"
            elif kinds == {"faction"} and rel.get(a["source"], {}).get(b["source"], 0) < -0.2:
                reaction = "стычка"
            elif "monster" in kinds:
                reaction = "паника" if "politics" in kinds or "faction" in kinds else "оборона"
            else:
                reaction = "трение"
            # точка пересечения — взвешенно ближе к более сильному фронту
            wa, wb = a["intensity"], b["intensity"]
            mx = (a["x"] * wb + b["x"] * wa) / (wa + wb)
            my = (a["y"] * wb + b["y"] * wa) / (wa + wb)
            intersections.append({
                "a": a["id"], "b": b["id"], "x": round(mx, 1), "y": round(my, 1),
                "strength": round(combo, 3), "reaction": reaction,
            })

    return {"tick": at_tick, "incidents": incidents, "intersections": intersections}


def _effect_place(world, sp: Spawn):
    """Реальная локация-якорь для эффектов: origin как есть / сайт за 'gate:<key>' /
    общегородской центр для 'center'/'town'/'world' (чинит «след не лёг»)."""
    o = sp.origin
    places = getattr(world.spatial, "places", {})
    if o in places:
        return o
    if o.startswith("gate:"):
        from ..content.region import REGION_SITES
        return (REGION_SITES.get(o[5:]) or {}).get("place")
    if o in ("center", "town", "world"):
        for cand in ("place:phandalin_square", "building:townmaster_hall", "settlement:phandalin"):
            if cand in places:
                return cand
    return None


def _gossip_npcs(world) -> list[str]:
    """Сплетники города — узнают ПУБЛИЧНЫЕ новости быстро (хаб молвы; чинит лаг диффузии)."""
    from ..world.components import Persona
    out = []
    for nid in world.npcs():
        per = world.ecs.get(nid, Persona)
        traits = (getattr(per, "traits", []) or []) if per else []
        if any(t in traits for t in ("gossipy", "welcoming", "talkative", "chatty", "jovial")):
            out.append(nid)
    return out


def apply_incident_effects(world, sp: Spawn) -> list[str]:
    """Закоммитить эффекты инцидента в МИР (event-sourced, для живой игры/срабатывания):
      1) стойкий след на месте-источнике (Place.alterations);
      2) Δ отношений — агрессивный ход фракции роняет отношения с её врагами;
      3) слух → публичный факт в граф знаний; узнают NPC на месте + сплетники-хаб;
      4) МУТАЦИЯ КАРТЫ — закрыть/разрушить/открыть локацию (effects.change).
    Возвращает список применённых эффектов. Идемпотентность — на стороне вызывающего."""
    eff = sp.effects or {}
    applied = []
    place = _effect_place(world, sp)

    alt = eff.get("alteration")
    if alt and place:
        world.commit("world_effect", "incident",
                     payload={"kind": "place", "target": place, "note": str(alt)[:120]})
        applied.append(f"след «{alt}» на {place}")

    if sp.kind == "faction" and sp.source in getattr(world, "factions", {}):
        f = world.factions[sp.source]
        for other, val in (getattr(f, "relations", {}) or {}).items():
            if val < -0.1:
                world.commit("faction_relation", sp.source,
                             payload={"a": sp.source, "b": other, "value": max(-1.0, val - 0.05)})
                applied.append(f"отношения {sp.source}→{other} {val:.2f}→{max(-1.0, val-0.05):.2f}")

    rumor = eff.get("rumor") or sp.label
    if rumor:
        fid = f"fact:inc:{sp.id}"
        world.commit("incident_rumor", "incident", payload={      # публичная новость: sensitivity 0
            "fid": fid, "text": str(rumor)[:160], "topic": "rumors",
            "tags": ["событие", sp.kind], "sensitivity": 0.0})
        knowers = {e for e in world.spatial.occupants(place) if str(e).startswith("npc:")} if place else set()
        knowers |= set(_gossip_npcs(world))                        # хаб слышит городские новости в тот же день
        for npc in knowers:
            world.commit("learn_fact", "incident", payload={"npc": npc, "fact": fid})
        applied.append(f"слух «{rumor}» (+{len(knowers)} узнали)")

    chg = eff.get("change")
    if isinstance(chg, dict) and chg.get("action"):
        world.commit("place_change", "incident", payload=chg)
        applied.append(f"карта: {chg['action']} → {chg.get('target') or chg.get('name') or '?'}")
    return applied
