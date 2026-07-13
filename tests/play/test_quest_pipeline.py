"""Утренний конвейер: один seed всплывает; приватный → offered, публичный → board; протухший → compost."""
import json
import os
import re
import tempfile
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import pipeline as P
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Stub:
    """Сценарно-нейтральный дублёр LLM: судья ранжирует ЛЮБОЙ поданный seed (по его sid из
    payload'а), фреймер называет только заказчика (он всегда в списке МОЖНО НАЗЫВАТЬ) — поэтому один
    и тот же дублёр обслуживает и приватный (Дунн), и публичный (Марта) сценарии без подгонки."""

    def call(self, role, messages, **kw):
        sys, usr = messages[0]["content"], messages[1]["content"]
        if "редактор" in sys:                       # judge
            sids = re.findall(r"seed_[a-z_]+", usr)
            top = sids[0] if sids else ""
            return {"content": json.dumps({"rank": [top], "veto": [],
                                           "why": {top: "тёплый крючок"}}, ensure_ascii=False)}
        m = re.search(r"ЗАКАЗЧИК:\s*(.+?)\.", usr)   # framer
        giver = (m.group(1) if m else "Заказчик").split()[0]   # имя без фамилии (валидатор дробит на токены)
        return {"content": json.dumps(
            {"pitch": f"{giver} ищет помощи, награда найдётся.",
             "foreshadow": f"{giver} не находит покоя.",
             "reveal": f"{giver} ещё вспомнит обиду."}, ensure_ascii=False)}


def _advance_foreshadow(n=None):
    """Run the foreshadow countdown to completion (or `n` ticks) — mirrors world.py's per-tick call
    to foreshadow.lines(); the cast list is irrelevant to the countdown itself (only to which pids
    receive the line), so an empty order still decrements every live foreshadow contract."""
    from aidnd.server.play.engine.quests import foreshadow as FS
    for _ in range(n if n is not None else core.PB["quest_foreshadow_ticks"]):
        FS.lines([])


def _person(pid, name, role, agendas=(), rels=None):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    st.agendas = list(agendas)
    st.relationships = dict(rels or {})
    return SimpleNamespace(name=name, role=role, state=st, persona={}, work=None, home=None)


@pytest.fixture
def town(monkeypatch):
    snap = dict(core._S._d())                        # снимок сессии world-1 — вернём после теста
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    monkeypatch.setattr(core, "_model", lambda: _Stub())
    gt = 3 * 1440
    core._S["gt"] = gt
    dunn_ms = Milestone("вернуть гроссбух сестры", "acquire", "debt:marta", {},
                        {"type": "have", "item": "гроссбух"})
    dunn = _person("npc:dunn", "Дунн Ли", "охотник",
                   agendas=[Agenda("вернуть гроссбух сестры", "ambition", 0.7, [dunn_ms])],
                   rels={"npc:ralf": {"affinity": -0.4}})
    ralf = _person("npc:ralf", "Ральф Ли", "ростовщик", rels={"npc:dunn": {"affinity": -0.1}})
    marta = _person("npc:marta", "Марта Ли", "торговка", rels={"npc:ralf": {"affinity": -0.6}})
    core._S["people"] = {"npc:dunn": dunn, "npc:ralf": ralf, "npc:marta": marta}
    core._S["crof"] = {"npc:dunn": 7, "npc:ralf": 9, "npc:marta": 4}
    core._S["loc"] = 7                              # игрок в узле Дунна
    core._S["city"] = None
    st.purse_add(core._wid(), "npc:dunn", 41)
    st.deed_add(core._wid(), gt - 1440, "npc:ralf", "promise", "npc:marta", "",
                status="broken", data={"what": "вернуть гроссбух", "made_gt": gt - 1440})
    yield st
    core._S._d().clear()
    core._S._d().update(snap)


def test_one_seed_surfaces_private(town):
    news = P.quest_morning()
    assert news
    # freshly sifted → FORESHADOW beat, not yet visible as an offer (spec Beat 1)
    pending = [c for c in town.contracts(core._wid(), "queued") if c.get("src") == "sift"]
    assert len(pending) == 1 and pending[0]["arc"]["beat"] == "foreshadow"
    assert not [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"]
    _advance_foreshadow()                              # quest_foreshadow_ticks pass → offer surfaces
    offered = town.contracts(core._wid(), "offered")
    emergent = [c for c in offered if c.get("src") == "sift"]
    assert len(emergent) == 1
    ct = emergent[0]
    assert ct["giver"] == "npc:dunn" and ct["arc"]["beat"] == "offered"
    assert ct["done_any"] == [{"type": "have", "item": "гроссбух"}]  # done_any[0] = дословная веха
    assert ct["step"] == 0
    assert ct["steps"][0]["kind"] == "bring"


def test_public_pattern_goes_to_board(town, monkeypatch):
    # заставим просев выдать только публичный паттерн: у Дунна убираем агенду
    core._S["people"]["npc:dunn"].state.agendas = []
    P.quest_morning()
    _advance_foreshadow()
    board = [c for c in town.contracts(core._wid(), "board") if c.get("src") == "sift"]
    assert board and board[0]["giver"] == "npc:marta"
    # grievance pattern: pipeline materialized a REAL revenge milestone on Марта (mirrors deals.py) →
    # done_any[0] is verbatim from it and quest_writeback can advance her cursor uniformly.
    assert board[0]["done_any"][0] == {"type": "dead", "id": "npc:ralf"}
    marta_ag = core._S["people"]["npc:marta"].state.agendas
    assert marta_ag and marta_ag[-1].kind == "revenge"
    assert marta_ag[-1].current().done == {"type": "dead", "id": "npc:ralf"}
    assert f"agenda:npc:marta:{len(marta_ag) - 1}" in board[0]["seed"]["evidence"]


def test_accepted_emergent_contract_survives_give_and_talk(town):
    """CRITICAL regression: an accepted (status→'active') emergent contract used to persist
    step=<dict> — every legacy reader (_ct_cur/_ct_advance) treats 'step' as an int index, so
    min(dict, 0) crashed on the very next give/move/talk while the contract was active."""
    from aidnd.server.play.mechanics import contracts as C

    P.quest_morning()
    _advance_foreshadow()
    ct = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    assert ct["step"] == 0                            # int, as _make_contract persists it
    # mirror contract_accept (world.py:162-178): flip status to active, data untouched
    town.save_contract(core._wid(), ct["id"], "active",
                       {k: v for k, v in ct.items() if k not in ("id", "status")})
    # unrelated item/npc drive the improvised-contract triggers — must not raise
    assert C._contract_on_give("npc:ralf", {"name": "морковь", "kind": "misc"}) is None
    assert C._contract_on_talk("npc:ralf") is None
    still = next(c for c in town.contracts(core._wid(), "active") if c["id"] == ct["id"])
    assert still["step"] == 0                          # untouched — improvised machinery intact


def test_window_one_holds_across_mornings(town):
    news1 = P.quest_morning()
    assert news1
    _advance_foreshadow()
    first = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    news2 = P.quest_morning()                          # next morning — window still occupied
    assert not any("зреет дело" in n for n in news2)
    offered = [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"]
    assert len(offered) == 1 and offered[0]["id"] == first["id"]
    core._S["gt"] += (core.PB["quest_offer_days"] + 1) * 1440   # compost frees the window
    news3 = P.quest_morning()
    assert any("зреет дело" in n for n in news3)
    _advance_foreshadow()
    fresh = [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"] + \
            [c for c in town.contracts(core._wid(), "board") if c.get("src") == "sift"]
    assert len(fresh) == 1 and fresh[0]["id"] != first["id"]


def test_occupied_weak_candidate_blocks_no_llm(town, monkeypatch):
    """(a) window occupied, next morning's best fresh candidate is far below k×in-flight → quiet
    morning, incumbent untouched, and — crucially — NO LLM call at all (the judge is gated on the
    pure-code salience comparison BEFORE it would ever run)."""
    P.quest_morning()
    _advance_foreshadow()
    first = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")

    class _NoCallStub:
        def call(self, role, messages, **kw):                    # pragma: no cover — must never run
            raise AssertionError("LLM must not be called on a weak occupied morning")

    monkeypatch.setattr(core, "_model", lambda: _NoCallStub())
    monkeypatch.setattr(P.salience, "score", lambda s, ctx: s.__setitem__("score", 0.01) or 0.01)

    news = P.quest_morning()
    assert not any("зреет дело" in n for n in news)
    offered = [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"]
    assert len(offered) == 1 and offered[0]["id"] == first["id"]
    assert offered[0]["arc"]["beat"] == "offered"                 # untouched, not bumped


def test_occupied_strong_candidate_interrupts(town, monkeypatch):
    """(b) window occupied, a fresh candidate clears k×in-flight → INTERRUPT: the incumbent (Дунн,
    private/offered) returns to waiting ('queued', not composted); the strong new seed (Марта's
    broken_promise, public) proceeds through judge→framer→cast→persist→surface; exactly one
    offered/board sift contract remains at the end."""
    P.quest_morning()
    _advance_foreshadow()
    first = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    assert first["giver"] == "npc:dunn"

    orig_score = P.salience.score

    def _boost(seed, ctx):
        s = orig_score(seed, ctx)
        if seed["pattern"] == "broken_promise":
            s = seed["score"] = s * 1000.0               # dominates any k×in-flight threshold
        return s

    monkeypatch.setattr(P.salience, "score", _boost)
    news = P.quest_morning()
    assert any("зреет дело" in n for n in news)

    bumped = next(c for c in town.contracts(core._wid(), "queued") if c["id"] == first["id"])
    assert bumped["arc"]["beat"] == "foreshadow-pending"          # waiting, not composted

    _advance_foreshadow()                               # the interrupting seed's own foreshadow beat
    offered = [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"]
    board = [c for c in town.contracts(core._wid(), "board") if c.get("src") == "sift"]
    live = offered + board
    assert len(live) == 1                                         # exactly one live emergent offer
    assert live[0]["giver"] == "npc:marta" and live[0]["id"] != first["id"]
    assert board and board[0]["id"] == live[0]["id"]


def test_occupied_strong_interrupt_framer_fails_keeps_incumbent(town, monkeypatch):
    """(IMPORTANT fix) bump_weakest() must fire only after the interrupting seed's framer succeeds:
    if the framer raises LLMUnavailable mid-interrupt, the incumbent must NOT have been demoted —
    otherwise the window ends the morning with zero live offers and the demoted row is orphaned."""
    P.quest_morning()
    _advance_foreshadow()
    first = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    assert first["giver"] == "npc:dunn"

    orig_score = P.salience.score

    def _boost(seed, ctx):
        s = orig_score(seed, ctx)
        if seed["pattern"] == "broken_promise":
            s = seed["score"] = s * 1000.0               # dominates any k×in-flight threshold
        return s

    monkeypatch.setattr(P.salience, "score", _boost)

    class _FramerDownStub(_Stub):
        def call(self, role, messages, **kw):
            sys = messages[0]["content"]
            if "редактор" not in sys:                     # framer branch (judge already ranked it)
                from aidnd.inference.client import LLMUnavailable
                raise LLMUnavailable("no model")
            return super().call(role, messages, **kw)

    monkeypatch.setattr(core, "_model", lambda: _FramerDownStub())
    news = P.quest_morning()
    assert not any("зреет дело" in n for n in news)

    still_offered = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    assert still_offered["id"] == first["id"]
    assert still_offered["arc"]["beat"] == "offered"          # never bumped

    offered = [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"]
    board = [c for c in town.contracts(core._wid(), "board") if c.get("src") == "sift"]
    assert len(offered + board) == 1                          # exactly one live row, no orphan
    assert not [c for c in town.contracts(core._wid(), "queued") if c.get("src") == "sift"]


def test_expire_composts_stale_bumped_row_but_not_fresh(town):
    """(IMPORTANT fix) foreshadow-pending queued rows (bump_weakest's demoted incumbents) leak
    forever unless _expire_stale composts them too: a row bumped long ago closes on the next check;
    a freshly bumped row survives untouched."""
    gt = core._gt()
    old_cid = f"ct:sift:npc:dunn:{gt - (core.PB['quest_offer_days'] + 1) * 1440}"
    town.save_contract(core._wid(), old_cid, "queued",
                       {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн Ли",
                        "arc": {"beat": "foreshadow-pending"},
                        "seed": {"score": 1.0, "pattern": "kin_debt"}})
    fresh_cid = f"ct:sift:npc:marta:{gt}"
    town.save_contract(core._wid(), fresh_cid, "queued",
                       {"src": "sift", "giver": "npc:marta", "giver_name": "Марта Ли",
                        "arc": {"beat": "foreshadow-pending"},
                        "seed": {"score": 1.0, "pattern": "broken_promise"}})
    news = P._expire_stale()
    assert any("протух" in n or "сам" in n for n in news)
    closed = next(c for c in town.contracts(core._wid(), "closed") if c["id"] == old_cid)
    assert closed["arc"]["beat"] == "expired"
    still_queued = next(c for c in town.contracts(core._wid(), "queued") if c["id"] == fresh_cid)
    assert still_queued["arc"]["beat"] == "foreshadow-pending"


def test_bumped_contract_resurfaces_when_window_frees(town, monkeypatch):
    """(c) after the interrupt, composting the interrupter frees the window; the next morning the
    bumped Дунн material comes back through the ordinary sift/judge/framer path (the code does not
    keep a literal queued-row-replay — Task 14 scope — so this asserts the honest, actually-observed
    behavior: a fresh Дунн offer surfaces again. The old bumped row shares its birth gt with the
    interrupted offer, so once the same quest_offer_days elapse it composts too — no orphan leak."""
    P.quest_morning()
    _advance_foreshadow()
    first = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")

    orig_score = P.salience.score

    def _boost(seed, ctx):
        s = orig_score(seed, ctx)
        if seed["pattern"] == "broken_promise":
            s = seed["score"] = s * 1000.0
        return s

    monkeypatch.setattr(P.salience, "score", _boost)
    P.quest_morning()                                              # interrupt: Дунн bumped, Марта live
    bumped = next(c for c in town.contracts(core._wid(), "queued") if c["id"] == first["id"])
    assert bumped["arc"]["beat"] == "foreshadow-pending"
    _advance_foreshadow()                                            # Марта's own foreshadow beat

    monkeypatch.setattr(P.salience, "score", orig_score)            # back to real salience weights
    core._S["gt"] += (core.PB["quest_offer_days"] + 1) * 1440       # composts Марта's board offer
    news = P.quest_morning()
    assert any("зреет дело" in n for n in news)                     # window free → normal path resumed
    _advance_foreshadow()

    live = [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"] + \
           [c for c in town.contracts(core._wid(), "board") if c.get("src") == "sift"]
    assert len(live) == 1 and live[0]["giver"] == "npc:dunn"        # Дунн's material re-surfaced
    assert live[0]["id"] != first["id"]                             # via a fresh sift, not a row replay

    old_bumped = next(c for c in town.contracts(core._wid(), "closed") if c["id"] == first["id"])
    assert old_bumped["arc"]["beat"] == "expired"                   # composted, not left orphaned
    assert not [c for c in town.contracts(core._wid(), "queued") if c["id"] == first["id"]]


def test_llm_unavailable_in_quest_morning_returns_no_offer(town, monkeypatch):
    from aidnd.inference.client import LLMUnavailable

    class _DownStub:
        def call(self, role, messages, **kw):
            raise LLMUnavailable("no model")

    monkeypatch.setattr(core, "_model", lambda: _DownStub())
    news = P.quest_morning()
    assert news == []
    assert not [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"]
    assert not [c for c in town.contracts(core._wid(), "queued") if c.get("src") == "sift"]


class _PlanStub(_Stub):
    """Extends _Stub with the planner branch (_PLAN_SYS text) so quest_morning's new agenda-seeding
    step (pipeline._seed_agendas) gets a real milestone back — a delegatable 'acquire/have' goal that
    blocked_rival (seeds.py:pat_blocked_rival) can pick up (needs an OPEN delegatable milestone)."""

    def __init__(self):
        self.plan_calls = 0

    def call(self, role, messages, **kw):
        sys = messages[0]["content"]
        if "планировщик" in sys:
            self.plan_calls += 1
            return {"content": json.dumps({
                "summary": "разжиться кошелем", "kind": "predation", "importance": 0.8,
                "milestones": [{"desc": "стащить кошель", "goal": "acquire", "target": "кошель",
                                "meta": {}, "done": {"type": "have", "item": "кошель"}}],
            }, ensure_ascii=False)}
        return super().call(role, messages, **kw)


class _DownDuringPlanStub(_Stub):
    """Planner branch raises LLMUnavailable; judge/framer branches behave like _Stub (so the rest
    of the morning — sift over the fixture's pre-existing hooks — proceeds unaffected)."""

    def __init__(self):
        self.plan_calls = 0

    def call(self, role, messages, **kw):
        sys = messages[0]["content"]
        if "планировщик" in sys:
            self.plan_calls += 1
            from aidnd.inference.client import LLMUnavailable
            raise LLMUnavailable("no model")
        return super().call(role, messages, **kw)


def test_morning_seeds_agendas_for_agenda_less_npcs(town, monkeypatch):
    """(a) Two agenda-less rivals with a mutual grudge get planned via _seed_agendas; the planted
    delegatable milestone lets blocked_rival fire and the sift/judge/framer chain bind a contract."""
    stub = _PlanStub()
    monkeypatch.setattr(core, "_model", lambda: stub)
    core._S["people"]["npc:dunn"].state.agendas = []     # neutralize kin_debt/broken_promise/
    core._S["people"]["npc:ralf"].state.relationships = {"npc:marta": {"affinity": -0.4}}
    core._S["people"]["npc:marta"].state.relationships = {"npc:ralf": {"affinity": -0.3}}
    news = P.quest_morning()
    assert stub.plan_calls >= 1                          # at least one agenda-less NPC was planned
    got_agenda = any((p.state.agendas or []) for p in core._S["people"].values())
    assert got_agenda
    assert news                                            # sift/judge/framer bound the planted hook


def test_morning_skips_planning_for_npcs_with_live_agendas(town, monkeypatch):
    """(b) All three already carry a live agenda → _seed_agendas finds no candidates, no planner
    calls made (judge/framer calls from the normal sift path still happen)."""
    stub = _PlanStub()
    monkeypatch.setattr(core, "_model", lambda: stub)
    dummy = Milestone("держаться подальше", "need", "wealth", {}, {"type": "wealth", "value": 999})
    for p in core._S["people"].values():
        p.state.agendas = [Agenda("что-то своё", "ambition", 0.5, [dummy])]
    P.quest_morning()
    assert stub.plan_calls == 0


def test_morning_llm_unavailable_during_planning_does_not_crash(town, monkeypatch):
    """(c) Planner raises LLMUnavailable for the first agenda-less candidate → seeding stops quietly,
    no partial agenda is left on that NPC, and the morning continues (no crash; pre-existing hooks
    still produce the usual private offer)."""
    stub = _DownDuringPlanStub()
    monkeypatch.setattr(core, "_model", lambda: stub)
    news = P.quest_morning()
    assert stub.plan_calls >= 1
    assert not (core._S["people"]["npc:marta"].state.agendas or [])
    assert not (core._S["people"]["npc:ralf"].state.agendas or [])
    assert news                                            # dunn's pre-existing hook still surfaces


def test_expire_compost_closes_offer_and_keeps_agenda(town):
    P.quest_morning()
    _advance_foreshadow()
    ct = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    core._S["gt"] += (core.PB["quest_offer_days"] + 1) * 1440   # два дня спустя
    news = P._expire_stale()
    assert any("протух" in n or "сам" in n for n in news)
    assert not town.contracts(core._wid(), "offered")
    closed = next(c for c in town.contracts(core._wid(), "closed") if c["id"] == ct["id"])
    assert closed["arc"]["beat"] == "expired"
    assert core._S["people"]["npc:dunn"].state.agendas[0].cursor == 0   # агенда цела — сам займётся


def test_quiet_morning_still_rechecks_overtaken(town, monkeypatch):
    """FIX regression: the overtaken recheck used to run only at the tail of the FULL success path
    (a new quest surfacing) — every early return (no pool, quiet-occupied, judge-veto, admit-None,
    poor-giver, framer-fail) skipped it, so a live incumbent whose giver already resolved his own
    milestone stayed 'offered' forever unless some OTHER morning also produced a fresh quest. Drive
    it through the real quest_morning() entry: Дунн's incumbent offer is live, his agenda then
    advances past its anchoring milestone (self-resolved), and the morning has NO new candidates at
    all (sift patched empty) — an honest quiet morning. quest_morning() must still return the
    overtaken closing line and close the contract, with zero LLM calls anywhere in the turn."""
    P.quest_morning()
    _advance_foreshadow()
    first = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    assert first["giver"] == "npc:dunn"

    # Дунн сам раздобыл гроссбух — его агенда шагнула дальше пройденной вехи
    core._S["people"]["npc:dunn"].state.agendas[0].cursor = 1

    class _NoCallStub:
        def call(self, role, messages, **kw):                    # pragma: no cover — must never run
            raise AssertionError("LLM must not be called on a quiet overtaken-only morning")

    monkeypatch.setattr(core, "_model", lambda: _NoCallStub())
    monkeypatch.setattr(P, "_seed_agendas", lambda people, gt: None)   # no agenda-less seeding this morning
    monkeypatch.setattr(P.seeds, "sift", lambda *a, **k: [])            # no new candidates whatsoever

    news = P.quest_morning()
    assert any("улажено" in n or "поздно" in n for n in news)           # overtaken close still fires
    assert not any("зреет дело" in n for n in news)                     # honestly quiet — nothing new

    assert not [c for c in town.contracts(core._wid(), "offered") if c["id"] == first["id"]]
    closed = next(c for c in town.contracts(core._wid(), "closed") if c["id"] == first["id"])
    assert closed["arc"]["beat"] == "overtaken"


def test_allowed_widens_with_seed_summary_role_and_target(town):
    """The starvation bug: a wealth-milestone plain_need seed's ONLY villain/prize-derived allowed
    names are {giver, гильдия} — no LLM can pitch «накопить 15 монет» without naming the giver's own
    trade/venue/goal. _allowed must widen with sim-authored truth: the seed's summary (the giver's
    real Agenda.summary), his role, and the milestone target — never invented material."""
    core._S["people"]["npc:pit"] = _person(
        "npc:pit", "Ушлый Пит", "кузнец",
        agendas=[Agenda("Скопив денег, купить у кузнеца Айвора кинжал", "wealth", 0.6,
                        [Milestone("купить кинжал", "need", "wealth", {},
                                   {"type": "wealth", "value": 15})])])
    from aidnd.server.play.engine.quests import seeds as S
    seed = next(s for s in S.sift(core._S["people"], [], core._S["gt"])
                if s["giver"] == "npc:pit")
    allowed = P._allowed(seed)
    assert seed["summary"] == "Скопив денег, купить у кузнеца Айвора кинжал"
    assert allowed & {"кузнец", "кузнеца"}                       # role AND/OR summary tokens land
    assert any(a for a in allowed if "Айвор" in a)                # summary carries the named smith
    assert any(a for a in allowed if "кинжал" in a)               # summary carries the target item
    from aidnd.server.play.engine.quests import framing as F
    pitch = "Чужак, помоги мне — я коплю на кинжал у Айвора, кузнеца."
    assert F.valid_entities(pitch, allowed)
