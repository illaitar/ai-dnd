"""Стойкие последствия (агент последствий пишет их событием world_effect): след на
предмете/локации/персонаже виден при осмотре и переживает сейв/лоад. Здесь проверяем
ДЕТЕРМИНИРОВАННУЮ часть — хранение и поверхность, без обращения к модели."""

from aidnd import config, ids
from aidnd.bootstrap import new_session
from aidnd.gen.item_gen import spawn_item
from aidnd.runtime.persistence import delete_save, load_session, save_session
from aidnd.world.components import Persona


def _carry(s):
    return s.world.containers[f"carry:{ids.name_of(s.player)}"].items


def _effect(s, **payload):
    s.world.commit("world_effect", s.player, target=payload.get("target"), payload=payload)


def test_item_alteration_shows_on_examine():
    s = new_session(seed=config.WORLD_SEED, roster_size=2, use_model=False)
    dagger = spawn_item(s.world, "tmpl:dagger", f"carry:{ids.name_of(s.player)}",
                        owner=s.player, instance_id="it:test_dagger")
    _effect(s, kind="item", target=dagger, note="надпись «тест»")
    assert "тест" in (s.world.items[dagger].mods or {}).get("alterations", [None])[0]
    look = s.handle("осмотреть кинжал")
    assert "тест" in (look.get("text") or ""), look.get("text")


def test_place_and_npc_marks_surface():
    s = new_session(seed=config.WORLD_SEED, roster_size=2, use_model=False)
    place = s.current_place()
    _effect(s, kind="place", target=place, note="опрокинутый стол")
    assert "опрокинутый стол" in (s.look().get("text") or "")
    _effect(s, kind="npc", target="npc:toblen_stonehill", note="рассечённая бровь")
    assert "рассечённая бровь" in s._describe_npc("npc:toblen_stonehill")


def test_relation_and_condition_effects_apply():
    s = new_session(seed=config.WORLD_SEED, roster_size=2, use_model=False)
    from aidnd.cognition.relationships import edge
    _effect(s, kind="npc", target="npc:toblen_stonehill", fear=0.2)
    assert edge(s.world, "npc:toblen_stonehill", s.player).fear >= 0.2
    _effect(s, kind="self", target=s.player, condition="опьянение", minutes=30)
    assert any(c.name == "опьянение" for c in s.world.conditions.get(s.player, []))


def test_alteration_survives_save_load():
    s = new_session(seed=config.WORLD_SEED, roster_size=2, use_model=False)
    sword = next(i for i in _carry(s) if s.world.items[i].template_id == "tmpl:longsword")
    _effect(s, kind="item", target=sword, note="зарубка «Уголёк»")
    slug = save_session(s, "alt-test-tmp")["slug"]
    try:
        s2 = load_session(slug, use_model=False)
        sword2 = next(i for i in _carry(s2) if s2.world.items[i].template_id == "tmpl:longsword")
        assert any("Уголёк" in a for a in (s2.world.items[sword2].mods or {}).get("alterations", [])), \
            "след не пережил сейв/лоад"
    finally:
        delete_save(slug)


def test_persona_has_marks_field():
    s = new_session(seed=config.WORLD_SEED, roster_size=2, use_model=False)
    assert hasattr(s.world.ecs.get("npc:toblen_stonehill", Persona), "marks")
