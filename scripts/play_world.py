"""Проба гринфилда: карта (citygraph) + население (play.populate) с мозгами (mind). Ни строчки
Фэндалина/старого движка. Печатает ростер и гоняет мозг на паре жителей.

  .venv/bin/python scripts/play_world.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.citygraph import CityParams, generate  # noqa: E402
from aidnd.mind import Body, World, perceive, think  # noqa: E402
from aidnd.play import populate  # noqa: E402


def run(seed=1):
    city = generate(CityParams(seed=seed, key_buildings=8, river=True, walls=True))
    people = populate(city, seed=seed, commoners=12, deviants=2)
    print(f"КАРТА: {city.stats()['nodes']} узлов, {len(city.houses)} домов, "
          f"{len(city.key_buildings)} ключевых зданий.")
    print(f"НАСЕЛЕНИЕ: {len(people)} жителей (у каждого мозг mind.NpcState).\n")

    for p in people.values():
        t = p.state.config.traits
        hot = ", ".join(f"{k} {t[k]:.2f}" for k in ("greed", "honesty", "bravery", "sociability", "malice")
                        if abs(t[k] - 0.5) > 0.15) or "уравновешен"
        work = p.work or "—"
        print(f"  {p.name:20} {p.role:11} дом@{p.home:<4} работа:{work:7} "
              f"обаян {p.charisma:.2f} богат {p.appearance:.2f}  · {hot}")

    # мозг работает на этих жителях: поставим двоих в одну комнату и посмотрим реакцию
    print("\nПРОВЕРКА МОЗГА — трактирщик и бродяга в одной комнате:")
    keeper = next(p for p in people.values() if p.role == "трактирщик")
    rogue = next(p for p in people.values() if p.role in ("бродяга", "головорез"))
    for actor, other in ((keeper, rogue), (rogue, keeper)):
        w = World()
        w.link("зал", "улица")
        w.add(Body(id=actor.id, place="зал", charisma=actor.charisma, appearance=actor.appearance))
        w.add(Body(id=other.id, place="зал", charisma=other.charisma, appearance=other.appearance))
        actor.state.needs["social"] = 0.5
        r = think(actor.state, w, perceive(actor.state, w))
        print(f"  {actor.name} ({actor.role}) ⇒ {r['chosen']['action']} ({r['chosen']['goal']})")


if __name__ == "__main__":
    run(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
