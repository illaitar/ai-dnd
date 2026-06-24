"""Физический контекст сцены: сезон, время суток, погода, освещение (read-model).

Всё детерминировано от мирового сида и тика, поэтому воспроизводимо при replay и
не входит в state_hash. Погода стабильна в пределах суток и зависит от сезона;
в помещении она «за окнами». Контекст отдаётся нарратору и в UI, чтобы сцена была
заземлена в физическом окружении.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .. import config

SEASONS = ["spring", "summer", "autumn", "winter"]
SEASON_RU = {"spring": "весна", "summer": "лето", "autumn": "осень", "winter": "зима"}
TIME_RU = {"morning": "утро", "day": "день", "evening": "вечер", "night": "ночь"}

# погода с весами по сезонам
WEATHER_RU = {"clear": "ясно", "cloudy": "облачно", "rain": "дождь", "fog": "туман",
              "snow": "снег", "storm": "гроза", "windy": "ветрено"}
SEASON_WEATHER = {
    "spring": {"clear": 3, "cloudy": 3, "rain": 3, "fog": 2, "windy": 2, "storm": 1},
    "summer": {"clear": 5, "cloudy": 2, "rain": 2, "storm": 2, "windy": 1},
    "autumn": {"clear": 2, "cloudy": 4, "rain": 3, "fog": 3, "windy": 2},
    "winter": {"clear": 2, "cloudy": 3, "snow": 4, "fog": 2, "windy": 2},
}

INDOOR_KINDS = {"building", "room"}
SHELTER_AFFORD = {"inn", "shop", "shrine", "manor", "townhall", "hideout", "residential"}


@dataclass
class SceneContext:
    day: int
    season: str
    time_of_day: str
    hhmm: str
    weather: str
    indoor: bool
    light: str                  # bright | soft | dim | dark
    place_name: str
    ambiance: str               # короткая физическая атмосфера места
    descriptor: str             # готовая фраза для нарратора/UI
    intensity: str = "none"     # none|light|moderate|heavy (осадки/туман)
    wind: str = "calm"          # calm|breezy|strong

    def to_dict(self) -> dict:
        return {"day": self.day, "season": self.season, "season_ru": SEASON_RU[self.season],
                "time_of_day": self.time_of_day, "time_ru": TIME_RU.get(self.time_of_day, ""),
                "hhmm": self.hhmm, "weather": self.weather,
                "weather_ru": WEATHER_RU.get(self.weather, self.weather),
                "intensity": self.intensity, "wind": self.wind,
                "indoor": self.indoor, "light": self.light, "place_name": self.place_name,
                "ambiance": self.ambiance, "descriptor": self.descriptor,
                "effects": effects(self).to_dict()}


def day_number(tick: int) -> int:
    per_day = (24 * 60) // config.SIM_MINUTES_PER_TICK
    return tick // per_day


def season_of_day(day: int) -> str:
    base = SEASONS.index(config.START_SEASON) if config.START_SEASON in SEASONS else 2
    return SEASONS[(base + day // config.DAYS_PER_SEASON) % 4]


def season_of(tick: int) -> str:
    return season_of_day(day_number(tick))


def _weighted(weights: dict, rng: random.Random) -> str:
    items = list(weights.items())
    total = sum(w for _, w in items)
    r, acc = rng.random() * total, 0.0
    for k, w in items:
        acc += w
        if r <= acc:
            return k
    return items[-1][0]


def _base_draw(seed: int, day: int, region: str, season: str) -> str:
    """Независимый сезонно-взвешенный розыгрыш погоды на день."""
    return _weighted(SEASON_WEATHER[season], random.Random(f"{seed}|{day}|{region}|wbase"))


def _day_weather(seed: int, day: int, region: str, season: str) -> str:
    """Погода дня с 1-шаговой ИНЕРЦИЕЙ: сегодня нередко тянется за вчерашним днём —
    нет скачков ясно→гроза→ясно. Чистая функция (seed, day, region) → replay-safe."""
    today = _base_draw(seed, day, region, season)
    if day <= 0:
        return today
    prev = _base_draw(seed, day - 1, region, season_of_day(day - 1))
    if random.Random(f"{seed}|{day}|{region}|inertia").random() < 0.45:
        return prev                                  # вчерашняя погода держится
    return today


def _segment_weather(day_w: str, seed: int, day: int, tod: str, region: str, season: str) -> str:
    """Внутрисуточный сдвиг: туман любит утро, грозы — день/вечер, к ночи буря стихает,
    туман рассеивается днём. Детерминировано по (seed, day, tod, region)."""
    r = random.Random(f"{seed}|{day}|{tod}|{region}|seg").random()
    if tod == "morning" and day_w in ("clear", "cloudy") and season != "summer" and r < 0.35:
        return "fog"
    if tod in ("day", "evening") and day_w == "cloudy" and season in ("summer", "spring") and r < 0.18:
        return "storm"
    if tod == "night" and day_w == "storm":
        return "rain" if r < 0.6 else "cloudy"       # ночью гроза стихает
    if tod == "day" and day_w == "fog" and r < 0.5:
        return "clear" if season == "summer" else "cloudy"   # туман рассеивается к полудню
    if tod == "evening" and day_w == "rain" and r < 0.25:
        return "cloudy"                              # дождь стихает к вечеру
    return day_w


PRECIP = {"rain", "snow", "storm"}


def intensity_of(weather: str, seed: int, day: int, tod: str, region: str) -> str:
    """none|light|moderate|heavy для осадков/тумана; остальное — none."""
    if weather not in PRECIP and weather != "fog":
        return "none"
    if weather == "storm":
        return "heavy"
    r = random.Random(f"{seed}|{day}|{tod}|{region}|intensity").random()
    if weather == "fog":
        return "heavy" if r < 0.4 else "moderate"
    return "heavy" if r < 0.3 else ("moderate" if r < 0.7 else "light")


def wind_of(weather: str) -> str:
    if weather == "storm":
        return "strong"
    if weather == "windy":
        return "breezy"
    return "calm"


def weather_of(world_seed: int, tick: int, region: str, season: str) -> str:
    """Итоговая погода на тик: погода дня (с инерцией) + внутрисуточный сдвиг."""
    day = day_number(tick)
    day_w = _day_weather(world_seed, day, region, season)
    return _segment_weather(day_w, world_seed, day, _tod_of(tick), region, season)


def _tod_of(tick: int) -> str:
    minutes = (tick * config.SIM_MINUTES_PER_TICK) % (24 * 60)
    h = minutes // 60
    return ("morning" if 5 <= h < 12 else "day" if 12 <= h < 18
            else "evening" if 18 <= h < 22 else "night")


def _light(time_of_day: str, indoor: bool, weather: str) -> str:
    if indoor:
        return "dim" if time_of_day == "night" else "soft"
    base = {"morning": "soft", "day": "bright", "evening": "dim", "night": "dark"}[time_of_day]
    if weather in ("fog", "storm", "snow") and base == "bright":
        base = "soft"
    return base


def is_indoor(world, place) -> bool:
    """Укрыто от неба: здание-укрытие, комната внутри здания, либо узел под землёй."""
    if not place:
        return False
    affs = set(getattr(place, "affordances", []) or [])
    if place.kind == "building" and (affs & SHELTER_AFFORD):
        return True
    if place.kind == "room":
        parent = world.spatial.places.get(place.parent) if place.parent else None
        return bool(parent and parent.kind in ("building", "site"))
    return False


def _weather_phrase(weather: str, indoor: bool, intensity: str = "moderate",
                    wind: str = "calm") -> str:
    if weather == "rain":
        out = {"light": "моросит дождь", "heavy": "хлещет ливень"}.get(intensity, "идёт дождь")
    elif weather == "snow":
        out = {"light": "порхает редкий снег", "heavy": "метёт метель"}.get(intensity, "идёт снег")
    elif weather == "fog":
        out = "стелется густой туман" if intensity == "heavy" else "стелется туман"
    else:
        out = {"clear": "небо ясное", "cloudy": "небо затянуто облаками",
               "storm": "бушует гроза", "windy": "налетает порывистый ветер"}.get(
                   weather, WEATHER_RU.get(weather, weather))
    if wind == "strong" and weather not in ("storm", "windy"):
        out += ", задувает сильный ветер"
    return ("снаружи " + out) if indoor else out


def scene_context(world, place_id: str) -> SceneContext:
    tick = world.clock.tick
    season = season_of(tick)
    tod = world.clock.time_of_day()
    place = world.spatial.places.get(place_id)
    region = place.parent if place else "region:phandalin"
    reg = region or "region"
    weather = weather_of(world.seed, tick, reg, season)
    intensity = intensity_of(weather, world.seed, day_number(tick), tod, reg)
    wind = wind_of(weather)
    indoor = is_indoor(world, place)
    light = _light(tod, indoor, weather)
    name = place.name if place else place_id
    ambiance = getattr(place, "ambiance", None) or _default_ambiance(place)
    desc = (f"{SEASON_RU[season].capitalize()}, {TIME_RU.get(tod, tod)}. "
            f"{_weather_phrase(weather, indoor, intensity, wind).capitalize()}. {ambiance}")
    return SceneContext(day_number(tick), season, tod, world.clock.hhmm(), weather,
                        indoor, light, name, ambiance, desc, intensity=intensity, wind=wind)


def _default_ambiance(place) -> str:
    kind = place.kind if place else ""
    affs = set(getattr(place, "affordances", []) or []) if place else set()
    if "inn" in affs:
        return "В общем зале тепло, пахнет элем и дымом очага."
    if "shop" in affs:
        return "Полки уставлены товаром, пахнет кожей и пылью."
    if "shrine" in affs:
        return "Тихо горят свечи, воздух пропитан благовониями."
    if "hideout" in affs or "manor" in affs:
        return "Сырые каменные стены, эхо шагов, запах плесени."
    if kind == "site" or "combat" in affs:
        return "Сырая каменная пещера, где-то капает вода."
    if kind == "room":
        return "Просторная площадь, утоптанная земля под ногами."
    return "Вокруг привычная обстановка."


# --------------------------------------------------------------------------- #
#  Механические эффекты погоды/освещения (док 07 §6 — заводятся в проверки).   #
#  Бой НЕ трогаем (P0): ranged_adv отдаётся арбитру/нарратору как заметка.     #
# --------------------------------------------------------------------------- #
@dataclass
class EnvEffects:
    visibility: str             # normal | reduced | poor
    perception_adv: int         # зрительное восприятие (поиск/заметить)
    stealth_adv: int            # укрытие шумом/мглой
    survival_adv: int           # чтение следов
    ranged_adv: int             # дальний бой (нарратору/арбитру; в бросок атаки НЕ вшито)
    flame_dc: int               # надбавка к DC розжига открытого огня
    travel_mult: float          # множитель времени перехода дикими землями
    note: str                   # краткая RU-сводка эффектов для нарратора/арбитра

    def to_dict(self) -> dict:
        return {"visibility": self.visibility, "perception_adv": self.perception_adv,
                "stealth_adv": self.stealth_adv, "survival_adv": self.survival_adv,
                "ranged_adv": self.ranged_adv, "flame_dc": self.flame_dc,
                "travel_mult": self.travel_mult, "note": self.note}


def _effects_note(vis: str, surv: int, ranged: int, flame: int) -> str:
    parts = []
    if vis == "poor":
        parts.append("видимость скверная")
    elif vis == "reduced":
        parts.append("видимость снижена")
    if ranged < 0:
        parts.append("дальний бой затруднён")
    if surv > 0:
        parts.append("следы чётко видны на снегу")
    elif surv < 0:
        parts.append("следы размывает")
    if flame >= 4:
        parts.append("развести открытый огонь трудно")
    return ("Погодные эффекты: " + ", ".join(parts) + ".") if parts else ""


def effects(scene: SceneContext) -> EnvEffects:
    """Чистая функция сцена → игромеханические модификаторы. Детерминирована."""
    w, i, wind, light = scene.weather, scene.intensity, scene.wind, scene.light
    if scene.indoor:                                  # погода «за окнами» — почти без эффекта
        vis = "poor" if light == "dark" else "normal"
        return EnvEffects(vis, -1 if vis == "poor" else 0, 1 if vis == "poor" else 0,
                          0, 0, 0, 1.0, "темно — видимость скверная." if vis == "poor" else "")
    poor = ((w == "fog" and i == "heavy") or w == "storm"
            or (w == "snow" and i == "heavy") or light == "dark")
    reduced = (not poor) and (w in ("fog", "rain", "snow") or light == "dim")
    vis = "poor" if poor else ("reduced" if reduced else "normal")
    perception_adv = -1 if poor else 0
    stealth_adv = 1 if (poor or (w in ("rain", "storm") and i in ("moderate", "heavy"))) else 0
    if w == "snow" and i in ("light", "moderate"):
        survival_adv = 1                              # свежий снег держит след
    elif (w == "rain" and i == "heavy") or w == "storm":
        survival_adv = -1                             # ливень смывает
    else:
        survival_adv = 0
    ranged_adv = -1 if (w in ("fog", "storm") or wind == "strong"
                        or (w in ("rain", "snow") and i == "heavy")) else 0
    flame_dc = (6 if w == "storm"
                else 4 if (w in ("rain", "snow") and i == "heavy")
                else 2 if ((w in ("rain", "snow") and i == "moderate") or wind == "strong")
                else 0)
    travel_mult = (1.5 if w == "storm"
                   else 1.3 if (w in ("rain", "snow") and i == "heavy")
                   else 1.15 if w in ("rain", "snow", "fog")
                   else 1.0)
    return EnvEffects(vis, perception_adv, stealth_adv, survival_adv, ranged_adv,
                      flame_dc, travel_mult, _effects_note(vis, survival_adv, ranged_adv, flame_dc))


_SIGHT_SKILLS = {"perception", "investigation"}


def check_advantage(scene: SceneContext, *, skill: str | None = None, ranged: bool = False) -> int:
    """Дельта advantage (+1/0/−1) от погоды/света для проверки навыка или дальнего боя."""
    e = effects(scene)
    if ranged:
        return e.ranged_adv
    s = (skill or "").lower()
    if s == "stealth":
        return e.stealth_adv
    if s == "survival":
        return e.survival_adv
    if s in _SIGHT_SKILLS:
        return e.perception_adv
    return 0
