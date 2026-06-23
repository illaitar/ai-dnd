"""Out-of-domain проверка квест-адаптера: новые сеттинги/каст, та же структура спеки.

Запуск НА СЕРВЕРЕ (Ollama локально):
    . .venv/bin/activate && python eval_ood.py

Цель — отличить «выучил задачу» от «запомнил 200 примеров». Спеки ниже — НЕ из
Фандалина (ледяной север, пираты, подземье, пустыня, город). Метрика — тот же
валидатор квест-билда (echo полей, предикаты из allowed, никаких выдуманных id).
Печатает вердикт base vs adapter и сам сгенерённый квест для глаз.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "datasets", "quests"))

import build as quest_build  # noqa: E402  (SYS + validate + cast_ids)
from aidnd.inference.client import OllamaClient, OllamaError  # noqa: E402
from eval_compare import extract_json  # noqa: E402

OOD = [
    ("ледяной север / clear", {
        "kind": "side", "tier": 2, "theme": "clear", "giver": "npc:elder_revjak",
        "reward": {"currency": {"gp": 75}, "xp": 300, "items": [], "faction_rep": {"faction:reghed_nomads": 0.15}},
        "allowed_preds": ["Flag", "LairCleared"], "prerequisites": [],
        "world_facts": ["ледяные тролли заняли курган предков", "племя не может хоронить мёртвых"],
        "constraints": "clear the lair",
        "cast": {"factions": [{"id": "faction:reghed_nomads", "name": "Кочевники Регхеда"}],
                 "npcs": [{"id": "npc:elder_revjak", "name": "Старейшина Ревьяк", "role": "elder", "faction": "faction:reghed_nomads", "place": "place:tent_camp"},
                          {"id": "npc:ice_troll_matriarch", "name": "Матриарх ледяных троллей", "role": "boss", "hostile": True, "place": "place:frozen_barrow"}],
                 "items": [], "locations": [{"id": "place:frozen_barrow", "name": "Промёрзший курган", "kind": "room"}]}}),
    ("пиратский архипелаг / heist", {
        "kind": "faction", "tier": 3, "theme": "heist", "giver": "npc:captain_morwenna",
        "reward": {"currency": {"gp": 150}, "xp": 550, "items": [], "faction_rep": {"faction:black_sails": 0.2}},
        "allowed_preds": ["Flag", "HasItem", "TalkedTo"], "prerequisites": [],
        "world_facts": ["губернатор хранит Рубин Кракена в сейфе форта", "Чёрные паруса хотят его выкрасть"],
        "constraints": "heist; steal the item",
        "cast": {"factions": [{"id": "faction:black_sails", "name": "Чёрные паруса"}],
                 "npcs": [{"id": "npc:captain_morwenna", "name": "Капитан Морвенна", "role": "pirate_captain", "faction": "faction:black_sails", "place": "place:hidden_cove"},
                          {"id": "npc:governor_aldric", "name": "Губернатор Алдрик", "role": "governor", "place": "place:fort_vault"}],
                 "items": [{"id": "tmpl:kraken_ruby", "name": "Рубин Кракена"}],
                 "locations": [{"id": "place:fort_vault", "name": "Сейф форта", "kind": "room"}, {"id": "place:hidden_cove", "name": "Тайная бухта", "kind": "site"}]}}),
    ("подземье / diplomacy", {
        "kind": "main", "tier": 4, "theme": "diplomacy", "giver": "npc:matron_zaviel",
        "reward": {"currency": {"gp": 300}, "xp": 850, "items": [], "faction_rep": {"faction:house_xular": 0.25}},
        "allowed_preds": ["AnyOf", "Flag", "TalkedTo"], "prerequisites": [],
        "world_facts": ["дом Ксулар на грани войны с гильдией свечников", "нужен посредник"],
        "constraints": "broker peace",
        "cast": {"factions": [{"id": "faction:house_xular", "name": "Дом Ксулар"}, {"id": "faction:candle_guild", "name": "Гильдия свечников"}],
                 "npcs": [{"id": "npc:matron_zaviel", "name": "Матрона Завиэль", "role": "matron", "faction": "faction:house_xular", "place": "place:obsidian_spire"},
                          {"id": "npc:guildmaster_phenrir", "name": "Гильдмастер Фенрир", "role": "guildmaster", "faction": "faction:candle_guild", "place": "place:fungal_market"}],
                 "items": [], "locations": [{"id": "place:obsidian_spire", "name": "Обсидиановый шпиль", "kind": "building"}, {"id": "place:fungal_market", "name": "Грибной рынок", "kind": "site"}]}}),
    ("пустыня / escort", {
        "kind": "side", "tier": 2, "theme": "escort", "giver": "npc:sheikh_amar",
        "reward": {"currency": {"gp": 75}, "xp": 300, "items": [], "faction_rep": {"faction:sand_riders": 0.15}},
        "allowed_preds": ["Flag", "NpcAtPlace"], "prerequisites": [],
        "world_facts": ["караван должен пройти через земли гулей", "песчаные всадники просят охрану"],
        "constraints": "escort to destination",
        "cast": {"factions": [{"id": "faction:sand_riders", "name": "Песчаные всадники"}],
                 "npcs": [{"id": "npc:sheikh_amar", "name": "Шейх Амар", "role": "sheikh", "faction": "faction:sand_riders", "place": "place:oasis_camp"},
                          {"id": "npc:merchant_yusra", "name": "Торговка Юсра", "role": "merchant", "place": "place:oasis_camp"}],
                 "items": [], "locations": [{"id": "place:oasis_camp", "name": "Лагерь у оазиса", "kind": "site"}, {"id": "place:sunken_temple", "name": "Затонувший храм", "kind": "site"}]}}),
    ("город / mystery", {
        "kind": "board", "tier": 3, "theme": "mystery", "giver": "npc:inspector_calla",
        "reward": {"currency": {"gp": 120}, "xp": 550, "items": [], "faction_rep": {"faction:city_watch": 0.2}},
        "allowed_preds": ["AnyOf", "KnowsFact", "TalkedTo"], "prerequisites": [],
        "world_facts": ["часовщик исчез, башенные часы бьют тринадцать", "горожане напуганы"],
        "constraints": "solve the mystery",
        "cast": {"factions": [{"id": "faction:city_watch", "name": "Городская стража"}],
                 "npcs": [{"id": "npc:inspector_calla", "name": "Инспектор Калла", "role": "inspector", "faction": "faction:city_watch", "place": "place:watch_house"},
                          {"id": "npc:apprentice_tomas", "name": "Подмастерье Томас", "role": "witness", "place": "place:clocktower"}],
                 "items": [], "locations": [{"id": "place:clocktower", "name": "Часовая башня", "kind": "building"}, {"id": "place:watch_house", "name": "Дом стражи", "kind": "building"}]}}),
]


def resolve(client, tag):
    inst = set(client.list_models())
    return tag if tag in inst else (f"{tag}:latest" if f"{tag}:latest" in inst else None)


def gen_validate(client, model, spec):
    msgs = [{"role": "system", "content": quest_build.SYS},
            {"role": "user", "content": json.dumps(spec, ensure_ascii=False)}]
    out = client.chat(model, msgs, options={"temperature": 0})["content"]
    q = extract_json(out)
    if q is None:
        return None, "no-json"
    return q, quest_build.validate(q, spec)


def main():
    client = OllamaClient()
    base = resolve(client, "qwen3.5:9b")
    adapter = resolve(client, "aidnd-quest")
    print(f"base={base}  adapter={adapter}\n")
    b_ok = a_ok = 0
    for label, spec in OOD:
        print("=" * 70)
        print(f"OOD: {label}  (giver={spec['giver']}, theme={spec['theme']}, tier={spec['tier']})")
        bq, berr = gen_validate(client, base, spec)
        aq, aerr = gen_validate(client, adapter, spec)
        b_ok += berr is None
        a_ok += aerr is None
        print(f"  BASE    : {'✅ valid' if berr is None else '❌ ' + str(berr)}")
        print(f"  ADAPTER : {'✅ valid' if aerr is None else '❌ ' + str(aerr)}")
        if aq:
            print(f"    title : {aq.get('title')}")
            hook = (aq.get('hook') or '')[:160]
            print(f"    hook  : {hook}")
            for s in aq.get("stages", [])[:3]:
                print(f"    stage {s.get('id')}: {str(s.get('objective'))[:80]}  → {json.dumps(s.get('completion'), ensure_ascii=False)[:90]}")
    print("\n" + "=" * 70)
    print(f"ИТОГ OOD ({len(OOD)} спеков):  base {b_ok}/{len(OOD)}   adapter {a_ok}/{len(OOD)}")


if __name__ == "__main__":
    main()
