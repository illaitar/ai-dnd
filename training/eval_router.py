"""Before/after для router-адаптера на HF-весах (adapter on/off), без Ollama.

Запуск НА СЕРВЕРЕ:  . .venv/bin/activate && python eval_router.py --adapter router

Router — это классификация, поэтому метрика — СОВПАДЕНИЕ с эталоном (gold):
  kind  → правильный класс (query/dialogue/command/freeform)
  field → kind + тип-специфичное поле (query_type для query, verb для command)
  full  → kind + field + target (лояльно) + tone
«До» = тот же путь с выключенным адаптером (model.disable_adapter).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

os.environ.setdefault("UNSLOTH_DISABLE_STATISTICS", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "datasets", "quests"))

from eval_compare import extract_json  # noqa: E402
from eval_hf import gen  # noqa: E402  (VL-processor-safe генерация)


def _input(user: str) -> str:
    m = re.findall(r"«([^»]+)»", user)
    return m[-1] if m else user[-60:]


def _norm(t) -> str:
    return (t or "").strip().lower()


def compare(pred: dict, gold: dict) -> dict:
    if not isinstance(pred, dict):
        return {"kind": False, "field": False, "full": False}
    k = gold.get("kind")
    kind_ok = pred.get("kind") == k
    if k == "query":
        field_ok = pred.get("query_type") == gold.get("query_type")
    elif k == "command":
        field_ok = pred.get("verb") == gold.get("verb")
    else:
        field_ok = True
    tone_ok = pred.get("tone") == gold.get("tone")
    gt, pt = _norm(gold.get("target")), _norm(pred.get("target"))
    target_ok = (gt == pt) or (bool(gt) and bool(pt) and (gt in pt or pt in gt))
    return {"kind": kind_ok, "field": kind_ok and field_ok,
            "full": kind_ok and field_ok and tone_ok and target_ok}


def run(model, tok, rows, max_new=64):
    agg = {"kind": 0, "field": 0, "full": 0, "parsed": 0}
    misses = []
    for r in rows:
        msgs = r["messages"]
        gold = json.loads(msgs[2]["content"])
        txt = gen(model, tok, [msgs[0], msgs[1]], max_new)
        pred = extract_json(txt)
        if pred is None:
            misses.append((_input(msgs[1]["content"]), "no-json"))
            continue
        agg["parsed"] += 1
        c = compare(pred, gold)
        for kk in ("kind", "field", "full"):
            agg[kk] += c[kk]
        if not c["full"]:
            misses.append((_input(msgs[1]["content"]),
                          f"pred:{pred.get('kind')}/{pred.get('verb') or pred.get('query_type')}"
                          f"/{pred.get('tone')} vs gold:{gold.get('kind')}/"
                          f"{gold.get('verb') or gold.get('query_type')}/{gold.get('tone')}"))
    n = len(rows)
    pct = {k: 100 * agg[k] / n for k in ("kind", "field", "full", "parsed")}
    return agg, pct, misses


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="router")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    out_dir = os.path.join(HERE, "out", a.adapter)
    with open(os.path.join(HERE, "data", a.adapter, "eval.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    if a.limit:
        rows = rows[:a.limit]

    from unsloth import FastModel
    model, tok = FastModel.from_pretrained(model_name=out_dir, max_seq_length=2048, load_in_4bit=True)
    FastModel.for_inference(model)

    print(f"[after] адаптер ВКЛ, {len(rows)} примеров…", flush=True)
    _, a_pct, a_miss = run(model, tok, rows)

    b_pct = None
    if callable(getattr(model, "disable_adapter", None)):
        print("[before] адаптер ВЫКЛ…", flush=True)
        with model.disable_adapter():
            _, b_pct, _ = run(model, tok, rows)

    print(f"\n# Router before/after (n={len(rows)})")
    print("| модель | kind | +field | full |")
    print("|---|---|---|---|")
    if b_pct:
        print(f"| BEFORE (adapter off) | {b_pct['kind']:.0f}% | {b_pct['field']:.0f}% | {b_pct['full']:.0f}% |")
    print(f"| AFTER  (adapter on)  | {a_pct['kind']:.0f}% | {a_pct['field']:.0f}% | {a_pct['full']:.0f}% |")
    if b_pct:
        print(f"\nΔ full: {a_pct['full'] - b_pct['full']:+.0f} п.п.  ({b_pct['full']:.0f}% → {a_pct['full']:.0f}%)")
    print(f"\nADAPTER промахи ({len(a_miss)}):")
    for inp, why in a_miss[:12]:
        print(f"  «{inp}»  {why}")

    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    with open(os.path.join(HERE, "reports", "router_compare.json"), "w", encoding="utf-8") as f:
        json.dump({"before": b_pct, "after": a_pct}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
