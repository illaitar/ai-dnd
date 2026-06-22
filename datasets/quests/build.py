"""Собрать датасет квест-генератора: словари из examples.py → чат-JSONL + валидация.

Запуск:  python build.py        (из каталога datasets/quests)

Что параметризовано на ВХОДЕ (модель только копирует/подставляет, не выдумывает):
  kind, theme, tier, giver, focus, cast, reward, prerequisites, allowed_preds.
Что движок делает САМ (убрано из выхода модели):
  quest_id, world_bindings — выводятся; rewards — считаются по таблице (tier × kind),
  фракция награды берётся из фракции заказчика; prerequisites — вход, не выход.
Невалидное не пишется.
"""

from __future__ import annotations

import json
import os
import re

SYS = (
    "You are a D&D 5e quest designer for a Sword-Coast frontier campaign (Lost Mine of "
    "Phandalin). You are given a quest request that includes a cast (factions, NPCs, item "
    "templates, locations), and fixed fields: kind, theme, tier, giver, reward, "
    "allowed_preds, prerequisites. Output ONE JSON object — a complete quest — that echoes "
    "kind/theme/tier/giver_ref/rewards exactly from the request and uses only ids from the "
    "cast (plus pc:hero). Every stage completion predicate MUST be one of allowed_preds. Do "
    "NOT invent npc:/place:/tmpl:/faction: ids, reward numbers, quest ids or world bindings — "
    "those are fixed or engine-derived. You author only: title, hook, framing, giver_lines, "
    "the stage objectives and their completion predicates (chosen from allowed_preds), and "
    "objective_text/completion_text. Narrative is Russian, in-character. Output ONLY the JSON."
)

PREDS = {"Flag", "NpcDead", "LairCleared", "KnowsFact", "HasItem", "HasItemQty",
         "ItemInContainer", "TalkedTo", "NpcAtPlace", "AnyOf"}
KINDS = {"main", "side", "board", "faction", "emergent"}
EFFECTS = {"set_flag", "complete"}
ENTITY_RE = re.compile(r"^(npc|place|building|site|room|tmpl|it|shop|faction):[A-Za-z0-9_]+$")

# награды по тиру (gp, xp) и множитель по типу квеста; репутация по тиру
REWARD_TABLE = {1: (25, 100), 2: (75, 300), 3: (150, 550), 4: (300, 850), 5: (600, 1500)}
KIND_MULT = {"board": 0.8, "side": 1.0, "faction": 1.0, "emergent": 0.9, "main": 1.3}
REP_BY_TIER = {1: 0.1, 2: 0.15, 3: 0.2, 4: 0.25, 5: 0.3}

# допустимые предикаты по теме (модель выбирает только из них)
THEME_PREDS = {
    "retrieve": {"HasItem", "TalkedTo", "AnyOf", "Flag"},
    "deliver": {"HasItem", "TalkedTo"},
    "gather": {"HasItemQty", "TalkedTo"},
    "bounty": {"NpcDead", "Flag"},
    "hunt": {"KnowsFact", "NpcDead", "Flag", "AnyOf"},
    "clear": {"LairCleared", "Flag"},
    "escort": {"NpcAtPlace", "Flag"},
    "rescue": {"NpcAtPlace", "Flag"},
    "talk": {"TalkedTo", "KnowsFact", "Flag"},
    "diplomacy": {"TalkedTo", "Flag", "AnyOf"},
    "recruit": {"TalkedTo", "Flag"},
    "mystery": {"KnowsFact", "TalkedTo", "AnyOf"},
    "investigate": {"KnowsFact", "Flag", "AnyOf", "TalkedTo"},
    "explore": {"HasItem", "KnowsFact", "Flag", "AnyOf", "TalkedTo"},
    "heist": {"HasItem", "Flag", "TalkedTo"},
    "smuggle": {"HasItem", "TalkedTo", "NpcAtPlace", "Flag"},
    "capture": {"Flag", "TalkedTo"},
    "extort": {"Flag", "TalkedTo"},
    "sabotage": {"Flag", "TalkedTo"},
    "defend": {"Flag"},
    "protect": {"Flag"},
    "cleanse": {"Flag", "TalkedTo"},
    "restore": {"Flag"},
}
THEMES = set(THEME_PREDS)


def _giver_faction(spec: dict) -> str | None:
    for n in spec.get("cast", {}).get("npcs", []):
        if n.get("id") == spec.get("giver"):
            return n.get("faction")
    return None


def reward_for(spec: dict) -> dict:
    """Детерминированная награда: таблица тира × множитель типа + репутация фракции заказчика."""
    gp, xp = REWARD_TABLE[spec["tier"]]
    mult = KIND_MULT.get(spec.get("kind"), 1.0)
    fac = _giver_faction(spec)
    rep = {fac: REP_BY_TIER[spec["tier"]]} if fac else {}
    return {"currency": {"gp": int(gp * mult)}, "xp": int(xp * mult), "items": [], "faction_rep": rep}


def cast_ids(spec: dict) -> set[str]:
    ids = {"pc:hero"}
    for group in ("factions", "npcs", "items", "locations"):
        for e in spec.get("cast", {}).get(group, []):
            if e.get("id"):
                ids.add(e["id"])
    return ids


def _entity_ids(obj) -> set[str]:
    found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and ENTITY_RE.match(k):
                found.add(k)
            found |= _entity_ids(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= _entity_ids(v)
    elif isinstance(obj, str) and ENTITY_RE.match(obj):
        found.add(obj)
    return found


def _pred_names(p, out: set) -> set:
    if isinstance(p, dict) and p.get("pred"):
        out.add(p["pred"])
        if p["pred"] == "AnyOf":
            for sub in p.get("args", []):
                _pred_names(sub, out)
    return out


def _check_pred(p) -> str | None:
    if not isinstance(p, dict) or p.get("pred") not in PREDS:
        return f"bad predicate: {p}"
    if p["pred"] == "AnyOf":
        for sub in p.get("args", []):
            err = _check_pred(sub)
            if err:
                return err
    elif not isinstance(p.get("args"), list) or not p["args"]:
        return f"predicate {p['pred']} needs args"
    return None


def enrich_spec(spec: dict, quest: dict) -> dict:
    """Полный вход: фиксируем kind/reward/prerequisites/allowed_preds (детерминированно)."""
    s = {
        "kind": quest["kind"], "tier": spec["tier"], "theme": spec["theme"],
        "giver": spec["giver"], "focus": spec.get("focus"),
        "reward": reward_for({**spec, "kind": quest["kind"]}),
        "allowed_preds": sorted(THEME_PREDS.get(spec["theme"], set())),
        "prerequisites": list(quest.get("prerequisites", [])),
        "world_facts": spec.get("world_facts", []),
        "constraints": spec.get("constraints", ""),
        "cast": spec.get("cast", {}),
    }
    return s


def clean_quest(quest: dict, spec_in: dict) -> dict:
    """Выход модели: без quest_id/world_bindings/prerequisites; rewards = заданный бюджет."""
    q = {k: v for k, v in quest.items()
         if k not in ("quest_id", "world_bindings", "prerequisites", "rewards")}
    q["rewards"] = spec_in["reward"]
    return q


def validate(quest: dict, spec_in: dict) -> str | None:
    for key in ("kind", "title", "theme", "tier", "giver_ref", "stages", "objective_text"):
        if key not in quest:
            return f"missing key: {key}"
    if quest["kind"] not in KINDS:
        return f"unknown kind: {quest['kind']}"
    if quest["theme"] not in THEMES:
        return f"unknown theme: {quest['theme']}"
    if spec_in["kind"] != quest["kind"]:
        return f"kind != spec.kind ({quest['kind']} / {spec_in['kind']})"
    if spec_in["theme"] != quest["theme"]:
        return f"theme != spec.theme ({quest['theme']} / {spec_in['theme']})"
    if spec_in["giver"] != quest["giver_ref"]:
        return f"giver_ref != spec.giver ({quest['giver_ref']} / {spec_in['giver']})"
    allowed = set(spec_in["allowed_preds"])
    stages = quest["stages"]
    if not isinstance(stages, list) or not stages:
        return "no stages"
    ids = {s.get("id") for s in stages}
    completes = False
    for s in stages:
        for k in ("id", "objective", "completion"):
            if k not in s:
                return f"stage missing {k}: {s.get('id')}"
        err = _check_pred(s["completion"])
        if err:
            return f"stage {s['id']}: {err}"
        used = _pred_names(s["completion"], set())
        if not used <= allowed:
            return f"stage {s['id']}: predicates {sorted(used - allowed)} not in allowed_preds for theme '{quest['theme']}'"
        for eff in s.get("on_complete", []):
            if eff.get("effect") not in EFFECTS:
                return f"stage {s['id']}: bad effect {eff}"
            if eff["effect"] == "complete":
                completes = True
        for nxt in s.get("next", []):
            if nxt not in ids:
                return f"stage {s['id']}: dangling next '{nxt}'"
    if not completes:
        return "no stage emits effect 'complete'"
    invented = _entity_ids(quest) - cast_ids(spec_in)
    if invented:
        return f"references ids outside the cast: {sorted(invented)}"
    return None


def sample(spec_in: dict, quest_out: dict) -> dict:
    return {"messages": [
        {"role": "system", "content": SYS},
        {"role": "user", "content": json.dumps(spec_in, ensure_ascii=False)},
        {"role": "assistant", "content": json.dumps(quest_out, ensure_ascii=False)}]}


def main() -> None:
    from examples import QUESTS
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "quests.jsonl")
    written, bad, seen = 0, 0, set()
    with open(out, "w", encoding="utf-8") as f:
        for ex in QUESTS:
            quest, raw_spec = ex["quest"], ex["spec"]
            spec_in = enrich_spec(raw_spec, quest)
            err = validate(quest, spec_in)
            if quest.get("quest_id") in seen:
                err = err or f"duplicate quest_id: {quest['quest_id']}"
            if err:
                bad += 1
                print(f"  ✗ {quest.get('quest_id', '?')}: {err}")
                continue
            seen.add(quest.get("quest_id"))
            f.write(json.dumps(sample(spec_in, clean_quest(quest, spec_in)), ensure_ascii=False) + "\n")
            written += 1
    print(f"\nwrote {written} samples → {out}" + (f"  ({bad} invalid skipped)" if bad else ""))
    from collections import Counter
    print("themes:", dict(Counter(e["quest"]["theme"] for e in QUESTS)))
    print("kinds: ", dict(Counter(e["quest"]["kind"] for e in QUESTS)))
    print("tiers: ", dict(sorted(Counter(e["quest"]["tier"] for e in QUESTS).items())))


if __name__ == "__main__":
    main()
