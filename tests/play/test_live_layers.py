"""LOD layers for the live tick — how many NPCs think (LLM) per tick, and fair rotation.

Salient NPCs always think; the low-impulse background crowd is staggered round-robin.
"""

from aidnd.server.play.engine.world import _active_budget, _select_actors


def test_budget_scales_with_crowd():
    assert _active_budget(1) == 1
    assert _active_budget(3) == 3          # small scene — everyone
    assert _active_budget(10) == 5         # crowd — half
    assert _active_budget(20) == 6         # capped for latency
    assert _active_budget(5) == 3          # ceil(2.5)


def test_small_crowd_everyone_thinks():
    imp = {f"n{i}": (0.35, "фон") for i in range(3)}
    ranked = list(imp)
    assert set(_select_actors(ranked, imp, {})) == set(ranked)


def test_salient_always_think_even_in_a_crowd():
    imp = {f"n{i}": (0.35, "фон") for i in range(10)}
    imp["n0"] = (4.0, "долг ответа")       # answering the player
    imp["n1"] = (3.5, "событие")           # reacting to an event
    ranked = sorted(imp, key=lambda p: -imp[p][0])
    actors = _select_actors(ranked, imp, {})
    assert "n0" in actors and "n1" in actors
    assert len(actors) == 5                # budget for 10 present


def test_background_crowd_rotates_across_ticks():
    imp = {f"n{i}": (0.35, "фон") for i in range(10)}   # all background, none salient
    ranked = sorted(imp, key=str)
    lv: dict = {}
    a1 = set(_select_actors(ranked, imp, lv))
    a2 = set(_select_actors(ranked, imp, lv))
    assert len(a1) == 5 and len(a2) == 5
    assert a1 != a2                        # a different subset thinks next tick
    assert a1 | a2 == set(imp)             # two ticks cover the whole crowd — nobody starves


def test_high_need_is_not_salient_only_budget_many_think():
    # REASON-based salience: «нужда» with a HIGH impulse (2.1) is NOT a must — it joins the
    # rotating background. Only budget-many of the 20 are picked; a «долг ответа» always is.
    imp = {f"n{i}": (2.1, "нужда") for i in range(20)}
    imp["deb"] = (4.0, "долг ответа")
    ranked = sorted(imp, key=lambda p: -imp[p][0])
    lv: dict = {}
    actors = _select_actors(ranked, imp, lv)
    assert "deb" in actors                       # owed answer — always thinks
    assert len(actors) == _active_budget(21)     # 6 — budget, not "all needy think"
    assert lv["rot_cursor"] > 0                  # background rotation advanced
    a2 = set(_select_actors(ranked, imp, lv))
    assert set(actors) != a2                      # next tick rotates a different needy subset


def test_salient_flood_bypasses_the_cap():
    # a brawl: everyone has a real reason — all think, budget does not gate real behavior
    imp = {f"n{i}": (3.5, "событие") for i in range(10)}
    ranked = list(imp)
    assert set(_select_actors(ranked, imp, {})) == set(imp)
