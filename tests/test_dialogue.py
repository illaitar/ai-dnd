"""Диалог и нарратив: маршрутизация реплик, приветствие vs тема, гейты страха при
запугивании, и заземление офлайн-нарратора (делится РЕАЛЬНЫМ фактом, без выдумки и
без утечки секрета ниже порога). Всё детерминированно (use_model=False)."""

from aidnd.bootstrap import new_session
from aidnd.content.knowledge import disclosable
from aidnd.eval.conversations import _HISTORY_WORDS
from aidnd.world.components import Persona, Relationships, RelEdge

NPC = "npc:toblen_stonehill"      # трактирщик в «Каменном Холме», где стартует игрок


def _sess():
    return new_session(seed=1337, roster_size=4, use_model=False)


def _set_rel(s, npc, **kw):
    rels = s.world.ecs.get(npc, Relationships) or Relationships()
    s.world.ecs.add(npc, rels)
    rels.edges[s.player] = RelEdge(**kw)
    return rels


# --- маршрутизация интента ------------------------------------------------- #
def test_addressing_named_npc_with_question_routes_to_talk():
    """«Toblen, что слышно…?» — реплика NPC, а не inspect со стат-блоком."""
    s = _sess()
    r = s.handle("Toblen, что слышно про Красных плащей?")
    assert r.get("npc") == NPC                  # talk-путь проставляет npc; inspect — нет
    assert r.get("kind") == "narration"
    assert "human" not in r["text"]             # не _describe_npc «… — human, innkeeper»


def test_explicit_intimidate_not_shadowed_by_talk_keyword():
    """«запугать… говори!» — это intimidate, а не talk по слову «говор» (порядок kw)."""
    s = _sess()
    assert s._parse_intent("запугать Toblen: говори, где они прячутся!").verb == "intimidate"


# --- приветствие vs тема --------------------------------------------------- #
def test_greeting_word_is_greeting_not_cold_withhold():
    s = _sess()
    r = s.handle("Toblen, привет!")
    assert r.get("npc") == NPC
    assert "болтать с незнаком" not in r["text"]        # не холодный withhold
    assert "Добро пожаловать" in r["text"] or "?" in r["text"]


def test_extract_topic_separates_greeting_from_substance():
    s = _sess()
    assert s._extract_topic("Toblen, привет!", NPC) == ""          # приветствие
    assert s._extract_topic("добрый день", NPC) == ""
    assert s._extract_topic("что слышно про орков?", NPC) != ""    # тема


# --- запугивание и гейт страха --------------------------------------------- #
def test_terrified_npc_yields_without_a_roll():
    """Уже напуганный (fear≥0.6) уступает без броска — геймплей сходится с когницией."""
    s = _sess()
    _set_rel(s, NPC, fear=0.9, trust=-0.3)
    r = s.handle("запугать Toblen")
    assert s.pending_roll is None
    assert r.get("npc") == NPC
    assert "Не трогай" in r["text"] or "уступает" in r["text"]


def test_calm_npc_intimidation_still_requires_check():
    """Не напуганный — обычная проверка (фикс гейта не сломал нормальный путь)."""
    s = _sess()
    _set_rel(s, NPC, fear=0.0)
    r = s.handle("запугать Toblen")
    assert r.get("kind") == "roll_request" and s.pending_roll is not None


# --- заземление нарратора (офлайн) ----------------------------------------- #
def test_trusted_npc_offline_reply_grounds_a_real_fact():
    """Делясь, NPC называет РЕАЛЬНЫЙ доступный факт, а не пустую отписку."""
    s = _sess()
    _set_rel(s, NPC, trust=0.7, affinity=0.5)
    s.cognition.observe(NPC, "мы уже знакомы", importance=3)
    r = s.handle("спросить Toblen про Красных плащей")
    low = r["text"].lower()
    assert any(w in low for w in ("плащ", "торговц", "трясут", "распояса"))


def test_stranger_greeting_has_no_invented_history():
    s = _sess()
    low = s.handle("Toblen, привет!")["text"].lower()
    assert not any(w in low for w in _HISTORY_WORDS)




def test_disclosable_facts_grow_with_trust():
    s = _sess()
    persona = s.world.ecs.get("npc:halia_thornton", Persona)
    n = lambda tr: len(disclosable(persona, tr))
    assert n(0.0) <= n(0.3) <= n(0.6) <= n(0.9)
    assert n(0.9) > n(0.0)


def test_first_meeting_becomes_known_after_talk():
    """После разговора у NPC появляется память об игроке → больше не «впервые»."""
    s = _sess()
    before = len(s.cognition.retrieve(NPC, "", s.player).memories)
    s.handle("Toblen, привет!")
    after = len(s.cognition.retrieve(NPC, "", s.player).memories)
    assert after > before
