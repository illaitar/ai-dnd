"""4 обычные фэнтези-ситуации через граф-мозг (MODULARBRAIN). Для каждой — контраст по модулятору:
одно и то же тело, сдвинули состояние → путь по графу свернул на другое действие. Всё эмерджентно,
без правил на ситуацию. Показываем модуляторы + выбор + ключевой шаг трассы.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.mind import TRAITS, Body, Goal, Item, NpcConfig, NpcState, think  # noqa: E402
from aidnd.mind.world import World  # noqa: E402


def npc(traits, needs=None, emotion=None, power=1):
    cfg = NpcConfig(id="я", traits={**dict.fromkeys(TRAITS, 0.5), **traits})
    st = NpcState.from_config(cfg)
    for k, v in (needs or {}).items():
        st.needs[k] = v
    for k, v in (emotion or {}).items():
        st.emotion[k] = v
    return st, power


def scene(st, power, here=None, exits=None, items=None, extra=None, rel=None):
    w = World()
    for e in (exits or []):
        w.link("тут", e)
    w.add(Body("я", "тут", power=power))
    for e in (here or []):
        w.add(Body(e["id"], "тут", power=e.get("power", 1), appearance=e.get("appearance", .2),
                   attention=e.get("attention", .7), faction=e.get("faction", "town"),
                   attacking=e.get("attacking"), loot=[Item(x, .5) for x in e.get("loot", [])]))
    w.ground["тут"] = [Item(n, .05, satisfies=s) for n, s in (items or [])]
    st.relationships = rel or {}
    st.extra_goals = extra or []
    return w


def show(tag, st, w):
    r = think(st, w)
    m = r["modulators"]
    ms = " ".join(f"{k[:4]}={m[k]}" for k in ("arousal", "valence", "dominance", "resolution"))
    print(f"   {tag:22} [{ms}]  ⇒ {r['chosen']['action']}  ({r['chosen']['goal']})")


print("═" * 78)
print("1. ГОЛОДНЫЙ ТОРГ — наёмник торгуется за вяленое мясо у каравана")
print("   (жадный, но терпеливый: сытый держит цену; голодный уступает — arousal↑, resolution↓)")
tr = {"greed": .8, "irritability": .25, "bravery": .8}
g = lambda: [Goal("trade", "торговец", .6, {"concession": .3, "prob_concede": .7})]  # noqa: E731
st, p = npc(tr, needs={"hunger": .15}); show("сыт (hunger .15)", st, scene(st, p, here=[{"id": "торговец"}], extra=g()))
st, p = npc(tr, needs={"hunger": .95}); show("голоден (hunger .95)", st, scene(st, p, here=[{"id": "торговец"}], extra=g()))

print("\n2. ХИЩНИК ТЕРЯЕТ ТЕРПЕНИЕ — вор у ротозея с кошелём, но рядом один свидетель")
print("   (спокойный ЖДЁТ, пока свидетель уйдёт; на взводе — хватает при нём: arousal рушит выжидание)")
tr = {"greed": .9, "honesty": .1, "lawful": .1, "bravery": .7}
here = [{"id": "ротозей", "appearance": .5, "attention": .2, "loot": ["монеты"]}, {"id": "свидетель"}]
st, p = npc(tr, needs={"wealth": .2}, power=2); show("хладнокровен", st, scene(st, p, here=here, exits=["прочь"]))
st, p = npc(tr, needs={"wealth": .95}, emotion={"anger": .5}, power=2); show("на взводе (жажда+гнев)", st, scene(st, p, here=here, exits=["прочь"]))

print("\n3. ТРОЛЛЬ И ДРУГ — верный товарищ, друга прижал тролль; храбрость vs ужас")
print("   (спокойный кидается защищать; охваченный ужасом бросает друга — fear→dominance↓→бегство)")
tr = {"loyalty": .9, "bravery": .7}
here = [{"id": "друг", "power": 1}, {"id": "тролль", "power": 3, "faction": "monster", "attacking": "друг"}]
rel = {"друг": {"trust": .5, "affinity": .8, "fear": 0.0}}
st, p = npc(tr, power=3); show("собран (fear 0)", st, scene(st, p, here=here, exits=["прочь"], rel=rel))
st, p = npc(tr, emotion={"fear": .85}, power=3); show("в ужасе (fear .85)", st, scene(st, p, here=here, exits=["прочь"], rel=rel))

print("\n4. НАДЕЖДА vs ОТЧАЯНИЕ — грабитель наедине с настороженным равным по силе (риск реален)")
print("   (на кураже давит/бьёт; в унынии не рискует и мнётся: valence→осторожность на рисковом акте)")
tr = {"greed": .85, "honesty": .1, "lawful": .15, "bravery": .55}
here = [{"id": "странник", "appearance": .6, "attention": .85, "power": 2, "loot": ["кошель"]}]  # начеку, равен → риск
st, p = npc(tr, emotion={"joy": .55}, power=2); show("на кураже (joy)", st, scene(st, p, here=here, exits=["прочь"]))
st, p = npc(tr, emotion={"distress": .8}, power=2); show("в унынии (distress)", st, scene(st, p, here=here, exits=["прочь"]))
print("═" * 78)
