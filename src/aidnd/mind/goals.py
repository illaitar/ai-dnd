"""Цели = ЖЕЛАЕМЫЕ ИСХОДЫ с ценностью (не планы и не шаги). Каждый тик формируются из восприятия:
стоячие (нужды) + возможности (богатая цель рядом → завладеть; угроза → уцелеть; союзник в беде →
защитить; неопределённость о ценном → разузнать). payoff каждой считается в value.py из черт/эмоций.

Здесь НЕТ скриптов поведения — только «что ценно сейчас». Как добиваться — решит utility над
общими примитивами. Формирование НОВОЙ ситуативной цели — место для LLM (помечено), но базовый
набор выводится механически, чтобы стенд был детерминирован и проверяем.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .value import _is_ally, hostility
from .world import Item  # noqa: F401  (используется вызывающими сценариями)

# вес нужды = насколько НПЦ вообще движим этой нуждой (черта усиливает)
NEED_WEIGHT = {"social": "sociability", "purpose": "ambition",
               "wealth": "greed", "novelty": "curiosity"}


@dataclass
class Goal:
    kind: str                       # acquire | safe | trade | affiliate | protect | inform | need
    target: str | None = None       # id тела / имя нужды / тема
    value: float = 0.0              # сырой payoff до масштабирования чертой (в value.py)
    meta: dict = field(default_factory=dict)

    def label(self) -> str:
        return f"{self.kind}:{self.target}={round(self.value, 2)}"


def standing_needs(state) -> list:
    """Стоячие цели из нужд — payoff = уровень·вес черты."""
    out = []
    for nd, lvl in state.needs.items():
        w = state.config.traits.get(NEED_WEIGHT[nd], 0.5) + 0.5 if nd in NEED_WEIGHT else 1.0
        val = lvl * w
        if val > 0.08:
            meta = dict(state.needs_sources.get(nd, {})) if hasattr(state, "needs_sources") else {}
            out.append(Goal("need", nd, val, meta))
    return out


def _agenda_goals(state) -> list:
    """Долгосрочные цели → механическая цель ТЕКУЩЕЙ вехи (её ядро тянет реактивно). Гейты формирования
    не применяются: планировщик уже решил, что это цель (мирный может мстить, скромный — копить)."""
    out = []
    for ag in getattr(state, "agendas", None) or []:
        if getattr(ag, "status", "") != "active":
            continue
        m = ag.current()
        if not m:
            continue
        meta = dict(m.meta)
        meta["agenda"] = ag.summary
        out.append(Goal(m.kind, m.target, ag.importance, meta))
    return out


def propose_goals(state, world, percept) -> list:
    """Полный набор целей-кандидатов на этот тик. Ничего не «выбирает» — выбор делает utility."""
    me = percept.me
    goals = list(getattr(state, "extra_goals", []))      # сценарии могут подложить trade/affiliate/inform
    goals += _agenda_goals(state)                        # долгосрочные цели (планировщик)
    goals += standing_needs(state)

    # ОСТРАЯ угроза — только со-локация (враг в лицо → бегство); дальнего врага обходят (риск узла)
    danger, threat_id = 0.0, None
    for b in percept.present:
        h = hostility(state, me, b)
        if h > danger:
            danger, threat_id = h, b.id
    safe_val = max(state.emotion.get("fear", 0.0), danger)
    if safe_val > 0.08 and threat_id:
        goals.append(Goal("safe", threat_id, safe_val))

    # возможность завладеть — НЕ у всех: только при хищной СКЛОННОСТИ и на реально стоящей цели.
    # Обычный горожанин (честный/законопослушный) не «прикидывает ограбить» соседа — цель не рождается.
    tr = state.config.traits
    predatory = tr.get("greed", 0.5) * (1 - tr.get("honesty", 0.5)) * (1 - 0.5 * tr.get("lawful", 0.5))
    malice = tr.get("malice", 0.5)
    for b in percept.present + percept.nearby:
        if b.id == me.id or _is_ally(state, b):
            continue
        if predatory > 0.30 and b.appearance > 0.25:        # ← LLM-апрейзал ценности подключится здесь
            goals.append(Goal("acquire", b.id, b.appearance))
        if malice > 0.6 and not b.down():                   # хищность — отдельная цель, не из жадности
            goals.append(Goal("harm", b.id, malice))

    # социальный заход: поговорить с присутствующим — закрыть соц-нужду ЧЕРЕЗ человека (не ресурс).
    # Тянет sociability × соц-нужда × (симпатия + ОБАЯНИЕ цели). Красота (charisma) ≠ богатство (appearance).
    # ТОЛПА у цели разбавляет тягу (все облепили «звезду» → остальные ищут собеседника рядом),
    # ВЗАИМНОСТЬ (он сейчас говорит со МНОЙ) усиливает — так складываются устойчивые пары беседы.
    soc = state.needs.get("social", 0.0)
    socbl = tr.get("sociability", 0.5)
    if soc > 0.12:
        for b in percept.present:
            if b.id == me.id or hostility(state, me, b) > 0.3 or b.down():
                continue
            aff = (state.relationships.get(b.id) or {}).get("affinity", 0.0)
            draw = soc * (0.3 + socbl) * (0.3 + 0.5 * max(0.0, aff) + 0.6 * getattr(b, "charisma", 0.3))
            suitors = sum(1 for ob in percept.present
                          if ob.id not in (me.id, b.id) and getattr(ob, "talking_to", None) == b.id)
            if getattr(b, "talking_to", None) == me.id:
                draw *= 1.6
            draw /= (1.0 + 0.5 * suitors)
            if draw > 0.12:
                goals.append(Goal("converse", b.id, min(1.0, draw)))

    # защита союзника: со-локация — союзник рядом, которого атакуют
    for b in percept.present:
        if not _is_ally(state, b):
            continue
        attacker = next((x for x in percept.present if x.attacking == b.id), None)
        if attacker:
            peril = attacker.power / (b.hp + 1e-9)
            goals.append(Goal("protect", b.id, min(1.1, 0.5 + 0.3 * peril),
                              {"attacker": attacker.id}))
    return goals
