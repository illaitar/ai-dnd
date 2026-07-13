"""FRAMING — the two LLM seams (spec §3/§5 Steps 3-4).
  judge(...)  — ONE ranking call: K seeds as plain-Russian evidence + personas → {rank,veto,why}.
  framer(...) — 3 written artifacts (pitch / foreshadow / reveal) + a structural apophenia validator.
No LLM → honest absence (parse failure → empty / None; LLMUnavailable propagates to the morning hook).
"""

from __future__ import annotations

import json
import logging
import re

from aidnd.server.play.engine.core import _tokens_ru

log = logging.getLogger("aidnd.quests")

_CAP_RU = re.compile(r"[А-ЯЁ][а-яё]+")
_QUOTED = re.compile(r"«([^»]+)»")

# Sentence-initial capitalization is Russian orthography, not a properness signal — but a
# sentence-initial word can still BE the injected entity ("Гримберт ждёт тебя у моста." as the
# whole sentence). So only a curated set of common openers (imperatives/pronouns/discourse
# words that routinely start quest lines) get a free pass; anything else sentence-initial is
# still checked like any other candidate.
_OPENERS = frozenset({
    "верни", "найди", "принеси", "отнеси", "помоги", "разыщи", "забери", "чужак", "странник",
    "он", "она", "они", "оно", "тебя", "тебе", "твой", "твоя", "здесь", "если", "когда", "там",
    "вот", "это", "есть", "прошу", "слушай", "говорят",
})

_FRAMER_SYS = (
    "Ты пишешь ТРИ короткие фразы для городского поручения. Используй ТОЛЬКО названных людей и вещи — "
    "никого и ничего нового не выдумывай. Верни СТРОГО JSON: "
    '{"pitch":"<просьба в характере, 1-2 фразы, с сутью и наградой>", '
    '"foreshadow":"<что гложет заказчика, 1 фраза, до предложения>", '
    '"reveal":"<фраза поворота, если всплывёт второй факт>"}.'
)

_JUDGE_SYS = (
    "Ты — редактор городских слухов. Оцени зёрна сюжета на живость и вкус; наложи вето на те, "
    "что звучат фальшиво; каждому дай ОДНУ фразу «чем цепляет». Верни СТРОГО JSON: "
    '{"rank": ["<sid>", ...], "veto": ["<sid>", ...], '
    '"why": {"<sid>": "<одна фраза>", ...}}. Только перечисленные sid, ничего не выдумывай.'
)


def render_evidence(seed: dict, deeds: dict, names: dict) -> str:
    """One seed → plain-Russian header (only evidence facts + personas, no predicates leak)."""
    gv = seed["giver_name"]
    vil = names.get(seed["cast"].get("villain"), "кто-то")
    prize = names.get(seed["cast"].get("prize"))
    head = f"{seed['sid']} [{seed['pattern']}]: {gv} против {vil}"
    head += f" (речь о {prize})." if prize else "."
    facts = []
    for i in seed.get("evidence", []):
        d = deeds.get(i.split(":", 1)[1] if i.startswith("deed:") else i)   # anchors carry deed:-prefix (seeds.py)
        if not d:
            continue
        what = d.get("data", {}).get("what") or d.get("verb")
        facts.append(f"{names.get(d.get('actor'), 'кто-то')}: {what}")
    return head + ("\n  Факты: " + "; ".join(facts) if facts else "")


def judge(seeds: list, deeds: dict, names: dict, manager) -> list[dict]:
    if manager is None:
        return []
    for s in seeds:
        s.setdefault("sid", f"seed_{s['giver'].split(':')[-1]}_{s['pattern']}")
    payload = "\n".join(render_evidence(s, deeds, names) for s in seeds)
    resp = manager.call("narrator",
                        [{"role": "system", "content": _JUDGE_SYS},
                         {"role": "user", "content": payload}],
                        options={"temperature": 0.4})
    t = (resp.get("content") if resp else "") or ""
    try:
        d = json.loads(t[t.find("{"): t.rfind("}") + 1])
        rank, veto, why = list(d["rank"]), set(d.get("veto") or []), dict(d.get("why") or {})
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        log.warning("quests: judge вернул неразборный JSON — предложения нет этим утром")
        return []
    by_sid = {s["sid"]: s for s in seeds}
    kept = []
    for sid in rank:
        s = by_sid.get(sid)
        if not s or sid in veto:
            continue
        s["why"] = str(why.get(sid, ""))[:160]
        kept.append(s)
    return kept


def _stem4(word: str) -> set:
    """A coarser prefix (4 chars, not _tokens_ru's 5) so short names still match their case
    endings ("Дунн"↔"Дунну", "Марта"↔"Марты") — _tokens_ru alone is too fine for 4-5 letter names.
    Trade-off accepted: a 4-char radius also admits first-4 collisions between unrelated names
    ("Мартин"↔"Марта"); the prompt's МОЖНО НАЗЫВАТЬ list is the first line of defense, this
    validator is the second, coarser one."""
    return {t[:4] for t in _tokens_ru(word)}


def _all_tokens_match(phrase: str, allow_tok: set) -> bool:
    """Every meaningful token of `phrase` (predlogs/short words already dropped by _tokens_ru)
    must stem-match an allowed name — a phrase isn't known just because ONE of its words is."""
    toks = _tokens_ru(phrase)
    if not toks:
        return False
    return all(t[:4] in allow_tok for t in toks)


def valid_entities(text: str, allowed: set) -> bool:
    """Every «quoted» phrase and Capitalized Cyrillic word must share a stem with some allowed
    name (mirrors _build_step contracts.py:60 — an unknown entity fails the whole artifact).
    A capitalized word at the very start of a sentence is only skipped when it's a common opener
    (imperative/pronoun/discourse word) or already matches an allowed name — sentence-initial
    capitalization is Russian orthography, but the word itself can still be the injected entity."""
    text = text or ""
    allow_tok = set()
    for a in allowed:
        allow_tok |= _stem4(a)
    cands = list(_QUOTED.findall(text))
    for m in _CAP_RU.finditer(text):
        word = m.group()
        i = m.start() - 1
        while i >= 0 and text[i] in " \t\n":
            i -= 1
        sentence_initial = i < 0 or text[i] in ".!?"
        if sentence_initial and (word.lower() in _OPENERS or _all_tokens_match(word, allow_tok)):
            continue
        cands.append(word)
    for c in cands:
        if not _all_tokens_match(c, allow_tok):
            return False
    return True


def framer(seed: dict, allowed: set, manager) -> dict | None:
    """ONE artifact set (pitch/foreshadow/reveal); apophenia validator rejects unknown entities;
    one regenerate on failure, else honest absence (mirrors _build_step's reject-don't-repair)."""
    if manager is None:
        return None
    user = (f"ЗАКАЗЧИК: {seed['giver_name']}. Суть: {seed.get('why', '')}\n"
            f"МОЖНО НАЗЫВАТЬ: {', '.join(sorted(allowed))}.")
    for _attempt in range(2):                      # generate → validate → regenerate once → skip
        resp = manager.call("narrator",
                            [{"role": "system", "content": _FRAMER_SYS},
                             {"role": "user", "content": user}],
                            options={"temperature": 0.7})
        t = (resp.get("content") if resp else "") or ""
        try:
            d = json.loads(t[t.find("{"): t.rfind("}") + 1])
            art = {k: str(d.get(k, ""))[:220] for k in ("pitch", "foreshadow", "reveal")}
        except (json.JSONDecodeError, ValueError):
            continue
        required_ok = bool(art["pitch"]) and bool(art["foreshadow"]) and (
            bool(art["reveal"]) if seed.get("twist") else True)
        if required_ok and all(valid_entities(v, allowed) for v in art.values()):
            return art
    log.warning("quests: фреймер назвал чужую сущность дважды — пропуск этим утром")
    return None
