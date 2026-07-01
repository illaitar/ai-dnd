"""Генерация изображений (fal.ai Flux). Портрет NPC = НАБОР ЭМОЦИЙ одного лица (подход B из
прототипа: отдельные генерации flux/schnell с ОБЩИМ seed + детальным описанием → лицо держится,
эмоции выразительны, единый «домашний» стиль общим style-хвостом). Слайсинг не нужен.

Ключ: env FAL_KEY или .secrets/fal.key. Картинки тяжёлые — падают файлами в data/portraits/<id>/,
в гит НЕ идут (rsync на прод). Промпт зданий (build_prompt) оставлен как был.
"""

from __future__ import annotations

import os

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FAL = "https://fal.run/"

# единый стиль всего пула — главный рычаг когерентности (тот же, что в прототипе)
STYLE = ("dark grim low-fantasy D&D character portrait, painterly semi-realistic, muted earthy "
         "palette, dramatic chiaroscuro lighting, plain dark background, head and shoulders bust, "
         "centered, no text, no watermark, no frame")

# 4 эмоции: ключ ложится на mind._emo / play (спокойное/тёплое/раздражённое/настороженное)
EMOTIONS = (("спокойное", "calm neutral expression"),
            ("тёплое", "warm friendly smile"),
            ("раздражённое", "angry scowling expression"),
            ("настороженное", "wary alert expression, narrowed eyes"))


def _fal_key() -> str | None:
    v = os.environ.get("FAL_KEY")
    if v:
        return v.strip()
    p = os.path.join(_ROOT, ".secrets", "fal.key")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    return None


def portrait_prompt(persona: dict, expr: str) -> str:
    """Промпт лица: ВЕДЁМ явной фразой пол+возраст (сильный якорь для Flux — голый тег 'f' слаб),
    затем визуальные теги персоны, эмоция, единый стиль."""
    sexw = {"m": "man", "f": "woman"}.get(persona.get("sex"), "person")
    agew = {"young": "young ", "middle": "middle-aged ", "old": "old ", "elder": "elderly "}.get(
        persona.get("age"), "")
    lead = f"a {agew}{sexw}"
    drop = {"m", "f", "male", "female", "man", "woman"}     # выкидываем слабые/дублирующие пол-теги
    tags = [str(t) for t in (persona.get("portrait") or []) if str(t).strip().lower() not in drop]
    if not tags:                                            # фоллбэк, если LLM не заполнил
        tags = [persona.get("build", "average"), (persona.get("look") or {}).get("hair", "")]
    body = ", ".join(t for t in tags if t)
    return f"{lead}, {body}, {expr}, {STYLE}" if body else f"{lead}, {expr}, {STYLE}"


class ImageGen:
    """База: ничего не генерит (хук выключен)."""

    def available(self) -> bool:
        return False

    def generate(self, prompt: str, *, seed: int | None = None, kind: str = "portrait") -> str | None:
        return None

    def portraits(self, npc_id: str, persona: dict, seed: int, out_dir: str) -> dict:
        return {}


class FluxImageGen(ImageGen):
    """fal.ai Flux schnell. Один вызов = одна эмоция; общий seed на NPC держит лицо."""

    def __init__(self, api_key: str | None = None, model: str = "fal-ai/flux/schnell"):
        self.api_key = api_key or _fal_key()
        self.model = model

    def available(self) -> bool:
        return bool(self.api_key) and _HAS_HTTPX

    def generate(self, prompt: str, *, seed: int | None = None, kind: str = "portrait") -> str | None:
        """Один вызов fal.run → URL картинки (или None + причина в исключении не глушим наружу выше)."""
        if not self.available():
            return None
        payload = {"prompt": prompt, "image_size": "square_hd", "num_inference_steps": 4,
                   "num_images": 1, "enable_safety_checker": False}
        if seed is not None:
            payload["seed"] = int(seed)
        r = httpx.post(FAL + self.model, json=payload, timeout=180,
                       headers={"Authorization": f"Key {self.api_key}", "Content-Type": "application/json"})
        if r.status_code != 200:
            raise RuntimeError(f"fal {r.status_code}: {r.text[:160]}")
        imgs = (r.json() or {}).get("images") or []
        return imgs[0]["url"] if imgs else None

    def portraits(self, npc_id: str, persona: dict, seed: int, out_dir: str) -> dict:
        """4 эмоции одного лица → файлы out_dir/<npc_id>/<emo>.png. Возвращает {emo: '<id>/<emo>.png'}."""
        if not self.available():
            return {}
        d = os.path.join(out_dir, npc_id)
        os.makedirs(d, exist_ok=True)
        out = {}
        for emo, expr in EMOTIONS:
            url = self.generate(portrait_prompt(persona, expr), seed=seed)
            if not url:
                continue
            img = httpx.get(url, timeout=120).content
            with open(os.path.join(d, f"{emo}.png"), "wb") as f:
                f.write(img)
            out[emo] = f"{npc_id}/{emo}.png"
        return out


def get_imagegen() -> ImageGen:
    g = FluxImageGen()
    return g if g.available() else ImageGen()


def build_prompt(data: dict, *, sign: str | None = None) -> str:
    """Промпт под ЗДАНИЕ из фактшита характеристик (без изменений)."""
    parts = [sign or data.get("type", "здание"), data.get("type", ""),
             data.get("tier", ""), data.get("condition", "")]
    mat = data.get("materials") or {}
    if mat.get("walls"):
        parts.append(mat["walls"])
    parts += (data.get("features") or [])[:3]
    body = ", ".join(p for p in parts if p)
    return f"fantasy frontier town building, {body}, dark grim D&D, isometric, detailed, no text"
