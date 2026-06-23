"""Плейтест «как реальный игрок»: гоняет живую сессию через разнообразный и
провокационный ввод, авто-бросает кости на roll_request, печатает полный трейс
каждой стадии (route/feasibility/arbiter/consequence/dialogue). Цель — узкие места.

Запуск (туннель к Ollama поднят):
    OLLAMA_HOST=http://localhost:11434 python playtest.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from aidnd.bootstrap import new_session  # noqa: E402

# Сценарий в стиле игрока: ориентация → диалог → freeform с последствиями →
# враждебное/кража → движение/торговля → крайние/опечатки/расплывчатое.
SCRIPT = [
    "осмотреться",
    "кто здесь в зале?",
    "что у меня в инвентаре?",
    "сколько у меня золота?",
    "поговорить с трактирщиком",
    "что слышно нового в городе?",
    "спросить Сильдара, нет ли для меня работы",
    "заказываю кружку эля и осушаю её залпом",
    "выцарапываю кинжалом свою метку на краю стола",
    "переворачиваю стол в зале",
    "я бью трактирщика кулаком в челюсть",
    "плюю ему под ноги",
    "пытаюсь незаметно срезать кошель у Сильдара",
    "иду на рыночную площадь",
    "осмотреться",
    "купить ещё одно зелье лечения",
    "я пытаюсь поджечь рыночную лавку факелом",
    "одним прыжком допрыгнуть до луны",
    "асмотреться вокрук",
    "а что вообще тут происходит?",
]


def trace(i, t, r):
    print(f"\n[{i}] → {t}")
    line = f"    kind={r.get('kind')}"
    if r.get("needs_roll") is not None:
        line += f" needs_roll={r.get('needs_roll')}"
    fz = r.get("feasibility")
    if isinstance(fz, dict):
        line += f" feas={ {k: fz.get(k) for k in ('plausible', 'probability') if k in fz} }"
    print(line)
    sp = r.get("speaker") or ""
    txt = (r.get("text") or "").replace("\n", " ")[:260]
    print("    " + (sp + ": " if sp else "") + txt)


def main():
    s = new_session(use_model=True, roster_size=6)
    m = s.model
    print("online:", m is not None and m.available())
    print("router→", m.model_for("router"), "arbiter→", m.model_for("arbiter"),
          "consequence→", m.model_for("consequence"))
    for i, t in enumerate(SCRIPT, 1):
        r = s.handle(t)
        trace(i, t, r)
        if r.get("kind") == "roll_request" or r.get("needs_roll"):
            face = 18 if i % 2 == 0 else 4    # чередуем успех/провал, чтобы увидеть обе ветки
            rr = s.submit_roll([face])
            print(f"    ↳ бросок [{face}]: " + (rr.get("text") or "").replace("\n", " ")[:260])
    # стойкость следов на стартовой локации (если вернёмся) — финальный осмотр
    print("\n=== финальный осмотр места ===")
    print("   ", (s.handle("что вокруг?").get("text") or "")[:400])


if __name__ == "__main__":
    main()
