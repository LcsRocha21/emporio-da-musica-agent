"""Test doubles for the LLM layer."""

from emporio_agent.llm.base import LLMResponse, ToolCall


class ScriptedLLM:
    """Returns pre-written responses in order and records what it was asked."""

    model = "scripted-model"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, system_prompt, messages, tools):
        self.calls.append({"system_prompt": system_prompt, "messages": list(messages), "tools": tools})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def say(text):
    """A model answer with plain text."""
    return LLMResponse(text=text)


def call(name, call_id=None, **args):
    """A model answer that asks for one tool call."""
    return LLMResponse(text=None, tool_calls=[ToolCall(name=name, args=args, id=call_id)])
