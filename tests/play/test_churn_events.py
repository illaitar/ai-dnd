"""Inc1 — scene churn as feed events. Pure-function unit tests over _salient / _churn_items:
salient joiners are NAMED (capped by churn_named_max), the rest collapse into one summary line per
direction; an empty diff yields no items. No LLM, no session mutation beyond a snapshot restore."""
from types import SimpleNamespace

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine.core import PLAYER
from aidnd.server.play.engine.world import _churn_items, _ru_count, _salient


def _npc(pid, name, role="горожанин", knows_player=False, hp=None):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    if knows_player:
        st.relationships[PLAYER] = {"trust": 0.2, "affinity": 0.3, "fear": 0.0}
    if hp is not None:
        st.hp = hp
    return SimpleNamespace(id=pid, name=name, role=role, state=st, work=None, home=None, persona={})


def _people(*npcs):
    return {n.id: n for n in npcs}


def test_salient_by_each_signal():
    ppl = _people(
        _npc("p_ac", "Мара", knows_player=True),          # acquaintance
        _npc("p_gv", "Роза", role="лавочник"),            # giver (via set)
        _npc("p_tg", "Тор", role="кузнец"),               # contract target (via set)
        _npc("p_guard", "Гром", role="стражник"),         # guard
        _npc("p_hurt", "Пал", hp=3),                      # wounded (hp<max, default max 10)
        _npc("p_bg", "Йорг"),                             # plain civilian
    )
    givers, targets = {"p_gv"}, {"p_tg"}
    assert _salient("p_ac", ppl, givers, targets)
    assert _salient("p_gv", ppl, givers, targets)
    assert _salient("p_tg", ppl, givers, targets)
    assert _salient("p_guard", ppl, givers, targets)
    assert _salient("p_hurt", ppl, givers, targets)
    assert not _salient("p_bg", ppl, givers, targets)


def test_empty_diff_no_items():
    who = frozenset({"a", "b"})
    assert _churn_items(who, who, _people(_npc("a", "A"), _npc("b", "B")), set(), set()) == []


def test_five_joins_two_salient_two_named_plus_summary():
    # 5 join, 2 salient (acquaintance + giver), 3 background → 2 named + 1 summary «вошли трое»
    ppl = _people(
        _npc("host", "Гром", role="трактирщик"),          # already present
        _npc("p_mara", "Мара", knows_player=True),
        _npc("p_roza", "Роза Медовар", role="лавочник"),
        _npc("p_yorg", "Йорг"), _npc("p_pal", "Пал"), _npc("p_tim", "Тим"),
    )
    prev = frozenset({"host"})
    here = frozenset({"host", "p_mara", "p_roza", "p_yorg", "p_pal", "p_tim"})
    items = _churn_items(prev, here, ppl, {"p_roza"}, set())
    named = [i for i in items if i.get("pid")]
    summary = [i for i in items if not i.get("pid")]
    assert {i["who"] for i in named} == {"Мара", "Роза Медовар"}   # 2 named (== churn_named_max)
    assert len(summary) == 1                                        # one arrival summary
    assert _ru_count(3) in summary[0]["text"]                       # «трое»
    assert all(i["k"] == "deed" for i in items)                    # feed-shape compat (scene_digest)


def test_leavers_symmetric_summary():
    ppl = _people(_npc("host", "Гром"), _npc("p_vit", "Витольд"), _npc("p_x", "Икс"))
    prev = frozenset({"host", "p_vit", "p_x"})
    here = frozenset({"host"})                                     # two left, neither salient
    items = _churn_items(prev, here, ppl, set(), set())
    assert len(items) == 1 and items[0].get("pid") is None
    assert _ru_count(2) in items[0]["text"]                        # «зал редеет — вышли двое»


def test_named_cap_folds_extra_salient_into_summary():
    # 3 salient joiners, churn_named_max=2 → 2 named + summary counting the 3rd
    ppl = _people(
        _npc("host", "Гром"),
        _npc("g1", "Роза", role="лавочник"), _npc("g2", "Тор", role="кузнец"),
        _npc("g3", "Влас", role="писарь"),
    )
    prev = frozenset({"host"})
    here = frozenset({"host", "g1", "g2", "g3"})
    items = _churn_items(prev, here, ppl, {"g1", "g2", "g3"}, set())
    named = [i for i in items if i.get("pid")]
    summary = [i for i in items if not i.get("pid")]
    assert len(named) == 2 and len(summary) == 1
