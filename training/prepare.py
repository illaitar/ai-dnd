"""Детерминированный train/eval-сплит исходного чат-JSONL для дообучения адаптера.

Запуск:  python prepare.py --adapter quest --src ../datasets/quests/quests.jsonl --holdout 20

Сплит стратифицирован (для квестов — по tier из user-спеки), чтобы eval-выборка
была представительной. Eval-строки остаются в messages-формате: spec_in
восстанавливается из messages[1] (json), gold — из messages[2]. Никакого LLM.
"""

from __future__ import annotations

import argparse
import json
import os


def _tier(rec: dict) -> str:
    """Стратификационный ключ: tier из user-спеки (для квестов); иначе 'na'."""
    try:
        spec = json.loads(rec["messages"][1]["content"])
        return str(spec.get("tier", "na"))
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        return "na"


def split(rows: list[dict], holdout: int, seed: int) -> tuple[list[dict], list[dict]]:
    """Берём holdout строк в eval, разложив их по стратам пропорционально, детерминированно."""
    buckets: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        buckets.setdefault(_tier(r), []).append(i)
    for k in buckets:                       # детерминированный порядок внутри страты
        buckets[k].sort(key=lambda i: (json.dumps(rows[i], ensure_ascii=False), i))
    order = sorted(buckets)                 # обход страт по возрастанию ключа
    eval_idx: set[int] = set()
    step = 0
    while len(eval_idx) < min(holdout, len(rows)):
        progressed = False
        for k in order:
            if step < len(buckets[k]):
                eval_idx.add(buckets[k][step])
                progressed = True
                if len(eval_idx) >= holdout:
                    break
        if not progressed:
            break
        step += 1
    train = [r for i, r in enumerate(rows) if i not in eval_idx]
    ev = [r for i, r in enumerate(rows) if i in eval_idx]
    return train, ev


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=os.environ.get("ADAPTER", "quest"))
    ap.add_argument("--src", default=os.environ.get("SRC_JSONL", "../datasets/quests/quests.jsonl"))
    ap.add_argument("--holdout", type=int, default=int(os.environ.get("EVAL_HOLDOUT", "20")))
    ap.add_argument("--seed", type=int, default=int(os.environ.get("SEED", "1337")))
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    src = a.src if os.path.isabs(a.src) else os.path.join(here, a.src)
    with open(src, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    train, ev = split(rows, a.holdout, a.seed)
    out_dir = os.path.join(here, "data", a.adapter)
    os.makedirs(out_dir, exist_ok=True)
    for name, part in (("train", train), ("eval", ev)):
        with open(os.path.join(out_dir, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for r in part:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter
    print(f"[{a.adapter}] src={len(rows)}  train={len(train)}  eval={len(ev)} → {os.path.relpath(out_dir)}")
    print("  eval по стратам (tier):", dict(sorted(Counter(_tier(r) for r in ev).items())))


if __name__ == "__main__":
    main()
