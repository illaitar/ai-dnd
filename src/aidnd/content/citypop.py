"""Городская популяция: именованные жители, что наполняют публичные места города.

Лёгкие заглушки (имя+раса+дом+привычки: где работают днём, где сидят вечером по привлекательности места).
Не ECS-сущности, пока игрок не заговорит — тогда заглушка МАТЕРИАЛИЗУЕТСЯ в полноценного NPC (персона,
характер, статы/навыки, профессия, семья-соседи по дому, знания мира) и дальше живёт как обычный NPC.

Масштабируется от города (число домов), как стража — от размера. Детерминировано по seed → пересоздаётся
на load; материализованные NPC — уже настоящие, персистятся обычным путём.
"""

from __future__ import annotations

# тяга места (по аффордансам): куда тянет вечером (досуг) и днём (работа)
LEISURE = {"inn": 6, "drink": 6, "serve": 3, "shrine": 2, "shop": 1, "guild": 1, "board": 1}
WORKAFF = {"shop": 4, "work": 2, "serve": 3, "shrine": 2, "guild": 2, "townhall": 2, "farm": 2, "mine": 2}
# профессия по главной аффордансе места работы
PROF_BY_AFF = {"inn": "слуга", "serve": "слуга", "drink": "разносчик", "shop": "лавочник", "farm": "фермер",
               "mine": "рудокоп", "shrine": "служка", "guild": "писарь", "townhall": "чиновник",
               "work": "ремесленник"}
RACE_DIST = [("human", 0.62), ("halfling", 0.14), ("dwarf", 0.14), ("half-elf", 0.06), ("elf", 0.04)]


def _minute(world) -> int:
    h, m = world.clock.hhmm().split(":")
    return int(h) * 60 + int(m)


def _phase(minute: int) -> str:
    return "night" if (minute < 6 * 60 or minute >= 22 * 60) else \
        "day" if minute < 18 * 60 else "evening"


def _pick(rng, weighted):
    total = sum(w for _, w in weighted) or 1
    r = rng.random() * total
    for item, w in weighted:
        r -= w
        if r <= 0:
            return item
    return weighted[-1][0]


class CityPopulation:
    def __init__(self, world, seed: int):
        import random

        from ..gen.names import make_name
        from ..gen.seeds import subseed
        self.world = world
        self.materialized: dict[str, str] = {}                 # stub_id → npc_id (после знакомства)
        rng = random.Random(subseed(int(seed), "citypop_world"))
        # публичные места города (по аффордансам) + их тяга
        pubs = self._public_places(world)
        leisure_w = [(pid, LEISURE.get(self._aff(world, pid), 0)) for pid in pubs]
        leisure_w = [(p, w) for p, w in leisure_w if w] or [(pubs[0], 1)] if pubs else []
        work_w = [(pid, WORKAFF.get(self._aff(world, pid), 0)) for pid in pubs]
        work_w = [(p, w) for p, w in work_w if w]
        # сколько жителей (масштаб от домов), детерминированно
        houses = (getattr(world, "city_profile", None) or {}).get("houses", 60)
        n = max(20, min(280, houses // 8))
        reg: set[str] = set()
        self.agents: dict[str, dict] = {}
        for i in range(n):
            race = _pick(rng, RACE_DIST)
            gender = "female" if rng.random() < 0.5 else "male"
            given, sur = make_name(race, gender, reg, rng)
            works = rng.random() < 0.78 and work_w
            goes_out = rng.random() < 0.5 and leisure_w
            self.agents[f"pop:{i}"] = {
                "id": f"pop:{i}", "name": f"{given} {sur}", "race": race, "gender": gender,
                "work": _pick(rng, work_w) if works else None,
                "evening": _pick(rng, leisure_w) if goes_out else None,
                "household": [],                               # соседи по дому (имена) — для «семьи»
            }
        self._seed_households(rng)

    # --- геометрия/типы ----------------------------------------------------- #
    @staticmethod
    def _aff(world, pid: str) -> str:
        p = world.spatial.places.get(pid)
        affs = list(getattr(p, "affordances", []) or []) if p else []
        for a in affs:                                         # первая значимая аффорданса
            if a in LEISURE or a in WORKAFF:
                return a
        return affs[0] if affs else ""

    @staticmethod
    def _public_places(world) -> list[str]:
        out = []
        for pid, p in world.spatial.places.items():
            if getattr(p, "kind", "") != "building" or getattr(p, "parent", "") != "settlement:phandalin":
                continue
            affs = set(getattr(p, "affordances", []) or [])
            if affs & {"inn", "drink", "serve", "shop", "shrine", "guild", "townhall", "farm"} \
               and not (affs & {"hideout", "manor"}):
                out.append(pid)
        return sorted(out)

    def _seed_households(self, rng):
        ids = list(self.agents)
        rng.shuffle(ids)
        i = 0
        while i < len(ids):
            size = rng.randint(1, 4)
            fam = ids[i:i + size]
            names = [self.agents[a]["name"] for a in fam]
            for a in fam:                                      # соседи по дому = «семья»
                self.agents[a]["household"] = [self.agents[x]["name"] for x in fam if x != a]
            sur = self.agents[fam[0]]["name"].split()[-1]      # общая фамилия в семье
            for a in fam[1:]:
                given = self.agents[a]["name"].split()[0]
                self.agents[a]["name"] = f"{given} {sur}"
            _ = names
            i += size

    # --- присутствие во времени --------------------------------------------- #
    def place_of(self, aid: str, minute: int) -> str | None:
        ag = self.agents.get(aid)
        if not ag:
            return None
        ph = _phase(minute)
        if ph == "day":
            return ag["work"]
        if ph == "evening":
            return ag["evening"]
        return None                                            # ночью по домам (не на игровых местах)

    def present_at(self, place: str, minute: int) -> list[str]:
        """Заглушки жителей (ещё не материализованные), что сейчас в этом месте."""
        return [aid for aid, ag in self.agents.items()
                if aid not in self.materialized and self.place_of(aid, minute) == place]

    def name_of(self, aid: str) -> str:
        return self.agents.get(aid, {}).get("name", aid)

    def match(self, text: str, place: str, minute: int) -> str | None:
        """Найти присутствующую заглушку по упоминанию имени в тексте."""
        low = text.lower()
        for aid in self.present_at(place, minute):
            nm = self.agents[aid]["name"].lower()
            if nm in low or nm.split()[0] in low:
                return aid
        return None

    # --- материализация в полноценного NPC ---------------------------------- #
    def materialize(self, aid: str, place: str, model=None) -> str | None:
        """Заглушка → настоящий NPC: персона, статы/навыки, профессия, семья, знания. Возвращает npc_id."""
        if aid in self.materialized:
            return self.materialized[aid]
        ag = self.agents.get(aid)
        if not ag:
            return None
        from ..gen.names import make_name  # noqa: F401  (реестр уже учтён при генерации)
        from .phandalin import _add_npc
        npc_id = f"npc:{aid.replace(':', '_')}"
        work = ag.get("work")
        prof = PROF_BY_AFF.get(self._aff(self.world, work), "горожанин") if work else "горожанин"
        fam = ag.get("household") or []
        know = []
        if fam:
            know.append({"fact": f"Живёт одним двором с: {', '.join(fam)}.", "topic": "personal",
                         "tags": ["семья", "дом"], "disclosure_gate": {"trust": 0.25}})
        _add_npc(self.world, npc_id, ag["name"], "townsfolk", "srd:commoner", race=ag["race"],
                 profession=prof, works_at=work, place=place, knowledge=know or None)
        self.materialized[aid] = npc_id
        return npc_id
