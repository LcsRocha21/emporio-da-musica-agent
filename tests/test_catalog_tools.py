from emporio_agent.tools.catalog import get_product, search_products


def names(result):
    return [p["name"] for p in result["products"]]


def test_acoustic_guitars_up_to_1000_only_returns_available_ones_in_range(store):
    result = search_products(category="violões", max_price=1000, limit=20)
    assert result["total_matches"] == len(result["products"]) > 5
    assert all(p["price_brl"] <= 1000 for p in result["products"])
    assert all(p["availability"] == "in_stock" for p in result["products"])
    assert all(p["category"] == "Violões" for p in result["products"])
    assert "Yamaha C40 Nylon Natural" in names(result)
    assert not any("Taylor" in n or "Martin" in n for n in names(result))
    # product 96 (R$ 799,90) is in range but out of stock, so it must not be offered
    assert "Giannini GF-3D Dreadnought Sunburst" not in names(result)


def test_price_filter_uses_the_promotional_price(store):
    # Kalani KAL-700T costs R$ 359 but has 10% off (R$ 323,10): it fits a R$ 330 budget.
    result = search_products(category="ukulele", max_price=330)
    assert "Kalani KAL-700T Tenor Natural" in names(result)
    kalani = next(p for p in result["products"] if p["product_id"] == 127)
    assert kalani["price_display"] == "R$ 323,10"
    assert kalani["promotion"]["original_price_display"] == "R$ 359,00"
    assert kalani["promotion"]["discount_percent"] == 10


def test_category_is_detected_inside_the_query_and_steel_synonym_works(store):
    result = search_products(query="violão de aço")
    assert result["total_matches"] > 3
    assert {p["specs"]["strings"] for p in result["products"]} == {"steel"}


def test_seven_string_guitars_are_instruments_not_accessories(store):
    result = search_products(query="violão 7 cordas")
    assert result["total_matches"] >= 4
    assert all("7 Cordas" in n for n in names(result))


def test_electroacoustic_filter(store):
    result = search_products(category="violões", electroacoustic=True, string_material="nylon", limit=20)
    assert result["products"]
    assert all(p["specs"]["electronics"] == "yes" and p["specs"]["strings"] == "nylon" for p in result["products"])


def test_empty_category_returns_note_instead_of_inventing_products(store):
    result = search_products(query="saxofone")
    assert result["total_matches"] == 0 and result["products"] == []
    assert "no products" in result["note"]


def test_unavailable_products_can_be_requested_and_are_flagged(store):
    result = search_products(query="giannini gf-3d", only_available=False)
    assert [p["availability"] for p in result["products"]] == ["out_of_stock"]
    assert search_products(query="giannini gf-3d")["total_matches"] == 0


def test_sorting_and_limit(store):
    cheap = search_products(category="violões", limit=2)
    dear = search_products(category="violões", sort_by="price_desc", limit=2)
    assert cheap["products"][0]["price_brl"] < dear["products"][0]["price_brl"]
    assert len(cheap["products"]) == 2 and cheap["total_matches"] > 2
    assert dear["products"][0]["name"] == "Martin D-28E Elétrico Aço Natural"  # R$ 12.000, most expensive


def test_takamine_gd20_price_and_pix(store):
    result = get_product("Takamine GD20")
    assert result["status"] == "found"
    product = result["product"]
    assert product["price_display"] == "R$ 2.199,00"
    assert product["pix_price_display"] == "R$ 2.089,05"
    assert product["promotion"] is None
    assert "alternatives" not in result


def test_promotional_product_shows_original_price_and_no_pix_discount(store):
    product = get_product("Taylor 110e")["product"]  # 8% off R$ 5.999
    assert product["promotion"]["original_price_display"] == "R$ 5.999,00"
    assert product["promotion"]["promo_price_display"] == "R$ 5.519,08"
    assert product["promotion"]["discount_percent"] == 8
    assert product["pix_price_display"] is None


def test_expired_promotions_are_never_applied(store):
    product = get_product("Giannini GF-3D")["product"]  # had 18% and 40% promotions, both inactive
    assert product["promotion"] is None
    assert product["price_display"] == "R$ 799,90"


def test_out_of_stock_product_comes_with_alternatives(store):
    result = get_product("Giannini GF-3D")
    assert result["product"]["availability"] == "out_of_stock"
    alternatives = result["alternatives"]
    assert 1 <= len(alternatives) <= 3
    assert all(a["availability"] == "in_stock" and a["category"] == "Violões" for a in alternatives)
    assert all(a["product_id"] != 96 for a in alternatives)


def test_discontinued_and_coming_soon_products(store):
    assert get_product("Shelby SN-7C")["product"]["availability"] == "discontinued"
    soon = get_product("Kala KA-ABP-CTG")
    assert soon["product"]["availability"] == "coming_soon"
    assert soon["alternatives"] and all(a["category"] == "Ukuleles" for a in soon["alternatives"])


def test_ambiguous_and_unknown_products(store):
    ambiguous = get_product("Takamine")
    assert ambiguous["status"] == "ambiguous" and ambiguous["total_matches"] == 4

    missing = get_product("Fender Jazzmaster")
    assert missing["status"] == "not_found"
    assert missing["suggestions"]  # close names such as other Fender models


def test_lookup_by_id_and_accent_insensitive_name(store):
    assert get_product("95")["product"]["name"].startswith("Takamine GD20")
    assert get_product("tagima dallas tuner aco")["product"]["product_id"] == 86
