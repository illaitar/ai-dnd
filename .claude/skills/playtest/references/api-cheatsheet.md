# Player API cheat-sheet (paste into the player prompt — verbatim, complete)

All JSON over http://127.0.0.1:8098. Use `curl --max-time 240` on /live /talk /say /act (LLM-backed).

IF 2+ consecutive LLM-backed calls return errors: STOP playing, report «BLOCKED (infra?)» with the
exact error strings, and end your run — do not spend budget probing «broken» systems during an outage.

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
- `POST /api/play/give {"npc":"<pid>","coins":N}` — give N coins (a GIFT, not a purchase — the NPC
  owes you nothing back; it can complete money-quests on the spot). Buying = market/buy at a venue.
  If you «pay» for goods via /give and get nothing, report WHICH affordance you used — that's the finding.
- give an ITEM: `POST /api/play/give {"npc":"<pid>","item":"<name>"}`
- DIRECTIONS: lost? Ask a PERSON: `/say {"npc":..,"text":"где <место>?"}` — a shared answer marks
  your map and writes a journal told-row. Never search by walking node numbers.

## Combat (the part testers keep missing)
- `GET  /api/play/combat` — state: grid w/h, units[] (id, x, y, hp, ac), order, turn, status
- `POST /api/play/combat_act` — one action per your turn: `{"type":"move","x":X,"y":Y}` · `{"type":"attack","target":"<unit id>"}` · `{"type":"dodge"}` · `{"type":"flee"}` · `{"type":"end"}`. Bad payloads return an error naming the accepted shapes. Repeat GET → act until status ≠ active.

## Items & person-to-person trade (BUYING FROM A PERSON WORKS — use these, not /give)
- `GET  /api/play/inventory` — your bag
- `GET  /api/play/wares?npc=<pid>` — what that NPC will sell you, with THEIR prices
- `POST /api/play/buy {"npc":"<pid>","item":"<item id from wares>"}` — buy it (price shifts with affinity/greed)
- `POST /api/play/sell {"npc":..,"item":..}` · `POST /api/play/offer {..}` — sell/haggle to them
- `POST /api/play/inspect {"item":..}` — closer look (may reveal hidden qualities)
- `POST /api/play/use {"item":..}` — eat/drink/apply
- `POST /api/play/loot {"container":..}` — take from a container revealed in the room
- `POST /api/play/commission {..}` / `repair` — order crafting/fixing from an artisan

## Money & misc
- coins visible in /scene; buy/sell at market venues: `POST /api/play/market/buy|sell` (see venue context)
- SLEEP: no /rest endpoint — use freeform: `POST /api/play/act {"text":"снимаю тюфяк и ложусь спать до утра"}` where lodging exists (таверна); costs ~2 монеты, jumps to morning
