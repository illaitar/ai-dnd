"""HTTP-эндпоинты игр пользователя: список и удаление.

Сохранение/загрузка самой партии идёт через WS (там живёт сессия); здесь — метаданные."""

from __future__ import annotations

from fastapi import APIRouter

from . import games
from .db import DbSession
from .routes_auth import CurrentUser

router = APIRouter(prefix="/games", tags=["games"])


@router.get("")
async def my_games(user: CurrentUser, db: DbSession) -> dict:
    return {"games": await games.list_games(db, user.id)}


@router.delete("/{game_id}")
async def remove(game_id: int, user: CurrentUser, db: DbSession) -> dict:
    return {"ok": await games.delete_game(db, user.id, game_id)}
