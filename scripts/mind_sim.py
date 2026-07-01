"""Стенд многоагентной симуляции эмерджентного ядра: живой городок.

8 ОБЫЧНЫХ горожан (ремесло/дом/дневной распорядок) + 2 отклонения (вор, душегуб). Все ходят через
ОДНУ utility. Обычные люди ЖИВУТ (работают/едят/отдыхают/общаются — нужды закрываются ресурсами на
местах), хищники крадутся к поживе и бьют в уединении. Никакого «сценария»: что выйдет — то и выйдет.
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.mind import (  # noqa: E402
    TRAITS,
    Body,
    Item,
    NpcConfig,
    NpcState,
    apply,
    decide,
    perceive,
)
from aidnd.mind.tick import _decay_emotion, _decay_needs  # noqa: E402
from aidnd.mind.world import World  # noqa: E402

HUB = "площадь"
# места и их РЕСУРСЫ-удовлетворители (use → закрывает нужду)
RESOURCES = {
    "трактир": [("похлёбка", "hunger"), ("застолье", "social")],
    "рынок":   [("снедь", "hunger"), ("торг", "purpose")],
    "кузница": [("горн", "purpose")],
    "поле":    [("борозда", "purpose")],
    "дом":     [("очаг", "comfort"), ("лежанка", "fatigue")],
    HUB:       [("сходка", "social")],
}
# обычный распорядок: где закрывать какую нужду (кроме purpose — у каждого своё ремесло)
COMMON_SRC = {"hunger": "трактир", "fatigue": "дом", "comfort": "дом", "social": "трактир"}

# внешние роли (что видят ОСТАЛЬНЫЕ — натуру хищников выдают только черты в их собственном промпте)
ROLES = {"Мойра": "пекарь", "Бран": "кузнец", "Од": "фермер", "Нэлл": "трактирщица",
         "Гвен": "прачка", "Сэм": "работяга", "Тим": "мальчишка", "Лия": "торговка",
         "Рэн": "оборванец", "Мордо": "чужак"}
PLACE_DESC = {
    HUB: "Городская площадь — сердце городка, тут судачат и приглядывают за чужаками.",
    "трактир": "Трактир — тепло, пахнет похлёбкой, гомон и кружки.",
    "рынок": "Рыночные ряды — прилавки, снедь, толкотня и зазывалы.",
    "кузница": "Кузница — жар горна, звон молота, копоть.",
    "поле": "Поля за околицей — борозды, ветер, ни души окрест.",
    "дом": "Жилой дом — очаг, лавки и лежанки, укромно.",
}


def mk(world, minds, nid, traits, *, power=1, appearance=0.2, faction="town",
       loot=None, work=None, needs=None, rel=None, deviant=False):
    cfg = NpcConfig(id=nid, name=nid, traits={**dict.fromkeys(TRAITS, 0.5), **traits})
    st = NpcState.from_config(cfg)
    for k, v in (needs or {}).items():
        st.needs[k] = v
    st.relationships = rel or {}
    if not deviant:                       # обычный горожанин: полный распорядок дня
        src = {nd: {"source": pl} for nd, pl in COMMON_SRC.items()}
        if work:
            src["purpose"] = {"source": work}
        st.needs_sources = src
    world.add(Body(id=nid, place=HUB, power=power, appearance=appearance,
                   faction=faction, loot=list(loot or [])))
    minds[nid] = st
    return st


def build():
    w = World()
    for pl in RESOURCES:
        if pl != HUB:
            w.link(HUB, pl)
    for pl, res in RESOURCES.items():
        w.ground[pl] = [Item(n, 0.05, satisfies=s) for n, s in res]
    minds = {}

    # ── 8 обычных горожан ──
    mk(w, minds, "Мойра",  {"sociability": .6, "honesty": .7}, work="рынок",   needs={"hunger": .5})
    mk(w, minds, "Бран",   {"honesty": .6, "pride": .6}, power=2, work="кузница", needs={"purpose": .5})
    mk(w, minds, "Од",     {"honesty": .6}, work="поле",    needs={"fatigue": .5})
    mk(w, minds, "Нэлл",   {"sociability": .85, "honesty": .7}, work="трактир", needs={"social": .5})
    mk(w, minds, "Гвен",   {"sociability": .6}, work="трактир", needs={"hunger": .4, "comfort": .4})
    mk(w, minds, "Сэм",    {"bravery": .6}, power=2, work="кузница", needs={"fatigue": .7})
    mk(w, minds, "Тим",    {"curiosity": .85, "sociability": .7}, work="поле", needs={"social": .5})
    mk(w, minds, "Лия",    {"greed": .6, "sociability": .7, "honesty": .6}, appearance=.55,
       loot=[Item("выручка", .4)], work="рынок")            # честная торговка — но заметная (мишень)

    # ── 2 отклонения ──
    mk(w, minds, "Рэн", {"greed": .9, "honesty": .1, "lawful": .15, "bravery": .4},
       power=2, deviant=True, needs={"wealth": .6})          # вор
    mk(w, minds, "Мордо", {"malice": .85, "greed": .8, "honesty": .1, "lawful": .1, "bravery": .85,
                           "irritability": .3}, power=3, deviant=True)   # душегуб

    w.npc_minds = minds
    return w, minds


def run(seed=7, ticks=12):
    w, minds = build()
    rng = random.Random(seed)
    icon = {"attack": "⚔", "take": "💰", "give": "🎁", "say": "💬", "move": "→", "use": "✳", "wait": "·"}

    for t in range(1, ticks + 1):
        for st in minds.values():
            _decay_needs(st)
            _decay_emotion(st)
        order = list(minds.values())
        rng.shuffle(order)
        print(f"\n─── тик {t} " + "─" * 42)
        for st in order:
            body = w.bodies[st.config.id]
            if body.down():
                continue
            (a, g, u), _ = decide(st, w, perceive(st, w), temp=0.22, rng=rng)
            ev = apply(a, st, w)
            note = ""
            if ev.get("hit"):
                tb = w.bodies[ev["hit"]]
                note = f"  ⟹ {ev['hit']} hp={tb.hp}" + ("  ☠ УБИТ" if tb.down() else "")
            elif ev.get("took"):
                note = f"  ⟹ забрал «{ev['took']}»"
            elif ev.get("satisfied"):
                note = f"  ⟹ {ev['satisfied']}↓"
            dev = "†" if st.config.id in ("Рэн", "Мордо") else " "
            print(f" {dev}[{body.place:8}] {st.config.name:6} {icon.get(a.kind, '?')} {a.label():20}"
                  f" ({g.kind if g else 'idle'}){note}")

    print("\n═══ итог " + "═" * 42)
    for nid, st in minds.items():
        b = w.bodies[nid]
        status = "☠" if b.down() else f"hp={b.hp}"
        top = max(st.needs, key=st.needs.get)
        print(f"  {st.config.name:6} @{b.place:8} {status:6} нужда:{top}={st.needs[top]:.2f} "
              f"страх={st.emotion['fear']:.2f} добыча:{', '.join(i.name for i in b.loot) or '—'}")


if __name__ == "__main__":
    run(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 7,
        ticks=int(sys.argv[2]) if len(sys.argv) > 2 else 12)
