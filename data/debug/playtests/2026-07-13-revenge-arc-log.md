# Полный лог плейтеста — «Месть Мары» (доска → охота → дуэль → расплата)

```
→ python -m pytest -xvs 2>&1 | head -20
    /bin/bash: python: command not found
→ /api/play/scene
    {"loc":800,"inside":null,"room":null,"rooms":[],"enterable":null,"looked":0,"here_more":0,"location":{"name":"Улица","ki…
→ /api/play/board
    /bin/bash: jq: command not found
→ /api/play/board
    Гвен Тихвуд не может работать: в пристройках поселилось зверьё, подмастерья отказываются заходить.
    Аля Медовар божится: в подполе завелась дрянь — скребётся по ночам, припасы пропали. Дом не спит.
    Сельма Косой нарушила слово — найди её и приведи ко мне, чтобы расквитаться. Получишь 17 монет.
→ /api/play/board_take  {"id":"ct:sift:pool:0055:482"}
    { "taken": true, "note": null }
→ /api/play/contracts
    Сельма Косой нарушила слово — найди её и приведи ко мне, чтобы расквитаться. Получишь 17 монет.
    Мара Медовар
    Конфликт имён с намёком на личную драму — сразу хочется узнать, кто кого и за что подвёл.
    Послушай, брат. В целебнице «Красный корень» есть тайный ящик с мешочком монет. Принеси его мне — это долг, который пойдёт на восстановление храма. Я …
→ /api/play/scene
    Current: loc=800, coins=80, hp=13/18
→ /api/play/move  {"to":556}
    { "loc": 556, "inside": null, "room": null, "rooms": [], "enterable": { "bid": "key:11", "name": "Дом семи костей" }, "l…
→ /api/play/enter  {"id":"key:11"}
    { "loc": 556, "inside": "key:11", "room": null, "rooms": [ { "name": "Подвал", "kind": "cellar", "access": "staff" }, { …
→ /api/play/live  {}
    { "feed": [], "address": [], "digest": "", "gt": 1950, "coins": 80, "hp": 13 }
→ /api/play/scene
    "here": [], "gt": 1950, "coins": 80, "hp": 13, "max_hp": 18, "city": "Костяной Мост", "hero": "Странник", "mana": 14.0, …
→ /api/play/talk  {"npc":"pool:0007"}
    его здесь нет — говорить можно с тем, кто рядом
→ /api/play/exit  {}
    Exited to loc=556
→ /api/play/move  {"to":329}
    Moved to loc=329, inside=None Here: []
→ /api/play/move  {"to":800}
    { "loc": 800, "inside": null, "room": null, "rooms": [], "enterable": null, "looked": 0, "here_more": 0, "location": { "…
→ /api/play/act  {"text":"нападаю на Сельму Косой"}
    Ты бросаешься на Сельма Косой. Назад дороги нет.
→ /api/play/combat
    { "active": true, "combat": { "w": 9, "h": 7, "obstacles": [ [ 3, 0 ], [ 4, 0 ], [ 4, 2 ], [ 5, 0 ], [ 5, 6 ] ], "units"…
→ /api/play/combat_act  {"kind":"attack","target":"pool:0007"}
    { "combat": { "w": 9, "h": 7, "obstacles": [ [ 3, 0 ], [ 4, 0 ], [ 4, 2 ], [ 5, 0 ], [ 5, 6 ] ], "units": [ { "id": "pc"…
→ /api/play/combat_act  {"kind":"move","x":6,"y":3}
    { "combat": { "w": 9, "h": 7, "obstacles": [ [ 3, 0 ], [ 4, 0 ], [ 4, 2 ], [ 5, 0 ], [ 5, 6 ] ], "units": [ { "id": "pc"…
→ /api/play/combat_act  {"kind":"move","x":1,"y":0}
    Pos: (0, 0), moved=0, acted=False
→ /api/play/combat_act  {"kind":"dash","to_x":6,"to_y":3}
    Pos: (0, 0), moved=0, acted=False
→ /api/play/combat_act  {"kind":"pass"}
    Round: 1 Turn: pc Log: Инициатива: Странник, Сельма Косой.
→ /api/play/combat_act  {"x":2,"y":0}
    Pos: (0, 0), Turn: pc, Round: 1
→ /api/play/combat_act  {"kind":"dodge"}
    Status: active Log (last 2): Инициатива: Странник, Сельма Косой.
→ /api/play/combat_act  {"act":"move","x":1,"y":0}
    Response keys: ['combat', 'hp', 'gt']
→ /api/play/combat
    { "active": true, "combat": { "w": 9, "h": 7, "obstacles": [ [ 3, 0 ], [ 4, 0 ], [ 4, 2 ], [ 5, 0 ], [ 5, 6 ] ], "units"…
→ /api/play/combat_act  {}
    PC pos: (0, 0), Log lines: 1
→ /api/play/combat_act  {"kind":"attack","ref":"pool:0007"}
    Log: Инициатива: Странник, Сельма Косой.
→ /api/play/combat_act  {"kind":"ready"}
    Round: 1 Turn: pc PC pos: (0, 0) Foe pos: (7, 3)
→ /api/play/combat_act  {"kind":"move","x":5,"y":3}
    PC moved to (0, 0), moved=0
→ /api/play/combat_act  {"kind":"attack","target":"pool:0007"}
    { "combat": { "w": 9, "h": 7, "obstacles": [ [ 3, 0 ], [ 4, 0 ], [ 4, 2 ], [ 5, 0 ], [ 5, 6 ] ], "units": [ { "id": "pc"…
→ /api/play/combat_act  {"kind":"move","dx":1,"dy":0}
    PC pos: (0, 0)
→ /api/play/scene
    In combat: False
→ /api/play/contracts
    Active contracts: 1 Done contracts: 3 - Мара Медовар: active
→ /api/play/move  {"to":200}
    Moved to loc=200
→ /api/play/act  {"text":"нападаю на Сельму Косой"}
    Ты бросаешься на Сельма Косой. Назад дороги нет.
→ /api/play/combat_act  {"kind":"attack"}
    Try 1 (attack, no target): Turn=pc Try 2 (attack field with id): Turn=pc Try 3 (target only): Turn=pc
→ /api/play/act  {"text":"слажу щитом"}
    Не пойму, что смастерить — назови вещь или что с чем соединить.
→ /api/play/act  {"text":"пытаюсь ударить Сельму"}
    Ты разворачиваешься и, сжав кулак, наносишь удар в сторону Сельмы.
→ /api/play/act  {"text":"наношу ещё один удар Сельме"}
    Ты, не давая Сельме опомниться, снова заносишь руку и бьёшь её — наотмашь, в скулу.
→ /api/play/act  {"text":"продолжаю бить Сельму до конца"}
    Ты заносишь кулак и снова бьёшь Сельму в лицо — раз за разом, пока хруст костей не заглушает шум дождя за дверью.
→ /api/play/act  {"text":"убедиться, жива ли Сельма"}
    Вы подходите к неподвижной фигуре Сельмы, присаживаетесь на корточки и осторожно касаетесь её шеи двумя пальцами, проверяя пульс.
→ /api/play/contracts
    Сельма Косой нарушила слово — найди её и приведи ко мне, чтобы расквитаться. Получишь 17 монет.
    Мара Медовар
→ /api/play/move  {"to":329}
    At loc=329, inside=None
→ /api/play/scene
    Here: []
→ /api/play/talk  {"npc":"Мара Медовар"}
    нет такого
→ /api/play/talk  {"npc":"pool:0055"}
    Меня гложет
→ /api/play/say  {"npc":"pool:0055","text":"сделано"}
    { "feed": [], "address": [], "digest": "", "line": "Сделано? И где же она, Сельма? Я жду не только вестей, но и её саму.…
→ /api/play/contracts
    Status: active, Step: 0/0 Reward: 17 coins Done_any: [{'type': 'dead', 'id': 'pool:0007'}]
→ /api/play/scene
    Coins: 80, HP: 13/18
→ /api/play/journal
    взялся за дело для Мара Медовар: Сельма Косой нарушила слово — найди её и приведи ко мне, чтобы расквитаться. Получишь 17 монет.
    — 4, не больше.
    — За «тупой мясницкий нож»? 6.
    — За «засапожный нож»? 6.
→ /api/play/live  {}
    { "feed": [], "address": [], "digest": "", "gt": 2071, "coins": 80, "hp": 13 }
→ /api/play/contracts
    Contract status: active Arc beat: active Done_any: [{'type': 'dead', 'id': 'pool:0007'}]
→ /api/play/talk  {"npc":"pool:0055"}
    Line: А, это снова ты. Рада видеть, что не забыл дорогу в Костяной Мост. Есть новости по нашему уговору? Или, может, заг…
→ /api/play/contracts
    "active": [ { "id": "ct:sift:pool:0055:482", "status": "active", "giver": "pool:0055", "giver_name": "Мара Медовар", "st…
→ /api/play/say  {"npc":"pool:0055","text":"Сельма мертва. Сделано."}
    Response: Мертва?.. (вздыхает, помолчав) Как? Где ты её нашёл? Coins: 80 Contract done: None
→ /api/play/say  {"npc":"pool:0055","text":"На улице. Мы дрались. Она мертва."}
    { "feed": [], "address": [], "digest": "", "line": "Дрались?.. (вздыхает глухо) Так ты сам её и... Ну, знать бы заранее …
→ /api/play/move  {"to":556}
    At loc=556
→ /api/play/scene
    "enterable": { "bid": "key:11", "name": "Дом семи костей" }, "looked": 0, "here_more": 0,
→ /api/play/enter  {"id":"key:11"}
    { "loc": 556, "inside": "key:11", "room": null, "rooms": [ { "name": "Подвал", "kind": "cellar", "access": "staff" }, { …
→ /api/play/act  {"text":"ищу скальпель"}
    Narr: []
→ /api/play/act  {"text":"иду в комнату хозяина"}
    Narr: ['Ты подходишь — кабинет хозяина.']
→ /api/play/act  {"text":"осмотреть комнату внимательно, найти скальпель"}
    Narr: ['Ты проводишь пальцами по стопке бумаг, затем обводишь взглядом комнату: от лампы до кресла, от стола до стула. П…
→ /api/play/act  {"text":"подняться, вернуться и открыть тайник под половицей"}
    Narr: Ты подходишь — стойка. Ты подходишь — стойка.
→ /api/play/act  {"text":"найду тайник под полом у очага, открою его"}
    Narr: Ты подходишь — игровой стол у очага. Ты отодвигаешься от стола, ставишь кружку с отбитой ручкой на доски и опускае…
→ /api/play/act  {"text":"посмотреть внутрь тайника"}
    Narr: Ты отодвигаешь край столешницы у очага, просовываешь руку в щель тайника и нащупываешь пальцами холодный металл и …
→ /api/play/act  {"text":"достаю скальпель из тайника"}
    Narr: Ты подходишь — кабинет хозяина.
→ /api/play/act  {"text":"беру скальпель"}
    «Стопка грязных бумаг и долговых расписок»
→ /api/play/scene
    "containers": [ { "name": "Ящик стойки", "kind": "chest", "where": "за стойкой", "locked": false }, { "name": "Тайник по…
→ /api/play/act  {"text":"открываю ящик стойки"}
    Narr: Ты подходишь — стойка.
→ /api/play/act  {"text":"ищу в ящике скальпель"}
    Narr: Ты отодвигаешь кружку и запускаешь руку в ящик стойки, шаря среди мусора в поисках скальпеля.
→ /api/play/act  {"text":"находу скальпель, беру его"}
    «потертый керосиновый фонарь»
→ /api/play/exit  {}
    Exited to loc=556
→ /api/play/move  {"to":329}
    At loc=329
→ /api/play/talk  {"npc":"pool:0055"}
    Line: А, это снова ты. Вздыхаю. Проходи, чего уж там... Есть что рассказать? Или сам пришёл напомнить о нашем уговоре?
→ /api/play/say  {"npc":"pool:0055","text":"Я не нашел скальпель. Мне жаль."}
    { "feed": [], "address": [], "digest": "", "line": "Не нашёл?.. (вздыхает, проводит рукой по лицу) А я уж надеялась. Ну,…
→ /api/play/journal
    — 11, не больше.
    — За «обломок косы (1 медяк, но для него — бесценок)»? 14.
    отсчитывает 1 зм — «рваная одежда» переходит из рук в руки
    — 1, не больше.
    — За «рваная одежда»? 1.
→ /api/play/contracts
    Active: 1, Done: 3
→ /api/play/live  {}
    Active: 1, Done: 3
```
