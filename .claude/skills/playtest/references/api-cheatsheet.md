# Player API cheat-sheet (paste into the player prompt — verbatim, complete)

All JSON over http://127.0.0.1:8098. Use `curl --max-time 240` on /live /talk /say /act (LLM-backed).

## Moving & looking
- `GET  /api/play/scene` — where you are: loc, inside, here[] (people: id, name), enterable {bid,name}, ambient, gt, coins, hp
- `POST /api/play/move {"to":<node int>}` · `POST /api/play/enter {"id":"<bid>"}` · `POST /api/play/exit {}`
- `POST /api/play/live {}` — wait one tick, watch: returns feed[] of speech/deeds around you (k, who, text, tier)

## Talking
- `POST /api/play/talk {"npc":"<pid>"}` — approach: card (name, role, emotion, aff/trust/fear, gnaw if any) + greet line; may reveal an offer «Уговор»
- `POST /api/play/say {"npc":"<pid>","text":"..."}` — say to them (Russian). Asking «нет ли работы?» reveals pending offers
- `POST /api/play/say {"text":"..."}` — say aloud to the room (people may react next tick)

## Quests & board
- `GET  /api/play/board` — guild jobs + lairs + **postings[]** (public townsfolk contracts: {id,title,reward,giver})
- `POST /api/play/board_take {"id":"<posting or ad id>"}` — take a board job (THIS is the accept for board items)
- `POST /api/play/contract_accept {"id":"<ct id>"}` — accept a personally-offered contract
- `GET  /api/play/contracts` — your jobs: active[] (giver, kind, pitch, step info) + recent done
- `GET  /api/play/journal?kind=&limit=30` — your chronicle «Хроника» (kinds: person|event|quest|place; prov: saw/heard1/heard2/told)

## Doing things
- `POST /api/play/act {"text":"<free Russian action>"}` — freeform: search, climb, threaten, steal, inspect… Violence toward a present person STARTS A DUEL (response carries combat:true — then use the combat API below; free text never kills anyone by itself)
- `POST /api/play/give {"npc":"<pid>","coins":N}` — give N coins (gift; can complete money-quests on the spot)
- give an ITEM: `POST /api/play/give {"npc":"<pid>","item":"<name>"}`

## Combat (the part testers keep missing)
- `GET  /api/play/combat` — state: grid w/h, units[] (id, x, y, hp, ac), order, turn, status
- `POST /api/play/combat_act` — one action per your turn: `{"type":"move","x":X,"y":Y}` · `{"type":"attack","target":"<unit id>"}` · `{"type":"dodge"}` · `{"type":"flee"}` · `{"type":"end"}`. Bad payloads return an error naming the accepted shapes. Repeat GET → act until status ≠ active.

## Money & misc
- coins visible in /scene; buy/sell at market venues: `POST /api/play/market/buy|sell` (see venue context)
- `POST /api/play/rest {}` where lodging exists — sleep to morning
