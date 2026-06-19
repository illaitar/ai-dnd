"""Подключение модельных ролей в игровой цикл (с детерминированными фоллбэками):
feasibility (выполнимость действия игрока), item_smith (свойства предмета), narrator
исходов (render_scene), quest_writer (квесты), reflection (синтез памяти NPC), а также
guard'ы офлайна. Модель эмулируется заглушкой/monkeypatch — проверяем именно ПРОВОДКУ."""

import aidnd.inference.agents as agents
from aidnd.bootstrap import new_session
from aidnd.gen.item_gen import _smith_for, spawn_item
from aidnd.inventory.container import Container


def _sess(seed=1337):
    return new_session(seed=seed, roster_size=4, use_model=False)


class _Off:               # «модель подключена», но сервер недоступен → реальные агенты в фоллбэк
    def available(self): return False


class _On:                # сервер доступен (внутренности агента замоканы поверх)
    def available(self): return True
    def model_for(self, role): return "test"


# --- feasibility: можно ли действие игрока в контексте --------------------- #
def test_feasibility_fallback_blocks_impossible_allows_mundane():
    s = _sess()
    assert s.feasibility("я взмываю в небо и парю над городом")["feasible"] is False
    assert s.feasibility("я насвистываю весёлый мотив")["feasible"] is True


def test_feasibility_uses_model_when_available(monkeypatch):
    s = _sess(); s.model = _Off()
    monkeypatch.setattr(agents, "assess_feasibility",
                        lambda m, a, c: {"plausibility": 0.04, "drivers": [], "verdict_note": "немыслимо"})
    fz = s.feasibility("одним взглядом обращаю стражу в камень")
    assert fz["feasible"] is False and fz["p"] == 0.04 and fz["reason"] == "немыслимо"


def test_freeform_action_refused_when_infeasible():
    s = _sess()
    r = s.handle("телепортируюсь прямиком в логово")
    assert "качает головой" in r["text"] and r["feasibility"]["feasible"] is False


# --- item_smith: имя/описание экземпляра предмета -------------------------- #
def test_item_smith_sets_name_and_description():
    s = _sess()
    tid = next(iter(s.world.templates))
    s.world.containers["container:test"] = Container(container_id="container:test",
                                                     owner_ref=None, kind="chest", items=[])
    iid = spawn_item(s.world, tid, "container:test",
                     smith=lambda t: {"name": "Клинок Зари", "description": "светится на рассвете"})
    inst = s.world.items[iid]
    assert inst.custom_name == "Клинок Зари" and inst.description == "светится на рассвете"


def test_smith_for_is_none_offline_and_builds_with_model(monkeypatch):
    assert _smith_for(None, "ctx") is None
    monkeypatch.setattr(agents, "forge_item",
                        lambda m, name, cat, rar, ctx: {"name": "Перо Феникса"})
    smith = _smith_for(_On(), "из тайника")
    assert smith is not None
    tmpl = type("T", (), {"name": "feather", "category": "magic", "rarity": "rare"})()
    assert smith(tmpl)["name"] == "Перо Феникса"


# --- narrator исходов (render_scene в рантайме) ---------------------------- #
def test_outcome_narrator_offline_returns_none_online_renders(monkeypatch):
    s = _sess()
    assert s._narrate_outcome("Удар мечом: 7 рубящего урона.") is None     # офлайн → механика
    s.model = _Off()
    monkeypatch.setattr(agents, "render_scene",
                        lambda m, summ, persona, topic="": {"narration": "Клинок поёт, рассекая тьму."})
    assert s._narrate_outcome("Удар мечом: 7 рубящего урона.", topic="combat") == "Клинок поёт, рассекая тьму."


# --- quest_writer: побочные квесты ---------------------------------------- #
def test_quest_writer_fallback_registers_quest():
    s = _sess()
    q = s.director.generate_side_quest("npc:harbin_wester", "place:wyvern_tor",
                                       "Орки у Тора", "Разберись с орочьим лагерем")
    assert q is not None and q.quest_id in s.world.quests
    assert q.giver_lines and q.framing


def test_quest_writer_uses_model(monkeypatch):
    s = _sess(); s.director.model = _Off()
    monkeypatch.setattr(agents, "write_quest", lambda *a: {
        "title": "Тень над Тором", "framing": "Над холмами сгущается беда.",
        "giver_lines": ["Прошу, изгони орков с Вайверн-Тор."], "objective_text": "Очисти Тор"})
    q = s.director.generate_side_quest("npc:harbin_wester", "place:wyvern_tor",
                                       "Орки у Тора", "Очисти Тор")
    assert "сгущается" in q.framing and q.giver_lines


# --- reflection: NPC синтезирует опыт ------------------------------------- #
def test_reflection_triggers_with_accumulated_experience():
    s = _sess()
    npc = "npc:toblen_stonehill"
    for i in range(3):
        s.cognition.observe(npc, f"наблюдение {i}", importance=4)
    assert s.cognition.maybe_reflect(npc, every=4) == []          # 3 наблюдения — рано
    s.cognition.observe(npc, "наблюдение 4", importance=4)
    out = s.cognition.maybe_reflect(npc, every=4)                 # кратно 4 → рефлексия
    assert out and out[0].get("statement")


# --- combat tactician: guard + проводка ----------------------------------- #
def test_choose_tactic_offline_guard_and_engine_wiring():
    assert agents.choose_tactic(None, "digest", "npc:x") is None     # нет сервера → None
    s = _sess()
    from aidnd.combat.engine import CombatEngine
    eng = CombatEngine(s.world, s.dice, s.model, s.cognition, s.lod)
    assert hasattr(eng, "_model_tactic") and hasattr(eng, "_tactic_digest")
    assert eng.model is s.model                                     # модель прокинута в бой
