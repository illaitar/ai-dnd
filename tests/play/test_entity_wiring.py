"""Consume-side wiring for the enriched entity (docs/.../npc-entity-enrichment-design.md §4.2).

An enriched `mech` flows into NpcConfig (worldview/skills/allegiances/...) and the three Body.*
fields are sourced from it: power←skills.combat, attention←perception.vigilance, faction←
allegiances[0].group. A legacy (un-enriched) mech degrades to neutral defaults and never crashes.
"""

from __future__ import annotations

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine.world import _body_attention, _body_faction, _body_power


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
