"""Доразрешение пула сущностей сцены: «а есть ли тут кто-то/что-то?» (док 06 + main §2).

Мастер оценивает вероятность ПО КОНТЕКСТУ (тип локации, время, погода, флаги мира,
уже зафиксированные сущности), кидает СИДИРОВАННО и ФИКСИРУЕТ результат навсегда:
повторный вопрос по тому же ключу даёт тот же ответ (eager persistence). Если
выпало «никого/ничего нет» — это записывается, и спросить 1000 раз ничего не
изменит. При «есть» — сущность лениво материализуется и тоже персистится.

Существование решает правдоподобие; нашёл ли игрок — отдельный бросок (док 06 §5,
док 07), он остаётся за вызывающим кодом.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .. import ids
from .seeds import subseed

# базовая P(вокруг есть ещё кто-то) по типу локации
PRESENCE = {
    "frontier_town": 0.5, "settlement": 0.5, "market": 0.55, "manor": 0.25,
    "shrine": 0.2, "dungeon": 0.02, "site": 0.04, "wilderness": 0.08, "wilds": 0.08,
}
WATCH_BASE = 0.3                # P(наблюдает | присутствует)

# базовая P(существует скрытый <вид>) по типу локации
HIDDEN = {
    "dungeon": {"stash": 0.6, "trap": 0.4, "item": 0.5},
    "site": {"stash": 0.5, "trap": 0.3, "item": 0.4},
    "manor": {"stash": 0.4, "trap": 0.3, "item": 0.35},
    "frontier_town": {"stash": 0.1, "item": 0.12, "trap": 0.05},
    "market": {"stash": 0.1, "item": 0.12, "trap": 0.05},
    "shrine": {"stash": 0.15, "item": 0.15},
    "wilderness": {"stash": 0.2, "item": 0.2},
}


@dataclass
class Resolution:
    key: str
    present: bool = False
    watching: bool = False
    npc: str | None = None
    exists: bool = False
    container: str | None = None
    p: float = 0.0
    recorded: bool = False      # вернулось из персистентного факта (не свежий бросок)


class DiscoveryService:
    def __init__(self, world, dice=None, char_gen=None) -> None:
        self.world = world
        self.dice = dice
        self.char_gen = char_gen

    # ----------------------------------------------- контекст сцены --------
    def location_type(self, place_id: str) -> str:
        sp = self.world.spatial
        p = sp.places.get(place_id)
        if not p:
            return "wilderness"
        # подземелье/логово — по предку-site либо аффордансу боя
        node = p
        seen = 0
        while node and seen < 8:
            if node.kind == "site" or "combat" in (node.affordances or []) or "hideout" in (node.affordances or []):
                return "dungeon"
            if node.kind == "settlement":
                break
            node = sp.places.get(node.parent) if node.parent else None
            seen += 1
        # поселение → город; иначе по аффордансам/виду
        affs = set(p.affordances or [])
        if affs & {"inn", "shop", "townhall"} or (p.district == "market"):
            return "market"
        if "shrine" in affs:
            return "shrine"
        if "manor" in affs:
            return "manor"
        if p.kind in ("building", "room"):
            return "frontier_town"
        return "wilderness"

    def _ctx_mods(self, place_id: str) -> tuple[float, float]:
        """Множители присутствия и наблюдения от времени/погоды/флагов."""
        from ..world import environment
        sc = environment.scene_context(self.world, place_id)
        presence_mod, watch_mod = 1.0, 1.0
        if sc.time_of_day == "night":
            presence_mod *= 0.4
        elif sc.time_of_day == "evening":
            presence_mod *= 0.8
        if sc.weather in ("storm", "rain", "snow"):
            presence_mod *= 0.6
        # флаги мира: после зачистки Красных плащей соглядатаев меньше
        if "post_redbrand_purge" in self.world.flags:
            watch_mod *= 0.5
        # активная враждебная фракция в регионе → выше шанс слежки
        if any("redbrands" in f or "watched" in f for f in self.world.flags):
            watch_mod *= 2.0
        return presence_mod, watch_mod

    def _fixed_others_here(self, place_id: str, exclude: str) -> list[str]:
        out = []
        for npc in self.world.npcs():
            pos = self.world.position(npc)
            if pos and pos.place_id == place_id and npc != exclude and self.world.is_alive(npc):
                out.append(npc)
        return out

    def _rng(self, key: str) -> random.Random:
        return random.Random(subseed(self.world.seed, "discovery", key))

    # ----------------------------------------------- наблюдатель -----------
    def resolve_observers(self, place_id: str, player: str) -> Resolution:
        """«Не наблюдает ли кто-то за мной?» Существование решается раз и навсегда."""
        key = f"presence:{place_id}"
        rec = self.world.resolutions.get(key)
        if rec:
            return Resolution(key, rec["present"], rec["watching"], rec.get("npc"),
                              exists=rec["present"], p=rec.get("p", 0.0), recorded=True)

        loc = self.location_type(place_id)
        presence_mod, watch_mod = self._ctx_mods(place_id)
        fixed = self._fixed_others_here(place_id, player)
        rng = self._rng(key)

        p_present = min(0.99, PRESENCE.get(loc, 0.05) * presence_mod)
        present = bool(fixed) or rng.random() <= p_present
        npc = None
        watching = False
        if present:
            if fixed:
                npc = fixed[0]                       # потенциальный наблюдатель — кто уже тут
            elif self.char_gen is not None:
                npc = self._spawn_passerby(place_id, loc, rng)
            p_watch = min(0.95, WATCH_BASE * watch_mod)
            watching = rng.random() <= p_watch

        self.world.commit("resolve", "dm", payload={
            "key": key, "present": present, "watching": watching, "npc": npc,
            "p": round(p_present, 3), "loc": loc})
        return Resolution(key, present, watching, npc, exists=present, p=p_present)

    def _spawn_passerby(self, place_id: str, loc: str, rng: random.Random) -> str | None:
        roles = (["merchant", "laborer", "farmhand", "guard", "none"] if loc in
                 ("frontier_town", "market") else ["scout", "vagrant", "none"])
        race = rng.choice(["human", "human", "halfling", "dwarf"])
        job = rng.choice(roles)
        short = ids.name_of(place_id)[:6]
        name = f"Прохожий {short}{rng.randint(10, 99)}"
        try:
            return self.char_gen.spawn_npc(name, race, job, "region:phandalin", place_id)
        except Exception:
            return None

    # ----------------------------------------------- скрытое (вещи) --------
    def resolve_hidden(self, place_id: str, kind: str = "stash") -> Resolution:
        """«Есть ли тут скрытый тайник/предмет?» Существование фиксируется навсегда."""
        key = f"hidden:{place_id}:{kind}"
        rec = self.world.resolutions.get(key)
        if rec:
            return Resolution(key, exists=rec["exists"], container=rec.get("container"),
                              p=rec.get("p", 0.0), recorded=True)
        loc = self.location_type(place_id)
        p = HIDDEN.get(loc, {}).get(kind, 0.1)
        rng = self._rng(key)
        exists = rng.random() <= p
        container = None
        if exists:
            container = self._spawn_hidden_container(place_id, kind, rng)
        self.world.commit("resolve", "dm", payload={
            "key": key, "exists": exists, "container": container,
            "p": round(p, 3), "loc": loc})
        return Resolution(key, exists=exists, container=container, p=p)

    def _spawn_hidden_container(self, place_id: str, kind: str, rng: random.Random) -> str:
        from ..inventory.container import Container
        from .item_gen import generate_individual_treasure
        cid = f"container:hidden_{ids.name_of(place_id)}_{kind}"
        if cid in self.world.containers:
            return cid
        c = Container(container_id=cid, owner_ref=None, kind="chest", items=[])
        self.world.containers[cid] = c
        generate_individual_treasure(self.world, 0.5, self._party_level(),
                                     self.world.seed, cid,
                                     model=getattr(self.char_gen, "model", None))
        return cid

    def _party_level(self) -> int:
        from ..world.components import Stats5e
        if self.world.player_id:
            st = self.world.ecs.get(self.world.player_id, Stats5e)
            return st.level if st else 1
        return 1

    # ----------------------------------------------- интерьер дома ---------
    # Ленивая материализация наполнения дома + eager-персист (док 06 §2, main §2):
    # содержимое генерируется ДЕТЕРМИНИРОВАННО по сиду и фиксируется событием
    # «resolve» — повторный запрос даёт то же и переживает снапшот/реплей.
    _FIRST = {
        "human": ["Эдвин", "Марта", "Гарет", "Лина", "Освальд", "Бесс", "Том", "Карина", "Ройс", "Ильза"],
        "halfling": ["Пиппин", "Роза", "Мило", "Дейзи", "Анна"],
        "dwarf": ["Торин", "Бруна", "Дарек", "Хельга"],
        "elf": ["Аэлар", "Силь", "Таэль", "Энна"],
    }
    _ROLES = {
        "inn": ["трактирщик", "подавальщица", "усталый постоялец"],
        "shop": ["лавочник", "подмастерье", "придирчивый покупатель"],
        "shrine": ["жрец", "молчаливый послушник"],
        "townhall": ["писарь", "скучающий стражник"],
        "manor": ["дворецкий", "горничная", "хозяин поместья"],
        "farm": ["фермер", "батрак"],
        "home": ["хозяин дома", "хозяйка", "ребёнок", "старик у очага"],
    }
    _TRAITS = ["приветливый", "ворчливый", "настороженный", "болтливый", "усталый",
               "добродушный", "хитрый", "набожный"]
    _GOODS = {
        "inn": ["кружки эля", "котелок похлёбки", "связка ключей от комнат"],
        "shop": ["рулоны ткани", "мешки с зерном", "моток верёвки", "масляная лампа"],
        "shrine": ["курильница", "свечи", "священный символ"],
        "townhall": ["стопка свитков", "печать городка", "запылённый гербовник"],
        "manor": ["серебряный подсвечник", "гобелен", "запертый сундук"],
        "farm": ["вилы", "корзина яблок", "бочонок солений"],
        "home": ["очаг с углями", "лежанка", "сундучок с пожитками", "пучок сушёных трав"],
    }
    _AMBIANCE = {
        "inn": "Гомон, запах эля и дыма; в очаге трещит огонь.",
        "shop": "Полки до потолка, пахнет пылью и воском.",
        "shrine": "Полумрак, мерцают свечи, тянет благовониями.",
        "townhall": "Скрип перьев, ряды полок со свитками.",
        "manor": "Сумрачные залы, тяжёлые шторы, эхо шагов.",
        "farm": "Земляной пол, пахнет сеном и скотиной.",
        "home": "Тесная комнатёнка: очаг, лавка, нехитрый скарб.",
    }

    def _building_kind(self, place_id: str, hint: str | None) -> str:
        p = self.world.spatial.places.get(place_id)
        affs = set(p.affordances) if p else set()
        if "inn" in affs or "drink" in affs:
            return "inn"
        for a in ("shop", "shrine", "townhall", "manor", "farm"):
            if a in affs:
                return a
        if "hideout" in affs:
            return "manor"
        return hint if hint in self._ROLES else "home"

    def materialize_interior(self, place_id: str, kind_hint: str | None = None,
                             model=None) -> dict:
        """Наполнить дом контентом (жильцы, обстановка, описание) ОДИН раз и сохранить.
        Повторный вызов возвращает то же из памяти (recorded=True)."""
        # каждый осмотр поднимает индекс важности места (даже если содержимое уже в памяти)
        self.world.commit("interest", self.world.player_id or "dm",
                          payload={"place": place_id, "amount": 1})
        key = f"interior:{place_id}"
        rec = self.world.resolutions.get(key)
        if rec:
            return {**rec, "recorded": True}
        kind = self._building_kind(place_id, kind_hint)
        rng = random.Random(subseed(self.world.seed, "interior", place_id))
        # жильцы (иногда дом пуст)
        base = {"inn": 3, "shop": 2, "shrine": 1, "townhall": 2, "manor": 3, "farm": 2, "home": 2}[kind]
        n = max(0, base - rng.randint(0, 2)) if kind == "home" else max(1, base - rng.randint(0, 1))
        races = ["human", "human", "human", "halfling", "dwarf", "elf"]
        roles = list(self._ROLES[kind])
        occupants = []
        for i in range(n):
            race = rng.choice(races)
            occupants.append({
                "name": rng.choice(self._FIRST.get(race, self._FIRST["human"])),
                "race": race, "role": roles[i % len(roles)],
                "trait": rng.choice(self._TRAITS), "age": rng.randint(8, 70)})
        # обстановка/предметы (2-4)
        pool = self._GOODS[kind]
        items = rng.sample(pool, k=min(len(pool), 2 + rng.randint(0, 2)))
        desc = self._AMBIANCE[kind]
        if model is not None and getattr(model, "available", lambda: False)():
            from ..inference.agents import render_scene
            out = render_scene(model, f"Интерьер: {kind}. Жильцы: "
                               + ", ".join(f"{o['name']} ({o['role']})" for o in occupants)
                               + f". Обстановка: {', '.join(items)}.", None, "interior")
            if out and out.get("narration"):
                desc = out["narration"]
        payload = {"key": key, "place": place_id, "kind": kind, "occupants": occupants,
                   "items": items, "description": desc, "materialized": True}
        self.world.commit("resolve", "dm", payload=payload)
        return {**payload, "recorded": False}
