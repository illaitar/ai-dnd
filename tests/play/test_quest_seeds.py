"""Просев: пять паттернов связываются/воздерживаются ровно как в §5 Step 1 (тройка Дунн/Марта/Ральф)."""
from types import SimpleNamespace

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.server.play.engine.quests import seeds as S


def _person(pid, name, role, agendas=(), rels=None):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    st.agendas = list(agendas)
    st.relationships = dict(rels or {})
    return SimpleNamespace(name=name, role=role, state=st, persona={}, work=None)


def _fixture(gt=3 * 1440):
    # Дунн: открытая веха acquire, done={have,гроссбух}; недолюбливает Ральфа (−0.4)
    dunn_ms = Milestone("вернуть гроссбух сестры", "acquire", "debt:marta", {},
                        {"type": "have", "item": "гроссбух"})
    dunn = _person("npc:dunn", "Дунн Ли", "охотник",
                   agendas=[Agenda("вернуть гроссбух сестры", "ambition", 0.7, [dunn_ms])],
                   rels={"npc:ralf": {"affinity": -0.4}})
    # Ральф: держатель гроссбуха; к Дунну лишь −0.1 (не взаимная вражда)
    ralf = _person("npc:ralf", "Ральф Ли", "ростовщик",
                   rels={"npc:dunn": {"affinity": -0.1}})
    # Марта: сестра Дунна, обида на Ральфа (−0.6), своей агенды нет
    marta = _person("npc:marta", "Марта Ли", "торговка",
                    rels={"npc:ralf": {"affinity": -0.6}})
    people = {"npc:dunn": dunn, "npc:ralf": ralf, "npc:marta": marta}
    # d123: обещание Ральфа Марте — нарушено, 1 день назад
    d123 = {"id": "d123", "gt": gt - 1440, "actor": "npc:ralf", "obj": "npc:marta",
            "verb": "promise", "place": "", "status": "broken",
            "data": {"what": "вернуть гроссбух", "made_gt": gt - 1440}}
    # d124: Ральф сам должен гильдии — второй факт о составе (кандидат на твист)
    d124 = {"id": "d124", "gt": gt - 720, "actor": "npc:ralf", "obj": "guild",
            "verb": "promise", "place": "", "status": "broken",
            "data": {"what": "отдать гильдии 200", "made_gt": gt - 720}}
    return people, [d123, d124], gt


def test_kin_debt_and_broken_promise_bind_others_abstain():
    people, deeds, gt = _fixture()
    got = {(s["pattern"], s["giver"]) for s in S.sift(people, deeds, gt)}
    assert ("kin_debt", "npc:dunn") in got          # ✔ Дунн — брат за сестру
    assert ("broken_promise", "npc:marta") in got   # ✔ Марта — жертва с обидой
    assert ("blocked_rival", "npc:dunn") not in got  # ✘ вражда не взаимна (Ральф→Дунн −0.1)
    assert not any(p == "unanswered_blood" for p, _ in got)  # ✘ нет крови/кражи
    assert not any(p == "courtship_wall" for p, _ in got)    # ✘ веха не courtship


def test_kin_debt_goal_is_verbatim_milestone_done():
    people, deeds, gt = _fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "kin_debt")
    assert seed["goal"]["done"] == {"type": "have", "item": "гроссбух"}  # дословно из вехи
    assert seed["cast"] == {"villain": "npc:ralf", "prize": "npc:marta"}
    assert "deed:d123" in seed["evidence"]
    assert "agenda:npc:dunn:0" in seed["evidence"]


def test_broken_promise_goal_is_real_met_dict():
    people, deeds, gt = _fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "broken_promise")
    assert seed["goal"]["done"] == {"type": "dead", "id": "npc:ralf"}   # маршрут-возмездие, код-авторство
    assert seed["evidence"] == ["deed:d123"]


def test_twist_candidate_from_second_fact_touching_cast():
    people, deeds, gt = _fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "kin_debt")
    assert seed["twist"] and seed["twist"]["adds"] == {"type": "dead", "id": "npc:ralf"}
    assert "d124" in seed["twist"]["fact"]


def _blood_fixture(gt=5 * 1440):
    # Тэм — жертва убийства; Коул — брат (общая фамилия Ли), жив и может нанять партию
    victim = _person("npc:tam", "Тэм Ли", "фермер")
    brother = _person("npc:cole", "Коул Ли", "кузнец")
    villain = _person("npc:vex", "Векс Дорн", "бродяга")
    people = {"npc:tam": victim, "npc:cole": brother, "npc:vex": villain}
    d = {"id": "d200", "gt": gt - 60, "actor": "npc:vex", "obj": "npc:tam",
         "verb": "murder", "place": "", "status": "open", "witnesses": ["npc:cole"],
         "data": {}}
    return people, [d], gt


def test_unanswered_blood_giver_is_kin_not_victim():
    people, deeds, gt = _blood_fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "unanswered_blood")
    assert seed["giver"] == "npc:cole"                             # брат, не сама жертва
    assert seed["cast"] == {"villain": "npc:vex", "prize": "npc:tam"}   # жертва — приз (память)
    assert seed["evidence"] == ["deed:d200"]                       # deed:-префикс


def test_unanswered_blood_abstains_after_arrest():
    people, deeds, gt = _blood_fixture()
    arrest = {"id": "d201", "gt": gt - 10, "actor": "guard", "obj": "npc:vex",
              "verb": "arrest", "place": "", "status": "closed", "data": {}}
    got = S.sift(people, deeds + [arrest], gt)
    assert not any(s["pattern"] == "unanswered_blood" for s in got)   # ответ уже есть — арест злодея


def test_unanswered_blood_abstains_when_dead_flag_set():
    people, deeds, gt = _blood_fixture()
    got = S.sift(people, deeds, gt, flag_get=lambda k: k == "dead|npc:vex")
    assert not any(s["pattern"] == "unanswered_blood" for s in got)   # мир уже отметил злодея мёртвым


def test_unanswered_blood_abstains_without_living_kin():
    victim = _person("npc:tam", "Тэм Ли", "фермер")
    villain = _person("npc:vex", "Векс Дорн", "бродяга")
    people = {"npc:tam": victim, "npc:vex": villain}
    d = {"id": "d200", "gt": 100, "actor": "npc:vex", "obj": "npc:tam",
         "verb": "murder", "place": "", "status": "open", "witnesses": ["npc:vex"], "data": {}}
    got = S.sift(people, [d], 200)
    assert not any(s["pattern"] == "unanswered_blood" for s in got)   # некому нанять партию — труп не наймёт
