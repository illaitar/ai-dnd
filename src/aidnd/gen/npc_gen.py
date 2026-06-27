"""Character Generator (док 02).

LOD на глубину контента: при рождении — табличный скелет без LLM; при первом L3 —
обогащение прозы персоны моделью под схемой (с детерминированным фоллбэком);
когнитивная память только в активном L3. Тройная экономия.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .. import ids
from ..rules.srd import get_stat_block
from ..world.components import (
    LODState,
    Persona,
    Profession,
    Relationships,
    RelEdge,
    Schedule,
    ScheduleBlock,
    Stats5e,
)
from ..world.spatial import Place
from .lore_keeper import validate_npc_draft
from .names import make_name
from .seeds import subseed


@dataclass
class SettlementProfile:
    name: str
    target_population: int = 45
    profession_dist: dict = field(default_factory=dict)
    race_dist: dict = field(default_factory=dict)
    age_mean: int = 35
    age_std: int = 14
    household_dist: dict = field(default_factory=lambda: {1: 0.3, 2: 0.3, 3: 0.25, 4: 0.15})


# профессия -> SRD стат-блок (док 02 §4)
ARCHETYPE_STATBLOCK = {
    "farmhand": "srd:commoner", "miner": "srd:commoner", "merchant": "srd:commoner",
    "innkeeper": "srd:commoner", "blacksmith": "srd:commoner", "priest": "srd:acolyte",
    "guard": "srd:guard", "scout": "srd:scout", "laborer": "srd:commoner",
    "hunter": "srd:scout", "healer": "srd:acolyte", "none": "srd:commoner",
}

# профессия -> тип здания работы
WORKPLACE_TYPE = {
    "blacksmith": "smithy", "innkeeper": "inn", "merchant": "shop", "priest": "shrine",
    "guard": "townhall", "miner": "mine", "farmhand": "farm", "hunter": "wilds",
    "healer": "shrine", "laborer": "yard", "scout": "wilds",
}

DEFAULT_TRAITS = {
    "farmhand": ["hardworking", "talkative"], "miner": ["gruff", "tired"],
    "merchant": ["shrewd", "friendly"], "innkeeper": ["welcoming", "gossipy"],
    "blacksmith": ["strong", "blunt"], "priest": ["calm", "devout"],
    "guard": ["watchful", "dutiful"], "none": ["ordinary"],
}

DEFAULT_SCHEDULE = [
    ("06:00", "work"), ("13:00", "eat"), ("19:00", "home"), ("23:00", "sleep"),
]


class CharacterGenerator:
    """Генератор по контракту дока 01: bulk pregen (tabular) + lazy enrich (model)."""

    def __init__(self, world, model=None) -> None:
        self.world = world
        self.model = model
        self._bld_counter = 0
        self._capacity: dict = {}

    # ------------------------------------------------ bulk pregen ----------
    def generate_roster(self, profile: SettlementProfile, quota: int) -> list[str]:
        rng = random.Random(subseed(self.world.seed, "roster", profile.name))
        occupied = self._unique_roles_taken()
        ids_out: list[str] = []
        households = self._partition_households(quota, profile, rng)
        for hh_size in households:
            surname = None
            members: list[str] = []
            for i in range(hh_size):
                race = self._sample(profile.race_dist, rng)
                job = "none" if i and rng.random() < 0.5 else self._sample(
                    self._adjusted(profile.profession_dist, occupied), rng)
                gender = rng.choice(["male", "female"])
                age = max(16, int(rng.gauss(profile.age_mean, profile.age_std))) if i == 0 \
                    else rng.randint(6, 60)
                given, surname = make_name(race, gender, self.world.name_registry, rng, surname)
                npc_id = self._build_skeleton(given, surname, race, gender, age, job, rng)
                members.append(npc_id)
                ids_out.append(npc_id)
                if job not in ("none",):
                    occupied.add(job)
            self._assign_places(members, rng)
            self._seed_household_rels(members)
        return ids_out

    def _build_skeleton(self, given, surname, race, gender, age, job, rng) -> str:
        name = f"{given} {surname}"
        npc_id = ids.make("npc", name)
        # коллизия id — добавим суффикс
        if self.world.ecs.exists(npc_id):
            npc_id = ids.make("npc", f"{name} {rng.randint(100,999)}")
        self.world.ecs.spawn(npc_id)
        sb_ref = ARCHETYPE_STATBLOCK.get(job, "srd:commoner")
        sb = get_stat_block(sb_ref)
        persona = Persona(
            name=name, archetype=job, race=race, gender=gender, age=age,
            profession=None if job == "none" else job,
            traits=list(DEFAULT_TRAITS.get(job, ["ordinary"])),
            stat_block_ref=sb_ref,
        )
        try:                                # базовые знания профессии/фракции (док 02 §4)
            from ..content.knowledge import inherit_knowledge
            inherit_knowledge(persona, None if job == "none" else job, persona.faction)
        except Exception:
            pass
        self.world.ecs.add(npc_id, persona)
        self.world.ecs.add(npc_id, Stats5e(
            str_=sb.str_, dex=sb.dex, con=sb.con, int_=sb.int_, wis=sb.wis, cha=sb.cha,
            max_hp=sb.hp, hp=sb.hp, ac_base=sb.ac, proficiency=sb.proficiency, speed=sb.speed,
            proficient_skills=list(sb.skills),
        ))
        self.world.ecs.add(npc_id, LODState(tier=0))
        self.world.ecs.add(npc_id, Relationships())
        if job != "none":
            self.world.ecs.add(npc_id, Profession(job=job))
            self.world.commit("kg_set", "worldgen", payload={"s": npc_id, "r": "profession", "o": job})
        self.world.name_registry.add(name)
        try:                                # знания мира/города/роли + рёбра knows (граф знаний)
            from ..content.facts import seed_known_facts
            seed_known_facts(self.world, npc_id)
        except Exception:
            pass
        return npc_id

    # ------------------------------------------ CSP assign places ----------
    def _assign_places(self, members: list[str], rng) -> None:
        # workplaces
        for npc_id in members:
            prof = self.world.ecs.get(npc_id, Profession)
            if not prof:
                continue
            wtype = WORKPLACE_TYPE.get(prof.job, "yard")
            wb = self._building_of_type(wtype) or self._instantiate_building(wtype, rng)
            prof.workplace_ref = wb
            self.world.commit("kg_set", "worldgen",
                              payload={"s": npc_id, "r": "works_at", "o": wb})
        # residence (семья вместе)
        home = self._residential_with_capacity(len(members)) or self._instantiate_building("house", rng)
        for npc_id in members:
            prof = self.world.ecs.get(npc_id, Profession)
            if prof:
                prof.residence_ref = home
            self.world.commit("kg_set", "worldgen",
                              payload={"s": npc_id, "r": "lives_in", "o": home})
            self._set_default_schedule(npc_id, home, prof.workplace_ref if prof else home)
        self._capacity[home] = self._capacity.get(home, 0) + len(members)

    def _set_default_schedule(self, npc_id, home, work) -> None:
        blocks = []
        for t, aff in DEFAULT_SCHEDULE:
            place = work if aff == "work" else (home if aff in ("home", "sleep") else "building:stonehill_inn")
            blocks.append(ScheduleBlock(t=t, place=place, affordance=aff))
        self.world.ecs.add(npc_id, Schedule(routine=blocks))

    # ------------------------------------------ relationships --------------
    def _seed_household_rels(self, members: list[str]) -> None:
        for a in members:
            for b in members:
                if a == b:
                    continue
                rels = self.world.ecs.get(a, Relationships)
                rels.edges[b] = RelEdge(affinity=0.6, trust=0.7, respect=0.4, tags=["family"])

    # ------------------------------------------ lazy enrichment ------------
    def enrich(self, npc_id: str) -> None:
        """Первое L3: обогатить voice/traits моделью под схемой emit_persona,
        с детерминированным фоллбэком, если модель недоступна (док 02 §10)."""
        persona = self.world.ecs.get(npc_id, Persona)
        if not persona or persona.enriched:
            return
        result = None
        if self.model is not None:
            from ..inference.agents import enrich_persona
            result = enrich_persona(self.model, persona, self.world)
        if not result:
            # детерминированный фоллбэк
            result = {
                "voice": f"говорит как {persona.archetype}, по делу",
                "traits": persona.traits + ["wary of strangers"],
            }
        persona.voice = result.get("voice") or persona.voice
        persona.traits = result.get("traits") or persona.traits
        persona.appearance = result.get("appearance") or persona.appearance
        persona.ideal = result.get("ideal") or persona.ideal
        persona.bond = result.get("bond") or persona.bond
        persona.flaw = result.get("flaw") or persona.flaw
        if result.get("epithet"):
            persona.epithet = result["epithet"]
        # секреты/слухи → гейтованные knowledge-items: слухи (gate 0) делятся свободно,
        # секреты (gate 0.6) — только при доверии (живой мир, content/knowledge.disclosable)
        have = {k.get("fact") for k in persona.knowledge}
        for s in result.get("secrets") or []:
            if s and s not in have:
                item = {"fact": s, "topic": "тайна", "disclosure_gate": {"trust": 0.6}}
                persona.knowledge.append(item); persona.secrets.append(item); have.add(s)
        for k in result.get("knowledge") or []:
            if k and k not in have:
                persona.knowledge.append({"fact": k, "topic": "слухи", "disclosure_gate": {"trust": 0.0}})
                have.add(k)
        persona.enriched = True

    # ------------------------------------------ player-spawned -------------
    def spawn_npc(self, name: str, race: str, job: str, region: str,
                  place_id: str | None = None, source: str = "lazy") -> str:
        rng = random.Random(subseed(self.world.seed, "spawn", name, self.world.clock.tick))
        gender = rng.choice(["male", "female"])
        given_sur = name if " " in name else f"{name} {make_name(race, gender, self.world.name_registry, rng)[1]}"
        parts = given_sur.split(" ", 1)
        npc_id = self._build_skeleton(parts[0], parts[1] if len(parts) > 1 else "", race, gender,
                                      rng.randint(20, 55), job, rng)
        self._assign_places([npc_id], rng)
        if place_id:
            self.world.commit("set_position", "worldgen",
                              target=npc_id, payload={"region": region, "place": place_id})
        # валидация
        persona = self.world.ecs.get(npc_id, Persona)
        prof = self.world.ecs.get(npc_id, Profession)
        draft = {"name": persona.name, "profession": persona.profession,
                 "workplace_ref": prof.workplace_ref if prof else None,
                 "residence_ref": prof.residence_ref if prof else None, "_registered": True}
        validate_npc_draft(draft, self.world)  # фиксы уже применены CSP
        return npc_id

    # ------------------------------------------ helpers --------------------
    def _building_of_type(self, btype: str) -> str | None:
        for pid, place in self.world.spatial.places.items():
            if place.kind == "building" and btype in place.affordances:
                return pid
        return None

    def _residential_with_capacity(self, size: int, cap: int = 6) -> str | None:
        for pid, place in self.world.spatial.places.items():
            if place.kind == "building" and "residential" in place.affordances:
                if self._capacity.get(pid, 0) + size <= cap:
                    return pid
        return None

    def _instantiate_building(self, btype: str, rng) -> str:
        self._bld_counter += 1
        bid = f"building:{btype}_{self._bld_counter:02d}"
        affs = ["residential"] if btype == "house" else [btype, "work"]
        place = Place(place_id=bid, kind="building", name=f"{btype} {self._bld_counter}",
                      parent="settlement:phandalin", district="residential", affordances=affs)
        self.world.spatial.add_place(place)
        self.world.commit("kg_add", "worldgen",
                          payload={"s": bid, "r": "located_in", "o": "district:residential"})
        return bid

    def _unique_roles_taken(self) -> set[str]:
        taken = set()
        for npc in self.world.npcs():
            prof = self.world.ecs.get(npc, Profession)
            if prof and prof.job in ("innkeeper", "blacksmith"):
                taken.add(prof.job)
        return taken

    @staticmethod
    def _sample(dist: dict, rng) -> str:
        items = [(k, v) for k, v in dist.items() if v > 0]
        total = sum(v for _, v in items) or 1
        r = rng.random() * total
        acc = 0.0
        for k, v in items:
            acc += v
            if r <= acc:
                return k
        return items[-1][0] if items else "none"

    @staticmethod
    def _adjusted(dist: dict, occupied: set[str]) -> dict:
        out = dict(dist)
        for role in ("innkeeper", "blacksmith"):
            if role in occupied:
                out[role] = 0.0
        return out

    @staticmethod
    def _partition_households(quota: int, profile: SettlementProfile, rng) -> list[int]:
        sizes, n = [], 0
        while n < quota:
            s = min(CharacterGenerator._sample(profile.household_dist, rng), quota - n)
            s = max(1, int(s))
            sizes.append(s)
            n += s
        return sizes
