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

    def to_dict(self) -> dict:
        return {"day": self.day, "season": self.season, "season_ru": SEASON_RU[self.season],
                "time_of_day": self.time_of_day, "time_ru": TIME_RU.get(self.time_of_day, ""),
                "hhmm": self.hhmm, "weather": self.weather,
                "weather_ru": WEATHER_RU.get(self.weather, self.weather),
                "indoor": self.indoor, "light": self.light, "place_name": self.place_name,
                "ambiance": self.ambiance, "descriptor": self.descriptor}


def day_number(tick: int) -> int:
    per_day = (24 * 60) // config.SIM_MINUTES_PER_TICK
    return tick // per_day


def season_of(tick: int) -> str:
    d = day_number(tick)
    base = SEASONS.index(config.START_SEASON) if config.START_SEASON in SEASONS else 2
    return SEASONS[(base + d // config.DAYS_PER_SEASON) % 4]


def weather_of(world_seed: int, tick: int, region: str, season: str) -> str:
    rng = random.Random(f"{world_seed}|{day_number(tick)}|{region}|weather")
    weights = SEASON_WEATHER[season]
    items = list(weights.items())
    total = sum(w for _, w in items)
    r = rng.random() * total
    acc = 0.0
    for k, w in items:
        acc += w
        if r <= acc:
            return k
    return items[-1][0]


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


def _weather_phrase(weather: str, indoor: bool) -> str:
    out = {
        "clear": "небо ясное", "cloudy": "небо затянуто облаками",
        "rain": "идёт дождь", "fog": "стелется туман", "snow": "падает снег",
        "storm": "бушует гроза", "windy": "налетает порывистый ветер",
    }.get(weather, WEATHER_RU.get(weather, weather))
    return ("снаружи " + out) if indoor else out


def scene_context(world, place_id: str) -> SceneContext:
    tick = world.clock.tick
    season = season_of(tick)
    tod = world.clock.time_of_day()
    place = world.spatial.places.get(place_id)
    region = place.parent if place else "region:phandalin"
    weather = weather_of(world.seed, tick, region or "region", season)
    indoor = is_indoor(world, place)
    light = _light(tod, indoor, weather)
    name = place.name if place else place_id
    ambiance = getattr(place, "ambiance", None) or _default_ambiance(place)
    desc = (f"{SEASON_RU[season].capitalize()}, {TIME_RU.get(tod, tod)}. "
            f"{_weather_phrase(weather, indoor).capitalize()}. {ambiance}")
    return SceneContext(day_number(tick), season, tod, world.clock.hhmm(), weather,
                        indoor, light, name, ambiance, desc)


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
