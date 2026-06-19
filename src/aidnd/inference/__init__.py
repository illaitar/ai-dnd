"""L4 Inference — клиент модели, реестр агентов, structured output (main §6, §12).

Клиент модели (client.py) — единственный компонент, переиспользованный из ai-dnd.
Всё остальное (агенты, схемы, фоллбэки) реализовано по диздоку.
"""

from . import agents
from .client import ModelManager, OllamaClient, OllamaError
from .structured import coerce, extract

__all__ = ["OllamaClient", "OllamaError", "ModelManager", "agents", "extract", "coerce"]
