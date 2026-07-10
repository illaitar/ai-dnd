# Item attribute graph — Phase 1 (the model foundation) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the canonical attribute layer for items — a curated attribute vocabulary, an authored materials/forms/treatments graph, deterministic composition (composition → attribute vector), and effect derivation (attribute vector → game mods) — all pure and unit-tested, with **no consumer touched yet** so the full suite stays green.

**Architecture:** New pure module `aidnd.items.attrs` holds the graph loader, `compose()`, and `derive_effects()`. The attribute vocabulary `ATTRS` lives in `aidnd.items.model` (alongside `KINDS`/`SLOTS`); `normalize()` gains `attrs`/`parts`/`form` fields (additive — legacy items normalize unchanged). Graph data is `aidnd/items/attrgraph.json`. Effect coefficients live in an `attrs.py` module-level `DEFAULT_RULES` (the pure-module-owns-its-constants exception; a `PB` override seam is deferred to Phase 3, when the play layer first calls `derive_effects`).

**Tech Stack:** Python 3.14, pytest.

## Global Constraints

- **No hardcoded gameplay numbers in play-layer code.** Attribute contributions/deltas live in `attrgraph.json` (data). Effect-rule coefficients live in `attrs.py`'s `DEFAULT_RULES` — permitted because `aidnd.items.attrs` is a pure, standalone-testable module (same exception as `convo.py`). No balance number is authored by an LLM.
- **Attributes are intrinsic; the form gates effects, not the vector.** `compose()` uses materials + treatments only (no form term). `derive_effects()` is where the form gates which effects express. (This refines the spec's U2 wording, which mentioned form-weighting in composition — we keep attributes intrinsic and put all form logic in derivation. Flagged for the reviewer.)
- **Additive only in Phase 1.** Do not modify `inspect`/`view`/combat/worth or any consumer. `normalize()` only *adds* keys; every existing field stays byte-identical.
- **Full suite green** before finishing each task: `uv run pytest /Users/nik/Desktop/dnd-ai/tests` (ABSOLUTE path — the shell CWD drifts).
- Spec: [docs/superpowers/specs/2026-07-10-item-attribute-graph-design.md](../specs/2026-07-10-item-attribute-graph-design.md). This plan implements **increment step 1** of that spec ("Model + graph data + composition math + `derive_effects` + pure tests").

---

### Task 1: attribute vocabulary + graph data + loader

**Files:**
- Modify: `src/aidnd/items/model.py` (add `ATTRS` tuple)
- Create: `src/aidnd/items/attrgraph.json` (materials / forms / treatments)
- Create: `src/aidnd/items/attrs.py` (graph loader)
- Test: `tests/items/test_attrs.py` (create)

**Interfaces:**
- Produces: `aidnd.items.model.ATTRS: tuple[str, ...]` — the 13 attribute keys.
- Produces: `aidnd.items.attrs.attr_graph() -> dict` — cached `{materials, forms, treatments}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/items/test_attrs.py
from aidnd.items.attrs import attr_graph
from aidnd.items.model import ATTRS


def test_attrs_vocabulary_is_13():
    assert len(ATTRS) == 13
    assert "мана" in ATTRS and "чара" in ATTRS and "острота" in ATTRS


def test_graph_loads_and_references_only_known_attrs():
    g = attr_graph()
    assert g["materials"] and g["forms"] and g["treatments"]
    for _m, contrib in g["materials"].items():
        assert set(contrib) <= set(ATTRS), f"unknown attr in material {_m}: {set(contrib) - set(ATTRS)}"
    for _t, delta in g["treatments"].items():
        assert set(delta) <= set(ATTRS), f"unknown attr in treatment {_t}"
    for _f, spec in g["forms"].items():
        for _eff, attrs in spec.get("expresses", {}).items():
            assert set(attrs) <= set(ATTRS), f"unknown attr in form {_f}/{_eff}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attrs.py -v`
Expected: FAIL — `ImportError` (`attrs` module / `ATTRS` not defined).

- [ ] **Step 3: Add `ATTRS` to `model.py`**

In `src/aidnd/items/model.py`, after the `COMPETENCIES = (...)` line (near line 31), add:

```python
# ATTRIBUTES: intrinsic physical properties (0–100), the canonical center of the item model.
# Composition (materials+treatments) feeds them; effects derive from them (see aidnd.items.attrs).
ATTRS = ("острота", "твёрдость", "прочность", "вес", "гибкость", "краса", "ценность",
         "чара", "мана", "святость", "скверна", "теплостойкость", "точность")
```

- [ ] **Step 4: Create `attrgraph.json`**

Create `src/aidnd/items/attrgraph.json`:

```json
{
  "materials": {
    "сталь":         {"твёрдость": 70, "острота": 65, "прочность": 70, "вес": 60, "теплостойкость": 60},
    "железо":        {"твёрдость": 55, "острота": 45, "прочность": 60, "вес": 62, "теплостойкость": 55},
    "серебро":       {"краса": 80, "ценность": 75, "чара": 55, "святость": 60, "твёрдость": 30, "вес": 58},
    "золото":        {"краса": 85, "ценность": 90, "чара": 40, "вес": 75, "твёрдость": 20},
    "дуб":           {"прочность": 55, "вес": 45, "гибкость": 30, "теплостойкость": 20},
    "кожа":          {"гибкость": 70, "прочность": 40, "вес": 20},
    "кость":         {"твёрдость": 45, "острота": 40, "прочность": 45, "вес": 35},
    "лён":           {"гибкость": 75, "вес": 10, "прочность": 25},
    "лунный камень": {"чара": 70, "мана": 60, "краса": 65, "ценность": 55}
  },
  "forms": {
    "клинок":  {"kind": "weapon",     "expresses": {"attack": ["острота", "твёрдость", "точность"]}},
    "топор":   {"kind": "weapon",     "expresses": {"attack": ["твёрдость", "вес", "острота"]}},
    "рукоять": {"kind": "misc",       "expresses": {}},
    "древко":  {"kind": "misc",       "expresses": {}},
    "щит":     {"kind": "armor",      "expresses": {"defense": ["твёрдость", "прочность"]}},
    "доспех":  {"kind": "armor",      "expresses": {"defense": ["твёрдость", "прочность", "гибкость"]}},
    "оправа":  {"kind": "trinket",    "expresses": {}},
    "сосуд":   {"kind": "consumable", "expresses": {}}
  },
  "treatments": {
    "закалка":   {"твёрдость": 12, "гибкость": -8},
    "заточка":   {"острота": 15},
    "золочение": {"краса": 18, "ценность": 20},
    "чернение":  {"краса": 6, "теплостойкость": 4},
    "полировка": {"краса": 10, "острота": 4},
    "освящение": {"святость": 25},
    "отрава":    {"скверна": 30},
    "зарядка":   {"мана": 25}
  }
}
```

- [ ] **Step 5: Create `attrs.py` with the loader**

Create `src/aidnd/items/attrs.py`:

```python
"""Attribute graph: materials/forms/treatments → intrinsic attribute vector → derived effects.
Pure & deterministic; code owns the math. Composition = materials (max per attr) + treatment deltas,
quality-scaled, clamped 0–100. derive_effects projects the TRUE vector (form-gated) into game mods.

Key functions
-------------
attr_graph() -> dict : Load/cache the authored materials/forms/treatments graph.
compose(parts, quality) -> dict : Composition → {attr:int} true vector (0–100).
derive_effects(item, rules) -> dict : Attribute vector + form → {mods, worth, durability}.
"""

from __future__ import annotations

import json
import os

from .model import ATTRS

_GRAPH = None
_GPATH = os.path.join(os.path.dirname(__file__), "attrgraph.json")


def attr_graph() -> dict:
    global _GRAPH
    if _GRAPH is None:
        with open(_GPATH, encoding="utf-8") as f:
            _GRAPH = json.load(f)
    return _GRAPH
```

- [ ] **Step 6: Run tests + full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attrs.py -v` → PASS
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/items/model.py src/aidnd/items/attrgraph.json src/aidnd/items/attrs.py tests/items/test_attrs.py
git commit -m "feat(items): attribute vocabulary + materials/forms/treatments graph + loader [attr-graph p1]"
```

---

### Task 2: composition — materials + treatments → attribute vector

**Files:**
- Modify: `src/aidnd/items/attrs.py` (add `QUALITY_MUL`, `_clamp`, `compose`)
- Test: `tests/items/test_attrs.py` (extend)

**Interfaces:**
- Consumes: `attr_graph()` (Task 1).
- Produces: `compose(parts, quality="plain", graph=None) -> dict[str,int]` — true vector; `parts` is `[{"role":str,"material":str,"treatments":[str]}]`. Per attribute, the strongest contributing part wins (`max`); treatment deltas sum; result quality-scaled and clamped 0–100; zero/absent attrs omitted.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/items/test_attrs.py
from aidnd.items.attrs import compose

KNIFE = [{"role": "клинок", "material": "сталь", "treatments": ["заточка"]},
         {"role": "рукоять", "material": "дуб", "treatments": []}]


def test_compose_knife_expresses_steel_and_wood():
    a = compose(KNIFE, "plain")
    assert a["острота"] == 65 + 15          # steel 65 + hone 15
    assert a["твёрдость"] == 70             # from steel blade
    assert a["прочность"] == 70             # max(steel 70, oak 55)
    assert a["вес"] == 60                   # max(steel 60, oak 45)


def test_temper_raises_hardness_lowers_flex():
    plain = compose([{"role": "клинок", "material": "кожа", "treatments": []}], "plain")
    tempered = compose([{"role": "клинок", "material": "кожа", "treatments": ["закалка"]}], "plain")
    assert tempered["твёрдость"] > plain.get("твёрдость", 0)
    assert tempered.get("гибкость", 0) < plain["гибкость"]   # кожа гибкость 70 → 62


def test_quality_scales_the_vector():
    crude = compose(KNIFE, "crude")
    exq = compose(KNIFE, "exquisite")
    assert exq["острота"] > crude["острота"]


def test_clamp_ceiling_at_100():
    a = compose([{"role": "оправа", "material": "золото", "treatments": ["золочение"]}], "exquisite")
    assert a["ценность"] <= 100
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attrs.py -k compose -v`
Expected: FAIL — `compose` not defined (ImportError).

- [ ] **Step 3: Implement `compose`**

In `src/aidnd/items/attrs.py`, after `attr_graph()`, add:

```python
QUALITY_MUL = {"crude": 0.85, "plain": 1.0, "fine": 1.12, "exquisite": 1.25}


def _clamp(v) -> int:
    return max(0, min(100, int(round(v))))


def compose(parts, quality: str = "plain", graph: dict | None = None) -> dict:
    """parts=[{role,material,treatments[]}] → {attr:int} true vector (0–100). Strongest part wins
    per attribute (max); treatment deltas sum; quality-scaled; clamped; zero attrs omitted."""
    g = graph or attr_graph()
    mats, treats = g["materials"], g["treatments"]
    acc: dict = {}
    for part in parts or []:
        for a, v in mats.get(part.get("material", ""), {}).items():
            acc[a] = max(acc.get(a, 0), v)                 # the sharpest/hardest part defines the attr
    for part in parts or []:
        for t in part.get("treatments") or []:
            for a, dv in treats.get(t, {}).items():
                acc[a] = acc.get(a, 0) + dv
    mul = QUALITY_MUL.get(quality, 1.0)
    return {a: _clamp(v * mul) for a, v in acc.items() if a in ATTRS and _clamp(v * mul) > 0}
```

- [ ] **Step 4: Run tests + full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attrs.py -v` → PASS
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/items/attrs.py tests/items/test_attrs.py
git commit -m "feat(items): compose() — materials+treatments → quality-scaled attribute vector [attr-graph p1]"
```

---

### Task 3: `derive_effects` — attribute vector + form → game mods

**Files:**
- Modify: `src/aidnd/items/attrs.py` (add `DEFAULT_RULES`, `FOCUS_FORMS`, `_band`, `_score`, `derive_effects`)
- Test: `tests/items/test_attrs.py` (extend)

**Interfaces:**
- Consumes: `attr_graph()`, an item dict shaped `{"attrs": {a:{"surface":int,"true":int}}, "form": str, "kind": str}`.
- Produces: `derive_effects(item, rules=None) -> {"mods":[...], "worth":int, "durability":dict|None}`. Reads **true** attribute values. `attack`/`defense` only when the item's `form` expresses them; `appearance`/`worth`/`poison`/`mana`/`durability` computed for any form (mana only for `consumable` kind or a focus form). Mods shaped like `norm_mod` inputs: `{target, op, amount, when[, hidden]}`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/items/test_attrs.py
from aidnd.items.attrs import derive_effects


def _item(attrs, form="клинок", kind="weapon"):
    return {"attrs": {a: {"surface": v, "true": v} for a, v in attrs.items()}, "form": form, "kind": kind}


def test_sharp_blade_yields_attack():
    eff = derive_effects(_item({"острота": 80, "твёрдость": 70, "точность": 50}, "клинок", "weapon"))
    atk = [m for m in eff["mods"] if m["target"] == "attack"]
    assert atk and atk[0]["amount"] >= 2


def test_same_attrs_as_shield_yield_no_attack():
    eff = derive_effects(_item({"острота": 80, "твёрдость": 70, "прочность": 65}, "щит", "armor"))
    assert not [m for m in eff["mods"] if m["target"] == "attack"]
    assert [m for m in eff["mods"] if m["target"] == "defense"]


def test_beauty_yields_appearance_and_worth():
    eff = derive_effects(_item({"краса": 90, "ценность": 80}, "оправа", "trinket"))
    assert [m for m in eff["mods"] if m["target"] == "social:appearance"]
    assert eff["worth"] > 0


def test_toxic_is_hidden_and_mana_focus():
    poison = derive_effects(_item({"скверна": 60}, "клинок", "weapon"))
    pm = [m for m in poison["mods"] if m["target"] == "special:poison"]
    assert pm and pm[0]["hidden"] is True
    mana = derive_effects(_item({"мана": 70}, "оправа", "trinket"))
    assert [m for m in mana["mods"] if m["target"] == "special:mana"]


def test_derive_reads_true_not_surface():
    forged = {"attrs": {"ценность": {"surface": 90, "true": 5}}, "form": "оправа", "kind": "trinket"}
    honest = {"attrs": {"ценность": {"surface": 90, "true": 90}}, "form": "оправа", "kind": "trinket"}
    assert derive_effects(forged)["worth"] < derive_effects(honest)["worth"]


def test_durability_from_integrity():
    eff = derive_effects(_item({"прочность": 80}, "клинок", "weapon"))
    assert eff["durability"] and eff["durability"]["max"] >= 4
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attrs.py -k derive -v`
Expected: FAIL — `derive_effects` not defined.

- [ ] **Step 3: Implement `derive_effects`**

In `src/aidnd/items/attrs.py`, after `compose`, add:

```python
# Effect-rule coefficients — code owns the math (pure module; PB override seam lands in Phase 3).
DEFAULT_RULES = {
    "attack":     {"w": {"острота": 0.5, "твёрдость": 0.3, "точность": 0.2},
                   "bands": [(80, 3), (60, 2), (40, 1)], "when": "equipped"},
    "defense":    {"w": {"твёрдость": 0.6, "прочность": 0.4},
                   "bands": [(80, 3), (60, 2), (40, 1)], "when": "equipped"},
    "appearance": {"attr": "краса", "bands": [(88, 3), (70, 2), (45, 1)],
                   "target": "social:appearance", "when": "worn"},
    "poison":     {"attr": "скверна", "bands": [(75, 3), (50, 2), (20, 1)],
                   "target": "special:poison", "when": "on_use"},
    "mana":       {"attr": "мана", "bands": [(75, 3), (50, 2), (25, 1)], "target": "special:mana"},
    "worth":      {"w": {"ценность": 0.6, "краса": 0.25, "чара": 0.15}, "k": 0.6, "min": 1},
    "durability": {"attr": "прочность", "k": 0.5, "min": 4},
}
FOCUS_FORMS = ("оправа", "посох", "жезл", "амулет", "талисман")


def _true(attrs: dict, a: str) -> int:
    return int((attrs.get(a) or {}).get("true", 0))


def _band(v: float, bands: list) -> int:
    for thr, amt in bands:                                 # bands ordered high→low
        if v >= thr:
            return amt
    return 0


def _score(attrs: dict, w: dict) -> float:
    return sum(_true(attrs, a) * k for a, k in w.items())


def derive_effects(item: dict, rules: dict | None = None) -> dict:
    """Attribute TRUE vector + form → {mods, worth, durability}. Form gates attack/defense."""
    r = rules or DEFAULT_RULES
    attrs = item.get("attrs") or {}
    form = item.get("form") or ""
    kind = item.get("kind") or ""
    expresses = ((attr_graph()["forms"].get(form) or {}).get("expresses")) or {}
    mods: list = []
    for key in ("attack", "defense"):                      # form-gated combat effects
        if key in expresses:
            amt = _band(_score(attrs, r[key]["w"]), r[key]["bands"])
            if amt:
                mods.append({"target": key, "op": "add", "amount": amt, "when": r[key]["when"]})
    ap = r["appearance"]                                    # universal: appearance
    amt = _band(_true(attrs, ap["attr"]), ap["bands"])
    if amt:
        mods.append({"target": ap["target"], "op": "add", "amount": amt, "when": ap["when"]})
    po = r["poison"]                                        # universal: toxicity (hidden)
    amt = _band(_true(attrs, po["attr"]), po["bands"])
    if amt:
        mods.append({"target": po["target"], "op": "add", "amount": amt, "when": po["when"], "hidden": True})
    mn = r["mana"]                                          # mana: focus (equipped) or consumable (on_use)
    amt = _band(_true(attrs, mn["attr"]), mn["bands"])
    if amt and (kind == "consumable" or form in FOCUS_FORMS):
        mods.append({"target": mn["target"], "op": "add", "amount": amt,
                     "when": "on_use" if kind == "consumable" else "equipped"})
    wr = r["worth"]
    worth = max(wr["min"], round(_score(attrs, wr["w"]) * wr["k"]))
    du = r["durability"]
    pr = _true(attrs, du["attr"])
    durability = {"max": max(du["min"], round(pr * du["k"]))} if pr else None
    return {"mods": mods, "worth": worth, "durability": durability}
```

- [ ] **Step 4: Run tests + full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attrs.py -v` → PASS
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/items/attrs.py tests/items/test_attrs.py
git commit -m "feat(items): derive_effects() — attribute vector + form → game mods (code owns the math) [attr-graph p1]"
```

---

### Task 4: model integration — `attrs`/`parts`/`form` on the factsheet + exports

**Files:**
- Modify: `src/aidnd/items/model.py` (add `norm_attr_vector`, `norm_parts`; extend `normalize`)
- Modify: `src/aidnd/items/__init__.py` (export `ATTRS`, `attr_graph`, `compose`, `derive_effects`)
- Test: `tests/items/test_attr_model.py` (create)

**Interfaces:**
- Consumes: `ATTRS` (Task 1).
- Produces: `normalize(d)` output gains three keys — `"form": str`, `"parts": [{"role","material","treatments"}]`, `"attrs": {a:{"surface":int,"true":int}}` — additively. Legacy dicts (no attrs/parts/form) yield `form=""`, `parts=[]`, `attrs={}` with every existing field unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/items/test_attr_model.py
from aidnd.items import compose, derive_effects, normalize
from aidnd.items.attrs import attr_graph  # noqa: F401  (ensures export path is wired)


def test_normalize_passes_attrs_parts_form():
    it = normalize({
        "kind": "weapon", "name": "стальной нож", "form": "клинок",
        "parts": [{"role": "клинок", "material": "сталь", "treatments": ["заточка"]}],
        "attrs": {"острота": {"surface": 80, "true": 80}, "нет-такого": {"true": 5}},
    })
    assert it["form"] == "клинок"
    assert it["parts"][0]["material"] == "сталь"
    assert "острота" in it["attrs"] and "нет-такого" not in it["attrs"]   # unknown attr dropped
    assert it["attrs"]["острота"] == {"surface": 80, "true": 80}


def test_normalize_clamps_and_defaults_surface_to_true():
    it = normalize({"attrs": {"твёрдость": {"true": 150}, "краса": 40}})
    assert it["attrs"]["твёрдость"]["true"] == 100                        # clamped
    assert it["attrs"]["краса"] == {"surface": 40, "true": 40}            # scalar → surface==true


def test_legacy_item_unchanged():
    it = normalize({"kind": "weapon", "name": "ржавый нож", "worth": 3, "mods": []})
    assert it["attrs"] == {} and it["parts"] == [] and it["form"] == ""
    assert it["name"] == "ржавый нож" and it["kind"] == "weapon" and it["worth"] == 3


def test_compose_feeds_derive_via_normalize():
    parts = [{"role": "клинок", "material": "сталь", "treatments": ["заточка", "закалка"]}]
    vec = compose(parts, "fine")
    it = normalize({"kind": "weapon", "form": "клинок", "parts": parts,
                    "attrs": {a: {"surface": v, "true": v} for a, v in vec.items()}})
    eff = derive_effects(it)
    assert [m for m in eff["mods"] if m["target"] == "attack"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attr_model.py -v`
Expected: FAIL — `normalize` output lacks `form`/`parts`/`attrs` (KeyError), and `compose`/`derive_effects` not exported from `aidnd.items`.

- [ ] **Step 3: Add `norm_attr_vector` + `norm_parts` to `model.py`**

In `src/aidnd/items/model.py`, after `norm_durability` (near line 96), add:

```python
def _clamp100(v) -> int:
    return max(0, min(100, _num(v, 0)))


def norm_attr_vector(a) -> dict:
    """{attr: int | {surface,true}} → {attr: {surface:int, true:int}}. Unknown attrs dropped,
    values clamped 0–100; a scalar means surface == true (honest)."""
    if not isinstance(a, dict):
        return {}
    out = {}
    for k, v in a.items():
        if k not in ATTRS:
            continue
        if isinstance(v, dict):
            t = _clamp100(v.get("true", v.get("surface", 0)))
            s = _clamp100(v.get("surface", t))
        else:
            t = s = _clamp100(v)
        out[k] = {"surface": s, "true": t}
    return out


def norm_parts(p) -> list:
    out = []
    for part in (p if isinstance(p, list) else []):
        if not isinstance(part, dict) or not str(part.get("material") or "").strip():
            continue
        out.append({"role": str(part.get("role") or "").strip(),
                    "material": str(part["material"]).strip(),
                    "treatments": _list(part.get("treatments"))})
    return out
```

- [ ] **Step 4: Extend `normalize` to emit the three keys**

In `src/aidnd/items/model.py`, inside the `normalize` return dict (after the `"make": ...` line, near line 116), add these three keys:

```python
        "make": (d.get("make") if isinstance(d.get("make"), dict) else None),
        "form": str(d.get("form") or "").strip(),
        "parts": norm_parts(d.get("parts")),
        "attrs": norm_attr_vector(d.get("attrs")),
    }
```

(Keep every other key exactly as-is — this is purely additive.)

- [ ] **Step 5: Export the new surface from `__init__.py`**

In `src/aidnd/items/__init__.py`, add an import and extend `__all__`:

```python
from .attrs import attr_graph, compose, derive_effects
from .model import ATTRS, Capability, normalize, rarity_price
```

and add `"ATTRS", "attr_graph", "compose", "derive_effects"` to the `__all__` list.

- [ ] **Step 6: Run tests + full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/items/test_attr_model.py -v` → PASS
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS (additive change; no consumer touched)

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/items/model.py src/aidnd/items/__init__.py tests/items/test_attr_model.py
git commit -m "feat(items): attrs/parts/form on the factsheet + package exports [attr-graph p1]"
```

---

## Self-review notes

- **Spec coverage (increment step 1):** attribute vocabulary (T1), graph data (T1), composition math (T2), `derive_effects` (T3), model carrying attrs/parts/form (T4), pure tests throughout. Inspection-on-attrs, consumer conversion, and the catalog/migration are **later phases** (own plans) — deliberately out of scope here to keep the suite green.
- **Deferred by design:** the `PB` override of `DEFAULT_RULES` (lands when the play layer first calls `derive_effects`, Phase 3); surface/true deception is *representable* now (T4) and *revealed* in Phase 2 (inspection rewrite); `derive_effects` returns a `durability.max` only — the wear/break loop is Phase 3+.
- **Type consistency:** `compose` returns `{attr:int}`; `derive_effects` consumes `{attr:{surface,true}}` (an item's stored form) and reads `true`; `normalize` produces that stored form. The T4 `test_compose_feeds_derive_via_normalize` exercises the seam end-to-end.
- **Refinement flagged for the reviewer:** attributes are intrinsic — `compose` has no form term; all form logic lives in `derive_effects`. This is a deliberate, documented departure from the spec's U2 phrasing.
