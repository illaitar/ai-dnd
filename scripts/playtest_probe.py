"""Плейтест от лица игрока: полная сессия через API с прицелом на странности/нереалистичности.
Пишет читаемый транскрипт в stdout. Локальная БД (после — git checkout data/worlds.db).
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
W = 100


def h(t):
    print("\n" + "═" * 8 + f" {t} " + "═" * max(1, W - 10 - len(t)))


def p(label, v):
    print(f"  {label}: {v}")


h("ПРИБЫТИЕ")
sc = c.get("/api/play/scene").json()
p("локация", sc["location"]["name"] + " · " + sc["location"]["kind"])
p("время/монеты", f"{sc['gt']//60:02d}:{sc['gt']%60:02d} / {sc['coins']} зм")
p("кто здесь", [(x["name"][:40], x["role"]) for x in sc["here"]])
p("ёмкости", [(x["name"], "🔒" if x["locked"] else "·") for x in sc["location"]["containers"]])

h("ЖИВОЙ ФОН — 3 тика")
for i in range(3):
    r = c.post("/api/play/live", json={}).json()
    for f in r.get("feed", []):
        print(f"   · {f['who'][:36]}" + (f" → {f.get('to','')[:24]}: «{f['text'][:70]}»" if f["k"] == "speech"
                                          else f" — {f['text'][:80]}"))
    for a in r.get("address", []):
        print(f"   🗣 К ТЕБЕ — {a['who'][:36]}: «{a['text'][:90]}»")
    time.sleep(6.5)

npc = sc["here"][0]["id"]
h("РАЗГОВОР с трактирщицей")
t = c.post("/api/play/talk", json={"npc": npc}).json()
p("имя/эмоция", f"{t['name']} / {t['emotion']}")
p("GREET", t["line"][:150])
p("ключи на виду", t.get("keys"))
if t.get("contract"):
    ct = t["contract"]
    p("ПРОСЬБА", ct["pitch"][:150])
    p("уговор", f"{ct['kind']}: {ct.get('want') or ct.get('target_name')} | {ct['where']} | {ct['reward']} зм")

r = c.post("/api/play/say", json={"npc": npc, "text": "Что нового в городе? Есть работа для меня?"}).json()
p("SAY→", r["line"][:150])

h("ТОРГ: продаю ЕЙ ЖЕ её эль (налутал из её бочки)")
lt = c.post("/api/play/loot", json={"container": "Бочка с элем"}).json()
p("лут бочки", [i["name"] for i in lt.get("items", [])] or lt.get("error"))
inv = c.get("/api/play/inventory").json()["items"]
if inv:
    o = c.post("/api/play/offer", json={"npc": npc, "item": inv[0]["id"]}).json()
    p("оффер за её же эль", f"{o.get('price')} зм | «{(o.get('line') or '')[:110]}»")

h("ВИТРИНА и покупка")
w = c.get(f"/api/play/wares?npc={npc}").json()
p("товары", [(i["name"][:32], i["price"]) for i in w.get("items", [])])

h("КРАЖА у неё на глазах у толпы")
st = c.post("/api/play/steal", json={"npc": npc}).json()
p("исход", "ПОЙМАН" if st.get("caught") else f"украдено {st.get('coins_taken') or (st.get('item') or {}).get('name')}")
t2 = c.post("/api/play/talk", json={"npc": npc}).json()
p("GREET после кражи", t2["line"][:160])
p("эмоция", t2["emotion"])

h("СВОБОДНЫЕ ДЕЙСТВИЯ — странные вводы")
for txt in ["смотрю в окно на дождь", "заказываю комнату на ночь", "фывапролдж",
            "поджигаю трактир", "выпиваю эль из сумки", "иду к реке"]:
    r = c.post("/api/play/act", json={"text": txt}).json()
    out = r.get("narr") or [k for k in ("loot", "inspect", "goto", "open_talk") if r.get(k) is not None]
    print(f"  «{txt}» → {str(out)[:110]}")

h("КАНДИДАТЫ КОНТРАКТОВ Беты (абсурд-чек: своё же здание?)")
cands = rp._contract_candidates(npc)
for x in cands[:8]:
    print(f"   - «{x['name'][:40]}» → {x['where'][:44]}")

h("НОЧЬ/УТРО: распорядок и сцены улиц")
kb = rp._S["geom"]["keys"][3]
mv = c.post("/api/play/move", json={"to": kb["node"]}).json()
p("пришёл", f"{mv['location']['name']} ({kb['label']}), кто здесь: {len(mv['here'])}")
rp._S["gt"] = 8 * 60
rp._S["routine_key"] = None
rp._apply_routine()
sc2 = c.get("/api/play/scene").json()
p("утром там же", f"кто здесь: {len(sc2['here'])} | ambient: {sc2['ambient']}")
tav = next(k for k in rp._S["geom"]["keys"] if k["label"] == "трактир")
mv2 = c.post("/api/play/move", json={"to": tav["node"]}).json()
p("трактир утром", f"кто здесь: {[x['name'][:28] for x in mv2['here']]}")

h("ИТОГО: сумка/дела/монеты")
inv = c.get("/api/play/inventory").json()["items"]
p("сумка", [(i["name"][:30], i["worth"]) for i in inv])
j = c.get("/api/play/contracts").json()
p("дела", [(x["giver_name"], x.get("kind"), x.get("want") or x.get("target_name")) for x in j["active"]])
sc3 = c.get("/api/play/scene").json()
p("монеты/время", f"{sc3['coins']} зм / {sc3['gt']//60%24:02d}:{sc3['gt']%60:02d}")
