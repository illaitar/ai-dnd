#!/usr/bin/env python3
"""PostToolUse-хук: авто-`ruff --fix` по только что отредактированному .py.

Читает событие инструмента из stdin (JSON), берёт tool_input.file_path. Если это .py в проекте —
гонит `ruff check --fix` (тихо чинит импорты/форматирование), затем `ruff check`; если остались
НЕИСПРАВИМЫЕ ошибки — печатает их в stderr и выходит с кодом 2 (Claude Code вернёт это как фидбек,
чтобы модель их поправила). Никогда не роняет правку из-за проблем самого тулинга (нет uv/ruff →
тихий выход 0).
"""

import json
import os
import subprocess
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

path = (data.get("tool_input") or {}).get("file_path", "") or ""
if not path.endswith(".py"):
    sys.exit(0)                                    # не питон — хуку тут делать нечего

proj = os.environ.get("CLAUDE_PROJECT_DIR") or "."
if not os.path.isabs(path):
    path = os.path.join(proj, path)
if not os.path.exists(path):
    sys.exit(0)

try:
    subprocess.run(["uv", "run", "ruff", "check", "--fix", path],
                   cwd=proj, capture_output=True, text=True, timeout=60)
    left = subprocess.run(["uv", "run", "ruff", "check", path],
                          cwd=proj, capture_output=True, text=True, timeout=60)
except Exception:
    sys.exit(0)                                    # тулинг недоступен — не мешаем работе

if left.returncode != 0:                           # остались неисправимые — вернуть Claude на фикс
    rel = os.path.relpath(path, proj)
    if rel.startswith(".."):                        # файл вне проекта — показать как есть
        rel = path
    sys.stderr.write(f"ruff: остались ошибки в {rel} (авто-фикс не покрыл) — поправь:\n")
    sys.stderr.write(left.stdout or left.stderr or "")
    sys.exit(2)

sys.exit(0)
