"""Async DB layer for service (Postgres): engine, session factory, Base, init_db.

Users / session-tokens / games. URL — config.DATABASE_URL (env AIDND_DATABASE_URL).
SQLAlchemy 2.0 async + asyncpg. Schema created via create_all (Alembic — later).

Key functions
-------------
Base : SQLAlchemy ORM declarative base for all model classes.
engine : AsyncIO PostgreSQL engine (create_async_engine) with NullPool.
SessionLocal : Async session factory bound to the engine.
init_db() -> None : Create all tables from models.metadata (idempotent).
get_session() -> AsyncIterator[AsyncSession] : FastAPI dependency yielding a DB session per request.
DbSession : Type alias (Annotated) for session dependency injection in route handlers.
"""

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


# NullPool: fresh connection per operation. asyncpg connections are bound to event-loop;
# without a pool, no cross-loop issues (HTTP+WS, tests). For our scale, overhead is minimal.
engine = create_async_engine(config.DATABASE_URL, poolclass=NullPool)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create tables if they don't exist (idempotent)."""
    from . import models  # noqa: F401 — registers tables in Base.metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: DB session per request."""
    async with SessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]   # type alias for dependency injection in route handlers
