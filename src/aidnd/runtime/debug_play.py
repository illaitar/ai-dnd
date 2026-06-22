"""Консольный режим отладки: авто-прогон сессии (взять квест и выполнить его).

Запуск:  python -m aidnd debug            (по умолчанию ТРЕБУЕТ онлайн-сервер модели)
         python -m aidnd debug --offline  (детерминированные фоллбэки, для CI/сравнения)

Это диагностический прогон, а не игра: драйвер сам ведёт персонажа по сценарию
(дойти до доски объявлений → принять задание → выполнить требование → сдать), печатая
каждый шаг с типом результата, нарративом и дельтой состояния квеста. Любые расхождения
(исключения, неверная маршрутизация интента, не продвинувшийся квест, неначисленная
награда, пустой нарратив) собираются в отчёт «ПРОБЛЕМЫ» в конце.

Намеренно гоняем команды через `session.handle(...)` свободным текстом — так в прогоне
реально участвуют LLM-агенты (intent → narrator → cognition), и мы видим их огрехи; а
сам каркас квеста дёргаем структурными методами (`accept_quest`/`turn_in_quest`), чтобы
отделить «сломалась механика квеста» от «модель не так поняла фразу».
"""

from __future__ import annotations

from .. import config
from ..bootstrap import new_session
from ..gen.seeds import subseed
from ..rules.dice import roll_expr

BOARD_PLACE = "building:notice_board"
SHRINE_PLACE = "building:shrine_of_luck"
DEMO_QUEST = "quest:board_garaele"      # «поговорить с сестрой Гарэле» — самый показательный цикл


def _short(text: str | None, limit: int = 600) -> str:
    t = (text or "").strip()
    return t if len(t) <= limit else t[:limit].rstrip() + " …"


class DebugDriver:
    """Обёртка над сессией: ведёт сценарий, печатает шаги, копит проблемы."""

    def __init__(self, session, require_model: bool) -> None:
        self.s = session
        self.require_model = require_model
        self.issues: list[str] = []
        self.n = 0
        self._salt = 1

    # --------------------------------------------------------------- вывод ---
    def step(self, title: str) -> None:
        self.n += 1
        print(f"\n{'─' * 70}\n[{self.n:02d}] {title}\n{'─' * 70}")

    def info(self, msg: str) -> None:
        print(f"     {msg}")

    def ok(self, msg: str) -> None:
        print(f"     ✓ {msg}")

    def issue(self, msg: str) -> None:
        self.issues.append(msg)
        print(f"     ⚠ ПРОБЛЕМА: {msg}")

    def check(self, cond: bool, ok_msg: str, bad_msg: str) -> bool:
        (self.ok if cond else self.issue)(ok_msg if cond else bad_msg)
        return cond

    # ------------------------------------------------------------ команды ---
    def _resolve_rolls(self, result: dict) -> dict:
        """Автодокрут приостановленных бросков (server-animated, воспроизводимо)."""
        while isinstance(result, dict) and result.get("kind") == "roll_request":
            rr = result["roll_request"]
            seed = subseed(0, rr["request_id"], self._salt) & 0x7FFFFFFF
            faces = roll_expr(rr["request_id"], rr["dice"], seed, source="debug").raw
            dc = f" против DC {rr['dc']}" if rr.get("dc") is not None else ""
            self.info(f"🎲 {rr['dice']} (мод {rr['modifier']:+d}){dc} → {faces}")
            self._salt += 1
            result = self.s.submit_roll(faces)
        return result

    def cmd(self, text: str) -> dict:
        """Свободный текст игрока → handle (через LLM-агентов) → печать результата."""
        print(f"     ⌨  «{text}»")
        try:
            result = self._resolve_rolls(self.s.handle(text))
        except Exception as e:  # noqa: BLE001 — в отладке ловим всё, чтобы прогон не падал
            import traceback
            self.issue(f"исключение в handle({text!r}): {e!r}")
            traceback.print_exc()
            return {"kind": "error", "text": ""}
        self._salt += 5
        kind = result.get("kind", "?")
        body = _short(result.get("text"))
        self.info(f"→ kind={kind}")
        if body:
            print("       " + body.replace("\n", "\n       "))
        else:
            self.issue(f"пустой нарратив на «{text}» (агент-нарратор вернул пусто?)")
        return result

    # ------------------------------------------------------------ запросы ---
    @property
    def place(self) -> str:
        return self.s.current_place()

    def quest(self, qid: str):
        return self.s.world.quests.get(qid)

    def qsig(self, qid: str) -> str:
        q = self.quest(qid)
        return "нет квеста" if not q else f"state={q.state} stages={q.current_stages}"

    def player_xp(self) -> int:
        return self.s.view()["player"].get("xp", 0)

    def player_gp(self) -> int:
        return self.s.world.wallet(self.s.player).get("gp", 0)

    def goto(self, phrase: str, expect: str, label: str) -> None:
        """Перейти по свободной фразе и убедиться, что дошли куда нужно."""
        before = self.place
        self.cmd(phrase)
        if self.place == expect:
            self.ok(f"на месте: {label} ({expect})")
        elif before == expect:
            self.ok(f"уже был на месте: {label}")
        else:
            self.issue(f"не дошёл до «{label}»: ожидалось {expect}, "
                       f"сейчас {self.place} (интент свёл фразу не туда / маршрут не найден)")
            # форсируем приход точным именем места, чтобы сценарий продолжился
            name = self.s._place_name(expect)
            self.info(f"форсирую переход точным именем: «иди в {name}»")
            self.cmd(f"иди в {name}")
            self.check(self.place == expect, f"форс-переход удался ({expect})",
                       f"форс-переход не сработал, сейчас {self.place}")

    # ------------------------------------------------------------ сценарий ---
    def preflight(self) -> bool:
        self.step("Преполётная проверка: сервер с моделями")
        online = bool(self.s.model and self.s.model.available())
        print(f"     OLLAMA_HOST : {config.OLLAMA_HOST}")
        print(f"     BASE_MODEL  : {config.BASE_MODEL}")
        print(f"     INTENT_MODEL: {config.INTENT_MODEL}")
        if online:
            try:
                models = self.s.model.client.list_models()
                self.info(f"модели на сервере: {models}")
            except Exception as e:  # noqa: BLE001
                self.info(f"(список моделей недоступен: {e!r})")
            self.ok("сервер модели ONLINE — агенты intent/narrator/cognition активны")
            return True
        if self.require_model:
            self.issue("сервер модели НЕ ДОСТУПЕН, а режим требует онлайн "
                       "(подними туннель к Ollama или запусти с --offline)")
            return False
        self.info("сервер OFFLINE — идём на детерминированных фоллбэках (--offline)")
        return True

    def play_quest(self) -> None:
        s = self.s

        self.step("Старт: осмотреться")
        look = s.look()
        self.info(f"место: {look.get('place_name')} ({look.get('place')})")
        self.info("NPC рядом: " + (", ".join(n["name"] for n in look.get("npcs", [])) or "никого"))
        self.info("выходы: " + ", ".join(e["name"] for e in look.get("exits", [])))
        xp0, gp0 = self.player_xp(), self.player_gp()
        self.info(f"персонаж: XP={xp0}, золото={gp0}")

        self.step("Идём к доске объявлений")
        self.goto("подойти к доске объявлений", BOARD_PLACE, "Доска объявлений")

        self.step("Смотрим задания на доске")
        board = s.board_view()
        if not self.check(board is not None, "доска доступна (board_view вернул список)",
                          "board_view вернул None — доска не распознаётся на этом месте"):
            return
        for q in board["quests"]:
            flags = []
            if q["can_accept"]:
                flags.append("можно взять")
            if q["can_turn_in"]:
                flags.append("можно сдать")
            self.info(f"• [{q['req_kind']}] {q['title']} — {q['objective']} "
                      f"(награда: {q['reward']}) [{', '.join(flags) or q['state']}]")

        self.step(f"Принимаем задание {DEMO_QUEST}")
        q = self.quest(DEMO_QUEST)
        if not self.check(q is not None, f"квест найден: «{q.title if q else '?'}»",
                          f"в мире нет квеста {DEMO_QUEST}"):
            return
        self.info(f"до принятия: {self.qsig(DEMO_QUEST)}")
        res = s.accept_quest(DEMO_QUEST)
        self.info("→ " + _short(res.get("text")))
        q = self.quest(DEMO_QUEST)
        self.check(q.state == "active", f"квест принят: {self.qsig(DEMO_QUEST)}",
                   f"квест не перешёл в active: {self.qsig(DEMO_QUEST)}")
        self.check(q.current_stages == ["do"], "активна стадия требования «do»",
                   f"неожиданная стартовая стадия: {q.current_stages}")

        self.step("Идём в Святилище Удачи к сестре Гарэле")
        self.goto("иди в святилище удачи", SHRINE_PLACE, "Святилище Удачи")
        here = [n for n in s.npcs_here()]
        self.info("NPC здесь: " + (", ".join(s._display(n) for n in here) or "никого"))
        if "npc:sister_garaele" not in here:
            self.issue("сестры Гарэле нет в святилище — требование не выполнить разговором")

        self.step("Выполняем требование: разговор с сестрой Гарэле")
        before = self.qsig(DEMO_QUEST)
        self.cmd("поговорить с сестрой Гарэле")
        talked = "talked:npc:sister_garaele" in s.world.flags
        if not talked:
            # фолбэк: повторяем фактическим отображаемым именем (как в goto). Если помогло —
            # это сигнал, что распознавание ссылки на NPC по русскому тексту хромает.
            disp = s._display("npc:sister_garaele")
            self.info(f"разговор не зачёлся — повтор точным именем: «поговорить с {disp}»")
            self.cmd(f"поговорить с {disp}")
            talked = "talked:npc:sister_garaele" in s.world.flags
            if talked:
                self.issue("ссылку «сестрой Гарэле» NPC-матч не распознал; помог только "
                           "точный показ-name — стоит сматчить рус. имя/эпитет с id NPC")
        self.check(talked, "флаг разговора выставлен (talked:npc:sister_garaele)",
                   "флаг разговора НЕ выставлен — TalkedTo не сработает")
        q = self.quest(DEMO_QUEST)
        self.info(f"стадии: было {before} → стало {self.qsig(DEMO_QUEST)}")
        self.check(q.current_stages == ["turnin"],
                   "требование зачтено, квест ждёт сдачи (стадия «turnin»)",
                   f"квест не продвинулся к сдаче: {q.current_stages}")

        self.step("Возвращаемся к доске и сдаём задание")
        self.goto("вернуться к доске объявлений", BOARD_PLACE, "Доска объявлений")
        xp1, gp1 = self.player_xp(), self.player_gp()
        res = s.turn_in_quest(DEMO_QUEST)
        self.info("→ " + _short(res.get("text")))
        q = self.quest(DEMO_QUEST)
        self.check(q.state == "completed", f"квест завершён: {self.qsig(DEMO_QUEST)}",
                   f"квест не завершился: {self.qsig(DEMO_QUEST)}")

        self.step("Сверяем награду")
        xp2, gp2 = self.player_xp(), self.player_gp()
        want_xp, want_gp = q.rewards.xp, int(q.rewards.currency.get("gp", 0))
        self.info(f"XP: {xp1} → {xp2} (ожидали +{want_xp})")
        self.info(f"Золото: {gp1} → {gp2} (ожидали +{want_gp})")
        self.check(xp2 - xp1 == want_xp, f"XP начислены верно (+{want_xp})",
                   f"XP начислены неверно: дельта {xp2 - xp1}, ожидали +{want_xp}")
        self.check(gp2 - gp1 == want_gp, f"золото начислено верно (+{want_gp})",
                   f"золото начислено неверно: дельта {gp2 - gp1}, ожидали +{want_gp}")

    def report(self) -> int:
        self.step("ИТОГ")
        if not self.issues:
            print("     ✅ Проблем не обнаружено — квест взят и выполнен от начала до конца.")
            return 0
        print(f"     ❌ Найдено проблем: {len(self.issues)}")
        for i, m in enumerate(self.issues, 1):
            print(f"        {i}. {m}")
        return 1


def run(offline: bool = False) -> int:
    """Точка входа консольного debug-режима. Возвращает код выхода (0 — без проблем)."""
    print("=" * 70)
    print(" AI-DnD — КОНСОЛЬНЫЙ РЕЖИМ ОТЛАДКИ (авто-прогон квеста)")
    print("=" * 70)
    require_model = not offline
    session = new_session(seed=config.WORLD_SEED, roster_size=12, use_model=not offline)
    drv = DebugDriver(session, require_model=require_model)
    if not drv.preflight():
        return drv.report()
    try:
        drv.play_quest()
    except Exception as e:  # noqa: BLE001
        import traceback
        drv.issue(f"необработанное исключение в сценарии: {e!r}")
        traceback.print_exc()
    return drv.report()
