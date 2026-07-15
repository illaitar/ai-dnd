"""Tests for Pass A NPC entity enrichment (deterministic, idempotent, schema-shaped).

Covers docs/superpowers/specs/2026-07-15-npc-entity-enrichment-design.md §3: same pid → same
output across runs; every §3 key present with correct types/ranges; and derivation sanity
(жрец → devout + temple; головорез → high combat + low empathy; a demon-cultist minority with
Багровый/Тень deity exists in a role-mixed cohort).
"""

from __future__ import annotations

import os
import random
import tempfile

import pytest

from aidnd.worldgen import WorldStore
from aidnd.worldgen.enrich_pool import (
    CULT_DEITIES,
    LIGHT_DEITIES,
    MATERIALS,
    TABOO_VOCAB,
    build_index,
    enrich_person,
    enrich_pool,
)

_ALL_DEITIES = set(LIGHT_DEITIES) | set(CULT_DEITIES) | {"нет"}


def _fresh_store() -> WorldStore:
    return WorldStore(os.path.join(tempfile.mkdtemp(), "worlds.db"))


def _mk(store, pid, role, *, name="Бран Полынь", dependent=False, head=None,
        traits=None, abilities=None, appearance=0.3):
    from aidnd.worldgen.abilities import roll_abilities
    from aidnd.worldgen.population import _traits
    mech = {"role": role,
            "traits": traits or _traits(role, random.Random(f"t|{pid}")),
            "abilities": abilities or roll_abilities(role, random.Random(f"a|{pid}"))}
    if dependent:
        mech["dependent"] = True
        mech["head"] = head
    persona = {"race": "человек"}
    store.save_person(pid, role, name, 0.3, appearance, mech, persona, {}, seed=1)


def _seed_cohort(store) -> None:
    """A role-mixed cohort: key roles + a batch of thugs/vagrants (cult draw) + a household."""
    roles = ["жрец", "знахарка", "кузнец", "стражник", "лавочник", "трактирщик",
             "бард", "мельник", "дубильщик", "сапожник", "горожанин"]
    i = 0
    for role in roles:
        _mk(store, f"pool:{i:04d}", role, name=f"Имя Род{i}")
        i += 1
    for _ in range(40):                      # many thugs/vagrants → cult minority must surface
        role = "головорез" if i % 2 == 0 else "бродяга"
        _mk(store, f"pool:{i:04d}", role, name="Тень Овражный")
        i += 1
    # a household: adult head + two dependents (real kin edges)
    _mk(store, f"pool:{i:04d}", "горожанин", name="Горм Тихвуд")
    head = f"pool:{i:04d}"; i += 1
    _mk(store, f"pool:{i:04d}", "дитя", name="Лия Тихвуд", dependent=True, head=head); i += 1
    _mk(store, f"pool:{i:04d}", "старик", name="Ода Тихвуд", dependent=True, head=head); i += 1


@pytest.fixture
def cohort():
    store = _fresh_store()
    _seed_cohort(store)
    return store


# ── schema shape ────────────────────────────────────────────────────────────
def test_schema_all_keys_present_and_typed(cohort):
    enrich_pool(cohort)
    for row in cohort.list_people(limit=1000):
        m = row["mech"]
        # §3.1 two new traits, in range
        for k in ("empathy", "vengefulness"):
            assert 0.0 <= m["traits"][k] <= 1.0
        # §3.2 worldview — all 10 fields
        wv = m["worldview"]
        assert wv["faith"]["deity"] in _ALL_DEITIES
        assert 0.0 <= wv["faith"]["devotion"] <= 1.0
        assert set(wv["morals"]) == {"violence", "theft", "authority", "outsiders", "magic", "death"}
        for v in wv["morals"].values():
            assert -1.0 <= v <= 1.0
        assert all(tb in TABOO_VOCAB for tb in wv["taboos"])
        assert -1.0 <= wv["mood_baseline"] <= 1.0
        # §3.4 standing
        assert isinstance(m["standing"]["rank"], str)
        assert 0.0 <= m["standing"]["notoriety"] <= 1.0
        # §3.5 skills
        sk = m["skills"]
        assert 0.0 <= sk["combat"] <= 1.0
        assert 0.0 <= sk["magic"] <= 1.0
        assert 0.0 <= sk["literacy"] <= 1.0
        assert all(mat in MATERIALS and 0.0 <= val <= 1.0 for mat, val in sk["craft"].items())
        # §3.3 allegiances
        for a in m["allegiances"]:
            assert set(a) == {"group", "kind", "role", "standing"}
        # §3.9 perception
        assert 0.0 <= m["perception"]["vigilance"] <= 1.0
        # §3.7 rels
        for e in m["rels"]:
            assert e["kind"] in ("kin", "friend", "rival", "debtor", "creditor",
                                 "patron", "beloved", "enemy")
            assert -1.0 <= e["weight"] <= 1.0


def test_dependents_empty_economy_but_have_worldview(cohort):
    enrich_pool(cohort)
    deps = [r for r in cohort.list_people(limit=1000) if (r["mech"].get("dependent"))]
    assert deps
    for r in deps:
        assert r["mech"]["economy"] == {}           # witness, but earns nothing
        assert r["mech"]["worldview"]["morals"]      # still carries a worldview
        assert "empathy" in r["mech"]["traits"]


def test_adults_have_economy(cohort):
    enrich_pool(cohort)
    kuz = next(r for r in cohort.list_people(limit=1000) if r["role"] == "кузнец")
    assert kuz["mech"]["economy"]["produces"] == "подковы"


# ── determinism / idempotency ───────────────────────────────────────────────
def test_deterministic_across_stores():
    a, b = _fresh_store(), _fresh_store()
    _seed_cohort(a); _seed_cohort(b)
    enrich_pool(a); enrich_pool(b)
    ma = {r["id"]: r["mech"] for r in a.list_people(limit=1000)}
    mb = {r["id"]: r["mech"] for r in b.list_people(limit=1000)}
    assert ma == mb


def test_idempotent_rerun(cohort):
    enrich_pool(cohort)
    once = {r["id"]: r["mech"] for r in cohort.list_people(limit=1000)}
    enrich_pool(cohort)
    twice = {r["id"]: r["mech"] for r in cohort.list_people(limit=1000)}
    assert once == twice


def test_enrich_person_pure_deterministic(cohort):
    rows = cohort.list_people(limit=1000)
    idx = build_index(rows)
    row = rows[0]
    assert enrich_person(row, idx) == enrich_person(row, idx)


# ── derivation sanity ───────────────────────────────────────────────────────
def test_priest_is_devout_with_temple(cohort):
    enrich_pool(cohort)
    priest = next(r for r in cohort.list_people(limit=1000) if r["role"] == "жрец")
    m = priest["mech"]
    assert m["worldview"]["faith"]["devotion"] >= 0.6
    assert m["worldview"]["faith"]["deity"] in LIGHT_DEITIES
    assert any(a["kind"] == "temple" for a in m["allegiances"])


def test_thug_high_combat_low_empathy(cohort):
    enrich_pool(cohort)
    thugs = [r for r in cohort.list_people(limit=1000) if r["role"] == "головорез"]
    assert thugs
    avg_combat = sum(r["mech"]["skills"]["combat"] for r in thugs) / len(thugs)
    avg_emp = sum(r["mech"]["traits"]["empathy"] for r in thugs) / len(thugs)
    assert avg_combat >= 0.4
    assert avg_emp <= 0.4
    assert all(any(a["kind"] == "gang" for a in r["mech"]["allegiances"]) for r in thugs)


def test_demon_cult_minority_exists(cohort):
    enrich_pool(cohort)
    deities = {r["mech"]["worldview"]["faith"]["deity"]
               for r in cohort.list_people(limit=1000)}
    assert deities & set(CULT_DEITIES)          # Багровый/Тень present in the cohort


def test_household_kin_edges_are_real_ids(cohort):
    enrich_pool(cohort)
    rows = {r["id"]: r for r in cohort.list_people(limit=1000)}
    head = next(r for r in rows.values()
                if r["name"] == "Горм Тихвуд" and not r["mech"].get("dependent"))
    kin = [e["other"] for e in head["mech"]["rels"] if e["kind"] == "kin"]
    assert kin
    for other in kin:
        assert other in rows                    # points at a real pool id
        assert rows[other]["mech"].get("dependent")   # its two dependents


def test_only_mech_grows_persona_untouched(cohort):
    before = {r["id"]: r["persona"] for r in cohort.list_people(limit=1000)}
    enrich_pool(cohort)
    after = {r["id"]: r["persona"] for r in cohort.list_people(limit=1000)}
    assert before == after
