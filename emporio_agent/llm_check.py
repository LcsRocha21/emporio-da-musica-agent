"""Check that the Gemini connection works end to end.

    python -m emporio_agent.llm_check                 # asks one real question that needs a tool
    python -m emporio_agent.llm_check --list-models   # model ids your API key can use
"""

import argparse
import json
import sys

from emporio_agent.agent import Agent
from emporio_agent.llm.base import LLMError
from emporio_agent.llm.gemini import GeminiLLM

QUESTION = "Vocês abrem no sábado? Até que horas?"


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

    parser = argparse.ArgumentParser(prog="python -m emporio_agent.llm_check")
    parser.add_argument("--list-models", action="store_true", help="list the models usable with generateContent")
    args = parser.parse_args(argv)

    try:
        llm = GeminiLLM()
        if args.list_models:
            print("Models available for your API key (set one in .env as GEMINI_MODEL):\n")
            for model in llm.client.models.list():
                actions = getattr(model, "supported_actions", None) or []
                if not actions or "generateContent" in actions:
                    print("  " + model.name.removeprefix("models/"))
            return 0

        print(f"Model: {llm.model}\nQuestion: {QUESTION}\n")
        reply = Agent(llm).reply(QUESTION)
    except LLMError as error:
        print(f"[FAILED] {error}")
        return 1

    for call in reply.tool_calls:
        print(f"Tool called: {call.name}({json.dumps(call.args, ensure_ascii=False)})")
    print(f"\nDJ: {reply.text}\n")
    if reply.tool_calls:
        print("[OK] The model answered and used tools.")
        return 0
    print("[WARNING] The model answered without calling any tool; check the model and the prompt.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
