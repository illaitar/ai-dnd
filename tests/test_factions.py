"""Фракции: пер-мирная генерация, склонность, вступление/смена, репутация, обвязки."""

from aidnd import config
from aidnd.bootstrap import new_session
from aidnd.inventory import container as inv
from aidnd.rules.factions import social_reaction
from aidnd.runtime import persistence
from aidnd.world.components import Affiliation, Faction


def test_civic_factions_generated_deterministic():
    a = new_session(seed=1337, roster_size=2, use_model=False)
    b = new_session(seed=1337, roster_size=2, use_model=False)
    assert sorted(a.world.factions) == sorted(b.world.factions)        # детерминизм по сиду
    assert "faction:merchant_guild" in a.world.factions               # ядро всегда есть
    assert "faction:watch" in a.world.factions
    assert len([f for f in a.world.factions if not f.startswith("faction:red")]) >= 4


def test_pc_class_affinity():
    s = new_session(seed=1337, roster_size=2, use_model=False, pc_spec={"klass": "rogue"})
    aff = s.world.ecs.get("pc:hero", Affiliation)
    assert aff.affinity.get("faction:thieves_guild", 0) > 0            # плут тянется к ворам


def test_join_requires_reputation_then_succeeds():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    r = s.join_faction("faction:watch")
    assert r["kind"] == "system" and "репутац" in r["text"].lower()    # порог не достигнут
    s.world.commit("faction_rep", "pc:hero", payload={"faction": "faction:watch", "delta": 0.4})
    s.join_faction("faction:watch")
    aff = s.world.ecs.get("pc:hero", Affiliation)
    assert aff.membership == "faction:watch"
    assert "pc:hero" in s.world.ecs.get("faction:watch", Faction).members


def test_switch_faction_penalizes_rival():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    # искусственно сделаем стражу врагом гильдии торговцев
    s.world.commit("faction_relation", "dm",
                   payload={"a": "faction:merchant_guild", "b": "faction:watch", "value": -0.5})
    s.world.commit("faction_rep", "pc:hero", payload={"faction": "faction:watch", "delta": 0.4})
    s.join_faction("faction:watch")
    s.world.commit("faction_rep", "pc:hero", payload={"faction": "faction:merchant_guild", "delta": 0.4})
    before = s.world.reputation.get("faction:watch", 0.0)
    s.join_faction("faction:merchant_guild")                            # смена фракции
    aff = s.world.ecs.get("pc:hero", Affiliation)
    assert aff.membership == "faction:merchant_guild"
    assert s.world.reputation.get("faction:watch", 0.0) < before        # соперник недоволен


def test_reputation_clamped():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    for _ in range(20):
        s.world.commit("faction_rep", "pc:hero", payload={"faction": "faction:watch", "delta": 0.2})
    assert s.world.reputation["faction:watch"] == 1.0                   # зажато сверху


def test_social_reaction_sign():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    # член гильдии торговцев (linene) — найдём его фракцию
    fac = s.world.ecs.get("npc:linene_graywind", Faction)  # noqa: F841 (just ensure import ok)
    base = social_reaction(s.world, "pc:hero", "npc:linene_graywind")
    s.world.commit("faction_rep", "pc:hero", payload={"faction": "faction:merchant_guild", "delta": 0.4})
    s.world.commit("faction_join", "pc:hero", payload={"faction": "faction:merchant_guild"})
    joined = social_reaction(s.world, "pc:hero", "npc:linene_graywind")
    assert joined > base                                                # свои относятся теплее


def test_faction_discount_at_shop():
    s = new_session(seed=1337, roster_size=4, use_model=False)
    shop = s.world.containers["shop:lionshield"]
    iid = shop.items[0]
    base = inv.price_of(s.world, s.world.items[iid], shop, "pc:hero")
    s.world.commit("faction_rep", "pc:hero", payload={"faction": "faction:merchant_guild", "delta": 0.6})
    s.world.commit("faction_join", "pc:hero", payload={"faction": "faction:merchant_guild"})
    discounted = inv.price_of(s.world, s.world.items[iid], shop, "pc:hero")
    assert discounted < base                                            # член гильдии — дешевле


def test_inspect_marks_enriched_offline():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    assert not s.world.ecs.get("faction:watch", Faction).enriched
    s.inspect_faction("faction:watch")
    assert s.world.ecs.get("faction:watch", Faction).enriched          # офлайн → дефолты, помечено


def test_membership_and_rep_survive_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_DIR", str(tmp_path))
    s = new_session(seed=1337, roster_size=2, use_model=False)
    s.world.commit("faction_rep", "pc:hero", payload={"faction": "faction:watch", "delta": 0.5})
    s.join_faction("faction:watch")
    card = persistence.save_session(s, "fac")
    loaded = persistence.load_session(card["slug"], use_model=False)
    assert loaded.world.ecs.get("pc:hero", Affiliation).membership == "faction:watch"
    assert round(loaded.world.reputation.get("faction:watch", 0), 2) == round(
        s.world.reputation.get("faction:watch", 0), 2)
