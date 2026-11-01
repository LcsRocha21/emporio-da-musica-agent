"""General tools: current date/opening hours and hand-over to the human team."""

import json
import uuid
from datetime import datetime, time, timedelta

from emporio_agent import config

WEEKDAYS_PT = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]

# Manual section 2. Keys are datetime.weekday(): Monday = 0. Sunday (6) is closed.
STORE_HOURS = {
    **{day: (time(9, 0), time(18, 0)) for day in range(5)},
    5: (time(9, 0), time(13, 0)),
}

HANDOFF_REASONS = ("complaint", "cancellation", "return_or_exchange", "order_issue", "other")


def _hours_label(day: int) -> str:
    hours = STORE_HOURS.get(day)
    return f"{hours[0]:%H:%M} às {hours[1]:%H:%M}" if hours else "fechado"


def get_current_datetime() -> dict:
    """Return the current date and time in Campo Grande and whether the store is open
    right now. Use it for "are you open now?", "until what time do you open today?" and
    whenever the date matters. Regular hours: Mon-Fri 09:00-18:00, Sat 09:00-13:00,
    Sun and holidays closed. Holidays are not detected automatically.
    """
    now = config.get_now()
    hours = STORE_HOURS.get(now.weekday())
    is_open = bool(hours and hours[0] <= now.time() < hours[1])

    result = {
        "date": now.strftime("%d/%m/%Y"),
        "time": now.strftime("%H:%M"),
        "weekday": WEEKDAYS_PT[now.weekday()],
        "store_open_now": is_open,
        "today_hours": _hours_label(now.weekday()),
        "note": "Holidays are not detected automatically; the store is closed on holidays.",
    }
    if not is_open:
        candidate = now
        for offset in range(0, 8):
            candidate = now + timedelta(days=offset)
            opening = STORE_HOURS.get(candidate.weekday())
            if opening and (offset > 0 or now.time() < opening[0]):
                result["next_opening"] = (
                    f"{WEEKDAYS_PT[candidate.weekday()]}, {candidate:%d/%m/%Y} às {opening[0]:%H:%M}"
                )
                break
    return result


def handoff_to_human(summary: str, reason: str = "other", customer_name: str | None = None,
                     contact: str | None = None) -> dict:
    """Register a request for the human team and tell the customer when to expect an answer.
    Use it for complaints, cancellations, returns/exchanges that need action, a customer
    who asks for a person, or anything you cannot or should not resolve yourself.
    Do NOT use it for questions you can answer with the other tools.

    Args:
        summary: Short, self-contained description of the case, including order number and
            what the customer wants (the human will not see the whole chat).
        reason: "complaint", "cancellation", "return_or_exchange", "order_issue" or "other".
        customer_name: Customer's name if known.
        contact: Phone or e-mail to reach the customer, if given.
    """
    if reason not in HANDOFF_REASONS:
        reason = "other"
    ticket_id = uuid.uuid4().hex[:8].upper()
    record = {
        "ticket_id": ticket_id,
        "created_at": config.get_now().isoformat(timespec="seconds"),
        "reason": reason,
        "customer_name": customer_name,
        "contact": contact,
        "summary": summary,
    }
    path = config.HANDOFF_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "status": "registered",
        "ticket_id": ticket_id,
        "expected_response": "A team member will get back to the customer within 24 business hours.",
    }
