"""REPLAY RECORDER — the game's own flight recorder.

Every player-visible line, exactly as play.html renders it, is appended live to a per-session text
file under ``data/playtest_logs/``. After any playtest or live session that file IS the full textual
replay of what the player saw: input echoes, narration, NPC replies, overheard speech/deeds, the
scene digest, combat log, contract resolutions and errors — in the same order the UI shows them.

Capture seam: a server-side response tap (HTTP middleware in ``server/app.py``) reads the JSON body
of the narrative ``/api/play/*`` endpoints and mirrors the frontend render functions here. No LLM,
best-effort (never raises into the request path), negligible cost (append + flush). Kill-switch:
``AIDND_NO_REPLAY=1``.

Key functions
-------------
record(wid, verb, req, resp, status) -> None : Tap one endpoint response; append its lines (safe).
format_lines(verb, req, resp, st) -> list[str] : Pure formatter — the UI-mirroring line block.
rotate(wid) -> None : Force a fresh replay file for wid on its next write (called on newworld).
"""

from __future__ import annotations

import datetime as _dt
import glob
import os

# Base directory for replay files. Module-level so tests can patch it to a tmp dir.
BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "playtest_logs")
)

# POST endpoints (verb = path after "/api/play/") whose responses render narrative to the thread.
# Everything that ticks the world or speaks a line; pure data/UI endpoints (map, inventory, journal,
# plan, wares, …) are deliberately excluded. GET "combat" is added separately (opens the combat view).
_NARR_POST = {
    "act", "say", "talk", "move", "enter", "exit", "room", "zone", "live", "look",
    "cast", "enchant", "learn", "use", "give", "loot", "inspect", "steal",
    "commission", "repair", "offer", "sell", "buy", "askkey", "sign_ack",
    "board_take", "delve", "ad_take", "contract_accept", "surrender", "watch_flee",
    "guild_redeem", "dungeon_move", "dungeon_loot", "dungeon_exit", "combat_act",
    "debug/skip", "market/buy", "market/sell",
}

# Short stage directions for actions the UI doesn't echo as player text (move/enter/…). The player's
# own typed input (act/say) is echoed verbatim instead — see _echo.
_STAGE = {
    "exit": "выхожу наружу",
    "look": "осматриваюсь",
    "cast": "рисую круг",
    "loot": "обыскиваю",
    "inspect": "разглядываю",
    "steal": "краду",
    "give": "отдаю",
    "delve": "спускаюсь в подземелье",
    "board_take": "беру дело с доски",
    "ad_take": "беру объявление",
    "contract_accept": "берусь за уговор",
    "surrender": "сдаюсь",
    "watch_flee": "бегу от стражи",
    "dungeon_move": "иду вглубь",
    "dungeon_loot": "обыскиваю",
    "dungeon_exit": "наружу",
    "debug/skip": "пропускаю время",
    "guild_redeem": "получаю награду в гильдии",
    "commission": "заказываю работу",
    "repair": "чиню",
    "enchant": "накладываю чары",
    "learn": "учу глиф",
}

_PHASE_RU = {"morning": "утро", "day": "день", "evening": "вечер", "night": "ночь"}


def should_tap(verb: str) -> bool:
    """Whether verb's response is narrative and worth buffering/parsing at all — the single source
    of truth shared by record() and the ASGI tap in server/app.py, which bails BEFORE draining the
    body/json-parsing for every polled non-narrative endpoint (map, inventory, journal, …)."""
    return verb in _NARR_POST or verb == "combat"


def _phase_ru(gt: int) -> str:
    h = (int(gt) // 60) % 24
    key = (
        "night" if h < 6 else "morning" if h < 11 else "day" if h < 17 else "evening" if h < 22
        else "night"
    )
    return _PHASE_RU[key]


class _WidState:
    """Per-world recorder state, kept for the life of the process."""

    def __init__(self) -> None:
        self.path: str | None = None
        self.header_written = False
        self.force_new = False
        self.last_gt: int | None = None
        self.combat_len = 0  # last-seen length of the combat log (dedup across ticks)
        self.had_combat = False  # was combat present on the previous response for this wid?


_STATES: dict[int, _WidState] = {}


def rotate(wid: int) -> None:
    """Start a fresh replay file for wid on its next write (called when a new world is created)."""
    st = _STATES.setdefault(int(wid), _WidState())
    st.path = None
    st.header_written = False
    st.force_new = True
    st.last_gt = None
    st.combat_len = 0
    st.had_combat = False


# ── pure formatting (unit-tested directly) ──────────────────────────────────────────────────────

def _clean_name(who) -> str:
    """Never leak a raw pool/bp/npc id as a speaker name (mirrors play.html npcMsg)."""
    s = str(who or "").strip()
    if not s or s.startswith(("pool:", "bp:", "npc:")):
        return "голос"
    return s


def _echo(verb: str, req: dict, resp: dict) -> str | None:
    """The player's input line, as the UI echoes it (act/say) or as a stage direction (move/…)."""
    if verb in ("act", "say"):
        t = str(req.get("text", "")).strip()
        return f"> {t}" if t else None
    if verb == "live":
        return None  # deferred crowd/NPC reactions — a continuation, no fresh input
    if verb == "talk":
        nm = _clean_name(resp.get("name") or req.get("npc"))
        return f"> [подхожу: {nm}]"
    if verb == "move":
        loc = resp.get("location") or {}
        dest = resp.get("moved") or loc.get("name") or req.get("to")
        return f"> [иду: {dest}]"
    if verb == "enter":
        loc = resp.get("location") or {}
        nm = loc.get("name") or (resp.get("enterable") or {}).get("name") or "внутрь"
        return f"> [вхожу: {nm}]"
    if verb == "room":
        kd = {"cellar": "подвал", "backroom": "задняя комната", "attic": "чердак",
              "quarters": "жильё", "hidden": "тайник"}
        room = req.get("room", "")
        return f"> [иду: {kd.get(room, room)}]"
    if verb == "zone":
        return f"> [осматриваю: зона {req.get('zid', '')}]"
    if verb == "combat_act":
        t = req.get("type", "")
        m = {"move": "шаг", "attack": "удар", "dodge": "защита", "flee": "бегство", "end": "конец хода"}
        return f"> [бой: {m.get(t, t)}]"
    if verb == "combat":
        return None  # opening the combat view — the log below speaks for itself
    stage = _STAGE.get(verb)
    return f"> [{stage}]" if stage else f"> [{verb}]"


def _resp_gt(resp: dict):
    gt = resp.get("gt")
    if gt is None and isinstance(resp.get("over"), dict):
        gt = resp["over"].get("gt")
    return gt


def _feed_lines(feed) -> list[str]:
    """Overheard speech + deeds, ordered most-hearable first (mirrors play.html pushFeed)."""
    arr = sorted(feed or [], key=lambda x: (x.get("tier", 1) if x.get("k") == "speech" else 9))
    out = []
    for f in arr:
        if f.get("k") == "speech":
            out.append(f"  · {_clean_name(f.get('who'))} → {f.get('to', '')}: «{f.get('text', '')}»")
        else:
            who = str(f.get("who") or "").strip()
            out.append(f"  · {who}: {f.get('text', '')}" if who else f"  · {f.get('text', '')}")
    return out


def format_lines(verb: str, req: dict, resp: dict, st: _WidState) -> list[str]:
    """Pure: the block of replay lines for one endpoint response, mirroring the UI render order.

    Order per turn: input echo → gt divider (on a >60-min jump) → narr → contract resolution →
    direct address → freeform reply → digest|feed → combat wrapup → combat-log delta → error.
    """
    lines: list[str] = []
    req = req or {}
    resp = resp or {}

    echo = _echo(verb, req, resp)
    if echo:
        lines.append(echo)

    # time divider — a jump > 60 min (sleep / skip) starts a new game-day beat
    gt = _resp_gt(resp)
    if gt is not None:
        try:
            gt = int(gt)
            if st.last_gt is not None and gt - st.last_gt > 60:
                lines.append(f"— gt {gt} · {_phase_ru(gt)} —")
            st.last_gt = gt
        except (TypeError, ValueError):
            pass

    for t in resp.get("narr") or []:
        lines.append(str(t))

    if resp.get("contract_done"):
        lines.append(str(resp["contract_done"]))

    for a in resp.get("address") or []:
        lines.append(f"{_clean_name(a.get('who') or a.get('npc'))} — тебе. {a.get('text', '')}")

    line = resp.get("line")
    if isinstance(line, dict) and line.get("text"):  # scene freeform single reply {who,text}
        lines.append(f"{_clean_name(line.get('who'))}. {line['text']}")
    elif isinstance(line, str) and line.strip():     # talk/say reply — speaker is the addressee
        # /say returns the fog-aware display name in line_who; fall back to «голос» only when
        # it is genuinely absent (a raw pool id in req.npc would leak, so never trust that alone)
        who = _clean_name(resp.get("line_who") or resp.get("name") or req.get("npc"))
        lines.append(f"{who}. {line.strip()}")

    if resp.get("digest"):
        lines.append(f"  ⋯ {resp['digest']}")
    else:
        lines.extend(_feed_lines(resp.get("feed")))

    over = resp.get("over")
    if isinstance(over, dict):
        for t in over.get("narr") or []:
            lines.append(str(t))
        death = over.get("death")
        if isinstance(death, dict):
            cause = death.get("cause", "")
            lines.append(f"  ! Смерть: {death.get('text', 'Тьма.')}"
                         + (f" ({cause})" if cause else ""))

    # combat log — emit only lines new since the last tick of THIS encounter
    cb = resp.get("combat")
    has_combat = isinstance(cb, dict) and isinstance(cb.get("log"), list)
    if has_combat:
        log = cb["log"]
        # a fresh encounter began if the log shrank, OR this is the first tick with combat present
        # since the last one without it (a new fight observed with log length >= the previous
        # fight's final length must not silently swallow its opening lines).
        if len(log) < st.combat_len or not st.had_combat:
            st.combat_len = 0
        for entry in log[st.combat_len:]:
            lines.append(f"  ⚔ {entry}")
        st.combat_len = len(log)
    st.had_combat = has_combat

    if resp.get("error"):
        lines.append(f"  ! {resp['error']}")

    return lines


# ── file plumbing (best-effort) ─────────────────────────────────────────────────────────────────

def _path_for(wid: int, st: _WidState) -> str:
    """Resolve (and remember) the replay file for wid: reuse the latest existing file for this world,
    unless a rotation was requested (newworld), in which case start a timestamped new one."""
    if st.path:
        return st.path
    os.makedirs(BASE_DIR, exist_ok=True)
    if not st.force_new:
        existing = sorted(glob.glob(os.path.join(BASE_DIR, f"replay-w{wid}-*.txt")))
        if existing:
            st.path = existing[-1]
            st.header_written = True  # append to an in-progress replay, no new header
            return st.path
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M")
    st.path = os.path.join(BASE_DIR, f"replay-w{wid}-{stamp}.txt")
    st.force_new = False
    return st.path


def record(wid, verb: str, req: dict | None, resp: dict | None, status: int = 200) -> None:
    """Tap one endpoint response and append its replay lines. Best-effort: never raises."""
    try:
        if os.environ.get("AIDND_NO_REPLAY") or wid is None:
            return
        wid = int(wid)
        if verb == "newworld":
            rotate(wid)
            return
        if not should_tap(verb):
            return
        st = _STATES.setdefault(wid, _WidState())
        lines = format_lines(verb, req or {}, resp or {}, st)
        if not lines:
            return
        path = _path_for(wid, st)
        with open(path, "a", encoding="utf-8") as fh:
            if not st.header_written:
                gt = _resp_gt(resp or {})
                when = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
                gt_note = f" · игровое время gt {int(gt)} ({_phase_ru(int(gt))})" if gt is not None else ""
                fh.write(f"# Реплей — мир {wid} · {when}{gt_note}\n\n")
                st.header_written = True
            fh.write("\n".join(lines) + "\n")
            fh.flush()
    except Exception:  # noqa: BLE001 — the recorder must never break gameplay
        pass
