"""Provider-neutral types for talking to an LLM.

The agent only knows these types. Everything specific to one provider (Gemini today)
lives in its own adapter module, so switching provider means writing one small class.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


class LLMError(RuntimeError):
    """The model provider failed in a way the user should hear about (bad key, quota...)."""


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass
class ToolResult:
    name: str
    result: Any
    id: str | None = None


@dataclass
class Message:
    """One turn of the conversation.

    ``provider_state`` carries the provider's own object for an assistant turn (for Gemini
    it holds the "thought signatures" that must be sent back unchanged while a tool-calling
    turn is in progress). It is opaque to the agent and never saved to disk.
    """

    role: Literal["user", "assistant", "tool"]
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    provider_state: Any = None


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider_state: Any = None


class LLMClient(Protocol):
    def generate(self, system_prompt: str, messages: list[Message], tools: list[dict]) -> LLMResponse:
        """Run one model call. ``tools`` are declarations from ``tools.schema``."""
        ...
