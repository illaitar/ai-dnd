"""Физический контекст сцены: детерминизм сезона/погоды, помещение (read-model)."""

from aidnd.content import build_world
from aidnd.world import environment as env


def test_season_cycles_over_days():
    # старт — осень; через сезон (28 дней) → зима
    per_day = (24 * 60) // 10
    assert env.season_of(0) == "autumn"
    assert env.season_of(per_day * 28) == "winter"
    assert env.season_of(per_day * 28 * 4) == "autumn"   # полный год


def test_weather_deterministic_per_day_and_seed():
    w1 = env.weather_of(1337, 0, "region:phandalin", "autumn")
    w2 = env.weather_of(1337, 0, "region:phandalin", "autumn")
    assert w1 == w2                                       # тот же сид/день → та же погода
    assert w1 in env.SEASON_WEATHER["autumn"]
    # другой сид — обычно другая погода (хотя бы по диапазону валидна)
    assert env.weather_of(999, 0, "region:phandalin", "autumn") in env.SEASON_WEATHER["autumn"]


def test_winter_can_snow_but_summer_cannot():
    assert "snow" in env.SEASON_WEATHER["winter"]
    assert "snow" not in env.SEASON_WEATHER["summer"]


def test_indoor_vs_outdoor():
    w = build_world(seed=1337, roster_size=2)
    inn = w.spatial.places["building:stonehill_inn"]
    square = w.spatial.places["place:phandalin_square"]
    assert env.is_indoor(w, inn) is True            # трактир — укрытие
    assert env.is_indoor(w, square) is False        # площадь — под открытым небом


def test_scene_context_reproducible_and_fields():
    w = build_world(seed=1337, roster_size=2)
    sc1 = env.scene_context(w, "building:stonehill_inn")
    sc2 = env.scene_context(w, "building:stonehill_inn")
    assert sc1.to_dict() == sc2.to_dict()
    assert sc1.season in env.SEASONS and sc1.descriptor
    assert sc1.indoor is True
