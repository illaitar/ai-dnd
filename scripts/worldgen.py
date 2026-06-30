"""Скрипт начальной генерации мира: город (граф) + слой насыщения локаций (LLM).

Первая ручка — две опции насыщения:
  --enrich keys  — только ключевые локации
  --enrich all   — каждое здание (вычислительно тяжело — это ожидаемо)

LLM-модуль (aidnd.worldgen.enrich_llm) отделён от скрипта. Конкурентность по умолчанию берётся
из модели (облако параллелит, локальная Ollama — последовательно). Прогресс — здания/батчи.

Примеры:
  AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=... .venv/bin/python scripts/worldgen.py --seed 7 --key 10 --enrich keys
  .venv/bin/python scripts/worldgen.py --enrich all --stub            # офлайн-заглушка, без сети
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.citygraph import CityParams, generate  # noqa: E402
from aidnd.worldgen import (  # noqa: E402
    LLMEnricher,
    StubEnricher,
    WorldStore,
    enrich_city,
    store_world,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="Генерация мира: город + насыщение локаций")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--key", type=int, default=10, help="число ключевых зданий")
    ap.add_argument("--enrich", choices=["keys", "all"], default="all",
                    help="keys — только ключевые локации; all — каждое здание")
    ap.add_argument("--world", type=int, default=0, help="id мира — сохранить насыщение в БД (0=не сохранять)")
    ap.add_argument("--db", default=None, help="путь к worlds.db (по умолч. <repo>/data/worlds.db)")
    ap.add_argument("--no-river", action="store_true")
    ap.add_argument("--no-walls", action="store_true")
    ap.add_argument("--concurrency", type=int, default=0, help="макс. одновременных промптов (0=авто)")
    ap.add_argument("--stub", action="store_true", help="без LLM (детерминированная заглушка)")
    ap.add_argument("--out", default="-", help="JSON-дамп (- = не писать, основное хранилище — БД)")
    args = ap.parse_args()

    city = generate(CityParams(seed=args.seed, key_buildings=args.key,
                               river=not args.no_river, walls=not args.no_walls))
    n_all = sum(1 for h in city.houses.values() if not h.building) + len(city.key_buildings)
    n_targets = len(city.key_buildings) if args.enrich == "keys" else n_all
    print(f"город seed={args.seed}: {city.stats()['nodes']} узлов, {len(city.houses)} домов, "
          f"{len(city.key_buildings)} ключевых. Насыщаем: {n_targets} ({args.enrich}).")

    if args.stub:
        enricher, conc = StubEnricher(), (args.concurrency or 8)
    else:
        from aidnd.inference import ModelManager
        mgr = ModelManager()
        if not mgr.available():
            print("LLM недоступен (профиль/ключ). Запусти с --stub или настрой модель.")
            sys.exit(1)
        enricher = LLMEnricher(mgr)
        conc = args.concurrency or mgr.enrich_concurrency()
    print(f"насыщение: до {conc} промптов одновременно.")

    _phase = [""]

    def on_prog(s):
        if s["phase"] != _phase[0]:               # новая фаза — с новой строки
            if _phase[0]:
                print()
            _phase[0] = s["phase"]
        bar = "#" * int(20 * s["pct"] / 100)
        print(f"\r  {s['phase']:<14} [{bar:<20}] {s['done']}/{s['total']} · "
              f"батч {s['batch']}/{s['batches_total']} · {s['pct']}%   ", end="", flush=True)

    enr = enrich_city(city, args.enrich, enricher, max_concurrent=conc, on_progress=on_prog)
    print()

    if args.world:
        store = WorldStore(args.db)
        store_world(store, args.world, city, enr)
        print(f"мир {args.world} → БД {store.path}: зданий в базе {store.count(args.world)}.")
    if args.out and args.out != "-":
        out = {"params": {"seed": args.seed, "key_buildings": args.key,
                          "river": not args.no_river, "walls": not args.no_walls, "enrich": args.enrich},
               "graph": city.debug_data(), "enrichment": enr.to_dict()}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    sub = sum(len(b.data.get("sub_rooms", [])) for b in enr.buildings.values())
    print(f"готово: насыщено {len(enr.buildings)} зданий, суб-помещений {sub}.")


if __name__ == "__main__":
    main()
