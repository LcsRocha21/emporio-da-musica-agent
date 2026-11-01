from emporio_agent.tools.orders import check_return_eligibility, get_order_status

ANA = {"customer_email": "anacarol.ferreira@coldmail.com"}  # customer 2, owner of order 8
PEDRO = {"customer_phone": "(67) 98432-1098"}  # customer 3, owner of orders 1 and 19


def test_shipped_order_with_tracking_and_email_check(store):
    result = get_order_status(8, **ANA)
    order = result["order"]
    assert result["status"] == "ok"
    assert order["status"] == "shipped"
    assert order["tracking_code"] == "BRJL5544332BR"
    assert order["estimated_delivery"] == "28/02/2026"
    assert order["payment"] == "Cartão de débito"
    assert order["items"] == [{"product_id": 120, "name": "Kala KA-C Concert Mogno", "quantity": 1}]


def test_email_check_is_case_insensitive_and_phone_accepts_any_format(store):
    assert get_order_status(8, customer_email=" Anacarol.Ferreira@Coldmail.com ")["status"] == "ok"
    for phone in ("(67) 99654-7821", "67996547821", "+55 67 99654-7821", "5567996547821"):
        assert get_order_status(8, customer_phone=phone)["status"] == "ok", phone


def test_no_identification_means_no_data(store):
    result = get_order_status(8)
    assert result["status"] == "verification_required"
    assert "order" not in result


def test_wrong_identification_leaks_nothing_and_looks_the_same_as_unknown_order(store):
    wrong = get_order_status(8, customer_email="someone.else@jmail.com")
    unknown = get_order_status(9999, **ANA)
    assert wrong == unknown
    assert wrong["status"] == "not_verified"
    assert "tracking" not in str(wrong).lower().replace("tracking code", "")


def test_other_customers_cannot_see_the_order(store):
    # Pedro's phone does not open Ana's order 8.
    assert get_order_status(8, **PEDRO)["status"] == "not_verified"


def test_order_without_tracking_yet(store):
    order = get_order_status(9, customer_email="juliana.almeida@hayoo.com.br")["order"]
    assert order["status"] == "confirmed" and order["tracking_code"] is None
    assert order["estimated_delivery"] is None


def test_cancelled_order_shows_the_reason(store):
    # Order 17 belongs to customer 15.
    order = get_order_status(17, customer_email="matheus.correia@hayoo.com.br")["order"]
    assert order["status"] == "cancelled"
    assert order["notes"] == "Pedido cancelado pelo cliente antes do processamento"


def test_list_orders_for_an_identified_customer(store):
    result = get_order_status(**PEDRO)
    assert result["status"] == "ok"
    assert [o["order_id"] for o in result["orders"]] == [19, 1]  # newest first
    assert result["customer_name"] == "Pedro Henrique Oliveira"


def test_duplicate_customer_email_is_not_used_to_expose_orders(store):
    # Customers 11 and 43 share this e-mail (known data issue): refuse to guess.
    result = get_order_status(customer_email="bruno.martins@jmail.com")
    assert result["status"] == "ambiguous_identity"
    assert "orders" not in result
    # The phone number is unique, so it still identifies the right customer.
    assert get_order_status(customer_phone="(67) 98543-2109")["status"] == "ok"


def test_regret_within_7_days_of_delivery(store, at):
    at("2025-10-30T10:00:00")  # order 1 estimated delivery 25/10/2025 -> deadline 01/11/2025
    result = check_return_eligibility(1, "regret", **PEDRO)
    assert result["eligible"] is True
    assert result["deadline"] == "01/11/2025"
    assert result["days_left"] == 2
    assert "10 business days" in result["refund"]
    assert "does not say when" in result["refund_note"]
    assert result["delivery_date_is_estimate"] is True


def test_regret_on_the_last_day_is_still_valid_and_one_day_later_is_not(store, at):
    at("2025-11-01T23:00:00")
    assert check_return_eligibility(1, "regret", **PEDRO)["eligible"] is True
    at("2025-11-02T08:00:00")
    late = check_return_eligibility(1, "regret", **PEDRO)
    assert late["eligible"] is False and late["days_overdue"] == 1


def test_defect_exchange_window_and_warranty_after_it(store, at):
    at("2025-11-10T10:00:00")  # purchase 15/10/2025 -> exchange deadline 14/11/2025
    inside = check_return_eligibility(1, "defect", **PEDRO)
    assert inside["eligible"] is True and inside["deadline"] == "14/11/2025"

    at("2025-12-01T10:00:00")
    outside = check_return_eligibility(1, "defect", **PEDRO)
    assert outside["eligible"] is False
    assert outside["legal_warranty_active"] is True  # 90 days from receipt: until 23/01/2026
    assert outside["legal_warranty_deadline"] == "23/01/2026"

    at("2026-03-01T10:00:00")
    assert check_return_eligibility(1, "defect", **PEDRO)["legal_warranty_active"] is False


def test_preference_exchange_depends_on_stock(store, at):
    at("2025-10-28T10:00:00")
    result = check_return_eligibility(1, "preference", **PEDRO)
    assert result["eligible"] is True and "stock" in result["rule"]


def test_not_yet_delivered_order_is_not_returnable_yet(store, at):
    at("2026-03-01T10:00:00")
    result = check_return_eligibility(8, "regret", **ANA)  # shipped, not delivered
    assert result["eligible"] is None
    assert "not been delivered" in result["rule"]


def test_cancelled_order_has_nothing_to_return(store, at):
    at("2026-03-01T10:00:00")
    result = check_return_eligibility(19, "regret", **PEDRO)  # order 19 is cancelled and belongs to customer 3
    assert result["eligible"] is False
    assert result["cancellation_reason"] == "Pagamento não confirmado dentro do prazo"


def test_return_check_requires_identity_and_a_valid_reason(store):
    assert check_return_eligibility(1, "regret")["status"] == "verification_required"
    assert check_return_eligibility(1, "regret", customer_email="x@y.com")["status"] == "not_verified"
    assert check_return_eligibility(1, "boredom", **PEDRO)["status"] == "error"
