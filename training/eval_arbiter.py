"""Before/after для arbiter-адаптера на HF-весах (adapter on/off), без Ollama.

Запуск НА СЕРВЕРЕ:  . .venv/bin/activate && python eval_arbiter.py --adapter arbiter

Арбитр выдаёт {resolution, ability, skill, dc}. DC — субъективная оценка, поэтому:
  res   → resolution точно (auto_success/auto_fail/roll)
  skill → среди gold-роллов: точный навык
  dc    → среди gold-роллов: |pred-gold| ≤ 2 (допуск)
  full  → res + (для ролла: skill и dc; для auto: только res)
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
from eval_hf import gen  # noqa: E402


def _action(user: str) -> str:
    m = re.findall(r"«([^»]+)»", user)
    return m[0] if m else user[:60]


def run(model, tok, rows, max_new=96):
    res_ok = full_ok = parsed = 0
    roll_n = skill_ok = dc_ok = 0
    misses = []
    for r in rows:
        msgs = r["messages"]
        gold = json.loads(msgs[2]["content"])
        txt = gen(model, tok, [msgs[0], msgs[1]], max_new)
        pred = extract_json(txt)
        if pred is None:
            misses.append((_action(msgs[1]["content"]), "no-json"))
            continue
        parsed += 1
        g_res, p_res = gold.get("resolution"), pred.get("resolution")
        r_ok = p_res == g_res
        res_ok += r_ok
        if g_res == "roll":
            roll_n += 1
            s_ok = r_ok and pred.get("skill") == gold.get("skill")
            skill_ok += s_ok
            try:
                d_ok = r_ok and abs(int(pred.get("dc")) - int(gold.get("dc"))) <= 2
            except (TypeError, ValueError):
                d_ok = False
            dc_ok += d_ok
            f = bool(s_ok and d_ok)
        else:
            f = bool(r_ok)
        full_ok += f
        if not f:
            misses.append((_action(msgs[1]["content"]),
                          f"pred:{p_res}/{pred.get('skill')}/{pred.get('dc')} vs "
                          f"gold:{g_res}/{gold.get('skill')}/{gold.get('dc')}"))
    n = len(rows)
    return {"res": 100 * res_ok / n, "full": 100 * full_ok / n, "parsed": 100 * parsed / n,
            "skill": 100 * skill_ok / roll_n if roll_n else 0,
            "dc": 100 * dc_ok / roll_n if roll_n else 0, "roll_n": roll_n}, misses


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="arbiter")
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

    print(f"\n# Arbiter before/after (n={len(rows)}, из них roll={a_pct['roll_n']})")
    print("| модель | resolution | skill(roll) | dc±2(roll) | full |")
    print("|---|---|---|---|---|")
    if b_pct:
        print(f"| BEFORE | {b_pct['res']:.0f}% | {b_pct['skill']:.0f}% | {b_pct['dc']:.0f}% | {b_pct['full']:.0f}% |")
    print(f"| AFTER  | {a_pct['res']:.0f}% | {a_pct['skill']:.0f}% | {a_pct['dc']:.0f}% | {a_pct['full']:.0f}% |")
    if b_pct:
        print(f"\nΔ full: {a_pct['full'] - b_pct['full']:+.0f} п.п.  ({b_pct['full']:.0f}% → {a_pct['full']:.0f}%)")
    print(f"\nADAPTER промахи ({len(a_miss)}):")
    for inp, why in a_miss[:12]:
        print(f"  «{inp}»  {why}")

    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    with open(os.path.join(HERE, "reports", "arbiter_compare.json"), "w", encoding="utf-8") as f:
        json.dump({"before": b_pct, "after": a_pct}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
