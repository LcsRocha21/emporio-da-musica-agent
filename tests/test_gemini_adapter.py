"""Tests for the Gemini adapter.

Most tests use a stand-in for the google-genai ``types`` module, so the adapter's own
logic (request building, history replay, response parsing, retries) is verified without
the SDK or the network. The last tests use the real SDK types when it is installed.
"""

import pytest

from emporio_agent.llm.base import LLMError, Message, ToolCall, ToolResult
from emporio_agent.llm.gemini import DEFAULT_MODEL, GeminiLLM
from emporio_agent.tools import TOOL_FUNCTIONS
from emporio_agent.tools.schema import build_declarations


class Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return f"Obj({self.__dict__})"


class FakeTypes:
    class Part(Obj):
        @classmethod
        def from_text(cls, text):
            return cls(text=text)

    Content = FunctionResponse = FunctionDeclaration = Tool = GenerateContentConfig = Obj
    AutomaticFunctionCallingConfig = Obj


class ApiError(Exception):
    def __init__(self, code, message="boom"):
        super().__init__(message)
        self.code = code
        self.message = message


class FakeClient:
    """Plays back responses (or raises exceptions) and records every request."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.requests.append({"model": model, "contents": contents, "config": config})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def response(*parts):
    return Obj(candidates=[Obj(content=Obj(role="model", parts=list(parts)))])


def text_part(text, thought=False):
    return Obj(text=text, thought=thought, function_call=None)


def call_part(name, args, call_id="id1"):
    return Obj(text=None, thought=False, function_call=Obj(name=name, args=args, id=call_id))


def make_llm(*outcomes, **kwargs):
    client = FakeClient(*outcomes)
    sleeps = []
    llm = GeminiLLM(client=client, types_module=FakeTypes, sleep=sleeps.append, **kwargs)
    return llm, client, sleeps


DECLARATIONS = build_declarations(TOOL_FUNCTIONS)


# ------------------------------------------------------------------ request building


def test_request_carries_prompt_tools_and_disables_automatic_function_calling():
    llm, client, _ = make_llm(response(text_part("oi")))
    llm.generate("SYSTEM PROMPT", [Message("user", text="oi")], DECLARATIONS)

    request = client.requests[0]
    config = request["config"]
    assert request["model"] == DEFAULT_MODEL
    assert config.system_instruction == "SYSTEM PROMPT"
    assert config.automatic_function_calling.disable is True
    declared = config.tools[0].function_declarations
    assert [d.name for d in declared] == [fn.__name__ for fn in TOOL_FUNCTIONS]
    by_name = {d.name: d for d in declared}
    assert by_name["get_product"].parameters_json_schema["required"] == ["product"]
    assert not hasattr(by_name["get_current_datetime"], "parameters_json_schema")  # no params -> no schema


def test_model_comes_from_argument_then_environment_then_default(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "env-model")
    assert make_llm(model="arg-model")[0].model == "arg-model"
    assert make_llm()[0].model == "env-model"
    monkeypatch.delenv("GEMINI_MODEL")
    assert make_llm()[0].model == DEFAULT_MODEL


def test_missing_api_key_gives_a_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiLLM(types_module=FakeTypes)


# ------------------------------------------------------------------ history replay


def test_live_tool_turn_replays_the_models_own_content_then_function_responses():
    model_content = Obj(role="model", parts=[call_part("get_product", {"product": "x"}, "c1")])
    history = [
        Message("user", text="preço do x?"),
        Message("assistant", tool_calls=[ToolCall("get_product", {"product": "x"}, "c1")], provider_state=model_content),
        Message("tool", tool_results=[ToolResult("get_product", {"status": "found"}, "c1")]),
    ]
    llm, client, _ = make_llm(response(text_part("R$ 10")))
    llm.generate("p", history, DECLARATIONS)

    contents = client.requests[0]["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[1] is model_content  # untouched, so thought signatures survive
    function_response = contents[2].parts[0].function_response
    assert (function_response.id, function_response.name) == ("c1", "get_product")
    assert function_response.response == {"result": {"status": "found"}}


def test_restored_history_replays_text_only_and_skips_old_tool_turns():
    history = [
        Message("user", text="oi"),
        Message("assistant", text="Fala!"),  # restored: no provider_state
        Message("user", text="preço?"),
        Message("assistant", tool_calls=[ToolCall("get_product", {"product": "x"}, "c1")]),  # restored tool call
        Message("tool", tool_results=[ToolResult("get_product", {"status": "found"}, "c1")]),
        Message("assistant", text="R$ 10"),
        Message("user", text="valeu"),
    ]
    llm, client, _ = make_llm(response(text_part("de nada")))
    llm.generate("p", history, DECLARATIONS)
    contents = client.requests[0]["contents"]
    assert [c.role for c in contents] == ["user", "model", "user", "model", "user"]
    assert [c.parts[0].text for c in contents] == ["oi", "Fala!", "preço?", "R$ 10", "valeu"]


# ------------------------------------------------------------------ response parsing


def test_text_answer_is_parsed_and_the_content_is_kept_as_provider_state():
    llm, _, _ = make_llm(response(text_part("Olá, "), text_part("tudo bem?")))
    result = llm.generate("p", [Message("user", text="oi")], DECLARATIONS)
    assert result.text == "Olá, tudo bem?" and result.tool_calls == []
    assert result.provider_state is not None


def test_thought_summaries_are_not_shown_to_the_customer():
    llm, _, _ = make_llm(response(text_part("pensando alto...", thought=True), text_part("Resposta final")))
    assert llm.generate("p", [Message("user", text="oi")], DECLARATIONS).text == "Resposta final"


def test_tool_calls_are_parsed_with_their_ids():
    llm, _, _ = make_llm(response(call_part("get_product", {"product": "Takamine"}, "x9"), call_part("search_policies", None, "x10")))
    result = llm.generate("p", [Message("user", text="oi")], DECLARATIONS)
    assert result.text is None
    assert [(c.name, c.args, c.id) for c in result.tool_calls] == [
        ("get_product", {"product": "Takamine"}, "x9"),
        ("search_policies", {}, "x10"),
    ]


def test_blocked_or_empty_responses_become_an_empty_result():
    llm, _, _ = make_llm(Obj(candidates=[]), Obj(candidates=[Obj(content=None)]), Obj(candidates=[Obj(content=Obj(parts=None))]))
    for _ in range(3):
        result = llm.generate("p", [Message("user", text="oi")], DECLARATIONS)
        assert result.text is None and result.tool_calls == [] and result.provider_state is None


# ------------------------------------------------------------------ errors and retries


def test_transient_errors_are_retried_with_backoff():
    llm, client, sleeps = make_llm(ApiError(503), ApiError(429), response(text_part("ok")))
    assert llm.generate("p", [Message("user", text="oi")], DECLARATIONS).text == "ok"
    assert len(client.requests) == 3 and sleeps == [2.0, 4.0]


def test_persistent_rate_limit_becomes_a_friendly_error():
    llm, client, _ = make_llm(*[ApiError(429, "quota exceeded")] * 4, max_retries=3)
    with pytest.raises(LLMError, match="quota"):
        llm.generate("p", [Message("user", text="oi")], DECLARATIONS)
    assert len(client.requests) == 4


def test_non_retryable_errors_fail_immediately_with_a_hint():
    llm, client, _ = make_llm(ApiError(404, "model not found"), model="gemini-typo")
    with pytest.raises(LLMError) as info:
        llm.generate("p", [Message("user", text="oi")], DECLARATIONS)
    assert len(client.requests) == 1
    assert "gemini-typo" in str(info.value) and "--list-models" in str(info.value)

    llm, _, _ = make_llm(ApiError(400, "API key not valid"))
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        llm.generate("p", [Message("user", text="oi")], DECLARATIONS)


# ------------------------------------------------------------------ real SDK (skipped when not installed)


@pytest.fixture
def real_types():
    genai_types = pytest.importorskip("google.genai.types")
    return genai_types


def test_real_sdk_accepts_our_declarations_config_and_history(real_types):
    t = real_types
    reply = t.GenerateContentResponse(
        candidates=[t.Candidate(content=t.Content(role="model", parts=[t.Part.from_text(text="Olá!")]))]
    )
    client = FakeClient(reply)
    llm = GeminiLLM(client=client, model="any-model", sleep=lambda s: None)
    model_turn = t.Content(role="model", parts=[t.Part(function_call=t.FunctionCall(name="get_product", args={"product": "x"}, id="c1"))])
    history = [
        Message("user", text="preço do x?"),
        Message("assistant", tool_calls=[ToolCall("get_product", {"product": "x"}, "c1")], provider_state=model_turn),
        Message("tool", tool_results=[ToolResult("get_product", {"status": "found", "price": 10.5}, "c1")]),
    ]
    result = llm.generate("system", history, DECLARATIONS)
    assert result.text == "Olá!"
    config = client.requests[0]["config"]
    assert isinstance(config, t.GenerateContentConfig) and len(config.tools[0].function_declarations) == 9
    assert [c.role for c in client.requests[0]["contents"]] == ["user", "model", "user"]
