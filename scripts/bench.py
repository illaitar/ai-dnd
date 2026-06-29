"""Раннер бенчмарка NPC-взаимодействий: гоняет сценарии ОНЛАЙН (живой DeepSeek) и возвращает транскрипты.

Мир строится офлайн (быстро, без генерации через LLM), затем к сессии цепляется онлайн-менеджер — так
LLM зовётся только на сам ДИАЛОГ/реакцию, а не на пре-ген мира (иначе 200 прогонов = разорение).

Спека сценария (JSON): {id, kind: player|npc_npc, category, intent, setup, script|rounds}.
  setup: {seed?, place, target?, npcs?, player_rel?{trust,affinity,fear}, opinions?{a:{b:v}}, needs?{npc:{k:v}}, wallets?{npc:{...}}}
  player: script — список реплик игрока (строка → _do_talk к target; {"cmd": "..."} → handle).
  npc_npc: rounds — сколько тиков соц-жизни наблюдать.
Запуск:  AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=... python scripts/bench.py specs.json > out.json
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("AIDND_PROFILE", "deepseek")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.bootstrap import new_session  # noqa: E402
from aidnd.inference import ModelManager  # noqa: E402
from aidnd.runtime.orchestrator import Action  # noqa: E402

_MGR = None


def _mgr():
    global _MGR
    if _MGR is None:
        _MGR = ModelManager()
    return _MGR


def _apply_setup(s, setup: dict) -> None:
    from aidnd.content.agent import set_opinion
    from aidnd.npc.integration import npc_state
    from aidnd.world.components import Relationships, RelEdge
    place = setup.get("place")
    if place:
        pos = s.world.position(s.player)
        if pos:
            pos.place_id = place
    movers = list(setup.get("npcs") or [])
    if setup.get("target"):
        movers.append(setup["target"])
    for n in movers:                                       # свести участников в одно место
        p = s.world.position(n)
        if p and place:
            p.place_id = place
    pr, tgt = setup.get("player_rel"), setup.get("target")
    if pr and tgt:
        r = s.world.ecs.get(tgt, Relationships) or Relationships()
        s.world.ecs.add(tgt, r)
        r.edges[s.player] = RelEdge(**pr)
    for a, d in (setup.get("opinions") or {}).items():
        for b, v in d.items():
            set_opinion(s.world, a, b, v)
    for n, d in (setup.get("needs") or {}).items():
        npc_state(s.world, n).needs.update(d)
    for n, w in (setup.get("wallets") or {}).items():
        s.world.wallets[n] = w


def run(spec: dict) -> dict:
    tr = []
    try:
        s = new_session(seed=int(spec.get("seed", 1337)), roster_size=8, use_model=False)
        s.model = _mgr()                                   # офлайн-мир + онлайн-диалог
        _apply_setup(s, spec.get("setup", {}))
        if spec["kind"] == "player":
            tgt = (spec.get("setup") or {}).get("target")
            if tgt:                                        # расписание перетирает ручную расстановку и шлёт NPC «в путь»:
                s.npcs_here()                              # дать расписанию отработать (позиции + transits)
                tp = s.world.position(tgt)
                if tp:
                    s._road = None
                    s.world.position(s.player).place_id = tp.place_id          # идём ТУДА, где NPC реально осел
                    (getattr(s.world, "transits", None) or {}).pop(tgt, None)  # «прибыл» — снять с улицы
            for step in spec.get("script", []):
                if isinstance(step, dict):                 # произвольная команда через интент
                    r = s.handle(step.get("cmd", "")) or {}
                    tr.append({"cmd": step.get("cmd"), "reply": r.get("text") or "", "kind": r.get("kind")})
                else:
                    r = s._do_talk(Action(actor=s.player, verb="talk", target=tgt), step)
                    tr.append({"player": step, "reply": r.get("text") or "",
                               "phase": r.get("phase"), "topics": r.get("topics")})
        elif spec["kind"] == "npc_npc":
            from aidnd.content import agent as _ag
            from aidnd.content import dialogue_fsm
            npcs = (spec.get("setup") or {}).get("npcs") or []
            a = npcs[0] if npcs else None
            b = npcs[1] if len(npcs) > 1 else None
            for _ in range(int(spec.get("rounds", 6))):    # ВЕДЁМ ЗАДАННУЮ ПАРУ через FSM (не случайный амбиент)
                if a and b:
                    conv = s._npc_convo(a, b)
                    dialogue_fsm.advance(s.world, conv, a, b, s.player)
                    pa = _ag.choose(s.world, a, [b])
                    pb = _ag.choose(s.world, b, [a])
                    row = {"a": _ag._name(s.world, a), "b": _ag._name(s.world, b),
                           "phase": conv.phase, "track": conv.track,
                           "a_does": pa[0] if pa else None, "b_does": pb[0] if pb else None}
                    if pa and pa[0] == "gossip":           # о ком и каким тоном сплетничает a
                        c, v = _ag._strongest_opinion(s.world, a, b)
                        row["gossip_about"] = _ag._name(s.world, c) if c else None
                        row["tone"] = "чернит" if v < 0 else "хвалит"
                    if pa and pa[0] == "commission":       # реально провести сделку (оплата + мастер в работу)
                        row["commission_fired"] = _ag._commission_x(s.world, a, b)
                    tr.append(row)
                s._tick(1)
    except Exception as e:  # noqa: BLE001
        tr.append({"error": f"{type(e).__name__}: {e}"})
    return {"id": spec.get("id"), "category": spec.get("category"), "kind": spec.get("kind"),
            "intent": spec.get("intent"), "transcript": tr}


def main() -> None:
    specs = json.load(open(sys.argv[1], encoding="utf-8"))
    if isinstance(specs, dict):
        specs = [specs]
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6   # онлайн-вызовы I/O-bound → параллелим
    out = [None] * len(specs)
    if workers > 1:
        new_session(seed=1, roster_size=8, use_model=False)  # прогрев ленивых модулей (citygen и пр.) до пула
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, res in zip(range(len(specs)), ex.map(run, specs)):
                out[i] = res
    else:
        out = [run(sp) for sp in specs]
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
