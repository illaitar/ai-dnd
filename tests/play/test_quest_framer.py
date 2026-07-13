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


def test_validator_sentence_initial_is_not_a_free_pass():
    # "Гримберт" opens the sentence but isn't an opener and isn't allowed — must still be caught.
    assert not F.valid_entities("Гримберт ждёт тебя у моста.", set())
    assert F.valid_entities("Верни гроссбух Марты.", {"гроссбух", "Марта"})   # "Верни" ∈ openers
    assert F.valid_entities("Чужак, помоги.", set())                          # "Чужак" ∈ openers
    assert not F.valid_entities("Долг давит. Гримберт всё знает.", set())     # neither sentence is clean


def test_validator_quoted_phrase_requires_every_token_to_match():
    only_ledger = {"гроссбух"}
    assert not F.valid_entities("Верни «гроссбух и карта рудника»", only_ledger)   # "карта"/"рудника" unknown
    assert F.valid_entities("Верни «гроссбух Марты»", {"гроссбух", "Марта"})


def test_render_evidence_villain_less_seed_has_no_protiv_kto_to():
    """plain_need seeds carry cast.villain=None — the header must not read '... против кто-то'
    (that would misrepresent a seed with no antagonist at all)."""
    seed = {"sid": "seed_znah_plainneed", "pattern": "plain_need", "giver_name": "Знахарка Тэс",
            "cast": {"villain": None, "prize": None},
            "goal": {"done": {"type": "have", "item": "herbs"}},
            "evidence": ["agenda:npc:znah:0"]}
    text = F.render_evidence(seed, {}, {})
    assert "против" not in text
    assert "кто-то" not in text
    assert "Знахарка Тэс" in text and "herbs" in text


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
            '"foreshadow":"Тебя гложет долг — гроссбух у Ральфа.",'
            '"reveal":"Ральф должен гильдии."}')
    stub = _Stub([bad, good])
    art = F.framer(_seed(), ALLOWED, stub)
    assert art is not None and stub.n == 2                # одна регенерация → принято


def test_framer_no_manager_returns_none():
    assert F.framer(_seed(), ALLOWED, None) is None


def test_framer_rejects_raw_pid_leak():
    """Belt-and-suspenders: a raw internal id in the pitch is a hard reject even if it would
    otherwise pass the entity validator (live bug: «расквитаться с pool:0007» leaked to the player)."""
    bad = ('{"pitch":"Помоги расквитаться с pool:0007 за нарушенное слово.",'
           '"foreshadow":"Тебя гложет обида.","reveal":""}')
    stub = _Stub([bad, bad])
    seed = dict(_seed(), twist=None)
    assert F.framer(seed, ALLOWED | {"pool:0007"}, stub) is None
    assert stub.n == 2


def test_opener_2nd_person_verb_allowed_sentence_initial():
    assert F.valid_entities("Поможешь мне с долгом?", set())
    assert not F.valid_entities("Гримберт ждёт.", set())


def test_framer_reveal_optional_when_seed_has_no_twist():
    seed = dict(_seed(), twist=None)   # legal per seeds.py — not every seed carries a twist
    good = ('{"pitch":"Верни Дунну долг.","foreshadow":"Тебя гложет вина.","reveal":""}')
    art = F.framer(seed, ALLOWED, _Stub([good]))
    assert art is not None and art["reveal"] == ""


def _wealth_seed():
    return {"sid": "seed_dunn_wealth", "pattern": "plain_need", "giver": "npc:dunn",
            "giver_name": "Дунн", "why": "нужда",
            "goal": {"done": {"type": "wealth", "value": 50}},
            "cast": {"villain": None, "prize": None}}


def test_framer_rejects_fabricated_wealth_number():
    """live bug: LLM invented «200 монет» for a wealth|50 seed — the true target is 50, not 200."""
    bad = ('{"pitch":"Принеси мне 200 монет.","foreshadow":"Тебя гложет нужда в деньгах.",'
           '"reveal":""}')
    stub = _Stub([bad, bad])
    seed = dict(_wealth_seed(), twist=None)
    assert F.framer(seed, {"Дунн", "гильдия"}, stub) is None
    assert stub.n == 2                                     # regenerated once, still bad → skip


def test_framer_accepts_true_wealth_number():
    good = ('{"pitch":"Принеси мне 50 монет.","foreshadow":"Тебя гложет нужда в деньгах.",'
            '"reveal":""}')
    stub = _Stub([good])
    seed = dict(_wealth_seed(), twist=None)
    art = F.framer(seed, {"Дунн", "гильдия"}, stub)
    assert art is not None and "50" in art["pitch"]


def test_framer_accepts_true_reward_number_when_passed():
    good = ('{"pitch":"Принеси мне 50 монет, получишь 30 монет награды.",'
            '"foreshadow":"Тебя гложет нужда в деньгах.","reveal":""}')
    stub = _Stub([good])
    seed = dict(_wealth_seed(), twist=None)
    art = F.framer(seed, {"Дунн", "гильдия"}, stub, reward=30)
    assert art is not None and "30" in art["pitch"]


def test_framer_artifacts_are_plain_strings_no_predicate_leak():
    good = ('{"pitch":"Верни гроссбух Марты.",'
            '"foreshadow":"Тебя гложет долг — гроссбух у Ральфа.",'
            '"reveal":"Ральф должен гильдии."}')
    art = F.framer(_seed(), ALLOWED, _Stub([good]))
    for v in art.values():
        assert isinstance(v, str)
    assert set(art) == {"pitch", "foreshadow", "reveal"}   # no stray keys (predicates/numbers)
