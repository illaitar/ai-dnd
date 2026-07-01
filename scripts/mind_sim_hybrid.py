"""ГИБРИД: механическое ядро даёт ранжированные побуждения (решительность/последствия), LLM выбирает
из верхних В ХАРАКТЕРЕ, добавляет реплику и ОПИСЫВАЕТ, что делает/думает. Лучшее из двух: consequential
акты — на детерминированном ядре, живой текст — на модели.

Запуск (ключ НЕ печатать/не коммитить):
  AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=$(tr -d '\\n\\r' < .secrets/deepseek.key) \\
      .venv/bin/python scripts/mind_sim_hybrid.py 7 6
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
from aidnd.mind.llm_agent import apply_actions, decide_hybrid  # noqa: E402
from aidnd.mind.tick import _decay_emotion, _decay_needs  # noqa: E402
from mind_sim import PLACE_DESC, ROLES, build  # noqa: E402


def run(seed=7, ticks=6):
    mgr = ModelManager()
    online = mgr.available()
    if not online:
        print("⚠ LLM недоступен — гибрид деградирует в чистую механику (запусти с AIDND_PROFILE=deepseek …).\n")
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
        alive = [st for st in minds.values() if not w.bodies[st.config.id].down()]

        def _decide(st):
            return st.config.id, decide_hybrid(st, w, perceive(st, w), mgr, ctx)

        with ThreadPoolExecutor(max_workers=8) as ex:
            decisions = dict(ex.map(_decide, alive))

        print(f"\n─── тик {t} " + "─" * 50)
        order = [st.config.id for st in alive]
        rng.shuffle(order)
        for nid in order:
            st = minds[nid]
            if w.bodies[nid].down():
                continue
            d = decisions[nid]
            log = apply_actions(d["actions"], st, w, t)
            label = " ".join(log)
            history[nid].append(label)
            last_actions[nid] = label
            mark = "†" if nid in dev else " "
            urge = d["prefs"][0][0] if d["prefs"] else "—"
            print(f" {mark}[{w.bodies[nid].place:8}] {st.config.name:6} {label:24}")
            if d.get("does") or d.get("think"):
                print(f"        побужд:{urge:16} · «{d.get('does', '')}» — {d.get('think', '')}")

    print("\n═══ итог " + "═" * 50)
    for nid, st in minds.items():
        b = w.bodies[nid]
        status = "☠" if b.down() else f"hp={b.hp}"
        print(f"  {st.config.name:6} @{b.place:8} {status:6} "
              f"страх={st.emotion['fear']:.2f} добыча:{', '.join(i.name for i in b.loot) or '—'}")


if __name__ == "__main__":
    run(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 7,
        ticks=int(sys.argv[2]) if len(sys.argv) > 2 else 6)
