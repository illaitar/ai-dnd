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


def surprise_stab(s, victim):
    """Стелс-удар в упор. NB: мирные паникуют и убегают, а у плута офлайн слабый урон — поэтому бьём
    контрольным наверняка (находка: внятного механизма стелс-убийства/внезапного раунда пока нет)."""
    cs = s.combat.state
    s.world.get_stats(victim).hp = 0                          # клинок под рёбра — наверняка
    cs.combatants[victim].fled = False
    cs.outcome, cs.mode = "victory", "ended"
    s._on_combat_end()                                       # → дело об убийстве (kill_*; по факту свидетелей)
    dead = not s.world.is_alive(victim)
    s.combat = None
    return "victory", dead


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
    st.cha = 18
    if "persuasion" not in st.proficient_skills:
        st.proficient_skills.append("persuasion")
    print(f"Плут-убийца: CHA {st.cha}, Убеждение проф. | темперамент стражи: {s.world.watch_temperament['label']}")

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
    roll_out(s)
    per = s.world.ecs.get(victim, Persona)
    print(f"уговор: {(r.get('text') or '')[:60]}… → следует={per.following}")
    if not per.following:
        per.following = True
        print("  (убеждение чужака в тёмный угол — DC высокий; для сценария ведём силой)")

    # 2) наедине — проверка свидетелей
    put(s, victim, spot)
    others = [n for n in s.npcs_here() if n not in (s.player, victim)]
    print(f"\n[{hh(s)}] «{s._place_name(spot)}» наедине — посторонних: {others or 'нет'} | свидетели(движок)={s._deed_witnessed([victim])}")

    # 3) ПРОТКНУТЬ
    r = s.handle(f"напасть на {s._display(victim).split()[0]}")
    print(f"удар: {(r.get('text') or '')[:60]}")
    if s.combat:
        out, dead = surprise_stab(s, victim); print(f"  внезапный удар: исход={out} | жертва мертва={dead}")
    heat(s, "приватное убийство")

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
    s.start_combat([v2])
    s._note_town_deed([v2], innocent=True)                  # нападение (при свидетелях)
    out, dead = surprise_stab(s, v2)                         # убийство (при свидетелях)
    print(f"  удар при свидетелях: жертва мертва={dead}")
    heat(s, "людное убийство")
    put(s, s.player, "building:townmaster_hall")            # пришёл туда, где стража
    print("  реакция стражи:", watch_note(s) or "—")


if __name__ == "__main__":
    run()
