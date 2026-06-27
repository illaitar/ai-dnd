"""DM Director / оркестратор темпа (main §8, §12.8, док 05 §3).

Управляет темпом и кадрированием: когда подсветить квестовый крючок, когда
выкинуть энкаунтер, когда держать паузу. На старте — эвристики, опционально
тонкая LLM-логика. Гейтит спавн побочек (док 05 §9).
"""

from __future__ import annotations

import random

from ..gen.seeds import subseed
from ..world.components import Persona

MAX_ACTIVE_SIDE = 3

# темп: базовая P(случайное событие за «пустой» бит) по типу локации. Опасная глушь
# живее людных безопасных мест; святилище/поместье — тихие. Вероятность РАСТЁТ с
# длиной затишья (ramp) и режется контекстом — событие лишь там, где обстановка
# позволяет (вне боя/диалога; гейт quiet<2 = «ещё не застой»).
AMBIENT_BASE = {
    "dungeon": 0.11, "site": 0.11, "wilderness": 0.11, "wilds": 0.11,
    "manor": 0.05, "market": 0.045, "frontier_town": 0.045, "shrine": 0.03,
}
DANGEROUS = {"dungeon", "site", "wilderness", "wilds"}
SOCIAL = {"market", "frontier_town"}
QUIET_GATE = 3          # сколько «пустых» битов нужно, прежде чем темп оживает (выше = реже дёргает)
PACING_CAP = 0.32       # потолок вероятности за один бит

_THREAT = ["Где-то во тьме скрежетнул потревоженный камень — ты здесь не один.",
           "Сквозняк доносит чужой запах: зверь, а может, и кое-что похуже.",
           "Вдалеке коротко рокочет гортанный голос — и обрывается тишиной."]
_FIND = ["Под ногой тускло блеснул металл — стоит здесь обыскаться.",
         "В трещине стены угадывается рукотворная пустота — тайник?",
         "Носок сапога цепляет припорошенный край чего-то сделанного руками."]
_COMPANY = ["Кто-то из местных неспешно направляется в твою сторону.",
            "Рядом задерживается прохожий, явно не прочь заговорить."]


class Director:
    def __init__(self, world, quest_system, model=None) -> None:
        self.world = world
        self.quests = quest_system
        self.model = model

    def has_room_for_quest(self) -> bool:
        active = sum(1 for q in self.world.quests.values()
                     if q.kind == "side" and q.state == "active")
        return active < MAX_ACTIVE_SIDE

    def surface_hooks_near(self, npc_id: str) -> list[str]:
        """Крючки квестов, которые этот NPC может раскрыть (док 05 §3)."""
        out = []
        p = self.world.ecs.get(npc_id, Persona)
        if not p:
            return out
        for k in p.knowledge:
            qid = k.get("unlocks_quest")
            if qid and qid in self.world.quests and self.world.quests[qid].state == "not_offered":
                self.quests.offer(qid)
                out.append(qid)
        return out

    def generate_side_quest(self, giver: str, location: str, title: str,
                            objective: str, template_id: str = "bounty"):
        """Собирает побочный квест: слоты + текст от модели (роль quest_writer),
        фоллбэк — шаблонное обрамление. Регистрирует и предлагает квест. None — нет
        места под ещё одну побочку (док 05 §9)."""
        if not self.has_room_for_quest():
            return None
        from ..gen.quest_gen import generate_side_quest as _assemble
        writer = None
        if self.model is not None:
            from ..inference.agents import write_quest
            writer = lambda t, g, l, ti, ob: write_quest(self.model, t, g, l, ti, ob)  # noqa: E731
        q = _assemble(self.world, template_id, giver, location, title, objective,
                      self.world.seed, quest_writer=writer)
        self.world.quests[q.quest_id] = q
        return q

    def pacing_check(self) -> dict:
        """Возвращает директиву темпа (эвристики + опц. LLM)."""
        if self.model is not None:
            from ..inference.agents import emit_directive
            digest = self._digest()
            out = emit_directive(self.model, digest)
            if out:
                return out
        # эвристика: после зачистки логова — подсветить следующий крючок
        if "cragmaw_cleared" in self.world.flags and "hook:redbrands" not in self.world.flags:
            self.world.flags.add("hook:redbrands")
            return {"directive": "surface_hook", "ref": "redbrands",
                    "reason": "логово зачищено, путь ведёт к Красным плащам"}
        return {"directive": "hold", "ref": None, "reason": "темп ровный"}

    def _digest(self) -> str:
        active = [q.title for q in self.world.quests.values() if q.state == "active"]
        return (f"tick={self.world.clock.tick}; flags={sorted(self.world.flags)[:6]}; "
                f"active_quests={active}")

    # --- темп: случайное событие во время затишья (main §8 pacing) -------- #
    def pacing_probability(self, location_type: str, quiet: int) -> float:
        """P(событие) за бит: 0 до порога затишья, дальше растёт линейно до потолка.
        «Долго ничего не происходит И обстановка позволяет» = высокий quiet × живая
        локация. Безопасные людные места дают мягкие события, опасная глушь — острые."""
        if quiet < QUIET_GATE:
            return 0.0
        base = AMBIENT_BASE.get(location_type, 0.03)
        ramp = min(2.0, 1.0 + 0.3 * (quiet - 1))           # медленнее нарастает → реже спам
        return min(PACING_CAP, base * ramp)

    def ambient_beat(self, seed: int, tick: int, place_id: str, location_type: str,
                     scene, quiet: int, has_company: bool = False) -> dict | None:
        """Детерминированный (seed+tick+место) случайный бит при затишье — или None.
        Вид события подбирается под обстановку: глушь → угроза/находка, людное →
        встреча/фон, тихое → фон. Бит НАРРАТИВНЫЙ: даёт зацепку, но не навязывает
        механику (бой/урон) — игрок реагирует обычными действиями (бой/обыск/разговор),
        поэтому реплей остаётся воспроизводимым."""
        p = self.pacing_probability(location_type, quiet)
        if p <= 0.0:
            return None
        rng = random.Random(subseed(seed, "pacing", tick, place_id))
        if rng.random() > p:
            return None
        event = self._pick_event(location_type, has_company, rng)
        pool = getattr(self.world, "event_pool", None)         # пред-генерированный LLM-пул → РАЗНЫЕ строки
        pooled = pool.draw(event, location_type) if pool else None
        return {"kind": "ambient_event", "event": event, "p": round(p, 3),
                "location_type": location_type,
                "title": (pooled.get("title") if pooled else ""),
                "text": pooled["line"] if pooled else self._beat_text(event, scene, rng)}

    def _pick_event(self, loc: str, has_company: bool, rng: random.Random) -> str:
        if loc in DANGEROUS:
            return rng.choices(["threat", "find", "ambient"], [0.55, 0.25, 0.20])[0]
        if loc in SOCIAL:
            return rng.choices(["company", "ambient"], [0.5, 0.5])[0]
        return "ambient"

    def _beat_text(self, event: str, scene, rng: random.Random) -> str:
        if event == "threat":
            return rng.choice(_THREAT)
        if event == "find":
            return rng.choice(_FIND)
        if event == "company":
            return rng.choice(_COMPANY)
        # ambient — фон от погоды/времени/атмосферы места
        amb = []
        w = getattr(scene, "weather", "")
        if w == "rain":
            amb.append("Дождь ровно барабанит — время будто загустело.")
        elif w == "storm":
            amb.append("Где-то ворчит гроза, отзываясь дрожью в стенах.")
        elif w == "snow":
            amb.append("Снег ложится беззвучно, скрадывая все звуки.")
        elif w == "fog":
            amb.append("Туман сужает мир до нескольких шагов вокруг.")
        elif w == "windy":
            amb.append("Порыв ветра несёт пыль и далёкие, неразборчивые звуки.")
        if getattr(scene, "time_of_day", "") == "night":
            amb.append("Глубокая ночь; редкие звуки кажутся громче, чем днём.")
        if getattr(scene, "ambiance", ""):
            amb.append(scene.ambiance)
        amb.append("Проходит ещё немного времени — пока спокойно.")
        return rng.choice(amb)
