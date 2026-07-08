"""Tests for the non-human race seeder (deterministic, idempotent pool-modifying step)."""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from aidnd.worldgen.seed_races import seed_races

from aidnd.worldgen import WorldStore

NON_HUMAN = {"орк", "дворф", "эльф"}
_RACE_RELATIONS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "aidnd", "content", "race_relations.json")


def _fresh_store() -> WorldStore:
    return WorldStore(os.path.join(tempfile.mkdtemp(), "worlds.db"))


def _seed_humans(store: WorldStore, n: int = 20) -> None:
    for i in range(n):
        pid = f"pool:{i:04d}"
        mech = {"role": "гвардеец", "traits": [], "abilities": {}}
        persona = {"sex": "m", "age": "adult", "race": "человек", "look": {}}
        store.save_person(pid, "гвардеец", f"Иван {i}", 0.5, 0.5, mech, persona, {}, seed=1)


@pytest.fixture
def populated_store():
    store = _fresh_store()
    _seed_humans(store, 20)
    return store


def test_race_relations_content_sane():
    # Sanity: race values used by the seeder must match keys used by race_relations.json.
    with open(_RACE_RELATIONS_PATH, encoding="utf-8") as f:
        race_relations = json.load(f)
    known = set(race_relations) | {race for d in race_relations.values() for race in d}
    assert NON_HUMAN <= known


def test_seed_races_produces_non_human(populated_store):
    seed_races(populated_store, fraction=0.1)
    people = populated_store.list_people(limit=1000)
    races = [p["persona"].get("race") for p in people]
    non_human = [r for r in races if r in NON_HUMAN]
    assert len(non_human) >= 1


def test_seed_races_fraction_tolerance(populated_store):
    seed_races(populated_store, fraction=0.1)
    people = populated_store.list_people(limit=1000)
    races = [p["persona"].get("race") for p in people]
    non_human_frac = sum(1 for r in races if r in NON_HUMAN) / len(races)
    # tolerance: within a wide band given only 20 rows
    assert 0.0 < non_human_frac <= 0.35


def test_seed_races_does_not_disturb_mech():
    store = _fresh_store()
    _seed_humans(store, 20)
    before = {p["id"]: p["mech"] for p in store.list_people(limit=1000)}
    seed_races(store, fraction=0.1)
    after = {p["id"]: p["mech"] for p in store.list_people(limit=1000)}
    assert before == after


def test_seed_races_deterministic():
    store_a = _fresh_store()
    _seed_humans(store_a, 20)
    seed_races(store_a, fraction=0.1)

    store_b = _fresh_store()
    _seed_humans(store_b, 20)
    seed_races(store_b, fraction=0.1)

    races_a = {p["id"]: p["persona"].get("race") for p in store_a.list_people(limit=1000)}
    races_b = {p["id"]: p["persona"].get("race") for p in store_b.list_people(limit=1000)}
    assert races_a == races_b


def test_seed_races_idempotent(populated_store):
    n1 = seed_races(populated_store, fraction=0.1)
    non_human_after_1 = {p["id"] for p in populated_store.list_people(limit=1000)
                          if p["persona"].get("race") in NON_HUMAN}
    n2 = seed_races(populated_store, fraction=0.1)
    non_human_after_2 = {p["id"] for p in populated_store.list_people(limit=1000)
                          if p["persona"].get("race") in NON_HUMAN}
    assert non_human_after_1 == non_human_after_2
    assert n1 >= 1
    assert n2 == 0
