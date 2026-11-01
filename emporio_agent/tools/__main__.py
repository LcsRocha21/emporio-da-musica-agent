"""Playground to try the agent's tools from the terminal, without any LLM or API key.

    python -m emporio_agent.tools                       # list the tools
    python -m emporio_agent.tools get_product product="Takamine GD20"
    python -m emporio_agent.tools search_products category=violões max_price=1000
    python -m emporio_agent.tools calculate_payment_options product_ids=95,96

Arguments are ``name=value`` pairs. Values are read as JSON when possible (numbers,
true/false, lists) and as plain text otherwise; ``1,2,3`` becomes a list.
"""

import json
import sys

from emporio_agent.tools import TOOLS


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    if "," in raw:
        return [parse_value(part.strip()) for part in raw.split(",") if part.strip()]
    return raw


def list_tools() -> None:
    print("Available tools:\n")
    for name, fn in TOOLS.items():
        first_line = (fn.__doc__ or "").strip().splitlines()[0]
        print(f"  {name}\n      {first_line}")
    print('\nUsage: python -m emporio_agent.tools <tool> name=value ...   (e.g. product="Takamine GD20")')


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    try:
        from dotenv import load_dotenv

        load_dotenv()  # lets EMPORIO_NOW be set in .env
    except ImportError:
        pass

    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help", "list"):
        list_tools()
        return 0
    name, *pairs = args
    if name not in TOOLS:
        print(f"Unknown tool '{name}'. Run without arguments to list the tools.")
        return 2

    kwargs = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator:
            print(f"Invalid argument '{pair}': use name=value.")
            return 2
        kwargs[key] = parse_value(value)
    try:
        result = TOOLS[name](**kwargs)
    except TypeError as error:
        print(f"Invalid arguments for {name}: {error}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
