"""Батч-генерация ПУЛА NPC (мир-агностичный банк готовых людей), зеркало scripts/worldgen.py.

На каждого: механика (роль/11 черт/обаяние/богатство) → персона+инвентарь (LLM character_writer) →
4 портрета-эмоции (Flux schnell, общий seed) → БД people. Инкрементально, с resume.

Ключи из .secrets: deepseek.key (LLM), fal.key (портреты). Персона едет в data/worlds.db (коммитится),
портреты — файлами в data/portraits/<id>/ (в гит НЕ идут, на прод rsync).

Запуск (малый батч):  .venv/bin/python scripts/peoplegen.py --count 24
Флаги: --count N --seed S --concurrency K --no-portraits --resume
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
    """Подтянуть ключи из .secrets в окружение ДО импорта aidnd.config (он читает env на импорте)."""
    def load(fname, var):
        if os.environ.get(var):
            return
        p = os.path.join(ROOT, ".secrets", fname)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                os.environ[var] = f.read().strip()
    load("deepseek.key", "DEEPSEEK_API_KEY")
    load("fal.key", "FAL_KEY")
    if os.environ.get("DEEPSEEK_API_KEY"):
        os.environ.setdefault("AIDND_PROFILE", "deepseek")


_setenv()

from aidnd.inference import ModelManager                       # noqa: E402
from aidnd.mind import ABILITIES                               # noqa: E402
from aidnd.play.population import person_core                  # noqa: E402
from aidnd.worldgen import (LLMPersona, PersonaCtx, StubPersona,  # noqa: E402
                            WorldStore, get_imagegen)

PORTRAITS_DIR = os.path.join(ROOT, "data", "portraits")

# распределение архетипов в пуле: масса горожан + разброс ремёсел + немного лихого люда
MIX = (["горожанин"] * 10 + ["трактирщик", "кузнец", "лавочник", "стражник", "жрец",
       "знахарка", "бард", "мельник", "дубильщик", "сапожник"] * 2 + ["бродяга", "головорез"] * 2)


def _archetypes(count: int, seed: int) -> list[str]:
    m = random.Random(f"arch|{seed}")
    bag = MIX * (count // len(MIX) + 1)
    m.shuffle(bag)
    return bag[:count]


def _portraits_only(store) -> None:
    """Перегенерить портреты по уже сохранённым персонам (персоны/механику НЕ трогаем)."""
    img = get_imagegen()
    if not img.available():
        print("Flux недоступен — нечего делать"); return
    ids = sorted(store.person_ids())
    print(f"перегенерация портретов: {len(ids)} NPC")

    def rework(pid):
        p = store.get_person(pid)
        seed = 1000 + int(pid.split(":")[1])
        ports = img.portraits(pid, p["persona"], seed=seed, out_dir=PORTRAITS_DIR)
        return pid, p, ports

    n = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for fut in as_completed([ex.submit(rework, pid) for pid in ids]):
            pid, p, ports = fut.result()
            store.save_person(pid, p["role"], p["name"], p["charisma"], p["appearance"],
                              p["mech"], p["persona"], ports, p["seed"])
            n += 1
            print(f"  [{n}/{len(ids)}] {pid} {p['name']:22} sex={p['persona']['sex']} портретов:{len(ports)}")
    print("готово (портреты)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=24)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--no-portraits", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--portraits-only", action="store_true",
                    help="перегенерить только портреты по уже готовым персонам (дёшево итерировать промпт)")
    a = ap.parse_args()

    store = WorldStore()
    if a.portraits_only:
        _portraits_only(store)
        return
    mgr = ModelManager()
    online = mgr.available()
    enr = LLMPersona(mgr) if online else StubPersona()
    img = get_imagegen() if not a.no_portraits else None
    print(f"LLM: {'deepseek' if online else 'СТАБ (офлайн)'} · портреты: "
          f"{'Flux' if (img and img.available()) else 'выкл'} · банк сейчас: {store.people_count()}")

    roles = _archetypes(a.count, a.seed)
    done = store.person_ids() if a.resume else set()
    todo = [(i, r) for i, r in enumerate(roles) if f"pool:{i:04d}" not in done]
    print(f"к генерации: {len(todo)} из {a.count}")

    def work(item):
        i, role = item
        pid = f"pool:{i:04d}"
        rng = random.Random(f"{a.seed}|{i}")                   # свой поток на NPC → тред-безопасно
        core = person_core(role, rng)
        ctx = PersonaCtx(id=pid, name=core["name"], role=role, sex=core["sex"],
                         traits=core["traits"], charisma=core["charisma"], appearance=core["appearance"])
        persona = enr.describe(ctx) or StubPersona().describe(ctx)
        portraits = {}
        if img and img.available():
            portraits = img.portraits(pid, persona, seed=1000 + i, out_dir=PORTRAITS_DIR)
        mech = {"role": role, "traits": core["traits"], "abilities": dict.fromkeys(ABILITIES, 10)}
        return pid, role, core, persona, portraits

    n = 0
    with ThreadPoolExecutor(max_workers=max(1, a.concurrency)) as ex:
        for fut in as_completed([ex.submit(work, it) for it in todo]):
            pid, role, core, persona, portraits = fut.result()
            store.save_person(pid, role, core["name"], core["charisma"], core["appearance"],
                              {"role": role, "traits": core["traits"], "abilities": dict.fromkeys(ABILITIES, 10)},
                              persona, portraits, seed=a.seed)
            n += 1
            print(f"  [{n}/{len(todo)}] {pid} {role:11} {core['name']:22} "
                  f"портретов:{len(portraits)}")

    print(f"\nготово. в банке: {store.people_count()} · портреты → {PORTRAITS_DIR}")


if __name__ == "__main__":
    main()
