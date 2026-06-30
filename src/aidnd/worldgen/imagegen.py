"""Хук генерации изображений — ОТДЕЛЬНЫЙ модуль, на будущее. Интерфейс ImageGen.generate(prompt)->ref|None.

Пока заглушка (не настроено). Дешёвый провайдер (напр. FLUX.1 schnell на fal.ai, ~$0.003/картинка)
подключается позже через env (FAL_KEY). Промпт под здание собирается из фактшита (build_prompt).
"""

from __future__ import annotations

import os


class ImageGen:
    """База: ничего не генерит (хук выключен)."""

    def available(self) -> bool:
        return False

    def generate(self, prompt: str, *, kind: str = "building", ref: str | None = None) -> str | None:
        return None


class FluxImageGen(ImageGen):
    """Заготовка под FLUX.1 schnell (fal.ai). Реализация вызова — позже."""

    def __init__(self, api_key: str | None = None, model: str = "fal-ai/flux/schnell"):
        self.api_key = api_key or os.environ.get("FAL_KEY")
        self.model = model

    def available(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str, *, kind: str = "building", ref: str | None = None) -> str | None:
        if not self.available():
            return None
        # TODO: HTTP-вызов fal.ai FLUX schnell → URL картинки. Пока хук не реализован.
        return None


def get_imagegen() -> ImageGen:
    g = FluxImageGen()
    return g if g.available() else ImageGen()


def build_prompt(data: dict, *, sign: str | None = None) -> str:
    """Промпт под здание из фактшита характеристик (для будущей генерации)."""
    parts = [sign or data.get("type", "здание"), data.get("type", ""),
             data.get("tier", ""), data.get("condition", "")]
    mat = data.get("materials") or {}
    if mat.get("walls"):
        parts.append(mat["walls"])
    parts += (data.get("features") or [])[:3]
    body = ", ".join(p for p in parts if p)
    return f"fantasy frontier town building, {body}, dark grim D&D, isometric, detailed, no text"
