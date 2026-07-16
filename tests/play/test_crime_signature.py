"""Soliciting murder must be judged on the death axis, not authority (playtest gap: a pacifist
witness with morals.death=-0.9 felt NOTHING when the PC offered coin for a killing, because
`core._crime_signature` tagged the offer purely ["вероломство"] → TAG_AXIS routes that tag to
"authority", and an un-enriched authority=0 zeroes the whole moral lens. 1299/1354 pool NPCs carry
a nonzero morals.death — that's the axis a murder-for-hire offer should actually land on.

`core._crime_affect` fans a code-derived Event onto the co-present crowd via
`mind.project.project_and_apply` (МОЗГ Inc2) — zero LLM."""

from __future__ import annotations

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core


class _P:
    def __init__(self, name, pid, wv=None):
        self.name, self.role, self.work, self.persona = name, "завсегдатай", None, {}
        cfg = NpcConfig(id=pid, name=name, role="завсегдатай", worldview=wv or {})
        self.state = NpcState.from_config(cfg)


def test_crime_signature_solicitation_includes_death_tag():
    """`_crime_signature` for a murder-for-hire offer must carry "убийство" (death axis) alongside
    "вероломство" (authority shade) — `_dominant` picks убийство first (severity-ordered)."""
    tags, intensity, threat, harm = core._crime_signature(
        "предлагает золото за убийство соперника"
    )
    assert "убийство" in tags
    assert intensity == 0.6
    assert threat == 0.0   # an offer is not physical danger
    assert harm == 0.0


def test_pacifist_witness_feels_outrage_at_solicitation(monkeypatch):
    """A pacifist witness (morals.death=-0.8, authority=0.0) must register disgust/outrage when
    the PC solicits murder in front of them. Under the OLD single-tag ["вероломство"] signature,
    TAG_AXIS routes to "authority" — a zero authority stance means the moral lens is a no-op and
    every dim stays 0, even though this witness is horrified by killing."""
    monkeypatch.setattr(core, "_npc_save", lambda *a, **k: None, raising=False)
    pacifist = _P("Освин", "npc:osvin", {"morals": {"death": -0.8, "authority": 0.0}})
    people = {"npc:osvin": pacifist}

    core._crime_affect(
        people, ["npc:osvin"], "pc", "предлагает золото за убийство соперника", "loc:x"
    )

    assert pacifist.state.emotion["disgust"] > 0.0
    assert pacifist.state.emotion["distress"] >= 0.0
