# City Simulation

`src/aidnd/society/` (model) + `src/aidnd/server/play/engine/worldsim.py` (`routine_step`).
~1354 NPCs live out a day CHEAPLY without LLM: each at every phase/tick chooses a PLACE via utility-model
over needs. This is the core of the "living frontier": by day the city works, by evening drinks, by night sleeps—
emergently, from individual needs, not hardcoded "create crowd".

Separate from the LIVE SCENE (LLM, [locations.md](locations.md)): the city is a cheap passive layer
(zero LLM), the scene around the player is an expensive LLM-layer. Simulation places NPCs on graph nodes;
the scene takes those nearby. The seam where the two rings finally touch — arrivals/departures the
player SEES, hard venue capacity, transit walkers, and the end of scene-pinning — is
[sim-stitching.md](sim-stitching.md).

## Model (Sims/Zubek needs-utility + RimWorld-windows)

Verified by research (2026-07-07, 2 threads: daily-life industry + agent/visualization).
Our `society/` is already the right model, no need to rewrite the core:

- **Needs** (`needs.py`): 7 need-urges (hunger/fatigue/social/wealth/purpose/comfort/novelty),
  each grows on its own per hour (`grow`), amplified by traits, sated at places. Circadian rhythm—
  via speeds (fatigue builds toward night, hunger toward noon) → sleep/eating fall into rhythm naturally.
- **Places advertise needs** (`places.py`, smart objects like The Sims): `PlaceKind.sates =
  {need: sate_rate}`; `window`—suitability by time of day (our RimWorld-timetable);
  `likes`—affinity by trait; `gate`—who has access (any/job/guard/rogue); `detect`—
  link to real buildings. Catalog: home/work/tavern/temple/market/street/patrol/prowl/
  appointment.
- **Choice** (`routine.py`): `score = window × affinity(traits) × Σ(sate_rate×need_pressure)`;
  `choose_c`—lottery among top choices (≥0.85·best, anti-stickiness) + inertia ×1.12 toward "current place"
  (anti-jitter, lesson from Sims). `explain()`—diagnostics [(kind, score)] for /minddebug and UI.
- **routine_step**: the ONLY writer of `crof` (pid→node placement). Cycles ALL residents
  O(people×places), cheaply, every ~30 game-min (keyed `_gt()//30`, idempotent per phase);
  workers ordered first. Reassigns everyone — including NPCs standing in the player's scene
  (scene-pinning was removed, see [sim-stitching.md](sim-stitching.md) Inc4). Enforces a **durable
  capacity ledger** `Counter(crof.values()) + player`, recomputed from `crof` each call (never
  persisted — a pure function of the durable placement, so a restart can't drift it): a full venue
  (`_building_cap` = Σ social-zone caps, min 6, default 14) is skipped and the mover **overflows**
  down the same-need candidate chain (`PB.overflow_max_hops`) for ALL venue kinds — tavern/temple/
  market — falling back to a street node if exhausted. Commitments (deeds/appointments) respect the
  ledger too: at a full venue the NPC waits «у входа», not phantom-stacked inside. A settled
  reassignment of ≥ `PB.transit_min_steps` nodes becomes a derived transit walker instead of an
  instant teleport (Inc3). Writes chosen activity-kind to `_S["crof_kind"]` (observability/GIF).

**Philosophy (principles 6, 7, 10):** LLM only OFFLINE (personas, agendas, day_curve at pool forging);
runtime—pure arithmetic. Naive LLM-agent ≈ $25/agent/hour (Stanford Smallville)—unacceptable for ~1354 NPCs;
"day as data" + utility = 50-100× cheaper (Lyfe/AGA/ORACLE).

## Done (2026-07-07, on prod)

- **Work for all** (root of the "living day"): before—24 of 900 worked (key building owners),
  the other 876 drifted through streets. Now **craftspeople labor at HOME**
  (Watabou's historical norm: dwelling above/behind the workshop): anyone without a venue and role ≠
  "townsperson"—work-candidate = their home. Day count: 10→**620** working by morning.
- **Window calibration to bells/canonical hours**: work—peak morning-day (1.0), decline evening (0.2),
  night ≈0; tavern—evening peak (1.0), NIGHT curfew (0.15); market—day (1.0), night ≈0; temple—
  morning service + evensong; street—day, night curfew (0.05, only patrol/prowl remain). Night count:
  midnight = **590 at home, 104 criminal (thieves), 49 on patrol (guard), taverns 123**—plausible night.
- **Inertia** (×1.12 toward current place)—against flickering between equal-value places.
- **crof_kind**—activity-kind per NPC (for GIF and future UI hints "working/dining/on patrol").

## GIF "City Day" (`scripts/cityday.py`)

A day in 30 minutes (48 frames) → snapshot of all ~1354 NPCs' positions on the graph → bubbles ∝ √number at node,
color = activity (home/work/tavern/temple/market/street/patrol/criminal, palette after "Breathing City"),
background darkens at night, clock+legend → `ffmpeg` to looped GIF (`data/debug/cityday/day.gif`). Diagnostic tool:
visually shows whether the rhythm works.

## Done (2026-07-14, on prod) — the ring-A↔B seam

The "Designing v2" layers below are all shipped (see the ✔ implementation order). The last inert
layer — the *seam* between the passive sim and the live scene — is now stitched in four increments
(full canon: [sim-stitching.md](sim-stitching.md)): (1) arrivals/departures are code-generated feed
events narrated by the existing `scene_digest`; (2) the durable capacity ledger + overflow above;
(3) cross-town reassignments become derived transit walkers («в пути»/«проходит мимо»); (4)
scene NPCs are no longer pinned — a resident the routine moves actually LEAVES. Also there: the
**crowd LOD fix** — how many NPCs think per tick is now REASON-based salience (`_MUST_WHY`), not a
numeric impulse threshold; crowds rotate through a round-robin, salient reasons always think. Cut a
130-LLM-call tick down to ~6.

## v2 layers (A–E all ✔ shipped 2026-07-07; design record kept below)

The current model is good cheap **placement** ("where everyone is, by time of day"), but not
**life**. The design below layers three things (intent, economy, role↔venue) atop the
utility-core (it's sound, NOT rewritten). Passed red-team (2026-07-07)—accounting for
money conservation, economy visibility, seam with LLM-agendas, turn-based play, demography.

**Two structural pivots (key from red-team):**
- **Economy—NOT aggregate-primary, but NAMED supply-chain-primary.** Felt
  economy = specific chain "this miller → this bakery → this shop", visible to the player and can be broken;
  aggregate sinks—only backdrop for nameless masses. Fixes invisibility,
  money conservation (easy in small closed loop), and seam with agendas (about specific people).
- **Intent—QUERY-shaped, not state-shaped.** Not "NPC carries plan in DB", but function
  `predict(pid, phase) → (node, why, route)` — running utility forward for a phase (cheap,
  deterministic by seed, nothing persisted). Follow/intercept/tracking = query the forecast.
  Fits turn-based play (tick jumps hours—stored trajectory is illusion).

Invariants: **0 LLM at runtime**, **data not code**, **LOD** (named at player, aggregate—
mass), **everything real** (money/goods move, persist), **no mechanical gates**.

### Layer A—INTENT as FORECAST (query-shaped)

- `predict(pid, phase)` = same `choose_c`, run for given phase → `(node, place-kind,
  node-route)`. Zero stored state, zero persist; deterministic. Current
  `routine_step` = "apply predict for current phase to all" + write to crof/crof_kind.
- **Intercept/meeting—at PLAN level, not position**: "does rogue's route cross node
  N in phase-window", not "is he on the tile" (turn-based world has no position). Guard catches rogue
  if forecast-routes share a node in one phase.
- **Obligations—FORECAST overrides** (data-flags, not separate trajectory): `flee >
  appointment(deeds) > shift(duty) > follow(player) > errand(delivery) > routine`.
  Follow = pin predict to player's node, BUT critical need overrides (RimWorld: hungry
  companion leaves to eat—explicit rule, not "follows you to death"). Appointment already does this.
- Unlocks: "come with me", intercepts, ambush on route, deliveries (errand with on_arrive),
  "track X" (= read predict(X)). Investigators/quests read forecast, not guess.

### Layer B—ECONOMY: named chains + background

**PRIMARY tier—NAMED CHAINS (felt, agent-level, ~5-10 per city).** When building the world from real venues+producers,
several chains assemble `raw → producer@venue → good → shop/market → consumers` (data-templates `content/chains.json`:
grain milling, hide→shoes, ore→vessels, ale, potions…). Each—small graph of named NPCs + nodes +
real goods (item-factsheet) + price. **Player sees and breaks it**: kill miller → milling halts →
baker out of flour → bread prices rise (visible named chain, not abstraction); hoard the shop →
shortage; dump dungeon leather → tannery gluts → prices fall.

**MONEY CONSERVATION (closed loop, fixes runaway).** City's coin `M`—fixed (changes ONLY by player inflow/outflow:
dungeon loot inflates → inflation; player hoards and leaves → deflation—real felt effect). Once per day money
FLOWS through chains `consumer → shop → producer → (take+margin+own consumption) → back`—circulates, not created.
Poverty = loss of share of turnover (your goods unwanted / you got undercut), not "coin vanished". No unconditional
"+coin for work"—income ONLY from others' spending. This makes `wealth`-need real: empty purse = high need = pressure
to work/crime/debt (debt/crime—already mechanics).

**Prices**—per-good from chain supply-vs-demand, with CLAMPS and ELASTICITY (expensive → fewer buy → stock doesn't
go negative; redundancy/substitution/import against single point of failure—kill the only miller: bread gets dear,
but caravan/neighbor's mill soften it, not "starvation forever").

**BACKGROUND tier—nameless masses (aggregate, cheap).** ~850 non-chain NPCs = abstract food demand (feeds food-chain
demand) + casual labor + slow drift of wealth in LIMITED coin pool (no per-agent runaway). This—"population"-number,
not per-agent econ simulation.

**Seam with LLM-agendas (fixes "empty chatter").** Agendas about SPECIFIC people/venues ("buy out the mill",
"ruin shoemaker Alia") get mechanics: named NPC accumulates chain margin → if owner dies/ruined, ambitious one
**really buys venue** → city changes owner (major consequence, deed). Nameless-mass agendas stay flavor.
So "everything real" reaches the economy.

### Layer C—Role↔venue (spatially FIRST, economically—with B)

- **C-spatial (can be first, before economy):** services (innkeeper/shopkeeper/priest)—
  need venue, gravity `P ∝ capacity / distance(home,venue)^β`; profession surplus over slots →
  reclassification as **narrative downward mobility** (ruined innkeeper → bitter day-laborer,
  marked in memory/agenda—not silent label-swap). Also governs pool generation: profession share ∝ city demand
  (offline at forging).
- **C-economic (only with B):** crafts (tanner/weaver/miller) work at home, but
  **produce into chain goods**—"home=workshop" only honest when B's stock exists.
  Before B—don't claim "produces".

### Layer D—Demography and households (DECISION NEEDED)

Pool now: 661 adult / 188 middle / 47 young / 4 old—**almost all working-age, no dependents**.
"Household with dependents" has nothing to build on. Fork (choose before code): (a) **augment demography
in pool** offline—children/elderly in households (dependents consume, don't produce; grounds inheritance/
"spare the family"/demography); OR (b) **restrict households** to "adults under one roof + econ-solidarity"
without dependents (cheaper, leaner). Recommendation—(a) via small offline pass at pool forging, since households
need dependents for sense. Families from ties now SCATTERED—households need family settling together (reshape placement,
watch determinism/saves).

### Layer E—Time (single source of truth)

`open_hours` (opening/closing in game time) on venue—**single** source of "when place is active"; 4-phase utility
windows become DERIVED from them (not two systems). Plus day of week / market day (market ×1.5) and canonical service
hours. Data, not code. Economy "once per day" lazy on skipped days (player sleeps/in dungeon 3 days → catch up 3
updates by day, like deeds-appointments)—against desync on absences.

### Observability

NPC schedule card (Majora's Bombers' Notebook—scale "where at what phase" from `predict()`);
activity label above NPC ("working/dining/on patrol" from crof_kind); stand `/citydebug/cityday`
(GIF + named chains as dashboard: who→whom→price, where shortage); occupancy gradient
(DF low/high: "busy with important" → shorter replies to player).

### Implementation order (cheap green increments; C-spatial → A → B → C-econ → D/E)

1. **C-spatial ✔** (2026-07-07, on prod): `_plan_jobs` (deterministic, both placement paths)—
   venue recruits NEAREST-by-home workers of role (gravity, workcap by type); service surplus →
   day-laborer reclassification with memory "was X before"; crafts work at home (role kept). Count:
   taverns 6 each, innkeeper 54→12, 143 day-laborers. Lie "innkeeper at home" fixed; agendas
   "save for my own" gain meaning.
2. **A intent-forecast ✔** (2026-07-07, on prod): `predict(pid,phase)`→{node,kind,route},
   `forecast(pid)`=day schedule, `crosses(pid,node,phase)`=plan-level intercept;
   obligations as override (set_commit/clear_commit: flee>appointment>shift>follow>errand;
   follow pins to player, yields to critical need). Endpoint /api/play/schedule (card for acquaintance).
   Core (choose_c) untouched. 4 tests.
3. **B1 economy ✔** (2026-07-07, on prod): 10 named chains (chains.json) +
   `economy.py`—coin-seed M + daily economy_step (production→goods, purchase=coin transfer
   CONSERVATION M, prices from demand/stock clamp+elasticity) + wealth-need from purse;
   endpoint /api/play/economy (stand). Count: M invariant, inequality emergent, chain break→price up. 4 tests.
   **B2 player commodity market ✔** (2026-07-07, on prod): inside venue player trades chain goods at live price—
   `market_here/player_buy/player_sell`. Buy: stock−, price↑ (clamp base×4), coin player→producers = INFLATION (M+),
   good to pack. Sell: stock+, price↓, coin buyers→player = DEFLATION (M−), spread 0.7 + illiquid. Market trick:
   hoard bread → price ×8 → city starves. Fix price semantics in economy_step (demand=demand, not ×3—stock now
   accumulates in surplus; shortage→up/excess→down; stock ceiling demand×8). Endpoints /api/play/market[/buy|/sell] +
   UI modal "vendor". 3 tests (M invariant 12897).
   **B3 venue buyout ✔** (2026-07-07, on prod): `former_role` at reclassification (C-spatial);
   daily `venue_buyouts`—aspirant day-laborer with OWN former craft + money buys vacant venue (owner dead/spots < capacity)
   → work=venue, role restored, deed 'acquire', money to co-owner (M kept) or from city (M−). Economic healing:
   kill chain producer → aspirant revives it. Live: kill tavern workers → ex-innkeeper buys back, craft returned.
   5 tests (determinism: force world rebuild per-test).
4. **C-economic ✔** (2026-07-07) folded into B: production = output×live producers in
   economy_step (no separate layer). TOTAL B done (B1+B2+B3).
5. **D demography/households ✔** (2026-07-07, on prod, fork (a)—dependents IN POOL):
   **D1**—`_households` splits pool into families (by surname, size 1-5), each lives in ONE house
   (houses deduplicated by node); count 349 households, 0 mixed-surname. **D2**—scripts/depgen.py
   (offline, no LLM) augmented +454 dependents (children/elderly, mech.dependent+head, template persona)
   into worlds.db (900→1354); settle in household head's house, work=None, excluded from "home work"
   (_NONCRAFT); top-up settles them in OLD worlds without disturbing adults. Count: 100% under adult
   kin roof, restore holds. 5 tests. NEXT: household-economy (head feeds dependents → food demand),
   personas/portraits for dependents (separate batch).
6. **E time ✔** (2026-07-07, on prod): **E1 lazy catch-up**—economy_step(day=) for specific days;
   economy_catchup() runs turnover for EACH skipped day (baseline—day start, flag econ_day, cap 7 = LOD),
   decoupled from "morning" (hook in _apply_routine, idempotent); jump 0→5=[1..5], coin kept.
   **E2 open_hours** (single source of hours)—canon windows by venue type (tavern 11-01, market/shop day,
   temple services, gambling 18-04, hours past midnight); gates player trade B2 (closed→"opens at N:00",
   banner 🔒), feeds narrative. 4 tests. NEXT: market day (weekly markets busier), NPC-windows places.py
   derive from same canon.
7. Observability (stand /citydebug/cityday, activity label above NPC, cards)—in parallel.

### What Does NOT Break

Utility-core (`society/`), scene (reads crof/predict same way), events (places=real homes/jobs;
with economy—richer: deficit-event from real chain), deal-gate (hire with real money from `M`),
turn-based (intent—forecast, not real time). Core not rewritten, layers stack.


Related: [sim-stitching.md](sim-stitching.md) (ring-A↔B seam: churn/capacity/transit/unpin) ·
[loop.md](loop.md) (fast/slow tick) · [mind.md](mind.md) (NPC minds) ·
[locations.md](locations.md) (live scene, capacity,
materialization=layer 2) · [worldgen.md](worldgen.md) (graph, settlement, pool) ·
[items.md](items.md) (goods=factsheet) · [quests.md](quests.md) · [entities.md](entities.md)
