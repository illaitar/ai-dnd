"""Батч-генерация ПУЛА ЗДАНИЙ (мир-агностичный банк фактшитов), зеркало peoplegen.

Как с NPC: большой пул готовых зданий; мир при создании раздаёт из пула БЕЗ LLM.
kind='key' — значимые (таверны/кузницы/лавки, с сервисами), kind='res' — жилые дома.
Имена в пуле НЕЙТРАЛЬНЫ к городу (без региона в промпте) — вывеска не привязана к месту.

Запуск:  .venv/bin/python scripts/buildinggen.py --keys 180 --res 420
Флаги: --keys N --res N --seed S --concurrency K --resume
"""

from __future__ import annotations

import argparse
import os
import random
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

from aidnd.worldgen import WorldStore  # noqa: E402
from aidnd.worldgen.enrich_llm import BuildingCtx, LLMEnricher  # noqa: E402

# типы значимых зданий (широкая палитра фронтирного городка)
KEY_TYPES = [
    "Таверна", "Трактир с комнатами", "Кузница", "Лавка всякой всячины", "Лавка зелий и трав",
    "Храм", "Часовня", "Пекарня", "Мясная лавка", "Целебница", "Конюшня", "Склад",
    "Мастерская плотника", "Мастерская кожевника", "Швейная мастерская", "Дом старосты",
    "Гильдия", "Купеческий дом", "Ломбард-меняльня", "Рыбная лавка", "Оружейная лавка",
    "Свечная мастерская", "Гончарная мастерская", "Пивоварня", "Мельница у окраины",
    "Баня", "Игорный дом", "Книжная лавка писца",
]
# колориты жилых домов (occupant-профессии для разнообразия)
RES_FLAVORS = [
    "Дом рыбака", "Дом кожевника", "Дом вдовы", "Дом стражника", "Дом плотника", "Дом прачки",
    "Дом охотника", "Дом пекаря", "Дом сапожника", "Дом возчика", "Дом швеи", "Дом углежога",
    "Дом травницы", "Дом каменщика", "Дом бондаря", "Дом рудокопа", "Дом писца", "Дом повитухи",
    "Дом старой четы", "Дом многодетной семьи", "Дом одинокого старика", "Дом молодожёнов",
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Генерация пула зданий")
    ap.add_argument("--keys", type=int, default=180)
    ap.add_argument("--res", type=int, default=420)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--concurrency", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    from aidnd.inference import ModelManager
    mgr = ModelManager()
    if not mgr.available():
        print("LLM недоступен."); sys.exit(1)
    enricher = LLMEnricher(mgr)
    conc = args.concurrency or mgr.enrich_concurrency()
    store = WorldStore()
    rng = random.Random(args.seed)

    jobs = []                                             # (bid, kind, btype, ctx)
    for i in range(args.keys):
        t = KEY_TYPES[i % len(KEY_TYPES)]
        bid = f"bp:key:{i:04d}"
        jobs.append((bid, "key", t, BuildingCtx(
            id=bid, name_hint=t, role_hint="значимое здание небольшого городка",
            landmarks=rng.choice([[], [], ["river"], ["gate"], ["bridge"], ["wall"]]))))
    for i in range(args.res):
        t = RES_FLAVORS[i % len(RES_FLAVORS)]
        bid = f"bp:res:{i:04d}"
        jobs.append((bid, "res", t, BuildingCtx(
            id=bid, name_hint=t, role_hint="жилой дом горожанина",
            landmarks=rng.choice([[], [], [], ["river"], ["wall"]]))))

    if args.resume:
        have = {b["id"] for b in store.pool_buildings()}
        jobs = [j for j in jobs if j[0] not in have]
    print(f"пул зданий: генерим {len(jobs)} (key+res), конкурентность {conc}")

    done = fail = 0

    def gen(job):
        bid, kind, btype, ctx = job
        data = enricher.describe_building(ctx)
        return bid, kind, btype, data

    with ThreadPoolExecutor(max_workers=conc) as ex:
        futs = [ex.submit(gen, j) for j in jobs]
        for f in as_completed(futs):
            try:
                bid, kind, btype, data = f.result()
            except Exception as exc:                      # noqa: BLE001
                fail += 1; print(f"\n! {exc}"); continue
            if data:
                store.pool_save_building(bid, kind, btype, data)
                done += 1
            else:
                fail += 1
            print(f"\r  готово {done} · ошибок {fail}   ", end="", flush=True)
    print(f"\nпул: {store.pool_count('key')} key + {store.pool_count('res')} res.")


if __name__ == "__main__":
    main()
