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
            # ПУЛ NPC — мир-агностичный банк готовых людей (персона+инвентарь+портреты-пути)
            c.execute("CREATE TABLE IF NOT EXISTS people (id TEXT PRIMARY KEY, role TEXT, name TEXT, "
                      "charisma REAL, appearance REAL, mech TEXT, persona TEXT, portraits TEXT, "
                      "seed INT, created TEXT)")
            # привязка людей к конкретному миру (кто где стоит) — стейт, персист
            c.execute("CREATE TABLE IF NOT EXISTS placements (world_id INT, npc_id TEXT, node INT, "
                      "home INT, work TEXT, PRIMARY KEY(world_id, npc_id))")

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

    def building_ids(self, world_id: int) -> set:
        with self._conn() as c:
            return {r[0] for r in c.execute("SELECT building_id FROM buildings WHERE world_id=?", (world_id,))}

    def clear_world(self, world_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM buildings WHERE world_id=?", (world_id,))

    # ------------------------------------------------------ пул NPC ------- #
    def save_person(self, pid: str, role: str, name: str, charisma: float, appearance: float,
                    mech: dict, persona: dict, portraits: dict, seed: int) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO people (id,role,name,charisma,appearance,mech,persona,"
                      "portraits,seed,created) VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))",
                      (pid, role, name, float(charisma), float(appearance),
                       json.dumps(mech, ensure_ascii=False), json.dumps(persona, ensure_ascii=False),
                       json.dumps(portraits, ensure_ascii=False), int(seed)))

    def get_person(self, pid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone()
        return _person(r) if r else None

    def person_ids(self) -> set:
        with self._conn() as c:
            return {r[0] for r in c.execute("SELECT id FROM people")}

    def people_count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM people").fetchone()[0]

    def list_people(self, limit: int = 50, role: str | None = None) -> list:
        q = "SELECT * FROM people" + (" WHERE role=?" if role else "") + " LIMIT ?"
        args = ((role, limit) if role else (limit,))
        with self._conn() as c:
            return [_person(r) for r in c.execute(q, args)]

    def free_people(self, world_id: int, role: str | None = None, limit: int = 32) -> list:
        """Люди из банка, ещё НЕ привязанные к этому миру (для наполнения толпы). Опц. по роли."""
        q = ("SELECT p.* FROM people p WHERE p.id NOT IN (SELECT npc_id FROM placements WHERE world_id=?)"
             + (" AND p.role=?" if role else "") + " LIMIT ?")
        args = ((world_id, role, limit) if role else (world_id, limit))
        with self._conn() as c:
            return [_person(r) for r in c.execute(q, args)]

    def place_person(self, world_id: int, npc_id: str, node: int, home: int, work: str | None) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO placements (world_id,npc_id,node,home,work) VALUES (?,?,?,?,?)",
                      (world_id, npc_id, node, home, work))

    def placements_for(self, world_id: int) -> list:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM placements WHERE world_id=?", (world_id,))]


def _person(r) -> dict:
    return {"id": r["id"], "role": r["role"], "name": r["name"], "charisma": r["charisma"],
            "appearance": r["appearance"], "mech": json.loads(r["mech"]),
            "persona": json.loads(r["persona"]), "portraits": json.loads(r["portraits"]), "seed": r["seed"]}


def _row(r) -> dict:
    return {"building_id": r["building_id"], "is_key": bool(r["is_key"]), "node": r["node"],
            "sign": r["sign"], "data": json.loads(r["data"])}
