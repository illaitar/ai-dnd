# Items as an attribute graph — design spec (subsystem 1 of 3)

**Status:** approved design, ready for implementation plan. Date: 2026-07-10.
**Program:** the craft/items rework. Three sequenced sub-projects:
1. **Item attribute graph (THIS spec)** — the foundation.
2. Luck & inspiration (global PC traits) — separate spec.
3. Emergent craft spark ladder — separate spec; depends on 1 + 2.

This spec covers **only** subsystem 1. It must not preclude 2–3; the interfaces they need are
listed in "Downstream interfaces" below.

## Problem

The item system is a flat factsheet with three unconnected craft paths (see the current-state audit).
Two structural faults block everything downstream:

1. **`material` is a cosmetic string.** An item carries `material: "неясный сплав"` — pure display.
   A silver blade and a steel blade are mechanically identical. Material quality never reaches the
   dice: `craft()` accepts an `inputs=` material bonus and *no caller passes it*.
2. **Effects are hand-authored per item and mostly sleep.** A `mod` (`{target, op, amount, when}`) is
   typed onto each item by the LLM smith; the smith prompt itself says combat targets are allowed
   "но пусть спят". There is no shared vocabulary connecting *what a thing is made of* to *what it
   does*, so nothing is consistent and most effects are inert.

The emergent craft ladder (subsystem 3) needs "a better item with better attributes" to be a
computable thing. It is not, today. This subsystem makes it one.

## Root cause

The model has no layer between composition and effect. Materials, forms, and treatments don't exist
as data with mechanical meaning; effects are authored, not derived. The fix is to insert a canonical
middle layer — **attributes** — that composition feeds and effects derive from.

## Design decision (locked)

- **Attributes are intrinsic physical properties**, the canonical center of the model. Materials +
  forms + treatments feed *into* them; game effects (attack/defense/worth/appearance/…) are computed
  *out* of them by code. (Chosen over "effects as the hubs".)
- **Full rework**: `normalize`/`inspect`/`view`/combat/worth read attributes directly; legacy items
  migrate. (Chosen over a non-breaking projection or a generative-only compiler.)
- **Migration = a canonical catalog** built by an offline LLM re-forge of every distinct item name,
  cached in `worlds.db`. This same catalog is subsystem 3's rung-0 craft pool (one artifact, two
  jobs).
- **Code owns the math.** Effect derivation is a code-owned rules table (thresholds/curves), tunable
  in `PB`. The LLM authors *composition and flavor*, never a balance number.
- The attribute vocabulary is a **curated core**; only subsystem 3's bespoke tier extends it.

## Architecture — five units

### U1 — the attribute vocabulary

A curated core of 13 intrinsic properties, each a scalar **0–100**:

`острота` (sharpness) · `твёрдость` (hardness) · `прочность` (integrity/wear) · `вес` (heft) ·
`гибкость` (flexibility) · `краса` (beauty) · `ценность` (preciousness) · `чара` (arcane
receptivity) · `мана` (stored magical energy) · `святость` (sanctity) · `скверна` (taint/toxicity) ·
`теплостойкость` (heat resistance) · `точность` (balance/trueness).

**`чара` vs `мана` (disambiguation, binding):** `чара` = how well a substrate *takes* enchantment
(silver/crystal high, iron low) — it gates whether/how strongly an `enchant` can be applied. `мана` =
*stored magical energy / capacity to supply it* (a charged crystal, a focus, a mana-restoring brew).
A plain silver ring: high `чара`, zero `мана` until charged.

Each attribute on an item holds **two values — `surface` and `true`**. That pair *is* the deception
layer: a forgery has high surface `ценность` and low true `ценность`; a `craft_eye`/appraise
inspection reveals the gap. For an honest item surface == true.

### U2 — the attribute graph (`src/aidnd/items/attrgraph.json`, authored data)

Three node types; edges carry attribute contributions/deltas.

- **materials** → base attribute contributions.
  `сталь → {твёрдость:70, острота:65, прочность:70, вес:60, теплостойкость:60}`;
  `серебро → {краса:80, ценность:75, чара:55, святость:60, твёрдость:30}`;
  `дуб → {прочность:55, вес:45, гибкость:30}`; `кожа → {гибкость:70, прочность:40, вес:20}`;
  `лунный камень → {чара:70, мана:60, краса:65}`; `целебные травы → {скверна:0, …}` (potency for
  consumables). Numbers are authored data, tuned later.
- **forms** (archetype: `клинок`, `древко`, `щит`, `оправа`, `сосуд`, `подошва`, `навершие`…) —
  declare **which attributes express and as which effect**. The form is the gate that keeps a sharp
  `щит` from yielding +attack. A form maps expressed-attributes → effect-rule keys (U4).
- **treatments** (process: `закалка → +твёрдость −гибкость`, `заточка → +острота`,
  `золочение → +краса +ценность`, `зачарование → +чара, grants:<effect>` (needs `чара` headroom),
  `отрава → +скверна (hidden)`, `освящение → +святость`, `зарядка → +мана`) — each is an
  attribute-delta op. This is how hone/temper/enchant/poison/charge/repair all become *one verb:
  mutate an attribute*.

Composition math (code, deterministic): `attrs = Σ material contributions (by part) → gated/weighted
by form → treatment deltas applied → clamped 0–100`, then scaled by craftsmanship `quality`
(crude/plain/fine/exquisite as a multiplier band). Surface := true for honest items; forgeries and
flaws set surface ≠ true.

### U3 — the item model (canonical = composition + attributes)

```
item = {
  id, name, kind, slot, rarity, weight,          # weight derived from вес × size
  parts:  [{role:"клинок", material:"сталь", treatments:["закалка","заточка"]},
           {role:"рукоять", material:"дуб",  treatments:[]}],
  attrs:  {острота:{surface:78, true:78}, твёрдость:{surface:72, true:72}, …},   # SOURCE OF TRUTH
  hidden: [ … ],                 # narrative truths that are NOT pure attributes
                                 # (provenance, curse, compartment, function) — keep as today, gated
  durability: derived from прочность (max/current, break_behavior, weak_at),
  make: {maker_id, maker_name, mastery, margin, mark},
}
```

- `attrs` is canonical. There is **no stored mod list** to drift out of sync.
- `derive_effects(item) -> {mods, worth, appearance, …}` computes the effect layer from `attrs`
  (true values) + form on read. Consumers call it.
- Narrative `hidden` props that aren't attributes (provenance/curse/compartment/function) stay in the
  `hidden[]` model exactly as today, with their existing inspection gates. Attribute deception
  (forgery/true_worth/true_material/flaw) is now expressed as `surface ≠ true` on the relevant
  attribute rather than a bespoke hidden string, but the *inspection gate mechanics* (via/dc/req) are
  reused (U5).

### U4 — effect derivation & consumer rewrites (the "full" part)

`derive_effects` uses a **code-owned rules table** (tunable in `PB`), form-gated. Illustrative:

| effect (target)     | derived from (true attrs), when form expresses it | notes |
|---------------------|---------------------------------------------------|-------|
| `attack`            | `f(острота, твёрдость, точность)` — weapon forms   | edged vs blunt weight the inputs differently |
| `defense`           | `f(твёрдость, прочность)` — armor/shield forms     | |
| `social:appearance` | `f(краса)`                                         | any worn/held form |
| `worth`             | `g(ценность, краса, чара, quality, rarity)`        | true worth; surface worth from surface attrs |
| `poison` (hidden)   | `скверна > 0`                                       | hidden by default |
| `enchant` / grants  | `чара ≥ threshold` + a `зачарование` treatment      | |
| `special:mana`      | `мана` — focus/trinket (equipped) lifts `mana_cap`; consumable restores `_mana` on use | ties to `pc/mana.py` |
| `durability`        | `прочность` → max; `weak_at` from a flaw           | wear/break loop is subsystem 3+ |

Rewrites (all read `derive_effects` instead of stored mods/persona strings):
- **combat** — `_combatant_from_npc` / `_pc_combatant` source weapon/armor stats from the equipped
  items' derived `attack`/`defense`, not persona gear strings.
- **worth/negotiation** — `view()` returns surface worth (from surface attrs) until true worth is
  revealed, then true worth (from true attrs). Existing worth-gating semantics preserved.
- **inspect** — reveals **true attribute values** (gate by `via`/competency as today); the item card
  shows surface until revealed. A forgery reveals the surface/true gap on `craft_eye`.
- **item card / UI** — renders attributes and derived effects; surface values pre-inspection.

### U5 — migration = the canonical catalog (offline LLM re-forge, cached)

- A gen script (sibling of `peoplegen.py`/`depgen.py`) forges **every distinct item name** across
  `SEED_POOL`, NPC persona `gear`, and zone `objects` into `parts` + `attrs`, once, cached in
  `worlds.db`, keyed by `(kind, canonical_name)`. LLM authors composition; code computes `attrs`.
- Runtime items reference a catalog base and apply **instance deltas** (wear, enchant, poison).
- An unseen name (novel loot / a bespoke craft) is forged on demand and joins the catalog.
- This catalog **is** subsystem 3's rung-0 craft pool (lookup by kind/name). Building it here is the
  migration; reusing it there is rung 0.
- The current `item_pool` (weighted random loot table) remains for *random* loot draws; the catalog
  adds the *keyed* lookup it lacks.

## Downstream interfaces (subsystems 2–3 must not be precluded)

- **Craft ladder (3)** calls `catalog_lookup(kind, name) -> item | None` (rung 0), a composition
  builder `forge_from_composition(parts, quality, maker) -> item`, and reads material `attrs` as the
  "material quality" term of `spark`. `derive_effects` gives rung-1 "modified item" its bumps.
- **Luck & inspiration (2)** are `spark` terms in subsystem 3; this subsystem needs no hook for them.
- Attribute deltas (`hone/temper/enchant/poison/charge/repair`) are exposed as one internal op
  `apply_treatment(item, treatment)` that mutates `attrs` and lets `derive_effects` re-project —
  reused by craft, repair, and magic later.

## Global constraints

- **No hardcoded gameplay numbers in code** — attribute contributions/deltas live in `attrgraph.json`
  (data); effect-rule coefficients and thresholds live in `PB`. The pure item module may hold
  structural constants (enum lists, the attribute vocabulary) but not balance values.
- **No LLM fallback at runtime** — catalog *lookup* is deterministic; forging an unseen name needs
  the LLM and errors honestly if unavailable (never a canned stub). Offline catalog build is a gen
  script, not a runtime path.
- **Full suite green** before ship: `uv run pytest /Users/nik/Desktop/dnd-ai/tests` (absolute path).

## Testing

- **Pure/unit:** material + form + treatment → expected attribute vector (clamped, quality-scaled);
  attribute vector + form → expected derived effects (threshold table); `закалка` raises `твёрдость`
  and lowers `гибкость`; `заточка` raises `острота`; a `щит` form yields `defense`, never `attack`;
  `чара` vs `мана` are independent (charging raises `мана`, not `чара`).
- **Deception:** a forgery (surface `ценность` high, true low) is hidden on `glance`, revealed on
  `craft_eye`/appraise; `view()` shows surface worth until revealed, true worth after.
- **Migration:** a legacy flat weapon re-forges into a plausible `parts`/`attrs`, and its
  `derive_effects` attack ≈ its old bonus (within a tolerance band); catalog lookup is deterministic
  and LLM-free for seen names.
- **Consumers:** combat damage/defense read from equipped items' derived effects; a mana focus lifts
  `mana_cap`; a mana draught restores `_mana`.

## Risks

- **Scale of the rewrite.** `inspect`/`view`/combat/worth all change. Mitigate: `derive_effects` is
  the single seam; consumers call it, so the blast radius is one function's contract. Land the model
  + derivation + tests first, then convert consumers one at a time behind the same green suite.
- **Catalog build cost/quality.** ~one LLM forge per distinct name (far fewer than 1354 — names
  repeat). Mitigate: dedupe by name, cache in `worlds.db` (git), gen offline, spot-check a sample.
- **Attribute→effect tuning.** Derived numbers may feel off vs the old hand-authored ones. Mitigate:
  coefficients in `PB`; the migration tolerance test anchors weapons to their old bonuses.
- **`чара`/`мана` overlap** confusing the smith. Mitigate: the binding disambiguation in U1 goes into
  the forge prompt verbatim.

## Increment (green → commit → deploy), high level

1. Model + graph data + composition math + `derive_effects` + pure tests (no consumers yet).
2. Inspection/view on attributes (surface/true, deception) + tests.
3. Consumer conversion: combat, worth, item card — one at a time, suite green each.
4. Catalog gen script + migration + `catalog_lookup`; re-forge seed/gear/zone names; deploy.

The implementation plan will break these into task-sized steps.
