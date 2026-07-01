"""ПРОТОТИП портретов NPC через Flux (fal.ai). Проверяем ДВА вопроса до прогонки 1000:
  1) единый «домашний» стиль на РАЗНЫХ персонажах (общий style-хвост промпта);
  2) «одно лицо — разные эмоции»:
     A. ЛИСТ ВЫРАЖЕНИЙ — один вызов, сетка 2×2 того же лица, режем на 4 кропа (flux/dev);
     B. ПО-ЭМОЦИОННО — 4 вызова с ОДНИМ seed и одинаковой внешностью (flux/schnell).

Ключ: .secrets/fal.key (или env FAL_KEY). Вывод: data/portraits/_proto/<персонаж>/...
Запуск:  .venv/bin/python scripts/portrait_proto.py
Стоит копейки (≈15 картинок). Ничего в гит не пишет (data/portraits/ в .gitignore).
"""

from __future__ import annotations

import io
import os
import sys

import httpx

try:
    from PIL import Image
except ImportError:
    print("нужен Pillow"); sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "portraits", "_proto")
FAL = "https://fal.run/"

# единый стиль всего пула — общий хвост промпта (главный рычаг когерентности)
STYLE = ("dark grim low-fantasy D&D character portrait, painterly semi-realistic, "
         "muted earthy palette, dramatic chiaroscuro lighting, plain dark background, "
         "head and shoulders bust, centered, no text, no watermark, no frame")

# 4 эмоции (лягут на mind EMOTIONS + нейтраль): спокойное / тёплое / злое / испуг
EMO = [("calm", "calm neutral expression"), ("warm", "warm friendly smile"),
       ("angry", "angry scowling expression"), ("afraid", "fearful wide-eyed expression")]

# разнообразные лица — проверяем стиль на непохожих людях
CHARS = [
    ("smith", 101, "a grizzled middle-aged human blacksmith, weathered scarred face, "
                    "short greying beard, soot-smudged, worn leather apron over linen"),
    ("herbalist", 202, "a young lean human herbalist woman, sharp freckled face, dark hair "
                       "in a loose braid, patched grey hooded cloak, dried herbs at collar"),
    ("keeper", 303, "a portly jovial middle-aged human tavern-keeper, balding, ruddy round "
                    "face, big moustache, stained apron over a comfortable tunic"),
]


def _key() -> str:
    v = os.environ.get("FAL_KEY")
    if v:
        return v.strip()
    with open(os.path.join(ROOT, ".secrets", "fal.key"), encoding="utf-8") as f:
        return f.read().strip()


def fal(model: str, payload: dict) -> str | None:
    """Синхронный вызов fal.run → URL первой картинки (или None + печать ошибки)."""
    try:
        r = httpx.post(FAL + model, json=payload, timeout=180,
                       headers={"Authorization": f"Key {_key()}", "Content-Type": "application/json"})
    except httpx.HTTPError as e:
        print(f"  ! сеть: {e}"); return None
    if r.status_code != 200:
        print(f"  ! {model} HTTP {r.status_code}: {r.text[:200]}"); return None
    imgs = (r.json() or {}).get("images") or []
    return imgs[0]["url"] if imgs else None


def grab(url: str) -> Image.Image | None:
    try:
        b = httpx.get(url, timeout=120).content
        return Image.open(io.BytesIO(b)).convert("RGB")
    except (httpx.HTTPError, OSError) as e:
        print(f"  ! скачивание: {e}"); return None


def quad(img: Image.Image) -> list[Image.Image]:
    w, h = img.size
    return [img.crop(b) for b in ((0, 0, w // 2, h // 2), (w // 2, 0, w, h // 2),
                                  (0, h // 2, w // 2, h), (w // 2, h // 2, w, h))]


def run() -> None:
    for cid, seed, desc in CHARS:
        d = os.path.join(OUT, cid)
        os.makedirs(d, exist_ok=True)
        print(f"\n== {cid} ==")

        # A. ЛИСТ ВЫРАЖЕНИЙ (flux/dev, один вызов → 4 кропа)
        sheet_prompt = (f"character expression sheet, a 2x2 grid of four bust portraits of "
                        f"THE EXACT SAME person: {desc}. Identical face, hair and outfit in all "
                        f"four cells; four expressions — top-left {EMO[0][1]}, top-right {EMO[1][1]}, "
                        f"bottom-left {EMO[2][1]}, bottom-right {EMO[3][1]}; four equal quadrants, "
                        f"evenly divided, one face per cell; {STYLE}")
        print("  A: лист выражений (flux/dev)…")
        url = fal("fal-ai/flux/dev", {"prompt": sheet_prompt, "image_size": "square_hd",
                                      "num_inference_steps": 28, "guidance_scale": 3.5,
                                      "num_images": 1, "seed": seed, "enable_safety_checker": False})
        if url and (im := grab(url)):
            im.save(os.path.join(d, "A_sheet.png"))
            for (name, _), crop in zip(EMO, quad(im)):
                crop.save(os.path.join(d, f"A_{name}.png"))
            print("     ✓ A_sheet.png + 4 кропа")

        # B. ПО-ЭМОЦИОННО (flux/schnell, одинаковый seed + внешность)
        print("  B: по-эмоционно (flux/schnell, общий seed)…")
        for name, expr in EMO:
            u = fal("fal-ai/flux/schnell",
                    {"prompt": f"{desc}, {expr}; {STYLE}", "image_size": "square_hd",
                     "num_inference_steps": 4, "num_images": 1, "seed": seed,
                     "enable_safety_checker": False})
            if u and (im := grab(u)):
                im.save(os.path.join(d, f"B_{name}.png"))
        print("     ✓ B_calm/warm/angry/afraid.png")

    print(f"\nготово → {OUT}")


if __name__ == "__main__":
    run()
