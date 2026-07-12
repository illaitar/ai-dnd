"""Hook 1: journal_feed captures witnessed speech (tier 1/2) and deeds (with a pid).
Unwitnessed deeds are structurally impossible — they never enter the feed → no row."""

import pytest

from aidnd.server.play.engine import journal
from aidnd.worldgen import WorldStore


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(journal, "_store", lambda: st)
    monkeypatch.setattr(journal, "_wid", lambda: 1)
    monkeypatch.setattr(journal, "_gt", lambda: 512)
    return st


def test_tier1_speech_is_heard1_verbatim(wired):
    journal.journal_feed([{"k": "speech", "who": "Бронт", "tier": 1, "text": "полная фраза"}])
    r = wired.journal_list(1)
    assert len(r) == 1 and r[0]["prov"] == "heard1"
    assert r[0]["text"] == "полная фраза" and r[0]["refs"] == []


def test_tier2_speech_is_heard2_fragment(wired):
    journal.journal_feed([{"k": "speech", "who": "Бронт", "tier": 2,
                           "text": "… так и не … Марты, …"}])
    r = wired.journal_list(1)
    assert len(r) == 1 and r[0]["prov"] == "heard2"
    assert r[0]["text"] == "… так и не … Марты, …"


def test_tier3_speech_and_murmur_skip(wired):
    journal.journal_feed([{"k": "speech", "who": "зал", "tier": 3,
                           "text": "у «зала» о чём-то говорят"},
                          {"k": "deed", "who": "зал", "text": "за столами гудит негромкий говор"}])
    assert wired.journal_list(1) == []                         # neither journals


def test_witnessed_deed_is_saw_with_actor_ref(wired):
    journal.journal_feed([{"k": "deed", "who": "Гарм", "pid": "garm",
                           "text": "Гарм ныряет рукой в чужой кошель"}])
    r = wired.journal_list(1)
    assert len(r) == 1 and r[0]["prov"] == "saw"
    assert r[0]["refs"] == ["garm"] and r[0]["text"] == "Гарм ныряет рукой в чужой кошель"


def test_unwitnessed_deed_no_row(wired):
    # The market theft happens in another node → it is NEVER appended to the player's feed.
    # journal_feed only ever sees the witnessed feed → exactly the one witnessed deed journals.
    feed = [{"k": "deed", "who": "Гарм", "pid": "garm", "text": "Гарм ныряет в чужой кошель"}]
    journal.journal_feed(feed)
    r = wired.journal_list(1)
    assert len(r) == 1 and r[0]["refs"] == ["garm"]            # no market-theft row exists


def test_mixed_feed_order_preserved(wired):
    journal.journal_feed([
        {"k": "speech", "who": "Бронт", "tier": 2, "text": "… Марты …"},
        {"k": "deed", "who": "Гарм", "pid": "garm", "text": "срезает кошель"},
        {"k": "deed", "who": "зал", "text": "гул толпы"},       # ambient — skipped
    ])
    r = wired.journal_list(1)                                   # newest-first
    assert [x["kind"] for x in r] == ["event", "event"]
    assert r[0]["refs"] == ["garm"] and r[1]["prov"] == "heard2"
