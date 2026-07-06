"""Кейсы скелета подземелий: детерминизм, гарантии проходимости, циклы, честные тупики."""

import json

from aidnd.worldgen.dungeongen import _solvable, generate


def test_deterministic():
    a, b = generate("t|1", "Ruin"), generate("t|1", "Ruin")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_batch_guarantees():
    for i in range(30):
        d = generate(f"t|{i}", ["Ruin", "Caverns", "Forest"][i % 3])
        # цель достижима С учётом ключей и БЕЗ секреток (критпуть чист)
        assert _solvable(d["rooms"], d["edges"], d["keys"], d["entrance"], d["goal"], False)
        # jaquays: минимум два независимых цикла, тупики только с наградой
        assert d["metrics"]["cyclomatic"] >= 2
        assert not d["metrics"]["bad_deadends"]
        # каждый замок имеет ключ где-то в данже
        locks = {e["lock"] for e in d["edges"] if e["kind"] == "locked"}
        assert locks <= {k["id"] for k in d["keys"]} | {None}


def test_key_before_lock():
    """Ключ обязан лежать в области, достижимой БЕЗ прохода замка (Ashmore/Nitsche)."""
    seen_lock = False
    for i in range(40):
        d = generate(f"kl|{i}", "Ruin")
        locked = [e for e in d["edges"] if e["kind"] == "locked"]
        if not locked:
            continue
        seen_lock = True
        for e in locked:
            edges_wo = [x for x in d["edges"] if x is not e]
            key_rooms = [k["room"] for k in d["keys"] if k["id"] == e["lock"]]
            assert key_rooms, f"замок {e['lock']} без ключа"
            ok = any(_solvable(d["rooms"], edges_wo, [], d["entrance"], kr, True)
                     for kr in key_rooms)
            assert ok, f"ключ {e['lock']} заперт за собственным замком (сид kl|{i})"
    assert seen_lock, "за 40 сидов ни одного замка — словарь циклов не работает"


def test_cave_env_gives_caves():
    caves = sum(1 for i in range(10)
                for r in generate(f"cv|{i}", "Caverns")["rooms"]
                if len(r["tiles"]) not in
                (len(r["tiles"][0]) * 0,) and _is_ragged(r))
    assert caves >= 3


def _is_ragged(r) -> bool:
    xs = [t[0] for t in r["tiles"]]
    ys = [t[1] for t in r["tiles"]]
    return len(r["tiles"]) < (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)


def test_stock_quotas_and_boss():
    import collections

    kinds = collections.Counter()
    for i in range(20):
        d = generate(f"sq|{i}", "Ruin", cr=2.0)
        boss = next(r for r in d["rooms"] if r["kind"] == "goal")
        assert boss["content"]["boss"] and boss["content"]["units"]
        assert boss["content"]["treasure"]["guarded"]
        for r in d["rooms"]:
            kinds[(r.get("content") or {}).get("kind", "?")] += 1
            if (r.get("content") or {}).get("kind") == "trap":
                assert r["content"]["trap"]["telegraph"]  # ловушка всегда телеграфирует
    total = sum(kinds.values())
    assert 0.25 < kinds["monster"] / total < 0.45      # квоты B/X дышат, но держатся
    assert 0.2 < kinds["empty"] / total < 0.45


def test_brief_applies_without_dangling_clues():
    import random as _r

    from aidnd.worldgen.dungeonlore import apply_brief

    brief = {"name": "Тест-склеп", "history": {"built": "x", "happened": "y", "now": "z"},
             "bits": [{"id": "b1", "text": "след"}], "chief": "Вожак",
             "rooms": [{"arch": a, "name": f"к-{a}", "desc": "d", "clue": "b1"}
                       for a in ("entrance", "hall", "cave", "chief", "store", "post",
                                 "danger", "treasure", "secret")]}
    d = generate("bf|1", "Caverns", cr=1.0)
    apply_brief(d, brief, _r.Random(1))
    named = [r for r in d["rooms"] if r.get("name")]
    assert len(named) == len(d["rooms"])               # все комнаты получили виньетку
    assert d["name"] == "Тест-склеп"
    assert all(r.get("clue") == "b1" for r in named)
