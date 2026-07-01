"""ЗАСЕЛЕНИЕ МОДЕЛЬНОЙ ЛОКАЦИИ NPC ИЗ ПУЛА: реальные люди банка (черты/обаяние/богатство из mech)
живут в зале таверны через mind (decide→apply), ИГРОК — такой же Body среди них. Смотрим:
кто с кем заговаривает, кто бирюком, кто щупает чужой кошель, что из этого СЛЫШИТ игрок
(= честный ambient-фид из реальных действий, не LLM-обои).

  .venv/bin/python scripts/pool_scene.py [seed] [ticks]
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.mind import Body, Item, NpcConfig, NpcState, decide, perceive, apply  # noqa: E402
from aidnd.mind.tick import _decay_emotion, _decay_needs  # noqa: E402
from aidnd.mind.world import World  # noqa: E402
from aidnd.worldgen import WorldStore  # noqa: E402

PLAYER = "pc"


def build(seed: int):
    """Зал таверны + улица; 9 человек из пула (по ролям — вечер в таверне) + игрок."""
    store = WorldStore()
    rng = random.Random(f"scene|{seed}")
    picks, seen_roles = [], []
    want = ["трактирщик", "бард", "горожанин", "горожанин", "горожанин", "лавочник",
            "бродяга", "головорез", "знахарка"]
    pool = store.list_people(limit=1000)
    rng.shuffle(pool)
    for role in want:
        row = next((p for p in pool if p["role"] == role and p["id"] not in seen_roles), None)
        if row:
            picks.append(row)
            seen_roles.append(row["id"])

    w = World()
    w.link("зал", "улица")
    # зал ПРЕДЛАГАЕТ закрытие нужд — потому туда и идут, потому там и сидят (вечер в таверне)
    w.ground["зал"] = [Item("похлёбка", 0.3, satisfies="hunger"),
                       Item("кружка эля", 0.25, satisfies="comfort"),
                       Item("место у очага", 0.2, satisfies="fatigue"),
                       Item("байки барда", 0.2, satisfies="novelty")]
    minds = {}
    for row in picks:
        mech = row["mech"]
        cfg = NpcConfig(id=row["id"], name=row["name"], role=row["role"],
                        traits=mech.get("traits") or {}, abilities=mech.get("abilities") or {})
        st = NpcState.from_config(cfg)
        r = random.Random(f"{seed}|{row['id']}")
        for n in st.needs:                                  # вечер: соц-нужда повыше, вечерняя усталость
            st.needs[n] = round(r.uniform(0.15, 0.4), 2)
        st.needs["social"] = round(r.uniform(0.35, 0.7), 2)
        loot = [Item("кошель", round(0.2 + row["appearance"] * 0.6, 2), kind="coin",
                     amount=round(3 + row["appearance"] * 30))] if row["appearance"] >= 0.3 else []
        w.add(Body(id=row["id"], place="зал", charisma=row["charisma"], appearance=row["appearance"],
                   attention=round(r.uniform(0.4, 0.85), 2), loot=loot))
        minds[row["id"]] = st

    # ИГРОК — такой же Body: скромно одет, при монете, внимателен
    w.add(Body(id=PLAYER, place="зал", charisma=0.45, appearance=0.35, attention=0.8,
               loot=[Item("кошель", 0.4, kind="coin", amount=12)]))
    w.npc_minds = minds
    return w, minds, {row["id"]: row for row in picks}


def feed_line(actor, a, g, rows) -> str | None:
    """Действие NPC → строка фида, КАК ЕЁ ВИДИТ игрок (незнакомцы обезличены дескриптором)."""
    def who(pid):
        if pid == PLAYER:
            return "тебя"
        row = rows.get(pid)
        if not row:
            return pid
        p = row["persona"]
        sex = "женщина" if p.get("sex") == "f" else "мужчина"
        look = (p.get("look") or {}).get("clothing", "")
        return f"{sex} ({look.split(',')[0]})" if look else sex

    name = who(actor)
    if a.kind == "say":
        verb = {"chat": "заводит разговор с", "flatter": "рассыпается в любезностях перед",
                "ask": "что-то выспрашивает у", "threat": "цедит угрозу в сторону"}.get(a.say, "говорит с")
        return f"{name} {verb} {who(a.target)}"
    if a.kind == "take":
        return f"{name} тянется к чужому добру ({who(a.target)})!"
    if a.kind == "attack":
        return f"{name} бросается на {who(a.target)}!"
    if a.kind == "move":
        return f"{name} уходит ({a.to})"
    if a.kind == "wait" and g and g.kind == "acquire":
        return f"{name} странно поглядывает на {who(g.target)}"
    return None                                             # тихие действия фид не засоряют


def run(seed: int = 3, ticks: int = 10) -> None:
    w, minds, rows = build(seed)
    rng = random.Random(seed)
    print("В зале:", ", ".join(f"{r['name']}({r['role']})" for r in rows.values()), "+ ИГРОК\n")
    for t in range(1, ticks + 1):
        for st in minds.values():
            _decay_needs(st)
            _decay_emotion(st)
        order = list(minds.values())
        rng.shuffle(order)
        heard = []
        for st in order:
            b = w.bodies[st.config.id]
            if b.down() or b.place != "зал":
                continue
            (a, g, _u), _ = decide(st, w, perceive(st, w), temp=0.3, rng=rng)
            apply(a, st, w)
            line = feed_line(st.config.id, a, g, rows)
            if line:
                heard.append(line)
        print(f"── тик {t} ──── что слышит/видит игрок ─────")
        for ln in (heard or ["тихо: стук кружек, гул очага"]):
            print(f"   · {ln}")

    print("\n═══ к игроку (отношение NPC после сцены) ═══")
    for nid, st in minds.items():
        rel = st.relationships.get(PLAYER)
        if rel and (abs(rel["affinity"]) > 0.05 or rel["fear"] > 0.05):
            print(f"  {rows[nid]['name']:20} aff={rel['affinity']:.2f} fear={rel['fear']:.2f}")
    print("\n═══ симпатии внутри зала ═══")
    for nid, st in minds.items():
        warm = {rows.get(k, {'name': k}).get('name', k): round(v['affinity'], 2)
                for k, v in st.relationships.items() if v['affinity'] >= .3 and k != PLAYER}
        if warm:
            print(f"  {rows[nid]['name']:20} → {warm}")


if __name__ == "__main__":
    run(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 3,
        ticks=int(sys.argv[2]) if len(sys.argv) > 2 else 10)
