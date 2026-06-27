"""Асинхронный слой БД сервиса (Postgres): движок, фабрика сессий, Base, init_db.

Пользователи / сессии-токены / игры. URL — config.DATABASE_URL (env AIDND_DATABASE_URL).
SQLAlchemy 2.0 async + asyncpg. Схема создаётся через create_all (Alembic — позже)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from .. import config


class Base(DeclarativeBase):
    pass


# NullPool: свежее соединение на операцию. asyncpg-соединения привязаны к event-loop;
# без пула нет кросс-loop проблем (HTTP+WS, тесты). Для нашего масштаба оверхед минимален.
engine = create_async_engine(config.DATABASE_URL, poolclass=NullPool)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Создать таблицы, если их нет (идемпотентно)."""
    from . import models  # noqa: F401 — регистрирует таблицы в Base.metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: сессия БД на запрос."""
    async with SessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]   # тип-алиас зависимости для ручек
