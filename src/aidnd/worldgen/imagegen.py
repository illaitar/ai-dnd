"""Image generation (fal.ai Flux). NPC portrait = SET OF EMOTIONS of one face (approach B from
prototype: separate flux/schnell generations with SHARED seed + detailed description → face holds,
emotions expressive, unified "home" style with shared style-tail). Slicing not needed.

Key: env FAL_KEY or .secrets/fal.key. Images are heavy — fall as files into data/portraits/<id>/,
don't go to git (rsync to prod). Building prompt (build_prompt) left as was.

Key functions
-------------
portrait_prompt(persona, expr) -> str : Generate Flux prompt for NPC portrait with
  emotion and unified styling.
ImageGen : Base class for image generation (stub/no-op).
FluxImageGen : fal.ai Flux schnell backend; generate() + portraits() for 4 emotions.
get_imagegen() -> ImageGen : Factory; returns FluxImageGen if available, else ImageGen.
build_prompt(data, sign) -> str : Generate Flux prompt for building from sheet data.
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

# unified style of entire pool — main lever of coherence (same as in prototype)
STYLE = ("dark grim low-fantasy D&D character portrait, painterly semi-realistic, muted earthy "
         "palette, dramatic chiaroscuro lighting, plain dark background, head and shoulders bust, "
         "centered, no text, no watermark, no frame")

# 4 emotions: key maps to mind._emo / play (calm/warm/irritated/wary)
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
    """Face prompt: LEAD with explicit phrase sex+age (strong anchor for Flux — bare tag 'f' weak),
    then visual tags of persona, emotion, unified style."""
    sexw = {"m": "man", "f": "woman"}.get(persona.get("sex"), "person")
    agew = {"young": "young ", "middle": "middle-aged ", "old": "old ", "elder": "elderly "}.get(
        persona.get("age"), "")
    lead = f"a {agew}{sexw}"
    drop = {"m", "f", "male", "female", "man", "woman"}     # drop weak/duplicating gender tags
    tags = [str(t) for t in (persona.get("portrait") or []) if str(t).strip().lower() not in drop]
    if not tags:                                            # fallback if LLM didn't populate
        tags = [persona.get("build", "average"), (persona.get("look") or {}).get("hair", "")]
    body = ", ".join(t for t in tags if t)
    return f"{lead}, {body}, {expr}, {STYLE}" if body else f"{lead}, {expr}, {STYLE}"


class ImageGen:
    """Base: doesn't generate anything (hook disabled)."""

    def available(self) -> bool:
        return False

    def generate(self, prompt: str, *, seed: int | None = None, kind: str = "portrait") -> str | None:
        return None

    def portraits(self, npc_id: str, persona: dict, seed: int, out_dir: str) -> dict:
        return {}


class FluxImageGen(ImageGen):
    """fal.ai Flux schnell. One call = one emotion; shared seed per NPC keeps face."""

    def __init__(self, api_key: str | None = None, model: str = "fal-ai/flux/schnell"):
        self.api_key = api_key or _fal_key()
        self.model = model

    def available(self) -> bool:
        return bool(self.api_key) and _HAS_HTTPX

    def generate(self, prompt: str, *, seed: int | None = None, kind: str = "portrait") -> str | None:
        """One call to fal.run → image URL (or None; exception reason not suppressed above)."""
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
        """4 emotions of one face → files out_dir/<npc_id>/<emo>.png. Returns {emo: '<id>/<emo>.png'}."""
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
    """Prompt for BUILDING from characteristics sheet (unchanged)."""
    parts = [sign or data.get("type", "здание"), data.get("type", ""),
             data.get("tier", ""), data.get("condition", "")]
    mat = data.get("materials") or {}
    if mat.get("walls"):
        parts.append(mat["walls"])
    parts += (data.get("features") or [])[:3]
    body = ", ".join(p for p in parts if p)
    return f"fantasy frontier town building, {body}, dark grim D&D, isometric, detailed, no text"
