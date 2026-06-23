"""QLoRA SFT одного адаптера через Unsloth (запускать НА сервере с CUDA, RTX 4070 Ti Super).

Запуск (на сервере, после prepare.py):
    source config.env
    python train_lora.py --adapter quest

16 ГБ VRAM → 4-bit база (load_in_4bit). Учим ТОЛЬКО ответ ассистента
(train_on_responses_only) — модель не тратит ёмкость на воспроизведение промпта.
Сохраняет LoRA-адаптер в out/<adapter>/ (его потом конвертим в GGUF для Ollama).
"""

from __future__ import annotations

import argparse
import json
import os

# Unsloth при загрузке шлёт анонимный телеметрический stats-пинг с таймаутом 120 с.
# На сервере этот эндпойнт недоступен → таймаут → unsloth ложно падает с «HuggingFace
# is down» ещё ДО скачивания модели. Флаг проверяется в get_statistics на старте
# from_pretrained, поэтому ставим до импорта unsloth. (Скачивание самой модели работает.)
os.environ.setdefault("UNSLOTH_DISABLE_STATISTICS", "1")


def make_loss_logger(log_path: str):
    """TrainerCallback: пишет {step,loss,lr,epoch,pct} в JSONL и печатает строку на каждый лог-шаг."""
    from transformers import TrainerCallback

    class LossLogger(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kw):
            if not logs or "loss" not in logs:
                return
            total = state.max_steps or 0
            rec = {"step": state.global_step, "total": total,
                   "pct": round(100 * state.global_step / total, 1) if total else None,
                   "loss": round(float(logs["loss"]), 4),
                   "lr": logs.get("learning_rate"),
                   "epoch": round(float(logs.get("epoch", 0)), 3)}
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            print(f"[train {rec['step']}/{total} {rec['pct']}%] loss={rec['loss']} "
                  f"lr={rec['lr']:.2e} epoch={rec['epoch']}", flush=True)

    return LossLogger()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=os.environ.get("ADAPTER", "quest"))
    ap.add_argument("--base_hf", default=os.environ.get("BASE_HF", "unsloth/Qwen2.5-1.5B-Instruct"))
    ap.add_argument("--epochs", type=float, default=float(os.environ.get("EPOCHS", "3")))
    ap.add_argument("--lr", type=float, default=float(os.environ.get("LR", "2e-4")))
    ap.add_argument("--r", type=int, default=int(os.environ.get("LORA_R", "16")))
    ap.add_argument("--alpha", type=int, default=int(os.environ.get("LORA_ALPHA", "32")))
    ap.add_argument("--max_seq", type=int, default=int(os.environ.get("MAX_SEQ", "4096")))
    ap.add_argument("--batch", type=int, default=int(os.environ.get("BATCH", "2")))
    ap.add_argument("--grad_accum", type=int, default=int(os.environ.get("GRAD_ACCUM", "8")))
    ap.add_argument("--seed", type=int, default=int(os.environ.get("SEED", "1337")))
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    train_path = os.path.join(here, "data", a.adapter, "train.jsonl")
    out_dir = os.path.join(here, "out", a.adapter)
    os.makedirs(out_dir, exist_ok=True)

    # Тяжёлые импорты — лениво, чтобы файл читался/линтился и на машине без CUDA.
    # Qwen3.5 (qwen35, MoE+GatedDeltaNet, мультимодаль) грузится через FastModel.
    from unsloth import FastModel  # noqa: E402
    from unsloth.chat_templates import train_on_responses_only  # noqa: E402
    from datasets import load_dataset  # noqa: E402
    from trl import SFTConfig, SFTTrainer  # noqa: E402

    model, tok = FastModel.from_pretrained(
        model_name=a.base_hf, max_seq_length=a.max_seq, load_in_4bit=True, full_finetuning=False)
    # LoRA только на языковую часть (vision не трогаем); внутр. маппинг модулей — на стороне unsloth.
    model = FastModel.get_peft_model(
        model, r=a.r, lora_alpha=a.alpha, lora_dropout=0.0, bias="none",
        finetune_vision_layers=False, finetune_language_layers=True,
        finetune_attention_modules=True, finetune_mlp_modules=True,
        use_gradient_checkpointing="unsloth", random_state=a.seed)

    def render(ex):
        try:                              # без reasoning-токенов: учим прямой JSON-ответ
            txt = tok.apply_chat_template(ex["messages"], tokenize=False,
                                          add_generation_prompt=False, enable_thinking=False)
        except TypeError:                 # шаблон без enable_thinking
            txt = tok.apply_chat_template(ex["messages"], tokenize=False,
                                          add_generation_prompt=False)
        return {"text": txt}

    ds = load_dataset("json", data_files=train_path, split="train")
    ds = ds.map(render)

    log_path = os.path.join(out_dir, "train_log.jsonl")
    open(log_path, "w").close()   # свежий лог на каждый запуск
    trainer = SFTTrainer(
        model=model, tokenizer=tok, train_dataset=ds, callbacks=[make_loss_logger(log_path)],
        args=SFTConfig(
            dataset_text_field="text", max_seq_length=a.max_seq,
            per_device_train_batch_size=a.batch, gradient_accumulation_steps=a.grad_accum,
            warmup_ratio=0.05, num_train_epochs=a.epochs, learning_rate=a.lr,
            logging_steps=1, optim="adamw_8bit", weight_decay=0.01,
            lr_scheduler_type="cosine", seed=a.seed, output_dir=os.path.join(out_dir, "_ckpt"),
            report_to="none"))

    # Учим только токены ответа ассистента (маска промпта) — формат Qwen/ChatML.
    # Шаблон Qwen3.5 свежий: если маркеры не совпадут — не падаем, учим всю последовательность.
    try:
        trainer = train_on_responses_only(
            trainer,
            instruction_part="<|im_start|>user\n",
            response_part="<|im_start|>assistant\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] train_on_responses_only отключён ({exc}); учу полную последовательность",
              flush=True)

    trainer.train()
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    print(f"[{a.adapter}] LoRA-адаптер сохранён → {out_dir}")


if __name__ == "__main__":
    main()
