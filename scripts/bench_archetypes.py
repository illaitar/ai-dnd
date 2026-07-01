"""Бенчмарк архетипов: 1000 РАНДОМИЗИРОВАННЫХ ситуаций в разных помещениях, поделённых по архетипам.
Каждый сэмпл: свежая сцена (комната, свидетели, сила/богатство цели, нужды, сила нападающего — всё
случайно) → механическое ядро выбирает ход → сверяем с ОРАКУЛОМ НАМЕРЕНИЯ (что этот характер ДОЛЖЕН
сделать, по простым человекочитаемым правилам от черт, а НЕ по формулам ядра). Пасс-рейт = насколько
архетип держит характер поперёк разброса. Итог — таблица архетип×ситуация.
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aidnd.mind import Body, Goal, Item, decide, perceive  # noqa: E402
from aidnd.mind.world import World  # noqa: E402
from archetypes import ARCHETYPES, _spawn, _state  # noqa: E402

ROOMS = ["двор", "площадь", "проулок", "трактир", "амбар", "кузница", "мост", "погреб", "рынок", "часовня"]
N = 1000


def _pred(tr) -> bool:
    """Намерение хищничать (человекочитаемо, независимо от формул ядра)."""
    return tr.get("malice", 0) >= 0.6 or (
        tr.get("greed", 0) >= 0.6 and tr.get("honesty", 1) <= 0.35 and tr.get("lawful", 1) <= 0.45)


def _hits(a, who) -> bool:
    return a.target == who and (a.kind in ("attack", "take") or (a.kind == "say" and a.say == "threat"))


# ── ситуации: (генератор сцены, оракул намерения) ──
def s_prey_alone(rng, arch):
    st, pw, ap = _state(arch)
    w = World()
    here, out = rng.choice(ROOMS), "прочь"
    w.link(here, out)
    _spawn(st, w, here, pw, ap)
    w.add(Body("мишень", here, power=1, appearance=rng.uniform(.6, .95),
               attention=rng.uniform(.55, .9), loot=[Item("кошель", rng.uniform(.4, .8))]))
    return st, w, {}


def o_prey_alone(tr, pw, meta, a, g):
    return _hits(a, "мишень") == _pred(tr)                 # хищник бьёт наедине; мирный — нет


def s_prey_crowd(rng, arch):
    st, pw, ap = _state(arch)
    w = World()
    here = rng.choice(ROOMS)
    w.link(here, "прочь")
    _spawn(st, w, here, pw, ap)
    w.add(Body("мишень", here, power=1, appearance=rng.uniform(.7, .95),
               attention=.8, loot=[Item("кошель", .6)]))
    for i in range(rng.randint(2, 4)):
        w.add(Body(f"зевака{i}", here))
    return st, w, {}


def o_prey_crowd(tr, pw, meta, a, g):
    return not (a.target == "мишень" and a.kind in ("attack", "take"))   # никто не бьёт в открытую при толпе


def s_ally(rng, arch):
    st, pw, ap = _state(arch)
    w = World()
    here = rng.choice(ROOMS)
    w.link(here, "прочь")
    _spawn(st, w, here, pw, ap)
    st.relationships["друг"] = {"trust": .6, "affinity": .8, "fear": 0.0}
    ap_pow = rng.randint(1, 3)
    w.add(Body("друг", here, hp=8, power=1))
    w.add(Body("бандит", here, power=ap_pow, faction="outlaw", attacking="друг"))
    return st, w, {"atk": ap_pow}


def o_ally(tr, pw, meta, a, g):
    attacked = a.kind == "attack" and a.target == "бандит"
    if tr.get("malice", 0) >= 0.6:
        return attacked                                    # злодей бьёт бандита в любом случае (когда может)
    lo, br, atk = tr.get("loyalty", .5), tr.get("bravery", .5), meta["atk"]
    # заступается, если верен, храбр И способен одолеть (сильнее; при равенстве — храбрый/очень верный)
    defends = lo >= 0.4 and br >= 0.5 and (pw > atk or (pw >= atk and (br >= 0.75 or lo >= 0.8)))
    return attacked == defends


def s_threat(rng, arch):
    st, pw, ap = _state(arch)
    w = World()
    here = rng.choice(ROOMS)
    w.link(here, "прочь")
    _spawn(st, w, here, pw, ap)
    w.add(Body("тварь", here, power=rng.randint(5, 7), faction="monster"))
    return st, w, {}


def o_threat(tr, pw, meta, a, g):
    return g == "safe"                                     # смертельная угроза в лицо → реагирует (бежит/бьётся)


def s_hunger(rng, arch):
    st, pw, ap = _state(arch)
    w = World()
    here = rng.choice(ROOMS)
    _spawn(st, w, here, pw, ap)
    st.needs["hunger"] = rng.uniform(.8, 1.0)
    st.needs_sources = {"hunger": {"source": here}}
    w.ground[here] = [Item("похлёбка", .05, satisfies="hunger")]
    return st, w, {}


def o_hunger(tr, pw, meta, a, g):
    return a.kind == "use"                                 # голоден и еда рядом → ест


def s_deal(rng, arch):
    st, pw, ap = _state(arch)
    w = World()
    here = rng.choice(ROOMS)
    _spawn(st, w, here, pw, ap)
    st.extra_goals = [Goal("trade", "купец", rng.uniform(.5, .7),
                           {"concession": rng.uniform(.2, .4), "prob_concede": rng.uniform(.5, .8)})]
    w.add(Body("купец", here, power=1))
    return st, w, {}


def o_deal(tr, pw, meta, a, g):
    if tr.get("malice", 0) >= 0.6:
        return a.kind == "attack" and a.target == "купец"   # душегуб наедине режет, а не торгует
    # жадный ТОРГУЕТСЯ (держит цену ИЛИ берёт уже выгодное); нежадный не тратит время — соглашается
    if tr.get("greed", .5) >= 0.75 and tr.get("irritability", .5) <= 0.65:
        return a.kind == "say" and a.say in ("counter", "accept")
    return a.kind == "say" and a.say == "accept"


SITS = [("добыча-наедине", s_prey_alone, o_prey_alone), ("добыча-в-толпе", s_prey_crowd, o_prey_crowd),
        ("союзник-в-беде", s_ally, o_ally), ("угроза", s_threat, o_threat),
        ("голод+еда", s_hunger, o_hunger), ("сделка", s_deal, o_deal)]


def run():
    res = {a[0]: {s[0]: [0, 0] for s in SITS} for a in ARCHETYPES}
    for i in range(N):
        arch = ARCHETYPES[i % len(ARCHETYPES)]
        sname, gen, oracle = SITS[(i // len(ARCHETYPES)) % len(SITS)]
        rng = random.Random(1000 + i)
        st, w, meta = gen(rng, arch)
        (a, g, u), _ = decide(st, w, perceive(st, w))
        ok = oracle(arch[2], arch[3], meta, a, (g.kind if g else "—"))
        cell = res[arch[0]][sname]
        cell[1] += 1
        cell[0] += 1 if ok else 0

    scol = [s[0] for s in SITS]
    head = f"{'архетип':12} " + " ".join(f"{s[:8]:>8}" for s in scol) + f" {'ИТОГ':>6}"
    print(head)
    print("─" * len(head))
    tot_p = tot_n = 0
    col_p = {s: 0 for s in scol}
    col_n = {s: 0 for s in scol}
    for name, _r, _t, _p, _a in ((a[0], None, None, None, None) for a in ARCHETYPES):
        row = res[name]
        ap = an = 0
        cells = []
        for s in scol:
            p, n = row[s]
            ap += p
            an += n
            col_p[s] += p
            col_n[s] += n
            cells.append(f"{(100 * p / n if n else 0):7.0f}%")
        tot_p += ap
        tot_n += an
        print(f"{name:12} " + " ".join(cells) + f" {(100 * ap / an if an else 0):5.0f}%")
    print("─" * len(head))
    foot = [f"{(100 * col_p[s] / col_n[s] if col_n[s] else 0):7.0f}%" for s in scol]
    print(f"{'по ситуации':12} " + " ".join(foot) + f" {(100 * tot_p / tot_n):5.0f}%")
    print(f"\nВСЕГО: {tot_p}/{tot_n} = {100 * tot_p / tot_n:.1f}% совпадений с намерением архетипа.")


if __name__ == "__main__":
    run()
