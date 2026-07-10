"""Scene digest — the end-of-tick narrator.

Weaves the tick's OBSERVABLE events (ambient sound, NPC actions, overheard speech) into ONE
third-person account for the player, ordered nearest → farthest. This is where raw per-NPC
self-narration (`does`, first person, may leak intent) is re-authored as observable prose and
stripped of thoughts/plans/hidden motives. See
docs/superpowers/specs/2026-07-10-scene-digest-chat-design.md (Increment 2).
"""

from __future__ import annotations

from aidnd.server.play.engine.core import _model

_SYS = (
    "Ты — рассказчик сцены в мрачном фэнтези. Тебе дают список наблюдаемых событий вокруг "
    "игрока за один ход: звуки окружения, действия людей, обрывки чужой речи — с пометкой, "
    "насколько это близко и слышно. Собери из них ОДНО живое описание сцены от ТРЕТЬЕГО лица, "
    "по-русски, 2–4 предложения, идя от самого близкого и слышимого к дальнему фону.\n"
    "ЖЁСТКИЕ ПРАВИЛА:\n"
    "1. Только то, что видно и слышно СО СТОРОНЫ. НИКОГДА не описывай мысли, намерения, планы "
    "или скрытые мотивы персонажей («в поисках добычи», «задумал», «решил») — лишь внешние "
    "действия. Оценки-домыслы тоже убирай.\n"
    "2. Незнакомцев называй естественно по внешности («рыжий крепкий мужчина», «дворф с чёрной "
    "бородой»), НЕ ярлыками вида «мужчина — рыжие».\n"
    "3. Дальнюю речь передавай глухо — общим смыслом или гулом, не дословно; близкую можно ближе "
    "к словам.\n"
    "4. Не выдумывай ничего сверх списка. Не обращайся к игроку на «ты» и не описывай его "
    "действия; если он попал в кадр — отстранённо («путник», «чужак у входа»).\n"
    "Верни только прозу сцены, без пояснений и списков."
)

_NEAR = {1: "близко", 2: "поодаль", 3: "издалека"}


def _event_lines(feed: list[dict]) -> list[str]:
    """Structured event list handed to the narrator (deterministic — unit-tested)."""
    out: list[str] = []
    for f in feed or []:
        text = (f.get("text") or "").strip()
        if not text:
            continue
        who = (f.get("who") or "").strip()
        if f.get("k") == "speech":
            where = _NEAR.get(f.get("tier", 1), "поодаль")
            out.append(f"- речь ({where}): {who or 'кто-то'} — {text}")
        else:
            out.append(f"- действие/звук: {(who + ': ') if who else ''}{text}")
    return out


def scene_digest(feed: list[dict], place: str) -> str:
    """Weave the tick feed into one observable third-person paragraph. '' if nothing to tell.

    May raise LLMUnavailable / LLMBadOutput — the caller (_world_tick) handles it (no fallback).
    """
    lines = _event_lines(feed)
    if not lines:
        return ""
    resp = _model().call(
        "narrator",
        [
            {"role": "system", "content": _SYS},
            {"role": "user",
             "content": f"Место: {place}. Наблюдаемые события вокруг игрока за этот ход:\n"
                        + "\n".join(lines)},
        ],
        options={"temperature": 0.5},
    )
    return (resp.get("content") or "").strip()
