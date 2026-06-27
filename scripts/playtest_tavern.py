"""Плейтест: целый день в таверне, общение с разными людьми (100+ команд).

Проверяем на живой модели: материализацию фон→собеседник (любое обращение по имени), качество диалога
(персона/профессия/семья/знания), смену толпы по времени (расписание+привлекательность), плотность в
осмотре, разнообразие персонажей. Логирует всё + сводку аномалий.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from aidnd.bootstrap import new_session  # noqa: E402
from aidnd.content.citypop import _minute, crowd_at, density_label  # noqa: E402
from aidnd.world.components import Persona, Stats5e  # noqa: E402

INN = "building:stonehill_inn"
LOG = open(os.path.join(os.path.dirname(__file__), "..", "tavern_playtest.txt"), "w", encoding="utf-8")
N = 0
ANOM = []
REPLIES = []


def out(s=""):
    print(s)
    LOG.write(s + "\n")
    LOG.flush()


def goto(s, hh):
    for _ in range(900):
        if int(s.world.clock.hhmm().split(":")[0]) == hh:
            return
        s.world.clock.tick += 1


def cmd(s, label, text):
    global N
    N += 1
    try:
        r = s.handle(text) or {}
    except Exception as e:
        ANOM.append(f"[{label}] EXC: {e}")
        out(f"#{N:03d} ⚠ ИСКЛЮЧЕНИЕ [{label}]: {e}")
        out("    " + traceback.format_exc().splitlines()[-1])
        return {}
    txt = (r.get("text") or "").replace("\n", " ")
    out(f"#{N:03d} [{s.world.clock.hhmm()}] «{label[:38]}» → {r.get('kind', '')}: {txt[:200]}")
    if r.get("kind") in ("narration", "talk", "dialogue") and txt:
        REPLIES.append(txt)
    return r


QUESTIONS = ["поздоровайся и спроси, чем он живёт", "спроси, что слышно нового в городе",
             "расспроси про его семью и ремесло", "спроси, как тут со стражей и порядком",
             "спроси, что он думает о Красных плащах", "спроси, где тут можно подзаработать",
             "спроси про местные слухи и тайны", "пошути и спроси про его любимое занятие",
             "спроси, чего он боится в этом городе", "спроси совета, кому тут можно доверять"]


def present_names(s):
    names = [s._display(n) for n in s.npcs_here() if n != s.player and s.world.is_alive(n)]
    pop = getattr(s.world, "citypop", None)
    if pop:
        names += [pop.name_of(a) for a in pop.present_at(INN, _minute(s.world))]
    seen, out2 = set(), []
    for nm in names:                                          # дедуп по имени
        fn = nm.split()[0]
        if fn and fn not in seen:
            seen.add(fn)
            out2.append(nm)
    return out2


def run():
    out("=== ДЕНЬ В ТАВЕРНЕ (DeepSeek) ===")
    s = new_session(seed=7, roster_size=20, use_model=True, progress=lambda *a: None)
    s.world.commit("set_position", s.player, target=s.player,
                   payload={"region": "region:phandalin", "place": INN})
    out(f"Старт у «{s._place_name(INN)}». Стража: {s.world.watch_temperament['label']}.\n")
    met: dict[str, str] = {}                                   # имя → npc_id (с кем говорили)
    qi = 0
    while N < 112:                                            # естественный день: время идёт само (тик/команду)
        if N % 7 == 0:
            cmd(s, "осмотреться", "осмотреться")
            pres0 = present_names(s)
            out(f"   👥 [{s.world.clock.hhmm()}] {density_label(crowd_at(s.world, INN))} — "
                f"{len(pres0)} лиц: {[p.split()[0] for p in pres0[:8]]}")
            cmd(s, "выпить/посидеть", "взять кружку эля, посидеть и оглядеться")   # дать времени идти
        pres = present_names(s)
        if not pres:
            cmd(s, "ждать", "посидеть у очага и оглядеть зал")
            continue
        nm_full = pres[qi % len(pres)]
        nm = nm_full.split()[0]
        q = QUESTIONS[qi % len(QUESTIONS)]
        qi += 1
        r = cmd(s, f"{nm}: {q[7:30]}", f"поговорить с {nm}: {q}")
        if r.get("npc"):
            met[nm_full] = r["npc"]

    # --- сводка ---
    out("\n=== ИТОГ ===")
    out(f"команд: {N} | материализовано собеседников: {len(met)}")
    out("\nЛица, с кем говорили (персона/профессия/черты):")
    for _nm, nid in list(met.items())[:14]:
        p = s.world.ecs.get(nid, Persona)
        st = s.world.ecs.get(nid, Stats5e)
        if p:
            out(f"  • {p.name} ({p.race}, {p.profession or '—'}) HP{st.hp if st else '?'} "
                f"черты={p.traits[:3]} голос={(p.voice or '')[:30]}")
    # разнообразие реплик
    uniq = len(set(REPLIES))
    out(f"\nреплик всего: {len(REPLIES)} | уникальных: {uniq} "
        f"({'ОК разнообразие' if uniq > len(REPLIES) * 0.7 else '⚠ много повторов'})")
    out(f"\nАНОМАЛИЙ: {len(ANOM)}")
    for a in ANOM:
        out("  ⚠ " + a)
    LOG.close()


if __name__ == "__main__":
    run()
