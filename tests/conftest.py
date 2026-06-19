"""Общие фикстуры тестов. pythonpath=src задан в pyproject."""

import pytest

from aidnd.bootstrap import new_session
from aidnd.content import build_world, register_quests
from aidnd.gen import QuestSystem


@pytest.fixture
def world():
    return build_world(seed=1337, roster_size=8)


@pytest.fixture
def world_with_quests():
    w = build_world(seed=1337, roster_size=8)
    qs = QuestSystem(w)
    register_quests(w, qs)
    return w, qs


@pytest.fixture
def session():
    # use_model=False — детерминированный режим без сети (для воспроизводимых тестов)
    return new_session(seed=1337, roster_size=8, use_model=False)
