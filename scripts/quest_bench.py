"""КВЕСТОВЫЙ БЕНЧ: постановка и выполнение (личная просьба · гильдия · сон · утро мира).

Гонит полный цикл против дев-сервера (живой LLM): вступление в гильдию и взятие заказа,
выпрашивание личной просьбы у жителей (talk→offer→accept), попытка закрыть шаг на месте
(deliver адресату в зале / bring из local ёмкости), сон до утра и утренняя жизнь доски/дел.
Ассерты — механические; отчёт markdown; ненулевой выход при провале критического.

Запуск: .venv/bin/python scripts/quest_bench.py [--base URL]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

CHECKS, LOG = [], []


def check(name, ok, detail="", critical=True):
    CHECKS.append((name, bool(ok), detail, critical))
    print(("  ✓ " if ok else ("  ✗ " if critical else "  ~ ")) + name +
          (f" — {detail}" if detail else ""))


def note(line):
    LOG.append(line)
    print("  ·", line)


def api(base, path, body=None, timeout=180):
    req = urllib.request.Request(
        base + path, data=(json.dumps(body or {}).encode() if body is not None else None),
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_text": raw}
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode() or "{}")
        except Exception:
            return {"error": f"http {e.code}"}
    except Exception as e:
        return {"error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8099")
    ap.add_argument("--out", default="data/debug/quest_bench.md")
    a = ap.parse_args()
    B = a.base
    api(B, "/api/play/debuglog/clear", {})

    sc = api(B, "/api/play/scene")
    for _ in range(3):
        if not sc.get("combat"):
            break
        api(B, "/api/play/watch_flee", {})
        sc = api(B, "/api/play/scene")
    coins0 = sc.get("coins")
    note(f"старт: gt={sc.get('gt')} coins={coins0} внутри={bool(sc.get('inside'))}")

    print("\n── ГИЛЬДИЯ ──")
    gb = api(B, "/api/play/board")
    check("Г1 гильдия отвечает и принимает (жетон)",
          bool(gb.get("guild")) and (gb.get("joined") or (gb.get("status") or {}).get("rank")),
          f"статус={gb.get('status')}")
    jobs = gb.get("jobs") or []
    check("Г2 на доске есть clear-заказы с CR/наградой",
          bool(jobs) and all("cr" in j and "reward" in j for j in jobs),
          f"заказов={len(jobs)}")
    took = {}
    cr_max = (gb.get("status") or {}).get("cr_max", 1.0)
    fit = [j for j in jobs if j["cr"] <= cr_max]
    if fit:
        took = api(B, "/api/play/board_take", {"id": min(fit, key=lambda x: x["cr"])["id"]})
        check("Г3 заказ по чину взят", took.get("taken") is True, str(took.get("error") or ""))
    elif jobs:                                       # по чину нет — гейт обязан отказать
        took = api(B, "/api/play/board_take", {"id": min(jobs, key=lambda x: x["cr"])["id"]})
        check("Г3 гейт рангов отказывает не по чину",
              bool(took.get("error")) and "чин" in str(took.get("error")),
              str(took.get("error") or ""))
    cts = api(B, "/api/play/contracts")
    actives = (cts.get("active") or cts.get("contracts") or
               (cts if isinstance(cts, list) else []))
    check("Г4 контракт гильдии в журнале (если заказ взят)",
          (not took.get("taken")) or (any((c.get("giver") == "guild") for c in actives)
                                      if isinstance(actives, list) else False),
          f"активных={len(actives) if isinstance(actives, list) else '?'}")

    print("\n── СОН (просьбы просят днём, не в час ночи) ──")
    gt0 = api(B, "/api/play/scene").get("gt") or 0
    slept = api(B, "/api/play/act", {"text": "Снимаю тюфяк на ночь и сплю до самого утра."})
    sc2 = api(B, "/api/play/scene")
    gt1 = sc2.get("gt") or 0
    check("С1 сон промотал время к утру",
          gt1 > gt0 and 5 * 60 <= (gt1 % 1440) <= 11 * 60,
          f"{gt0 % 1440 // 60:02d}:{gt0 % 60:02d} → {gt1 % 1440 // 60:02d}:{gt1 % 60:02d} · "
          f"narr={((slept.get('narr') or ['—'])[0])[:60]}")
    check("С2 сон восстановил силы", (sc2.get("hp") == sc2.get("max_hp")) if sc2.get("max_hp")
          else sc2.get("hp") is not None, f"hp={sc2.get('hp')}/{sc2.get('max_hp')}")
    api(B, "/api/play/live", {})

    print("\n── ЛИЧНАЯ ПРОСЬБА (утро) ──")
    sc = api(B, "/api/play/scene")
    if not sc.get("inside"):
        api(B, "/api/play/enter", {})
    api(B, "/api/play/look", {})
    api(B, "/api/play/look", {})
    sc = api(B, "/api/play/scene")
    here = [h for h in ((sc.get("location") or {}).get("here") or []) if h.get("id")]
    if not here:                                     # утро: люди на работах — ИДЁМ к ним
        if sc.get("inside"):
            api(B, "/api/play/exit", {})
        mp = api(B, "/api/play/map")
        keys = [k for k in (mp.get("keys") or []) if k.get("node") != mp.get("loc")]
        note("карта знает: " + ", ".join(k.get("label", "?") for k in (mp.get("keys") or []))
             + " (туман: рынок не открыт — идём к известному)")
        for k in keys[:2]:                           # столб на площади: прохожие + объявления
            mv = api(B, "/api/play/move", {"to": k["node"]})
            for _ in range(2):
                if not mv.get("stopped"):
                    break
                mv = api(B, "/api/play/move", {"to": mv.get("remaining", k["node"])})
            api(B, "/api/play/look", {})
            sc = api(B, "/api/play/scene")
            ads = sc.get("board_ads") or []
            if ads:
                note("столб: объявления горожан: " + "; ".join(
                    f"{a.get('giver_name')}: {a.get('kind')} {a.get('want') or a.get('target_name')}"
                    f" за {a.get('reward') or a.get('reward_name')}" for a in ads[:3]))
                check("Д1 столб живёт: объявления валидны (гивер/вид/цель/награда)",
                      all(a.get("giver_name") and a.get("kind") for a in ads), f"ads={len(ads)}",
                      critical=False)
            here = [h for h in ((sc.get("location") or {}).get("here") or []) if h.get("id")]
            if not here:                             # подождать прохожих пару тиков
                for _ in range(2):
                    api(B, "/api/play/live", {})
                api(B, "/api/play/look", {})
                sc = api(B, "/api/play/scene")
                here = [h for h in ((sc.get("location") or {}).get("here") or []) if h.get("id")]
            note(f"у «{k['label']}»: душ рядом {len(here)}")
            if here:
                break
    check("Л0 люди рядом утром (зал/улица/площадь)", bool(here), f"душ={len(here)}",
          critical=False)
    offer, giver = None, None
    for h in here[:4]:
        t = api(B, "/api/play/talk", {"npc": h["id"]})
        if t.get("contract"):
            offer, giver = t["contract"], h["id"]
            break
    if offer:
        steps = offer.get("steps") or [offer]
        kinds = [st.get("kind") for st in steps]
        note(f"просьба от {offer.get('giver_name')}: {kinds} — «{(offer.get('pitch') or '')[:90]}» "
             f"награда={offer.get('reward')}{' (вещь: ' + str(offer.get('reward_name')) + ')' if offer.get('reward_item') else ''}")
        check("Л1 просьба валидна (виды шагов из словаря, награда есть)",
              all(k in ("bring", "deliver", "visit", "befriend", "dead") for k in kinds)
              and (offer.get("reward") or offer.get("reward_item")),
              f"шаги={kinds}")
        acc = api(B, "/api/play/contract_accept", {"id": offer.get("id")})
        check("Л2 уговор принят (offered→active)", acc.get("accepted") is True,
              str(acc.get("error") or ""))
        # попытка закрыть ПЕРВЫЙ шаг не сходя с места
        cur = steps[0]
        done = None
        if cur.get("kind") == "deliver" and acc.get("note"):
            tgt = cur.get("target")
            if any(h["id"] == tgt for h in here):
                inv = api(B, "/api/play/inventory")
                iid = next((i.get("id") for i in (inv.get("items") or [])
                            if cur.get("want", "") in (i.get("name") or "")), None)
                if iid:
                    done = api(B, "/api/play/give", {"npc": tgt, "item": iid})
        if done is not None:
            check("Л3 шаг deliver закрыт фактом мира (вручил адресату)",
                  bool(done.get("contract_done") or any("исполнил" in (n or "")
                       for n in (done.get("narr") or []))),
                  str((done.get("narr") or [""])[0])[:80], critical=False)
        else:
            note(f"первый шаг «{cur.get('kind')}: {cur.get('want') or cur.get('target_name')} "
                 f"({cur.get('where')})» требует похода — фиксируем постановку")
    else:
        check("Л1 хоть один житель предложил просьбу", False,
              "4 talk — без офферов (агенды/coffer?)", critical=False)

    print("\n── УТРО МИРА ──")
    gb2 = api(B, "/api/play/board")
    jobs2 = gb2.get("jobs") or []
    note(f"доска утром: заказов={len(jobs2)} (было {len(jobs)})")
    check("У1 мир живёт без игрока: NPC закрывают заказы ИЛИ доска пополняется",
          len(jobs2) != len(jobs), f"{len(jobs)}→{len(jobs2)}", critical=False)
    dd = api(B, "/api/play/deeds").get("deeds") or []
    note("дела мира: " + "; ".join(f"{d['verb']}({d['actor']}→{d.get('obj', '')})" for d in dd[:6]))
    check("У2 NPC-зачистки пишутся ДЕЛАМИ (deed clear)",
          any(d["verb"] == "clear" for d in dd), f"дел={len(dd)}", critical=False)

    fails = [c for c in CHECKS if not c[1] and c[3]]
    soft = [c for c in CHECKS if not c[1] and not c[3]]
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("# Квестовый бенч\n\n| проверка | итог | детали |\n|---|---|---|\n")
        for name, ok, det, crit in CHECKS:
            f.write(f"| {name} | {'✓' if ok else ('✗' if crit else '~')} | {det} |\n")
        f.write("\n## Хроника\n\n" + "\n".join(f"- {line}" for line in LOG) + "\n")
    print(f"\nитог: {len(CHECKS) - len(fails) - len(soft)} ✓ · {len(soft)} ~ · {len(fails)} ✗ → {a.out}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
