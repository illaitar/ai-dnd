"""Граф знаний мира: канонические факты-ноды + сидинг и распространение (док 02 §4+).

Факт — общий узел (мировой/городской/фракционный/ролевой/личный). Ноды-сущности
(NPC, фракции) ссылаются на факт ребром `knows` (триплы в world.kg), так что
«кто что знает» — это обход графа, а не текст в персоне.

Два момента жизненного цикла:
  • build_fact_base() — при СТАРТЕ игры наполняет большой пул фактов мира и города
    (авторские + производные от сайтов/фракций/профессий). Детерминированно.
  • seed_known_facts() — при СОЗДАНИИ NPC раздаёт ему знания по области: мировые
    знают все, городские — с высокой вероятностью (сид-детерминировано), фракционные —
    члены фракции, ролевые — по профессии; плюс авторские личные факты персоны.

Persona.knowledge остаётся заполненным (вью факта через as_knowledge_item) — это
сохраняет обратную совместимость с disclosable()/director/mapinfo. Релевантный отбор
под запрос игрока делает cognition.recall поверх этих же данных.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..gen.seeds import subseed
from ..world.components import Persona
from .knowledge import FACTION_KNOWLEDGE, PROFESSION_KNOWLEDGE
from .region import REGION_SITES

P_CITY = 0.8   # вероятность, что горожанин знает общегородской факт


@dataclass
class Fact:
    """Каноническая факт-нода графа знаний."""

    fact_id: str
    text: str
    topic: str = "rumors"
    scope: str = "city"            # world | city | faction:<id> | role:<job> | personal
    sensitivity: float = 0.1       # 0..1 → порог доверия для раскрытия (disclosure gate)
    tags: list[str] = field(default_factory=list)   # для релевантности (recall)
    subject: str | None = None     # о ком/чём факт (entity/site id)
    truth: bool = True
    unlocks_quest: str | None = None


def as_knowledge_item(f: Fact) -> dict:
    """Вью факта в формате Persona.knowledge (обратная совместимость с disclosable/director)."""
    item = {
        "fact": f.text, "topic": f.topic,
        "disclosure_gate": {"trust": f.sensitivity},
        "fact_id": f.fact_id, "scope": f.scope, "tags": list(f.tags),
    }
    if f.unlocks_quest:
        item["unlocks_quest"] = f.unlocks_quest
    return item


# --------------------------------------------------------------------------- #
#  Авторская основа пула (старт игры)                                          #
# --------------------------------------------------------------------------- #
# Мировые факты — фон края, который знает почти каждый (низкий порог раскрытия).
_AUTHORED_WORLD = [
    ("Фэндалин — обнесённый стеной фронтирный город у Каменных холмов на реке; стража немногочисленна, и закон тут слаб", "phandalin", 0.0, ["фэндалин", "город"]),
    ("к северу лежит Невервинтер, к югу — тракт на Глубоководье; дороги небезопасны", "geography", 0.0, ["дороги", "невервинтер", "география"]),
    ("когда-то гномы и люди добывали волшебную руду в Пещере Эха Волн, пока её не поглотила беда", "wave_echo", 0.1, ["рудник", "история", "магия"]),
    ("на фронтире пошаливают гоблины и разбойники — редкий караван доходит без приключений", "rumors", 0.0, ["гоблины", "разбой", "дорога"]),
]

# Городские факты — слухи и новости Фэндалина (горожане знают с высокой вероятностью).
_AUTHORED_CITY = [
    ("в городе хозяйничают Красные плащи — головорезы в алых плащах, и управы на них нет", "redbrands", 0.05, ["красные плащи", "банда"]),
    ("градоправитель Харбин Вестер труслив и делает вид, что разбойников не существует", "redbrands", 0.1, ["харбин", "власть"]),
    ("руду из шахт почти не возят — цены в лавках поползли вверх", "mine", 0.05, ["руда", "цены", "торговля"]),
    ("в «Каменном Холме» дают ночлег, горячую похлёбку и свежие сплетни", "rumors", 0.0, ["таверна", "ночлег"]),
    ("дворф Гундрен Рокскикер хлопотал о чём-то в городе, да вдруг пропал по дороге", "gundren", 0.2, ["гундрен", "пропажа"]),
    ("у Львинощит Костер угнали караван с товаром где-то на тракте", "lionshield", 0.1, ["караван", "лавка"]),
]


def build_fact_base(world, model=None) -> None:
    """Наполнить world.facts каноническими фактами (старт игры). Детерминированно.

    Порядок построения фиксирован → fact_id стабильны между билдами (важно для replay,
    хотя сами рёбра knows воспроизводит build_world, а не сейв-хвост)."""
    facts: dict[str, Fact] = world.facts
    seq = {"n": 0}

    def reg(text, topic, scope, sensitivity, tags=None, subject=None, unlocks=None):
        seq["n"] += 1
        fid = f"fact:{seq['n']:04d}"
        facts[fid] = Fact(fid, text, topic, scope, float(sensitivity),
                          list(tags or []), subject, True, unlocks)
        return fid

    for text, topic, sens, tags in _AUTHORED_WORLD:
        reg(text, topic, "world", sens, tags)
    for text, topic, sens, tags in _AUTHORED_CITY:
        reg(text, topic, "city", sens, tags)

    # сайты региона → мировое «где что лежит» + городской слух об опасности/содержимом
    for key, s in REGION_SITES.items():
        label = s["label"]
        reg(f"{label} — это {s['terrain']}, {s['direction']} отсюда", key, "world", 0.05,
            [label.lower(), s["direction"], "место"], subject=s.get("place"))
        reg(f"болтают, что в месте «{label}» опасность {s['danger']}: {s['contents']}", key,
            "city", 0.2, [label.lower(), "опасность", s["danger"]], subject=s.get("place"))

    # фракционные знания → область faction:<id> (знают члены фракции)
    for fid, items in FACTION_KNOWLEDGE.items():
        for it in items:
            reg(it["fact"], it.get("topic", "rumors"), fid,
                (it.get("disclosure_gate") or {}).get("trust", 0.5),
                [it.get("topic", "")], unlocks=it.get("unlocks_quest"))

    # профессиональные знания → роль role:<job> (знают носители профессии)
    for job, items in PROFESSION_KNOWLEDGE.items():
        for it in items:
            reg(it["fact"], it.get("topic", "rumors"), f"role:{job}",
                (it.get("disclosure_gate") or {}).get("trust", 0.1),
                [it.get("topic", ""), job], unlocks=it.get("unlocks_quest"))

    # LLM-обогащение: большой пул дополнительных слухов мира/города (если есть модель).
    # Кешируется по сиду → детерминированно между перезапусками (replay-safe).
    if model is not None:
        for it in _llm_facts(world, model):
            sc = it.get("scope") if it.get("scope") in ("world", "city") else "city"
            sens = max(0.0, min(0.6, float(it.get("sensitivity", 0.1))))
            reg(it["text"], it.get("topic") or "rumors", sc, sens,
                it.get("tags") or [it.get("topic") or "rumors"])


def _world_digest(world) -> str:
    from ..gen.citymap import city_brief
    sites = ", ".join(s["label"] for s in REGION_SITES.values())
    head = city_brief(getattr(world, "city_profile", None) or {}) or "Фэндалин — фронтирный город у Каменных холмов."
    return (f"{head} Это фронтир у Каменных холмов: вокруг дикие земли и места: "
            f"{sites}. В округе действуют Красные плащи, гоблины Крэгмо, Жентарим, Арфисты, "
            "Союз Лордов; рудник заброшен, дороги небезопасны, стража не поспевает за всем.")


def _llm_facts(world, model) -> list[dict]:
    """LLM-слухи с кешом по сиду (детерминизм между перезапусками; сейв-хвост не трогает)."""
    import json
    import os

    from .. import config
    path = os.path.join(config.SAVE_DIR, f"facts_cache_{world.seed}.json")
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                cached = json.load(fh)
            if isinstance(cached, list):
                return cached
    except Exception:
        pass
    try:
        from ..inference.agents import emit_world_facts
        facts = emit_world_facts(model, _world_digest(world), n=14) or []
    except Exception:
        facts = []
    facts = [f for f in facts if isinstance(f, dict) and f.get("text")]
    if facts:
        try:
            os.makedirs(config.SAVE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(facts, fh, ensure_ascii=False)
        except Exception:
            pass
    return facts


def seed_known_facts(world, npc_id: str) -> None:
    """Раздать NPC знания при создании: мир (все) + город (вероятностно) + фракция/роль,
    плюс зарегистрировать авторские личные знания как ноды. Проставляет рёбра knows."""
    persona = world.ecs.get(npc_id, Persona)
    if persona is None:
        return
    job = persona.profession or persona.archetype
    fac = persona.faction
    have = {k.get("fact") for k in persona.knowledge}

    def link(fid: str) -> None:
        world.commit("kg_add", "worldgen", payload={"s": npc_id, "r": "knows", "o": fid})

    for fid, f in list(world.facts.items()):
        if not isinstance(f, Fact):
            continue
        if f.scope == "world":
            known = True
        elif f.scope == "city":
            known = random.Random(subseed(world.seed, "knows", npc_id, fid)).random() < P_CITY
        elif f.scope.startswith("faction:"):
            known = (fac == f.scope)
        elif f.scope.startswith("role:"):
            known = (f.scope == f"role:{job}")
        else:
            known = False
        if not known:
            continue
        if f.text not in have:
            persona.knowledge.append(as_knowledge_item(f))
            have.add(f.text)
        link(fid)

    # авторские личные знания (заданы в _add_npc) → личные факт-ноды + рёбра knows
    for it in persona.knowledge:
        if it.get("fact_id"):
            continue
        fid = _register_personal(world, npc_id, it)
        it["fact_id"] = fid
        it.setdefault("scope", "personal")
        link(fid)


def _register_personal(world, npc_id: str, item: dict) -> str:
    prefix = f"fact:p:{npc_id}:"
    n = sum(1 for k in world.facts if str(k).startswith(prefix)) + 1
    fid = f"{prefix}{n}"
    world.facts[fid] = Fact(
        fid, item.get("fact", ""), item.get("topic", "rumors"), "personal",
        (item.get("disclosure_gate") or {}).get("trust", 0.1),
        list(item.get("tags") or [item.get("topic", "")]),
        unlocks_quest=item.get("unlocks_quest"))
    return fid


def teach_personal_fact(world, npc_id: str, item: dict) -> str:
    """Записать ЛИЧНЫЙ факт в память NPC: личный факт-нод + ребро knows + Persona.knowledge. → fact_id.

    item: {fact, topic, tags, trust (порог раскрытия 0..1), unlocks_quest?}. Идемпотентно по содержанию
    в рамках одной сборки мира; на load пересоздаётся в build_world (рёбра графа — множество)."""
    from ..world.components import Persona
    payload = {"fact": item.get("fact", ""), "topic": item.get("topic", "rumors"),
               "tags": list(item.get("tags") or []),
               "disclosure_gate": {"trust": float(item.get("trust", 0.1))},
               "unlocks_quest": item.get("unlocks_quest")}
    fid = _register_personal(world, npc_id, payload)
    world.commit("kg_add", "worldgen", payload={"s": npc_id, "r": "knows", "o": fid})
    per = world.ecs.get(npc_id, Persona)
    if per is not None and world.facts.get(fid):
        per.knowledge.append(as_knowledge_item(world.facts[fid]))
    return fid


def register_rumor(world, text: str, tags=None, source_npc: str | None = None) -> str:
    """Рантайм-слух (city-scope) — расходится по горожанам через diffuse_rumors, игрок услышит в разговорах.
    Используется деятельными NPC: их шаги-замыслы порождают молву в городе."""
    n = sum(1 for k in world.facts if str(k).startswith("fact:rumor:")) + 1
    fid = f"fact:rumor:{n}"
    world.facts[fid] = Fact(fid, text, "rumors", "city", 0.1, list(tags or ["слух"]))
    if source_npc:                                          # источник уже знает свою молву
        world.commit("kg_add", "agency", payload={"s": source_npc, "r": "knows", "o": fid})
    return fid


def knowers_of(world, fact_id: str) -> list[str]:
    """Обход графа: кто знает факт (ноды-сущности с ребром knows → fact_id)."""
    return world.kg.subjects_of("knows", fact_id)


def diffuse_rumors(world, max_spreads: int | None = None) -> int:
    """Оборот слухов: знающий факт NPC передаёт его незнающему — рёбра knows растут со временем.

    Распространяются только нечувствительные правдивые слухи мира/города. Детерминировано по
    (seed, tick); каждое «узнавание» — event learn_fact (синк в граф и Persona.knowledge),
    поэтому воспроизводится при загрузке. Возвращает число новых узнаваний."""
    from .. import config
    cap = config.DIFFUSE_MAX_PER_STEP if max_spreads is None else max_spreads
    rng = random.Random(subseed(world.seed, "diffuse", world.clock.tick))
    spreadable = [fid for fid, f in world.facts.items()
                  if isinstance(f, Fact) and f.scope in ("world", "city")
                  and f.truth and f.sensitivity <= 0.2]
    npcs = [n for n in world.npcs() if world.is_alive(n)]   # мёртвые слухов не разносят
    if not spreadable or len(npcs) < 2:
        return 0
    rng.shuffle(spreadable)
    spreads = 0
    for fid in spreadable:
        if spreads >= cap:
            break
        knowers = set(world.kg.subjects_of("knows", fid))
        if not knowers:
            continue
        candidates = [n for n in npcs if n not in knowers]
        if not candidates:
            continue
        target = rng.choice(candidates)
        world.commit("learn_fact", "rumor", payload={"npc": target, "fact": fid})
        spreads += 1
    return spreads
