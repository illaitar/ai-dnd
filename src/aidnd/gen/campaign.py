"""Архитектор основного сюжета: генерация бесповторной арки + интро на старте игры.

Заменяет авторский lost_mine. По состоянию мира (фракции/опасные места/NPC/класс) LLM-агент
`campaign_architect` пишет интро-крючок и арку из 4-6 актов с твистами; есть детерминированный
фоллбэк (без модели). План маппится в Quest/Stage (предикаты завершения над реальным миром) и
хранится в session.boot → переживает сейв/лоад. Динамика (этап 2, готов): на переходах между
актами reshape_main_quest переписывает ещё НЕ пройденные акты под изменившийся мир (события,
мутации карты, союзы), фиксируя пройденное; вызывается из orchestrator._director_reshape.
"""

from __future__ import annotations

from .provenance import Provenance
from .quest_gen import Predicate, Quest, Rewards, Stage

_DANGER_ORDER = {"низкая": 0, "средняя": 1, "высокая": 2, "смертельная": 3}


def world_digest(world) -> str:
    """Снимок мира для архитектора: фракции (с лидерами/целями/территорией), опасные места
    (place_id для 'clear'), ключевые NPC (id для 'kill'/'talk'). Архитектор ссылается на эти id."""
    from ..content.region import REGION_SITES
    from ..world.components import Persona, Progression
    lines = ["ФРАКЦИИ (id, имя, лидер, цели, территория):"]
    for fid, f in world.factions.items():
        goals = "; ".join(getattr(f, "goals", []) or [])[:90] or "—"
        terr = ", ".join((getattr(f, "controls", []) or [])[:3]) or "—"
        lines.append(f"  - {fid} «{getattr(f, 'name', fid)}» лидер={getattr(f, 'leader', None) or '—'}; "
                     f"цели: {goals}; терр: {terr}")
    lines.append("ОПАСНЫЕ МЕСТА (ключ, place_id для ctype=clear, опасность, что внутри):")
    for k, v in REGION_SITES.items():
        if v.get("place") in world.spatial.places:
            lines.append(f"  - {k} place={v.get('place')} «{v.get('label', k)}» — "
                         f"{v.get('danger')}; {str(v.get('contents', ''))[:48]}")
    lines.append("КЛЮЧЕВЫЕ NPC (id для ctype=kill/talk):")
    leaders = {getattr(f, "leader", None) for f in world.factions.values()}
    _GENERIC = {"", "none", "miner", "farmhand", "commoner", "hunter", "townsfolk"}
    for nid in world.npcs():
        per = world.ecs.get(nid, Persona)
        if not per:
            continue
        role = (getattr(per, "archetype", "") or getattr(per, "profession", "") or "").lower()
        if nid not in leaders and role in _GENERIC:        # отсекаем безликих горожан — меньше шума архитектору
            continue
        lines.append(f"  - {nid} «{getattr(per, 'name', nid)}» {role}"
                     + (" [лидер фракции]" if nid in leaders else ""))
    prog = world.ecs.get("pc:hero", Progression)
    if prog:
        lines.append(f"ИГРОК: класс {getattr(prog, 'klass', '') or getattr(prog, 'class_name', '?')}")
    return "\n".join(lines)


def _fallback_plan(world) -> dict:
    """Детерминированная арка из состояния мира (когда модель недоступна)."""
    from ..content.region import REGION_SITES
    sites = [(k, v) for k, v in REGION_SITES.items() if v.get("place") in world.spatial.places]
    sites.sort(key=lambda kv: _DANGER_ORDER.get(kv[1].get("danger"), 1))
    leader = next((getattr(f, "leader", None) for f in world.factions.values()
                   if getattr(f, "leader", None)), None)
    stages = [{"objective": "Разузнать у мастера города, что неспокойно в Фэндалине",
               "ctype": "talk", "ref": "npc:harbin_wester", "twist": None}]
    if sites:
        mid = sites[len(sites) // 2][1]
        stages.append({"objective": f"Зачистить {mid.get('label')}", "ctype": "clear",
                       "ref": mid["place"], "twist": "след ведёт к кому-то из горожан"})
    if leader:
        stages.append({"objective": "Найти и остановить главаря угрозы", "ctype": "kill",
                       "ref": leader, "twist": "за ним стоит сила покрупнее"})
    if sites:
        last = sites[-1][1]
        stages.append({"objective": f"Дойти до {last.get('label')} и покончить с угрозой",
                       "ctype": "clear", "ref": last["place"], "twist": None})
    return {"intro": "Фэндалин встречает тебя тревогой: на тракте неспокойно, а в городе шепчутся о большем.",
            "title": "Тень над Фэндалином",
            "premise": "Раскрыть, кто стоит за бедами фронтира, и остановить угрозу.",
            "stages": stages}


def _as_text(v) -> str:
    if isinstance(v, dict):
        return str(v.get("description") or v.get("text") or v.get("objective") or "")
    return str(v) if v else ""


_CTYPE_ALIAS = {"defeat": "kill", "kill": "kill", "slay": "kill", "clear": "clear",
                "clear_lair": "clear", "reach": "clear", "talk": "talk", "speak": "talk",
                "item": "item", "collect": "item", "obtain": "item", "retrieve": "item"}


def _act_fields(st: dict):
    """Достаёт (ctype, ref, text, twist) из акта в любом формате модели: ctype/ref могут быть
    вложены в objective={ctype,ref}, текст — в title/description."""
    objf = st.get("objective")
    if isinstance(objf, dict):
        ctype_raw = objf.get("ctype") or objf.get("objective_type") or objf.get("type")
        ref = objf.get("ref") or objf.get("target") or objf.get("target_id")
        text = st.get("title") or st.get("description") or st.get("name") or ""
    else:
        ctype_raw = st.get("ctype") or st.get("objective_type") or st.get("type")
        ref = st.get("ref") or st.get("target") or st.get("target_id")
        text = objf or st.get("title") or st.get("description") or st.get("goal") or ""
    ctype = _CTYPE_ALIAS.get(str(ctype_raw or "").lower())
    return ctype, ref, _as_text(text), (st.get("twist") or st.get("reveal") or st.get("plot_twist"))


def _normalize_plan(raw) -> dict | None:
    """Толерантный разбор: модели вольно именуют поля (campaign_title/intro_hook/acts; objective
    как вложенный dict). Приводим к {intro,title,premise,stages[ctype,ref,objective,twist]}."""
    if not isinstance(raw, dict):
        return None
    stages_src = list(raw.get("stages") or raw.get("acts") or raw.get("quests") or raw.get("steps") or [])
    intro = ""
    ih = raw.get("intro_hook")                            # часто несёт интро-текст И первый акт
    if isinstance(ih, dict):
        intro = _as_text(ih.get("description") or ih.get("text") or ih.get("hook"))
        if ih.get("objective") or ih.get("ref") or ih.get("target"):
            stages_src = [ih] + stages_src
    stages = []
    for st in stages_src:
        if not isinstance(st, dict):
            continue
        ctype, ref, text, twist = _act_fields(st)
        if ctype in _CTYPE and ref:
            stages.append({"objective": text or "продвинуть сюжет", "ctype": ctype, "ref": ref, "twist": twist})
    if not stages:
        return None
    intro = intro or _as_text(raw.get("intro") or raw.get("introduction") or raw.get("hook"))
    return {"intro": intro, "title": str(raw.get("title") or raw.get("campaign_title") or "Основной сюжет"),
            "premise": _as_text(raw.get("premise") or raw.get("description")), "stages": stages}


def _display_name(world, ref: str) -> str:
    from ..world.components import Persona
    pl = world.spatial.places.get(ref)
    if pl:
        return pl.name
    per = world.ecs.get(ref, Persona)
    if per:
        return getattr(per, "name", ref)
    return str(ref).split(":")[-1]


def _objective_text(ctype: str, ref: str, world) -> str:
    name = _display_name(world, ref)
    return {"talk": f"Поговорить с {name}", "kill": f"Одолеть {name}",
            "clear": f"Зачистить «{name}»", "item": f"Раздобыть {name}"}.get(ctype, "Продвинуть сюжет")


def _ground(plan: dict, world) -> dict | None:
    """Заземление: оставляем только акты с РЕАЛЬНЫМ ref (иначе квест не закрыть); длинные/пустые
    цели (часто туда утекает интро) заменяем короткой целью из ctype+ref."""
    valid = set(world.npcs()) | set(world.spatial.places)
    out = []
    for st in plan.get("stages", []):
        ref = st.get("ref")
        if ref not in valid and not str(ref).startswith("tmpl:"):
            continue
        obj = st.get("objective") or ""
        if not obj or len(obj) > 90 or obj == "продвинуть сюжет":   # пусто/длинно/сентинел → чистая цель из ctype+ref
            obj = _objective_text(st["ctype"], ref, world)
        out.append({**st, "objective": obj})
    if not out:
        return None
    plan["stages"] = out
    return plan


def forge_main_quest(world, model) -> dict:
    """План основного сюжета: LLM-архитектор (если доступен и заземляем) или детерминированный фоллбэк."""
    if model is not None and getattr(model, "available", lambda: False)():
        try:
            from ..inference.agents import forge_campaign
            plan = _normalize_plan(forge_campaign(model, world_digest(world)))
            plan = _ground(plan, world) if plan else None
        except Exception:
            plan = None
        if plan and len(plan["stages"]) >= 2:
            plan["intro"] = plan.get("intro") or _fallback_plan(world)["intro"]
            return plan
    return _fallback_plan(world)


_CTYPE = {
    "kill": lambda ref: Predicate("NpcDead", [ref]),
    "clear": lambda ref: Predicate("LairCleared", [ref]),
    "talk": lambda ref: Predicate("TalkedTo", [ref]),
    "item": lambda ref: Predicate("HasItem", ["pc:hero", ref]),
}


def _stage_from_plan(sid: str, st: dict, next_sid: str | None, last: bool) -> Stage:
    """Один акт плана → Stage: предикат завершения из ctype+ref; твист → флаг twist:{sid};
    последний акт → флаг main_quest_won."""
    mk = _CTYPE.get(st.get("ctype"))
    cond = mk(st["ref"]) if (mk and st.get("ref")) else None
    oc = []
    if st.get("twist"):
        oc.append({"effect": "set_flag", "flag": f"twist:{sid}"})
    if last:
        oc.append({"effect": "set_flag", "flag": "main_quest_won"})
    return Stage(sid, str(st.get("objective", ""))[:140],
                 completion_conditions=[cond] if cond else [],
                 on_complete=oc, next_stages=[next_sid] if next_sid else [])


def plan_to_quest(plan: dict) -> Quest:
    """План → Quest (kind=main, id=quest:main): акты-стадии, завершение → реальные предикаты,
    твист → флаг на завершении акта, последний акт → флаг main_quest_won."""
    raw = plan.get("stages") or []
    stages = [_stage_from_plan(f"a{i + 1}", st, f"a{i + 2}" if i + 1 < len(raw) else None,
                               i + 1 == len(raw)) for i, st in enumerate(raw)]
    return Quest(
        quest_id="quest:main", kind="main", title=str(plan.get("title", "Основной сюжет"))[:60],
        giver_ref=None, state="active", current_stages=["a1"] if stages else [],
        stages=stages, framing=str(plan.get("premise", "")),
        rewards=Rewards(xp=2000),
        world_bindings=[s["ref"] for s in raw if s.get("ref")],
        provenance=Provenance(source="generated", generator="campaign@1.0"))


def reshape_main_quest(world, quest, plan: dict, model, delta: str) -> str | None:
    """Квест-директор (этап 2): на переходе акта переписать ещё НЕ пройденные акты под изменившийся
    мир. Пройденное и текущий акт фиксированы — заменяется только хвост. План (boot) обновляется →
    переживает сейв/лоад. Возвращает короткую заметку игроку или None (без изменений)."""
    if model is None or not getattr(model, "available", lambda: False)():
        return None
    if not getattr(quest, "current_stages", None):
        return None
    ids = [s.stage_id for s in quest.stages]
    cur = quest.current_stages[0]
    if cur not in ids:
        return None
    ki = ids.index(cur)
    tail = quest.stages[ki + 1:]
    if not tail:                                          # на финальном акте — переписывать нечего
        return None
    completed = [s.objective for s in quest.stages[:ki]]
    try:
        from ..inference.agents import reforge_acts
        raw = reforge_acts(model, plan.get("title", ""), plan.get("premise", ""), completed,
                           quest.stages[ki].objective, world_digest(world), delta, len(tail))
        new = _ground(_normalize_plan(raw), world) if raw else None
    except Exception:
        new = None
    if not new or not new.get("stages"):
        return None
    # перестроить хвост Stage-объектами, продолжая нумерацию после текущего акта
    m = len(new["stages"])
    new_stages = [_stage_from_plan(f"a{ki + 2 + i}", st, f"a{ki + 3 + i}" if i + 1 < m else None,
                                   i + 1 == m) for i, st in enumerate(new["stages"])]
    quest.stages[ki].next_stages = [new_stages[0].stage_id]
    quest.stages = quest.stages[:ki + 1] + new_stages
    kept = [s.get("ref") for s in (plan.get("stages") or [])[:ki + 1] if s.get("ref")]
    quest.world_bindings = kept + [s["ref"] for s in new["stages"] if s.get("ref")]
    plan["stages"] = (plan.get("stages") or [])[:ki + 1] + new["stages"]   # boot → сейв/лоад
    plan["reshaped"] = plan.get("reshaped", 0) + 1
    return "Ход событий меняет твой путь — " + (new["stages"][0].get("objective") or "сюжет повернул")
