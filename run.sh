#!/usr/bin/env bash
# Run the AI-DnD Engine. Usage:
#   ./run.sh            — play in the terminal (CLI)
#   ./run.sh serve      — web server at http://127.0.0.1:8000  (live map at /map)
#   ./run.sh doctor     — check model-server availability (optional SSH tunnel)
#   ./run.sh test       — run pytest
#   ./run.sh lint       — run ruff
#   ./run.sh eval       — eval scenes (LLM-as-judge); pass --offline to run without a server
set -e
cd "$(dirname "$0")"

# Prefer uv; fall back to a local .venv.
if command -v uv >/dev/null 2>&1; then
  PY="uv run python"
  RUFF="uv run ruff"
else
  if [ ! -d .venv ]; then python3 -m venv .venv && .venv/bin/pip install -q -e .; fi
  PY=".venv/bin/python"
  RUFF=".venv/bin/ruff"
fi

# Optional: SSH tunnel to the model server (Ollama), e.g.
#   ssh -fN -L 11434:localhost:11434 user@host

case "${1:-play}" in
  serve)  exec $PY -m aidnd serve ;;
  doctor) exec $PY -m aidnd doctor ;;
  test)   exec $PY -m pytest -q ;;
  lint)   exec $RUFF check . ;;
  eval)   shift; exec $PY -m aidnd.eval "$@" ;;
  *)      exec $PY -m aidnd ;;
esac
