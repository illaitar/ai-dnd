"""Детерминизм по иерархии сидов (док 01 §4).

Мировой сид порождает суб-сиды по доменам генерации через хеш. Один мировой сид
воспроизводит один и тот же предгенерированный мир; ленивые генерации сидятся от
мирового сида + вид + локация + тик доступа, поэтому воспроизводимы при replay.
"""

from __future__ import annotations

import hashlib


def subseed(world_seed: int, *parts) -> int:
    digest = hashlib.blake2b(
        (str(world_seed) + "|" + "|".join(map(str, parts))).encode()
    ).hexdigest()[:16]
    return int(digest, 16)
