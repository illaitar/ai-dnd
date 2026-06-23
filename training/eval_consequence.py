"""Before/after для consequence-адаптера на HF-весах (adapter on/off), без Ollama.

Запуск НА СЕРВЕРЕ:  . .venv/bin/activate && python eval_consequence.py --adapter consequence

Consequence выдаёт {effects:[…]}. Ключевое:
  decision → решение «эмитить эффект» совпадает с эталоном (тривиальное → пусто)
  valid    → среди эмитнутых: верные kind, без чужих ключей, заземление на каст
  full     → decision + valid
«До» = тот же путь с выключенным адаптером (model.disable_adapter).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

os.environ.setdefault("UNSLOTH_DISABLE_STATISTICS", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "datasets", "quests"))

from eval_compare import extract_json  # noqa: E402
from eval_hf import gen  # noqa: E402

BAD = {"entity", "target_kind", "target_type", "type", "value", "change_kind"}
KINDS = {"place", "npc", "item", "self"}


def _cast(user: str):
    def grab(label):
        m = re.search(label + r":\s*(\[.*?\])", user)
        try:
            return [str(x).lower() for x in ast.literal_eval(m.group(1))] if m else []
        except (ValueError, SyntaxError):
            return []
    return grab("Present NPCs"), grab("Carried items")


def _action(user: str) -> str:
    m = re.findall(r"«([^»]+)»", user)
    return m[0] if m else user[:50]


def valid(pred: dict, npcs, items) -> bool:
    if not isinstance(pred, dict) or not isinstance(pred.get("effects"), list):
        return False
    for e in pred["effects"]:
        if not isinstance(e, dict) or (BAD & set(e)) or e.get("kind") not in KINDS:
            return False
        nm = (e.get("name") or "").lower()
        if e["kind"] == "npc" and nm and not any(nm in n or n in nm for n in npcs):
            return False
        if e["kind"] == "item" and nm and not any(nm in i or i in nm for i in items):
            return False
    return True


def run(model, tok, rows, max_new=160):
    parsed = dec_ok = val_ok = full_ok = 0
    misses = []
    for r in rows:
        msgs = r["messages"]
        gold = json.loads(msgs[2]["content"])
        npcs, items = _cast(msgs[1]["content"])
        txt = gen(model, tok, [msgs[0], msgs[1]], max_new)
        pred = extract_json(txt)
        if pred is None or not isinstance(pred.get("effects"), list):
            misses.append((_action(msgs[1]["content"]), "no-json/effects"))
            continue
        parsed += 1
        d = bool(pred["effects"]) == bool(gold["effects"])
        v = valid(pred, npcs, items)
        dec_ok += d
        val_ok += v
        f = d and v
        full_ok += f
        if not f:
            kinds = [e.get("kind") for e in pred["effects"] if isinstance(e, dict)]
            misses.append((_action(msgs[1]["content"]),
                          f"pred:{len(pred['effects'])}eff{kinds} vs gold:{len(gold['effects'])}eff"
                          f"{' [decision]' if not d else ''}{' [invalid]' if not v else ''}"))
    n = len(rows)
    return {"parsed": 100 * parsed / n, "decision": 100 * dec_ok / n,
            "valid": 100 * val_ok / n, "full": 100 * full_ok / n}, misses


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="consequence")
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
    a_pct, a_miss = run(model, tok, rows)
    b_pct = None
    if callable(getattr(model, "disable_adapter", None)):
        print("[before] адаптер ВЫКЛ…", flush=True)
        with model.disable_adapter():
            b_pct, _ = run(model, tok, rows)

    print(f"\n# Consequence before/after (n={len(rows)})")
    print("| модель | decision | valid | full |")
    print("|---|---|---|---|")
    if b_pct:
        print(f"| BEFORE | {b_pct['decision']:.0f}% | {b_pct['valid']:.0f}% | {b_pct['full']:.0f}% |")
    print(f"| AFTER  | {a_pct['decision']:.0f}% | {a_pct['valid']:.0f}% | {a_pct['full']:.0f}% |")
    if b_pct:
        print(f"\nΔ full: {a_pct['full'] - b_pct['full']:+.0f} п.п.  ({b_pct['full']:.0f}% → {a_pct['full']:.0f}%)")
    print(f"\nADAPTER промахи ({len(a_miss)}):")
    for inp, why in a_miss[:12]:
        print(f"  «{inp}»  {why}")

    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    with open(os.path.join(HERE, "reports", "consequence_compare.json"), "w", encoding="utf-8") as f:
        json.dump({"before": b_pct, "after": a_pct}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
