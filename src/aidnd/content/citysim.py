"""Городская симуляция как stateful ABM: у каждого жителя живое состояние (место, нужды, путь),
которое эволюционирует тик за тиком. Никаких жёстких расписаний — поведение ЭМЕРДЖЕНТНО из нужд + времени
суток + притягательности мест.

Нужды: энергия (падает бодрствуя, копится дома-сном), голод и тяга к общению (растут, гасятся в тавернах/на
людях). Решение — по ПОЛЕЗНОСТИ места: привлекательность(час) + насколько закрывает текущую нужду + якорь
дом/работа + инерция − дорога. Лучшее место ≠ текущему → идёт туда (транзит занимает время).

Детерминировано по seed (реплей-сейф), состояние компактное (персистится), догоняет пропущенные тики.
Один движок и для геймплея (present_at/place_of), и для визуализации (позиции по времени).
"""

from __future__ import annotations

import math
import random
import zlib


def _h(s) -> int:
    """Стабильный хеш строки (встроенный hash() рандомизируется по процессам → ломал бы сейв/лоад)."""
    return zlib.crc32(str(s).encode())


# НУЖДЫ (все: растут → хочется удовлетворить): усталость (гасится дома-сном), голод, тяга к общению.
NEEDS = ("fatigue", "hunger", "social")
HOME = None                                   # «дома/за городом» — не игровое место

# профиль типа места: какие нужды гасит (sat), базовая тяга, и когда пик (для множителя по часу)
PROFILE = {
    "inn":    {"sat": {"hunger": 0.45, "social": 0.45}, "draw": 1.0, "peak": "evening"},
    "tavern": {"sat": {"hunger": 0.35, "social": 0.55}, "draw": 1.0, "peak": "evening"},
    "shop":   {"sat": {"hunger": 0.30}, "draw": 0.7, "peak": "day"},     # работа кормит, но общения не даёт — к вечеру тянет в люди
    "shrine": {"sat": {"social": 0.25}, "draw": 0.45, "peak": "day"},
    "square": {"sat": {"social": 0.45}, "draw": 0.7, "peak": "day"},
    "work":   {"sat": {}, "draw": 0.95, "peak": "work"},        # работа: тянет в часы, нужд не гасит
    "home":   {"sat": {"fatigue": 0.6}, "draw": 0.85, "peak": "night"},   # дом гасит усталость (сон)
}


def _bell(h: float, c: float, w: float) -> float:
    return math.exp(-((h - c) ** 2) / (2 * w * w))


def _time_mult(peak: str, minute: int) -> float:
    h = minute / 60.0
    if peak == "evening":
        return 0.35 + 1.7 * _bell(h, 20, 3.2) + 0.7 * _bell(h, 13, 1.4)   # вечерний пик + обед
    if peak == "day":
        return 0.30 + 1.3 * _bell(h, 13.5, 3.6)
    if peak == "work":
        return 0.15 + 1.9 * (1.0 if 7 <= h < 18 else 0.0)
    if peak == "night":
        return 0.45 + 1.6 * (1.0 - (1.0 if 7 <= h < 22 else 0.0))
    return 0.6


def phase(minute: int) -> str:
    h = minute / 60.0
    return "night" if (h < 6 or h >= 22) else "morning" if h < 11 else "day" if h < 18 else "evening"


class CitySim:
    def __init__(self, places: dict, agents: list, seed: int, mpt: int = 10):
        """places: {place_id: {"kind": str, "xy": (x,y)|None}} — публичные игровые места.
        agents:  [{"id", "home_xy"(viz)|None, "home_place"(gameplay)|None, "work"(place_id)|None}]."""
        self.seed = seed
        self.mpt = mpt
        self.places = places
        self.kind = {pid: p.get("kind", "") for pid, p in places.items()}
        self.tick = 0
        self.agents: dict[str, dict] = {}
        for a in agents:
            rng = random.Random((seed ^ _h(a["id"])) & 0xFFFFFFFF)
            self.agents[a["id"]] = {
                "id": a["id"], "home_xy": a.get("home_xy"), "home_place": a.get("home_place"),
                "work": a.get("work"), "place": a.get("home_place"),   # стартуют дома (отдохнувшие)
                "needs": {"fatigue": rng.uniform(0.0, 0.3), "hunger": rng.uniform(0.0, 0.3),
                          "social": rng.uniform(0.0, 0.3)},
                "rate": {"fatigue": rng.uniform(0.010, 0.018), "hunger": rng.uniform(0.012, 0.020),
                         "social": rng.uniform(0.008, 0.016)},
                # «сова»: ночная натура — поздние гуляки, неспящие, ранние пекари (малая доля сильно ночных)
                "owl": round(rng.uniform(0.6, 1.0), 2) if rng.random() < 0.04 else 0.0,
                "transit": None, "noise": rng.uniform(0.0, 1.0),
            }

    # --- эволюция нужд за один тик ----------------------------------------- #
    @staticmethod
    def _evolve(a: dict, resting: bool, working: bool, sat: dict):
        n, r = a["needs"], a["rate"]
        if resting:                                                        # дома вне работы — сон/отдых
            n["fatigue"] = max(0.0, n["fatigue"] - r["fatigue"] * 2.2)     # усталость спадает
            n["hunger"] = min(1.0, n["hunger"] + r["hunger"] * 0.5)
            n["social"] = min(1.0, n["social"] + r["social"] * 0.4)
        else:
            n["fatigue"] = min(1.0, n["fatigue"] + r["fatigue"] * (1.6 if working else 1.0))  # устаёт
            n["hunger"] = min(1.0, n["hunger"] + r["hunger"])
            n["social"] = min(1.0, n["social"] + r["social"])
        for need, amt in (sat or {}).items():                              # место гасит нужды (еда/общение)
            n[need] = max(0.0, n[need] - amt)

    # --- полезность места для агента --------------------------------------- #
    # «дом» агента = a["home_place"]: для заглушек None (за городом), для ростера здание-резиденция.
    def _utility(self, a: dict, place, minute: int) -> float:
        is_home = (place == a["home_place"])
        is_work = (place is not None and place == a["work"])
        kinds = set()                                                      # место может быть и домом, и работой
        if is_work:
            kinds.add("work")
        if is_home:
            kinds.add("home")
        pk = self.kind.get(place, "")                                      # тип места учитываем ВСЕГДА:
        if pk:                                                             # инн даёт social и своему хозяину (иначе уходит)
            kinds.add(pk)
        if not kinds:
            kinds.add("")
        best = -1e9
        for kind in kinds:                                                 # берём лучший подходящий профиль
            prof = PROFILE.get(kind, {"sat": {}, "draw": 0.4, "peak": ""})
            s = prof["draw"] * _time_mult(prof["peak"], minute)
            for need, amt in prof["sat"].items():                          # закрывает горящую нужду — ценно
                nv = a["needs"][need]
                s += nv * amt * 3.0
                if nv > 0.65:                                              # ГОРЯЩАЯ нужда тянет к утолителю
                    s += (nv - 0.65) * amt * 8.0                           # поверх инерции дома/работы (иначе сидят сиднем)
            best = max(best, s)
        u = best
        burn = max(0.0, max(a["needs"].values()) - 0.65) / 0.35            # 0 при ≤0.65, 1 при нужде 1.0
        stay = 1.0 - 0.55 * burn                                           # «держащие» бонусы слабеют, когда нужда горит
        if is_home:
            u += 0.4 * stay                                                # свой дом (но не держит, когда гонит нужда)
        if is_work:
            u += 0.5 * stay                                                # свой труд
        if place == a["place"]:
            u += 0.9 * stay                                                # инерция — не дёргаться без повода
        if a["owl"] and phase(minute) == "night":                          # ночная натура: не домой, а наружу —
            if not (is_home and self.kind.get(place, "") in ("inn", "tavern")):   # но если ДОМ и есть ночная жизнь
                u += (-2.4 if is_home else 1.3) * a["owl"]                  # (трактир), не гнать хозяина прочь
        return u

    def _decide(self, a: dict, minute: int):
        seen, uniq = set(), []
        for c in [a["home_place"], a["work"], *self.places.keys()]:        # кандидаты: дом, работа, публичные
            if c in seen:
                continue
            if c is None and a["home_place"] is not None:                  # None = «за городом» только у заглушек
                continue
            if c is None or c == a["home_place"] or c == a["work"] or c in self.places:
                seen.add(c)
                uniq.append(c)
        rng = random.Random((self.seed ^ _h(a["id"]) ^ self.tick) & 0xFFFFFFFF)
        best, bestu = a["place"], -1e9
        for c in uniq:
            u = self._utility(a, c, minute) + rng.uniform(0.0, 0.5)        # лёгкий шум — разнообразие
            if u > bestu:
                best, bestu = c, u
        return best

    # --- шаг тика ----------------------------------------------------------- #
    def _step(self, a: dict, minute: int):
        tr = a["transit"]
        if tr:
            self._evolve(a, resting=False, working=False, sat={})          # в пути — тратит силы
            if self.tick >= tr["arrive"]:
                a["place"] = tr["to"]
                a["transit"] = None
            return
        at_home = (a["place"] == a["home_place"])
        at_work = (a["place"] is not None and a["place"] == a["work"])
        working = at_work and 7 <= minute // 60 < 18                       # на работе в рабочие часы — устаёт
        resting = at_home and not working                                  # дома вне работы — отдыхает
        psat = PROFILE.get(self.kind.get(a["place"], ""), {}).get("sat", {})
        if resting:                                                        # дома отдыхаешь; если дом людный (инн) —
            soc = psat.get("social")                                       # компания всё же гасит тоску (хозяин не уходит)
            sat = {"social": soc * 0.6} if soc else {}
        else:
            sat = psat
        self._evolve(a, resting, working, sat)
        dest = self._decide(a, minute)
        if dest != a["place"]:                                            # решил идти — в путь (займёт время)
            a["transit"] = {"from": a["place"], "to": dest, "start": self.tick,
                            "arrive": self.tick + 1 + (1 if a["noise"] < 0.5 else 2)}

    def advance(self, to_tick: int, cap: int = 300):
        """Догнать симуляцию до to_tick. При огромном скачке (load/долгий отдых) симулируем ХВОСТ окна
        (~2 суток прогрева до цели) — нужды циклятся за сутки, этого хватает на верный устойчивый расклад."""
        if to_tick <= self.tick:
            return
        if to_tick - self.tick > cap:                                     # промотать древнее, прогреть хвост
            self.tick = to_tick - cap
        while self.tick < to_tick:
            self.tick += 1
            minute = (self.tick * self.mpt) % 1440
            for a in self.agents.values():
                self._step(a, minute)

    # --- запросы ------------------------------------------------------------ #
    def present_at(self, place: str) -> list:
        return [aid for aid, a in self.agents.items() if a["transit"] is None and a["place"] == place]

    def place_of(self, aid: str):
        a = self.agents.get(aid)
        return None if not a or a["transit"] else a["place"]

    def in_transit(self, aid: str) -> bool:
        a = self.agents.get(aid)
        return bool(a and a["transit"])

    def xy_at(self, aid: str, place_xy):
        """Позиция для визуализации: место→xy (+джиттер), дома→home_xy, в пути→интерполяция."""
        a = self.agents[aid]
        jx = ((_h(aid) % 13) - 6) * 1.3
        jy = ((_h(aid) // 13 % 13) - 6) * 1.3
        tr = a["transit"]
        if tr:
            pa = place_xy(tr["from"], a)
            pb = place_xy(tr["to"], a)
            f = min(1.0, max(0.0, (self.tick - tr["start"]) / max(1, tr["arrive"] - tr["start"])))
            return (pa[0] + (pb[0] - pa[0]) * f, pa[1] + (pb[1] - pa[1]) * f)
        x, y = place_xy(a["place"], a)
        return (x + jx, y + jy)
