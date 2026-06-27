---
license: apache-2.0
base_model: Qwen/Qwen3-14B
language:
  - ru
pipeline_tag: text-generation
tags:
  - lora
  - qlora
  - gguf
  - ollama
  - dnd
  - russian
---

# aidnd-location

QLoRA adapter for **[Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B)**, merged and exported
to **GGUF (Q4_K_M)**, for the [AI-DnD Engine](https://github.com/illaitar/ai-dnd). It is the
`location_writer` role: it turns a **structured location spec into a terse, grounded prose
description** for a Russian D&D frontier setting — including a one-level tree of
sub-locations (a tavern's *common room / kitchen / cellar*, a ruin's *cellar pit*).

- **Base:** Qwen3-14B · **Method:** QLoRA (4-bit), merged → GGUF Q4_K_M
- **Input:** location parameters — `type`, `size`, `material`, `condition`, `smell`, `sound`,
  `light`, `air`, `mood`, `affordances`, … (rendered by `location_user`)
- **Output:** 3–5 sentences, concrete sensory detail, **no purple prose, no invented
  elements, no numbers** — живой, простой, заземлённый стиль
- **Dataset:** 534 nodes (154 locations + 380 sub-locations) across 20+ archetypes,
  parametrized as a tree (`datasets/location/`)

## Use with Ollama

```bash
huggingface-cli download Illaitar/aidnd-location location-q4_k_m.gguf Modelfile --local-dir aidnd-location
cd aidnd-location && ollama create aidnd-location -f Modelfile
ollama run aidnd-location "Локация «Кузница» (тип: smithy; запах: угар, окалина; свет: багровый от горна). Опиши место для рассказчика: 3-5 предложений."
```

Trained with the QLoRA pipeline in [`training/`](https://github.com/illaitar/ai-dnd/tree/main/training)
(Unsloth → merge 16-bit → `convert_hf_to_gguf` → quantize → Ollama). One of several per-role
adapters; see the [model overview](https://github.com/illaitar/ai-dnd/blob/main/docs/models.md).
