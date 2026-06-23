"""Мердж LoRA-адаптера в базу → полный fp16 HF-чекпойнт (для конвертации в GGUF).

Запуск НА СЕРВЕРЕ:  python merge_lora.py --adapter quest
Обходит острый угол LoRA→GGUF конвертера (reorder голов): полный конвертер
convert_hf_to_gguf.py работает с целыми тензорами и qwen35 поддерживает.
"""

from __future__ import annotations

import argparse
import os

os.environ.setdefault("UNSLOTH_DISABLE_STATISTICS", "1")  # иначе телеметрия виснет 120с

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=os.environ.get("ADAPTER", "quest"))
    ap.add_argument("--max_seq", type=int, default=int(os.environ.get("MAX_SEQ", "2048")))
    a = ap.parse_args()

    out_dir = os.path.join(HERE, "out", a.adapter)
    merged = os.path.join(out_dir, "merged_16bit")

    from unsloth import FastModel
    model, tok = FastModel.from_pretrained(model_name=out_dir, max_seq_length=a.max_seq,
                                           load_in_4bit=True)
    print(f"[merge] {out_dir} → {merged} (merged_16bit)", flush=True)
    model.save_pretrained_merged(merged, tok, save_method="merged_16bit")
    print(f"[merge] готово → {merged}", flush=True)


if __name__ == "__main__":
    main()
