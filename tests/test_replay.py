"""Golden replay: детерминизм event sourcing (док 08 §5, §12).

Пре-ген восстанавливается из сида; рантайм-хвост реплеится из лога. Replay
подставляет залогированные значения (RollRecord), не пересевает. Идентичность
состояния по state_hash ловит регрессии движка.
"""

from aidnd.content import build_world


def _scripted_runtime(world):
    """Полностью event-sourced сценарий (без боя): перемещение, лут, валюта, KG."""
    # игрок идёт в пещеру
    world.commit("set_position", "pc:hero", target="pc:hero",
                 payload={"region": "region:phandalin", "place": "place:cragmaw_klarg_cave",
                          "cell": [2, 2]})
    # лутает сундук Klarg: переносит ящик и зелья в инвентарь, монеты в кошелёк
    chest = world.containers["container:klarg_chest"]
    for iid in list(chest.items):
        inst = world.items[iid]
        if inst.template_id in ("tmpl:cp", "tmpl:sp", "tmpl:gp"):
            coin = inst.template_id.split(":")[1]
            world.commit("currency_transfer", "pc:hero",
                         payload={"from": None, "to": "pc:hero", "coins": {coin: inst.quantity}})
            world.commit("item_remove", "pc:hero",
                         payload={"container": "container:klarg_chest", "instance": iid, "destroy": True})
        else:
            world.commit("item_move", "pc:hero",
                         payload={"from": "container:klarg_chest", "to": "carry:hero",
                                  "instance": iid})
    # возвращается в город
    world.commit("set_position", "pc:hero", target="pc:hero",
                 payload={"region": "region:phandalin", "place": "place:phandalin_square",
                          "cell": [0, 0]})
    world.commit("set_flag", "pc:hero", payload={"flag": "visited_cragmaw"})


def test_golden_replay_matches():
    # 1) построить мир, выполнить сценарий
    w1 = build_world(seed=4242, roster_size=6)
    baseline = w1.log.count()
    _scripted_runtime(w1)
    h1 = w1.state_hash()
    runtime_events = w1.log.after(baseline - 1)  # хвост после пре-гена

    # 2) пересобрать пре-ген из того же сида и реплеить хвост
    w2 = build_world(seed=4242, roster_size=6)
    for ev in runtime_events:
        w2.apply(ev)
    h2 = w2.state_hash()

    assert h1 == h2, "реплей рантайм-хвоста поверх пре-гена должен дать то же состояние"


def test_replay_preserves_logged_roll_faces():
    from aidnd.world.events import RollRecord
    w = build_world(seed=1, roster_size=2)
    rec = RollRecord("rq1", "1d20", raw=[18], total=23, nat=18, source="player_ui")
    ev = w.commit("attack", "pc:hero", target="npc:klarg", roll=rec)
    # сериализация/десериализация события сохраняет грани
    from aidnd.world.events import Event
    restored = Event.from_dict(ev.to_dict())
    assert restored.roll.raw == [18] and restored.roll.source == "player_ui"
