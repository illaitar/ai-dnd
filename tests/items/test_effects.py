from aidnd.items.attrs import derive_effects


def _draught(svyat=0, mana=0):
    attrs = {}
    if svyat:
        attrs["святость"] = {"surface": svyat, "true": svyat}
    if mana:
        attrs["мана"] = {"surface": mana, "true": mana}
    return {"kind": "consumable", "name": "зелье", "attrs": attrs}


def _heal(item):
    return [m for m in derive_effects(item)["mods"] if m["target"] == "special:heal"]


def test_heal_rule_bands_on_svyatost():
    assert _heal(_draught(60))[0]["amount"] == 5             # 60 ≥ 45 → medium
    assert _heal(_draught(60))[0]["when"] == "on_use"
    assert _heal(_draught(100))[0]["amount"] == 8            # ≥ 70 → large
    assert _heal(_draught(25))[0]["amount"] == 2             # ≥ 20 → small
    assert _heal(_draught(15)) == []                          # < 20 → no heal (honest 'no effect')


def test_heal_only_on_consumables():
    trinket = {"kind": "trinket", "form": "амулет", "attrs": {"святость": {"surface": 90, "true": 90}}}
    assert [m for m in derive_effects(trinket)["mods"] if m["target"] == "special:heal"] == []
