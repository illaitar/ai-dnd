"""Replay recorder — the line-formatter mirrors play.html's render, and the file recorder appends
a faithful textual replay. Pure formatter tests (canned response dicts → exact text block), plus
combat-log dedup, the gt-jump divider, and end-to-end file writing into a tmp dir.
"""

from aidnd.server.play import replay


def _make_test_app():
    """Minimal app replicating server/app.py's exact middleware wiring — no existing test
    bootstraps the real FastAPI app (heavy DB/session setup), so this locks the ASGI plumbing
    (tap registered INNER to GZip, body-cache/reconstruction) against Starlette version bumps
    without dragging in real /api/play/* session dependencies.
    """
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from starlette.middleware.gzip import GZipMiddleware

    from aidnd.server.app import _replay_tap

    test_app = FastAPI()
    test_app.middleware("http")(_replay_tap)  # registered first → sits INNER to GZip
    test_app.add_middleware(GZipMiddleware, minimum_size=1000)

    @test_app.post("/api/play/say")
    async def _say(request: Request):
        request.state.wid = 9001
        request.state.replay_req = await request.json()
        return JSONResponse({"gt": 100, "line": "Здорово.", "name": "Марта"})

    @test_app.get("/api/play/map")
    async def _map(request: Request):
        request.state.wid = 9001
        return JSONResponse({"viewBox": [0, 0, 1, 1]})

    return test_app


def test_asgi_tap_narrative_endpoint_writes_replay_and_passes_body(tmp_path, monkeypatch):
    """POST to a narrative endpoint: the client still receives the intact JSON body, and the
    replay file picks up the line — end-to-end through the real middleware stack (gzip inner,
    body-iterator drain, response reconstruction), not just the pure formatter."""
    from starlette.testclient import TestClient

    monkeypatch.setattr(replay, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(replay, "_STATES", {})
    monkeypatch.delenv("AIDND_NO_REPLAY", raising=False)

    client = TestClient(_make_test_app())
    resp = client.post("/api/play/say", json={"npc": "n", "text": "Привет!"})
    assert resp.status_code == 200
    assert resp.json() == {"gt": 100, "line": "Здорово.", "name": "Марта"}

    files = list(tmp_path.glob("replay-w9001-*.txt"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "> Привет!" in text
    assert "Марта. Здорово." in text


def test_asgi_tap_non_narrative_endpoint_untouched(tmp_path, monkeypatch):
    """GET a non-narrative (polled) endpoint: response passes through unmodified and nothing is
    recorded — the early bail in _replay_tap must fire before any body draining."""
    from starlette.testclient import TestClient

    monkeypatch.setattr(replay, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(replay, "_STATES", {})
    monkeypatch.delenv("AIDND_NO_REPLAY", raising=False)

    client = TestClient(_make_test_app())
    resp = client.get("/api/play/map")
    assert resp.status_code == 200
    assert resp.json() == {"viewBox": [0, 0, 1, 1]}
    assert list(tmp_path.glob("*.txt")) == []


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


def test_combat_new_encounter_at_or_above_prior_length_not_dropped():
    """A second encounter's log, first observed at a length >= the first encounter's final length,
    must not have its opening lines silently swallowed by the shrink-only dedup check."""
    st = _st()
    fight1 = {"combat": {"log": ["Бой начался.", "Гоблин бьёт — 4 урона.", "Гоблин падает."]}}
    assert replay.format_lines("combat", {}, fight1, st) == [
        "  ⚔ Бой начался.",
        "  ⚔ Гоблин бьёт — 4 урона.",
        "  ⚔ Гоблин падает.",
    ]
    assert st.combat_len == 3
    # a tick with no combat in between (fight ended, combat block absent from the response)
    replay.format_lines("act", {"text": "иду дальше"}, {"narr": ["Тихо."]}, st)
    assert st.had_combat is False
    # second encounter first observed with a log length >= the first fight's final length (3)
    fight2 = {"combat": {"log": ["Новый бой начался.", "Волк рычит.", "Волк кусает.", "Ты бьёшь."]}}
    lines = replay.format_lines("combat", {}, fight2, st)
    assert lines == [
        "  ⚔ Новый бой начался.",
        "  ⚔ Волк рычит.",
        "  ⚔ Волк кусает.",
        "  ⚔ Ты бьёшь.",
    ]
    assert st.combat_len == 4


def test_should_tap_predicate_matches_narrative_whitelist():
    for verb in replay._NARR_POST:
        assert replay.should_tap(verb) is True
    assert replay.should_tap("combat") is True
    for verb in ("map", "inventory", "journal", "contracts", "scene", "wares", "plan",
                 "newworld", "debuglog", "state", ""):
        assert replay.should_tap(verb) is False, verb


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
