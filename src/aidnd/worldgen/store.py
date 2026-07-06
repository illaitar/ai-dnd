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
            # выкованные предметы (фактшит) + инвентарь игрока (что держит + что вскрыто про предмет)
            c.execute("CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, data TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS inventory (world_id INT, item_id TEXT, holder TEXT, "
                      "known TEXT, PRIMARY KEY(world_id, item_id))")
            # состояние игрока-агента (память + отношения) — «игрок такой же агент, как NPC»
            c.execute("CREATE TABLE IF NOT EXISTS pc_state (world_id INT PRIMARY KEY, data TEXT)")
            # кошельки держателей (монеты — счётчик, не предмет) и флаги мира (маркеры материализации)
            c.execute("CREATE TABLE IF NOT EXISTS purse (world_id INT, holder TEXT, coins INT, "
                      "PRIMARY KEY(world_id, holder))")
            c.execute("CREATE TABLE IF NOT EXISTS flags (world_id INT, key TEXT, val TEXT, "
                      "PRIMARY KEY(world_id, key))")
            # контракты: делегированные вехи агенд NPC (want-предикат + реальная награда)
            c.execute("CREATE TABLE IF NOT EXISTS deeds (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                      "world_id INT, gt INT, actor TEXT, verb TEXT, obj TEXT, place TEXT, "
                      "witnesses TEXT, status TEXT, data TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS contracts (world_id INT, id TEXT, status TEXT, "
                      "data TEXT, PRIMARY KEY(world_id, id))")
            # живое состояние placed NPC (память/отношения/нужды) — переживает рестарт
            c.execute("CREATE TABLE IF NOT EXISTS building_pool (id TEXT PRIMARY KEY, kind TEXT, "
                      "btype TEXT, data TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS user_worlds (user_id TEXT PRIMARY KEY, "
                      "world_id INTEGER, seed INTEGER)")
            # пул предметов мира (весовой) + реестр выпавших уникальных (больше не спавнятся)
            c.execute("CREATE TABLE IF NOT EXISTS item_pool (world_id INT, key TEXT, data TEXT, "
                      "weight INT, PRIMARY KEY(world_id, key))")
            c.execute("CREATE TABLE IF NOT EXISTS unique_spawned (world_id INT, key TEXT, "
                      "PRIMARY KEY(world_id, key))")
            c.execute("CREATE TABLE IF NOT EXISTS npc_state (world_id INT, npc_id TEXT, data TEXT, "
                      "PRIMARY KEY(world_id, npc_id))")

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
    def flags_prefix(self, world_id: int, prefix: str) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT key, val FROM flags WHERE world_id=? AND key LIKE ?",
                             (world_id, prefix + "%")).fetchall()
        return {r[0]: r[1] for r in rows}

    def user_world(self, user_id: str) -> tuple | None:
        """(world_id, seed) пользователя или None."""
        with self._conn() as c:
            r = c.execute("SELECT world_id, seed FROM user_worlds WHERE user_id=?",
                          (str(user_id),)).fetchone()
        return (int(r[0]), int(r[1])) if r else None

    def user_world_create(self, user_id: str) -> tuple:
        """Выделить пользователю НОВЫЙ мир. id/seed берём из МОНОТОННОГО счётчика (flags[0]),
        а не MAX(world_id): после пермасмерти строка юзера удаляется, и MAX бы переиспользовал
        тот же id/seed → тот же город. Счётчик только растёт — новый мир всегда другой."""
        with self._conn() as c:
            r = c.execute("SELECT val FROM flags WHERE world_id=0 AND key='world_seq'").fetchone()
            cur = int(r[0]) if r else 0
            mx = c.execute("SELECT COALESCE(MAX(world_id), 0) FROM user_worlds").fetchone()[0]
            seq = max(cur, int(mx)) + 1                   # переживает миграцию со старой MAX-логики
            c.execute("INSERT OR REPLACE INTO flags (world_id, key, val) VALUES (0, 'world_seq', ?)",
                      (str(seq),))
            c.execute("INSERT OR REPLACE INTO user_worlds (user_id, world_id, seed) VALUES (?,?,?)",
                      (str(user_id), seq, seq))
        return seq, seq

    def destroy_world(self, world_id: int) -> None:
        """Пермасмерть: стереть ВЕСЬ рантайм мира и освободить юзера (при заходе получит новый).
        world_id=0 (глобальные флаги/счётчики) не трогаем — стираем только реальные миры (≥1)."""
        if int(world_id) < 1:
            return
        with self._conn() as c:
            for iid in [row[0] for row in
                        c.execute("SELECT item_id FROM inventory WHERE world_id=?", (world_id,))]:
                c.execute("DELETE FROM items WHERE id=?", (iid,))   # предмет живёт в одном мире
            for t in ("buildings", "placements", "inventory", "pc_state", "purse", "flags",
                      "contracts", "npc_state", "item_pool", "unique_spawned"):
                c.execute(f"DELETE FROM {t} WHERE world_id=?", (world_id,))
            c.execute("DELETE FROM user_worlds WHERE world_id=?", (world_id,))

    # ------------------------------------------------------ пул предметов мира --- #
    def pool_add_item(self, world_id: int, key: str, data: dict, weight: int) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO item_pool (world_id, key, data, weight) VALUES (?,?,?,?)",
                      (world_id, key, json.dumps(data, ensure_ascii=False), int(weight)))

    def pool_items(self, world_id: int) -> list:
        with self._conn() as c:
            rows = c.execute("SELECT key, data, weight FROM item_pool WHERE world_id=?",
                             (world_id,)).fetchall()
        return [{"key": r[0], "data": json.loads(r[1]), "weight": int(r[2])} for r in rows]

    def item_pool_count(self, world_id: int) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM item_pool WHERE world_id=?", (world_id,)).fetchone()[0]

    def unique_taken(self, world_id: int, key: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM unique_spawned WHERE world_id=? AND key=?",
                             (world_id, key)).fetchone() is not None

    def unique_mark(self, world_id: int, key: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO unique_spawned (world_id, key) VALUES (?,?)",
                      (world_id, key))

    def pool_save_building(self, bid: str, kind: str, btype: str, data: dict) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO building_pool (id, kind, btype, data) VALUES (?,?,?,?)",
                      (bid, kind, btype, json.dumps(data, ensure_ascii=False)))

    def pool_buildings(self, kind: str | None = None) -> list:
        with self._conn() as c:
            rows = c.execute("SELECT id, kind, btype, data FROM building_pool" +
                             (" WHERE kind=?" if kind else ""),
                             ((kind,) if kind else ())).fetchall()
        return [{"id": r[0], "kind": r[1], "btype": r[2], "data": json.loads(r[3])} for r in rows]

    def pool_count(self, kind: str | None = None) -> int:
        with self._conn() as c:
            q = "SELECT COUNT(*) FROM building_pool" + (" WHERE kind=?" if kind else "")
            return c.execute(q, ((kind,) if kind else ())).fetchone()[0]

    # ── ДЕЛА (deeds): append-only журнал мира — субстрат сплетен/стражи/хроники/обязательств ──
    def deed_add(self, world_id: int, gt: int, actor: str, verb: str, obj: str = "",
                 place: str = "", witnesses: list | None = None, status: str = "",
                 data: dict | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO deeds (world_id, gt, actor, verb, obj, place, witnesses, status, data) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (world_id, gt, actor, verb, obj, place,
                 json.dumps(witnesses or [], ensure_ascii=False), status,
                 json.dumps(data or {}, ensure_ascii=False)))
            return int(cur.lastrowid)

    def deeds(self, world_id: int, verb: str | None = None, actor: str | None = None,
              status: str | None = None, since_gt: int | None = None, limit: int = 20) -> list:
        q, args = "SELECT id, gt, actor, verb, obj, place, witnesses, status, data FROM deeds "                   "WHERE world_id=?", [world_id]
        if verb:
            q += " AND verb=?"; args.append(verb)
        if actor:
            q += " AND actor=?"; args.append(actor)
        if status:
            q += " AND status=?"; args.append(status)
        if since_gt is not None:
            q += " AND gt>=?"; args.append(since_gt)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [{"id": r[0], "gt": r[1], "actor": r[2], "verb": r[3], "obj": r[4],
                 "place": r[5], "witnesses": json.loads(r[6] or "[]"),
                 "status": r[7], "data": json.loads(r[8] or "{}")} for r in rows]

    def deed_status(self, world_id: int, deed_id: int, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE deeds SET status=? WHERE world_id=? AND id=?",
                      (status, world_id, deed_id))

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

    def clear_placements(self, world_id: int) -> None:
        """Сброс привязок мира (напр., граф города изменился и старые узлы протухли)."""
        with self._conn() as c:
            c.execute("DELETE FROM placements WHERE world_id=?", (world_id,))

    # ---------------------------------------------------- предметы -------- #
    def save_item(self, item: dict) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO items (id,data) VALUES (?,?)",
                      (item["id"], json.dumps(item, ensure_ascii=False)))

    def get_item(self, item_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT data FROM items WHERE id=?", (item_id,)).fetchone()
        return json.loads(r["data"]) if r else None

    def inv_add(self, world_id: int, item_id: str, holder: str = "pc", known=None) -> None:
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO inventory (world_id,item_id,holder,known) VALUES (?,?,?,?)",
                      (world_id, item_id, holder, json.dumps(list(known or []), ensure_ascii=False)))

    def inv_set_known(self, world_id: int, item_id: str, known) -> None:
        with self._conn() as c:
            c.execute("UPDATE inventory SET known=? WHERE world_id=? AND item_id=?",
                      (json.dumps(list(known or []), ensure_ascii=False), world_id, item_id))

    def inventory(self, world_id: int, holder: str = "pc") -> list:
        with self._conn() as c:
            rows = c.execute("SELECT item_id,known FROM inventory WHERE world_id=? AND holder=?",
                             (world_id, holder)).fetchall()
        return [{"item_id": r["item_id"], "known": json.loads(r["known"])} for r in rows]

    def inv_move(self, world_id: int, item_id: str, holder: str) -> None:
        """Перенос предмета к другому держателю (лут/кража/покупка/дар — один механизм)."""
        with self._conn() as c:
            c.execute("UPDATE inventory SET holder=? WHERE world_id=? AND item_id=?",
                      (holder, world_id, item_id))

    def inv_drop(self, world_id: int, item_id: str) -> None:
        """Изъять предмет из мира совсем (конфискация/расход/уничтожение)."""
        with self._conn() as c:
            c.execute("DELETE FROM inventory WHERE world_id=? AND item_id=?", (world_id, item_id))
            c.execute("DELETE FROM items WHERE id=?", (item_id,))

    def purse_get(self, world_id: int, holder: str) -> int:
        with self._conn() as c:
            r = c.execute("SELECT coins FROM purse WHERE world_id=? AND holder=?",
                          (world_id, holder)).fetchone()
        return int(r["coins"]) if r else 0

    def purse_add(self, world_id: int, holder: str, delta: int) -> int:
        v = max(0, self.purse_get(world_id, holder) + int(delta))
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO purse (world_id,holder,coins) VALUES (?,?,?)",
                      (world_id, holder, v))
        return v

    def flag_get(self, world_id: int, key: str) -> str | None:
        with self._conn() as c:
            r = c.execute("SELECT val FROM flags WHERE world_id=? AND key=?", (world_id, key)).fetchone()
        return r["val"] if r else None

    def flag_set(self, world_id: int, key: str, val: str = "1") -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO flags (world_id,key,val) VALUES (?,?,?)", (world_id, key, val))

    # ---------------------------------------------------- контракты ------- #
    def save_contract(self, world_id: int, cid: str, status: str, data: dict) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO contracts (world_id,id,status,data) VALUES (?,?,?,?)",
                      (world_id, cid, status, json.dumps(data, ensure_ascii=False)))

    def contracts(self, world_id: int, status: str | None = None) -> list:
        q = "SELECT id,status,data FROM contracts WHERE world_id=?" + (" AND status=?" if status else "")
        with self._conn() as c:
            rows = c.execute(q, (world_id, status) if status else (world_id,)).fetchall()
        return [{"id": r["id"], "status": r["status"], **json.loads(r["data"])} for r in rows]

    def save_npc_state(self, world_id: int, npc_id: str, data: dict) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO npc_state (world_id,npc_id,data) VALUES (?,?,?)",
                      (world_id, npc_id, json.dumps(data, ensure_ascii=False)))

    def get_npc_state(self, world_id: int, npc_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT data FROM npc_state WHERE world_id=? AND npc_id=?",
                          (world_id, npc_id)).fetchone()
        return json.loads(r["data"]) if r else None

    # ---------------------------------------------------- игрок-агент ----- #
    def save_pc(self, world_id: int, data: dict) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO pc_state (world_id,data) VALUES (?,?)",
                      (world_id, json.dumps(data, ensure_ascii=False)))

    def get_pc(self, world_id: int) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT data FROM pc_state WHERE world_id=?", (world_id,)).fetchone()
        return json.loads(r["data"]) if r else None


def _person(r) -> dict:
    return {"id": r["id"], "role": r["role"], "name": r["name"], "charisma": r["charisma"],
            "appearance": r["appearance"], "mech": json.loads(r["mech"]),
            "persona": json.loads(r["persona"]), "portraits": json.loads(r["portraits"]), "seed": r["seed"]}


def _row(r) -> dict:
    return {"building_id": r["building_id"], "is_key": bool(r["is_key"]), "node": r["node"],
            "sign": r["sign"], "data": json.loads(r["data"])}
