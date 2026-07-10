# Item attribute graph — Phase 2 (inspection reveals true vs surface) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Wire the attribute deception layer: an item's attributes carry surface (may lie) and true values; an observer sees surface-derived worth/effects until an inspection (`appraise`/`craft_eye`/`lore`/`expert`) reveals the true values of an attribute *group*. Legacy items (no `attrs`) are unchanged.

**Architecture:** The lie lives entirely in `surface ≠ true` — a poisoned blade has surface `скверна`=0, so deriving from surface naturally hides the poison until revealed. `derive_effects(item, known=…)` resolves each attribute to true (if its group is in `known`) or surface (default `known=None` = reality/omniscient → all true, so Phase-1 callers are unaffected). `inspect()` returns which attribute groups a method reveals; the `/inspect` endpoint merges those group sentinels into the item's `known` set (same store field as hidden-prop reveals). `view()` gains an attribute branch that shows the surface-until-revealed vector plus derived worth/mods.

**Tech Stack:** Python 3.14, pytest.

## Global Constraints

- **`derive_effects(item)` with no `known` must be byte-identical to Phase 1** (reality = all true) — every Phase-1 test must still pass.
- **Legacy items (`attrs == {}`) route through the existing `view()` unchanged** — no field renamed or dropped; `_item_card`/combat/trade see identical output for today's items (none of which have `attrs` yet).
- **No hardcoded gameplay numbers in play-layer code.** Reveal DC / group→competency maps live as module constants in the pure `aidnd.items` modules (the pure-module exception).
- **No import cycle:** `inspect.py` may import from `.attrs` (which imports only `.model`).
- **Full suite green** before finishing each task: `uv run pytest /Users/nik/Desktop/dnd-ai/tests` (ABSOLUTE path). Baseline is 298 passing.
- Spec: [docs/superpowers/specs/2026-07-10-item-attribute-graph-design.md](../specs/2026-07-10-item-attribute-graph-design.md) (U1 surface/true, U4 inspection). Phase 1 shipped `ATTRS`, `attrgraph.json`, `compose`, `derive_effects`, and `attrs`/`parts`/`form` on `normalize`.

**Note on visibility:** no live item has `attrs` populated yet (the catalog/craft phases forge those), so this phase has no in-game effect — it is verified by unit + integration tests, and deployed to keep prod in sync.

---

### Task 1: thread an observer's `known` through `derive_effects` (attribute groups)

**Files:**
- Modify: `src/aidnd/items/attrs.py` (add `ATTR_GROUPS`, `attr_group`, `_eff`; thread `known` through `_score` and `derive_effects`)
- Test: `tests/items/test_attrs.py` (extend)

**Interfaces:**
- Produces: `ATTR_GROUPS: dict[str, tuple]` (sentinels `"attr:phys"|"attr:value"|"attr:arcane"` → member attrs); `attr_group(attr) -> str` (the sentinel for an attr); `derive_effects(item, rules=None, known=None)` — `known=None` → all true (reality); `known` a set → per-attribute true if its group sentinel is in `known`, else surface.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/items/test_attrs.py
def test_known_none_is_reality_all_true():
    it = {"attrs": {"ценность": {"surface": 90, "true": 5}}, "form": "оправа", "kind": "trinket"}
    assert derive_effects(it)["worth"] == derive_effects(it, known={"attr:value"})["worth"]  # both true=5


def test_surface_until_value_group_revealed():
    it = {"attrs": {"ценность": {"surface": 90, "true": 5}}, "form": "оправа", "kind": "trinket"}
    assert derive_effects(it, known=set())["worth"] > derive_effects(it, known={"attr:value"})["worth"]


def test_poison_hidden_until_arcane_revealed():
    it = {"attrs": {"скверна": {"surface": 0, "true": 60}}, "form": "клинок", "kind": "weapon"}
    assert not [m for m in derive_effects(it, known=set())["mods"] if m["target"] == "special:poison"]
    assert [m for m in derive_effects(it, known={"attr:arcane"})["mods"] if m["target"] == "special:poison"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attrs.py -k "known or surface_until or poison_hidden" -v`
Expected: FAIL — `derive_effects()` has no `known` kwarg (TypeError).

- [ ] **Step 3: Add groups + effective-value resolution, thread `known`**

In `src/aidnd/items/attrs.py`, after `FOCUS_FORMS = (...)`, add:

```python
# attribute groups — an inspection reveals a whole group's TRUE values (sentinels double as `known` keys)
ATTR_GROUPS = {
    "attr:phys":   ("острота", "твёрдость", "прочность", "точность", "гибкость", "вес", "теплостойкость"),
    "attr:value":  ("ценность", "краса"),
    "attr:arcane": ("чара", "мана", "святость", "скверна"),
}
_ATTR_TO_GROUP = {a: g for g, atts in ATTR_GROUPS.items() for a in atts}


def attr_group(a: str) -> str:
    return _ATTR_TO_GROUP.get(a, "attr:phys")


def _eff(attrs: dict, a: str, known) -> int:
    """Effective value for an observer: TRUE if known is None (reality) or the attr's group is
    revealed in `known`; else SURFACE (the lie)."""
    v = attrs.get(a) or {}
    if known is None or attr_group(a) in known:
        return int(v.get("true", 0))
    return int(v.get("surface", 0))
```

Then replace the existing `_true` helper and its callers. Change `_score` to:

```python
def _score(attrs: dict, w: dict, known) -> float:
    return sum(_eff(attrs, a, known) * k for a, k in w.items())
```

Change `derive_effects` signature to `def derive_effects(item: dict, rules: dict | None = None, known=None) -> dict:` and, inside it, replace every `_true(attrs, X)` with `_eff(attrs, X, known)` and every `_score(attrs, W)` with `_score(attrs, W, known)`. Delete the now-unused `_true` function. (The attack/defense/appearance/poison/mana/worth/durability blocks are otherwise unchanged.)

- [ ] **Step 4: Run tests + full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attrs.py -v` → PASS (Phase-1 tests still green — they call `derive_effects(item)` → `known=None` → true)
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/items/attrs.py tests/items/test_attrs.py
git commit -m "feat(items): derive_effects observes an attribute-group `known` set (surface vs true) [attr-graph p2]"
```

---

### Task 2: `inspect()` reveals attribute groups by method

**Files:**
- Modify: `src/aidnd/items/inspect.py` (add `_attr_reveal`; return `attr_groups`)
- Modify: `src/aidnd/server/play/handlers/inventory.py` (merge `attr_groups` into `known`)
- Test: `tests/items/test_inspect_attrs.py` (create)

**Interfaces:**
- Consumes: `Capability` (abilities/competencies), the item's `attrs`.
- Produces: `inspect(...)` return dict gains `"attr_groups": [sentinel,...]` — the groups newly revealed this inspection. `craft_eye`→phys (needs a craft competency), `appraise`→value, `lore`→arcane (value/arcane pass on a competency shortcut OR an ability roll vs `_ATTR_DC`), `expert`→all three.

- [ ] **Step 1: Write the failing test**

```python
# tests/items/test_inspect_attrs.py
from aidnd.items import inspect as item_inspect
from aidnd.items.model import Capability

FORGERY = {"id": "f1", "kind": "trinket", "form": "оправа",
           "attrs": {"ценность": {"surface": 90, "true": 5}}, "hidden": []}
BLADE = {"id": "b1", "kind": "weapon", "form": "клинок",
         "attrs": {"острота": {"surface": 30, "true": 80}}, "hidden": []}


def test_appraiser_competency_reveals_value():
    merchant = Capability(abilities={"int": 12}, competencies={"trade"})
    assert "attr:value" in item_inspect(FORGERY, merchant, "appraise")["attr_groups"]


def test_craft_eye_needs_a_trained_hand():
    smith = Capability(abilities={"int": 10}, competencies={"metalwork"})
    layman = Capability(abilities={"int": 10})
    assert "attr:phys" in item_inspect(BLADE, smith, "craft_eye")["attr_groups"]
    assert "attr:phys" not in item_inspect(BLADE, layman, "craft_eye")["attr_groups"]


def test_glance_reveals_no_groups():
    anyone = Capability(abilities={"int": 20}, competencies={"trade", "metalwork", "lore"})
    assert item_inspect(FORGERY, anyone, "glance")["attr_groups"] == []


def test_expert_reveals_all_groups():
    res = item_inspect(FORGERY, Capability(abilities={"int": 10}), "expert")
    assert set(res["attr_groups"]) == {"attr:phys", "attr:value", "attr:arcane"}


def test_no_attrs_no_groups():
    legacy = {"id": "l1", "kind": "weapon", "attrs": {}, "hidden": []}
    assert item_inspect(legacy, Capability(abilities={"int": 20}), "expert")["attr_groups"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_inspect_attrs.py -v`
Expected: FAIL — `inspect()` returns no `attr_groups` key (KeyError).

- [ ] **Step 3: Add `_attr_reveal` and return `attr_groups` in `inspect.py`**

In `src/aidnd/items/inspect.py`, after the imports, add module constants:

```python
_VIA_GROUP = {"craft_eye": "attr:phys", "appraise": "attr:value", "lore": "attr:arcane"}
_GROUP_COMPS = {"attr:phys": {"metalwork", "leather", "gems", "herbs"},
                "attr:value": {"trade", "gems"},
                "attr:arcane": {"lore", "faith"}}
_ATTR_DC = 12


def _attr_reveal(item: dict, cap: Capability, via: str, seed: str) -> list:
    """Attribute GROUPS this inspection reveals as true. Expert assesses fully; a trained eye
    (competency) sees at a glance; else appraise/lore fall to an ability roll; phys needs the hand."""
    if not item.get("attrs"):
        return []
    if via == "expert":
        return list(_VIA_GROUP.values())
    grp = _VIA_GROUP.get(via)
    if not grp:
        return []
    if cap.competencies & _GROUP_COMPS[grp]:
        return [grp]
    if grp == "attr:phys":
        return []                                          # physical truth needs the trained hand
    abil = max(cap.mod("int"), cap.mod("wis")) if via == "appraise" else cap.mod("int")
    return [grp] if abil + _roll(seed) >= _ATTR_DC else []
```

Then, in `inspect(...)`, change the final `return` to also compute and include newly-revealed groups:

```python
    attr_groups = [g for g in _attr_reveal(item, cap, via, f"{base}|attrs|{via}") if g not in known]
    return {"revealed": revealed, "hints": hints, "via": via, "attr_groups": attr_groups}
```

- [ ] **Step 4: Merge `attr_groups` into `known` in the endpoint**

In `src/aidnd/server/play/handlers/inventory.py`, in `inspect_item`, change:

```python
    known |= {h["prop"] for h in res["revealed"]}
```
to:
```python
    known |= {h["prop"] for h in res["revealed"]} | set(res.get("attr_groups", []))
```

- [ ] **Step 5: Run tests + full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_inspect_attrs.py -v` → PASS
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidnd/items/inspect.py src/aidnd/server/play/handlers/inventory.py tests/items/test_inspect_attrs.py
git commit -m "feat(items): inspect() reveals attribute groups by method; endpoint merges them into known [attr-graph p2]"
```

---

### Task 3: `view()` shows the surface-until-revealed attribute vector

**Files:**
- Modify: `src/aidnd/items/inspect.py` (add an attribute branch to `view()`)
- Test: `tests/items/test_attr_view.py` (create)

**Interfaces:**
- Consumes: `derive_effects`, `ATTR_GROUPS`, `attr_group` (from `.attrs`), an item with `attrs`, the observer `known` set.
- Produces: for an item WITH `attrs`, `view()` returns the legacy key set plus `"attrs"` — a `{attr: {"value": int, "true_known": bool}}` map (value = true if the group is revealed, else surface) — with `worth`/`mods` derived from the effective vector and `unknown` = count of attribute groups not yet revealed. Legacy items (no `attrs`) are byte-identical to before.

- [ ] **Step 1: Write the failing test**

```python
# tests/items/test_attr_view.py
from aidnd.items import normalize, view


def _mk(d):
    it = normalize(d)
    it["id"] = "vt"
    return it


def test_forgery_worth_flips_on_value_reveal():
    it = _mk({"kind": "trinket", "name": "перстень", "form": "оправа",
              "attrs": {"ценность": {"surface": 90, "true": 5}}})
    assert view(it, set())["worth"] > view(it, {"attr:value"})["worth"]
    assert view(it, {"attr:value"})["worth_known"] is True
    assert view(it, set())["worth_known"] is False


def test_shown_vector_and_unknown_count():
    it = _mk({"kind": "weapon", "name": "нож", "form": "клинок",
              "attrs": {"острота": {"surface": 30, "true": 80}}})
    v = view(it, set())
    assert v["attrs"]["острота"] == {"value": 30, "true_known": False}
    assert v["unknown"] == 3
    v2 = view(it, {"attr:phys"})
    assert v2["attrs"]["острота"] == {"value": 80, "true_known": True}
    assert v2["unknown"] == 2


def test_legacy_view_has_no_attrs_key_and_same_worth():
    it = _mk({"kind": "weapon", "name": "ржавый нож", "worth": 3, "apparent_worth": 3, "mods": []})
    v = view(it, set())
    assert "attrs" not in v and v["worth"] == 3
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attr_view.py -v`
Expected: FAIL — `view()` returns no `attrs` key / wrong worth for attribute items.

- [ ] **Step 3: Add the attribute branch to `view()`**

In `src/aidnd/items/inspect.py`, at the very top of `view(item, known=None)`, before the existing legacy body, add:

```python
def view(item: dict, known=None) -> dict:
    """What observer KNOWS about the item (for UI/negotiation)."""
    known = set(known or [])
    if item.get("attrs"):
        return _view_attrs(item, known)
    # ---- legacy factsheet path (items without an attribute vector) ----
    <the existing body stays exactly as-is here>
```

And add the helper (place it directly above `view`):

```python
def _view_attrs(item: dict, known: set) -> dict:
    """View for attribute-driven items: surface values until the group is revealed; worth/mods
    derived from the effective vector."""
    from .attrs import ATTR_GROUPS, attr_group, derive_effects

    eff = derive_effects(item, known=known)
    shown = {}
    for a, v in item["attrs"].items():
        grp_known = attr_group(a) in known
        shown[a] = {"value": int(v["true"] if grp_known else v["surface"]), "true_known": grp_known}
    return {"name": item["name"], "kind": item["kind"], "slot": item["slot"],
            "material": item["material"], "quality": item["quality"], "weight": item["weight"],
            "worth": eff["worth"], "worth_known": ("attr:value" in known),
            "tags": item["tags"], "mods": eff["mods"], "attrs": shown,
            "facts": [h["fact"] for h in item.get("hidden", []) if h["prop"] in known and h.get("fact")],
            "unknown": sum(1 for g in ATTR_GROUPS if g not in known),
            "durability": item.get("durability")}
```

- [ ] **Step 4: Run tests + full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attr_view.py -v` → PASS
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS (legacy `view()` unchanged → `_item_card`/trade/combat identical for today's items)

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/items/inspect.py tests/items/test_attr_view.py
git commit -m "feat(items): view() surfaces the attribute vector, surface-until-revealed [attr-graph p2]"
```

---

### Task 4: end-to-end deception integration test + deploy

**Files:**
- Test: `tests/items/test_deception.py` (create)

**Interfaces:** consumes `compose`, `normalize`, `inspect`, `view` — the whole seam.

- [ ] **Step 1: Write the integration test**

```python
# tests/items/test_deception.py
from aidnd.items import inspect as item_inspect
from aidnd.items import normalize, view
from aidnd.items.model import Capability


def _forged_ring():
    """A gilded-brass ring passed off as gold: surface краса/ценность high, true low."""
    it = normalize({"kind": "trinket", "name": "перстень «под золото»", "form": "оправа",
                    "attrs": {"ценность": {"surface": 85, "true": 10},
                              "краса": {"surface": 80, "true": 40}}})
    it["id"] = "ring1"
    return it


def test_appraisal_deflates_a_forgery():
    it = _forged_ring()
    known = set()
    assert view(it, known)["worth_known"] is False
    surface_worth = view(it, known)["worth"]
    merchant = Capability(abilities={"int": 14}, competencies={"trade"})
    res = item_inspect(it, merchant, "appraise")
    known |= set(res["attr_groups"])                       # what the endpoint does
    v = view(it, known)
    assert v["worth_known"] is True and v["worth"] < surface_worth


def test_hidden_poison_surfaces_only_under_lore():
    it = normalize({"kind": "weapon", "name": "тонкий стилет", "form": "клинок",
                    "attrs": {"острота": {"surface": 70, "true": 70},
                              "скверна": {"surface": 0, "true": 65}}})
    it["id"] = "stiletto1"
    assert not [m for m in view(it, set())["mods"] if m["target"] == "special:poison"]
    sage = Capability(abilities={"int": 12}, competencies={"lore"})
    known = set(item_inspect(it, sage, "lore")["attr_groups"])
    assert [m for m in view(it, known)["mods"] if m["target"] == "special:poison"]
```

- [ ] **Step 2: Run + full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_deception.py -v` → PASS
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS

- [ ] **Step 3: Commit**

```bash
git add tests/items/test_deception.py
git commit -m "test(items): end-to-end attribute deception — forgery deflates on appraisal, poison hides until lore [attr-graph p2]"
```

- [ ] **Step 4: Deploy** (manual, after review): import smoke-test (`python -c "import aidnd.server.app"`), then `/deploy` — push origin main, VPS git-reset + restart `aidnd`, verify `/play`→303, `/`→200. No visible change (no live item has `attrs` yet); this keeps prod in sync.

## Self-review notes

- **Spec coverage:** U1 surface/true deception (Tasks 1,3,4); U4 "inspect reveals true attribute values, gate by via/competency" (Task 2). The `layer` reader the Phase-1 note promised is realized as the `known`-set parameter (more expressive: per-group, not a binary layer).
- **Design choices locked here (documented for the reviewer):** reveal granularity is per attribute *group* (phys/value/arcane) keyed by inspection `via`; a trained competency reveals at a glance, else appraise/lore roll vs a flat `_ATTR_DC=12` (gap-scaled difficulty is a future tuning knob); phys truth needs a craft competency (no layman roll). Deception needs no special "hidden mod" gating — a lie is just surface≠true (a poison sets surface `скверна`=0).
- **Backward safety:** `derive_effects(item)` default `known=None` = reality (Phase-1 unaffected); `view()` legacy branch byte-identical; no live item has `attrs`, so `_item_card`/combat/trade are unchanged in the running game.
- **Deferred:** combat and trade-price negotiation reading `derive_effects` (Phase 3); the catalog that actually forges attribute-bearing (and forged) items (Phase 4).
