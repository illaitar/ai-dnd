"""Стойкие изменения предметов: любое freeform-изменение сохраняется на конкретном
экземпляре и видно при осмотре — в том числе после сейв/лоада (док 03/06)."""

from aidnd import config, ids
from aidnd.bootstrap import new_session
from aidnd.gen.item_gen import spawn_item
from aidnd.runtime.persistence import delete_save, load_session, save_session


def _carry(s):
    return s.world.containers[f"carry:{ids.name_of(s.player)}"].items


def _alterations(s, iid):
    return (s.world.items[iid].mods or {}).get("alterations") or []


def _do(s, phrase):
    out = s.handle(phrase)
    if out.get("kind") == "roll_request":          # офлайн часто просит бросок — кидаем удачно
        out = s.submit_roll([20])
    return out


def test_engraving_persists_and_shows_on_examine():
    s = new_session(seed=config.WORLD_SEED, roster_size=2, use_model=False)
    dagger = spawn_item(s.world, "tmpl:dagger", f"carry:{ids.name_of(s.player)}",
                        owner=s.player, instance_id="it:test_dagger")
    # сценарий: точильным камнем гравируем «тест» на клинке кинжала
    _do(s, "я делаю гравировку «тест» на клинке кинжала точильным камнем")
    assert any("тест" in a for a in _alterations(s, dagger)), _alterations(s, dagger)
    # позже достаём кинжал и осматриваем — гравировка на месте
    look = s.handle("я достаю кинжал из сумки и осматриваю его")
    assert "тест" in (look.get("text") or ""), look.get("text")


def test_any_modification_is_remembered_not_only_engraving():
    s = new_session(seed=config.WORLD_SEED, roster_size=2, use_model=False)
    spawn_item(s.world, "tmpl:dagger", f"carry:{ids.name_of(s.player)}",
               owner=s.player, instance_id="it:test_dagger")
    _do(s, "я повязываю красную ленту на рукоять кинжала")
    look = s.handle("осмотреть кинжал")
    assert "лент" in (look.get("text") or "").lower(), look.get("text")


def test_alteration_survives_save_load():
    s = new_session(seed=config.WORLD_SEED, roster_size=2, use_model=False)
    # гравируем СТАРТОВЫЙ предмет (он в пре-гене → переживает реплей при загрузке)
    sword = next(i for i in _carry(s) if s.world.items[i].template_id == "tmpl:longsword")
    _do(s, "я выцарапываю на мече надпись «Уголёк»")
    assert any("Уголёк" in a for a in _alterations(s, sword)), _alterations(s, sword)
    slug = save_session(s, "alt-test-tmp")["slug"]
    try:
        s2 = load_session(slug, use_model=False)
        sword2 = next(i for i in _carry(s2) if s2.world.items[i].template_id == "tmpl:longsword")
        assert any("Уголёк" in a for a in _alterations(s2, sword2)), "не пережило сейв/лоад"
        look = s2.handle("осмотреть меч")
        assert "Уголёк" in (look.get("text") or ""), look.get("text")
    finally:
        delete_save(slug)
