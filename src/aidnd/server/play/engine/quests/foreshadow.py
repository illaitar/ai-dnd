"""FORESHADOW beat (spec §3a Beat 1 · §5 Step 4 ticks). The cast get the framer's foreshadow line
as a per-mind context injection + a hot impulse — the SAME mechanism as world.py's oaths (a pid→line
dict fed into ctx and an impulse bump). After quest_foreshadow_ticks the director promotes to offered.
Minds are never throttled — this only adds a line to those already in the scene."""

from __future__ import annotations

from aidnd.server.play.engine.core import _store, _wid


def lines(order: list) -> dict:
    """{pid: foreshadow line} for cast members present in `order`; count down; promote when done."""
    present = set(order)
    out = {}
    for ct in _store().contracts(_wid(), "queued"):
        if ct.get("src") != "sift" or (ct.get("arc") or {}).get("beat") != "foreshadow":
            continue
        line = (ct.get("framer") or {}).get("foreshadow")
        cast_pids = [v for v in (ct.get("roles") or {}).values() if v]
        touched = [pid for pid in cast_pids if pid in present]
        if line:
            for pid in touched:
                out[pid] = line
        arc = dict(ct["arc"])
        arc["fore_left"] = int(arc.get("fore_left", 0)) - 1
        data = {k: v for k, v in ct.items() if k not in ("id", "status")}
        if arc["fore_left"] <= 0:                        # foreshadow spent → surface the offer
            from aidnd.server.play.engine.quests.pipeline import _surface
            data["arc"] = arc
            _surface(ct["id"], {"id": ct["id"], "status": "queued", **data})
        else:
            data["arc"] = arc
            _store().save_contract(_wid(), ct["id"], "queued", data)
    return out
