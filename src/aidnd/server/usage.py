"""Лимиты бесплатного тарифа + разблокировка безлимита кодом.

На юзера: FREE_ENRICH генераций мира и FREE_REQUESTS игровых запросов. Валидный код,
введённый в настройках, ставит user.unlimited=True. Коды генерит владелец (server/gencode).
consume_* перечитывают юзера в текущей сессии БД (кэш на WS-коннекте мог устареть)."""

from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import config
from .models import UnlockCode, User


def snapshot(user: User) -> dict:
    """Состояние лимитов для UI-шкалы."""
    return {"unlimited": bool(user.unlimited),
            "enrich": {"used": int(user.enrich_used), "free": config.FREE_ENRICH},
            "requests": {"used": int(user.request_used), "free": config.FREE_REQUESTS}}


async def _get(db: AsyncSession, user_id: int) -> User:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


async def consume_enrich(db: AsyncSession, user_id: int) -> tuple[bool, User]:
    """Списать 1 генерацию мира. (ok, свежий user). ok=False — лимит исчерпан."""
    user = await _get(db, user_id)
    if not user.unlimited:
        if user.enrich_used >= config.FREE_ENRICH:
            return False, user
        user.enrich_used += 1
        await db.commit()
    return True, user


async def consume_request(db: AsyncSession, user_id: int) -> tuple[bool, User]:
    """Списать 1 игровой запрос. (ok, свежий user). ok=False — лимит исчерпан."""
    user = await _get(db, user_id)
    if not user.unlimited:
        if user.request_used >= config.FREE_REQUESTS:
            return False, user
        user.request_used += 1
        await db.commit()
    return True, user


async def redeem(db: AsyncSession, user_id: int, code: str) -> tuple[bool, User]:
    """Погасить код → unlimited. (ok, свежий user). ok=False — код неверный/использован."""
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
    """Создать n кодов разблокировки (для владельца, server/gencode)."""
    codes = []
    for _ in range(max(1, n)):
        c = secrets.token_hex(4).upper()                 # 8 hex-символов, легко продиктовать
        db.add(UnlockCode(code=c))
        codes.append(c)
    await db.commit()
    return codes
