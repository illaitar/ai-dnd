"""Система погоды: детерминизм/replay, внутрисуточная динамика, инерция день-к-дню,
механические эффекты (видимость/скрытность/выслеживание/дальний/огонь/перемещение) и
их проводка в проверки навыков."""

from aidnd import config
from aidnd.bootstrap import new_session
from aidnd.world import environment as E

PER_DAY = (24 * 60) // config.SIM_MINUTES_PER_TICK
REG = "region:phandalin"


def _scene(w, i="moderate", wind="calm", light="bright", indoor=False):
    return E.SceneContext(1, "autumn", "day", "13:00", w, indoor, light,
                          "X", "", w, intensity=i, wind=wind)


# --- детерминизм / replay-safe ------------------------------------------- #
def test_weather_is_deterministic_per_tick():
    t = 3 * PER_DAY + 30
    assert E.weather_of(1337, t, REG, "autumn") == E.weather_of(1337, t, REG, "autumn")
    # другой сид — в общем случае другая погода (хотя бы где-то по последовательности)
    a = [E._day_weather(1337, d, REG, E.season_of_day(d)) for d in range(20)]
    b = [E._day_weather(42, d, REG, E.season_of_day(d)) for d in range(20)]
    assert a != b


def test_intraday_variation_exists():
    """Где-то на горизонте утро отличается от дня (внутрисуточный сдвиг работает)."""
    diffs = 0
    for d in range(40):
        morn = E.weather_of(1337, d * PER_DAY + 6 * 6, REG, E.season_of_day(d))
        day = E.weather_of(1337, d * PER_DAY + 13 * 6, REG, E.season_of_day(d))
        diffs += morn != day
    assert diffs > 0


def test_day_to_day_inertia():
    """Инерция: соседние дни иногда совпадают (не чистый шум)."""
    seq = [E._day_weather(1337, d, REG, E.season_of_day(d)) for d in range(60)]
    repeats = sum(seq[i] == seq[i - 1] for i in range(1, len(seq)))
    assert repeats >= 10           # при инерции 0.45 повторов заметно больше нуля


# --- эффекты -------------------------------------------------------------- #
def test_clear_weather_has_no_penalties():
    e = E.effects(_scene("clear", "none"))
    assert e.visibility == "normal" and e.perception_adv == 0 and e.ranged_adv == 0
    assert e.travel_mult == 1.0 and e.flame_dc == 0 and e.note == ""


def test_fog_obscures_sight_and_aids_stealth():
    e = E.effects(_scene("fog", "heavy"))
    assert e.visibility == "poor"
    assert e.perception_adv == -1 and e.stealth_adv == 1 and e.ranged_adv == -1


def test_storm_penalises_ranged_fire_and_travel():
    e = E.effects(_scene("storm", "heavy", "strong"))
    assert e.ranged_adv == -1 and e.flame_dc > 0 and e.travel_mult > 1.0


def test_fresh_snow_helps_tracking():
    assert E.effects(_scene("snow", "light")).survival_adv == 1
    assert E.effects(_scene("rain", "heavy")).survival_adv == -1    # ливень смывает след


def test_indoor_weather_is_neutral():
    e = E.effects(_scene("storm", "heavy", "strong", indoor=True))
    assert e.travel_mult == 1.0 and e.ranged_adv == 0 and e.visibility == "normal"


def test_check_advantage_maps_skills():
    fog = _scene("fog", "heavy")
    assert E.check_advantage(fog, skill="perception") == -1
    assert E.check_advantage(fog, skill="stealth") == 1
    assert E.check_advantage(_scene("storm", "heavy", "strong"), ranged=True) == -1
    assert E.check_advantage(_scene("snow", "light"), skill="survival") == 1
    assert E.check_advantage(fog, skill="persuasion") == 0          # соц.навык — без эффекта


def test_scene_dict_exposes_weather_fields():
    d = _scene("rain", "heavy").to_dict()
    assert d["weather"] == "rain" and d["intensity"] == "heavy"
    assert "effects" in d and d["effects"]["ranged_adv"] == -1


# --- проводка в проверку навыка ------------------------------------------ #
def test_env_adv_flows_into_check_request():
    s = new_session(seed=1337, roster_size=4, use_model=False)
    base = s.rules.build_check_request(s.player, "stealth", 12, kind="skill")
    worse = s.rules.build_check_request(s.player, "stealth", 12, kind="skill", env_adv=-1)
    better = s.rules.build_check_request(s.player, "stealth", 12, kind="skill", env_adv=1)
    assert worse.advantage == base.advantage - 1
    assert better.advantage == min(1, base.advantage + 1)
