import inspect
import json

from emporio_agent.tools import TOOLS
from emporio_agent.tools.__main__ import main, parse_value


def test_every_tool_is_documented_and_fully_typed():
    assert len(TOOLS) == 9
    for name, fn in TOOLS.items():
        assert fn.__doc__ and len(fn.__doc__) > 80, f"{name} needs a docstring: the LLM reads it"
        for param in inspect.signature(fn).parameters.values():
            assert param.annotation is not inspect.Parameter.empty, f"{name}.{param.name} needs a type hint"


def test_tool_results_are_json_serializable(store, at):
    at("2026-03-01T10:00:00")
    samples = [
        ("search_products", {"query": "yamaha"}),
        ("get_product", {"product": "Takamine GD20"}),
        ("calculate_payment_options", {"product_ids": [95, 96]}),
        ("estimate_shipping", {"city": "Dourados", "product_ids": [95]}),
        ("get_order_status", {"order_id": 8, "customer_email": "anacarol.ferreira@coldmail.com"}),
        ("check_return_eligibility", {"order_id": 1, "reason": "regret", "customer_phone": "(67) 98432-1098"}),
        ("search_policies", {"query": "horário de funcionamento"}),
        ("get_current_datetime", {}),
        ("handoff_to_human", {"summary": "test"}),
    ]
    assert {name for name, _ in samples} == set(TOOLS)
    for name, kwargs in samples:
        json.dumps(TOOLS[name](**kwargs), ensure_ascii=False)


def test_playground_parses_values():
    assert parse_value("1000") == 1000
    assert parse_value("true") is True
    assert parse_value("95,96") == [95, 96]
    assert parse_value("[95, 96]") == [95, 96]
    assert parse_value("violões") == "violões"


def test_playground_runs_a_tool_and_prints_json(store, capsys):
    assert main(["get_product", "product=Takamine GD20"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["product"]["price_display"] == "R$ 2.199,00"


def test_playground_lists_tools_and_rejects_bad_input(store, capsys):
    assert main([]) == 0
    assert "search_products" in capsys.readouterr().out
    assert main(["nope"]) == 2
    assert main(["get_product", "wrong_argument=1"]) == 2
    assert main(["get_product", "no-equals-sign"]) == 2
