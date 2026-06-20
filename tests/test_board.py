"""Доска объявлений: посты квестов, приём, требования (предмет/разговор), сдача."""

from aidnd import config
from aidnd.bootstrap import new_session
from aidnd.gen.item_gen import spawn_item
from aidnd.runtime import persistence
from aidnd.world.components import Progression

BOARD = "building:notice_board"


def _at_board(s):
    s.world.commit("set_position", "pc:hero", target="pc:hero",
                   payload={"region": "region:phandalin", "place": BOARD})


def test_board_place_exists_and_reachable():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    p = s.world.spatial.places.get(BOARD)
    assert p and "board" in p.affordances
    assert s.world.spatial.path_between("place:phandalin_square", BOARD)   # дойти можно


def test_board_quests_posted_and_view_gated():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    posted = [q for q in s.world.quests.values() if getattr(q, "kind", "") == "board"]
    assert len(posted) >= 3 and all(q.state == "offered" for q in posted)
    assert s.board_view() is None                          # не у доски — не видно
    _at_board(s)
    bv = s.board_view()
    assert bv and len(bv["quests"]) >= 3                   # у доски — список заданий


def test_item_quest_accept_objective_turnin_reward():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    _at_board(s)
    s.accept_quest("quest:board_torch")
    q = s.world.quests["quest:board_torch"]
    assert q.state == "active" and "do" in q.current_stages
    # раздобыли факел (как в игре — предмет попадает в сумку событием перемещения)
    spawn_item(s.world, "tmpl:torch", "container:klarg_chest", source="test", instance_id="it:test_torch")
    s.world.commit("item_move", "pc:hero",
                   payload={"from": "container:klarg_chest", "to": "carry:hero", "instance": "it:test_torch"})
    assert "turnin" in q.current_stages                    # стадия продвинулась на событии
    xp_before = s.world.ecs.get("pc:hero", Progression).xp
    s.turn_in_quest("quest:board_torch")
    assert q.state == "completed"
    assert s.world.ecs.get("pc:hero", Progression).xp == xp_before + 50   # награда выдана


def test_talk_quest_requirement():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    _at_board(s)
    s.accept_quest("quest:board_garaele")
    q = s.world.quests["quest:board_garaele"]
    s.world.commit("set_flag", "pc:hero", payload={"flag": "talked:npc:sister_garaele"})  # «поговорил»
    assert "turnin" in q.current_stages
    s.turn_in_quest("quest:board_garaele")
    assert q.state == "completed"


def test_turn_in_requires_being_at_board():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    _at_board(s)
    s.accept_quest("quest:board_torch")
    spawn_item(s.world, "tmpl:torch", "carry:hero", owner="pc:hero",
               source="test", instance_id="it:test_torch2")
    s.world.commit("set_position", "pc:hero", target="pc:hero",
                   payload={"region": "region:phandalin", "place": "place:phandalin_square"})
    r = s.turn_in_quest("quest:board_torch")               # не у доски
    assert r["kind"] == "system" and "доск" in r["text"].lower()
    assert s.world.quests["quest:board_torch"].state == "active"


def test_accepted_board_quest_survives_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_DIR", str(tmp_path))
    s = new_session(seed=1337, roster_size=2, use_model=False)
    _at_board(s)
    s.accept_quest("quest:board_klarg")
    card = persistence.save_session(s, "board")
    loaded = persistence.load_session(card["slug"], use_model=False)
    assert loaded.world.quests["quest:board_klarg"].state == "active"   # приём реплеится
