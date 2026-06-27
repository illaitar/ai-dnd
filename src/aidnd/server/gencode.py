"""CLI владельца: сгенерировать коды разблокировки безлимита.

  python -m aidnd.server.gencode [N]     # N кодов (по умолчанию 1), печатает их по одному
"""

from __future__ import annotations

import asyncio
import sys

from . import usage
from .db import SessionLocal, init_db


async def _main(n: int) -> None:
    await init_db()
    async with SessionLocal() as db:
        for code in await usage.generate_codes(db, n):
            print(code)


if __name__ == "__main__":
    asyncio.run(_main(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
