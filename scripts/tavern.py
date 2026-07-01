"""Интеракция 10 РАЗНЫХ людей в таверне — механический мозг (с соц-целью converse). Смотрим, кто
с кем заговаривает, кто бирюком, кто приглядывается к чужому кошелю. Всё эмерджентно из черт/нужд/
обаяния/симпатий; никаких скриптов сцены. LLM не участвует (проверяем именно МЕХАНИКУ социалки).
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.mind import TRAITS, Body, Item, NpcConfig, NpcState, apply, decide, perceive  # noqa: E402
from aidnd.mind.tick import _decay_emotion, _decay_needs  # noqa: E402
from aidnd.mind.world import World  # noqa: E402

# (имя, роль, черты, charisma, appearance, needs, loot)
CAST = [
    ("Мара", "подавальщица", {"sociability": .85, "honesty": .6}, .70, .3, {"social": .5}, []),
    ("Лютик", "бард", {"sociability": .9, "charisma": 0, "curiosity": .7, "pride": .6}, .88, .35, {"social": .7, "novelty": .5}, []),
    ("Гарен", "стражник", {"lawful": .9, "loyalty": .8, "bravery": .8, "honesty": .8}, .35, .3, {"purpose": .5}, []),
    ("Скрип", "оборванец", {"greed": .9, "honesty": .1, "lawful": .15, "bravery": .4}, .2, .2, {"wealth": .6, "social": .15}, []),
    ("Тил", "юнец", {"sociability": .7, "bravery": .4}, .4, .25, {"social": .8}, []),
    ("Бром", "буян", {"irritability": .9, "bravery": .8, "pride": .8, "malice": .35}, .3, .3, {"fatigue": .6, "social": .4}, []),
    ("Обен", "купец", {"greed": .8, "sociability": .5, "honesty": .55, "lawful": .6}, .45, .8, {"social": .4}, [Item("кошель", .6)]),
    ("Сельма", "знахарка", {"honesty": .9, "sociability": .7, "malice": 0.0, "loyalty": .7}, .55, .3, {"social": .5}, []),
    ("Молчун", "чужак", {"sociability": .12, "curiosity": .5, "bravery": .5}, .25, .2, {"novelty": .4}, []),
    ("Дара", "наёмница", {"bravery": .8, "greed": .6, "honesty": .5, "loyalty": .4}, .4, .35, {"social": .3, "purpose": .4}, []),
]
# заранее сложившиеся симпатии
REL = {
    "Тил": {"Мара": .55},          # юнец влюблён в подавальщицу
    "Мара": {"Тил": .3, "Сельма": .6},
    "Сельма": {"Мара": .6},
}


def build():
    w = World()
    w.link("таверна", "улица")
    minds = {}
    for name, role, traits, cha, app, needs, loot in CAST:
        cfg = NpcConfig(id=name, name=name, role=role, traits={**dict.fromkeys(TRAITS, 0.5), **traits})
        st = NpcState.from_config(cfg)
        for k, v in needs.items():
            st.needs[k] = v
        st.relationships = {who: {"trust": .3, "affinity": a, "fear": 0.0} for who, a in REL.get(name, {}).items()}
        w.add(Body(id=name, place="таверна", charisma=cha, appearance=app,
                   loot=[Item(i.name, i.value) for i in loot]))
        minds[name] = st
    w.npc_minds = minds
    return w, minds


ICON = {"chat": "💬", "flatter": "🥰", "ask": "❓", "threat": "😠", "counter": "🤝", "accept": "🤝"}


def label(a, g):
    gk = g.kind if g else "—"
    if a.kind == "say":
        return f"{ICON.get(a.say, '💬')} {a.say}→{a.target}"
    if a.kind == "wait" and gk == "acquire":
        return "👁 выжидает (добыча в толпе)"
    if a.kind == "move":
        return f"→ {a.to}"
    if a.kind == "use":
        return f"🍺 {a.item.name if a.item else ''}"
    if a.kind == "attack":
        return f"⚔ {a.target}"
    if a.kind == "take":
        return f"💰 {a.target}"
    return {"wait": "· ждёт"}.get(a.kind, a.kind)


def run(seed=5, ticks=7):
    w, minds = build()
    rng = random.Random(seed)
    for t in range(1, ticks + 1):
        for st in minds.values():
            _decay_needs(st)
            _decay_emotion(st)
        order = list(minds.values())
        rng.shuffle(order)
        print(f"\n─── тик {t} " + "─" * 44)
        for st in order:
            b = w.bodies[st.config.id]
            if b.down():
                continue
            (a, g, u), _ = decide(st, w, perceive(st, w), temp=0.3, rng=rng)
            apply(a, st, w)
            print(f"  {st.config.name:7} ({st.config.role:12}) {label(a, g):22} [{g.kind if g else '—'}]")

    print("\n═══ сложившиеся симпатии (кто кого проникся) ═══")
    for nid, st in minds.items():
        warm = {k: round(v['affinity'], 2) for k, v in st.relationships.items() if v['affinity'] >= .35}
        if warm:
            print(f"  {nid:7} → {warm}")


if __name__ == "__main__":
    run(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 5,
        ticks=int(sys.argv[2]) if len(sys.argv) > 2 else 7)
