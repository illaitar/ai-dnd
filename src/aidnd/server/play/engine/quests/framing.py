"""FRAMING — the two LLM seams (spec §3/§5 Steps 3-4).
  judge(...)  — ONE ranking call: K seeds as plain-Russian evidence + personas → {rank,veto,why}.
  framer(...) — 3 written artifacts (pitch / foreshadow / reveal) + a structural apophenia validator.
No LLM → honest absence (parse failure → empty / None; LLMUnavailable propagates to the morning hook).
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("aidnd.quests")

_CAP_RU = re.compile(r"[А-ЯЁ][а-яё]+")
_QUOTED = re.compile(r"«([^»]+)»")

# Sentence-initial capitalization is Russian orthography, not a properness signal — but a
# sentence-initial word can still BE the injected entity ("Гримберт ждёт тебя у моста." as the
# whole sentence). So only a curated set of common openers (imperatives/pronouns/discourse
# words that routinely start quest lines) get a free pass; anything else sentence-initial is
# still checked like any other candidate.
_OPENERS = frozenset({
    # imperatives of the quest register
    "верни", "найди", "принеси", "отнеси", "помоги", "разыщи", "забери", "добудь", "достань",
    "узнай", "выясни", "скажи", "спроси", "поговори", "приходи", "загляни", "поспеши", "берегись",
    "помни", "знай", "сделай", "будь",
    # address & the FULL pronoun paradigm (foreshadow speaks in the giver's first person —
    # live rejection: «Меня гложет…»)
    "чужак", "странник", "он", "она", "они", "оно", "ты", "вы", "я", "мы",
    "меня", "мне", "мной", "мною", "нас", "нам", "нами", "наш", "наша", "наше", "наши",
    "мой", "моя", "моё", "мои", "тебя", "тебе", "тобой", "твой", "твоя", "твоё", "твои",
    "вас", "вам", "вами", "ваш", "ваша", "ваше", "ваши",
    "его", "её", "ему", "ей", "им", "ими", "их", "себя", "себе", "собой",
    "сам", "сама", "само", "сами", "свой", "своя", "своё", "свои",
    "никто", "ничего", "все", "всё", "каждый", "кто-то", "что-то",
    # interrogatives (live rejection: «Кто подсобит…»)
    "кто", "что", "чем", "кому", "кого", "как", "где", "куда", "когда", "зачем", "почему", "сколько",
    # discourse markers & hearsay (live rejection: «Оказывается, мельник…» — the twist opener)
    "оказывается", "говорят", "ходят", "слышал", "слышно", "ведь", "вот", "это", "есть", "если",
    "здесь", "там", "может", "пусть", "пока", "потом", "сначала", "теперь", "скоро", "недавно",
    # temporal adverbs
    "вчера", "сегодня", "завтра", "утром", "днём", "вечером", "ночью",
    # quest-register abstractions (never proper names in this register)
    "прошу", "слушай", "награда", "плата", "обещаю", "клянусь", "дело", "беда", "нужда", "спасибо",
})

_FRAMER_SYS = (
    "Ты пишешь ТРИ короткие фразы для городского поручения, СТРОГО ПО-РУССКИ. Используй ТОЛЬКО названных людей и вещи — "
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


_WANT_RU = {"have": "раздобыть", "wealth": "накопить денег", "affinity": "наладить дела",
            "dead": "свести счёты"}


def _plain_want(seed: dict, names: dict) -> str:
    """Villain-less header text — names the milestone's want, not a predicate/target internals."""
    done = seed["goal"]["done"] or {}
    verb = _WANT_RU.get(done.get("type"), "разобраться со своим делом")
    if done.get("type") == "have" and done.get("item"):
        return f"{verb} «{done['item']}»"
    if done.get("type") in ("affinity", "dead"):
        who = names.get(done.get("id"))
        return f"{verb} с {who}" if who else verb
    return verb


def _evidence_facts(seed: dict, deeds: dict, names: dict) -> list:
    facts = []
    for i in seed.get("evidence", []):
        d = deeds.get(i.split(":", 1)[1] if i.startswith("deed:") else i)   # anchors carry deed:-prefix (seeds.py)
        if not d:
            continue
        what = d.get("data", {}).get("what") or d.get("verb")
        facts.append(f"{names.get(d.get('actor'), 'кто-то')}: {what}")
    return facts


def render_evidence(seed: dict, deeds: dict, names: dict) -> str:
    """One seed → plain-Russian header (only evidence facts + personas, no predicates leak).
    Villain-less (plain_need) seeds get a dedicated header — "против кто-то" would misrepresent
    a seed with no antagonist at all."""
    gv = seed["giver_name"]
    villain = seed["cast"].get("villain")
    facts = _evidence_facts(seed, deeds, names)
    if villain is None:
        head = f"{seed['sid']} [{seed['pattern']}]: {gv} хочет {_plain_want(seed, names)}."
        return head + ("\n  Факты: " + "; ".join(facts) if facts else "")
    vil = names.get(villain, "кто-то")
    prize = names.get(seed["cast"].get("prize"))
    head = f"{seed['sid']} [{seed['pattern']}]: {gv} против {vil}"
    head += f" (речь о {prize})." if prize else "."
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


_FUNC_RU = frozenset({
    "и", "а", "но", "же", "не", "ни", "или", "для", "под", "над", "при", "без", "про",
    "от", "до", "по", "за", "на", "в", "во", "с", "со", "у", "о", "об", "к", "ко", "из", "то",
})


def _ru_words(s: str) -> list:
    """Own tokenizer for the validator: _tokens_ru drops ≤3-letter words, which silently killed
    SHORT NAMES on both sides (live: giver «Рэн» rejected as unknown). Keep every ≥2-char word
    that isn't a function word."""
    return [w for w in re.findall(r"[а-яёa-z0-9]+", s.lower()) if len(w) >= 2 and w not in _FUNC_RU]


def _stem4(word: str) -> set:
    """A coarser prefix (4 chars) so short names still match their case
    endings ("Дунн"↔"Дунну", "Марта"↔"Марты"); short names («Рэн») survive whole.
    Trade-off accepted: a 4-char radius also admits first-4 collisions between unrelated names
    ("Мартин"↔"Марта"); the prompt's МОЖНО НАЗЫВАТЬ list is the first line of defense, this
    validator is the second, coarser one."""
    return {w[:4] for w in _ru_words(word)}


def _all_tokens_match(phrase: str, allow_tok: set) -> bool:
    """Every meaningful token of `phrase` (function words dropped by _ru_words)
    must stem-match an allowed name — a phrase isn't known just because ONE of its words is."""
    toks = _ru_words(phrase)
    if not toks:
        return False
    def hit(w):
        # common-prefix rule scaled by token length: two tokens match when they share
        # max(2, min(len)-1) leading chars — bridges Russian case endings even inside the
        # stem window («Юна»↔«Юну», «Ирма»↔«Ирмы», «Дунн»↔«Дунну»). Collision radius is
        # deliberately loose (validator = second line of defense; the prompt is the first).
        for a in allow_tok:
            m = max(2, min(len(w), len(a)) - 1)
            if w[:m] == a[:m]:
                return True
        return False
    return all(hit(w) for w in toks)


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
        if not _ru_words(c):
            continue                      # pure function-word candidate («За…») — nothing to validate
        if not _all_tokens_match(c, allow_tok):
            log.info("quests: валидатор отверг «%s» (текст: %s…)", c, text[:90])
            return False
    return True


_NUM = re.compile(r"\d+")


def _true_numbers(seed: dict, reward: int | float | None) -> set:
    """Numbers code actually owns for this seed (spec: pitch figures are never the LLM's invention).
    wealth predicates carry a real target amount (seed['goal']['done']['value']); any real reward
    counts too; 0 and single-digit flavor numbers ("через 2 дня") are trivially harmless."""
    nums = {0}
    done = seed.get("goal", {}).get("done") or {}
    if done.get("type") == "wealth" and done.get("value") is not None:
        try:
            nums.add(int(round(float(done["value"]))))
        except (TypeError, ValueError):
            pass
    if reward:
        try:
            nums.add(int(round(float(reward))))
        except (TypeError, ValueError):
            pass
    return nums


def valid_numbers(text: str, true_nums: set) -> bool:
    """Every standalone digit-run in `text` must be one of `true_nums` or a trivially small
    (≤9) flavor number — numbers are code's domain, not the LLM's invention (mirrors
    valid_entities: a fabricated figure fails the whole artifact)."""
    for m in _NUM.finditer(text or ""):
        n = int(m.group())
        if n in true_nums or n <= 9:
            continue
        log.info("quests: валидатор отверг число «%d» (текст: %s…)", n, (text or "")[:90])
        return False
    return True


def framer(seed: dict, allowed: set, manager, reward: int | float | None = None) -> dict | None:
    """ONE artifact set (pitch/foreshadow/reveal); apophenia validator rejects unknown entities AND
    fabricated numbers; one regenerate on failure, else honest absence (mirrors _build_step's
    reject-don't-repair). `reward` (coin reward, when already known at call time) is fed into the
    prompt and the number-validator alongside the seed's own true target value."""
    if manager is None:
        return None
    # summary IS the giver's real life-goal (plan_agenda-authored, sim truth) — write ABOUT it, not
    # just around the giver's name; the judge's `why` is flavor-only fallback when a seed carries none.
    # advertise only Cyrillic material — raw predicate keywords (wealth/have) stay in `allowed`
    # for validation but must not be parroted into a Russian pitch («помоги накопить wealth»)
    advertised = sorted(a for a in allowed if re.search(r"[а-яА-ЯёЁ]", a))
    lines = [f"ЗАКАЗЧИК: {seed['giver_name']}. Суть: {seed.get('summary') or seed.get('why', '')}",
             f"МОЖНО НАЗЫВАТЬ: {', '.join(advertised or sorted(allowed))}."]
    done = seed.get("goal", {}).get("done") or {}
    if done.get("type") == "wealth" and done.get("value") is not None:
        # numbers are code's domain — the true target goes IN the prompt so the LLM can't invent one
        lines.append(f"ЦЕЛЬ: не хватает {int(round(float(done['value'])))} монет.")
    elif done.get("type") == "have" and done.get("item"):
        lines.append(f"ЦЕЛЬ: раздобыть «{done['item']}».")
    if reward:
        lines.append(f"НАГРАДА: {int(round(float(reward)))} монет.")
    user = "\n".join(lines)
    true_nums = _true_numbers(seed, reward)
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
        if (required_ok and all(valid_entities(v, allowed) for v in art.values())
                and all(valid_numbers(v, true_nums) for v in art.values())):
            return art
    log.warning("quests: фреймер назвал чужую сущность или число дважды — пропуск этим утром")
    return None
