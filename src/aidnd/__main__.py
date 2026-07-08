"""CLI entry point for the NEW control loop.

Run:     python -m aidnd            (web server)
         python -m aidnd serve      (same)

The old terminal game loop (bootstrap/runtime/rules) has been removed — the player interface
is rebuilt from scratch on mind+citygraph+worldgen (population — worldgen.population).

Key functions
-------------
main() -> None : CLI dispatcher; routes 'serve'/'web' to web server, errors on unknown commands.
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
