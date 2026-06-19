"""Единый авторитетный актор состояния (док 08 §1-2).

Все мутации проходят через одну сериализованную очередь команд — гонок нет.
Медленная сайд-эффектная работа (LLM, генерация) идёт вне критического пути и
возвращается командами. RollRequest — эффект, RollResult игрока — команда; ход
возобновляется при её приходе, ничего не блокируется.

В прототипе очередь обрабатывается синхронно (драйвится CLI/WebSocket-циклом).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Command:
    kind: str                       # player_action | roll_result | tick | worker_result
    payload: dict = field(default_factory=dict)
    request_id: str | None = None


class StateActor:
    def __init__(self, world) -> None:
        self.world = world
        self.queue: deque[Command] = deque()
        self.handlers: dict[str, Callable] = {}
        self.suspended: dict[str, dict] = {}   # request_id -> контекст приостановленного хода

    def register(self, kind: str, handler: Callable) -> None:
        self.handlers[kind] = handler

    def submit(self, cmd: Command) -> None:
        self.queue.append(cmd)

    def suspend(self, request_id: str, context: dict) -> None:
        """Приостановить ход на бросок игрока (док 07 §4)."""
        self.suspended[request_id] = context

    def resume(self, request_id: str) -> dict | None:
        return self.suspended.pop(request_id, None)

    def drain(self) -> list:
        """Обработать все команды последовательно (единственный писатель)."""
        results = []
        while self.queue:
            cmd = self.queue.popleft()
            handler = self.handlers.get(cmd.kind)
            if handler:
                out = handler(cmd, self.world)
                if out is not None:
                    results.append(out)
        return results
