"""CLI-точка входа НОВОГО контура.

Запуск:  python -m aidnd            (веб-сервер)
         python -m aidnd serve      (то же)

Старый терминальный игровой цикл (bootstrap/runtime/rules) снесён — интерфейс игрока
строится заново на mind+citygraph+worldgen (aidnd.play).
"""

from __future__ import annotations

import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd in ("serve", "web", ""):
        from .server.app import run
        run()
    else:
        print(f"неизвестная команда «{cmd}». Доступно: serve")
        sys.exit(2)


if __name__ == "__main__":
    main()
