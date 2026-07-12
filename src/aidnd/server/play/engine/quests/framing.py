"""FRAMING — the two LLM seams (spec §3/§5 Steps 3-4).
  judge(...)  — ONE ranking call: K seeds as plain-Russian evidence + personas → {rank,veto,why}.
  framer(...) — 3 written artifacts (pitch / foreshadow / reveal) + a structural apophenia validator.
No LLM → honest absence (parse failure → empty / None; LLMUnavailable propagates to the morning hook).
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger("aidnd.quests")

_JUDGE_SYS = (
    "Ты — редактор городских слухов. Оцени зёрна сюжета на живость и вкус; наложи вето на те, "
    "что звучат фальшиво; каждому дай ОДНУ фразу «чем цепляет». Верни СТРОГО JSON: "
    '{"rank": ["<sid>", ...], "veto": ["<sid>", ...], '
    '"why": {"<sid>": "<одна фраза>", ...}}. Только перечисленные sid, ничего не выдумывай.'
)


def render_evidence(seed: dict, deeds: dict, names: dict) -> str:
    """One seed → plain-Russian header (only evidence facts + personas, no predicates leak)."""
    gv = seed["giver_name"]
    vil = names.get(seed["cast"].get("villain"), "кто-то")
    prize = names.get(seed["cast"].get("prize"))
    head = f"{seed['sid']} [{seed['pattern']}]: {gv} против {vil}"
    head += f" (речь о {prize})." if prize else "."
    facts = []
    for i in seed.get("evidence", []):
        d = deeds.get(i)
        if not d:
            continue
        what = d.get("data", {}).get("what") or d.get("verb")
        facts.append(f"{names.get(d.get('actor'), 'кто-то')}: {what}")
    return head + ("\n  Факты: " + "; ".join(facts) if facts else "")


def judge(seeds: list, deeds: dict, names: dict, manager) -> list[dict]:
    if manager is None:
        return []
    for s in seeds:
        s.setdefault("sid", f"seed_{s['giver'].split(':')[-1]}_{s['pattern']}")
    payload = "\n".join(render_evidence(s, deeds, names) for s in seeds)
    resp = manager.call("narrator",
                        [{"role": "system", "content": _JUDGE_SYS},
                         {"role": "user", "content": payload}],
                        options={"temperature": 0.4})
    t = (resp.get("content") if resp else "") or ""
    try:
        d = json.loads(t[t.find("{"): t.rfind("}") + 1])
        rank, veto, why = list(d["rank"]), set(d.get("veto") or []), dict(d.get("why") or {})
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        log.warning("quests: judge вернул неразборный JSON — предложения нет этим утром")
        return []
    by_sid = {s["sid"]: s for s in seeds}
    kept = []
    for sid in rank:
        s = by_sid.get(sid)
        if not s or sid in veto:
            continue
        s["why"] = str(why.get(sid, ""))[:160]
        kept.append(s)
    return kept
