# Running locally

The engine runs fully offline with deterministic fallbacks. A connected model only raises
quality where a role is wired in.

## Connecting a model

```bash
uv run aidnd doctor     # prints OLLAMA_HOST and whether the server is reachable
```

Expose a local [Ollama](https://ollama.com) server (e.g. via an SSH tunnel) and confirm
`server available: True`. Without it, deterministic fallbacks are used for every role.

## Run on your own hardware (fully local)

Run the model on your own machine — no remote box, no tunnel. One-time setup installs
Ollama, pulls the models and verifies:

```bash
bash scripts/setup_local.sh        # installs Ollama, pulls Qwen models, runs `doctor`
./scripts/run_local.sh serve       # web UI on http://127.0.0.1:8000
./scripts/run_local.sh             # play in the terminal
./scripts/run_local.sh debug --quest dungeon   # console playthrough
```

Models are set in `scripts/local.env` and overridable by env var:

| role | default | override |
|---|---|---|
| narration / cognition / combat / quests | `qwen2.5:7b-instruct` | `AIDND_MODEL` |
| intent classifier (fast, small) | `qwen2.5:1.5b-instruct` | `AIDND_INTENT_MODEL` |

Lighter machine? `AIDND_MODEL=qwen2.5:3b-instruct bash scripts/setup_local.sh`. The base
model wants ~6–8 GB free RAM (7B) or ~3 GB (3B); the intent model is ~1 GB. Apple Silicon
and recent Linux/NVIDIA work out of the box. The engine still falls back to deterministic
behavior for any role if the server is down.
