"""Снапшоты и восстановление (док 08 §5).

Источник истины — лог. Пре-ген детерминирован от сида. Загрузка: построить мир
из сида (build_world), затем реплей рантайм-хвоста. Снапшоты материализованного
состояния — оптимизация; в прототипе храним сид + лог (реплей быстрый).
"""

from __future__ import annotations

from ..world.persistence import load_events, read_meta
from ..world.persistence import save as _save_log


def save_game(world, save_dir: str) -> str:
    return _save_log(world, save_dir)


def load_game(save_dir: str, builder):
    """builder(seed) -> World строит пре-ген; затем реплеим хвост событий."""
    meta = read_meta(save_dir)
    if not meta:
        return None
    world = builder(meta["seed"])
    # сбрасываем лог пре-гена (он детерминирован) и реплеим сохранённый рантайм-лог
    load_events(world, save_dir)
    return world


def maybe_snapshot(world, every: int = 1000) -> bool:
    return world.log.count() % every == 0
