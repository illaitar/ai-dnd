"""SALIENCE — code owns the ordering (spec §5 Step 2). Weights live in PB; the deed-weight table
and the 5-day freshness window are the only code constants (the DEFAULT_RULES precedent, §4/§8).

score = w_rare·rarity + w_peak·peak + w_near·proximity + w_fresh·freshness
  rarity     = 1 / (1 + recent_count)
  peak       = |affinity(giver→villain)| + max deed-weight in evidence
  proximity  = 1.0 same node / 0.6 adjacent / 0.2 else
  freshness  = max(0, 1 − age_days / 5)     (age_days = (now_gt − deed_gt) / 1440)

seeds.py (Task 2) prefixes evidence deed ids with "deed:" (e.g. "deed:d123") and also carries
plain "agenda:<pid>:<idx>" evidence entries that name no journal deed — score() strips the
"deed:" prefix when resolving against ctx["deeds"] and silently skips entries that don't
resolve to a deed (agenda anchors contribute no deed-weight/freshness by design).
"""

from __future__ import annotations

from aidnd.server.play.engine.core import PB

DEED_W = {"promise": 0.5, "favor": 0.3, "theft": 0.7, "murder": 1.0}
FRESH_DAYS = 5


def rarity(recent_count: int) -> float:
    return 1.0 / (1.0 + max(0, recent_count))


def peak(giver_villain_aff: float, evidence_deeds: list) -> float:
    dw = max((DEED_W.get(d.get("verb"), 0.0) for d in evidence_deeds), default=0.0)
    return abs(giver_villain_aff) + dw


def proximity(giver_node, player_node, adjacent: bool) -> float:
    if giver_node is not None and giver_node == player_node:
        return 1.0
    return 0.6 if adjacent else 0.2


def freshness(deed_gt: int, now_gt: int) -> float:
    age_days = (now_gt - deed_gt) / 1440.0
    return max(0.0, 1.0 - age_days / FRESH_DAYS)


def _resolve_deed_id(evidence_id: str) -> str:
    """Strip the "deed:" prefix seeds.py attaches to journal-deed evidence anchors."""
    return evidence_id[5:] if evidence_id.startswith("deed:") else evidence_id


def score(seed: dict, ctx: dict) -> float:
    giver, villain = seed["giver"], seed["cast"]["villain"]
    ev = [ctx["deeds"][did] for eid in seed.get("evidence", [])
          if (did := _resolve_deed_id(eid)) in ctx["deeds"]]
    r = rarity(ctx["recent"].get(seed["pattern"], 0))
    pk = peak(ctx["aff_edges"].get((giver, villain), 0.0), ev)
    px = ctx["prox"].get(giver, 0.2)
    fr = max((freshness(d["data"].get("made_gt", d["gt"]), ctx["now_gt"]) for d in ev), default=0.0)
    s = (PB["quest_w_rare"] * r + PB["quest_w_peak"] * pk
         + PB["quest_w_near"] * px + PB["quest_w_fresh"] * fr)
    seed["score"] = round(s, 6)
    return seed["score"]
