"""СЦЕНАРНЫЙ БЕНЧ живой сцены (docs/locations.md, кейсы 1/4/5/12 + дирижёр) — живой LLM.

Гонит сессию в таверне против дев-сервера (AIDND_OPEN_PLAY, deepseek), затем разбирает
СТРУКТУРНЫЙ лог сцены (aidnd.scene из data/debug/play.log) и ленту — и проверяет
механическими ассертами. Отчёт — markdown; ненулевой код выхода при провале.

Запуск:  .venv/bin/python scripts/scene_bench.py [--base http://127.0.0.1:8099] [--ticks 8]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request

CHECKS = []            # (имя, ok, детали)


def check(name: str, ok: bool, detail: str = ""):
    CHECKS.append((name, ok, detail))
    print(("  ✓ " if ok else "  ✗ ") + name + (f" — {detail}" if detail else ""))


def api(base, path, body=None, timeout=90):
    req = urllib.request.Request(
        base + path, data=(json.dumps(body or {}).encode() if body is not None else None),
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_text": raw}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8099")
    ap.add_argument("--ticks", type=int, default=8)
    ap.add_argument("--out", default="data/debug/scene_bench.md")
    a = ap.parse_args()

    api(a.base, "/api/play/debuglog/clear", {})
    sc = api(a.base, "/api/play/scene")
    for _ in range(3):                                      # выбраться из застрявшего боя
        if not sc.get("combat"):
            break
        api(a.base, "/api/play/watch_flee", {})
        sc = api(a.base, "/api/play/scene")
    if not sc.get("inside"):
        api(a.base, "/api/play/enter", {})
    api(a.base, "/api/play/look", {})

    feeds, addresses = [], []
    for _i in range(a.ticks):
        r = api(a.base, "/api/play/live", {})
        feeds += r.get("feed") or []
        addresses += r.get("address") or []
        time.sleep(0.2)

    # молчание: если было обращение — молчим тик и смотрим реакцию (кейс 2 мягко)
    api(a.base, "/api/play/live", {})

    log = api(a.base, "/api/play/debuglog").get("_text", "")
    ticks = re.findall(r"ТИК (\d+) .*? LLM-актёров=(\d+)", log)
    debts = re.findall(r"▸ (\S+ \S+) \[[^\]]*\] зона=(\S[^ ]*).*?имп=[\d.]+\(долг ответа\)"
                       r".*?actions: (.*?)(?:\n|$)", log, re.S)
    say_frags = [f for f in feeds if f.get("k") == "speech" and "краем уха" in (f.get("text") or "")]
    say_full = [f for f in feeds if f.get("k") == "speech" and "краем уха" not in (f.get("text") or "")]
    bg_lines = [f for f in feeds if "занят" in (f.get("text") or "")]

    print("\n── ПРОВЕРКИ ──")
    # Д1: дирижёр — не все думают; актёров/тик в [1..кэп], в среднем меньше душ
    acts = [int(n) for _t, n in ticks]
    check("Д1 дирижёр: LLM-актёров/тик 1..8 и не «все всегда»",
          bool(acts) and all(1 <= x <= 8 for x in acts) and (min(acts) < 8 or len(set(acts)) > 1),
          f"актёры по тикам: {acts}")
    # Д2: фоновые живут (занятия в ленте)
    check("Д2 фон: занятия без LLM видны в ленте", len(bg_lines) > 0, f"{len(bg_lines)} строк")
    # К4: долги в основном гасятся репликой (осознанное уклонение — легально по характеру)
    paid = sum(1 for _nm, _z, actions in debts if "say" in actions)
    check("К4 вопрос→ответ: ≥50% долгов гасятся репликой (уклонение — характер, не молчание)",
          bool(debts) and paid * 2 >= len(debts), f"долгов={len(debts)}, отвечено={paid}")
    # К5: слышимость — чужие зоны обрывками
    check("К5 слух: реплики чужих зон — «краем уха» обрывками",
          len(say_frags) > 0, f"обрывков={len(say_frags)}, полных(своя зона/адресные)={len(say_full)}")
    # К1: обращения к игроку не роятся и не дублируются
    sigs = [frozenset(re.findall(r"\w{4,}", (ad.get("text") or "").lower())[:5]) for ad in addresses]
    dup = sum(1 for i, s1 in enumerate(sigs) for s2 in sigs[i + 1:] if len(s1 & s2) >= 4)
    check("К1 чужак: обращений ≤ 1/тик в среднем и без дублей-приветствий",
          len(addresses) <= max(2, a.ticks // 2) and dup == 0,
          f"обращений={len(addresses)}, дублей={dup}")
    # К12: работник держит пост (РАБ из сборки остаётся в своей зоне)
    m = re.search(r"• (\S+ \S+) \[([^\]]+)\] \(РАБ\) → (\S[^|]*?) \|", log)
    if m:
        nm_, _role, zone0 = m.group(1), m.group(2), m.group(3).strip()
        moves = re.findall(rf"[▸·] (?:фон )?{re.escape(nm_)} \[[^\]]*\] зона=([^\s]+)", log)
        stayed = all(zone0.startswith(z.rstrip('.…')) or z.startswith(zone0[:6]) for z in moves) \
            if moves else True
        check("К12 пост: работник не покидает пост-зону", stayed,
              f"{nm_}: {zone0} → {sorted(set(moves))[:4]}")
    else:
        check("К12 пост: работник заведения на посту в рабочую фазу", False,
              "ИЗВЕСТНЫЙ БАГ МИРА: рутина не держит владельца на посту вечером (society)")
    # Р: разговоры существуют
    convs = re.findall(r"разговоров=(\d+)", log)
    check("Р разговор-объект: беседы живут в сцене",
          any(int(c) > 0 for c in convs), f"по тикам: {convs}")

    fails = [c for c in CHECKS if not c[1]]
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("# Сценарный бенч\n\n| проверка | итог | детали |\n|---|---|---|\n")
        for name, ok, det in CHECKS:
            f.write(f"| {name} | {'✓' if ok else '✗'} | {det} |\n")
        f.write(f"\nадресаций: {len(addresses)} · feed: {len(feeds)} строк\n")
    print(f"\nитог: {len(CHECKS) - len(fails)}/{len(CHECKS)} ок → {a.out}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
