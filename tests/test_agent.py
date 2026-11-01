import pytest

from emporio_agent.agent import EMPTY_REPLY, TOO_MANY_STEPS_REPLY, Agent
from emporio_agent.llm.base import LLMError, LLMResponse, ToolCall
from emporio_agent.tools import TOOL_FUNCTIONS
from tests.helpers import ScriptedLLM, call, say


def roles(agent):
    return [m.role for m in agent.messages]


def test_plain_answer_without_tools(store):
    llm = ScriptedLLM(say("Oi! Como posso ajudar?"))
    agent = Agent(llm)
    reply = agent.reply("oi")
    assert reply.text == "Oi! Como posso ajudar?" and reply.tool_calls == []
    assert roles(agent) == ["user", "assistant"]
    sent = llm.calls[0]
    assert "You are DJ" in sent["system_prompt"]
    assert len(sent["tools"]) == len(TOOL_FUNCTIONS) == 9


def test_tool_call_runs_the_real_tool_and_feeds_the_result_back(store):
    llm = ScriptedLLM(call("get_product", call_id="c1", product="Takamine GD20"), say("O Takamine GD20 sai por R$ 2.199,00."))
    agent = Agent(llm)
    reply = agent.reply("Quanto custa o Takamine GD20?")

    assert reply.text.startswith("O Takamine GD20")
    assert [t.name for t in reply.tool_calls] == ["get_product"]
    assert reply.tool_calls[0].args == {"product": "Takamine GD20"}
    assert roles(agent) == ["user", "assistant", "tool", "assistant"]

    second_call_messages = llm.calls[1]["messages"]
    tool_message = second_call_messages[-1]
    assert tool_message.role == "tool"
    assert tool_message.tool_results[0].id == "c1"
    assert tool_message.tool_results[0].result["product"]["price_display"] == "R$ 2.199,00"


def test_several_tool_calls_in_one_turn_keep_their_order_and_ids(store):
    response = LLMResponse(
        text=None,
        tool_calls=[
            ToolCall("get_product", {"product": "Takamine GD20"}, "a"),
            ToolCall("calculate_payment_options", {"product_ids": [95]}, "b"),
        ],
    )
    llm = ScriptedLLM(response, say("Pronto!"))
    agent = Agent(llm)
    reply = agent.reply("preço e parcelamento do GD20")
    assert [t.name for t in reply.tool_calls] == ["get_product", "calculate_payment_options"]
    results = llm.calls[1]["messages"][-1].tool_results
    assert [(r.name, r.id) for r in results] == [("get_product", "a"), ("calculate_payment_options", "b")]
    assert results[1].result["max_installments"] == 12


def test_numbers_sent_as_floats_by_the_model_are_accepted(store):
    llm = ScriptedLLM(
        call("get_order_status", order_id=8.0, customer_email="anacarol.ferreira@coldmail.com"),
        call("calculate_payment_options", product_ids=[95.0]),
        say("ok"),
    )
    agent = Agent(llm)
    agent.reply("status do pedido 8")
    assert llm.calls[1]["messages"][-1].tool_results[0].result["order"]["tracking_code"] == "BRJL5544332BR"
    assert llm.calls[2]["messages"][-1].tool_results[0].result["status"] == "ok"


def test_unknown_tool_and_bad_arguments_become_errors_the_model_can_read(store):
    llm = ScriptedLLM(call("fly_to_the_moon"), call("get_product", wrong_argument=1), say("Desculpa, vou tentar de novo."))
    agent = Agent(llm)
    reply = agent.reply("algo")
    assert reply.tool_calls[0].result["status"] == "error" and "Unknown tool" in reply.tool_calls[0].result["message"]
    assert "Invalid arguments" in reply.tool_calls[1].result["message"]
    assert reply.text == "Desculpa, vou tentar de novo."


def test_a_crashing_tool_does_not_crash_the_conversation_or_leak_details():
    def boom() -> dict:
        """A tool that always fails, only used in this test to check error handling."""
        raise RuntimeError("secret database path /srv/internal.db")

    llm = ScriptedLLM(call("boom"), say("Tive um problema técnico, posso passar para a equipe."))
    agent = Agent(llm, tool_functions=[boom])
    reply = agent.reply("faz algo")
    result = reply.tool_calls[0].result
    assert result["status"] == "error"
    assert "secret" not in str(result) and "do not guess" in result["message"].lower()
    assert "equipe" in reply.text


def test_tool_results_are_json_safe(store):
    llm = ScriptedLLM(call("search_products", query="ukulele", limit=2), say("ok"))
    agent = Agent(llm)
    agent.reply("tem ukulele?")
    result = llm.calls[1]["messages"][-1].tool_results[0].result
    assert isinstance(result, dict) and result["total_matches"] > 0


def test_endless_tool_loop_is_cut_and_answered_with_a_fallback(store):
    llm = ScriptedLLM(*[call("get_current_datetime") for _ in range(10)])
    agent = Agent(llm, max_tool_rounds=3)
    reply = agent.reply("hora?")
    assert reply.text == TOO_MANY_STEPS_REPLY
    assert len(llm.calls) == 3 and len(reply.tool_calls) == 3
    assert roles(agent)[-1] == "assistant" and agent.messages[-1].text == TOO_MANY_STEPS_REPLY


def test_empty_model_answer_gets_a_polite_fallback_kept_in_history():
    llm = ScriptedLLM(LLMResponse(text=None), say("agora sim"))
    agent = Agent(llm)
    assert agent.reply("oi").text == EMPTY_REPLY
    assert agent.messages[-1].text == EMPTY_REPLY
    assert agent.reply("oi de novo").text == "agora sim"


def test_provider_errors_roll_the_turn_back_so_the_customer_can_retry(store):
    llm = ScriptedLLM(say("primeira"), call("get_current_datetime"), LLMError("quota"), say("segunda tentativa"))
    agent = Agent(llm)
    agent.reply("um")
    before = list(agent.messages)
    with pytest.raises(LLMError):
        agent.reply("dois")
    assert agent.messages == before  # user message, tool call and tool result were all removed
    assert agent.reply("dois de novo").text == "segunda tentativa"


def test_the_whole_conversation_is_sent_on_every_call(store):
    llm = ScriptedLLM(say("a"), say("b"), say("c"))
    agent = Agent(llm)
    for text in ("1", "2", "3"):
        agent.reply(text)
    assert [len(c["messages"]) for c in llm.calls] == [1, 3, 5]


def test_customer_name_reaches_the_system_prompt():
    llm = ScriptedLLM(say("oi"))
    Agent(llm, customer_name="Ana Carolina").reply("oi")
    assert "The customer's name is Ana Carolina" in llm.calls[0]["system_prompt"]
