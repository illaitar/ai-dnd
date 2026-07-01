"""LLM-насыщение NPC — зеркало enrich_llm.py, но про людей. Один вызов на NPC → персона-фактшит:
структурная ВНЕШНОСТЬ (визуальные поля → промпт Flux), манера/голос, био, секрет, связи, зацепки И
полный ИНВЕНТАРЬ/ЭКИПИРОВКА (пока флейвор-теги). Не проза — теги/энумы/короткие фразы; речь соберёт
нарратор в рантайме. Согласовано с МЕХАНИКОЙ (11 черт mind + обаяние + видимое богатство) через
подсказки в промпте, но НИКОГДА не переписывает числа — персона это только флейвор поверх.

LLMPersona — реальный путь (роль character_writer → профиль deepseek); StubPersona — офлайн/тесты.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

SEX = ("m", "f")
AGE = ("young", "adult", "middle", "old", "elder")
BUILD = ("lean", "average", "stocky", "heavy", "tall")
VOICE = ("gruff", "warm", "clipped", "florid", "meek", "booming")
STANCE = ("warm", "neutral", "wary", "dour", "greedy", "hostile")
ITEM_TIER = ("poor", "modest", "fine", "rich")


@dataclass
class PersonaCtx:
    id: str
    name: str
    role: str
    sex: str = "m"                     # задаётся механикой вместе с именем — персона/портрет ОБЯЗАНЫ соблюдать
    traits: dict = field(default_factory=dict)
    charisma: float = 0.3
    appearance: float = 0.3            # видимое богатство [0..1]
    region: str = "фронтир тёмного фэнтези (D&D)"


_PERSONA_SYS = (
    "Ты — генератор персон NPC для тёмно-фэнтезийного фронтирного городка (D&D). По краткой механической "
    "заготовке (роль, черты характера, обаяние, видимое богатство) верни ТОЛЬКО JSON-фактшит человека — "
    "КОРОТКО, теги/энумы/короткие фразы, БЕЗ прозы и абзацев (речь и описания соберёт нарратор). "
    "Персона обязана быть СОГЛАСОВАНА с чертами и богатством (жадный — прижимист и хапуга; бедный — в "
    "обносках; смелый — держится прямо). Поля:\n"
    "sex (m|f); age (young|adult|middle|old|elder); build (lean|average|stocky|heavy|tall); race (обычно человек);\n"
    "look {face, hair, skin, clothing, marks:[приметы]} — ВИЗУАЛЬНО, одежда по достатку;\n"
    "voice (gruff|warm|clipped|florid|meek|booming); speech (массив речевых привычек);\n"
    "stance (warm|neutral|wary|dour|greedy|hostile) — базовая манера к чужаку, в тон чертам;\n"
    "origin (откуда/кто); background (массив факт-тегов: бывшее ремесло, зачем в городе);\n"
    "wants (массив стремлений); fears (массив страхов); quirk (одна памятная деталь);\n"
    "secret ({what, where, gate} или null); ties (массив коротких связей: кому должен/родня/вражда);\n"
    "rumors (массив коротких зацепок-слухов);\n"
    "portrait (массив ВИЗУАЛЬНЫХ тегов НА АНГЛИЙСКОМ для художника: пол/возраст/лицо/волосы/одежда/приметы);\n"
    "gear {weapon, offhand, armor, garb, trinkets:[...]} — оружие/щит/броня могут быть null; каждый предмет "
    "{name, tier:(poor|modest|fine|rich), note}; garb — повседневная одежда;\n"
    "carry {coins:(целое, по достатку), goods:[товары/припасы], personal:[личные мелочи]};\n"
    "valuables (массив — что ценного можно украсть).\n"
    "ЯЗЫК: энум-поля (sex/age/build/voice/stance/tier) и МАССИВ portrait — строго АНГЛ. ключи/слова. "
    "ВСЁ остальное (look, speech, origin, background, wants, fears, quirk, secret, ties, rumors, названия "
    "предметов и заметки, goods/personal/valuables) — НА РУССКОМ, короткими естественными фразами, без "
    "snake_case и англицизмов."
)


def _parse_json(text: str | None) -> dict | None:
    if not text:
        return None
    t = re.sub(r"```$", "", re.sub(r"^```(?:json)?", "", text.strip()).strip()).strip()
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except (json.JSONDecodeError, ValueError):
                return None
    return None


def _enum(v, allowed, default):
    return v if v in allowed else default


def _list(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _item(v):
    if not isinstance(v, dict) or not str(v.get("name") or "").strip():
        return None
    return {"name": str(v["name"]).strip(), "tier": _enum(v.get("tier"), ITEM_TIER, "modest"),
            "note": str(v.get("note") or "").strip()}


def trait_hints(traits: dict, charisma: float, appearance: float) -> str:
    """Черты + обаяние + богатство → русские подсказки-прилагательные для промпта (якорь согласованности)."""
    g, h = traits.get, []
    def hi(k, t=0.65): return g(k, 0.5) >= t
    def lo(k, t=0.35): return g(k, 0.5) <= t
    if hi("greed"): h.append("прижимист, корыстен")
    if lo("greed", .3): h.append("щедр")
    if lo("honesty"): h.append("лжив, скользкий")
    if hi("honesty", .78): h.append("честен, прямодушен")
    if hi("malice", .55): h.append("жесток, злобен")
    elif hi("malice", .3): h.append("есть жестокость")
    if hi("sociability", .7): h.append("говорлив, общителен")
    if lo("sociability", .3): h.append("нелюдим, молчалив")
    if lo("bravery"): h.append("трусоват, робок")
    if hi("bravery", .78): h.append("смел, держится прямо")
    if hi("pride", .7): h.append("горделив, чванлив")
    if hi("irritability", .68): h.append("вспыльчив")
    if hi("curiosity", .72): h.append("любопытен")
    if lo("lawful", .25): h.append("плюёт на закон")
    if hi("lawful", .78): h.append("чтит порядок")
    if hi("ambition", .72): h.append("честолюбив")
    h.append("обаятелен, приятной наружности" if charisma >= .6
             else "невзрачен" if charisma <= .3 else "заурядной внешности")
    h.append("богато одет" if appearance >= .6 else "беден, в обносках" if appearance <= .3 else "одет прилично")
    return "; ".join(h)


def normalize(d: dict, ctx: PersonaCtx) -> dict:
    d = d or {}
    look = d.get("look") if isinstance(d.get("look"), dict) else {}
    gear = d.get("gear") if isinstance(d.get("gear"), dict) else {}
    carry = d.get("carry") if isinstance(d.get("carry"), dict) else {}
    secret = d.get("secret") if isinstance(d.get("secret"), dict) and d["secret"].get("what") else None
    try:
        coins = max(0, int(carry.get("coins", 0)))
    except (TypeError, ValueError):
        coins = 0
    portrait = [w for w in _list(d.get("portrait")) if re.search("[A-Za-z]", w)]  # только EN-теги
    return {
        "sex": ctx.sex if ctx.sex in SEX else _enum(d.get("sex"), SEX, "m"),  # пол диктует механика
        "age": _enum(d.get("age"), AGE, "adult"),
        "build": _enum(d.get("build"), BUILD, "average"), "race": str(d.get("race") or "человек").strip(),
        "look": {"face": str(look.get("face", "") or "").strip(), "hair": str(look.get("hair", "") or "").strip(),
                 "skin": str(look.get("skin", "") or "").strip(), "clothing": str(look.get("clothing", "") or "").strip(),
                 "marks": _list(look.get("marks"))},
        "voice": _enum(d.get("voice"), VOICE, "clipped"), "speech": _list(d.get("speech")),
        "stance": _enum(d.get("stance"), STANCE, "neutral"),
        "origin": str(d.get("origin") or "").strip(), "background": _list(d.get("background")),
        "wants": _list(d.get("wants")), "fears": _list(d.get("fears")),
        "quirk": str(d.get("quirk") or "").strip(),
        "secret": ({"what": str(secret.get("what", "")), "where": str(secret.get("where", "")),
                    "gate": str(secret.get("gate", ""))} if secret else None),
        "ties": _list(d.get("ties")), "rumors": _list(d.get("rumors")),
        "portrait": portrait,
        "gear": {"weapon": _item(gear.get("weapon")), "offhand": _item(gear.get("offhand")),
                 "armor": _item(gear.get("armor")), "garb": _item(gear.get("garb")),
                 "trinkets": [it for it in (_item(x) for x in (gear.get("trinkets") or [])) if it]},
        "carry": {"coins": coins, "goods": _list(carry.get("goods")), "personal": _list(carry.get("personal"))},
        "valuables": _list(d.get("valuables")),
    }


class PersonaEnricher:
    def describe(self, ctx: PersonaCtx) -> dict | None:
        raise NotImplementedError


class StubPersona(PersonaEnricher):
    """Детерминированная заглушка (офлайн/тесты) — без выдумки, ровно по механике."""

    def describe(self, ctx: PersonaCtx) -> dict:
        rich = ctx.appearance >= 0.55
        return normalize({
            "sex": "m", "age": "adult", "build": "average",
            "look": {"face": "обветренное лицо", "hair": "тёмные волосы", "skin": "загорелая кожа",
                     "clothing": ("добротный кафтан" if rich else "простая холщовая рубаха"),
                     "marks": ["мозолистые руки"]},
            "voice": "clipped", "speech": ["говорит по делу"], "stance": "neutral",
            "origin": "здешний, из городка", "background": [f"{ctx.role} на фронтире"],
            "wants": ["прожить день без бед"], "fears": ["лихие люди на трактах"],
            "quirk": "теребит поясной ремень",
            "portrait": ["human", "adult", "weathered face", "plain tunic"],
            "gear": {"garb": {"name": ("добротная одежда" if rich else "холщовая одежда"),
                              "tier": ("fine" if rich else "poor"), "note": ""},
                     "trinkets": [{"name": "медный оберег", "tier": "poor", "note": ""}]},
            "carry": {"coins": (20 if rich else 4), "goods": [], "personal": ["огниво"]},
            "valuables": (["кошель"] if rich else []),
        }, ctx)


class LLMPersona(PersonaEnricher):
    """Реальный путь: роль character_writer, JSON-фактшит (без прозы)."""

    def __init__(self, manager):
        self.manager = manager

    def describe(self, ctx: PersonaCtx) -> dict | None:
        if not self.manager.available():
            return None
        sex_ru = "женский" if ctx.sex == "f" else "мужской"
        user = (f"Заготовка NPC: роль «{ctx.role}»; ПОЛ {sex_ru} (строго соблюдай в look и в portrait-тегах); "
                f"характер — {trait_hints(ctx.traits, ctx.charisma, ctx.appearance)}; мир: {ctx.region}. "
                f"Имя уже дано: {ctx.name}. Сгенерируй персону этого человека.")
        resp = self.manager.call("character_writer",
                                 [{"role": "system", "content": _PERSONA_SYS},
                                  {"role": "user", "content": user}], options={"temperature": 0.75})
        data = _parse_json(resp.get("content") if resp else None)
        return normalize(data, ctx) if data else None
