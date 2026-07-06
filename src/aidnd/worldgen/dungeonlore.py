"""LLM-вкус подземелий — этап B (docs/dungeons.md): бриф + виньетки комнат, ОФЛАЙН в пул.

Архитектор пишет БРИФ: история места в 3 слоях (кто построил → что случилось → кто живёт
теперь), нарративные биты, палитра, именования — НИ ОДНОЙ координаты (наука: LLM не
контролирует геометрию). Декоратор по брифу пишет виньетки на АРХЕТИПЫ комнат (вход, зал,
логово вождя, склад…) с уликой-ссылкой на бит истории — валидатор бьёт висячие ссылки
(Qud-метод: история рационализируется задним числом и оставляет СЛЕДЫ по комнатам).
Рантайм детерминирован: generate() раздаёт виньетки комнатам по архетипу и сиду.
"""

from __future__ import annotations

import json
import re

from ..inference import LLMBadOutput

ARCHES = ("entrance", "hall", "cave", "chief", "store", "post",
          "danger", "treasure", "secret")

_ARCH_SYS = (
    "Ты — архитектор подземелий тёмно-фэнтезийного фронтира (D&D). Дана СРЕДА и возможные "
    "обитатели. Придумай ОДНО место с историей. Верни ТОЛЬКО JSON:\n"
    '{"name": "<имя места, 2-4 слова, по-русски>", "folk": "<вид нынешних хозяев из списка>", '
    '"history": {"built": "<кто и зачем построил/обжил, 1 предложение>", '
    '"happened": "<что случилось, 1 предложение>", "now": "<кто и как живёт теперь>"}, '
    '"bits": [{"id": "b1", "text": "<нарративный факт-след истории>"}, … 5-7 битов], '
    '"palette": {"materials": "<камень/дерево/кость…>", "light": "<чем освещено/тьма>", '
    '"sound": "<что слышно>"}, "chief": "<имя-кличка вождя>", '
    '"lock_flavor": "<чем заперты запертые двери — по теме места>"}\n'
    "История ЧЕСТНАЯ и локальная (не эпос): развалины конкретной судьбы. Биты — конкретные "
    "СЛЕДЫ, которые можно увидеть в комнатах (обгоревшая балка, детская обувь, счётные "
    "зарубки). Никаких координат и планировки — только смысл и вкус."
)

_DEC_SYS = (
    "Ты — декоратор подземелья. Дан БРИФ места (история, биты, палитра). Напиши виньетки "
    "для архетипов комнат. Верни ТОЛЬКО JSON:\n"
    '{"rooms": [{"arch": "entrance|hall|cave|chief|store|post|danger|treasure|secret", '
    '"name": "<имя комнаты, 1-3 слова>", "desc": "<1-2 предложения: что видно, чем пахнет; '
    'вплети след истории>", "clue": "<id бита из брифа, след которого здесь виден>"}, …]}\n'
    "10-14 виньеток, КАЖДЫЙ архетип хотя бы раз (entrance, hall, cave, chief, store, post, "
    "danger, treasure, secret). desc — environmental storytelling: не «страшная комната», "
    "а ЧТО именно осталось и о чём это говорит. clue строго из id битов брифа."
)


def _parse(text: str | None) -> dict | None:
    if not text:
        return None
    t = re.sub(r"```$", "", re.sub(r"^```(?:json)?", "", text.strip()).strip()).strip()
    try:
        return json.loads(t[t.find("{"): t.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def forge_dungeon_brief(env: str, folk_hint: list, mgr) -> dict:
    """Архитектор + декоратор → валидный бриф с виньетками (для пула; LLM только офлайн)."""
    user = f"СРЕДА: {env}. ВОЗМОЖНЫЕ ХОЗЯЕВА: {', '.join(folk_hint) or 'дикие твари'}."
    b = _parse(mgr.call("dungeon_architect",
                        [{"role": "system", "content": _ARCH_SYS},
                         {"role": "user", "content": user}],
                        options={"temperature": 0.9}).get("content"))
    if not b or not b.get("bits") or not (b.get("history") or {}).get("now"):
        raise LLMBadOutput("architect: нет брифа/битов")
    bit_ids = {str(x.get("id")) for x in b["bits"] if isinstance(x, dict)}
    d = _parse(mgr.call("dungeon_decorator",
                        [{"role": "system", "content": _DEC_SYS},
                         {"role": "user", "content": "БРИФ:\n" + json.dumps(
                             b, ensure_ascii=False)}],
                        options={"temperature": 0.8}).get("content"))
    rooms = [v for v in (d or {}).get("rooms") or []
             if isinstance(v, dict) and v.get("arch") in ARCHES and v.get("name")
             and str(v.get("clue")) in bit_ids]        # висячие ссылки — вон (урок Story2Game)
    if len(rooms) < 8:
        raise LLMBadOutput(f"decorator: виньеток {len(rooms)} < 8 (или битые ссылки)")
    b["rooms"] = rooms
    b["env"] = env
    return b


def room_arch(r: dict) -> str:
    """Архетип комнаты скелета — по фактам структуры, не по прихоти."""
    if r["kind"] == "entrance":
        return "entrance"
    if r["kind"] == "goal":
        return "chief"
    if r.get("frole") == "склад":
        return "store"
    if r.get("frole") == "пост":
        return "post"
    if "treasure" in r["tags"]:
        return "treasure"
    if "danger" in r["tags"]:
        return "danger"
    xs = [t[0] for t in r["tiles"]]
    ys = [t[1] for t in r["tiles"]]
    ragged = len(r["tiles"]) < (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)
    return "cave" if ragged else "hall"


def apply_brief(d: dict, brief: dict, rng) -> None:
    """Виньетки брифа → комнаты по архетипу, детерминированно; secret-комнаты — у секреток."""
    by_arch: dict = {}
    for v in brief.get("rooms") or []:
        by_arch.setdefault(v["arch"], []).append(v)
    secret_rooms = {e["b"] for e in d["edges"] if e["kind"] == "secret"} | \
                   {e["a"] for e in d["edges"] if e["kind"] == "secret"}
    d["name"] = brief.get("name") or "Безымянные развалины"
    d["palette"] = brief.get("palette") or {}
    d["history"] = brief.get("history") or {}
    d["chief"] = brief.get("chief")
    d["lock_flavor"] = brief.get("lock_flavor")
    bags: dict = {}                                   # раздача БЕЗ повторов, пока есть чем
    for r in d["rooms"]:
        arch = "secret" if r["id"] in secret_rooms and r["kind"] == "room" else room_arch(r)
        pool = by_arch.get(arch) or by_arch.get("hall") or []
        if not pool:
            continue
        bag = bags.setdefault(arch, [])
        if not bag:
            bag[:] = sorted(range(len(pool)), key=lambda _i: rng.random())
        v = pool[bag.pop()]
        r["name"], r["desc"], r["clue"] = v["name"], v.get("desc", ""), v.get("clue")
