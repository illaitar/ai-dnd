"""Экран инвентаря/экипировки и выборы 1 уровня в создании персонажа."""

from aidnd.bootstrap import new_session
from aidnd.world.components import Progression


def test_inventory_view_lists_equipped_and_carry():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    inv = s.inventory_view()
    assert inv["slots"]["броня"] and inv["slots"]["основная рука"]   # воин одет по умолчанию
    ids = {it["id"] for it in inv["items"]}
    assert "it:hero_potions" in ids                                  # зелья в сумке
    assert any(it["usable"] for it in inv["items"])                  # зелье — используемое


def test_unequip_lowers_ac_and_equip_restores():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    ac0 = s.inventory_view()["ac"]
    s.unequip_item("it:hero_armor")
    assert s.inventory_view()["ac"] < ac0                            # без брони КД ниже
    s.equip_item("it:hero_armor")
    assert s.inventory_view()["ac"] == ac0                           # надели обратно — вернулось


def test_use_potion_heals_and_consumes():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    st = s.world.get_stats("pc:hero")
    s.world.commit("damage", "pc:hero", target="pc:hero", payload={"amount": 6})
    hp0, qty0 = st.hp, s.world.items["it:hero_potions"].quantity
    s.use_item("it:hero_potions")
    assert st.hp > hp0                                               # вылечились
    assert s.world.items["it:hero_potions"].quantity == qty0 - 1     # одно зелье израсходовано


def test_creation_l1_fighter_style():
    s = new_session(seed=1337, roster_size=2, use_model=False,
                    pc_spec={"klass": "fighter", "l1": {"fighting_style": "dueling"}})
    assert s.world.ecs.get("pc:hero", Progression).fighting_style == "dueling"


def test_creation_l1_cleric_domain_and_invalid_fallback():
    s = new_session(seed=1337, roster_size=2, use_model=False,
                    pc_spec={"klass": "cleric", "l1": {"subclass": "light"}})
    assert s.world.ecs.get("pc:hero", Progression).subclass == "light"
    bad = new_session(seed=1337, roster_size=2, use_model=False,
                      pc_spec={"klass": "fighter", "l1": {"fighting_style": "bogus"}})
    assert bad.world.ecs.get("pc:hero", Progression).fighting_style == "defense"   # невалид → дефолт


def test_creation_l1_rogue_expertise_from_chosen_skills():
    s = new_session(seed=1337, roster_size=2, use_model=False,
                    pc_spec={"klass": "rogue",
                             "skills": ["stealth", "perception", "acrobatics", "deception"],
                             "l1": {"expertise": ["stealth", "perception"]}})
    prog = s.world.ecs.get("pc:hero", Progression)
    assert set(prog.expertise) == {"stealth", "perception"}
