"""Building a Townsperson (mind + persona + portraits) from a pool row.

Key functions
-------------
_person_from_row(row, home, work) -> Townsperson : Ready NPC from bank → Townsperson with mind
    + rich persona/portraits.
"""

from __future__ import annotations

import os
import random

from aidnd.mind import NpcConfig, NpcState
from aidnd.worldgen.population import Townsperson

from ..core import _PORT_DIR
from ..session.persist import _store
from ..session.state import _wid
from .building import _building_keys


def _portraits_of(row: dict) -> dict:
    """Portrait map {emotion: rel-path} for a pool row. The bank predates the portraits
    column (rows hold {}), but the rendered files ARE on disk — data/portraits/<id>/<эмоция>.png —
    so derive the map from the directory when the row is empty."""
    ports = row.get("portraits") or {}
    if ports:
        return ports
    pdir = os.path.join(_PORT_DIR, row["id"])
    if not os.path.isdir(pdir):
        return {}
    return {f[:-4]: f"{row['id']}/{f}" for f in sorted(os.listdir(pdir)) if f.endswith(".png")}


def _hydrate_rels(st, rels: list) -> None:
    """Seed §3.7 `mech.rels` into `state.relationships` as a day-0 social graph.

    weight (−1..+1) → {affinity, trust, fear}: liking lifts affinity/trust, enmity
    (negative weight, esp. rival/enemy) adds fear so `bucket()`/hostility/proxemics
    read a real fabric on tick 0 instead of a town of strangers.
    """
    for e in rels:
        other = e.get("other")
        if not other:
            continue
        w = float(e.get("weight", 0.0))
        kind = e.get("kind", "")
        fear = round(-w * 0.5, 2) if (w < 0 and kind in ("rival", "enemy")) else 0.0
        st.relationships[other] = {"affinity": round(w, 2),
                                   "trust": round(max(0.0, w), 2), "fear": fear,
                                   "anchored": True}          # авторские родство/вражда пожизненны (§4.3)


def _person_from_row(row: dict, home: int, work: str | None) -> Townsperson:
    """Ready NPC from bank → Townsperson with mind + rich persona/portraits."""
    mech = row.get("mech") or {}
    cfg = NpcConfig(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        traits=mech.get("traits") or {},
        abilities=mech.get("abilities") or {},
        # enriched entity slices (§3) — .get with empty defaults so legacy rows degrade to neutral
        worldview=mech.get("worldview") or {},
        skills=mech.get("skills") or {},
        allegiances=mech.get("allegiances") or [],
        standing=mech.get("standing") or {},
        perception=mech.get("perception") or {},
    )
    st = NpcState.from_config(cfg)
    r = random.Random(row["id"])  # light background needs, deterministic
    for n in st.needs:
        st.needs[n] = round(r.uniform(0.1, 0.35), 2)
    _hydrate_rels(st, mech.get("rels") or [])  # §3.7 seeded day-0 social fabric
    saved = _store().get_npc_state(_wid(), row["id"])  # lived experience survives restart
    if saved:
        st.relationships.update(saved.get("relationships") or {})  # lived edges win over seed
        st.needs.update(saved.get("needs") or {})
        st.last_decay_gt = int(saved.get("last_decay_gt") or 0)  # decay clock survives restart (Inc1)
        st.familiarity.update(saved.get("familiarity") or {})    # pre-acquaintance counters survive restart (Inc3)
        for m in saved.get("memory") or []:
            mm = st.memory.add(
                m["text"],
                m["t"],
                m.get("importance", 0.3),
                kind=m.get("kind", "observation"),
                about=m.get("about") or [],
            )
            mm.last_access = m.get("last_access", m["t"])
    tp = Townsperson(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        home=home,
        work=work,
        charisma=row["charisma"],
        appearance=row["appearance"],
        state=st,
        persona=row.get("persona"),
        portraits=_portraits_of(row),
    )
    if work:  # building owner → keys to his locked containers
        tp.keys = _building_keys(work)
    return tp
