"""Долгосрочные цели (агенды) поверх реактивного ядра: планировщик (LLM/StubPlanner) ставит агенду,
её ТЕКУЩАЯ веха инжектится обычной механической целью, и ядро тянет её реактивно. Проверяем: мирная
цель (ухаживание) и тёмная (месть) РАВНО ведут NPC; острая нужда/угроза ПЕРЕБИВАЮТ агенду; вехи
продвигаются по факту. Всё детерминированно (без LLM) — это спека для калибровки планового слоя.
"""

from __future__ import annotations

from aidnd.mind import (
    TRAITS,
    Body,
    Item,
    NpcConfig,
    NpcState,
    advance_agendas,
    courtship_agenda,
    decide,
    perceive,
    predation_agenda,
    revenge_agenda,
)
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.mind.world import World


def _npc(nid, place, world, traits=None, needs=None, agendas=None, **body):
    cfg = NpcConfig(id=nid, name=nid, traits={**dict.fromkeys(TRAITS, 0.5), **(traits or {})})
    st = NpcState.from_config(cfg)
    for k, v in (needs or {}).items():
        st.needs[k] = v
    st.agendas = agendas or []
    world.add(Body(id=nid, place=place, **body))
    return st


def _choose(st, world):
    (a, g, u), ranked = decide(st, world, perceive(st, world))
    return a, g


# ── МИРНАЯ агенда: ухаживание ведёт NPC к избраннице и к жестам расположения ──
def test_courtship_agenda_drives_approach_and_affection():
    w = World()
    w.link("двор", "дом")
    # избранница в соседнем доме — NPC должен ПОДОЙТИ (позиционирование многотиковой цели)
    st = _npc("Юн", "двор", w, traits={"sociability": .6}, agendas=[courtship_agenda("Нэлл")])
    w.add(Body("Нэлл", "дом"))
    a, g = _choose(st, w)
    assert g.kind == "affiliate" and a.kind == "move" and a.to == "дом"

    # рядом — уже ухаживает (лесть/дар), а не просто стоит
    st.node = None
    w.bodies["Юн"].place = "дом"
    a, g = _choose(st, w)
    assert g.kind == "affiliate" and (a.say == "flatter" or a.kind == "give")


# ── ТЁМНАЯ агенда: месть ведёт ДАЖЕ НЕзлонравного (планировщик решил, гейт малодушия обойдён) ──
def test_revenge_agenda_makes_peaceful_npc_hunt_specific_foe():
    def stand(place_foe, extra=None):
        w = World()
        w.link("площадь", "закоулок")
        st = _npc("Мирон", "площадь", w, traits={"malice": .1, "honesty": .5, "bravery": .7},
                  power=3, agendas=[revenge_agenda("Гарет")])
        w.add(Body("Гарет", place_foe, power=1))
        for b in (extra or []):
            w.add(b)
        return st, w

    # враг рядом и ОДИН → бьёт (хотя NPC не злонравен — это ПЛАН, не натура)
    st, w = stand("площадь")
    a, g = _choose(st, w)
    assert g.kind == "harm" and a.kind == "attack" and a.target == "Гарет"

    # враг в толпе → НЕ бьёт (свидетели), выжидает/крадётся
    st, w = stand("площадь", extra=[Body("зевака1", "площадь"), Body("зевака2", "площадь"),
                                    Body("зевака3", "площадь")])
    a, g = _choose(st, w)
    assert not (a.kind == "attack")

    # посторонний НИКОГДА не становится жертвой (агенда адресна, злонравия нет)
    st, w = stand("закоулок", extra=[Body("прохожий", "площадь", appearance=.2)])
    a, g = _choose(st, w)
    assert not (a.kind == "attack" and a.target == "прохожий")
    assert g.kind == "harm" and a.kind == "move" and a.to == "закоулок"   # крадётся к врагу


# ── арбитраж: острая угроза ПЕРЕБИВАЕТ долгосрочную месть (реактивный слой выигрывает) ──
def test_acute_threat_preempts_agenda():
    w = World()
    w.link("площадь", "проулок")
    st = _npc("Мирон", "площадь", w, traits={"malice": .1, "bravery": .2}, power=1,
              agendas=[revenge_agenda("Гарет")])
    w.add(Body("Гарет", "проулок", power=1))          # цель мести — в стороне
    w.add(Body("тролль", "площадь", power=6, faction="monster"))   # смертельная угроза В ЛИЦО
    a, g = _choose(st, w)
    assert g.kind == "safe" and a.kind == "move"       # спасается, а не мстит


# ── вехи продвигаются ПО ФАКТУ; исчерпанная агенда завершается ──
def test_milestone_advances_and_completes():
    w = World()
    st = _npc("Тать", "рынок", w, traits={"greed": .8}, agendas=[predation_agenda("купец")])
    ag = st.agendas[0]
    assert ag.status == "active" and ag.current().kind == "acquire"
    advance_agendas(st, w)
    assert ag.status == "active"                        # условие «есть кошель» ещё не выполнено
    w.bodies["Тать"].loot.append(Item("кошель", .6))    # добыл
    advance_agendas(st, w)
    assert ag.status == "done"                          # веха закрыта → агенда исполнена


# ── две агенды разом (мирная + тёмная): обе — кандидаты, арбитраж решает по обстановке ──
def test_multiple_agendas_coexist():
    w = World()
    st = _npc("Двоедум", "дом", w, traits={"sociability": .6, "bravery": .7}, power=3,
              agendas=[courtship_agenda("Мила"), revenge_agenda("Ррог")])
    w.add(Body("Мила", "дом"))
    w.add(Body("Ррог", "дом", power=1))                # и любовь, и враг в одной комнате, врагов нет свидетелей
    a, g = _choose(st, w)
    assert g.kind in ("harm", "affiliate")             # обе агенды живут; арбитраж выбрал сильнейшую
