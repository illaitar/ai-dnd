"""Тест характеров: 15 архетипов × батарея зондов. Каждый зонд — стандартная сцена; смотрим, что
архетип ВЫБИРАЕТ через механическое ядро (детерминированно, argmax). Личность должна читаться из
поступков, а не из ярлыка. LLM не участвует — чистое ядро решений.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.mind import (  # noqa: E402
    TRAITS,
    Body,
    Goal,
    Item,
    NpcConfig,
    NpcState,
    decide,
    perceive,
)
from aidnd.mind.world import World  # noqa: E402

# (имя, роль, черты, power, appearance)
ARCHETYPES = [
    ("Крестьянин", "пахарь", {}, 1, .2),
    ("Стражник", "страж", {"lawful": .9, "loyalty": .85, "bravery": .8, "honesty": .8, "malice": .05}, 3, .3),
    ("Карманник", "вор", {"greed": .85, "honesty": .1, "lawful": .15, "bravery": .35}, 1, .2),
    ("Головорез", "громила", {"greed": .7, "bravery": .8, "pride": .8, "honesty": .25, "lawful": .3,
                              "malice": .35}, 4, .3),
    ("Убийца", "душегуб", {"malice": .9, "greed": .5, "bravery": .85, "honesty": .1, "lawful": .05,
                           "irritability": .2}, 3, .3),
    ("Трус", "бедолага", {"bravery": .1, "honesty": .5, "loyalty": .3}, 1, .2),
    ("Верный", "товарищ", {"loyalty": .95, "bravery": .7, "honesty": .8}, 2, .3),
    ("Купец", "торговец", {"greed": .85, "honesty": .55, "sociability": .6, "lawful": .6}, 1, .55),
    ("Гуляка", "пьянчуга", {"sociability": .8, "bravery": .3, "irritability": .5, "curiosity": .5}, 1, .3),
    ("Фанатик", "ревнитель", {"lawful": .95, "loyalty": .8, "pride": .7, "bravery": .7, "malice": .2}, 3, .3),
    ("Интриган", "делец", {"ambition": .9, "greed": .6, "honesty": .3, "lawful": .3, "sociability": .7,
                           "pride": .8}, 2, .4),
    ("Вспыльчивый", "буян", {"irritability": .95, "bravery": .85, "pride": .8, "malice": .4}, 3, .3),
    ("Добряк", "знахарка", {"honesty": .9, "loyalty": .7, "malice": .0, "sociability": .7, "greed": .2}, 1, .3),
    ("Отшельник", "нелюдим", {"sociability": .1, "curiosity": .6, "bravery": .5}, 1, .2),
    ("Наёмник", "клинок", {"bravery": .8, "greed": .65, "honesty": .5, "loyalty": .4, "lawful": .4}, 3, .35),
]


def _state(arch):
    name, role, traits, power, app = arch
    cfg = NpcConfig(id=name, name=name, role=role, traits={**dict.fromkeys(TRAITS, 0.5), **traits})
    st = NpcState.from_config(cfg)
    for n in st.needs:
        st.needs[n] = 0.15                       # спокойный фон, чтобы нужды не забивали зонд
    return st, power, app


def _spawn(st, world, place, power, app, **kw):
    world.add(Body(id=st.config.id, place=place, power=power, appearance=app, **kw))


def _res(st, world):
    (a, g, u), _ = decide(st, world, perceive(st, world))
    return f"{a.label()} ({g.kind if g else '—'})"


# ── зонды: каждый строит свежий мир и сцену вокруг архетипа ──
def p_idle(st, power, app):
    w = World()
    w.link("тут", "прочь")
    _spawn(st, w, "тут", power, app)
    return _res(st, w)


def p_prey_alone(st, power, app):
    w = World()
    w.link("тут", "прочь")
    _spawn(st, w, "тут", power, app)
    w.add(Body("богач", "тут", power=1, appearance=.85, attention=.8, loot=[Item("кошель", .6)]))
    return _res(st, w)


def p_prey_crowd(st, power, app):
    w = World()
    w.link("тут", "прочь")
    _spawn(st, w, "тут", power, app)
    w.add(Body("богач", "тут", power=1, appearance=.85, attention=.8, loot=[Item("кошель", .6)]))
    for n in ("зевакаА", "зевакаБ", "зевакаВ"):
        w.add(Body(n, "тут"))
    return _res(st, w)


def p_pickpocket(st, power, app):
    w = World()
    _spawn(st, w, "тут", power, app)
    w.add(Body("ротозей", "тут", power=1, appearance=.5, attention=.2, loot=[Item("монеты", .4)]))
    w.add(Body("прохожий", "тут"))
    return _res(st, w)


def p_threat(st, power, app):
    w = World()
    w.link("тут", "прочь")
    _spawn(st, w, "тут", power, app)
    w.add(Body("тролль", "тут", power=6, faction="monster"))
    return _res(st, w)


def p_ally(st, power, app):
    w = World()
    w.link("тут", "прочь")
    _spawn(st, w, "тут", power, app)
    st.relationships["друг"] = {"trust": .6, "affinity": .8, "fear": 0.0}
    w.add(Body("друг", "тут", hp=8, power=1))
    w.add(Body("бандит", "тут", power=2, faction="outlaw", attacking="друг"))
    return _res(st, w)


def p_hunger(st, power, app):
    w = World()
    _spawn(st, w, "тут", power, app)
    st.needs["hunger"] = 0.9
    st.needs_sources = {"hunger": {"source": "тут"}}
    w.ground["тут"] = [Item("похлёбка", .05, satisfies="hunger")]
    return _res(st, w)


def p_deal(st, power, app):
    w = World()
    _spawn(st, w, "тут", power, app)
    st.extra_goals = [Goal("trade", "купец", .6, {"concession": .3, "prob_concede": .7})]
    w.add(Body("купец", "тут", power=1))
    return _res(st, w)


PROBES = [
    ("досуг", p_idle), ("добыча-наедине", p_prey_alone), ("добыча-в-толпе", p_prey_crowd),
    ("ротозей", p_pickpocket), ("угроза-в-лицо", p_threat), ("союзник-в-беде", p_ally),
    ("голод+еда", p_hunger), ("сделка", p_deal),
]


def run(only=None):
    for arch in ARCHETYPES:
        name, role, traits, power, app = arch
        if only and name != only:
            continue
        flavor = " ".join(f"{k}{v:.2f}" for k, v in traits.items()) or "всё 0.50"
        print(f"\n=== {name} ({role}) | power {power} · {flavor}")
        for label, fn in PROBES:
            st, pw, ap = _state(arch)
            print(f"    {label:16} → {fn(st, pw, ap)}")


if __name__ == "__main__":
    run(only=(sys.argv[1] if len(sys.argv) > 1 else None))
