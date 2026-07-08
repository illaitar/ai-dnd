"""HTTP auth endpoints: /auth/register, /auth/login, /auth/google, /auth/logout, /auth/me.

Email+password (argon2) and Google (id_token from client-side Sign-In button) — both methods
return an opaque session token. Protected routes require Bearer token (current_user).

Key functions
-------------
register(body, response, db) -> dict : Create new user account with email+password.
login(body, response, db) -> dict : Authenticate user with email+password credentials.
google(body, response, db) -> dict : Authenticate user via Google id_token.
logout(response, db, authorization, aidnd_session) -> dict : Revoke current session token.
me(user) -> dict : Return authenticated user profile."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Response
from pydantic import BaseModel

from . import auth
from .db import DbSession
from .models import User

router = APIRouter(prefix="/auth", tags=["auth"])

CurrentUser = Annotated[User, Depends(auth.current_user)]


class Credentials(BaseModel):
    email: str
    password: str


class GoogleToken(BaseModel):
    id_token: str


def _user_out(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name,
            "google": bool(user.google_sub)}


@router.post("/register")
async def register(body: Credentials, response: Response, db: DbSession) -> dict:
    user, token = await auth.register(db, body.email, body.password)
    auth.set_session_cookie(response, token)
    return {"token": token, "user": _user_out(user)}


@router.post("/login")
async def login(body: Credentials, response: Response, db: DbSession) -> dict:
    user, token = await auth.login(db, body.email, body.password)
    auth.set_session_cookie(response, token)
    return {"token": token, "user": _user_out(user)}


@router.post("/google")
async def google(body: GoogleToken, response: Response, db: DbSession) -> dict:
    user, token = await auth.login_google(db, body.id_token)
    auth.set_session_cookie(response, token)
    return {"token": token, "user": _user_out(user)}


@router.post("/logout")
async def logout(response: Response, db: DbSession,
                 authorization: Annotated[str, Header()] = "",
                 aidnd_session: Annotated[str, Cookie()] = "") -> dict:
    await auth.revoke(db, auth._bearer(authorization) or aidnd_session)
    auth.clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    return _user_out(user)
