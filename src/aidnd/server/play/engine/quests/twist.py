"""TWIST beat (spec §3a · §5 Step 5). reveal_on (first visit to the villain node) → arc.beat='twisted';
APPEND the twist's real _met dict to done_any (never mutate [0], never remove) — widening the routes,
never invalidating progress. Reveal text → player journal + the giver's next conversation line."""

from __future__ import annotations

from aidnd.server.play.engine.core import _store, _wid


def _j_beat(cid, beat, facts):
    try:
        from aidnd.server.play.engine.journal import j_beat
    except ImportError:
        return
    try:
        j_beat(cid, beat, facts)
    except Exception:  # noqa: BLE001 — journaling is best-effort, never breaks the twist
        pass


def on_visit(loc: int, node_of) -> str | None:
    for ct in _store().contracts(_wid(), "active"):
        if ct.get("src") != "sift" or (ct.get("arc") or {}).get("beat") == "twisted":
            continue
        tw = ((ct.get("seed") or {}).get("twist")) or None
        if not tw or tw.get("reveal_on", "").split(":", 1)[0] != "visit":
            continue
        villain = tw["reveal_on"].split(":", 1)[1]
        if node_of(villain) != loc:
            continue
        done_any = list(ct.get("done_any") or [])
        adds = tw.get("adds")
        if adds and adds not in done_any:               # append-only, dedup
            done_any.append(adds)
        reveal = (ct.get("framer") or {}).get("reveal") or "Всплыл новый поворот в этом деле."
        data = {k: v for k, v in ct.items() if k not in ("id", "status")}
        data["done_any"] = done_any
        data["arc"] = {"beat": "twisted"}
        data["giver_next_line"] = reveal                # giver voices it in the next conversation
        _store().save_contract(_wid(), ct["id"], "active", data)
        _j_beat(ct["id"], "twist", {"reveal": reveal})   # single twist beat (see decision above)
        return reveal
    return None
