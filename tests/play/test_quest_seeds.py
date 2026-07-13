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


def _plain_fixture(gt=3 * 1440):
    # знахарка: открытая веха have|herbs — просто хочет расплатиться с кузнецом (docs/quests.md:
    # "квест = делегированная нужда"), никакого злодея/deed не требуется
    znah_ms = Milestone("расплатиться с кузнецом", "acquire", "npc:smith", {},
                        {"type": "have", "item": "herbs"})
    znah = _person("npc:znah", "Знахарка Тэс", "знахарка",
                   agendas=[Agenda("расплатиться с кузнецом", "ambition", 0.6, [znah_ms])])
    # ушлый: открытая веха wealth|50 — купить кинжал
    wealth_ms = Milestone("купить кинжал", "need", "wealth", {}, {"type": "wealth", "value": 50})
    rogue = _person("npc:rogue", "Ушлый Пит", "бродяга",
                    agendas=[Agenda("купить кинжал", "wealth", 0.6, [wealth_ms])])
    # праздный: открытая веха at|market — patrol/travel goal, NOT delegatable
    at_ms = Milestone("дойти до рынка", "goto", "market", {}, {"type": "at", "place": "market"})
    idle = _person("npc:idle", "Праздный Джо", "зевака",
                   agendas=[Agenda("сходить на рынок", "ambition", 0.5, [at_ms])])
    # закрытый: агенда есть, но не активна (status='done') — не подходит
    closed_ms = Milestone("давно исполнено", "acquire", "x", {}, {"type": "have", "item": "x"})
    closed_ag = Agenda("старое дело", "ambition", 0.5, [closed_ms])
    closed_ag.status = "done"
    closed = _person("npc:closed", "Закрытый Кэл", "рыбак", agendas=[closed_ag])
    people = {"npc:znah": znah, "npc:rogue": rogue, "npc:idle": idle, "npc:closed": closed}
    return people, [], gt


def test_pat_plain_need_binds_have_and_wealth_milestones():
    people, deeds, gt = _plain_fixture()
    got = {(s["pattern"], s["giver"]) for s in S.sift(people, deeds, gt)}
    assert ("plain_need", "npc:znah") in got
    assert ("plain_need", "npc:rogue") in got


def test_pat_plain_need_abstains_for_at_milestone_and_closed_agenda():
    people, deeds, gt = _plain_fixture()
    got = {(s["pattern"], s["giver"]) for s in S.sift(people, deeds, gt)}
    assert ("plain_need", "npc:idle") not in got     # 'at' — never sifted (§4 table)
    assert ("plain_need", "npc:closed") not in got   # no active agenda at all


def test_pat_plain_need_goal_and_cast_shape():
    people, deeds, gt = _plain_fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["giver"] == "npc:znah")
    assert seed["goal"]["done"] == {"type": "have", "item": "herbs"}   # дословно из вехи
    assert seed["cast"]["villain"] is None
    assert seed["evidence"] == ["agenda:npc:znah:0"]
    assert seed["twist"] is None
    assert seed["motivation"] == "equipment"                          # have → equipment
    seed2 = next(s for s in S.sift(people, deeds, gt) if s["giver"] == "npc:rogue")
    assert seed2["goal"]["done"] == {"type": "wealth", "value": 50}
    assert seed2["motivation"] == "wealth"                            # wealth → wealth


def test_pat_plain_need_does_not_double_bind_a_giver_already_seeded_by_a_flavored_pattern():
    # Дунн — уже связан kin_debt в основной фикстуре; plain_need не должен добавить второй seed
    # на ту же веху/дающего.
    people, deeds, gt = _fixture()
    got = [s for s in S.sift(people, deeds, gt) if s["giver"] == "npc:dunn"]
    assert len(got) == 1 and got[0]["pattern"] == "kin_debt"


def test_unanswered_blood_abstains_without_living_kin():
    victim = _person("npc:tam", "Тэм Ли", "фермер")
    villain = _person("npc:vex", "Векс Дорн", "бродяга")
    people = {"npc:tam": victim, "npc:vex": villain}
    d = {"id": "d200", "gt": 100, "actor": "npc:vex", "obj": "npc:tam",
         "verb": "murder", "place": "", "status": "open", "witnesses": ["npc:vex"], "data": {}}
    got = S.sift(people, [d], 200)
    assert not any(s["pattern"] == "unanswered_blood" for s in got)   # некому нанять партию — труп не наймёт
