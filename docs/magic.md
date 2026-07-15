# Magic Circles

`src/aidnd/magic` (grammar + inscribe) + `server/play/handlers/magic.py` (loop). Reference for
[principle 2](README.md): **the LLM is free in the ESSENCE of a law, never in its POWER** — grammar and
budget are deterministic, the clamp is rigid.

## Circle = a DRAWING

Composition: `[{glyph id, size 0..1, angle 0..360, ring 0|1}]`. Size = power, position = the circle's
orientation (on self / outward / around), inner ring = tint. Geometry rules (`RULES_RU`, grammar.py) —
the same five rules feed the law-scribe's prompt: size↔power, position↔direction, rings, contradictions,
budget.

- **Power budget** = Σ (glyph weight × size multiplier × ring multiplier).
- **Canonical hash** of the drawing (size binned, angle by 8 sectors) — the grimoire cache key.
- `base_law` — a deterministic law SKELETON by table logic; not a fallback but the scaffold
  `clamp_law` fills the LLM's gaps into.
- Only **learned glyphs** may be drawn; an unknown glyph → locked, learn it from a teacher.

## Law from the LLM

Role `spell_scribe` (`inscribe.py`): drawing + rules + glyph glossary → a law IN FULL —
name / flavor / sensory / kind (**freeform**: flight, fog, illusion, shackles, light, unlock… open
list `LAW_KINDS`) / power / target / range / duration / law-phrase / taboo / combat mech. The server
**clamps** it (`clamp_law`): power ≤ budget, range ≤ 12, duration ≤ 20, damage die `N≤power`d`≤8`,
heal ≤ 2×power, aoe radius ≤ 1+power/3, status from the menu (bound/asleep/afraid), turns ≤ duration.
Cache = a **grimoire per world** keyed by drawing hash — re-casting the same circle replays the same
law with no LLM call.

## Casting — no roll

A clean circle with enough mana fires ALWAYS; there is no cast roll. Failure only for honest reasons —
a contradiction in the drawing, or the candle guttering (mana ran out mid-draw). Either → **wild
magic**: role `wild_magic` plays the outcome from a bounded menu `backfire · nothing · scorch · warp ·
boon` (magnitude 1–3, element from the dictionary) — chaos that cannot break the world. A known circle
casts instantly for a fixed fraction of budget; a fresh one costs leak×drawing-seconds + budget.
Burning mana grows the cap; a rupture exhausts harder. Freeform essence executes as a **world event**
(narration + memory + witnesses); combat mech (damage/aoe/status/heal/reveal/unlock/light) resolves
against the live `Encounter`. Combat or dark law before townsfolk = taboo → bounty (`taboo_witness`).

## Enchanting — a bound law

Instead of casting, a drawn circle's law can be **bound into an item** (`/enchant`): the item's чара
(arcane attribute, [items.md](items.md)) caps the law's budget, binding costs mana like a cast, and
the law fires later on `/use` (`_activate_enchant`) through the same deterministic runner — charges
decrement to zero, then the enchant is spent and the item stays. A weapon's elemental attributes also
surface directly in combat as typed on-hit payloads (no circle needed) — see [combat.md](combat.md).

## Mana economy (all numbers — PB)

Start / cap / hard-cap by Int, regen per hour with **sleep ×3**, exhaustion from overspend. Drawing on
the canvas drains mana in real time (drag/size/rings — the client melts the candle in sync via the
`draw` rate from `/glyphs`). Learning glyphs — from a mage (elements/forms/modes) or scribe
(verbs/modes) for coins by glyph weight, free at high affinity (`/learn`, `/teachers`); `/grimoire`
lists inscribed laws with composition and cast count.

## Next

- A dedicated order/inquisition tier of manhunt for witchcraft (current taboo is the light version).
- Ranged/positional spell tactics deeper into combat AI.

Related: [loop.md](loop.md) (magic handler) · [combat.md](combat.md) (mechanics + elemental on-hit) ·
[items.md](items.md) (enchanting, чара) · [entities.md](entities.md) (grimoire in flags)
