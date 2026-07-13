"""Твист: reveal_on → arc twisted, done_any ТОЛЬКО дополняется (инвариант add-or-never-replace)."""
import os
import tempfile

from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import twist as T
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _active_ct(st):
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "active",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "roles": {"giver": "npc:dunn", "villain": "npc:ralf"},
                      "arc": {"beat": "active"},
                      "done_any": [{"type": "have", "item": "гроссбух"}],
                      "seed": {"twist": {"fact": "d124: гильдия", "reveal_on": "visit:npc:ralf",
                                         "adds": {"type": "dead", "id": "npc:ralf"}}},
                      "framer": {"reveal": "Ральф сам должен гильдии — его можно прижать."}})


def test_visit_villain_fires_twist_appends_disjunct(monkeypatch):
    st = _store(monkeypatch)
    _active_ct(st)
    node_of = {"npc:ralf": 9, "npc:dunn": 7}.get
    txt = T.on_visit(9, node_of)                       # игрок пришёл в узел Ральфа
    assert txt and "гильдии" in txt
    ct = st.contracts(core._wid(), "active")[0]
    assert ct["arc"]["beat"] == "twisted"
    assert ct["done_any"] == [{"type": "have", "item": "гроссбух"},
                              {"type": "dead", "id": "npc:ralf"}]  # добавлено, не заменено
    assert ct["done_any"][0] == {"type": "have", "item": "гроссбух"}  # [0] неизменно


def test_twist_fires_once(monkeypatch):
    st = _store(monkeypatch)
    _active_ct(st)
    node_of = {"npc:ralf": 9}.get
    assert T.on_visit(9, node_of)
    assert T.on_visit(9, node_of) is None              # второй визит — уже twisted, молчит
    ct = st.contracts(core._wid(), "active")[0]
    assert len(ct["done_any"]) == 2                    # дизъюнкт не задублирован


def test_no_twist_when_not_at_villain(monkeypatch):
    st = _store(monkeypatch)
    _active_ct(st)
    assert T.on_visit(7, {"npc:ralf": 9}.get) is None  # игрок у Дунна, не у Ральфа


def test_no_twist_when_seed_carries_none(monkeypatch):
    st = _store(monkeypatch)
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "active",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "arc": {"beat": "active"},
                      "done_any": [{"type": "have", "item": "гроссбух"}],
                      "seed": {"twist": None}, "framer": {}})
    assert T.on_visit(9, {"npc:ralf": 9}.get) is None
    ct = st.contracts(core._wid(), "active")[0]
    assert ct["arc"]["beat"] == "active"
    assert len(ct["done_any"]) == 1


class _FakeRng:
    def __init__(self, val):
        self._val = val

    def random(self):
        return self._val


def test_gate_twist_pb_deterministic(monkeypatch):
    """PB['quest_twist_p'] gates planting at seed time — house-pattern deterministic RNG keyed by cid."""
    from aidnd.server.play.engine.quests import pipeline as P

    twist = {"fact": "d1: гильдия", "reveal_on": "visit:npc:ralf", "adds": {"type": "dead", "id": "npc:ralf"}}
    cid = "ct:sift:npc:dunn:100"

    seed_kept = {"twist": dict(twist)}
    monkeypatch.setattr(P.random, "Random", lambda key: _FakeRng(0.0))
    P._gate_twist(seed_kept, cid)
    assert seed_kept["twist"] == twist                 # roll below quest_twist_p (0.7) — kept

    seed_dropped = {"twist": dict(twist)}
    monkeypatch.setattr(P.random, "Random", lambda key: _FakeRng(0.99))
    P._gate_twist(seed_dropped, cid)
    assert seed_dropped["twist"] is None                # roll above quest_twist_p — dropped

    seed_none = {"twist": None}
    P._gate_twist(seed_none, cid)
    assert seed_none["twist"] is None                   # nothing to gate — stays None, no crash


def test_contract_on_move_fires_twist_via_crof(monkeypatch):
    """Wiring: _contract_on_move looks up the villain's node from _S['crof'] and fires the twist
    when no step-completion already fired (Inc-1's _sift_maybe_close guard runs first)."""
    import aidnd.server.play.mechanics.contracts as C
    st = _store(monkeypatch)
    _active_ct(st)
    monkeypatch.setattr(C, "_sift_maybe_close", lambda: None)  # isolate: only the twist wiring here
    core._S["crof"] = {"npc:ralf": 9, "npc:dunn": 7}
    try:
        assert C._contract_on_move(9) is None            # never closes — only widens
        ct = st.contracts(core._wid(), "active")[0]
        assert ct["arc"]["beat"] == "twisted"
        assert len(ct["done_any"]) == 2
    finally:
        core._S.pop("crof", None)
