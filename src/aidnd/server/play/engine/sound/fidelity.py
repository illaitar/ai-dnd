"""Fidelity rendering — how an overheard line looks at each tier.

Key functions
-------------
cutout(text, seed) -> str
    Keep sound_cutout_keep fraction of words (deterministic on seed), mask the
    rest with «…» — the L2 'part of a conversation' render.
overheard_line(text, tier, zone_name, seed) -> (str, float)
    (display_text, memory_weight) for an overheard conversation line at a tier.
"""

import random

from ..core import PB


def cutout(text: str, seed: str) -> str:
    """Keep sound_cutout_keep fraction of words (deterministic on seed), mask the
    rest with «…» — the L2 'part of a conversation' render."""
    words = text.split()
    if not words:
        return text
    rng = random.Random(seed)
    keep = max(1, round(len(words) * PB["sound_cutout_keep"]))
    idx = sorted(rng.sample(range(len(words)), min(keep, len(words))))
    out, gap = [], False
    for i in range(len(words)):
        if i in idx:
            out.append(words[i])
            gap = False
        elif not gap:
            out.append("…")
            gap = True
    return " ".join(out)


def overheard_line(text: str, tier: str, zone_name: str, seed: str) -> tuple[str, float]:
    """(display_text, memory_weight) for an overheard conversation line at a tier."""
    if tier == "L1":
        return text, PB["sound_mem_l1"]
    if tier == "L2":
        return cutout(text, seed), PB["sound_mem_l2"]
    return f"у «{zone_name}» о чём-то говорят", PB["sound_mem_l3"]
