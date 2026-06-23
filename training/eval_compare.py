"""Before/after на eval-выборке: база vs дообученный адаптер, объективная метрика.

Запуск (туннель к Ollama поднят):
    source config.env
    python eval_compare.py --adapter quest --before "$BASE_OLLAMA" --after aidnd-quest

Использует ЕДИНСТВЕННЫЙ переиспользуемый из ai-dnd механизм — запрос модели с
сервера (aidnd.inference.client.OllamaClient). Метрика — валидатор квест-билда
(datasets/quests/build.validate): % распарсенного JSON и % прошедшего валидацию
(echo kind/theme/tier/giver, предикаты из allowed, нет выдуманных id, структура стадий).
Любую из двух моделей можно пропустить, если её нет в Ollama.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "datasets", "quests"))

from aidnd.inference.client import ModelManager, OllamaClient, OllamaError  # noqa: E402
import build as quest_build  # noqa: E402


def extract_json(text: str) -> dict | None:
    """Достаёт первый сбалансированный {...} из ответа модели (терпимо к ```/прозе)."""
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            esc = (c == "\\") and not esc
            if c == '"' and not esc:
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def score(client: OllamaClient, model: str, rows: list[dict]) -> dict:
    """Прогоняет модель по eval-строкам, возвращает метрики + по-примерные результаты."""
    parsed_ok = valid_ok = 0
    errors: Counter = Counter()
    cases: list[dict] = []
    for r in rows:
        msgs = r["messages"]
        spec_in = json.loads(msgs[1]["content"])
        sys_user = [msgs[0], msgs[1]]
        try:
            out = client.chat(model, sys_user, options={"temperature": 0})["content"]
        except OllamaError as exc:
            errors["<request-error>"] += 1
            cases.append({"spec": spec_in, "error": f"request: {exc}", "raw": ""})
            continue
        quest = extract_json(out)
        if quest is None:
            errors["<no-json>"] += 1
            cases.append({"spec": spec_in, "error": "no-json", "raw": out[:400]})
            continue
        parsed_ok += 1
        err = quest_build.validate(quest, spec_in)
        if err:
            errors[err.split(":")[0].split("(")[0].strip()[:40]] += 1
            cases.append({"spec": spec_in, "error": err, "quest": quest})
        else:
            valid_ok += 1
            cases.append({"spec": spec_in, "error": None, "quest": quest})
    n = len(rows)
    return {"model": model, "n": n, "parsed": parsed_ok, "valid": valid_ok,
            "parse_pct": 100 * parsed_ok / n if n else 0,
            "valid_pct": 100 * valid_ok / n if n else 0,
            "errors": dict(errors.most_common()), "cases": cases}


def report(adapter: str, before: dict | None, after: dict | None) -> str:
    L = [f"# Before/After — адаптер `{adapter}`\n"]
    L.append("| модель | n | JSON распарсен | прошёл валидацию |")
    L.append("|---|---|---|---|")
    for tag, res in (("BEFORE (база)", before), ("AFTER (адаптер)", after)):
        if res:
            L.append(f"| {tag}: `{res['model']}` | {res['n']} | "
                     f"{res['parsed']}/{res['n']} ({res['parse_pct']:.0f}%) | "
                     f"{res['valid']}/{res['n']} ({res['valid_pct']:.0f}%) |")
        else:
            L.append(f"| {tag} | — | пропущено (нет модели) | — |")
    if before and after:
        d = after["valid_pct"] - before["valid_pct"]
        L.append(f"\n**Δ валидности: {d:+.0f} п.п.** ({before['valid_pct']:.0f}% → {after['valid_pct']:.0f}%)\n")
    for tag, res in (("BEFORE", before), ("AFTER", after)):
        if not res:
            continue
        L.append(f"\n## {tag} — типы ошибок")
        L.append("```")
        for k, v in (res["errors"] or {"<нет>": 0}).items():
            L.append(f"{v:3d}  {k}")
        L.append("```")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=os.environ.get("ADAPTER", "quest"))
    ap.add_argument("--before", default=os.environ.get("BASE_OLLAMA", "qwen2.5:1.5b-instruct"))
    ap.add_argument("--after", default=None, help="тег дообученной модели, напр. aidnd-quest")
    ap.add_argument("--limit", type=int, default=0, help="ограничить число eval-примеров")
    a = ap.parse_args()

    eval_path = os.path.join(HERE, "data", a.adapter, "eval.jsonl")
    with open(eval_path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if a.limit:
        rows = rows[:a.limit]

    client = OllamaClient()
    installed = set()
    try:
        installed = set(client.list_models())
    except OllamaError as exc:
        print(f"Ollama недоступна ({exc}). Подними туннель: ./scripts/tunnel.sh", file=sys.stderr)
        sys.exit(2)

    def run(tag):
        if not tag:
            return None
        # Ollama хранит имена с тегом (aidnd-quest:latest) — матчим терпимо.
        name = tag if tag in installed else (f"{tag}:latest" if f"{tag}:latest" in installed else None)
        if name is None:
            print(f"  пропуск {tag!r}: нет в Ollama (есть: {sorted(installed)})")
            return None
        print(f"  гоняю {name} по {len(rows)} примерам…")
        return score(client, name, rows)

    before, after = run(a.before), run(a.after)
    rep = report(a.adapter, before, after)
    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    out = os.path.join(HERE, "reports", f"{a.adapter}_compare.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(rep)
    print("\n" + rep)
    print(f"отчёт → {os.path.relpath(out)}")


if __name__ == "__main__":
    main()
