"""Плейтест-2: проверка стражи/времени-в-бою/сценок→бой + 3 дня/бой/деньги/главный квест.

Двигается через travel_to (без гейта одного шага), много ходит между зданиями (триггерит уличные
сценки → возможный бой), дерётся по-настоящему, ночует (дни идут), берёт и сдаёт квест ради денег,
говорит с мастером города. Логирует и собирает аномалии/покрытие.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from aidnd.bootstrap import new_session                      # noqa: E402
from aidnd.inventory.items import wallet_value_cp            # noqa: E402
from aidnd.world.environment import day_number              # noqa: E402

LOG = open(os.path.join(os.path.dirname(__file__), "..", "playtest2_out.txt"), "w", encoding="utf-8")
ANOM = []
COVER = {"combats": 0, "guard_breaks": 0, "enemy_flees": 0, "street_combat": 0, "turnins": 0,
         "days_reached": 1, "talks": 0, "moves": 0, "errors": 0, "attacks": 0}
INN, BOARD, SHRINE, HALL, SHOP, TAVERN, SQUARE = (
    "building:stonehill_inn", "building:notice_board", "building:shrine_of_luck",
    "building:townmaster_hall", "building:barthens_provisions", "building:sleeping_giant",
    "place:phandalin_square")
N = 0


def out(s=""):
    print(s)
    LOG.write(s + "\n")
    LOG.flush()


def gp(s):
    return round(wallet_value_cp(s.world.wallets.get(s.player, {})) / 100, 1)


def act(s, label, fn):
    global N
    N += 1
    try:
        r = fn() or {}
    except Exception as e:
        COVER["errors"] += 1
        ANOM.append(f"[{label}] ИСКЛЮЧЕНИЕ: {e}")
        out(f"#{N:03d} ⚠ ИСКЛЮЧЕНИЕ [{label}]: {e}")
        out("    " + traceback.format_exc().splitlines()[-1])
        return {}
    day = day_number(s.world.clock.tick) + 1
    COVER["days_reached"] = max(COVER["days_reached"], day)
    text = (r.get("text") or "").replace("\n", " ⏎ ")
    out(f"#{N:03d} д{day} [{s._place_name(s.current_place())[:18]}] gp{gp(s)} «{label[:30]}» → {r.get('kind', '')}: {text[:140]}")
    if s.view().get("in_combat"):
        drive_combat(s, label)
    return r


def drive_combat(s, why):
    COVER["combats"] += 1
    if "сценк" in why or "ход" in why or "идти" in why:
        COVER["street_combat"] += 1
    cs = s.combat.state
    out(f"  ⚔ БОЙ (town={cs.town}) против: {[s._display(e) for e in s.combat.alive_enemies()]}")
    for _ in range(60):
        cs = s.combat.state
        if cs.mode != "active":
            break
        if not s.combat.is_pc_turn():
            s.combat_end_turn()
            continue
        cv = s.combat_view()
        if cv.get("targets") and "attack" in (cv.get("actions") or []):
            COVER["attacks"] += 1
            r = s.combat_attack(cv["targets"][0])
            if s.pending_roll or (r or {}).get("roll_request"):
                s.handle("кидаю")
            continue
        enemies = [c for c in cv["combatants"] if c["side"] == "enemy" and not c["fled"] and c["hp"] > 0]
        reach = cv.get("reachable") or []
        if enemies and reach and "move" in (cv.get("actions") or []):
            ex, ey = enemies[0]["pos"]
            s.combat_move(min(reach, key=lambda c: abs(c[0] - ex) + abs(c[1] - ey)))
            continue
        s.combat_end_turn()
    cs = s.combat.state
    if cs.guard_intervened:
        COVER["guard_breaks"] += 1
    COVER["enemy_flees"] += sum(1 for c in cs.combatants.values() if c.side == "enemy" and c.fled)
    out(f"  ⚔ исход: {cs.outcome} | стража={cs.guard_intervened} | раундов={cs.round}")
    s.combat = None


def go(s, place):
    COVER["moves"] += 1
    r = act(s, f"→ {s._place_name(place)[:16]}", lambda: s.travel_to(place))
    if "не разведал" in (r.get("text") or "") and place != SQUARE:   # площадь смежна со всеми → через неё
        act(s, "→ площадь (хаб)", lambda: s.travel_to(SQUARE))
        r = act(s, f"→ {s._place_name(place)[:16]}", lambda: s.travel_to(place))
    return r


def talk(s, line):
    COVER["talks"] += 1
    return act(s, line, lambda: s.handle(line))


def rest(s):
    return act(s, "переночевать до утра", lambda: s.handle("снять комнату и лечь спать до утра"))


def run():
    out("=== МИР (DeepSeek) ===")
    s = new_session(seed=11, roster_size=10, use_model=True)
    mq = next((q for q in s.world.quests.values() if getattr(q, "kind", "") == "main"), None)
    out(f"Старт gp{gp(s)} | главный квест: {mq.title if mq else '—'}")

    # --- ДЕНЬ 1: знакомство, главный квест, лёгкий квест за деньги ---
    talk(s, "осмотреться")
    talk(s, "поговорить с трактирщиком, что неспокойно в городе")
    go(s, BOARD)
    b = s.view().get("board") or {}
    for q in (b.get("quests") or [])[:3]:
        if q.get("can_accept"):
            act(s, f"взять «{q['title'][:16]}»", lambda qq=q: s.accept_quest(qq["id"]))
    go(s, HALL)
    talk(s, "поговорить с мастером города о том, что случилось")
    go(s, SHRINE)
    talk(s, "поговорить с сестрой гарэле, передать весть")
    go(s, BOARD)                                            # сдать квест Гарэле ради денег
    b = s.view().get("board") or {}
    for q in (b.get("quests") or []):
        if q.get("can_turn_in"):
            COVER["turnins"] += 1
            act(s, f"сдать «{q['title'][:16]}»", lambda qq=q: s.turn_in_quest(qq["id"]))
    # много ходьбы → уличные сценки (возможен бой)
    for place in (SHOP, TAVERN, SQUARE, SHOP, TAVERN, SQUARE, SHOP):
        if N > 40:
            break
        go(s, place)
        talk(s, "осмотреться")
    rest(s)                                                # → день 2

    # --- ДЕНЬ 2: ещё ходьба/сценки/бой + проверка мутаций доски ---
    for place in (BOARD, SHOP, SQUARE, TAVERN, HALL, SHOP, SQUARE, BOARD, TAVERN):
        if N > 80:
            break
        go(s, place)
        talk(s, "осмотреться")
    rest(s)                                                # → день 3

    # --- ДЕНЬ 3 ---
    for place in (SQUARE, SHOP, TAVERN, BOARD, SQUARE, SHOP):
        if N > 110:
            break
        go(s, place)
    talk(s, "осмотреться")

    out("\n=== ИТОГ ===")
    out(f"Действий: {N} | дней достигнуто: {COVER['days_reached']} | финал gp{gp(s)}")
    out("Покрытие: " + ", ".join(f"{k}={v}" for k, v in COVER.items()))
    out("\nХРОНИКА КВЕСТОВ:")
    for q in s.quest_journal():
        out(f"  • [{q['kind']}] {q['title']} ({q['state']})")
        for e in q.get("timeline", [])[-3:]:
            out(f"      {e['stamp']} — {e['text'][:66]}")
    out(f"\nАНОМАЛИЙ: {len(ANOM)}")
    for a in ANOM:
        out("  ⚠ " + a)
    LOG.close()


if __name__ == "__main__":
    run()
