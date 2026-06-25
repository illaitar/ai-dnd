"""Оркестратор и главный игровой цикл (main §8, док 07 §4).

Пайплайн хода: intent → resolver(легальность) → [возможен бросок игрока] →
rules.resolve → world.apply → cognition.observe/appraise → narrator.render.
Шаг оценки содержит бросок посередине: при нужде возвращается RollRequest и ход
приостанавливается до RollResult (док 07 §4).

LLM-пути (intent-парсер, нарратор, когниция) имеют детерминированные фоллбэки,
поэтому всё работает без сервера модели.
"""

from __future__ import annotations

from .. import config, ids
from ..cognition import Cognition, CognitionStore
from ..combat import CombatEngine
from ..gen import CharacterGenerator, QuestSystem
from ..inventory import container as inv
from ..lod import LODManager
from ..lod.smart_objects import fast_forward
from ..rules import Action, DiceService, RulesEngine
from ..rules.dice import RollResult, validate_player_roll
from ..world.components import Persona
from .director import Director

# ключевые слова интента (фоллбэк интент-парсера, main §12.1).
# Порядок ВАЖЕН: специфичные/враждебные глаголы раньше «talk», иначе «запугать…
# говори!» ловится на «говор» как разговор. Сначала attack/intimidate/persuade.
VERB_KEYWORDS = {
    "move": ["иди", "идти", "иду", "пойд", "go ", "move", "войти", "зайти", "направ",
             "подойд", "подойт", "подход", "верну", "вернис", "двигай", "топай"],
    "attack": ["бью", "атак", "напад", "ударь", "attack", "kill", "убить", "руб"],
    "intimidate": ["запуга", "угрож", "intimidate", "припугн"],
    "persuade": ["убеди", "уговор", "persuade", "договор"],
    "deceive": ["обман", "соврат", "притвор", "блеф", "выдать себя", "deceive", "приврат"],
    "talk": ["поговор", "говор", "спрос", "talk", "ask", "обрат", "привет"],
    "inspect": ["осмотр", "осматр", "смотр", "look", "examine", "оглядет", "разгляд", "рассматр"],
    "search": ["обыск", "ищу", "иска", "search", "найти", "пошарь"],
    "loot": ["лут", "обобрать", "loot", "забрать", "открыть сундук", "обыскать труп"],
    "buy": ["купить", "куплю", "buy", "приобрес"],
    "sell": ["продать", "продаю", "sell"],
    "inventory": ["инвентар", "инв", "inventory", "сумк", "рюкзак"],
    "wait": ["ждать", "жду", "wait", "отдых", "rest", "ждём"],
    "drink": ["выпить", "выпью", "выпивк", "эля", "эль", "пива", "пиво", "налей", "пинт",
              "кружк", "браг", "вина", "вискар", "хмель"],
}


class GameSession:
    """Синхронный фасад движка для CLI и WebSocket-сервера."""

    def __init__(self, world, model=None, quest_system: QuestSystem | None = None) -> None:
        self.world = world
        self.model = model
        self.dice = DiceService(world)
        self.rules = RulesEngine(world, self.dice)
        self.lod = LODManager(world)
        self.cog_store = CognitionStore()
        self.cognition = Cognition(world, self.cog_store, model)
        self.charts = CharacterGenerator(world, model)
        from ..gen import DiscoveryService
        self.discovery = DiscoveryService(world, self.dice, self.charts)
        self.quests = quest_system or QuestSystem(world)
        self.director = Director(world, self.quests, model)
        self.combat: CombatEngine | None = None
        self.pending_roll: dict | None = None     # приостановленный ход на бросок
        self.player = world.player_id or "pc:hero"
        self.dialogue_partner: str | None = None  # с кем сейчас идёт разговор
        self._last_item: str | None = None        # последний осмотренный предмет (для «на нём…»)
        self._history: list[dict] = []            # последние ходы (ввод/ответ) — контекст для роутера
        self.journal: list[str] = []              # журнал событий игрока (read-model)
        self._quest_log_seen = 0                  # сколько строк журнала квестов уже втянуто
        self.quiet_ticks = 0                      # длина затишья для нарративного темпа
        self._log_journal("Ты прибыл в Фэндалин — фронтирный городок у Мечового Берега.")

    # ===================================================================== #
    #  Восприятие сцены                                                     #
    # ===================================================================== #
    def current_place(self) -> str:
        pos = self.world.position(self.player)
        return pos.place_id if pos else "place:phandalin_square"

    def npcs_here(self) -> list[str]:
        place = self.current_place()
        out = []
        for npc in self.world.npcs():
            pos = self.world.position(npc)
            if pos and pos.place_id == place and self.world.is_alive(npc):
                out.append(npc)
        return out

    def exits(self) -> list[str]:
        """Связанные локации из графа связности (порталы текущего узла)."""
        return self.world.spatial.connections(self.current_place())

    def _companions(self) -> list[str]:
        """Спутники партии (Persona.companion) — следуют за игроком и бьются рядом."""
        return [n for n in self.world.npcs()
                if (p := self.world.ecs.get(n, Persona)) and p.companion
                and self.world.is_alive(n)]

    # человекочитаемые взаимодействия с окружением по аффордансам места
    AFFORD_LABEL = {
        "inn": "отдохнуть и перекусить", "drink": "выпить", "eat": "поесть",
        "serve": "снять комнату", "shop": "посмотреть товар", "work": "оглядеть работу",
        "sleep": "лечь спать до утра",
        "shrine": "помолиться", "townhall": "справиться о делах города",
        "manor": "осмотреть поместье", "hideout": "искать тайный ход",
        "farm": "оглядеть хозяйство", "combat": "осмотреть поле боя",
    }

    def affordances_here(self) -> list[dict]:
        """Что можно сделать с окружением в текущем месте (smart-object аффордансы)."""
        p = self.world.spatial.places.get(self.current_place())
        out, seen = [], set()
        for a in (p.affordances if p else []):
            lbl = self.AFFORD_LABEL.get(a)
            if lbl and lbl not in seen:
                out.append({"affordance": a, "label": lbl})
                seen.add(lbl)
        return out

    def look(self) -> dict:
        place = self.current_place()
        p = self.world.spatial.places.get(place)
        name = p.name if p else place
        npcs = [self._display(n) for n in self.npcs_here()]
        sc = self.scene_context()
        actions = self.affordances_here()
        text = f"{sc.descriptor}\nТы в локации «{name}». " + (
            f"Здесь: {', '.join(npcs)}." if npcs else "Здесь пусто.")
        if p and p.alterations:                           # стойкие следы действий в локации
            text += " Следы: " + "; ".join(p.alterations) + "."
        if actions:
            text += " Можно: " + ", ".join(a["label"] for a in actions) + "."
        return {
            "kind": "look", "text": text,
            "place": place, "place_name": name, "scene": sc.to_dict(),
            "npcs": [{"id": n, "name": self._display(n)} for n in self.npcs_here()],
            "exits": [{"id": e, "name": self._place_name(e)} for e in self.exits()],
            "actions": actions,
            "view": self.view(),
        }

    # ===================================================================== #
    #  Главный обработчик ввода                                             #
    # ===================================================================== #
    def is_game_over(self) -> bool:
        """Игра окончена, если герой мёртв (0 HP). Дальнейшие действия блокируются."""
        return not self.world.is_alive(self.player)

    def _game_over_result(self) -> dict:
        return {"kind": "game_over", "game_over": True,
                "text": "💀 Игра окончена. Герой пал. Начни новую игру или загрузи сейв.",
                "view": self.view()}

    def handle(self, text: str) -> dict:
        if self.is_game_over():
            return self._game_over_result()
        if self.combat and self.combat.state.mode == "active":
            return {"kind": "combat", "text": "Идёт бой — используй боевые действия.",
                    "view": self.view()}
        if self._is_item_followup(text):                  # «а на нём что написано?» → про последний предмет
            return self._post(self._answer_query("look", text), "query")
        svc = self._inn_service(text)                     # услуги двора (комната/еда/меню) — до роутера
        if svc is not None:
            return self._post(svc, "serve")
        mv = self._movement_intent(text)                  # явное «идти/подойти к <место>» — детерминированно, до роутера
        if mv is not None:                                # навигация не должна зависеть от настроения LLM-роутера
            self.dialogue_partner = None
            action = Action(actor=self.player, verb="move", target=None, tone="neutral")
            return self._post(self._do_move(action, text), "move")
        route = self._route(text)                         # LLM-роутер (онлайн) / детерминированный фоллбэк
        # продолжение разговора: при активном собеседнике рядом «расскажи о…/что слышно»
        # (freeform или общий look) — это реплика ему, а не бросок/мировой-запрос
        convertible = ((route["kind"] == "command" and (route.get("verb") or "freeform") == "freeform")
                       or (route["kind"] == "query" and (route.get("query") or "look") == "look"))
        if (convertible and self.dialogue_partner and self.dialogue_partner in self.npcs_here()
                and not self._item_in_carry(text)
                and not any(k in text.lower() for k in (*self._HOSTILE_KW, *self._FREEFORM_KW))):
            route = {"kind": "command", "verb": "talk", "target": self.dialogue_partner}
        if route["kind"] == "query":                      # вопрос о мире/себе → ответ из стейта, без броска
            out, verb = self._answer_query(route.get("query") or "look", text), "query"
        else:
            verb = route.get("verb") or "freeform"
            action = Action(actor=self.player, verb=verb, target=route.get("target"),
                            tone=route.get("tone", "neutral"))
            # действие (не разговор) завершает текущий диалог; покупка сведений/торговля
            # идут у текущего собеседника, поэтому диалог не сбрасывают
            if verb not in ("talk", "persuade", "intimidate", "deceive", "inspect",
                            "buyinfo", "buy", "sell"):
                self.dialogue_partner = None
            handler = getattr(self, f"_do_{verb}", None)
            out = handler(action, text) if handler else self._resolve_freeform(text, action.target)
        result = self._post(out, verb)
        self._remember(text, result)                      # короткая память диалога (контекст роутера)
        return result

    def _is_item_followup(self, text: str) -> bool:
        """Продолжение про последний осмотренный предмет: местоимение «на нём…» + вопрос
        об осмотре/надписи. Решается детерминированно (не отдаём догадке роутера)."""
        if not (self._last_item and self._last_item in self._carry_items()):
            return False
        low = text.lower()
        pron = any(p in low for p in ("на нём", "на нем", "на ней", "о нём", "о нем",
                                      "что там", "на этом", "на нём", "этот предмет"))
        about = any(k in low for k in ("написа", "гравир", "надпис", "выцарап", "начертан",
                                       "метк", "рун", "что-то", "что то", "осмотр", "разгляд"))
        return pron and about

    def _remember(self, text: str, result: dict) -> None:
        self._history.append({"in": text.strip()[:160], "out": (result.get("text") or "")[:160]})
        self._history = self._history[-5:]                # последние 5 ходов

    def _recent_context(self, n: int = 4) -> str:
        lines = []
        for h in self._history[-n:]:
            lines.append(f"Игрок: {h['in']}")
            if h["out"]:
                lines.append(f"Мастер: {h['out'][:120]}")
        return "\n".join(lines)

    # ===================================================================== #
    #  Нарративный темп: при затишье и подходящей обстановке — случайный бит #
    # ===================================================================== #
    _EVENTFUL_VERBS = {"attack", "loot", "buy", "sell", "buyinfo", "persuade",
                       "intimidate", "deceive", "search", "move"}

    def _is_eventful(self, result: dict, verb: str) -> bool:
        """Произошло ли что-то «интересное» (сбрасывает затишье)."""
        if verb in self._EVENTFUL_VERBS:
            return True
        if isinstance(result, dict):
            if any(result.get(k) for k in ("container", "map_belief")):
                return True
            if "⚠" in (result.get("text") or ""):
                return True
            dec = result.get("decision")
            if isinstance(dec, dict) and dec.get("action") == "share_info":
                return True
        return False

    def _post(self, result: dict, verb: str) -> dict:
        """После хода: бой/ожидание броска не трогаем; иначе ведём счётчик затишья и,
        если режиссёр выкинул случайный бит, подмешиваем его в нарратив."""
        if self.combat and self.combat.state.mode == "active":
            return result
        if isinstance(result, dict) and result.get("kind") == "roll_request":
            return result
        result = self._surface_incidents(result)          # живые события, сработавшие за этот ход
        if self._is_eventful(result, verb):
            self.quiet_ticks = 0
            return result
        self.quiet_ticks += 1
        beat = self._ambient_beat()
        if beat and isinstance(result, dict):
            self.quiet_ticks = 0
            result = dict(result)
            result["text"] = ((result.get("text") or "").rstrip() + "\n\n— " + beat["text"]).strip()
            result["ambient_event"] = beat
            self._log_journal("· " + beat["text"])
        return result

    def _surface_incidents(self, result: dict) -> dict:
        """Сработавшие за ход инциденты — в нарратив, журнал и (если меняли карту) флаг map_dirty."""
        pending = self.__dict__.get("_inc_pending")
        if not pending or not isinstance(result, dict):
            return result
        self._inc_pending = []
        lines, map_dirty = [], False
        for sp in pending:
            lines.append(f"⚡ В городе: {sp.label}" + (f" — {sp.desc}" if sp.desc else ""))
            self._log_journal("⚡ " + sp.label)
            if (sp.effects or {}).get("change"):
                map_dirty = True
        result = dict(result)
        result["text"] = ((result.get("text") or "").rstrip() + "\n\n" + "\n".join(lines)).strip()
        result["incidents_fired"] = [sp.label for sp in pending]
        if map_dirty:
            result["map_dirty"] = True                     # фронту — перечитать карту (статусы изменились)
        return result

    def _ambient_beat(self) -> dict | None:
        place = self.current_place()
        return self.director.ambient_beat(
            self.world.seed, self.world.clock.tick, place,
            self.discovery.location_type(place), self.scene_context(),
            self.quiet_ticks, bool(self.npcs_here()))

    def submit_roll(self, raw_faces: list[int]) -> dict:
        """Принимает грани от игрока и возобновляет приостановленный ход (док 07 §4)."""
        if not self.pending_roll:
            return {"kind": "error", "text": "Нет ожидающего броска.", "view": self.view()}
        ctx = self.pending_roll
        self.pending_roll = None
        result = validate_player_roll(ctx["request"], raw_faces, source="player_ui")
        return ctx["resume"](result)

    # ===================================================================== #
    #  Обработчики глаголов (exploration)                                  #
    # ===================================================================== #
    def _do_move(self, action: Action, text: str) -> dict:
        dest = self._match_place(text)
        if not dest:
            low = text.lower()                            # локация не распознана
            move_verb = any(k in low for k in ("иди", "идти", "иду", "пойд", "двигай", "войти",
                                               "зайти", "направ", "шага", "топай", "перейти", "go "))
            if not move_verb or any(k in low for k in self._FREEFORM_KW):
                return self._resolve_freeform(text)        # роутер ошибся / физическое действие → freeform
            return {"kind": "system", "text": "Куда идти? Доступные выходы: "
                    + ", ".join(self._place_name(e) for e in self.exits()),
                    "view": self.view()}
        # НЕОДНОЗНАЧНОСТЬ: модель локаций дала 2+ известных места с высокой долей вероятности —
        # не угадываем, а просим уточнить (напр. две таверны). Фронт покажет варианты кнопками.
        opts = self._movement_options(text)
        if opts:
            return {"kind": "system", "view": self.view(), "clarify_places": opts,
                    "text": "Уточни, куда именно: " + " или ".join(f"«{o['name']}»" for o in opts) + "?"}
        cur = self.current_place()
        if dest == cur:
            look = self.look()
            look["text"] = "Ты уже здесь. " + look["text"]
            return look
        name = self._place_name(dest)
        # ГЕЙТ ЗНАНИЯ: нельзя направиться туда, о чём не знаешь (не примыкает, не разведано,
        # не услышано). Разведка — ногами через соседние локации или со слов/карты.
        if not self._knows_place(dest):
            return {"kind": "narration", "view": self.view(),
                    "text": f"Ты не знаешь, где находится «{name}». Сначала разведай это — "
                            f"расспроси местных или дойди туда, изучая город шаг за шагом."}
        # ГЕЙТ РАССТОЯНИЯ: текстовой командой — только к примыкающей локации (1 переход);
        # дальше игрок идёт через карту (там прокладывается путь и случаются события).
        hops = self.world.spatial.hops_between(cur, dest)
        if hops and hops > 1:
            return {"kind": "system", "view": self.view(), "travel_far": dest,
                    "text": f"«{name}» отсюда не дойти одним шагом — это {hops} кварталов пути. "
                            f"Открой карту и проложи маршрут — в дороге может что-то случиться."}
        return self._commit_move(dest)

    def _commit_move(self, dest: str, lead: str | None = None) -> dict:
        """Фактический переход в локацию dest (многоходовый путь допустим — для карты).
        Гейты знания/расстояния делает вызывающий; здесь — стоимость пути, спутники,
        журнал, разведка, туман подземелья, сверка наводок, тик времени и нарратив."""
        cur = self.current_place()
        path = self.world.spatial.path_between(cur, dest)
        if not path:
            return {"kind": "system", "text": f"Ты не знаешь, как добраться до "
                    f"«{self._place_name(dest)}».", "view": self.view()}
        for a, b in zip(path, path[1:]):                  # запертая дверь на пути?
            guard = self.world.dungeon_locks.get(frozenset((a, b)))
            if guard and f"cleared:{guard}" not in self.world.flags:
                return {"kind": "system", "view": self.view(),
                        "text": f"Дальше путь к «{self._place_name(dest)}» преграждает запертая "
                                f"дверь — её откроет лишь зачистка «{self._place_name(guard)}»."}
        ticks, region_travel = self._travel_cost(path)
        self.world.commit("set_position", self.player, target=self.player,
                          payload={"region": "region:phandalin", "place": dest})
        for comp in self._companions():               # спутники идут с игроком
            self.world.commit("set_position", comp, target=comp,
                              payload={"region": "region:phandalin", "place": dest})
        hours = ticks * config.SIM_MINUTES_PER_TICK // 60
        self._log_journal(f"Перешёл в «{self._place_name(dest)}»"
                          + (f" (путь ~{hours} ч)" if region_travel and hours else "") + ".")
        self._record_explored(dest)
        for pid in path:                                  # туман подземелья: открыть пройденные комнаты
            if self._dungeon_of(pid):
                self.world.commit("set_flag", self.player, payload={"flag": f"dseen:{pid}"})
        self.world.commit("interest", self.player, payload={"place": dest, "amount": 1})  # частые визиты ↑ важность
        debunked = self._verify_map_here(dest)        # сверка купленных наводок с реальностью
        self._tick(ticks)
        look = self.look()
        if lead is None:
            if region_travel:
                lead = (f"Путь к «{self._place_name(dest)}» ведёт дикими землями и "
                        f"занимает несколько часов.")
                incident = self._travel_incident(dest)
                if incident:
                    lead += " " + incident
            else:
                lead = f"Ты направляешься в «{self._place_name(dest)}»."
        look["text"] = lead + " " + look["text"]
        if debunked:
            look["text"] += "\n⚠ Сведения об этом месте оказались ложными!"
        return look

    # стоимость пути: шаг по городу дёшев, дикие земли — часы и риск (док §3.4)
    _DANGER_FACTOR = {"высокая": 1.4, "смертельная": 1.8}

    def _travel_cost(self, path: list[str]) -> tuple[int, bool]:
        sp = self.world.spatial
        wild_kinds = {"wilds", "site"}
        ticks, region = 0, False
        for a, b in zip(path, path[1:]):
            pa, pb = sp.places.get(a), sp.places.get(b)
            is_wild = ((pa and pa.kind in wild_kinds) or (pb and pb.kind in wild_kinds)
                       or (pb and pb.parent == "region:phandalin"))
            if is_wild:
                region, ticks = True, ticks + 18          # ~3 часа дикими землями за переход
            else:
                ticks += 1                                 # шаг по городу
        if region:
            from ..content.region import REGION_SITES, reachable_place_to_site
            key = reachable_place_to_site(path[-1])
            danger = REGION_SITES.get(key, {}).get("danger") if key else None
            ticks = int(ticks * self._DANGER_FACTOR.get(danger, 1.0))
            from ..world import environment
            ticks = int(ticks * environment.effects(self.scene_context()).travel_mult)  # погода
        return max(1, ticks), region

    def _travel_incident(self, dest: str) -> str:
        """Детерминированная (по seed+место) дорожная зарисовка для опасных маршрутов.
        Без боя — чтобы реплей оставался воспроизводимым; это крючок под будущие
        случайные встречи."""
        import random

        from ..content.region import REGION_SITES, reachable_place_to_site
        from ..gen.seeds import subseed
        key = reachable_place_to_site(dest)
        danger = REGION_SITES.get(key, {}).get("danger") if key else None
        if danger not in ("высокая", "смертельная"):
            return ""
        flav = ["По обочине — свежие следы крупных лап; место и впрямь неспокойное.",
                "Вдалеке кружит вороньё над чем-то павшим у тропы.",
                "Дважды ты сходишь с дороги, заслышав чужие голоса, и пережидаешь в укрытии."]
        return random.Random(subseed(self.world.seed, "travel_incident", dest)).choice(flav)

    def _record_explored(self, place_id: str) -> None:
        """Помечает посещённую локацию как достоверно известную на карте игрока.
        Личный визит ДОЛЖЕН быть не беднее купленного слуха — поэтому подтягиваем
        ground-truth (рельеф/сторона света/содержимое) из REGION_SITES, если место
        соответствует известному сайту."""
        bid = f"belief:explored:{place_id}"
        if bid in self.world.player_maps.get(self.player, {}):
            return
        from ..content.region import REGION_SITES, reachable_place_to_site
        key = reachable_place_to_site(place_id)
        truth = REGION_SITES.get(key, {}) if key else {}
        belief = {"id": bid, "site": key, "place": place_id, "source": "explored",
                  "label": truth.get("label") or self._place_name(place_id),
                  "terrain": truth.get("terrain", ""), "direction": truth.get("direction", ""),
                  "contents": truth.get("contents", ""), "danger": truth.get("danger", ""),
                  "reliability": "explored", "true": True, "verified": True}
        self.world.commit("map_update", self.player,
                          payload={"player": self.player, "belief": belief})

    def _verify_map_here(self, place_id: str) -> bool:
        from ..gen import mapinfo
        revealed = mapinfo.verify_on_visit(self.world, self.player, place_id)
        debunked = False
        for bid, was_true in revealed:
            if not was_true:
                debunked = True
                b = self.world.player_maps[self.player][bid]
                self._log_journal(f"Ложь раскрыта: сведения «{b['label']}» от "
                                  f"{self._display(b['source'])} оказались враньём.")
        return debunked

    def _do_talk(self, action: Action, text: str) -> dict:
        npc = action.target or self._match_npc(text) or self.dialogue_partner
        if not npc:
            here = self.npcs_here()
            npc = here[0] if len(here) == 1 else None
        if not npc:
            here = self.npcs_here()
            return {"kind": "system", "text": "С кем говорить? Рядом: "
                    + (", ".join(self._display(n) for n in here) or "никого"), "view": self.view()}
        if npc not in self.npcs_here():
            self.dialogue_partner = None
            return {"kind": "system", "text": f"{self._display(npc)} здесь нет.", "view": self.view()}

        self.lod.ensure_tier(npc, in_dialogue=True)
        self.charts.enrich(npc)
        ctx0 = self.cognition.retrieve(npc, "", self.player)
        first_meeting = not ctx0.memories          # нет воспоминаний об игроке = впервые
        rel = ctx0.rel
        topic = self._extract_topic(text, npc)
        self.dialogue_partner = npc
        self.world.commit("set_flag", self.player, payload={"flag": f"talked:{npc}"})  # для квестов «поговорить с …»

        if not topic:
            # ИНИЦИАЦИЯ: NPC приветствует и сам спрашивает, что нужно — без реакции
            # на несуществующую реплику игрока (заземление, без выдуманной истории)
            self.cognition.observe(npc, "ко мне подошёл незнакомец", importance=2)
            self.world.commit("talk", self.player, target=npc, payload={"opening": True})
            self._log_journal(f"Заговорил с {self._display(npc)}.")
            line = self._strip_leading_name(self._npc_greeting(npc, rel, first_meeting), npc)
            line += self._reveal_note(self._reveal_from_dialogue(npc, rel, None))
            self._tick()
            return {"kind": "narration", "text": line, "speaker": self._display(npc),
                    "npc": npc, "hint": "Спроси о чём-нибудь, предложи дело или скажи что-то.",
                    "view": self.view()}

        # игрок что-то СКАЗАЛ/СПРОСИЛ → реакция с учётом отношений и гейтов
        ctx = self.cognition.retrieve(npc, topic, self.player)
        decision = self.cognition.policy(npc, "talk", action.tone, ctx, self.player)
        hooks = self.director.surface_hooks_near(npc)
        self.cognition.observe_and_appraise(npc, self.player, "talk", action.tone,
                                            f"игрок сказал: {topic[:120]}")
        self._remember_salient(npc, text)             # имя/цель/намерение игрока → точная память для узнавания
        self.world.commit("talk", self.player, target=npc, payload={"topic": topic[:60]})
        self._player_shares_with(npc, topic)          # реплика игрока может научить NPC (игрок — источник молвы)
        line = self._strip_leading_name(self._npc_reply(npc, decision, topic, rel, first_meeting, hooks), npc)
        line += self._reveal_note(self._reveal_from_dialogue(npc, rel, topic))
        self._log_journal(f"Поговорил с {self._display(npc)}.")
        self._tick()
        return {"kind": "narration", "text": line, "speaker": self._display(npc),
                "npc": npc, "decision": decision, "hooks": hooks, "view": self.view()}

    def _strip_leading_name(self, line: str, npc: str) -> str:
        """Реплику показывает поле speaker, поэтому имя в начале текста — лишнее (иначе
        фронт даёт «Имя Имя …»). Снимаем ведущее имя NPC."""
        nm = self._display(npc)
        s = line.lstrip()
        if nm and s.startswith(nm):
            s = s[len(nm):].lstrip(" :,—-")
            return s[:1].upper() + s[1:] if s else line
        return line

    def _extract_topic(self, text: str, npc: str) -> str:
        """Вычленяет реплику/тему игрока, отбросив каркас «поговорить с X». Пусто —
        чистая инициация (приветствие)."""
        persona = self.world.ecs.get(npc, Persona)
        t = " " + text.lower() + " "
        if persona:
            for nm in [persona.name.lower()] + persona.name.lower().split():
                if len(nm) > 2:
                    t = t.replace(nm, " ")
        for w in ("поговорить", "поговорю", "поговори", "говорить", "говорю", "заговорить",
                  "спросить", "спрошу", "спроси", "обратиться", "подойти", "подхожу",
                  "хочу", "давай", "talk", "speak", "ask", " с ", " to ", "его", "неё", "ним"):
            t = t.replace(w, " ")
        # чистое приветствие — это инициация, а не «тема»: иначе «привет!» незнакомцу
        # уходит в policy(talk) и при низком доверии получает холодный withhold.
        # Токенизируем по словам (без пунктуации), чтобы «привет!» == «привет».
        import re
        greetings = {"привет", "приветствую", "здравствуй", "здравствуйте", "здорово",
                     "хай", "доброго", "добрый", "день", "вечер", "утро", "доброе",
                     "hello", "hi", "greetings"}
        toks = [w for w in re.split(r"[^0-9a-zа-яё]+", t) if w and w not in greetings]
        return text.strip() if ("?" in text or len(" ".join(toks)) >= 4) else ""

    def _do_persuade(self, action: Action, text: str) -> dict:
        return self._social_check(action, text, "persuasion")

    def _do_intimidate(self, action: Action, text: str) -> dict:
        return self._social_check(action, text, "intimidation")

    def _do_deceive(self, action: Action, text: str) -> dict:
        return self._social_check(action, text, "deception")

    def _social_check(self, action: Action, text: str, skill: str) -> dict:
        npc = action.target or self._match_npc(text) or (self.npcs_here()[0] if self.npcs_here() else None)
        if not npc:
            return {"kind": "system", "text": "Не на кого воздействовать.", "view": self.view()}
        self.lod.ensure_tier(npc, in_dialogue=True)
        # уже напуганный (fear-гейт открыт) уступает БЕЗ броска — иначе геймплейный пут
        # запугивания игнорировал страх, расходясь с когницией (fear≥0.6 → защита)
        from ..cognition import gate_open
        if skill == "intimidation" and gate_open(self.world, npc, self.player, "yield"):
            self.cognition.observe_and_appraise(npc, self.player, "intimidate", "fearful",
                                                "игрок надавил на и без того напуганного")
            self.dialogue_partner = npc
            self._log_journal(f"{self._display(npc)} уступает под давлением (уже в страхе).")
            self._tick()
            reply = self._npc_reply(npc, {"action": "yield"}, text,
                                    self.cognition.retrieve(npc, "", self.player).rel, False,
                                    self.director.surface_hooks_near(npc))
            return {"kind": "narration", "text": reply, "npc": npc, "view": self.view()}
        dc = 13
        req = self.rules.build_check_request(self.player, skill, dc, target=npc, kind="skill",
                                             env_adv=self._env_check_adv(skill))

        def resume(result: RollResult) -> dict:
            outcome = self.rules.adjudicate(action, req, result)
            tone = {"persuasion": "friendly", "intimidation": "fearful",
                    "deception": "deceptive"}.get(skill, "friendly")
            self.cognition.observe_and_appraise(npc, self.player, skill, tone, outcome.summary)
            self.world.commit(skill, self.player, target=npc,
                              payload={"success": outcome.success},
                              roll=result.to_record(req.dice))
            ctx = self.cognition.retrieve(npc, "", self.player)
            rel, first = ctx.rel, (not ctx.memories)
            # успех проверки = временный «эффективный гейт»: NPC выдаёт более чувствительное и
            # релевантное знание, чем при пассивном доверии (док 02 §4+: убеждение/обман/страх).
            gate_level = min(1.0, rel.trust + 0.35) if outcome.success else None
            if skill == "deception" and outcome.success:   # ложь сработала — метка для последствий
                self.world.commit("rel_update", self.player,
                                  payload={"npc": npc, "target": self.player, "tags": ["deceived"]})
            reply = self._npc_reply(npc, {"action": "share_info" if outcome.success else "withhold"},
                                    text, rel, first, self.director.surface_hooks_near(npc),
                                    gate_level=gate_level)
            self._log_journal(f"{'Убедил' if skill == 'persuasion' and outcome.success else 'Говорил с'} "
                              f"{self._display(npc)} ({'успех' if outcome.success else 'неудача'}).")
            self._tick()
            return {"kind": "narration", "text": f"{outcome.summary} {reply}", "npc": npc,
                    "view": self.view()}

        return self._suspend(req, resume, f"Проверка {skill} против DC {dc}.")

    def _do_search(self, action: Action, text: str) -> dict:
        place = self.current_place()
        dc = 15
        # секретная дверь в подземелье — ищется тем же чеком, что и тайники
        secret = self.world.dungeon_secrets.get(place)
        if secret and f"secret_found:{place}" not in self.world.flags:
            if self.rules.try_passive(self.player, "perception", dc):
                return self._reveal_secret(place, secret, "Сквозняк из щели выдаёт скрытый ход.")
            req = self.rules.build_check_request(self.player, "investigation", dc, kind="skill",
                                                 env_adv=self._env_check_adv("investigation"))

            def resume_secret(result: RollResult) -> dict:
                outcome = self.rules.adjudicate(action, req, result)
                self.world.commit("search", self.player, payload={"success": outcome.success},
                                  roll=result.to_record(req.dice))
                self._tick()
                if outcome.success:
                    return self._reveal_secret(place, secret, outcome.summary)
                return {"kind": "narration", "text": outcome.summary
                        + " Стены кажутся глухими — ничего не найдено.", "view": self.view()}

            return self._suspend(req, resume_secret, f"Поиск тайного хода: Investigation против DC {dc}.")
        # пассивная Perception (док 07 §5) — авто без броска
        if self.rules.try_passive(self.player, "perception", dc):
            return self._reveal_container(place, "Твоё чутьё сразу находит тайник.")
        req = self.rules.build_check_request(self.player, "investigation", dc, kind="skill",
                                             env_adv=self._env_check_adv("investigation"))

        def resume(result: RollResult) -> dict:
            outcome = self.rules.adjudicate(action, req, result)
            self.world.commit("search", self.player, payload={"success": outcome.success},
                              roll=result.to_record(req.dice))
            self._tick()
            if outcome.success:
                return self._reveal_container(place, outcome.summary + " Ты находишь тайник.")
            return {"kind": "narration", "text": outcome.summary + " Ничего не найдено.",
                    "view": self.view()}

        return self._suspend(req, resume, f"Обыск: Investigation против DC {dc}.")

    def _do_scan(self, action: Action, text: str) -> dict:
        """«Осматриваюсь — не наблюдает ли кто?» Существование решает правдоподобие
        по контексту и фиксируется навсегда; заметишь ли — пассивная Perception."""
        place = self.current_place()
        res = self.discovery.resolve_observers(place, self.player)
        self._tick()
        tag = " (уже выяснено ранее)" if res.recorded else ""
        if not res.present:
            self._log_journal("Осмотрелся — вокруг никого.")
            return {"kind": "narration", "view": self.view(),
                    "text": f"Ты внимательно осматриваешься{tag}. Вокруг ни души — ты здесь один."}
        watcher = res.npc
        wname = self._display(watcher) if watcher and self.world.ecs.exists(watcher) else "кто-то"
        if not res.watching:
            self._log_journal("Осмотрелся — рядом есть люди, слежки нет.")
            return {"kind": "narration", "view": self.view(),
                    "text": f"Поблизости есть люди{tag}, но никто не следит за тобой намеренно."}
        # за тобой наблюдают — заметишь ли ты соглядатая? (пассивная Perception vs скрытность)
        from ..rules.checks import skill_modifier
        dc = 12 + (skill_modifier(self.world, watcher, "stealth") if watcher else 0)
        if self.rules.try_passive(self.player, "perception", dc):
            self._log_journal(f"Заметил слежку: {wname}.")
            return {"kind": "narration", "view": self.view(),
                    "text": f"Краем глаза ты ловишь это: {wname} украдкой наблюдает за тобой{tag}."}
        return {"kind": "narration", "view": self.view(),
                "text": "Тебя не покидает ощущение чужого взгляда в спину, но источник ускользает."}

    def _do_inspect(self, action: Action, text: str) -> dict:
        npc = self._match_npc(text)
        if npc:
            return {"kind": "narration", "text": self._describe_npc(npc), "view": self.view()}
        iid = self._item_in_carry(text)                   # «осмотреть кинжал» — конкретный предмет
        if iid:
            return {"kind": "narration", "text": self._describe_item(iid), "view": self.view()}
        if self._is_bare_look(text):                      # «осмотреться вокруг» — обычный обзор
            return self.look()
        return self._resolve_freeform(text)               # «осмотреть руку» и пр. — freeform-действие

    _BARE_LOOK_KW = ["осмотреться", "осмотрюсь", "осмотрись", "осматрива", "оглядет", "оглядыва",
                     "оглянут", "озира", "вокруг", "где я", "что здесь", "что вокруг",
                     "комнат", "помещ", "зал", "местност", "локац", "округ", "look"]

    def _is_bare_look(self, text: str) -> bool:
        low = text.lower()
        return any(k in low for k in self._BARE_LOOK_KW) or len(low.split()) <= 1

    def _do_loot(self, action: Action, text: str) -> dict:
        self.current_place()
        containers = self._containers_here()
        if not containers:                                # нечего лутать → это freeform-действие
            return self._resolve_freeform(text, action.target)
        cid = containers[0]
        c = self.world.containers[cid]
        try:
            items = inv.loot(self.world, self.player, c)
        except inv.InventoryError as e:
            return {"kind": "system", "text": f"Не получается: {e}", "view": self.view()}
        taken = []
        carry = f"carry:{ids.name_of(self.player)}"
        for iid in list(items):
            t = self.world.items[iid].template_id
            if t in ("tmpl:cp", "tmpl:sp", "tmpl:gp"):
                coin = ids.name_of(t)
                qty = self.world.items[iid].quantity
                inv.transfer_currency(self.world, None, self.player, {coin: qty}, actor=self.player)
                self.world.commit("item_remove", self.player,
                                  payload={"container": cid, "instance": iid, "destroy": True})
                taken.append(f"{qty} {coin}")
            else:
                try:
                    inv.move(self.world, cid, carry, iid, actor=self.player)
                    taken.append(self._item_name(iid))
                except inv.InventoryError:
                    pass
        self._tick()
        if taken:
            self._log_journal("Забрал: " + ", ".join(taken) + ".")
        return {"kind": "narration", "text": f"Ты забираешь: {', '.join(taken) or 'ничего'}.",
                "view": self.view()}

    def _do_buy(self, action: Action, text: str) -> dict:
        shop = self._shop_here()
        if not shop:
            # лавки нет, но рядом NPC (трактирщик и т.п.) — это вопрос/просьба к нему,
            # а не дед-энд: «сколько стоит снять комнату?», «налей эля». Уводим в диалог.
            here = self.npcs_here()
            npc = self.dialogue_partner if self.dialogue_partner in here else (here[0] if here else None)
            if npc:
                return self._do_talk(Action(actor=self.player, verb="talk", target=npc), text)
            return {"kind": "system", "text": "Поблизости нет лавки.", "view": self.view()}
        c = self.world.containers[shop]
        if not c.items:
            return {"kind": "system", "text": "Лавка пуста.", "view": self.view()}
        goods = ", ".join(f"{self._item_name(i)} ({inv.price_of(self.world, self.world.items[i], c, self.player)//100} зм)"
                          for i in c.items)
        low = text.lower()
        iid = next((i for i in c.items if self._item_match(i, low)), None)
        if iid is None:                               # не назвали товар — покажем ассортимент
            return {"kind": "shop", "text": f"На прилавке: {goods}. Что берёшь?",
                    "shop": shop, "view": self.view()}
        price = inv.price_of(self.world, self.world.items[iid], c, self.player) // 100
        name = self._item_name(iid)
        try:
            inv.buy(self.world, self.player, shop, iid)
            self._tick()
            return {"kind": "narration", "text": f"Ты покупаешь {name} за ~{price} зм. "
                    f"Кошелёк: {self._coins()}.", "view": self.view()}
        except inv.InventoryError as e:
            return {"kind": "system", "text": f"Покупка не удалась: {e}", "view": self.view()}

    def _do_sell(self, action: Action, text: str) -> dict:
        shop = self._shop_here()
        if not shop:
            return {"kind": "system", "text": "Поблизости нет лавки, чтобы продать.", "view": self.view()}
        carry = self.world.containers.get(f"carry:{ids.name_of(self.player)}")
        if not carry or not carry.items:
            return {"kind": "system", "text": "В сумке нечего продавать.", "view": self.view()}
        low = text.lower()
        iid = next((i for i in carry.items if self._item_match(i, low)), None)
        if iid is None:
            bag = ", ".join(self._item_name(i) for i in carry.items)
            return {"kind": "shop", "text": f"Что продать? В сумке: {bag}.", "view": self.view()}
        name = self._item_name(iid)
        try:
            inv.sell(self.world, self.player, shop, iid)
            self._tick()
            return {"kind": "narration", "text": f"Ты продаёшь {name}. Кошелёк: {self._coins()}.",
                    "view": self.view()}
        except inv.InventoryError as e:
            return {"kind": "system", "text": f"Продажа не удалась: {e}", "view": self.view()}

    def _item_match(self, iid: str, low: str) -> bool:
        name = self._item_name(iid).split("×")[0].strip().lower()
        return bool(name) and (name in low or any(w in low for w in name.split() if len(w) > 3))

    def _coins(self) -> str:
        w = self.world.wallet(self.player)
        return ", ".join(f"{v} {k}" for k, v in w.items() if v) or "пусто"

    def _do_buyinfo(self, action: Action, text: str) -> dict:
        """Покупка картографических сведений у NPC — могут оказаться ложью/неполнотой."""
        from ..content.region import REGION_SITES
        from ..gen import mapinfo
        npc = (action.target or self._match_npc(text) or self.dialogue_partner
               or (self.npcs_here()[0] if self.npcs_here() else None))
        if not npc:
            return {"kind": "system", "text": "Не у кого расспросить о дорогах.", "view": self.view()}
        sites = mapinfo.sellable_sites(self.world, npc)
        if not sites:
            return {"kind": "narration", "view": self.view(),
                    "text": f"{self._display(npc)} разводит руками: «Про дальние тропы я не знаю»."}
        low = text.lower()
        chosen = next((s for s in sites if any(w in low for w in REGION_SITES[s]["label"].lower().split()
                                               if len(w) > 3)), None)
        if not chosen:
            bought = self.world.player_maps.get(self.player, {})
            chosen = next((s for s in sites if f"belief:{npc}:{s}" not in bought), sites[0])
        res = mapinfo.buy_info(self.world, self.player, npc, chosen)
        if res.get("error") == "insufficient_funds":
            return {"kind": "system", "text": f"Не хватает золота — просят {res['price_gp']} зм.",
                    "view": self.view()}
        if res.get("error") == "already_known":
            return {"kind": "narration", "text": "Это ты уже слышал.", "view": self.view()}
        if res.get("error"):
            return {"kind": "system", "text": "Сведений нет.", "view": self.view()}
        gp = mapinfo.price_gp(chosen)
        self._log_journal(f"Купил у {self._display(npc)} сведения о «{res['label']}» ({gp} зм).")
        self._tick()
        parts = [f"«{res['label']}» — на {res['direction']}, {res['terrain']}."]
        if res.get("contents"):
            parts.append(f"Сказывают: {res['contents']}.")
        else:
            parts.append("Подробностей он не ведает.")
        if res.get("danger") and res["danger"] != "?":
            parts.append(f"Опасность: {res['danger']}.")
        # игроко-безопасный вид: НЕ отдаём true/reliability — иначе ложь видна в payload
        safe = {k: res.get(k) for k in ("label", "site", "place", "terrain",
                                        "direction", "contents", "danger", "source")}
        safe["display"] = "hearsay"
        return {"kind": "narration", "npc": npc, "map_belief": safe, "view": self.view(),
                "text": f"{self._display(npc)} (за {gp} зм): " + " ".join(parts)
                        + "  — записано на карту (правдивость не гарантирована)."}

    def map_view(self) -> list[dict]:
        """Карта глазами игрока (исследовано / со слов / подтверждено / опровергнуто)."""
        from ..gen import mapinfo
        return mapinfo.map_view(self.world, self.player)

    def region_map(self) -> dict:
        """Самодостаточный снимок карты региона для виджета — на ЛЮБОЙ момент партии.

        Позиции сайтов берутся из СТОРОН СВЕТА графа проходимости (рёбра диких
        земель), время пути — из `_travel_cost`, состояния пинов — из `map_view`
        игрока. Виджет/страница рисуют строго по этим данным, без хардкода."""
        from ..content.region import REGION_SITES
        from ..world.spatial import DIR_RU, DIRECTIONS
        sp = self.world.spatial
        SQ = "place:phandalin_square"
        place_dir = {dest: d for d, dest in sp.exits_of("place:phandalin_wilds").items()}

        def dir_of(pid: str):
            node, seen = pid, 0
            while node and seen < 6:                       # сайт или его узел-подход
                if node in place_dir:
                    return place_dir[node]
                pl = sp.places.get(node)
                node = pl.parent if pl else None
                seen += 1
            return None

        def src_name(src):
            if not src:
                return None
            if src == "explored":
                return "разведано лично"
            return self._display(src) if src.startswith("npc:") else src

        view = {v["place"]: v for v in self.map_view() if v.get("place")}
        sites = []
        for key, t in REGION_SITES.items():
            pid = t["place"]
            canon = dir_of(pid)
            dx, dy = DIRECTIONS.get(canon, (0, 0))
            path = sp.path_between(SQ, pid)
            hours = (round(self._travel_cost(path)[0] * config.SIM_MINUTES_PER_TICK / 60, 1)
                     if path else None)
            v = view.get(pid)
            sites.append({
                "key": key, "label": t["label"], "place": pid,
                "dir": canon, "dir_ru": DIR_RU.get(canon, ""), "dx": dx, "dy": dy,
                "hours": hours, "danger": t["danger"], "terrain": t["terrain"],
                "display": v["display"] if v else "unknown",
                "source": src_name(v.get("source")) if v else None,
                "lied_by": src_name(v.get("lied_by")) if v else None,
            })
        return {
            "player_place": self.current_place(),
            "town": {"label": "Фэндалин", "place": SQ, "go": "идти на площадь"},
            "sites": sites,
        }

    def shop_view(self) -> dict | None:
        """Read-model лавки для торгового интерфейса: товар с ценами/описанием,
        кошелёк игрока и что из его сумки можно продать (с учётом deals_in). None —
        рядом нет лавки."""
        shop_id = self._shop_here()
        if not shop_id:
            return None
        c = self.world.containers[shop_id]
        goods = [{"id": i, "name": self._item_name(i),
                  "price_gp": max(1, inv.price_of(self.world, self.world.items[i], c, self.player) // 100),
                  "desc": self.world.items[i].description} for i in c.items]
        sellable = []
        carry = self.world.containers.get(f"carry:{ids.name_of(self.player)}")
        for i in (carry.items if carry else []):
            inst = self.world.items[i]
            tmpl = self.world.templates.get(inst.template_id)
            if not tmpl or "unsellable" in (tmpl.tags or ()) or inst.equipped_slot:
                continue
            if c.deals_in and tmpl.category not in c.deals_in:
                continue
            sellable.append({"id": i, "name": self._item_name(i),
                             "price_gp": max(1, int(tmpl.base_value * inst.quantity * c.buy_rate) // 100)})
        return {"shop": shop_id, "merchant": self._display(c.owner_ref) if c.owner_ref else "лавка",
                "deals_in": list(c.deals_in or []), "wallet": self._coins(),
                "goods": goods, "sellable": sellable}

    def map_levels(self) -> dict:
        """Многоуровневая карта: континент/регион → город (улицы) → интерьер (комнаты).
        Узлы каждого уровня расставлены по сторонам света (dx,dy) для мини-карты;
        фронт даёт вкладки уровней и переход кликом."""
        from ..world.spatial import DIR_RU, DIRECTIONS, LAYOUT_OFFSETS
        sp = self.world.spatial
        place = self.current_place()
        cur = sp.places.get(place)
        parent = sp.places.get(cur.parent) if (cur and cur.parent) else None

        def occ(pid):
            return [self._display(e) for e in sp.occupants(pid)
                    if e != self.player and self.world.is_alive(e)]

        # --- регион: сайты по сторонам света + город-хаб ---------------------
        rm = self.region_map()
        SQ = "place:phandalin_square"
        region = [{"id": SQ, "name": "Фэндалин", "kind": "settlement", "dx": 0, "dy": 0,
                   "dir_ru": "", "current": place in (SQ,), "display": "explored",
                   "go": "идти на площадь"}]
        for s in rm["sites"]:
            region.append({"id": s["place"], "name": s["label"], "kind": "site",
                           "dx": s["dx"], "dy": s["dy"], "dir_ru": s["dir_ru"],
                           "current": s["place"] == place, "display": s["display"],
                           "go": ("идти в " + s["label"]) if s["display"] != "unknown" else None})
        levels = [{"id": "region", "title": "Окрестности Фэндалина", "nodes": region}]

        # --- город: площадь-хаб + здания по компасу --------------------------
        town = [{"id": SQ, "name": self._place_name(SQ), "kind": "room", "dx": 0, "dy": 0,
                 "dir_ru": "", "current": place == SQ, "go": "идти на площадь", "occupants": occ(SQ)}]
        for d, dest in sp.exits_of(SQ).items():
            if d in DIRECTIONS:
                dx, dy, dir_ru = *DIRECTIONS[d], DIR_RU.get(d, "")
            else:
                dx, dy, dir_ru = 0.0, -0.55, ""          # внекомпасные (доска объявлений) — у центра
            town.append({"id": dest, "name": self._place_name(dest),
                         "kind": sp.places[dest].kind if dest in sp.places else "",
                         "dx": dx, "dy": dy, "dir_ru": dir_ru, "current": place == dest,
                         "go": "идти в " + self._place_name(dest), "occupants": occ(dest)})
        levels.append({"id": "town", "title": "Фэндалин — улицы", "nodes": town})

        # --- интерьер: дочерние комнаты текущего здания/сайта (если есть) -----
        host = parent if (parent and cur and cur.kind == "room" and parent.kind in ("building", "site")) else cur
        if host:
            rooms = [c for c in (host.children or []) if c in sp.places and sp.places[c].kind == "room"]
            if rooms:
                inner = [{"id": host.place_id, "name": host.name, "kind": host.kind, "dx": 0, "dy": 0,
                          "dir_ru": "", "current": place == host.place_id, "go": None, "occupants": occ(host.place_id)}]
                for rid in rooms:
                    d = sp.direction_to(host.place_id, rid) or "deeper"
                    dx, dy = LAYOUT_OFFSETS.get(d, (0, 1))
                    inner.append({"id": rid, "name": self._place_name(rid), "kind": "room",
                                  "dx": dx, "dy": dy, "dir_ru": DIR_RU.get(d, ""), "current": place == rid,
                                  "go": "идти в " + self._place_name(rid), "occupants": occ(rid)})
                levels.append({"id": "interior", "title": host.name, "nodes": inner})

        # текущий уровень для открытия вкладки
        if cur and cur.parent == "region:phandalin" and cur.kind in ("site", "wilds"):
            level = "region"
        elif cur and cur.kind == "room" and parent and parent.kind == "site":
            level = "interior"
        else:
            level = "town"
        return {"current": place, "current_level": level, "levels": levels}

    def _do_inventory(self, action: Action, text: str) -> dict:
        return {"kind": "inventory", "text": self._inventory_text(), "view": self.view()}

    def _do_map(self, action: Action, text: str) -> dict:
        """Показать карту региона: связность нодами (текст) + структурированный
        region_map для веб-виджета. Это РАЗНОЕ с buyinfo (покупкой наводок у NPC)."""
        return {"kind": "map", "text": self.map_text(),
                "region_map": self.region_map(), "view": self.view()}

    def _do_wait(self, action: Action, text: str) -> dict:
        self._tick(2)
        fast_forward(self.world, self.player)
        # привал — большое затишье: режиссёр заметно охотнее подкидывает событие
        # (праздно ждать в опасной глуши — напрашиваться на встречу)
        self.quiet_ticks += 2
        sc = self.scene_context()
        return {"kind": "narration",
                "text": f"Ты выжидаешь. Время идёт ({self.world.clock.hhmm()}). "
                        f"{sc.descriptor}",
                "view": self.view()}

    def _do_attack(self, action: Action, text: str) -> dict:
        target = action.target or self._match_npc(text)
        here = self.npcs_here()
        enemies = [n for n in here if self._is_hostile(n)]
        if target and target not in enemies and self._is_hostile(target):
            enemies = [target] + [e for e in enemies if e != target]
        if enemies:
            return self.start_combat(enemies)
        if target and target in here:                     # игрок ЯВНО бьёт присутствующего (нейтрала) — его выбор
            return self.start_combat([target])
        # ни враждебных, ни названной присутствующей цели → НЕ бить случайного соседа/спутника
        return {"kind": "narration", "view": self.view(),
                "text": "Нападать не на кого — врага рядом нет."}

    # ===================================================================== #
    #  Бой (мост к CombatEngine)                                            #
    # ===================================================================== #
    def start_combat(self, enemy_ids: list[str]) -> dict:
        from ..combat import BattleGrid
        from ..content.maps import load_meta
        place = self.current_place()
        meta = load_meta(place)
        grid = BattleGrid.from_meta(meta) if meta else BattleGrid.empty()
        self.combat = CombatEngine(self.world, self.dice, self.model, self.cognition, self.lod)
        # спутники, оказавшиеся рядом, вступают в бой на стороне игрока (не соло против группы)
        allies = [c for c in self._companions()
                  if (pos := self.world.position(c)) and pos.place_id == place]
        cs = self.combat.start([self.player, *allies], enemy_ids, grid=grid,
                               init_surfaces=(meta or {}).get("surfaces"))
        self.dialogue_partner = None
        self._log_journal("Вступил в бой: " + ", ".join(self._display(e) for e in enemy_ids) + ".")
        return {"kind": "combat_start", "text": "Бой начинается! " + cs.log[-1],
                "combat": self.combat_view(), "view": self.view()}

    # ---- ход PC: можно двигаться И действовать; монстры ходят на End Turn --
    def _require_pc_turn(self):
        if not self.combat or not self.combat.is_pc_turn() or self.pending_roll:
            return {"kind": "error", "text": "Сейчас не твой ход.", "view": self.view()}
        return None

    def _combat_result(self, text: str, *, kind: str = "combat", roll_req=None) -> dict:
        out = {"kind": kind, "text": text.strip(),
               "combat": self.combat_view(), "view": self.view()}
        if roll_req is not None:
            out["roll_request"] = self._roll_req_dict(roll_req)
        return out

    def _after_action(self, out: dict) -> dict:
        """Обёртка результата боевого действия PC: текст + хвост при конце боя.
        Ход НЕ завершается — игрок может ещё двигаться/действовать (стиль BG).
        Механический исход опц. отрисовывается нарратором (числа не меняются)."""
        mech = out.get("outcome", "")
        tail = self._on_combat_end() if self.combat.check_end() else ""
        narr = self._narrate_outcome(mech, topic="combat") if mech else None
        return self._combat_result((narr or mech) + tail)

    def combat_attack(self, target_id: str) -> dict:
        if (err := self._require_pc_turn()):
            return err
        req = self.combat.pc_declare_attack(target_id)
        if not hasattr(req, "request_id"):           # отказ (вне досягаемости/нет действия)
            return self._combat_result(req.get("outcome", ""))
        self.pending_roll = {"request": req, "resume": self._combat_resume_factory(req)}
        return self._combat_result(f"Бросок атаки по {self._display(target_id)}.",
                                   kind="roll_request", roll_req=req)

    def _combat_resume_factory(self, req):
        def resume(result: RollResult) -> dict:
            out = self.combat.submit_roll(result)
            if not out["done"]:                      # нужен ещё бросок (урон)
                nreq = out["next_request"]
                self.pending_roll = {"request": nreq, "resume": self._combat_resume_factory(nreq)}
                return self._combat_result(out["outcome"], kind="roll_request", roll_req=nreq)
            return self._after_action(out)
        return resume

    def combat_move(self, cell) -> dict:
        if (err := self._require_pc_turn()):
            return err
        return self._after_action(self.combat.move_to(cell))

    def combat_action(self, action: str, target=None, cell=None, spell=None) -> dict:
        if (err := self._require_pc_turn()):
            return err
        handlers = {
            "dash": lambda: self.combat.dash(),
            "dodge": lambda: self.combat.dodge(),
            "disengage": lambda: self.combat.disengage(),
            "shove": lambda: self.combat.shove(target),
            "cast": lambda: self.combat.cast(self.player, spell, target=target,
                                             cell=tuple(cell) if cell else None),
        }
        fn = handlers.get(action)
        return self._after_action(fn() if fn else {"outcome": "неизвестное действие"})

    def combat_end_turn(self) -> dict:
        if not self.combat:
            return {"kind": "error", "text": "Нет боя.", "view": self.view()}
        self.combat.end_turn()
        return self._combat_result("Ход завершён." + self._run_monster_turns())

    def _run_monster_turns(self) -> str:
        lines, guard = [], 0
        cs = self.combat.state
        while cs.mode == "active" and not self.combat.is_pc_turn() and guard < 60:
            guard += 1
            lines.append(self.combat.auto_turn()["outcome"])
        if cs.mode == "ended":
            lines.append(self._on_combat_end())
        return "\n" + "\n".join(l for l in lines if l) if lines else ""

    def _on_combat_end(self) -> str:
        cs = self.combat.state
        if cs.outcome == "victory":                       # зачистка локации (для LairCleared/замков)
            self.world.commit("set_flag", self.player,
                              payload={"flag": f"cleared:{self.current_place()}"})
        for q in list(self.world.quests.values()):
            if q.state == "active":
                self.quests.advance(q)
        if "cragmaw_cleared" in self.world.flags:
            self.director.pacing_check()
        msg = {"victory": "Победа! Враги повержены.",
               "tpk": "Партия пала...", "flee": "Враги бежали.",
               "defeat": "💀 Герой пал. Игра окончена."}.get(cs.outcome, "Бой окончен.")
        self._log_journal(msg)
        return f"\n=== {msg} ==="

    def combat_view(self) -> dict | None:
        if not self.combat:
            return None
        cs = self.combat.state
        g = cs.grid
        cur = cs.current()
        combatants = []
        for eid in cs.initiative_order:
            st = self.world.get_stats(eid)
            c = cs.combatants[eid]
            conds = [cd.name for cd in self.world.conditions.get(eid, [])]
            combatants.append({
                "id": eid, "name": self._display(eid), "hp": st.hp if st else 0,
                "max_hp": st.max_hp if st else 0, "ac": c.ac, "side": c.side,
                "fled": c.fled, "current": eid == cur, "pos": list(c.pos),
                "conditions": conds})
        # данные для текущего хода PC: достижимость, цели, доступные действия
        reachable, targets, actions = [], [], []
        if self.combat.is_pc_turn():
            reachable = [list(k) for k in self.combat.reachable_cells().keys()]
            targets = [e for e in self.combat.alive_enemies()
                       if self.combat.in_attack_range(self.player, e)]
            tb = cs.turn_budget
            if tb.action and targets:
                actions.append("attack")
            if tb.movement > 0:
                actions.append("move")
            if tb.action:
                actions += ["dash", "dodge", "disengage"]
                if any(g.adjacent(cs.combatants[self.player].pos, cs.combatants[e].pos)
                       for e in self.combat.alive_enemies()):
                    actions.append("shove")
            actions.append("end_turn")
        place = self.current_place()
        p = self.world.spatial.places.get(place)
        return {
            "round": cs.round, "mode": cs.mode, "outcome": cs.outcome, "turn": cur,
            "is_pc_turn": self.combat.is_pc_turn(),
            "grid": {"cols": g.cols, "rows": g.rows, "cell": g.cell, "terrain": g.terrain},
            "battlemap": f"/static/maps/{p.battlemap}" if (p and p.battlemap) else None,
            "surfaces": [{"pos": list(cell), "kind": s.kind} for cell, s in cs.surfaces.items()],
            "combatants": combatants, "enemies": self.combat.alive_enemies(),
            "reachable": reachable, "targets": targets, "actions": actions,
            "movement": cs.turn_budget.movement, "player": self.player,
            "log": cs.log[-8:]}

    # ===================================================================== #
    #  Внутреннее                                                           #
    # ===================================================================== #
    def _suspend(self, req, resume, msg: str) -> dict:
        self.pending_roll = {"request": req, "resume": resume}
        return {"kind": "roll_request", "text": msg,
                "roll_request": self._roll_req_dict(req), "view": self.view()}

    def _roll_req_dict(self, req) -> dict:
        return {"request_id": req.request_id, "dice": req.dice, "modifier": req.modifier,
                "advantage": req.advantage, "dc": req.dc if req.visibility == "open" else None,
                "kind": req.kind, "visibility": req.visibility}

    def _reveal_container(self, place: str, msg: str) -> dict:
        # материализуем тайник Klarg при обыске Cragmaw (lazy → персист)
        cid = "container:klarg_chest"
        if place == "place:cragmaw_klarg_cave" and cid in self.world.containers:
            items = [self._item_name(i) for i in self.world.containers[cid].items]
            return {"kind": "narration", "text": msg + " Содержимое: " + ", ".join(items),
                    "container": cid, "view": self.view()}
        return {"kind": "narration", "text": msg, "view": self.view()}

    # ===================================================================== #
    #  Подземелья: туман, секретные ходы, тайловая карта                    #
    # ===================================================================== #
    def _dungeon_of(self, place: str):
        for d in self.world.dungeons.values():
            if place in d.rooms:
                return d
        return None

    def _reveal_secret(self, place: str, secret_room: str, msg: str) -> dict:
        """Открыть секретный проход place→secret_room (реплей через reveal_passage)."""
        self.world.commit("reveal_passage", self.player, payload={"a": place, "b": secret_room})
        self.world.commit("set_flag", self.player, payload={"flag": f"dseen:{secret_room}"})
        self._log_journal(f"Найден тайный ход в «{self._place_name(secret_room)}».")
        self._tick()
        return {"kind": "narration", "view": self.view(),
                "text": msg + f" Открывается скрытый проход в «{self._place_name(secret_room)}»."}

    def dungeon_map(self) -> dict | None:
        """Тайловая карта текущего подземелья с туманом (по dseen-флагам). Для UI."""
        d = self._dungeon_of(self.current_place())
        if not d:
            return None
        from ..gen import dungeon as dg
        cur = self.current_place()
        floors = []
        for f in d.floors:
            rows = []
            for y in range(f.h):
                line = []
                for x in range(f.w):
                    line.append(f.grid[y][x])
                rows.append(line)
            for rid in f.rooms:                           # туман: не пройденные комнаты — глухие
                r = d.rooms[rid]
                if f"dseen:{rid}" not in self.world.flags:
                    for (x, y) in r.cells:
                        rows[y][x] = dg.WALL
                    if r.secret:                          # секретку прячем и саму дверь
                        rows[r.center[1]][r.center[0]] = dg.WALL
            # секретная дверь: глухая стена, пока её не нашли (в MVP секретка одна)
            found_secret = any(fl.startswith("secret_found:") for fl in self.world.flags)
            for y in range(f.h):
                for x in range(f.w):
                    if rows[y][x] == dg.SECRET:
                        rows[y][x] = dg.DOOR if found_secret else dg.WALL
            floors.append({"index": f.index, "w": f.w, "h": f.h,
                           "rows": ["".join(r) for r in rows]})
        return {"site": d.site_key, "current": cur,
                "current_floor": d.rooms[cur].floor if cur in d.rooms else 0, "floors": floors}

    def dungeon_map_text(self) -> str:
        """ASCII текущего подземелья с туманом и меткой игрока (для консоли/отладки)."""
        from ..gen import dungeon as dg
        dm = self.dungeon_map()
        if not dm:
            return "Ты не в подземелье."
        d = self.world.dungeons[dm["site"]]
        cur = dm["current"]
        out = []
        for fl in dm["floors"]:
            rows = [list(r) for r in fl["rows"]]
            for rid in d.floors[fl["index"]].rooms:       # маркеры наполнения видимых комнат
                r = d.rooms[rid]
                if f"dseen:{rid}" not in self.world.flags:
                    continue
                cx, cy = r.center
                mk = None
                if rid == cur:
                    mk = "@"
                elif any(self._is_hostile(n) for n in self.world.spatial.occupants(rid)):
                    mk = "B" if r.role == "boss" else "g"
                if mk and rows[cy][cx] in (dg.FLOOR, dg.ENTRANCE, dg.STAIRS_DN, dg.STAIRS_UP):
                    rows[cy][cx] = mk
            mark = " ◄ ты здесь" if fl["index"] == dm["current_floor"] else ""
            out.append(f"— этаж {fl['index'] + 1}{mark} —")
            out.extend("".join(r) for r in rows)
        return "\n".join(out)

    def _tick(self, n: int = 1) -> None:
        before = self.world.clock.tick
        self.world.clock.advance(n)
        self.lod.tick(self.player)
        self._expire_conditions()                         # временные эффекты (опьянение и пр.) спадают со временем
        # оборот слухов: знания расходятся по NPC. Длинный сон/ожидание = несколько оборотов,
        # чтобы «жизнь города» проходила пропорционально времени (а не один раз на любой прыжок).
        cycles = self.world.clock.tick // config.DIFFUSE_EVERY - before // config.DIFFUSE_EVERY
        if cycles:
            from ..content.facts import diffuse_rumors
            for _ in range(min(cycles, 24)):
                diffuse_rumors(self.world)
        self._fire_due_incidents(before, self.world.clock.tick)  # живой слой событий (этап 3)

    # ===================================================================== #
    #  Живой слой инцидентов: события срабатывают по ходу времени           #
    # ===================================================================== #
    def _incident_digest(self, factions: list, sites: list) -> str:
        def pn(pid):
            p = self.world.spatial.places.get(pid)
            return p.name if p else pid
        lines = ["Фракции (id, бойцов, территория place_id, враги):"]
        for f in factions:
            terr = "; ".join(f"{c} ({pn(c)})" for c in (f.get("controls") or [])[:2]) or "—"
            rivals = ", ".join(f"{o}({v:+.1f})" for o, v in (f.get("relations") or {}).items() if v < -0.1) or "нет"
            lines.append(f"  - {f['id']} «{f['name']}»: {len(f.get('members') or [])}; терр: {terr}; враги: {rivals}")
        lines.append("Опасные места (origin gate:<ключ>):")
        for s in sites[:8]:
            lines.append(f"  - {s['key']} «{s['label']}» — {s['danger']}")
        return "\n".join(lines)

    def _incident_schedule(self):
        """Расписание инцидентов на окно вперёд (LLM-режиссёр / правила). Перегенерится,
        когда время подходит к концу окна — так события идут потоком всю партию."""
        cur = self.world.clock.tick
        if getattr(self, "_inc_sched", None) is None or cur >= getattr(self, "_inc_horizon", -1):
            from .incidents import build_schedule
            from ..content.region import REGION_SITES
            w = self.world
            factions = [{"id": fid, "name": getattr(f, "name", fid),
                         "controls": list(getattr(f, "controls", []) or []),
                         "members": list(getattr(f, "members", []) or []),
                         "relations": dict(getattr(f, "relations", {}) or {})}
                        for fid, f in w.factions.items()]
            sites = [{"key": k, "place": v.get("place"), "danger": v.get("danger"),
                      "label": v.get("label", k)} for k, v in REGION_SITES.items()]
            self._inc_sched = build_schedule(factions, sites, w.seed, cur, cur + 72,
                                             model=self.model, digest=self._incident_digest(factions, sites))
            self._inc_horizon = cur + 72
            self._inc_fired = set()
        return self._inc_sched

    def _fire_due_incidents(self, before: int, after: int) -> None:
        """Срабатывают инциденты, чьё время наступило (effects в мир: слухи, Δ отношений,
        мутации карты). Один раз каждый (учёт по id). Виден игроку через _post."""
        if after <= before:
            return
        from .incidents import apply_incident_effects
        sched = self._incident_schedule()                # может пересоздать _inc_fired (новое окно)
        fired = self.__dict__.setdefault("_inc_fired", set())
        for sp in sched:
            if before < sp.spawn_tick <= after and sp.id not in fired:
                fired.add(sp.id)
                apply_incident_effects(self.world, sp)
                self._spawn_incident_quest(sp)            # угроза-событие → задание на доске
                self.__dict__.setdefault("_inc_pending", []).append(sp)

    def _spawn_incident_quest(self, sp) -> None:
        """Угроза-инцидент (вылазка монстров) → новое задание на доске объявлений, привязанное
        к источнику. Один на сайт (дедуп); сдача — зачистка источника. Реактивно/сейв-сейф."""
        if sp.kind != "monster":
            return
        from ..content.region import REGION_SITES
        site = REGION_SITES.get(sp.source) or {}
        site_place = site.get("place")
        if not site_place or site_place not in self.world.spatial.places:
            return
        qid = f"quest:inc:{sp.source}"                    # один на источник
        if qid in self.world.quests:
            return
        from ..gen.provenance import Provenance
        from ..gen.quest_gen import Predicate, Quest, Rewards, Stage
        from ..content.board import BOARD_PLACE
        label = site.get("label", sp.source)
        reward = Rewards(currency={"gp": 40}, xp=120, faction_rep={"faction:watch": 0.15})
        q = Quest(
            quest_id=qid, kind="board", title=f"Угроза: {sp.label}", giver_ref=BOARD_PLACE, state="offered",
            stages=[
                Stage("do", f"отразить угрозу — зачистить «{label}»",
                      completion_conditions=[Predicate("Flag", [f"cleared:{site_place}"])], next_stages=["turnin"]),
                Stage("turnin", "вернуться к доске объявлений и доложить",
                      completion_conditions=[Predicate("Flag", [f"turnin:{qid}"])],
                      on_complete=[{"effect": "complete"}]),
            ],
            current_stages=[], rewards=reward, framing=sp.desc or sp.label,
            world_bindings=[BOARD_PLACE, site_place],
            provenance=Provenance(source="incident", generator="incident@1.0"))
        q.req_kind = "bounty"
        q.req_ref = site_place
        self.quests.register(q)
        self._log_journal(f"📜 На доске появилось задание: «{q.title}»")

    def _expire_conditions(self) -> None:
        """Снимает состояния с длительностью по игровому времени, чей срок истёк."""
        now = self.world.clock.tick
        for eid, conds in list(self.world.conditions.items()):
            kept = [c for c in conds if not (getattr(c, "duration_kind", None) == "time"
                    and c.until_tick is not None and c.until_tick <= now)]
            if len(kept) != len(conds):
                dropped = {c.name for c in conds} - {c.name for c in kept}
                self.world.conditions[eid] = kept
                if eid == self.player and "опьянение" in dropped:
                    self._log_journal("Хмель отступил — голова проясняется.")

    def _apply_intoxication(self, ticks: int = 6) -> int:
        """Вешает/продлевает «опьянение» (помеха на атаки и проверки) на ticks игровых тиков."""
        from ..rules.conditions import Condition
        conds = self.world.conditions.setdefault(self.player, [])
        cur = next((c for c in conds if c.name == "опьянение"), None)
        if cur:
            cur.until_tick = (cur.until_tick or self.world.clock.tick) + ticks  # ещё кружка → дольше
            return cur.until_tick
        until = self.world.clock.tick + ticks
        conds.append(Condition(name="опьянение", duration_kind="time", until_tick=until, source="drink"))
        return until

    def _do_drink(self, action: Action, text: str) -> dict:
        from ..inventory.container import transfer_currency
        from ..inventory.items import COIN, wallet_value_cp
        iid = self._item_in_carry(text)                   # «выпить зелье …» — расходник при себе
        if iid:
            t = self.world.templates.get(self.world.items[iid].template_id)
            if t and t.category == "consumable":
                return self.use_item(iid)                 # зелье пьём где угодно (эффект из шаблона)
        affs = {a["affordance"] for a in self.affordances_here()}
        if not ({"drink", "inn"} & affs):                 # иначе — выпивка только в заведении
            return {"kind": "system", "text": "Здесь нечего пить — нужна таверна, трактир "
                    "или зелье при себе.", "view": self.view()}
        if wallet_value_cp(self.world.wallets.get(self.player, {})) < 2 * COIN["sp"]:
            return {"kind": "system", "text": "Не хватает монет даже на кружку эля.", "view": self.view()}
        transfer_currency(self.world, self.player, None, {"sp": 2}, actor="drink")  # платим заведению
        self._apply_intoxication()
        self._log_journal("Выпил кружку эля (−2 sp).")
        self._tick()
        drunk = any(c.name == "опьянение" for c in self.world.conditions.get(self.player, []))
        txt = ("Ты осушаешь кружку доброго эля (−2 sp). Тепло растекается по телу, мир чуть "
               "покачивается — рука и глаз уже не так верны.") if drunk else "Ты выпиваешь кружку эля (−2 sp)."
        return {"kind": "narration", "text": txt, "view": self.view()}

    # --- услуги двора: комната/еда (реальные транзакции, не флавор) --------- #
    _ROOM_KW = ("снять комнат", "комнату на ночь", "снять номер", "снять угол", "переночев",
                "ночлег", "заночев", "снять жиль", "снять койк", "на ночлег", "снять эту комнат")
    _MEAL_KW = ("поесть", "перекус", "поужина", "пообеда", "покуша", "похлёбк", "похлебк",
                "горячего поес", "поедим", "перехвати", "поснедать", "трапез", "заказать ед")
    _INN_MENU_KW = ("отдохнуть и перекусить", "что предлага", "какие услуги", "что у вас есть",
                    "меню", "что есть из", "услуги двора", "почём ноч", "сколько за комнат")
    _SLEEP_KW = ("спать", "лечь", "ложусь", "до утра", "отоспат", "отосплюсь", "на боковую",
                 "вздремн", "соснуть", "выспат", "ко сну", "отдохнуть до утра")

    def _inn_service(self, text: str) -> dict | None:
        """Перехват услуг ДО роутера (детерминированно, по affordance места): аренда комнаты
        (открывает под-локацию), еда, меню — реальные транзакции; сон — в снятой комнате."""
        affs = {a["affordance"] for a in self.affordances_here()}
        low = text.lower()
        if "sleep" in affs and any(k in low for k in self._SLEEP_KW):  # в своей комнате — отдых
            return self._sleep_until_morning()
        if not (affs & {"inn", "serve", "eat"}):
            return None
        if any(k in low for k in self._ROOM_KW):
            return self._rent_room()
        if any(k in low for k in self._INN_MENU_KW):
            return self._inn_menu()
        if any(k in low for k in self._MEAL_KW):
            return self._eat_meal()
        return None

    def _inn_menu(self) -> dict:
        return {"kind": "narration",
                "text": "За стойкой предлагают: комната на ночь — 5 sp (своя комната наверху, спать "
                        "там можно в любой момент); горячая похлёбка — 3 sp (подлечиться); "
                        "кружка эля — 2 sp. Скажи, что берёшь: «снять комнату», «поесть» или «выпить».",
                "view": self.view()}

    def _rent_room(self) -> dict:
        from ..inventory.container import transfer_currency
        from ..inventory.items import COIN, wallet_value_cp
        inn = self.current_place()
        rid = f"room:{inn.split(':')[-1]}_rented"
        if f"rented:{inn}" in self.world.flags and rid in self.world.spatial.places:
            return {"kind": "system", "text": "Комната уже за тобой — поднимись к себе "
                    "(выход «Снятая комната») и ложись спать, когда устанешь.", "view": self.view()}
        if wallet_value_cp(self.world.wallets.get(self.player, {})) < 5 * COIN["sp"]:
            return {"kind": "system", "text": "На комнату не хватает (нужно 5 sp).", "view": self.view()}
        transfer_currency(self.world, self.player, None, {"sp": 5}, actor="inn")
        self.world.commit("rent_room", self.player, payload={
            "inn": inn, "room": rid, "name": "Снятая комната",
            "ambiance": "Тесная сухая комнатка наверху: лежанка, табурет, ставни глушат дождь."})
        self._log_journal("Снял комнату на дворе (−5 sp).")
        return {"kind": "narration",
                "text": "Ты платишь 5 sp — комната твоя. Наверху открылась «Снятая комната»: "
                        "поднимись туда (выход наверх) и ложись спать, когда устанешь.",
                "view": self.view()}

    def _sleep_until_morning(self) -> dict:
        h, m = (int(x) for x in self.world.clock.hhmm().split(":"))
        to_morning = (8 * 60 - (h * 60 + m)) % (24 * 60) or 24 * 60   # до ближайших 08:00
        self._tick(max(1, to_morning // config.SIM_MINUTES_PER_TICK))
        st = self.world.get_stats(self.player)
        if st and st.hp < st.max_hp:                      # сон = полное восстановление HP
            self.world.commit("heal", self.player, target=self.player,
                              payload={"amount": st.max_hp - st.hp})
        self._log_journal("Выспался до утра.")
        return {"kind": "narration",
                "text": f"Ты заваливаешься на лежанку и спишь до утра ({self.world.clock.hhmm()}). "
                        f"Силы полностью восстановлены.", "view": self.view()}

    def _eat_meal(self) -> dict:
        from ..inventory.container import transfer_currency
        from ..inventory.items import COIN, wallet_value_cp
        if wallet_value_cp(self.world.wallets.get(self.player, {})) < 3 * COIN["sp"]:
            return {"kind": "system", "text": "На еду не хватает (нужно 3 sp).", "view": self.view()}
        transfer_currency(self.world, self.player, None, {"sp": 3}, actor="inn")
        st = self.world.get_stats(self.player)
        healed = 0
        if st and st.hp < st.max_hp:                      # горячая еда — небольшое лечение
            healed = min(5, st.max_hp - st.hp)
            self.world.commit("heal", self.player, target=self.player, payload={"amount": healed})
        self._tick(2)
        self._log_journal("Поел горячего (−3 sp).")
        extra = f" Восстановлено {healed} HP." if healed else ""
        return {"kind": "narration",
                "text": f"Ты съедаешь миску горячей похлёбки с хлебом (−3 sp).{extra}",
                "view": self.view()}

    # допустимые глаголы движка (валидация выхода LLM-парсера)
    _VERBS = {"move", "talk", "attack", "inspect", "search", "persuade", "intimidate",
              "deceive", "loot", "buy", "sell", "inventory", "wait", "scan", "buyinfo",
              "map", "drink"}
    _MAPINFO_KW = ["сведен", "наводк", "карт", "о дороге", "о пути", "путь к", "дорог к",
                   "что знаешь о", "слух о", "разузнать"]

    _MAP_KW = ["карт", " map", "карту", "карты", "карте", "куда идти", "куда можно",
               "куда пойти", "где я", "местност", "локаци", "окрестност"]
    # физические/импровизированные действия → freeform (а не «реплика»), даже если рядом NPC
    _FREEFORM_KW = ["подбир", "подобрат", "подними", "поднять", "кин", "брос", "метн", "швыр",
                    "толкн", "схват", "оттолк", "перепрыг", "перелез", "взбер", "взбир", "влез",
                    "залаз", "лезу", "карабк", "вылом", "выбить", "поджеч", "подожг", "протисн",
                    "прокрад", "спрята", "перевяз"]
    _OBSERVER_KW = ["наблюда", "следит", "следят", "соглядат", "за мной", "за нами",
                    "кто-то рядом", "кто-нибудь рядом", "не видит ли", "не смотрит ли",
                    "кто-то смотрит", "watching", "следил"]

    def _keyword_intent(self, text: str) -> Action | None:
        """Детерминированный разбор по ключевым словам (приоритетнее LLM)."""
        low = text.lower()
        # более специфичный интент: «не наблюдает ли кто-то?» — раньше общего осмотра
        if any(k in low for k in self._OBSERVER_KW):
            return Action(actor=self.player, verb="scan", tone="neutral")
        # покупка сведений/карты у NPC — специфичнее общего «купить»
        if (("купить" in low or "куплю" in low or "разузнать" in low or "что знаешь" in low)
                and any(k in low for k in self._MAPINFO_KW)):
            return Action(actor=self.player, verb="buyinfo", tone="neutral",
                          target=self._match_npc(text))
        # показать карту/местность — РАНЬШЕ осмотра: «посмотреть карту» ≠ inspect
        if any(k in low for k in self._MAP_KW):
            return Action(actor=self.player, verb="map", tone="neutral")
        # сторона света как команда движения («на север», «вглубь», «N»)
        if self._direction_in(low):
            return Action(actor=self.player, verb="move", tone="neutral")
        for verb, kws in VERB_KEYWORDS.items():
            if any(k in low for k in kws):
                tone = "hostile" if verb in ("attack", "intimidate") else "neutral"
                return Action(actor=self.player, verb=verb, tone=tone,
                              target=self._match_npc(text))
        return None

    _QUERY_TYPES = {"look", "items", "who", "exits", "inventory", "status", "map"}

    def _route(self, text: str) -> dict:
        """Полноценная маршрутизация: онлайн — LLM-роутер; иначе детерминированный фоллбэк.
        Возвращает {kind:'query'|'command', query?, verb?, target?, tone?}."""
        if self.model is not None and self.model.available():
            from ..inference.agents import route_action
            out = route_action(self.model, text, self._intent_context(),
                               [self._display(n) for n in self.npcs_here()],
                               history=self._recent_context())
            r = self._route_from_llm(out, text)
            if r:
                return r
            if config.LLM_REQUIRED:                       # без фоллбэков не падаем в подстроки
                return {"kind": "command", "verb": "freeform", "target": self._match_npc(text)}
        return self._route_offline(text)

    def _route_from_llm(self, out: dict | None, text: str) -> dict | None:
        if not out or out.get("kind") not in ("query", "dialogue", "command", "freeform"):
            return None
        kind = out["kind"]
        if kind == "query":
            q = out.get("query_type")
            low = text.lower()
            # «кто такие/что за/кто это <X>» — вопрос о СУЩНОСТИ к собеседнику, а не «кто здесь»
            if q == "who" and any(k in low for k in ("такие", "такой", "такая", "что за", "кто это")):
                if self.dialogue_partner or self.npcs_here():
                    return {"kind": "command", "verb": "talk",
                            "target": self._match_npc(text) or self.dialogue_partner, "tone": "neutral"}
            return {"kind": "query", "query": q if q in self._QUERY_TYPES else "look"}
        tgt = self._match_npc(out.get("target") if isinstance(out.get("target"), str) else "") \
            or self._match_npc(text)
        tone = out.get("tone", "neutral")
        if kind == "dialogue":
            return {"kind": "command", "verb": "talk", "target": tgt or self.dialogue_partner, "tone": tone}
        verb = out.get("verb")
        if kind == "command" and verb in self._VERBS:
            return {"kind": "command", "verb": verb, "target": tgt, "tone": tone}
        return {"kind": "command", "verb": "freeform", "target": tgt, "tone": tone}

    def _route_offline(self, text: str) -> dict:
        q = self._query_type(text)                        # запрос к миру/себе (вопрос/императив осмотра)
        if q and not self.dialogue_partner and not self._match_npc(text):
            return {"kind": "query", "query": q}
        act = self._parse_intent(text)                    # keyword + named/freeform
        return {"kind": "command", "verb": act.verb, "target": act.target, "tone": act.tone}

    def _parse_intent(self, text: str) -> Action:
        # 1) ЛЁГКАЯ модель-классификатор интента — первой, когда сервер доступен.
        #    Её единственная задача: понять смысл и выбрать БЛИЖАЙШУЮ команду движка
        #    (роль intent → config.INTENT_MODEL, маленький Qwen). Так естественные
        #    формулировки не зависят от хрупких ключевых слов.
        if self.model is not None and self.model.available():
            act = self._model_intent(text)
            if act is not None:
                return act
        # 2) офлайн / модель не уверена → детерминированный keyword-парсер (фоллбэк).
        #    В режиме без фоллбэков (LLM_REQUIRED) keyword-эвристику не используем.
        if not config.LLM_REQUIRED:
            kw = self._keyword_intent(text)
            if kw:
                return kw
        # 3) обращение к присутствующему NPC (по имени или вопрос при ком-то рядом) —
        #    это реплика; идёт диалог — продолжаем его; иначе свободное действие.
        named = self._match_npc(text)
        if any(k in text.lower() for k in self._FREEFORM_KW):   # физическое/импровиз — это freeform
            return Action(actor=self.player, verb="freeform", target=named)
        if self.dialogue_partner or named or ("?" in text and self.npcs_here()):
            return Action(actor=self.player, verb="talk",
                          target=named or self.dialogue_partner)
        return Action(actor=self.player, verb="freeform")

    def _model_intent(self, text: str) -> Action | None:
        """Классификация интента лёгкой моделью → ближайшая команда движка, или None
        (модель не уверена / вернула 'other' / не из набора команд → пусть решит фоллбэк)."""
        from ..inference.agents import parse_intent
        out = parse_intent(self.model, text, self.player,
                           [self._display(n) for n in self.npcs_here()],
                           context=self._intent_context())
        if not out or out.get("needs_clarification"):
            return None
        verb = out.get("verb")
        if verb not in self._VERBS:
            return None
        return Action(actor=self.player, verb=verb,
                      target=self._match_npc(out.get("target") or text),
                      tone=out.get("tone", "neutral"),
                      targets_npc=bool(out.get("target")))

    def _intent_context(self) -> str:
        """Краткий контекст сцены для классификатора интента."""
        place = self._place_name(self.current_place())
        exits = ", ".join(self._place_name(e) for e in self.exits()) or "—"
        affs = ", ".join(a["label"] for a in self.affordances_here()) or "—"
        return f"место={place}; выходы=[{exits}]; можно=[{affs}]"

    def _rel_summary(self, rel, first_meeting: bool) -> str:
        if first_meeting:
            return "stranger; you have never met before; no shared history"
        if rel.trust >= 0.5 or rel.affinity >= 0.5:
            return f"trusted acquaintance (trust {rel.trust:.2f})"
        if rel.fear >= 0.5:
            return f"afraid of you (fear {rel.fear:.2f})"
        if rel.trust <= -0.3 or rel.affinity <= -0.3:
            return "wary, somewhat hostile toward you"
        return f"acquaintance, neutral (trust {rel.trust:.2f})"

    def _memory_summary(self, npc: str, rel, first_meeting: bool, topic: str = "") -> str:
        """Грунт для нарратора: отношение + ЧТО NPC реально помнит об игроке. Первая встреча —
        жёсткий запрет выдумывать знакомство; иначе — ссылаться ТОЛЬКО на реальную память
        (чинит галлюцинации «узнаю тебя по телеге у ворот» и неверные «помню, ты говорил…»)."""
        base = self._rel_summary(rel, first_meeting)
        if first_meeting:
            return (base + ". CRITICAL: you have NEVER met this person before — do NOT pretend to "
                    "recognise them, do NOT invent any shared past or earlier conversation.")
        mems = self.cognition.retrieve(npc, topic or "", self.player).memories
        mem_txt = "; ".join(getattr(m, "text", "") for m in mems[:6] if getattr(m, "text", ""))
        if mem_txt:
            return (base + f". What you ACTUALLY remember about this person (reference ONLY this, "
                    f"do not invent other shared history): {mem_txt}")
        return base

    def _remember_salient(self, npc: str, text: str) -> None:
        """Извлекает из реплики игрока заметное (имя / цель пути / кого ищет) → отдельные ноды
        памяти NPC, чтобы узнавание на возврате было ТОЧНЫМ, а не выдуманным."""
        import re
        low = text.lower()
        m = re.search(r"(?:меня зовут|зови меня|моё имя|мое имя)\s+([а-яёa-z]{2,16})", low)
        if m:
            self.cognition.observe(npc, f"игрок представился: {m.group(1).capitalize()}", importance=7)
        m2 = re.search(r"(?:иду|идти|направля\w+|держу путь|путь лежит|отправля\w+)\s+(?:в|к|на|до)\s+([а-яё«»\" ]{3,30})", low)
        if m2:
            self.cognition.observe(npc, f"игрок направляется в: {m2.group(1).strip(chr(32)+chr(34)+'«»')[:32]}", importance=6)
        m3 = re.search(r"(?:я ищу|разыскиваю|ищу пропавш\w*|в поисках)\s+([а-яё«»\" ]{3,30})", low)
        if m3:
            self.cognition.observe(npc, f"игрок ищет: {m3.group(1).strip(chr(32)+chr(34)+'«»')[:32]}", importance=6)

    def _npc_greeting(self, npc: str, rel, first_meeting: bool) -> str:
        """Приветствие NPC при инициации — заземлено, без выдуманной истории."""
        persona = self.world.ecs.get(npc, Persona)
        if self.model is not None:
            from ..inference.agents import render_dialogue
            line = render_dialogue(
                self.model, persona, self._memory_summary(npc, rel, first_meeting),
                situation=("A stranger walks up and greets you for the first time"
                           if first_meeting else "Someone you know greets you"),
                player_line="", intent="greet and ask what they want",
                scene=self._narrator_context(), mode="greeting")
            if line:
                return line
        return self._greeting_fallback(persona, first_meeting)

    def _npc_reply(self, npc: str, decision: dict, topic: str, rel, first_meeting, hooks,
                   gate_level: float | None = None) -> str:
        persona = self.world.ecs.get(npc, Persona)
        action = decision.get("action", "respond")
        action = action if isinstance(action, str) else "respond"
        name = self._display(npc)
        sharing = action in ("share_info", "respond")
        items, news, exhausted = ([], False, False)
        if sharing:
            items, news, exhausted = self._facts_for_reply(npc, rel, topic, gate_level)
        if exhausted:                                   # просил новости, а всё уже рассказано → честно, без выдумки
            return (f"{name} разводит руками: «Да ничего нового, чего бы ты от меня "
                    f"уже не слышал. Пока тихо».")
        feed = items[:2]                                # 1–2 факта: что отдали нарратору ≈ что игрок узнаёт
        if self.model is not None:
            from ..inference.agents import render_dialogue
            line = render_dialogue(
                self.model, persona, self._memory_summary(npc, rel, first_meeting, topic),
                situation=f"The player says/asks: «{topic}». Your stance: {action}.",
                player_line=topic, intent=action, scene=self._narrator_context(),
                facts=[it["fact"] for it in feed], mode="dialogue")
            if line and not self._degenerate(line):     # отсеять мусорный вывод модели («??????»)
                if sharing:
                    self._record_player_learned(npc, feed)
                return self._maybe_hook(line, hooks)
        # заземление офлайн / при сбое модели: называем РЕАЛЬНЫЙ факт, без выдумки
        share_line = f"{name}: «Раз уж спрашиваешь — слушай.»"
        if action == "share_info" and feed:
            self._record_player_learned(npc, feed[:1])
            share_line = f"{name} понижает голос: «Раз уж спрашиваешь — {feed[0]['fact']}.»"
        templates = {
            "share_info": share_line,
            "withhold": f"{name} уклончиво пожимает плечами: «Не моё это дело — болтать с незнакомцами».",
            "trade": f"{name}: «Глянь товар, цены честные».",
            "flee": f"{name} в страхе пятится прочь.",
            "call_guards": f"{name} кричит: «Стража!»",
            "yield": f"{name} поднимает руки: «Не трогай меня!»",
            "refuse": f"{name}: «Нет. И разговор окончен».",
            "respond": f"{name} сдержанно кивает: «И тебе не хворать. Чего хотел?»",
        }
        return self._maybe_hook(templates.get(action, templates["respond"]), hooks)

    # --- слухи как память: что игрок знает / узнаёт / приносит сам ---------- #
    _NEWS_KW = ("нов", "слух", "вест", "молв", "сплетн", "что слышно", "что происходит",
                "что творит", "что в город", "чем живёт", "чем живет", "свеж")

    def _is_news_query(self, topic: str | None) -> bool:
        low = (topic or "").lower()
        return any(k in low for k in self._NEWS_KW)

    def _player_knows(self) -> set:
        """fact_id, которые игрок уже знает (рёбра (player, knows, …) в графе знаний)."""
        return set(self.world.kg.objects_of(self.player, "knows"))

    def _facts_for_reply(self, npc: str, rel, topic: str | None, gate_level):
        """Факты для реплики. На запрос НОВОСТЕЙ — только неизвестные игроку (unknown-first):
        пусто → exhausted («ничего нового»). На предметный вопрос — самые релевантные
        (повтор допустим). Возвращает (items, news, exhausted)."""
        news = self._is_news_query(topic)
        exclude = self._player_knows() if news else None
        items = self.cognition.recall(npc, topic or "", rel, gate_level=gate_level, k=8, exclude=exclude)
        if news:                                          # свежесть: происшествия-инциденты — вперёд старого лора
            items = sorted(items, key=lambda it: 0 if "событие" in (it.get("tags") or []) else 1)
        return items, news, (news and not items)

    def _record_player_learned(self, npc: str, items: list) -> None:
        """Игрок узнал раскрытые факты → ребро (player, knows, fid) тем же событием learn_fact,
        что и диффузия между NPC. «Ничего нового» теперь вытекает из памяти, без костыля."""
        for it in items:
            fid = it.get("fact_id")
            if fid and not self.world.kg.has(self.player, "knows", fid):
                self.world.commit("learn_fact", npc, payload={"npc": self.player, "fact": fid})

    def _player_shares_with(self, npc: str, topic: str) -> None:
        """Реплика игрока по теме: если игрок знает релевантный факт, которого NPC не знает,
        NPC перенимает его (игрок — источник молвы) тем же событием learn_fact."""
        import re
        qtoks = {t for t in re.split(r"[^0-9a-zа-яё]+", (topic or "").lower()) if len(t) >= 4}
        if not qtoks:
            return
        npc_knows = set(self.world.kg.objects_of(npc, "knows"))
        for fid in self._player_knows():
            if fid in npc_knows:
                continue
            fact = self.world.facts.get(fid)
            if fact is None:
                continue
            ftoks = set(re.split(r"[^0-9a-zа-яё]+", getattr(fact, "text", "").lower()))
            if qtoks & ftoks:                           # реплика пересекается с фактом игрока
                self.world.commit("learn_fact", self.player, payload={"npc": npc, "fact": fid})
                break

    @staticmethod
    def _degenerate(line: str) -> bool:
        """Вырожденный вывод модели (повтор «?????», почти нет букв) → не показывать, уйти в факт."""
        s = (line or "").strip()
        letters = sum(ch.isalpha() for ch in s)
        if letters < 2:
            return True
        return len(s) >= 8 and letters < len(s) * 0.4

    def _maybe_hook(self, line: str, hooks: list[str]) -> str:
        if hooks:
            q = self.world.quests.get(hooks[0])
            if q and q.giver_lines:
                line += f" «{q.giver_lines[0]}»"
        return line

    def _greeting_fallback(self, persona, first_meeting: bool) -> str:
        name = persona.name if persona else "Незнакомец"
        arch = (persona.archetype or persona.profession or "") if persona else ""
        g = {
            "innkeeper": f"{name} протирает кружку и приветливо кивает: «Добро пожаловать в «Каменный Холм», путник. Комнату, эль или, может, новости?»",
            "merchant": f"{name} окидывает тебя оценивающим взглядом: «Чем могу служить? Товар у меня добрый».",
            "guard": f"{name} меряет тебя взглядом: «Чужак? По какому делу в Фэндалине?»",
            "townmaster": f"{name} нервно поправляет воротник: «Да-да? Чем могу быть полезен… по-быстрому?»",
            "priest": f"{name} мягко склоняет голову: «Да хранит тебя удача, странник. Чем могу помочь?»",
        }.get(arch)
        if g:
            return g
        return f"{name} вопросительно смотрит на тебя: «Не припомню тебя, незнакомец. Чем могу помочь?»"

    def _describe_npc(self, npc: str) -> str:
        p = self.world.ecs.get(npc, Persona)
        if not p:
            return "Ничего особенного."
        epithet = f" ({p.epithet})" if p.epithet else ""
        traits = ", ".join(p.traits) if p.traits else "обычный"
        prof = f", {p.profession}" if p.profession else ""
        marks = f" Следы: {'; '.join(p.marks)}." if p.marks else ""   # синяки/метки от действий
        return f"{p.name}{epithet} — {p.race}{prof}. {traits.capitalize()}.{marks}"

    def _inventory_text(self) -> str:
        carry = self.world.containers.get(f"carry:{ids.name_of(self.player)}")
        items = [self._item_name(i) for i in carry.items] if carry else []
        wallet = self.world.wallet(self.player)
        coins = ", ".join(f"{v} {k}" for k, v in wallet.items() if v)
        return f"Инвентарь: {', '.join(items) or 'пусто'}. Кошелёк: {coins or 'пусто'}."

    # --------------------------------------------- инвентарь/экипировка ----- #
    _EQUIP_SLOTS = ["main_hand", "off_hand", "armor"]
    _SLOT_RU = {"main_hand": "основная рука", "off_hand": "вторая рука", "armor": "броня"}

    def _slot_for(self, tmpl, eq: dict) -> str | None:
        """В какой слот встаёт предмет (с учётом занятых): оружие/щит/броня."""
        if not tmpl:
            return None
        tags = tmpl.tags or ()
        if "shield" in tags:
            return "off_hand"
        if tmpl.category == "armor":
            return "armor"
        if tmpl.category == "weapon":
            if "two_handed" in tags:
                return "main_hand"
            return "off_hand" if "main_hand" in eq else "main_hand"
        return None

    def inventory_view(self) -> dict:
        from ..inventory import container as invc
        carry = self.world.containers.get(f"carry:{ids.name_of(self.player)}")
        eq = invc._equipped(self.world, self.player)
        items = []
        for iid in (carry.items if carry else []):
            inst = self.world.items.get(iid)
            if not inst:
                continue
            tmpl = self.world.templates.get(inst.template_id)
            equipped = inst.equipped_slot is not None
            target = None if equipped else self._slot_for(tmpl, eq)
            items.append({
                "id": iid, "name": self._item_name(iid),
                "category": tmpl.category if tmpl else "", "qty": inst.quantity,
                "desc": inst.description or "", "equipped": equipped,
                "slot_ru": self._SLOT_RU.get(inst.equipped_slot or "", ""),
                "equippable": target is not None,
                "usable": bool(tmpl and tmpl.category == "consumable")})
        slots = {self._SLOT_RU[s]: (self._item_name(eq[s].instance_id) if s in eq else None)
                 for s in self._EQUIP_SLOTS}
        return {"slots": slots, "items": items, "wallet": self._coins(),
                "ac": invc.armor_class(self.world, self.player)}

    def equip_item(self, iid: str) -> dict:
        from ..inventory import container as invc
        inst = self.world.items.get(iid)
        tmpl = self.world.templates.get(inst.template_id) if inst else None
        if not inst:
            return {"kind": "system", "text": "Нет такого предмета.", "view": self.view()}
        slot = self._slot_for(tmpl, invc._equipped(self.world, self.player))
        if not slot:
            return {"kind": "system", "text": "Это нельзя экипировать.", "view": self.view()}
        try:
            invc.equip(self.world, self.player, iid, slot)
        except invc.InventoryError as e:
            return {"kind": "system", "text": f"Не удалось: {e}", "view": self.view()}
        res = self.look()
        res["text"] = (f"Ты берёшь {self._item_name(iid)} ({self._SLOT_RU[slot]}). "
                       f"AC {invc.armor_class(self.world, self.player)}.")
        return res

    def unequip_item(self, iid: str) -> dict:
        from ..inventory import container as invc
        invc.unequip(self.world, self.player, iid)
        res = self.look()
        res["text"] = f"Ты убираешь {self._item_name(iid)}. AC {invc.armor_class(self.world, self.player)}."
        return res

    def use_item(self, iid: str) -> dict:
        """Применить расходник: эффекты берутся из шаблона (base_stats) — работает для любого
        зелья/эликсира, а не только лечения."""
        from ..gen.seeds import subseed
        from ..rules.dice import roll_expr
        inst = self.world.items.get(iid)
        tmpl = self.world.templates.get(inst.template_id) if inst else None
        if not inst or not tmpl or tmpl.category != "consumable":
            return {"kind": "system", "text": "Это нельзя использовать.", "view": self.view()}
        nm = self._item_name(iid)
        bs = tmpl.base_stats or {}
        verb = "осушаешь" if ("зель" in nm.lower() or "элик" in nm.lower()
                              or "potion" in inst.template_id) else "используешь"
        parts = [f"Ты {verb} {nm}."]
        if bs.get("heal"):                                # лечение по формуле шаблона
            seed = subseed(self.world.seed, "use", iid, self.world.clock.tick) & 0x7FFFFFFF
            heal = roll_expr("use_potion", str(bs["heal"]), seed, source="server_seeded").total
            self.world.commit("heal", self.player, target=self.player, payload={"amount": heal})
            parts.append(f"Восстановлено {heal} HP.")
        if bs.get("cure"):                                # антидот: снять отраву/дурман
            conds = self.world.conditions.get(self.player, [])
            cured = [c for c in conds if c.name in ("poisoned", "отравление", "опьянение")]
            if cured:
                self.world.conditions[self.player] = [c for c in conds if c not in cured]
                parts.append("Отрава и дурман отступают.")
        self.world.commit("item_consume", self.player,
                          payload={"container": f"carry:{ids.name_of(self.player)}",
                                   "instance": iid, "amount": 1})
        res = self.look()
        res["text"] = " ".join(parts)
        return res

    def _display(self, eid: str) -> str:
        p = self.world.ecs.get(eid, Persona)
        if p:
            return p.epithet or p.name
        return ids.name_of(eid)

    def _place_name(self, pid: str) -> str:
        p = self.world.spatial.places.get(pid)
        return p.name if p else pid

    def _item_name(self, iid: str) -> str:
        inst = self.world.items.get(iid)
        if not inst:
            return iid
        if inst.custom_name:
            return inst.custom_name
        tmpl = self.world.templates.get(inst.template_id)
        base = tmpl.name if tmpl else inst.template_id
        return f"{base}×{inst.quantity}" if inst.quantity > 1 else base

    def _match_npc(self, text: str) -> str | None:
        """Сопоставляет ссылку игрока с присутствующим NPC по имени, эпитету и рус.
        алиасам. Стем-матч (как у _match_place) терпит падежи: «Гарэле/Гарэлой»,
        «Кларга/Кларгу». При нескольких NPC рядом выбираем с наибольшим совпадением."""
        import re
        low = text.lower()
        toks = [t for t in re.split(r"[^0-9a-zа-яё]+", low) if len(t) >= 3]
        best, best_score = None, 0
        for npc in self.npcs_here():
            p = self.world.ecs.get(npc, Persona)
            if not p:
                continue
            forms = [p.name.lower()]
            if p.epithet:
                forms.append(p.epithet.lower())
            forms += [a.lower() for a in getattr(p, "aliases", [])]
            score = 0
            for form in forms:
                if form and form in low:                  # полное вхождение формы
                    score = max(score, 5)
                for w in form.split():
                    if len(w) < 3:
                        continue
                    stem = w[:5]
                    if any(t.startswith(stem) or stem.startswith(t) for t in toks):
                        score += 1
            if score > best_score:
                best, best_score = npc, score
        return best

    def _direction_in(self, low: str) -> str | None:
        from ..world.spatial import DIR_ALIASES
        words = set(low.replace(",", " ").split())
        for alias, canon in DIR_ALIASES.items():
            if alias in words or (len(alias) > 3 and alias in low):
                return canon
        return None

    # разговорные синонимы локаций (стем → place_id); участвуют в подборе как кандидаты,
    # поэтому коллизия с реальным именем (две «таверны») всплывает как неоднозначность
    _PLACE_ALIASES = {"город": "place:phandalin_square", "площад": "place:phandalin_square",
                      "фэндалин": "place:phandalin_square", "рынок": "place:phandalin_square",
                      "рынк": "place:phandalin_square", "базар": "place:phandalin_square",
                      "дикие": "place:phandalin_wilds", "пустош": "place:phandalin_wilds",
                      "таверн": "building:stonehill_inn", "трактир": "building:stonehill_inn",
                      "постоял": "building:stonehill_inn",
                      "лавк": "building:barthens_provisions", "бартен": "building:barthens_provisions",
                      "львинощ": "building:lionshield_coster", "lionshield": "building:lionshield_coster",
                      "ратуш": "building:townmaster_hall", "святил": "building:shrine_of_luck"}

    def _place_candidates(self, text: str) -> list[tuple]:
        """Достижимые локации, подходящие под текст, со счётом (имя + синоним). Стем-матч
        под рус. падежи. Сортировка: счёт ↓, затем известные раньше, затем ближе по графу.
        Возвращает [(pid, score, hops)]."""
        import re
        low = text.lower()
        sp = self.world.spatial
        cur = self.current_place()
        toks = [t for t in re.split(r"[^0-9a-zа-яё]+", low) if len(t) >= 3]
        scores: dict[str, int] = {}
        for pid, place in sp.places.items():
            if pid == cur or sp.hops_between(cur, pid) is None:
                continue
            name = place.name.lower()
            sc = 5 if name in low else 0
            for w in name.split():
                if len(w) >= 4 and any(t.startswith(w[:5]) or w[:5].startswith(t) for t in toks):
                    sc += 1
            if sc:
                scores[pid] = sc
        for k, pid in self._PLACE_ALIASES.items():        # синоним = кандидат (тай с именем → уточнение)
            if k in low and pid != cur and pid in sp.places and sp.hops_between(cur, pid) is not None:
                scores[pid] = max(scores.get(pid, 0), 1)
        return sorted(((pid, sc, sp.hops_between(cur, pid)) for pid, sc in scores.items()),
                      key=lambda x: (-x[1], not self._knows_place(x[0]), x[2]))

    # обобщённые слова выхода → направление-ребро текущего узла (выйти из комнаты «вниз/наружу»)
    _GEN_EXIT = {"спуст": "down", "вниз": "down", "внизу": "down", "первый этаж": "down",
                 "общий зал": "down", "в зал": "down", "наверх": "up", "вверх": "up",
                 "наружу": "out", "на улицу": "out"}

    def _match_place(self, text: str) -> str | None:
        sp = self.world.spatial
        cur = self.current_place()
        low = text.lower()
        d = self._direction_in(low)                      # 1) сторона света — однозначный сосед
        if d:
            exits = sp.exits_of(cur)
            if d in exits:
                return exits[d]
        cands = self._place_candidates(text)             # 2) лучшее по имени/синониму (известные — раньше)
        if cands:
            return cands[0][0]
        # 3) обобщённый выход: «спуститься/вниз/наружу/общий зал» → ребро по направлению
        exits = sp.exits_of(cur)
        for kw, dd in self._GEN_EXIT.items():
            if kw in low and dd in exits:
                return exits[dd]
        # 4) «выйти/наружу/обратно/назад» из локации с единственной связью — это очевидный выход
        conns = sp.connections(cur)
        if len(conns) == 1 and any(k in low for k in ("выйт", "выход", "наружу", "обратно", "назад", "вон отсюда")):
            return conns[0]
        return None

    _AMBIG_SHARE = 0.30                                    # доля вероятности, при которой вариант стоит предложить

    def _rank_places(self, text: str) -> list[dict]:
        """Модель локаций: вместо одной локации — список ИЗВЕСТНЫХ кандидатов под фразу
        с долями вероятности p (сумма = 1) из нормированного счёта совпадения (имя+синоним).
        Нельзя предложить место, которого игрок не знает, — поэтому только известные."""
        known = [(pid, sc) for pid, sc, _h in self._place_candidates(text)
                 if self._knows_place(pid)]
        total = sum(sc for _p, sc in known)
        if not total:
            return []
        return [{"id": pid, "name": self._place_name(pid), "p": round(sc / total, 3)}
                for pid, sc in known]

    def _movement_options(self, text: str) -> list[dict]:
        """Если две и более известных локации имеют высокую долю вероятности — вернуть их
        как варианты для явного выбора игроком; иначе [] (решаем сами). Сторона света — нет."""
        if self._direction_in(text.lower()):
            return []
        high = [r for r in self._rank_places(text) if r["p"] >= self._AMBIG_SHARE]
        return high if len(high) >= 2 else []

    # --- знание мест и распознавание перемещения ------------------------- #
    _MOVE_CUES = ("иди", "идти", "иду", "пойд", "пойт", "пошёл", "пошел", "подойд",
                  "подойти", "подойм", "подним", "подня", "наверх", "вверх", "вниз",
                  "спуст", "двигай", "двин", "направ", "войти", "войду", "зайти", "зайду",
                  "выйт", "выход", "наружу", "уйт", "уход", "перейти", "перехож",
                  "топай", "шагай", "доберись", "добрать", "дойт", "дойд", "отправ",
                  "сходи", "сходить", "go ", "вернуть", "вернусь", "вернёт")
    _EXAMINE_CUES = ("осмотр", "оглядыв", "разгляд", "прочит", "почита", "читать", "изуч",
                     "глян", "посмотр", "что на ", "что там", "обыщ", "обыска", "что написа")

    _DIALOG_CUES = ("здравству", "привет", "доброго", "хозяин", "меня зовут", "как тебя",
                    "как вас", "расскажи", "поведай", "слыхал", "слышал", "знаешь ли",
                    "помнишь", "узнаёшь", "узнаешь", "что слышно", "правда ли", "спрош",
                    "представ", "я наёмник", "я ищу", "скажу", "не слыхал")

    def _movement_intent(self, text: str) -> str | None:
        """Детерминированно распознаёт явную команду «идти/подойти к <место>» к узнаваемой
        локации (а НЕ осмотр/чтение и НЕ реплику NPC). Возвращает place_id или None."""
        low = text.lower()
        if any(k in low for k in self._EXAMINE_CUES):     # «осмотреть доску» ≠ «подойти к доске»
            return None
        # разговорная фраза к NPC не должна перехватываться движением
        # («Меня зовут Кейл, иду в Логово…» — это реплика, а не команда идти)
        if any(k in low for k in self._DIALOG_CUES):
            return None
        if "?" in text and (self.dialogue_partner or self.npcs_here()):
            return None
        if not (any(k in low for k in self._MOVE_CUES) or self._direction_in(low)):
            return None
        return self._match_place(text)

    def _known_places(self) -> set[str]:
        """Места, куда игрок в принципе может направиться: примыкающие выходы (видны со
        сцены) + текущее + всё, о чём есть запись на карте игрока (разведано / со слов)."""
        cur = self.current_place()
        known = {cur} | set(self.world.spatial.connections(cur))
        for b in self.world.player_maps.get(self.player, {}).values():
            if b.get("place"):
                known.add(b["place"])
        return known

    def _knows_place(self, place_id: str) -> bool:
        return place_id in self._known_places()

    def travel_to(self, place_id: str) -> dict:
        """Санкционированное перемещение «через карту»: многоходовый путь допустим,
        гейт только по знанию (карта — обзор города/региона). Текстовый гейт расстояния
        здесь НЕ применяется — карта и есть способ дойти до далёкого известного места."""
        sp = self.world.spatial
        if place_id not in sp.places:
            return {"kind": "system", "text": "Такого места нет.", "view": self.view()}
        cur = self.current_place()
        if place_id == cur:
            look = self.look()
            look["text"] = "Ты уже здесь. " + look["text"]
            return self._post(look, "look")
        if not self._knows_place(place_id):
            return {"kind": "narration", "view": self.view(),
                    "text": f"Ты ещё не разведал «{self._place_name(place_id)}» — "
                            f"сначала узнай, где это (на месте или со слов)."}
        return self._post(self._commit_move(place_id), "move")

    def _containers_here(self) -> list[str]:
        place = self.current_place()
        out = []
        for cid, c in self.world.containers.items():
            if c.kind == "corpse":
                out.append(cid)                       # трупы лутаются где угодно (упрощённо)
            elif c.kind == "chest" and place == "place:cragmaw_klarg_cave":
                out.append(cid)                       # тайник Klarg доступен в его пещере
        return out

    def _shop_here(self) -> str | None:
        place = self.current_place()
        mapping = {"building:barthens_provisions": "shop:barthen",
                   "building:lionshield_coster": "shop:lionshield"}
        return mapping.get(place)

    def _is_hostile(self, npc: str) -> bool:
        if f"hostile:{npc}" in self.world.flags:          # озлоблен рантайм-событием (напр., напали)
            return True
        p = self.world.ecs.get(npc, Persona)
        return bool(p and p.faction in ("faction:cragmaw", "faction:redbrands"))

    def _do_freeform(self, action: Action, text: str) -> dict:
        return self._resolve_freeform(text, action.target)

    # --- общий резолвер любого свободного действия (боевого и не боевого) ---
    #   intent → plausibility → нужен ли бросок и с какой вероятностью → результат.
    _SKILL_KW = [                                          # (ключи, навык) для офлайн-арбитра
        (("перепрыг", "прыг", "влез", "взбер", "перелез", "карабк", "залез", "подтян",
          "вылом", "выбить", "толкн", "сдвин", "оттолк", "поднять", "подними", "удерж",
          "кин", "брос", "метн", "швырн", "разорв", "сорв"), "athletics"),
        (("прокрад", "крад", "подкрад", "спрятат", "притаит", "тихо", "бесшум", "укрыт"), "stealth"),
        (("увернут", "проскольз", "протисн", "балансир", "кувыр", "акробат", "пролез"), "acrobatics"),
        (("взлом", "отмыч", "карман", "стащ", "стянут", "ловк", "фокус", "обезвред"), "sleight_of_hand"),
        (("заметить", "высмотр", "приглядет", "прислуш", "услыш", "разглядет", "осмотрет"), "perception"),
        (("изуч", "разобрат", "понять", "вычисл", "осмотреть", "обыщ", "исслед", "следы"), "investigation"),
        (("вспомн", "что знаю", "припомн", "магия", "заклинан", "руны"), "arcana"),
        (("перевяз", "лечит", "рану", "оказать помощь", "медициy"), "medicine"),
        (("убедить", "уговор", "упрос", "разжалоб", "договор"), "persuasion"),
        (("обман", "соврат", "притвор", "выдать себя", "блеф"), "deception"),
        (("запуг", "угроз", "припугн", "застращ"), "intimidation"),
    ]

    def _guess_skill(self, low: str) -> str:
        for keys, skill in self._SKILL_KW:
            if any(k in low for k in keys):
                return skill
        return "athletics"                                # дефолт: физическое усилие

    def _norm_skill(self, raw: str | None, text: str) -> str:
        """Приводит навык из любого формата арбитра («DEX + Stealth», «thrown») к валидному
        ключу 5e; иначе — эвристика по тексту действия."""
        from ..rules.srd import SKILL_ABILITY
        s = (raw or "").lower()
        for sk in SKILL_ABILITY:
            if sk in s or sk.replace("_", " ") in s:
                return sk
        alias = {"thrown": "athletics", "throw": "athletics", "climb": "athletics",
                 "jump": "athletics", "lift": "athletics", "sneak": "stealth", "hide": "stealth",
                 "lockpick": "sleight_of_hand", "thiev": "sleight_of_hand", "balance": "acrobatics",
                 "tumble": "acrobatics", "spot": "perception", "listen": "perception",
                 "persuade": "persuasion", "convince": "persuasion", "lie": "deception",
                 "threaten": "intimidation"}
        for k, sk in alias.items():
            if k in s:
                return sk
        for a, sk in {"dex": "acrobatics", "str": "athletics", "cha": "persuasion",
                      "int": "investigation", "wis": "perception", "con": "athletics"}.items():
            if a in s:
                return sk
        return self._guess_skill(text.lower())

    _TRIVIAL_KW = ["сажус", "сесть", "присяд", "встаю", "встать", "передохн", "перевож дух",
                   "перевести дух", "отдыха", "отдохн", "дышу", "жду", "подожд", "киваю",
                   "оглядыва", "озира"]

    def _skill_kw(self, low: str) -> str | None:
        """Навык по ключевым словам, или None если действие не похоже на проверку навыка."""
        for keys, skill in self._SKILL_KW:
            if any(k in low for k in keys):
                return skill
        return None

    def _arbiter_fallback(self, text: str, p: float) -> dict:
        """Детерминированный арбитр (офлайн): по правдоподобию и ключевым словам.
        Без явного навыка и без риска бросок НЕ нужен (а не дефолт-athletics).
        Онлайн эту роль точнее играет агент-арбитр (decide_resolution)."""
        low = text.lower()
        if any(k in low for k in self._TRIVIAL_KW):       # будничное → без броска
            return {"resolution": "auto_success"}
        skill = self._skill_kw(low)
        risky = p < 0.5 or any(k in low for k in ("страж", "враг", "противник", "замок", "против",
                                                  "часов", "охран", "опасн", "сложн", "трудн"))
        if skill is None and not risky:                   # нет навыка и риска → просто получается
            return {"resolution": "auto_success"}
        dc = max(5, min(25, round(20 - p * 16)))          # p 0.8→7, 0.5→12, 0.3→15
        return {"resolution": "roll", "skill": skill or "athletics", "dc": dc}

    @staticmethod
    def _success_pct(req) -> int:
        need = (req.dc or 10) - req.modifier              # нужно выкинуть ≥ need на d20
        base = max(0, min(20, 21 - need)) / 20
        if req.advantage > 0:
            base = 1 - (1 - base) ** 2
        elif req.advantage < 0:
            base = base ** 2
        return round(base * 100)

    _HOSTILE_KW = ["кин", "кид", "брос", "метн", "мета", "швыр", "ударь", "бью", "бей",
                   "толкн", "пихн", "атак", "напад", "руб", "пни", "пина", "режу", "коли",
                   "стреля", "пыря", "плюн", "плюю", "плева", "врежу", "вмаж", "душу", "пощёчин",
                   "пощечин"]

    def _aggro(self, target: str) -> None:
        """Нападение озлобляет цель, её подельников рядом и (если жертва мирная) стражу;
        репутация с задетыми фракциями падает. Всё событийно → реплей-safe."""
        def hostile(n):
            self.world.commit("set_flag", self.player, payload={"flag": f"hostile:{n}"})
        hostile(target)
        p = self.world.ecs.get(target, Persona)
        fac = p.faction if p else None
        for n in self.npcs_here():                        # подельники той же фракции
            np = self.world.ecs.get(n, Persona)
            if n != target and np and np.faction and np.faction == fac:
                hostile(n)
        civilian = (fac is None) or (p and p.archetype in ("guard", "commoner", "townmaster"))
        if civilian:                                      # нападение на мирного — преступление
            for n in self.npcs_here():
                np = self.world.ecs.get(n, Persona)
                if n != target and np and (np.faction == "faction:watch" or np.archetype == "guard"):
                    hostile(n)
            self.world.commit("faction_rep", self.player, payload={"faction": "faction:watch", "delta": -0.2})
        if fac:
            self.world.commit("faction_rep", self.player, payload={"faction": fac, "delta": -0.15})

    def _improvised_attack(self, text: str, target: str) -> dict:
        """Враждебное freeform-действие по NPC: бросок vs AC → урон при попадании →
        агро (цель/подельники/стража) → начало боя."""
        if not (self.world.ecs.exists(target) and self.world.is_alive(target)):
            return self._resolve_freeform(text, None)
        from ..rules.checks import ability_mod
        st = self.world.get_stats(target)
        ac = st.ac_base if st else 12
        strmod = ability_mod(self.world, self.player, "str")
        req = self.dice.request_player(kind="attack", dice="1d20", modifier=strmod, dc=ac,
                                       roller=self.player,
                                       context={"skill": "импровиз. атака", "target": target})
        pct = self._success_pct(req)
        tname = self._display(target)
        action = Action(actor=self.player, verb="attack", target=target)

        def resume(result: RollResult) -> dict:
            outcome = self.rules.adjudicate(action, req, result)
            dealt = 0
            if outcome.success:
                dmg = self.dice.roll_seeded("damage", "1d4", modifier=strmod, roller=self.player)
                dealt = max(1, dmg.total)
                self.world.commit("damage", self.player, target=target,
                                  payload={"amount": dealt}, roll=dmg.to_record("1d4"))
            self._aggro(target)
            self._tick()
            head = (f"Попадание по {tname} — {dealt} урона!" if outcome.success
                    else f"Мимо {tname}.")
            enemies = [n for n in self.npcs_here() if self._is_hostile(n) and self.world.is_alive(n)]
            if enemies:
                cs = self.start_combat(enemies)
                cs["text"] = head + " На тебя бросаются — начинается бой!"
                return cs
            return {"kind": "narration", "text": head + " Твоя выходка не осталась без последствий.",
                    "view": self.view()}

        return self._suspend(req, resume,
                             f"Импровизированная атака по {tname}: бросок против AC {ac} "
                             f"(~{pct}% попадания).")

    # --- стойкие изменения предметов (любое freeform-изменение сохраняется) ---
    def _carry_items(self) -> list[str]:
        c = self.world.containers.get(f"carry:{ids.name_of(self.player)}")
        return list(c.items) if c else []

    def _item_in_carry(self, text: str) -> str | None:
        """Находит экземпляр в инвентаре, упомянутый в тексте (стем-матч по имени;
        порог 3 буквы — чтобы ловить короткие «меч», «лук», «нож»)."""
        import re
        toks = [t for t in re.split(r"[^0-9a-zа-яё]+", text.lower()) if len(t) >= 3]
        for iid in self._carry_items():
            for w in re.split(r"[^0-9a-zа-яё]+", self._item_name(iid).lower()):
                if len(w) >= 3 and any(t.startswith(w[:5]) or w.startswith(t[:5]) for t in toks):
                    return iid
        return None

    def _describe_item(self, iid: str) -> str:
        """Заземлённое описание экземпляра: имя + флавор + накопленные изменения."""
        inst = self.world.items.get(iid)
        if not inst:
            return "Такого предмета у тебя нет."
        self._last_item = iid                             # запомнить для местоимений «на нём…»
        tmpl = self.world.templates.get(inst.template_id)
        desc = inst.description or getattr(tmpl, "description", None) or ""
        parts = [self._item_name(iid).capitalize() + "."]
        if desc:
            parts.append(desc)
        alts = (inst.mods or {}).get("alterations") or []
        if alts:
            parts.append("Следы изменений: " + "; ".join(alts) + ".")
        if inst.equipped_slot:
            parts.append("(в руке)")
        return " ".join(parts).strip()

    # --- запросы о мире/себе: отвечаем из читаемого стейта, без модели и броска ---
    _QUERY_HEADS = ("что", "какие", "какой", "какая", "кто", "кого", "где", "куда",
                    "сколько", "чем", "чего", "есть ли", "видно ли", "можно ли", "видишь",
                    "вижу ли")

    def _query_type(self, text: str) -> str | None:
        low = text.strip().lower()
        has_item = self._item_in_carry(low) is not None  # «осмотреть кинжал» — это про предмет, не запрос
        if not has_item:                                  # императивный обзор вокруг (без вопроса)
            if any(p in low for p in ("по сторон", "оглядыва", "озира", "окидыва", "оглянул",
                                      "оглянут", "осматрива", "осмотрюсь", "осмотреться",
                                      "смотрю вокруг", "смотрю по", "гляжу вокруг")):
                return "look"
            if any(p in low for p in ("сумк", "рюкзак", "мои вещи", "свои вещи", "что несу",
                                      "что у меня", "инвентар", "пожитк", "пересчита", "кошел",
                                      "при себе", "в карман")):
                return "inventory"
        is_q = (low.endswith("?") or any(low.startswith(w) for w in self._QUERY_HEADS)
                or any(p in low for p in ("что вижу", "что видно", "что рядом", "что здесь",
                                          "что вокруг", "кто здесь", "кто рядом", "куда можно")))
        if not is_q:
            return None
        if any(k in low for k in ("предмет", "вещ", "лежит", "на полу", "на земле", "ценн",
                                  "добыч", "взять", "подобрать", "лут", "трофе")):
            return "items"
        if any(k in low for k in ("кто", "кого", "люд", "персонаж", "нпс")):
            return "who"
        if any(k in low for k in ("куда", "выход", "пойти", "идти", "уйти", "дорог", "путь")):
            return "exits"
        if any(k in low for k in ("сумк", "инвентар", "при себе", "ношу", "у меня в",
                                  "что у меня", "золот", "денег", "монет", "снаряж")):
            return "inventory"
        if any(k in low for k in ("здоров", "хп", "hp", "ранен", "состояни", "сколько жизн", "цел ли")):
            return "status"
        if any(k in low for k in ("карт", "местност", "округ", "где я")):
            return "map"
        return "look"

    def _answer_query(self, qtype: str, text: str = "") -> dict:
        low = text.lower()
        if any(k in low for k in ("скрыва", "прячет", "прячут", "затаил", "в тени", "соглядат",
                                  "следит", "следят", "подсматр", "подслуш", "шпион", "слежк")):
            return self._do_scan(Action(actor=self.player, verb="scan"), text)  # «кто скрывается?» → проверка
        iid = self._item_in_carry(text)                   # назван предмет при себе?
        if not iid and any(p in low for p in ("на нём", "на нем", "на ней", "на это", "на том",
                                              "о нём", "о нем", "что там", "что на")):
            if self._last_item and self._last_item in self._carry_items():
                iid = self._last_item                     # местоимение → последний осмотренный
        if iid and qtype not in ("who", "exits", "status", "map"):
            inst = self.world.items.get(iid)
            if any(k in low for k in ("написа", "гравир", "надпис", "выцарап", "начертан",
                                      "метк", "рун", "что-то на", "что то на")):
                alts = (inst.mods or {}).get("alterations") or [] if inst else []
                nm = self._item_name(iid)
                txt = (f"На «{nm}»: " + "; ".join(alts) + ".") if alts \
                    else f"На «{nm}» ничего не написано — он чист."
                return {"kind": "narration", "text": txt, "view": self.view()}
            return {"kind": "narration", "text": self._describe_item(iid), "view": self.view()}
        if qtype == "look":
            return self.look()
        if qtype == "map":
            return {"kind": "look", "text": self.map_text(), "view": self.view()}
        if qtype == "inventory":
            return {"kind": "inventory", "text": self._inventory_text(), "view": self.view()}
        if qtype == "who":
            who = [self._display(n) for n in self.npcs_here()]
            txt = ("Рядом: " + ", ".join(who) + ".") if who else "Рядом никого нет."
            return {"kind": "narration", "text": txt, "view": self.view()}
        if qtype == "exits":
            ex = [self._place_name(e) for e in self.exits()]
            txt = ("Отсюда можно пройти: " + ", ".join(ex) + ".") if ex else "Явных выходов отсюда нет."
            return {"kind": "narration", "text": txt, "view": self.view()}
        if qtype == "status":
            pl = self.view().get("player", {})
            txt = (f"{pl.get('name', 'Ты')}: уровень {pl.get('level', 1)}, "
                   f"HP {pl.get('hp')}/{pl.get('max_hp')}.")
            return {"kind": "narration", "text": txt, "view": self.view()}
        # items: что заметного рядом — контейнеры/лавка/affordances (без выдумки)
        bits = []
        for cid in self._containers_here():
            names = [self._item_name(i) for i in self.world.containers[cid].items]
            if names:
                bits.append(", ".join(names))
        affs = [a["label"] for a in self.affordances_here()]
        if bits:
            txt = "На виду: " + "; ".join(bits) + "."
        elif self._shop_here():
            txt = "Здесь торгуют — можно посмотреть товар («купить», «что продаёшь»)."
        else:
            txt = "Ничего ценного на виду." + ((" Можно: " + ", ".join(affs) + ".") if affs else "")
        return {"kind": "narration", "text": txt, "view": self.view()}

    def _resolve_freeform(self, text: str, target: str | None = None, hostile: bool = False) -> dict:
        low0 = text.lower()
        if hostile or any(k in low0 for k in self._HOSTILE_KW):   # враждебное действие по NPC
            tgt = target or self.dialogue_partner             # «бью ему / плюну в него» → собеседник
            if not tgt:
                here = self.npcs_here()
                tgt = here[0] if len(here) == 1 else None     # единственный рядом — очевидная цель
            if tgt and self.world.ecs.exists(tgt) and self.world.is_alive(tgt):
                return self._improvised_attack(text, tgt)     # импровиз-атака с последствиями (урон/агро/бой)

        # осмотр предмета из инвентаря → заземлённое описание (с накопленными изменениями)
        if any(k in low0 for k in ("осмотр", "осматр", "разгляд", "рассматр", "посмотр", "погляж",
                                   "гляж", "изуч", "достаю", "достать", "достан", "вынима", "вытаск")):
            iid = self._item_in_carry(text)
            if iid:
                self._tick()
                return {"kind": "narration", "text": self._describe_item(iid), "view": self.view()}

        fz = self.feasibility(text)
        if not fz["feasible"]:                            # неосуществимо здесь и сейчас
            self._tick()
            return {"kind": "narration", "feasibility": fz, "needs_roll": False,
                    "text": f"Мастер качает головой: {fz['reason']}", "view": self.view()}
        p = float(fz.get("p", 0.5))
        adj = None
        if self.model is not None and self.model.available():
            from ..inference.agents import decide_resolution
            sc = self.scene_context()
            adj = decide_resolution(self.model, text,
                                    f"{sc.descriptor} Локация: {sc.place_name}. "
                                    f"{self._env_note()}".strip(), p)
        if not adj:
            if config.LLM_REQUIRED:                       # без фоллбэков: не подменяем эвристикой
                self._tick()
                return {"kind": "error", "feasibility": fz, "view": self.view(),
                        "text": "Модель не разобрала действие (режим без фоллбэков). "
                                "Переформулируй или подними сервер моделей."}
            adj = self._arbiter_fallback(text, p)
        res = adj.get("resolution", "roll")
        why = adj.get("reason") or adj.get("reasoning") or fz["reason"]
        if res == "auto_fail":
            self._tick()
            return {"kind": "narration", "feasibility": fz, "needs_roll": False,
                    "text": f"Так не выйдет: {why}", "view": self.view()}
        if res == "auto_success":
            self._tick()
            narr = self._narrate_outcome(f"Игрок: {text.strip()} — удаётся без труда.", topic="freeform")
            return {"kind": "narration", "feasibility": fz, "needs_roll": False,
                    "text": (narr or f"Без труда удаётся: {text.strip()}.")
                    + self._apply_consequences(text, "success"), "view": self.view()}

        # нужен бросок: навык + DC (DC кодирует вероятность), считаем шанс успеха
        skill = self._norm_skill(adj.get("skill") or adj.get("ability_skill") or adj.get("ability"), text)
        dc = int(adj.get("dc") or max(5, min(25, round(20 - p * 16))))
        req = self.rules.build_check_request(self.player, skill, dc, kind="skill", target=target,
                                             env_adv=self._env_check_adv(skill))
        pct = self._success_pct(req)
        action = Action(actor=self.player, verb="freeform", target=target)

        def resume(result: RollResult) -> dict:
            outcome = self.rules.adjudicate(action, req, result)
            self.world.commit("check", self.player,
                              payload={"skill": skill, "dc": dc, "success": outcome.success},
                              roll=result.to_record(req.dice))
            self._tick()
            tag = "успех" if outcome.success else "провал"
            narr = self._narrate_outcome(
                f"Игрок: {text.strip()} — {tag} ({skill} {result.total} против DC {dc}).",
                topic="freeform")
            trail = ""                                    # последствия пишутся на успех и крит-провал
            if outcome.success:
                trail = self._apply_consequences(text, "critical_success" if outcome.crit else "success")
            elif outcome.fumble:
                trail = self._apply_consequences(text, "critical_failure")
            return {"kind": "narration", "feasibility": fz, "needs_roll": True,
                    "outcome_success": outcome.success,
                    "text": (narr or (("Получилось! " if outcome.success else "Не вышло. ")
                                      + f"({skill} {result.total} против DC {dc})")) + trail,
                    "view": self.view()}

        return self._suspend(req, resume,
                             f"Нужен бросок: {skill} против DC {dc} (~{pct}% успеха).")

    def _apply_consequences(self, text: str, outcome: str) -> str:
        """Агент последствий: переписывает стойкий контекст мира (локация/NPC/предмет),
        отношения, состояния, флаги. Только онлайн; всё событийно (переживает сейв/лоад)."""
        if self.model is None or not self.model.available():
            return ""
        from ..inference.agents import world_effects
        place = self.current_place()
        pl = self.world.spatial.places.get(place)
        loc = f"«{pl.name if pl else place}»: {self.scene_context().descriptor}"
        npcs = [self._display(n) for n in self.npcs_here()]
        items = [self._item_name(i) for i in self._carry_items()]
        out = world_effects(self.model, text, outcome, loc, npcs, items, self._recent_context())
        notes = []
        for raw in (out.get("effects") if out else []) or []:
            e = self._norm_effect(raw)
            tid = self._resolve_effect_target(e, text)
            if not tid:
                continue
            payload = {"kind": e["kind"], "target": tid, "note": e.get("note"),
                       "condition": e.get("condition"), "minutes": e.get("minutes"),
                       "flag": e.get("flag")}
            for k in ("trust", "fear", "affinity"):       # дельты отношений ограничены
                v = e.get(k)
                payload[k] = max(-0.25, min(0.25, float(v))) if isinstance(v, (int, float)) else None
            if not any(payload.get(k) for k in ("note", "trust", "fear", "affinity", "condition", "flag")):
                continue
            self.world.commit("world_effect", self.player, target=tid, payload=payload)
            if payload["note"]:
                notes.append(payload["note"])
            if len(notes) >= 3:
                break
        return (" След: " + "; ".join(notes) + ".") if notes else ""

    @staticmethod
    def _norm_effect(e: dict) -> dict:
        """Нормализует эффект из любого формата модели (kind|entity|target_kind, note|value…)."""
        if not isinstance(e, dict):
            return {"kind": ""}
        k = str(e.get("kind") or e.get("entity") or e.get("target_kind")
                or e.get("target_type") or "").lower()
        kind = ("place" if k.startswith(("loc", "place", "мест"))
                else "npc" if k in ("npc", "character", "person", "персонаж")
                else "item" if k in ("item", "object", "предмет")
                else "self" if k in ("self", "player", "игрок") else k)
        name = e.get("name") or e.get("target_name") or e.get("target") or e.get("id")
        etype = str(e.get("type") or e.get("change_kind") or e.get("change") or "note").lower()
        val = next((e[f] for f in ("note", "value", "description", "desc")
                    if isinstance(e.get(f), str) and e[f].strip()), None)
        out = {"kind": kind, "name": name if isinstance(name, str) else ""}
        for d in ("trust", "fear", "affinity"):           # дельты могут лежать прямо в полях
            if isinstance(e.get(d), (int, float)):
                out[d] = e[d]
        if etype.startswith(("cond", "status", "effect")) and val:
            out["condition"] = val
            out["minutes"] = e.get("minutes")
        elif etype == "flag" and val:
            out["flag"] = val
        elif not etype.startswith("relat") and val:
            out["note"] = val
        return out

    def _resolve_effect_target(self, e: dict, text: str) -> str | None:
        kind = e.get("kind")
        name = e.get("name") if isinstance(e.get("name"), str) else ""
        if kind == "place":
            return self.current_place()
        if kind == "self":
            return self.player
        if kind == "npc":
            tid = self._match_npc(name) or self._match_npc(text)
            here = self.npcs_here()
            if tid in here:
                return tid
            return here[0] if len(here) == 1 else None
        if kind == "item":
            return self._item_in_carry(name) or self._item_in_carry(text)
        return None

    def feasibility(self, text: str) -> dict:
        """Оценка выполнимости действия игрока в контексте сцены (роль plausibility).
        {feasible, p, reason}. Модель при наличии, иначе правило-фоллбэк."""
        scene = self.scene_context()
        ctx = f"{scene.descriptor} Локация: {scene.place_name}. {self._env_note()}".strip()
        if self.model is not None:
            from ..inference.agents import assess_feasibility
            out = assess_feasibility(self.model, text, ctx)
            if out:
                p = float(out.get("plausibility", 0.5))
                return {"feasible": p >= 0.2, "p": p,
                        "reason": out.get("verdict_note") or "это здесь неосуществимо."}
        return self._feasibility_fallback(text)

    def _feasibility_fallback(self, text: str) -> dict:
        low = text.lower()
        impossible = ("полет", "полёт", "взлет", "взлёт", "взмыва", "взмой", "парю", "парить",
                      "лечу", "левитир", "в небо", "телепорт", "воскрес", "оживить",
                      "превратись", "превращаюсь", "наколдуй золото", "останови время",
                      "стань невидим", "сквозь стен", "fly", "teleport", "resurrect", "levitat")
        if any(w in low for w in impossible):
            return {"feasible": False, "p": 0.05,
                    "reason": "это тебе не под силу здесь и сейчас."}
        return {"feasible": True, "p": 0.5, "reason": ""}

    def _narrate_outcome(self, summary: str, persona=None, topic: str = "") -> str | None:
        """Нарратор отрисовывает механический исход прозой (роль narrator/render_scene),
        НЕ меняя чисел. None офлайн — вызывающий оставляет механический текст как есть."""
        if self.model is None:
            return None
        from ..inference.agents import render_scene
        out = render_scene(self.model, summary,
                           persona or self.world.ecs.get(self.player, Persona), topic,
                           scene=self._narrator_context(),
                           mode="combat" if topic == "combat" else "outcome")
        return out.get("narration") if out else None

    def _narrator_context(self) -> str:
        """Богатый контекст сцены для нарратора: время/сезон/погода/место (descriptor),
        кто рядом, последние ходы — чтобы он не выдумывал антураж и держал преемственность."""
        sc = self.scene_context()
        npcs = ", ".join(self._display(n) for n in self.npcs_here()) or "никого нет"
        ctx = f"{sc.descriptor} Место: «{sc.place_name}». Рядом: {npcs}."
        recent = self._recent_context(3)
        if recent:
            ctx += f"\nЧто было только что:\n{recent}"
        return ctx

    # ===================================================================== #
    #  Информационное представление связности локаций (вместо карты)        #
    # ===================================================================== #
    def connectivity(self) -> dict:
        """Где игрок, куда (и в какую сторону света) можно пройти, кто где рядом —
        граф-карта нодами с направленными рёбрами."""
        from ..world.spatial import DIR_RU
        place = self.current_place()
        here = self.world.spatial
        conns = []
        for pid in here.connections(place):
            occ = [self._display(e) for e in here.occupants(pid)
                   if e != self.player and self.world.is_alive(e)]
            d = here.direction_to(place, pid)
            conns.append({"id": pid, "name": self._place_name(pid),
                          "kind": here.places[pid].kind if pid in here.places else "",
                          "dir": d, "dir_ru": DIR_RU.get(d, "") if d else "",
                          "occupants": occ})
        conns.sort(key=lambda c: (c["dir"] is None, c["name"]))
        return {
            "current": {"id": place, "name": self._place_name(place)},
            "connections": conns,
        }

    def map_text(self) -> str:
        """Связность как текст (для CLI /map): выходы по сторонам света + мини-карта."""
        c = self.connectivity()
        lines = [f"📍 Ты здесь: {c['current']['name']}", "Выходы:"]
        for x in c["connections"]:
            arrow = f"{x['dir_ru']}: " if x["dir_ru"] else "→ "
            who = f" — {', '.join(x['occupants'])}" if x["occupants"] else ""
            lines.append(f"  {arrow}{x['name']}{who}")
        mini = self._minimap()
        if mini:
            lines += ["", "Карта:", mini]
        return "\n".join(lines)

    def _minimap(self) -> str:
        """ASCII-мини-карта поселения нодами по компасной раскладке."""
        coords = self.world.spatial.layout("place:phandalin_square")
        if len(coords) < 2:
            return ""
        cur = self.current_place()
        xs = [c[0] for c in coords.values()]
        ys = [c[1] for c in coords.values()]
        labels = {}
        for pid, (x, y) in coords.items():
            name = self._place_name(pid)
            lab = "".join(w[0] for w in name.split()[:2]).upper()[:2] or name[:2]
            labels[(x - min(xs), y - min(ys))] = (lab, pid == cur)
        rows = []
        for gy in range(max(ys) - min(ys) + 1):
            cells = []
            for gx in range(max(xs) - min(xs) + 1):
                lab, is_cur = labels.get((gx, gy), ("", False))
                cells.append(f"[{lab:^2}]" if is_cur and lab else (f" {lab:^2} " if lab else "    "))
            rows.append("".join(cells))
        return "\n".join(rows)

    # ===================================================================== #
    #  Физический контекст сцены (сезон/время/погода) + знания NPC          #
    # ===================================================================== #
    def scene_context(self):
        from ..world import environment
        return environment.scene_context(self.world, self.current_place())

    def scene_descriptor(self) -> str:
        return self.scene_context().descriptor

    def _env_check_adv(self, skill: str, ranged: bool = False) -> int:
        """Поправка advantage от погоды/света для проверки навыка (док 07 §6)."""
        from ..world import environment
        return environment.check_advantage(self.scene_context(), skill=skill, ranged=ranged)

    def _env_note(self) -> str:
        """Краткая сводка погодных эффектов — в контекст арбитра/feasibility."""
        from ..world import environment
        return environment.effects(self.scene_context()).note

    def _disclosable_facts(self, npc: str, rel, topic: str | None = None, limit: int = 5,
                           gate_level: float | None = None):
        """Факты под раскрытие, отранжированные по релевантности запросу игрока (recall).
        topic здесь — реплика/запрос игрока (для ранжирования), gate_level — эффективное
        доверие после пройденной проверки убеждения/обмана."""
        items = self.cognition.recall(npc, topic or "", rel, gate_level=gate_level, k=limit)
        return [it["fact"] for it in items]

    # ===================================================================== #
    #  Журнал игрока и контекст (read-model поверх event log, док 08 §4)     #
    # ===================================================================== #
    def _log_journal(self, msg: str) -> None:
        self.journal.append(f"[{self.world.clock.hhmm()}] {msg}")
        self.journal = self.journal[-50:]

    def _pull_quest_journal(self) -> None:
        log = self.quests.log
        for line in log[self._quest_log_seen:]:
            self.journal.append(f"[{self.world.clock.hhmm()}] {line}")
        self._quest_log_seen = len(log)

    def context_line(self) -> str:
        st = self.world.get_stats(self.player)
        p = self.world.ecs.get(self.player, Persona)
        cls = (p.archetype if p and p.archetype else "авантюрист")
        return (f"{self._display(self.player)} — человек-{cls} {st.level if st else 1} ур., "
                f"чужак в этих краях. Сейчас: «{self._place_name(self.current_place())}», "
                f"{self.world.clock.hhmm()}.")

    def active_quests(self) -> list[str]:
        out = []
        for q in self.world.quests.values():
            if q.state not in ("offered", "active"):
                continue
            obj = next((q.stage(sid).objective for sid in q.current_stages
                        if q.stage(sid)), "")
            out.append(f"[{q.state}] {q.title}" + (f" — {obj}" if obj else ""))
        return out

    def journal_data(self) -> dict:
        self._pull_quest_journal()
        return {"context": self.context_line(), "quests": self.active_quests(),
                "events": self.journal[-14:]}

    def journal_text(self) -> str:
        j = self.journal_data()
        lines = ["═══ ЖУРНАЛ ═══", "Ты: " + j["context"]]
        if j["quests"]:
            lines.append("Активные квесты:")
            lines += ["  • " + q for q in j["quests"]]
        lines.append("Недавние события:")
        lines += ["  " + e for e in j["events"]]
        return "\n".join(lines)

    # ===================================================================== #
    #  Снимок состояния для UI                                              #
    # ===================================================================== #
    def _key_houses(self) -> list[dict]:
        """Дома, чей индекс важности достиг порога → стали ключевыми (подпись на карте)."""
        th = config.PLACE_IMPORTANCE_KEY
        out = []
        for pid, c in self.world.importance.items():
            if c < th or not pid.startswith("house:"):
                continue
            rec = self.world.resolutions.get(f"interior:{pid}", {})
            occ = rec.get("occupants") or []
            name = f"Дом — {occ[0]['name']}" if occ else "Приметный дом"
            out.append({"id": pid, "importance": c, "kind": rec.get("kind", "home"), "name": name})
        return out

    def _progression_view(self) -> dict | None:
        from ..combat.spells import SPELLS
        from ..rules.progression import (
            CLASSES,
            FIGHTING_STYLES,
            SUBCLASSES,
            feature_label,
            next_threshold,
        )
        from ..world.components import Progression
        prog = self.world.ecs.get(self.player, Progression)
        st = self.world.get_stats(self.player)
        if not prog or not st:
            return None
        feats = []
        for f in prog.features:
            if f == "fighting_style":
                feats.append("Боевой стиль: " + FIGHTING_STYLES.get(prog.fighting_style, {}).get("name", ""))
            else:
                feats.append(feature_label(f))
        sub = SUBCLASSES.get(prog.class_id, {}).get(prog.subclass, {}).get("name") if prog.subclass else None
        spells = [{"key": k, "name": SPELLS[k].name, "level": SPELLS[k].level}
                  for k in (prog.cantrips + prog.spells_known) if k in SPELLS]
        return {
            "class_id": prog.class_id, "class_name": CLASSES[prog.class_id]["name"],
            "subclass": sub, "xp": prog.xp, "xp_next": next_threshold(st.level),
            "features": feats, "fighting_style": prog.fighting_style,
            "expertise": list(prog.expertise), "feats": list(prog.feats),
            "spells": spells, "slots": dict(st.spell_slots),
            "caster": bool(CLASSES[prog.class_id]["caster"]),
        }

    def pending_levelup(self) -> dict | None:
        """Если накоплен опыт на новый уровень — что предстоит выбрать игроку."""
        from ..rules.progression import CLASSES
        from ..world.components import Progression
        from .leveling import choices_for
        prog = self.world.ecs.get(self.player, Progression)
        st = self.world.get_stats(self.player)
        if not prog or not st or prog.pending <= 0:
            return None
        target = st.level + 1
        return {"from": st.level, "to": target, "remaining": prog.pending,
                "class_id": prog.class_id, "class_name": CLASSES[prog.class_id]["name"],
                "choices": choices_for(prog.class_id, target, st, prog)}

    def apply_levelup(self, selections: dict) -> dict:
        """Применить выбор игрока: собрать и закоммитить событие level_up."""
        from ..world.components import Progression
        from .leveling import build_payload, choices_for, validate
        prog = self.world.ecs.get(self.player, Progression)
        st = self.world.get_stats(self.player)
        if not prog or prog.pending <= 0:
            return {"kind": "error", "text": "Сейчас нет повышения уровня.", "view": self.view()}
        target = st.level + 1
        needed = choices_for(prog.class_id, target, st, prog)
        err = validate(needed, selections or {})
        if err:
            return {"kind": "error", "text": err, "view": self.view()}
        payload = build_payload(prog.class_id, target, st, prog, selections or {})
        self.world.commit("level_up", self.player, payload=payload)
        self._log_journal(f"Повышение до {target} уровня.")
        res = self.look()
        res["text"] = f"⬆ {self._display(self.player)} достигает {target} уровня!"
        return res

    # ----------------------------------------------------- фракции ---------- #
    def _affiliation(self):
        from ..world.components import Affiliation
        aff = self.world.ecs.get(self.player, Affiliation)
        if aff is None:
            aff = Affiliation()
            self.world.ecs.add(self.player, aff)
        return aff

    def _faction_list(self) -> list[str]:
        return sorted(self.world.factions.keys())

    def _factions_view(self) -> dict | None:
        from ..rules.factions import rank_for_rep, standing_tier
        from ..world.components import Faction
        aff = self._affiliation()
        items = []
        for fid in self._faction_list():
            fac = self.world.ecs.get(fid, Faction)
            if not fac:
                continue
            if fid not in self.world.known_factions and aff.membership != fid:
                continue                                  # игрок ещё не слышал об этой фракции
            rep = self.world.reputation.get(fid, 0.0)
            label, color = standing_tier(rep)
            is_member = aff.membership == fid
            rank = (fac.ranks[rank_for_rep(fac, rep)] if fac.ranks and is_member else None)
            rels = [{"name": self.world.ecs.get(o, Faction).name if self.world.ecs.get(o, Faction) else o,
                     "value": v} for o, v in fac.relations.items()]
            items.append({
                "id": fid, "name": fac.name, "kind": fac.kind, "emblem": fac.emblem,
                "blurb": fac.blurb, "goals": list(fac.goals), "values": list(fac.values),
                "standing": round(rep, 2), "standing_label": label, "standing_color": color,
                "affinity": round(aff.affinity.get(fid, 0.0), 2),
                "member": is_member, "rank": rank, "members": len(fac.members),
                "relations": rels, "controls": list(fac.controls),
                "joinable": fac.joinable, "join_min_rep": fac.join_min_rep,
                "can_join": fac.joinable and not is_member and rep >= fac.join_min_rep,
            })
        return {"membership": aff.membership, "list": items}

    def faction_reaction(self, npc_id: str) -> float:
        """Отношение NPC к игроку через призму фракций (своя +, вражеская −, репутация)."""
        from ..rules.factions import social_reaction
        return social_reaction(self.world, self.player, npc_id)

    def inspect_faction(self, fid: str) -> dict:
        """Открыть фракцию: лениво обогатить LLM (если есть модель) и вернуть вид."""
        from ..gen.faction_gen import enrich_faction
        if fid in self.world.factions:
            enrich_faction(self.world, fid, self.model)
        return {"kind": "factions", "view": self.view()}

    def join_faction(self, fid: str) -> dict:
        from ..world.components import Faction
        fac = self.world.ecs.get(fid, Faction)
        if not fac or not fac.joinable:
            return {"kind": "error", "text": "В эту фракцию нельзя вступить.", "view": self.view()}
        self._reveal_factions({fid})                        # вступаешь — значит точно знаешь о ней
        aff = self._affiliation()
        if aff.membership == fid:
            return {"kind": "system", "text": f"Ты уже в «{fac.name}».", "view": self.view()}
        rep = self.world.reputation.get(fid, 0.0)
        if rep < fac.join_min_rep:
            need = round(fac.join_min_rep - rep, 2)
            return {"kind": "system", "text": f"«{fac.name}» пока не доверяет тебе "
                    f"(нужно ещё +{need} репутации).", "view": self.view()}
        prev = aff.membership
        if prev:                                            # смена фракции
            self.world.commit("faction_leave", self.player, payload={"faction": prev})
        self.world.commit("faction_join", self.player, payload={"faction": fid})
        # соперники реагируют на вступление: репутация падает по их неприязни
        for ofid, val in fac.relations.items():
            if val < 0:
                self.world.commit("faction_rep", self.player,
                                  payload={"faction": ofid, "delta": val * 0.3})
        self.world.commit("faction_affinity", self.player, payload={"faction": fid, "delta": 0.3})
        self._log_journal(f"Вступление во фракцию «{fac.name}».")
        res = self.look()
        res["text"] = (f"Ты вступаешь в «{fac.name}»."
                       + (f" Прежняя верность «{self._faction_name(prev)}» разорвана." if prev else ""))
        return res

    def leave_faction(self) -> dict:
        aff = self._affiliation()
        if not aff.membership:
            return {"kind": "system", "text": "Ты не состоишь ни в одной фракции.", "view": self.view()}
        fid = aff.membership
        name = self._faction_name(fid)
        self.world.commit("faction_leave", self.player, payload={"faction": fid})
        self._log_journal(f"Выход из фракции «{name}».")
        res = self.look()
        res["text"] = f"Ты покидаешь «{name}»."
        return res

    def _faction_name(self, fid: str | None) -> str:
        from ..world.components import Faction
        fac = self.world.ecs.get(fid, Faction) if fid else None
        return fac.name if fac else (fid or "—")

    def _reveal_factions(self, fids) -> list[str]:
        """Открыть игроку фракции (он «узнал» о них). Возвращает имена новооткрытых."""
        names = []
        for fid in fids:
            if not fid or fid not in self.world.factions or fid in self.world.known_factions:
                continue
            self.world.commit("faction_learned", self.player, payload={"faction": fid})
            nm = self._faction_name(fid)
            names.append(nm)
            self._log_journal(f"Узнал(а) о фракции «{nm}».")
        return names

    def _reveal_note(self, names: list[str]) -> str:
        return ("  📜 Ты узнаёшь о фракции " + ", ".join(f"«{n}»" for n in names) + ".") if names else ""

    def _reveal_from_dialogue(self, npc: str, rel, topic: str | None) -> list[str]:
        """Что за фракции всплыли в разговоре: своя у NPC + те, чьё знание он раскрыл."""
        from ..content.knowledge import disclosable, faction_for_topic
        from ..world.components import Persona
        persona = self.world.ecs.get(npc, Persona)
        if not persona:
            return []
        fids = set()
        if persona.faction:
            fids.add(persona.faction)
        for item in disclosable(persona, rel.trust, topic):
            fid = faction_for_topic(item.get("topic"))
            if fid:
                fids.add(fid)
        return self._reveal_factions(fids)

    # ------------------------------------------- доска объявлений ----------- #
    def _at_board(self) -> bool:
        p = self.world.spatial.places.get(self.current_place())
        return bool(p and "board" in (p.affordances or []))

    def _reward_text(self, r) -> str:
        parts = []
        if r.currency:
            parts.append(", ".join(f"{v} {k}" for k, v in r.currency.items()))
        if r.xp:
            parts.append(f"{r.xp} XP")
        for fid, d in (r.faction_rep or {}).items():
            parts.append(f"реп. {self._faction_name(fid)} {'+' if d >= 0 else ''}{d}")
        return " · ".join(parts) or "—"

    def board_view(self) -> dict | None:
        """Список простых заданий на доске (только когда игрок у доски объявлений)."""
        if not self._at_board():
            return None
        items = []
        for q in self.world.quests.values():
            if getattr(q, "kind", "") != "board":
                continue
            cur = next((q.stage(s).objective for s in q.current_stages if q.stage(s)),
                       q.stages[0].objective if q.stages else "")
            items.append({
                "id": q.quest_id, "title": q.title, "framing": q.framing, "objective": cur,
                "state": q.state, "reward": self._reward_text(q.rewards),
                "req_kind": getattr(q, "req_kind", ""),
                "can_accept": q.state in ("offered", "not_offered"),
                "can_turn_in": q.state == "active" and "turnin" in q.current_stages,
            })
        return {"place": self._place_name(self.current_place()), "quests": items}

    def accept_quest(self, qid: str) -> dict:
        q = self.world.quests.get(qid)
        if not q or getattr(q, "kind", "") != "board" or q.state not in ("offered", "not_offered"):
            return {"kind": "system", "text": "Это задание сейчас нельзя принять.", "view": self.view()}
        first = q.stages[0].stage_id if q.stages else None
        self.world.commit("quest_state", self.player, target=qid,
                          payload={"state": "active", "current_stages": [first] if first else []})
        self._log_journal(f"Принято задание: «{q.title}».")
        res = self.look()
        res["text"] = f"📜 Принято задание: «{q.title}». {q.framing}"
        return res

    def turn_in_quest(self, qid: str) -> dict:
        q = self.world.quests.get(qid)
        if not q or q.state != "active":
            return {"kind": "system", "text": "Это задание не в работе.", "view": self.view()}
        if "turnin" not in q.current_stages:
            return {"kind": "system", "text": "Задание ещё не выполнено.", "view": self.view()}
        if not self._at_board():
            return {"kind": "system", "text": "Сдать можно только у доски объявлений.", "view": self.view()}
        self.world.commit("set_flag", self.player, payload={"flag": f"turnin:{qid}"})  # → advance → complete
        res = self.look()
        res["text"] = f"✅ Задание «{q.title}» сдано. Награда: {self._reward_text(q.rewards)}."
        return res

    def view(self) -> dict:
        st = self.world.get_stats(self.player)
        place = self.current_place()
        prog_v = self._progression_view()
        return {
            "player": {
                "id": self.player, "name": self._display(self.player),
                "hp": st.hp if st else 0, "max_hp": st.max_hp if st else 0,
                "ac": inv.armor_class(self.world, self.player),
                "level": st.level if st else 1,
                "xp": prog_v["xp"] if prog_v else 0,
                "xp_next": prog_v["xp_next"] if prog_v else None,
                "class_name": prog_v["class_name"] if prog_v else "",
            },
            "progression": prog_v,
            "levelup": self.pending_levelup(),
            "factions": self._factions_view(),
            "board": self.board_view(),
            "inventory": self.inventory_view(),
            "place": place, "place_name": self._place_name(place),
            "seed": self.world.seed,
            "time": self.world.clock.hhmm(),
            "game_over": self.is_game_over(),
            "in_combat": bool(self.combat and self.combat.state.mode == "active"),
            "combat": self.combat_view(),                # бойцы/цели/действия — для UI и тестов боя
            "pending_roll": self._roll_req_dict(self.pending_roll["request"]) if self.pending_roll else None,
            "connectivity": self.connectivity(),
            "region_map": self.region_map(),
            "map_levels": self.map_levels(),
            "shop": self.shop_view(),
            "key_houses": self._key_houses(),
            "pacing": {"quiet": self.quiet_ticks},
            "scene": self.scene_context().to_dict(),
            "context": self.context_line(),
            "dialogue_with": self._display(self.dialogue_partner) if self.dialogue_partner else None,
            "journal": (self._pull_quest_journal() or self.journal[-10:]),
            "quests": [{"id": q.quest_id, "title": q.title, "state": q.state,
                        "objective": next((q.stage(sid).objective for sid in q.current_stages
                                           if q.stage(sid)), "")}
                       for q in self.world.quests.values() if q.state in ("offered", "active")],
            "quest_log": self.quests.log[-6:],
        }
