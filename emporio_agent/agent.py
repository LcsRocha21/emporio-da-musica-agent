"""The agent loop: model -> tool calls -> tool results -> model, until it answers."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from emporio_agent.llm.base import LLMClient, LLMError, Message, ToolCall, ToolResult
from emporio_agent.prompt import build_system_prompt
from emporio_agent.tools import TOOL_FUNCTIONS
from emporio_agent.tools.schema import build_declarations

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6

TOO_MANY_STEPS_REPLY = (
    "Opa, me enrolei aqui e não consegui concluir isso agora 😅 Pode me perguntar de novo? "
    "Se preferir, posso passar seu caso para a equipe."
)
EMPTY_REPLY = "Desculpa, não consegui responder agora. Pode tentar de novo, por favor?"


@dataclass
class ToolTrace:
    name: str
    args: dict[str, Any]
    result: Any


@dataclass
class AgentReply:
    text: str
    tool_calls: list[ToolTrace] = field(default_factory=list)


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        tool_functions: list[Callable] | None = None,
        customer_name: str | None = None,
        system_prompt: str | None = None,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
    ):
        functions = tool_functions if tool_functions is not None else TOOL_FUNCTIONS
        self.llm = llm
        self.tools = {fn.__name__: fn for fn in functions}
        self.declarations = build_declarations(functions)
        self.system_prompt = system_prompt or build_system_prompt(customer_name)
        self.max_tool_rounds = max_tool_rounds
        self.messages: list[Message] = []

    def reply(self, user_text: str) -> AgentReply:
        """Answer one customer message. On a provider error the turn is rolled back and the error re-raised."""
        turn_start = len(self.messages)
        self.messages.append(Message(role="user", text=user_text))
        trace: list[ToolTrace] = []
        try:
            for _ in range(self.max_tool_rounds):
                response = self.llm.generate(self.system_prompt, self.messages, self.declarations)
                self.messages.append(
                    Message(
                        role="assistant",
                        text=response.text,
                        tool_calls=response.tool_calls,
                        provider_state=response.provider_state,
                    )
                )
                if not response.tool_calls:
                    return AgentReply(text=response.text or self._fallback(EMPTY_REPLY), tool_calls=trace)

                results = []
                for call in response.tool_calls:
                    result = self._run_tool(call)
                    trace.append(ToolTrace(call.name, call.args, result))
                    results.append(ToolResult(name=call.name, result=result, id=call.id))
                self.messages.append(Message(role="tool", tool_results=results))
        except LLMError:
            del self.messages[turn_start:]
            raise
        return AgentReply(text=self._fallback(TOO_MANY_STEPS_REPLY), tool_calls=trace)

    def _fallback(self, text: str) -> str:
        """Record a canned answer in the history so turns keep alternating, and return it."""
        if not self.messages or self.messages[-1].role != "assistant" or self.messages[-1].tool_calls:
            self.messages.append(Message(role="assistant", text=text))
        elif not self.messages[-1].text:
            self.messages[-1].text = text
        return text

    def _run_tool(self, call: ToolCall) -> Any:
        function = self.tools.get(call.name)
        if function is None:
            return {"status": "error", "message": f"Unknown tool '{call.name}'. Available: {', '.join(self.tools)}."}
        try:
            result = function(**call.args)
        except TypeError as exc:
            logger.warning("Bad arguments for %s: %s", call.name, exc)
            return {"status": "error", "message": f"Invalid arguments for {call.name}: {exc}"}
        except Exception:  # noqa: BLE001 - a tool bug must not crash the conversation
            logger.exception("Tool %s failed", call.name)
            return {
                "status": "error",
                "message": f"The tool {call.name} failed unexpectedly. Do not guess the answer: apologize and "
                "offer to pass the question to the team.",
            }
        return json.loads(json.dumps(result, ensure_ascii=False, default=str))
