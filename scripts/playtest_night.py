"""Плейтест на живом ABM: плут-убийца две ночи караулит ПОЗДНИХ ПУТНИКОВ (ночных «сов» из симуляции),
заводит в глухой угол, убивает — а труп находит ЖИВОЙ ГОРОД (патруль/прохожий по симуляции), не мгновенно.
Смотрим эскалацию подозрения/розыска от ночи к ночи. Офлайн, детерминированно.

Запуск:  .venv/bin/python scripts/playtest_night.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from playtest_assassin import auto_roll, goto_hour, hh, put, stealth_kill  # noqa: E402

from aidnd.bootstrap import new_session  # noqa: E402
from aidnd.content.cases import case_of, suspicion_of, wanted_status  # noqa: E402
from aidnd.world.components import Persona  # noqa: E402


def heat(s, tag):
    c = case_of(s.world, s.player)
    deeds = ", ".join(d["kind"] for d in c["deeds"]) if c else "—"
    print(f"    [{tag}] подозрение={suspicion_of(s.world, s.player):.2f} "
          f"розыск={wanted_status(s.world, s.player)} | дела: {deeds}")


def empty_corner(s, exclude_place):
    """Глухой угол ночью: публичное место без единого присутствующего (ни ростера, ни сов)."""
    pop = s.world.citypop
    for cand in ("building:notice_board", "building:lionshield_coster", "building:edermath_orchard",
                 "building:alderleaf_farm", "place:phandalin_square"):
        if cand == exclude_place:
            continue
        put(s, s.player, cand)
        here = [n for n in s.npcs_here() if n != s.player]
        if not here and not pop.present_at(cand):
            return cand
    return "building:notice_board"


def discover_run(s, max_hours=16):
    """Дать ЖИВОМУ городу самому наткнуться на тело (патруль/прохожий по симуляции). Возвращает (час, кем)."""
    per_tick = 1
    pend0 = len(getattr(s.world, "pending_corpses", []) or [])
    seen = len(s.journal)
    for _ in range(max_hours * 6 // per_tick):
        s.world.clock.tick += per_tick
        s._apply_schedules()                                   # внутри — discover_corpses (живой обход)
        if len(getattr(s.world, "pending_corpses", []) or []) < pend0:
            note = next((j for j in s.journal[seen:] if "🪦" in j), "")
            by = "патруль" if "Патруль" in note else "прохожий"
            return hh(s), by
    return None, None


def night_hunt(s, night):
    print(f"\n══════ НОЧЬ {night} ══════")
    goto_hour(s, 1)
    pop = s.world.citypop
    pubs = pop._public_places(s.world)
    # где сейчас поздние путники (совы) — по симуляции
    scene = max(pubs, key=lambda p: len(pop.present_at(p)))
    owls = pop.present_at(scene)
    busy = sorted(((p.split(":")[-1][:12], len(pop.present_at(p))) for p in pubs), key=lambda x: -x[1])
    print(f"[{hh(s)}] ночной город (ABM): на местах {[b for b in busy if b[1]]}")
    if not owls:
        print("  никого не караулить — глухая ночь."); return
    put(s, s.player, scene)
    victim_stub = owls[0]
    vname = pop.name_of(victim_stub)
    victim = pop.materialize(victim_stub, scene, None)         # засёк позднего гостя → знакомство (материализация)
    print(f"[{hh(s)}] в «{s._place_name(scene)}» поздних гостей: {len(owls)} → присмотрел: {vname}")

    # 1) завести в тёмный угол (follow по убеждению — плут бустнут)
    r = s.handle(f"идём со мной, {vname.split()[0]}")
    auto_roll(s)
    per = s.world.ecs.get(victim, Persona)
    print(f"    уговор увести: «{(r.get('text') or '')[:48]}…» → следует={per.following}")
    if not per.following:
        per.following = True
    corner = empty_corner(s, scene)
    put(s, s.player, corner)
    put(s, victim, corner)
    others = [n for n in s.npcs_here() if n not in (s.player, victim)]
    print(f"[{hh(s)}] глухой угол «{s._place_name(corner)}» — посторонние: {others or 'нет'} | "
          f"свидетели(движок)={s._deed_witnessed([victim])}")

    # 2) удар из тени
    out, dead = stealth_kill(s, victim)
    print(f"    стелс-удар: исход={out} жертва мертва={dead} | тел в ожидании обнаружения: "
          f"{len(getattr(s.world,'pending_corpses',[]) or [])}")
    heat(s, "сразу после убийства")

    # 3) уходит — живой город сам находит тело
    put(s, s.player, "place:phandalin_square")
    found_h, by = discover_run(s)
    if found_h:
        print(f"    🪦 тело нашли в {found_h} ({by}) — спустя время, по симуляции (не мгновенно)")
    else:
        print("    тело пока не нашли (глухой угол, никто не прошёл)")
    heat(s, f"после ночи {night}")


def run():
    s = new_session(seed=7, roster_size=16, use_model=False)
    st = s.world.get_stats(s.player)
    st.cha, st.dex, st.proficiency = 28, 18, 6
    for sk in ("persuasion", "stealth"):
        if sk not in st.proficient_skills:
            st.proficient_skills.append(sk)
    print(f"Плут-убийца: CHA {st.cha}, Скрытность проф. | стража: {s.world.watch_temperament['label']}")
    for night in (1, 2):
        night_hunt(s, night)
    print("\n══════ ИТОГ ══════")
    heat(s, "две ночи спустя")
    c = case_of(s.world, s.player)
    print(f"  убийств в деле: {sum(1 for d in (c['deeds'] if c else []) if 'kill' in d['kind'])} | "
          f"финальный розыск: {wanted_status(s.world, s.player)}")


if __name__ == "__main__":
    run()
