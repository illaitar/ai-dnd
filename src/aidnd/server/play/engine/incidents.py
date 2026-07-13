"""City incidents — mini dungeons INSIDE the city, born from the global NPC simulation.

Each incident is tied to the living threads of the world (docs/dungeons.md "city"):
- location = home/work of a REAL resident (their node, their name in the quest header);
- patron = a live NPC — pays the reward from THEIR OWN wallet (guild — from guild coffers);
- gang = the townspeople themselves with malice: miller by day — thief by night; combat with them
  is real (death = dead flag, city loses a person); each morning the gang STEALS from neighbors
  (theft deeds from real actor → town gossip, shared stash grows, quest cost rises);
- haunt = home of someone who REALLY died in this world (dead flags — including victims of
  player contract murders: ordered assassination → victim's home is haunted → new quest);
- missing = resident is captured (captive flag — honestly disappears from city scenes), rescue
  returns them; stash = cache of stolen goods FROM deed journal (return to victims — real wallets).
The dungeon itself is a small dungeongen (city scale) with pool briefing. No LLM at runtime.

Key functions
-------------
incidents_active() -> list : Returns all active incidents in the world.
incident_spawn() -> list : Morning: spawn one incident from city life (max 2 active).
gang_morning() -> list : Daily escalation: active gangs steal coins & record deeds.
incident_jobs() -> list : Format incidents as guild board quests with CR & reward.
incident_resolve(inc_id, fell_members) -> list : Complete incident: reward patron,
                                                   free captive, return loot to victims.
"""

from __future__ import annotations

import json
import os
import random

from aidnd.server.play.engine.core import (
    _S,
    PB,
    _gt,
    _store,
    _wid,
)

_ICAT: dict | None = None


def _cat() -> list:
    global _ICAT
    if _ICAT is None:
        p = os.path.join(os.path.dirname(__file__), "..", "..", "..", "content",
                         "incidents.json")
        with open(p, encoding="utf-8") as f:
            _ICAT = json.load(f)
    return _ICAT["types"]


def incidents_active() -> list:
    return _store().contracts(_wid(), "incident")


def _flags(prefix: str) -> set:
    return {k.split("|", 1)[1] for k in _store().flags_prefix(_wid(), prefix)}


def _fam(name: str) -> str:
    return (name or "").split()[-1]


def _place_binding(inc: dict, t: dict) -> tuple[str | None, int | None]:
    """Resolve the incident's building id + door node from the victim/patron the generator already
    knows. Prose place stays; this adds the machine binding F4/board need. vacant/stash → no bid."""
    people = _S.get("people") or {}
    cr2b = _S.get("cr2b") or {}
    keynode = _S.get("keynode") or {}
    victim = t.get("victim")
    if victim == "work":
        pid = inc.get("patron")
        p = people.get(pid)
        bid = p.work if p is not None else None
        return bid, (keynode.get(bid) if bid else None)
    if victim in ("home", "dead_home"):
        # dead_home stores the dead resident's name; the home node is that resident's .home
        pid = inc.get("patron") if victim == "home" else None
        if victim == "dead_home":
            pid = next((k for k, pp in people.items()
                        if _fam(pp.name) == _fam(inc.get("dead_name", ""))), None) or inc.get("patron")
        p = people.get(pid)
        node = getattr(p, "home", None) if p is not None else None
        return (cr2b.get(node) if node is not None else None), node
    return None, None


def incident_spawn() -> list:
    """Morning: world spawns an incident from city LIFE (≤2 active, chance per day)."""
    people = _S.get("people") or {}
    if not people:
        return []
    act = incidents_active()
    day = _gt() // 1440
    if len(act) >= 2 or random.Random(f"incday|{_wid()}|{day}").random() > PB["incident_p"]:
        return []
    rng = random.Random(f"inc|{_wid()}|{day}")
    dead = _flags("dead|")
    gone = dead | _flags("captive|")
    alive = {pid: p for pid, p in sorted(people.items()) if pid not in gone}
    types = list(_cat())
    rng.shuffle(types)
    types.sort(key=lambda t: -t["w"] * rng.random())
    for t in types:
        inc = _try_build(t, alive, dead, rng)
        if inc:
            iid = f"inc|{day}|{t['key']}"
            _store().save_contract(_wid(), iid, "incident", inc)
            if inc.get("captive"):
                _store().flag_set(_wid(), f"captive|{inc['captive']}")
            return [inc["news"]]
    return []


def _try_build(t: dict, alive: dict, dead: set, rng) -> dict | None:
    people = _S.get("people") or {}
    cr = round(rng.uniform(*t["cr"]), 2)
    inc = {"type": t["key"], "goal": t["goal"], "env": t["env"], "cr": cr,
           "esc": t.get("esc", False), "made_gt": _gt(), "stash": 0, "members": [],
           "captive": None, "patron": None, "giver": "guild"}
    if t["victim"] == "dead_home":                    # home of someone who actually died in THIS world
        if not dead:
            return None
        vid = rng.choice(sorted(dead))
        vic = people.get(vid)
        if vic is None:
            return None
        inc["place"] = f"дом, где жил {vic.name}"
        inc["dead_name"] = vic.name
        kin = [pid for pid, p in alive.items()
               if _fam(p.name) == _fam(vic.name) and pid != vid]
        inc["patron"] = kin[0] if kin else None
    elif t["victim"] in ("home", "work"):             # home/homestead of a real resident
        pool_p = [pid for pid, p in alive.items()
                  if p.persona and (t["victim"] == "home" or p.work)]
        if not pool_p:
            return None
        pid = rng.choice(pool_p)
        p = people[pid]
        inc["patron"] = pid
        inc["giver"] = pid                            # pays from THEIR OWN wallet
        inc["place"] = (f"подворье, где трудится {p.name}" if t["victim"] == "work"
                        else f"дом семьи {_fam(p.name)}")
        if t["goal"] == "rescue":                     # patron's relative is kidnapped
            kin = [k for k, pp in alive.items()
                   if _fam(pp.name) == _fam(p.name) and k != pid]
            if not kin:
                return None
            inc["captive"] = rng.choice(kin)
            inc["captive_name"] = people[inc["captive"]].name
    elif t["victim"] == "vacant":
        inc["place"] = "заброшенный дом у стены"
    if t["foe"] == "citizens":                        # gang of their own: townspeople with malice
        rogues = [pid for pid, p in alive.items()
                  if p.state.config.traits.get("malice", 0.5) >= PB["incident_gang_malice"]
                  and p.role not in ("стражник",) and pid != inc.get("patron")]
        if len(rogues) < 2:
            return None
        inc["members"] = rng.sample(rogues, min(4, max(2, len(rogues) // 3 or 2)))
        inc["chief"] = max(inc["members"],
                           key=lambda m: people[m].state.config.traits.get("malice", 0))
    if t["key"] == "stash":                           # thief's cache from deed journal
        thefts = [d for d in _store().deeds(_wid(), verb="theft", limit=30)
                  if d["actor"] in alive]
        if not thefts:
            return None
        thief = thefts[0]["actor"]
        inc["members"] = [thief]
        inc["chief"] = thief
        inc["stash"] = 6 + int(cr * 8)
        inc["victims"] = list({d["obj"] for d in thefts if d["actor"] == thief
                               and d["obj"] in alive})[:3]
    inc["bid"], inc["node"] = _place_binding(inc, t)   # machine binding for board/F4 (prose stays)
    pn = people.get(inc["patron"])
    subs = {"patron": pn.name if pn else "гильдия", "place": inc.get("place", ""),
            "dead": inc.get("dead_name", ""), "captive": inc.get("captive_name", "")}
    inc["title"] = t["title"].format(**subs)
    inc["pitch"] = t["pitch"].format(**subs)
    reward = max(2, round(cr * PB["guild_reward_per_cr"]))
    if inc["giver"] != "guild":                       # personal quest — clamped by wallet
        reward = max(2, min(reward, _store().purse_get(_wid(), inc["giver"])))
    inc["reward"] = reward
    inc["news"] = f"Город гудит: {inc['title']} — {subs['patron']} ищет смельчака"
    return inc


def gang_morning() -> list:
    """Escalation: active gang steals from NEIGHBORS — real coins, real deeds."""
    from aidnd.server.play.engine import deeds as _deeds

    people = _S.get("people") or {}
    news = []
    for inc in incidents_active():
        if not inc.get("esc") or not inc.get("members"):
            continue
        day = _gt() // 1440
        rng = random.Random(f"gangsteal|{inc['id']}|{day}")
        marks = [pid for pid in sorted(people)
                 if pid not in inc["members"] and _store().purse_get(_wid(), pid) > 2]
        if not marks:
            continue
        mark = rng.choice(marks)
        take = min(3, _store().purse_get(_wid(), mark))
        _store().purse_add(_wid(), mark, -take)
        actor = rng.choice(inc["members"])
        d = {k: v for k, v in inc.items() if k not in ("id", "status")}
        d["stash"] = d.get("stash", 0) + take
        d["reward"] = d.get("reward", 4) + 1          # city grows angry — quest costs more
        _store().save_contract(_wid(), inc["id"], "incident", d)
        _deeds.record(actor, "theft", obj=mark, place="ночная улица", witnesses=[],
                      data={"coins": take, "gang": inc["id"]})
        people[mark].state.memory.add("ночью обчистили мой дом — шайка распоясалась",
                                      _gt() // 10, 0.8)
        news.append(f"ночью обчистили дом ({people[mark].name}) — шайка наглеет")
    return news


def incident_jobs() -> list:
    """Format incidents as guild board quests (alongside lairs) — with a real direction to the site."""
    from aidnd.server.play.engine import geo

    people = _S.get("people") or {}
    loc = _S.get("loc")
    out = []
    for inc in incidents_active():
        pn = people.get(inc.get("patron"))
        pitch = inc["pitch"]
        bid = inc.get("bid")
        if bid and loc is not None:                    # append the true way there (F5)
            d = geo.direction_line(loc, bid)
            if d and d != "это на другом конце города":
                pitch = f"{pitch} — {d}"
        out.append({"id": f"ct:inc:{inc['id']}", "lair": inc["id"], "name": inc["title"],
                    "cr": inc["cr"], "reward": inc.get("reward", 4),
                    "kind": inc["goal"], "pitch": pitch,
                    "giver_name": pn.name if pn else "гильдия", "incident": True,
                    "bid": bid, "node": inc.get("node")})
    return out


def incident_resolve(inc_id: str, fell_members: list) -> list:
    """Quest complete: reward (patron/guild wallet), captive freed, stolen goods —
    to victims, city remembers. Fallen gang members — real dead of the city."""
    from aidnd.server.play.engine import deeds as _deeds

    people = _S.get("people") or {}
    inc = next((x for x in incidents_active() if x["id"] == inc_id), None)
    if not inc:
        return []
    narr = []
    reward = inc.get("reward", 4)
    giver = inc.get("giver", "guild")
    pay = min(reward, _store().purse_get(_wid(), giver)) if giver != "guild" else reward
    src = people[giver].name if giver in people else "Гильдия"
    _store().purse_add(_wid(), giver if giver != "guild" else "guild", -pay)
    total = _store().purse_add(_wid(), "pc", pay)
    narr.append(f"{src} платит уговорённое: +{pay} зм (кошель: {total}).")
    if inc.get("captive"):
        _store().flag_del(_wid(), f"captive|{inc['captive']}")
        nm = inc.get("captive_name", "спасённый")
        narr.append(f"{nm} на свободе — сам доберётся до родни, а те не забудут.")
        for _pid, p in people.items():
            if _fam(p.name) == _fam(nm):
                rel = p.state.rel("pc")
                rel["affinity"] = min(1.0, rel["affinity"] + 0.35)
                p.state.memory.add(f"этот человек вернул нам {nm}", _gt() // 10, 0.9,
                                   about=["pc"])
    if inc.get("stash"):
        cut = inc["stash"] // 3
        back = inc["stash"] - cut
        for vid in inc.get("victims") or []:
            _store().purse_add(_wid(), vid, back // max(1, len(inc.get("victims") or [1])))
            if vid in people:
                people[vid].state.memory.add("мне вернули украденное!", _gt() // 10, 0.8,
                                             about=["pc"])
        _store().purse_add(_wid(), "pc", cut)
        narr.append(f"Схрон: {back} зм возвращаются людям, твоя доля — {cut} зм.")
    for pid in fell_members:                          # fallen — real dead of the city
        if pid in people:
            _store().flag_set(_wid(), f"dead|{pid}")
            _deeds.record("pc", "clear", obj=pid, place=inc.get("place", ""),
                          witnesses=[], data={"incident": inc_id})
    if inc.get("patron") in people:
        p = people[inc["patron"]]
        rel = p.state.rel("pc")
        rel["affinity"] = min(1.0, rel["affinity"] + 0.3)
        p.state.memory.add(f"он разобрался: {inc['title']}", _gt() // 10, 0.85, about=["pc"])
    _deeds.record("pc", "clear", obj=inc["title"], place=inc.get("place", ""), witnesses=[])
    d = {k: v for k, v in inc.items() if k not in ("id", "status")}
    _store().save_contract(_wid(), inc["id"], "inc_done", d)
    return narr
