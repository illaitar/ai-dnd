"""Досеять в банк зданий (worlds.db) КЛЮЧЕВОЕ здание «Магическая башня» — место, где маг обучает
глифам и стихиям (§М-4). Идемпотентно: повторный запуск не плодит дубликаты. btype содержит
«магическая», чтобы _assign_key_buildings поймал слот «Магическая башня» из _SIGNIFICANT.

    python scripts/tower_seed.py [путь-к-worlds.db]
"""

from __future__ import annotations

import sys

from aidnd.worldgen.store import WorldStore

TOWER = {
    "name": "Башня Пепельного Ключа",
    "atmosphere": "магическая башня · запах озона и жжёных трав, гул под сводами",
    "type": "магическая башня",
    "tier": "fine", "size": "tall", "floors": 4, "age": "old", "condition": "sound",
    "materials": {"walls": "тёсаный камень, руны по кладке", "roof": "медь, позеленевшая от лет"},
    "features": ["винтовая лестница", "стол с мелом для чертёжных кругов",
                 "полки с гримуарами и склянками", "астролябия у окна"],
    "smells": ["озон", "жжёные травы", "старая бумага"],
    "sounds": ["низкий гул", "потрескивание свечей", "скрип пера"],
    "lighting": "dim", "services": ["обучение глифам и стихиям", "толкование магии"],
    "wares": [], "hours": "с рассвета до глубокой ночи", "foot_traffic": "quiet",
    "occupants_kind": "маг-наставник", "prosperity": "steady", "reputation": "с опаской уважаемое",
    "notable": "на верхнем ярусе всегда горит одинокое окно",
    "secret": {"what": "запретный круг, вычерченный под полом", "where": "подвал башни",
               "gate": "сдвинуть плиту (проверка Внимательности Сл 15)"},
}


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "data/worlds.db"
    st = WorldStore(path)
    existing = [b for b in st.pool_buildings("key") if "магическ" in b["btype"].lower()]
    if existing:
        print(f"башня уже в пуле ({existing[0]['id']}) — пропускаю")
        return
    keys = st.pool_buildings("key")
    n = 1 + max((int(b["id"].split(":")[-1]) for b in keys if b["id"].split(":")[-1].isdigit()), default=-1)
    bid = f"bp:key:{n:04d}"
    st.pool_save_building(bid, "key", "магическая башня", TOWER)
    print(f"добавлена «Магическая башня» → {bid} (ключевых в пуле: {len(keys) + 1})")


if __name__ == "__main__":
    main()
