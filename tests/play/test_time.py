"""Слой E (время, docs/citysim.md §E): ленивый catch-up экономики + часы заведений (open_hours)."""

import os
import tempfile

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine import economy as ec
from aidnd.server.play.engine import open_hours as oh
from aidnd.server.play.engine.session import persist


@pytest.fixture
def world(monkeypatch):
    from aidnd.server.play.engine.world import _play
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(persist, "_STORE",
                        WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None
    _city, people, _crof, _cr2b, _loc = _play()
    core._S["gt"] = 8 * 60
    ec.ensure()
    return people


# ── E1: ленивый catch-up ──
def test_catchup_runs_each_missed_day(world, monkeypatch):
    days = []
    orig = ec.economy_step
    monkeypatch.setattr(ec, "economy_step",
                        lambda day=None: (days.append(day), orig(day))[1])
    core._S["gt"] = 5 * 1440 + 8 * 60                    # проспал до дня 5
    ec.economy_catchup()
    assert days == [1, 2, 3, 4, 5]                        # оборот за КАЖДЫЙ пропущенный день


def test_catchup_capped_and_idempotent(world, monkeypatch):
    days = []
    orig = ec.economy_step
    monkeypatch.setattr(ec, "economy_step",
                        lambda day=None: (days.append(day), orig(day))[1])
    core._S["gt"] = 30 * 1440 + 8 * 60                   # глубокий прыжок
    ec.economy_catchup(cap=7)
    assert len(days) == 7 and days[-1] == 30             # LOD-кап: не молотим всю историю
    days.clear()
    ec.economy_catchup()                                 # тот же день ещё раз
    assert days == []                                    # идемпотентно


def test_catchup_conserves_money(world):
    m0 = ec.money_supply()
    core._S["gt"] = 6 * 1440 + 8 * 60
    ec.economy_catchup()
    assert ec.money_supply() == m0                        # перескок дней не создаёт/не жжёт монету


# ── E2: часы заведений (open_hours) ──
def test_hours_gate_by_kind_and_time():
    assert oh.is_open("таверна «Гнилой зуб»", 20 * 60)   # вечер — таверна открыта
    assert not oh.is_open("таверна «Гнилой зуб»", 8 * 60)  # утро — таверна заперта
    assert oh.is_open("лавка бакалейщика", 12 * 60)       # день — лавка открыта
    assert not oh.is_open("лавка бакалейщика", 2 * 60)    # ночь — заперта
    assert oh.is_open("игорный дом", 2 * 60)              # окно за полночь — притон ночью открыт
    assert not oh.is_open("игорный дом", 12 * 60)         # днём закрыт
    assert oh.is_open("жилой дом", 3 * 60)                # у жилья часов нет — всегда «открыт»
    assert oh.opens_at("кузница") == 7
