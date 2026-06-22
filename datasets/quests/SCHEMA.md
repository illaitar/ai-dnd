# Quest-generator fine-tuning dataset

Goal: fine-tune the quest generator to emit **one complete, executable quest as a single
JSON message** — by **composing only the entities it is given**, never inventing new ones.

Separation of concerns:

- **The world supplies the cast.** The engine collects what's available near the giver /
  location — factions, NPCs, item templates, locations — and passes them in the request.
- **The generator only assembles.** It picks ids from that cast and arranges stages,
  predicates, rewards and narrative. It must **not invent** `npc:` / `place:` / `tmpl:` /
  `faction:` ids. The only entity id it may use that isn't in the cast is `pc:hero`.
- It **may** author free strings: quest `flag` names and `KnowsFact` facts (those are
  quest-internal, not world entities).

Each training line is a **chat sample** (JSONL):

```json
{"messages":[
  {"role":"system","content":"<SYSTEM>"},
  {"role":"user","content":"<SPEC as compact JSON>"},
  {"role":"assistant","content":"<QUEST as compact JSON>"}
]}
```

## SYSTEM (fixed for every line)

> You are a D&D 5e quest designer for a Sword-Coast frontier campaign (Lost Mine of
> Phandalin). You are given a quest request that includes a **cast**: the factions, NPCs,
> item templates and locations available in the world. Output ONE JSON object — a complete
> quest — that **uses only ids from the cast** (plus `pc:hero`). Do NOT invent any
> `npc:`/`place:`/`tmpl:`/`faction:` id. You MAY define new quest `flag` names and
> `KnowsFact` facts. Completion conditions MUST use the engine predicate vocabulary so the
> rules engine can verify progress deterministically. Narrative fields (`framing`, `hook`,
> `giver_lines`, `objective_text`, `completion_text`) are in Russian and in-character;
> machine fields are exact. Rewards scale with `tier`. Output ONLY the JSON.

## USER — the quest request (`spec`)

```json
{
  "kind": "side",
  "tier": 1,
  "theme": "retrieve",
  "giver": "npc:linene_graywind",
  "focus": "site:cragmaw_hideout",
  "world_facts": ["караван Львинощит ограбили на тракте", "ящики у гоблинов Крэгмо"],
  "constraints": "side quest; modest reward",
  "cast": {
    "factions": [{"id": "faction:merchant_guild", "name": "Торговая гильдия"}],
    "npcs": [
      {"id": "npc:linene_graywind", "name": "Linene Graywind", "role": "merchant",
       "faction": "faction:merchant_guild", "place": "building:lionshield_coster"}
    ],
    "items": [{"id": "tmpl:supply_crate", "name": "ящик с припасами"}],
    "locations": [
      {"id": "site:cragmaw_hideout", "name": "Логово Крэгмо", "kind": "site"},
      {"id": "building:lionshield_coster", "name": "Львинощит Костер", "kind": "building"}
    ]
  }
}
```

- `giver` and `focus` are ids that appear in the cast.
- **`kind`** ∈ {main, side, board, faction, emergent} — the structural quest type, **fixed by
  the request**. The generator must echo `kind`, `theme`, `tier` and `giver` exactly (they are
  inputs, not choices) — this removes a degree of freedom and curbs hallucination/bias.
- `tier` 1–5. `theme` ∈ {retrieve, deliver, bounty, clear, escort, investigate, talk,
  rescue, protect, gather, sabotage, diplomacy, hunt, heist, smuggle, capture, cleanse,
  defend, explore, restore, recruit, extort, mystery}.

## ASSISTANT — the quest (single JSON object)

Every entity id below comes from the cast. Delivery is modelled as **HasItem → TalkedTo**
(carry the item, then hand it to a cast NPC) so no instance/container ids are invented.

```json
{
  "quest_id": "quest:retrieve_lionshield_crate",
  "kind": "side", "title": "Украденный товар",
  "giver_ref": "npc:linene_graywind", "tier": 1, "theme": "retrieve",
  "hook": "У Львинощит Костер пропал караван — ящики ищут по фронтиру.",
  "framing": "Линен Грейвинд просит вернуть украденные ящики её фактории.",
  "giver_lines": ["«Гоблины с тракта увели мой груз. Вернёшь ящики — отблагодарю»."],
  "stages": [
    {"id": "s1", "objective": "забрать ящик Львинощит из логова Крэгмо",
     "completion": {"pred": "HasItem", "args": ["pc:hero", "tmpl:supply_crate"]},
     "on_complete": [], "next": ["s2"]},
    {"id": "s2", "objective": "вернуть ящик Линен Грейвинд",
     "completion": {"pred": "TalkedTo", "args": ["npc:linene_graywind"]},
     "on_complete": [{"effect": "complete"}], "next": []}
  ],
  "rewards": {"currency": {"gp": 50}, "xp": 150, "items": [],
              "faction_rep": {"faction:merchant_guild": 0.15}},
  "prerequisites": [],
  "objective_text": "Вернуть украденный ящик Львинощит Костер.",
  "completion_text": "«Ты вернул мой груз. Львинощит этого не забудет» — Линен жмёт тебе руку.",
  "world_bindings": ["npc:linene_graywind", "tmpl:supply_crate", "site:cragmaw_hideout"]
}
```

## Predicate vocabulary

| pred | args | entity-id args (must be in cast) |
|---|---|---|
| `Flag` | `["flagname"]` | — (flag is a free string) |
| `NpcDead` | `["npc:id"]` | `npc:id` |
| `LairCleared` | `["place:id"]` | the place id |
| `KnowsFact` | `["pc:hero","fact"]` | `pc:hero` (fact is free) |
| `HasItem` | `["pc:hero","tmpl:id"]` | `tmpl:id` |
| `TalkedTo` | `["npc:id"]` | `npc:id` |
| `AnyOf` | `[ <predicate>, … ]` | recurse |

`on_complete` effects: `{"effect":"set_flag","flag":"…"}` (free flag) or `{"effect":"complete"}`.
`ItemInContainer` exists in the engine but is **not used by the generator** (it needs a
specific instance/container id) — model delivery as HasItem → TalkedTo instead.

## Conventions

- **Two-stage default**: do the thing → return to a cast NPC and hand in (`TalkedTo`).
  `bounty`/`clear` may be single-stage (`NpcDead` / `LairCleared` → complete).
- **Cast-only ids**: `giver_ref`, every predicate id-arg, `rewards.items`,
  `rewards.faction_rep` keys, and `world_bindings` must all be cast ids (or `pc:hero`).
  Flags and `KnowsFact` facts are authored freely.
- **Reward by tier**: t1 xp 50–200 / gp 10–75 · t2 200–450 / 50–150 · t3 450–700 / 100–250 ·
  t4 700–1100 / 250–500 · t5 1100–1800 / 500–900. `faction_rep` 0.1–0.3, faction from cast.
- **Diversity targets** across 200: all themes, tiers 1–5, 1–3 stages, every predicate type,
  with/without factions, some `AnyOf` (branching) and `prerequisites`.

`validate.py`/`build.py` reject any output that references an id outside its spec's cast.
