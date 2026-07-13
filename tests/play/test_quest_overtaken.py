"""Обгон: заказчик сам закрыл веху → квест закрывается 'overtaken' честной репликой, без утечки на
доску; ещё живая веха остаётся нетронутой; пропавший/мёртвый заказчик тоже обгон; уже
скомпостированная (по возрасту) отложенная строка не переписывается повторно."""
import os
import tempfile
from types import SimpleNamespace

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import pipeline as P
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _dunn(cursor: int) -> SimpleNamespace:
    ms = Milestone("вернуть гроссбух", "acquire", "debt:marta", {}, {"type": "have", "item": "гроссбух"})
    ag = Agenda("вернуть гроссбух", "ambition", 0.7, [ms])
    ag.cursor = cursor
    npc = SimpleNamespace(name="Дунн", state=NpcState.from_config(NpcConfig(id="npc:dunn", name="Дунн")))
    npc.state.agendas = [ag]
    return npc


def test_overtaken_closes_when_giver_advanced(monkeypatch):
    st = _store(monkeypatch)
    core._S["people"] = {"npc:dunn": _dunn(cursor=1)}      # Марта сама уплатила долг — веха уже пройдена
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "offered",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "arc": {"beat": "offered"}, "seed": {"pattern": "kin_debt"},
                      "done_any": [{"type": "have", "item": "гроссбух"}],
                      "roles": {"giver": "npc:dunn"}})
    news = P._recheck_overtaken()
    assert any("улажено" in n or "поздно" in n for n in news)
    assert not st.contracts(core._wid(), "offered")
    closed = st.contracts(core._wid(), "closed")[0]
    assert closed["arc"]["beat"] == "overtaken"
    assert not st.contracts(core._wid(), "board")          # никакой утечки на доску


def test_still_open_milestone_untouched(monkeypatch):
    st = _store(monkeypatch)
    core._S["people"] = {"npc:dunn": _dunn(cursor=0)}       # веха всё ещё актуальна
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "offered",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "arc": {"beat": "offered"}, "seed": {"pattern": "kin_debt"},
                      "done_any": [{"type": "have", "item": "гроссбух"}],
                      "roles": {"giver": "npc:dunn"}})
    news = P._recheck_overtaken()
    assert news == []
    still = st.contracts(core._wid(), "offered")
    assert len(still) == 1
    assert still[0]["arc"]["beat"] == "offered"             # непотревожено
    assert not st.contracts(core._wid(), "closed")


def test_missing_giver_is_overtaken(monkeypatch):
    """Заказчик пропал из живого пула (умер/уехал) — предложение всё равно моот, а не зависает вечно."""
    st = _store(monkeypatch)
    core._S["people"] = {}                                  # Дунна больше нет в живом пуле
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "board",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "arc": {"beat": "offered"}, "seed": {"pattern": "broken_promise"},
                      "done_any": [{"type": "dead", "id": "npc:ralf"}],
                      "roles": {"giver": "npc:dunn"}})
    news = P._recheck_overtaken()
    assert news
    closed = st.contracts(core._wid(), "closed")[0]
    assert closed["arc"]["beat"] == "overtaken"
    assert not st.contracts(core._wid(), "board")


def test_active_accepted_quest_journals_on_overtaken(monkeypatch):
    """Игрок уже принял дело (active) — обгон закрывает контракт И кладёт закрывающую реплику в
    журнал через j_quest (spec: 'saw' beat), а не только в новостную строку морнинга."""
    st = _store(monkeypatch)
    core._S["people"] = {"npc:dunn": _dunn(cursor=1)}       # обогнан уже во время активного дела
    cid = "ct:sift:npc:dunn:4320"
    st.save_contract(core._wid(), cid, "active",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "arc": {"beat": "active"}, "seed": {"pattern": "kin_debt"},
                      "done_any": [{"type": "have", "item": "гроссбух"}],
                      "roles": {"giver": "npc:dunn"}})
    news = P._recheck_overtaken()
    assert news
    closed = st.contracts(core._wid(), "closed")[0]
    assert closed["arc"]["beat"] == "overtaken"
    assert not st.contracts(core._wid(), "active")
    rows = st.journal_list(core._wid(), kind="quest")
    assert any(r.get("prov") == "saw" and cid in (r.get("refs") or []) for r in rows)


def test_composted_bumped_row_not_double_closed(monkeypatch):
    """Директорский обзор: bump_weakest() уже отложил строку (queued/foreshadow-pending); _expire_stale
    её компостирует по возрасту первой (как в tick_morning) — recheck не должен переписать beat=expired
    на 'overtaken' или создать вторую закрытую запись."""
    st = _store(monkeypatch)
    core._S["people"] = {"npc:dunn": _dunn(cursor=1)}       # даже моот-условие выполнено —
    core._S["gt"] = 100000                                  # но строка уже старая и будет скомпостирована первой
    cid = "ct:sift:npc:dunn:0"                               # born=0 → далеко за quest_offer_days
    st.save_contract(core._wid(), cid, "queued",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "arc": {"beat": "foreshadow-pending"}, "seed": {"pattern": "kin_debt"},
                      "done_any": [{"type": "have", "item": "гроссбух"}],
                      "roles": {"giver": "npc:dunn"}})
    news = P._expire_stale() + P._recheck_overtaken()        # exact tick_morning ordering
    assert len(news) == 1                                    # composted once — recheck saw nothing left
    closed = st.contracts(core._wid(), "closed")
    assert len(closed) == 1
    assert closed[0]["arc"]["beat"] == "expired"              # not overwritten to 'overtaken'
