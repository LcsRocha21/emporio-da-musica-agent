import pytest

from emporio_agent import cli, llm_check
from emporio_agent.agent import Agent
from emporio_agent.llm.base import LLMError, Message, ToolCall, ToolResult
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


# ------------------------------------------------------------------ saving and resuming


def test_after_turn_runs_once_per_delivered_answer_and_not_after_errors():
    saved = []
    agent = Agent(ScriptedLLM(say("um"), LLMError("quota"), say("dois")))
    lines, feed = [], iter(["a", "b", "c"])
    cli.run_chat(agent, input_fn=lambda p: next(feed, "sair"), print_fn=lambda *a: lines.append(" ".join(map(str, a))),
                 after_turn=lambda current: saved.append(len(current.messages)))
    assert saved == [2, 4]  # the failed turn was rolled back and never saved


def test_resumed_conversation_shows_a_recap_instead_of_the_greeting():
    agent = Agent(ScriptedLLM(say("Claro!")))
    agent.messages = [
        Message("user", text="oi"),
        Message("assistant", text="Fala!"),
        Message("user", text="quero um violão"),
        Message("assistant", tool_calls=[ToolCall("search_products", {}, "x")]),
        Message("tool", tool_results=[ToolResult("search_products", {}, "x")]),
        Message("assistant", text="Tenho vários!"),
    ]
    output = run(agent, ["pode ser"])
    assert "conversa retomada" in output
    assert "Você: quero um violão" in output and "DJ: Tenho vários!" in output
    assert "Eu sou o DJ" not in output and "Fala!" not in output.split("conversa retomada")[1].split("Você: quero")[0]
    assert "DJ: Claro!" in output


@pytest.fixture
def chat_env(monkeypatch, tmp_path):
    """Run main() against a temporary history folder with a scripted model and typed input."""
    from emporio_agent import config
    import emporio_agent.llm.gemini as gemini

    monkeypatch.setattr(config, "CHAT_HISTORY_DIR", tmp_path)
    models = []

    def start(*answers, typed):
        llm = ScriptedLLM(*answers)
        models.append(llm)
        monkeypatch.setattr(gemini, "GeminiLLM", lambda: llm)
        feed = iter(typed)
        monkeypatch.setattr("builtins.input", lambda prompt="": next(feed))
        return llm

    start.dir = tmp_path
    return start


def test_main_saves_the_session_and_a_second_run_resumes_it(chat_env, capsys):
    chat_env(say("Temos sim!"), typed=["tem violão?", "sair"])
    assert cli.main(["--session", "ana", "--name", "Ana Carolina"]) == 0
    assert "Conversa salva em ana.json" in capsys.readouterr().out
    assert (chat_env.dir / "ana.json").is_file()

    llm = chat_env(say("Claro, qual?"), typed=["quero o mais barato", "sair"])
    assert cli.main(["--session", "ana"]) == 0
    output = capsys.readouterr().out
    assert "conversa retomada" in output and "DJ: Temos sim!" in output
    sent = llm.calls[0]
    assert [m.text for m in sent["messages"]] == ["tem violão?", "Temos sim!", "quero o mais barato"]
    assert "The customer's name is Ana Carolina" in sent["system_prompt"]  # name restored from the file


def test_main_resume_picks_the_latest_session_or_starts_fresh(chat_env, capsys):
    chat_env(say("a"), typed=["oi", "sair"])
    assert cli.main(["--resume"]) == 0
    assert "nenhuma conversa salva" in capsys.readouterr().out

    chat_env(say("b"), typed=["de novo", "sair"])
    assert cli.main(["--resume"]) == 0
    assert "conversa retomada" in capsys.readouterr().out


def test_main_exports_a_markdown_transcript(chat_env, tmp_path):
    chat_env(call("get_current_datetime"), say("Hoje é domingo."), typed=["que dia é hoje?", "sair"])
    target = tmp_path / "out" / "example.md"
    target.parent.mkdir()
    assert cli.main(["--session", "ex", "--export", str(target)]) == 0
    text = target.read_text(encoding="utf-8")
    assert "**Você:** que dia é hoje?" in text and "get_current_datetime" in text and "**DJ:** Hoje é domingo." in text


def test_main_rejects_bad_session_names_and_corrupt_files(chat_env, capsys):
    assert cli.main(["--session", "../evil"]) == 2
    assert "Session names may only contain" in capsys.readouterr().out

    (chat_env.dir / "bad.json").write_text("{oops", encoding="utf-8")
    assert cli.main(["--session", "bad"]) == 2
    assert "not a valid saved conversation" in capsys.readouterr().out


def test_session_and_resume_cannot_be_combined(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--session", "a", "--resume"])
    assert "not both" in capsys.readouterr().err
