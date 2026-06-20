"""Базовые знания по профессиям и фракциям, наследуемые NPC (док 02 §4).

Каждый NPC наследует факты своей профессии и фракции (плюс авторские/именные).
Факты гейтятся порогом доверия (disclosure_gate.trust): сплетни — низкий порог,
чувствительное — средний, тайны — высокий. Это даёт NPC РЕАЛЬНОЕ знание для
диалога, чтобы при доверии он делился фактами мира, а не выдумывал.
"""

from __future__ import annotations


def _k(fact, topic, trust=0.1, unlocks=None):
    item = {"fact": fact, "topic": topic, "disclosure_gate": {"trust": trust}}
    if unlocks:
        item["unlocks_quest"] = unlocks
    return item


# профессия -> базовые знания
PROFESSION_KNOWLEDGE = {
    "innkeeper": [
        _k("в городе судачат, что Красные плащи распоясались и трясут торговцев", "redbrands", 0.1),
        _k("через город то и дело проходят искатели приключений к старым рудникам", "rumors", 0.05),
        _k("дворф Гундрен Роксикер недавно был тут, говорил о какой-то находке", "gundren", 0.3),
    ],
    "merchant": [
        _k("караван с товаром Львинощита перехватили по дороге у тропы", "lionshield", 0.1,
           unlocks="quest:lionshield_goods"),
        _k("цены на руду взлетели — поставки из рудника прекратились", "mine", 0.1),
        _k("Красные плащи требуют «плату за защиту» с лавочников", "redbrands", 0.2),
    ],
    "blacksmith": [
        _k("телеги с рудой из шахты не приходят уже недели две", "mine", 0.1),
        _k("без руды я перебиваюсь починкой да подковами", "trade", 0.05),
    ],
    "miner": [
        _k("старики болтают о Пещере Эха Волн и забытой Кузне Заклинаний", "wave_echo", 0.3),
        _k("в туннелях у Крэгмо завелись гоблины", "cragmaw", 0.2),
    ],
    "guard": [
        _k("Красные плащи держат город в страхе, а власть бездействует", "redbrands", 0.1),
        _k("за головы разбойников у Вайверн-Тор обещана награда", "wyvern_tor", 0.1,
           unlocks="quest:wyvern_tor_orcs"),
    ],
    "townmaster": [
        _k("орки совершают набеги со стороны Вайверн-Тор — городу нужна помощь", "wyvern_tor", 0.1,
           unlocks="quest:wyvern_tor_orcs"),
        _k("я бы и рад навести порядок с Красными плащами, да руки коротки", "redbrands", 0.2),
    ],
    "priest": [
        _k("дурные знамения тревожат прихожан в последние дни", "omens", 0.1),
        _k("сестра Гараэле просила разузнать о банши Агате близ Конибери", "garaele", 0.3),
    ],
    "farmhand": [
        _k("Красные плащи поколачивают всякого, кто жалуется вслух", "redbrands", 0.2),
        _k("на ферме Олдерлиф привечают усталых путников", "alderleaf", 0.05),
    ],
    "hunter": [
        _k("в холмах у Вайверн-Тор видели орочьи тропы", "wyvern_tor", 0.1),
        _k("к северу, в Громовом Древе, бродит что-то крылатое и злое", "thundertree", 0.3),
    ],
    "scout": [
        _k("дороги небезопасны: засады гоблинов на Трибоарской тропе", "cragmaw", 0.1),
    ],
}

# фракция -> базовые знания (часть — тайны, высокий порог)
FACTION_KNOWLEDGE = {
    "faction:redbrands": [
        _k("укрытие Красных плащей — в подвалах поместья Тресендар", "redbrands", 0.5),
        _k("главарь Красных плащей — маг по прозвищу Стеклянный Посох", "glasstaff", 0.6),
    ],
    "faction:cragmaw": [
        _k("логово Крэгмо стерегёт багбир Кларг", "cragmaw", 0.4),
        _k("дворфа-пленника увезли в замок Крэгмо", "gundren", 0.6),
    ],
    "faction:zhentarim": [
        _k("Жентарим тихо прибирает к рукам торговлю в этих краях", "zhentarim", 0.5),
        _k("я веду здесь дела Чёрной Сети", "zhentarim_secret", 0.7),
    ],
    "faction:harpers": [
        _k("Арфисты тайно приглядывают за равновесием на фронтире", "harpers", 0.5),
    ],
    "faction:lords_alliance": [
        _k("Союз Лордов хочет вернуть порядок и торговлю в Фэндалин", "lords_alliance", 0.4),
    ],
}


# тема знания → фракция (для «узнавания» фракций из услышанного в диалоге)
TOPIC_FACTION = {}
for _fid, _items in FACTION_KNOWLEDGE.items():
    for _it in _items:
        TOPIC_FACTION.setdefault(_it["topic"], _fid)
TOPIC_FACTION.setdefault("cragmaw", "faction:cragmaw")     # упоминается и в профессиях/разведке


def faction_for_topic(topic: str | None) -> str | None:
    return TOPIC_FACTION.get(topic or "")


def inherit_knowledge(persona, profession: str | None, faction: str | None) -> None:
    """Добавляет персоне базовые знания профессии и фракции (без дублей)."""
    have = {k.get("fact") for k in persona.knowledge}
    for item in PROFESSION_KNOWLEDGE.get(profession or "", []):
        if item["fact"] not in have:
            persona.knowledge.append(dict(item))
            have.add(item["fact"])
    for item in FACTION_KNOWLEDGE.get(faction or "", []):
        if item["fact"] not in have:
            persona.knowledge.append(dict(item))
            have.add(item["fact"])


def disclosable(persona, trust: float, topic: str | None = None) -> list[dict]:
    """Знания, которые NPC готов раскрыть при текущем доверии (опц. по теме)."""
    out = []
    for k in persona.knowledge:
        gate = (k.get("disclosure_gate") or {}).get("trust", 0.0)
        if trust + 1e-9 >= gate:
            if topic and topic not in (k.get("topic", ""), ""):
                continue
            out.append(k)
    return out
