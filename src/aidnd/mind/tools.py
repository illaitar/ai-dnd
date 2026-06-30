"""Инструменты NPC. Два класса:
  READ (query) — читают состояние, без эффекта, «бесплатны»: perceive, recall, assess, locate.
  WRITE (act)  — меняют мир, тратят ход: move (далее say/give/take/use/attack/emote/wait).
Каждый инструмент работает над (state: NpcState, scene: Scene, **params). Реестр TOOLS + run_tool.
"""

from __future__ import annotations

from .model import NpcState, Scene


def _resolve(city, target):
    """target → узел графа / id здания (для route). int|'key:N'|имя здания|None."""
    if target is None or target == "":
        return None
    if isinstance(target, int):
        return target
    s = str(target).strip()
    if s.lstrip("-").isdigit():
        return int(s)
    if s in city.key_buildings:
        return s
    low = s.lower()
    for bid, kb in city.key_buildings.items():       # матч по имени здания
        if kb.name and kb.name.lower() in low or low in kb.name.lower():
            return bid
    return None


# ── READ ──────────────────────────────────────────────────────────────────
def perceive(state: NpcState, scene: Scene, **_) -> dict:
    """Что вокруг СЕЙЧАС: место, кто present, легальные выходы, предметы."""
    city, node = scene.city, state.node
    here = [n.config.id for n in scene.npcs.values() if n is not state and n.node == node]
    moves = []
    if node is not None:
        for m in city.exits(node):
            moves.append({"to": m.to, "kind": m.kind, "heading": m.heading, "name": m.name})
    return {"node": node, "kind": str(city.node_kind(node) or "") if node is not None else "",
            "present": here, "exits": moves, "items": scene.items.get(node, [])}


def recall(state: NpcState, scene: Scene, query: str = "", k: int = 10, reranker=None, **_) -> dict:
    """Ретрива top-k воспоминаний по вопросу (SOTA: скор → rerank)."""
    mems = state.memory.recall(query, scene.clock, k=int(k), reranker=reranker)
    return {"query": query, "memories": [
        {"text": m.text, "importance": round(m.importance, 2), "t": m.t, "kind": m.kind,
         "about": m.about} for m in mems]}


def assess(state: NpcState, scene: Scene, entity: str = "", **_) -> dict:
    """Что знаю о КОНКРЕТНОМ X: отношение + факты о нём."""
    rel = state.relationships.get(entity, {"trust": 0.0, "affinity": 0.0, "fear": 0.0})
    facts = [m.text for m in state.memory.items if entity in m.about or entity.lower() in m.text.lower()]
    return {"entity": entity, "relationship": rel, "facts": facts[:10],
            "emotion_toward": {e: tgt for e, tgt in state.emotion_target.items() if tgt == entity}}


def locate(state: NpcState, scene: Scene, target: str = "", **_) -> dict:
    """Пространственное знание: путь/румб/ориентиры до цели (гейт перемещения)."""
    dst = _resolve(scene.city, target)
    if dst is None or state.node is None:
        return {"target": target, "known": False}
    r = scene.city.route(state.node, dst)
    near = ({"id": r.near_target.id, "name": r.near_target.name, "dist": r.near_target.dist}
            if r.near_target else None)
    return {"target": target, "known": True, "found": r.found, "length": round(r.length, 1),
            "crossroads": len(r.crossroads), "bearing": r.bearing,
            "near_target": near, "landmarks": r.landmarks,
            "steps": [{"kind": s.kind, "heading": s.heading, "name": s.name} for s in r.steps]}


# ── WRITE ─────────────────────────────────────────────────────────────────
def move(state: NpcState, scene: Scene, target: str = "", **_) -> dict:
    """Шаг по графу к цели (один узел за вызов; остаток пути возвращаем)."""
    dst = _resolve(scene.city, target)
    if dst is None or state.node is None:
        return {"moved": False, "reason": "цель неизвестна"}
    r = scene.city.route(state.node, dst)
    if not r.found or len(r.nodes) < 2:
        return {"moved": False, "reason": "нет пути" if not r.found else "уже на месте"}
    step = r.steps[0]
    state.node = r.nodes[1]
    return {"moved": True, "to": state.node, "step": step.kind, "heading": step.heading,
            "remaining": len(r.nodes) - 2, "arrived": len(r.nodes) == 2}


TOOLS = {
    "perceive": {"cls": "query", "fn": perceive, "params": []},
    "recall":   {"cls": "query", "fn": recall,   "params": ["query"]},
    "assess":   {"cls": "query", "fn": assess,   "params": ["entity"]},
    "locate":   {"cls": "query", "fn": locate,   "params": ["target"]},
    "move":     {"cls": "act",   "fn": move,     "params": ["target"]},
}


def run_tool(name: str, state: NpcState, scene: Scene, params: dict | None = None, reranker=None) -> dict:
    spec = TOOLS.get(name)
    if not spec:
        return {"error": f"нет инструмента {name}"}
    kw = dict(params or {})
    if name == "recall":
        kw["reranker"] = reranker
    return {"tool": name, "cls": spec["cls"], "result": spec["fn"](state, scene, **kw)}
