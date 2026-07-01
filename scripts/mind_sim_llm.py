"""Тот же городок, но КАЖДЫЙ NPC каждый тик спрашивает LLM «что делаю дальше» (полный контекст →
последовательность инструментов). Прямое сравнение с механическим ядром (scripts/mind_sim.py).

Запуск (ключ НЕ печатать/не коммитить):
  AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=$(tr -d '\\n\\r' < .secrets/deepseek.key) \\
      .venv/bin/python scripts/mind_sim_llm.py 7 6
"""

from __future__ import annotations

import os
import random
import sys
from collections import deque
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aidnd.inference import ModelManager  # noqa: E402
from aidnd.mind import perceive  # noqa: E402
from aidnd.mind.llm_agent import apply_actions, decide_llm  # noqa: E402
from aidnd.mind.tick import _decay_emotion, _decay_needs  # noqa: E402
from mind_sim import PLACE_DESC, ROLES, build  # noqa: E402


def run(seed=7, ticks=6):
    mgr = ModelManager()
    if not mgr.available():
        print("LLM недоступен: запусти с AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=... "
              "(ключ из .secrets/deepseek.key).")
        sys.exit(1)
    w, minds = build()
    rng = random.Random(seed)
    history = {nid: deque(maxlen=10) for nid in minds}
    last_actions = {nid: "—" for nid in minds}
    dev = {"Рэн", "Мордо"}

    for t in range(1, ticks + 1):
        for st in minds.values():
            _decay_needs(st)
            _decay_emotion(st)
        ctx = {"clock": t, "roles": ROLES, "place_desc": PLACE_DESC,
               "history": {k: list(v) for k, v in history.items()}, "last_actions": dict(last_actions)}

        # решения ПАРАЛЛЕЛЬНО на снимке начала тика (одновременный ход), затем применяем по очереди
        alive = [st for st in minds.values() if not w.bodies[st.config.id].down()]

        def _decide(st):
            return st.config.id, decide_llm(st, w, perceive(st, w), mgr, ctx)

        with ThreadPoolExecutor(max_workers=8) as ex:
            decisions = dict(ex.map(_decide, alive))

        print(f"\n─── тик {t} " + "─" * 46)
        order = [st.config.id for st in alive]
        rng.shuffle(order)
        for nid in order:
            st = minds[nid]
            if w.bodies[nid].down():
                continue
            d = decisions.get(nid, {"think": "", "actions": [{"tool": "wait"}]})
            log = apply_actions(d["actions"], st, w, t)
            label = " ".join(log)
            history[nid].append(label)
            last_actions[nid] = label
            mark = "†" if nid in dev else " "
            think = d.get("think", "")
            print(f" {mark}[{w.bodies[nid].place:8}] {st.config.name:6} {label:26} "
                  f"« {think[:70]} »")

    print("\n═══ итог " + "═" * 46)
    for nid, st in minds.items():
        b = w.bodies[nid]
        status = "☠" if b.down() else f"hp={b.hp}"
        print(f"  {st.config.name:6} @{b.place:8} {status:6} "
              f"страх={st.emotion['fear']:.2f} добыча:{', '.join(i.name for i in b.loot) or '—'}")


if __name__ == "__main__":
    run(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 7,
        ticks=int(sys.argv[2]) if len(sys.argv) > 2 else 6)
