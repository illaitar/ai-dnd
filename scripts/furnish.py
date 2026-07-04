"""Обстановка ПУЛА зданий зонами и предметами (docs/locations.md, шаг 1).

Батч по building_pool: шаблон зон (content/zones.json) + LLM-наполнение каждой зоны
(роль furnisher, каждый предмет отдельной записью). Пишет data["zones"] обратно в пул
(worlds.db). Resume: строки с уже готовыми zones пропускаются (перегенерить: --force).

Запуск:  .venv/bin/python scripts/furnish.py --limit 15            # малая часть, отладка
         .venv/bin/python scripts/furnish.py --kind key            # все значимые
Флаги: --limit N --kind key|res --concurrency K --force
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def _setenv() -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        p = os.path.join(ROOT, ".secrets", "deepseek.key")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                os.environ["DEEPSEEK_API_KEY"] = f.read().strip()
    if os.environ.get("DEEPSEEK_API_KEY"):
        os.environ.setdefault("AIDND_PROFILE", "deepseek")


_setenv()

from aidnd.inference import ModelManager  # noqa: E402
from aidnd.worldgen import WorldStore  # noqa: E402
from aidnd.worldgen.furnish import furnish_building  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Обстановка пула зданий зонами и предметами")
    ap.add_argument("--limit", type=int, default=0, help="0 = все подходящие")
    ap.add_argument("--kind", default="key", choices=("key", "res"))
    ap.add_argument("--concurrency", type=int, default=0, help="0 = по бэкенду")
    ap.add_argument("--force", action="store_true", help="перегенерить и уже обставленные")
    a = ap.parse_args()

    mgr = ModelManager()
    if not mgr.available():                    # пул — прод-данные: без LLM не обставляем
        sys.exit("LLM недоступен (профиль/ключ) — обстановку без модели не генерим")
    store = WorldStore()
    rows = sorted(store.pool_buildings(a.kind), key=lambda r: r["id"])   # стабильный порядок
    todo = [r for r in rows if a.force or not r["data"].get("zones")]
    if a.limit:
        todo = todo[: a.limit]
    conc = a.concurrency or mgr.enrich_concurrency()
    print(f"пул {a.kind}: {len(rows)} зданий, к обстановке {len(todo)}, параллельность {conc}")

    def work(row):
        data = furnish_building(row["data"], row["btype"], mgr, kind=row["kind"])
        store.pool_save_building(row["id"], row["kind"], row["btype"], data)
        n = sum(len(z["objects"]) for z in data["zones"])
        return row["id"], row["btype"], len(data["zones"]), n

    done = fails = 0
    with ThreadPoolExecutor(max_workers=conc) as ex:
        futs = {ex.submit(work, r): r["id"] for r in todo}
        for f in as_completed(futs):
            try:
                bid, btype, nz, no = f.result()
                done += 1
                print(f"  [{done}/{len(todo)}] {bid} «{btype}»: {nz} зон, {no} предметов")
            except Exception as exc:                     # noqa: BLE001 — батч не роняем, итог честный
                fails += 1
                print(f"  ✗ {futs[f]}: {exc}")
    print(f"готово: {done} ок, {fails} ошибок")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
