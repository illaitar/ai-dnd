"""ECS-компоненты (main §3.1).

Сущность — голый id. Поведение и данные лежат в компонентах. NPC, предмет,
дверь — это просто разные наборы компонентов. LOD-тиры тоже компоненты,
которые система симуляции добавляет и снимает.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    region_id: str
    place_id: str | None = None           # узел графа локаций (building/room/site)


@dataclass
class ScheduleBlock:
    t: str                  # "06:00"
    place: str              # place/building id
    affordance: str         # work | eat | home | sleep | serve | drink ...


@dataclass
class Schedule:
    routine: list[ScheduleBlock] = field(default_factory=list)


@dataclass
class RelEdge:
    """Вектор аффекта к сущности (main §5.4)."""

    affinity: float = 0.0   # -1..1 симпатия
    trust: float = 0.0      # -1..1 доверие
    fear: float = 0.0       #  0..1 страх
    respect: float = 0.0    # -1..1 уважение
    tags: list[str] = field(default_factory=list)  # "saved_my_life", ...

    def clamp(self) -> None:
        self.affinity = max(-1.0, min(1.0, self.affinity))
        self.trust = max(-1.0, min(1.0, self.trust))
        self.fear = max(0.0, min(1.0, self.fear))
        self.respect = max(-1.0, min(1.0, self.respect))


@dataclass
class Relationships:
    edges: dict[str, RelEdge] = field(default_factory=dict)  # target_id -> RelEdge


@dataclass
class LODState:
    tier: int = 0           # 0..3
    salience: float = 0.0
    last_promoted_tick: int = 0
    last_active_tick: int = 0


@dataclass
class Stats5e:
    """Лист характеристик 5e (используется PC и боевыми NPC)."""

    str_: int = 10
    dex: int = 10
    con: int = 10
    int_: int = 10
    wis: int = 10
    cha: int = 10
    proficiency: int = 2
    level: int = 1
    max_hp: int = 10
    hp: int = 10
    temp_hp: int = 0
    speed: int = 30
    ac_base: int = 10                       # без брони/щита (док 04 пересчитает)
    proficient_skills: list[str] = field(default_factory=list)
    proficient_saves: list[str] = field(default_factory=list)
    spell_slots: dict[str, int] = field(default_factory=dict)   # "1": 2
    spell_ability: str = "int"

    def ability(self, key: str) -> int:
        return {
            "str": self.str_, "dex": self.dex, "con": self.con,
            "int": self.int_, "wis": self.wis, "cha": self.cha,
        }[key]


@dataclass
class Progression:
    """Прокачка персонажа 5e: класс, опыт, фичи, подкласс, заклинания (rules/progression)."""

    class_id: str = "fighter"
    xp: int = 0
    subclass: str | None = None
    fighting_style: str | None = None
    features: list[str] = field(default_factory=list)        # выданные фичи (id)
    expertise: list[str] = field(default_factory=list)       # навыки с компетентностью
    feats: list[str] = field(default_factory=list)           # взятые черты
    cantrips: list[str] = field(default_factory=list)        # известные заговоры
    spells_known: list[str] = field(default_factory=list)    # книга/известные заклинания
    pending: int = 0                                         # сколько уровней ждут выбора игрока


@dataclass
class Persona:
    """Персона NPC (main §3.1, расширена в доке 02 §3)."""

    name: str
    archetype: str = "commoner"
    race: str = "human"
    gender: str = "unknown"
    age: int = 30
    profession: str | None = None
    traits: list[str] = field(default_factory=list)
    ideal: str = ""
    bond: str = ""
    flaw: str = ""
    voice: str | None = None            # лениво заполняется при первом L3
    appearance: list[str] = field(default_factory=list)
    stat_block_ref: str = "srd:commoner"
    faction: str | None = None
    faction_rank: str | None = None
    epithet: str | None = None          # "the Black Spider", "Glasstaff"
    aliases: list[str] = field(default_factory=list)  # рус. формы имени для матчинга ссылок игрока
    knowledge: list[dict] = field(default_factory=list)  # KnowledgeItem-словари
    secrets: list[dict] = field(default_factory=list)
    marks: list[str] = field(default_factory=list)  # стойкие следы на персонаже (синяк, метка) — агент последствий
    enriched: bool = False              # прошёл ли first-L3 обогащение моделью
    companion: bool = False             # спутник партии: следует за игроком и бьётся на его стороне
    following: bool = False             # временно идёт с игроком (уговорил/нанял) — следует, но не в партии


@dataclass
class Profession:
    job: str
    workplace_ref: str | None = None    # инвариант: профессия ⟹ workplace
    residence_ref: str | None = None    # инвариант: профессия ⟹ residence
    skill_level: str = "journeyman"     # apprentice | journeyman | master


@dataclass
class Faction:
    """Компонент фракции на сущности-фракции (генерируется per-world, обогащается LLM)."""

    name: str
    kind: str = "guild"                 # thieves_guild|merchant_guild|aristocracy|temple|watch|arcane|criminal|...
    blurb: str = ""                     # короткое описание (LLM)
    goals: list[str] = field(default_factory=list)     # к чему стремится
    values: list[str] = field(default_factory=list)    # что одобряет/осуждает
    emblem: str = "🏳"                  # герб-эмодзи
    leader: str | None = None           # npc id главы
    members: list[str] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)
    relations: dict[str, float] = field(default_factory=dict)   # faction_id -> [-1..1]
    ranks: list[str] = field(default_factory=list)     # тиры стояния (низший→высший)
    join_min_rep: float = 0.25          # порог репутации для вступления
    joinable: bool = True               # можно ли вступить игроку
    enriched: bool = False              # применено ли LLM-обогащение


@dataclass
class Affiliation:
    """Принадлежность персонажа к фракциям: членство, ранг и склонности."""

    membership: str | None = None                      # текущая фракция (id)
    rank: int = 0                                       # индекс в Faction.ranks
    affinity: dict[str, float] = field(default_factory=dict)   # faction_id -> склонность [-1..1]


@dataclass
class GoalPlan:
    """Дневной план L3-NPC (main §5.5)."""

    day_goal: str = ""
    blocks: list[str] = field(default_factory=list)
