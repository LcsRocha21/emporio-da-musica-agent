"""Turn the tool functions into provider-neutral JSON-schema declarations.

The single source of truth for each tool is its Python signature and its docstring:
the function description is the docstring, parameter descriptions come from the
``Args:`` block, and types come from the annotations. Nothing is written twice.
"""

import inspect
import re
import types
import typing
from collections.abc import Callable

# Parameters whose values are a closed set. The docstrings say the same, but a schema
# enum makes the model much less likely to invent a value.
PARAMETER_ENUMS = {
    ("search_products", "sort_by"): ["price_asc", "price_desc"],
    ("search_products", "string_material"): ["nylon", "steel"],
    ("check_return_eligibility", "reason"): ["regret", "defect", "preference"],
    ("handoff_to_human", "reason"): ["complaint", "cancellation", "return_or_exchange", "order_issue", "other"],
}

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _schema_for(annotation) -> dict:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        options = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return _schema_for(options[0])  # Optional[X] -> X (the parameter is simply not required)
    if origin is list:
        (item,) = typing.get_args(annotation) or (str,)
        return {"type": "array", "items": _schema_for(item)}
    if annotation in _JSON_TYPES:
        return {"type": _JSON_TYPES[annotation]}
    raise TypeError(f"Unsupported tool parameter type: {annotation!r}")


def _split_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """Return (description without the Args block, {param: description})."""
    lines = inspect.cleandoc(doc).splitlines()
    description_lines: list[str] = []
    params: dict[str, str] = {}
    in_args, current = False, None
    for line in lines:
        if line.strip() == "Args:":
            in_args = True
            continue
        if in_args:
            entry = re.match(r"^ {4}(\w+): (.*)$", line)
            if entry:
                current = entry.group(1)
                params[current] = entry.group(2).strip()
                continue
            if line.startswith("        ") and current:
                params[current] += " " + line.strip()
                continue
            if line.strip() == "":
                continue
            in_args, current = False, None  # a new section such as "Returns:"
        description_lines.append(line)
    description = re.sub(r"\n{3,}", "\n\n", "\n".join(description_lines)).strip()
    return description, params


def build_declaration(fn: Callable) -> dict:
    """{"name", "description", "parameters": <JSON schema object>} for one tool."""
    description, param_docs = _split_docstring(fn.__doc__ or "")
    hints = typing.get_type_hints(fn)
    properties, required = {}, []
    for name, parameter in inspect.signature(fn).parameters.items():
        schema = _schema_for(hints[name])
        if name in param_docs:
            schema["description"] = param_docs[name]
        if (fn.__name__, name) in PARAMETER_ENUMS:
            schema["enum"] = PARAMETER_ENUMS[(fn.__name__, name)]
        properties[name] = schema
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "name": fn.__name__,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


def build_declarations(functions: list[Callable]) -> list[dict]:
    return [build_declaration(fn) for fn in functions]
