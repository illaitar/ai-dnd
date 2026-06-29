"""Мок-модель (Фаза 2): движок идёт по LLM-пути детерминированно, без сети/API.

Это фундамент вырезания офлайн-фоллбэков — тесты смогут гонять онлайн-логику на FakeModel."""

from aidnd.bootstrap import new_session
from aidnd.inference.agents import match_entity, parse_intent, render_scene
from aidnd.inference.client import is_offline
from aidnd.inference.fakemodel import FakeModel
from aidnd.world.components import Persona


def test_fake_model_is_not_offline():
    m = FakeModel()
    assert m.available() and not is_offline(m)


def test_fake_model_free_text_for_narrator():
    """Нарратор (schema=None) → непустой свободный текст (онлайн-путь render_scene)."""
    s = new_session(seed=1, roster_size=4, use_model=False)
    s.model = FakeModel()
    npc = next(iter(s.npcs_here()), None) or next(iter(s.world.npcs()))
    out = render_scene(s.model, "тест-исход", s.world.ecs.get(npc, Persona), mode="dialogue")
    assert out and out.get("narration")


def test_fake_model_structured_is_schema_valid():
    """Структурная роль (со схемой) → валидный по схеме объект с required-полями."""
    m = FakeModel()
    intent = parse_intent(m, "иду на север", "pc:hero")   # → {"verb": <enum>, ...}
    assert intent is not None and intent.get("verb") in {
        "move", "talk", "attack", "inspect", "search", "persuade", "intimidate",
        "deceive", "loot", "buy", "sell", "inventory", "wait", "scan", "buyinfo", "other"}
    # match_entity (роль npc_ref, индекс) — мок отдаёт -2 (недоступно? нет — call есть) или валидный индекс
    idx = match_entity(m, "тролль", ["Тролль", "Гоблин"])
    assert isinstance(idx, int)


def test_injected_model_reaches_session():
    s = new_session(seed=1, roster_size=4, use_model=False, model=FakeModel())
    assert not is_offline(s.model)
