"""Разговор-объект: создание/слияние/долг/распад — чистая логика, без LLM."""

from __future__ import annotations

from aidnd.server.play.engine.convo import (
    QUIET_DIE,
    conv_block,
    conv_debt_to,
    conv_note_say,
    conv_of,
    conv_tick,
)

NAMES = {"a": "Аля", "b": "Борх", "c": "Кедрик", "pc": "чужак"}


def test_say_creates_conv_and_debt():
    lv = {"clock": 0}
    conv_note_say(lv, "a", "b", "Борх, ты видел чужака?", "стол у очага")
    c = conv_of(lv, "a")
    assert c and set(c["members"]) == {"a", "b"} and c["zone"] == "стол у очага"
    assert conv_debt_to(lv, "b") and conv_debt_to(lv, "b")["frm"] == "a"
    assert conv_debt_to(lv, "a") is None                       # долг на адресате, не на авторе


def test_reply_clears_debt_and_sets_reverse():
    lv = {"clock": 0}
    conv_note_say(lv, "a", "b", "видел чужака?", "очаг")
    conv_note_say(lv, "b", "a", "видел, тихий какой-то", "очаг")
    assert conv_debt_to(lv, "b") is None                       # ответил
    assert conv_debt_to(lv, "a")                               # теперь слово за Алей


def test_third_joins_and_merge():
    lv = {"clock": 0}
    conv_note_say(lv, "a", "b", "…", "очаг")
    conv_note_say(lv, "c", "a", "о чём шепчетесь?", "очаг")     # третий подсел
    c = conv_of(lv, "b")
    assert set(c["members"]) == {"a", "b", "c"}
    assert len(lv["convs"]) == 1                                # не два кружка, а один


def test_leaving_zone_and_quiet_death():
    lv = {"clock": 0}
    conv_note_say(lv, "a", "b", "…", "стол у окна")
    places = {"a": "стол у окна", "b": "стол у окна"}
    conv_tick(lv, places.get)
    assert conv_of(lv, "a")
    places["b"] = "очаг"                                        # Борх пересел
    conv_tick(lv, places.get)
    assert conv_of(lv, "a") is None                             # беседа распалась (остался один)
    conv_note_say(lv, "a", "b", "…", "стол у окна")
    for _ in range(QUIET_DIE):
        conv_tick(lv, {"a": "стол у окна", "b": "стол у окна"}.get)
    assert conv_of(lv, "a") is None                             # тишина убила разговор


def test_block_renders_debt():
    lv = {"clock": 0}
    conv_note_say(lv, "a", "b", "ну так что, знаешь его?", "очаг")
    blk = conv_block(lv, "b", NAMES)
    assert "ТЕКУЩИЙ РАЗГОВОР" in blk and "Аля" in blk and "ТЕБЕ обращена" in blk
    blk_a = conv_block(lv, "a", NAMES)
    assert "не отвечай за него" in blk_a                        # третьим не встревать


def test_debt_expires():
    lv = {"clock": 0}
    conv_note_say(lv, "a", "b", "эй?", "очаг")
    for _ in range(4):
        conv_tick(lv, {"a": "очаг", "b": "очаг"}.get)
        conv_note_say(lv, "a", "c", "ладно, Кедрик, а ты?", "очаг") if False else None
    assert conv_debt_to(lv, "b") is None                        # вопрос прогорел
