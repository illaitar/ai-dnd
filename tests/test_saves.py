"""Новая игра (класс/снаряжение/сценарий) и сейв/лоад поверх event sourcing."""

from aidnd import config
from aidnd.bootstrap import new_session
from aidnd.runtime import persistence
from aidnd.world.components import Persona


def test_default_pc_is_fighter_at_inn():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    assert s.world.ecs.get("pc:hero", Persona).archetype == "fighter"
    assert "it:hero_sword" in s.world.items                      # стабильный id для тестов
    assert s.world.position("pc:hero").place_id == "building:stonehill_inn"


def test_new_game_rogue_escort_scenario():
    s = new_session(seed=1337, roster_size=2, use_model=False, scenario="escort",
                    pc_spec={"klass": "rogue", "kit": "blades", "name": "Тень"})
    p = s.world.ecs.get("pc:hero", Persona)
    assert p.archetype == "rogue" and p.name == "Тень"
    assert "it:hero_blade" in s.world.items                      # снаряжение плута
    assert s.world.position("pc:hero").place_id == "place:phandalin_wilds"
    assert "escort_active" in s.world.flags                      # флаг сценария
    assert s.world.position("npc:sildar_hallwinter").place_id == "place:phandalin_wilds"


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_DIR", str(tmp_path))
    s = new_session(seed=1337, roster_size=4, use_model=False)
    # детерминированный рантайм-хвост
    s.world.commit("set_position", "pc:hero", target="pc:hero",
                   payload={"region": "region:phandalin", "place": "place:phandalin_square"})
    s.world.commit("set_flag", "pc:hero", payload={"flag": "test_flag"})
    s.world.commit("interest", "pc:hero", payload={"place": "place:phandalin_square", "amount": 2})
    s._tick(5)
    s.journal.append("[00:50] проверка сейва")
    h_live = s.world.state_hash()

    card = persistence.save_session(s, "Проверка")
    loaded = persistence.load_session(card["slug"], use_model=False)

    assert loaded.world.state_hash() == h_live               # ядро мира восстановлено точно
    assert loaded.world.position("pc:hero").place_id == "place:phandalin_square"
    assert "test_flag" in loaded.world.flags
    assert loaded.world.importance.get("place:phandalin_square") == 2
    assert loaded.world.clock.tick == s.world.clock.tick     # час сохранён вне событий
    assert loaded.journal == s.journal


def test_list_and_delete_save(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_DIR", str(tmp_path))
    s = new_session(seed=1337, roster_size=2, use_model=False)
    card = persistence.save_session(s, "Слот 1")
    saves = persistence.list_saves()
    assert any(x["slug"] == card["slug"] for x in saves)
    assert persistence.delete_save(card["slug"]) is True
    assert all(x["slug"] != card["slug"] for x in persistence.list_saves())
