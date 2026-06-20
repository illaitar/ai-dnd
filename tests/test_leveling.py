"""Опыт, повышение уровня, выборы 5e и заклинательство (старт с 1 уровня)."""

from aidnd import config
from aidnd.bootstrap import new_session
from aidnd.runtime import persistence
from aidnd.world.components import Progression


def _pc(s):
    return s.world.ecs.get("pc:hero", Progression), s.world.get_stats("pc:hero")


def test_starts_at_level_1():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    prog, st = _pc(s)
    assert st.level == 1 and prog.class_id == "fighter" and prog.xp == 0
    assert st.max_hp == 12                       # d10 + Телосложение 14 (+2)


def test_xp_marks_pending_level():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    s.world.commit("gain_xp", "pc:hero", payload={"xp": 300})
    prog, _ = _pc(s)
    assert prog.pending == 1
    pend = s.pending_levelup()
    assert pend and pend["to"] == 2


def test_fighter_levelup_path_to_4():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    s.world.commit("gain_xp", "pc:hero", payload={"xp": 2700})   # → 4 уровень
    prog, _ = _pc(s)
    assert prog.pending == 3
    assert s.apply_levelup({}).get("kind") != "error"             # L2 без выбора
    assert s.apply_levelup({"subclass": "champion"}).get("kind") != "error"  # L3 подкласс
    assert s.apply_levelup({"asi": "asi:str"}).get("kind") != "error"        # L4 ASI
    prog, st = _pc(s)
    assert st.level == 4 and prog.subclass == "champion"
    assert st.str_ == 18 and prog.pending == 0                    # +2 Сила


def test_levelup_validation_blocks_missing_choice():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    s.world.commit("gain_xp", "pc:hero", payload={"xp": 900})     # → 3 уровень
    s.apply_levelup({})                                           # L2 ок
    assert s.apply_levelup({}).get("kind") == "error"            # L3 без подкласса — ошибка


def test_cleric_caster_setup_and_slots():
    s = new_session(seed=1337, roster_size=2, use_model=False, pc_spec={"klass": "cleric"})
    prog, st = _pc(s)
    assert st.spell_ability == "wis" and st.spell_slots.get("1") == 2
    assert len(prog.cantrips) == 3 and prog.spells_known
    s.world.commit("gain_xp", "pc:hero", payload={"xp": 900})     # → 3 уровень
    for _ in range(2):                                            # L2, L3 — каждый требует выбор заклинаний
        pend = s.pending_levelup()
        ch = next((c for c in pend["choices"] if c["id"] == "spells"), None)
        sel = {"spells": [ch["options"][0]["id"]]} if ch else {}
        assert s.apply_levelup(sel).get("kind") != "error"
    _, st = _pc(s)
    assert st.level == 3 and st.spell_slots.get("2") == 2         # ячейки 2 круга на 3 уровне


def test_levelup_survives_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_DIR", str(tmp_path))
    s = new_session(seed=1337, roster_size=2, use_model=False)
    s.world.commit("gain_xp", "pc:hero", payload={"xp": 300})
    s.apply_levelup({})                                           # → 2 уровень (событие в хвосте)
    card = persistence.save_session(s, "lvl")
    loaded = persistence.load_session(card["slug"], use_model=False)
    _, st = _pc(loaded)
    assert st.level == 2                                          # level_up реплеится при загрузке
