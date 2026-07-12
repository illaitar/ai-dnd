"""Фреймер — 3 строки + апофения-валидатор: чужая сущность → отказ (как _build_step)."""
from aidnd.server.play.engine.quests import framing as F


def _seed():
    return {"sid": "seed_dunn_kindebt", "pattern": "kin_debt", "giver": "npc:dunn",
            "giver_name": "Дунн", "why": "тёплый крючок",
            "goal": {"done": {"type": "have", "item": "гроссбух"}},
            "cast": {"villain": "npc:ralf", "prize": "npc:marta"}}


ALLOWED = {"Дунн", "Марта", "Ральф", "гроссбух", "гильдия"}


def test_validator_accepts_only_known_entities():
    assert F.valid_entities("Верни Дунну гроссбух Марты от Ральфа", ALLOWED)
    assert not F.valid_entities("Найди Гундрена в руднике", ALLOWED)   # Гундрен ∉ allowed


class _Stub:
    def __init__(self, seq):
        self.seq, self.n = seq, 0

    def call(self, role, messages, **kw):
        out = self.seq[min(self.n, len(self.seq) - 1)]
        self.n += 1
        return {"content": out}


def test_framer_returns_three_valid_strings():
    good = ('{"pitch":"Чужак, верни гроссбух Марты — тридцать монет.",'
            '"foreshadow":"Тебя гложет долг Марты — гроссбух всё у Ральфа.",'
            '"reveal":"Ральф сам должен гильдии — его можно прижать."}')
    art = F.framer(_seed(), ALLOWED, _Stub([good]))
    assert set(art) == {"pitch", "foreshadow", "reveal"}
    assert "гроссбух" in art["pitch"]


def test_framer_regenerates_once_then_skips():
    bad = ('{"pitch":"Найди Гундрена","foreshadow":"Гундрен пропал",'
           '"reveal":"Гундрен в руднике"}')
    stub = _Stub([bad, bad])
    assert F.framer(_seed(), ALLOWED, stub) is None       # оба раза чужая сущность → None
    assert stub.n == 2                                     # ровно одна регенерация


def test_framer_regenerates_once_then_accepts():
    bad = ('{"pitch":"Найди Гундрена","foreshadow":"Гундрен пропал",'
           '"reveal":"Гундрен в руднике"}')
    good = ('{"pitch":"Верни гроссбух Марты.",'
            '"foreshadow":"Долг гложет — гроссбух у Ральфа.",'
            '"reveal":"Ральф должен гильдии."}')
    stub = _Stub([bad, good])
    art = F.framer(_seed(), ALLOWED, stub)
    assert art is not None and stub.n == 2                # одна регенерация → принято


def test_framer_no_manager_returns_none():
    assert F.framer(_seed(), ALLOWED, None) is None


def test_framer_artifacts_are_plain_strings_no_predicate_leak():
    good = ('{"pitch":"Верни гроссбух Марты.",'
            '"foreshadow":"Долг гложет — гроссбух у Ральфа.",'
            '"reveal":"Ральф должен гильдии."}')
    art = F.framer(_seed(), ALLOWED, _Stub([good]))
    for v in art.values():
        assert isinstance(v, str)
    assert set(art) == {"pitch", "foreshadow", "reveal"}   # no stray keys (predicates/numbers)
