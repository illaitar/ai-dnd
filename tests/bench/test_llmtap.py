# `llm_tap()` monkeypatches `ModelManager.call` (the class method) for the duration of the
# context, so it must be exercised through a real `ModelManager` instance (or subclass) rather
# than a hand-rolled fake object — otherwise the patch would never be hit. `StubModelManager`
# skips the real __init__ (no backends/config/httpx needed) and, crucially, does NOT override
# `call` itself: it relies on inheriting whatever `ModelManager.call` currently is, so a test-only
# `patch.object(ModelManager, "call", ...)` stub underneath `llm_tap()` is what actually answers
# the call — no live LLM, no network, no AIDND_PROFILE.
from unittest.mock import patch

from aidnd.inference.client import ModelManager
from bench.llmtap import llm_tap


class StubModelManager(ModelManager):
    def __init__(self) -> None:
        pass  # skip real backend/config setup entirely


def _canned_call(self, role, messages, **kwargs):
    return {"content": "stubbed narration", "tool_calls": []}


def test_llm_tap_records_one_call_with_role_and_raw():
    mgr = StubModelManager()
    messages = [{"role": "user", "content": "hi"}]
    with patch.object(ModelManager, "call", _canned_call):
        with llm_tap() as calls:
            result = mgr.call("narrator", messages)

        # restored to the outer _canned_call stub (not left as the tap's wrapper) once llm_tap
        # exits, while we're still inside patch.object's own scope
        assert ModelManager.call is _canned_call

    assert result == {"content": "stubbed narration", "tool_calls": []}
    assert len(calls) == 1
    recorded = calls[0]
    assert recorded.role == "narrator"
    assert recorded.messages == messages
    assert recorded.raw == result
    assert recorded.parsed == result
    assert recorded.ms >= 0
