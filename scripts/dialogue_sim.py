"""Сырой диалог с игроком в таверне: LLM озвучивает NPC, состояние (симпатия+настроение) дрейфует
по ходу и кормит каждую реплику. 10 реплик игрока, базовая симпатия к нему. Механика диалог пока не
тянет (нет соц-целей) — это делает LLM-слой, гейтя тон отношением/эмоцией.

  AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=$(tr -d '\\n\\r' < .secrets/deepseek.key) \\
      .venv/bin/python scripts/dialogue_sim.py
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.inference import ModelManager  # noqa: E402

PERSONA = (
    "Ты — Мара, подавальщица в таверне «Пьяный вепрь» на фронтире. Бойкая на язык, тёплая, но себе на "
    "уме; повидала всякого. Отвечаешь В ХАРАКТЕРЕ, живой разговорной речью, 1-3 фразы, без ремарок-описаний. "
    "У тебя есть ТЕКУЩЕЕ отношение к собеседнику (affinity 0..1) и настроение — они управляют тоном: низкая "
    "симпатия = суховато/настороже, высокая = тепло/игриво; раздражил — холоднее. После реплики ОБНОВИ "
    "своё отношение по тому, как он себя повёл (льстит/уважает/помогает → выше; хамит/давит/подозрителен → "
    "ниже). Верни СТРОГО JSON: {\"reply\":\"...\", \"affinity\":0.0-1.0, \"mood\":\"одно слово\"}."
)

PLAYER = [
    "Привет, Мара. Тяжёлый выдался денёк?",
    "У вас тут всегда так шумно по вечерам?",
    "А ты сама давно в этом городке?",
    "Красивая заколка. Подарок от кого-то?",
    "Плесни ещё эля, и если есть чем закусить — тащи.",
    "Слыхал, на северном тракте пошаливают. До вас доходило что-нибудь?",
    "Да брось, по глазам вижу — ты знаешь больше, чем говоришь.",
    "Ладно, не хмурься. Я не из тех, кто лезет не в своё дело.",
    "А после смены — может, покажешь, где тут наливают что покрепче?",
    "Спасибо, Мара. С тобой этот тракт кажется не таким уж и глухим.",
]


def _parse(t):
    if not t:
        return None
    t = re.sub(r"```$", "", re.sub(r"^```(?:json)?", "", t.strip()).strip()).strip()
    try:
        return json.loads(t[t.find("{"):t.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def bar(v):
    n = int(round(v * 10))
    return "█" * n + "·" * (10 - n)


def run():
    mgr = ModelManager()
    if not mgr.available():
        print("LLM недоступен — запусти с AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=...")
        sys.exit(1)
    affinity, mood = 0.4, "нейтральное"          # БАЗОВАЯ симпатия к игроку
    history = []
    print(f"═══ Таверна «Пьяный вепрь». Мара, базовая симпатия к игроку {affinity:.2f} ═══\n")
    for i, line in enumerate(PLAYER, 1):
        ctx = "\n".join(history[-6:])
        user = (f"ТВОЁ СОСТОЯНИЕ СЕЙЧАС: симпатия {affinity:.2f}, настроение «{mood}».\n"
                f"Недавний разговор:\n{ctx or '(только подошёл)'}\n\nИгрок говорит: «{line}»\n"
                f"Ответь в характере и обнови отношение (JSON).")
        resp = mgr.call("npc_mind", [{"role": "system", "content": PERSONA},
                                     {"role": "user", "content": user}],
                        schema=True, options={"temperature": 0.8})
        d = _parse(resp.get("content") if resp else None) or {}
        reply = str(d.get("reply", "…")).strip()
        na = d.get("affinity")
        if isinstance(na, (int, float)):
            affinity = max(0.0, min(1.0, float(na)))
        mood = str(d.get("mood", mood)).strip()[:16]
        print(f"[{i:2}] Игрок: {line}")
        print(f"     Мара:  {reply}")
        print(f"           симпатия [{bar(affinity)}] {affinity:.2f}  · {mood}\n")
        history.append(f"Игрок: {line}")
        history.append(f"Мара: {reply}")
    print(f"═══ Итог: симпатия {affinity:.2f} ({mood}) ═══")


if __name__ == "__main__":
    run()
