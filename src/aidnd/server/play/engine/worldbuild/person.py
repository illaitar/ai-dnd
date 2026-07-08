"""Building a Townsperson (mind + persona + portraits) from a pool row.

Key functions
-------------
_person_from_row(row, home, work) -> Townsperson : Ready NPC from bank → Townsperson with mind
    + rich persona/portraits.
"""

from __future__ import annotations

import random

from aidnd.mind import NpcConfig, NpcState
from aidnd.worldgen.population import Townsperson

from ..session.persist import _store
from ..session.state import _wid
from .building import _building_keys


def _person_from_row(row: dict, home: int, work: str | None) -> Townsperson:
    """Ready NPC from bank → Townsperson with mind + rich persona/portraits."""
    mech = row.get("mech") or {}
    cfg = NpcConfig(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        traits=mech.get("traits") or {},
        abilities=mech.get("abilities") or {},
    )
    st = NpcState.from_config(cfg)
    r = random.Random(row["id"])  # light background needs, deterministic
    for n in st.needs:
        st.needs[n] = round(r.uniform(0.1, 0.35), 2)
    saved = _store().get_npc_state(_wid(), row["id"])  # lived experience survives restart
    if saved:
        st.relationships = saved.get("relationships") or {}
        st.needs.update(saved.get("needs") or {})
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
        portraits=row.get("portraits") or {},
    )
    if work:  # building owner → keys to his locked containers
        tp.keys = _building_keys(work)
    return tp
