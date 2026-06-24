"""Граф знаний: генерация пула при старте, наполнение NPC, релевантный recall, гейт."""

from __future__ import annotations

from aidnd.bootstrap import new_session
from aidnd.content import build_world
from aidnd.content.facts import Fact, knowers_of
from aidnd.world.components import Persona, RelEdge

TOBLEN = "npc:toblen_stonehill"
IARNO = "npc:iarno_glasstaff"


def _sess():
    return new_session(seed=1337, roster_size=8, use_model=False)


def _scopes(world) -> set[str]:
    return {f.scope.split(":")[0] for f in world.facts.values() if isinstance(f, Fact)}


# --- генерация пула при старте --------------------------------------------- #
def test_fact_base_generated_at_start():
    w = build_world(seed=1337, roster_size=0)
    facts = [f for f in w.facts.values() if isinstance(f, Fact)]
    assert len(facts) >= 30                                   # «большой кусок» знаний
    # все уровни области присутствуют
    assert {"world", "city"} <= _scopes(w)
    assert any(f.scope.startswith("faction:") for f in facts)
    assert any(f.scope.startswith("role:") for f in facts)


# --- наполнение NPC + рёбра knows ------------------------------------------ #
def test_npc_seeded_with_world_and_city_facts():
    w = build_world(seed=1337, roster_size=0)
    persona = w.ecs.get(TOBLEN, Persona)
    scopes = {(k.get("scope") or "") for k in persona.knowledge}
    assert "world" in scopes and "city" in scopes
    # каждое знание persona теперь привязано к факт-ноде
    assert all(k.get("fact_id") for k in persona.knowledge)
    # рёбра knows проставлены в графе
    known = w.kg.objects_of(TOBLEN, "knows")
    assert len(known) >= 5


def test_world_fact_known_by_many():
    w = build_world(seed=1337, roster_size=8)
    wf = next(fid for fid, f in w.facts.items()
              if isinstance(f, Fact) and f.scope == "world")
    knowers = knowers_of(w, wf)
    assert len(knowers) >= 8                                  # мировое знают почти все


def test_faction_fact_only_for_members():
    w = build_world(seed=1337, roster_size=0)
    hideout = next(fid for fid, f in w.facts.items()
                   if isinstance(f, Fact) and f.scope == "faction:redbrands"
                   and "тресендар" in f.text.lower())
    knowers = knowers_of(w, hideout)
    assert IARNO in knowers                                   # член Красных плащей знает укрытие
    assert TOBLEN not in knowers                              # трактирщик — нет


# --- релевантность recall --------------------------------------------------- #
def test_recall_ranks_relevant_first():
    s = _sess()
    rel = RelEdge(trust=0.7)
    top = s.cognition.recall(TOBLEN, "что ты знаешь о Красных плащах?", rel, k=1)
    assert top and "плащ" in top[0]["fact"].lower()          # релевантный факт — первым

    # иной запрос → иной топ-факт
    top2 = s.cognition.recall(TOBLEN, "расскажи про рудник и руду", rel, k=3)
    joined = " ".join(it["fact"].lower() for it in top2)
    assert "руд" in joined


# --- гейт: убеждение/обман поднимает эффективное доверие -------------------- #
def test_recall_gates_by_trust_and_opens_on_check():
    s = _sess()
    rel0 = RelEdge(trust=0.0)                                 # незнакомец
    low = [it["fact"].lower() for it in s.cognition.recall(IARNO, "укрытие плащей", rel0, k=10)]
    assert not any("тресендар" in f for f in low)            # чувствительное закрыто

    # успешная проверка → эффективный гейт открывает чувствительный факт
    hi = [it["fact"].lower() for it in
          s.cognition.recall(IARNO, "укрытие плащей", rel0, gate_level=0.7, k=10)]
    assert any("тресендар" in f for f in hi)


# --- детерминизм распространения -------------------------------------------- #
def test_seeding_deterministic_by_seed():
    a = build_world(seed=1337, roster_size=8)
    b = build_world(seed=1337, roster_size=8)
    npc = next(n for n in a.npcs())
    assert sorted(a.kg.objects_of(npc, "knows")) == sorted(b.kg.objects_of(npc, "knows"))


# --- обман как маршрутизируемый глагол извлечения --------------------------- #
def test_deceive_routes_to_social_check():
    s = _sess()
    act = s._keyword_intent("соврать трактирщику, что я важная шишка из Невервинтера")
    assert act is not None and act.verb == "deceive"


# --- диффузия слухов во времени --------------------------------------------- #
def test_diffusion_grows_knowledge_over_time():
    s = _sess()
    w = s.world
    before = len(w.kg.by_relation("knows"))
    for _ in range(30):
        s._tick(6)                              # каждые DIFFUSE_EVERY тиков — оборот слухов
    after = len(w.kg.by_relation("knows"))
    assert after > before                       # городские слухи расходятся → новых рёбер больше


def test_diffusion_is_replay_safe_via_save_load():
    from aidnd.runtime.persistence import delete_save, load_session, save_session
    s = _sess()
    for _ in range(6):
        s._tick(6)                              # порождаем learn_fact события в рантайм-хвосте
    h1 = s.world.state_hash()
    save_session(s, "difftest")
    try:
        s2 = load_session("difftest", use_model=False)
        assert s2.world.state_hash() == h1      # пре-ген + реплей хвоста = то же состояние
    finally:
        delete_save("difftest")


# --- LLM-обогащение: кеш по сиду (детерминизм без вызова модели) ------------- #
def test_llm_facts_loaded_from_cache(tmp_path, monkeypatch):
    import json
    import os

    from aidnd import config
    from aidnd.content.facts import build_fact_base
    from aidnd.world import World
    monkeypatch.setattr(config, "SAVE_DIR", str(tmp_path))
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(os.path.join(str(tmp_path), "facts_cache_777.json"), "w", encoding="utf-8") as fh:
        json.dump([{"text": "у мельника опять пропали мешки муки", "scope": "city",
                    "topic": "mill", "sensitivity": 0.05, "tags": ["мельник", "мука"]}], fh,
                  ensure_ascii=False)
    w = World(seed=777)
    build_fact_base(w, model=object())          # кеш есть → модель не дёргается
    assert any("мешки муки" in f.text for f in w.facts.values() if isinstance(f, Fact))
