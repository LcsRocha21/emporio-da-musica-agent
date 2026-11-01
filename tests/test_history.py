import json
import os

import pytest

from emporio_agent import history
from emporio_agent.history import HistoryError
from emporio_agent.llm.base import Message, ToolCall, ToolResult

SAMPLE = [
    Message("user", text="Quanto custa o Takamine GD20?"),
    Message("assistant", tool_calls=[ToolCall("get_product", {"product": "Takamine GD20"}, "c1")], provider_state=object()),
    Message("tool", tool_results=[ToolResult("get_product", {"status": "found", "name": "Takamine GD20"}, "c1")]),
    Message("assistant", text="Sai por R$ 2.199,00.", provider_state=object()),
]


def test_round_trip_keeps_text_and_tool_records_but_never_provider_state(tmp_path):
    path = tmp_path / "s.json"
    history.save_session(path, SAMPLE, customer_name="Ana Carolina")
    assert "provider_state" not in path.read_text(encoding="utf-8")

    session = history.load_session(path)
    assert session.customer_name == "Ana Carolina"
    assert [m.role for m in session.messages] == ["user", "assistant", "tool", "assistant"]
    assert session.messages[1].tool_calls[0] == ToolCall("get_product", {"product": "Takamine GD20"}, "c1")
    assert session.messages[2].tool_results[0].result["status"] == "found"
    assert session.messages[3].text == "Sai por R$ 2.199,00."
    assert all(m.provider_state is None for m in session.messages)


def test_file_is_utf8_readable_json_and_no_temp_file_is_left(tmp_path):
    path = tmp_path / "s.json"
    history.save_session(path, SAMPLE)
    assert "R$ 2.199,00" in path.read_text(encoding="utf-8")  # accents and symbols are not escaped
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]


def test_saving_creates_missing_folders(tmp_path):
    path = tmp_path / "deep" / "er" / "s.json"
    history.save_session(path, SAMPLE)
    assert path.is_file()


def test_unreadable_or_corrupt_files_raise_a_clear_error(tmp_path):
    with pytest.raises(HistoryError, match="Could not read"):
        history.load_session(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(HistoryError, match="not a valid saved conversation"):
        history.load_session(broken)
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"version": 1}), encoding="utf-8")
    with pytest.raises(HistoryError, match="not a valid saved conversation"):
        history.load_session(wrong)


def test_session_names_cannot_escape_the_history_folder(tmp_path):
    assert history.session_path("ana-1_b", tmp_path) == tmp_path / "ana-1_b.json"
    for bad in ("../evil", "a/b", "a b", "", "x" * 65, "ação"):
        with pytest.raises(HistoryError):
            history.session_path(bad, tmp_path)


def test_latest_session_is_the_most_recently_saved_json_and_ignores_other_files(tmp_path):
    assert history.latest_session(tmp_path) is None
    assert history.latest_session(tmp_path / "does-not-exist") is None
    for name, mtime in (("old.json", 1_000), ("new.json", 3_000), ("mid.json", 2_000)):
        history.save_session(tmp_path / name, SAMPLE)
        os.utime(tmp_path / name, (mtime, mtime))
    (tmp_path / "handoffs.jsonl").write_text("{}", encoding="utf-8")
    os.utime(tmp_path / "handoffs.jsonl", (9_000, 9_000))
    assert history.latest_session(tmp_path).name == "new.json"


def test_new_session_ids_are_valid_session_names(tmp_path):
    assert history.session_path(history.new_session_id(), tmp_path)


def test_markdown_transcript_shows_customer_tools_and_answers_in_order():
    text = history.export_markdown(SAMPLE, customer_name="Ana Carolina", title="Exemplo 1")
    assert text.startswith("# Exemplo 1")
    assert "**DJ:** Fala, Ana!" in text  # the greeting the customer saw
    assert text.index("**Você:** Quanto custa") < text.index("get_product") < text.index("**DJ:** Sai por")
    assert '`get_product({"product": "Takamine GD20"})`' in text
    assert '"status": "found"' in text
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_markdown_transcript_truncates_long_tool_results_and_handles_no_tools():
    long_result = Message("tool", tool_results=[ToolResult("search_products", {"items": ["x" * 1000]}, "a")])
    call = Message("assistant", tool_calls=[ToolCall("search_products", {}, "a")])
    text = history.export_markdown([Message("user", text="oi"), call, long_result, Message("assistant", text="ok")])
    assert "…" in text and len(text) < 1200

    plain = history.export_markdown([Message("user", text="oi"), Message("assistant", text="Fala!")])
    assert "Ferramentas" not in plain
