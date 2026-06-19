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
    "move": ["иди", "идти", "иду", "пойд", "go ", "move", "войти", "зайти", "нап혀рав"],
    "attack": ["бью", "атак", "напад", "ударь", "attack", "kill", "убить", "руб"],
    "intimidate": ["запуга", "угрож", "intimidate", "припугн"],
    "persuade": ["убеди", "уговор", "persuade", "договор"],
    "talk": ["поговор", "говор", "спрос", "talk", "ask", "обрат", "привет"],
    "inspect": ["осмотр", "смотр", "look", "examine", "оглядет", "разгляд"],
    "search": ["обыск", "ищу", "иска", "search", "найти", "пошарь"],
    "loot": ["лут", "обобрать", "loot", "забрать", "открыть сундук", "обыскать труп"],
    "buy": ["купить", "куплю", "buy", "приобрес"],
    "sell": ["продать", "продаю", "sell"],
    "inventory": ["инвентар", "инв", "inventory", "сумк", "рюкзак"],
    "wait": ["ждать", "жду", "wait", "отдых", "rest", "ждём"],
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

    # человекочитаемые взаимодействия с окружением по аффордансам места
    AFFORD_LABEL = {
        "inn": "отдохнуть и перекусить", "drink": "выпить", "eat": "поесть",
        "serve": "снять комнату", "shop": "посмотреть товар", "work": "оглядеть работу",
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
    def handle(self, text: str) -> dict:
        if self.combat and self.combat.state.mode == "active":
            return {"kind": "combat", "text": "Идёт бой — используй боевые действия.",
                    "view": self.view()}
        action = self._parse_intent(text)
        verb = action.verb
        # действие (не разговор) завершает текущий диалог; покупка сведений/торговля
        # идут у текущего собеседника, поэтому диалог не сбрасывают
        if verb not in ("talk", "persuade", "intimidate", "inspect", "buyinfo", "buy", "sell"):
            self.dialogue_partner = None
        handler = getattr(self, f"_do_{verb}", None)
        result = handler(action, text) if handler else self._narrate_freeform(text)
        return self._post(result, verb)

    # ===================================================================== #
    #  Нарративный темп: при затишье и подходящей обстановке — случайный бит #
    # ===================================================================== #
    _EVENTFUL_VERBS = {"attack", "loot", "buy", "sell", "buyinfo", "persuade",
                       "intimidate", "search", "move"}

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
            return {"kind": "system", "text": "Куда идти? Доступные выходы: "
                    + ", ".join(self._place_name(e) for e in self.exits()),
                    "view": self.view()}
        cur = self.current_place()
        if dest == cur:
            look = self.look()
            look["text"] = "Ты уже здесь. " + look["text"]
            return look
        # маршрутизация: до известной локации идём по графу проходимости (не только
        # к прямому соседу) — без авто-прокладки пришлось бы хопать вручную
        path = self.world.spatial.path_between(cur, dest)
        if not path:
            return {"kind": "system", "text": f"Ты не знаешь, как добраться до "
                    f"«{self._place_name(dest)}».", "view": self.view()}
        ticks, region_travel = self._travel_cost(path)
        self.world.commit("set_position", self.player, target=self.player,
                          payload={"region": "region:phandalin", "place": dest})
        hours = ticks * config.SIM_MINUTES_PER_TICK // 60
        self._log_journal(f"Перешёл в «{self._place_name(dest)}»"
                          + (f" (путь ~{hours} ч)" if region_travel and hours else "") + ".")
        self._record_explored(dest)
        debunked = self._verify_map_here(dest)        # сверка купленных наводок с реальностью
        self._tick(ticks)
        look = self.look()
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

        if not topic:
            # ИНИЦИАЦИЯ: NPC приветствует и сам спрашивает, что нужно — без реакции
            # на несуществующую реплику игрока (заземление, без выдуманной истории)
            self.cognition.observe(npc, "ко мне подошёл незнакомец", importance=2)
            self.world.commit("talk", self.player, target=npc, payload={"opening": True})
            self._log_journal(f"Заговорил с {self._display(npc)}.")
            line = self._npc_greeting(npc, rel, first_meeting)
            self._tick()
            return {"kind": "narration", "text": line, "speaker": self._display(npc),
                    "npc": npc, "hint": "Спроси о чём-нибудь, предложи дело или скажи что-то.",
                    "view": self.view()}

        # игрок что-то СКАЗАЛ/СПРОСИЛ → реакция с учётом отношений и гейтов
        ctx = self.cognition.retrieve(npc, topic, self.player)
        decision = self.cognition.policy(npc, "talk", action.tone, ctx, self.player)
        hooks = self.director.surface_hooks_near(npc)
        self.cognition.observe_and_appraise(npc, self.player, "talk", action.tone,
                                            f"игрок сказал: {topic[:60]}")
        self.world.commit("talk", self.player, target=npc, payload={"topic": topic[:60]})
        line = self._npc_reply(npc, decision, topic, rel, first_meeting, hooks)
        self._log_journal(f"Поговорил с {self._display(npc)}.")
        self._tick()
        return {"kind": "narration", "text": line, "speaker": self._display(npc),
                "npc": npc, "decision": decision, "hooks": hooks, "view": self.view()}

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
        req = self.rules.build_check_request(self.player, skill, dc, target=npc, kind="skill")

        def resume(result: RollResult) -> dict:
            outcome = self.rules.adjudicate(action, req, result)
            tone = "friendly" if skill == "persuasion" else "fearful"
            self.cognition.observe_and_appraise(npc, self.player, skill, tone, outcome.summary)
            self.world.commit(skill, self.player, target=npc,
                              payload={"success": outcome.success},
                              roll=result.to_record(req.dice))
            ctx = self.cognition.retrieve(npc, "", self.player)
            rel, first = ctx.rel, (not ctx.memories)
            reply = self._npc_reply(npc, {"action": "share_info" if outcome.success else "withhold"},
                                    text, rel, first, self.director.surface_hooks_near(npc))
            self._log_journal(f"{'Убедил' if skill == 'persuasion' and outcome.success else 'Говорил с'} "
                              f"{self._display(npc)} ({'успех' if outcome.success else 'неудача'}).")
            self._tick()
            return {"kind": "narration", "text": f"{outcome.summary} {reply}", "npc": npc,
                    "view": self.view()}

        return self._suspend(req, resume, f"Проверка {skill} против DC {dc}.")

    def _do_search(self, action: Action, text: str) -> dict:
        place = self.current_place()
        dc = 15
        # пассивная Perception (док 07 §5) — авто без броска
        if self.rules.try_passive(self.player, "perception", dc):
            return self._reveal_container(place, "Твоё чутьё сразу находит тайник.")
        req = self.rules.build_check_request(self.player, "investigation", dc, kind="skill")

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
        return self.look()

    def _do_loot(self, action: Action, text: str) -> dict:
        self.current_place()
        containers = self._containers_here()
        if not containers:
            return {"kind": "system", "text": "Здесь нечего обыскивать.", "view": self.view()}
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
            return {"kind": "system", "text": "Поблизости нет лавки.", "view": self.view()}
        c = self.world.containers[shop]
        if not c.items:
            return {"kind": "system", "text": "Лавка пуста.", "view": self.view()}
        iid = c.items[0]
        try:
            inv.buy(self.world, self.player, shop, iid)
            self._tick()
            return {"kind": "narration", "text": f"Ты покупаешь {self._item_name(iid)}.",
                    "view": self.view()}
        except inv.InventoryError as e:
            return {"kind": "system", "text": f"Покупка не удалась: {e}", "view": self.view()}

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

    def _do_inventory(self, action: Action, text: str) -> dict:
        return {"kind": "inventory", "text": self._inventory_text(), "view": self.view()}

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
        enemies = [n for n in self.npcs_here() if self._is_hostile(n)]
        if target and target not in enemies and self._is_hostile(target):
            enemies = [target] + [e for e in enemies if e != target]
        if not enemies:
            return {"kind": "system", "text": "Здесь нет врагов для атаки.", "view": self.view()}
        return self.start_combat(enemies)

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
        cs = self.combat.start([self.player], enemy_ids, grid=grid,
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
        for q in list(self.world.quests.values()):
            if q.state == "active":
                self.quests.advance(q)
        if "cragmaw_cleared" in self.world.flags:
            self.director.pacing_check()
        msg = {"victory": "Победа! Враги повержены.",
               "tpk": "Партия пала...", "flee": "Враги бежали."}.get(cs.outcome, "Бой окончен.")
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

    def _tick(self, n: int = 1) -> None:
        self.world.clock.advance(n)
        self.lod.tick(self.player)

    # допустимые глаголы движка (валидация выхода LLM-парсера)
    _VERBS = {"move", "talk", "attack", "inspect", "search", "persuade", "intimidate",
              "loot", "buy", "sell", "inventory", "wait", "scan", "buyinfo"}
    _MAPINFO_KW = ["сведен", "наводк", "карт", "о дороге", "о пути", "путь к", "дорог к",
                   "что знаешь о", "слух о", "разузнать"]

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
        # сторона света как команда движения («на север», «вглубь», «N»)
        if self._direction_in(low):
            return Action(actor=self.player, verb="move", tone="neutral")
        for verb, kws in VERB_KEYWORDS.items():
            if any(k in low for k in kws):
                tone = "hostile" if verb in ("attack", "intimidate") else "neutral"
                return Action(actor=self.player, verb=verb, tone=tone,
                              target=self._match_npc(text))
        return None

    def _parse_intent(self, text: str) -> Action:
        # 1) ключевые слова — детерминированно и надёжно (фикс «/inv → talk»)
        kw = self._keyword_intent(text)
        if kw:
            return kw
        # 2) свободный творческий текст → LLM-парсер, но с ВАЛИДАЦИЕЙ глагола
        if self.model is not None:
            from ..inference.agents import parse_intent
            opts = [self._display(n) for n in self.npcs_here()]
            out = parse_intent(self.model, text, self.player, opts)
            if out and not out.get("needs_clarification") and out.get("verb") in self._VERBS:
                return Action(actor=self.player, verb=out["verb"],
                              target=self._match_npc(out.get("target") or ""),
                              tone=out.get("tone", "neutral"),
                              targets_npc=bool(out.get("target")))
        # 3) обращение к присутствующему NPC (по имени или вопрос при ком-то рядом) —
        #    это реплика; идёт диалог — продолжаем его; иначе осматриваемся.
        #    (фикс: «Toblen, что слышно?» раньше уходило в inspect → выдавало стат-блок)
        named = self._match_npc(text)
        if self.dialogue_partner or named or ("?" in text and self.npcs_here()):
            return Action(actor=self.player, verb="talk",
                          target=named or self.dialogue_partner)
        # нераспознанный нетривиальный ввод — свободное действие (пройдёт гейт
        # выполнимости), а не молчаливый «осмотр»
        return Action(actor=self.player, verb="freeform")

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

    def _npc_greeting(self, npc: str, rel, first_meeting: bool) -> str:
        """Приветствие NPC при инициации — заземлено, без выдуманной истории."""
        persona = self.world.ecs.get(npc, Persona)
        if self.model is not None:
            from ..inference.agents import render_dialogue
            line = render_dialogue(
                self.model, persona, self._rel_summary(rel, first_meeting),
                situation=("A stranger walks up and greets you for the first time"
                           if first_meeting else "Someone you know greets you"),
                player_line="", intent="greet and ask what they want",
                scene=self.scene_descriptor())
            if line:
                return line
        return self._greeting_fallback(persona, first_meeting)

    def _npc_reply(self, npc: str, decision: dict, topic: str, rel, first_meeting, hooks) -> str:
        persona = self.world.ecs.get(npc, Persona)
        action = decision.get("action", "respond")
        action = action if isinstance(action, str) else "respond"
        if self.model is not None:
            from ..inference.agents import render_dialogue
            line = render_dialogue(
                self.model, persona, self._rel_summary(rel, first_meeting),
                situation=f"The player says/asks: «{topic}». Your stance: {action}.",
                player_line=topic, intent=action, scene=self.scene_descriptor(),
                facts=self._disclosable_facts(npc, rel))
            if line:
                return self._maybe_hook(line, hooks)
        name = self._display(npc)
        # заземление офлайн: делясь, NPC называет РЕАЛЬНЫЙ доступный факт (по теме,
        # иначе первый разблокированный), а не пустую отписку «расскажу, что знаю»
        share_line = f"{name}: «Раз уж спрашиваешь — слушай.»"
        if action == "share_info":
            fact = self._relevant_fact(npc, rel, topic)
            if fact:
                share_line = f"{name} понижает голос: «Раз уж спрашиваешь — {fact}.»"
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

    def _relevant_fact(self, npc: str, rel, topic: str | None) -> str | None:
        """Самый релевантный РАЗБЛОКИРОВАННЫЙ факт NPC: по совпадению слов темы, иначе
        первый доступный при текущем доверии. Только из реально известного — без выдумки."""
        facts = self._disclosable_facts(npc, rel)
        if not facts:
            return None
        low = (topic or "").lower()
        toks = [w for w in low.replace(",", " ").replace("?", " ").split() if len(w) > 3]
        for f in facts:
            if any(t[:5] in f.lower() for t in toks):
                return f
        return facts[0]

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
        return f"{p.name}{epithet} — {p.race}{prof}. {traits.capitalize()}."

    def _inventory_text(self) -> str:
        carry = self.world.containers.get(f"carry:{ids.name_of(self.player)}")
        items = [self._item_name(i) for i in carry.items] if carry else []
        wallet = self.world.wallet(self.player)
        coins = ", ".join(f"{v} {k}" for k, v in wallet.items() if v)
        return f"Инвентарь: {', '.join(items) or 'пусто'}. Кошелёк: {coins or 'пусто'}."

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
        low = text.lower()
        for npc in self.npcs_here():
            p = self.world.ecs.get(npc, Persona)
            if p and (p.name.lower() in low or (p.epithet and p.epithet.lower() in low)
                      or p.name.split()[0].lower() in low):
                return npc
        return None

    def _direction_in(self, low: str) -> str | None:
        from ..world.spatial import DIR_ALIASES
        words = set(low.replace(",", " ").split())
        for alias, canon in DIR_ALIASES.items():
            if alias in words or (len(alias) > 3 and alias in low):
                return canon
        return None

    def _match_place(self, text: str) -> str | None:
        import re
        low = text.lower()
        sp = self.world.spatial
        cur = self.current_place()
        # 1) сторона света → сосед по направленному ребру текущего узла
        d = self._direction_in(low)
        if d:
            exits = sp.exits_of(cur)
            if d in exits:
                return exits[d]
        # 2) лучшее совпадение по ИМЕНИ среди достижимых локаций: стем-матч (морфология
        #    рус. падежей), при равенстве — ближайшая по графу. Так «пещеру» у входа в
        #    логово даёт пещеру Кларга, а не Эха Волн (устранение коллизии keymap).
        toks = [t for t in re.split(r"[^0-9a-zа-яё]+", low) if len(t) >= 3]
        best, best_score, best_hops = None, 0, 10 ** 9
        for pid, place in sp.places.items():
            if pid == cur:
                continue
            hops = sp.hops_between(cur, pid)
            if hops is None:                              # недостижимо → не предлагаем
                continue
            name = place.name.lower()
            score = 5 if name in low else 0
            for w in name.split():
                if len(w) < 4:
                    continue
                stem = w[:5]
                if any(t.startswith(stem) or stem.startswith(t) for t in toks):
                    score += 1
            if score and (score > best_score or (score == best_score and hops < best_hops)):
                best, best_score, best_hops = pid, score, hops
        if best:
            return best
        # 3) разговорные синонимы (без двусмысленного «пещер» — он теперь решается по графу)
        aliases = {"город": "place:phandalin_square", "площад": "place:phandalin_square",
                   "фэндалин": "place:phandalin_square",
                   "дикие": "place:phandalin_wilds", "пустош": "place:phandalin_wilds",
                   "таверн": "building:stonehill_inn", "трактир": "building:stonehill_inn",
                   "постоял": "building:stonehill_inn",
                   "лавк": "building:barthens_provisions", "бартен": "building:barthens_provisions",
                   "львинощ": "building:lionshield_coster", "lionshield": "building:lionshield_coster",
                   "ратуш": "building:townmaster_hall", "святил": "building:shrine_of_luck"}
        for k, pid in aliases.items():
            if k in low and pid in sp.places and sp.hops_between(cur, pid) is not None:
                return pid
        return None

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
        p = self.world.ecs.get(npc, Persona)
        return bool(p and p.faction in ("faction:cragmaw", "faction:redbrands"))

    def _do_freeform(self, action: Action, text: str) -> dict:
        return self._narrate_freeform(text)

    def _narrate_freeform(self, text: str) -> dict:
        """Свободное действие: сперва ГЕЙТ ВЫПОЛНИМОСТИ (можно ли это здесь и сейчас —
        роль plausibility), затем нарратор описывает попытку (роль narrator/render_scene).
        Офлайн — детерминированные фоллбэки."""
        fz = self.feasibility(text)
        if not fz["feasible"]:
            return {"kind": "narration", "feasibility": fz,
                    "text": f"Мастер качает головой: {fz['reason']}", "view": self.view()}
        narr = self._narrate_outcome(f"Игрок пытается: {text.strip()}", topic="freeform")
        return {"kind": "narration", "feasibility": fz,
                "text": narr or "Мастер обдумывает твои слова... (свободное действие)",
                "view": self.view()}

    def feasibility(self, text: str) -> dict:
        """Оценка выполнимости действия игрока в контексте сцены (роль plausibility).
        {feasible, p, reason}. Модель при наличии, иначе правило-фоллбэк."""
        scene = self.scene_context()
        ctx = f"{scene.descriptor} Локация: {scene.place_name}."
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
                           persona or self.world.ecs.get(self.player, Persona), topic)
        return out.get("narration") if out else None

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

    def _disclosable_facts(self, npc: str, rel, topic: str | None = None, limit: int = 5):
        persona = self.world.ecs.get(npc, Persona)
        if not persona:
            return []
        from ..content.knowledge import disclosable
        return [k["fact"] for k in disclosable(persona, rel.trust, topic)][:limit]

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
    def view(self) -> dict:
        st = self.world.get_stats(self.player)
        place = self.current_place()
        return {
            "player": {
                "id": self.player, "name": self._display(self.player),
                "hp": st.hp if st else 0, "max_hp": st.max_hp if st else 0,
                "ac": inv.armor_class(self.world, self.player),
                "level": st.level if st else 1,
            },
            "place": place, "place_name": self._place_name(place),
            "time": self.world.clock.hhmm(),
            "in_combat": bool(self.combat and self.combat.state.mode == "active"),
            "pending_roll": self._roll_req_dict(self.pending_roll["request"]) if self.pending_roll else None,
            "connectivity": self.connectivity(),
            "region_map": self.region_map(),
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
