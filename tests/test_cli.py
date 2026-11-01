from emporio_agent import cli, llm_check
from emporio_agent.agent import Agent
from emporio_agent.llm.base import LLMError
from tests.helpers import ScriptedLLM, call, say


def run(agent, inputs, name=None, debug=False):
    lines, feed = [], iter(inputs)

    def fake_input(prompt):
        try:
            return next(feed)
        except StopIteration:
            raise EOFError

    cli.run_chat(
        agent,
        customer_name=name,
        input_fn=fake_input,
        print_fn=lambda *a: lines.append(" ".join(map(str, a))),
        debug=debug,
    )
    return "\n".join(lines)


def test_chat_greets_answers_and_says_goodbye():
    output = run(Agent(ScriptedLLM(say("Temos sim!"))), ["", "tem violão?", "sair"], name="Lucas Mendes")
    assert "DJ: Fala, Lucas! Eu sou o DJ, assistente virtual" in output
    assert "DJ: Temos sim!" in output
    assert output.rstrip().endswith("DJ: Valeu pela visita! Qualquer coisa, é só chamar 🎶")


def test_chat_ends_cleanly_on_end_of_input():
    assert "DJ: Oi" in run(Agent(ScriptedLLM(say("Oi"))), ["oi"])


def test_debug_mode_shows_tool_calls(store):
    agent = Agent(ScriptedLLM(call("get_product", product="Takamine GD20"), say("R$ 2.199,00")))
    quiet = run(agent, ["preço do gd20?"])
    assert "[tool]" not in quiet

    agent = Agent(ScriptedLLM(call("get_product", product="Takamine GD20"), say("R$ 2.199,00")))
    output = run(agent, ["preço do gd20?"], debug=True)
    assert '[tool] get_product({"product": "Takamine GD20"})' in output
    assert "R$ 2.199,00" in output


def test_provider_errors_are_shown_and_the_chat_continues():
    agent = Agent(ScriptedLLM(LLMError("Gemini API error 429: quota"), say("Agora foi!")))
    output = run(agent, ["oi", "oi de novo"])
    assert "[erro] Gemini API error 429: quota" in output
    assert "DJ: Agora foi!" in output


def test_main_reports_a_missing_key_instead_of_crashing(monkeypatch, capsys):
    import emporio_agent.llm.gemini as gemini

    def no_key():
        raise LLMError("GEMINI_API_KEY is not set.")

    monkeypatch.setattr(gemini, "GeminiLLM", no_key)
    assert cli.main([]) == 1
    assert "GEMINI_API_KEY is not set" in capsys.readouterr().out


def test_llm_check_succeeds_when_the_model_uses_a_tool(monkeypatch, capsys):
    llm = ScriptedLLM(call("get_current_datetime"), say("Sábado abrimos das 9h às 13h."))
    monkeypatch.setattr(llm_check, "GeminiLLM", lambda: llm)
    assert llm_check.main([]) == 0
    output = capsys.readouterr().out
    assert "Tool called: get_current_datetime" in output and "[OK]" in output


def test_llm_check_warns_when_no_tool_was_used(monkeypatch, capsys):
    monkeypatch.setattr(llm_check, "GeminiLLM", lambda: ScriptedLLM(say("Não sei.")))
    assert llm_check.main([]) == 2
    assert "[WARNING]" in capsys.readouterr().out


def test_llm_check_reports_provider_failures(monkeypatch, capsys):
    monkeypatch.setattr(llm_check, "GeminiLLM", lambda: ScriptedLLM(LLMError("Gemini API error 403: denied")))
    assert llm_check.main([]) == 1
    assert "[FAILED] Gemini API error 403" in capsys.readouterr().out
