"""Драйвер ЖИВОЙ игры для плейтеста: гоняет список команд через GameSession.handle ОНЛАЙН,
честно кидает кости на броски, ведёт компактный лог + состояние, персистит сессию между запусками
(сейв-слот 'live'), чтобы играть адаптивно по чанкам.

  AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=... python scripts/play.py commands.json
commands.json — JSON-список строк-команд игрока. Лог дописывается в playtest_live.txt; N — в playtest_live.n.
"""
from __future__ import annotations

import json
import os
import sys
import traceback

os.environ.setdefault("AIDND_PROFILE", "deepseek")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd import config  # noqa: E402
from aidnd.bootstrap import new_session  # noqa: E402
from aidnd.runtime.persistence import load_session, save_session  # noqa: E402

SLOT = "live"
LOGF = os.path.join(os.path.dirname(__file__), "..", "playtest_live.txt")
NF = os.path.join(os.path.dirname(__file__), "..", "playtest_live.n")
ANOM: list[str] = []


def _state(s) -> str:
    from aidnd.inventory.items import wallet_value_cp
    from aidnd.world.components import Stats5e
    try:
        place = s._place_name(s.current_place()) if s.current_place() else ("улица" if s._road is not None else "?")
    except Exception:
        place = "?"
    st = s.world.ecs.get(s.player, Stats5e)
    hp = f"{st.hp}/{st.max_hp}" if st else "?"
    gp = round(wallet_value_cp(s.world.wallets.get(s.player, {})) / 100, 1)
    day = s.world.clock.tick * config.SIM_MINUTES_PER_TICK // (24 * 60) + 1
    m = (s.world.clock.tick * config.SIM_MINUTES_PER_TICK) % (24 * 60)
    here = [s._display(n) for n in s.npcs_here() if n != s.player][:5]
    combat = "⚔БОЙ" if (s.combat and s.combat.state.mode == "active") else ""
    return (f"📍{place} {m // 60:02d}:{m % 60:02d} д{day} | hp {hp} gp {gp} {combat} "
            f"| рядом: {', '.join(here) or '—'}")


def _txt(r: dict) -> str:
    return (r.get("text") or r.get("narration") or r.get("hint") or "").strip()


def _drive_combat(s) -> str:
    """Авто-вести бой структурным API (бьём ближайшего, при нужде подходим), честные кости."""
    log = [f"⚔ БОЙ против {[s._display(e) for e in s.combat.alive_enemies()]}"]
    for _ in range(150):
        cs = s.combat.state
        if cs.mode != "active":
            break
        if not s.combat.is_pc_turn():
            s.combat_end_turn()
            continue
        cv = s.combat_view()
        if cv.get("targets") and "attack" in (cv.get("actions") or []):
            rr = s.combat_attack(cv["targets"][0])
            if s.pending_roll or (rr or {}).get("roll_request"):
                t = _txt(s.handle("кидаю") or {})
                if t and len(log) < 14:
                    log.append("· " + t[:120])
            continue
        en = [c for c in cv["combatants"] if c["side"] == "enemy" and not c.get("fled") and c["hp"] > 0]
        reach = cv.get("reachable") or []
        if en and reach and "move" in (cv.get("actions") or []):
            ex, ey = en[0]["pos"]
            s.combat_move(min(reach, key=lambda c: abs(c[0] - ex) + abs(c[1] - ey)))
            continue
        s.combat_end_turn()
    log.append(f"⚔ ИСХОД: {s.combat.state.outcome} (hp игрока {s.world.ecs.get(s.player, __import__('aidnd.world.components', fromlist=['Stats5e']).Stats5e).hp})")
    s.combat = None
    return "\n    ".join(log)


def main() -> None:
    cmds = json.load(open(sys.argv[1], encoding="utf-8"))
    fresh = not os.path.exists(os.path.join(config.SAVE_DIR, SLOT + ".json"))
    if fresh:
        s = new_session(seed=20240630, roster_size=8, use_model=True)
    else:
        s = load_session(SLOT, use_model=True)
    n = int(open(NF).read().strip()) if os.path.exists(NF) else 0
    log = open(LOGF, "a", encoding="utf-8")

    def out(line: str) -> None:
        print(line)
        log.write(line + "\n")
        log.flush()

    if fresh:
        out("\n========== НОВАЯ ПАРТИЯ ==========")
        out("  " + _state(s))
    for cmd in cmds:
        n += 1
        try:
            if cmd.startswith("@travel:"):                          # путешествие к сайту (API, не текст)
                r = s.travel_to(cmd.split(":", 1)[1]) or {}
            else:
                r = s.handle(cmd) or {}
            body = _txt(r)
            if r.get("kind") == "roll_request" or s.pending_roll:    # на бросок — честно кидаем (один раз)
                r2 = s.handle("кидаю") or {}
                if _txt(r2):
                    body += "  🎲→ " + _txt(r2)
            s.pending_roll = None                                   # не тащим зависший бросок в следующее действие
            if s.combat and s.combat.state.mode == "active":        # завязался бой → авто-ведём
                body += "\n    " + _drive_combat(s)
        except Exception as e:  # noqa: BLE001
            ANOM.append(f"#{n} [{cmd}] {type(e).__name__}: {e}")
            out(f"#{n:03d} ⟫ {cmd}\n    ⚠ ИСКЛЮЧЕНИЕ: {type(e).__name__}: {e}")
            out("       " + traceback.format_exc().splitlines()[-1])
            continue
        out(f"#{n:03d} ⟫ {cmd}\n    {body[:600] or '(пусто)'}\n    {_state(s)}")
    save_session(s, SLOT)
    open(NF, "w").write(str(n))
    if ANOM:
        out("\n⚠ АНОМАЛИИ ЭТОГО ЧАНКА:")
        for a in ANOM:
            out("  " + a)
    out(f"\n[чанк завершён: всего действий {n}]")


if __name__ == "__main__":
    main()
