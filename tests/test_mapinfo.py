"""Покупка карт-сведений: честность продавца, ложь/неполнота, фиксация, разоблачение."""

from aidnd.bootstrap import new_session
from aidnd.gen import mapinfo
from aidnd.inventory.items import wallet_value_cp


def _sess(seed=1337):
    s = new_session(seed=seed, roster_size=4, use_model=False)
    s.world.wallet("pc:hero").update({"gp": 500})
    return s


def test_buy_charges_and_records():
    s = _sess()
    before = wallet_value_cp(s.world.wallet("pc:hero"))
    b = mapinfo.buy_info(s.world, "pc:hero", "npc:toblen_stonehill", "wyvern_tor")
    assert "error" not in b
    assert wallet_value_cp(s.world.wallet("pc:hero")) < before          # списано золото
    assert "belief:npc:toblen_stonehill:wyvern_tor" in s.world.player_maps["pc:hero"]


def test_buy_deterministic_by_seed():
    ra = mapinfo.buy_info(_sess(7).world, "pc:hero", "npc:halia_thornton", "cragmaw_hideout")
    rb = mapinfo.buy_info(_sess(7).world, "pc:hero", "npc:halia_thornton", "cragmaw_hideout")
    assert (ra["reliability"], ra["contents"], ra["true"]) == (rb["reliability"], rb["contents"], rb["true"])


def _false_rate(npc, site, n=40):
    c = 0
    for seed in range(n):
        b = mapinfo.buy_info(_sess(seed).world, "pc:hero", npc, site)
        if b.get("true") is False:
            c += 1
    return c / n


def test_shady_seller_lies_far_more_than_honest():
    honest = _false_rate("npc:toblen_stonehill", "wave_echo_cave")   # трактирщик — честный
    shady = _false_rate("npc:halia_thornton", "wave_echo_cave")      # Жентарим — жулик
    assert shady > honest
    assert shady >= 0.3 and honest <= 0.15


def test_already_known_no_recharge():
    s = _sess()
    mapinfo.buy_info(s.world, "pc:hero", "npc:toblen_stonehill", "wyvern_tor")
    before = wallet_value_cp(s.world.wallet("pc:hero"))
    r = mapinfo.buy_info(s.world, "pc:hero", "npc:toblen_stonehill", "wyvern_tor")
    assert r.get("error") == "already_known"
    assert wallet_value_cp(s.world.wallet("pc:hero")) == before       # повторно не берут денег


def test_map_view_hides_truth_until_verified():
    s = _sess()
    mapinfo.buy_info(s.world, "pc:hero", "npc:halia_thornton", "wave_echo_cave")
    e = next(x for x in mapinfo.map_view(s.world, "pc:hero") if x["site"] == "wave_echo_cave")
    assert e["display"] == "hearsay"          # непроверенное «со слов» — ложь неотличима
    assert "true" not in e                    # секрет истинности не утекает игроку


def test_insufficient_funds():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    s.world.wallets["pc:hero"] = {"cp": 5}
    r = mapinfo.buy_info(s.world, "pc:hero", "npc:toblen_stonehill", "wave_echo_cave")
    assert r.get("error") == "insufficient_funds"


def test_visit_debunks_lie_and_drops_trust():
    """Найти сид, где жулик соврал про ДОСТИЖИМОЕ логово, и разоблачить на месте."""
    for seed in range(80):
        s = _sess(seed)
        b = mapinfo.buy_info(s.world, "pc:hero", "npc:halia_thornton", "cragmaw_hideout")
        if b.get("true") is False:
            t0 = s.cognition.retrieve("npc:halia_thornton", "", "pc:hero").rel.trust
            revealed = mapinfo.verify_on_visit(s.world, "pc:hero", "place:cragmaw_klarg_cave")
            assert any(not was_true for _, was_true in revealed)         # ложь вскрыта
            bid = "belief:npc:halia_thornton:cragmaw_hideout"
            assert s.world.player_maps["pc:hero"][bid]["reliability"] == "false_revealed"
            t1 = s.cognition.retrieve("npc:halia_thornton", "", "pc:hero").rel.trust
            assert t1 < t0                                                # доверие упало
            return
    raise AssertionError("за 80 сидов жулик ни разу не соврал — крайне маловероятно")


def test_visit_confirms_truth():
    """Правдивая наводка о достижимом месте при посещении становится подтверждённой."""
    for seed in range(80):
        s = _sess(seed)
        b = mapinfo.buy_info(s.world, "pc:hero", "npc:toblen_stonehill", "cragmaw_hideout")
        if b.get("true"):
            mapinfo.verify_on_visit(s.world, "pc:hero", "place:cragmaw_klarg_cave")
            bid = "belief:npc:toblen_stonehill:cragmaw_hideout"
            assert s.world.player_maps["pc:hero"][bid]["reliability"] == "true_revealed"
            return
    raise AssertionError("честный ни разу не сказал правду — невозможно")
