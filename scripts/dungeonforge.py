"""Ковка брифов подземелий в ПУЛ (worlds.db, kind='dungeon') — LLM только офлайн.

По 4 брифа на каждую среду логовищ: architect (история 3 слоя + биты + палитра) →
decorator (виньетки архетипов комнат с уликами по битам, валидация ссылок).
Запуск: AIDND_PROFILE=deepseek .venv/bin/python scripts/dungeonforge.py [--per-env N]
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from aidnd.combat.encounters import pick_encounter
from aidnd.inference import ModelManager
from aidnd.worldgen import WorldStore
from aidnd.worldgen.dungeonlore import forge_dungeon_brief

ENVS = ["Forest", "Hill", "Grassland", "Swamp", "Ruin", "Caverns"]


def folk_hint(env: str) -> list:
    names = []
    for cr in (0.5, 1.5, 3.0):
        for u in pick_encounter(cr, env, seed=f"hint|{env}|{cr}"):
            if u.name not in names:
                names.append(u.name)
    return names[:5]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-env", type=int, default=4)
    a = ap.parse_args()
    store = WorldStore()
    mgr = ModelManager()
    have = {r["id"] for r in store.pool_buildings("dungeon")}
    jobs = [(env, i) for env in ENVS for i in range(a.per_env)
            if f"bp:dung:{env.lower()}:{i}" not in have]
    print(f"брифов к ковке: {len(jobs)} (в пуле {len(have)})")

    def one(env, i):
        b = forge_dungeon_brief(env, folk_hint(env), mgr)
        store.pool_save_building(f"bp:dung:{env.lower()}:{i}", "dungeon", env, b)
        return env, i, b

    ok = err = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(one, env, i) for env, i in jobs]
        for f in as_completed(futs):
            try:
                env, i, b = f.result()
                ok += 1
                print(f"  [{ok}/{len(jobs)}] {env}:{i} «{b['name']}» — "
                      f"битов {len(b['bits'])}, виньеток {len(b['rooms'])}")
            except Exception as e:  # noqa: BLE001 — одна ковка не роняет батч
                err += 1
                print(f"  ✗ {e}")
    print(f"готово: {ok} ок, {err} ошибок")


if __name__ == "__main__":
    main()
