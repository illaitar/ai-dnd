"""Связка карты и перемещения: достижимость сайтов, маршрутизация, время/риск в
пути, честная AOI (containment ≠ проходимость), отсутствие утечки истины, свёртка
дублей и замкнутость петли купил→дошёл→разоблачил для ВСЕХ региональных сайтов."""

from aidnd.bootstrap import new_session
from aidnd.content.region import REGION_SITES, reachable_place_to_site
from aidnd.gen import mapinfo


def _sess(seed=0):
    s = new_session(seed=seed, roster_size=4, use_model=False)
    s.world.wallet("pc:hero").update({"gp": 500})
    return s


def test_all_region_sites_are_real_reachable_nodes():
    """P1: каждый сайт REGION_SITES — узел графа, достижимый из города, и петля
    reachable_place_to_site замкнута (раньше работало лишь для логова Крэгмо)."""
    s = _sess()
    sp = s.world.spatial
    sq = "place:phandalin_square"
    for key, v in REGION_SITES.items():
        pid = v["place"]
        assert pid in sp.places, f"{key}: нет узла {pid}"
        assert sp.path_between(sq, pid) is not None, f"{key}: недостижим"
        assert reachable_place_to_site(pid) == key


def test_routing_multi_hop_to_named_location():
    """P5: «идти в логово» из таверны прокладывает путь через площадь и дикие земли
    к подходу, затем «идти в пещеру» уводит в пещеру Кларга (а не телепорт)."""
    s = _sess()
    assert s.current_place() == "building:stonehill_inn"
    s.handle("идти в логово")
    assert s.current_place() == "site:cragmaw_hideout"
    s.handle("идти в пещеру")
    assert s.current_place() == "place:cragmaw_klarg_cave"


def test_cave_disambiguation_prefers_nearest():
    """P8: у входа в логово «пещера» — это пещера Кларга, а не Пещера Эха Волн
    (коллизия подстроки «пещер» снята матчем по графу/ближайшему узлу)."""
    s = _sess()
    s.handle("идти в логово")
    assert s._match_place("идти в пещеру") == "place:cragmaw_klarg_cave"


def test_region_travel_costs_hours_town_step_is_cheap():
    """P3: переход дикими землями стоит часы, шаг по городу — минуты."""
    s = _sess()
    t0 = s.world.clock.tick
    s.handle("идти в лавку Бартена")           # шаг по городу
    town = s.world.clock.tick - t0
    s2 = _sess()
    t1 = s2.world.clock.tick
    s2.handle("идти в логово")                 # дикие земли
    wild = s2.world.clock.tick - t1
    assert wild >= town * 5 and wild > 0


def test_aoi_does_not_leak_containment_nodes():
    """P4: рёбра вложенности (settlement/region) не попадают в порталы, поэтому AOI
    у площади не «видит» абстрактные узлы."""
    sp = _sess().world.spatial
    nb = sp.neighbors("place:phandalin_square", 1)
    assert not any(x.startswith(("settlement", "region")) for x in nb)
    assert "settlement:phandalin" not in sp.connections("place:phandalin_square")


def test_buyinfo_payload_hides_truth():
    """P2: купленная наводка отдаётся игроко-безопасно — без полей true/reliability."""
    s = _sess(7)
    out = s._do_buyinfo(type("A", (), {"target": "npc:halia_thornton"})(),
                        "разузнать о дороге к пещере эха волн")
    belief = out.get("map_belief", {})
    assert belief and "true" not in belief and "reliability" not in belief


def test_explored_pin_is_rich_and_deduped():
    """P7: личный визит даёт богатый пин (рельеф/сторона света из ground-truth), а
    купленный слух о том же месте сворачивается в один пин «разведано»."""
    s = _sess()
    mapinfo.buy_info(s.world, "pc:hero", "npc:halia_thornton", "cragmaw_hideout")
    s._record_explored("place:cragmaw_klarg_cave")
    pins = [v for v in mapinfo.map_view(s.world, "pc:hero")
            if v["place"] == "place:cragmaw_klarg_cave"]
    assert len(pins) == 1
    assert pins[0]["display"] == "explored"
    assert pins[0]["terrain"] == "холмы, пещера"


def test_region_map_is_graph_driven_and_deterministic():
    """Снимок region_map(): все сайты, направления = стороны света графа, часы>0,
    повторный вызов идентичен (read-model детерминирован)."""
    from aidnd.world.spatial import DIR_ALIASES
    s = _sess()
    rm = s.region_map()
    assert {x["key"] for x in rm["sites"]} == set(REGION_SITES)
    for x in rm["sites"]:
        assert x["dir"] == DIR_ALIASES.get(REGION_SITES[x["key"]]["direction"])
        assert x["hours"] and x["hours"] > 0
    assert s.region_map() == rm


def test_region_map_flags_liar_even_after_exploration():
    """После личного визита пин — «разведано» (правда из первых рук), но факт лжи
    источника всё равно всплывает полем lied_by (P7 не теряет соц. информацию)."""
    for seed in range(80):
        s = _sess(seed)
        b = mapinfo.buy_info(s.world, "pc:hero", "npc:halia_thornton", "wyvern_tor")
        if b.get("true") is False:
            s.world.commit("set_position", "pc:hero", target="pc:hero",
                           payload={"region": "region:phandalin", "place": "place:wyvern_tor"})
            s._record_explored("place:wyvern_tor")
            s._verify_map_here("place:wyvern_tor")
            site = next(x for x in s.region_map()["sites"] if x["key"] == "wyvern_tor")
            assert site["display"] == "explored"
            assert site["lied_by"] and "Halia" in site["lied_by"]
            return
    raise AssertionError("за 80 сидов жулик ни разу не соврал про Вайверн-Тор")


def test_lie_loop_closes_for_non_cragmaw_site():
    """P1: купить ложь у жулика о ТЕПЕРЬ достижимом сайте и разоблачить визитом."""
    for seed in range(80):
        s = _sess(seed)
        b = mapinfo.buy_info(s.world, "pc:hero", "npc:halia_thornton", "wyvern_tor")
        if b.get("true") is False:
            s.world.commit("set_position", "pc:hero", target="pc:hero",
                           payload={"region": "region:phandalin", "place": "place:wyvern_tor"})
            assert s._verify_map_here("place:wyvern_tor") is True       # ложь вскрыта
            bid = "belief:npc:halia_thornton:wyvern_tor"
            assert s.world.player_maps["pc:hero"][bid]["reliability"] == "false_revealed"
            return
    raise AssertionError("за 80 сидов жулик ни разу не соврал про Вайверн-Тор")
