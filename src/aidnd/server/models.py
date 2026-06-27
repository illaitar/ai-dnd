"""Модели БД сервиса: users / auth_sessions / games (SQLAlchemy 2.0).

- users: аккаунт. pw_hash (argon2) и/или google_sub — поддержаны оба способа входа
  (email+пароль и Google OAuth); хотя бы один заполнен.
- auth_sessions: непрозрачные отзывные токены сессий (не stateless-JWT).
- games: сохранённые игры пользователя (снапшот мира), привязка к user_id."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    pw_hash: Mapped[str | None] = mapped_column(String(255))          # argon2; null → только OAuth
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)  # null → только пароль
    display_name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # лимиты бесплатного тарифа (разблок кодом → unlimited)
    enrich_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    request_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unlimited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)  # secrets.token_urlsafe
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    seed: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str | None] = mapped_column(String(160))
    snapshot: Mapped[str | None] = mapped_column(Text)               # сериализованный снапшот мира (JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UnlockCode(Base):
    """Код разблокировки безлимита: генерится владельцем (CLI), гасится при вводе в настройках."""
    __tablename__ = "unlock_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    grant: Mapped[str] = mapped_column(String(20), default="unlimited", server_default="unlimited")
    redeemed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    redeemed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
