# Models & training

Each model-backed role is a **per-role LoRA adapter** over a shared base model. Adapters are
trained with QLoRA (4-bit, fits 16 GB VRAM), merged/exported to GGUF and registered in
Ollama as `aidnd-<role>`, and published on Hugging Face. One base stays resident; the
adapters are light. Every role keeps a deterministic fallback, so the engine runs fully
without any of them (see [Agent roles](agents.md)).

## Published adapters

| Adapter | Role | Base | Dataset | Before → after | Hugging Face |
|---|---|---|---|---|---|
| `aidnd-router` | intent → verb/target/tone | Qwen3.5-9B | `datasets/freeform/router.jsonl` | held-out `kind` 75→92%, full 50→71% | [nikalutis/aidnd-router](https://huggingface.co/nikalutis/aidnd-router) |
| `aidnd-arbiter` | adjudicate free-form actions | Qwen3.5-9B | `datasets/freeform/arbiter.jsonl` | resolution 10→83%, dc±2 100% | [nikalutis/aidnd-arbiter](https://huggingface.co/nikalutis/aidnd-arbiter) |
| `aidnd-consequence` | world effects of an action | Qwen3.5-9B | `datasets/freeform/consequence.jsonl` | valid schema 47→100%, full 43→83% | [nikalutis/aidnd-consequence](https://huggingface.co/nikalutis/aidnd-consequence) |
| `aidnd-narrator` | render outcomes + dialogue (prose) | Qwen3.5-9B | `datasets/narrator/narrator.jsonl` (626 ex.) | keeps canon names, terse live voice | [nikalutis/aidnd-narrator](https://huggingface.co/nikalutis/aidnd-narrator) |
| `aidnd-quest` | side-quest framing + giver lines | Qwen3.5-9B | `datasets/quests/quests.jsonl` | valid quests 0→85% | [nikalutis/aidnd-quest](https://huggingface.co/nikalutis/aidnd-quest) |
| `aidnd-location` | location descriptions (parameters → prose) | Qwen3-14B | `datasets/location/location.jsonl` (534 nodes) | — | [nikalutis/aidnd-location](https://huggingface.co/nikalutis/aidnd-location) |

Bases (Ollama tags): `qwen3.5:9b` for most roles, `qwen3:14b` for `location` (14B is
markedly better at descriptive prose), `qwen3.5:2b` for the fast intent classifier.

`ModelManager.ROLE_MODELS` (`src/aidnd/inference/client.py`) maps each role to
`(base, adapter)`; `model_for()` resolves the adapter if present in Ollama and otherwise
falls back to the bare base, which in turn falls back to deterministic code.

## The `location` adapter

The newest adapter generates **parametrized location descriptions as a tree**. Each training
example is a JSON object with ~18 fields (`type`, `size`, `material`, `condition`, `smell`,
`sound`, `light`, `air`, `mood`, `affordances`, …) plus a `gold` description, and a
`sublocations` array of child places (a one-level tree — a tavern's *common room / kitchen /
cellar*, a ruin's *proval in podval*). `location_user()` renders the parameters into the
prompt for both training and inference (`train == inference`). Dataset: 154 locations + 380
sub-locations across 20+ archetypes; see `datasets/location/`.

## Training pipeline

```
datasets/<role>/build.py   →  <role>.jsonl   (style validator)
prepare.py                 →  data/<role>/{train,eval}.jsonl   (deterministic split)
train_lora.py              →  out/<role>/     (Unsloth QLoRA SFT, server)
export_ollama.sh           →  GGUF + Modelfile + `ollama create aidnd-<role>`
eval_compare.py            →  reports/<role>_compare.md   (before/after)
```

Everything is driven from `training/config.env`. The full cycle runs detached on the GPU
server (rsync + `pipeline.sh`):

```bash
cd training
# the location adapter, trained on the 14B base:
BASE_HF=unsloth/Qwen3-14B BASE_OLLAMA=qwen3:14b ADAPTER=location MAX_SEQ=1024 BATCH=1 ./run_remote.sh
./monitor.sh location                       # watch the loss / phases
```

`BASE_HF` (training weights) and `BASE_OLLAMA` (the matching Ollama tag) **must be the same
model**, or the LoRA will not apply.

## Publishing to Hugging Face

```bash
hf auth login                               # one-time
HF_REPO=nikalutis/aidnd-location ./hf/upload.sh location
```

Uploads the quantized GGUF (`q4_k_m`), a `Modelfile`, and the model card from
`hf/README_<role>.md`. See `training/README.md` for the per-adapter details and the
GGUF-export caveats.
