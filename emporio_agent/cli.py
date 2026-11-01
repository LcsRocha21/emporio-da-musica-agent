"""Command-line chat with DJ.

    python -m emporio_agent                    # chat
    python -m emporio_agent --name "Lucas"     # greet the customer by name
    python -m emporio_agent --debug            # also show the tools the agent calls
    python -m emporio_agent --session ana      # save to chat_history/ana.json (resumes it if it exists)
    python -m emporio_agent --resume           # continue the most recent saved conversation
    python -m emporio_agent --export chat.md   # also write a Markdown transcript after every answer
"""

import argparse
import json
import sys
from collections.abc import Callable

from pathlib import Path

from emporio_agent import history
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
    input_fn: Callable[[str], str] | None = None,
    print_fn: Callable[..., None] | None = None,
    debug: bool = False,
    after_turn: Callable[[Agent], None] | None = None,
) -> None:
    """Chat loop. ``after_turn`` runs after every answer that was delivered (used to save the session)."""
    input_fn = input_fn or input
    print_fn = print_fn or print
    print_fn("Empório da Música — atendimento (digite 'sair' para encerrar)\n")
    if agent.messages:
        _print_recap(agent, print_fn)
    else:
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
        if after_turn:
            after_turn(agent)


def _print_recap(agent: Agent, print_fn: Callable[..., None]) -> None:
    spoken = [m for m in agent.messages if m.role in ("user", "assistant") and m.text and not m.tool_calls]
    print_fn("(conversa retomada — últimas mensagens)\n")
    for message in spoken[-2:]:
        speaker = "Você" if message.role == "user" else "DJ"
        print_fn(f"{speaker}: {message.text}\n")


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
    parser.add_argument("--session", metavar="NAME", help="save the conversation as chat_history/NAME.json, resuming it if it exists")
    parser.add_argument("--resume", action="store_true", help="continue the most recent saved conversation")
    parser.add_argument("--export", metavar="FILE", help="write a Markdown transcript of the conversation to FILE after every answer")
    args = parser.parse_args(argv)
    if args.session and args.resume:
        parser.error("use either --session or --resume, not both")

    try:
        path = _choose_session_path(args)
        saved = history.load_session(path) if path.exists() else None
    except history.HistoryError as error:
        print(f"[erro] {error}")
        return 2
    customer_name = args.name or (saved.customer_name if saved else None)

    from emporio_agent.llm.gemini import GeminiLLM

    try:
        llm = GeminiLLM()
    except LLMError as error:
        print(f"[erro] {error}")
        return 1

    agent = Agent(llm, customer_name=customer_name)
    if saved:
        agent.messages = saved.messages
    export_path = Path(args.export) if args.export else None

    def save(current: Agent) -> None:
        try:
            history.save_session(path, current.messages, customer_name)
            if export_path:
                export_path.write_text(history.export_markdown(current.messages, customer_name), encoding="utf-8")
        except (history.HistoryError, OSError) as error:
            print(f"[aviso] a conversa não foi salva: {error}")

    run_chat(agent, customer_name=customer_name, debug=args.debug, after_turn=save)
    if path.exists():
        print(f"Conversa salva em {path.name}. Para retomar: python -m emporio_agent --session {path.stem}")
    return 0


def _choose_session_path(args) -> Path:
    if args.resume:
        latest = history.latest_session()
        if latest:
            return latest
        print("[aviso] nenhuma conversa salva ainda; começando uma nova.")
    if args.session:
        return history.session_path(args.session)
    return history.session_path(history.new_session_id())
