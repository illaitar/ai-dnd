"""Consume-side wiring for the enriched entity (docs/.../npc-entity-enrichment-design.md §4.2).

An enriched `mech` flows into NpcConfig (worldview/skills/allegiances/...) and the three Body.*
fields are sourced from it: power←skills.combat, attention←perception.vigilance, faction←
allegiances[0].group. A legacy (un-enriched) mech degrades to neutral defaults and never crashes.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine.session import persist
from aidnd.server.play.engine.session.state import _wid
from aidnd.server.play.engine.world import _body_attention, _body_faction, _body_power
from aidnd.server.play.engine.worldbuild.person import _hydrate_rels, _person_from_row
from aidnd.worldgen import WorldStore


def _cfg(**mech_slices) -> NpcConfig:
    return NpcConfig(id="pool:test", name="Тест", role="головорез", **mech_slices)


# ── enriched entity → config + Body.* ────────────────────────────────────────
def test_config_carries_enriched_slices():
    cfg = _cfg(
        worldview={"morals": {"death": 0.6}, "mood_baseline": 0.4},
        skills={"combat": 0.62, "craft": {"металл": 0.7}, "magic": 0.1, "literacy": 0.3},
        allegiances=[{"group": "шайка-оврага", "kind": "gang", "role": "member", "standing": 0.3}],
        standing={"rank": "отребье", "notoriety": 0.4},
        perception={"vigilance": 0.72},
    )
    assert cfg.worldview["morals"]["death"] == 0.6
    assert cfg.skills["combat"] == 0.62
    assert cfg.allegiances[0]["group"] == "шайка-оврага"
    assert cfg.standing["rank"] == "отребье"
    assert cfg.perception["vigilance"] == 0.72


def test_body_fields_sourced_from_entity():
    cfg = _cfg(
        skills={"combat": 0.35},
        perception={"vigilance": 0.72},
        allegiances=[{"group": "шайка-оврага", "kind": "gang", "role": "initiate", "standing": 0.2}],
    )
    assert _body_power(cfg) == 0.35          # was flat 1.0
    assert _body_attention(cfg) == 0.72      # was rng.uniform(.45,.85)
    assert _body_faction(cfg) == "шайка-оврага"   # was all "town"


def test_mood_baseline_ties_emotion_baseline():
    cheerful = NpcState.from_config(_cfg(worldview={"mood_baseline": 0.8}))
    gloomy = NpcState.from_config(_cfg(worldview={"mood_baseline": -0.8}))
    assert cheerful.emotion_baseline("joy") > 0.0
    assert gloomy.emotion_baseline("distress") > 0.0
    assert cheerful.emotion_baseline("distress") == 0.0


# ── legacy / un-enriched rows degrade to neutral (regression guard, §4.3) ─────
def test_unenriched_config_neutral_no_crash():
    cfg = NpcConfig(id="pool:legacy", name="Старьё", role="горожанин")   # no mech slices
    assert _body_power(cfg) == 1.0           # legacy parity fallback
    assert _body_attention(cfg) == 0.5       # neutral vigilance
    assert _body_faction(cfg) == "town"      # no allegiance → town
    st = NpcState.from_config(cfg)
    assert st.emotion_baseline("joy") == 0.0
    assert st.emotion_baseline("distress") == 0.0


def test_empty_slice_dicts_neutral():
    cfg = _cfg(skills={}, perception={}, allegiances=[])
    assert _body_power(cfg) == 1.0
    assert _body_attention(cfg) == 0.5
    assert _body_faction(cfg) == "town"


# ── §3.7 day-0 social fabric: _hydrate_rels + saved-state precedence ─────────
def _row(pid: str, rels: list) -> dict:
    return {
        "id": pid,
        "name": "Тест",
        "role": "горожанин",
        "charisma": 0.5,
        "appearance": "неприметный",
        "mech": {"rels": rels},
    }


@pytest.fixture
def live_store(monkeypatch):
    """A fresh, empty live.db so _person_from_row's `saved = _store().get_npc_state(...)`
    restore path is exercised against a controlled fixture instead of the real runtime db."""
    store = WorldStore(os.path.join(tempfile.mkdtemp(), "live.db"))
    monkeypatch.setattr(persist, "_STORE", store)
    return store


def test_hydrate_rels_weight_to_affect_mapping():
    """weight (−1..+1) → {affinity, trust, fear}: a strong friend lifts affinity/trust and adds
    no fear; a strong rival/enemy goes negative-affinity, zero-trust, and picks up fear."""
    cfg = NpcConfig(id="pool:t1", name="Т", role="горожанин")
    st = NpcState.from_config(cfg)
    _hydrate_rels(st, [
        {"other": "pool:friend", "kind": "friend", "weight": 0.8},
        {"other": "pool:enemy", "kind": "enemy", "weight": -0.7},
    ])
    friend = st.relationships["pool:friend"]
    assert friend == {"affinity": 0.8, "trust": 0.8, "fear": 0.0}
    enemy = st.relationships["pool:enemy"]
    assert enemy == {"affinity": -0.7, "trust": 0.0, "fear": 0.35}


def test_saved_edge_beats_day0_seed(live_store):
    """Critical precedence: mech.rels seeds a day-0 relationship to pid X, but the world already
    has a LIVED edge to X in npc_state (restart/reload path). person.py must hydrate the seed
    THEN overlay the saved state, so the saved edge wins — the seed must not clobber a real,
    lived relationship on reload. If hydrate ran AFTER restore instead of before, this would fail:
    the seed-derived {affinity:0.9,...} would stomp the saved {affinity:-0.6,...}."""
    wid = _wid()
    row = _row("pool:npc2", rels=[{"other": "pool:x", "kind": "friend", "weight": 0.9}])
    live_store.save_npc_state(wid, "pool:npc2", {
        "relationships": {"pool:x": {"affinity": -0.6, "trust": 0.1, "fear": 0.4}},
    })
    tp = _person_from_row(row, home=1, work=None)
    assert tp.state.relationships["pool:x"] == {"affinity": -0.6, "trust": 0.1, "fear": 0.4}


def test_seed_only_pid_survives_when_absent_from_saved_state(live_store):
    """A pid seeded via mech.rels but never mentioned in the saved npc_state must still be present
    after restore — `.update()` overlays saved edges onto the seeded map, it doesn't replace it."""
    wid = _wid()
    row = _row("pool:npc3", rels=[{"other": "pool:onlyseed", "kind": "patron", "weight": 0.4}])
    live_store.save_npc_state(wid, "pool:npc3", {
        "relationships": {"pool:someoneelse": {"affinity": 0.2, "trust": 0.2, "fear": 0.0}},
    })
    tp = _person_from_row(row, home=1, work=None)
    assert tp.state.relationships["pool:onlyseed"] == {"affinity": 0.4, "trust": 0.4, "fear": 0.0}
    assert tp.state.relationships["pool:someoneelse"] == {"affinity": 0.2, "trust": 0.2, "fear": 0.0}
