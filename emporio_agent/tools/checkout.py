"""Checkout tools: payment options (PIX, cards, boleto) and shipping.

Rules come from the store policy manual (sections 3 and 5). Where the manual is
ambiguous or contradicts itself, the interpretation is documented in the README.
"""

from contextlib import closing
from decimal import Decimal

from emporio_agent.text_utils import normalize_text
from emporio_agent.tools._common import connect, format_brl, money
from emporio_agent.tools.catalog import load_catalog

MAX_INSTALLMENTS = 12
COMBINED_PAYMENT_MIN_TOTAL = Decimal("2000")  # manual 3.1: combining methods above R$ 2.000,00
LOCAL_FREE_SHIPPING_ABOVE = Decimal("500")  # manual 5.1: free shipping on orders above R$ 500,00
LOCAL_SHIPPING_FEE = Decimal("35")
LOCAL_CITY = "campo grande"  # the manual only names Campo Grande's metropolitan region

CARRIER_OPTIONS = [
    {"service": "PAC (Correios)", "delivery_time": "5 a 12 dias úteis", "tracking": True, "insurance": True},
    {"service": "SEDEX (Correios)", "delivery_time": "2 a 5 dias úteis", "tracking": True, "insurance": True},
    {"service": "Jadlog (.package)", "delivery_time": "3 a 8 dias úteis", "tracking": True, "insurance": True},
]


def min_installment_value(installments: int) -> Decimal:
    """Smallest allowed installment (manual 3.1): 1x none, 2-3x R$ 50, 4-6x R$ 80, 7-12x R$ 100."""
    if installments <= 1:
        return Decimal(0)
    if installments <= 3:
        return Decimal(50)
    if installments <= 6:
        return Decimal(80)
    return Decimal(100)


def installment_plan(total: Decimal) -> list[dict]:
    """Every valid interest-free credit card plan for `total`."""
    plan = []
    for n in range(1, MAX_INSTALLMENTS + 1):
        if total / n >= min_installment_value(n):
            plan.append(
                {
                    "installments": n,
                    "installment_value_display": format_brl(total / n),
                    "total_display": format_brl(total),
                    "interest": "none",
                }
            )
    return plan


def local_shipping_fee(order_total: Decimal) -> Decimal:
    """Campo Grande metropolitan region: free above R$ 500, otherwise a flat R$ 35."""
    return Decimal(0) if order_total > LOCAL_FREE_SHIPPING_ABOVE else LOCAL_SHIPPING_FEE


def _load_items(product_ids: list[int] | int) -> tuple[list[dict], list[int]]:
    if isinstance(product_ids, (int, str)):  # tolerate a single id instead of a list
        product_ids = [product_ids]
    with closing(connect()) as conn:
        by_id = {p["product_id"]: p for p in load_catalog(conn)}
    items = [by_id[int(pid)] for pid in product_ids if int(pid) in by_id]
    unknown = [int(pid) for pid in product_ids if int(pid) not in by_id]
    return items, unknown


def calculate_payment_options(product_ids: list[int]) -> dict:
    """Work out how a customer can pay for one or more products: PIX price, debit,
    boleto and the credit card installment plans allowed by store rules. Use it whenever
    the customer asks about PIX discount, parcelamento ("posso parcelar em 10x?"),
    boleto or how much each installment is. Never do these calculations yourself.

    Rules applied: PIX has 5% off the list price, except on products with an active
    promotion (promotions are not cumulative). Credit card is interest-free up to 12x
    with a minimum installment of R$ 50 (2-3x), R$ 80 (4-6x) and R$ 100 (7-12x).

    Args:
        product_ids: Ids of the products in the purchase (from search_products or
            get_product). Repeat an id for more than one unit.

    Returns:
        subtotal, PIX total and savings, debit/boleto totals, the list of valid credit
        card plans (`credit_card_plans`, `max_installments`) and whether combining
        payment methods is allowed.
    """
    items, unknown = _load_items(product_ids)
    if not items:
        return {"status": "error", "message": "No valid product ids were given.", "unknown_product_ids": unknown}

    subtotal = sum((p["effective_price"] for p in items), Decimal(0))
    pix_total = sum((p["pix_price"] if p["pix_price"] is not None else p["effective_price"] for p in items), Decimal(0))
    plan = installment_plan(subtotal)

    result = {
        "status": "ok",
        "items": [{"product_id": p["product_id"], "name": p["name"], "price_display": format_brl(p["effective_price"]),
                   "on_promotion": p["promotion"] is not None} for p in items],
        "subtotal_display": format_brl(subtotal),
        "pix": {
            "total_display": format_brl(pix_total),
            "savings_display": format_brl(subtotal - pix_total),
            "note": "5% off the list price; not applied to products already on promotion.",
        },
        "debit_card": {"total_display": format_brl(subtotal), "terms": "single payment, all card brands"},
        "boleto": {"total_display": format_brl(subtotal), "terms": "single payment, clears in up to 3 business days"},
        "credit_card_plans": plan,
        "max_installments": plan[-1]["installments"],
        "combined_payment_allowed": subtotal > COMBINED_PAYMENT_MIN_TOTAL,
        "combined_payment_note": "Combining payment methods (e.g. PIX + card) is allowed for purchases above R$ 2.000,00.",
    }
    unavailable = [p["name"] for p in items if p["availability"] != "in_stock"]
    if unavailable:
        result["unavailable_items"] = unavailable
    if unknown:
        result["unknown_product_ids"] = unknown
    return result


def _needs_individual_quote(product: dict) -> bool:
    """Large instruments that the manual says need an individual freight quote."""
    name = normalize_text(product["name"])
    return "bateria acustica" in name or "piano" in name


def estimate_shipping(city: str, product_ids: list[int]) -> dict:
    """Shipping cost and delivery time for a purchase, depending on the customer's city.
    Use it for questions like "how much is shipping to Dourados?" or "is delivery free?".
    Ask for the city first if the customer did not say it.

    Campo Grande: free above R$ 500, otherwise R$ 35, 1-3 business days by the store's own
    motorcycle courier. Other cities: Correios (PAC/SEDEX) or Jadlog, with the price
    calculated from the ZIP code (CEP) at checkout, so no price can be quoted here.
    Large instruments (acoustic drum kits, pianos) need an individual freight quote.

    Args:
        city: Customer's delivery city, e.g. "Campo Grande", "Dourados".
        product_ids: Ids of the products in the purchase (repeat an id for more units).
    """
    if not (city or "").strip():
        return {"status": "city_required", "message": "Ask the customer for the delivery city."}
    items, unknown = _load_items(product_ids)
    if not items:
        return {"status": "error", "message": "No valid product ids were given.", "unknown_product_ids": unknown}

    total = sum((p["effective_price"] for p in items), Decimal(0))
    result = {"status": "ok", "city": city.strip(), "order_total_display": format_brl(total)}

    large = [p["name"] for p in items if _needs_individual_quote(p)]
    if large:
        result["individual_quote_required_for"] = large
        result["individual_quote_note"] = "Large instruments need a freight quote made individually by the team."

    if normalize_text(city) == LOCAL_CITY:
        fee = local_shipping_fee(total)
        result.update(
            region="Campo Grande metropolitan region",
            delivery_method="store's own motorcycle courier (the customer is called before delivery)",
            delivery_time="1 a 3 dias úteis",
            shipping_fee_display="Grátis" if fee == 0 else format_brl(fee),
            free_shipping=fee == 0,
            free_shipping_rule="Free for orders above R$ 500,00; otherwise flat R$ 35,00.",
        )
    else:
        result.update(
            region="Outside the Campo Grande metropolitan region",
            carriers=CARRIER_OPTIONS,
            shipping_fee_display=None,
            note="The freight price is calculated automatically from ZIP code, weight and size when the order is placed. "
            "All shipments include insurance and a tracking code.",
        )
    if unknown:
        result["unknown_product_ids"] = unknown
    return result
