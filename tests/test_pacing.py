"""Нарративный темп: при затишье и подходящей обстановке режиссёр повышает
вероятность случайного события. Вид события — под локацию (опасная глушь → угроза/
находка, людное → встреча/фон). Плюс взаимодействие с окружением (аффордансы)."""

from aidnd.bootstrap import new_session


def _sess(seed=0):
    return new_session(seed=seed, roster_size=4, use_model=False)


def _at(s, place):
    s.world.commit("set_position", "pc:hero", target="pc:hero",
                   payload={"region": "region:phandalin", "place": place})


# --- вероятность темпа (чистая функция режиссёра) -------------------------- #
def test_pacing_probability_gate_and_ramp():
    from aidnd.runtime.director import PACING_CAP, QUIET_GATE
    d = _sess().director
    for q in range(QUIET_GATE):                               # до порога затишья — тишина
        assert d.pacing_probability("dungeon", q) == 0.0
    p_lo, p_mid, p_hi = (d.pacing_probability("dungeon", q)
                         for q in (QUIET_GATE, QUIET_GATE + 1, QUIET_GATE + 5))
    assert 0 < p_lo < p_mid                                   # после порога растёт
    assert p_mid <= p_hi <= PACING_CAP                        # дальше упирается в потолок


def test_pacing_location_permissiveness_ordering():
    """Обстановка решает: глушь живее людного безопасного, святилище — тише всех."""
    d = _sess().director
    q = 6
    assert (d.pacing_probability("dungeon", q) > d.pacing_probability("market", q)
            > d.pacing_probability("shrine", q))


# --- интеграция: затишье в глуши рождает события ---------------------------- #
def test_resting_in_wilds_surfaces_threat_class_events():
    s = _sess()
    _at(s, "place:wyvern_tor")                                # site → «dungeon»-класс
    events = [s.handle("ждать").get("ambient_event") for _ in range(14)]
    fired = [e for e in events if e]
    assert fired, "за 14 привалов в глуши не случилось ни одного события"
    assert all(e["event"] in ("threat", "find", "ambient") for e in fired)
    assert any(e["event"] == "threat" for e in fired)         # опасность ощутима


def test_town_pacing_is_social_not_threat():
    """В людном безопасном месте события мягкие — встреча/фон, без угроз."""
    s = _sess()                                               # старт в таверне (market)
    fired = [e for e in (s.handle("ждать").get("ambient_event") for _ in range(14)) if e]
    assert fired
    assert all(e["event"] in ("company", "ambient") for e in fired)
    assert not any(e["event"] == "threat" for e in fired)


# --- гейты: затишья нет / занят / событие сбрасывает счётчик ---------------- #
def test_single_quiet_glance_below_gate_has_no_beat():
    s = _sess()
    r = s.handle("осмотреться")                               # quiet=1 < порога
    assert r.get("ambient_event") is None


def test_eventful_action_resets_quiet_and_injects_nothing():
    s = _sess()
    s.handle("ждать"); s.handle("ждать")                      # накопили затишье
    r = s.handle("идти на площадь")                           # перемещение — событие
    assert r.get("ambient_event") is None and s.quiet_ticks == 0


def test_pacing_is_deterministic():
    def run():
        s = _sess(); _at(s, "place:wyvern_tor")
        return [s.handle("ждать").get("ambient_event", {} ).get("text") for _ in range(8)]
    assert run() == run()


# --- взаимодействие с окружением (аффордансы) ------------------------------- #
def test_affordances_surface_in_look():
    s = _sess()                                               # таверна «Каменный Холм»
    labels = [a["label"] for a in s.affordances_here()]
    assert "отдохнуть и перекусить" in labels and "выпить" in labels
    look = s.look()                                           # осмотр лаконичен: аффордансы — чипами (actions), не стеной текста
    assert {a["label"] for a in look["actions"]} >= {"отдохнуть и перекусить", "выпить"}
    assert "«Постоялый двор «Каменный Холм»»" in look["text"]  # локация есть
    assert "Можно:" not in look["text"] and "человек" not in look["text"]  # без списка действий и счёта толпы


def test_affordances_change_with_place():
    s = _sess()
    _at(s, "building:shrine_of_luck")
    assert any(a["affordance"] == "shrine" for a in s.affordances_here())
