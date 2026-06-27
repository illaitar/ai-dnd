"""Тактический бой и реактивное продвижение квестов (док 09-10, док 05 §8)."""

from aidnd.bootstrap import new_session
from aidnd.rules.dice import validate_player_roll


def _drive_pc_turn(eng, faces_atk=18, faces_dmg=6):
    """Ход PC: при нужде сблизиться по сетке, затем атаковать (фикс. грани)."""
    tgt = eng._choose_target("pc:hero")
    if tgt and not eng.in_attack_range("pc:hero", tgt):
        reach = eng.reachable_cells()
        if reach:
            best = min(reach, key=lambda c: eng.state.grid.distance_squares(
                c, eng.state.combatants[tgt].pos))
            eng.move_to(best)
    if tgt and eng.in_attack_range("pc:hero", tgt) and eng.state.turn_budget.action:
        req = eng.pc_declare_attack(tgt)
        if hasattr(req, "request_id"):
            out = eng.submit_roll(validate_player_roll(req, [faces_atk]))
            while not out["done"]:
                q = out["next_request"]
                out = eng.submit_roll(validate_player_roll(q, [faces_dmg]))
    eng.end_turn()


def _run_fight(seed):
    s = new_session(seed=seed, roster_size=4, use_model=False)
    s.handle("идти в логово")
    s.handle("идти в пещеру")
    s.handle("атаковать Klarg")
    eng = s.combat
    guard = 0
    while eng.state.mode == "active" and guard < 150:
        guard += 1
        if eng.is_pc_turn():
            _drive_pc_turn(eng)
        else:
            eng.auto_turn()
    return s










def test_quest_advances_on_klarg_death():
    # основной сюжет теперь генерируется (gen.campaign); веха «Крэгмо» сохраняет милстоун-флаг
    s = new_session(seed=1337, roster_size=4, use_model=False)
    assert "cragmaw_cleared" not in s.world.flags
    st = s.world.get_stats("npc:klarg")
    s.world.commit("damage", "pc:hero", target="npc:klarg", payload={"amount": st.hp})
    assert "cragmaw_cleared" in s.world.flags          # смерть Кларга → веха срабатывает


