"""Диагностический плейтест: ~3 игровых дня, 120+ действий, живой DeepSeek.

Адаптивный драйвер: на каждом шаге смотрит состояние (бой/журней/доска/NPC/выходы) и выбирает
осмысленное действие, вплетая цели (главный квест → ратуша, бой → опасное место, деньги → доска).
Логирует всё в файл и собирает АНОМАЛИИ + покрытие. Запуск:
  AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=... python scripts/playtest_diag.py
"""

import os
import random
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.bootstrap import new_session                      # noqa: E402
from aidnd.inventory.items import wallet_value_cp            # noqa: E402

LOG = open(os.path.join(os.path.dirname(__file__), "..", "playtest_out.txt"), "w", encoding="utf-8")
RNG = random.Random(7)
ANOM, COVER = [], {"combats": 0, "street_events": 0, "leads": 0, "board_accept": 0,
                   "turnins": 0, "trades": 0, "talks": 0, "moves": 0, "rolls": 0, "errors": 0}
RECENT: list = []


def out(s=""):
    print(s)
    LOG.write(s + "\n")
    LOG.flush()


def gold_cp(s):
    return wallet_value_cp(s.world.wallets.get(s.player, {}))


def snap(s):
    st = s.world.get_stats(s.player)
    from aidnd.world.environment import day_number
    return {"day": day_number(s.world.clock.tick) + 1, "place": s._place_name(s.current_place()),
            "hp": st.hp if st else 0, "gp": round(gold_cp(s) / 100, 1)}


def flag(msg):
    ANOM.append(msg)
    out("  ⚠ АНОМАЛИЯ: " + msg)


N = 0


def act(s, label, fn):
    """Выполнить действие, залогировать, проверить на аномалии."""
    global N
    N += 1
    before = snap(s)
    try:
        r = fn() or {}
    except Exception as e:
        COVER["errors"] += 1
        flag(f"[{label}] ИСКЛЮЧЕНИЕ: {e}")
        out("    " + traceback.format_exc().splitlines()[-1])
        return {}
    text = (r.get("text") or "").replace("\n", " ⏎ ")
    kind = r.get("kind", "")
    after = snap(s)
    out(f"#{N:03d} день{after['day']} [{after['place'][:22]}] «{label[:34]}» → {kind}: {text[:150]}")
    # --- авто-детекторы аномалий ---
    if not text and kind not in ("combat", "look", "inventory"):
        flag(f"[{label}] пустой ответ (kind={kind})")
    low = text.lower()
    if any(k in low for k in ("traceback", "exception", "error:", "keyerror", "none type", "nonetype")):
        flag(f"[{label}] технический мусор в тексте: {text[:80]}")
    RECENT.append(text[:60])
    if len(RECENT) >= 4 and len(set(RECENT[-4:])) == 1 and text:
        flag(f"[{label}] один и тот же ответ ×4 (застрял?): {text[:60]}")
    # покрытие фич
    if "перекрёст" in low and "минуешь" in low:
        pass
    if r.get("signs_offer"):
        pass
    if "зацепк" in low:
        COVER["leads"] += 1
    if kind == "roll_request" or "бросок" in low or r.get("roll_request"):
        COVER["rolls"] += 1
    return r


def drive_combat(s):
    """Довести бой до конца: атака цели в досягаемости, иначе сближение, иначе конец хода."""
    COVER["combats"] += 1
    out("  ⚔ БОЙ начался")
    for _ in range(40):
        cv = s.combat_view()
        if not cv or cv.get("mode") != "active":
            out(f"  ⚔ БОЙ окончен: {cv.get('outcome') if cv else '—'}")
            return
        if not cv.get("is_pc_turn"):
            act(s, "бой:конец хода(ожидание)", s.combat_end_turn)
            continue
        if cv.get("targets") and "attack" in (cv.get("actions") or []):
            act(s, "бой:атака", lambda: s.combat_attack(cv["targets"][0]))
            continue
        enemies = [c for c in cv["combatants"] if c["side"] == "enemy" and not c["fled"] and c["hp"] > 0]
        reach = cv.get("reachable") or []
        if enemies and reach and "move" in (cv.get("actions") or []):
            ex, ey = enemies[0]["pos"]
            best = min(reach, key=lambda c: abs(c[0] - ex) + abs(c[1] - ey))
            act(s, "бой:сближение", lambda: s.combat_move(best))
            continue
        act(s, "бой:конец хода", s.combat_end_turn)
    flag("бой не завершился за 40 действий")


def handle_roll(s, r):
    """Если игра запросила бросок — подтвердить (катим как есть)."""
    for _ in range(3):
        if not (s.pending_roll or (r or {}).get("roll_request")):
            return r
        r = act(s, "бросок", lambda: s.handle("кидаю"))
    return r


def first_npc(s):
    n = s.npcs_here()
    return (n[0], s._display(n[0])) if n else (None, None)


def run():
    out("=== СОЗДАНИЕ МИРА (DeepSeek, обогащение) ===")
    s = new_session(seed=11, roster_size=10, use_model=True)
    out(f"Старт: {snap(s)} | главный квест: "
        + next((q.title for q in s.world.quests.values() if getattr(q, "kind", "") == "main"), "—"))

    # сценарный костяк целей (вплетаются между адаптивными действиями)
    goals = [
        "осмотреться", "поговорить с трактирщиком", "что тут слышно",
        "расспросить о том, что неспокойно в городе", "выйти на улицу",
        "идти на площадь", "осмотреться", "идти к доске объявлений",
        "идти в ратушу", "поговорить с мастером города",
        "расспросить мастера, что случилось в городе",
        "идти в лавку бартена", "посмотреть товар",
        "идти в таверну спящий великан", "что слышно о бандитах",
        "идти к святилищу удачи", "поговорить с сестрой гарэле",
        "идти к поместью тресендар", "осмотреться", "напасть",
        "идти на площадь", "отдохнуть до утра",
        "идти к логову крэгмо", "осмотреться", "напасть",
        "вернуться в город", "отдохнуть до утра",
    ]
    fillers = ["осмотреться", "что вокруг", "проверить карту", "что у меня в сумке",
               "идти дальше", "оглядеться по сторонам", "сколько у меня денег"]

    gi = 0
    while N < 125:
        v = s.view()
        # 1) бой
        if v.get("in_combat"):
            drive_combat(s)
            continue
        # 2) журней (уличное событие — иногда реагируем, иногда идём дальше)
        if s._journey:
            COVER["street_events"] += 1
            if RNG.random() < 0.5:
                act(s, "реакция на сценку", lambda: s.handle("оглядеться, что происходит"))
            r = act(s, "идти дальше", lambda: s.handle("дальше"))
            continue
        # 3) запись вывесок
        if getattr(s, "_sign_offer", None) and RNG.random() < 0.6:
            act(s, "записать на карту", lambda: s.handle("да"))
            continue
        # 4) доска: взять/сдать
        b = v.get("board")
        if b:
            tin = next((q for q in b["quests"] if q.get("can_turn_in")), None)
            if tin:
                COVER["turnins"] += 1
                act(s, f"сдать «{tin['title'][:18]}»", lambda: s.turn_in_quest(tin["id"]))
                continue
            acc = next((q for q in b["quests"] if q.get("can_accept")), None)
            if acc and COVER["board_accept"] < 4:
                COVER["board_accept"] += 1
                act(s, f"взять «{acc['title'][:18]}»", lambda: s.accept_quest(acc["id"]))
                continue
        # 5) цель из костяка, иначе адаптивный филлер
        if gi < len(goals):
            action = goals[gi]
            gi += 1
        else:
            npc_id, npc_name = first_npc(s)
            if npc_id and RNG.random() < 0.4:
                action = f"поговорить с {npc_name}"
            else:
                action = RNG.choice(fillers)
        if action.startswith("поговорить") or action.startswith("расспросить") or "слышно" in action or "что случилось" in action:
            COVER["talks"] += 1
        if action.startswith("идти") or action.startswith("выйти") or action.startswith("вернуться"):
            COVER["moves"] += 1
        if "товар" in action or "купить" in action:
            COVER["trades"] += 1
        r = act(s, action, lambda a=action: s.handle(a))
        r = handle_roll(s, r)

    # финал
    out("\n=== ИТОГ ===")
    out(f"Действий: {N} | финал: {snap(s)}")
    out("Покрытие: " + ", ".join(f"{k}={v}" for k, v in COVER.items()))
    out("\nАКТИВНЫЕ КВЕСТЫ / ХРОНИКА:")
    for q in s.quest_journal():
        out(f"  • [{q['kind']}] {q['title']} ({q['state']}) — сейчас: {q.get('now', '')[:50]}")
        for e in q.get("timeline", [])[-3:]:
            out(f"      {e['stamp']} — {e['text'][:70]}")
    out(f"\nАНОМАЛИЙ НАЙДЕНО: {len(ANOM)}")
    for a in ANOM:
        out("  ⚠ " + a)
    LOG.close()


if __name__ == "__main__":
    run()
