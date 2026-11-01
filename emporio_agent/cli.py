"""Command-line chat with DJ.

    python -m emporio_agent                    # chat
    python -m emporio_agent --name "Lucas"     # greet the customer by name
    python -m emporio_agent --debug            # also show the tools the agent calls
"""

import argparse
import json
import sys
from collections.abc import Callable

from emporio_agent.agent import Agent
from emporio_agent.llm.base import LLMError
from emporio_agent.prompt import greeting

EXIT_WORDS = {"sair", "exit", "quit"}
GOODBYE = "Valeu pela visita! Qualquer coisa, é só chamar 🎶"


def _short(value, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def run_chat(
    agent: Agent,
    customer_name: str | None = None,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[..., None] = print,
    debug: bool = False,
) -> None:
    print_fn("Empório da Música — atendimento (digite 'sair' para encerrar)\n")
    print_fn(f"DJ: {greeting(customer_name)}\n")
    while True:
        try:
            text = input_fn("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print_fn()
            break
        if not text:
            continue
        if text.lower() in EXIT_WORDS:
            print_fn(f"\nDJ: {GOODBYE}")
            break
        try:
            reply = agent.reply(text)
        except LLMError as error:
            print_fn(f"\n[erro] {error}\n")
            continue
        print_fn()
        if debug:
            for call in reply.tool_calls:
                print_fn(f"  [tool] {call.name}({_short(call.args)})\n         -> {_short(call.result)}")
        print_fn(f"DJ: {reply.text}\n")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(prog="python -m emporio_agent", description="Chat with DJ, the Empório da Música assistant.")
    parser.add_argument("--name", help="customer's name, used in the greeting")
    parser.add_argument("--debug", action="store_true", help="show the tools called on each answer")
    args = parser.parse_args(argv)

    from emporio_agent.llm.gemini import GeminiLLM

    try:
        llm = GeminiLLM()
    except LLMError as error:
        print(f"[erro] {error}")
        return 1
    run_chat(Agent(llm, customer_name=args.name), customer_name=args.name, debug=args.debug)
    return 0
