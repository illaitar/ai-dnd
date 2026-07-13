"""Live-playtest bug: public emergent (src='sift') board postings were invisible on
GET /api/play/board and could not be taken via board_take (only guild-board ads were handled).
board() now merges them into a 'postings' list; board_take() accepts them through the same
_accept_contract path as contract_accept, so beat/journal bookkeeping never diverges (via
j_beat, prov='accept')."""
import asyncio

import pytest

from aidnd.server.play.engine import core, journal
from aidnd.server.play.engine import world as world_mod
from aidnd.server.play.engine.pc import hero as hero_mod
from aidnd.server.play.handlers import board as board_mod
from aidnd.server.play.mechanics import contracts as ct_mod
from aidnd.worldgen import WorldStore


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _Voice:
    """Stub narrator so j_beat's single model call resolves without a live LLM."""
    def call(self, role, messages, **kw):
        return {"content": "принял дело"}


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    for mod in (core, journal, world_mod, hero_mod, ct_mod, board_mod):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(journal, "_gt", lambda: 100)
    monkeypatch.setattr(board_mod, "_play", lambda: None, raising=False)
    monkeypatch.setattr(core, "_model", lambda: _Voice(), raising=False)
    d = core._S._d()
    saved = dict(d)                    # snapshot the shared world-1 session blob...
    try:
        d.clear()
        d["wid"] = 1
        d["gt"] = 100
        yield st
    finally:
        d.clear()
        d.update(saved)                # ...and restore it so later tests keep their 'seed' etc.


def _posting(st, cid="ct:sift:npc:marta:100"):
    st.save_contract(
        1, cid, "board",
        {"giver": "npc:marta", "giver_name": "Марта Ли", "step": 0,
         "steps": [{"kind": "dead", "target": "npc:ralf"}],
         "reward": 30, "reward_item": None, "reward_name": None,
         "pitch": "Марта ищет того, кто рассчитается с Ральфом за старый долг.",
         "src": "sift", "seed": {"pattern": "revenge"},
         "arc": {"beat": "offered"}, "roles": {"giver": "npc:marta", "villain": "npc:ralf"},
         "done_any": [{"type": "dead", "id": "npc:ralf"}]},
    )
    return cid


def test_board_response_contains_sift_posting(wired):
    cid = _posting(wired)
    r = board_mod.board()
    postings = r["postings"]
    assert len(postings) == 1
    p = postings[0]
    assert p["id"] == cid
    assert p["giver"] == "Марта Ли"
    assert p["reward"] == 30
    assert p["title"] == "Марта ищет того, кто рассчитается с Ральфом за старый долг."


def test_guild_ads_unaffected_when_no_postings(wired):
    r = board_mod.board()
    assert r["postings"] == []
    assert isinstance(r["jobs"], list)  # guild board still renders as before


def test_board_take_accepts_posting_active_and_journals_once(wired):
    cid = _posting(wired)
    res = asyncio.run(board_mod.board_take(_Req({"id": cid})))
    assert res.get("taken") is True
    ct = next(c for c in wired.contracts(1, "active") if c["id"] == cid)
    assert ct["arc"]["beat"] == "active"
    j = wired.journal_list(1, kind="quest")
    told = [e for e in j if e["prov"] == "accept" and e["refs"] == [cid]]
    assert len(told) == 1
    # posting no longer sits in 'board' status
    assert not [c for c in wired.contracts(1, "board") if c["id"] == cid]
