"""Morning orchestration (spec §3a/§5). Inc 2: window=1 hardcoded (exactly one seed surfaces per
morning; the director in Inc 3 replaces this). No LLM at either seam → honest absence, boards continue.

  sift → salience → judge → framer → casting → save_contract(status='queued') → surface (private/public)
  + expiry-compost of offers older than quest_offer_days (giver keeps his agenda; no board leak).
"""

from __future__ import annotations

import logging
import random

from aidnd.inference.client import LLMUnavailable
from aidnd.mind import World as MWorld
from aidnd.mind.llm_agent import plan_agenda
from aidnd.server.play.engine import core
from aidnd.server.play.engine.core import _S, PB, _binfo, _gt, _store, _wid
from aidnd.server.play.engine.quests import bridge, casting, framing, salience, seeds

log = logging.getLogger("aidnd.quests")

PUBLIC_PATTERNS = {"broken_promise", "unanswered_blood"}
GRIEVANCE_PATTERNS = {"broken_promise", "unanswered_blood"}   # no pre-existing giver milestone


def _ensure_milestone(seed: dict) -> None:
    """Grievance patterns (broken_promise/unanswered_blood) name a revenge predicate but the giver
    carries NO milestone for it. Insert a real revenge Agenda into the giver's LIVE state so
    done_any[0] lifts verbatim from a real milestone and the Inc-1 writeback advances a real cursor
    uniformly (spec §4 'each enforced disjunct is a real _met dict' + the honest bridge).

    Persistence mirrors deals.py:155 EXACTLY: the agenda is inserted into the in-memory
    _S["people"][giver].state.agendas and lives there for the session. save_npc_state intentionally
    persists only relationships/needs/memory — NOT agendas — so deals.py's hired-agenda and this
    revenge-agenda both survive purely on the live pool wrapper. No new persistence is invented."""
    if seed["pattern"] not in GRIEVANCE_PATTERNS:
        return                                       # milestone-anchored: giver already carries it
    from aidnd.mind.agenda import Agenda, Milestone
    giver = (_S.get("people") or {})[seed["giver"]]
    st = giver.state
    if st.agendas is None:
        st.agendas = []
    villain = seed["cast"].get("villain")
    done = dict(seed["goal"]["done"])                # the intended revenge predicate (real _met dict)
    for i, ag in enumerate(st.agendas):              # idempotent: reuse a matching live revenge agenda
        if getattr(ag, "status", "active") == "active" and ag.current() and ag.current().done == done:
            tag = f"agenda:{seed['giver']}:{i}"
            if tag not in seed["evidence"]:
                seed["evidence"].append(tag)
            return
    ms = Milestone(desc=f"свести счёты с обидчиком ({villain})", kind="harm",
                   target=villain, done=done)
    idx = len(st.agendas)
    # seed["summary"] IS this exact grievance text (seeds.py:_revenge_summary) — single source of truth
    st.agendas.append(Agenda(summary=seed.get("summary") or f"расквитаться с {villain} за нарушенное слово",
                             kind="revenge", importance=0.8, milestones=[ms]))
    seed["evidence"].append(f"agenda:{seed['giver']}:{idx}")   # anchor for bridge._anchor_idx


def _names() -> dict:
    return {pid: p.name for pid, p in (_S.get("people") or {}).items()}


def _adjacent(city, a, b) -> bool:
    if city is None or a is None or b is None:
        return False
    try:
        return any({e.a, e.b} == {a, b} for e in city.edges())
    except Exception:                               # noqa: BLE001 — graph shape guard
        return False


def _ctx(chosen_deeds: dict, gt: int) -> dict:
    people = _S.get("people") or {}
    crof, loc, city = _S.get("crof") or {}, _S.get("loc"), _S.get("city")
    aff = {}
    for pid, p in people.items():
        for other, rel in (p.state.relationships or {}).items():
            aff[(pid, other)] = rel.get("affinity", 0.0)
    prox = {pid: salience.proximity(crof.get(pid), loc, _adjacent(city, crof.get(pid), loc))
            for pid in people}
    recent = {}
    for pat in ("kin_debt", "broken_promise", "blocked_rival", "unanswered_blood", "courtship_wall",
                "plain_need"):
        recent[pat] = int(_store().flag_get(_wid(), f"qrecent|{pat}") or 0)
    return {"recent": recent, "aff_edges": aff, "deeds": chosen_deeds, "prox": prox, "now_gt": gt}


def _allowed(seed: dict) -> set:
    """Sim-authored truth only, never invention (spec: no mechanical gates). The judge's `why` is
    ONE editorial flourish per spec §5 Step 3 — it never widened `allowed` (nothing to whitelist from
    it). A plain_need seed's real content is the giver's own life-goal (Agenda.summary from
    plan_agenda), his role, his home/work venue, and the milestone's target — all honest sim state
    the framer needs in order to write ABOUT the goal instead of just naming the giver."""
    names = _names()
    out = {seed["giver_name"]}
    for r in ("villain", "prize"):
        nm = names.get(seed["cast"].get(r))
        if nm:
            out.add(nm)
    done = seed["goal"]["done"]
    if done.get("type") == "have" and done.get("item"):
        out.add(str(done["item"]))
    out.add("гильдия")
    summary = seed.get("summary")
    if summary:
        out.add(summary)                              # tokenizes via _stem4 — whitelists its words
    people = _S.get("people") or {}
    giver = people.get(seed["giver"])
    if giver is not None:
        if getattr(giver, "role", None):
            out.add(giver.role)
        if getattr(giver, "work", None):
            out.add(_binfo(giver.work)["name"])
    target = seed.get("goal", {}).get("target")
    if isinstance(target, str) and target:
        out.add(target)
    return out


def _reward(seed: dict, cast: dict) -> tuple | None:
    """Reward shape (spec §5 Step 4 + carried review): coins from casting when the giver can pay;
    a poor PRIVATE giver (purse < contract_poor_purse) pays with a real item from his own inventory,
    mirroring _make_contract (contracts.py:180-188). Private giver with neither coins nor item →
    None (seed skipped). Public patterns are community bounties — no personal-funding gate."""
    giver = seed["giver"]
    purse = _store().purse_get(_wid(), giver)
    if seed["pattern"] in PUBLIC_PATTERNS or purse >= PB["contract_poor_purse"]:
        return cast["reward"], None, None
    rows = [(r["item_id"], _store().get_item(r["item_id"]))
            for r in _store().inventory(_wid(), giver)]
    rows = [(i, it) for i, it in rows if it and it.get("kind") != "key"]
    if not rows:
        return None
    item_id, it = max(rows, key=lambda x: x[1].get("worth", 0))
    return 0, item_id, it.get("name")


def _has_hook(persona: dict) -> bool:
    """Persona material a life-goal can hang on: something the NPC wants/covets (real fields written
    by worldgen persona_llm.py — wants/valuables), not a placeholder empty persona."""
    return bool((persona or {}).get("wants")) or bool((persona or {}).get("valuables"))


def _has_grudge(state) -> bool:
    return any(rel.get("affinity", 0.0) < -0.2 for rel in (state.relationships or {}).values())


def _plan_candidates(people: dict, gt: int) -> list[str]:
    """Up to quest_plan_n agenda-less NPCs with persona material (wants/valuables) or a grudge
    (affinity edge < -0.2) — deterministic order seeded by the day, no live agenda already."""
    day = gt // 1440
    pool = [pid for pid, p in sorted(people.items())
            if not any(getattr(ag, "status", "active") == "active" for ag in (p.state.agendas or []))
            and (_has_hook(p.persona) or _has_grudge(p.state))]
    random.Random(f"plan|{day}").shuffle(pool)
    return pool[:PB["quest_plan_n"]]


def _seed_agendas(people: dict, gt: int) -> None:
    """Morning agenda seeding: give up to quest_plan_n agenda-less NPCs a life-goal so the sifter has
    material to work with (patterns need an OPEN milestone — seeds.py:_open_milestone). Mirrors
    _make_contract's lazy plan_agenda call (contracts.py:172-175) exactly: same MWorld() stub, same
    ctx shape. Populates state.agendas in memory only — same lifecycle as deals.py:155 (no new
    persistence; save_npc_state deliberately never writes agendas)."""
    cands = _plan_candidates(people, gt)
    if not cands:
        return
    mgr = core._model()
    for pid in cands:
        p = people[pid]
        try:
            ag = plan_agenda(p.state, MWorld(), {"roles": {pid: p.role}}, mgr)
        except LLMUnavailable:
            log.info("quests: LLM недоступен — посев агенд прерван на %s", pid)
            return
        if ag:
            if p.state.agendas is None:
                p.state.agendas = []
            p.state.agendas.append(ag)


def quest_morning() -> list[str]:
    from aidnd.server.play.engine.quests import director

    people = _S.get("people") or {}
    if not people:
        return []
    news = _expire_stale()                            # compost first — frees the window this morning
    gt = _gt()
    occupied = director.window_occupied()             # beat-aware — a bumped waiter never blocks it
    if not occupied:
        _seed_agendas(people, gt)                      # NPCs without a live agenda get one (quest_plan_n)
    raw = _store().deeds(_wid(), since_gt=gt - salience.FRESH_DAYS * 1440, limit=60)
    deeds_by_id = {d["id"]: d for d in raw}
    pool = seeds.sift(people, raw, gt, flag_get=lambda k: _store().flag_get(_wid(), k))
    if not pool:
        return news
    ctx = _ctx(deeds_by_id, gt)
    for s in pool:
        salience.score(s, ctx)
    pool.sort(key=lambda s: -s["score"])
    if occupied and not director.would_interrupt(pool[0]["score"]):
        return news                                   # quiet morning — no judge/framer LLM calls at all
    topk = pool[:PB["quest_topk"]]
    try:
        kept = framing.judge(topk, deeds_by_id, _names(), core._model())
    except LLMUnavailable:
        log.info("quests: LLM недоступен — судья пропущен, утро без нового дела")
        return news
    if not kept:
        return news
    admitted = director.admit(kept)                  # window/interrupt decision (replaces [:1])
    if admitted is None:
        return news
    seed = admitted
    try:
        art = framing.framer(seed, _allowed(seed), core._model())
    except LLMUnavailable:
        log.info("quests: LLM недоступен — фреймер пропущен, утро без нового дела")
        return news
    if not art:
        return news
    _ensure_milestone(seed)                          # grievance patterns: materialize a real milestone
    giver = people[seed["giver"]]
    villain = people.get(seed["cast"].get("villain"))
    c = casting.cast(seed, giver.state, villain.state if villain else None, _store(), _wid())
    rw = _reward(seed, c)
    if rw is None:                                   # poor private giver, no item — honest skip
        log.info("quests: seed %s пропущен — заказчику нечем платить", seed.get("sid"))
        return news
    reward, reward_item, reward_name = rw
    from aidnd.mind.agenda import Milestone
    m = Milestone(desc="", kind=seed["goal"]["kind"], target=seed["goal"]["target"],
                  done=dict(seed["goal"]["done"]))
    cid = f"ct:sift:{seed['giver']}:{gt}"
    roles = {"giver": seed["giver"], "villain": seed["cast"].get("villain"),
             "prize": seed["cast"].get("prize")}
    data = {"giver": seed["giver"], "giver_name": seed["giver_name"],
            "step": 0, "steps": [c["step"]], **c["step"],
            "reward": reward, "reward_item": reward_item, "reward_name": reward_name,
            "pitch": art["pitch"], "why": seed["giver_name"],
            "src": "sift", "seed": seed, "arc": {"beat": "foreshadow"}, "roles": roles,
            "done_any": bridge.make_done_any(m),
            "framer": art, "dc": c["dc"]}
    if occupied:
        director.bump_weakest()                       # everything that could fail has succeeded —
                                                        # only now demote the incumbent to waiting
    _store().save_contract(_wid(), cid, "queued", data)
    _store().flag_set(_wid(), f"qrecent|{seed['pattern']}",
                      str(int(_store().flag_get(_wid(), f"qrecent|{seed['pattern']}") or 0) + 1))
    _surface(cid, {"id": cid, "status": "queued", **data})
    news.append(f"в городе зреет дело: {seed['giver_name']} ищет, кому довериться")
    return news + director.tick_morning()


def _surface(cid: str, ct: dict) -> None:
    """Promote a queued emergent contract to the player (Inc 2: immediately; Inc 3: director-timed).
    Private → status 'offered' (dialogue's contract_accept picks it up); public grievance/bounty →
    status 'board' (merges onto the shared board)."""
    data = {k: v for k, v in ct.items() if k not in ("id", "status")}
    data["arc"] = {"beat": "offered"}
    if ct["seed"]["pattern"] in PUBLIC_PATTERNS:
        _store().save_contract(_wid(), cid, "board", data)
    else:
        _store().save_contract(_wid(), cid, "offered", data)


def _expire_stale() -> list[str]:
    """Compost: an emergent offer unaccepted for quest_offer_days closes; the giver keeps his agenda
    (he acts on it himself → new deeds → next sift). Private grief never leaks to a public board.

    Also composts bumped rows ('queued', arc.beat='foreshadow-pending'): bump_weakest() only demotes
    them out of the director's window — nothing else ever re-surfaces or closes them, so without this
    they'd sit forever as orphaned rows. Same age/compost semantics as a live offer; the giver keeps
    his agenda either way."""
    gt, news = _gt(), []
    for status in ("offered", "board", "queued"):
        for ct in _store().contracts(_wid(), status):
            if ct.get("src") != "sift":
                continue
            if status == "queued" and (ct.get("arc") or {}).get("beat") != "foreshadow-pending":
                continue                              # freshly queued (not yet surfaced) — leave alone
            try:
                born = int(str(ct["id"]).rsplit(":", 1)[-1])
            except (ValueError, IndexError):
                continue
            if gt - born < PB["quest_offer_days"] * 1440:
                continue
            data = {k: v for k, v in ct.items() if k not in ("id", "status")}
            data["arc"] = {"beat": "expired"}
            _store().save_contract(_wid(), ct["id"], "closed", data)
            news.append(f"{ct.get('giver_name', 'кто-то')} махнул рукой — займётся делом сам")
    return news


def _recheck_overtaken() -> list[str]:
    """Morning evidence re-check per live seed (filled in Task 14)."""
    return []
