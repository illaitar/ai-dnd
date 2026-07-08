"""Inference — model client, routing by role, structured output.

Project rule: no offline fallbacks. No model → LLMUnavailable; could not parse
response → LLMBadOutput. Both errors honestly reach the player (503 at server boundary).

Key functions
-------------
ModelManager: Central inference router, routes requests by role/model.
OllamaClient: Direct Ollama client with Anthropic API compatibility.
extract(response, tool_name) -> dict | None: Parse structured output.
coerce(obj, required) -> dict | None: Validate required schema fields.
LLMUnavailable: Raised when model unavailable (no offline fallback).
LLMBadOutput: Raised when model output cannot be parsed/validated.
"""

from .client import LLMBadOutput, LLMUnavailable, ModelManager, OllamaClient, OllamaError
from .structured import coerce, extract

__all__ = ["OllamaClient", "OllamaError", "ModelManager",
           "LLMUnavailable", "LLMBadOutput", "extract", "coerce"]
