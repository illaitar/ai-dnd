"""The Event signature (МОЗГ Inc2) — an OBJECTIVE, not-pre-judged descriptor of an act. Every
act-resolution site (player or NPC) builds one; project.py lands it on each perceiving witness
through the visceral + moral-lens channels. Zero new LLM. See
docs/superpowers/specs/2026-07-15-brain-design.md §4.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Event:
    """An act, described objectively (no judgement baked in). The witness's own worldview decides
    whether this row lands as horror or grim satisfaction — that split lives in project.py, never
    here. Examples (§4.1):
      * kill:        Event("pc", "npc:beggar", 0.9, 0.7, 1.0, ["убийство","насилие","смерть"], zone=…)
      * gift:        Event("npc:0301", "npc:0142", 0.2, 0.0, 0.0, ["дар"])  — warmth-only
      * co-presence: Event(other, me, 0.05, 0.0, 0.0, ["видит"])           — surface read only
    """

    actor: str                          # body id who acted (pc or npc)
    target: str | None                  # body id acted upon (None for ambient acts)
    intensity: float                    # [0..1] overall salience of the act
    physical_threat: float              # [0..1] danger radiated to onlookers (weapon out, blow)
    target_harm: float                  # [0..1] harm done to target (0 none … 1.0 killed)
    tags: list[str] = field(default_factory=list)   # descriptive labels: [убийство, насилие, смерть]
    zone: str | None = None             # event location (audibility/sight perception gate)
