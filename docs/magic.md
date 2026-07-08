# Magic Circles (M-6)

`src/aidnd/magic`. Reference for [principle 2](README.md): **LLM is free in the ESSENCE of the law, but not in POWER** — grammar and budget are deterministic, clamp is rigid.

## Circle = DRAWING

Composition: `[{glyph id, size 0..1, angle 0..360, ring 0|1}]`. Size = power, position = circle's orientation (on self/outward/around), inner ring = tint. Geometry rules (`RULES_RU`, grammar.py) — the same 5 rules go into the lawgiver's prompt: size↔power, position↔direction, rings, contradictions, budget.

- **Power budget** = Σ (glyph weight × size multiplier × ring multiplier).
- **Canonical hash** of the drawing (size by bins, angle by 8 sectors) — cache key.
- `base_law` — deterministic LAW SKELETON by table logic; NOT fallback: `clamp_law` fills in gaps in the LLM's answer.

## Law from LLM

Role `spell_scribe`: drawing + rules + glyph dictionary → law IN FULL: name/flavor/sensory/kind (**freeform** — flight, fog, illusion, shackles…)/power/target/range/duration/taboo/mech. Server clamps (`clamp_law`): power ≤ budget, range ≤ 12, duration ≤ 20, die `N≤power`d`≤8`, heal ≤ 2×power, aoe-radius ≤ 1+power/3, statuses from menu. Cache — **grimoire-per-world** by drawing hash (`flags: grim|<hash>`; re-casting the same circle = same law).

## Cast WITHOUT roll

Failure — only for honest reasons: contradictions in the drawing / overspend / candle extinguished → **wild magic**: role `wild_magic` plays out outcome from LIMITED menu `backfire · nothing · scorch · warp · boon` (magnitude 1-3, element from dictionary) — won't break the world. Combat/dark witchcraft with witnesses = taboo → bounty points (PB `taboo_witness`).

## Mana economy (all numbers — PB)

Start 12 / cap 14, hard cap Int×8; regen 1/hour, **sleep ×3**; exhaustion from overspend (penalty until expiration); drawing on canvas drains mana in real time (drag/size/rings — interactive canvas in UI). Learning glyphs — from mage/scribe for coins (handlers/magic.py: learn/teachers).

Related: [loop.md](loop.md) (magic handler) · [combat.md](combat.md) (mechanics in combat) · [entities.md](entities.md) (grimoire in flags)
