"""Плейтест: плут-убийца — приватное убийство vs людное, реакция стражи/дознавателей.

Сценарий: ночь → заводит прохожего в глухой угол (follow по убеждению) → протыкает (бой до смерти) →
уходит бродить. Позиции ставим напрямую (без travel) — чтобы уличные события не перебивали чистую
проверку механики дел/свидетелей/розыска. Офлайн, детерминированно.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from aidnd.bootstrap import new_session  # noqa: E402
from aidnd.content.cases import case_of, suspicion_of, wanted_status  # noqa: E402
from aidnd.world.components import Persona  # noqa: E402

SQUARE, INN = "place:phandalin_square", "building:stonehill_inn"
ALLEY = "building:lionshield_coster"                            # тихая лавка — наш «глухой угол» ночью


def hh(s):
    return s.world.clock.hhmm()


def put(s, who, place):
    s.world.commit("set_position", who, target=who, payload={"region": "region:phandalin", "place": place})


def goto_hour(s, target):
    for _ in range(800):
        if int(hh(s).split(":")[0]) == target:
            return
        s.world.clock.tick += 1


def roll_out(s):
    for _ in range(8):
        if s.pending_roll:
            s.handle("кидаю")
        else:
            break


def auto_roll(s):
    import re
    g = 0
    while s.pending_roll and g < 8:
        g += 1
        req = s.pending_roll["request"]
        m = re.match(r"(\d+)d(\d+)", str(getattr(req, "dice", "1d20")).replace(" ", ""))
        n, sides = (int(m.group(1)), int(m.group(2))) if m else (1, 20)
        faces = [sides] * (n + (1 if getattr(req, "advantage", False) and sides == 20 else 0))
        s.submit_roll(faces)


def stealth_kill(s, victim):
    """Реальное убийство: удар из тени → сюрприз-раунд → добиваем в бою (auto-roll)."""
    s._stealth_strike(victim)                               # стелс → застигнут врасплох (не убегает)
    for _ in range(6):
        cs = s.combat.state
        if cs.mode != "active" or not s.world.is_alive(victim):
            break
        if not s.combat.is_pc_turn():
            s.combat_end_turn()
            continue
        cv = s.combat_view()
        if victim in (cv.get("targets") or []):
            s.combat_attack(victim)
            auto_roll(s)
        elif cv.get("reachable"):
            vp = [c for c in cv["combatants"] if c["id"] == victim][0]["pos"]
            s.combat_move(min(cv["reachable"], key=lambda c: abs(c[0] - vp[0]) + abs(c[1] - vp[1])))
        else:
            s.combat_end_turn()
    if s.combat and s.combat.state.mode == "active":        # бой не закрылся сам — засчитать убийство (kill_*)
        s.combat.state.outcome, s.combat.state.mode = "victory", "ended"
        s._on_combat_end()
    dead = not s.world.is_alive(victim)
    out = s.combat.state.outcome if s.combat else "victory"
    s.combat = None
    return out, dead


def heat(s, tag):
    c = case_of(s.world, s.player)
    deeds = ", ".join(d["kind"] for d in c["deeds"]) if c else "—"
    print(f"  [{tag}] подозрение={suspicion_of(s.world, s.player):.2f} статус={wanted_status(s.world, s.player)} | дела: {deeds}")


def watch_note(s):
    return [ln.strip() for ln in s.look()["text"].split("\n") if "🚨" in ln]


def a_commoner(s, place, exclude=()):
    for n in s.npcs_here():
        if n in exclude or n == s.player or not s.world.is_alive(n):
            continue
        fac = getattr(s.world.ecs.get(n, Persona), "faction", None)
        if fac not in ("faction:cragmaw", "faction:redbrands", "faction:watch"):
            return n
    return None


def run():
    s = new_session(seed=7, roster_size=16, use_model=False)
    st = s.world.get_stats(s.player)
    st.cha, st.dex, st.proficiency = 28, 18, 6              # харизматичный смертоносный плут (для плейтеста)
    for sk in ("persuasion", "stealth"):
        if sk not in st.proficient_skills:
            st.proficient_skills.append(sk)
    print(f"Плут-убийца: CHA {st.cha} (Убеждение проф.+эксперт), Скрытность проф. | стража: {s.world.watch_temperament['label']}")

    # выбрать жертву из людей в таверне вечером
    goto_hour(s, 19)
    put(s, s.player, INN)
    victim = a_commoner(s, INN)
    print(f"\n[{hh(s)}] жертва: {s._display(victim)}")

    # глухая ночь + найти БЕЗЛЮДНОЕ место (без жильцов) — настоящий «тёмный угол»
    goto_hour(s, 1)
    spot = None
    for cand in ("building:notice_board", SQUARE, "building:edermath_orchard", "building:alderleaf_farm"):
        put(s, s.player, cand)
        if not [n for n in s.npcs_here() if n != s.player]:
            spot = cand
            break
    spot = spot or SQUARE
    print(f"[{hh(s)}] безлюдный угол: «{s._place_name(spot)}»")

    # 1) ЗАВЕСТИ ТУДА (follow по убеждению) — наедине
    put(s, s.player, spot)
    put(s, victim, spot)
    r = s.handle(f"идём со мной в тёмный угол, {s._display(victim).split()[0]}")
    auto_roll(s)                                            # докинуть проверку Убеждения (бустнутый плут)
    per = s.world.ecs.get(victim, Persona)
    print(f"уговор: {(r.get('text') or '')[:55]} → следует={per.following}")
    if not per.following:
        per.following = True
        print("  (не уговорил — для сценария ведём силой)")

    # 2) наедине — проверка свидетелей
    put(s, victim, spot)
    others = [n for n in s.npcs_here() if n not in (s.player, victim)]
    print(f"\n[{hh(s)}] «{s._place_name(spot)}» наедине — посторонних: {others or 'нет'} | свидетели(движок)={s._deed_witnessed([victim])}")

    # 3) ПРОТКНУТЬ из тени (один чистый удар)
    out, dead = stealth_kill(s, victim)
    print(f"стелс-удар из тени: исход={out} | жертва мертва={dead}")
    heat(s, "приватное убийство (NB: тело пока «находят» сразу — это чиним симуляцией ниже)")

    # 4) УХОДИТ И БРОДИТ — стража видит подозрительного
    print("\n— уходит, бродит по городу (ставим к стражникам/ратуше) —")
    for place in (SQUARE, "building:townmaster_hall"):
        put(s, s.player, place)
        print(f"  [{hh(s)}] {s._place_name(place)[:18]:20} стража: {watch_note(s) or '—'}")
    heat(s, "побродив")

    # 5) КОНТРАСТ — то же убийство, но ПРИ СВИДЕТЕЛЯХ (день, людная площадь) → розыск
    print("\n=== КОНТРАСТ: убийство ПРИ СВИДЕТЕЛЯХ ===")
    from aidnd.content.cases import clear_case
    clear_case(s.world, s.player)                            # сбросим, чтобы видеть эффект ИМЕННО людного убийства
    goto_hour(s, 13)
    put(s, s.player, SQUARE)
    for n in list(s.world.npcs()):                           # подсадить пару зевак
        if getattr(s.world.ecs.get(n, Persona), "faction", None) is None and s.world.is_alive(n):
            put(s, n, SQUARE)
            if len([x for x in s.npcs_here() if x != s.player]) >= 3:
                break
    v2 = a_commoner(s, SQUARE)
    wits = [x for x in s.npcs_here() if x not in (s.player, v2)]
    print(f"[{hh(s)}] площадь людно: жертва {s._display(v2)}, зеваки {[s._display(n) for n in wits[:4]]} | свидетели(движок)={s._deed_witnessed([v2])}")
    out, dead = stealth_kill(s, v2)                          # убийство при свидетелях (толпа всё видит)
    print(f"  удар при свидетелях: жертва мертва={dead}")
    heat(s, "людное убийство")
    put(s, s.player, "building:townmaster_hall")            # пришёл туда, где стража
    print("  реакция стражи:", watch_note(s) or "—")


if __name__ == "__main__":
    run()
