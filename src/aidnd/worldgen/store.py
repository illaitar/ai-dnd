"""SQLite-БД насыщенных миров: world_id + здания (фактшит). Дешёвое переиспользование: load, без LLM.

Файл по умолчанию <repo>/data/worlds.db (override через AIDND_WORLDS_DB). Коммитится — мир едет на прод.
"""

from __future__ import annotations

import json
import os
import sqlite3


def _default_path() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "worlds.db")


class WorldStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("AIDND_WORLDS_DB") or _default_path()
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS worlds (id INTEGER PRIMARY KEY, seed INT, "
                      "key_buildings INT, river INT, walls INT, segment REAL, created TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS buildings (world_id INT, building_id TEXT, is_key INT, "
                      "node INT, sign TEXT, data TEXT, PRIMARY KEY(world_id, building_id))")

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def upsert_world(self, world_id: int, seed: int, key_buildings: int, river: bool,
                     walls: bool, segment=None) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO worlds (id,seed,key_buildings,river,walls,segment,created) "
                      "VALUES (?,?,?,?,?,?,datetime('now'))",
                      (world_id, int(seed), int(key_buildings), int(river), int(walls), segment))

    def save_building(self, world_id: int, building_id: str, is_key: bool, node: int,
                      sign: str | None, data: dict) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO buildings (world_id,building_id,is_key,node,sign,data) "
                      "VALUES (?,?,?,?,?,?)",
                      (world_id, building_id, int(is_key), node, sign,
                       json.dumps(data, ensure_ascii=False)))

    def get_building(self, world_id: int, building_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM buildings WHERE world_id=? AND building_id=?",
                          (world_id, building_id)).fetchone()
        return _row(r) if r else None

    def find_world(self, seed: int, key_buildings: int, river: bool, walls: bool, segment=None) -> int | None:
        seg = None if segment in (None, "", 0, 0.0) else round(float(segment), 2)
        with self._conn() as c:
            r = c.execute("SELECT id FROM worlds WHERE seed=? AND key_buildings=? AND river=? AND walls=? "
                          "AND (segment IS ? OR segment=?)",
                          (int(seed), int(key_buildings), int(river), int(walls), seg, seg)).fetchone()
        return r["id"] if r else None

    def world(self, world_id: int) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM worlds WHERE id=?", (world_id,)).fetchone()
        return dict(r) if r else None

    def count(self, world_id: int) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM buildings WHERE world_id=?", (world_id,)).fetchone()[0]


def _row(r) -> dict:
    return {"building_id": r["building_id"], "is_key": bool(r["is_key"]), "node": r["node"],
            "sign": r["sign"], "data": json.loads(r["data"])}
