"""Google Gemini adapter (google-genai SDK) using manual function calling.

Function calling is driven by our own loop (``agent.py``), not by the SDK's automatic
loop, so every tool call can be logged, tested and limited.

Conversation replay rules:

* While a turn is in progress, the model's own ``Content`` object (with its thought
  signatures) is sent back unchanged, as Gemini requires for tool calling.
* Turns restored from disk have no such object. Their plain text turns are replayed;
  old tool-call turns are skipped, since the assistant's text already carries the outcome.
"""

import os
import time
from typing import Any

from emporio_agent.llm.base import LLMError, LLMResponse, Message, ToolCall

# Free-tier "Flash-Lite" class model: best daily request allowance for development.
# Model ids change over time; override with GEMINI_MODEL and list what your key can use with
#   python -m emporio_agent.llm_check --list-models
DEFAULT_MODEL = "gemini-3.5-flash-lite"

RETRYABLE_CODES = {429, 500, 502, 503, 504}


class GeminiLLM:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: Any = None,
        types_module: Any = None,
        max_retries: int = 3,
        sleep=time.sleep,
    ):
        if types_module is None:
            try:
                from google.genai import types as types_module
            except ImportError as exc:
                raise LLMError("The google-genai package is not installed. Run: pip install -r requirements.txt") from exc
        self.types = types_module
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        self.max_retries = max_retries
        self._sleep = sleep

        if client is None:
            key = api_key or os.getenv("GEMINI_API_KEY")
            if not key:
                raise LLMError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
            from google import genai

            client = genai.Client(api_key=key)
        self.client = client

    # ------------------------------------------------------------------ requests

    def generate(self, system_prompt: str, messages: list[Message], tools: list[dict]) -> LLMResponse:
        t = self.types
        config = t.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[t.Tool(function_declarations=[self._declaration(d) for d in tools])] if tools else None,
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._call(self._to_contents(messages), config)
        return self._parse(response)

    def _declaration(self, spec: dict):
        kwargs = {"name": spec["name"], "description": spec["description"]}
        if spec["parameters"].get("properties"):
            kwargs["parameters_json_schema"] = spec["parameters"]
        return self.types.FunctionDeclaration(**kwargs)

    def _to_contents(self, messages: list[Message]) -> list:
        t = self.types
        contents: list = []
        replay_tool_results = False  # only after an assistant turn we are able to replay faithfully
        for message in messages:
            if message.role == "user":
                contents.append(t.Content(role="user", parts=[t.Part.from_text(text=message.text or "")]))
                replay_tool_results = False
            elif message.role == "assistant":
                if message.provider_state is not None:
                    contents.append(message.provider_state)
                    replay_tool_results = bool(message.tool_calls)
                else:
                    replay_tool_results = False
                    if message.text and not message.tool_calls:
                        contents.append(t.Content(role="model", parts=[t.Part.from_text(text=message.text)]))
            elif message.role == "tool" and replay_tool_results:
                parts = [
                    t.Part(function_response=t.FunctionResponse(id=r.id, name=r.name, response={"result": r.result}))
                    for r in message.tool_results
                ]
                contents.append(t.Content(role="user", parts=parts))
                replay_tool_results = False
        return contents

    def _call(self, contents: list, config):
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            try:
                return self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except Exception as exc:  # noqa: BLE001 - SDK raises several error types
                code = getattr(exc, "code", None)
                if code in RETRYABLE_CODES and attempt < self.max_retries:
                    self._sleep(delay)
                    delay *= 2
                    continue
                raise LLMError(self._explain(exc, code)) from exc
        raise AssertionError("unreachable")

    def _explain(self, exc: Exception, code: int | None) -> str:
        detail = getattr(exc, "message", None) or str(exc)
        hints = {
            400: "Check that GEMINI_API_KEY is valid.",
            401: "Check that GEMINI_API_KEY is valid.",
            403: "The key was rejected or has no access to this model.",
            404: f"Model '{self.model}' was not found. List the models your key can use with: "
            "python -m emporio_agent.llm_check --list-models, then set GEMINI_MODEL in .env.",
            429: "Rate limit or daily quota reached (free tier). Wait a little or pick another model.",
        }
        hint = hints.get(code, "")
        return f"Gemini API error{f' {code}' if code else ''}: {detail} {hint}".strip()

    # ------------------------------------------------------------------ responses

    @staticmethod
    def _parse(response) -> LLMResponse:
        candidates = getattr(response, "candidates", None) or []
        content = candidates[0].content if candidates else None
        parts = (content.parts if content is not None else None) or []
        text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))
        calls = [
            ToolCall(name=p.function_call.name, args=dict(p.function_call.args or {}), id=p.function_call.id)
            for p in parts
            if getattr(p, "function_call", None)
        ]
        return LLMResponse(text=text or None, tool_calls=calls, provider_state=content if parts else None)
