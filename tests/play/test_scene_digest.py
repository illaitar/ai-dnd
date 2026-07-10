"""Scene digest — the end-of-tick narrator that weaves observable events into one account.

Covers the deterministic event-assembly and the LLM call boundary (stubbed).
"""

from aidnd.server.play.engine.narrator import scene_digest as sd


def test_event_lines_labels_speech_by_distance_and_actions():
    feed = [
        {"k": "deed", "who": "Тол Рыжий", "text": "хохочет и идёт к выходу"},
        {"k": "speech", "who": "дворф", "to": "гному", "tier": 3, "text": "о чём-то спорят"},
        {"k": "speech", "who": "шрам", "to": "гному", "tier": 1, "text": "гоблинов выбили"},
        {"k": "deed", "who": "", "text": "за столами гудит негромкий говор"},
    ]
    lines = sd._event_lines(feed)
    assert any("действие/звук: Тол Рыжий: хохочет" in ln for ln in lines)
    assert any("речь (близко): шрам" in ln for ln in lines)
    assert any("речь (издалека): дворф" in ln for ln in lines)
    assert any(ln.startswith("- действие/звук: за столами") for ln in lines)  # ambient, no 'who'


def test_blank_events_are_dropped():
    assert sd._event_lines([{"k": "deed", "who": "x", "text": "   "}]) == []


def test_empty_feed_returns_empty_without_model(monkeypatch):
    def _boom():
        raise AssertionError("scene_digest must not touch the model when there is nothing to tell")

    monkeypatch.setattr(sd, "_model", _boom)
    assert sd.scene_digest([], "Таверна") == ""


def test_digest_calls_narrator_and_trims(monkeypatch):
    class _Stub:
        def call(self, role, messages, **kw):
            assert role == "narrator"
            assert "Тол Рыжий" in messages[1]["content"]      # events reach the prompt
            assert "Речной зубр" in messages[1]["content"]    # place reaches the prompt
            return {"content": "  У стойки рыжий мужчина хохочет и идёт к выходу.  "}

    monkeypatch.setattr(sd, "_model", lambda: _Stub())
    out = sd.scene_digest([{"k": "deed", "who": "Тол Рыжий", "text": "хохочет"}],
                          "Таверна «Речной зубр»")
    assert out == "У стойки рыжий мужчина хохочет и идёт к выходу."
