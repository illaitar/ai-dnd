"""Демонстрация интеграции LLM-планировщика с механическим ядром: LLM ОДИН раз придумывает
долгосрочную агенду (по натуре+памяти), дальше механика КАЖДЫЙ тик тянет текущую веху реактивно.
LLM тут = планировщик (и нарратор), решения по тикам — детерминированное ядро.

  AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=$(tr -d '\\n\\r' < .secrets/deepseek.key) \\
      .venv/bin/python scripts/mind_plan_demo.py 7 8
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aidnd.inference import ModelManager  # noqa: E402
from aidnd.mind import advance_agendas, apply, decide, perceive  # noqa: E402
from aidnd.mind.agenda import StubPlanner  # noqa: E402
from aidnd.mind.llm_agent import plan_agenda  # noqa: E402
from aidnd.mind.tick import _decay_emotion, _decay_needs  # noqa: E402
from mind_sim import PLACE_DESC, ROLES, build  # noqa: E402

# кому что вспомнить (материал для планировщика) → ожидаем разные агенды
SEED_MEMORY = {
    "Сэм": [("Бран прилюдно опозорил меня в трактире, я поклялся расквитаться", 0.9, "grudge")],
    "Лия": [("Мечтаю выкупить лучший прилавок на рынке и зажить богато", 0.7, "dream")],
    "Мордо": [("У торговки Лии на поясе тугой кошель — лёгкая пожива", 0.8, "note")],
    "Тим": [("Заглядываюсь на трактирщицу Нэлл, да всё робею", 0.6, "note")],
}


def run(seed=7, ticks=8):
    mgr = ModelManager()
    w, minds = build()
    rng = random.Random(seed)
    for nid, mems in SEED_MEMORY.items():
        for txt, imp, kind in mems:
            minds[nid].memory.add(txt, 0, importance=imp, kind=kind)

    planners = list(SEED_MEMORY)
    ctx = {"roles": ROLES, "place_desc": PLACE_DESC}
    online = mgr.available()
    stub = StubPlanner()
    print("═══ ПЛАНИРОВАНИЕ (LLM" + (" онлайн" if online else " недоступен → StubPlanner") + ") ═══")
    for nid in planners:
        st = minds[nid]
        ag = (plan_agenda(st, w, ctx, mgr) if online else None) or stub.plan(
            st, w, {"mark": "Лия", "beloved": "Нэлл", "dream": "прилавок"})
        st.agendas = [ag] if ag else []
        m = ag.current() if ag else None
        print(f"  {nid:6} → «{ag.summary}» [{ag.kind}, важность {ag.importance:.2f}] "
              f"вехи: {len(ag.milestones)}; сейчас: {m.desc if m else '—'} "
              f"({m.kind}→{m.target})" if ag else f"  {nid}: (без агенды)")

    print("\n═══ ИСПОЛНЕНИЕ (механическое ядро, по тикам) ═══")
    for t in range(1, ticks + 1):
        for st in minds.values():
            _decay_needs(st)
            _decay_emotion(st)
        order = list(minds.values())
        rng.shuffle(order)
        print(f"\n─── тик {t} " + "─" * 40)
        for st in order:
            b = w.bodies[st.config.id]
            if b.down():
                continue
            (a, g, u), _ = decide(st, w, perceive(st, w), temp=0.22, rng=rng)
            ev = apply(a, st, w)
            advance_agendas(st, w)
            if st.config.id in planners:                # показываем только героев с агендой
                note = ""
                if ev.get("hit"):
                    tb = w.bodies[ev["hit"]]
                    note = f"  ⟹ {ev['hit']} hp={tb.hp}" + ("  ☠" if tb.down() else "")
                elif ev.get("took"):
                    note = f"  ⟹ забрал «{ev['took']}»"
                ag = st.agendas[0] if st.agendas else None
                tag = f"[{ag.kind}:{ag.status}]" if ag else ""
                print(f"  {st.config.name:6} @{b.place:8} {a.label():18} ({g.kind if g else '—'}) "
                      f"{tag}{note}")

    print("\n═══ ИТОГ АГЕНД ═══")
    for nid in planners:
        ag = minds[nid].agendas[0] if minds[nid].agendas else None
        b = w.bodies[nid]
        print(f"  {nid:6} @{b.place:8} {'☠' if b.down() else 'жив'}: "
              + (f"«{ag.summary}» — {ag.status}, веха {ag.cursor}/{len(ag.milestones)}"
                 f"  добыча:{', '.join(i.name for i in b.loot) or '—'}" if ag else "нет агенды"))


if __name__ == "__main__":
    run(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 7,
        ticks=int(sys.argv[2]) if len(sys.argv) > 2 else 8)
