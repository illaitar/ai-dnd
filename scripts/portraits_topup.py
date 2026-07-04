"""Догенерация портретов до потолка: NPC без портретов получают их, пока в банке
не станет CAP душ с лицами. Существующие не трогаем. Ключ: .secrets/fal.key."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
for f, v in (("deepseek.key", "DEEPSEEK_API_KEY"), ("fal.key", "FAL_KEY")):
    p = os.path.join(ROOT, ".secrets", f)
    if os.path.exists(p) and not os.environ.get(v):
        os.environ[v] = open(p).read().strip()
from aidnd.worldgen import WorldStore
from aidnd.worldgen.imagegen import get_imagegen

CAP = int(sys.argv[1]) if len(sys.argv) > 1 else 500
PORTRAITS_DIR = os.path.join(ROOT, "data", "portraits")
store, img = WorldStore(), get_imagegen()
if not img.available():
    print("Flux недоступен"); sys.exit(1)
have = {d for d in os.listdir(PORTRAITS_DIR)} if os.path.isdir(PORTRAITS_DIR) else set()
have = {h for h in have if h.startswith("pool")}
ids = sorted(store.person_ids())
todo = [pid for pid in ids if pid.replace(":", "_") not in have and pid not in have][: max(0, CAP - len(have))]
print(f"с портретами: {len(have)} · потолок {CAP} · догенерим {len(todo)}")

def gen(pid):
    p = store.get_person(pid)
    return pid, img.portraits(pid, p["persona"], seed=1000 + int(pid.split(":")[1]), out_dir=PORTRAITS_DIR)

n = e = 0
with ThreadPoolExecutor(max_workers=6) as ex:
    for f in as_completed([ex.submit(gen, pid) for pid in todo]):
        try:
            f.result(); n += 1
        except Exception as exc:  # noqa: BLE001
            e += 1; print("!", exc)
        print(f"\r  готово {n} · ошибок {e}   ", end="", flush=True)
print("\nитого с портретами:", len(have) + n)
