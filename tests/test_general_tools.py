import json

from emporio_agent.tools.general import get_current_datetime, handoff_to_human


def test_open_on_a_weekday_morning(at):
    at("2026-11-02T10:00:00")  # Monday
    result = get_current_datetime()
    assert result["weekday"] == "segunda-feira"
    assert result["store_open_now"] is True
    assert result["today_hours"] == "09:00 às 18:00"
    assert "next_opening" not in result


def test_closed_before_opening_and_after_closing(at):
    at("2026-11-02T08:30:00")
    assert get_current_datetime()["next_opening"] == "segunda-feira, 02/11/2026 às 09:00"
    at("2026-11-02T18:00:00")  # closing time itself counts as closed
    result = get_current_datetime()
    assert result["store_open_now"] is False
    assert result["next_opening"] == "terça-feira, 03/11/2026 às 09:00"


def test_saturday_hours_end_at_13h(at):
    at("2026-11-07T12:59:00")
    assert get_current_datetime()["store_open_now"] is True
    at("2026-11-07T14:00:00")
    result = get_current_datetime()
    assert result["store_open_now"] is False
    assert result["next_opening"] == "segunda-feira, 09/11/2026 às 09:00"


def test_sunday_is_closed(at):
    at("2026-11-01T13:00:00")
    result = get_current_datetime()
    assert result["weekday"] == "domingo" and result["today_hours"] == "fechado"
    assert result["store_open_now"] is False
    assert result["next_opening"] == "segunda-feira, 02/11/2026 às 09:00"


def test_handoff_registers_a_ticket_with_the_24h_promise(store, at):
    at("2026-03-01T10:00:00")
    result = handoff_to_human("Order 1: customer wants to return the Martin D-28.", "return_or_exchange",
                              customer_name="Pedro", contact="(67) 98432-1098")
    assert result["status"] == "registered" and len(result["ticket_id"]) == 8
    assert "24 business hours" in result["expected_response"]

    lines = (store / "handoffs.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert record["ticket_id"] == result["ticket_id"]
    assert record["reason"] == "return_or_exchange"
    assert record["created_at"].startswith("2026-03-01T10:00:00")


def test_handoff_with_unknown_reason_falls_back_to_other(store):
    handoff_to_human("Something odd", "banana")
    record = json.loads((store / "handoffs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["reason"] == "other"
