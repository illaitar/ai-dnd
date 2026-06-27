"""Пул случайных событий, пред-генерируемый LLM пачками для РАЗНЫХ кондиций города.

Зачем: события в пути/в затишье должны быть РАЗНЫМИ (не шаблон), но дёргать LLM на каждое — дорого и
тормозит ход. Поэтому заранее генерим пачки (≈200 строк суммарно) по видам×обстановкам, держим в пуле и
на событие просто берём готовую строку. Когда строк по кондиции мало — асинхронно догружаем в фоне
(daemon-поток), не блокируя игру. Нет модели/пусто — вызывающий откатывается на свой шаблон.

События чисто нарративные (мир не мутируют), поэтому неважно, что текст не реплеится — как и было.
"""

from __future__ import annotations

import threading

# кондиции: (вид, обстановка-метка для промпта). ~14 строк на кондицию ≈ 200 суммарно.
KEYS = [
    ("threat", "логово/подземелье"), ("threat", "дикая глушь"),
    ("find", "логово/подземелье"), ("find", "дикая глушь"),
    ("company", "людный городок"), ("ambient", "городок"),
    ("ambient", "логово/подземелье"), ("ambient", "дикая глушь"),
    ("street", "улицы городка"),
]
LOW_WATER = 4          # меньше стольких строк по кондиции → догрузить
BATCH = 14             # строк за один LLM-вызов


def _label(kind: str, loc: str) -> str:
    """Нормализовать тип локации в метку-обстановку пула (совпадает с KEYS)."""
    if kind == "street":
        return "улицы городка"
    if loc in ("dungeon", "site"):
        return "логово/подземелье"
    if loc in ("wilderness", "wilds"):
        return "дикая глушь"
    return "людный городок" if kind == "company" else "городок"


class EventPool:
    def __init__(self, model):
        self.model = model
        self.pool: dict[tuple, list] = {}
        self._lock = threading.Lock()
        self._busy: set = set()

    def available(self) -> bool:
        return self.model is not None and getattr(self.model, "available", lambda: False)()

    # на старте греем ГОРОДСКИЕ кондиции (игрок начинает в городе); глушь/логова — лениво по приходу,
    # чтобы не дёргать кучу LLM-вызовов на каждый старт сессии (важно для мультиюзера).
    PRIME = [("street", "улицы городка"), ("ambient", "городок"), ("company", "людный городок")]

    def prime(self) -> None:
        """Пред-генерация городских кондиций в фоне (не блокирует старт; остальное — лениво при draw)."""
        for key in self.PRIME:
            self._refill_async(key)

    def draw(self, kind: str, loc_type: str) -> dict | None:
        """Готовое событие {title,line,involves,hostile} для (вид, обстановка) или None (откат на шаблон)."""
        key = (kind, _label(kind, loc_type))
        with self._lock:
            lst = self.pool.get(key)
            item = lst.pop() if lst else None
            low = (not lst) or len(lst) < LOW_WATER
        if low:
            self._refill_async(key)
        return item

    # --- фоновая догрузка --------------------------------------------------- #
    def _refill_async(self, key: tuple) -> None:
        if not self.available():
            return
        with self._lock:
            if key in self._busy:
                return
            self._busy.add(key)
        threading.Thread(target=self._refill, args=(key,), daemon=True).start()

    def _refill(self, key: tuple) -> None:
        try:
            from ..inference.agents import generate_event_batch
            items = generate_event_batch(self.model, key[0], key[1], BATCH)
            if items:
                with self._lock:
                    self.pool.setdefault(key, []).extend(items)
        except Exception:
            pass
        finally:
            with self._lock:
                self._busy.discard(key)

    def stats(self) -> dict:
        with self._lock:
            return {f"{k[0]}/{k[1]}": len(v) for k, v in self.pool.items()}
