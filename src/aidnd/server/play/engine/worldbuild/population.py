"""Population bookkeeping: households, surnames, downward-mobility notes, and placement restore.

Key functions
-------------
_surname(name) -> str : Surname = last name token (else empty) — same logic as pre-acquaintance kin.
_reclass_note(p, former) -> None : Narrative downward mobility note ('was once X').
_households(rows, rng) -> list : Split pool into FAMILY households — small groups of one surname.
_restore_placed(city, placed) -> tuple : Rebuild the SAME residents from stored placements.
_topup_dependents(city, by_id, placed, dead, homes, people, spot) -> None : House dependents added
    to the pool after this world was settled.
"""

from __future__ import annotations

from ..session.persist import _pool, _store
from ..session.state import _wid
from ..session.time import _mt
from .jobs import _plan_jobs
from .person import _person_from_row


def _surname(name: str) -> str:
    """Surname = last name token (else empty) — same logic as pre-acquaintance kin."""
    parts = name.split()
    return parts[-1] if len(parts) > 1 else ""


def _households(rows: list, rng) -> list:
    """D1: split pool into FAMILY households — small groups of one surname (couple/siblings),
    each lives in one house. Deterministic (rng from settle|wid). Size 1-5, peak 2-3."""
    by_sur: dict = {}
    for r in rows:
        by_sur.setdefault(_surname(r["name"]) or r["id"], []).append(r["id"])
    households = []
    for sur in sorted(by_sur):
        members = sorted(by_sur[sur])
        rng.shuffle(members)
        i = 0
        while i < len(members):
            size = rng.choices([1, 2, 3, 4, 5], weights=[2, 4, 4, 2, 1])[0]
            households.append(members[i:i + size])
            i += size
    return households


def _reclass_note(p, former: str) -> None:
    """Narrative downward mobility: mark 'was once X' + former_role (for venue buyout,
    layer B3) — not silent role change."""
    p.former_role = former                            # grad student remembers craft (can buy out)
    if any("прежде был" in m.text for m in p.state.memory.items):
        return
    p.state.memory.add(f"прежде был {former}, да места не нашёл — перебиваюсь подёнщиной",
                       _mt(), 0.5)


def _restore_placed(city, placed):
    """Rebuild the SAME residents from stored placements (persisted across re-entry): drop the
    dead/captive, re-plan jobs (venue gravity may have shifted), then top up any dependents forged
    into the pool after this world was first settled. Returns (people, spot); may be empty."""
    store, by_id = _store(), {r["id"]: r for r in _pool().list_people(limit=100000)}
    dead = {k.split("|", 1)[1] for k in store.flags_prefix(_wid(), "dead|")} | \
        {k.split("|", 1)[1] for k in store.flags_prefix(_wid(), "captive|")}  # captives don't roam
    homes = {pid: pl["home"] for pid, pl in placed.items() if pid not in dead}
    roles = {pid: by_id[pid]["role"] for pid in homes if pid in by_id}
    jobs = _plan_jobs(city, homes, roles)               # venue gravity + reclassification
    people, spot = {}, {}
    for pid, pl in placed.items():
        if pid in dead or pid not in by_id:
            continue  # the dead do not return
        work, override = jobs.get(pid, (None, None))
        p = _person_from_row(by_id[pid], pl["home"], work)
        if override:
            _reclass_note(p, p.role)
            p.role = override
        people[pid] = p
        spot[pid] = pl["node"]
    _topup_dependents(city, by_id, placed, dead, homes, people, spot)
    return people, spot


def _topup_dependents(city, by_id, placed, dead, homes, people, spot):
    """D2 top-up: dependents added to the pool AFTER this world was settled — house each with its
    family head once (without disturbing placed adults); thereafter they live via placements.
    Mutates people/spot in place and persists the placement."""
    store = _store()
    for pid, row in by_id.items():
        if pid in placed or pid in dead or not (row.get("mech") or {}).get("dependent"):
            continue
        head = (row["mech"] or {}).get("head")
        home = homes.get(head) or (placed.get(head) or {}).get("home")
        if home is None:                                # head dead/unplaced — skip
            continue
        people[pid] = _person_from_row(row, home, None)
        spot[pid] = home
        store.place_person(_wid(), pid, home, home, None)
