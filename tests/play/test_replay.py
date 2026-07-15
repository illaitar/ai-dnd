"""Replay recorder — the line-formatter mirrors play.html's render, and the file recorder appends
a faithful textual replay. Pure formatter tests (canned response dicts → exact text block), plus
combat-log dedup, the gt-jump divider, and end-to-end file writing into a tmp dir.
"""

from aidnd.server.play import replay


def _st():
    return replay._WidState()


def test_say_line_with_narr_and_feed():
    resp = {
        "gt": 1180,
        "line": "И тебе не хворать, странник.",
        "name": "Тол Рыжий",
        "narr": ["Он поднимает кружку в приветствии."],
        "feed": [
            {"k": "speech", "who": "дворф", "to": "гному", "tier": 3, "text": "спорят о цене"},
            {"k": "speech", "who": "шрам", "to": "бармену", "tier": 1, "text": "ещё эля!"},
            {"k": "deed", "who": "Марта", "text": "вытирает столы"},
        ],
    }
    lines = replay.format_lines("say", {"npc": "n1", "text": "Здорово, Тол."}, resp, _st())
    assert lines == [
        "> Здорово, Тол.",
        "Он поднимает кружку в приветствии.",
        "Тол Рыжий. И тебе не хворать, странник.",
        "  · шрам → бармену: «ещё эля!»",        # tier 1 (nearest) sorts before tier 3
        "  · дворф → гному: «спорят о цене»",
        "  · Марта: вытирает столы",              # deeds last
    ]


def test_act_with_scene_line_and_digest():
    resp = {
        "narr": ["Ты толкаешь тяжёлую дверь."],
        "line": {"who": "Страж", "text": "Куда прёшь?"},
        "digest": "В зале пахнет дымом; у очага кто-то тихо смеётся.",
        "feed": [{"k": "deed", "who": "x", "text": "не должно попасть — есть digest"}],
    }
    lines = replay.format_lines("act", {"text": "вхожу внутрь"}, resp, _st())
    assert lines == [
        "> вхожу внутрь",
        "Ты толкаешь тяжёлую дверь.",
        "Страж. Куда прёшь?",
        "  ⋯ В зале пахнет дымом; у очага кто-то тихо смеётся.",
    ]


def test_move_stage_direction_and_address_and_contract_done():
    resp = {
        "location": {"name": "Таверна «Гнилой зуб»"},
        "contract_done": "Уговор исполнен — Ганс кивает и отсчитывает монеты.",
        "address": [{"npc": "n2", "who": "Ганс", "text": "Вот и ты, наконец!"}],
    }
    lines = replay.format_lines("move", {"to": 25}, resp, _st())
    assert lines == [
        "> [иду: Таверна «Гнилой зуб»]",
        "Уговор исполнен — Ганс кивает и отсчитывает монеты.",
        "Ганс — тебе. Вот и ты, наконец!",
    ]


def test_enter_and_exit_stage_directions():
    assert replay.format_lines("enter", {}, {"location": {"name": "Кузница"}}, _st())[0] \
        == "> [вхожу: Кузница]"
    assert replay.format_lines("exit", {}, {}, _st())[0] == "> [выхожу наружу]"


def test_talk_hides_raw_pool_id():
    resp = {"name": "pool:1234", "line": "Чего надо?"}
    lines = replay.format_lines("talk", {"npc": "pool:1234"}, resp, _st())
    assert lines == ["> [подхожу: голос]", "голос. Чего надо?"]


def test_error_line():
    lines = replay.format_lines("act", {"text": "лечу на луну"}, {"error": "так не выйдет"}, _st())
    assert lines == ["> лечу на луну", "  ! так не выйдет"]


def test_gt_jump_emits_divider():
    st = _st()
    st.last_gt = 1300  # ~21:40
    lines = replay.format_lines("debug/skip", {}, {"gt": 1900, "narr": ["Ты просыпаешься."]}, st)
    # 1900 → 07:00 → утро; jump 600 min > 60 → divider
    assert lines == [
        "> [пропускаю время]",
        "— gt 1900 · утро —",
        "Ты просыпаешься.",
    ]
    assert st.last_gt == 1900


def test_small_gt_step_no_divider():
    st = _st()
    st.last_gt = 1180
    lines = replay.format_lines("say", {"npc": "n", "text": "привет"}, {"gt": 1185, "line": "ага"}, st)
    assert not any(ln.startswith("— gt") for ln in lines)


def test_combat_log_delta_dedup():
    st = _st()
    v1 = {"combat": {"log": ["Бой начался.", "Гоблин бьёт — 4 урона."]}}
    assert replay.format_lines("combat", {}, v1, st) == [
        "  ⚔ Бой начался.",
        "  ⚔ Гоблин бьёт — 4 урона.",
    ]
    # next tick — same encounter, two new lines; the first two are NOT repeated
    v2 = {"combat": {"log": ["Бой начался.", "Гоблин бьёт — 4 урона.",
                             "Ты бьёшь — 6 урона.", "Гоблин падает."]}}
    assert replay.format_lines("combat_act", {"type": "attack"}, v2, st) == [
        "> [бой: удар]",
        "  ⚔ Ты бьёшь — 6 урона.",
        "  ⚔ Гоблин падает.",
    ]


def test_combat_new_encounter_resets_dedup():
    st = _st()
    st.combat_len = 5  # a prior fight left the counter high
    v = {"combat": {"log": ["Новый бой.", "Волк рычит."]}}  # shorter → fresh encounter
    lines = replay.format_lines("combat", {}, v, st)
    assert lines == ["  ⚔ Новый бой.", "  ⚔ Волк рычит."]
    assert st.combat_len == 2


def test_combat_over_wrapup_and_death():
    st = _st()
    resp = {
        "combat": {"log": ["Финальный удар."]},
        "over": {"narr": ["Логово затихло."], "death": {"text": "Тьма.", "cause": "клинок гоблина"}},
    }
    lines = replay.format_lines("combat_act", {"type": "attack"}, resp, st)
    assert "Логово затихло." in lines
    assert "  ⚔ Финальный удар." in lines
    assert "  ! Смерть: Тьма. (клинок гоблина)" in lines


def test_live_has_no_input_echo():
    resp = {"narr": ["Толпа шумит."], "digest": "Гул голосов накрывает площадь."}
    lines = replay.format_lines("live", {}, resp, _st())
    assert lines == ["Толпа шумит.", "  ⋯ Гул голосов накрывает площадь."]


def test_record_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(replay, "_STATES", {})
    monkeypatch.delenv("AIDND_NO_REPLAY", raising=False)
    replay.record(7, "say", {"npc": "n", "text": "Привет!"},
                  {"gt": 1180, "line": "И тебе привет.", "name": "Марта"}, 200)
    replay.record(7, "act", {"text": "оглядываюсь"}, {"narr": ["Пусто и тихо."]}, 200)
    files = list(tmp_path.glob("replay-w7-*.txt"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert text.startswith("# Реплей — мир 7 ·")
    assert "> Привет!" in text
    assert "Марта. И тебе привет." in text
    assert "> оглядываюсь" in text
    assert "Пусто и тихо." in text


def test_record_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(replay, "_STATES", {})
    monkeypatch.setenv("AIDND_NO_REPLAY", "1")
    replay.record(7, "say", {"text": "молчок"}, {"line": "нет записи"}, 200)
    assert list(tmp_path.glob("*.txt")) == []


def test_record_skips_non_narrative_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(replay, "_STATES", {})
    monkeypatch.delenv("AIDND_NO_REPLAY", raising=False)
    replay.record(7, "map", None, {"viewBox": [0, 0, 1, 1]}, 200)
    replay.record(7, "inventory", None, {"items": []}, 200)
    assert list(tmp_path.glob("*.txt")) == []


def test_newworld_rotates_file(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(replay, "_STATES", {})
    monkeypatch.delenv("AIDND_NO_REPLAY", raising=False)
    replay.record(7, "say", {"text": "первый"}, {"line": "мир А"}, 200)
    first = list(tmp_path.glob("replay-w7-*.txt"))
    assert len(first) == 1
    replay.record(7, "newworld", {}, {}, 200)  # wipe → next write must open a NEW file
    st = replay._STATES[7]
    assert st.force_new and st.path is None
