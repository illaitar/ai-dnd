"""Inference — клиент модели, роутинг по ролям, structured output.

Правило проекта: офлайн-фоллбэков НЕТ. Нет модели → LLMUnavailable; не разобрали
ответ → LLMBadOutput. Обе ошибки честно доходят до игрока (503 на границе сервера).
"""

from .client import LLMBadOutput, LLMUnavailable, ModelManager, OllamaClient, OllamaError
from .structured import coerce, extract

__all__ = ["OllamaClient", "OllamaError", "ModelManager",
           "LLMUnavailable", "LLMBadOutput", "extract", "coerce"]
