"""ФАЗА 1-2 граф-мозга (MODULARBRAIN): вектор УРДЖЕЙ поверх нужд + ШИНА МОДУЛЯТОРОВ.

Урдж (Бах/PSI): urge_d = |set−cur| (у нас set=0 → «хочу низко» → urge = уровень нужды), urgency
растёт к критическому. Модуляторы — 6 глобальных ручек из урджей+эмоций+черт (arousal/valence/
dominance/resolution/selection_threshold/securing). Это МЕХАНИЗМ СИСТЕМНОСТИ: одна ручка пронизывает
все узлы, поэтому голод перекрашивает даже торговлю без правила «если голоден в торговле».

НЕЙТРАЛЬНО при базовом состоянии (нужды≈0.2, эмоции 0, черты 0.5 → arousal≈valence≈…≈0.5), поэтому
подключение к скору (brain.modulate) не сдвигает поведение в норме — только под давлением.
"""

from __future__ import annotations

from .goals import NEED_WEIGHT


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def urges(state) -> dict:
    """На каждую нужду: urge (насколько не удовлетворена) + urgency (близость к критическому) + приоритет."""
    out = {}
    for nd, cur in state.needs.items():
        urgency = _clamp(cur / (1.05 - cur), 0.0, 1.5)          # к cur→1 срочность взлетает
        w = state.config.traits.get(NEED_WEIGHT[nd], 0.5) + 0.5 if nd in NEED_WEIGHT else 1.0
        out[nd] = {"urge": cur, "urgency": urgency, "priority": cur * w}
    return out


def _lead(urg: dict) -> dict:
    return max(urg.values(), key=lambda u: u["priority"]) if urg else {"urge": 0, "urgency": 0, "priority": 0}


def modulators(state) -> dict:
    """6 глобальных модуляторов + служебные поля (ведущий мотив, max срочность)."""
    t, e, urg = state.config.traits, state.emotion, urges(state)
    lead = _lead(urg)
    max_urgency = min(1.0, max((u["urgency"] for u in urg.values()), default=0.0))
    mean_urge = sum(u["urge"] for u in urg.values()) / max(1, len(urg))
    anger, fear = e.get("anger", 0.0), e.get("fear", 0.0)
    joy, distress = e.get("joy", 0.0), e.get("distress", 0.0)
    irr = t.get("irritability", 0.5)

    arousal = _clamp(0.15 + 0.5 * irr + 0.45 * max_urgency + 0.4 * (anger + fear))
    valence = _clamp(0.55 + 0.5 * (joy - distress) - 0.3 * mean_urge)
    dominance = _clamp(0.5 + 0.5 * (t.get("bravery", .5) - .5) + 0.25 * (t.get("pride", .5) - .5)
                       + 0.3 * anger - 0.35 * fear)
    resolution = _clamp(0.62 - 0.4 * max_urgency + 0.2 * (t.get("curiosity", .5) - .5))
    selection_threshold = _clamp(0.3 + 0.4 * min(1.0, lead["priority"] / 1.5)
                                 + 0.2 * ((t.get("pride", .5) + t.get("ambition", .5)) / 2 - .5)
                                 - 0.2 * (irr - .5))
    securing = _clamp(0.4 + 0.6 * (t.get("curiosity", .5) - .5) + 0.3 * urg.get("novelty", {}).get("urge", 0)
                      - 0.3 * min(1.0, lead["priority"] / 1.5))
    return {"arousal": arousal, "valence": valence, "dominance": dominance,
            "resolution": resolution, "selection_threshold": selection_threshold, "securing": securing,
            "_lead": lead, "_max_urgency": max_urgency}


# что толкнуло модулятор (для панели «стрелки влияния» в дебаге)
DRIVERS = {
    "arousal": "нужды(срочность) + гнев/страх + вспыльчивость",
    "valence": "радость−подавленность − давление нужд",
    "dominance": "храбрость + гордость + гнев − страх / (сила vs цель)",
    "resolution": "падает под срочностью (спешка = грубее счёт)",
    "selection_threshold": "сила ведущего мотива + гордость/амбиции (упорство)",
    "securing": "любопытство + новизна − фокус на мотиве (внимание наружу)",
}
