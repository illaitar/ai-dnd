"""Городская популяция: именованные жители, что наполняют публичные места города.

Лёгкие заглушки (имя+раса+дом+привычки: где работают днём, где сидят вечером по привлекательности места).
Не ECS-сущности, пока игрок не заговорит — тогда заглушка МАТЕРИАЛИЗУЕТСЯ в полноценного NPC (персона,
характер, статы/навыки, профессия, семья-соседи по дому, знания мира) и дальше живёт как обычный NPC.

Масштабируется от города (число домов), как стража — от размера. Детерминировано по seed → пересоздаётся
на load; материализованные NPC — уже настоящие, персистятся обычным путём.
"""

from __future__ import annotations

# тяга места (по аффордансам): куда тянет вечером (досуг) и днём (работа). Место может и работать, и манить
# одновременно (таверна: днём — работники/обедающие, вечером — гуляки).
LEISURE = {"inn": 6, "drink": 6, "serve": 3, "shrine": 2, "shop": 1, "guild": 1, "board": 1}
WORKAFF = {"shop": 4, "work": 2, "serve": 3, "shrine": 2, "guild": 2, "townhall": 2, "farm": 2, "mine": 2,
           "inn": 3, "drink": 2}
# профессия по главной аффордансе места работы
PROF_BY_AFF = {"inn": "слуга", "serve": "слуга", "drink": "разносчик", "shop": "лавочник", "farm": "фермер",
               "mine": "рудокоп", "shrine": "служка", "guild": "писарь", "townhall": "чиновник",
               "work": "ремесленник"}
RACE_DIST = [("human", 0.62), ("halfling", 0.14), ("dwarf", 0.14), ("half-elf", 0.06), ("elf", 0.04)]
# аффорданса места → тип для ABM-симуляции (citysim.PROFILE)
_SIM_KIND = {"inn": "inn", "drink": "tavern", "serve": "tavern", "shop": "shop", "shrine": "shrine",
             "guild": "shop", "townhall": "shop", "farm": "shop", "work": "shop"}


def _place_kind(world, pid: str) -> str:
    p = world.spatial.places.get(pid)
    for a in (getattr(p, "affordances", []) or []):
        if a in _SIM_KIND:
            return _SIM_KIND[a]
    return "shop"


def _minute(world) -> int:
    h, m = world.clock.hhmm().split(":")
    return int(h) * 60 + int(m)


def _phase(minute: int) -> str:
    return "night" if (minute < 6 * 60 or minute >= 22 * 60) else \
        "day" if minute < 18 * 60 else "evening"


def crowd_at(world, place: str) -> int:
    """Сколько живых людей СЕЙЧАС в этом месте по честной ABM-симуляции (фон-жители + именные NPC)."""
    pop = getattr(world, "citypop", None)
    n = len(pop.present_at(place)) if pop else 0           # фон-заглушки по ABM (с учётом «в пути»/ночных сов)
    transits = getattr(world, "transits", None) or {}      # «в пути» не считаем тут
    n += sum(1 for npc in world.npcs()                     # материализованные/именные ECS-NPC, что тут
             if npc not in transits and (p := world.position(npc)) and p.place_id == place and world.is_alive(npc))
    return n


def density_label(n: int) -> str:
    return ("безлюдно" if n == 0 else "малолюдно" if n <= 3 else "оживлённо" if n <= 12
            else "людно" if n <= 22 else "не протолкнуться")


def event_pressure(n: int) -> float:
    """U-образный множитель шанса прервать игрока: и пусто (засада/грабёж в безлюдье), и битком
    (карманники/свалка/перебранки) повышают; около обычной людности — спокойнее."""
    if n <= 1:
        return 2.4
    if n <= 3:
        return 1.6
    if n <= 12:
        return 1.0
    if n <= 22:
        return 1.5
    return 2.2


def demand_factor(world, place: str) -> float:
    """Спрос от людности места → к цене (больше народу у лавки — дороже, в разумных пределах)."""
    return 1.0 + min(0.25, crowd_at(world, place) * 0.012)


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
        # публичные места города + тяга: работа И досуг считаются отдельно (место может быть и тем, и тем)
        pubs = self._public_places(world)

        def _affs(pid):
            p = world.spatial.places.get(pid)
            return set(getattr(p, "affordances", []) or []) if p else set()

        leisure_w = [(pid, max((LEISURE.get(a, 0) for a in _affs(pid)), default=0)) for pid in pubs]
        leisure_w = [(p, w) for p, w in leisure_w if w] or ([(pubs[0], 1)] if pubs else [])
        work_w = [(pid, max((WORKAFF.get(a, 0) for a in _affs(pid)), default=0)) for pid in pubs]
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
        self._build_sim(int(seed))                             # живой ABM-движок поверх заглушек + ростера

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

    # --- живой ABM-движок (непрерывная симуляция, не расписание) ------------- #
    def _build_sim(self, seed: int):
        """Stateful ABM поверх жителей: фон-заглушки + рядовой ECS-ростер ходят по НУЖДАМ (усталость/голод/
        общение) и времени суток, а не по жёстким блокам. Особые (стража/важные/спутники) — на своих системах.
        Время ABM = (tick·SIM_MINUTES_PER_TICK)%сутки → совпадает с игрой; детерминирован → пересоздаётся на load."""
        from .. import config
        from ..world.components import Profession
        from .citysim import CitySim
        w = self.world
        places = {pid: {"kind": _place_kind(w, pid), "xy": None} for pid in self._public_places(w)}
        agents = [{"id": aid, "home_xy": None, "home_place": None, "work": ag.get("work")}   # заглушки: дом за городом
                  for aid, ag in self.agents.items()]
        self.roster: set[str] = set()
        for npc in w.npcs():                                   # рядовой ростер: дом=резиденция, работа=workplace
            pr = w.ecs.get(npc, Profession)
            if not pr:
                continue
            agents.append({"id": npc, "home_xy": None, "work": pr.workplace_ref or None,
                           "home_place": pr.residence_ref or pr.workplace_ref or None})
            self.roster.add(npc)
        self.sim = CitySim(places, agents, seed=seed, mpt=config.SIM_MINUTES_PER_TICK)

    def tick(self):
        """Догнать ABM до текущего игрового тика (идемпотентно)."""
        if getattr(self, "sim", None):
            self.sim.advance(self.world.clock.tick)

    def target_of(self, npc: str) -> str | None:
        """Куда рядовой ростер-NPC хочет быть СЕЙЧАС по нуждам (для оркестратора вместо блока расписания)."""
        a = getattr(self, "sim", None) and self.sim.agents.get(npc)
        if not a:
            return None
        return a["transit"]["to"] if a["transit"] else a["place"]

    # --- присутствие во времени --------------------------------------------- #
    def place_of(self, aid: str, minute: int | None = None) -> str | None:
        self.tick()
        return self.sim.place_of(aid) if getattr(self, "sim", None) else None

    def present_at(self, place: str, minute: int | None = None) -> list[str]:
        """Фон-заглушки (ещё не материализованные), что СЕЙЧАС в этом месте по ABM (с учётом сов/в пути)."""
        self.tick()
        if not getattr(self, "sim", None):
            return []
        return [aid for aid in self.sim.present_at(place)
                if aid.startswith("pop:") and aid not in self.materialized]

    def name_of(self, aid: str) -> str:
        return self.agents.get(aid, {}).get("name", aid)

    def match(self, text: str, place: str, minute: int | None = None) -> str | None:
        """Найти присутствующую заглушку по упоминанию имени в тексте."""
        low = text.lower()
        for aid in self.present_at(place):
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
