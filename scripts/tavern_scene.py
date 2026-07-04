"""Полная сцена таверны в .txt: механический мозг (scripts/tavern) решает КТО ЧТО делает за каждый
момент, LLM озвучивает эти beats прозой + прямой речью, сохраняя характеры. Гибрид во всей красе:
консеквентное решает ядро, живой текст — модель. Пишет оформленный tavern_scene.txt.

  AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=$(tr -d '\\n\\r' < .secrets/deepseek.key) \\
      .venv/bin/python scripts/tavern_scene.py
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tavern import build  # noqa: E402

from aidnd.inference import ModelManager  # noqa: E402
from aidnd.mind import apply, decide, perceive  # noqa: E402
from aidnd.mind.tick import _decay_emotion, _decay_needs  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "tavern_scene.txt")
W = 74

SKETCH = {
    "Мара": "бойкая подавальщица, тёплая, но всё подмечает",
    "Лютик": "бард — сыплет байками, ловит взгляды, тщеславен",
    "Гарен": "стражник — немногословен, приглядывает за порядком",
    "Скрип": "тощий оборванец, глаза шарят по чужим кошелькам",
    "Тил": "юнец — краснеет и не сводит глаз с Мары",
    "Бром": "пьяный буян, вспыльчив, ищет, к кому прицепиться",
    "Обен": "дородный купец при тугом кошеле, любит поговорить",
    "Сельма": "спокойная знахарка, добрая, давняя подруга Мары",
    "Молчун": "чужак в капюшоне, в углу, ни с кем",
    "Дара": "наёмница при мече, холодно оценивает зал",
}


def beat(name, role, a, g, w):
    gk = g.kind if g else None
    tgt = a.target
    if a.kind == "say" and a.say in ("chat", "flatter", "ask"):
        verb = {"chat": "заводит разговор с", "flatter": "любезничает с", "ask": "расспрашивает"}[a.say]
        return f"{name} {verb} {tgt}"
    if a.kind == "say" and a.say == "threat":
        return f"{name} угрожает {tgt}"
    if a.kind == "wait" and gk == "acquire":
        return f"{name} исподволь приглядывается к чужому кошелю (ждёт удобного мига)"
    if a.kind == "take":
        return f"{name} тянется к добыче {tgt}"
    if a.kind == "attack":
        return f"{name} бросается на {tgt}"
    if a.kind == "use":
        return f"{name} прикладывается к кружке"
    if a.kind == "move":
        return f"{name} отходит к {a.to}" if a.to == "улица" else f"{name} возвращается в зал"
    if gk == "converse":
        return f"{name} ищет, с кем перекинуться словом"
    return f"{name} сидит молча, сам по себе"


def line(s=""):
    return s + "\n"


def box(title, sub):
    t = "╔" + "═" * W + "╗\n"
    t += "║" + title.center(W) + "║\n"
    t += "║" + sub.center(W) + "║\n"
    t += "╚" + "═" * W + "╝\n"
    return t


def run(seed=5, ticks=6):
    mgr = ModelManager()
    online = mgr.available()
    w, minds = build()
    rng = random.Random(seed)

    out = box("ТАВЕРНА «ПЬЯНЫЙ ВЕПРЬ»", "вечер на фронтире, дым, эль и чужие тайны")
    out += line()
    out += line("  Дощатый зал полон народу. Очаг чадит, кружки стучат о столы, где-то")
    out += line("  тренькает лютня. Десять судеб под одной прокопчённой крышей — и у каждой")
    out += line("  свой умысел на этот вечер.")
    out += line()
    out += line("┌" + "─" * (W - 2) + "┐")
    out += line("│ ДЕЙСТВУЮЩИЕ ЛИЦА" + " " * (W - 18) + "│")
    out += line("└" + "─" * (W - 2) + "┘")
    for nid, sk in SKETCH.items():
        out += line(f"   {nid:8} — {sk}")
    out += line()
    out += line("═" * W)
    out += line("  С Ц Е Н А".center(W))
    out += line("  (что делают — решает мозг NPC; как это выглядит — рассказывает голос)".center(W))
    out += line("═" * W)

    story = []
    for t in range(1, ticks + 1):
        for st in minds.values():
            _decay_needs(st)
            _decay_emotion(st)
        beats = []
        for st in sorted(minds.values(), key=lambda s: s.config.id):
            b = w.bodies[st.config.id]
            if b.down():
                continue
            (a, g, u), _ = decide(st, w, perceive(st, w), temp=0.3, rng=rng)
            apply(a, st, w)
            beats.append(beat(st.config.name, st.config.role, a, g, w))
        bl = "; ".join(beats)

        prose = None
        if online:
            sys_p = ("Ты — рассказчик тёмно-фэнтезийной таверны (D&D, фронтир). По СПИСКУ действий "
                     "персонажей за один момент напиши ОДИН цельный абзац живой сцены (4-7 предложений) "
                     "с 2-4 короткими репликами прямой речи, сохраняя характеры. НЕ добавляй событий "
                     "сверх списка, не меняй, кто что делает. Атмосферно, без воды. Только текст абзаца.")
            usr = (f"Персонажи: {'; '.join(f'{k} — {v}' for k, v in SKETCH.items())}.\n"
                   f"Что уже было: {story[-1] if story else '(вечер только начинается)'}\n\n"
                   f"СЕЙЧАС происходит (механика): {bl}\n\nНапиши абзац сцены.")
            resp = mgr.call("narrator", [{"role": "system", "content": sys_p},
                                         {"role": "user", "content": usr}], options={"temperature": 0.85})
            prose = (resp.get("content") if resp else "").strip()
        para = prose or ("· " + bl)
        story.append(para)
        out += line()
        out += line(f"── момент {t} " + "─" * (W - 12))
        for ln in _wrap(para, W - 3):
            out += line("  " + ln)
        out += line("     [механика: " + bl + "]") if False else ""   # механику прячем в конце

    out += line()
    out += line("═" * W)
    out += line("  Э П И Л О Г  —  что сложилось меж людьми".center(W))
    out += line("═" * W)
    for nid, st in minds.items():
        warm = sorted(((k, v["affinity"]) for k, v in st.relationships.items() if v["affinity"] >= .35),
                      key=lambda x: -x[1])
        if warm:
            out += line("   " + nid + " проникся к: " + ", ".join(f"{k} ({a:.2f})" for k, a in warm))
    out += line()
    out += line("  (симпатии сложились сами — из разговоров, обаяния и того, кто к кому потянулся)".center(W))
    out += line()
    out += line("╌" * W)
    out += line("  Решения — механический граф-мозг NPC (aidnd.mind). Проза и реплики — LLM поверх.".center(W))
    out += line("╌" * W)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"Сцена записана: {os.path.abspath(OUT)}  ({len(out)} символов, {'LLM' if online else 'без LLM'})")


def _wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > width:
            lines.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    if cur:
        lines.append(cur)
    return lines


if __name__ == "__main__":
    run(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 5,
        ticks=int(sys.argv[2]) if len(sys.argv) > 2 else 6)
