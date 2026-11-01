"""Order tools: order status and return/exchange eligibility.

Order data is personal data (LGPD), so every lookup requires the customer to prove who
they are by giving the e-mail or phone registered on the order. Failed checks reveal
nothing about the order.
"""

from contextlib import closing
from datetime import date, timedelta

from emporio_agent.config import get_now
from emporio_agent.text_utils import digits_only
from emporio_agent.tools._common import connect, format_brl, format_date_br

REGRET_WINDOW_DAYS = 7  # manual 4.1: right of withdrawal, from receipt
DEFECT_EXCHANGE_WINDOW_DAYS = 30  # manual 4.2: exchange for defect, from purchase
PREFERENCE_WINDOW_DAYS = 7  # manual 4.3
LEGAL_WARRANTY_DAYS = 90  # manual 8.1: legal warranty, from receipt

STATUS_EXPLANATION = {
    "pending": "Order received, waiting for the payment to be confirmed.",
    "confirmed": "Payment confirmed; the order is being prepared. The tracking code is sent as soon as it is dispatched.",
    "shipped": "Order dispatched and on its way to the customer.",
    "delivered": "Order delivered.",
    "cancelled": "Order cancelled.",
}

PAYMENT_LABEL = {"pix": "PIX", "debit": "Cartão de débito", "boleto": "Boleto bancário", "credit": "Cartão de crédito"}

VERIFICATION_REQUIRED = {
    "status": "verification_required",
    "message": "To protect the customer's data, ask for the e-mail or the phone number registered on the order "
    "before sharing anything about it.",
}
NOT_VERIFIED = {
    "status": "not_verified",
    "message": "No order was found that matches these details. Do not reveal whether the order number exists. "
    "Ask the customer to double-check the order number and the e-mail/phone used in the purchase.",
}


def _national_phone(phone: str | None) -> str:
    """Digits of a Brazilian phone without the +55 country code."""
    digits = digits_only(phone)
    return digits[2:] if len(digits) in (12, 13) and digits.startswith("55") else digits


def _identity_matches(customer, email: str | None, phone: str | None) -> bool:
    email_ok = bool(email) and email.strip().lower() == (customer["email_normalized"] or "")
    phone_ok = bool(phone) and _national_phone(phone) != "" and _national_phone(phone) == _national_phone(
        customer["phone_digits"]
    )
    return email_ok or phone_ok


def _authorized_order(conn, order_id: int, email: str | None, phone: str | None):
    """Return (order_row, None) if the customer is verified, else (None, error_dict)."""
    if not (email or phone):
        return None, VERIFICATION_REQUIRED
    row = conn.execute(
        """
        SELECT o.*, c.email_normalized, c.phone_digits
        FROM orders o JOIN customers c ON c.customer_id = o.customer_id
        WHERE o.order_id = ?
        """,
        (order_id,),
    ).fetchone()
    if row is None or not _identity_matches(row, email, phone):
        return None, NOT_VERIFIED
    return row, None


def _order_items(conn, order_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT p.product_id, p.name, oi.quantity
        FROM order_items oi JOIN products p ON p.product_id = oi.product_id
        WHERE oi.order_id = ? ORDER BY oi.item_id
        """,
        (order_id,),
    ).fetchall()
    return [{"product_id": r["product_id"], "name": r["name"], "quantity": r["quantity"]} for r in rows]


def _payment_display(order) -> str:
    label = PAYMENT_LABEL.get(order["payment_type"], order["payment_type"])
    return f"{label} em {order['installments']}x" if order["payment_type"] == "credit" else label


def _order_summary(conn, order) -> dict:
    return {
        "order_id": order["order_id"],
        "order_date": format_date_br(order["order_date"]),
        "status": order["status"],
        "status_explanation": STATUS_EXPLANATION.get(order["status"], order["status"]),
        "total_display": format_brl(order["total_brl"]),
        "items": _order_items(conn, order["order_id"]),
    }


def get_order_status(order_id: int | None = None, customer_email: str | None = None,
                     customer_phone: str | None = None) -> dict:
    """Check the status of a customer's order (tracking code, delivery estimate, payment,
    cancellation reason) or list the customer's orders. The customer MUST identify
    themselves with the e-mail or the phone registered on the order; ask for it if missing.

    Args:
        order_id: Order number. If omitted, the customer's orders are listed (requires the
            e-mail or phone to identify the customer).
        customer_email: E-mail registered in the store.
        customer_phone: Phone registered in the store (any format, with or without DDD +55).

    Returns:
        status "ok" with the order (or `orders` list), or "verification_required" /
        "not_verified" / "ambiguous_identity" (hand over to a human with handoff_to_human).
    """
    with closing(connect()) as conn:
        if order_id is None:
            return _list_orders(conn, customer_email, customer_phone)

        order, error = _authorized_order(conn, int(order_id), customer_email, customer_phone)
        if error:
            return error

        summary = _order_summary(conn, order)
        summary.update(
            payment=_payment_display(order),
            tracking_code=order["tracking_code"],
            estimated_delivery=format_date_br(order["estimated_delivery"]),
            notes=order["notes"],
        )
        if order["tracking_code"]:
            summary["tracking_note"] = "Tracking can be checked on the Correios or Jadlog website."
        return {"status": "ok", "order": summary}


def _list_orders(conn, email: str | None, phone: str | None) -> dict:
    if not (email or phone):
        return VERIFICATION_REQUIRED
    customers = [
        c for c in conn.execute("SELECT * FROM customers").fetchall() if _identity_matches(c, email, phone)
    ]
    if not customers:
        return NOT_VERIFIED
    if len(customers) > 1:
        return {
            "status": "ambiguous_identity",
            "message": "More than one customer record matches these details. Do not share order data; "
            "offer to hand the case over to the team with handoff_to_human.",
        }
    orders = conn.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY order_date DESC", (customers[0]["customer_id"],)
    ).fetchall()
    return {
        "status": "ok",
        "customer_name": customers[0]["name"],
        "orders": [_order_summary(conn, o) for o in orders],
        "note": "Ask which order the customer means before giving details." if len(orders) > 1 else None,
    }


def _days(value: str) -> date:
    return date.fromisoformat(value)


def check_return_eligibility(order_id: int, reason: str, customer_email: str | None = None,
                             customer_phone: str | None = None) -> dict:
    """Decide whether a delivered order can still be returned or exchanged, applying the
    store's policy (Código de Defesa do Consumidor rules from the manual). Use it when a
    customer wants to give up on a purchase, return it, exchange it or reports a defect.
    The customer MUST be identified by the e-mail or phone registered on the order.

    Args:
        order_id: Order number.
        reason: "regret" (changed their mind, 7 days from receipt, full refund),
            "defect" (manufacturing defect, exchange within 30 days of purchase, then
            warranty), or "preference" (exchange for another color/model within 7 days,
            subject to stock).
        customer_email: E-mail registered in the store.
        customer_phone: Phone registered in the store.

    Returns:
        eligible (True/False/None when not applicable yet), the rule applied, deadline,
        days left, conditions and next steps. The delivery date is only an estimate (the
        data has no actual delivery date), so mention that when quoting deadlines.
    """
    if reason not in ("regret", "defect", "preference"):
        return {"status": "error", "message": "reason must be one of: regret, defect, preference."}

    with closing(connect()) as conn:
        order, error = _authorized_order(conn, int(order_id), customer_email, customer_phone)
        if error:
            return error
        items = _order_items(conn, order["order_id"])

    today = get_now().date()
    base = {
        "status": "ok",
        "order_id": order["order_id"],
        "reason": reason,
        "order_status": order["status"],
        "items": items,
        "reference_date": format_date_br(today),
    }

    if order["status"] == "cancelled":
        return {**base, "eligible": False, "rule": "The order is already cancelled, so there is nothing to return.",
                "cancellation_reason": order["notes"]}
    if order["status"] != "delivered":
        return {
            **base,
            "eligible": None,
            "rule": "Return windows count from receipt, and this order has not been delivered yet.",
            "next_steps": ["If the customer wants to cancel before delivery, offer to hand the case over to the team "
                           "with handoff_to_human (the manual has no automatic cancellation flow)."],
        }

    delivery = _days(order["estimated_delivery"])
    purchase = _days(order["order_date"])
    base.update(delivery_date_used=format_date_br(delivery), delivery_date_is_estimate=True,
                purchase_date=format_date_br(purchase))
    conditions = [
        "Product in its original packaging, unused, with all accessories and manuals.",
        "Not eligible: custom or special-order setups, 'final sale' clearance items, and wind instrument mouthpieces.",
    ]

    if reason == "defect":
        exchange_deadline = purchase + timedelta(days=DEFECT_EXCHANGE_WINDOW_DAYS)
        legal_deadline = delivery + timedelta(days=LEGAL_WARRANTY_DAYS)
        in_exchange = today <= exchange_deadline
        result = {
            **base,
            "eligible": in_exchange,
            "rule": "Manufacturing defects can be exchanged within 30 days of purchase; after that the manufacturer "
            "warranty applies (the store can mediate on request).",
            "deadline": format_date_br(exchange_deadline),
            "conditions": ["Damage from misuse, drops, humidity or unauthorized modifications is not covered."],
        }
        if not in_exchange:
            result["legal_warranty_active"] = today <= legal_deadline
            result["legal_warranty_deadline"] = format_date_br(legal_deadline)
            result["next_steps"] = ["Explain the 30-day exchange window has passed, mention the 90-day legal warranty "
                                    "and the manufacturer warranty, and offer to mediate with handoff_to_human."]
        else:
            result["days_left"] = (exchange_deadline - today).days
            result["next_steps"] = ["Hand the case over to the team to arrange the exchange (handoff_to_human)."]
        return result

    window = REGRET_WINDOW_DAYS if reason == "regret" else PREFERENCE_WINDOW_DAYS
    deadline = delivery + timedelta(days=window)
    eligible = today <= deadline
    result = {**base, "eligible": eligible, "deadline": format_date_br(deadline), "conditions": conditions}
    if reason == "regret":
        result["rule"] = "Right of withdrawal: 7 calendar days after receipt, no justification needed."
        if eligible:
            result["refund"] = "Refund in the original payment method within 10 business days; return shipping is paid by the store."
    else:
        result["rule"] = "Exchange for preference (color/model/size): 7 days, subject to stock of the desired product."
        if eligible:
            result["refund"] = "Price differences are charged or refunded accordingly."
    if eligible:
        result["days_left"] = (deadline - today).days
        result["next_steps"] = ["Hand the case over to the team to start the process (handoff_to_human)."]
    else:
        result["days_overdue"] = (today - deadline).days
        result["next_steps"] = ["Explain the deadline has passed. If the product has a defect, the defect rules and "
                                "warranty may still apply."]
    return result
