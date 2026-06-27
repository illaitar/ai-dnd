"""Игры пользователя в БД: сохранить / список / снапшот / удалить (привязка к user_id).

Снапшот мира — JSON из persistence.serialize_session в games.snapshot. Восстановление
(deserialize_session) — CPU-тяжёлое; вызывающий код (WS) гонит его в треде."""

from __future__ import annotations

import json

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..runtime.persistence import serialize_session
from .models import Game


async def save_game(db: AsyncSession, user_id: int, session, title: str | None = None,
                    game_id: int | None = None) -> Game:
    """Сохранить текущую партию пользователя (новая или перезапись своей game_id)."""
    data = serialize_session(session, title or "Партия")
    snap = json.dumps(data, ensure_ascii=False)
    game = None
    if game_id is not None:
        game = (await db.execute(
            select(Game).where(Game.id == game_id, Game.user_id == user_id))).scalar_one_or_none()
        if game is None:
            raise ValueError("игра не найдена")
        game.snapshot, game.seed = snap, data["seed"]
        if title:
            game.title = title
    else:
        game = Game(user_id=user_id, seed=data["seed"], snapshot=snap,
                    title=title or (data["meta"].get("hero") or "Партия"))
        db.add(game)
    await db.commit()
    await db.refresh(game)
    return game


async def list_games(db: AsyncSession, user_id: int) -> list[dict]:
    rows = (await db.execute(select(Game).where(Game.user_id == user_id)
                             .order_by(Game.updated_at.desc()))).scalars().all()
    out = []
    for g in rows:
        meta = {}
        try:
            meta = (json.loads(g.snapshot) or {}).get("meta", {}) if g.snapshot else {}
        except (ValueError, TypeError):
            pass
        out.append({"id": g.id, "title": g.title, "seed": g.seed, "meta": meta,
                    "updated": g.updated_at.isoformat() if g.updated_at else None})
    return out


async def get_snapshot(db: AsyncSession, user_id: int, game_id: int) -> dict | None:
    """Снапшот игры пользователя (для deserialize в треде вызывающим). None — нет/чужая."""
    g = (await db.execute(
        select(Game).where(Game.id == game_id, Game.user_id == user_id))).scalar_one_or_none()
    if g is None or not g.snapshot:
        return None
    return json.loads(g.snapshot)


async def delete_game(db: AsyncSession, user_id: int, game_id: int) -> bool:
    r = await db.execute(delete(Game).where(Game.id == game_id, Game.user_id == user_id))
    await db.commit()
    return r.rowcount > 0
