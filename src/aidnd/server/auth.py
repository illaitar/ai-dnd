"""Auth сервиса: argon2-пароли, непрозрачные отзывные токены сессий, зависимость current_user,
регистрация/вход (email+пароль) и приём Google-аккаунта (id_token). Токены живут в auth_sessions."""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Annotated

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import config
from .db import DbSession
from .models import AuthSession, User

_ph = PasswordHasher()
COOKIE = "aidnd_session"                                  # имя cookie сессии


def set_session_cookie(response: Response, token: str) -> None:
    """HttpOnly-cookie сессии: авто-отправляется на HTTP и на WS-хендшейк (тот же origin).
    secure=True за TLS (AIDND_COOKIE_SECURE=1) — кука уходит только по HTTPS."""
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=config.COOKIE_SECURE,
                        max_age=config.SESSION_TTL_DAYS * 86400, path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def hash_pw(pw: str) -> str:
    return _ph.hash(pw)


def verify_pw(pw_hash: str, pw: str) -> bool:
    try:
        return _ph.verify(pw_hash, pw)
    except VerifyMismatchError:
        return False


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _bearer(authorization: str) -> str:
    return authorization.removeprefix("Bearer ").strip() if authorization else ""


async def issue_token(db: AsyncSession, user: User) -> str:
    """Выдать непрозрачный токен сессии (хранится в auth_sessions, отзывной)."""
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token=token, user_id=user.id,
                       expires_at=_utcnow() + dt.timedelta(days=config.SESSION_TTL_DAYS)))
    await db.commit()
    return token


async def register(db: AsyncSession, email: str, password: str) -> tuple[User, str]:
    email = (email or "").strip().lower()
    if not email or "@" not in email or len(password or "") < 6:
        raise HTTPException(400, "нужны email и пароль (минимум 6 символов)")
    exists = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "этот email уже зарегистрирован")
    user = User(email=email, pw_hash=hash_pw(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, await issue_token(db, user)


async def login(db: AsyncSession, email: str, password: str) -> tuple[User, str]:
    email = (email or "").strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user or not user.pw_hash or not verify_pw(user.pw_hash, password):
        raise HTTPException(401, "неверный email или пароль")
    return user, await issue_token(db, user)


async def verify_google_idtoken(id_token: str) -> dict:
    """Проверить Google id_token (tokeninfo) и aud==наш client_id. Возвращает claims."""
    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(503, "вход через Google не настроен")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token})
    if r.status_code != 200:
        raise HTTPException(401, "недействительный Google-токен")
    claims = r.json()
    if claims.get("aud") != config.GOOGLE_CLIENT_ID:
        raise HTTPException(401, "Google-токен выписан не для этого приложения")
    return claims


async def login_google(db: AsyncSession, id_token: str) -> tuple[User, str]:
    claims = await verify_google_idtoken(id_token)
    sub, email = claims.get("sub"), (claims.get("email") or "").lower()
    name = claims.get("name")
    user = (await db.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    if not user and email:                               # привязать к существующему email-аккаунту
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user and not user.google_sub:
            user.google_sub = sub
    if not user:
        user = User(email=email or f"{sub}@google.local", google_sub=sub, display_name=name)
        db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, await issue_token(db, user)


async def user_for_token(db: AsyncSession, token: str) -> User | None:
    if not token:
        return None
    sess = (await db.execute(select(AuthSession).where(AuthSession.token == token))).scalar_one_or_none()
    if not sess or sess.expires_at < _utcnow():
        return None
    return (await db.execute(select(User).where(User.id == sess.user_id))).scalar_one_or_none()


async def revoke(db: AsyncSession, token: str) -> None:
    sess = (await db.execute(select(AuthSession).where(AuthSession.token == token))).scalar_one_or_none()
    if sess:
        await db.delete(sess)
        await db.commit()


async def current_user(db: DbSession,
                       authorization: Annotated[str, Header()] = "",
                       aidnd_session: Annotated[str, Cookie()] = "") -> User:
    """Зависимость FastAPI: токен из cookie сессии ИЛИ Bearer-заголовка, иначе 401."""
    user = await user_for_token(db, _bearer(authorization) or aidnd_session)
    if not user:
        raise HTTPException(401, "требуется вход")
    return user
