"""Before/after ПРЯМО на обученных весах (unsloth/HF), без Ollama/GGUF.

Запуск НА СЕРВЕРЕ:
    . .venv/bin/activate
    python eval_hf.py --adapter quest

Грузит базу + LoRA одним разом; «после» = с адаптером, «до» = тот же путь с
выключенным адаптером (model.disable_adapter) — апельсины с апельсинами.
Метрика — валидатор квест-билда (datasets/quests/build.validate). Обходит острый
угол GGUF-конвертера LoRA (reorder голов внимания), который не нужен для оценки качества.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

os.environ.setdefault("UNSLOTH_DISABLE_STATISTICS", "1")  # иначе телеметрия виснет 120с и падает

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "datasets", "quests"))

import build as quest_build  # noqa: E402
from eval_compare import extract_json  # noqa: E402  (переиспользуем парсер JSON)


def gen(model, tok, sys_user: list[dict], max_new: int) -> str:
    import torch
    # Qwen3.5-9B мультимодальна → tok это ПРОЦЕССОР. apply_chat_template зовём на нём,
    # но кодируем/декодируем ТЕКСТОВЫМ токенизатором (иначе строка уходит в images→load_image).
    enc = getattr(tok, "tokenizer", tok)
    try:
        prompt = tok.apply_chat_template(sys_user, tokenize=False,
                                         add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        prompt = tok.apply_chat_template(sys_user, tokenize=False, add_generation_prompt=True)
    inputs = enc(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new, do_sample=False,
                             pad_token_id=enc.eos_token_id)
    return enc.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)


def run(model, tok, rows, max_new) -> dict:
    parsed = valid = 0
    from collections import Counter
    errs: Counter = Counter()
    for r in rows:
        msgs = r["messages"]
        spec = json.loads(msgs[1]["content"])
        txt = gen(model, tok, [msgs[0], msgs[1]], max_new)
        q = extract_json(txt)
        if q is None:
            errs["<no-json>"] += 1
            continue
        parsed += 1
        e = quest_build.validate(q, spec)
        if e:
            errs[e.split(":")[0].split("(")[0].strip()[:40]] += 1
        else:
            valid += 1
        print(f"  [{parsed + errs['<no-json>']}/{len(rows)}] valid={valid}", flush=True)
    n = len(rows)
    return {"n": n, "parsed": parsed, "valid": valid,
            "parse_pct": 100 * parsed / n, "valid_pct": 100 * valid / n,
            "errors": dict(errs.most_common())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=os.environ.get("ADAPTER", "quest"))
    ap.add_argument("--max_new", type=int, default=1200)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    out_dir = os.path.join(HERE, "out", a.adapter)
    eval_path = os.path.join(HERE, "data", a.adapter, "eval.jsonl")
    with open(eval_path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if a.limit:
        rows = rows[:a.limit]

    from unsloth import FastModel
    model, tok = FastModel.from_pretrained(model_name=out_dir, max_seq_length=2048,
                                           load_in_4bit=True)
    FastModel.for_inference(model)

    print(f"[after] адаптер включён, {len(rows)} примеров…", flush=True)
    after = run(model, tok, rows, a.max_new)

    before = None
    disable = getattr(model, "disable_adapter", None)
    if callable(disable):
        print("[before] адаптер выключен (disable_adapter)…", flush=True)
        with model.disable_adapter():
            before = run(model, tok, rows, a.max_new)
    else:
        print("disable_adapter недоступен — «до» берём из Ollama-бейзлайна (0/20).")

    def line(tag, res):
        return (f"| {tag} | {res['n']} | {res['parsed']}/{res['n']} ({res['parse_pct']:.0f}%) | "
                f"{res['valid']}/{res['n']} ({res['valid_pct']:.0f}%) | {res['errors']} |")

    print("\n# Before/After (HF, adapter=" + a.adapter + ")")
    print("| модель | n | JSON | валидно | ошибки |")
    print("|---|---|---|---|---|")
    if before:
        print(line("BEFORE (база, adapter off)", before))
    print(line("AFTER (база + LoRA)", after))
    if before:
        print(f"\nΔ валидности: {after['valid_pct'] - before['valid_pct']:+.0f} п.п. "
              f"({before['valid_pct']:.0f}% → {after['valid_pct']:.0f}%)")

    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    with open(os.path.join(HERE, "reports", f"{a.adapter}_hf_compare.json"), "w", encoding="utf-8") as f:
        json.dump({"before": before, "after": after}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
