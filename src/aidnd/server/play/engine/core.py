"""Игровой контур — ЯДРО: сессии-миры, состояние, БД, время, игрок-агент, общие хелперы.

Слой mechanics/ (см. docs/loop.md).
"""

from __future__ import annotations

import contextvars
import json
import os
import random

from fastapi import APIRouter, Depends, HTTPException, Request

from aidnd import config
from aidnd.items import Capability
from aidnd.mind import NpcConfig, NpcState
from aidnd.worldgen import WorldStore


async def _play_session(request: Request):
    """Зависимость всех /api/play/*: юзер по cookie → ЕГО мир → сессия мира в contextvar.
    Дев/тесты: AIDND_OPEN_PLAY=1 (или БД сервиса лежит) → общий мир 1 без входа."""
    uid, db_ok = None, True
    token = request.cookies.get("aidnd_session", "")
    try:
        from aidnd.server.auth import user_for_token
        from aidnd.server.db import SessionLocal

        async with SessionLocal() as db:
            if token:
                u = await user_for_token(db, token)
                uid = u.id if u else None
                request.state.user = u
    except Exception:  # noqa: BLE001 — сервисная БД лежит
        db_ok = False
    if uid is None:
        if os.environ.get("AIDND_OPEN_PLAY") or not db_ok:
            if 1 not in _SESS:
                dev_seed = int(_store().flag_get(0, "dev_seed") or 1)
                _SESS[1] = _fresh_sess(1, dev_seed)  # дев/демо: общий мир; сид растёт после смерти
            _CUR.set(_SESS[1])
            return
        raise HTTPException(401, "требуется вход")
    _UID.set(uid)
    u = getattr(request.state, "user", None)
    if u is not None and not u.unlimited and _llm_used(uid) >= config.DAILY_LLM:
        raise HTTPException(
            402, "дневной лимит рассказчика исчерпан — введи код на главной или возвращайся завтра"
        )
    row = _store().user_world(str(uid)) or _store().user_world_create(str(uid))
    wid, seed = row
    _CUR.set(_SESS.setdefault(wid, _fresh_sess(wid, seed)))


router = APIRouter(tags=["play"], dependencies=[Depends(_play_session)])
PLAYER = "pc"

_STORE: WorldStore | None = None
_POOL: WorldStore | None = None

# ЕДИНАЯ таблица баланса play-слоя (по образцу mind.value.BAL): все пороги/коэффициенты/времена
# ИМЕНОВАНЫ и живут здесь — не россыпью по коду.
PB = {
    "start_gt": 19 * 60 + 40,
    "start_coins": 12,
    "step_min": 1,
    "talk_min": 2,
    "loot_min": 2,
    "trade_min": 3,
    "act_min": 2,
    "live_tick_min": 3,
    "live_gap_s": 6.0,
    "give_min": 1,
    # цены: продать торговцу / купить у него (от ЕГО видения worth)
    "sell_base": 0.55,
    "sell_aff": 0.15,
    "sell_greed": -0.2,
    "buy_base": 1.35,
    "buy_greed": 0.25,
    "buy_aff": -0.15,
    # гейты преступлений
    "steal_dc_base": 9,
    "steal_dc_att": 8,
    "rob_dc_base": 10,
    "rob_dc_brav": 8,
    "purse_cut": 2,  # кража уносит 1/N кошеля
    "rob_cut_num": 2,
    "rob_cut_den": 3,  # грабёж уносит num/den
    # просьба ключа: bar = base + greed·k + honesty·k
    "askkey_base": 0.5,
    "askkey_greed": 0.4,
    "askkey_honesty": -0.2,
    # контракты
    "contract_enemy_aff": -0.1,
    "contract_poor_purse": 5,
    "contract_reward_min": 2,
    "complete_trust": 0.3,
    "complete_aff": 0.2,
    "befriend_aff": 0.25,
    "merchant_float": 30,
    "hostile_aff": -0.2,
    # распорядок жителей — из НУЖД (aidnd.society), не из вероятностей ролей (см. society/*)
    "live_llm_cap": 8,
    "impulse_llm": 1.0,  # дирижёр: LLM-ход только при импульсе выше порога (долг/нужда/беседа)
    "plan_cap": 3,  # цепочка звеньев из одной фразы: план длиннее — обрезаем
    # СДЕЛКИ игрока (deal-гейт): базовые DC/цены по видам, веса нрава/адекватности ставки
    "deal_dc_dead": 15,
    "deal_dc_bring": 11,
    "deal_dc_visit": 9,
    "deal_dc_befriend": 10,
    "deal_price_dead": 30,
    "deal_price_bring": 8,
    "deal_price_visit": 4,
    "deal_price_befriend": 6,
    "deal_honesty_k": 7,
    "deal_honesty_dead_k": 12,
    "deal_malice_dead_k": 8,
    "deal_adq_k": 5,
    "deal_adq_clamp": 6,  # адекватность ставки двигает DC максимум на ±6
    "deal_aff_k": 6,
    "deal_fear_k": 4,
    "deal_flat_honesty": 0.75,
    "deal_flat_malice": 0.35,  # честный и незлобный кровь не берёт БЕЗ броска
    "deal_kin_aff": 0.3,  # тёплые отношения с целью — «своих не трону»
    "deal_due_min": 1440,  # сутки на исполнение уговора
    "deal_night_min": 300,  # на кровь идут не раньше чем через 5 часов (ночью)
    "crime_solicit": 3,  # подстрекательство к убийству при отказе — розыск
    # ПОДСЛУШАТЬ (перцептивное звено): DC = база + шум зоны-цели; успех держится N тиков
    "listen_dc_base": 8,
    "listen_noise_k": 8,
    "listen_ticks": 3,
    "bg_feed_p": 0.25,  # фоновое занятие попадает в ленту с этой вероятностью (LOD)
    "here_show_cap": 12,
    # подарок: прирост симпатии = min(cap, base + worth/div)
    "gift_aff_base": 0.05,
    "gift_aff_div": 100,
    "gift_aff_cap": 0.25,
    # герой и логова
    "pc_max_hp": 18,
    "lairs": 5,
    "lair_cr_near": 0.8,
    "lair_cr_far": 3.0,
    "lair_travel_min": 25,
    "defeat_coin_cut": 2,
    "loot_coin_per_cr": 6,
    "loot_item_chance": 0.6,
    "combat_round_s": 5,  # 1 раунд боя = 5 секунд игрового времени
    "dungeon_waves": 2,  # логово = столько накатов врага
    "caravan_chance": 0.35,  # шанс каравана с товаром за утро
    "path_event_dc": 0.7,  # порог эмоции NPC, прерывающий путь
    "say_cap_per_tick": 3,  # не больше стольких реплик за живой тик (LOD ленты)
    # СТРАЖА / РОЗЫСК: вес преступлений (очки), порог задержания, спад/сутки, штраф, побег
    "crime_pickpocket": 1,
    "crime_rob": 3,
    "crime_assault": 4,
    "crime_murder": 8,
    "wanted_confront": 5,
    "wanted_decay": 2,
    "watch_fine_per_pt": 3,
    "watch_flee_dc": 12,
    "watch_jail_h": 7,  # не заплатил — «отсидка» до утра
    # МАГИЯ (мана-свеча): старт/потолок/реген/рост/усталость/сложность каста
    "mana_start": 12.0,
    "mana_cap_start": 14.0,
    "mana_hardcap_per_int": 8,  # потолок ≤ Int×8
    "mana_regen_base": 1.0,
    "mana_grow_frac": 0.1,
    "mana_sleep_mult": 3,  # сон наполняет свечу быстрее
    "fatigue_div": 8,
    "fatigue_min_per_pt": 24,  # усталость: 1+спалено/8 на статы, отходит
    # ЧЕРЧЕНИЕ (М-5.2): свеча тает ~drain/сек (мягче от Int+Wis) + вес глифа при нанесении;
    # известный круг из гримуара — мгновенно за долю сложности; выброс (маны 0) → misfire+усталость×mult
    "draw_drain_per_s": 1.5,
    "draw_intwis_k": 0.12,
    "known_cost_k": 0.6,
    "burnout_fat_mult": 2,
    # обучение глифам у мага/писца: цена = base + вес·k; ниже симпатии — не учит; высокая → даром
    "learn_base": 6,
    "learn_per_weight": 5,
    "learn_aff_min": -0.15,
    "learn_aff_free": 0.5,
    "taboo_witness": 2,  # атакующая магия при свидетелях → розыск
    "craft_skill_dc": 12,
    "craft_fail_min": 15,  # незнакомое ремесло: бросок Int / цена провала
    "guild_float": 120,
    "guild_reward_per_cr": 8,
    "guild_mark_fine": 15,
    # NPC-зачистки: шанс утреннего похода смелой пары
    "npc_delve_chance": 0.6,
    "npc_brave_min": 0.55,
    "fighter_roles": ("стражник", "охотник", "головорез", "бродяга", "наёмник"),
    "board_max_ads": 4,
    "board_npc_fulfill": 0.4,  # столб: потолок объявлений, шанс закрытия NPC
    "rest_cost": 2,
    "rest_until_h": 7,
    "tone_friendly_aff": 0.04,
    "tone_rude_aff": 0.08,
    "tone_threat_aff": 0.15,
    "tone_threat_fear": 0.2,
    "look_dc": 8,
    "look_good": 15,
}
_GT0 = PB["start_gt"]


def _gt() -> int:
    v = _S.get("gt")
    if v is None:  # холодный старт: время — ИЗ СЕЙВА, не с нуля
        row = _store().get_pc(_wid()) or {}  # (иначе распорядок/фаза дня строятся по 19:40)
        v = _S["gt"] = int(row.get("gt", _GT0))
    return v


def _gt_add(minutes: int) -> int:
    _S["gt"] = _gt() + max(0, int(minutes))
    return _S["gt"]


def _mt() -> int:
    return _gt() // 10  # такт памяти (halflife ретривы 144 такта ≈ сутки)


def _phase(gt: int | None = None) -> str:
    h = ((gt if gt is not None else _gt()) // 60) % 24
    return (
        "night"
        if h < 6
        else "morning"
        if h < 11
        else "day"
        if h < 17
        else "evening"
        if h < 22
        else "night"
    )


_PHASE_RU = {"morning": "утро", "day": "день", "evening": "вечер", "night": "ночь"}


def _store() -> WorldStore:
    """РАНТАЙМ миров (data/live.db, в гит не идёт): placements/items/flags/контракты/состояния."""
    global _STORE
    if _STORE is None:
        base = os.path.dirname(WorldStore().path)
        _STORE = WorldStore(os.path.join(base, "live.db"))
    return _STORE


def _pool() -> WorldStore:
    """КОНТЕНТ-ПУЛЫ (data/worlds.db, коммитится): банк людей, банк зданий."""
    global _POOL
    if _POOL is None:
        _POOL = WorldStore()
    return _POOL


# ------------------------------------------------ ИГРОК-АГЕНТ (pc_state) -- #
def _pc() -> NpcState:
    """Игрок — такой же агент: NpcState с памятью и отношениями. Персист в store."""
    if _S.get("pc") is None:
        st = NpcState.from_config(NpcConfig(id=PLAYER, name="ты", role="странник"))
        row = _store().get_pc(_wid())
        if row:
            st.relationships = row.get("relationships") or {}
            for m in row.get("memory") or []:
                mm = st.memory.add(
                    m["text"],
                    m["t"],
                    m.get("importance", 0.3),
                    kind=m.get("kind", "observation"),
                    about=m.get("about") or [],
                )
                mm.last_access = m.get("last_access", m["t"])
        _S["pc"] = st  # время НЕ трогаем: _gt() сам грузит из сейва
    return _S["pc"]


def _pc_hp(delta: int = 0, set_to: int | None = None) -> int:
    v = _S.get("pc_hp")
    if v is None:
        row = _store().get_pc(_wid()) or {}
        v = _S["pc_hp"] = row.get("hp", PB["pc_max_hp"])
    if set_to is not None:
        v = set_to
    v = max(0, min(PB["pc_max_hp"], v + delta))
    _S["pc_hp"] = v
    return v


def _pc_name() -> str:
    v = _S.get("pc_name")
    if v is None:
        v = _S["pc_name"] = (
            (_store().get_pc(_wid()) or {}).get("name") or "Странник"
        ).strip() or "Странник"
    return v


def _pc_set_name(name: str) -> None:
    _S["pc_name"] = str(name or "").strip()[:24] or "Странник"


_PC_CAP = Capability(abilities={"str": 10, "dex": 11, "con": 10, "int": 11, "wis": 11, "cha": 12})


# ------------------------------------------------------------ МАНА (магия) --- #
def _mana_hardcap() -> float:
    return _PC_CAP.abilities.get("int", 10) * PB["mana_hardcap_per_int"]  # предел роста от Int


def _mana_load() -> None:
    if _S.get("mana") is None:
        row = _store().get_pc(_wid()) or {}
        _S["mana"] = float(row.get("mana", PB["mana_start"]))
        _S["mana_cap"] = float(row.get("mana_cap", PB["mana_cap_start"]))
        _S["mana_gt"] = int(row.get("mana_gt", _gt()))
        _S["fat"] = int(row.get("fat", 0))
        _S["fat_until"] = int(row.get("fat_until", 0))


def _mana_rate() -> float:
    """Реген маны в час бодрствования — от Int/Wis."""
    return max(0.2, PB["mana_regen_base"] + _PC_CAP.mod("int") + _PC_CAP.mod("wis"))


def _mana() -> float:
    """Текущая мана с ЛЕНИВЫМ регеном от Int/Wis (без покадрового тика)."""
    _mana_load()
    dt_h = max(0, _gt() - _S["mana_gt"]) / 60.0
    if dt_h > 0:
        _S["mana"] = min(_S["mana_cap"], _S["mana"] + _mana_rate() * dt_h)
        _S["mana_gt"] = _gt()
    return round(_S["mana"], 2)


def _mana_sleep(hours: float) -> None:
    """Сон наполняет свечу быстрее бодрствования (×mana_sleep_mult): добор сверх ленивого регена."""
    _mana()  # ленивый реген за проспанное — по ставке ×1
    bonus = _mana_rate() * max(0.0, hours) * (PB["mana_sleep_mult"] - 1)
    _S["mana"] = min(_S["mana_cap"], _S["mana"] + bonus)


def _mana_cap() -> float:
    _mana_load()
    return round(_S["mana_cap"], 2)


def _mana_spend(amount: float) -> float:
    _S["mana"] = max(0.0, _mana() - float(amount))
    return round(_S["mana"], 2)


def _mana_grow(spent: float) -> None:
    """Рост потолка от выжигания (магия как мышца), до жёсткого предела Int×N."""
    if spent <= 0:
        return
    _S["mana_cap"] = min(
        _mana_hardcap(),
        _S["mana_cap"] + round(PB["mana_grow_frac"] * spent / max(1.0, _S["mana_cap"]), 3),
    )


def _fatigue() -> int:
    """Текущий штраф усталости ко ВСЕМ характеристикам (спадает со временем)."""
    _mana_load()
    if _gt() >= _S.get("fat_until", 0):
        _S["fat"], _S["fat_until"] = 0, 0
    return int(_S.get("fat", 0))


def _fat_add(spent: float) -> None:
    """Надрыв после каста: усталость по спалённой мане, длится дольше при большем выгорании."""
    pts = 1 + int(spent) // PB["fatigue_div"]
    _S["fat"] = _fatigue() + pts
    _S["fat_until"] = _gt() + pts * PB["fatigue_min_per_pt"]


# стартовый набор глифов игрока (§М1e): хватает на огненную стрелу и лечение; остальное — учить
_STARTER_GLYPHS = ("огонь", "свет", "стрела", "исцелить", "больше")


def _glyphs_known() -> list:
    """Глифы, которыми ВЛАДЕЕТ игрок (персист в pc_state); прочие надо выучить у мага."""
    if _S.get("glyphs") is None:
        row = _store().get_pc(_wid()) or {}
        g = row.get("glyphs")
        _S["glyphs"] = list(dict.fromkeys(g if g is not None else _STARTER_GLYPHS))
    return list(_S["glyphs"])


def _glyph_learn(gid: str) -> bool:
    """Добавить глиф в арсенал игрока. True — впервые выучен, False — уже знал."""
    known = _glyphs_known()
    if gid in known:
        return False
    _S["glyphs"] = known + [gid]
    return True


def _pc_cap_eff():
    """Способности игрока С УЧЁТОМ усталости (для новых бросков/каста) — все статы просажены."""
    fat = _fatigue()
    if not fat:
        return _PC_CAP
    from aidnd.items import Capability

    return Capability(
        abilities={k: max(1, v - fat) for k, v in _PC_CAP.abilities.items()},
        competencies=_PC_CAP.competencies,
        tools=_PC_CAP.tools,
    )


def _pc_save() -> None:
    st = _pc()
    _mana_load()
    _store().save_pc(
        _wid(),
        {
            "gt": _gt(),
            "hp": _pc_hp(),
            "name": _pc_name(),
            "relationships": st.relationships,
            "mana": round(_S["mana"], 2),
            "mana_cap": round(_S["mana_cap"], 2),
            "mana_gt": _S["mana_gt"],
            "fat": _S.get("fat", 0),
            "fat_until": _S.get("fat_until", 0),
            "glyphs": _glyphs_known(),
            "loc": _S.get("loc"),
            "inside": _S.get("inside"),
            "room": _S.get("room"),  # позиция переживает рестарт
            "zone": _S.get("zone"),
            "memory": [
                {
                    "text": m.text,
                    "t": m.t,
                    "importance": m.importance,
                    "last_access": m.last_access,
                    "kind": m.kind,
                    "about": m.about,
                }
                for m in st.memory.items[-400:]
            ],
        },
    )  # хвост — журнал не разрастается бесконечно


def _met() -> set:
    return set(_pc().relationships)


def _pc_remember(text: str, importance: float = 0.3, about=None, kind: str = "observation") -> None:
    _pc().memory.add(text, _mt(), importance, kind=kind, about=list(about or []))
    _pc_save()


def _npc_save(pid: str) -> None:
    """Прожитое NPC (память/отношения/нужды) → БД: переживает рестарт сервера."""
    p = (_S.get("people") or {}).get(pid)
    if not p:
        return
    st = p.state
    _store().save_npc_state(
        _wid(),
        pid,
        {
            "relationships": st.relationships,
            "needs": st.needs,
            "memory": [
                {
                    "text": m.text,
                    "t": m.t,
                    "importance": m.importance,
                    "last_access": m.last_access,
                    "kind": m.kind,
                    "about": m.about,
                }
                for m in st.memory.items[-200:]
            ],
        },
    )


_SESS: dict = {}  # world_id → сессия мира (в памяти)
_CUR = contextvars.ContextVar("play_sess", default=None)
_UID = contextvars.ContextVar("play_uid", default=None)


def _llm_day_key(uid) -> str:
    import time as _t

    return f"llm|{uid}|{_t.strftime('%Y%m%d')}"


def _llm_used(uid) -> int:
    return int(_store().flag_get(0, _llm_day_key(uid)) or 0)


def _llm_hook(role, model) -> None:
    """Каждый LLM-вызов в игровом контуре — тик счётчика пользователя (лимит без кода)."""
    uid = _UID.get()
    if uid is not None:
        _store().flag_set(0, _llm_day_key(uid), str(_llm_used(uid) + 1))


def _fresh_sess(wid: int, seed: int) -> dict:
    return {
        "wid": wid,
        "seed": seed,
        "city": None,
        "people": None,
        "crof": None,
        "cr2b": None,
        "loc": None,
        "geom": None,
        "model": None,
    }


class _SessProxy:
    """Код по-прежнему говорит _S[...] — за ним стоит сессия ТЕКУЩЕГО мира (contextvar).
    Вне auth-контура (тесты/дев) — общий мир 1."""

    def _d(self) -> dict:
        d = _CUR.get()
        if d is None:
            d = _SESS.setdefault(1, _fresh_sess(1, 1))
            _CUR.set(d)
        return d

    def __getitem__(self, k):
        return self._d()[k]

    def __setitem__(self, k, v):
        self._d()[k] = v

    def __contains__(self, k):
        return k in self._d()

    def get(self, k, default=None):
        return self._d().get(k, default)

    def setdefault(self, k, default=None):
        return self._d().setdefault(k, default)

    def pop(self, k, default=None):
        return self._d().pop(k, default)

    def update(self, *a, **kw):
        self._d().update(*a, **kw)


_S = _SessProxy()


def _wid() -> int:
    return _S["wid"]


def current_world_id():
    """ID мира текущего запроса (для тегирования логов) или None вне play-сессии."""
    s = _CUR.get()
    return s.get("wid") if s else None


_COLORS = ["#c98a52", "#6f8f6a", "#8a6fae", "#a86a6a", "#5f8296", "#b0894a"]


def _binfo(bid: str | None) -> dict:
    """Имя/вид/метка места — из ФАКТШИТА здания (enrichment генерит name/atmosphere/type),
    не из кода. Фоллбэк — вывеска графа."""
    bd = _store().get_building(_wid(), bid) if bid else None
    data = (bd or {}).get("data") or {}
    name = data.get("name") or (bd or {}).get("sign") or "Здание"
    kind = data.get("atmosphere") or data.get("type") or "постройка"
    label = (data.get("type") or "дом").split(",")[0].split()[0][:12]
    return {"name": name, "kind": kind, "label": label}


# тип здания (из фактшита) → роль работника; таблица данных, порядок = приоритет совпадения
_TYPE_ROLE = (
    ("таверн", "трактирщик"),
    ("трактир", "трактирщик"),
    ("постоял", "трактирщик"),
    ("оружейн", "оружейник"),
    ("лавк", "лавочник"),
    ("склад", "лавочник"),
    ("кузн", "кузнец"),
    ("храм", "жрец"),
    ("свят", "жрец"),
    ("часовн", "жрец"),
    ("башн", "маг"),
    ("магич", "маг"),
    ("колдун", "маг"),
    ("чароде", "маг"),
    ("аркан", "маг"),
    ("обсерватор", "маг"),
    ("писц", "писец"),
    ("писар", "писец"),
    ("фолиант", "писец"),
    ("свиток", "писец"),
    ("целебн", "знахарка"),
    ("знахар", "знахарка"),
    ("травн", "знахарка"),
    ("мельниц", "мельник"),
    ("пекарн", "трактирщик"),
    ("мастерск", "сапожник"),
    ("кожевн", "дубильщик"),
    ("дубильн", "дубильщик"),
    ("конюшн", "горожанин"),
    ("усадьб", "горожанин"),
    ("гильди", "стражник"),
)

# роли, что учат магии (§М-4): маг в башне — стихиям и глифам; писец — «глаголам» письма
TEACHER_ROLES = ("маг", "писец", "писарь")


def _role_for_building(bid: str) -> str:
    """Роль работника — ИЗ ДАННЫХ здания (тип/имя из фактшита), не по порядковому кругу."""
    info = _binfo(bid)
    t = (info["kind"] + " " + info["name"]).lower()
    return next((r for w, r in _TYPE_ROLE if w in t), "горожанин")


def _city_name() -> str:
    v = _S.get("city_name")
    if v is None:
        v = _store().flag_get(_wid(), "city_name")
        if not v:  # новый мир: имя — из ПУЛА имён (без LLM)
            names = _pool().pool_buildings("city_name")
            if names:
                v = random.Random(f"cname|{_wid()}").choice(names)["data"]["name"]
                _store().flag_set(_wid(), "city_name", v)
        v = _S["city_name"] = v or "городок"
    return v


def _seen() -> set:
    if _S.get("seen") is None:
        _S["seen"] = {k.split("|", 1)[1] for k in _store().flags_prefix(_wid(), "seen|")}
    return _S["seen"]


def _mark_seen(bid: str | None) -> None:
    """Туман войны: локация становится известной (метка на карте), когда игрок её УЗНАЛ —
    пришёл сам или услышал от людей/справки."""
    if bid and bid not in _seen():
        _S["seen"].add(bid)
        _store().flag_set(_wid(), f"seen|{bid}")


def _topics_for(p) -> list:
    """Темы разговора — из ПЕРСОНЫ (слухи/стремления), не из таблицы ролей."""
    per = p.persona or {}
    out = [t[:40] for t in (per.get("rumors") or [])[:2]] + [
        t[:40] for t in (per.get("wants") or [])[:1]
    ]
    return out or ["что нового?", "о городе", "о жизни здесь"]


def _spurns(p) -> bool:
    """Не желает иметь с тобой дела: вражда или свежий адресный гнев."""
    rel = p.state.relationships.get(PLAYER) or {}
    ang = p.state.emotion.get("anger", 0)
    return rel.get("affinity", 0) < PB["hostile_aff"] or (
        ang > 0.5 and p.state.emotion_target.get("anger") == PLAYER
    )


_DM_SYS = (
    "Ты — мастер настольной игры. Игрок заявил действие, которое НЕ ИСПОЛНЯЕТСЯ механикой — "
    "мир от него НЕ изменится. Тебе дан СНИМОК живой сцены (место, время, люди и их занятия, "
    "последние реплики, предметы рядом) — это ЕДИНСТВЕННАЯ правда: опирайся на неё и вплетай её "
    "детали (кто рядом чем занят, что слышно), НИЧЕГО не выдумывай сверх снимка и не противоречь "
    "ему (если люди греются у очага — очаг горит). Ответь 1-2 фразами: 2-е лицо, настоящее время, "
    "сухо. НИКОГДА не подтверждай свершение заявленного (особенно разрушительного): покажи, почему "
    "оно не происходит или на чём останавливается — либо, для созерцательного, что игрок видит."
)


def _model():
    if _S["model"] is None:
        from aidnd.inference import ModelManager

        mgr = ModelManager()
        mgr.on_call = _llm_hook  # каждый вызов — тик лимита юзера
        _S["model"] = mgr
    return _S["model"]


def _inscriber():
    """Инскриптор магии (роль А — закон круга, роль Б — дикий хаос). Только LLM — без фоллбэков."""
    if _S.get("inscriber") is None:
        from aidnd.magic import LLMInscriber

        _S["inscriber"] = LLMInscriber(_model())
    return _S["inscriber"]


def _grimoire_get(h: str) -> dict | None:
    """Вписанный закон круга (по хэшу состава) для текущего мира — или None."""
    raw = _store().flag_get(_wid(), f"grim|{h}")
    return json.loads(raw) if raw else None


def _grimoire_put(h: str, entry: dict) -> None:
    _store().flag_set(_wid(), f"grim|{h}", json.dumps(entry, ensure_ascii=False))


def _grimoire_list() -> list:
    """Все вписанные в мир круги (гримуар игрока), в порядке первого творения."""
    out = []
    for v in _store().flags_prefix(_wid(), "grim|").values():
        try:
            out.append(json.loads(v))
        except (ValueError, TypeError):
            pass
    return sorted(out, key=lambda e: e.get("first_gt", 0))


def _in_room(where: str, room: str | None, rooms: list) -> bool:
    """Ёмкость принадлежит помещению: по совпадению слов комнаты в where (падежи не мешают);
    иначе — общий зал."""
    wt = _tokens_ru(where)
    if room:
        return bool(_tokens_ru(room) & wt)
    return not any(_tokens_ru(r["name"]) & wt for r in rooms)  # в зале — не привязанное к комнатам


def _role_at(node, people, spot, n2b):
    bid = n2b.get(node)
    if not bid:
        return None
    return next(
        (people[pid].role for pid, s in spot.items() if s == node and people[pid].work == bid), None
    )


def _here(node, spot):
    return [pid for pid, s in spot.items() if s == node]


def _emo(st) -> str:
    e = st.emotion
    dom = max(e, key=e.get)
    if e[dom] < 0.15:
        return "спокойное"
    return {
        "joy": "тёплое",
        "anger": "раздражённое",
        "fear": "настороженное",
        "distress": "подавленное",
    }.get(dom, "ровное")


_PORT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "portraits")


def _portrait_url(p, emo: str | None = None) -> str | None:
    """URL портрета NPC под эмоцию (статика /portraits). None, если файла нет на диске —
    так прод без ещё не залитых картинок отдаёт инициалы, а не битые ссылки (персона живёт в БД)."""
    ports = getattr(p, "portraits", None) or {}
    if not ports:
        return None
    key = emo if emo in ports else "спокойное" if "спокойное" in ports else next(iter(ports))
    rel = ports[key]
    return "/portraits/" + rel if os.path.exists(os.path.join(_PORT_DIR, rel)) else None


def _tokens_ru(s: str) -> set:
    """Грубый стем: префикс-5 (падежи не мешают «медяки»↔«медяков»)."""
    return {
        w[:5] for w in str(s).lower().replace("«", " ").replace("»", " ").split() if len(w) >= 4
    }


def _wanted() -> int:
    return int(_store().flag_get(_wid(), "wanted|pc") or 0)


def _wanted_add(pts: int, reason: str = "") -> None:
    """Очки розыска: копятся от засвидетельствованных преступлений, спадают со временем."""
    _store().flag_set(_wid(), "wanted|pc", str(max(0, _wanted() + int(pts))))
    if reason and pts > 0:  # хроника — для реплики стражи
        prior = _store().flag_get(_wid(), "crimes|pc") or ""
        _store().flag_set(
            _wid(), "crimes|pc", ((prior + "; " + reason) if prior else reason)[-240:]
        )


def _wanted_clear() -> None:
    _store().flag_set(_wid(), "wanted|pc", "0")
    _store().flag_set(_wid(), "crimes|pc", "")


def _witness_crime(people, crof, loc, npc, what: str, weight: int = 2) -> int:
    """Преступление на глазах: жертва в гневе, свидетели пишут память (сплетни разнесут),
    очки розыска растут (жертва доносит + чем больше глаз, тем жарче)."""
    p = people[npc]
    rel = p.state.rel(PLAYER)
    rel["affinity"] = min(rel["affinity"], -0.5)
    p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.7)
    p.state.emotion_target["anger"] = PLAYER
    p.state.memory.add(f"чужак {what} — я этого не забуду!", _mt(), 0.9, about=[PLAYER])
    wit = [w for w in _here(loc, crof) if w != npc]
    for w in wit:
        people[w].state.memory.add(
            f"видел(а): чужак {what} ({p.name})", _mt(), 0.6, about=[PLAYER, npc]
        )
        _npc_save(w)
    _npc_save(npc)
    _wanted_add(weight + min(3, len(wit)), what)  # жертва + очевидцы → розыск
    return len(wit)


def _descriptor(p) -> str:
    """Незнакомец различим ГЛАЗАМИ: пол + УНИКАЛЬНАЯ примета (look.marks/hair/face из персоны),
    одежда — вторично. Три «мужика в балахонах» должны быть тремя разными людьми."""
    per = p.persona or {}
    look = per.get("look") or {}
    sex = "женщина" if per.get("sex") == "f" else "мужчина"
    mark = ""
    for src in ((look.get("marks") or [None])[0], look.get("hair"), look.get("face")):
        if src and str(src).strip():
            mark = str(src).split(",")[0].strip().lower()
            break
    cloth = (look.get("clothing") or "").split(",")[0].strip()
    if mark:
        return f"{sex} — {mark}"
    return f"{sex} ({cloth})" if cloth else sex


def _scene_descriptors(people, pids) -> dict:
    """Дескрипторы, РАЗЛИЧАЮЩИЕ незнакомцев в ЭТОЙ сцене: пул штампует «шрам на щеке» половине
    города — жадно выбираем каждому примету КАТЕГОРИИ, ещё не занятой соседями по сцене
    (метка → волосы → лицо → одежда → сложение); всё занято — склеиваем две приметы."""
    used: set = set()
    out: dict = {}
    for pid in sorted(pids):
        p = people.get(pid)
        per = (p.persona or {}) if p else {}
        look = per.get("look") or {}
        sex = "женщина" if per.get("sex") == "f" else "мужчина"
        cands = []
        for c in ((look.get("marks") or [None])[0], look.get("hair"), look.get("face"),
                  look.get("clothing"), per.get("build")):
            c = str(c).split(",")[0].strip().lower() if c and str(c).strip() else ""
            if c:
                cands.append(c)
        pick = None
        for c in cands:
            cat = c.split()[0][:5]                     # категория = стем первого слова («шрам…»)
            if cat not in used:
                used.add(cat)
                pick = c
                break
        if pick is None and cands:                     # все категории заняты — двойная примета
            pick = cands[0] + (", " + cands[1] if len(cands) > 1 else "")
        out[pid] = f"{sex} — {pick}" if pick else sex
    return out


def _display(pid: str, people) -> str:
    if pid == PLAYER:
        return "ты"
    p = people.get(pid)
    if not p:
        return "прохожий"  # неизвестный в этой сцене — но НИКОГДА не сырой id
    if pid in _met():
        return p.name
    d = ((_S.get("live") or {}).get("descr") or {}).get(pid)  # сцен-дескриптор различает соседей
    return d or _descriptor(p)
