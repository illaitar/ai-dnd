"""Плейтест-3: экономика + гильдия. Поднимаем ранг квестами → берём контракт (открывает путь) →
бой в логове → зачистка → ресурс потёк → цены/ассортимент лавки меняются. + 3 дня, деньги, стража.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from aidnd.bootstrap import new_session                      # noqa: E402
from aidnd.content.economy import resource_status, shop_supply_note  # noqa: E402
from aidnd.gen.item_gen import spawn_item                   # noqa: E402
from aidnd.inventory.items import wallet_value_cp           # noqa: E402
from aidnd.world.environment import day_number              # noqa: E402

LOG = open(os.path.join(os.path.dirname(__file__), "..", "playtest3_out.txt"), "w", encoding="utf-8")
ANOM = []
INN, BOARD, SHRINE, GUILD, SMITH, STORE, SQUARE = (
    "building:stonehill_inn", "building:notice_board", "building:shrine_of_luck",
    "building:adventurers_guild", "shop:lionshield", "shop:barthen", "place:phandalin_square")
N = 0


def out(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()


def gp(s):
    return round(wallet_value_cp(s.world.wallets.get(s.player, {})) / 100, 1)


def act(s, label, fn):
    global N
    N += 1
    try:
        r = fn() or {}
    except Exception as e:
        ANOM.append(f"[{label}] {e}")
        out(f"#{N:03d} ⚠ ИСКЛЮЧЕНИЕ [{label}]: {e}")
        out("    " + traceback.format_exc().splitlines()[-1]); return {}
    day = day_number(s.world.clock.tick) + 1
    out(f"#{N:03d} д{day} [{s._place_name(s.current_place())[:16]}] gp{gp(s)} «{label[:30]}» → {r.get('kind','')}: {(r.get('text') or '').replace(chr(10),' ')[:120]}")
    if s.view().get("in_combat"):
        drive_combat(s)
    return r


def drive_combat(s):
    cs = s.combat.state
    out(f"  ⚔ БОЙ (town={cs.town}) против {[s._display(e) for e in s.combat.alive_enemies()]}")
    for _ in range(80):
        cs = s.combat.state
        if cs.mode != "active":
            break
        if not s.combat.is_pc_turn():
            s.combat_end_turn(); continue
        cv = s.combat_view()
        if cv.get("targets") and "attack" in (cv.get("actions") or []):
            rr = s.combat_attack(cv["targets"][0])
            if s.pending_roll or (rr or {}).get("roll_request"):
                s.handle("кидаю")
            continue
        en = [c for c in cv["combatants"] if c["side"] == "enemy" and not c["fled"] and c["hp"] > 0]
        reach = cv.get("reachable") or []
        if en and reach and "move" in (cv.get("actions") or []):
            ex, ey = en[0]["pos"]
            s.combat_move(min(reach, key=lambda c: abs(c[0]-ex)+abs(c[1]-ey))); continue
        s.combat_end_turn()
    out(f"  ⚔ исход: {s.combat.state.outcome} | стража={s.combat.state.guard_intervened}")
    s.combat = None


def go(s, place):
    r = act(s, f"→ {s._place_name(place)[:14]}", lambda: s.travel_to(place))
    if "не разведал" in (r.get("text") or "") and place != SQUARE:
        act(s, "→ площадь", lambda: s.travel_to(SQUARE))
        r = act(s, f"→ {s._place_name(place)[:14]}", lambda: s.travel_to(place))
    return r


def store_prices(s):
    """Снимок цен/снабжения общей лавки (товары←тракт)."""
    return (round(resource_status(s.world, "goods") == "flowing", 0),
            shop_supply_note(s.world, ("gear", "consumable")))


def run():
    out("=== МИР (DeepSeek) ===")
    s = new_session(seed=11, roster_size=10, use_model=True)
    spawn_item(s.world, "tmpl:torch", f"carry:{s.player.split(':',1)[1]}", qty=1, source="test")  # под квест факела
    out(f"Старт gp{gp(s)} | металл={resource_status(s.world,'metal')} товары={resource_status(s.world,'goods')}")

    # --- поднять ранг гильдии двумя простыми контрактами (Гарэле + факел) ---
    go(s, BOARD)
    for q in (s.view().get("board") or {}).get("quests", []):
        if q.get("can_accept") and q["id"] in ("quest:board_garaele", "quest:board_torch"):
            act(s, f"взять «{q['title'][:14]}»", lambda qq=q: s.accept_quest(qq["id"]))
    go(s, SHRINE)
    act(s, "поговорить с Гарэле", lambda: s.handle("поговорить с сестрой гарэле, передать весть"))
    go(s, BOARD)
    for q in (s.view().get("board") or {}).get("quests", []):
        if q.get("can_turn_in"):
            act(s, f"сдать «{q['title'][:14]}»", lambda qq=q: s.turn_in_quest(qq["id"]))
    rep = s.world.reputation.get("faction:adventurers_guild", 0)
    out(f"--- стояние гильдии: {round(rep,3)} ---")

    # --- лавка ДО: цены на товары (тракт перекрыт cragmaw) ---
    go(s, STORE)
    bv = s.shop_view()
    before = {g["name"]: g["price_gp"] for g in (bv.get("goods") or [])} if bv else {}
    out(f"ЛАВКА ДО: {shop_supply_note(s.world,('gear','consumable'))} | примеры цен: {dict(list(before.items())[:3])}")

    # --- гильдия: ранг + взять контракт Крэгмо (откроет путь) ---
    go(s, GUILD)
    gv = s.guild_view()
    out(f"ГИЛЬДИЯ: ранг={gv['rank']} | контракты: " + "; ".join(f"{t['label']}[{t['danger']}/{t['status']}]" for t in gv["threats"][:3]))
    act(s, "взять контракт Крэгмо", lambda: s.take_contract("cragmaw_hideout"))

    # --- в логово → бой → зачистка ---
    act(s, "→ логово Крэгмо", lambda: s.travel_to("place:cragmaw_klarg_cave"))
    if not s.view().get("in_combat"):
        act(s, "напасть", lambda: s.handle("напасть на врагов"))
    out(f"--- после боя: cragmaw cleared={('cleared:place:cragmaw_klarg_cave' in s.world.flags)} товары={resource_status(s.world,'goods')} ---")

    # --- лавка ПОСЛЕ: товары должны подешеветь (тракт открыт) ---
    go(s, SQUARE); go(s, STORE)
    bv = s.shop_view()
    after = {g["name"]: g["price_gp"] for g in (bv.get("goods") or [])} if bv else {}
    out(f"ЛАВКА ПОСЛЕ: {shop_supply_note(s.world,('gear','consumable'))} | примеры цен: {dict(list(after.items())[:3])}")
    drops = [f"{nm}: {before[nm]}→{after[nm]}" for nm in after if nm in before and after[nm] < before[nm]]
    out(f"ПОДЕШЕВЕЛО: {drops or 'нет совпадений по позициям'}")

    # --- 3 дня ---
    act(s, "переночевать", lambda: s.handle("снять комнату и лечь спать до утра"))
    act(s, "переночевать", lambda: s.handle("лечь спать до утра"))

    out("\n=== ИТОГ ===")
    out(f"действий={N} день={day_number(s.world.clock.tick)+1} gp={gp(s)} стояние={round(s.world.reputation.get('faction:adventurers_guild',0),3)}")
    out(f"металл={resource_status(s.world,'metal')} товары={resource_status(s.world,'goods')}")
    out(f"АНОМАЛИЙ: {len(ANOM)}")
    for a in ANOM:
        out("  ⚠ " + a)
    LOG.close()


if __name__ == "__main__":
    run()
