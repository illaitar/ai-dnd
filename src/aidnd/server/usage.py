"""Free tier quota limits + unlimited unlock via code.

Per user: FREE_ENRICH world generations and FREE_REQUESTS game requests. A valid code
entered in settings sets user.unlimited=True. The owner generates codes (server/gencode).
consume_* re-read the user in the current DB session (cache from WS connect may be stale).

Key functions
   -----------
   snapshot(user: User) -> dict : Returns user quota state for UI.
   consume_enrich(db: AsyncSession, user_id: int) -> tuple[bool, User] : Consume world-generation quota; returns (ok, updated user).
   consume_request(db: AsyncSession, user_id: int) -> tuple[bool, User] : Consume game-request quota; returns (ok, updated user).
   redeem(db: AsyncSession, user_id: int, code: str) -> tuple[bool, User] : Redeem unlock code for unlimited access.
   generate_codes(db: AsyncSession, n: int = 1) -> list[str] : Generate new unlock codes (admin only).
"""

from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import config
from .models import UnlockCode, User


def snapshot(user: User) -> dict:
    """Quota state for UI scale."""
    return {"unlimited": bool(user.unlimited),
            "enrich": {"used": int(user.enrich_used), "free": config.FREE_ENRICH},
            "requests": {"used": int(user.request_used), "free": config.FREE_REQUESTS}}


async def _get(db: AsyncSession, user_id: int) -> User:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


async def consume_enrich(db: AsyncSession, user_id: int) -> tuple[bool, User]:
    """Consume 1 world generation. (ok, updated user). ok=False — quota exceeded."""
    user = await _get(db, user_id)
    if not user.unlimited:
        if user.enrich_used >= config.FREE_ENRICH:
            return False, user
        user.enrich_used += 1
        await db.commit()
    return True, user


async def consume_request(db: AsyncSession, user_id: int) -> tuple[bool, User]:
    """Consume 1 game request. (ok, updated user). ok=False — quota exceeded."""
    user = await _get(db, user_id)
    if not user.unlimited:
        if user.request_used >= config.FREE_REQUESTS:
            return False, user
        user.request_used += 1
        await db.commit()
    return True, user


async def redeem(db: AsyncSession, user_id: int, code: str) -> tuple[bool, User]:
    """Redeem code → unlimited. (ok, updated user). ok=False — code invalid/already used."""
    user = await _get(db, user_id)
    row = (await db.execute(
        select(UnlockCode).where(UnlockCode.code == (code or "").strip()))).scalar_one_or_none()
    if row is None or row.redeemed_by is not None:
        return False, user
    row.redeemed_by = user.id
    row.redeemed_at = dt.datetime.now(dt.UTC)
    user.unlimited = True
    await db.commit()
    return True, user


async def generate_codes(db: AsyncSession, n: int = 1) -> list[str]:
    """Generate n unlock codes (for owner, server/gencode)."""
    codes = []
    for _ in range(max(1, n)):
        c = secrets.token_hex(4).upper()                 # 8 hex digits, easy to dictate
        db.add(UnlockCode(code=c))
        codes.append(c)
    await db.commit()
    return codes
