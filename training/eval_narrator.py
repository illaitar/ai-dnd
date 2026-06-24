"""Прозовый before/after для НАРРАТОРА (eval_compare.py не годится — он ждёт JSON в
user-сообщении, а у нарратора там текст narrator_user()).

Гоняет base и адаптер по held-out eval (data/narrator/eval.jsonl) на одних промптах,
печатает side-by-side и агрегаты СТИЛЯ (длина, пафосные клише, цифры в прозе, перевод
канон-имён, начало с имени говорящего). Никакого LLM-судьи — глазами + простые метрики.

  python eval_narrator.py --before qwen3.5:9b --after aidnd-narrator --n 12
"""

from __future__ import annotations

import argparse
import json
import os
import re

import httpx

BANNED = [
    "сердце полно", "словно сам фатум", "добро пожаловать, странник", "первые лучи",
    "первых лучей", "о, путник", "молвил", "ступай с миром", "дышит запуст",
    "клинок поёт", "тьма обнима", "туман шепч", "пляшут тени", "сама судьба", "дивн",
]
# канон-имена, которые база любит ПЕРЕВОДИТЬ — ловим кальки
NAME_LEAKS = ["каменный холм", "каменьхилл", "стоунхилл", "спящий гигант", "холлвинтер",
              "зимний зал", "чёрный паук", "стеклянный посох"]


def chat(host: str, model: str, msgs: list[dict]) -> str:
    # think:false — как в движке (OllamaClient.chat по умолчанию), иначе qwen3.5
    # тратит бюджет на размышление и возвращает пустой content.
    r = httpx.post(f"{host}/api/chat",
                   json={"model": model, "messages": msgs, "stream": False,
                         "think": False, "options": {"temperature": 0}}, timeout=180)
    r.raise_for_status()
    return (r.json().get("message", {}).get("content") or "").strip()


def style_flags(mode: str, name: str, out: str) -> dict:
    low = out.lower()
    return {
        "len": len(out),
        "banned": sum(b in low for b in BANNED),
        "digits": 1 if (mode in ("outcome", "combat", "ambient") and re.search(r"\d", out)) else 0,
        "leak": sum(s in low for s in NAME_LEAKS),
        "lead_name": 1 if (name and low.startswith(name.split()[0].lower())) else 0,
        "no_quote": 1 if (mode in ("dialogue", "greeting") and "«" not in out) else 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default="qwen3.5:9b")
    ap.add_argument("--after", default="aidnd-narrator")
    ap.add_argument("--eval", default="data/narrator/eval.jsonl")
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    ap.add_argument("--n", type=int, default=12)
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    path = a.eval if os.path.isabs(a.eval) else os.path.join(here, a.eval)
    rows = [json.loads(ln) for ln in open(path, encoding="utf-8") if ln.strip()]
    agg = {a.before: [], a.after: []}

    prepped = []
    for r in rows:
        m = r["messages"]
        sys_p, user_p, gold = m[0]["content"], m[1]["content"], m[2]["content"]
        mode = user_p.split("Mode: ", 1)[1].split(" —", 1)[0].strip()
        name = ""
        for ln in user_p.splitlines():
            if ln.startswith("NPC: "):
                name = ln[5:].split(" —", 1)[0].strip()
                break
        prepped.append((mode, name, sys_p, user_p, gold))

    def _msgs(sp, up):
        return [{"role": "system", "content": sp}, {"role": "user", "content": up}]

    # ДВА ПРОХОДА: вся база, затем весь адаптер — 1 своп модели в VRAM вместо 2N
    befores = [chat(a.host, a.before, _msgs(sp, up)) for _, _, sp, up, _ in prepped]
    afters = [chat(a.host, a.after, _msgs(sp, up)) for _, _, sp, up, _ in prepped]

    for i, (mode, name, sp, user_p, gold) in enumerate(prepped):
        b, af = befores[i], afters[i]
        agg[a.before].append(style_flags(mode, name, b))
        agg[a.after].append(style_flags(mode, name, af))
        if i < a.n:
            ctx = next((x for x in user_p.splitlines()
                        if x.startswith(("Situation:", "Resolved Outcome", "The player"))), "")
            print(f"\n{'='*78}\n[{i+1}] mode={mode}  {('NPC: '+name) if name else ''}\n  {ctx[:110]}")
            print(f"  BASE  : {b[:200]}")
            print(f"  ADAPT : {af[:200]}")
            print(f"  GOLD  : {gold[:200]}")

    print(f"\n{'#'*78}\nАГРЕГАТ СТИЛЯ ({len(rows)} промптов): меньше — лучше (кроме len)\n{'#'*78}")
    print(f"{'model':<20} {'avg_len':>7} {'banned':>7} {'digits':>7} {'name_leak':>10} "
          f"{'lead_name':>10} {'no_quote':>9}")
    for name_, fs in agg.items():
        n = len(fs) or 1
        print(f"{name_:<20} {sum(f['len'] for f in fs)//n:>7} {sum(f['banned'] for f in fs):>7} "
              f"{sum(f['digits'] for f in fs):>7} {sum(f['leak'] for f in fs):>10} "
              f"{sum(f['lead_name'] for f in fs):>10} {sum(f['no_quote'] for f in fs):>9}")


if __name__ == "__main__":
    main()
