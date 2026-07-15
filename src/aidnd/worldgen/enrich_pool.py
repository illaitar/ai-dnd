"""Pass A of NPC entity enrichment — cheap, deterministic, no LLM.

Seeds the structured «D» slices of the enriched entity (docs/superpowers/specs/
2026-07-15-npc-entity-enrichment-design.md §3): the two extra traits (empathy,
vengefulness), the full worldview lens (faith/morals/taboos/mood), allegiances,
social standing, competencies (skills), kin + sampled relationships, economic
role, and a perception baseline. All values are derived from the row already in
the bank (role + 11 traits + abilities + charisma/appearance + household links),
so ONE offline pass lights up every downstream consumer without any LLM call.

Discipline mirrors `abilities.py` / `seed_races.py`: RNG keyed per-pid
(`random.Random(f"enrich|{pid}")`) so output is stable across runs and pool
order. Idempotent — re-running overwrites the same `mech.*` keys, never
duplicates. Only `mech` grows (additive JSON keys); persona/portraits/columns
are re-saved verbatim.

Key functions
-------------
enrich_pool(store, dry_run) -> int : Enrich every pool row; returns rows written.
enrich_person(row, index) -> dict : Derive the enriched `mech` for one row (pure).
build_index(rows) -> _PoolIndex : Households + sorted adult ids (shared context).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# ── vocabularies (RU) ──────────────────────────────────────────────────────
LIGHT_DEITIES = ("Светлая-Мать", "Кузнец-под-горой", "Серый-Странник", "Владыка-Костей")
CULT_DEITIES = ("Багровый", "Тень-Безымянная")
MATERIALS = ("металл", "кожа", "дерево", "ткань", "камень")
TABOO_VOCAB = ("убийство", "воровство", "кощунство", "людоедство",
               "клятвопреступление", "осквернение-мёртвых", "кровосмешение")
DEPENDENT_ROLES = ("дитя", "старик")

# role → primary deity leaning: weights over the pantheon (+ "нет" = irreligious)
_DEITY_WEIGHTS = {
    "жрец":       {"Светлая-Мать": 5, "Кузнец-под-горой": 2, "Серый-Странник": 1, "Владыка-Костей": 1},
    "знахарка":   {"Светлая-Мать": 4, "Владыка-Костей": 2, "нет": 1},
    "кузнец":     {"Кузнец-под-горой": 5, "Светлая-Мать": 1, "нет": 2},
    "оружейник":  {"Кузнец-под-горой": 4, "Багровый": 1, "нет": 2},
    "бродяга":    {"Серый-Странник": 4, "нет": 3, "Багровый": 1},
    "головорез":  {"нет": 4, "Багровый": 3, "Тень-Безымянная": 1, "Владыка-Костей": 1},
    "стражник":   {"Светлая-Мать": 3, "Кузнец-под-горой": 1, "нет": 2},
    "трактирщик": {"Светлая-Мать": 2, "Серый-Странник": 2, "нет": 3},
    "лавочник":   {"Серый-Странник": 2, "Светлая-Мать": 2, "нет": 3},
    "бард":       {"Серый-Странник": 3, "Светлая-Мать": 1, "нет": 3},
    "мельник":    {"Светлая-Мать": 3, "Кузнец-под-горой": 1, "нет": 3},
    "дубильщик":  {"Кузнец-под-горой": 2, "Светлая-Мать": 1, "нет": 3},
    "сапожник":   {"Кузнец-под-горой": 2, "Светлая-Мать": 1, "нет": 3},
    "горожанин":  {"Светлая-Мать": 3, "Серый-Странник": 1, "Кузнец-под-горой": 1, "нет": 3},
    "дитя":       {"Светлая-Мать": 3, "нет": 4},
    "старик":     {"Владыка-Костей": 2, "Светлая-Мать": 3, "нет": 3},
}
_DEITY_DEFAULT = {"Светлая-Мать": 3, "Серый-Странник": 1, "нет": 4}

# role → base empathy / vengefulness (nudged by traits + noise)
_EMPATHY_BASE = {
    "жрец": .78, "знахарка": .80, "трактирщик": .60, "бард": .55, "сапожник": .55,
    "горожанин": .50, "кузнец": .50, "мельник": .50, "стражник": .50, "лавочник": .45,
    "дубильщик": .45, "бродяга": .30, "головорез": .20, "дитя": .62, "старик": .60,
}
_VENGE_BASE = {
    "головорез": .70, "бродяга": .55, "стражник": .45, "кузнец": .50, "лавочник": .50,
    "бард": .50, "мельник": .50, "дубильщик": .50, "сапожник": .45, "трактирщик": .45,
    "горожанин": .45, "знахарка": .35, "жрец": .30, "дитя": .35, "старик": .50,
}

# role → primary allegiance (group, kind, role-in-group)
_ROLE_ALLEG = {
    "кузнец":     ("гильдия-кузнецов", "guild", "member"),
    "оружейник":  ("гильдия-кузнецов", "guild", "member"),
    "стражник":   ("стража", "watch", "member"),
    "жрец":       ("храм-Светлой-Матери", "temple", "member"),
    "знахарка":   ("храм-Светлой-Матери", "temple", "client"),
    "лавочник":   ("купеческая-ложа", "guild-mercantile", "member"),
    "трактирщик": ("купеческая-ложа", "guild-mercantile", "member"),
    "мельник":    ("купеческая-ложа", "guild-mercantile", "client"),
    "бард":       ("гильдия-искателей", "guild", "client"),
    "головорез":  ("шайка-оврага", "gang", "member"),
    "бродяга":    ("шайка-оврага", "gang", "initiate"),
}

# role → social rank (raised to «зажиточный» by high visible wealth)
_ROLE_RANK = {
    "головорез": "отребье", "бродяга": "отребье",
    "горожанин": "простолюдин", "мельник": "простолюдин", "дитя": "простолюдин",
    "старик": "простолюдин",
    "кузнец": "ремесленник", "лавочник": "ремесленник", "трактирщик": "ремесленник",
    "дубильщик": "ремесленник", "сапожник": "ремесленник", "бард": "ремесленник",
    "стражник": "служилый", "жрец": "духовенство", "знахарка": "духовенство",
}
_ROLE_NOTORIETY = {"головорез": .38, "бард": .32, "бродяга": .26, "жрец": .18,
                   "стражник": .15, "знахарка": .14, "трактирщик": .12}

# role → combat / literacy bumps and craft material
_ROLE_COMBAT = {"стражник": .32, "головорез": .38, "наёмник": .32, "охотник": .24,
                "кузнец": .12, "бродяга": .12, "дубильщик": .06,
                "дитя": -.20, "старик": -.18}
_ROLE_LITERACY = {"писец": .55, "жрец": .45, "бард": .35, "лавочник": .35,
                  "трактирщик": .20, "стражник": .14, "знахарка": .18,
                  "бродяга": -.10, "головорез": -.10, "дитя": -.25, "старик": -.05}
_ROLE_CRAFT = {"кузнец": ("металл", .72), "оружейник": ("металл", .74),
               "дубильщик": ("кожа", .66), "сапожник": ("кожа", .60)}

# role → economy (produces, output_rate, wage, consumes, self_sufficient)
_ROLE_ECONOMY = {
    "кузнец":     ("подковы", .50, None, ["хлеб", "эль"], False),
    "оружейник":  ("клинки", .45, None, ["хлеб", "эль"], False),
    "трактирщик": ("эль", .60, None, ["хлеб", "мясо"], False),
    "мельник":    ("мука", .58, None, ["зерно"], False),
    "лавочник":   (None, .42, None, ["хлеб", "эль"], False),
    "дубильщик":  ("кожа", .48, None, ["хлеб"], False),
    "сапожник":   ("обувь", .46, None, ["хлеб"], False),
    "жрец":       (None, .05, 2, ["хлеб"], False),
    "знахарка":   ("снадобья", .40, None, ["хлеб"], False),
    "стражник":   (None, .0, 3, ["хлеб", "эль"], False),
    "бард":       (None, .30, None, ["эль", "хлеб"], False),
    "бродяга":    (None, .10, None, ["хлеб"], False),
    "головорез":  (None, .20, None, ["хлеб", "эль"], False),
    "горожанин":  ("хлеб", .32, None, ["эль"], True),
}
_ROLE_VIGILANCE = {"стражник": .26, "охотник": .22, "головорез": .12, "бродяга": .12,
                   "лавочник": .08, "трактирщик": .06, "дитя": -.12, "старик": -.10}

# sampled-rel kinds → weight band (−1..+1); seeds day-0 social fabric
_REL_KINDS = {
    "rival":   (-0.50, -0.30),
    "enemy":   (-0.85, -0.60),
    "debtor":  (-0.30, -0.15),
    "creditor": (-0.30, -0.15),
    "patron":  (0.18, 0.35),
    "beloved": (0.50, 0.72),
}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _clamp1(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _wsample(rng: random.Random, weights: dict) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


@dataclass
class _PoolIndex:
    """Shared context derived once per run — households (real kin) + adult id list."""
    households: dict = field(default_factory=dict)      # head pid → [dependent pids]
    dep_head: dict = field(default_factory=dict)        # dependent pid → head pid
    adult_ids: list = field(default_factory=list)       # sorted adult pids (for sampling)
    adult_pos: dict = field(default_factory=dict)       # pid → index in adult_ids


def build_index(rows: list) -> _PoolIndex:
    idx = _PoolIndex()
    for r in rows:
        mech = r.get("mech") or {}
        if mech.get("dependent"):
            head = mech.get("head")
            if head:
                idx.households.setdefault(head, []).append(r["id"])
                idx.dep_head[r["id"]] = head
        else:
            idx.adult_ids.append(r["id"])
    idx.adult_ids.sort()
    idx.adult_pos = {pid: i for i, pid in enumerate(idx.adult_ids)}
    return idx


def _surname(name: str) -> str:
    parts = (name or "").split()
    return " ".join(parts[1:]) if len(parts) > 1 else ""


# ── per-slice derivation ───────────────────────────────────────────────────
def _traits2(role: str, t: dict, rng: random.Random) -> tuple[float, float]:
    """empathy, vengefulness — role base nudged by the existing 11 traits."""
    malice = t.get("malice", 0.5)
    loyalty = t.get("loyalty", 0.5)
    honesty = t.get("honesty", 0.5)
    pride = t.get("pride", 0.5)
    irrit = t.get("irritability", 0.5)
    empathy = _clamp(_EMPATHY_BASE.get(role, 0.5)
                     - (malice - 0.5) * 0.30 + (loyalty - 0.5) * 0.20
                     + rng.uniform(-0.07, 0.07))
    venge = _clamp(_VENGE_BASE.get(role, 0.45)
                   + (malice - 0.5) * 0.25 + (pride - 0.5) * 0.20
                   + (irrit - 0.5) * 0.20 - (honesty - 0.5) * 0.20
                   + rng.uniform(-0.07, 0.07))
    return round(empathy, 2), round(venge, 2)


def _worldview(role: str, t: dict, race: str, rng: random.Random) -> dict:
    deity = _wsample(rng, _DEITY_WEIGHTS.get(role, _DEITY_DEFAULT))
    # a small cult minority beyond role leanings (forbidden faiths hide among the poor)
    if deity == "нет" and role not in ("жрец", "знахарка") and rng.random() < 0.05:
        deity = rng.choice(CULT_DEITIES)
    if deity == "нет":
        devotion = round(_clamp(rng.uniform(0.0, 0.08)), 2)
    elif role == "жрец":
        devotion = round(_clamp(0.80 + rng.uniform(-0.10, 0.15)), 2)
    elif deity in CULT_DEITIES:
        devotion = round(_clamp(0.55 + rng.uniform(-0.15, 0.25)), 2)
    else:
        devotion = round(_clamp(0.32 + rng.uniform(-0.20, 0.30)), 2)

    malice = t.get("malice", 0.5)
    bravery = t.get("bravery", 0.5)
    honesty = t.get("honesty", 0.5)
    lawful = t.get("lawful", 0.5)
    loyalty = t.get("loyalty", 0.5)
    socia = t.get("sociability", 0.5)
    curio = t.get("curiosity", 0.5)
    irrit = t.get("irritability", 0.5)
    cult = deity in CULT_DEITIES

    role_violence = {"головорез": .35, "стражник": .12, "жрец": -.45, "знахарка": -.40,
                     "дитя": -.30, "старик": -.15}.get(role, -.10)
    violence = _clamp1((malice - 0.5) * 1.2 + (bravery - 0.5) * 0.4
                       + role_violence + (0.4 if cult else 0.0))
    theft = _clamp1(-(honesty - 0.5) * 1.6 - (lawful - 0.5) * 0.6)
    authority = _clamp1((lawful - 0.5) * 1.4 + (loyalty - 0.5) * 0.6
                        + {"стражник": .3, "головорез": -.3, "бродяга": -.3}.get(role, 0.0))
    outsiders = _clamp1((socia - 0.5) * 1.2 + (0.10 if race and race != "человек" else 0.0)
                        - {"головорез": .2, "бродяга": .1}.get(role, 0.0))
    magic = _clamp1((curio - 0.5) * 1.2 - 0.15
                    + (devotion * 0.4 if deity == "Кузнец-под-горой" else 0.0)
                    + (0.3 if cult else 0.0))
    role_death = {"головорез": .50, "знахарка": .30, "стражник": .18, "жрец": -.30,
                  "дитя": -.30, "старик": .10}.get(role, -.20)
    death = _clamp1(role_death + (malice - 0.5) * 0.4
                    + (0.35 if deity in ("Владыка-Костей", "Багровый") else 0.0))

    morals = {"violence": round(violence, 2), "theft": round(theft, 2),
              "authority": round(authority, 2), "outsiders": round(outsiders, 2),
              "magic": round(magic, 2), "death": round(death, 2)}

    taboos = []
    if not cult:
        taboos.append("людоедство")
        taboos.append("кровосмешение")
        if violence < -0.25:
            taboos.append("убийство")
        if theft < -0.25:
            taboos.append("воровство")
        if devotion > 0.45:
            taboos.append("кощунство")
        if honesty > 0.60 or lawful > 0.60:
            taboos.append("клятвопреступление")
        if death < 0.0 or deity == "Владыка-Костей":
            taboos.append("осквернение-мёртвых")
    # dedupe, keep vocab order
    taboos = [tb for tb in TABOO_VOCAB if tb in set(taboos)]

    mood = _clamp1((socia - 0.5) * 0.8 - (irrit - 0.5) * 0.8 + rng.uniform(-0.10, 0.10))
    return {"faith": {"deity": deity, "devotion": devotion}, "morals": morals,
            "taboos": taboos, "mood_baseline": round(mood, 2)}


def _allegiances(role: str, name: str, deity: str, rng: random.Random) -> list:
    out = []
    prim = _ROLE_ALLEG.get(role)
    if prim:
        group, kind, grole = prim
        if grole == "member" and rng.random() < 0.12:
            grole = "leader"
        standing = round(_clamp({"leader": 0.85, "member": 0.45,
                                 "initiate": 0.20, "client": 0.15}.get(grole, 0.3)
                                + rng.uniform(-0.08, 0.10)), 2)
        out.append({"group": group, "kind": kind, "role": grole, "standing": standing})
    if deity == "Багровый":
        out.append({"group": "культ-Багрового", "kind": "cult",
                    "role": "initiate" if rng.random() < 0.7 else "member",
                    "standing": round(_clamp(0.2 + rng.uniform(0.0, 0.3)), 2)})
    sur = _surname(name)
    if sur:
        out.append({"group": f"клан-{sur}", "kind": "clan", "role": "member",
                    "standing": round(_clamp(0.3 + rng.uniform(-0.1, 0.2)), 2)})
    return out


def _standing(role: str, appearance: float, rng: random.Random) -> dict:
    rank = _ROLE_RANK.get(role, "простолюдин")
    if rank in ("простолюдин", "ремесленник") and appearance >= 0.5:
        rank = "зажиточный"
    noto = _clamp(_ROLE_NOTORIETY.get(role, 0.05) + rng.uniform(-0.03, 0.05))
    return {"rank": rank, "notoriety": round(noto, 2)}


def _skills(role: str, ab: dict, t: dict, devotion: float, rng: random.Random) -> dict:
    def n(k):  # ability 6..17 → 0..1
        return _clamp((ab.get(k, 10) - 6) / 11.0)
    phys = (n("str") + n("dex") + n("con")) / 3.0
    combat = _clamp(0.15 + phys * 0.40 + (t.get("bravery", 0.5) - 0.5) * 0.30
                    + _ROLE_COMBAT.get(role, 0.0), 0.02, 1.0)
    literacy = _clamp(n("int") * 0.5 + _ROLE_LITERACY.get(role, 0.0))
    magic = _clamp(n("int") * 0.25 + (t.get("curiosity", 0.5) - 0.5) * 0.3
                   + devotion * 0.25 - 0.22, 0.0, 1.0)
    craft = {}
    cm = _ROLE_CRAFT.get(role)
    if cm:
        mat, base = cm
        craft[mat] = round(_clamp(base + rng.uniform(-0.08, 0.08)), 2)
    return {"combat": round(combat, 2), "craft": craft,
            "magic": round(magic, 2), "literacy": round(literacy, 2)}


def _economy(role: str) -> dict:
    e = _ROLE_ECONOMY.get(role)
    if not e:
        return {}
    produces, rate, wage, consumes, ss = e
    return {"produces": produces, "output_rate": rate, "wage": wage,
            "consumes": list(consumes), "self_sufficient": ss}


def _perception(role: str, ab: dict, rng: random.Random) -> dict:
    wisn = _clamp((ab.get("wis", 10) - 6) / 11.0)
    vig = _clamp(0.30 + wisn * 0.5 + _ROLE_VIGILANCE.get(role, 0.0)
                 + rng.uniform(-0.05, 0.05))
    return {"vigilance": round(vig, 2)}


def _rels(pid: str, role: str, is_dep: bool, idx: _PoolIndex, rng: random.Random) -> list:
    rels: list = []
    seen: set = set()

    def add(other, kind, weight):
        if other and other != pid and other not in seen:
            seen.add(other)
            rels.append({"other": other, "kind": kind, "weight": round(weight, 2)})

    # kin — REAL household edges (head ↔ dependents, siblings within a household)
    if is_dep:
        head = idx.dep_head.get(pid)
        add(head, "kin", 0.55)
        for sib in idx.households.get(head, []):
            add(sib, "kin", 0.45)
    else:
        for dep in idx.households.get(pid, []):
            add(dep, "kin", 0.55)

    # sampled ties (adults only) — deterministic neighbours in the id-cluster window
    if not is_dep and idx.adult_ids:
        pos = idx.adult_pos.get(pid, 0)
        lo, hi = max(0, pos - 15), min(len(idx.adult_ids), pos + 16)
        window = [q for q in idx.adult_ids[lo:hi] if q != pid and q not in seen]
        rng.shuffle(window)
        # rougher roles carry more (and more hostile) ties
        kinds = ["rival", "debtor", "creditor", "patron", "beloved"]
        if role in ("головорез", "бродяга"):
            kinds = ["enemy", "rival", "rival", "debtor", "creditor"]
        elif role in ("жрец", "знахарка"):
            kinds = ["patron", "beloved", "creditor", "debtor"]
        n = rng.choices([1, 2, 3], weights=[3, 4, 3])[0]
        for other in window[:n]:
            kind = rng.choice(kinds)
            lo_w, hi_w = _REL_KINDS[kind]
            add(other, kind, rng.uniform(lo_w, hi_w))
    return rels


def enrich_person(row: dict, idx: _PoolIndex) -> dict:
    """Return the enriched `mech` dict for one pool row (pure; deterministic per pid)."""
    pid = row["id"]
    mech = dict(row.get("mech") or {})
    persona = row.get("persona") or {}
    role = mech.get("role") or row.get("role") or "горожанин"
    is_dep = bool(mech.get("dependent"))
    race = persona.get("race") or "человек"
    rng = random.Random(f"enrich|{pid}")

    t = dict(mech.get("traits") or {})
    ab = mech.get("abilities") or {}
    empathy, venge = _traits2(role, t, rng)
    t["empathy"] = empathy
    t["vengefulness"] = venge
    mech["traits"] = t

    wv = _worldview(role, t, race, rng)
    mech["worldview"] = wv
    deity = wv["faith"]["deity"]
    devotion = wv["faith"]["devotion"]
    mech["allegiances"] = _allegiances(role, row.get("name") or "", deity, rng)
    mech["standing"] = _standing(role, float(row.get("appearance") or 0.2), rng)
    mech["skills"] = _skills(role, ab, t, devotion, rng)
    mech["perception"] = _perception(role, ab, rng)
    mech["rels"] = _rels(pid, role, is_dep, idx, rng)
    # dependents witness events (worldview/traits) but earn nothing → empty economy
    mech["economy"] = {} if is_dep else _economy(role)
    return mech


def enrich_pool(store, dry_run: bool = False) -> int:
    """Enrich every pool row in-place. dry_run → print 3 samples, write nothing.

    Returns the number of rows that would be / were written.
    """
    rows = store.list_people(limit=100000)
    idx = build_index(rows)
    written = 0
    samples = []
    for row in rows:
        mech = enrich_person(row, idx)
        if dry_run:
            if len(samples) < 3:
                samples.append((row["id"], row["role"], mech))
            written += 1
            continue
        store.save_person(row["id"], row["role"], row["name"], row["charisma"],
                          row["appearance"], mech, row["persona"], row["portraits"],
                          row["seed"])
        written += 1
    if dry_run:
        import json
        for pid, role, mech in samples:
            print(f"\n=== {pid} ({role}) ===")
            for key in ("worldview", "skills", "allegiances", "standing",
                        "perception", "economy"):
                print(f"  {key}: {json.dumps(mech.get(key), ensure_ascii=False)}")
            print(f"  traits.empathy={mech['traits'].get('empathy')} "
                  f"vengefulness={mech['traits'].get('vengefulness')}")
            print(f"  rels: {json.dumps(mech.get('rels'), ensure_ascii=False)}")
    return written
