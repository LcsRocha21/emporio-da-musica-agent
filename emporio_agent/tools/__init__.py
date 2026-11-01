"""Tools the agent can call. Each one is a plain Python function with typed arguments
and a docstring: the docstring is what the LLM reads to decide when to use it.

``search_policies`` (store manual retrieval) is added in a later step.
"""

from emporio_agent.tools.catalog import get_product, search_products
from emporio_agent.tools.checkout import calculate_payment_options, estimate_shipping
from emporio_agent.tools.general import get_current_datetime, handoff_to_human
from emporio_agent.tools.orders import check_return_eligibility, get_order_status

TOOL_FUNCTIONS = [
    search_products,
    get_product,
    calculate_payment_options,
    estimate_shipping,
    get_order_status,
    check_return_eligibility,
    get_current_datetime,
    handoff_to_human,
]

TOOLS = {fn.__name__: fn for fn in TOOL_FUNCTIONS}

__all__ = ["TOOLS", "TOOL_FUNCTIONS"]
