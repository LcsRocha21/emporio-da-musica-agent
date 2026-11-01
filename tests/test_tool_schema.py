import json

import pytest

from emporio_agent.tools import TOOL_FUNCTIONS
from emporio_agent.tools.schema import build_declaration, build_declarations


@pytest.fixture(scope="module")
def declarations():
    return {d["name"]: d for d in build_declarations(TOOL_FUNCTIONS)}


def test_every_tool_has_a_declaration_that_is_valid_json(declarations):
    assert set(declarations) == {fn.__name__ for fn in TOOL_FUNCTIONS}
    json.dumps(declarations)
    for spec in declarations.values():
        assert spec["description"] and "Args:" not in spec["description"]
        assert spec["parameters"]["type"] == "object"


def test_required_parameters_are_the_ones_without_defaults(declarations):
    required = {name: spec["parameters"]["required"] for name, spec in declarations.items()}
    assert required["get_product"] == ["product"]
    assert required["calculate_payment_options"] == ["product_ids"]
    assert required["estimate_shipping"] == ["city", "product_ids"]
    assert required["check_return_eligibility"] == ["order_id", "reason"]
    assert required["search_policies"] == ["query"]
    assert required["handoff_to_human"] == ["summary"]
    assert required["search_products"] == []
    assert required["get_order_status"] == []  # order_id is optional: without it the orders are listed
    assert required["get_current_datetime"] == []


def test_types_come_from_the_annotations(declarations):
    search = declarations["search_products"]["parameters"]["properties"]
    assert search["max_price"]["type"] == "number"
    assert search["limit"]["type"] == "integer"
    assert search["electroacoustic"]["type"] == "boolean"
    assert search["only_available"]["type"] == "boolean"
    assert declarations["calculate_payment_options"]["parameters"]["properties"]["product_ids"] == {
        "type": "array",
        "items": {"type": "integer"},
        "description": declarations["calculate_payment_options"]["parameters"]["properties"]["product_ids"]["description"],
    }
    assert declarations["get_order_status"]["parameters"]["properties"]["order_id"]["type"] == "integer"


def test_closed_sets_are_enums(declarations):
    props = declarations["check_return_eligibility"]["parameters"]["properties"]
    assert props["reason"]["enum"] == ["regret", "defect", "preference"]
    assert declarations["search_products"]["parameters"]["properties"]["sort_by"]["enum"] == ["price_asc", "price_desc"]
    assert "other" in declarations["handoff_to_human"]["parameters"]["properties"]["reason"]["enum"]


def test_parameter_descriptions_are_taken_from_the_docstring(declarations):
    props = declarations["search_products"]["parameters"]["properties"]
    assert "Portuguese" in props["query"]["description"]
    assert "promotional price" in props["min_price"]["description"]  # continuation lines are joined
    assert "same rule as min_price" in props["max_price"]["description"]
    assert "ZIP" not in declarations["estimate_shipping"]["parameters"]["properties"]["city"]["description"]
    assert all("description" in p for spec in declarations.values() for p in spec["parameters"]["properties"].values())


def test_tool_without_parameters_has_empty_properties(declarations):
    assert declarations["get_current_datetime"]["parameters"]["properties"] == {}


def test_unsupported_annotation_is_rejected():
    def bad(value: dict) -> dict:
        """Not supported."""

    with pytest.raises(TypeError, match="Unsupported"):
        build_declaration(bad)
