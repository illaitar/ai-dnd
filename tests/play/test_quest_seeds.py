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


def test_broken_promise_summary_names_villain_never_pid():
    """PID leak fix: _revenge_summary must carry the villain's NAME (here fixture's "Ральф Ли") —
    never a raw pid like "npc:ralf" — since this text flows into the inserted revenge Agenda,
    pipeline._allowed, and the framer prompt verbatim."""
    people, deeds, gt = _fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "broken_promise")
    assert "Ральф" in seed["summary"]
    assert "npc:" not in seed["summary"]


def test_unanswered_blood_summary_names_villain_never_pid():
    people, deeds, gt = _blood_fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "unanswered_blood")
    assert "Векс" in seed["summary"]
    assert "npc:" not in seed["summary"]


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


def test_pat_plain_need_carries_agenda_summary_as_seed_summary():
    """A plain_need seed's `summary` is the giver's own Agenda.summary (plan_agenda-authored, sim
    truth) — the honest material pipeline._allowed widens with so the framer can write about the
    actual life-goal instead of starving for lack of nameable cast."""
    wealth_ms = Milestone("купить кинжал", "need", "wealth", {}, {"type": "wealth", "value": 15})
    rogue = _person("npc:pit", "Ушлый Пит", "бродяга",
                    agendas=[Agenda("Скопив денег, купить у кузнеца Айвора кинжал",
                                    "wealth", 0.6, [wealth_ms])])
    people = {"npc:pit": rogue}
    seed = next(s for s in S.sift(people, [], 3 * 1440) if s["giver"] == "npc:pit")
    assert seed["summary"] == "Скопив денег, купить у кузнеца Айвора кинжал"


def test_pat_plain_need_does_not_double_bind_a_giver_already_seeded_by_a_flavored_pattern():
    # Дунн — уже связан kin_debt в основной фикстуре; plain_need не должен добавить второй seed
    # на ту же веху/дающего.
    people, deeds, gt = _fixture()
    got = [s for s in S.sift(people, deeds, gt) if s["giver"] == "npc:dunn"]
    assert len(got) == 1 and got[0]["pattern"] == "kin_debt"


def _courtship_name_fixture(gt=3 * 1440):
    """LLM-planned courtship agenda whose done.id is a display NAME (agenda.py:courtship_agenda
    writes the beloved's name, not her pid) — this is the live shape that produced an
    uncompletable courtship_wall quest (done.id keyed by name, _met reads real pids)."""
    ms = Milestone("расположить к себе Мойру", "affiliate", "Мойра Кожемяка", {},
                   {"type": "affinity", "id": "Мойра Кожемяка", "value": 0.3})
    suitor = _person("npc:suitor", "Иво Тарн", "кузнец",
                     agendas=[Agenda("завоевать расположение — Мойра Кожемяка", "courtship", 0.8, [ms])])
    moira = _person("npc:moira", "Мойра Кожемяка", "ткачиха")
    people = {"npc:suitor": suitor, "npc:moira": moira}
    return people, [], gt


def test_courtship_wall_resolves_name_id_to_giver_pid():
    people, deeds, gt = _courtship_name_fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "courtship_wall")
    assert seed["goal"]["done"] == {"type": "affinity", "id": "npc:moira", "value": 0.3}
    assert seed["cast"]["prize"] == "npc:moira"
    assert seed["target_name"] == "Мойра Кожемяка"


def test_courtship_wall_abstains_when_name_unresolvable():
    ms = Milestone("расположить к себе", "affiliate", "Незнакомка", {},
                   {"type": "affinity", "id": "Незнакомка", "value": 0.3})
    suitor = _person("npc:suitor", "Иво Тарн", "кузнец",
                     agendas=[Agenda("завоевать расположение", "courtship", 0.8, [ms])])
    people = {"npc:suitor": suitor}
    got = S.sift(people, [], 3 * 1440)
    assert not any(s["pattern"] == "courtship_wall" for s in got)   # honest absence, no uncompletable quest


def test_courtship_wall_leaves_already_real_pid_unchanged():
    ms = Milestone("расположить к себе", "affiliate", "npc:moira", {},
                   {"type": "affinity", "id": "npc:moira", "value": 0.5})
    suitor = _person("npc:suitor", "Иво Тарн", "кузнец",
                     agendas=[Agenda("завоевать расположение", "courtship", 0.8, [ms])])
    moira = _person("npc:moira", "Мойра Кожемяка", "ткачиха")
    people = {"npc:suitor": suitor, "npc:moira": moira}
    seed = next(s for s in S.sift(people, [], 3 * 1440) if s["pattern"] == "courtship_wall")
    assert seed["goal"]["done"] == {"type": "affinity", "id": "npc:moira", "value": 0.5}


def test_courtship_wall_resolves_partial_first_name_when_unambiguous():
    ms = Milestone("расположить", "affiliate", "Мойра", {},
                   {"type": "affinity", "id": "Мойра", "value": 0.4})
    suitor = _person("npc:suitor", "Иво Тарн", "кузнец",
                     agendas=[Agenda("завоевать расположение", "courtship", 0.8, [ms])])
    moira = _person("npc:moira", "Мойра Кожемяка", "ткачиха")
    people = {"npc:suitor": suitor, "npc:moira": moira}
    seed = next(s for s in S.sift(people, [], 3 * 1440) if s["pattern"] == "courtship_wall")
    assert seed["goal"]["done"]["id"] == "npc:moira"


def test_courtship_wall_abstains_on_ambiguous_partial_match():
    ms = Milestone("расположить", "affiliate", "Мойра", {},
                   {"type": "affinity", "id": "Мойра", "value": 0.4})
    suitor = _person("npc:suitor", "Иво Тарн", "кузнец",
                     agendas=[Agenda("завоевать расположение", "courtship", 0.8, [ms])])
    moira1 = _person("npc:moira1", "Мойра Кожемяка", "ткачиха")
    moira2 = _person("npc:moira2", "Мойра Свищ", "пряха")
    people = {"npc:suitor": suitor, "npc:moira1": moira1, "npc:moira2": moira2}
    got = S.sift(people, [], 3 * 1440)
    assert not any(s["pattern"] == "courtship_wall" for s in got)


def test_courtship_wall_name_resolved_seed_completes_via_bridge():
    """End-to-end: a name-keyed courtship milestone, once resolved by the sifter, is a genuinely
    completable quest — done_any_met fires when the GIVER's own relationships carry the resolved
    pid at the required affinity (exactly the live bug: done.id used to be a name that could never
    match state.relationships, keyed by pid)."""
    from aidnd.mind import Body, World
    from aidnd.server.play.engine.quests import bridge

    people, deeds, gt = _courtship_name_fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "courtship_wall")
    m = Milestone("", kind=seed["goal"]["kind"], target=seed["goal"]["target"],
                  done=dict(seed["goal"]["done"]))
    ct = {"src": "sift", "giver": "npc:suitor", "done_any": bridge.make_done_any(m)}
    suitor_state = people["npc:suitor"].state
    suitor_state.relationships["npc:moira"] = {"affinity": 0.3}
    world = World()
    world.add(Body(id="npc:suitor", place="дом"))
    assert bridge.done_any_met(ct, (suitor_state, world)) is True


def test_unanswered_blood_abstains_without_living_kin():
    victim = _person("npc:tam", "Тэм Ли", "фермер")
    villain = _person("npc:vex", "Векс Дорн", "бродяга")
    people = {"npc:tam": victim, "npc:vex": villain}
    d = {"id": "d200", "gt": 100, "actor": "npc:vex", "obj": "npc:tam",
         "verb": "murder", "place": "", "status": "open", "witnesses": ["npc:vex"], "data": {}}
    got = S.sift(people, [d], 200)
    assert not any(s["pattern"] == "unanswered_blood" for s in got)   # некому нанять партию — труп не наймёт
