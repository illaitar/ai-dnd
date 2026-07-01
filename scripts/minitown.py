"""Честная проверка: 3 здания, стражник + 10 крестьян + гуляка + наёмник. Никакого антагониста,
никаких агенд. Смотрим, «прикольно» ли. Чистое механическое ядро.
"""

from __future__ import annotations

import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aidnd.mind import TRAITS, Body, Item, NpcConfig, NpcState, apply, decide, perceive  # noqa: E402
from aidnd.mind.tick import _decay_emotion, _decay_needs  # noqa: E402
from aidnd.mind.world import World  # noqa: E402
from archetypes import ARCHETYPES  # noqa: E402

TR = {a[0]: a[2] for a in ARCHETYPES}
POW = {a[0]: a[3] for a in ARCHETYPES}
RES = {"трактир": [("похлёбка", "hunger"), ("застолье", "social")],
       "дом": [("лежанка", "fatigue"), ("очаг", "comfort")],
       "застава": [("дозор", "purpose")]}
SRC = {"hunger": "трактир", "fatigue": "дом", "comfort": "дом", "social": "трактир", "purpose": "застава"}


def mk(w, nid, arch, rng):
    cfg = NpcConfig(id=nid, name=nid, traits={**dict.fromkeys(TRAITS, 0.5), **TR[arch]})
    st = NpcState.from_config(cfg)
    for n in st.needs:
        st.needs[n] = rng.uniform(0.1, 0.5)
    st.needs_sources = {nd: {"source": pl} for nd, pl in SRC.items()}
    w.add(Body(id=nid, place="застава", power=POW[arch]))
    return st


def run(seed=3, ticks=8):
    w = World()
    for a, b in [("трактир", "площадь"), ("дом", "площадь"), ("застава", "площадь")]:
        w.link(a, b)
    for pl, res in RES.items():
        w.ground[pl] = [Item(n, .05, satisfies=s) for n, s in res]
    rng = random.Random(seed)
    minds = {}
    minds["Страж"] = mk(w, "Страж", "Стражник", rng)
    for i in range(1, 11):
        minds[f"Крестьянин{i}"] = mk(w, f"Крестьянин{i}", "Крестьянин", rng)
    minds["Гуляка"] = mk(w, "Гуляка", "Гуляка", rng)
    minds["Наёмник"] = mk(w, "Наёмник", "Наёмник", rng)
    w.npc_minds = minds

    incidents = 0
    for t in range(1, ticks + 1):
        for st in minds.values():
            _decay_needs(st)
            _decay_emotion(st)
        order = list(minds.values())
        rng.shuffle(order)
        kinds = Counter()
        spotlight = {}
        for st in order:
            (a, g, u), _ = decide(st, w, perceive(st, w), temp=0.2, rng=rng)
            ev = apply(a, st, w)
            kinds[a.kind] += 1
            if a.kind in ("attack", "take"):
                incidents += 1
            if st.config.id in ("Страж", "Наёмник", "Гуляка"):
                spotlight[st.config.id] = f"{a.label()} ({g.kind if g else '—'})"
        tally = ", ".join(f"{k}×{v}" for k, v in kinds.most_common())
        print(f"тик {t}: {tally}")
        print(f"        Страж: {spotlight.get('Страж','—'):22} "
              f"Наёмник: {spotlight.get('Наёмник','—'):22} Гуляка: {spotlight.get('Гуляка','—')}")

    print(f"\nЗА {ticks} ТИКОВ: нападений/краж — {incidents}. "
          f"Конфликтов, арестов, интриг, разговоров по существу — 0.")


if __name__ == "__main__":
    run(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 3,
        ticks=int(sys.argv[2]) if len(sys.argv) > 2 else 8)
