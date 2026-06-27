"""HTTP-эндпоинты лимитов: статус использования и разблокировка кодом."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from . import usage
from .db import DbSession
from .routes_auth import CurrentUser

router = APIRouter(prefix="/usage", tags=["usage"])


class Code(BaseModel):
    code: str


@router.get("")
async def my_usage(user: CurrentUser) -> dict:
    return usage.snapshot(user)


@router.post("/redeem")
async def redeem(body: Code, user: CurrentUser, db: DbSession) -> dict:
    ok, u = await usage.redeem(db, user.id, body.code)
    return {"ok": ok, "usage": usage.snapshot(u)}
