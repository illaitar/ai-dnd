"""D2 (демография, docs/citysim.md §D): ДОКОВАТЬ ИЖДИВЕНЦЕВ в пул (дети/старики) — офлайн, БЕЗ LLM.

Пул = 900 работоспособных взрослых (worlds.db:people). Здесь разбиваем их на семьи (по фамилии),
и к каждой добавляем 0-3 иждивенца — лёгкой ШАБЛОННОЙ персоной (без LLM/портретов): роль дитя/
старик, не работают, привязка к семье через mech.head + mech.dependent. Стабильная identity ⇒
restore мира их подхватит (settle селит иждивенца в дом его главы семьи).

Идемпотентно: если иждивенцы уже в пуле — выходит. Запуск: .venv/bin/python scripts/depgen.py
"""

from __future__ import annotations

import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from aidnd.play.population import _FEMALE, _MALE, _traits  # noqa: E402
from aidnd.worldgen import WorldStore  # noqa: E402
from aidnd.worldgen.abilities import roll_abilities  # noqa: E402

# «дитя» вдвое чаще старика — фронтир молод
_KINDS = ["дитя", "дитя", "старик"]
_CHILD_FACE = ["круглое, конопатое, любопытные глаза", "чумазое, щербатая улыбка",
               "востроносое, вихрастое", "пухлощёкое, сонное"]
_CHILD_CLOTH = ["холщовая рубаха до колен, босые ноги", "перешитый из отцовского зипунок",
                "латаное платьице, тесёмка в волосах", "мешковатая рубаха, деревянные башмаки"]
_ELDER_FACE = ["изрезанное морщинами, слезящиеся глаза", "иссохшее, беззубый рот",
               "пергаментная кожа, кустистые брови", "обвисшие щёки, мутный взгляд"]
_ELDER_CLOTH = ["ветхий тёплый кафтан, шаль на плечах", "заношенная роба, войлочные опорки",
                "латаный тулуп не по сезону", "серая хламида, посох у руки"]


def _dep_persona(role: str, sex: str, surname: str, rng: random.Random) -> dict:
    child = role == "дитя"
    return {
        "sex": sex, "age": "child" if child else "elder",
        "build": "мелкий" if child else "сгорбленный", "race": "человек",
        "look": {"face": rng.choice(_CHILD_FACE if child else _ELDER_FACE),
                 "hair": "вихор" if child else "седые космы",
                 "skin": "чистая, детская" if child else "морщинистая, в пятнах",
                 "clothing": rng.choice(_CHILD_CLOTH if child else _ELDER_CLOTH), "marks": []},
        "voice": "звонкий" if child else "надтреснутый",
        "speech": "простая, короткими фразами" if child else "неспешная, с присказками",
        "stance": "жмётся к взрослым" if child else "опирается на палку",
        "origin": f"родился(ась) в городке, семья {surname}" if child
        else f"старожил, доживает век при семье {surname}",
        "background": "малец на побегушках у родни" if child else "нянчил внуков, теперь при очаге",
        "wants": "играть да сладкого" if child else "покой и тепло очага",
        "fears": "темноты и чужих" if child else "хвори да одиночества",
        "quirk": "таскается хвостом за старшими" if child else "ворчит о былых временах",
        "secret": "", "ties": f"семья {surname}", "rumors": [],
        "portrait": "", "gear": [], "carry": [], "valuables": [],
    }


def _surname(name: str) -> str:
    parts = name.split()
    return " ".join(parts[1:]) if len(parts) > 1 else ""


def _families(rows: list, rng: random.Random) -> list:
    """Разбить взрослых на семьи (по фамилии, малые группы) — для назначения главы+иждивенцев."""
    by_sur: dict = {}
    for r in rows:
        by_sur.setdefault(_surname(r["name"]) or r["id"], []).append(r)
    fams = []
    for sur in sorted(by_sur):
        members = sorted(by_sur[sur], key=lambda r: r["id"])
        rng.shuffle(members)
        i = 0
        while i < len(members):
            size = rng.choices([1, 2, 3, 4, 5], weights=[2, 4, 4, 2, 1])[0]
            fams.append(members[i:i + size])
            i += size
    return fams


def main() -> None:
    store = WorldStore()
    rows = [r for r in store.list_people(limit=100000)
            if not (r.get("mech") or {}).get("dependent")]      # только взрослые как основа
    already = [pid for pid in store.person_ids() if pid.startswith("pool:")
               and (store.get_person(pid).get("mech") or {}).get("dependent")]
    if already:
        print(f"иждивенцы уже в пуле ({len(already)}) — идемпотентно выхожу")
        return
    rng = random.Random("dependents|v1")
    nxt = max(int(pid.split(":")[1]) for pid in store.person_ids()) + 1
    made = 0
    for fam in _families(rows, rng):
        head = fam[0]
        surname = _surname(head["name"])
        n_dep = rng.choices([0, 1, 2, 3], weights=[3, 4, 3, 2])[0]  # 0-3, в среднем ~1.2
        for _ in range(n_dep):
            role = rng.choice(_KINDS)
            sex = "m" if rng.random() < 0.5 else "f"
            given = rng.choice(_MALE if sex == "m" else _FEMALE)
            name = f"{given} {surname}".strip()
            pid = f"pool:{nxt:04d}"
            nxt += 1
            drng = random.Random(pid)
            mech = {"role": role, "traits": _traits(role, drng),
                    "abilities": roll_abilities(role, random.Random(f"abil|{pid}")),
                    "dependent": True, "head": head["id"]}
            persona = _dep_persona(role, sex, surname or "городка", drng)
            cha = round(0.15 + drng.uniform(0, 0.15), 2)   # тихие, невзрачные
            app = round(0.08 + drng.uniform(0, 0.12), 2)   # почти без своего добра
            store.save_person(pid, role, name, cha, app, mech, persona, {}, seed=1)
            made += 1
    print(f"добавлено иждивенцев: {made}. в банке теперь: {store.people_count()} "
          f"(взрослых {len(rows)} + иждивенцев {made})")


if __name__ == "__main__":
    main()
