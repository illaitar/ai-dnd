"""Персистентность (док 08 §5).

Источник истины — event log. Пре-ген детерминирован от сида, поэтому сохраняем
сид + рантайм-лог + позицию часов. Загрузка: восстановить пре-ген из сида, затем
реплей хвоста событий. Снапшоты материализованного состояния — оптимизация поверх
(в прототипе храним лог целиком, реплей быстрый).
"""

from __future__ import annotations

import json
import os

from .world import World


def save(world: World, save_dir: str) -> str:
    os.makedirs(save_dir, exist_ok=True)
    meta = {
        "seed": world.seed,
        "tick": world.clock.tick,
        "events": world.log.count(),
        "player_id": world.player_id,
    }
    with open(os.path.join(save_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    with open(os.path.join(save_dir, "events.jsonl"), "w", encoding="utf-8") as f:
        f.write(world.log.dumps())
    return save_dir


def load_events(world: World, save_dir: str) -> None:
    """Реплеит сохранённые события поверх (уже построенного из сида) мира."""
    path = os.path.join(save_dir, "events.jsonl")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    from .events import Event
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        ev = Event.from_dict(json.loads(line))
        world.log.append(ev)
        world.clock.tick = max(world.clock.tick, ev.tick)
        world.apply(ev)


def read_meta(save_dir: str) -> dict | None:
    path = os.path.join(save_dir, "meta.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
