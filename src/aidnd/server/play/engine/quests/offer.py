"""Private-offer routing: an offered emergent contract (src='sift') outranks the improvised
_contract_offer while it is live (spec §3a Beat 2 · dialogue.py:101)."""

from __future__ import annotations

from aidnd.server.play.engine.core import _store, _wid


def emergent_offer(npc: str) -> dict | None:
    for ct in _store().contracts(_wid(), "offered"):
        if ct.get("src") == "sift" and ct.get("giver") == npc:
            return ct
    return None
