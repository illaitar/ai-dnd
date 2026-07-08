# Refactor map: current → target (module-per-system)

The `server/play` layer crams ~25 distinct systems into a few megafiles (`world.py` 1706,
`core.py` 903, `resolve.py` 403, `freeform.py` 446, `mechanics/*` 1773). The domain packages
(`mind` 16 files, `worldgen` 17, `items` 6, `combat` 5, …) already show the target pattern:
**one focused module per system**. This map brings `server/play` up to the same standard.

**Rules for the whole migration**
- **Behavior-preserving.** Each extraction moves cohesive functions to a new home *unchanged*.
  Verify with an AST-identity check (docstring-strip + string-literal compare — the same net used
  for the earlier `world → resolve` move) so a move is provably not a rewrite.
- **Full granularity.** A module per system; a package when a system has ≥3 files. No megafile.
- **No function > 50 lines** (split as we move; `_live_tick` and `_attempt` are the big offenders).
- **Every file opens with an English "Key functions" docstring.**
- **Each step is a green increment** (`uv run pytest -q` → commit → deploy). One system per step.
- **Domain packages (`mind society citygraph worldgen items combat magic plot inference`) are left
  as-is** — they already meet the standard. This map is only `server/play`.

---

## Target tree — `server/play/`

```
server/play/
  session/                 the runtime session (was the _S blob + core.py plumbing)
    state.py        _CUR · _UID · _fresh_sess · _SessProxy · _S · _wid · current_world_id  → typed Session (later)
    time.py         _gt · _gt_add · _mt · _phase · _PHASE_RU                 (game clock)
    persist.py      _store · _pool · _pc_save · _npc_save                    (save/load worlds.db + live.db)
    config.py       PB · PLAYER                                             (tunables — sole home)
  pc/                      the PLAYER entity (state + resources)
    hero.py         _pc · _pc_hp · _pc_name · _pc_set_name · _PC_CAP · _pc_cap_eff · _met · _seen · _mark_seen · _pc_remember
    mana.py         _mana · _mana_load · _mana_rate · _mana_cap · _mana_spend · _mana_grow · _mana_hardcap · _mana_sleep
    fatigue.py      _fatigue · _fat_add
    glyphs.py       _STARTER_GLYPHS · _glyphs_known · _glyph_learn · _grimoire_get/put/list
  worldbuild/              building a per-user world from the pools
    assembly.py     _play · _settle_fresh · _fill_from_pool · _restore_placed
    population.py   _households · _topup_dependents · _surname · _reclass_note
    jobs.py         _plan_jobs · _assign_key_buildings · _role_for_building · _TYPE_ROLE · TEACHER_ROLES
    ties.py         _weave_ties · _weave_locals                             (social fabric)
    person.py       _person_from_row
    building.py     _binfo · _building_keys · _building_rooms · _building_containers · _res_binfo · _in_room
    geom.py         _build_geom · _scene_zones · map payload
  loop/                    the turn engine
    tick.py         _world_tick                                            (the one "world moved" point)
    routine.py      _apply_routine · _world_events   + worldsim.py (society→placement, Ring B)
    live/                  Ring A — the living scene
      build.py      _live_build · _live_affordances · _npc_surface
      conductor.py  _live_tick   (split into <50-line steps: order · waves · claims · background)
      gossip.py     _gossip
  action/                  PLAYER-ACTION RESOLUTION
    arbiter.py      PRIMITIVES · _sys_prompt · assemble_context · resolve · normalize_plan   [from resolve.py]
    attempt.py      _attempt (thin router over verbs)                       [from freeform.py]
    verbs/          move.py take.py say.py give.py use.py inspect.py listen.py craft.py rest.py attack.py  (one executor each)
  scene/                   the client VIEW of a place
    view.py         _scene_dict · _scene_locinfo · _scene_ambient · _scene_folk · _scene_rooms · _scene_extras · scene()
    vision.py       _look_key · _looked_level · look() · _watch_check       (fog / perception of the room)
  sound/                   audibility system (folder)
    audibility.py   audibility · _dist · tiers
    fidelity.py     cutout · overheard_line
    ambient.py      load_sound_sources · zone_source · audible_ambient
    surface.py      NEW: per-tick soundscape sweep (the surfacing layer, docs/sound-attention.md)
  narrator/                DM prose
    voice.py        _voice · _topics_for · _spurns · _DM_SYS
    snapshot.py     _dm_snapshot · _ambient_note
    lookup.py       _world_lookup
  conversation/     convo.py (convs · answer-debt · conv_block)
  deeds/            deeds.py → deed-log · gossip/wanted/chronicle queries (structure.md item 6)
  economy/          economy.py
  incidents/        incidents.py
  zones/            zones.py (zone selection by needs)
  llm/                     session LLM + usage
    manager.py      _model · _inscriber
    usage.py        _llm_day_key · _llm_used · _llm_hook
  mechanics/               domain mechanics — take (session, store, PB) as PARAMETERS (structure.md item 3)
    combat.py  contracts.py  deals.py  items.py
  handlers/               THIN endpoints only: unpack request → call a service → shape response
    act.py travel.py observe.py inventory.py trade.py board.py dungeon.py magic.py crime.py dialogue.py misc.py
```

Not-yet-built systems that get a home now (empty package + design link):
`attention/` (attention economy — docs/sound-attention.md Pillar 2) · `sound/surface.py`.

---

## Every system → current location → target home

| # | System | Current location | → Target |
|---|---|---|---|
| 1 | Session / `_S` state | core.py 514–589 | `session/state.py` |
| 2 | Game clock / phases | core.py 233–265 | `session/time.py` |
| 3 | Persistence (both DBs) | core.py 268–277, 442, 486 | `session/persist.py` |
| 4 | `PB` tunables | core.py 75–232 | `session/config.py` |
| 5 | Player / hero | core.py 286–331, 428–485, 668–691 | `pc/hero.py` |
| 6 | Mana (magic resource) | core.py 335–381 | `pc/mana.py` |
| 7 | Fatigue | core.py 391–407 | `pc/fatigue.py` |
| 8 | Glyphs / grimoire | core.py 407–428, 730–751 | `pc/glyphs.py` |
| 9 | World assembly / settlement | world.py 488–595 | `worldbuild/assembly.py` |
| 10 | Population (households/dependents) | world.py 412–487 | `worldbuild/population.py` |
| 11 | Jobs / employment gravity | world.py 320–411; core 610–655 | `worldbuild/jobs.py` |
| 12 | Social fabric (ties) | world.py 169–234 | `worldbuild/ties.py` |
| 13 | Person materialization | world.py 235–278 | `worldbuild/person.py` |
| 14 | Building data / rooms / containers | world.py 279–319, 358–377; core 598–609, 751 | `worldbuild/building.py` |
| 15 | Geometry / map payload | world.py 596–645, 1208 | `worldbuild/geom.py` |
| 16 | World-tick (turn engine) | world.py 1682–1706 | `loop/tick.py` |
| 17 | Routine / Ring B | world.py 100–168; worldsim.py | `loop/routine.py` |
| 18 | Live conductor / Ring A | world.py 933–1191, 897–932, 1192–1207, 1225–1681 | `loop/live/` |
| 19 | Player-action arbiter | resolve.py 45–205 | `action/arbiter.py` |
| 20 | Player-action executor (`_attempt`) | freeform.py 51–431 | `action/attempt.py` + `action/verbs/` |
| 21 | Scene view | world.py 655–772, 791–850 | `scene/view.py` |
| 22 | Player vision / look / fog | world.py 646–654, 718–724, 773–790; observe.py | `scene/vision.py` |
| 23 | Sound / audibility | sound.py; world.py 90–99 (overheard hook) | `sound/` (folder) |
| 24 | Per-tick soundscape surfacing | **does not exist yet** | `sound/surface.py` (new) |
| 25 | Narrator / DM | resolve.py 206–402; core 700–729 | `narrator/` |
| 26 | Conversations | convo.py | `conversation/` |
| 27 | Deeds / gossip / chronicle | deeds.py; world.py 1192 | `deeds/` |
| 28 | Economy | economy.py | `economy/` |
| 29 | Incidents | incidents.py | `incidents/` |
| 30 | Zone selection | zones.py | `zones/` |
| 31 | Session LLM + usage limits | core.py 518–534, 711–729 | `llm/` |
| 32 | Contracts / quests | mechanics/contracts.py; world 851–896 | `mechanics/contracts.py` (params) |
| 33 | Combat mechanics | mechanics/combat.py | `mechanics/combat.py` (params) |
| 34 | Trade / deals | mechanics/deals.py | `mechanics/deals.py` (params) |
| 35 | Inventory / item mechanics | mechanics/items.py | `mechanics/items.py` (params) |
| 36 | Attention economy | **designed, no code** | `attention/` (Pillar 2) |

Handlers (`travel · observe · inventory · trade · board · dungeon · magic · crime · dialogue · misc`)
stay in `handlers/` but shrink to thin request→service→response shims as their logic moves to the
systems above.

---

## Migration order (each = one green increment → deploy)

Ordered by *safety and leverage* — start where the seams are cleanest and the payoff is highest.

1. **`session/`** — split `core.py`: `time.py`, `persist.py`, `config.py`, `state.py`. (Everything imports these; do it first so later moves import clean names.)
2. **`pc/`** — hero · mana · fatigue · glyphs out of `core.py`. `core.py` now ~150 lines and dies into `session/` + re-exports.
3. **`sound/`** — promote `sound.py` to a package (`audibility · fidelity · ambient`); land **`surface.py`** (the per-tick soundscape — the sound-vision work rides in on this step).
4. **`narrator/`** — `_voice · _dm_snapshot · _ambient_note · _world_lookup` out of `resolve.py`.
5. **`action/`** — `resolve.py`→`arbiter.py`; `freeform._attempt`→`attempt.py` + `verbs/*`. (Biggest de-dumpstering; the verb-switch dissolves.)
6. **`worldbuild/`** — assembly · population · jobs · ties · person · building · geom out of `world.py`.
7. **`scene/`** — view · vision out of `world.py`.
8. **`loop/`** — tick · routine · `live/` out of `world.py`. `world.py` is now empty and is deleted.
9. **`conversation/ deeds/ economy/ incidents/ zones/ llm/`** — rehome the existing small files (cheap).
10. **`mechanics/` de-weld** — pass `(session, store, PB)` as params (structure.md item 3); handlers go thin.
11. **`attention/`** — scaffold the package for Pillar 2 (empty + design link) so it has a home when built.

After each step: `uv run pytest -q` green, AST-identity check on moved functions, commit, `/deploy`.
`structure.md`'s flatter target is superseded by this map; update its "Target Tree" to point here.

Related: [structure.md](structure.md) · [README.md](README.md) (principles) · [sound-attention.md](sound-attention.md) · [loop.md](loop.md).
