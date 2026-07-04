"""Плейтест-2: глубокие поверхности — длинный диалог, сплетни, ночь, эксперт-осмотр,
крафт-UX, продажа краденого владельцу, абьюз справки мира.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import aidnd.server.routes_play as rp  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from aidnd.server.app import app  # noqa: E402

c = TestClient(app)


def h(t):
    print("\n" + "═" * 8 + f" {t} " + "═" * max(1, 88 - len(t)))


sc = c.get("/api/play/scene").json()
beta = sc["here"][0]["id"]

h("ДЛИННЫЙ ДИАЛОГ (8 реплик) — деградация/повторы/выдумки")
c.post("/api/play/talk", json={"npc": beta})
qs = ["Расскажи про город — кто тут заправляет?",
      "А что за купец пропал у восточных ворот?",
      "Хм. А стража что говорит?",
      "Ладно. Что посоветуешь посмотреть в городе?",
      "А сама-то ты давно тут?",
      "Не боишься одна трактир держать?",
      "Если что-то узнаю про купца — скажу тебе.",
      "Ну, мне пора. Ещё увидимся."]
for q in qs:
    r = c.post("/api/play/say", json={"npc": beta, "text": q}).json()
    print(f"  Я: {q}")
    print(f"  Б: {r['line'][:170]}")

h("СПЛЕТНИ: краду у мельника при свидетелях → спрашиваю ТРЕТЬЕГО про себя")
mel = next((x["id"] for x in sc["here"] if x["role"] == "мельник"), None)
if mel:
    st = c.post("/api/play/steal", json={"npc": mel}).json()
    print("  кража у мельника:", "ПОЙМАН" if st.get("caught") else "успех", "| свид:", st.get("witnesses"))
    for _ in range(2):
        c.post("/api/play/live", json={})
        time.sleep(6.5)
    third = next((x["id"] for x in sc["here"] if x["id"] not in (beta, mel)), None)
    if third:
        c.post("/api/play/talk", json={"npc": third})
        r = c.post("/api/play/say", json={"npc": third, "text": "Что обо мне тут болтают?"}).json()
        print("  ТРЕТИЙ о тебе:", r["line"][:180])
else:
    print("  (мельника нет в зале)")

h("ПРОДАЮ ВЛАДЕЛЬЦУ ЕГО ЖЕ УКРАДЕНОЕ (если спёр вещь)")
inv = c.get("/api/play/inventory").json()["items"]
stolen = [i for i in inv if i["kind"] in ("trinket", "valuable", "misc") and "эль" not in i["name"].lower()]
if mel and stolen:
    o = c.post("/api/play/offer", json={"npc": mel, "item": stolen[0]["id"]}).json()
    print(f"  оффер мельнику за «{stolen[0]['name']}»: {o.get('price')} зм | «{(o.get('line') or '')[:130]}»")
else:
    print("  (нечего — кража не удалась/нет вещи)")

h("ЭКСПЕРТ-ОСМОТР: перстень → жрецу")
it = rp._forge("diag3|persten", "valuable", "перстень с мутным камнем", "тайник купца", "fine")
rp._store().inv_add(1, it["id"])
print("  скрытое:", [(x["prop"], x["gate"]["via"], x["gate"].get("req")) for x in it["hidden"]])
priest = next((x["id"] for x in sc["here"] if x["role"] == "жрец"), None)
me_try = c.post("/api/play/inspect", json={"item": it["id"], "via": "appraise"}).json()
print("  сам (appraise):", me_try.get("revealed") or "ничего", "| намёки:", len(me_try.get("hints", [])))
if priest:
    ex = c.post("/api/play/inspect", json={"item": it["id"], "via": "expert", "npc": priest}).json()
    print("  жрец (expert):", ex.get("revealed") or "ничего", "| by:", ex.get("by"))

h("КРАФТ-UX: заказ у знахарки и починка")
znah = next((x["id"] for x in sc["here"] if x["role"] == "знахарка"), None)
if znah:
    cm = c.post("/api/play/commission", json={"npc": znah}).json()
    itc = cm.get("item") or {}
    print(f"  заказ: «{itc.get('name')}» кач {itc.get('quality')} | скрытых {itc.get('unknown')}")
    for _ in range(4):
        u = c.post("/api/play/use", json={"item": itc.get("id")}).json()
        if u.get("event", {}).get("broke"):
            print("  сломалось — поведение:", u["event"]["break_behavior"])
            break
    rr = c.post("/api/play/repair", json={"item": itc.get("id"), "npc": znah}).json()
    print("  починка у знахарки:", rr.get("note") or rr.get("error"))
else:
    print("  (знахарки нет)")

h("СПРАВКА МИРА — абьюз")
for q in ["где живёт Бета Кожемяка?", "кто в городе самый богатый?", "где тут стража?", "как пройти к площади?"]:
    print(f"  «{q}» → {rp._world_lookup(q, rp._S['loc'])[:110]}")

h("НОЧЬ: трактир в 02:00 + живой тик")
rp._S["gt"] = 26 * 60
rp._S["routine_key"] = None
rp._apply_routine()
sc2 = c.get("/api/play/scene").json()
print("  трактир 02:00:", [x["name"][:30] for x in sc2["here"]] or "пусто")
r = c.post("/api/play/live", json={}).json()
for f in r.get("feed", [])[:4]:
    print("   ·", f["who"][:34], "—", str(f.get("text"))[:70])
for a in r.get("address", [])[:2]:
    print("   🗣", a["who"][:34], ":", a["text"][:80])
