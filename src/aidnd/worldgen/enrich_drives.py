"""Pass B of NPC entity enrichment (docs/superpowers/specs/
2026-07-15-npc-entity-enrichment-design.md §3.6, §4.1) — the ONE LLM-batch slice: `mech.drives`.

Every other slice (§3.1-3.5, §3.7-3.9) is cheap derived Pass A (`enrich_pool.py`, no LLM). Drives are
different: `persona.{wants,fears,secret}` are free RU prose the player never sees structured — only an
LLM call can distill "накопить на нож" into `{kind:wealth, target:"нож получше", amount:15, intensity:0.5}`
that `plan_agenda` (`llm_agent.py:305`) can cast straight into an `Agenda`/`Milestone`. A role-table (Pass
A discipline) can't read prose; that's why this is the one field with a batch pass, mirroring
`peoplegen.py`'s persona forge (same `character_writer` role, same ThreadPoolExecutor/resume pattern).

Dependents (`mech.dependent`) are skipped — they carry no agenda (§4.1: "~900 calls, not 1354").

No offline fallback (project rule): unparseable/no-model → `LLMBadOutput`/`LLMUnavailable` propagate to
the caller, which logs and SKIPS that row — no stub drives are ever written. A skipped row simply has no
`mech.drives` and is picked up again by `--resume`.

Key functions
-------------
DriveCtx : Context for one NPC's drive distillation (id/name/role + persona prose).
build_ctx(row) -> DriveCtx : Extract the drive-relevant persona slice from a pool row.
eligible_rows(store, resume) -> list[dict] : Adult rows to process (optionally skip already-drived).
normalize_drives(data) -> list[dict] | None : Validate/clamp raw LLM JSON into the §3.6 schema.
DrivesEnricher : Abstract base; subclasses implement derive(ctx) -> list[dict].
LLMDrives(manager) : Runtime enricher — one `character_writer` call per NPC.
StubDrives : Test-only enricher; deterministic, no LLM call.
write_drives(store, row, drives) -> None : Persist `mech.drives` for one row (additive JSON key).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..inference import LLMBadOutput

DRIVE_KINDS = ("wealth", "craft", "courtship", "revenge", "status", "faith", "escape")
MAX_DRIVES = 3


@dataclass
class DriveCtx:
    id: str
    name: str
    role: str
    wants: list = field(default_factory=list)
    fears: list = field(default_factory=list)
    secret: dict | None = None
    background: list = field(default_factory=list)


_DRIVES_SYS = (
    "Ты — аналитик мотивов NPC для тёмно-фэнтезийного фронтирного городка (D&D). По краткой заготовке "
    "человека (роль, стремления, страхи, тайна) выдели ЕГО ГЛАВНЫЕ движущие устремления — СТРУКТУРИРОВАННО, "
    "не прозой. Верни ТОЛЬКО JSON:\n"
    "drives — массив из 1-3 объектов {kind, target, amount, intensity}:\n"
    "kind (СТРОГО один из: wealth|craft|courtship|revenge|status|faith|escape) — тип устремления: "
    "wealth — жажда денег/имущества; craft — амбиция в ремесле/мастерстве; courtship — влечение к "
    "конкретному человеку; revenge — месть за обиду; status — власть/положение/признание; faith — "
    "религиозное рвение/служение; escape — бегство от места/жизни/долга.\n"
    "target — КОРОТКАЯ строка на РУССКОМ: имя/pid человека, место или вещь, к которой устремление "
    "направлено (бери из wants/fears/secret буквально, не выдумывай нового);\n"
    "amount — целое число (только для kind=wealth — сумма в монетах, которую хочет накопить/добыть; "
    "для остальных kind ПОЛЕ НЕ ВОЗВРАЩАЙ или null);\n"
    "intensity — число 0.0-1.0 — насколько сильно это устремление владеет человеком (тайна и застарелые "
    "обиды — обычно выше 0.6; мимолётные желания — ниже 0.4).\n"
    "Бери ТОЛЬКО то, что реально читается в заготовке — не сочиняй устремлений с нуля. Если человек мелок "
    "и невзрачен, 1 слабый drive — нормально. НЕ добавляй пояснений вне JSON."
)


def _parse_json(text: str | None):
    if not text:
        return None
    t = re.sub(r"```$", "", re.sub(r"^```(?:json)?", "", text.strip()).strip()).strip()
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        # fallback: extract the outermost {...} or [...] — deepseek sometimes wraps a bare
        # drives array, or the object, in stray prose despite the "ТОЛЬКО JSON" instruction.
        starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
        ends = [j for j in (t.rfind("}"), t.rfind("]")) if j != -1]
        if starts and ends:
            i, j = min(starts), max(ends)
            if i < j:
                try:
                    return json.loads(t[i:j + 1])
                except (json.JSONDecodeError, ValueError):
                    return None
    return None


def _clamp01(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        v = 0.5
    return round(max(0.0, min(1.0, v)), 2)


def normalize_drives(data) -> list[dict] | None:
    """Validate raw LLM JSON into the §3.6 schema. None on unusable/empty output (→ LLMBadOutput).

    Accepts either the requested `{"drives": [...]}` shape or a bare top-level array — deepseek
    occasionally drops the wrapper object despite the prompt; the item-level schema is still
    validated strictly either way.
    """
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data.get("drives")
    else:
        return None
    if not isinstance(raw, list):
        return None
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        target = str(item.get("target") or "").strip()
        if kind not in DRIVE_KINDS or not target:
            continue
        drive = {"kind": kind, "target": target, "intensity": _clamp01(item.get("intensity", 0.5))}
        if kind == "wealth" and item.get("amount") is not None:
            try:
                drive["amount"] = max(0, int(item["amount"]))
            except (TypeError, ValueError):
                pass
        out.append(drive)
        if len(out) >= MAX_DRIVES:
            break
    return out or None


def build_ctx(row: dict) -> DriveCtx:
    """Extract the drive-relevant persona slice from a pool row (pure)."""
    mech = row.get("mech") or {}
    persona = row.get("persona") or {}
    secret = persona.get("secret") if isinstance(persona.get("secret"), dict) else None
    return DriveCtx(id=row["id"], name=row.get("name") or "", role=mech.get("role") or row.get("role") or "горожанин",
                    wants=list(persona.get("wants") or []), fears=list(persona.get("fears") or []),
                    secret=secret, background=list(persona.get("background") or []))


def eligible_rows(store, resume: bool = False) -> list[dict]:
    """Adult pool rows (dependents carry no agenda — skipped). resume=True skips rows already drived."""
    rows = store.list_people(limit=100000)
    out = []
    for row in rows:
        mech = row.get("mech") or {}
        if mech.get("dependent"):
            continue
        if resume and mech.get("drives"):
            continue
        out.append(row)
    return out


class DrivesEnricher:
    def derive(self, ctx: DriveCtx) -> list[dict]:
        raise NotImplementedError


class StubDrives(DrivesEnricher):
    """Tests only (runtime never builds) — deterministic, no LLM call."""

    def derive(self, ctx: DriveCtx) -> list[dict]:
        target = (ctx.wants[0] if ctx.wants else ctx.fears[0] if ctx.fears else "лучшая доля")
        return [{"kind": "wealth", "target": target, "amount": 10, "intensity": 0.5}]


class LLMDrives(DrivesEnricher):
    """Real runtime path: character_writer role, one call per NPC, strict JSON contract."""

    def __init__(self, manager):
        self.manager = manager

    def derive(self, ctx: DriveCtx) -> list[dict]:
        secret_line = ""
        if ctx.secret:
            secret_line = f" тайна: {ctx.secret.get('what', '')}"
        user = (f"Заготовка NPC «{ctx.name}», роль «{ctx.role}». "
                f"стремления: {', '.join(ctx.wants) or '—'}; "
                f"страхи: {', '.join(ctx.fears) or '—'};"
                f"{secret_line}. "
                f"Выдели 1-3 структурированных устремления (drives) этого человека.")
        resp = self.manager.call("character_writer",
                                 [{"role": "system", "content": _DRIVES_SYS},
                                  {"role": "user", "content": user}], options={"temperature": 0.4})
        drives = normalize_drives(_parse_json(resp.get("content")))
        if not drives:
            raise LLMBadOutput(f"character_writer: drives не разобраны ({ctx.name})")
        return drives


def write_drives(store, row: dict, drives: list) -> None:
    """Persist `mech.drives` for one row — additive JSON key, same accessor Pass A uses."""
    mech = dict(row.get("mech") or {})
    mech["drives"] = drives
    store.save_person(row["id"], row["role"], row["name"], row["charisma"], row["appearance"],
                      mech, row["persona"], row["portraits"], row["seed"])
