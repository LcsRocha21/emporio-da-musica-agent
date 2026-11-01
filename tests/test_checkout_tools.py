from decimal import Decimal

from emporio_agent.tools.checkout import (
    calculate_payment_options,
    estimate_shipping,
    installment_plan,
    local_shipping_fee,
    min_installment_value,
)


def max_installments(product_id):
    return calculate_payment_options([product_id])["max_installments"]


def test_expensive_item_gets_pix_discount_12x_and_combined_payment(store):
    result = calculate_payment_options([95])  # Takamine GD20, R$ 2.199,00
    assert result["subtotal_display"] == "R$ 2.199,00"
    assert result["pix"]["total_display"] == "R$ 2.089,05"
    assert result["pix"]["savings_display"] == "R$ 109,95"
    assert result["max_installments"] == 12
    assert result["credit_card_plans"][-1]["installment_value_display"] == "R$ 183,25"
    assert result["combined_payment_allowed"] is True


def test_installment_limits_follow_manual_section_3_1(store):
    assert max_installments(119) == 3  # R$ 159,90: 4x would be R$ 39,98 (< R$ 80)
    assert max_installments(120) == 4  # R$ 349,90: 4x = R$ 87,48 ok; 5x = R$ 69,98 not ok
    assert max_installments(81) == 6  # R$ 599,90: 6x = R$ 99,98 ok; 7x = R$ 85,70 (< R$ 100)
    assert max_installments(92) == 12  # R$ 1.299,00 / 12 = R$ 108,25


def test_min_installment_value_thresholds():
    assert [min_installment_value(n) for n in (1, 2, 3, 4, 6, 7, 12)] == [0, 50, 50, 80, 80, 100, 100]
    assert [p["installments"] for p in installment_plan(Decimal("40"))] == [1]
    assert [p["installments"] for p in installment_plan(Decimal("100"))] == [1, 2]


def test_pix_discount_is_not_applied_on_promotional_products(store):
    result = calculate_payment_options([127])  # Kalani KAL-700T: R$ 359 with 10% promo = R$ 323,10
    assert result["subtotal_display"] == "R$ 323,10"
    assert result["pix"]["total_display"] == "R$ 323,10"
    assert result["pix"]["savings_display"] == "R$ 0,00"


def test_multiple_units_and_mixed_cart(store):
    result = calculate_payment_options([119, 119, 95])
    assert result["subtotal_display"] == "R$ 2.518,80"  # 2 x 159,90 + 2.199,00
    assert result["pix"]["total_display"] == "R$ 2.392,87"  # 5% off each item, rounded per item: 151,91 x 2 + 2.089,05


def test_unknown_and_unavailable_products(store):
    assert calculate_payment_options([99999])["status"] == "error"
    result = calculate_payment_options([96, 99999])
    assert result["unavailable_items"] == ["Giannini GF-3D Dreadnought Sunburst"]
    assert result["unknown_product_ids"] == [99999]


def test_a_single_id_is_accepted_instead_of_a_list(store):
    assert calculate_payment_options(95)["max_installments"] == 12


def test_local_shipping_is_free_only_above_500():
    assert local_shipping_fee(Decimal("500")) == Decimal(35)
    assert local_shipping_fee(Decimal("500.01")) == Decimal(0)
    assert local_shipping_fee(Decimal("159.90")) == Decimal(35)


def test_shipping_in_campo_grande(store):
    cheap = estimate_shipping("campo grande", [119])  # R$ 159,90
    assert cheap["shipping_fee_display"] == "R$ 35,00" and cheap["free_shipping"] is False
    assert cheap["delivery_time"] == "1 a 3 dias úteis"
    assert estimate_shipping("Campo Grande", [95])["free_shipping"] is True


def test_shipping_to_other_cities_uses_carriers_without_inventing_a_price(store):
    result = estimate_shipping("Dourados", [95])
    assert result["shipping_fee_display"] is None
    assert {c["service"] for c in result["carriers"]} == {"PAC (Correios)", "SEDEX (Correios)", "Jadlog (.package)"}


def test_large_instruments_need_individual_quote_but_electric_bass_does_not(store):
    drums = estimate_shipping("Campo Grande", [139])  # acoustic drum kit
    assert drums["individual_quote_required_for"] == ["Bateria Acústica Yamaha Kit 1 Studio"]
    # The catalog calls bass guitars "Contrabaixo", which is not the double bass of the manual.
    assert "individual_quote_required_for" not in estimate_shipping("Campo Grande", [137])


def test_shipping_asks_for_the_city_when_missing(store):
    assert estimate_shipping("  ", [95])["status"] == "city_required"
