"""Дела (deeds): журнал, обещания, сплетни — стор и чистые хелперы, без LLM/сервера."""

from __future__ import annotations

import os
import tempfile

from aidnd.worldgen import WorldStore


def _s() -> WorldStore:
    return WorldStore(os.path.join(tempfile.mkdtemp(), "t.db"))


def test_deed_journal_append_and_filters():
    s = _s()
    s.deed_add(1, 100, "npc:a", "theft", obj="pc", place="таверна",
               witnesses=["npc:b"], data={"what": "кошель"})
    s.deed_add(1, 200, "npc:b", "clear", obj="логово у мельницы")
    s.deed_add(2, 150, "npc:c", "theft")                     # чужой мир не течёт
    assert len(s.deeds(1)) == 2
    th = s.deeds(1, verb="theft")
    assert th[0]["data"]["what"] == "кошель" and th[0]["witnesses"] == ["npc:b"]
    assert s.deeds(1, since_gt=150)[0]["verb"] == "clear"


def test_promise_lifecycle():
    s = _s()
    i = s.deed_add(1, 100, "npc:a", "promise", obj="npc:b", status="active",
                   data={"what": "покажу ход", "due": "morning", "node": 7, "made_gt": 100})
    assert len(s.deeds(1, verb="promise", status="active")) == 1
    s.deed_status(1, i, "done")
    assert not s.deeds(1, verb="promise", status="active")
    assert s.deeds(1, verb="promise", status="done")


def test_promise_line_and_town_talk_format():
    from aidnd.server.play.engine.deeds import PHASE_RU, RU2PHASE, promise_line
    d = {"obj": "npc:b", "place": "у мельницы",
         "data": {"what": "принесу нож", "due": "morning", "where": "у мельницы"}}
    line = promise_line(d, {"npc:b": "Бета"})
    assert "СЛОВО" in line and "Бета" in line and "утром" in line
    assert RU2PHASE["на рассвете"] == "morning" and PHASE_RU["evening"] == "вечером"


def test_appointment_place_exists():
    from aidnd.society import PLACE
    pk = PLACE["appointment"]
    assert pk.window["night"] == 1.0 and pk.sates.get("purpose", 0) > 0
